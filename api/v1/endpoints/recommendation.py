# -*- coding: utf-8 -*-
"""Recommendation API endpoints and response mapping helpers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.recommendation import (
    RecommendationDetailResponse,
    RecommendationHistoryDeleteRequest,
    RecommendationHistoryDetailResponse,
    RecommendationHistoryFiltersResponse,
    RecommendationHistoryItemResponse,
    RecommendationHistoryListResponse,
    HotSectorItemResponse,
    HotSectorListResponse,
    PrioritySummaryResponse,
    RecommendationListResponse,
    RecommendationResponse,
    RefreshRequest,
    WatchlistAddRequest,
    WatchlistItemResponse,
)
from src.recommendation.models import (
    RecommendationPriority,
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


def _normalize_refresh_scope(request: RefreshRequest) -> tuple[str, str | None]:
    market = str(request.market or "").strip()
    if not market:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": "market is required before selecting sector",
            },
        )

    if request.sector is None:
        return market, None

    sector = str(request.sector or "").strip()
    if not sector:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": "sector is required when market is provided",
            },
        )
    return market, sector


def _normalize_market_code(market: str | None) -> str:
    return str(market or "CN").strip().upper() or "CN"


def _to_recommendation_response(
    item: StockRecommendation,
    service: RecommendationService,
) -> RecommendationResponse:
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
                priority = RecommendationPriority.NO_ENTRY.name

    region = getattr(item, "region", None)
    region_code = _region_to_code(region)

    total_score = float(getattr(composite_score, "total_score", 0.0) or 0.0)
    ai_refined = bool(getattr(composite_score, "ai_refined", False))
    ai_summary = getattr(composite_score, "ai_summary", None)
    raw_analysis_record_id = getattr(item, "analysis_record_id", None)
    try:
        analysis_record_id = (
            int(raw_analysis_record_id) if raw_analysis_record_id is not None else None
        )
    except (TypeError, ValueError):
        analysis_record_id = None
    if analysis_record_id is None:
        try:
            analysis_record_id = service.get_analysis_record_id_for_recommendation(item)
        except Exception as exc:
            logger.warning(
                "Failed to resolve analysis_record_id for recommendation item; fallback to null | code=%s error=%s",
                getattr(item, "code", None),
                exc,
            )
            analysis_record_id = None

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
        analysis_record_id=analysis_record_id,
        updated_at=item.updated_at,
    )


def _build_recommendation_detail_payload(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommendation": RecommendationHistoryItemResponse(**detail["recommendation"]),
        "analysis_detail": detail.get("analysis_detail"),
    }


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
            items=[_to_recommendation_response(item, service) for item in items],
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
        return _to_recommendation_response(items[0], service)
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
            items=[_to_recommendation_response(item, service) for item in items],
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
    "/history",
    response_model=RecommendationHistoryListResponse,
    responses={
        200: {"description": "Recommendation history list"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get recommendation history list",
)
def get_recommendation_history_list(
    market: str | None = Query(None, description="Market filter"),
    limit: int = Query(50, ge=0, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset"),
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationHistoryListResponse:
    try:
        items, total = service.get_recommendation_history(
            market=market,
            limit=limit,
            offset=offset,
        )
        return RecommendationHistoryListResponse(
            items=[RecommendationHistoryItemResponse(**item) for item in items],
            total=total,
            filters=RecommendationHistoryFiltersResponse(
                market=market,
                limit=limit,
                offset=offset,
            ),
        )
    except Exception as exc:
        logger.error("Failed to query recommendation history: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to query recommendation history: {str(exc)}",
            },
        )


@router.get(
    "/detail/{record_id}",
    response_model=RecommendationDetailResponse,
    responses={
        200: {"description": "Recommendation detail"},
        404: {"description": "Recommendation not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get recommendation detail",
)
def get_recommendation_detail(
    record_id: int,
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationDetailResponse:
    try:
        detail = service.get_recommendation_detail(record_id)
        if detail is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"Recommendation {record_id} not found",
                },
            )

        return RecommendationDetailResponse(
            **_build_recommendation_detail_payload(detail)
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to query recommendation detail for record_id=%s: %s",
            record_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to query recommendation detail: {str(exc)}",
            },
        )


@router.get(
    "/history/{record_id}",
    response_model=RecommendationHistoryDetailResponse,
    responses={
        200: {"description": "Recommendation history detail"},
        404: {
            "description": "Recommendation history not found",
            "model": ErrorResponse,
        },
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get recommendation history detail",
)
def get_recommendation_history_detail(
    record_id: int,
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationHistoryDetailResponse:
    try:
        detail = service.get_recommendation_detail(record_id)
        if detail is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"Recommendation history {record_id} not found",
                },
            )

        return RecommendationHistoryDetailResponse(
            **_build_recommendation_detail_payload(detail)
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to query recommendation history detail for record_id=%s: %s",
            record_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to query recommendation history detail: {str(exc)}",
            },
        )


@router.delete(
    "/history",
    responses={
        200: {"description": "Recommendation history deleted"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Delete recommendation history by record IDs",
)
def delete_recommendation_history(
    request: RecommendationHistoryDeleteRequest = Body(
        default_factory=RecommendationHistoryDeleteRequest
    ),
    service: RecommendationService = Depends(get_recommendation_service),
) -> dict[str, int | str]:
    try:
        deleted = service.delete_recommendation_history(request.record_ids)
        return {"status": "ok", "deleted": deleted}
    except Exception as exc:
        logger.error(
            "Failed to delete recommendation history for record_ids=%s: %s",
            request.record_ids,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to delete recommendation history: {str(exc)}",
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
    "/hot-sectors",
    response_model=HotSectorListResponse,
    responses={200: {"description": "Hot sector list"}},
    summary="Get hot sectors",
)
def get_hot_sectors(
    market: str | None = Query("CN", description="Market region code (CN/HK/US)"),
    service: RecommendationService = Depends(get_recommendation_service),
) -> HotSectorListResponse:
    target_market = _normalize_market_code(market)

    if target_market not in {"CN", "HK", "US"}:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": f"Unsupported market: {target_market}",
            },
        )

    sectors = service.get_hot_sectors(target_market)
    return HotSectorListResponse(
        sectors=[
            HotSectorItemResponse(
                name=str(item.get("name") or ""),
                change_pct=item.get("change_pct"),
                stock_count=item.get("stock_count"),
            )
            for item in sectors
        ]
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
        items = service.get_watchlist_items(region=market)
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
        item = service.add_watchlist_stock(
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
        removed = service.remove_watchlist_stock(code)
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
