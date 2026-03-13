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


class FakeRecommendationService:
    def __init__(self) -> None:
        self.watchlist_service = FakeWatchlistService()
        self.weights = ScoringWeights()
        self.last_refresh_all_force = False
        self.last_refresh_stocks_force = False
        self.last_refresh_all_market: str | None = None
        self.last_refresh_all_sector: str | None = None
        self.last_refresh_stocks_market: str | None = None
        self.last_refresh_stocks_sector: str | None = None
        self.recommendations = [
            _build_recommendation("AAPL", 86.0),
            _build_recommendation("600519", 67.0),
        ]

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

        missing_sector = self.client.post(
            "/api/v1/recommendation/refresh", json={"market": "US"}
        )
        self.assertEqual(missing_sector.status_code, 400)
        missing_sector_payload = missing_sector.json()
        missing_sector_error = missing_sector_payload.get(
            "detail", missing_sector_payload
        ).get("error", "")
        self.assertEqual(missing_sector_error, "validation_error")
        missing_sector_message = missing_sector_payload.get(
            "detail", missing_sector_payload
        ).get("message", "")
        self.assertIn("sector is required", missing_sector_message)

        full_response = self.client.post(
            "/api/v1/recommendation/refresh",
            json={"market": "US", "sector": "Tech"},
        )
        self.assertEqual(full_response.status_code, 200)
        full_data = full_response.json()
        self.assertEqual(full_data["total"], 2)
        self.assertEqual(len(full_data["items"]), 2)
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
        self.assertTrue(self.fake_service.last_refresh_stocks_force)

        not_found_response = self.client.post(
            "/api/v1/recommendation/refresh/NONE", json={}
        )
        self.assertEqual(not_found_response.status_code, 404)

    def test_list_and_summary_endpoints(self) -> None:
        list_response = self.client.get(
            "/api/v1/recommendation/list",
            params={"priority": "BUY_NOW", "sector": "Tech", "market": "US"},
        )
        self.assertEqual(list_response.status_code, 200)
        list_data = list_response.json()
        self.assertEqual(list_data["total"], 2)
        self.assertEqual(list_data["filters"]["market"], "US")
        self.assertIn("scores", list_data["items"][0])

        summary_response = self.client.get("/api/v1/recommendation/summary")
        self.assertEqual(summary_response.status_code, 200)
        summary_data = summary_response.json()
        self.assertEqual(summary_data["buy_now"], 1)
        self.assertEqual(summary_data["no_entry"], 4)

        openapi = self.client.get("/openapi.json").json()
        params = openapi["paths"]["/api/v1/recommendation/list"]["get"]["parameters"]
        param_names = {item["name"] for item in params}
        self.assertNotIn("limit", param_names)

    def test_weights_get_put_and_sum_validation(self) -> None:
        get_response = self.client.get("/api/v1/recommendation/weights")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["technical"], 30)

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
        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(put_response.json()["technical"], 35)

        invalid_response = self.client.put(
            "/api/v1/recommendation/weights",
            json={
                "technical": 50,
                "fundamental": 50,
                "sentiment": 50,
                "macro": 50,
                "risk": 50,
            },
        )
        self.assertEqual(invalid_response.status_code, 422)

    def test_watchlist_get_post_delete_endpoints(self) -> None:
        post_response = self.client.post(
            "/api/v1/recommendation/watchlist",
            json={"code": "AAPL", "name": "Apple Inc", "region": "US"},
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(post_response.json()["code"], "AAPL")

        override_response = self.client.post(
            "/api/v1/recommendation/watchlist",
            json={"code": "600519", "name": "Moutai", "region": "US"},
        )
        self.assertEqual(override_response.status_code, 200)
        self.assertEqual(override_response.json()["region"], "US")

        list_response = self.client.get("/api/v1/recommendation/watchlist")
        self.assertEqual(list_response.status_code, 200)
        list_data = list_response.json()
        self.assertEqual(len(list_data), 2)
        region_map = {item["code"]: item["region"] for item in list_data}
        self.assertEqual(region_map["AAPL"], "US")
        self.assertEqual(region_map["600519"], "US")

        delete_response = self.client.delete("/api/v1/recommendation/watchlist/AAPL")
        self.assertEqual(delete_response.status_code, 200)

        delete_missing = self.client.delete("/api/v1/recommendation/watchlist/AAPL")
        self.assertEqual(delete_missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
