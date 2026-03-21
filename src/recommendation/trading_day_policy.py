from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from src.core.trading_calendar import MARKET_TIMEZONE
from src.recommendation.market_utils import detect_market_region
from src.recommendation.models import MarketRegion


def derive_recommendation_trading_day(
    *,
    stock_code: str,
    updated_at: datetime,
    region: MarketRegion | str | None = None,
) -> date:
    resolved_region = _normalize_region(stock_code=stock_code, region=region)
    timezone_name = MARKET_TIMEZONE.get(resolved_region.value.lower(), "UTC")

    if updated_at.tzinfo is None:
        utc_time = updated_at.replace(tzinfo=timezone.utc)
    else:
        utc_time = updated_at.astimezone(timezone.utc)

    return utc_time.astimezone(ZoneInfo(timezone_name)).date()


def should_bypass_recommendation_reuse(*, force_refresh: bool) -> bool:
    return bool(force_refresh)


def _normalize_region(
    *,
    stock_code: str,
    region: MarketRegion | str | None,
) -> MarketRegion:
    if isinstance(region, MarketRegion):
        return region

    if region is not None:
        normalized = str(region).strip().upper()
        if normalized in MarketRegion.__members__:
            return MarketRegion[normalized]
        try:
            return MarketRegion(normalized)
        except ValueError:
            pass

    return detect_market_region(stock_code)
