# -*- coding: utf-8 -*-
"""Pydantic schemas for recommendation API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

from api.v1.schemas.history import AnalysisReport


class RecommendationResponse(BaseModel):
    """Response schema for one stock recommendation item."""

    stock_code: str = Field(..., description="Stock code")
    code: str | None = Field(None, description="Legacy alias for stock code")
    name: str = Field(..., description="Stock name")
    stock_name: str | None = Field(None, description="Legacy alias for stock name")
    market: str = Field(..., description="Market region code")
    region: str | None = Field(None, description="Legacy alias for market region code")
    sector: str | None = Field(None, description="Sector name")
    sectors: list[str] = Field(
        default_factory=list,
        description="Normalized sector list for canonical multi-sector compatibility",
    )
    canonical_key: str | None = Field(
        None,
        description="Canonical sector dedupe key",
    )
    display_label: str | None = Field(
        None,
        description="Canonical display label for sector rendering",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Known alias labels for the canonical sector",
    )
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
    analysis_record_id: int | None = Field(
        None, description="Linked analysis history record ID"
    )
    updated_at: datetime = Field(..., description="Last update timestamp")

    def model_post_init(self, __context: Any) -> None:
        if not self.sectors and self.sector:
            self.sectors = [self.sector]
        if not self.display_label and self.sector:
            self.display_label = self.sector
        if not self.canonical_key and self.display_label:
            self.canonical_key = "".join(self.display_label.strip().casefold().split())
        if not self.aliases:
            candidates = [
                *self.sectors,
                self.sector,
                self.display_label,
                self.canonical_key,
            ]
            normalized: list[str] = []
            for raw_value in candidates:
                value = str(raw_value or "").strip()
                if value and value not in normalized:
                    normalized.append(value)
            self.aliases = normalized


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
    analysis_record_id: int | None = Field(
        None, description="Linked analysis history record ID"
    )
    code: str = Field(..., description="Stock code")
    name: str = Field(..., description="Stock name")
    sector: str | None = Field(None, description="Sector name")
    sectors: list[str] = Field(
        default_factory=list,
        description="Normalized sector list for canonical multi-sector compatibility",
    )
    composite_score: float = Field(..., description="Composite score")
    priority: str = Field(..., description="Recommendation priority")
    recommendation_date: str | None = Field(None, description="Recommendation date")
    updated_at: str | None = Field(None, description="Recommendation update timestamp")
    ai_summary: str | None = Field(
        None, description="Optional AI recommendation summary"
    )
    region: str = Field(..., description="Market region code")
    market: str = Field(..., description="Legacy alias for market region code")

    def model_post_init(self, __context: Any) -> None:
        if not self.sectors and self.sector:
            self.sectors = [self.sector]


class RecommendationHistoryListResponse(BaseModel):
    items: list[RecommendationHistoryItemResponse] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    filters: RecommendationHistoryFiltersResponse


class RecommendationDetailResponse(BaseModel):
    recommendation: RecommendationHistoryItemResponse = Field(
        ..., description="Recommendation history metadata"
    )
    analysis_detail: AnalysisReport | None = Field(
        None, description="Linked analysis detail payload"
    )


class RecommendationHistoryDetailResponse(RecommendationDetailResponse):
    pass


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
    canonical_key: str | None = Field(None, description="Canonical dedupe key")
    display_label: str | None = Field(
        None, description="Canonical display label for the sector"
    )
    aliases: list[str] = Field(
        default_factory=list, description="Known alias labels for the canonical sector"
    )
    raw_name: str | None = Field(
        None, description="Raw provider sector label used for tracing"
    )
    source: str | None = Field(None, description="Source provider identifier")
    change_pct: float | None = Field(None, description="Sector change percentage")
    stock_count: int | None = Field(None, description="Stock count in sector")
    snapshot_at: datetime | None = Field(
        None, description="Snapshot freshness timestamp"
    )
    fetched_at: datetime | None = Field(
        None, description="Server snapshot persistence timestamp"
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.display_label and self.name:
            self.display_label = self.name
        if self.display_label and not self.name:
            self.name = self.display_label
        if not self.raw_name and self.name:
            self.raw_name = self.name


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
    market: str = Field(
        ...,
        validation_alias=AliasChoices("market", "region"),
        description="Required market region code for refresh scope",
    )
    sector: str | None = Field(
        None,
        validation_alias=AliasChoices("sector", "industry"),
        description="Required sector name for scoped refresh",
    )
    sectors: list[str] | None = Field(
        None,
        validation_alias=AliasChoices("sectors"),
        description="Canonical multi-sector input for scoped refresh",
    )

    def normalized_sectors(self) -> list[str]:
        normalized: list[str] = []

        for raw_value in self.sectors or []:
            value = str(raw_value).strip()
            if value and value not in normalized:
                normalized.append(value)

        if not normalized and self.sector is not None:
            legacy_sector = str(self.sector).strip()
            if legacy_sector:
                normalized.append(legacy_sector)

        return normalized

    def has_sector_scope(self) -> bool:
        if self.sector is not None:
            return True
        if self.sectors is None:
            return False
        return len(self.sectors) > 0

    def require_refresh_scope(self) -> tuple[str, list[str] | None]:
        market = str(self.market).strip()
        if not market:
            raise ValueError("market is required before selecting sector")

        sectors = self.normalized_sectors()
        if self.has_sector_scope() and not sectors:
            raise ValueError("sector is required when market is provided")

        return market, sectors or None


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
