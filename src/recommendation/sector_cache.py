# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from src.recommendation.models import SectorInfo
from src.repositories.recommendation_repo import RecommendationRepository


class SectorCacheService:
    def __init__(
        self,
        recommendation_repo: RecommendationRepository | None = None,
        *,
        sector_type: str = "industry",
        ttl_hours: int = 24,
        sector_fetcher: Callable[[str], Optional[SectorInfo]] | None = None,
    ) -> None:
        self.recommendation_repo = recommendation_repo or RecommendationRepository()
        self.sector_type = str(sector_type).strip() or "industry"
        self.ttl_hours = max(1, int(ttl_hours))
        self.sector_fetcher = sector_fetcher

    def get_sector_info(self, stock_code: str) -> Optional[SectorInfo]:
        normalized_code = str(stock_code).strip()
        if not normalized_code:
            return None

        cache = self.recommendation_repo.get_sector_cache(
            [normalized_code],
            sector_type=self.sector_type,
            ttl_hours=self.ttl_hours,
        )
        return cache.get(normalized_code)

    def save_sector_info(
        self,
        stock_code: str,
        sector_info: SectorInfo,
    ) -> None:
        normalized_code = str(stock_code).strip()
        normalized_sector = str(sector_info.sector_name).strip()
        if not normalized_code or not normalized_sector:
            return

        normalized_type = str(sector_info.sector_type).strip() or self.sector_type
        fetched_at = sector_info.fetched_at or datetime.utcnow()

        self.recommendation_repo.upsert_sector_cache(
            {normalized_code: normalized_sector},
            sector_type=normalized_type,
            fetched_at=fetched_at,
        )

    def get_or_fetch_sector(self, stock_code: str) -> Optional[SectorInfo]:
        normalized_code = str(stock_code).strip()
        if not normalized_code:
            return None

        cached_info = self.get_sector_info(normalized_code)
        if cached_info is not None:
            return cached_info

        if self.sector_fetcher is None:
            return None

        try:
            fetched_info = self.sector_fetcher(normalized_code)
        except Exception:
            return None

        if fetched_info is None:
            return None

        normalized_sector = str(fetched_info.sector_name).strip()
        normalized_type = str(fetched_info.sector_type).strip() or self.sector_type
        if not normalized_sector:
            return None

        fetched_at = datetime.utcnow()
        normalized_info = SectorInfo(
            sector_name=normalized_sector,
            sector_type=normalized_type,
            fetched_at=fetched_at,
        )
        self.save_sector_info(normalized_code, normalized_info)
        return normalized_info
