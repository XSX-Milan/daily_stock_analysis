# -*- coding: utf-8 -*-
"""Repository layer for recommendation persistence and queries."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, cast

from sqlalchemy import delete, desc, func, select, update

from src.recommendation.db_models import RecommendationRecord, SectorCacheRecord
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    SectorInfo,
    StockRecommendation,
)
from src.storage import DatabaseManager


class RecommendationRepository:
    """Read and write recommendation entities from the SQL storage layer."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def save_recommendation(self, rec: StockRecommendation) -> None:
        """Persist one recommendation by delegating to batch save."""
        self.save_batch([rec])

    def save_batch(self, recs: list[StockRecommendation]) -> None:
        """Upsert a batch of recommendations for their recommendation dates."""
        if not recs:
            return

        with self.db.session_scope() as session:
            for rec in recs:
                record_date = rec.updated_at.date()
                existing = session.execute(
                    select(RecommendationRecord).where(
                        RecommendationRecord.code == rec.code,
                        RecommendationRecord.recommendation_date == record_date,
                    )
                ).scalar_one_or_none()

                payload = self._to_record_payload(rec)
                if existing is None:
                    session.add(RecommendationRecord(**payload))
                else:
                    for key, value in payload.items():
                        setattr(existing, key, value)

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

    def get_list(
        self,
        priority: str | RecommendationPriority | None = None,
        sector: str | None = None,
        region: str | MarketRegion | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[StockRecommendation]:
        """Return recommendations filtered by priority, sector, and region."""
        filters = self._build_filters(priority=priority, sector=sector, region=region)

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
        filters = self._build_filters(priority=None, sector=None, region=market)

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
                region = str(cast(str, record.region))
                items.append(
                    {
                        "code": cast(str, record.code),
                        "name": cast(str, record.name),
                        "sector": cast(str | None, record.sector),
                        "composite_score": float(cast(float, record.total_score)),
                        "priority": cast(str, record.priority),
                        "recommendation_date": recommendation_date.isoformat()
                        if recommendation_date
                        else None,
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
        region: str | MarketRegion | None = None,
    ) -> int:
        """Return the count for recommendation records matching filters."""
        filters = self._build_filters(priority=priority, sector=sector, region=region)

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

    @staticmethod
    def _build_filters(
        priority: str | RecommendationPriority | None,
        sector: str | None,
        region: str | MarketRegion | None,
    ) -> list[Any]:
        filters: list[Any] = []

        if priority is not None:
            filters.append(
                RecommendationRecord.priority
                == RecommendationRepository._normalize_priority_label(priority)
            )

        if sector is not None:
            filters.append(RecommendationRecord.sector == sector)

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
    def _to_record_payload(rec: StockRecommendation) -> dict[str, Any]:
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
            "recommendation_date": rec.updated_at.date(),
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

        return StockRecommendation(
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
