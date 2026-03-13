# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import delete, desc, select

from src.recommendation.db_models import WatchlistRecord
from src.recommendation.models import MarketRegion, WatchlistItem
from src.storage import DatabaseManager


class WatchlistRepository:
    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def get_watchlist(
        self, region: str | MarketRegion | None = None
    ) -> list[WatchlistItem]:
        with self.db.session_scope() as session:
            query = select(WatchlistRecord)
            if region is not None:
                query = query.where(
                    WatchlistRecord.region == self._normalize_region_value(region)
                )

            rows = (
                session.execute(query.order_by(desc(WatchlistRecord.added_at)))
                .scalars()
                .all()
            )
            return [self._to_domain(row) for row in rows]

    def upsert(self, item: WatchlistItem) -> None:
        code = str(item.code).strip()
        if not code:
            return

        with self.db.session_scope() as session:
            existing = session.execute(
                select(WatchlistRecord).where(WatchlistRecord.code == code)
            ).scalar_one_or_none()

            payload = {
                "code": code,
                "name": str(item.name).strip() or code,
                "region": self._normalize_region_value(item.region),
                "added_at": item.added_at,
            }

            if existing is None:
                session.add(WatchlistRecord(**payload))
                return

            for key, value in payload.items():
                setattr(existing, key, value)

    def upsert_batch(self, items: list[WatchlistItem]) -> None:
        for item in items:
            self.upsert(item)

    def remove(self, code: str) -> int:
        normalized_code = str(code).strip()
        if not normalized_code:
            return 0

        with self.db.session_scope() as session:
            result = session.execute(
                delete(WatchlistRecord).where(WatchlistRecord.code == normalized_code)
            )
            return int(getattr(result, "rowcount", 0) or 0)

    def clear(self) -> int:
        with self.db.session_scope() as session:
            result = session.execute(delete(WatchlistRecord))
            return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    def _to_domain(record: WatchlistRecord) -> WatchlistItem:
        region = WatchlistRepository._region_from_storage(
            cast(str | None, record.region)
        )
        added_at = cast(datetime | None, record.added_at) or datetime.utcnow()
        return WatchlistItem(
            code=str(cast(str, record.code)),
            name=str(cast(str, record.name)),
            region=region,
            added_at=added_at,
        )

    @staticmethod
    def _normalize_region_value(region: str | MarketRegion) -> str:
        if isinstance(region, MarketRegion):
            return region.value

        raw_region = str(region).strip()
        if raw_region in MarketRegion.__members__:
            return MarketRegion[raw_region].value

        try:
            return MarketRegion(raw_region).value
        except ValueError:
            return MarketRegion.CN.value

    @staticmethod
    def _region_from_storage(region: str | None) -> MarketRegion:
        normalized = str(region or "").strip()
        if normalized in MarketRegion.__members__:
            return MarketRegion[normalized]

        try:
            return MarketRegion(normalized)
        except ValueError:
            return MarketRegion.CN
