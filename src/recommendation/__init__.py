# -*- coding: utf-8 -*-
"""Public exports for the recommendation domain package."""

from typing import TYPE_CHECKING

from src.recommendation.constants import (
    BUY_NOW_MIN_SCORE,
    DEFAULT_SCORING_WEIGHTS,
    DEFAULT_TOP_N_PER_SECTOR,
    POSITION_MIN_SCORE,
    WAIT_PULLBACK_MIN_SCORE,
)
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
    StockRecommendation,
    WatchlistItem,
)

if TYPE_CHECKING:
    from src.recommendation.engine import ScoringEngine, StockScoringData
    from src.recommendation.scheduler import RecommendationScheduler
    from src.services.recommendation_service import RecommendationService

__all__ = [
    "BUY_NOW_MIN_SCORE",
    "POSITION_MIN_SCORE",
    "WAIT_PULLBACK_MIN_SCORE",
    "DEFAULT_TOP_N_PER_SECTOR",
    "DEFAULT_SCORING_WEIGHTS",
    "RecommendationPriority",
    "MarketRegion",
    "DimensionScore",
    "CompositeScore",
    "StockRecommendation",
    "ScoringWeights",
    "WatchlistItem",
    "StockScoringData",
    "ScoringEngine",
    "RecommendationService",
    "RecommendationScheduler",
]


def __getattr__(name: str):
    """Lazily expose runtime-heavy recommendation symbols."""
    if name in {"ScoringEngine", "StockScoringData"}:
        from src.recommendation.engine import ScoringEngine, StockScoringData

        return {
            "ScoringEngine": ScoringEngine,
            "StockScoringData": StockScoringData,
        }[name]

    if name == "RecommendationService":
        from src.services.recommendation_service import RecommendationService

        return RecommendationService

    if name == "RecommendationScheduler":
        from src.recommendation.scheduler import RecommendationScheduler

        return RecommendationScheduler

    raise AttributeError(f"module 'src.recommendation' has no attribute {name!r}")


def __dir__() -> list[str]:
    """Return sorted module exports for introspection."""
    return sorted(__all__)
