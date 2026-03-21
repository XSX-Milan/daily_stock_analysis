import os
import sqlite3
import tempfile
import unittest

from sqlalchemy.exc import IntegrityError

from src.recommendation.db_models import (
    RecommendationRecord,
    ScoringConfigRecord,
    WatchlistRecord,
)
from src.storage import DatabaseManager


class TestRecommendationDbModels(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "recommendation_test.db")
        self.db_url = f"sqlite:///{self.db_path}"
        DatabaseManager.reset_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self.temp_dir.cleanup()

    def test_tables_created_by_database_manager(self):
        DatabaseManager(self.db_url)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            recommendation_columns = conn.execute(
                "PRAGMA table_info('recommendation_records')"
            ).fetchall()

        table_names = {row[0] for row in rows}
        recommendation_column_names = {row[1] for row in recommendation_columns}
        self.assertIn("recommendation_records", table_names)
        self.assertIn("watchlist_records", table_names)
        self.assertIn("scoring_config_records", table_names)
        self.assertIn("analysis_record_id", recommendation_column_names)

    def test_insert_and_query_records(self):
        db = DatabaseManager(self.db_url)

        with db.session_scope() as session:
            session.add(
                RecommendationRecord(
                    code="600519",
                    name="Kweichow Moutai",
                    region="CN",
                    sector="Liquor",
                    current_price=1688.8,
                    total_score=82.5,
                    priority="BUY_NOW",
                    dimension_scores_json='{"technical": 80}',
                    ideal_buy_price=1650.0,
                    stop_loss=1580.0,
                    take_profit=1780.0,
                    ai_refined=True,
                    ai_summary="Strong trend and improving sentiment",
                    analysis_record_id=123,
                )
            )
            session.add(WatchlistRecord(code="00700", name="Tencent", region="HK"))
            session.add(
                ScoringConfigRecord(key="default", value_json='{"technical": 30}')
            )

        with db.session_scope() as session:
            recommendation = (
                session.query(RecommendationRecord).filter_by(code="600519").one()
            )
            watchlist = session.query(WatchlistRecord).filter_by(code="00700").one()
            config = session.query(ScoringConfigRecord).filter_by(key="default").one()
            recommendation_priority = recommendation.priority
            recommendation_analysis_record_id = recommendation.analysis_record_id
            watchlist_name = watchlist.name
            config_value = config.get_value_dict()

        self.assertEqual(recommendation_priority, "BUY_NOW")
        self.assertEqual(recommendation_analysis_record_id, 123)
        self.assertEqual(watchlist_name, "Tencent")
        self.assertEqual(config_value, {"technical": 30})

    def test_unique_constraint_enforced_for_daily_recommendation(self):
        db = DatabaseManager(self.db_url)

        with db.session_scope() as session:
            session.add(
                RecommendationRecord(
                    code="AAPL",
                    name="Apple",
                    region="US",
                    sector="Technology",
                    current_price=220.1,
                    total_score=66.0,
                    priority="POSITION",
                    dimension_scores_json='{"macro": 70}',
                )
            )

        with self.assertRaises(IntegrityError):
            with db.session_scope() as session:
                session.add(
                    RecommendationRecord(
                        code="AAPL",
                        name="Apple",
                        region="US",
                        sector="Technology",
                        current_price=221.0,
                        total_score=67.0,
                        priority="POSITION",
                        dimension_scores_json='{"macro": 71}',
                    )
                )


if __name__ == "__main__":
    unittest.main()
