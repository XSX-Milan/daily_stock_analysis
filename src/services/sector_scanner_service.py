# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import logging
from typing import Any

from data_provider.base import DataFetcherManager
from src.data.stock_mapping import STOCK_NAME_MAP

logger = logging.getLogger(__name__)


_OVERSEAS_SECTOR_FALLBACK: dict[str, dict[str, list[str]]] = {
    "HK": {
        "technology": [
            "HK00700",
            "HK03690",
            "HK01810",
            "HK01024",
            "HK00981",
            "HK09988",
            "HK09618",
            "HK09888",
            "HK02015",
            "HK09868",
        ],
        "tech": [
            "HK00700",
            "HK03690",
            "HK01810",
            "HK01024",
            "HK00981",
            "HK09988",
            "HK09618",
            "HK09888",
            "HK02015",
            "HK09868",
        ],
        "\u79d1\u6280": [
            "HK00700",
            "HK03690",
            "HK01810",
            "HK01024",
            "HK00981",
            "HK09988",
            "HK09618",
            "HK09888",
            "HK02015",
            "HK09868",
        ],
    },
    "US": {
        "technology": [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMD",
            "INTC",
            "GOOGL",
            "GOOG",
            "META",
        ],
        "tech": [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMD",
            "INTC",
            "GOOGL",
            "GOOG",
            "META",
        ],
        "communicationservices": ["META", "GOOGL", "GOOG"],
        "\u79d1\u6280": [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMD",
            "INTC",
            "GOOGL",
            "GOOG",
            "META",
        ],
    },
}

_SECTOR_ALIASES: dict[str, set[str]] = {
    "technology": {"technology", "tech", "\u79d1\u6280"},
    "communicationservices": {
        "communicationservices",
        "internetcontent&information",
        "\u901a\u4fe1\u670d\u52a1",
        "\u901a\u8baf\u670d\u52a1",
    },
}


class SectorScannerService:
    def __init__(
        self, data_fetcher: DataFetcherManager, top_n: int = 10, max_universe: int = 200
    ):
        self.data_fetcher = data_fetcher
        self.top_n = max(1, top_n)
        self.max_universe = max(1, max_universe)
        self._last_scan: list[tuple[str, list[str]]] = []

    def scan_sectors(self) -> list[tuple[str, list[str]]]:
        top_sectors, _ = self.data_fetcher.get_sector_rankings(self.top_n)
        if not top_sectors:
            self._last_scan = []
            return []

        scanned: list[tuple[str, list[str]]] = []
        total_codes = 0

        for sector_item in top_sectors:
            sector_name = self._extract_sector_name(sector_item)
            if not sector_name:
                continue

            sector_codes = self.get_sector_stocks(sector_name, limit=self.top_n)
            if not sector_codes:
                continue

            remain = self.max_universe - total_codes
            if remain <= 0:
                break

            bounded_codes = sector_codes[:remain]
            if bounded_codes:
                scanned.append((sector_name, bounded_codes))
                total_codes += len(bounded_codes)

            if total_codes >= self.max_universe:
                break

        self._last_scan = scanned
        return scanned

    def get_sector_stocks(
        self,
        sector: str,
        limit: int = 10,
        market: str = "CN",
    ) -> list[str]:
        target_limit = max(1, limit)

        target_market = str(getattr(market, "value", market) or "CN").strip().upper()
        if target_market == "CN":
            return self._get_cn_sector_stocks(sector, target_limit)
        if target_market in {"HK", "US"}:
            return self._get_overseas_sector_stocks(
                sector=sector,
                limit=target_limit,
                market=target_market,
            )

        logger.warning("Unsupported market=%s for sector scan", target_market)
        return []

    def _get_cn_sector_stocks(self, sector: str, limit: int) -> list[str]:
        target_limit = max(1, limit)

        try:
            ak = importlib.import_module("akshare")
            df = ak.stock_board_industry_cons_em(symbol=sector)
        except Exception as exc:
            logger.warning(
                "Failed to fetch sector constituents for %s: %s", sector, exc
            )
            return []

        if df is None or df.empty or "代码" not in df.columns:
            return []

        codes: list[str] = []
        for raw_code in df["代码"].tolist():
            code = str(raw_code).strip()
            if code.isdigit() and len(code) == 6:
                codes.append(code)

        deduplicated_codes = list(dict.fromkeys(codes))
        return deduplicated_codes[:target_limit]

    def _get_overseas_sector_stocks(
        self,
        sector: str,
        limit: int,
        market: str,
    ) -> list[str]:
        target_limit = max(1, limit)
        normalized_target = self._normalize_sector_key(sector)
        if not normalized_target:
            return []

        market_candidates = self._build_market_candidates(market)
        if not market_candidates:
            return []

        matched_codes: list[str] = []
        provider_error: Exception | None = None

        try:
            yf = importlib.import_module("yfinance")
        except Exception as exc:
            provider_error = exc
            yf = None

        if yf is not None:
            for code in market_candidates:
                yf_symbol = self._to_yfinance_symbol(code, market)
                if not yf_symbol:
                    continue

                try:
                    info = yf.Ticker(yf_symbol).info or {}
                except Exception as exc:
                    if provider_error is None:
                        provider_error = exc
                    continue

                if self._is_sector_match(
                    normalized_target,
                    [info.get("sector"), info.get("industry")],
                ):
                    matched_codes.append(code)
                    if len(matched_codes) >= target_limit:
                        break

        if matched_codes:
            return list(dict.fromkeys(matched_codes))[:target_limit]

        fallback_codes = self._get_overseas_fallback_codes(normalized_target, market)
        if fallback_codes:
            return fallback_codes[:target_limit]

        if provider_error is not None:
            logger.warning(
                "Failed to fetch %s sector constituents for market=%s: %s",
                sector,
                market,
                provider_error,
            )

        return []

    def _build_market_candidates(self, market: str) -> list[str]:
        candidates: list[str] = []
        for raw_code in STOCK_NAME_MAP.keys():
            normalized = self._normalize_market_code(str(raw_code), market)
            if normalized:
                candidates.append(normalized)
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _normalize_market_code(code: str, market: str) -> str | None:
        raw = str(code or "").strip().upper()
        if not raw:
            return None

        if market == "HK":
            digits = ""
            if raw.startswith("HK"):
                digits = raw[2:]
            elif raw.endswith(".HK"):
                digits = raw[:-3]
            elif raw.isdigit() and 1 <= len(raw) <= 5:
                digits = raw

            if not digits.isdigit():
                return None
            return f"HK{digits.zfill(5)}"

        if market == "US":
            if raw.startswith("HK") or raw.endswith(".HK"):
                return None
            if raw.isdigit():
                return None
            return raw

        return None

    @staticmethod
    def _to_yfinance_symbol(code: str, market: str) -> str:
        normalized = str(code or "").strip().upper()
        if market == "US":
            return normalized

        if market == "HK":
            digits = normalized[2:] if normalized.startswith("HK") else normalized
            if not digits.isdigit():
                return ""
            return f"{int(digits):04d}.HK"

        return ""

    @classmethod
    def _is_sector_match(cls, target: str, values: list[Any]) -> bool:
        target_aliases = cls._resolve_sector_aliases(target)
        for value in values:
            normalized = cls._normalize_sector_key(value)
            if not normalized:
                continue
            if normalized in target_aliases:
                return True
            if any(
                alias in normalized or normalized in alias for alias in target_aliases
            ):
                return True
        return False

    @classmethod
    def _get_overseas_fallback_codes(cls, target: str, market: str) -> list[str]:
        aliases = cls._resolve_sector_aliases(target)
        fallback_map = _OVERSEAS_SECTOR_FALLBACK.get(market, {})
        matched: list[str] = []
        for key, codes in fallback_map.items():
            normalized_key = cls._normalize_sector_key(key)
            if not normalized_key:
                continue
            if normalized_key in aliases:
                matched.extend(codes)
        deduplicated = list(dict.fromkeys(matched))
        return [
            code
            for code in deduplicated
            if cls._normalize_market_code(code, market) is not None
        ]

    @classmethod
    def _resolve_sector_aliases(cls, value: str) -> set[str]:
        normalized = cls._normalize_sector_key(value)
        if not normalized:
            return set()

        aliases = {normalized}
        for alias_set in _SECTOR_ALIASES.values():
            if normalized in alias_set:
                aliases.update(alias_set)
        return aliases

    @staticmethod
    def _normalize_sector_key(value: Any) -> str:
        return "".join(str(value or "").strip().casefold().split())

    def get_all_scan_codes(self) -> list[str]:
        if not self._last_scan:
            self.scan_sectors()

        all_codes: list[str] = []
        seen: set[str] = set()
        for _, codes in self._last_scan:
            for code in codes:
                if code not in seen:
                    seen.add(code)
                    all_codes.append(code)

        return all_codes

    @staticmethod
    def _extract_sector_name(sector_item: Any) -> str:
        if isinstance(sector_item, dict):
            return str(
                sector_item.get("name") or sector_item.get("sector") or ""
            ).strip()
        return str(sector_item).strip()
