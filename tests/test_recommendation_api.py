from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

import src.auth as auth
from api.app import create_app
from api.v1.endpoints import recommendation as recommendation_endpoint
from src.config import Config
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
    StockRecommendation,
    WatchlistItem,
)
from src.services.sector_scanner_service import _OVERSEAS_SECTOR_FALLBACK


def _build_recommendation(code: str, score: float) -> StockRecommendation:
    return StockRecommendation(
        code=code,
        name=f"Name-{code}",
        region=MarketRegion.US if code == "AAPL" else MarketRegion.CN,
        sector="Tech",
        current_price=100.0,
        composite_score=CompositeScore(
            total_score=score,
            priority=RecommendationPriority.BUY_NOW
            if score >= 80
            else RecommendationPriority.POSITION,
            dimension_scores=[
                DimensionScore(dimension="technical", score=80.0, weight=0.3),
                DimensionScore(dimension="fundamental", score=70.0, weight=0.25),
            ],
        ),
        ideal_buy_price=98.0,
        stop_loss=93.0,
        take_profit=112.0,
        updated_at=datetime(2026, 3, 13, 10, 0, 0),
    )


class FakeWatchlistService:
    def __init__(self) -> None:
        self.items: list[WatchlistItem] = []

    def get_watchlist(self, region: str | None = None) -> list[WatchlistItem]:
        if region is None:
            return list(self.items)
        region_key = region.strip().upper()
        return [item for item in self.items if item.region.value == region_key]

    def add_stock(
        self, code: str, name: str, region: str | None = None
    ) -> WatchlistItem:
        normalized = code.strip().upper()
        if not normalized:
            raise ValueError("Invalid stock code")

        if region is not None and region.strip():
            region_key = region.strip().upper()
            if region_key in MarketRegion.__members__:
                resolved_region = MarketRegion[region_key]
            else:
                try:
                    resolved_region = MarketRegion(region_key)
                except ValueError as exc:
                    raise ValueError(f"Invalid market region: {region}") from exc
        elif normalized.startswith("HK") or normalized.isdigit():
            resolved_region = MarketRegion.HK
        elif normalized.isalpha():
            resolved_region = MarketRegion.US
        else:
            resolved_region = MarketRegion.CN

        item = WatchlistItem(
            code=normalized,
            name=name.strip() or normalized,
            region=resolved_region,
            added_at=datetime(2026, 3, 13, 10, 1, 0),
        )
        existing_codes = {row.code for row in self.items}
        if item.code not in existing_codes:
            self.items.append(item)
        return item

    def remove_stock(self, code: str) -> bool:
        normalized = code.strip().upper()
        before = len(self.items)
        self.items = [item for item in self.items if item.code != normalized]
        return len(self.items) < before


class FakeSectorRankingFetcher:
    def __init__(self) -> None:
        self.raise_error = False
        self.top_sectors: list[dict[str, object]] = [
            {"name": "半导体", "change_pct": 2.4},
            {"name": "人工智能", "change_pct": 1.7},
            {"name": "证券", "change_pct": 0.8},
        ]

    def get_sector_rankings(self, n: int = 5) -> tuple[list[dict[str, object]], list]:
        if self.raise_error:
            raise RuntimeError("sector rankings failed")
        return list(self.top_sectors)[:n], []


class FakeSectorScannerService:
    def __init__(self) -> None:
        self.raise_error = False
        self.data_fetcher = FakeSectorRankingFetcher()
        self.scan_result: list[tuple[str, list[str]]] = [
            ("半导体", ["688001", "688002", "688003"]),
            ("人工智能", ["300001", "300002"]),
            ("证券", ["600030"]),
            ("煤炭", ["601898", "600188"]),
        ]

    def scan_sectors(self) -> list[tuple[str, list[str]]]:
        if self.raise_error:
            raise RuntimeError("sector scanner failed")
        return list(self.scan_result)


class FakeRecommendationRepo:
    def __init__(self) -> None:
        self.last_history_market: str | None = None
        self.last_history_limit: int | None = None
        self.last_history_offset: int | None = None
        self.last_count_region: str | None = None
        self.history_rows: list[dict[str, object]] = [
            {
                "id": 1,
                "query_id": "rec_600519_20260319_1",
                "analysis_record_id": 101,
                "code": "600519",
                "name": "Name-600519",
                "sector": "Consumer",
                "composite_score": 77.5,
                "priority": "POSITION",
                "recommendation_date": "2026-03-19",
                "updated_at": "2026-03-19T10:00:00",
                "ai_summary": "稳健趋势",
                "region": "CN",
                "market": "CN",
            },
            {
                "id": 2,
                "query_id": "rec_AAPL_20260318_2",
                "analysis_record_id": None,
                "code": "AAPL",
                "name": "Name-AAPL",
                "sector": "Tech",
                "composite_score": 86.0,
                "priority": "BUY_NOW",
                "recommendation_date": "2026-03-18",
                "updated_at": "2026-03-18T10:00:00",
                "ai_summary": "动量延续",
                "region": "US",
                "market": "US",
            },
        ]

    def get_history_list(
        self,
        market: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        self.last_history_market = market
        self.last_history_limit = limit
        self.last_history_offset = offset

        rows = list(self.history_rows)
        if market is not None:
            normalized_market = str(market).strip().upper()
            rows = [
                row
                for row in rows
                if str(row.get("market", "")).strip().upper() == normalized_market
            ]
        return rows[offset : offset + limit]

    def delete_by_stock(self, code: str) -> int:
        normalized_code = str(code).strip()
        if not normalized_code:
            return 0

        before = len(self.history_rows)
        self.history_rows = [
            row
            for row in self.history_rows
            if str(row.get("code", "")) != normalized_code
        ]
        return before - len(self.history_rows)

    def delete_by_ids(self, record_ids: list[int]) -> int:
        normalized_ids = {
            int(record_id) for record_id in record_ids if int(record_id) > 0
        }
        before = len(self.history_rows)
        self.history_rows = [
            row
            for row in self.history_rows
            if int(str(row.get("id", 0) or 0)) not in normalized_ids
        ]
        return before - len(self.history_rows)

    def get_count(
        self,
        priority: str | None = None,
        sector: str | None = None,
        region: str | None = None,
    ) -> int:
        _ = (priority, sector)
        self.last_count_region = region
        rows = list(self.history_rows)
        if region is not None:
            normalized_region = str(region).strip().upper()
            rows = [
                row
                for row in rows
                if str(row.get("market", "")).strip().upper() == normalized_region
            ]
        return len(rows)


class FakeRecommendationService:
    def __init__(self) -> None:
        self._watchlist_service = FakeWatchlistService()
        self._sector_scanner_service = FakeSectorScannerService()
        self._recommendation_repo = FakeRecommendationRepo()
        self.weights = ScoringWeights()
        self.last_refresh_all_force = False
        self.last_refresh_stocks_force = False
        self.last_refresh_all_market: str | None = None
        self.last_refresh_all_sector: str | None = None
        self.last_refresh_stocks_market: str | None = None
        self.last_refresh_stocks_sector: str | None = None
        self.last_history_market: str | None = None
        self.last_history_limit: int | None = None
        self.last_history_offset: int | None = None
        self.last_count_region: str | None = None
        self.last_deleted_record_ids: list[int] | None = None
        self.last_hot_sector_market: str | None = None
        self.last_watchlist_region: str | None = None
        self.last_watchlist_add_payload: tuple[str, str, str | None] | None = None
        self.last_watchlist_remove_code: str | None = None
        self.last_detail_record_id: int | None = None
        self.history_call_count = 0
        self.delete_history_call_count = 0
        self.hot_sector_call_count = 0
        self.watchlist_get_call_count = 0
        self.watchlist_add_call_count = 0
        self.watchlist_remove_call_count = 0
        self.detail_call_count = 0
        self.analysis_record_lookup_count = 0
        self.last_analysis_lookup_code: str | None = None
        self.analysis_record_by_code = {
            "AAPL": 201,
            "600519": None,
        }
        self.recommendations = [
            _build_recommendation("AAPL", 86.0),
            _build_recommendation("600519", 67.0),
        ]

    def get_analysis_record_id_for_recommendation(
        self,
        recommendation: StockRecommendation,
    ) -> int | None:
        self.analysis_record_lookup_count += 1
        code = str(getattr(recommendation, "code", "") or "").strip().upper()
        self.last_analysis_lookup_code = code
        if not code:
            return None
        return self.analysis_record_by_code.get(code)

    @staticmethod
    def _normalize_market_code(value: object) -> str:
        resolved = getattr(value, "value", value)
        return str(resolved or "CN").strip().upper() or "CN"

    @staticmethod
    def _normalize_sector_name(value: object) -> str:
        return "".join(str(value or "").strip().casefold().split())

    @staticmethod
    def _extract_sector_name(item: object) -> str:
        if isinstance(item, dict):
            return str(item.get("name") or item.get("sector") or "").strip()
        return str(item or "").strip()

    @staticmethod
    def _extract_sector_change_pct(item: object) -> float | None:
        if not isinstance(item, dict):
            return None
        raw_change = item.get("change_pct")
        if raw_change is None:
            return None
        try:
            return float(raw_change)
        except (TypeError, ValueError):
            return None

    def refresh_all(
        self,
        force: bool = False,
        market: str | None = None,
        sector: str | None = None,
    ) -> list[StockRecommendation]:
        self.last_refresh_all_force = force
        self.last_refresh_all_market = market
        self.last_refresh_all_sector = sector
        return list(self.recommendations)

    def refresh_stocks(
        self,
        codes: list[str],
        force: bool = False,
        market: str | None = None,
        sector: str | None = None,
    ) -> list[StockRecommendation]:
        self.last_refresh_stocks_force = force
        self.last_refresh_stocks_market = market
        self.last_refresh_stocks_sector = sector
        if not codes:
            return []
        target = codes[0].strip().upper()
        if target == "NONE":
            return []
        return [_build_recommendation(target, 82.0)]

    def get_recommendations(
        self,
        priority: str | None = None,
        sector: str | None = None,
        region: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[StockRecommendation], int]:
        _ = (priority, sector, region, limit, offset)
        return list(self.recommendations), len(self.recommendations)

    def get_priority_summary(self) -> dict[str, int]:
        return {"BUY_NOW": 1, "POSITION": 2, "WAIT_PULLBACK": 3, "NO_ENTRY": 4}

    def get_recommendation_history(
        self,
        market: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        self.history_call_count += 1
        self.last_history_market = market
        self.last_history_limit = limit
        self.last_history_offset = offset
        rows = self._recommendation_repo.get_history_list(
            market=market,
            limit=limit,
            offset=offset,
        )
        total = self._recommendation_repo.get_count(region=market)
        self.last_count_region = market
        return rows, total

    def delete_recommendation_history(self, record_ids: list[int]) -> int:
        self.delete_history_call_count += 1
        self.last_deleted_record_ids = list(record_ids)
        return self._recommendation_repo.delete_by_ids(record_ids)

    def get_recommendation_detail(
        self,
        recommendation_record_id: int,
    ) -> dict[str, object] | None:
        self.detail_call_count += 1
        self.last_detail_record_id = recommendation_record_id
        recommendation = next(
            (
                dict(row)
                for row in self._recommendation_repo.history_rows
                if int(str(row.get("id", 0) or 0)) == recommendation_record_id
            ),
            None,
        )
        if recommendation is None:
            return None

        analysis_record_id = recommendation.get("analysis_record_id")
        query_id = str(recommendation.get("query_id") or "")
        meta_id = analysis_record_id if analysis_record_id is not None else None
        return {
            "recommendation": recommendation,
            "analysis_detail": {
                "meta": {
                    "id": meta_id,
                    "query_id": query_id,
                    "stock_code": recommendation["code"],
                    "stock_name": recommendation["name"],
                    "report_type": "full",
                    "report_language": "zh",
                    "created_at": recommendation.get("updated_at"),
                },
                "summary": {
                    "analysis_summary": f"Detail for {recommendation['code']}",
                    "operation_advice": recommendation.get("priority"),
                    "trend_prediction": "bullish",
                    "sentiment_score": 78,
                    "sentiment_label": "positive",
                },
                "strategy": {
                    "ideal_buy": "98.0",
                    "secondary_buy": "95.0",
                    "stop_loss": "90.0",
                    "take_profit": "110.0",
                },
                "details": {
                    "news_content": "detail payload",
                    "raw_result": {"source": "fake"},
                    "context_snapshot": None,
                },
            },
        }

    def get_hot_sectors(self, market: str | None = "CN") -> list[dict[str, object]]:
        self.hot_sector_call_count += 1
        target_market = self._normalize_market_code(market)
        self.last_hot_sector_market = target_market

        if target_market in {"HK", "US"}:
            fallback = _OVERSEAS_SECTOR_FALLBACK.get(target_market, {})
            return [
                {
                    "name": name,
                    "change_pct": None,
                    "stock_count": len(codes),
                }
                for name, codes in fallback.items()
            ]

        scanned: list[tuple[str, list[str]]] = []
        try:
            scanned = self._sector_scanner_service.scan_sectors() or []
        except Exception:
            scanned = []

        change_pct_by_sector: dict[str, float] = {}
        ranking_sector_names: list[str] = []
        ranking_sector_keys: set[str] = set()
        fetcher = getattr(self._sector_scanner_service, "data_fetcher", None)
        try:
            top_sectors, _ = (
                fetcher.get_sector_rankings(3) if fetcher is not None else ([], [])
            )
            for item in top_sectors or []:
                name = self._extract_sector_name(item)
                if not name:
                    continue

                normalized_name = self._normalize_sector_name(name)
                if not normalized_name:
                    continue

                if normalized_name not in ranking_sector_keys:
                    ranking_sector_names.append(name)
                    ranking_sector_keys.add(normalized_name)

                change_pct = self._extract_sector_change_pct(item)
                if change_pct is not None:
                    change_pct_by_sector[normalized_name] = change_pct
        except Exception:
            pass

        sectors: list[dict[str, object]] = []
        if scanned:
            for sector_name, stock_codes in scanned[:3]:
                name = str(sector_name or "").strip()
                if not name:
                    continue
                stock_count = (
                    len(stock_codes) if isinstance(stock_codes, list) else None
                )
                sectors.append(
                    {
                        "name": name,
                        "stock_count": stock_count,
                        "change_pct": change_pct_by_sector.get(
                            self._normalize_sector_name(name)
                        ),
                    }
                )
        else:
            for name in ranking_sector_names[:3]:
                sectors.append(
                    {
                        "name": name,
                        "stock_count": None,
                        "change_pct": change_pct_by_sector.get(
                            self._normalize_sector_name(name)
                        ),
                    }
                )

        return sectors

    def get_watchlist_items(self, region: str | None = None) -> list[WatchlistItem]:
        self.watchlist_get_call_count += 1
        self.last_watchlist_region = region
        return self._watchlist_service.get_watchlist(region=region)

    def add_watchlist_stock(
        self,
        code: str,
        name: str,
        region: str | None = None,
    ) -> WatchlistItem:
        self.watchlist_add_call_count += 1
        self.last_watchlist_add_payload = (code, name, region)
        return self._watchlist_service.add_stock(code=code, name=name, region=region)

    def remove_watchlist_stock(self, code: str) -> bool:
        self.watchlist_remove_call_count += 1
        self.last_watchlist_remove_code = code
        return self._watchlist_service.remove_stock(code)

    def get_scoring_weights(self) -> ScoringWeights:
        return self.weights

    def update_scoring_weights(self, weights: ScoringWeights) -> ScoringWeights:
        self.weights = weights
        return self.weights


class RecommendationApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,AAPL",
                    "GEMINI_API_KEY=test-key",
                    "ADMIN_AUTH_ENABLED=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        Config.reset_instance()

        auth._auth_enabled = None
        self.auth_patcher = patch.object(
            auth, "_is_auth_enabled_from_env", return_value=False
        )
        self.auth_patcher.start()

        self.fake_service = FakeRecommendationService()
        app = create_app(static_dir=Path(self.temp_dir.name) / "empty-static")
        app.dependency_overrides[recommendation_endpoint.get_recommendation_service] = (
            lambda: self.fake_service
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.auth_patcher.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def test_refresh_full_and_single_endpoints(self) -> None:
        missing_market = self.client.post(
            "/api/v1/recommendation/refresh", json={"sector": "Tech"}
        )
        self.assertEqual(missing_market.status_code, 400)
        missing_market_payload = missing_market.json()
        missing_market_error = missing_market_payload.get(
            "detail", missing_market_payload
        ).get("error", "")
        self.assertEqual(missing_market_error, "validation_error")
        missing_market_message = missing_market_payload.get(
            "detail", missing_market_payload
        ).get("message", "")
        self.assertIn("market is required", missing_market_message)

        market_only = self.client.post(
            "/api/v1/recommendation/refresh", json={"market": "CN"}
        )
        self.assertEqual(market_only.status_code, 200)
        market_only_data = market_only.json()
        self.assertEqual(market_only_data["total"], 2)
        self.assertEqual(market_only_data["items"][0]["analysis_record_id"], 201)
        self.assertIsNone(market_only_data["items"][1]["analysis_record_id"])
        self.assertEqual(self.fake_service.last_refresh_all_market, "CN")
        self.assertIsNone(self.fake_service.last_refresh_all_sector)

        null_sector = self.client.post(
            "/api/v1/recommendation/refresh", json={"market": "US", "sector": None}
        )
        self.assertEqual(null_sector.status_code, 200)
        self.assertEqual(self.fake_service.last_refresh_all_market, "US")
        self.assertIsNone(self.fake_service.last_refresh_all_sector)

        blank_sector = self.client.post(
            "/api/v1/recommendation/refresh", json={"market": "US", "sector": "   "}
        )
        self.assertEqual(blank_sector.status_code, 400)
        blank_sector_payload = blank_sector.json()
        blank_sector_message = blank_sector_payload.get(
            "detail", blank_sector_payload
        ).get("message", "")
        self.assertIn("sector is required", blank_sector_message)

        full_response = self.client.post(
            "/api/v1/recommendation/refresh",
            json={"market": "US", "sector": "Tech"},
        )
        self.assertEqual(full_response.status_code, 200)
        full_data = full_response.json()
        self.assertEqual(full_data["total"], 2)
        self.assertEqual(len(full_data["items"]), 2)
        self.assertEqual(full_data["items"][0]["analysis_record_id"], 201)
        self.assertIsNone(full_data["items"][1]["analysis_record_id"])
        self.assertFalse(self.fake_service.last_refresh_all_force)
        self.assertEqual(self.fake_service.last_refresh_all_market, "US")
        self.assertEqual(self.fake_service.last_refresh_all_sector, "Tech")

        force_response = self.client.post(
            "/api/v1/recommendation/refresh",
            json={
                "stock_codes": ["AAPL"],
                "force": True,
                "market": "US",
                "sector": "Technology",
            },
        )
        self.assertEqual(force_response.status_code, 200)
        force_data = force_response.json()
        self.assertEqual(force_data["items"][0]["analysis_record_id"], 201)
        self.assertTrue(self.fake_service.last_refresh_stocks_force)
        self.assertEqual(self.fake_service.last_refresh_stocks_market, "US")
        self.assertEqual(self.fake_service.last_refresh_stocks_sector, "Technology")

        alias_response = self.client.post(
            "/api/v1/recommendation/refresh",
            json={"region": "US", "industry": "Tech"},
        )
        self.assertEqual(alias_response.status_code, 200)

        single_response = self.client.post(
            "/api/v1/recommendation/refresh/AAPL",
            params={"force": "true"},
            json={},
        )
        self.assertEqual(single_response.status_code, 200)
        single_data = single_response.json()
        self.assertEqual(single_data["stock_code"], "AAPL")
        self.assertEqual(single_data["priority"], "BUY_NOW")
        self.assertEqual(single_data["analysis_record_id"], 201)
        self.assertGreater(self.fake_service.analysis_record_lookup_count, 0)
        self.assertTrue(self.fake_service.last_refresh_stocks_force)

        not_found_response = self.client.post(
            "/api/v1/recommendation/refresh/NONE", json={}
        )
        self.assertEqual(not_found_response.status_code, 404)

    def test_refresh_endpoint_same_day_reuse_identity(self) -> None:
        def _analysis_id_by_refresh_mode(
            recommendation: StockRecommendation,
        ) -> int | None:
            code = str(getattr(recommendation, "code", "") or "").strip().upper()
            if code != "AAPL":
                return self.fake_service.analysis_record_by_code.get(code)
            return 601 if self.fake_service.last_refresh_stocks_force else 501

        with patch.object(
            self.fake_service,
            "get_analysis_record_id_for_recommendation",
            side_effect=_analysis_id_by_refresh_mode,
        ):
            first_response = self.client.post(
                "/api/v1/recommendation/refresh",
                json={
                    "stock_codes": ["AAPL"],
                    "market": "US",
                    "sector": "Technology",
                },
            )
            second_response = self.client.post(
                "/api/v1/recommendation/refresh",
                json={
                    "stock_codes": ["AAPL"],
                    "market": "US",
                    "sector": "Technology",
                },
            )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        first_id = first_response.json()["items"][0]["analysis_record_id"]
        second_id = second_response.json()["items"][0]["analysis_record_id"]
        self.assertEqual(
            first_id,
            second_id,
            msg=(
                "same-day non-force refresh should reuse analysis_record_id "
                f"(first={first_id}, second={second_id})"
            ),
        )
        self.assertEqual(first_id, 501)
        self.assertFalse(self.fake_service.last_refresh_stocks_force)

    def test_refresh_endpoint_force_refresh_identity(self) -> None:
        def _analysis_id_by_refresh_mode(
            recommendation: StockRecommendation,
        ) -> int | None:
            code = str(getattr(recommendation, "code", "") or "").strip().upper()
            if code != "AAPL":
                return self.fake_service.analysis_record_by_code.get(code)
            return 601 if self.fake_service.last_refresh_stocks_force else 501

        with patch.object(
            self.fake_service,
            "get_analysis_record_id_for_recommendation",
            side_effect=_analysis_id_by_refresh_mode,
        ):
            non_force_response = self.client.post(
                "/api/v1/recommendation/refresh",
                json={
                    "stock_codes": ["AAPL"],
                    "market": "US",
                    "sector": "Technology",
                },
            )
            force_response = self.client.post(
                "/api/v1/recommendation/refresh",
                json={
                    "stock_codes": ["AAPL"],
                    "force": True,
                    "market": "US",
                    "sector": "Technology",
                },
            )

        self.assertEqual(non_force_response.status_code, 200)
        self.assertEqual(force_response.status_code, 200)
        non_force_id = non_force_response.json()["items"][0]["analysis_record_id"]
        force_id = force_response.json()["items"][0]["analysis_record_id"]
        self.assertNotEqual(
            non_force_id,
            force_id,
            msg=(
                "force refresh should expose a different analysis_record_id "
                f"than non-force refresh (non_force={non_force_id}, force={force_id})"
            ),
        )
        self.assertEqual(non_force_id, 501)
        self.assertEqual(force_id, 601)
        self.assertTrue(self.fake_service.last_refresh_stocks_force)

    def test_list_and_summary_endpoints(self) -> None:
        self.assertFalse(
            hasattr(self.fake_service.recommendations[0], "analysis_record_id")
        )
        list_response = self.client.get(
            "/api/v1/recommendation/list",
            params={"priority": "BUY_NOW", "sector": "Tech", "market": "US"},
        )
        self.assertEqual(list_response.status_code, 200)
        list_data = list_response.json()
        self.assertEqual(list_data["total"], 2)
        self.assertEqual(list_data["filters"]["market"], "US")
        self.assertIn("scores", list_data["items"][0])
        self.assertEqual(list_data["items"][0]["analysis_record_id"], 201)
        self.assertIsNone(list_data["items"][1]["analysis_record_id"])
        self.assertGreaterEqual(self.fake_service.analysis_record_lookup_count, 2)

        summary_response = self.client.get("/api/v1/recommendation/summary")
        self.assertEqual(summary_response.status_code, 200)
        summary_data = summary_response.json()
        self.assertEqual(summary_data["buy_now"], 1)
        self.assertEqual(summary_data["no_entry"], 4)

        openapi = self.client.get("/openapi.json").json()
        params = openapi["paths"]["/api/v1/recommendation/list"]["get"]["parameters"]
        param_names = {item["name"] for item in params}
        self.assertNotIn("limit", param_names)

    def test_history_get_and_delete_endpoints(self) -> None:
        page_one_response = self.client.get(
            "/api/v1/recommendation/history", params={"limit": 1, "offset": 0}
        )
        self.assertEqual(page_one_response.status_code, 200)
        page_one_payload = page_one_response.json()
        page_one_rows = page_one_payload["items"]
        self.assertEqual(len(page_one_rows), 1)
        self.assertEqual(page_one_rows[0]["code"], "600519")
        self.assertEqual(page_one_rows[0]["query_id"], "rec_600519_20260319_1")
        self.assertEqual(page_one_rows[0]["analysis_record_id"], 101)
        self.assertEqual(page_one_payload["total"], 2)
        self.assertEqual(
            page_one_payload["filters"], {"market": None, "limit": 1, "offset": 0}
        )
        self.assertEqual(self.fake_service.last_history_market, None)
        self.assertEqual(self.fake_service.last_history_limit, 1)
        self.assertEqual(self.fake_service.last_history_offset, 0)
        self.assertEqual(self.fake_service.last_count_region, None)
        self.assertEqual(self.fake_service.history_call_count, 1)

        page_two_response = self.client.get(
            "/api/v1/recommendation/history", params={"limit": 1, "offset": 1}
        )
        self.assertEqual(page_two_response.status_code, 200)
        page_two_payload = page_two_response.json()
        page_two_rows = page_two_payload["items"]
        self.assertEqual(len(page_two_rows), 1)
        self.assertEqual(page_two_rows[0]["code"], "AAPL")
        self.assertIsNone(page_two_rows[0]["analysis_record_id"])
        self.assertEqual(page_two_payload["total"], 2)
        self.assertEqual(
            page_two_payload["filters"], {"market": None, "limit": 1, "offset": 1}
        )
        self.assertNotEqual(page_one_rows[0]["code"], page_two_rows[0]["code"])
        self.assertEqual(page_one_payload["total"], page_two_payload["total"])
        self.assertEqual(self.fake_service.last_history_limit, 1)
        self.assertEqual(self.fake_service.last_history_offset, 1)
        self.assertEqual(self.fake_service.last_count_region, None)
        self.assertEqual(self.fake_service.history_call_count, 2)

        filtered_history_response = self.client.get(
            "/api/v1/recommendation/history",
            params={"market": "CN", "limit": 10, "offset": 0},
        )
        self.assertEqual(filtered_history_response.status_code, 200)
        filtered_payload = filtered_history_response.json()
        filtered_rows = filtered_payload["items"]
        self.assertEqual(len(filtered_rows), 1)
        self.assertEqual(filtered_rows[0]["market"], "CN")
        self.assertEqual(filtered_rows[0]["analysis_record_id"], 101)
        self.assertEqual(filtered_payload["total"], 1)
        self.assertEqual(
            filtered_payload["filters"], {"market": "CN", "limit": 10, "offset": 0}
        )
        self.assertEqual(self.fake_service.last_history_market, "CN")
        self.assertEqual(self.fake_service.last_history_limit, 10)
        self.assertEqual(self.fake_service.last_history_offset, 0)
        self.assertEqual(self.fake_service.last_count_region, "CN")
        self.assertEqual(self.fake_service.history_call_count, 3)

        delete_response = self.client.request(
            "DELETE",
            "/api/v1/recommendation/history",
            json={"record_ids": [1]},
        )
        self.assertEqual(delete_response.status_code, 200)
        delete_payload = delete_response.json()
        self.assertEqual(delete_payload["status"], "ok")
        self.assertEqual(delete_payload["deleted"], 1)
        self.assertEqual(self.fake_service.delete_history_call_count, 1)
        self.assertEqual(self.fake_service.last_deleted_record_ids, [1])

        missing_delete_response = self.client.request(
            "DELETE",
            "/api/v1/recommendation/history",
            json={"record_ids": [999]},
        )
        self.assertEqual(missing_delete_response.status_code, 200)
        self.assertEqual(missing_delete_response.json()["deleted"], 0)
        self.assertEqual(self.fake_service.delete_history_call_count, 2)
        self.assertEqual(self.fake_service.last_deleted_record_ids, [999])

        blank_delete_response = self.client.request(
            "DELETE",
            "/api/v1/recommendation/history",
            json={"record_ids": []},
        )
        self.assertEqual(blank_delete_response.status_code, 200)
        self.assertEqual(blank_delete_response.json()["deleted"], 0)
        self.assertEqual(self.fake_service.delete_history_call_count, 3)
        self.assertEqual(self.fake_service.last_deleted_record_ids, [])

    def test_history_detail_endpoint_returns_linked_payload(self) -> None:
        linked_response = self.client.get("/api/v1/recommendation/detail/1")
        self.assertEqual(linked_response.status_code, 200)
        linked_payload = linked_response.json()
        self.assertEqual(linked_payload["recommendation"]["id"], 1)
        self.assertEqual(
            linked_payload["recommendation"]["analysis_record_id"],
            101,
        )
        self.assertEqual(linked_payload["analysis_detail"]["meta"]["id"], 101)
        self.assertEqual(
            linked_payload["analysis_detail"]["meta"]["query_id"],
            "rec_600519_20260319_1",
        )
        self.assertEqual(self.fake_service.detail_call_count, 1)
        self.assertEqual(self.fake_service.last_detail_record_id, 1)

        legacy_response = self.client.get("/api/v1/recommendation/detail/2")
        self.assertEqual(legacy_response.status_code, 200)
        legacy_payload = legacy_response.json()
        self.assertEqual(legacy_payload["recommendation"]["id"], 2)
        self.assertIsNone(legacy_payload["recommendation"]["analysis_record_id"])
        self.assertIsNone(legacy_payload["analysis_detail"]["meta"]["id"])
        self.assertEqual(
            legacy_payload["analysis_detail"]["meta"]["query_id"],
            "rec_AAPL_20260318_2",
        )
        self.assertEqual(self.fake_service.detail_call_count, 2)
        self.assertEqual(self.fake_service.last_detail_record_id, 2)

        compatibility_response = self.client.get("/api/v1/recommendation/history/1")
        self.assertEqual(compatibility_response.status_code, 200)
        compatibility_payload = compatibility_response.json()
        self.assertEqual(compatibility_payload["recommendation"]["id"], 1)
        self.assertEqual(
            compatibility_payload["recommendation"]["analysis_record_id"],
            101,
        )
        self.assertEqual(self.fake_service.detail_call_count, 3)
        self.assertEqual(self.fake_service.last_detail_record_id, 1)

    def test_history_detail_endpoint_returns_404_when_missing(self) -> None:
        response = self.client.get("/api/v1/recommendation/detail/999")
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        error_payload = payload.get("detail", payload)
        self.assertEqual(error_payload["error"], "not_found")
        self.assertIn("999", error_payload["message"])
        self.assertEqual(self.fake_service.detail_call_count, 1)
        self.assertEqual(self.fake_service.last_detail_record_id, 999)

    def test_hot_sectors_cn_endpoint(self) -> None:
        self.fake_service._sector_scanner_service.scan_result = [
            ("半导体", ["688001", "688002", "688003"]),
            ("人工智能", ["300001", "300002"]),
            ("证券", ["600030"]),
            ("煤炭", ["601898", "600188"]),
        ]
        self.fake_service._sector_scanner_service.data_fetcher.top_sectors = [
            {"name": "半导体", "change_pct": "2.6"},
            {"name": "人工智能", "change_pct": 1.3},
            {"name": "证券"},
        ]

        response = self.client.get(
            "/api/v1/recommendation/hot-sectors", params={"market": "CN"}
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        sectors = payload["sectors"]
        self.assertEqual(len(sectors), 3)
        self.assertEqual(
            [item["name"] for item in sectors], ["半导体", "人工智能", "证券"]
        )
        self.assertEqual([item["stock_count"] for item in sectors], [3, 2, 1])
        self.assertAlmostEqual(sectors[0]["change_pct"], 2.6)
        self.assertAlmostEqual(sectors[1]["change_pct"], 1.3)
        self.assertIsNone(sectors[2]["change_pct"])
        self.assertEqual(self.fake_service.hot_sector_call_count, 1)
        self.assertEqual(self.fake_service.last_hot_sector_market, "CN")

    def test_hot_sectors_overseas_fallback_endpoint(self) -> None:
        for market in ("HK", "US"):
            response = self.client.get(
                "/api/v1/recommendation/hot-sectors", params={"market": market}
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            sectors = payload["sectors"]

            expected = _OVERSEAS_SECTOR_FALLBACK[market]
            expected_names = list(expected.keys())
            self.assertEqual([item["name"] for item in sectors], expected_names)
            self.assertEqual(
                [item["stock_count"] for item in sectors],
                [len(expected[name]) for name in expected_names],
            )
            self.assertTrue(all(item["change_pct"] is None for item in sectors))
            self.assertEqual(self.fake_service.last_hot_sector_market, market)
        self.assertEqual(self.fake_service.hot_sector_call_count, 2)

    def test_hot_sectors_cn_scanner_failure_uses_ranking_fallback(self) -> None:
        self.fake_service._sector_scanner_service.raise_error = True
        scanner_failed = self.client.get(
            "/api/v1/recommendation/hot-sectors", params={"market": "CN"}
        )
        self.assertEqual(scanner_failed.status_code, 200)
        sectors = scanner_failed.json()["sectors"]
        self.assertEqual(
            [item["name"] for item in sectors], ["半导体", "人工智能", "证券"]
        )
        self.assertTrue(all(item["stock_count"] is None for item in sectors))
        self.assertEqual(self.fake_service.hot_sector_call_count, 1)

    def test_hot_sectors_cn_fetcher_failure_keeps_scanned_names(self) -> None:
        self.fake_service._sector_scanner_service.raise_error = False
        self.fake_service._sector_scanner_service.scan_result = [
            ("半导体", ["688001", "688002", "688003"]),
            ("人工智能", ["300001", "300002"]),
        ]
        self.fake_service._sector_scanner_service.data_fetcher.raise_error = True

        fetcher_failed = self.client.get(
            "/api/v1/recommendation/hot-sectors", params={"market": "CN"}
        )
        self.assertEqual(fetcher_failed.status_code, 200)
        sectors = fetcher_failed.json()["sectors"]
        self.assertEqual([item["name"] for item in sectors], ["半导体", "人工智能"])
        self.assertEqual([item["stock_count"] for item in sectors], [3, 2])
        self.assertTrue(all(item["change_pct"] is None for item in sectors))
        self.assertEqual(self.fake_service.hot_sector_call_count, 1)

    def test_weights_endpoints_are_not_exposed(self) -> None:
        get_response = self.client.get("/api/v1/recommendation/weights")
        self.assertEqual(get_response.status_code, 404)

        put_response = self.client.put(
            "/api/v1/recommendation/weights",
            json={
                "technical": 35,
                "fundamental": 20,
                "sentiment": 20,
                "macro": 15,
                "risk": 10,
            },
        )
        self.assertEqual(put_response.status_code, 404)

        openapi = self.client.get("/openapi.json").json()
        self.assertNotIn("/api/v1/recommendation/weights", openapi["paths"])

    def test_watchlist_get_post_delete_endpoints(self) -> None:
        post_response = self.client.post(
            "/api/v1/recommendation/watchlist",
            json={"code": "AAPL", "name": "Apple Inc", "region": "US"},
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(post_response.json()["code"], "AAPL")
        self.assertEqual(self.fake_service.watchlist_add_call_count, 1)

        override_response = self.client.post(
            "/api/v1/recommendation/watchlist",
            json={"code": "600519", "name": "Moutai", "region": "US"},
        )
        self.assertEqual(override_response.status_code, 200)
        self.assertEqual(override_response.json()["region"], "US")
        self.assertEqual(self.fake_service.watchlist_add_call_count, 2)

        list_response = self.client.get("/api/v1/recommendation/watchlist")
        self.assertEqual(list_response.status_code, 200)
        list_data = list_response.json()
        self.assertEqual(len(list_data), 2)
        region_map = {item["code"]: item["region"] for item in list_data}
        self.assertEqual(region_map["AAPL"], "US")
        self.assertEqual(region_map["600519"], "US")
        self.assertEqual(self.fake_service.watchlist_get_call_count, 1)

        delete_response = self.client.delete("/api/v1/recommendation/watchlist/AAPL")
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(self.fake_service.watchlist_remove_call_count, 1)

        delete_missing = self.client.delete("/api/v1/recommendation/watchlist/AAPL")
        self.assertEqual(delete_missing.status_code, 404)
        self.assertEqual(self.fake_service.watchlist_remove_call_count, 2)


if __name__ == "__main__":
    unittest.main()
