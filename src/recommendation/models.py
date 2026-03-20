# -*- coding: utf-8 -*-
"""Core domain models for stock recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class RecommendationPriority(str, Enum):
    """Priority levels derived from the composite recommendation score."""

    BUY_NOW = "\u7acb\u5373\u53ef\u4e70"
    POSITION = "\u53ef\u5efa\u4ed3"
    WAIT_PULLBACK = "\u7b49\u5f85\u56de\u8c03"
    NO_ENTRY = "\u6682\u4e0d\u5165\u573a"


class MarketRegion(str, Enum):
    """Supported market regions for recommendation workflows."""

    CN = "CN"
    HK = "HK"
    US = "US"


@dataclass
class DimensionScore:
    """Score payload for one recommendation dimension."""

    dimension: str
    score: float
    weight: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositeScore:
    """Aggregate recommendation score composed of all dimensions."""

    total_score: float
    priority: RecommendationPriority
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    timeout_degraded: bool = False
    risk_fallback_degraded: bool = False
    ai_refined: bool = False
    ai_summary: str | None = None


@dataclass
class StockRecommendation:
    """Final recommendation entity returned to API and persistence layers."""

    code: str
    name: str
    region: MarketRegion
    sector: str | None
    current_price: float
    composite_score: CompositeScore
    ideal_buy_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ScoringWeights:
    """Dimension weight percentages that must sum to 100."""

    technical: int = 30
    fundamental: int = 25
    sentiment: int = 20
    macro: int = 15
    risk: int = 10

    def __post_init__(self) -> None:
        """Validate individual and total weight constraints."""
        values = {
            "technical": self.technical,
            "fundamental": self.fundamental,
            "sentiment": self.sentiment,
            "macro": self.macro,
            "risk": self.risk,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer percentage")
            if value < 0 or value > 100:
                raise ValueError(f"{name} must be within 0-100")
        if sum(values.values()) != 100:
            raise ValueError("Scoring weights must sum to 100")

    def to_fractions(self) -> dict[str, float]:
        """Convert integer percentages into decimal fractions."""
        return {
            "technical": self.technical / 100,
            "fundamental": self.fundamental / 100,
            "sentiment": self.sentiment / 100,
            "macro": self.macro / 100,
            "risk": self.risk / 100,
        }


@dataclass
class WatchlistItem:
    """Watchlist stock tracked for recommendation refresh."""

    code: str
    name: str
    region: MarketRegion
    added_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SectorInfo:
    """Sector metadata used by recommendation sector cache."""

    sector_name: str
    sector_type: str
    fetched_at: datetime
