# -*- coding: utf-8 -*-
"""SQLAlchemy persistence models for recommendation data."""

from datetime import date, datetime
import json
from typing import Any, Dict, Optional, cast

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from src.storage import Base


class RecommendationRecord(Base):
    """Database record for one stock recommendation snapshot."""

    __tablename__ = "recommendation_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    region = Column(String(10), nullable=False, index=True)
    sector = Column(String(100), index=True)
    current_price = Column(Float, nullable=False)
    total_score = Column(Float, nullable=False, index=True)
    priority = Column(String(32), nullable=False, index=True)
    dimension_scores_json = Column(Text, nullable=False)
    ideal_buy_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    ai_refined = Column(Boolean, nullable=False, default=False)
    ai_summary = Column(Text)
    analysis_record_id = Column(Integer, index=True)
    recommendation_date = Column(Date, nullable=False, default=date.today, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "code", "recommendation_date", name="uix_recommendation_code_date"
        ),
        Index("ix_recommendation_priority_score", "priority", "total_score"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize one recommendation ORM record to a plain dictionary."""
        recommendation_date = cast(Optional[date], self.recommendation_date)
        created_at = cast(Optional[datetime], self.created_at)
        updated_at = cast(Optional[datetime], self.updated_at)
        return {
            "code": self.code,
            "name": self.name,
            "region": self.region,
            "sector": self.sector,
            "current_price": self.current_price,
            "total_score": self.total_score,
            "priority": self.priority,
            "dimension_scores_json": self.dimension_scores_json,
            "ideal_buy_price": self.ideal_buy_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "ai_refined": self.ai_refined,
            "ai_summary": self.ai_summary,
            "analysis_record_id": self.analysis_record_id,
            "recommendation_date": recommendation_date.isoformat()
            if recommendation_date
            else None,
            "created_at": created_at.isoformat() if created_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
        }


class WatchlistRecord(Base):
    """Database record for one watchlist stock."""

    __tablename__ = "watchlist_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    region = Column(String(10), nullable=False, index=True)
    added_at = Column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (UniqueConstraint("code", name="uix_watchlist_code"),)


class ScoringConfigRecord(Base):
    """Database record for recommendation-related configuration payloads."""

    __tablename__ = "scoring_config_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), nullable=False)
    value_json = Column(Text, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    __table_args__ = (UniqueConstraint("key", name="uix_scoring_config_key"),)

    def get_value_dict(self) -> Optional[Dict[str, Any]]:
        """Parse the JSON payload into a dictionary."""
        try:
            return json.loads(cast(str, self.value_json))
        except Exception:
            return None


class SectorCacheRecord(Base):
    """Persisted sector cache entry for one stock and sector type."""

    __tablename__ = "sector_cache_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(20), nullable=False, index=True)
    sector_name = Column(String(100), nullable=False, index=True)
    sector_type = Column(String(50), nullable=False, index=True)
    fetched_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "stock_code",
            "sector_name",
            "sector_type",
            name="uix_sector_cache_stock_sector_type",
        ),
    )


class HotSectorSnapshotRecord(Base):
    __tablename__ = "hot_sector_snapshot_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(10), nullable=False, index=True)
    canonical_key = Column(String(100), nullable=False, index=True)
    display_label = Column(String(100), nullable=False)
    aliases_json = Column(Text, nullable=False, default="[]")
    raw_name = Column(String(100), nullable=False)
    source = Column(String(50), nullable=False)
    change_pct = Column(Float)
    stock_count = Column(Integer)
    snapshot_at = Column(DateTime, nullable=False, index=True)
    fetched_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "market",
            "canonical_key",
            name="uix_hot_sector_snapshot_market_canonical_key",
        ),
        Index(
            "ix_hot_sector_snapshot_market_snapshot_at",
            "market",
            "snapshot_at",
        ),
    )

    def get_aliases(self) -> list[str]:
        try:
            payload = json.loads(cast(str, self.aliases_json))
        except Exception:
            return []

        if not isinstance(payload, list):
            return []

        aliases: list[str] = []
        for item in payload:
            value = str(item).strip()
            if value and value not in aliases:
                aliases.append(value)
        return aliases
