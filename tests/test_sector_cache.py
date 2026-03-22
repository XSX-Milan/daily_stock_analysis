# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import select

from src.recommendation.db_models import HotSectorSnapshotRecord
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

    def test_upsert_hot_sector_snapshot_dedupes_market_canonical_rows(self) -> None:
        snapshot_at = datetime.utcnow() - timedelta(minutes=3)
        upserted = self.repo.upsert_hot_sector_snapshot(
            "us",
            [
                {
                    "canonical_key": "technology",
                    "display_label": "Technology",
                    "aliases": ["tech"],
                    "raw_name": "tech",
                    "source": "provider_a",
                    "change_pct": 3.1,
                    "stock_count": 42,
                    "snapshot_at": snapshot_at,
                },
                {
                    "canonical_key": "technology",
                    "display_label": "Technology",
                    "aliases": ["科技"],
                    "raw_name": "科技",
                    "source": "provider_b",
                    "change_pct": 3.2,
                    "stock_count": 43,
                    "snapshot_at": snapshot_at,
                },
                {
                    "canonical_key": "energy",
                    "display_label": "Energy",
                    "aliases": ["能源"],
                    "raw_name": "能源",
                    "source": "provider_a",
                    "change_pct": 1.8,
                    "stock_count": 21,
                    "snapshot_at": snapshot_at,
                },
            ],
        )

        self.assertEqual(upserted, 2)
        with self.db.session_scope() as session:
            rows = (
                session.execute(
                    select(HotSectorSnapshotRecord)
                    .where(HotSectorSnapshotRecord.market == "US")
                    .order_by(HotSectorSnapshotRecord.canonical_key)
                )
                .scalars()
                .all()
            )
            aliases_by_key = {str(row.canonical_key): row.get_aliases() for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertEqual(aliases_by_key.get("technology"), ["tech", "科技"])

    def test_get_hot_sector_snapshot_returns_fresh_rows_deterministically(self) -> None:
        snapshot_at = datetime.utcnow() - timedelta(minutes=2)
        self.repo.upsert_hot_sector_snapshot(
            "US",
            [
                {
                    "canonical_key": "technology",
                    "display_label": "Technology",
                    "aliases": ["tech", "科技"],
                    "raw_name": "科技",
                    "source": "fallback",
                    "change_pct": 3.2,
                    "stock_count": 20,
                    "snapshot_at": snapshot_at,
                },
                {
                    "canonical_key": "energy",
                    "display_label": "Energy",
                    "aliases": ["能源"],
                    "raw_name": "能源",
                    "source": "provider",
                    "change_pct": 3.2,
                    "stock_count": 10,
                    "snapshot_at": snapshot_at,
                },
                {
                    "canonical_key": "healthcare",
                    "display_label": "Healthcare",
                    "aliases": ["医疗"],
                    "raw_name": "医疗",
                    "source": "provider",
                    "change_pct": 1.1,
                    "stock_count": 80,
                    "snapshot_at": snapshot_at,
                },
            ],
        )

        snapshot = self.repo.get_hot_sector_snapshot(
            "US", ttl_minutes=30, include_stale=False
        )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertFalse(snapshot["is_stale"])
        self.assertEqual(snapshot["market"], "US")
        self.assertEqual(
            [item["canonical_key"] for item in snapshot["items"]],
            ["technology", "energy", "healthcare"],
        )
        first = snapshot["items"][0]
        self.assertEqual(
            set(first.keys()),
            {
                "market",
                "canonical_key",
                "display_label",
                "aliases",
                "raw_name",
                "source",
                "change_pct",
                "stock_count",
                "snapshot_at",
                "fetched_at",
                "updated_at",
            },
        )

    def test_get_hot_sector_snapshot_exposes_stale_when_fresh_missing(self) -> None:
        old_snapshot_at = datetime.utcnow() - timedelta(hours=3)
        self.repo.upsert_hot_sector_snapshot(
            "US",
            [
                {
                    "canonical_key": "technology",
                    "display_label": "Technology",
                    "aliases": ["tech", "科技"],
                    "raw_name": "tech",
                    "source": "fallback",
                    "change_pct": 2.6,
                    "stock_count": 18,
                    "snapshot_at": old_snapshot_at,
                }
            ],
        )

        fresh_only = self.repo.get_hot_sector_snapshot(
            "US", ttl_minutes=30, include_stale=False
        )
        self.assertIsNone(fresh_only)

        stale_snapshot = self.repo.get_hot_sector_snapshot(
            "US", ttl_minutes=30, include_stale=True
        )
        self.assertIsNotNone(stale_snapshot)
        assert stale_snapshot is not None
        self.assertTrue(stale_snapshot["is_stale"])
        self.assertEqual(len(stale_snapshot["items"]), 1)
        self.assertEqual(stale_snapshot["items"][0]["canonical_key"], "technology")


if __name__ == "__main__":
    unittest.main()
