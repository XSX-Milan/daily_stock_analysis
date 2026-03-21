from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from typing import cast

import src.auth as auth
from src.config import Config
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    StockRecommendation,
)
from src.services.analysis_result_service import AnalysisResultService
from src.storage import DatabaseManager


class AnalysisResultServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        auth._auth_enabled = False
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(
            self._temp_dir.name, "test_analysis_result_service.db"
        )
        os.environ["DATABASE_PATH"] = self._db_path

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    @staticmethod
    def _build_recommendation(
        *,
        code: str = "600519",
        updated_at: datetime | None = None,
    ) -> StockRecommendation:
        composite_score = CompositeScore(
            total_score=86.2,
            priority=RecommendationPriority.BUY_NOW,
            dimension_scores=[
                DimensionScore(
                    dimension="sentiment",
                    score=66.8,
                    weight=0.2,
                    details={},
                )
            ],
            ai_refined=True,
            ai_summary="多头趋势延续，关注回踩后的低吸机会。",
        )
        return StockRecommendation(
            code=code,
            name="贵州茅台",
            region=MarketRegion.CN,
            sector="白酒",
            current_price=100.0,
            composite_score=composite_score,
            ideal_buy_price=98.0,
            stop_loss=93.0,
            take_profit=110.0,
            updated_at=updated_at or datetime(2026, 3, 21, 10, 30, 0),
        )

    def test_save_recommendation_result_returns_explicit_identity(self) -> None:
        service = AnalysisResultService(db_manager=self.db)
        identity = service.save_recommendation_result(
            recommendation=self._build_recommendation(),
            recommendation_record_id=42,
        )

        self.assertGreater(identity.analysis_id, 0)
        self.assertEqual(identity.query_id, "rec_600519_20260321_42")

        row = service.get_by_id(identity.analysis_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.report_type, "recommendation")
        self.assertEqual(row.query_id, "rec_600519_20260321_42")
        self.assertEqual(row.sentiment_score, 67)
        self.assertEqual(row.operation_advice, "强烈买入")
        self.assertEqual(row.trend_prediction, "看多")
        self.assertEqual(row.ideal_buy, 98.0)
        self.assertEqual(row.stop_loss, 93.0)
        self.assertEqual(row.take_profit, 110.0)

        raw_result = json.loads(cast(str, row.raw_result))
        self.assertEqual(raw_result.get("source"), "recommendation_refresh")
        self.assertEqual(raw_result.get("data_sources"), "recommendation_refresh")
        self.assertEqual(
            raw_result.get("recommendation", {}).get("priority", {}).get("name"),
            "BUY_NOW",
        )

    def test_get_latest_recommendation_result_by_code_and_date(self) -> None:
        service = AnalysisResultService(db_manager=self.db)
        target_dt = datetime(2026, 3, 21, 14, 0, 0)
        first_identity = service.save_recommendation_result(
            recommendation=self._build_recommendation(updated_at=target_dt),
            recommendation_record_id=11,
        )
        second_identity = service.save_recommendation_result(
            recommendation=self._build_recommendation(updated_at=target_dt),
            recommendation_record_id=12,
        )

        latest = service.get_latest_recommendation_result(
            code="600519",
            target_date=target_dt.date(),
        )
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(cast(int, latest.id), second_identity.analysis_id)
        self.assertNotEqual(first_identity.analysis_id, second_identity.analysis_id)


if __name__ == "__main__":
    unittest.main()
