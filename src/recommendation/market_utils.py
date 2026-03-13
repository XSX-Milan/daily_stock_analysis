# -*- coding: utf-8 -*-
"""Helpers for market region detection and index mapping."""

from __future__ import annotations

from data_provider.hk_stock_utils import is_hk_stock_code
from data_provider.us_index_mapping import is_us_stock_code
from src.recommendation.models import MarketRegion


_REGION_INDICES: dict[MarketRegion, list[str]] = {
    MarketRegion.CN: ["000001", "399001", "399006"],
    MarketRegion.US: ["SPX", "DJI", "IXIC"],
    MarketRegion.HK: ["HSI"],
}

_REGION_CLOSE_HOUR: dict[MarketRegion, int] = {
    MarketRegion.CN: 15,
    MarketRegion.HK: 16,
    MarketRegion.US: 16,
}


def detect_market_region(code: str) -> MarketRegion:
    """Infer market region from stock code format."""
    normalized_code = (code or "").strip()

    if is_us_stock_code(normalized_code):
        return MarketRegion.US

    if is_hk_stock_code(normalized_code):
        return MarketRegion.HK

    return MarketRegion.CN


def get_market_indices(region: MarketRegion) -> list[str]:
    """Return benchmark index codes for one market region."""
    return list(_REGION_INDICES[region])


def get_market_close_hour(region: MarketRegion) -> int:
    """Return the local close hour used for region scheduling."""
    return _REGION_CLOSE_HOUR[region]
