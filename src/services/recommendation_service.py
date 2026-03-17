# -*- coding: utf-8 -*-
"""Service layer for recommendation refresh, scoring, and query workflows."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
from sqlalchemy import desc, select

from data_provider import DataFetcherManager
from data_provider.realtime_types import UnifiedRealtimeQuote
from src.analyzer import GeminiAnalyzer
from src.config import get_config
from src.recommendation.constants import (
    DEFAULT_SCORING_WEIGHTS,
    POSITION_MIN_SCORE,
)
from src.recommendation.sector_cache import SectorCacheService
from src.recommendation.db_models import ScoringConfigRecord
from src.recommendation.engine import ScoringEngine, StockScoringData
from src.recommendation.market_utils import detect_market_region, get_market_indices
from src.recommendation.models import (
    MarketRegion,
    ScoringWeights,
    SectorInfo,
    StockRecommendation,
)
from src.repositories.recommendation_repo import RecommendationRepository
from src.services.sector_scanner_service import SectorScannerService
from src.services.watchlist_service import WatchlistService
from src.stock_analyzer import TrendAnalysisResult, StockTrendAnalyzer
from src.storage import DatabaseManager, NewsIntel

logger = logging.getLogger(__name__)


class RecommendationService:
    """Coordinate data collection, scoring, persistence, and watchlist access."""

    SCORING_WEIGHTS_KEY = "recommendation.scoring_weights"
    SECTOR_CACHE_TYPE = "industry"

    def __init__(self, config: Any = None) -> None:
        self.config = config or get_config()

        def _config_int(*keys: str, default: int) -> int:
            for key in keys:
                if hasattr(self.config, key):
                    value = getattr(self.config, key)
                    if value is not None:
                        try:
                            return int(value)
                        except (TypeError, ValueError):
                            continue
            return int(default)

        self.max_workers = max(1, int(getattr(self.config, "max_workers", 4)))
        self.refresh_skip_seconds = max(
            0,
            _config_int("recommend_refresh_skip_seconds", default=300),
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
                    default=5,
                ),
            ),
            max_universe=max(
                1,
                _config_int(
                    "recommend_max_universe",
                    "recommendation_max_universe",
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
                default=5,
            ),
        )
        self.recommend_score_threshold_ai = max(
            0,
            min(
                100,
                _config_int("recommend_score_threshold_ai", default=60),
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
        target_sector = str(sector or "").strip()
        if not target_sector:
            raise ValueError("sector is required for recommendation refresh")

        sector_by_code: dict[str, str] = {}
        sector_codes: list[str] = []

        sector_codes = self.sector_scanner_service.get_sector_stocks(
            target_sector,
            limit=self.sector_scanner_service.max_universe,
            market=target_region.value,
        )
        if not sector_codes and target_region != MarketRegion.CN:
            logger.info(
                "Sector scan returned no codes for market=%s, sector=%s",
                target_region.value,
                target_sector,
            )
        for code in sector_codes:
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
        for code in scoped_watchlist_codes:
            sector_by_code.setdefault(code, target_sector)
        combined_codes = list(dict.fromkeys([*sector_codes, *scoped_watchlist_codes]))
        return self.refresh_stocks(
            combined_codes,
            sector_by_code=sector_by_code,
            force=force,
            market=target_region,
            sector=target_sector,
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

        resolved_sector_by_code = self._resolve_sector_mapping(
            codes_to_refresh,
            sector_by_code,
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
            score_first_enabled=sector is not None,
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
        normalized_sector_by_code = {
            str(code).strip(): value
            for code, value in resolved_sector_by_code.items()
            if str(code).strip() and str(value).strip()
        }

        new_recommendations: list[StockRecommendation] = []
        for (code, _), composite_score in zip(score_filtered_inputs, composite_scores):
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
        return merged_recommendations

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
            batch_max_workers=self.max_workers,
        )
        return new_weights

    def _build_stock_payload(
        self,
        code: str,
        region_index_data: dict[MarketRegion, dict[str, dict[str, float]]],
    ) -> dict[str, Any] | None:
        region = detect_market_region(code)
        name = self.fetcher_manager.get_stock_name(code) or code

        quote = self.fetcher_manager.get_realtime_quote(code)
        daily_df = self._get_daily_frame(code, days=90)

        if quote is None:
            quote = self._build_fallback_quote(code, name, daily_df)

        trend_result = self._build_trend_result(code, daily_df)
        news_items = self._load_recent_news_items(code)

        scoring_data = StockScoringData(
            region=region,
            trend_result=trend_result,
            quote=quote,
            news_items=news_items,
            index_data=region_index_data.get(region, {}),
        )

        ideal_buy_price, stop_loss, take_profit = self._price_levels(
            quote.price, trend_result.support_levels
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

        take_profit = round(current_price * 1.12, 2)
        return round(float(ideal_buy), 2), stop_loss, take_profit

    def _load_scoring_weights(self) -> ScoringWeights:
        with self.db_manager.session_scope() as session:
            record = session.execute(
                select(ScoringConfigRecord).where(
                    ScoringConfigRecord.key == self.SCORING_WEIGHTS_KEY
                )
            ).scalar_one_or_none()

            if record is None:
                return DEFAULT_SCORING_WEIGHTS

            payload = record.get_value_dict() or {}
            try:
                return ScoringWeights(**payload)
            except Exception:
                return DEFAULT_SCORING_WEIGHTS

    def _persist_scoring_weights(self, weights: ScoringWeights) -> None:
        payload_json = json.dumps(asdict(weights), ensure_ascii=False)
        with self.db_manager.session_scope() as session:
            record = session.execute(
                select(ScoringConfigRecord).where(
                    ScoringConfigRecord.key == self.SCORING_WEIGHTS_KEY
                )
            ).scalar_one_or_none()

            if record is None:
                session.add(
                    ScoringConfigRecord(
                        key=self.SCORING_WEIGHTS_KEY,
                        value_json=payload_json,
                    )
                )
            else:
                setattr(record, "value_json", payload_json)

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
