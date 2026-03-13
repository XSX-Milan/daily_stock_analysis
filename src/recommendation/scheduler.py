# -*- coding: utf-8 -*-
"""Scheduler for periodic recommendation refresh jobs."""

from __future__ import annotations

import logging
import importlib
import re
import threading
import time
from datetime import datetime
from typing import Any, Protocol

from src.scheduler import GracefulShutdown
from src.services.recommendation_service import RecommendationService

logger = logging.getLogger(__name__)

_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ShutdownAware(Protocol):
    """Protocol for a shared shutdown state provider."""

    @property
    def should_shutdown(self) -> bool:
        raise NotImplementedError


class RecommendationScheduler:
    """Run recommendation refresh tasks on a daily schedule."""

    def __init__(
        self,
        schedule_time: str = "18:00",
        service: RecommendationService | None = None,
        shutdown_handler: ShutdownAware | None = None,
        schedule_module: Any | None = None,
        poll_interval_seconds: float = 30.0,
        refresh_market: str = "",
        refresh_sector: str = "",
    ) -> None:
        self.schedule = schedule_module or self._import_schedule_module()
        self.schedule_time = self._normalize_time(schedule_time)
        self.service = service or RecommendationService()
        self.shutdown_handler = shutdown_handler or GracefulShutdown()
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self.refresh_market = (refresh_market or "").strip()
        self.refresh_sector = (refresh_sector or "").strip()
        self._running = False
        self._thread: threading.Thread | None = None

    def schedule_daily_refresh(self, time: str = "18:00") -> None:
        """Register one daily refresh task at the configured time."""
        self.schedule_time = self._normalize_time(time)
        self.schedule.every().day.at(self.schedule_time).do(self._safe_refresh)
        logger.info(
            "Recommendation daily refresh scheduled at %s (CST assumed)",
            self.schedule_time,
        )

    def start(self, run_immediately: bool = False) -> None:
        """Start the scheduler thread and optionally run once immediately."""
        if self._running:
            return

        if run_immediately:
            self._safe_refresh()

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Recommendation scheduler started")

    def stop(self) -> None:
        """Stop the scheduler loop and wait for the thread to exit."""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Recommendation scheduler stopped")

    def _safe_refresh(self) -> None:
        try:
            market, sector = self._resolve_refresh_scope()
            if not market or not sector:
                logger.warning(
                    "Recommendation refresh skipped: both recommend_refresh_market and recommend_refresh_sector are required"
                )
                return

            logger.info(
                "Recommendation refresh started at %s",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            refreshed = self.service.refresh_all(market=market, sector=sector)
            logger.info(
                "Recommendation refresh completed, %d stocks updated", len(refreshed)
            )
        except Exception as exc:
            logger.exception("Recommendation refresh failed: %s", exc)

    def _resolve_refresh_scope(self) -> tuple[str, str]:
        market = self.refresh_market
        sector = self.refresh_sector
        if market and sector:
            return market, sector

        config = getattr(self.service, "config", None)
        if not market:
            market = str(getattr(config, "recommend_refresh_market", "")).strip()
        if not sector:
            sector = str(getattr(config, "recommend_refresh_sector", "")).strip()
        return market, sector

    def _run_loop(self) -> None:
        while self._running and not self.shutdown_handler.should_shutdown:
            self.schedule.run_pending()
            time.sleep(self.poll_interval_seconds)

    @staticmethod
    def _import_schedule_module() -> Any:
        try:
            return importlib.import_module("schedule")
        except ImportError as exc:
            raise ImportError("Please install schedule: pip install schedule") from exc

    @staticmethod
    def _normalize_time(value: str) -> str:
        candidate = (value or "18:00").strip()
        if not _TIME_PATTERN.match(candidate):
            logger.warning(
                "Invalid recommendation refresh time '%s', fallback to 18:00", value
            )
            return "18:00"
        return candidate
