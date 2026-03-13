# -*- coding: utf-8 -*-
"""Service layer for recommendation watchlist operations."""

from __future__ import annotations

from datetime import datetime

from src.recommendation.market_utils import detect_market_region
from src.recommendation.models import MarketRegion, WatchlistItem
from src.repositories.watchlist_repo import WatchlistRepository
from src.services.stock_code_utils import normalize_code


class WatchlistService:
    def __init__(self, repo: WatchlistRepository | None = None) -> None:
        self.repo = repo or WatchlistRepository()

    def get_watchlist(
        self, region: str | MarketRegion | None = None
    ) -> list[WatchlistItem]:
        if region is None:
            return self.repo.get_watchlist()
        return self.repo.get_watchlist(region=self._parse_region(region))

    def add_stock(
        self, code: str, name: str, region: str | None = None
    ) -> WatchlistItem:
        normalized_code = normalize_code(code or "")
        if not normalized_code:
            raise ValueError("Invalid stock code")

        resolved_region = self._resolve_region(region, normalized_code)
        item = WatchlistItem(
            code=normalized_code,
            name=str(name or "").strip() or normalized_code,
            region=resolved_region,
            added_at=datetime.utcnow(),
        )
        self.repo.upsert(item)
        return item

    def remove_stock(self, code: str) -> bool:
        normalized_code = normalize_code(code or "")
        if not normalized_code:
            return False
        return self.repo.remove(normalized_code) > 0

    def get_stock_codes(self, region: str | MarketRegion | None = None) -> list[str]:
        return [item.code for item in self.get_watchlist(region=region)]

    @staticmethod
    def _resolve_region(region: str | None, code: str) -> MarketRegion:
        if region is not None and str(region).strip():
            return WatchlistService._parse_region(region)
        return detect_market_region(code)

    @staticmethod
    def _parse_region(region: str | MarketRegion) -> MarketRegion:
        if isinstance(region, MarketRegion):
            return region

        raw = str(region).strip().upper()
        if not raw:
            raise ValueError("Invalid market region")

        if raw in MarketRegion.__members__:
            return MarketRegion[raw]

        try:
            return MarketRegion(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid market region: {region}") from exc
