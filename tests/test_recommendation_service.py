from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from src.recommendation.models import (
    CompositeScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
)
from src.storage import DatabaseManager


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

    service.recommendation_repo.get_latest = Mock(return_value=None)
    service.recommendation_repo.save_batch = Mock()
    service.recommendation_repo.get_list = Mock(return_value=[])
    service.recommendation_repo.get_count = Mock(return_value=0)
    service.recommendation_repo.get_priority_counts = Mock(return_value={})
    service.sector_cache_service.get_or_fetch_sector = Mock(return_value=None)
    service.sector_cache_service.save_sector_info = Mock()
    return service


class RecommendationServiceTestCase(unittest.TestCase):
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

    def test_refresh_all_requires_market_and_sector(self) -> None:
        config = SimpleNamespace(max_workers=2)
        service = build_fast_service(config)

        with self.assertRaises(ValueError):
            service.refresh_all(market=None, sector="AI")

        with self.assertRaises(ValueError):
            service.refresh_all(market="CN", sector="")

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
        fresh_score = CompositeScore(
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
                CompositeScore(
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
                CompositeScore(
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

            high = CompositeScore(
                total_score=88.0, priority=RecommendationPriority.BUY_NOW
            )
            low = CompositeScore(
                total_score=55.0, priority=RecommendationPriority.WAIT_PULLBACK
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
                    CompositeScore(
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
        db_path = os.path.join(temp_dir.name, "recommendation_service.db")
        db_url = f"sqlite:///{db_path}"
        DatabaseManager.reset_instance()
        db = DatabaseManager(db_url)

        with patch(
            "src.services.recommendation_service.DatabaseManager.get_instance",
            return_value=db,
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

        self.assertEqual(
            updated,
            ScoringWeights(
                technical=35, fundamental=20, sentiment=20, macro=15, risk=10
            ),
        )
        self.assertEqual(loaded, updated)

        DatabaseManager.reset_instance()
        temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
