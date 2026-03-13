from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.recommendation.scheduler import RecommendationScheduler


class _DummyJob:
    def __init__(self, schedule_obj: "_DummySchedule") -> None:
        self.schedule_obj = schedule_obj
        self.scheduled_time: str | None = None

    @property
    def day(self) -> "_DummyJob":
        return self

    def at(self, schedule_time: str) -> "_DummyJob":
        self.scheduled_time = schedule_time
        return self

    def do(self, callback):
        self.schedule_obj.callback = callback
        self.schedule_obj.jobs.append(self)
        return self


class _DummySchedule:
    def __init__(self) -> None:
        self.jobs: list[_DummyJob] = []
        self.callback = None
        self.run_pending_calls = 0

    def every(self) -> _DummyJob:
        return _DummyJob(self)

    def run_pending(self) -> None:
        self.run_pending_calls += 1

    def get_jobs(self) -> list[_DummyJob]:
        return self.jobs


class RecommendationSchedulerTestCase(unittest.TestCase):
    class _ShutdownStub:
        should_shutdown = False

    @staticmethod
    def _shutdown_stub() -> "RecommendationSchedulerTestCase._ShutdownStub":
        return RecommendationSchedulerTestCase._ShutdownStub()

    def test_schedule_daily_refresh_uses_given_time(self) -> None:
        schedule_obj = _DummySchedule()
        service = Mock()
        shutdown = self._shutdown_stub()

        scheduler = RecommendationScheduler(
            schedule_time="18:00",
            service=service,
            shutdown_handler=shutdown,
            schedule_module=schedule_obj,
        )
        scheduler.schedule_daily_refresh(time="19:30")

        self.assertEqual(len(schedule_obj.get_jobs()), 1)
        self.assertEqual(schedule_obj.get_jobs()[0].scheduled_time, "19:30")

    def test_safe_refresh_calls_recommendation_service(self) -> None:
        schedule_obj = _DummySchedule()
        service = Mock()
        service.refresh_all.return_value = ["600519", "AAPL"]
        scheduler = RecommendationScheduler(
            service=service,
            shutdown_handler=self._shutdown_stub(),
            schedule_module=schedule_obj,
            refresh_market="CN",
            refresh_sector="AI",
        )

        scheduler._safe_refresh()

        service.refresh_all.assert_called_once_with(market="CN", sector="AI")

    def test_safe_refresh_uses_service_config_scope_when_ctor_scope_missing(
        self,
    ) -> None:
        schedule_obj = _DummySchedule()
        service = Mock()
        service.config = SimpleNamespace(
            recommend_refresh_market="US",
            recommend_refresh_sector="TECH",
        )
        service.refresh_all.return_value = ["AAPL"]
        scheduler = RecommendationScheduler(
            service=service,
            shutdown_handler=self._shutdown_stub(),
            schedule_module=schedule_obj,
        )

        scheduler._safe_refresh()

        service.refresh_all.assert_called_once_with(market="US", sector="TECH")

    def test_safe_refresh_logs_error_without_retry(self) -> None:
        schedule_obj = _DummySchedule()
        service = Mock()
        service.config = SimpleNamespace(
            recommend_refresh_market="CN",
            recommend_refresh_sector="AI",
        )
        service.refresh_all.side_effect = RuntimeError("boom")
        scheduler = RecommendationScheduler(
            service=service,
            shutdown_handler=self._shutdown_stub(),
            schedule_module=schedule_obj,
        )

        with self.assertLogs("src.recommendation.scheduler", level="ERROR") as log_ctx:
            scheduler._safe_refresh()

        self.assertTrue(
            any("Recommendation refresh failed" in item for item in log_ctx.output)
        )
        service.refresh_all.assert_called_once_with(market="CN", sector="AI")

    def test_safe_refresh_skips_when_scope_not_configured(self) -> None:
        schedule_obj = _DummySchedule()
        service = Mock()
        service.config = SimpleNamespace(
            recommend_refresh_market="",
            recommend_refresh_sector="",
        )
        scheduler = RecommendationScheduler(
            service=service,
            shutdown_handler=self._shutdown_stub(),
            schedule_module=schedule_obj,
        )

        with self.assertLogs(
            "src.recommendation.scheduler", level="WARNING"
        ) as log_ctx:
            scheduler._safe_refresh()

        self.assertTrue(
            any("refresh skipped" in item.lower() for item in log_ctx.output)
        )
        service.refresh_all.assert_not_called()

    def test_safe_refresh_skips_when_sector_missing(self) -> None:
        schedule_obj = _DummySchedule()
        service = Mock()
        service.config = SimpleNamespace(
            recommend_refresh_market="",
            recommend_refresh_sector="",
        )
        scheduler = RecommendationScheduler(
            service=service,
            shutdown_handler=self._shutdown_stub(),
            schedule_module=schedule_obj,
            refresh_market="CN",
            refresh_sector="",
        )

        with self.assertLogs(
            "src.recommendation.scheduler", level="WARNING"
        ) as log_ctx:
            scheduler._safe_refresh()

        self.assertTrue(
            any("refresh skipped" in item.lower() for item in log_ctx.output)
        )
        service.refresh_all.assert_not_called()

    def test_start_and_stop_runs_background_loop(self) -> None:
        schedule_obj = _DummySchedule()
        service = Mock()
        scheduler = RecommendationScheduler(
            service=service,
            shutdown_handler=self._shutdown_stub(),
            schedule_module=schedule_obj,
            poll_interval_seconds=0.1,
        )

        scheduler.start(run_immediately=False)
        time.sleep(0.15)
        scheduler.stop()

        self.assertGreaterEqual(schedule_obj.run_pending_calls, 1)


if __name__ == "__main__":
    unittest.main()
