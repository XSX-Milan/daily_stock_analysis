# -*- coding: utf-8 -*-
"""Recommendation API endpoints and response mapping helpers."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.recommendation import (
    PrioritySummaryResponse,
    RecommendationListResponse,
    RecommendationResponse,
    RefreshRequest,
    ScoringWeightsRequest,
    ScoringWeightsResponse,
    WatchlistAddRequest,
    WatchlistItemResponse,
)
from src.recommendation.models import (
    RecommendationPriority,
    ScoringWeights,
    StockRecommendation,
)
from src.services.recommendation_service import RecommendationService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_recommendation_service() -> RecommendationService:
    """Create a recommendation service dependency instance."""
    return RecommendationService()


def _region_to_code(value: object) -> str:
    resolved = getattr(value, "value", value)
    return str(resolved or "")


def _normalize_refresh_scope(request: RefreshRequest) -> tuple[str, str]:
    try:
        return request.require_refresh_scope()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_error", "message": str(exc)},
        )


def _to_recommendation_response(item: StockRecommendation) -> RecommendationResponse:
    """Convert one domain recommendation object into API response schema."""
    composite_score = getattr(item, "composite_score", None)
    dimension_scores = getattr(composite_score, "dimension_scores", []) or []
    scores: dict[str, float] = {}
    for score in dimension_scores:
        dimension = str(getattr(score, "dimension", "")).strip()
        if not dimension:
            continue
        scores[dimension] = float(getattr(score, "score", 0.0) or 0.0)

    raw_priority = getattr(composite_score, "priority", RecommendationPriority.NO_ENTRY)
    if isinstance(raw_priority, RecommendationPriority):
        priority = raw_priority.name
    else:
        priority = str(raw_priority)
        try:
            priority = RecommendationPriority[priority].name
        except Exception:
            try:
                priority = RecommendationPriority(priority).name
            except Exception:
                pass

    region = getattr(item, "region", None)
    region_code = _region_to_code(region)

    total_score = float(getattr(composite_score, "total_score", 0.0) or 0.0)
    ai_refined = bool(getattr(composite_score, "ai_refined", False))
    ai_summary = getattr(composite_score, "ai_summary", None)

    current_price = getattr(item, "current_price", None)
    suggested_buy = getattr(item, "ideal_buy_price", None)
    stop_loss = getattr(item, "stop_loss", None)
    take_profit = getattr(item, "take_profit", None)

    return RecommendationResponse(
        stock_code=item.code,
        code=item.code,
        name=item.name,
        stock_name=item.name,
        market=str(region_code),
        region=str(region_code),
        sector=item.sector,
        scores=scores,
        composite_score=total_score,
        priority=priority,
        suggested_buy=suggested_buy,
        ideal_buy_price=suggested_buy,
        current_price=float(current_price) if current_price is not None else None,
        stop_loss=stop_loss,
        take_profit=take_profit,
        ai_refined=ai_refined,
        ai_summary=str(ai_summary) if ai_summary is not None else None,
        updated_at=item.updated_at,
    )


@router.post(
    "/refresh",
    response_model=RecommendationListResponse,
    responses={
        200: {"description": "Recommendations refreshed"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Refresh recommendations",
)
def refresh_recommendations(
    request: RefreshRequest,
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationListResponse:
    """Refresh recommendations for the requested stock set."""
    try:
        market, sector = _normalize_refresh_scope(request)
        if request.stock_codes:
            items = service.refresh_stocks(
                request.stock_codes,
                force=request.force,
                market=market,
                sector=sector,
            )
        else:
            items = service.refresh_all(
                force=request.force, market=market, sector=sector
            )
        return RecommendationListResponse(
            items=[_to_recommendation_response(item) for item in items],
            total=len(items),
            filters={
                "stock_codes": request.stock_codes,
                "force": request.force,
                "market": market,
                "sector": sector,
            },
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_error", "message": str(exc)},
        )
    except Exception as exc:
        logger.error("Failed to refresh recommendations: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to refresh recommendations: {str(exc)}",
            },
        )


@router.post(
    "/refresh/{stock_code}",
    response_model=RecommendationResponse,
    responses={
        200: {"description": "Stock recommendation refreshed"},
        404: {"description": "Recommendation not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Refresh one stock recommendation",
)
def refresh_single_recommendation(
    stock_code: str,
    force: bool = Query(False, description="Force refresh switch"),
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationResponse:
    """Refresh and return recommendation data for a single stock."""
    try:
        items = service.refresh_stocks([stock_code], force=force)
        if not items:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"No recommendation generated for {stock_code}",
                },
            )
        return _to_recommendation_response(items[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to refresh stock %s: %s", stock_code, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to refresh stock recommendation: {str(exc)}",
            },
        )


@router.get(
    "/list",
    response_model=RecommendationListResponse,
    responses={
        200: {"description": "Recommendation list"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get recommendation list",
)
def get_recommendation_list(
    priority: str | None = Query(None, description="Priority filter"),
    sector: str | None = Query(None, description="Sector filter"),
    market: str | None = Query(None, description="Market filter"),
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationListResponse:
    """Return a filtered recommendation list."""
    try:
        result = service.get_recommendations(
            priority=priority,
            sector=sector,
            region=market,
        )

        if isinstance(result, tuple) and len(result) == 2:
            items, total = result
        else:
            items = list(result) if result is not None else []
            total = len(items)

        return RecommendationListResponse(
            items=[_to_recommendation_response(item) for item in items],
            total=total,
            filters={"priority": priority, "sector": sector, "market": market},
        )
    except Exception as exc:
        logger.error("Failed to query recommendations: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to query recommendations: {str(exc)}",
            },
        )


@router.get(
    "/summary",
    response_model=PrioritySummaryResponse,
    responses={
        200: {"description": "Priority summary"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get recommendation priority summary",
)
def get_recommendation_summary(
    service: RecommendationService = Depends(get_recommendation_service),
) -> PrioritySummaryResponse:
    """Return summary counters for each recommendation priority."""
    try:
        summary = service.get_priority_summary() or {}

        def _read_count(*keys: str) -> int:
            for key in keys:
                if key in summary:
                    return int(summary[key])
            return 0

        return PrioritySummaryResponse(
            buy_now=_read_count("BUY_NOW", RecommendationPriority.BUY_NOW.value),
            position=_read_count("POSITION", RecommendationPriority.POSITION.value),
            wait_pullback=_read_count(
                "WAIT_PULLBACK", RecommendationPriority.WAIT_PULLBACK.value
            ),
            no_entry=_read_count("NO_ENTRY", RecommendationPriority.NO_ENTRY.value),
        )
    except Exception as exc:
        logger.error("Failed to query recommendation summary: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to query recommendation summary: {str(exc)}",
            },
        )


@router.get(
    "/weights",
    response_model=ScoringWeightsResponse,
    responses={
        200: {"description": "Current scoring weights"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get scoring weights",
)
def get_scoring_weights(
    service: RecommendationService = Depends(get_recommendation_service),
) -> ScoringWeightsResponse:
    """Return the active scoring weight configuration."""
    try:
        weights = service.get_scoring_weights()
        return ScoringWeightsResponse(
            technical=weights.technical,
            fundamental=weights.fundamental,
            sentiment=weights.sentiment,
            macro=weights.macro,
            risk=weights.risk,
        )
    except Exception as exc:
        logger.error("Failed to query scoring weights: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to query scoring weights: {str(exc)}",
            },
        )


@router.put(
    "/weights",
    response_model=ScoringWeightsResponse,
    responses={
        200: {"description": "Scoring weights updated"},
        422: {"description": "Validation error", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Update scoring weights",
)
def update_scoring_weights(
    request: ScoringWeightsRequest,
    service: RecommendationService = Depends(get_recommendation_service),
) -> ScoringWeightsResponse:
    """Validate and update recommendation scoring weights."""
    try:
        updated = service.update_scoring_weights(
            ScoringWeights(
                technical=request.technical,
                fundamental=request.fundamental,
                sentiment=request.sentiment,
                macro=request.macro,
                risk=request.risk,
            )
        )
        return ScoringWeightsResponse(
            technical=updated.technical,
            fundamental=updated.fundamental,
            sentiment=updated.sentiment,
            macro=updated.macro,
            risk=updated.risk,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error", "message": str(exc)},
        )
    except Exception as exc:
        logger.error("Failed to update scoring weights: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to update scoring weights: {str(exc)}",
            },
        )


@router.get(
    "/watchlist",
    response_model=list[WatchlistItemResponse],
    responses={
        200: {"description": "Watchlist items"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get watchlist",
)
def get_watchlist(
    market: str | None = Query(None, description="Market filter"),
    service: RecommendationService = Depends(get_recommendation_service),
) -> list[WatchlistItemResponse]:
    """Return watchlist items, optionally filtered by market."""
    try:
        items = service.watchlist_service.get_watchlist(region=market)
        return [
            WatchlistItemResponse(
                code=item.code,
                name=item.name,
                region=_region_to_code(item.region),
                added_at=item.added_at,
            )
            for item in items
        ]
    except Exception as exc:
        logger.error("Failed to query watchlist: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to query watchlist: {str(exc)}",
            },
        )


@router.post(
    "/watchlist",
    response_model=WatchlistItemResponse,
    responses={
        200: {"description": "Watchlist stock added"},
        400: {"description": "Validation error", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Add stock to watchlist",
)
def add_watchlist_stock(
    request: WatchlistAddRequest,
    service: RecommendationService = Depends(get_recommendation_service),
) -> WatchlistItemResponse:
    """Add one stock to watchlist and return the stored item."""
    try:
        item = service.watchlist_service.add_stock(
            code=request.code,
            name=request.name,
            region=request.region,
        )
        return WatchlistItemResponse(
            code=item.code,
            name=item.name,
            region=_region_to_code(item.region),
            added_at=item.added_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_error", "message": str(exc)},
        )
    except Exception as exc:
        logger.error("Failed to add watchlist stock: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to add watchlist stock: {str(exc)}",
            },
        )


@router.delete(
    "/watchlist/{code}",
    responses={
        200: {"description": "Watchlist stock removed"},
        404: {"description": "Stock not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Remove stock from watchlist",
)
def remove_watchlist_stock(
    code: str,
    service: RecommendationService = Depends(get_recommendation_service),
) -> dict[str, str]:
    """Remove one stock from watchlist by code."""
    try:
        removed = service.watchlist_service.remove_stock(code)
        if not removed:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"Stock {code} is not in watchlist",
                },
            )
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to remove watchlist stock: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to remove watchlist stock: {str(exc)}",
            },
        )
