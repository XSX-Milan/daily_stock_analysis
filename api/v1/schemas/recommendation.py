# -*- coding: utf-8 -*-
"""Pydantic schemas for recommendation API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field


class RecommendationResponse(BaseModel):
    """Response schema for one stock recommendation item."""

    stock_code: str = Field(..., description="Stock code")
    code: str | None = Field(None, description="Legacy alias for stock code")
    name: str = Field(..., description="Stock name")
    stock_name: str | None = Field(None, description="Legacy alias for stock name")
    market: str = Field(..., description="Market region code")
    region: str | None = Field(None, description="Legacy alias for market region code")
    sector: str | None = Field(None, description="Sector name")
    scores: dict[str, float] = Field(
        default_factory=dict, description="Dimension scores"
    )
    composite_score: float = Field(..., description="Composite score (0-100)")
    priority: str = Field(..., description="Recommendation priority")
    suggested_buy: float | None = Field(None, description="Suggested buy price")
    ideal_buy_price: float | None = Field(
        None, description="Legacy alias for suggested buy price"
    )
    current_price: float | None = Field(None, description="Latest stock price")
    stop_loss: float | None = Field(None, description="Stop loss price")
    take_profit: float | None = Field(None, description="Take profit price")
    ai_refined: bool = Field(False, description="Whether AI refinement adjusted score")
    ai_summary: str | None = Field(None, description="Optional AI refinement summary")
    updated_at: datetime = Field(..., description="Last update timestamp")


class RecommendationListResponse(BaseModel):
    """Response schema for recommendation list queries."""

    items: list[RecommendationResponse] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    filters: dict[str, Any] = Field(default_factory=dict)


class RecommendationHistoryFiltersResponse(BaseModel):
    market: str | None = Field(None, description="Market filter")
    limit: int = Field(..., ge=0, description="Page size")
    offset: int = Field(..., ge=0, description="Offset")


class RecommendationHistoryItemResponse(BaseModel):
    id: int = Field(..., ge=1, description="Recommendation record ID")
    query_id: str | None = Field(None, description="Linked analysis history query ID")
    code: str = Field(..., description="Stock code")
    name: str = Field(..., description="Stock name")
    sector: str | None = Field(None, description="Sector name")
    composite_score: float = Field(..., description="Composite score")
    priority: str = Field(..., description="Recommendation priority")
    recommendation_date: str | None = Field(None, description="Recommendation date")
    updated_at: str | None = Field(None, description="Recommendation update timestamp")
    ai_summary: str | None = Field(
        None, description="Optional AI recommendation summary"
    )
    region: str = Field(..., description="Market region code")
    market: str = Field(..., description="Legacy alias for market region code")


class RecommendationHistoryListResponse(BaseModel):
    items: list[RecommendationHistoryItemResponse] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    filters: RecommendationHistoryFiltersResponse


class RecommendationHistoryDeleteRequest(BaseModel):
    record_ids: list[int] = Field(
        default_factory=list, description="Recommendation record IDs to delete"
    )


class PrioritySummaryResponse(BaseModel):
    """Response schema for recommendation priority counters."""

    buy_now: int = Field(0, ge=0)
    position: int = Field(0, ge=0)
    wait_pullback: int = Field(0, ge=0)
    no_entry: int = Field(0, ge=0)


class HotSectorItemResponse(BaseModel):
    """Response schema for one hot-sector item."""

    name: str = Field(..., description="Sector name")
    change_pct: float | None = Field(None, description="Sector change percentage")
    stock_count: int | None = Field(None, description="Stock count in sector")


class HotSectorListResponse(BaseModel):
    """Response schema for hot-sector list queries."""

    sectors: list[HotSectorItemResponse] = Field(default_factory=list)


class RefreshRequest(BaseModel):
    """Request schema for recommendation refresh endpoints."""

    stock_codes: list[str] | None = Field(
        None,
        validation_alias=AliasChoices("stock_codes", "codes"),
        description="Optional stock code list",
    )
    force: bool = Field(False, description="Force refresh switch")
    market: str | None = Field(
        None,
        validation_alias=AliasChoices("market", "region"),
        description="Required market region code for scoped refresh",
    )
    sector: str | None = Field(
        None,
        validation_alias=AliasChoices("sector", "industry"),
        description="Required sector name for scoped refresh",
    )

    def require_refresh_scope(self) -> tuple[str, str]:
        market = str(self.market or "").strip()
        if not market:
            raise ValueError("market is required before selecting sector")

        sector = str(self.sector or "").strip()
        if not sector:
            raise ValueError("sector is required when market is provided")

        return market, sector


class WatchlistItemResponse(BaseModel):
    """Response schema for one watchlist stock item."""

    code: str = Field(..., description="Stock code")
    name: str = Field(..., description="Stock name")
    region: str = Field(..., description="Market region code")
    added_at: datetime = Field(..., description="Created timestamp")


class WatchlistAddRequest(BaseModel):
    """Request schema for adding one stock to watchlist."""

    code: str = Field(..., min_length=1, description="Stock code")
    name: str = Field(..., min_length=1, description="Stock name")
    region: str | None = Field(
        None,
        validation_alias=AliasChoices("region", "market"),
        description="Optional market region code",
    )
