from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import pandas as pd

from src.config import Config, get_config, setup_env
from src.core.config_manager import ConfigManager
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
)


def build_composite_score(
    *,
    code: str,
    total_score: float,
    priority: RecommendationPriority,
) -> CompositeScore:
    composite_score = CompositeScore(total_score=total_score, priority=priority)
    setattr(composite_score, "code", code)
    return composite_score


def build_fast_service(config: SimpleNamespace):
    db_manager = MagicMock()
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None
    db_manager.session_scope.return_value.__enter__.return_value = session
    db_manager.session_scope.return_value.__exit__.return_value = None

    with (
        patch("src.services.recommendation_service.DataFetcherManager"),
        patch("src.services.recommendation_service.StockTrendAnalyzer"),
        patch("src.services.recommendation_service.GeminiAnalyzer"),
        patch("src.services.recommendation_service.RecommendationRepository"),
        patch("src.services.recommendation_service.WatchlistService"),
        patch("src.services.recommendation_service.SectorScannerService"),
        patch("src.services.recommendation_service.ScoringEngine"),
        patch(
            "src.services.recommendation_service.DatabaseManager.get_instance",
            return_value=db_manager,
        ),
    ):
        from src.services.recommendation_service import RecommendationService

        service = RecommendationService(config=config)

    def _mock_extract_sniper_points(result):
        if hasattr(result, "get_sniper_points"):
            return result.get_sniper_points() or {}
        return {}

    def _mock_build_raw_result(result):
        data = result.to_dict() if hasattr(result, "to_dict") else {}
        payload = dict(data) if isinstance(data, dict) else {"result": data}
        payload.update(
            {
                "data_sources": getattr(result, "data_sources", ""),
                "raw_response": getattr(result, "raw_response", None),
            }
        )
        return payload

    db_manager._extract_sniper_points = Mock(side_effect=_mock_extract_sniper_points)
    db_manager._build_raw_result = Mock(side_effect=_mock_build_raw_result)
    db_manager._safe_json_dumps = Mock(
        side_effect=lambda data: json.dumps(data, ensure_ascii=False, default=str)
    )

    service.recommendation_repo.get_latest = Mock(return_value=None)
    service.recommendation_repo.save_batch = Mock()
    service.recommendation_repo.get_list = Mock(return_value=[])
    service.recommendation_repo.get_count = Mock(return_value=0)
    service.recommendation_repo.get_priority_counts = Mock(return_value={})
    service.sector_cache_service.get_or_fetch_sector = Mock(return_value=None)
    service.sector_cache_service.save_sector_info = Mock()
    setattr(service, "_test_db_manager", db_manager)
    setattr(service, "_test_db_session", session)
    return service


class RecommendationServiceTestCase(unittest.TestCase):
    @staticmethod
    def _build_scoring_engine_stub(*, weights: ScoringWeights, **_: object) -> object:
        return SimpleNamespace(_weights=weights)

    def test_init_creates_required_components(self) -> None:
        config = SimpleNamespace(
            max_workers=3,
            recommend_sector_top_n=8,
            recommend_score_threshold_ai=70,
            recommendation_max_universe=120,
        )

        with (
            patch(
                "src.services.recommendation_service.DataFetcherManager"
            ) as manager_cls,
            patch(
                "src.services.recommendation_service.StockTrendAnalyzer"
            ) as trend_cls,
            patch("src.services.recommendation_service.GeminiAnalyzer") as gemini_cls,
            patch(
                "src.services.recommendation_service.RecommendationRepository"
            ) as repo_cls,
            patch(
                "src.services.recommendation_service.WatchlistService"
            ) as watchlist_cls,
            patch(
                "src.services.recommendation_service.SectorScannerService"
            ) as sector_cls,
            patch("src.services.recommendation_service.ScoringEngine") as engine_cls,
            patch("src.services.recommendation_service.DatabaseManager") as db_cls,
        ):
            from src.services.recommendation_service import RecommendationService

            service = RecommendationService(config=config)

        self.assertIsNotNone(service)
        manager_cls.assert_called_once_with()
        trend_cls.assert_called_once_with()
        gemini_cls.assert_called_once_with()
        repo_cls.assert_called_once_with()
        watchlist_cls.assert_called_once_with()
        sector_cls.assert_called_once_with(
            manager_cls.return_value,
            top_n=8,
            max_universe=120,
        )
        db_cls.get_instance.assert_called()
        engine_kwargs = engine_cls.call_args.kwargs
        self.assertIn("weights", engine_kwargs)
        self.assertIs(engine_kwargs["ai_refiner"], gemini_cls.return_value)
        self.assertEqual(service.recommend_score_threshold_ai, 70)

    def test_refresh_all_deduplicates_sector_and_watchlist_universe(self) -> None:
        config = SimpleNamespace(max_workers=2)

        with patch(
            "src.services.recommendation_service.RecommendationService.refresh_stocks"
        ) as refresh_stocks:
            refresh_stocks.return_value = ["ok"]
            service = build_fast_service(config)
            service.sector_scanner_service.get_sector_stocks = Mock(
                return_value=["000001", "000002", "000003", "000004"]
            )
            service.watchlist_service.get_watchlist = Mock(
                return_value=[
                    SimpleNamespace(code="000003"),
                    SimpleNamespace(code="000005"),
                ]
            )
            service.recommendation_repo.get_latest = Mock(
                side_effect=[
                    SimpleNamespace(sector="AI"),
                    SimpleNamespace(sector="Liquor"),
                ]
            )

            result = service.refresh_all(market="CN", sector="AI")

        self.assertEqual(result, ["ok"])
        refresh_stocks.assert_called_once_with(
            ["000001", "000002", "000003", "000004", "000005"],
            sector_by_code={
                "000001": "AI",
                "000002": "AI",
                "000003": "AI",
                "000004": "AI",
                "000005": "AI",
            },
            force=False,
            market=MarketRegion.CN,
            sector="AI",
        )

    def test_refresh_all_requires_market_and_rejects_blank_sector(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)

        with self.assertRaises(ValueError):
            service.refresh_all(market=None, sector="AI")

        with self.assertRaises(ValueError):
            service.refresh_all(market="CN", sector="")

    def test_refresh_all_with_explicit_sector_delegates_to_sector_refresh(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)

        with (
            patch.object(
                service,
                "_refresh_all_for_sector",
                return_value=["delegated"],
            ) as refresh_for_sector,
            patch.object(service, "refresh_stocks") as refresh_stocks,
        ):
            result = service.refresh_all(market="CN", sector="AI")

        self.assertEqual(result, ["delegated"])
        refresh_for_sector.assert_called_once_with(
            force=False,
            target_region=MarketRegion.CN,
            target_sector="AI",
        )
        refresh_stocks.assert_not_called()

    def test_resolve_auto_refresh_sectors_cn_uses_rankings_without_scan(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.sector_scanner_service.scan_sectors = Mock(
            side_effect=AssertionError("scan_sectors should not be called")
        )
        service.sector_scanner_service.data_fetcher = Mock()
        service.sector_scanner_service.data_fetcher.get_sector_rankings = Mock(
            return_value=([{"name": "AI"}, {"name": "半导体"}, {"name": "证券"}], [])
        )

        sectors = service._resolve_auto_refresh_sectors(MarketRegion.CN)

        self.assertEqual(sectors, ["AI", "半导体", "证券"])
        service.sector_scanner_service.scan_sectors.assert_not_called()

    def test_refresh_all_auto_hk_uses_overseas_fallback_sectors(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)

        from src.services.recommendation_service import _OVERSEAS_SECTOR_FALLBACK

        expected_sector_names = ["technology"]
        self.assertGreater(
            len(_OVERSEAS_SECTOR_FALLBACK["HK"]), len(expected_sector_names)
        )
        service.sector_scanner_service.get_sector_stocks = Mock(
            return_value=["HK00700", "HK03690"]
        )
        service.watchlist_service.get_watchlist = Mock(return_value=[])
        with patch.object(
            service, "refresh_stocks", return_value=["ok"]
        ) as refresh_stocks:
            result = service.refresh_all(market="HK", sector=None)

        self.assertEqual(result, ["ok"])
        refresh_stocks.assert_called_once_with(
            ["HK00700", "HK03690"],
            sector_by_code={
                "HK00700": "technology",
                "HK03690": "technology",
            },
            force=False,
        )
        service.sector_scanner_service.get_sector_stocks.assert_called_once_with(
            "technology",
            limit=service.sector_scanner_service.max_universe,
            market="HK",
        )

    def test_refresh_all_auto_us_deduplicates_alias_fallback_sectors(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)

        from src.services.recommendation_service import _OVERSEAS_SECTOR_FALLBACK

        expected_sector_names = ["technology", "communicationservices"]
        self.assertGreater(
            len(_OVERSEAS_SECTOR_FALLBACK["US"]), len(expected_sector_names)
        )
        service.sector_scanner_service.get_sector_stocks = Mock(
            side_effect=[
                ["AAPL", "MSFT", "NVDA", "AMD", "INTC", "GOOGL", "GOOG", "META"],
                ["META", "GOOGL", "GOOG"],
            ]
        )
        service.watchlist_service.get_watchlist = Mock(return_value=[])

        with patch.object(
            service, "refresh_stocks", return_value=["ok"]
        ) as refresh_stocks:
            result = service.refresh_all(market="US", sector=None)

        self.assertEqual(result, ["ok"])
        service.sector_scanner_service.get_sector_stocks.assert_has_calls(
            [
                call(
                    sector_name,
                    limit=service.sector_scanner_service.max_universe,
                    market="US",
                )
                for sector_name in expected_sector_names
            ]
        )
        self.assertEqual(service.sector_scanner_service.get_sector_stocks.call_count, 2)
        refresh_stocks.assert_called_once_with(
            ["AAPL", "MSFT", "NVDA", "AMD", "INTC", "GOOGL", "GOOG", "META"],
            sector_by_code={
                "AAPL": "technology",
                "MSFT": "technology",
                "NVDA": "technology",
                "AMD": "technology",
                "INTC": "technology",
                "GOOGL": "technology",
                "GOOG": "technology",
                "META": "technology",
            },
            force=False,
        )

    def test_refresh_all_auto_cn_uses_ranking_fallback_when_scan_empty(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.sector_scanner_service.scan_sectors = Mock(
            side_effect=AssertionError("scan_sectors should not be called")
        )
        service.sector_scanner_service.data_fetcher = Mock()
        service.sector_scanner_service.data_fetcher.get_sector_rankings = Mock(
            return_value=([{"name": "半导体"}, {"name": "人工智能"}], [])
        )
        service.sector_scanner_service.get_sector_stocks = Mock()
        service.sector_scanner_service.max_universe = 200
        service.recommendation_repo.get_list = Mock(
            return_value=[
                SimpleNamespace(code="688001", sector="半导体"),
                SimpleNamespace(code="300001", sector="人工智能"),
                SimpleNamespace(code="AAPL", sector="technology"),
            ]
        )
        service.watchlist_service.get_watchlist = Mock(return_value=[])

        with patch.object(service, "refresh_stocks") as refresh_stocks:
            result = service.refresh_all(market="CN", sector=None)

        self.assertEqual([item.code for item in result], ["688001", "300001"])
        service.sector_scanner_service.scan_sectors.assert_not_called()
        service.sector_scanner_service.get_sector_stocks.assert_not_called()
        service.recommendation_repo.get_list.assert_called_once_with(
            region=MarketRegion.CN,
            limit=5,
            offset=0,
        )
        refresh_stocks.assert_not_called()

    def test_refresh_all_auto_cn_uses_generic_persisted_fallback_when_sector_specific_empty(
        self,
    ) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.sector_scanner_service.scan_sectors = Mock(
            side_effect=AssertionError("scan_sectors should not be called")
        )
        service.sector_scanner_service.data_fetcher = Mock()
        service.sector_scanner_service.data_fetcher.get_sector_rankings = Mock(
            return_value=([{"name": "半导体"}], [])
        )
        service.sector_scanner_service.get_sector_stocks = Mock(return_value=[])
        service.sector_scanner_service.max_universe = 200
        service.recommendation_repo.get_list = Mock(
            return_value=[
                SimpleNamespace(code="688001", sector="半导体"),
                SimpleNamespace(code="600519", sector="白酒"),
                SimpleNamespace(code="AAPL", sector="technology"),
            ]
        )
        service.watchlist_service.get_watchlist = Mock(return_value=[])

        with patch.object(service, "refresh_stocks") as refresh_stocks:
            result = service.refresh_all(market="CN", sector=None)

        self.assertEqual([item.code for item in result], ["688001", "600519"])
        service.sector_scanner_service.scan_sectors.assert_not_called()
        service.sector_scanner_service.get_sector_stocks.assert_not_called()
        service.recommendation_repo.get_list.assert_called_once_with(
            region=MarketRegion.CN,
            limit=5,
            offset=0,
        )
        refresh_stocks.assert_not_called()

    def test_refresh_all_auto_cn_returns_empty_when_all_fallbacks_unavailable(
        self,
    ) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.sector_scanner_service.scan_sectors = Mock(
            side_effect=AssertionError("scan_sectors should not be called")
        )
        service.sector_scanner_service.data_fetcher = Mock()
        service.sector_scanner_service.data_fetcher.get_sector_rankings = Mock(
            return_value=([{"name": "半导体"}], [])
        )
        service.sector_scanner_service.get_sector_stocks = Mock(return_value=[])
        service.sector_scanner_service.max_universe = 5
        service.recommendation_repo.get_list = Mock(return_value=[])
        service.watchlist_service.get_watchlist = Mock(return_value=[])

        with patch.object(service, "refresh_stocks") as refresh_stocks:
            result = service.refresh_all(market="CN", sector=None)

        self.assertEqual(result, [])
        service.sector_scanner_service.scan_sectors.assert_not_called()
        refresh_stocks.assert_not_called()

    def test_resolve_auto_refresh_sectors_cn_returns_empty_without_scan_or_rankings(
        self,
    ) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.sector_scanner_service.scan_sectors = Mock(
            side_effect=AssertionError("scan_sectors should not be called")
        )
        service.sector_scanner_service.data_fetcher = Mock()
        service.sector_scanner_service.data_fetcher.get_sector_rankings = Mock(
            return_value=([], [])
        )

        sectors = service._resolve_auto_refresh_sectors(MarketRegion.CN)

        self.assertEqual(sectors, [])
        service.sector_scanner_service.scan_sectors.assert_not_called()

    def test_refresh_stocks_reuses_recent_records_when_not_forced(self) -> None:
        config = SimpleNamespace(max_workers=2, recommend_refresh_skip_seconds=300)
        service = build_fast_service(config)

        cached = Mock()
        cached.code = "600519"
        cached.updated_at = datetime.utcnow() - timedelta(seconds=30)
        cached.composite_score = Mock(total_score=77.0)

        stale = Mock()
        stale.code = "AAPL"
        stale.updated_at = datetime.utcnow() - timedelta(seconds=900)

        service.recommendation_repo.get_latest = Mock(side_effect=[cached, stale])
        service.recommendation_repo.save_batch = Mock()
        service._build_stock_payload = Mock(
            return_value={
                "code": "AAPL",
                "name": "Apple",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 200.0,
                "ideal_buy_price": 195.0,
                "stop_loss": 180.0,
                "take_profit": 225.0,
                "scoring_data": Mock(),
            }
        )
        fresh_score = build_composite_score(
            code="AAPL",
            total_score=88.0,
            priority=RecommendationPriority.BUY_NOW,
        )
        service.scoring_engine.score_batch = Mock(return_value=[fresh_score])

        result = service.refresh_stocks(["600519", "AAPL"])

        self.assertEqual([item.code for item in result], ["AAPL", "600519"])
        service._build_stock_payload.assert_called_once()
        called_code = service._build_stock_payload.call_args.args[0]
        self.assertEqual(called_code, "AAPL")
        saved_items = service.recommendation_repo.save_batch.call_args.args[0]
        self.assertEqual(len(saved_items), 1)
        self.assertEqual(saved_items[0].code, "AAPL")

    def test_refresh_stocks_force_bypasses_recent_cache(self) -> None:
        config = SimpleNamespace(max_workers=2, recommend_refresh_skip_seconds=300)
        service = build_fast_service(config)
        service._split_recent_cached_codes = Mock(return_value=({}, []))
        service._build_stock_payload = Mock(
            return_value={
                "code": "600519",
                "name": "Moutai",
                "region": MarketRegion.CN,
                "sector": "Liquor",
                "current_price": 100.0,
                "ideal_buy_price": 98.0,
                "stop_loss": 93.0,
                "take_profit": 110.0,
                "scoring_data": Mock(),
            }
        )
        service.scoring_engine.score_batch = Mock(
            return_value=[
                build_composite_score(
                    code="600519",
                    total_score=80.0,
                    priority=RecommendationPriority.BUY_NOW,
                )
            ]
        )
        service.recommendation_repo.save_batch = Mock()

        result = service.refresh_stocks(["600519"], force=True)

        self.assertEqual(len(result), 1)
        service._split_recent_cached_codes.assert_not_called()
        service._build_stock_payload.assert_called_once()

    def test_refresh_stocks_filters_codes_by_market_and_sector_scope(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.recommendation_repo.get_latest = Mock(
            side_effect=[
                SimpleNamespace(sector="Technology"),
                SimpleNamespace(sector="Liquor"),
            ]
        )
        service.recommendation_repo.save_batch = Mock()
        service._build_stock_payload = Mock(
            return_value={
                "code": "AAPL",
                "name": "Apple",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 200.0,
                "ideal_buy_price": 195.0,
                "stop_loss": 180.0,
                "take_profit": 225.0,
                "scoring_data": Mock(),
            }
        )
        service.scoring_engine.score_batch = Mock(
            return_value=[
                build_composite_score(
                    code="AAPL",
                    total_score=88.0,
                    priority=RecommendationPriority.BUY_NOW,
                )
            ]
        )

        result = service.refresh_stocks(
            ["AAPL", "600519"],
            force=True,
            market="US",
            sector="Technology",
        )

        self.assertEqual([item.code for item in result], ["AAPL"])
        service._build_stock_payload.assert_called_once()

    def test_refresh_stocks_requires_scope_pair_when_partially_provided(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)

        with self.assertRaises(ValueError):
            service.refresh_stocks(["AAPL"], market="US", sector=None)

        with self.assertRaises(ValueError):
            service.refresh_stocks(["AAPL"], market=None, sector="Technology")

    def test_refresh_stocks_auto_universe_enables_score_first_top_n(self) -> None:
        config = SimpleNamespace(
            max_workers=2,
            recommend_top_n_per_sector=2,
            recommend_score_threshold_ai=60,
        )
        service = build_fast_service(config)

        payloads = {
            "AAPL": {
                "code": "AAPL",
                "name": "Apple",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 200.0,
                "ideal_buy_price": 195.0,
                "stop_loss": 180.0,
                "take_profit": 225.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=92)
                ),
            },
            "MSFT": {
                "code": "MSFT",
                "name": "Microsoft",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 300.0,
                "ideal_buy_price": 295.0,
                "stop_loss": 280.0,
                "take_profit": 330.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=80)
                ),
            },
            "NVDA": {
                "code": "NVDA",
                "name": "NVIDIA",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 400.0,
                "ideal_buy_price": 390.0,
                "stop_loss": 365.0,
                "take_profit": 440.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=50)
                ),
            },
        }
        service._build_stock_payload = Mock(side_effect=lambda code, _: payloads[code])
        observed_codes: list[str] = []

        def _score_batch(inputs):
            observed_codes[:] = [code for code, _ in inputs]
            return [
                build_composite_score(
                    code=code,
                    total_score=90.0 - index,
                    priority=RecommendationPriority.BUY_NOW,
                )
                for index, (code, _) in enumerate(inputs)
            ]

        service.scoring_engine.score_batch = Mock(side_effect=_score_batch)
        service.recommendation_repo.save_batch = Mock()

        items = service.refresh_stocks(
            ["AAPL", "MSFT", "NVDA"],
            sector_by_code={
                "AAPL": "Technology",
                "MSFT": "Technology",
                "NVDA": "Technology",
            },
            force=True,
        )

        self.assertEqual(observed_codes, ["AAPL", "MSFT"])
        self.assertEqual([item.code for item in items], ["AAPL", "MSFT"])

    def test_refresh_stocks_explicit_sector_keeps_score_first_top_n(self) -> None:
        config = SimpleNamespace(
            max_workers=2,
            recommend_top_n_per_sector=2,
            recommend_score_threshold_ai=60,
        )
        service = build_fast_service(config)

        payloads = {
            "AAPL": {
                "code": "AAPL",
                "name": "Apple",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 200.0,
                "ideal_buy_price": 195.0,
                "stop_loss": 180.0,
                "take_profit": 225.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=88)
                ),
            },
            "MSFT": {
                "code": "MSFT",
                "name": "Microsoft",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 300.0,
                "ideal_buy_price": 295.0,
                "stop_loss": 280.0,
                "take_profit": 330.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=78)
                ),
            },
            "NVDA": {
                "code": "NVDA",
                "name": "NVIDIA",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 400.0,
                "ideal_buy_price": 390.0,
                "stop_loss": 365.0,
                "take_profit": 440.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=95)
                ),
            },
        }
        service._build_stock_payload = Mock(side_effect=lambda code, _: payloads[code])
        observed_codes: list[str] = []

        def _score_batch(inputs):
            observed_codes[:] = [code for code, _ in inputs]
            return [
                build_composite_score(
                    code=code,
                    total_score=92.0 - index,
                    priority=RecommendationPriority.BUY_NOW,
                )
                for index, (code, _) in enumerate(inputs)
            ]

        service.scoring_engine.score_batch = Mock(side_effect=_score_batch)
        service.recommendation_repo.save_batch = Mock()

        items = service.refresh_stocks(
            ["AAPL", "MSFT", "NVDA"],
            sector_by_code={
                "AAPL": "Technology",
                "MSFT": "Technology",
                "NVDA": "Technology",
            },
            force=True,
            market="US",
            sector="Technology",
        )

        self.assertEqual(observed_codes, ["NVDA", "AAPL"])
        self.assertEqual([item.code for item in items], ["NVDA", "AAPL"])

    def test_refresh_stocks_direct_path_without_sector_context_unchanged(self) -> None:
        config = SimpleNamespace(
            max_workers=2,
            recommend_top_n_per_sector=1,
            recommend_score_threshold_ai=95,
        )
        service = build_fast_service(config)

        payloads = {
            "AAPL": {
                "code": "AAPL",
                "name": "Apple",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 200.0,
                "ideal_buy_price": 195.0,
                "stop_loss": 180.0,
                "take_profit": 225.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=99)
                ),
            },
            "MSFT": {
                "code": "MSFT",
                "name": "Microsoft",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 300.0,
                "ideal_buy_price": 295.0,
                "stop_loss": 280.0,
                "take_profit": 330.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=70)
                ),
            },
            "NVDA": {
                "code": "NVDA",
                "name": "NVIDIA",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 400.0,
                "ideal_buy_price": 390.0,
                "stop_loss": 365.0,
                "take_profit": 440.0,
                "scoring_data": SimpleNamespace(
                    trend_result=SimpleNamespace(signal_score=40)
                ),
            },
        }
        service._build_stock_payload = Mock(side_effect=lambda code, _: payloads[code])
        observed_codes: list[str] = []

        def _score_batch(inputs):
            observed_codes[:] = [code for code, _ in inputs]
            return [
                build_composite_score(
                    code=code,
                    total_score=88.0 - index,
                    priority=RecommendationPriority.BUY_NOW,
                )
                for index, (code, _) in enumerate(inputs)
            ]

        service.scoring_engine.score_batch = Mock(side_effect=_score_batch)
        service.recommendation_repo.save_batch = Mock()

        items = service.refresh_stocks(["AAPL", "MSFT", "NVDA"], force=True)

        self.assertEqual(observed_codes, ["AAPL", "MSFT", "NVDA"])
        self.assertEqual([item.code for item in items], ["AAPL", "MSFT", "NVDA"])

    def test_refresh_stocks_scores_saves_and_sorts_desc(self) -> None:
        config = SimpleNamespace(max_workers=4)
        with patch(
            "src.services.recommendation_service.RecommendationService._build_stock_payload"
        ) as build_payload:
            service = build_fast_service(config)

            payload_a = {
                "code": "600519",
                "name": "Moutai",
                "region": MarketRegion.CN,
                "sector": "Liquor",
                "current_price": 100.0,
                "ideal_buy_price": 98.0,
                "stop_loss": 93.0,
                "take_profit": 110.0,
                "scoring_data": Mock(),
            }
            payload_b = {
                "code": "AAPL",
                "name": "Apple",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 200.0,
                "ideal_buy_price": 195.0,
                "stop_loss": 180.0,
                "take_profit": 225.0,
                "scoring_data": Mock(),
            }
            build_payload.side_effect = [payload_a, payload_b]

            high = build_composite_score(
                code="AAPL",
                total_score=88.0,
                priority=RecommendationPriority.BUY_NOW,
            )
            low = build_composite_score(
                code="600519",
                total_score=55.0,
                priority=RecommendationPriority.WAIT_PULLBACK,
            )
            service.scoring_engine.score_batch = Mock(return_value=[low, high])
            service.recommendation_repo.save_batch = Mock()

            items = service.refresh_stocks(["600519", "AAPL"])

        self.assertEqual([item.code for item in items], ["AAPL", "600519"])
        self.assertEqual(
            [item.composite_score.total_score for item in items],
            [88.0, 55.0],
        )
        service.recommendation_repo.save_batch.assert_called_once()
        saved_items = service.recommendation_repo.save_batch.call_args.args[0]
        self.assertEqual([item.code for item in saved_items], ["AAPL", "600519"])

    def test_refresh_stocks_uses_sector_metadata_from_sector_scan(self) -> None:
        config = SimpleNamespace(max_workers=2)
        with patch(
            "src.services.recommendation_service.RecommendationService._build_stock_payload"
        ) as build_payload:
            service = build_fast_service(config)
            service.recommendation_repo.save_batch = Mock()
            service.scoring_engine.score_batch = Mock(
                return_value=[
                    build_composite_score(
                        code="600519",
                        total_score=80.0,
                        priority=RecommendationPriority.BUY_NOW,
                    )
                ]
            )
            service.sector_cache_service.get_or_fetch_sector = Mock(
                return_value=SimpleNamespace(sector_name="Liquor")
            )
            build_payload.return_value = {
                "code": "600519",
                "name": "Moutai",
                "region": MarketRegion.CN,
                "sector": None,
                "current_price": 100.0,
                "ideal_buy_price": 98.0,
                "stop_loss": 93.0,
                "take_profit": 110.0,
                "scoring_data": Mock(),
            }

            items = service.refresh_stocks(
                ["600519"], sector_by_code={"600519": "Liquor"}
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].sector, "Liquor")

    def test_refresh_stocks_matches_scores_by_code_after_partial_failures(self) -> None:
        config = SimpleNamespace(max_workers=2)
        with patch(
            "src.services.recommendation_service.RecommendationService._build_stock_payload"
        ) as build_payload:
            service = build_fast_service(config)
            service.recommendation_repo.save_batch = Mock()
            payload_a = {
                "code": "600519",
                "name": "Moutai",
                "region": MarketRegion.CN,
                "sector": "Liquor",
                "current_price": 100.0,
                "ideal_buy_price": 98.0,
                "stop_loss": 93.0,
                "take_profit": 110.0,
                "scoring_data": Mock(),
            }
            payload_b = {
                "code": "AAPL",
                "name": "Apple",
                "region": MarketRegion.US,
                "sector": "Technology",
                "current_price": 200.0,
                "ideal_buy_price": 195.0,
                "stop_loss": 180.0,
                "take_profit": 225.0,
                "scoring_data": Mock(),
            }
            build_payload.side_effect = [payload_a, payload_b]
            service.scoring_engine.score_batch = Mock(
                return_value=[
                    build_composite_score(
                        code="AAPL",
                        total_score=88.0,
                        priority=RecommendationPriority.BUY_NOW,
                    )
                ]
            )

            items = service.refresh_stocks(["600519", "AAPL"], force=True)

        self.assertEqual([item.code for item in items], ["AAPL"])
        saved_items = service.recommendation_repo.save_batch.call_args.args[0]
        self.assertEqual([item.code for item in saved_items], ["AAPL"])

    def test_refresh_stocks_bridges_analysis_history_with_recommendation_payload(
        self,
    ) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.recommendation_repo.save_batch = Mock()
        service._build_stock_payload = Mock(
            return_value={
                "code": "600519",
                "name": "Moutai",
                "region": MarketRegion.CN,
                "sector": "Liquor",
                "current_price": 100.0,
                "ideal_buy_price": 98.0,
                "stop_loss": 93.0,
                "take_profit": 110.0,
                "scoring_data": Mock(),
            }
        )

        score = build_composite_score(
            code="600519",
            total_score=86.2,
            priority=RecommendationPriority.BUY_NOW,
        )
        score.dimension_scores = [
            DimensionScore(
                dimension="sentiment",
                score=66.8,
                weight=0.2,
                details={},
            )
        ]
        score.ai_summary = "多头趋势延续，关注回踩后的低吸机会。"
        service.scoring_engine.score_batch = Mock(return_value=[score])

        items = service.refresh_stocks(["600519"], force=True)

        self.assertEqual([item.code for item in items], ["600519"])
        session = getattr(service, "_test_db_session")
        session.add_all.assert_called_once()
        rows = session.add_all.call_args.args[0]
        self.assertEqual(len(rows), 1)

        row = rows[0]
        self.assertTrue(row.query_id.startswith("rec_600519_"))
        self.assertEqual(len(row.query_id.rsplit("_", maxsplit=1)[-1]), 8)
        self.assertEqual(row.sentiment_score, 67)
        self.assertEqual(row.operation_advice, "强烈买入")
        self.assertEqual(row.trend_prediction, "看多")
        self.assertEqual(row.analysis_summary, score.ai_summary)
        self.assertEqual(row.ideal_buy, 98.0)
        self.assertEqual(row.stop_loss, 93.0)
        self.assertEqual(row.take_profit, 110.0)

        raw_result = json.loads(row.raw_result)
        self.assertEqual(raw_result.get("source"), "recommendation_refresh")
        self.assertEqual(raw_result.get("data_sources"), "recommendation_refresh")
        self.assertEqual(
            raw_result.get("recommendation", {}).get("priority", {}).get("name"),
            "BUY_NOW",
        )

    def test_refresh_stocks_bridge_failure_logs_warning_without_blocking(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.recommendation_repo.save_batch = Mock()
        service._build_stock_payload = Mock(
            return_value={
                "code": "600519",
                "name": "Moutai",
                "region": MarketRegion.CN,
                "sector": "Liquor",
                "current_price": 100.0,
                "ideal_buy_price": 98.0,
                "stop_loss": 93.0,
                "take_profit": 110.0,
                "scoring_data": Mock(),
            }
        )
        service.scoring_engine.score_batch = Mock(
            return_value=[
                build_composite_score(
                    code="600519",
                    total_score=81.0,
                    priority=RecommendationPriority.POSITION,
                )
            ]
        )

        session = getattr(service, "_test_db_session")
        session.add_all.side_effect = RuntimeError("bridge write failed")

        with self.assertLogs(
            "src.services.recommendation_service", level="WARNING"
        ) as captured:
            items = service.refresh_stocks(["600519"], force=True)

        self.assertEqual(len(items), 1)
        service.recommendation_repo.save_batch.assert_called_once()
        self.assertTrue(
            any("analysis_history" in message for message in captured.output)
        )

    def test_build_stock_payload_prefers_quote_name_and_skips_name_lookup(self) -> None:
        service = build_fast_service(SimpleNamespace(max_workers=2))
        service.fetcher_manager.get_stock_name = Mock(return_value="Apple Lookup")
        service.fetcher_manager.get_realtime_quote = Mock(
            return_value=SimpleNamespace(price=200.0, name="Apple Quote")
        )
        service._get_daily_frame = Mock(return_value=None)
        service._build_trend_result = Mock(
            return_value=SimpleNamespace(support_levels=[])
        )
        service._load_recent_news_items = Mock(return_value=[])
        service._build_scoring_enrichment = Mock(
            return_value={
                "volume_trend": "unknown",
                "volume_ma5_ratio": None,
                "price_vs_ma10": None,
                "price_vs_ma20": None,
                "ma_alignment": "unknown",
                "trading_days": None,
                "max_hold_days": 10,
            }
        )

        payload = service._build_stock_payload("AAPL", {MarketRegion.US: {}})
        assert payload is not None

        self.assertEqual(payload["name"], "Apple Quote")
        self.assertEqual(payload["current_price"], 200.0)
        service.fetcher_manager.get_stock_name.assert_not_called()
        service.fetcher_manager.get_realtime_quote.assert_called_once_with("AAPL")

    def test_build_stock_payload_falls_back_to_name_lookup_when_quote_name_unusable(
        self,
    ) -> None:
        service = build_fast_service(SimpleNamespace(max_workers=2))
        service.fetcher_manager.get_stock_name = Mock(return_value="Apple Lookup")
        service.fetcher_manager.get_realtime_quote = Mock(
            return_value=SimpleNamespace(price=201.0, name="   ")
        )
        service._get_daily_frame = Mock(return_value=None)
        service._build_trend_result = Mock(
            return_value=SimpleNamespace(support_levels=[])
        )
        service._load_recent_news_items = Mock(return_value=[])
        service._build_scoring_enrichment = Mock(
            return_value={
                "volume_trend": "unknown",
                "volume_ma5_ratio": None,
                "price_vs_ma10": None,
                "price_vs_ma20": None,
                "ma_alignment": "unknown",
                "trading_days": None,
                "max_hold_days": 10,
            }
        )

        payload = service._build_stock_payload("AAPL", {MarketRegion.US: {}})
        assert payload is not None

        self.assertEqual(payload["name"], "Apple Lookup")
        self.assertEqual(payload["current_price"], 201.0)
        service.fetcher_manager.get_stock_name.assert_called_once_with(
            "AAPL", allow_realtime=False
        )
        service.fetcher_manager.get_realtime_quote.assert_called_once_with("AAPL")

    def test_build_stock_payload_preserves_quote_missing_name_fallback_behavior(
        self,
    ) -> None:
        service = build_fast_service(SimpleNamespace(max_workers=2))
        service.fetcher_manager.get_stock_name = Mock(return_value="")
        service.fetcher_manager.get_realtime_quote = Mock(return_value=None)
        service._get_daily_frame = Mock(
            return_value=pd.DataFrame({"close": [198.0, 199.5]})
        )
        service._build_trend_result = Mock(
            return_value=SimpleNamespace(support_levels=[])
        )
        service._load_recent_news_items = Mock(return_value=[])
        service._build_scoring_enrichment = Mock(
            return_value={
                "volume_trend": "unknown",
                "volume_ma5_ratio": None,
                "price_vs_ma10": None,
                "price_vs_ma20": None,
                "ma_alignment": "unknown",
                "trading_days": None,
                "max_hold_days": 10,
            }
        )

        payload = service._build_stock_payload("AAPL", {MarketRegion.US: {}})
        assert payload is not None

        self.assertEqual(payload["name"], "AAPL")
        self.assertEqual(payload["current_price"], 199.5)
        self.assertEqual(payload["ideal_buy_price"], 195.51)
        self.assertEqual(payload["stop_loss"], 185.53)
        self.assertEqual(payload["take_profit"], 223.44)
        self.assertEqual(payload["scoring_data"].quote.name, "AAPL")
        service.fetcher_manager.get_stock_name.assert_called_once_with(
            "AAPL", allow_realtime=False
        )
        service.fetcher_manager.get_realtime_quote.assert_called_once_with("AAPL")

    def test_get_recommendations_passthroughs_filters_and_total(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)
        service.recommendation_repo.get_list = Mock(return_value=["item"])
        service.recommendation_repo.get_count = Mock(return_value=7)

        items, total = service.get_recommendations(
            priority="BUY_NOW",
            sector="Technology",
            region="US",
            limit=10,
            offset=5,
        )

        self.assertEqual(items, ["item"])
        self.assertEqual(total, 7)
        service.recommendation_repo.get_list.assert_called_once_with(
            priority="BUY_NOW",
            sector="Technology",
            region="US",
            limit=10,
            offset=5,
        )
        service.recommendation_repo.get_count.assert_called_once_with(
            priority="BUY_NOW",
            sector="Technology",
            region="US",
        )

    def test_get_priority_summary_from_repository(self) -> None:
        service = build_fast_service(SimpleNamespace(max_workers=2))
        service.recommendation_repo.get_priority_counts = Mock(
            return_value={"BUY_NOW": 1, "POSITION": 2}
        )

        summary = service.get_priority_summary()
        self.assertEqual(summary, {"BUY_NOW": 1, "POSITION": 2})

    def test_update_scoring_weights_persists_for_new_service_instance(self) -> None:
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        env_path = os.path.join(temp_dir.name, ".env")
        Path(env_path).write_text("", encoding="utf-8")

        weight_env_keys = [
            "RECOMMEND_WEIGHT_TECHNICAL",
            "RECOMMEND_WEIGHT_FUNDAMENTAL",
            "RECOMMEND_WEIGHT_SENTIMENT",
            "RECOMMEND_WEIGHT_MACRO",
            "RECOMMEND_WEIGHT_RISK",
        ]
        previous_weight_env = {key: os.environ.get(key) for key in weight_env_keys}
        previous_env_file = os.environ.get("ENV_FILE")
        os.environ["ENV_FILE"] = env_path
        Config.reset_instance()

        db_manager = MagicMock()
        persisted: dict[str, str] = {}

        try:
            with (
                patch("src.services.recommendation_service.DataFetcherManager"),
                patch("src.services.recommendation_service.StockTrendAnalyzer"),
                patch("src.services.recommendation_service.GeminiAnalyzer"),
                patch("src.services.recommendation_service.RecommendationRepository"),
                patch("src.services.recommendation_service.WatchlistService"),
                patch("src.services.recommendation_service.SectorScannerService"),
                patch(
                    "src.services.recommendation_service.ScoringEngine",
                    side_effect=self._build_scoring_engine_stub,
                ),
                patch(
                    "src.services.recommendation_service.DatabaseManager.get_instance",
                    return_value=db_manager,
                ),
            ):
                from src.services.recommendation_service import RecommendationService

                service = RecommendationService(config=SimpleNamespace(max_workers=2))
                updated = service.update_scoring_weights(
                    {
                        "technical": 35,
                        "fundamental": 20,
                        "sentiment": 20,
                        "macro": 15,
                        "risk": 10,
                    }
                )

                reloaded = RecommendationService(config=SimpleNamespace(max_workers=2))
                loaded = reloaded.get_scoring_weights()

            persisted = ConfigManager(env_path=Path(env_path)).read_config_map()
        finally:
            for key, value in previous_weight_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            if previous_env_file is None:
                os.environ.pop("ENV_FILE", None)
            else:
                os.environ["ENV_FILE"] = previous_env_file
            Config.reset_instance()
            setup_env(override=True)
            temp_dir.cleanup()

        self.assertEqual(
            updated,
            ScoringWeights(
                technical=35, fundamental=20, sentiment=20, macro=15, risk=10
            ),
        )
        self.assertEqual(loaded, updated)
        self.assertEqual(persisted.get("RECOMMEND_WEIGHT_TECHNICAL"), "35")
        self.assertEqual(persisted.get("RECOMMEND_WEIGHT_FUNDAMENTAL"), "20")
        self.assertEqual(persisted.get("RECOMMEND_WEIGHT_SENTIMENT"), "20")
        self.assertEqual(persisted.get("RECOMMEND_WEIGHT_MACRO"), "15")
        self.assertEqual(persisted.get("RECOMMEND_WEIGHT_RISK"), "10")

    def test_init_scoring_weights_fallbacks_to_default_when_env_values_invalid(
        self,
    ) -> None:
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        env_path = os.path.join(temp_dir.name, ".env")
        Path(env_path).write_text(
            "\n".join(
                [
                    "RECOMMEND_WEIGHT_TECHNICAL=abc",
                    "RECOMMEND_WEIGHT_FUNDAMENTAL=25",
                    "RECOMMEND_WEIGHT_SENTIMENT=20",
                    "RECOMMEND_WEIGHT_MACRO=15",
                    "RECOMMEND_WEIGHT_RISK=10",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        weight_env_keys = [
            "RECOMMEND_WEIGHT_TECHNICAL",
            "RECOMMEND_WEIGHT_FUNDAMENTAL",
            "RECOMMEND_WEIGHT_SENTIMENT",
            "RECOMMEND_WEIGHT_MACRO",
            "RECOMMEND_WEIGHT_RISK",
        ]
        previous_weight_env = {key: os.environ.get(key) for key in weight_env_keys}
        previous_env_file = os.environ.get("ENV_FILE")
        os.environ["ENV_FILE"] = env_path
        Config.reset_instance()

        db_manager = MagicMock()

        try:
            with (
                patch("src.services.recommendation_service.DataFetcherManager"),
                patch("src.services.recommendation_service.StockTrendAnalyzer"),
                patch("src.services.recommendation_service.GeminiAnalyzer"),
                patch("src.services.recommendation_service.RecommendationRepository"),
                patch("src.services.recommendation_service.WatchlistService"),
                patch("src.services.recommendation_service.SectorScannerService"),
                patch(
                    "src.services.recommendation_service.ScoringEngine",
                    side_effect=self._build_scoring_engine_stub,
                ),
                patch(
                    "src.services.recommendation_service.DatabaseManager.get_instance",
                    return_value=db_manager,
                ),
            ):
                from src.services.recommendation_service import RecommendationService

                service = RecommendationService(config=SimpleNamespace(max_workers=2))
                loaded = service.get_scoring_weights()
        finally:
            for key, value in previous_weight_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            if previous_env_file is None:
                os.environ.pop("ENV_FILE", None)
            else:
                os.environ["ENV_FILE"] = previous_env_file
            Config.reset_instance()
            setup_env(override=True)
            temp_dir.cleanup()

        self.assertEqual(loaded, ScoringWeights())

    def test_init_prefers_env_recommendation_values_when_config_is_stale(self) -> None:
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        env_path = os.path.join(temp_dir.name, ".env")
        Path(env_path).write_text(
            "\n".join(
                [
                    "RECOMMEND_WEIGHT_TECHNICAL=35",
                    "RECOMMEND_WEIGHT_FUNDAMENTAL=20",
                    "RECOMMEND_WEIGHT_SENTIMENT=20",
                    "RECOMMEND_WEIGHT_MACRO=15",
                    "RECOMMEND_WEIGHT_RISK=10",
                    "RECOMMEND_REFRESH_SKIP_SECONDS=180",
                    "RECOMMEND_TOP_N_PER_SECTOR=7",
                    "RECOMMEND_MAX_UNIVERSE=150",
                    "RECOMMEND_SCORE_THRESHOLD_AI=75",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        previous_env_file = os.environ.get("ENV_FILE")
        os.environ["ENV_FILE"] = env_path
        Config.reset_instance()
        setup_env(override=True)
        stale_config = get_config()

        stale_config.recommend_weight_technical = 30
        stale_config.recommend_weight_fundamental = 25
        stale_config.recommend_weight_sentiment = 20
        stale_config.recommend_weight_macro = 15
        stale_config.recommend_weight_risk = 10
        stale_config.recommend_refresh_skip_seconds = 300
        stale_config.recommend_top_n_per_sector = 5
        stale_config.recommend_max_universe = 200
        stale_config.recommend_score_threshold_ai = 60

        db_manager = MagicMock()

        try:
            with (
                patch("src.services.recommendation_service.DataFetcherManager"),
                patch("src.services.recommendation_service.StockTrendAnalyzer"),
                patch("src.services.recommendation_service.GeminiAnalyzer"),
                patch("src.services.recommendation_service.RecommendationRepository"),
                patch("src.services.recommendation_service.WatchlistService"),
                patch("src.services.recommendation_service.SectorScannerService"),
                patch(
                    "src.services.recommendation_service.ScoringEngine",
                    side_effect=self._build_scoring_engine_stub,
                ),
                patch(
                    "src.services.recommendation_service.DatabaseManager.get_instance",
                    return_value=db_manager,
                ),
            ):
                from src.services.recommendation_service import RecommendationService

                service = RecommendationService(config=stale_config)
                loaded = service.get_scoring_weights()
        finally:
            if previous_env_file is None:
                os.environ.pop("ENV_FILE", None)
            else:
                os.environ["ENV_FILE"] = previous_env_file
            Config.reset_instance()
            setup_env(override=True)
            temp_dir.cleanup()

        self.assertEqual(
            loaded,
            ScoringWeights(
                technical=35,
                fundamental=20,
                sentiment=20,
                macro=15,
                risk=10,
            ),
        )
        self.assertEqual(service.refresh_skip_seconds, 180)
        self.assertEqual(service.recommend_top_n_per_sector, 7)
        self.assertEqual(service.recommend_score_threshold_ai, 75)


if __name__ == "__main__":
    unittest.main()
