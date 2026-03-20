# -*- coding: utf-8 -*-
"""Service layer for recommendation refresh, scoring, and query workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
from sqlalchemy import desc, select

from data_provider import DataFetcherManager
from data_provider.realtime_types import UnifiedRealtimeQuote
from src.analyzer import GeminiAnalyzer
from src.config import Config, get_config, setup_env
from src.core.config_manager import ConfigManager
from src.recommendation.constants import (
    CN_STOP_LOSS_RATIO,
    CN_TAKE_PROFIT_RATIO,
    DEFAULT_SCORING_WEIGHTS,
    POSITION_MIN_SCORE,
)
from src.recommendation.sector_cache import SectorCacheService
from src.recommendation.engine import ScoringEngine, StockScoringData
from src.recommendation.market_utils import detect_market_region, get_market_indices
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
    SectorInfo,
    StockRecommendation,
)
from src.repositories.recommendation_repo import RecommendationRepository
from src.services.sector_scanner_service import (
    SectorScannerService,
    _OVERSEAS_SECTOR_FALLBACK,
)
from src.services.watchlist_service import WatchlistService
from src.stock_analyzer import TrendAnalysisResult, StockTrendAnalyzer
from src.storage import AnalysisHistory, DatabaseManager, NewsIntel

logger = logging.getLogger(__name__)


@dataclass
class _RecommendationAnalysisBridgeResult:
    code: str
    name: str
    sentiment_score: int
    operation_advice: str
    trend_prediction: str
    analysis_summary: str
    raw_payload: dict[str, Any]
    sniper_points: dict[str, float | None]
    data_sources: str = "recommendation_refresh"
    raw_response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw_payload)

    def get_sniper_points(self) -> dict[str, float | None]:
        return dict(self.sniper_points)


class RecommendationService:
    """Coordinate data collection, scoring, persistence, and watchlist access."""

    SECTOR_CACHE_TYPE = "industry"
    AUTO_REFRESH_SECTOR_LIMIT = 3
    SCORING_WEIGHT_CONFIG_MAPPING: tuple[tuple[str, str, str, int], ...] = (
        ("technical", "RECOMMEND_WEIGHT_TECHNICAL", "recommend_weight_technical", 30),
        (
            "fundamental",
            "RECOMMEND_WEIGHT_FUNDAMENTAL",
            "recommend_weight_fundamental",
            25,
        ),
        ("sentiment", "RECOMMEND_WEIGHT_SENTIMENT", "recommend_weight_sentiment", 20),
        ("macro", "RECOMMEND_WEIGHT_MACRO", "recommend_weight_macro", 15),
        ("risk", "RECOMMEND_WEIGHT_RISK", "recommend_weight_risk", 10),
    )

    def __init__(self, config: Any = None) -> None:
        self.config = config or get_config()
        self._recommendation_config_map = self._read_recommendation_config_map()

        def _config_int(
            *keys: str,
            env_keys: tuple[str, ...] = (),
            default: int,
        ) -> int:
            value = self._recommendation_config_value(keys, env_keys, default)
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
            return int(default)

        self.max_workers = max(1, int(getattr(self.config, "max_workers", 4)))
        self.refresh_skip_seconds = max(
            0,
            _config_int(
                "recommend_refresh_skip_seconds",
                env_keys=("RECOMMEND_REFRESH_SKIP_SECONDS",),
                default=300,
            ),
        )

        self.fetcher_manager = DataFetcherManager()
        self.trend_analyzer = StockTrendAnalyzer()
        self.gemini_analyzer = GeminiAnalyzer()

        self.recommendation_repo = RecommendationRepository()
        self.watchlist_service = WatchlistService()
        self.sector_scanner_service = SectorScannerService(
            self.fetcher_manager,
            top_n=max(
                1,
                _config_int(
                    "recommend_top_n_per_sector",
                    "recommend_sector_top_n",
                    "recommendation_top_n_per_sector",
                    env_keys=(
                        "RECOMMEND_TOP_N_PER_SECTOR",
                        "RECOMMEND_SECTOR_TOP_N",
                    ),
                    default=5,
                ),
            ),
            max_universe=max(
                1,
                _config_int(
                    "recommend_max_universe",
                    "recommendation_max_universe",
                    env_keys=("RECOMMEND_MAX_UNIVERSE",),
                    default=200,
                ),
            ),
        )
        self.recommend_top_n_per_sector = max(
            1,
            _config_int(
                "recommend_top_n_per_sector",
                "recommend_sector_top_n",
                "recommendation_top_n_per_sector",
                env_keys=(
                    "RECOMMEND_TOP_N_PER_SECTOR",
                    "RECOMMEND_SECTOR_TOP_N",
                ),
                default=5,
            ),
        )
        self.recommend_score_threshold_ai = max(
            0,
            min(
                100,
                _config_int(
                    "recommend_score_threshold_ai",
                    env_keys=("RECOMMEND_SCORE_THRESHOLD_AI",),
                    default=60,
                ),
            ),
        )
        self.db_manager = DatabaseManager.get_instance()
        self.sector_cache_ttl_hours = max(
            1,
            int(getattr(self.config, "recommendation_sector_cache_ttl_hours", 24)),
        )
        self.sector_cache_service = SectorCacheService(
            self.recommendation_repo,
            sector_type=self.SECTOR_CACHE_TYPE,
            ttl_hours=self.sector_cache_ttl_hours,
        )

        weights = self._load_scoring_weights()
        self.scoring_engine = ScoringEngine(
            weights=weights,
            ai_refiner=self.gemini_analyzer,
            config=self.config,
            batch_max_workers=self.max_workers,
        )

    def refresh_all(
        self,
        force: bool = False,
        market: str | MarketRegion | None = None,
        sector: str | None = None,
    ) -> list[StockRecommendation]:
        """Refresh recommendations for sector scan results and watchlist stocks."""
        target_region = self._parse_market_region(market)
        if sector is None:
            target_sectors, used_ranking_fallback = (
                self._resolve_auto_refresh_sectors_with_source(target_region)
            )
            if not target_sectors:
                return []

            if target_region == MarketRegion.CN and used_ranking_fallback:
                persisted_items = self._fallback_cn_generic_persisted_recommendations(
                    limit=self._cn_auto_generic_fallback_limit()
                )
                if not persisted_items:
                    return []
                logger.info(
                    "Skipping CN sector constituent loop for ranking-derived fallback sectors; returning bounded persisted CN recommendations directly | count=%d",
                    len(persisted_items),
                )
                return persisted_items

            merged_sector_by_code: dict[str, str] = {}
            merged_codes: list[str] = []
            for target_sector in target_sectors:
                try:
                    sector_codes, sector_by_code = self._collect_sector_universe(
                        target_region=target_region,
                        target_sector=target_sector,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to refresh recommendations for market=%s sector=%s: %s",
                        target_region.value,
                        target_sector,
                        exc,
                    )
                    continue

                for code in sector_codes:
                    if code in merged_sector_by_code:
                        continue
                    merged_codes.append(code)
                    merged_sector_by_code[code] = (
                        sector_by_code.get(code) or target_sector
                    )

            if not merged_codes and target_region == MarketRegion.CN:
                persisted_items = self._fallback_cn_generic_persisted_recommendations(
                    limit=self._cn_auto_generic_fallback_limit()
                )
                if persisted_items:
                    logger.info(
                        "Returning bounded persisted CN recommendations directly after live universe fallback exhaustion | count=%d",
                        len(persisted_items),
                    )
                    return persisted_items

            if not merged_codes:
                return []

            return self.refresh_stocks(
                merged_codes,
                sector_by_code=merged_sector_by_code,
                force=force,
            )

        target_sector = str(sector).strip()
        if not target_sector:
            raise ValueError("sector is required for recommendation refresh")

        return self._refresh_all_for_sector(
            force=force,
            target_region=target_region,
            target_sector=target_sector,
        )

    def _resolve_auto_refresh_sectors(self, region: MarketRegion) -> list[str]:
        sectors, _ = self._resolve_auto_refresh_sectors_with_source(region)
        return sectors

    def _resolve_auto_refresh_sectors_with_source(
        self,
        region: MarketRegion,
    ) -> tuple[list[str], bool]:
        if region == MarketRegion.CN:
            fallback = self._fallback_cn_hot_sector_names(
                limit=self.AUTO_REFRESH_SECTOR_LIMIT
            )
            if fallback:
                logger.info(
                    "Using CN ranking-derived sector fallback candidates: %s",
                    ", ".join(fallback),
                )
            return fallback, True

        fallback = _OVERSEAS_SECTOR_FALLBACK.get(region.value, {})
        sectors: list[str] = []
        seen_universes: set[tuple[str, ...]] = set()

        for raw_sector, raw_codes in fallback.items():
            normalized_sector = str(raw_sector or "").strip()
            if not normalized_sector:
                continue

            normalized_codes = {
                str(code or "").strip().upper()
                for code in (raw_codes or [])
                if str(code or "").strip()
            }
            if normalized_codes:
                universe_key = tuple(sorted(normalized_codes))
            else:
                universe_key = (f"__sector__:{normalized_sector.casefold()}",)

            if universe_key in seen_universes:
                continue

            seen_universes.add(universe_key)
            sectors.append(normalized_sector)

        return sectors, False

    def _fallback_cn_hot_sector_names(self, limit: int) -> list[str]:
        target_limit = max(1, int(limit))
        fetcher = getattr(self.sector_scanner_service, "data_fetcher", None)
        if fetcher is None:
            return []

        try:
            top_sectors, _ = fetcher.get_sector_rankings(target_limit)
        except Exception as exc:
            logger.warning("Failed to fetch CN sector rankings: %s", exc)
            return []

        sectors: list[str] = []
        for item in top_sectors or []:
            if isinstance(item, dict):
                sector_name = item.get("name") or item.get("sector")
            else:
                sector_name = item
            normalized = str(sector_name or "").strip()
            if not normalized or normalized in sectors:
                continue
            sectors.append(normalized)
            if len(sectors) >= target_limit:
                break
        return sectors

    def _refresh_all_for_sector(
        self,
        force: bool,
        target_region: MarketRegion,
        target_sector: str,
    ) -> list[StockRecommendation]:
        combined_codes, sector_by_code = self._collect_sector_universe(
            target_region=target_region,
            target_sector=target_sector,
        )
        return self.refresh_stocks(
            combined_codes,
            sector_by_code=sector_by_code,
            force=force,
            market=target_region,
            sector=target_sector,
        )

    def _collect_sector_universe(
        self,
        target_region: MarketRegion,
        target_sector: str,
    ) -> tuple[list[str], dict[str, str]]:
        sector_by_code: dict[str, str] = {}
        normalized_sector_codes: list[str] = []

        sector_codes = self.sector_scanner_service.get_sector_stocks(
            target_sector,
            limit=self.sector_scanner_service.max_universe,
            market=target_region.value,
        )
        if not sector_codes and target_region == MarketRegion.CN:
            sector_codes = self._fallback_sector_codes_from_persisted_recommendations(
                target_region=target_region,
                target_sector=target_sector,
                limit=self.sector_scanner_service.max_universe,
            )
            if sector_codes:
                logger.info(
                    "Using persisted recommendation fallback codes for market=%s sector=%s | count=%d",
                    target_region.value,
                    target_sector,
                    len(sector_codes),
                )
        if not sector_codes and target_region != MarketRegion.CN:
            logger.info(
                "Sector scan returned no codes for market=%s, sector=%s",
                target_region.value,
                target_sector,
            )
        for raw_code in sector_codes:
            code = str(raw_code or "").strip()
            if not code:
                continue
            normalized_sector_codes.append(code)
            sector_by_code[code] = target_sector
            self.sector_cache_service.save_sector_info(
                code,
                SectorInfo(
                    sector_name=target_sector,
                    sector_type=self.SECTOR_CACHE_TYPE,
                    fetched_at=datetime.utcnow(),
                ),
            )

        watchlist_codes = [
            item.code
            for item in self.watchlist_service.get_watchlist(region=target_region)
        ]
        scoped_watchlist_codes = self._filter_codes_by_sector(
            watchlist_codes,
            target_sector,
            sector_by_code=sector_by_code,
        )
        normalized_watchlist_codes = [
            normalized
            for normalized in (
                str(raw_code or "").strip() for raw_code in scoped_watchlist_codes
            )
            if normalized
        ]
        for code in normalized_watchlist_codes:
            sector_by_code.setdefault(code, target_sector)
        combined_codes = list(
            dict.fromkeys([*normalized_sector_codes, *normalized_watchlist_codes])
        )
        return combined_codes, sector_by_code

    def _fallback_sector_codes_from_persisted_recommendations(
        self,
        target_region: MarketRegion,
        target_sector: str,
        limit: int,
    ) -> list[str]:
        try:
            rows = self.recommendation_repo.get_list(
                sector=target_sector,
                region=target_region,
                limit=max(1, int(limit)),
                offset=0,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load persisted recommendation fallback for market=%s sector=%s: %s",
                target_region.value,
                target_sector,
                exc,
            )
            return []

        fallback_codes: list[str] = []
        for item in rows:
            code = str(getattr(item, "code", "") or "").strip()
            if not code:
                continue
            if detect_market_region(code) != target_region:
                continue
            if code in fallback_codes:
                continue
            fallback_codes.append(code)
            if len(fallback_codes) >= max(1, int(limit)):
                break
        return fallback_codes

    def _fallback_cn_generic_persisted_recommendations(
        self,
        limit: int,
    ) -> list[StockRecommendation]:
        target_limit = max(1, int(limit))
        try:
            rows = self.recommendation_repo.get_list(
                region=MarketRegion.CN,
                limit=target_limit,
                offset=0,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load generic CN persisted recommendation fallback: %s",
                exc,
            )
            return []

        fallback_items: list[StockRecommendation] = []
        seen_codes: set[str] = set()
        for item in rows:
            code = str(getattr(item, "code", "") or "").strip()
            if not code:
                continue
            if detect_market_region(code) != MarketRegion.CN:
                continue
            if code in seen_codes:
                continue

            seen_codes.add(code)
            fallback_items.append(item)
            if len(fallback_items) >= target_limit:
                break

        return fallback_items

    def _cn_auto_generic_fallback_limit(self) -> int:
        # Emergency fail-open path after sector constituents and sector-scoped persisted
        # candidates are both unavailable. One sector-worth of candidates is enough to
        # keep refresh functional without pulling a broad CN pool.
        return max(
            1,
            min(
                int(self.sector_scanner_service.max_universe),
                int(self.recommend_top_n_per_sector),
            ),
        )

    def refresh_stocks(
        self,
        codes: list[str],
        sector_by_code: dict[str, str] | None = None,
        force: bool = False,
        market: str | MarketRegion | None = None,
        sector: str | None = None,
    ) -> list[StockRecommendation]:
        """Refresh recommendations for the provided stock code list."""
        normalized_codes = [str(code).strip() for code in codes if str(code).strip()]
        deduplicated_codes = list(dict.fromkeys(normalized_codes))
        if market is not None or sector is not None:
            if not str(market or "").strip():
                raise ValueError("market is required before selecting sector")
            if not str(sector or "").strip():
                raise ValueError("sector is required when market is provided")

            target_region = self._parse_market_region(market)
            target_sector = str(sector).strip()
            deduplicated_codes = [
                code
                for code in deduplicated_codes
                if detect_market_region(code) == target_region
            ]
            deduplicated_codes = self._filter_codes_by_sector(
                deduplicated_codes,
                target_sector,
                sector_by_code=sector_by_code,
            )
        if not deduplicated_codes:
            return []

        cached_by_code: dict[str, StockRecommendation] = {}
        codes_to_refresh = deduplicated_codes
        if not force:
            cached_by_code, codes_to_refresh = self._split_recent_cached_codes(
                deduplicated_codes
            )

        if not codes_to_refresh:
            return self._sort_recommendations(
                [
                    cached_by_code[code]
                    for code in deduplicated_codes
                    if code in cached_by_code
                ],
                deduplicated_codes,
            )

        normalized_sector_input = {
            str(code).strip(): str(value).strip()
            for code, value in (sector_by_code or {}).items()
            if str(code).strip() and str(value).strip()
        }

        resolved_sector_by_code = self._resolve_sector_mapping(
            codes_to_refresh,
            normalized_sector_input,
        )

        region_index_data = self._build_region_index_data(codes_to_refresh)
        payload_by_code: dict[str, dict[str, Any]] = {}

        worker_count = min(self.max_workers, len(codes_to_refresh))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(
                    self._build_stock_payload, code, region_index_data
                ): code
                for code in codes_to_refresh
            }
            for future in as_completed(future_map):
                code = future_map[future]
                try:
                    payload = future.result()
                    if payload is not None:
                        payload_by_code[code] = payload
                except Exception as exc:
                    logger.warning(
                        "Failed to assemble scoring payload for %s: %s", code, exc
                    )

        score_inputs: list[tuple[str, StockScoringData]] = []
        for code in codes_to_refresh:
            payload = payload_by_code.get(code)
            if payload is None:
                continue
            score_inputs.append((code, payload["scoring_data"]))

        if not score_inputs:
            return self._sort_recommendations(
                [
                    cached_by_code[code]
                    for code in deduplicated_codes
                    if code in cached_by_code
                ],
                deduplicated_codes,
            )

        score_filtered_inputs = self._select_score_first_inputs(
            score_inputs=score_inputs,
            payload_by_code=payload_by_code,
            score_first_enabled=(sector is not None) or bool(normalized_sector_input),
            market=market,
            sector=sector,
        )
        if not score_filtered_inputs:
            return self._sort_recommendations(
                [
                    cached_by_code[code]
                    for code in deduplicated_codes
                    if code in cached_by_code
                ],
                deduplicated_codes,
            )

        composite_scores = self.scoring_engine.score_batch(score_filtered_inputs)
        composite_score_by_code: dict[str, Any] = {}
        for composite_score in composite_scores:
            score_code = str(getattr(composite_score, "code", "") or "").strip()
            if not score_code:
                logger.warning(
                    "Skipped composite score without stock code during recommendation refresh"
                )
                continue
            if score_code not in payload_by_code:
                logger.warning(
                    "Skipped composite score for unknown stock code during recommendation refresh: %s",
                    score_code,
                )
                continue
            composite_score_by_code[score_code] = composite_score

        if not composite_score_by_code:
            return self._sort_recommendations(
                [
                    cached_by_code[code]
                    for code in deduplicated_codes
                    if code in cached_by_code
                ],
                deduplicated_codes,
            )

        normalized_sector_by_code = {
            str(code).strip(): value
            for code, value in resolved_sector_by_code.items()
            if str(code).strip() and str(value).strip()
        }

        new_recommendations: list[StockRecommendation] = []
        for code, _ in score_filtered_inputs:
            composite_score = composite_score_by_code.get(code)
            if composite_score is None:
                continue
            self._apply_ai_threshold_override(code, composite_score)
            payload = payload_by_code[code]
            sector_value = normalized_sector_by_code.get(code) or payload.get("sector")
            new_recommendations.append(
                StockRecommendation(
                    code=code,
                    name=payload["name"],
                    region=payload["region"],
                    sector=sector_value,
                    current_price=float(payload["current_price"]),
                    composite_score=composite_score,
                    ideal_buy_price=payload.get("ideal_buy_price"),
                    stop_loss=payload.get("stop_loss"),
                    take_profit=payload.get("take_profit"),
                    updated_at=datetime.utcnow(),
                )
            )

        sorted_new_recommendations = self._sort_recommendations(
            new_recommendations,
            [code for code, _ in score_filtered_inputs],
        )

        merged_by_code = dict(cached_by_code)
        for item in sorted_new_recommendations:
            merged_by_code[item.code] = item

        ordered_items = [
            merged_by_code[code]
            for code in deduplicated_codes
            if code in merged_by_code
        ]
        merged_recommendations = self._sort_recommendations(
            ordered_items, deduplicated_codes
        )
        self.recommendation_repo.save_batch(sorted_new_recommendations)
        try:
            self._bridge_recommendations_to_analysis_history(sorted_new_recommendations)
        except Exception as exc:
            logger.warning(
                "Failed to bridge recommendation refresh into analysis_history: %s",
                exc,
            )
        return merged_recommendations

    def _bridge_recommendations_to_analysis_history(
        self,
        recommendations: list[StockRecommendation],
    ) -> None:
        if not recommendations:
            return

        query_date = datetime.utcnow().strftime("%Y%m%d")
        records: list[AnalysisHistory] = []

        for recommendation in recommendations:
            bridge_result = self._build_analysis_bridge_result(recommendation)
            query_id = f"rec_{recommendation.code}_{query_date}"
            sniper_points = self.db_manager._extract_sniper_points(bridge_result)
            raw_result = self.db_manager._build_raw_result(bridge_result)

            records.append(
                AnalysisHistory(
                    query_id=query_id,
                    code=bridge_result.code,
                    name=bridge_result.name,
                    report_type="recommendation",
                    sentiment_score=bridge_result.sentiment_score,
                    operation_advice=bridge_result.operation_advice,
                    trend_prediction=bridge_result.trend_prediction,
                    analysis_summary=bridge_result.analysis_summary,
                    raw_result=self.db_manager._safe_json_dumps(raw_result),
                    news_content=None,
                    context_snapshot=None,
                    ideal_buy=sniper_points.get("ideal_buy"),
                    secondary_buy=sniper_points.get("secondary_buy"),
                    stop_loss=sniper_points.get("stop_loss"),
                    take_profit=sniper_points.get("take_profit"),
                    created_at=datetime.now(),
                )
            )

        if not records:
            return

        with self.db_manager.session_scope() as session:
            session.add_all(records)

    def _build_analysis_bridge_result(
        self,
        recommendation: StockRecommendation,
    ) -> _RecommendationAnalysisBridgeResult:
        sentiment_score = self._extract_sentiment_score(
            recommendation.composite_score,
        )
        operation_advice = self._map_operation_advice(recommendation.composite_score)
        trend_prediction = self._derive_trend_prediction(recommendation.composite_score)
        analysis_summary = str(recommendation.composite_score.ai_summary or "").strip()
        if not analysis_summary:
            analysis_summary = (
                f"{operation_advice}，综合评分 {recommendation.composite_score.total_score:.2f}，"
                f"趋势判断：{trend_prediction}。"
            )

        sniper_points = {
            "ideal_buy": recommendation.ideal_buy_price,
            "secondary_buy": None,
            "stop_loss": recommendation.stop_loss,
            "take_profit": recommendation.take_profit,
        }

        raw_payload = {
            "source": "recommendation_refresh",
            "code": recommendation.code,
            "name": recommendation.name,
            "region": recommendation.region.value,
            "sector": recommendation.sector,
            "current_price": recommendation.current_price,
            "sentiment_score": sentiment_score,
            "operation_advice": operation_advice,
            "trend_prediction": trend_prediction,
            "analysis_summary": analysis_summary,
            "recommendation": {
                "total_score": recommendation.composite_score.total_score,
                "priority": {
                    "name": recommendation.composite_score.priority.name,
                    "label": recommendation.composite_score.priority.value,
                },
                "dimension_scores": self._serialize_dimension_scores(
                    recommendation.composite_score.dimension_scores
                ),
                "ai_refined": bool(recommendation.composite_score.ai_refined),
                "ai_summary": recommendation.composite_score.ai_summary,
            },
            "sniper_points": sniper_points,
            "generated_at": (
                recommendation.updated_at.isoformat()
                if recommendation.updated_at
                else datetime.utcnow().isoformat()
            ),
        }

        return _RecommendationAnalysisBridgeResult(
            code=recommendation.code,
            name=recommendation.name,
            sentiment_score=sentiment_score,
            operation_advice=operation_advice,
            trend_prediction=trend_prediction,
            analysis_summary=analysis_summary,
            raw_payload=raw_payload,
            sniper_points=sniper_points,
            raw_response={
                "dashboard": {"battle_plan": {"sniper_points": sniper_points}}
            },
        )

    @staticmethod
    def _serialize_dimension_scores(
        dimension_scores: list[DimensionScore],
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for item in dimension_scores:
            payload.append(
                {
                    "dimension": item.dimension,
                    "score": item.score,
                    "weight": item.weight,
                    "details": item.details,
                }
            )
        return payload

    @staticmethod
    def _extract_sentiment_score(composite_score: CompositeScore) -> int:
        sentiment_dimension = next(
            (
                item
                for item in composite_score.dimension_scores
                if str(item.dimension).strip().casefold() == "sentiment"
            ),
            None,
        )
        if sentiment_dimension is None:
            return 50

        try:
            value = float(sentiment_dimension.score)
        except (TypeError, ValueError):
            return 50
        if pd.isna(value):
            return 50
        value = max(0.0, min(100.0, value))
        return int(round(value))

    @staticmethod
    def _map_operation_advice(composite_score: CompositeScore) -> str:
        mapping = {
            RecommendationPriority.BUY_NOW: "强烈买入",
            RecommendationPriority.POSITION: "建仓",
            RecommendationPriority.WAIT_PULLBACK: "观望",
            RecommendationPriority.NO_ENTRY: "回避",
        }
        return mapping.get(composite_score.priority, "观望")

    @staticmethod
    def _derive_trend_prediction(composite_score: CompositeScore) -> str:
        summary = str(composite_score.ai_summary or "").strip().casefold()
        if summary:
            bearish_markers = ("看空", "下跌", "bearish", "strong sell", "sell")
            bullish_markers = ("看多", "上涨", "bullish", "strong buy", "buy")
            if any(marker in summary for marker in bearish_markers):
                return "看空"
            if any(marker in summary for marker in bullish_markers):
                return "看多"

        fallback = {
            RecommendationPriority.BUY_NOW: "看多",
            RecommendationPriority.POSITION: "偏多",
            RecommendationPriority.WAIT_PULLBACK: "震荡",
            RecommendationPriority.NO_ENTRY: "观望",
        }
        return fallback.get(composite_score.priority, "观望")

    def _select_score_first_inputs(
        self,
        score_inputs: list[tuple[str, StockScoringData]],
        payload_by_code: dict[str, dict[str, Any]],
        score_first_enabled: bool,
        market: str | MarketRegion | None,
        sector: str | None,
    ) -> list[tuple[str, StockScoringData]]:
        total_count = len(score_inputs)
        if total_count == 0:
            return []

        market_value = str(getattr(market, "value", market) or "-")
        sector_value = str(sector or "-")

        if not score_first_enabled:
            logger.info(
                "Recommendation refresh staged counts | Total stocks: %d | After scoring filter: %d | Agent analyzed: %d | market=%s | sector=%s | score_first=false",
                total_count,
                total_count,
                total_count,
                market_value,
                sector_value,
            )
            return list(score_inputs)

        ranked_inputs: list[tuple[int, str, StockScoringData, float]] = []
        for index, (code, scoring_data) in enumerate(score_inputs):
            payload = payload_by_code.get(code) or {}
            trend_result = getattr(scoring_data, "trend_result", None)
            raw_signal_score = getattr(trend_result, "signal_score", None)
            if raw_signal_score is None:
                raw_signal_score = payload.get("signal_score")

            if raw_signal_score is None:
                signal_score = 0.0
            else:
                try:
                    signal_score = float(raw_signal_score)
                except (TypeError, ValueError):
                    signal_score = 0.0
            if pd.isna(signal_score):
                signal_score = 0.0

            clamped_score = max(0.0, min(100.0, signal_score))
            ranked_inputs.append((index, code, scoring_data, clamped_score))

        ranked_inputs.sort(key=lambda item: (-item[3], item[0]))
        threshold = float(self.recommend_score_threshold_ai)
        threshold_filtered = [item for item in ranked_inputs if item[3] >= threshold]

        used_threshold = True
        if threshold > 0 and not threshold_filtered and ranked_inputs:
            threshold_filtered = ranked_inputs
            used_threshold = False
            logger.info(
                "Score-first threshold produced empty candidates, fallback to top-N only | threshold=%.2f | market=%s | sector=%s",
                threshold,
                market_value,
                sector_value,
            )

        top_n = max(1, int(self.recommend_top_n_per_sector))
        filtered_inputs = [
            (code, scoring_data)
            for _, code, scoring_data, _ in threshold_filtered[:top_n]
        ]

        logger.info(
            "Recommendation refresh staged counts | Total stocks: %d | After scoring filter: %d | Agent analyzed: %d | top_n=%d | threshold=%.2f | threshold_applied=%s | market=%s | sector=%s",
            total_count,
            len(filtered_inputs),
            len(filtered_inputs),
            top_n,
            threshold,
            str(used_threshold).lower(),
            market_value,
            sector_value,
        )
        return filtered_inputs

    @staticmethod
    def _parse_market_region(value: str | MarketRegion | None) -> MarketRegion:
        if isinstance(value, MarketRegion):
            return value

        normalized = str(value or "").strip().upper()
        if not normalized:
            raise ValueError("market is required for recommendation refresh")

        if normalized in MarketRegion.__members__:
            return MarketRegion[normalized]

        try:
            return MarketRegion(normalized)
        except ValueError as exc:
            raise ValueError(f"Invalid market region: {value}") from exc

    def _filter_codes_by_sector(
        self,
        codes: list[str],
        sector: str,
        sector_by_code: dict[str, str] | None = None,
    ) -> list[str]:
        target = str(sector or "").strip().casefold()
        if not target:
            return list(codes)

        known_sectors = {
            str(code).strip(): str(name).strip()
            for code, name in (sector_by_code or {}).items()
            if str(code).strip() and str(name).strip()
        }
        matched: list[str] = []

        for code in codes:
            normalized_code = str(code).strip()
            if not normalized_code:
                continue

            candidate_sector = known_sectors.get(normalized_code)
            if candidate_sector is None:
                cached = self.recommendation_repo.get_latest(normalized_code)
                candidate_sector = cached.sector if cached is not None else None

            if str(candidate_sector or "").strip().casefold() == target:
                matched.append(normalized_code)

        return matched

    def _split_recent_cached_codes(
        self,
        codes: list[str],
    ) -> tuple[dict[str, StockRecommendation], list[str]]:
        if self.refresh_skip_seconds <= 0:
            return {}, list(codes)

        cutoff = datetime.utcnow() - timedelta(seconds=self.refresh_skip_seconds)
        cached_by_code: dict[str, StockRecommendation] = {}
        codes_to_refresh: list[str] = []

        for code in codes:
            cached = self.recommendation_repo.get_latest(code)
            if cached is None or cached.updated_at < cutoff:
                codes_to_refresh.append(code)
                continue
            cached_by_code[code] = cached

        return cached_by_code, codes_to_refresh

    @staticmethod
    def _sort_recommendations(
        recommendations: list[StockRecommendation],
        code_order: list[str],
    ) -> list[StockRecommendation]:
        order_map = {code: index for index, code in enumerate(code_order)}
        return sorted(
            recommendations,
            key=lambda item: (
                -float(item.composite_score.total_score),
                order_map.get(item.code, len(order_map)),
            ),
        )

    def _resolve_sector_mapping(
        self,
        codes: list[str],
        sector_by_code: dict[str, str] | None,
    ) -> dict[str, str]:
        normalized_input = {
            str(code).strip(): str(sector).strip()
            for code, sector in (sector_by_code or {}).items()
            if str(code).strip() and str(sector).strip()
        }

        resolved: dict[str, str] = {}

        for code in codes:
            normalized_code = str(code).strip()
            if not normalized_code:
                continue

            fallback_sector = normalized_input.get(normalized_code)
            if fallback_sector:
                self.sector_cache_service.save_sector_info(
                    normalized_code,
                    SectorInfo(
                        sector_name=fallback_sector,
                        sector_type=self.SECTOR_CACHE_TYPE,
                        fetched_at=datetime.utcnow(),
                    ),
                )

            sector_info = self.sector_cache_service.get_or_fetch_sector(normalized_code)
            if sector_info and sector_info.sector_name:
                resolved[normalized_code] = sector_info.sector_name

        return resolved

    def _apply_ai_threshold_override(
        self,
        code: str,
        composite_score: Any,
    ) -> None:
        threshold = float(self.recommend_score_threshold_ai)
        total_score = float(getattr(composite_score, "total_score", 0.0))

        if total_score < threshold:
            setattr(composite_score, "ai_refined", False)
            setattr(composite_score, "ai_summary", None)
            return

        if total_score >= POSITION_MIN_SCORE:
            return

        if self.gemini_analyzer is None:
            return

        if getattr(composite_score, "ai_refined", False):
            return

        try:
            self.scoring_engine._apply_ai_refinement(code, composite_score)
        except Exception:
            return

    def get_recommendations(
        self,
        priority: str | None = None,
        sector: str | None = None,
        region: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[StockRecommendation], int]:
        """Return filtered recommendation items and the total count."""
        items = self.recommendation_repo.get_list(
            priority=priority,
            sector=sector,
            region=region,
            limit=limit,
            offset=offset,
        )
        total = self.recommendation_repo.get_count(
            priority=priority,
            sector=sector,
            region=region,
        )
        return items, total

    def get_priority_summary(self) -> dict[str, int]:
        """Return recommendation counts grouped by priority."""
        return self.recommendation_repo.get_priority_counts()

    def get_scoring_weights(self) -> ScoringWeights:
        """Return the currently active scoring weights."""
        return self.scoring_engine._weights

    def update_scoring_weights(
        self, weights: ScoringWeights | dict[str, int]
    ) -> ScoringWeights:
        """Validate, persist, and activate a new scoring-weight configuration."""
        new_weights = (
            weights
            if isinstance(weights, ScoringWeights)
            else ScoringWeights(**weights)
        )
        self._persist_scoring_weights(new_weights)

        self.scoring_engine = ScoringEngine(
            weights=new_weights,
            ai_refiner=self.gemini_analyzer,
            config=self.config,
            batch_max_workers=self.max_workers,
        )
        return new_weights

    def _build_stock_payload(
        self,
        code: str,
        region_index_data: dict[MarketRegion, dict[str, dict[str, float]]],
    ) -> dict[str, Any] | None:
        region = detect_market_region(code)
        quote = self.fetcher_manager.get_realtime_quote(code)
        daily_df = self._get_daily_frame(code, days=90)

        quote_name = str(getattr(quote, "name", "") or "").strip()
        if quote_name:
            name = quote_name
        else:
            name = (
                self.fetcher_manager.get_stock_name(code, allow_realtime=False) or code
            )

        if quote is None:
            quote = self._build_fallback_quote(code, name, daily_df)

        trend_result = self._build_trend_result(code, daily_df)
        news_items = self._load_recent_news_items(code)
        enrichment = self._build_scoring_enrichment(daily_df)

        scoring_data = StockScoringData(
            region=region,
            trend_result=trend_result,
            quote=quote,
            news_items=news_items,
            index_data=region_index_data.get(region, {}),
            volume_trend=enrichment["volume_trend"],
            volume_ma5_ratio=enrichment["volume_ma5_ratio"],
            price_vs_ma10=enrichment["price_vs_ma10"],
            price_vs_ma20=enrichment["price_vs_ma20"],
            ma_alignment=enrichment["ma_alignment"],
            trading_days=enrichment["trading_days"],
            max_hold_days=enrichment["max_hold_days"],
        )

        ideal_buy_price, stop_loss, take_profit = self._price_levels(
            quote.price, trend_result.support_levels, region=region
        )
        return {
            "code": code,
            "name": name,
            "region": region,
            "sector": None,
            "current_price": float(quote.price or 0.0),
            "ideal_buy_price": ideal_buy_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "scoring_data": scoring_data,
        }

    def _build_scoring_enrichment(
        self,
        daily_df: pd.DataFrame | None,
    ) -> dict[str, Any]:
        enrichment: dict[str, Any] = {
            "volume_trend": "unknown",
            "volume_ma5_ratio": None,
            "price_vs_ma10": None,
            "price_vs_ma20": None,
            "ma_alignment": "unknown",
            "trading_days": None,
            "max_hold_days": 10,
        }
        if daily_df is None or daily_df.empty:
            return enrichment

        trading_days = int(len(daily_df.index))
        if trading_days > 0:
            enrichment["trading_days"] = trading_days
        if trading_days < 5:
            return enrichment

        close_values: list[float] = []
        volume_values: list[float] = []
        if "close" in daily_df.columns:
            close_values = self._numeric_values(daily_df["close"].tolist())
        if "volume" in daily_df.columns:
            volume_values = self._numeric_values(daily_df["volume"].tolist())

        if len(volume_values) >= 5:
            latest_volume = volume_values[-1]
            ma5_volume = self._window_mean(volume_values, 5)
            if ma5_volume > 0:
                volume_ma5_ratio = latest_volume / ma5_volume
                enrichment["volume_ma5_ratio"] = round(float(volume_ma5_ratio), 4)
                enrichment["volume_trend"] = self._classify_volume_trend(
                    volume_ma5_ratio
                )

        if len(close_values) >= 10:
            latest_price = close_values[-1]
            ma10 = self._window_mean(close_values, 10)
            if ma10 > 0:
                enrichment["price_vs_ma10"] = round((latest_price - ma10) / ma10, 4)

        if len(close_values) >= 20:
            latest_price = close_values[-1]
            ma20 = self._window_mean(close_values, 20)
            if ma20 > 0:
                enrichment["price_vs_ma20"] = round((latest_price - ma20) / ma20, 4)

            ma5 = self._window_mean(close_values, 5)
            ma10 = self._window_mean(close_values, 10)
            enrichment["ma_alignment"] = self._classify_ma_alignment(
                ma5=ma5,
                ma10=ma10,
                ma20=ma20,
            )

        return enrichment

    @staticmethod
    def _classify_volume_trend(volume_ma5_ratio: float) -> str:
        if volume_ma5_ratio < 0.8:
            return "shrinking"
        if volume_ma5_ratio > 1.2:
            return "expanding"
        return "moderate"

    @staticmethod
    def _classify_ma_alignment(
        ma5: float,
        ma10: float,
        ma20: float,
    ) -> str:
        if ma5 > ma10 > ma20:
            return "bullish"
        if ma5 < ma10 < ma20:
            return "bearish"
        return "mixed"

    def _build_region_index_data(
        self,
        codes: list[str],
    ) -> dict[MarketRegion, dict[str, dict[str, float]]]:
        regions = {detect_market_region(code) for code in codes}
        result: dict[MarketRegion, dict[str, dict[str, float]]] = {}
        for region in regions:
            result[region] = self._build_index_snapshots(region)
        return result

    def _build_index_snapshots(
        self, region: MarketRegion
    ) -> dict[str, dict[str, float]]:
        snapshots: dict[str, dict[str, float]] = {}
        for index_code in get_market_indices(region):
            snapshot: dict[str, float] = {}
            quote = self.fetcher_manager.get_realtime_quote(index_code)
            if quote and quote.price is not None:
                snapshot["price"] = float(quote.price)
                snapshot["change_pct"] = float(quote.change_pct or 0.0)

            df = self._get_daily_frame(index_code, days=90)
            if df is not None and not df.empty and "close" in df.columns:
                close_values = self._numeric_values(df["close"].tolist())
                if close_values:
                    snapshot["ma5"] = self._window_mean(close_values, 5)
                    snapshot["ma20"] = self._window_mean(close_values, 20)
                    snapshot["ma60"] = self._window_mean(close_values, 60)

            required = {"price", "change_pct", "ma5", "ma20", "ma60"}
            if required.issubset(set(snapshot.keys())):
                snapshots[index_code] = snapshot
        return snapshots

    def _get_daily_frame(self, code: str, days: int) -> pd.DataFrame | None:
        try:
            daily_data, _ = self.fetcher_manager.get_daily_data(code, days=days)
        except Exception:
            return None
        if daily_data is None or daily_data.empty:
            return None
        return daily_data

    def _build_fallback_quote(
        self,
        code: str,
        name: str,
        daily_df: pd.DataFrame | None,
    ) -> UnifiedRealtimeQuote:
        price = None
        if daily_df is not None and not daily_df.empty and "close" in daily_df.columns:
            close_values = self._numeric_values(daily_df["close"].tolist())
            if close_values:
                price = float(close_values[-1])

        return UnifiedRealtimeQuote(
            code=code,
            name=name,
            price=price,
            volume_ratio=1.0,
            turnover_rate=2.0,
            change_pct=0.0,
            pe_ratio=None,
            pb_ratio=None,
            total_mv=None,
        )

    def _build_trend_result(
        self,
        code: str,
        daily_df: pd.DataFrame | None,
    ) -> TrendAnalysisResult:
        if daily_df is None or daily_df.empty:
            return TrendAnalysisResult(code=code)

        try:
            return self.trend_analyzer.analyze(daily_df, code)
        except Exception:
            return TrendAnalysisResult(code=code)

    def _load_recent_news_items(
        self, code: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        with self.db_manager.session_scope() as session:
            rows = (
                session.execute(
                    select(NewsIntel)
                    .where(NewsIntel.code == code)
                    .order_by(desc(NewsIntel.fetched_at))
                    .limit(max(1, limit))
                )
                .scalars()
                .all()
            )

            return [
                {
                    "title": row.title,
                    "summary": row.snippet,
                    "source": row.source,
                    "url": row.url,
                }
                for row in rows
            ]

    @staticmethod
    def _price_levels(
        current_price: float | None,
        support_levels: list[float],
        region: MarketRegion | None = None,
    ) -> tuple[float | None, float | None, float | None]:
        if current_price is None or current_price <= 0:
            return None, None, None

        if support_levels:
            ideal_buy = min(
                support_levels, key=lambda level: abs(current_price - level)
            )
            stop_loss = round(ideal_buy * 0.95, 2)
        else:
            ideal_buy = round(current_price * 0.98, 2)
            stop_loss = round(current_price * 0.93, 2)

        target_region = region or MarketRegion.CN
        if target_region == MarketRegion.CN:
            stop_loss = round(current_price * CN_STOP_LOSS_RATIO, 2)
            take_profit = round(current_price * CN_TAKE_PROFIT_RATIO, 2)
        else:
            take_profit = round(current_price * 1.12, 2)
        return round(float(ideal_buy), 2), stop_loss, take_profit

    def _load_scoring_weights(self) -> ScoringWeights:
        payload: dict[str, int] = {}

        for (
            field_name,
            env_key,
            attr_name,
            default_value,
        ) in self.SCORING_WEIGHT_CONFIG_MAPPING:
            preferred_value = self._recommendation_config_value(
                (attr_name,), (env_key,)
            )
            resolved = self._coerce_weight_value(preferred_value)
            payload[field_name] = default_value if resolved is None else resolved

        try:
            return ScoringWeights(**payload)
        except Exception:
            return DEFAULT_SCORING_WEIGHTS

    def _persist_scoring_weights(self, weights: ScoringWeights) -> None:
        updates = [
            (env_key, str(getattr(weights, field_name)))
            for field_name, env_key, _, _ in self.SCORING_WEIGHT_CONFIG_MAPPING
        ]
        ConfigManager().apply_updates(
            updates=updates,
            sensitive_keys=set(),
            mask_token="******",
        )

        for field_name, _, attr_name, _ in self.SCORING_WEIGHT_CONFIG_MAPPING:
            setattr(self.config, attr_name, int(getattr(weights, field_name)))

        try:
            Config.reset_instance()
            setup_env(override=True)
        except Exception as exc:
            logger.warning(
                "Failed to reload runtime config after weight update: %s", exc
            )

    @staticmethod
    def _coerce_weight_value(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None

        if isinstance(value, int):
            candidate = value
        elif isinstance(value, float):
            if not float(value).is_integer():
                return None
            candidate = int(value)
        else:
            text = str(value).strip()
            if not text:
                return None
            try:
                candidate = int(text)
            except (TypeError, ValueError):
                return None

        if candidate < 0 or candidate > 100:
            return None
        return candidate

    def _read_recommendation_config_map(self) -> dict[str, Any]:
        try:
            return ConfigManager().read_config_map()
        except Exception as exc:
            logger.warning("Failed to read recommendation config map: %s", exc)
            return {}

    def _recommendation_config_value(
        self,
        attr_names: tuple[str, ...],
        env_keys: tuple[str, ...],
        default: Any = None,
    ) -> Any:
        if not isinstance(self.config, Config):
            explicit_value = self._config_attr_value(attr_names)
            if explicit_value is not None:
                return explicit_value

        for env_key in env_keys:
            env_value = self._recommendation_config_map.get(env_key)
            if env_value is None:
                continue
            if isinstance(env_value, str) and not env_value.strip():
                continue
            return env_value

        runtime_value = self._config_attr_value(attr_names)
        if runtime_value is not None:
            return runtime_value
        return default

    def _config_attr_value(self, attr_names: tuple[str, ...]) -> Any:
        for attr_name in attr_names:
            if not hasattr(self.config, attr_name):
                continue
            value = getattr(self.config, attr_name)
            if value is not None:
                return value
        return None

    @staticmethod
    def _numeric_values(values: list[Any]) -> list[float]:
        output: list[float] = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if pd.isna(number):
                continue
            output.append(number)
        return output

    @staticmethod
    def _window_mean(values: list[float], window: int) -> float:
        bounded = values[-max(1, window) :]
        if not bounded:
            return 0.0
        return float(sum(bounded) / len(bounded))
