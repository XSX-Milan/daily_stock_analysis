# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import logging
from typing import Any

from data_provider.base import DataFetcherManager

logger = logging.getLogger(__name__)


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

    def get_sector_stocks(self, sector: str, limit: int = 10) -> list[str]:
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
