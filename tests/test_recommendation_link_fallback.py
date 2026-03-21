import os
import tempfile
import unittest
from datetime import datetime
from typing import cast

from src.analyzer import AnalysisResult
from src.config import Config
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    StockRecommendation,
)
from src.repositories.recommendation_repo import RecommendationRepository
from src.services.history_service import HistoryService
from src.storage import AnalysisHistory, DatabaseManager


def build_recommendation(code: str, updated_at: datetime) -> StockRecommendation:
    return StockRecommendation(
        code=code,
        name=f"{code}-Name",
        region=MarketRegion.CN,
        sector="Sector",
        current_price=100.0,
        composite_score=CompositeScore(
            total_score=82.0,
            priority=RecommendationPriority.BUY_NOW,
            dimension_scores=[
                DimensionScore(
                    dimension="technical",
                    score=80.0,
                    weight=0.3,
                    details={"note": "seed"},
                )
            ],
            ai_refined=True,
            ai_summary="summary",
        ),
        ideal_buy_price=98.0,
        stop_loss=92.0,
        take_profit=110.0,
        updated_at=updated_at,
    )


class TestRecommendationLinkFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(
            self.temp_dir.name, "recommendation_link_fallback.db"
        )
        os.environ["DATABASE_PATH"] = self.db_path
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.history_service = HistoryService(self.db)
        self.recommendation_repo = RecommendationRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self.temp_dir.cleanup()

    def _save_analysis_history(self, query_id: str, code: str = "600519") -> int:
        result = AnalysisResult(
            code=code,
            name=f"{code}-Stock",
            sentiment_score=75,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="summary",
        )
        saved = self.db.save_analysis_history(
            result=result,
            query_id=query_id,
            report_type="simple",
            news_content="news",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertEqual(saved, 1)

        with self.db.get_session() as session:
            row = (
                session.query(AnalysisHistory)
                .filter(AnalysisHistory.query_id == query_id)
                .first()
            )
            if row is None:
                self.fail("missing analysis history row")
            return int(cast(int, row.id))

    def _save_recommendation(self, code: str = "600519") -> tuple[datetime, int, str]:
        updated_at = datetime(2026, 3, 13, 9, 0, 0)
        saved_map = self.recommendation_repo.save_batch(
            [build_recommendation(code=code, updated_at=updated_at)]
        )
        ((identity, recommendation_record_id),) = saved_map.items()
        saved_code, recommendation_date = identity
        query_id = self.recommendation_repo.build_history_query_id(
            saved_code,
            recommendation_date,
            recommendation_record_id,
        )
        return updated_at, recommendation_record_id, query_id

    def test_new_format_query_id_prefers_explicit_analysis_link(self) -> None:
        _, recommendation_record_id, recommendation_query_id = (
            self._save_recommendation()
        )
        linked_analysis_id = self._save_analysis_history("linked_query_001")
        self.assertEqual(
            self.recommendation_repo.update_analysis_record_link(
                recommendation_record_id,
                linked_analysis_id,
            ),
            1,
        )

        fallback_analysis_id = self._save_analysis_history(recommendation_query_id)

        detail = self.history_service.resolve_and_get_detail(recommendation_query_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.get("id"), linked_analysis_id)
        self.assertNotEqual(detail.get("id"), fallback_analysis_id)

    def test_legacy_format_query_id_resolves_by_code_and_date_compatibility(
        self,
    ) -> None:
        _, recommendation_record_id, recommendation_query_id = (
            self._save_recommendation()
        )
        linked_analysis_id = self._save_analysis_history("linked_query_legacy_001")
        self.assertEqual(
            self.recommendation_repo.update_analysis_record_link(
                recommendation_record_id,
                linked_analysis_id,
            ),
            1,
        )

        query_parts = recommendation_query_id.split("_")
        legacy_query_id = "_".join(query_parts[:-1])
        fallback_analysis_id = self._save_analysis_history(legacy_query_id)

        detail = self.history_service.resolve_and_get_detail(legacy_query_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.get("id"), linked_analysis_id)
        self.assertNotEqual(detail.get("id"), fallback_analysis_id)

    def test_missing_link_degrades_to_legacy_query_fallback(self) -> None:
        _, recommendation_record_id, recommendation_query_id = (
            self._save_recommendation()
        )
        self.assertEqual(
            self.recommendation_repo.update_analysis_record_link(
                recommendation_record_id,
                999999,
            ),
            1,
        )
        fallback_analysis_id = self._save_analysis_history(recommendation_query_id)

        detail = self.history_service.resolve_and_get_detail(recommendation_query_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        resolved_id = detail.get("id")
        self.assertEqual(
            resolved_id,
            fallback_analysis_id,
            msg=(
                "missing linked analysis should degrade to legacy query fallback "
                f"(resolved_id={resolved_id}, fallback_id={fallback_analysis_id})"
            ),
        )

    def test_null_analysis_link_degrades_to_legacy_query_fallback(self) -> None:
        _, recommendation_record_id, recommendation_query_id = (
            self._save_recommendation()
        )

        recommendation_record = self.recommendation_repo.get_by_id(
            recommendation_record_id
        )
        self.assertIsNotNone(recommendation_record)
        assert recommendation_record is not None
        self.assertIsNone(getattr(recommendation_record, "analysis_record_id", None))

        fallback_analysis_id = self._save_analysis_history(recommendation_query_id)

        detail = self.history_service.resolve_and_get_detail(recommendation_query_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.get("id"), fallback_analysis_id)


if __name__ == "__main__":
    unittest.main()
