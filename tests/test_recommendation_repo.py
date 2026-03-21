from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    StockRecommendation,
)
from src.recommendation.trading_day_policy import derive_recommendation_trading_day
from src.repositories.recommendation_repo import RecommendationRepository
from src.storage import DatabaseManager


def build_recommendation(
    code: str,
    *,
    name: str,
    region: MarketRegion,
    sector: str,
    priority: RecommendationPriority,
    total_score: float,
    updated_at: datetime,
) -> StockRecommendation:
    return StockRecommendation(
        code=code,
        name=name,
        region=region,
        sector=sector,
        current_price=100.0,
        composite_score=CompositeScore(
            total_score=total_score,
            priority=priority,
            dimension_scores=[
                DimensionScore(
                    dimension="technical",
                    score=70.0,
                    weight=0.3,
                    details={"note": "seed"},
                )
            ],
            ai_refined=True,
            ai_summary="concise",
        ),
        ideal_buy_price=98.0,
        stop_loss=92.0,
        take_profit=110.0,
        updated_at=updated_at,
    )


class TestRecommendationRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "recommendation_repo.db")
        self.db_url = f"sqlite:///{self.db_path}"
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(self.db_url)
        self.repo = RecommendationRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self.temp_dir.cleanup()

    def test_save_and_get_latest_supports_daily_upsert(self) -> None:
        now = datetime(2026, 3, 13, 10, 0, 0)
        rec_v1 = build_recommendation(
            "600519",
            name="Moutai",
            region=MarketRegion.CN,
            sector="Liquor",
            priority=RecommendationPriority.BUY_NOW,
            total_score=85.0,
            updated_at=now,
        )
        self.repo.save_recommendation(rec_v1)

        rec_v2 = build_recommendation(
            "600519",
            name="Moutai",
            region=MarketRegion.CN,
            sector="Liquor",
            priority=RecommendationPriority.POSITION,
            total_score=66.0,
            updated_at=now + timedelta(hours=1),
        )
        self.repo.save_recommendation(rec_v2)

        latest = self.repo.get_latest("600519")
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.composite_score.total_score, 66.0)
        self.assertEqual(
            latest.composite_score.priority, RecommendationPriority.POSITION
        )
        self.assertEqual(latest.region, MarketRegion.CN)
        self.assertEqual(
            latest.composite_score.dimension_scores[0].dimension, "technical"
        )

        self.assertEqual(self.repo.get_count(), 1)

    def test_save_batch_uses_market_local_trading_day_identity(self) -> None:
        cn_updated_at = datetime(2026, 3, 13, 2, 0, 0)
        hk_updated_at = datetime(2026, 3, 13, 18, 30, 0)
        us_updated_at = datetime(2026, 3, 13, 1, 30, 0)

        saved = self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=90.0,
                    updated_at=cn_updated_at,
                ),
                build_recommendation(
                    "00700",
                    name="Tencent",
                    region=MarketRegion.HK,
                    sector="Internet",
                    priority=RecommendationPriority.POSITION,
                    total_score=80.0,
                    updated_at=hk_updated_at,
                ),
                build_recommendation(
                    "AAPL",
                    name="Apple",
                    region=MarketRegion.US,
                    sector="Technology",
                    priority=RecommendationPriority.POSITION,
                    total_score=70.0,
                    updated_at=us_updated_at,
                ),
            ]
        )

        cn_day = derive_recommendation_trading_day(
            stock_code="600519",
            updated_at=cn_updated_at,
            region=MarketRegion.CN,
        )
        hk_day = derive_recommendation_trading_day(
            stock_code="00700",
            updated_at=hk_updated_at,
            region=MarketRegion.HK,
        )
        us_day = derive_recommendation_trading_day(
            stock_code="AAPL",
            updated_at=us_updated_at,
            region=MarketRegion.US,
        )

        self.assertIn(("600519", cn_day), saved)
        self.assertIn(("00700", hk_day), saved)
        self.assertIn(("AAPL", us_day), saved)

        history_by_code = {
            item["code"]: item
            for item in self.repo.get_history_list(limit=10, offset=0)
        }
        self.assertEqual(
            history_by_code["600519"]["recommendation_date"], cn_day.isoformat()
        )
        self.assertEqual(
            history_by_code["00700"]["recommendation_date"], hk_day.isoformat()
        )
        self.assertEqual(
            history_by_code["AAPL"]["recommendation_date"], us_day.isoformat()
        )

    def test_get_list_and_get_count_apply_priority_sector_region_filters(self) -> None:
        now = datetime(2026, 3, 13, 9, 0, 0)
        self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=90.0,
                    updated_at=now,
                ),
                build_recommendation(
                    "00700",
                    name="Tencent",
                    region=MarketRegion.HK,
                    sector="Internet",
                    priority=RecommendationPriority.POSITION,
                    total_score=72.0,
                    updated_at=now,
                ),
                build_recommendation(
                    "AAPL",
                    name="Apple",
                    region=MarketRegion.US,
                    sector="Technology",
                    priority=RecommendationPriority.POSITION,
                    total_score=70.0,
                    updated_at=now,
                ),
            ]
        )

        buy_now_items = self.repo.get_list(priority="BUY_NOW")
        self.assertEqual(len(buy_now_items), 1)
        self.assertEqual(buy_now_items[0].code, "600519")

        position_items = self.repo.get_list(priority=RecommendationPriority.POSITION)
        self.assertEqual(len(position_items), 2)

        hk_items = self.repo.get_list(region="HK")
        self.assertEqual(len(hk_items), 1)
        self.assertEqual(hk_items[0].code, "00700")

        tech_count = self.repo.get_count(sector="Technology")
        self.assertEqual(tech_count, 1)

        self.assertEqual(
            self.repo.get_count(
                priority=RecommendationPriority.POSITION, region=MarketRegion.US
            ),
            1,
        )

        paged = self.repo.get_list(limit=1, offset=1)
        self.assertEqual(len(paged), 1)

    def test_get_priority_counts_uses_latest_recommendation_date(self) -> None:
        latest_day = datetime(2026, 3, 13, 9, 0, 0)
        old_day = latest_day - timedelta(days=1)

        self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=88.0,
                    updated_at=old_day,
                ),
                build_recommendation(
                    "AAPL",
                    name="Apple",
                    region=MarketRegion.US,
                    sector="Technology",
                    priority=RecommendationPriority.POSITION,
                    total_score=70.0,
                    updated_at=latest_day,
                ),
                build_recommendation(
                    "MSFT",
                    name="Microsoft",
                    region=MarketRegion.US,
                    sector="Technology",
                    priority=RecommendationPriority.POSITION,
                    total_score=68.0,
                    updated_at=latest_day,
                ),
            ]
        )

        counts = self.repo.get_priority_counts()
        self.assertEqual(counts, {"POSITION": 2})

    def test_delete_old_removes_records_older_than_window(self) -> None:
        now = datetime.now()
        self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=85.0,
                    updated_at=now - timedelta(days=40),
                ),
                build_recommendation(
                    "00700",
                    name="Tencent",
                    region=MarketRegion.HK,
                    sector="Internet",
                    priority=RecommendationPriority.POSITION,
                    total_score=65.0,
                    updated_at=now,
                ),
            ]
        )

        deleted = self.repo.delete_old(days=30)
        self.assertEqual(deleted, 1)
        self.assertEqual(self.repo.get_count(), 1)
        self.assertIsNotNone(self.repo.get_latest("00700"))

    def test_get_history_list_returns_sorted_rows_with_market_filter(self) -> None:
        base_time = datetime(2026, 3, 13, 9, 0, 0)
        self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=88.0,
                    updated_at=base_time,
                ),
                build_recommendation(
                    "AAPL",
                    name="Apple",
                    region=MarketRegion.US,
                    sector="Technology",
                    priority=RecommendationPriority.POSITION,
                    total_score=91.0,
                    updated_at=base_time + timedelta(minutes=30),
                ),
                build_recommendation(
                    "TSLA",
                    name="Tesla",
                    region=MarketRegion.US,
                    sector="Automotive",
                    priority=RecommendationPriority.POSITION,
                    total_score=77.0,
                    updated_at=base_time - timedelta(days=1),
                ),
            ]
        )

        items = self.repo.get_history_list(limit=10, offset=0)
        self.assertEqual([item["code"] for item in items], ["AAPL", "600519", "TSLA"])

        first = items[0]
        self.assertEqual(
            set(first.keys()),
            {
                "id",
                "query_id",
                "analysis_record_id",
                "code",
                "name",
                "sector",
                "composite_score",
                "priority",
                "recommendation_date",
                "updated_at",
                "ai_summary",
                "region",
                "market",
            },
        )
        self.assertEqual(first["query_id"], f"rec_AAPL_20260313_{first['id']}")
        self.assertIsNone(first["analysis_record_id"])
        self.assertEqual(first["region"], "US")
        self.assertEqual(first["market"], "US")
        self.assertEqual(first["recommendation_date"], "2026-03-13")
        self.assertEqual(first["ai_summary"], "concise")

        us_items = self.repo.get_history_list(market="US", limit=10, offset=0)
        self.assertEqual([item["code"] for item in us_items], ["AAPL", "TSLA"])

        paged = self.repo.get_history_list(limit=1, offset=1)
        self.assertEqual(len(paged), 1)
        self.assertEqual(paged[0]["code"], "600519")

    def test_update_analysis_record_link_persists_and_exposes_in_history(self) -> None:
        updated_at = datetime(2026, 3, 13, 9, 0, 0)
        saved_map = self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=88.0,
                    updated_at=updated_at,
                )
            ]
        )
        recommendation_record_id = saved_map[("600519", updated_at.date())]

        updated = self.repo.update_analysis_record_link(
            recommendation_record_id=recommendation_record_id,
            analysis_record_id=1234,
        )

        self.assertEqual(updated, 1)
        item = self.repo.get_history_list(limit=1, offset=0)[0]
        self.assertEqual(item["id"], recommendation_record_id)
        self.assertEqual(item["analysis_record_id"], 1234)
        self.assertEqual(
            item["query_id"], f"rec_600519_20260313_{recommendation_record_id}"
        )

    def test_get_by_id_and_get_by_code_and_date_support_history_resolution(
        self,
    ) -> None:
        updated_at = datetime(2026, 3, 13, 9, 0, 0)
        saved_map = self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=88.0,
                    updated_at=updated_at,
                )
            ]
        )
        ((identity, recommendation_record_id),) = saved_map.items()
        saved_code, recommendation_date = identity

        record_by_id = self.repo.get_by_id(recommendation_record_id)
        self.assertIsNotNone(record_by_id)
        assert record_by_id is not None
        self.assertEqual(record_by_id.id, recommendation_record_id)
        self.assertEqual(record_by_id.code, saved_code)
        self.assertEqual(record_by_id.recommendation_date, recommendation_date)

        record_by_code_date = self.repo.get_by_code_and_date(
            saved_code,
            recommendation_date,
        )
        self.assertIsNotNone(record_by_code_date)
        assert record_by_code_date is not None
        self.assertEqual(record_by_code_date.id, recommendation_record_id)

        self.assertIsNone(self.repo.get_by_id(0))
        self.assertIsNone(self.repo.get_by_code_and_date("", recommendation_date))

    def test_get_linked_recommendation_for_date_requires_non_null_link(self) -> None:
        updated_at = datetime(2026, 3, 13, 9, 0, 0)
        saved_map = self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=88.0,
                    updated_at=updated_at,
                )
            ]
        )
        recommendation_day = derive_recommendation_trading_day(
            stock_code="600519",
            updated_at=updated_at,
            region=MarketRegion.CN,
        )

        self.assertIsNone(
            self.repo.get_linked_recommendation_for_date("600519", recommendation_day)
        )

        recommendation_record_id = saved_map[("600519", recommendation_day)]
        self.assertEqual(
            self.repo.update_analysis_record_link(
                recommendation_record_id=recommendation_record_id,
                analysis_record_id=345,
            ),
            1,
        )

        linked = self.repo.get_linked_recommendation_for_date(
            "600519", recommendation_day
        )
        self.assertIsNotNone(linked)
        assert linked is not None
        recommendation, analysis_record_id = linked
        self.assertEqual(recommendation.code, "600519")
        self.assertEqual(analysis_record_id, 345)

    def test_delete_by_stock_removes_all_rows_for_code(self) -> None:
        base_time = datetime(2026, 3, 13, 9, 0, 0)
        self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=82.0,
                    updated_at=base_time,
                ),
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.POSITION,
                    total_score=70.0,
                    updated_at=base_time - timedelta(days=1),
                ),
                build_recommendation(
                    "AAPL",
                    name="Apple",
                    region=MarketRegion.US,
                    sector="Technology",
                    priority=RecommendationPriority.POSITION,
                    total_score=74.0,
                    updated_at=base_time,
                ),
            ]
        )

        deleted = self.repo.delete_by_stock(" 600519 ")
        self.assertEqual(deleted, 2)
        self.assertIsNone(self.repo.get_latest("600519"))
        self.assertEqual(self.repo.get_count(), 1)
        self.assertIsNotNone(self.repo.get_latest("AAPL"))

        self.assertEqual(self.repo.delete_by_stock(""), 0)

    def test_delete_by_ids_removes_only_requested_rows(self) -> None:
        base_time = datetime(2026, 3, 13, 9, 0, 0)
        self.repo.save_batch(
            [
                build_recommendation(
                    "600519",
                    name="Moutai",
                    region=MarketRegion.CN,
                    sector="Liquor",
                    priority=RecommendationPriority.BUY_NOW,
                    total_score=82.0,
                    updated_at=base_time,
                ),
                build_recommendation(
                    "AAPL",
                    name="Apple",
                    region=MarketRegion.US,
                    sector="Technology",
                    priority=RecommendationPriority.POSITION,
                    total_score=74.0,
                    updated_at=base_time,
                ),
            ]
        )

        items = self.repo.get_history_list(limit=10, offset=0)
        target_id = next(item["id"] for item in items if item["code"] == "600519")

        deleted = self.repo.delete_by_ids([target_id])
        self.assertEqual(deleted, 1)

        remaining_codes = [
            item["code"] for item in self.repo.get_history_list(limit=10, offset=0)
        ]
        self.assertEqual(remaining_codes, ["AAPL"])
        self.assertEqual(self.repo.delete_by_ids([]), 0)


if __name__ == "__main__":
    unittest.main()
