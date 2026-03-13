# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from src.repositories.recommendation_repo import RecommendationRepository
from src.storage import DatabaseManager


class SectorCacheRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "sector_cache.db")
        self.db_url = f"sqlite:///{self.db_path}"
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(self.db_url)
        self.repo = RecommendationRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self.temp_dir.cleanup()

    def test_upsert_and_read_sector_cache_within_ttl(self) -> None:
        fetched_at = datetime.utcnow() - timedelta(hours=2)
        self.repo.upsert_sector_cache(
            {"600519": "Liquor", "000001": "Bank"},
            sector_type="industry",
            fetched_at=fetched_at,
        )

        cache = self.repo.get_sector_cache(["600519", "000001", "300750"], ttl_hours=24)

        self.assertEqual(set(cache.keys()), {"600519", "000001"})
        self.assertEqual(cache["600519"].sector_name, "Liquor")
        self.assertEqual(cache["600519"].sector_type, "industry")

    def test_get_sector_cache_respects_ttl_expiry(self) -> None:
        self.repo.upsert_sector_cache(
            {"600519": "Liquor"},
            fetched_at=datetime.utcnow() - timedelta(hours=30),
        )

        cache = self.repo.get_sector_cache(["600519"], ttl_hours=24)
        self.assertEqual(cache, {})

    def test_upsert_sector_cache_updates_existing_record_timestamp(self) -> None:
        old_time = datetime.utcnow() - timedelta(hours=4)
        new_time = datetime.utcnow() - timedelta(minutes=5)

        self.repo.upsert_sector_cache({"600519": "Liquor"}, fetched_at=old_time)
        self.repo.upsert_sector_cache({"600519": "Liquor"}, fetched_at=new_time)

        cache = self.repo.get_sector_cache(["600519"], ttl_hours=24)
        self.assertIn("600519", cache)
        self.assertGreaterEqual(
            cache["600519"].fetched_at, new_time - timedelta(seconds=1)
        )

    def test_empty_inputs_are_ignored(self) -> None:
        self.repo.upsert_sector_cache({"": "", "   ": "  "})
        cache = self.repo.get_sector_cache([], ttl_hours=24)
        self.assertEqual(cache, {})


if __name__ == "__main__":
    unittest.main()
