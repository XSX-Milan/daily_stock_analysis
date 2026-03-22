# -*- coding: utf-8 -*-
"""Repository layer for recommendation persistence and queries."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, cast

from sqlalchemy import delete, desc, func, select, update

from src.recommendation.db_models import (
    HotSectorSnapshotRecord,
    RecommendationRecord,
    SectorCacheRecord,
)
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    SectorInfo,
    StockRecommendation,
)
from src.recommendation.trading_day_policy import derive_recommendation_trading_day
from src.storage import DatabaseManager


class RecommendationRepository:
    """Read and write recommendation entities from the SQL storage layer."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def save_recommendation(self, rec: StockRecommendation) -> None:
        """Persist one recommendation by delegating to batch save."""
        self.save_batch([rec])

    @staticmethod
    def build_history_query_id(
        code: str, recommendation_date: date, record_id: int
    ) -> str:
        return f"rec_{str(code).strip()}_{recommendation_date.strftime('%Y%m%d')}_{int(record_id)}"

    def save_batch(
        self, recs: list[StockRecommendation]
    ) -> dict[tuple[str, date], int]:
        """Upsert a batch of recommendations for their recommendation dates."""
        if not recs:
            return {}

        saved_record_ids: dict[tuple[str, date], int] = {}

        with self.db.session_scope() as session:
            for rec in recs:
                record_date = derive_recommendation_trading_day(
                    stock_code=rec.code,
                    updated_at=rec.updated_at,
                    region=rec.region,
                )
                existing = session.execute(
                    select(RecommendationRecord).where(
                        RecommendationRecord.code == rec.code,
                        RecommendationRecord.recommendation_date == record_date,
                    )
                ).scalar_one_or_none()

                payload = self._to_record_payload(rec, recommendation_date=record_date)
                if existing is None:
                    existing = RecommendationRecord(**payload)
                    session.add(existing)
                else:
                    for key, value in payload.items():
                        setattr(existing, key, value)

                session.flush()
                saved_record_ids[(rec.code, record_date)] = int(cast(int, existing.id))

        return saved_record_ids

    def update_analysis_record_link(
        self,
        recommendation_record_id: int,
        analysis_record_id: int | None,
    ) -> int:
        try:
            normalized_recommendation_record_id = int(recommendation_record_id)
        except (TypeError, ValueError):
            return 0

        if normalized_recommendation_record_id <= 0:
            return 0

        normalized_analysis_record_id: int | None
        if analysis_record_id is None:
            normalized_analysis_record_id = None
        else:
            try:
                normalized_analysis_record_id = int(analysis_record_id)
            except (TypeError, ValueError):
                return 0
            if normalized_analysis_record_id <= 0:
                return 0

        with self.db.session_scope() as session:
            result = session.execute(
                update(RecommendationRecord)
                .where(RecommendationRecord.id == normalized_recommendation_record_id)
                .values(analysis_record_id=normalized_analysis_record_id)
            )
            updated_count = getattr(result, "rowcount", 0) or 0

        return int(updated_count)

    def get_latest(self, code: str) -> StockRecommendation | None:
        """Return the latest recommendation for one stock code."""
        with self.db.session_scope() as session:
            record = session.execute(
                select(RecommendationRecord)
                .where(RecommendationRecord.code == code)
                .order_by(
                    desc(RecommendationRecord.recommendation_date),
                    desc(RecommendationRecord.updated_at),
                )
                .limit(1)
            ).scalar_one_or_none()

            if record is None:
                return None

            return self._to_domain(record)

    def get_by_id(self, recommendation_record_id: int) -> RecommendationRecord | None:
        try:
            normalized_id = int(recommendation_record_id)
        except (TypeError, ValueError):
            return None

        if normalized_id <= 0:
            return None

        with self.db.get_session() as session:
            return session.execute(
                select(RecommendationRecord).where(
                    RecommendationRecord.id == normalized_id
                )
            ).scalar_one_or_none()

    def get_by_code_and_date(
        self,
        code: str,
        recommendation_date: date,
    ) -> RecommendationRecord | None:
        normalized_code = str(code).strip()
        if not normalized_code:
            return None

        with self.db.get_session() as session:
            return session.execute(
                select(RecommendationRecord)
                .where(
                    RecommendationRecord.code == normalized_code,
                    RecommendationRecord.recommendation_date == recommendation_date,
                )
                .order_by(
                    desc(RecommendationRecord.updated_at),
                    desc(RecommendationRecord.id),
                )
                .limit(1)
            ).scalar_one_or_none()

    def get_linked_recommendation_for_date(
        self,
        code: str,
        recommendation_date: date,
    ) -> tuple[StockRecommendation, int] | None:
        normalized_code = str(code).strip()
        if not normalized_code:
            return None

        with self.db.session_scope() as session:
            record = session.execute(
                select(RecommendationRecord)
                .where(
                    RecommendationRecord.code == normalized_code,
                    RecommendationRecord.recommendation_date == recommendation_date,
                    RecommendationRecord.analysis_record_id.is_not(None),
                )
                .order_by(
                    desc(RecommendationRecord.updated_at),
                    desc(RecommendationRecord.id),
                )
                .limit(1)
            ).scalar_one_or_none()

            if record is None:
                return None

            linked_analysis_id = cast(int | None, record.analysis_record_id)
            if linked_analysis_id is None:
                return None

            return self._to_domain(record), int(linked_analysis_id)

    def get_list(
        self,
        priority: str | RecommendationPriority | None = None,
        sector: str | None = None,
        sectors: list[str] | None = None,
        region: str | MarketRegion | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[StockRecommendation]:
        """Return recommendations filtered by priority, sector, and region."""
        filters = self._build_filters(
            priority=priority,
            sector=sector,
            sectors=sectors,
            region=region,
        )

        with self.db.session_scope() as session:
            query = (
                select(RecommendationRecord)
                .where(*filters)
                .order_by(
                    desc(RecommendationRecord.recommendation_date),
                    desc(RecommendationRecord.total_score),
                    desc(RecommendationRecord.updated_at),
                )
                .offset(max(offset, 0))
                .limit(max(limit, 0))
            )
            records = session.execute(query).scalars().all()
            return [self._to_domain(record) for record in records]

    def get_history_list(
        self,
        market: str | MarketRegion | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return recommendation history rows for API list responses."""
        filters = self._build_filters(
            priority=None,
            sector=None,
            sectors=None,
            region=market,
        )

        with self.db.session_scope() as session:
            records = (
                session.execute(
                    select(RecommendationRecord)
                    .where(*filters)
                    .order_by(
                        desc(RecommendationRecord.recommendation_date),
                        desc(RecommendationRecord.updated_at),
                        desc(RecommendationRecord.total_score),
                        desc(RecommendationRecord.id),
                    )
                    .offset(max(offset, 0))
                    .limit(max(limit, 0))
                )
                .scalars()
                .all()
            )
            items: list[dict[str, Any]] = []
            for record in records:
                recommendation_date = cast(date | None, record.recommendation_date)
                updated_at = cast(datetime | None, record.updated_at)
                region = str(cast(str, record.region))
                query_id = None
                if recommendation_date is not None and record.id is not None:
                    query_id = self.build_history_query_id(
                        cast(str, record.code),
                        recommendation_date,
                        int(cast(int, record.id)),
                    )
                items.append(
                    {
                        "id": int(cast(int, record.id)),
                        "query_id": query_id,
                        "analysis_record_id": (
                            int(cast(int, record.analysis_record_id))
                            if record.analysis_record_id is not None
                            else None
                        ),
                        "code": cast(str, record.code),
                        "name": cast(str, record.name),
                        "sector": cast(str | None, record.sector),
                        "composite_score": float(cast(float, record.total_score)),
                        "priority": cast(str, record.priority),
                        "recommendation_date": recommendation_date.isoformat()
                        if recommendation_date
                        else None,
                        "updated_at": updated_at.isoformat() if updated_at else None,
                        "ai_summary": cast(str | None, record.ai_summary),
                        "region": region,
                        "market": region,
                    }
                )

            return items

    def get_count(
        self,
        priority: str | RecommendationPriority | None = None,
        sector: str | None = None,
        sectors: list[str] | None = None,
        region: str | MarketRegion | None = None,
    ) -> int:
        """Return the count for recommendation records matching filters."""
        filters = self._build_filters(
            priority=priority,
            sector=sector,
            sectors=sectors,
            region=region,
        )

        with self.db.session_scope() as session:
            count = session.execute(
                select(func.count(RecommendationRecord.id)).where(*filters)
            ).scalar_one()

        return int(count)

    def delete_old(self, days: int = 30) -> int:
        """Delete recommendation records older than the retention window."""
        keep_days = max(days, 0)
        cutoff_date = date.today() - timedelta(days=keep_days)

        with self.db.session_scope() as session:
            result = session.execute(
                delete(RecommendationRecord).where(
                    RecommendationRecord.recommendation_date < cutoff_date
                )
            )
            deleted_count = getattr(result, "rowcount", 0) or 0

        return int(deleted_count)

    def delete_by_stock(self, code: str) -> int:
        """Delete all recommendation history rows for one stock code."""
        normalized_code = str(code).strip()
        if not normalized_code:
            return 0

        with self.db.session_scope() as session:
            result = session.execute(
                delete(RecommendationRecord).where(
                    RecommendationRecord.code == normalized_code
                )
            )
            deleted_count = getattr(result, "rowcount", 0) or 0

        return int(deleted_count)

    def delete_by_ids(self, record_ids: list[int]) -> int:
        normalized_ids = sorted(
            {int(record_id) for record_id in record_ids if int(record_id) > 0}
        )
        if not normalized_ids:
            return 0

        with self.db.session_scope() as session:
            result = session.execute(
                delete(RecommendationRecord).where(
                    RecommendationRecord.id.in_(normalized_ids)
                )
            )
            deleted_count = getattr(result, "rowcount", 0) or 0

        return int(deleted_count)

    def get_priority_counts(self) -> dict[str, int]:
        """Return latest-day recommendation counts grouped by priority."""
        with self.db.session_scope() as session:
            latest_date = session.execute(
                select(func.max(RecommendationRecord.recommendation_date))
            ).scalar_one_or_none()

            if latest_date is None:
                return {}

            rows = session.execute(
                select(
                    RecommendationRecord.priority, func.count(RecommendationRecord.id)
                )
                .where(RecommendationRecord.recommendation_date == latest_date)
                .group_by(RecommendationRecord.priority)
            ).all()

        return {
            self._normalize_priority_label(priority_value): int(count)
            for priority_value, count in rows
        }

    def get_sector_cache(
        self,
        stock_codes: list[str],
        *,
        sector_type: str = "industry",
        ttl_hours: int = 24,
    ) -> dict[str, SectorInfo]:
        normalized_codes = [
            str(code).strip() for code in stock_codes if str(code).strip()
        ]
        if not normalized_codes:
            return {}

        normalized_type = str(sector_type).strip() or "industry"
        cutoff = datetime.utcnow() - timedelta(hours=max(1, ttl_hours))

        cache: dict[str, SectorInfo] = {}
        with self.db.session_scope() as session:
            rows = (
                session.execute(
                    select(SectorCacheRecord)
                    .where(
                        SectorCacheRecord.stock_code.in_(normalized_codes),
                        SectorCacheRecord.sector_type == normalized_type,
                        SectorCacheRecord.fetched_at >= cutoff,
                    )
                    .order_by(desc(SectorCacheRecord.fetched_at))
                )
                .scalars()
                .all()
            )

            for row in rows:
                stock_code = str(cast(str, row.stock_code)).strip()
                sector_name = str(cast(str, row.sector_name)).strip()
                if not stock_code or not sector_name:
                    continue
                if stock_code in cache:
                    continue
                fetched_at = cast(datetime | None, row.fetched_at) or datetime.utcnow()
                cache[stock_code] = SectorInfo(
                    sector_name=sector_name,
                    sector_type=str(cast(str, row.sector_type)).strip()
                    or normalized_type,
                    fetched_at=fetched_at,
                )

        return cache

    def upsert_sector_cache(
        self,
        sector_by_code: dict[str, str],
        *,
        sector_type: str = "industry",
        fetched_at: datetime | None = None,
    ) -> None:
        normalized_type = str(sector_type).strip() or "industry"
        normalized_payload: dict[str, str] = {}
        for raw_code, raw_sector in sector_by_code.items():
            code = str(raw_code).strip()
            sector_name = str(raw_sector).strip()
            if code and sector_name:
                normalized_payload[code] = sector_name

        if not normalized_payload:
            return

        fetched_time = fetched_at or datetime.utcnow()

        with self.db.session_scope() as session:
            for code, sector_name in normalized_payload.items():
                existing = session.execute(
                    select(SectorCacheRecord).where(
                        SectorCacheRecord.stock_code == code,
                        SectorCacheRecord.sector_name == sector_name,
                        SectorCacheRecord.sector_type == normalized_type,
                    )
                ).scalar_one_or_none()

                if existing is None:
                    session.add(
                        SectorCacheRecord(
                            stock_code=code,
                            sector_name=sector_name,
                            sector_type=normalized_type,
                            fetched_at=fetched_time,
                            updated_at=fetched_time,
                        )
                    )
                else:
                    session.execute(
                        update(SectorCacheRecord)
                        .where(SectorCacheRecord.id == existing.id)
                        .values(fetched_at=fetched_time, updated_at=fetched_time)
                    )

    def upsert_hot_sector_snapshot(
        self,
        market: str,
        sectors: Iterable[dict[str, Any]],
        *,
        snapshot_at: datetime | None = None,
        fetched_at: datetime | None = None,
    ) -> int:
        normalized_market = str(market or "").strip().upper()
        if not normalized_market:
            return 0

        default_snapshot_at = snapshot_at or datetime.utcnow()
        fetched_time = fetched_at or datetime.utcnow()

        normalized_payload: dict[str, dict[str, Any]] = {}
        for item in sectors:
            canonical_key = str(item.get("canonical_key", "")).strip()
            if not canonical_key:
                continue

            raw_aliases = item.get("aliases")
            alias_candidates: list[str]
            if isinstance(raw_aliases, (list, tuple, set)):
                alias_candidates = [str(alias) for alias in raw_aliases]
            elif raw_aliases is None:
                alias_candidates = []
            else:
                alias_candidates = [str(raw_aliases)]

            item_snapshot_at = (
                cast(datetime, item["snapshot_at"])
                if isinstance(item.get("snapshot_at"), datetime)
                else default_snapshot_at
            )

            existing = normalized_payload.get(canonical_key)
            if existing is None:
                normalized_payload[canonical_key] = {
                    "canonical_key": canonical_key,
                    "display_label": str(item.get("display_label", "")).strip()
                    or canonical_key,
                    "aliases": self.normalize_sector_inputs(sectors=alias_candidates),
                    "raw_name": str(item.get("raw_name", "")).strip()
                    or str(item.get("display_label", "")).strip()
                    or canonical_key,
                    "source": str(item.get("source", "")).strip(),
                    "change_pct": item.get("change_pct"),
                    "stock_count": item.get("stock_count"),
                    "snapshot_at": item_snapshot_at,
                }
                continue

            merged_aliases = self.normalize_sector_inputs(
                sectors=[*cast(list[str], existing["aliases"]), *alias_candidates]
            )
            existing["aliases"] = merged_aliases
            existing["display_label"] = str(
                item.get("display_label", "")
            ).strip() or str(existing["display_label"])
            existing["raw_name"] = str(item.get("raw_name", "")).strip() or str(
                existing["raw_name"]
            )
            existing["source"] = str(item.get("source", "")).strip() or str(
                existing["source"]
            )
            if item.get("change_pct") is not None:
                existing["change_pct"] = item.get("change_pct")
            if item.get("stock_count") is not None:
                existing["stock_count"] = item.get("stock_count")
            if item_snapshot_at > cast(datetime, existing["snapshot_at"]):
                existing["snapshot_at"] = item_snapshot_at

        if not normalized_payload:
            return 0

        with self.db.session_scope() as session:
            for canonical_key in sorted(normalized_payload.keys()):
                item = normalized_payload[canonical_key]
                payload = self.build_hot_sector_snapshot_payload(
                    market=normalized_market,
                    canonical_key=str(item["canonical_key"]),
                    display_label=str(item["display_label"]),
                    aliases=cast(list[str], item["aliases"]),
                    raw_name=str(item["raw_name"]),
                    source=str(item["source"]),
                    snapshot_at=cast(datetime, item["snapshot_at"]),
                    change_pct=cast(float | None, item["change_pct"]),
                    stock_count=cast(int | None, item["stock_count"]),
                )
                existing = session.execute(
                    select(HotSectorSnapshotRecord).where(
                        HotSectorSnapshotRecord.market == normalized_market,
                        HotSectorSnapshotRecord.canonical_key == canonical_key,
                    )
                ).scalar_one_or_none()

                if existing is None:
                    session.add(
                        HotSectorSnapshotRecord(
                            **payload,
                            fetched_at=fetched_time,
                            updated_at=fetched_time,
                        )
                    )
                else:
                    session.execute(
                        update(HotSectorSnapshotRecord)
                        .where(HotSectorSnapshotRecord.id == existing.id)
                        .values(
                            **payload,
                            fetched_at=fetched_time,
                            updated_at=fetched_time,
                        )
                    )

        return len(normalized_payload)

    def get_hot_sector_snapshot(
        self,
        market: str,
        *,
        ttl_minutes: int = 30,
        include_stale: bool = True,
    ) -> dict[str, Any] | None:
        normalized_market = str(market or "").strip().upper()
        if not normalized_market:
            return None

        ttl_window = max(1, int(ttl_minutes))
        cutoff = datetime.utcnow() - timedelta(minutes=ttl_window)

        with self.db.session_scope() as session:
            latest_snapshot_at = cast(
                datetime | None,
                session.execute(
                    select(func.max(HotSectorSnapshotRecord.snapshot_at)).where(
                        HotSectorSnapshotRecord.market == normalized_market
                    )
                ).scalar_one_or_none(),
            )
            if latest_snapshot_at is None:
                return None

            is_stale = latest_snapshot_at < cutoff
            if is_stale and not include_stale:
                return None

            rows = (
                session.execute(
                    select(HotSectorSnapshotRecord)
                    .where(
                        HotSectorSnapshotRecord.market == normalized_market,
                        HotSectorSnapshotRecord.snapshot_at == latest_snapshot_at,
                    )
                    .order_by(
                        desc(
                            func.coalesce(HotSectorSnapshotRecord.change_pct, -(10**9))
                        ),
                        desc(func.coalesce(HotSectorSnapshotRecord.stock_count, -1)),
                        HotSectorSnapshotRecord.canonical_key,
                        HotSectorSnapshotRecord.id,
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return None

            latest_fetched_at = max(
                (
                    fetched_at
                    for fetched_at in (
                        cast(datetime | None, row.fetched_at) for row in rows
                    )
                    if fetched_at is not None
                ),
                default=None,
            )
            items = [self._hot_sector_snapshot_to_dict(row) for row in rows]

            return {
                "market": normalized_market,
                "snapshot_at": latest_snapshot_at,
                "fetched_at": latest_fetched_at,
                "is_stale": is_stale,
                "items": items,
            }

    @staticmethod
    def normalize_sector_inputs(
        sector: str | None = None,
        sectors: Iterable[str] | None = None,
    ) -> list[str]:
        normalized: list[str] = []

        for raw_value in sectors or []:
            value = str(raw_value).strip()
            if value and value not in normalized:
                normalized.append(value)

        if not normalized and sector is not None:
            legacy_sector = str(sector).strip()
            if legacy_sector:
                normalized.append(legacy_sector)

        return normalized

    @staticmethod
    def build_hot_sector_snapshot_payload(
        *,
        market: str,
        canonical_key: str,
        display_label: str,
        aliases: Iterable[str],
        raw_name: str,
        source: str,
        snapshot_at: datetime,
        change_pct: float | None = None,
        stock_count: int | None = None,
    ) -> dict[str, Any]:
        normalized_market = str(market or "").strip().upper()
        normalized_aliases = RecommendationRepository.normalize_sector_inputs(
            sectors=aliases
        )
        return {
            "market": normalized_market,
            "canonical_key": str(canonical_key or "").strip(),
            "display_label": str(display_label or "").strip(),
            "aliases_json": json.dumps(normalized_aliases, ensure_ascii=False),
            "raw_name": str(raw_name or "").strip(),
            "source": str(source or "").strip(),
            "snapshot_at": snapshot_at,
            "change_pct": change_pct,
            "stock_count": stock_count,
        }

    @staticmethod
    def _hot_sector_snapshot_to_dict(
        row: HotSectorSnapshotRecord,
    ) -> dict[str, Any]:
        return {
            "market": str(cast(str, row.market)),
            "canonical_key": str(cast(str, row.canonical_key)),
            "display_label": str(cast(str, row.display_label)),
            "aliases": row.get_aliases(),
            "raw_name": str(cast(str, row.raw_name)),
            "source": str(cast(str, row.source)),
            "change_pct": cast(float | None, row.change_pct),
            "stock_count": cast(int | None, row.stock_count),
            "snapshot_at": cast(datetime | None, row.snapshot_at),
            "fetched_at": cast(datetime | None, row.fetched_at),
            "updated_at": cast(datetime | None, row.updated_at),
        }

    @staticmethod
    def _build_filters(
        priority: str | RecommendationPriority | None,
        sector: str | None,
        sectors: Iterable[str] | None,
        region: str | MarketRegion | None,
    ) -> list[Any]:
        filters: list[Any] = []

        if priority is not None:
            filters.append(
                RecommendationRecord.priority
                == RecommendationRepository._normalize_priority_label(priority)
            )

        normalized_sectors = RecommendationRepository.normalize_sector_inputs(
            sector=sector,
            sectors=sectors,
        )
        if normalized_sectors:
            if len(normalized_sectors) == 1:
                filters.append(RecommendationRecord.sector == normalized_sectors[0])
            else:
                filters.append(RecommendationRecord.sector.in_(normalized_sectors))

        if region is not None:
            region_value = (
                region.value if isinstance(region, MarketRegion) else str(region)
            )
            filters.append(RecommendationRecord.region == region_value)

        return filters

    @staticmethod
    def _normalize_priority_label(priority: str | RecommendationPriority) -> str:
        if isinstance(priority, RecommendationPriority):
            return priority.name

        normalized_key = str(priority)
        if normalized_key in RecommendationPriority.__members__:
            return RecommendationPriority[normalized_key].name

        try:
            return RecommendationPriority(normalized_key).name
        except ValueError:
            return normalized_key

    @staticmethod
    def _to_record_payload(
        rec: StockRecommendation,
        recommendation_date: date,
    ) -> dict[str, Any]:
        return {
            "code": rec.code,
            "name": rec.name,
            "region": rec.region.value,
            "sector": rec.sector,
            "current_price": rec.current_price,
            "total_score": rec.composite_score.total_score,
            "priority": RecommendationRepository._normalize_priority_label(
                rec.composite_score.priority
            ),
            "dimension_scores_json": RecommendationRepository._dimension_scores_to_json(
                rec.composite_score.dimension_scores
            ),
            "ideal_buy_price": rec.ideal_buy_price,
            "stop_loss": rec.stop_loss,
            "take_profit": rec.take_profit,
            "ai_refined": rec.composite_score.ai_refined,
            "ai_summary": rec.composite_score.ai_summary,
            "recommendation_date": recommendation_date,
            "updated_at": rec.updated_at,
        }

    @staticmethod
    def _dimension_scores_to_json(scores: Iterable[DimensionScore]) -> str:
        payload = [
            {
                "dimension": item.dimension,
                "score": item.score,
                "weight": item.weight,
                "details": item.details,
            }
            for item in scores
        ]
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _to_domain(record: RecommendationRecord) -> StockRecommendation:
        recommendation_date = (
            cast(date | None, record.recommendation_date) or date.today()
        )
        updated_at = cast(datetime | None, record.updated_at) or datetime.combine(
            recommendation_date, time.min
        )

        composite_score = CompositeScore(
            total_score=float(cast(float, record.total_score)),
            priority=RecommendationRepository._priority_from_storage(
                cast(str, record.priority)
            ),
            dimension_scores=RecommendationRepository._dimension_scores_from_json(
                cast(str | None, record.dimension_scores_json)
            ),
            ai_refined=bool(cast(bool, record.ai_refined)),
            ai_summary=cast(str | None, record.ai_summary),
        )

        recommendation = StockRecommendation(
            code=cast(str, record.code),
            name=cast(str, record.name),
            region=MarketRegion(cast(str, record.region)),
            sector=cast(str | None, record.sector),
            current_price=float(cast(float, record.current_price)),
            composite_score=composite_score,
            ideal_buy_price=cast(float | None, record.ideal_buy_price),
            stop_loss=cast(float | None, record.stop_loss),
            take_profit=cast(float | None, record.take_profit),
            updated_at=updated_at,
        )
        setattr(recommendation, "record_id", cast(int | None, record.id))
        setattr(
            recommendation,
            "analysis_record_id",
            cast(int | None, record.analysis_record_id),
        )
        return recommendation

    @staticmethod
    def _priority_from_storage(value: str) -> RecommendationPriority:
        try:
            return RecommendationPriority[str(value)]
        except Exception:
            return RecommendationPriority(str(value))

    @staticmethod
    def _dimension_scores_from_json(raw_json: str | None) -> list[DimensionScore]:
        if not raw_json:
            return []

        try:
            payload = json.loads(raw_json)
        except Exception:
            return []

        if isinstance(payload, list):
            return [
                DimensionScore(
                    dimension=str(item.get("dimension", "")),
                    score=float(item.get("score", 0.0)),
                    weight=float(item.get("weight", 0.0)),
                    details=item.get("details", {})
                    if isinstance(item.get("details", {}), dict)
                    else {},
                )
                for item in payload
                if isinstance(item, dict)
            ]

        if isinstance(payload, dict):
            scores: list[DimensionScore] = []
            for dimension, value in payload.items():
                if isinstance(value, dict):
                    score = float(value.get("score", 0.0))
                    weight = float(value.get("weight", 0.0))
                    details = value.get("details", {})
                    if not isinstance(details, dict):
                        details = {}
                else:
                    score = float(value)
                    weight = 0.0
                    details = {}
                scores.append(
                    DimensionScore(
                        dimension=str(dimension),
                        score=score,
                        weight=weight,
                        details=details,
                    )
                )
            return scores

        return []
