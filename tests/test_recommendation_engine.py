# -*- coding: utf-8 -*-

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from data_provider.realtime_types import UnifiedRealtimeQuote
from src.agent.protocols import AgentOpinion, StageResult, StageStatus
from src.recommendation.engine import ScoringEngine, StockScoringData
from src.recommendation.models import (
    CompositeScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
)
from src.stock_analyzer import TrendAnalysisResult


def build_stock_data(code: str) -> StockScoringData:
    return StockScoringData(
        region=MarketRegion.CN,
        trend_result=TrendAnalysisResult(code=code),
        quote=UnifiedRealtimeQuote(
            code=code, price=100.0, volume_ratio=1.0, turnover_rate=2.0
        ),
        news_items=[{"title": "sample"}],
        index_data={"000001": {"price": 3200, "ma20": 3150, "change_pct": 0.4}},
    )


def completed_stage(signal: str, confidence: float, score_0_100: float) -> StageResult:
    return StageResult(
        stage_name="test",
        status=StageStatus.COMPLETED,
        opinion=AgentOpinion(
            signal=signal,
            confidence=confidence,
            reasoning="ok",
            raw_data={"score_0_100": score_0_100},
        ),
    )


def build_composite_score(
    code: str,
    total_score: float = 80.0,
    priority: RecommendationPriority = RecommendationPriority.POSITION,
) -> CompositeScore:
    composite_score = CompositeScore(total_score=total_score, priority=priority)
    setattr(composite_score, "code", code)
    return composite_score


class RecommendationEngineTestCase(unittest.TestCase):
    _DIMENSIONS = ("technical", "fundamental", "sentiment", "macro", "risk")

    @patch("src.recommendation.engine.build_recommendation_agent")
    def test_init_builds_default_recommendation_agents(
        self,
        build_recommendation_agent_fn: Mock,
    ) -> None:
        build_recommendation_agent_fn.side_effect = [
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
        ]
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20, fundamental=20, sentiment=20, macro=20, risk=20
            ),
        )
        self.assertIsNotNone(engine)
        self.assertEqual(build_recommendation_agent_fn.call_count, 5)
        called_dimensions = {
            call.kwargs.get("dimension")
            for call in build_recommendation_agent_fn.call_args_list
        }
        self.assertEqual(
            called_dimensions,
            {"technical", "fundamental", "sentiment", "macro", "risk"},
        )

    @patch("src.recommendation.engine.build_recommendation_agent")
    def test_init_maps_legacy_strategy_dir_to_skill_dir_for_recommendation(
        self,
        build_recommendation_agent_fn: Mock,
    ) -> None:
        build_recommendation_agent_fn.side_effect = [
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
        ]
        config = SimpleNamespace(
            agent_strategy_dir="/tmp/legacy-strategies",
            agent_skill_dir=None,
            agent_skills=None,
        )

        _ = ScoringEngine(
            weights=ScoringWeights(
                technical=20,
                fundamental=20,
                sentiment=20,
                macro=20,
                risk=20,
            ),
            config=config,
        )

        self.assertEqual(
            getattr(config, "agent_skill_dir", None), "/tmp/legacy-strategies"
        )
        for call in build_recommendation_agent_fn.call_args_list:
            self.assertIs(call.kwargs.get("config"), config)

    def test_score_stock_uses_agent_opinion_scores_with_weights(self) -> None:
        agents = {
            "technical": Mock(
                run=Mock(return_value=completed_stage("strong_buy", 0.9, 90))
            ),
            "fundamental": Mock(run=Mock(return_value=completed_stage("buy", 0.8, 80))),
            "sentiment": Mock(run=Mock(return_value=completed_stage("hold", 0.6, 60))),
            "macro": Mock(run=Mock(return_value=completed_stage("sell", 0.7, 40))),
            "risk": Mock(run=Mock(return_value=completed_stage("buy", 0.7, 70))),
        }
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=30, fundamental=25, sentiment=20, macro=15, risk=10
            ),
            agents=agents,
        )

        result = engine.score_stock("600519", build_stock_data("600519"))

        self.assertEqual(result.total_score, 72.0)
        self.assertEqual(result.priority, RecommendationPriority.POSITION)
        self.assertEqual(len(result.dimension_scores), 5)

    def test_score_stock_uses_fallback_when_agent_stage_fails(self) -> None:
        failed_stage = StageResult(
            stage_name="risk", status=StageStatus.FAILED, error="mock fail"
        )
        agents = {
            "technical": Mock(run=Mock(return_value=completed_stage("buy", 0.7, 80))),
            "fundamental": Mock(run=Mock(return_value=completed_stage("buy", 0.7, 80))),
            "sentiment": Mock(run=Mock(return_value=completed_stage("buy", 0.7, 80))),
            "macro": Mock(run=Mock(return_value=completed_stage("buy", 0.7, 80))),
            "risk": Mock(run=Mock(return_value=failed_stage)),
        }
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20, fundamental=20, sentiment=20, macro=20, risk=20
            ),
            agents=agents,
        )

        result = engine.score_stock("600519", build_stock_data("600519"))

        self.assertEqual(result.total_score, 74.0)
        risk_dim = [
            item for item in result.dimension_scores if item.dimension == "risk"
        ][0]
        self.assertEqual(risk_dim.score, 50.0)
        self.assertTrue(risk_dim.details["fallback"])

    def test_score_stock_raises_when_required_agent_missing(self) -> None:
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20, fundamental=20, sentiment=20, macro=20, risk=20
            ),
            agents={"technical": Mock()},
        )
        with self.assertRaises(ValueError):
            engine.score_stock("600519", build_stock_data("600519"))

    def test_score_batch_preserves_input_order(self) -> None:
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20,
                fundamental=20,
                sentiment=20,
                macro=20,
                risk=20,
            ),
            agents={
                "technical": Mock(
                    run=Mock(return_value=completed_stage("buy", 0.8, 80))
                ),
                "fundamental": Mock(
                    run=Mock(return_value=completed_stage("buy", 0.8, 80))
                ),
                "sentiment": Mock(
                    run=Mock(return_value=completed_stage("buy", 0.8, 80))
                ),
                "macro": Mock(run=Mock(return_value=completed_stage("buy", 0.8, 80))),
                "risk": Mock(run=Mock(return_value=completed_stage("buy", 0.8, 80))),
            },
            batch_max_workers=4,
        )

        scores = engine.score_batch(
            [
                ("600519", build_stock_data("600519")),
                ("AAPL", build_stock_data("AAPL")),
                ("00700", build_stock_data("00700")),
            ]
        )

        self.assertEqual(len(scores), 3)
        self.assertTrue(all(item.total_score == 80.0 for item in scores))
        self.assertEqual(
            [getattr(item, "code", None) for item in scores],
            ["600519", "AAPL", "00700"],
        )

    def test_score_batch_skips_failed_items_and_logs_warning(self) -> None:
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20,
                fundamental=20,
                sentiment=20,
                macro=20,
                risk=20,
            ),
            agents={},
            batch_max_workers=1,
        )

        def side_effect(code: str, _data: StockScoringData) -> CompositeScore:
            if code == "AAPL":
                raise RuntimeError("mock failure")
            return build_composite_score(code=code, total_score=82.0)

        with patch.object(engine, "score_stock", side_effect=side_effect):
            with self.assertLogs("src.recommendation.engine", level="WARNING") as logs:
                scores = engine.score_batch(
                    [
                        ("600519", build_stock_data("600519")),
                        ("AAPL", build_stock_data("AAPL")),
                        ("00700", build_stock_data("00700")),
                    ]
                )

        self.assertEqual(
            [getattr(item, "code", None) for item in scores], ["600519", "00700"]
        )
        self.assertTrue(any("AAPL" in log for log in logs.output))

    def test_score_batch_raises_runtime_error_when_all_items_fail(self) -> None:
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20,
                fundamental=20,
                sentiment=20,
                macro=20,
                risk=20,
            ),
            agents={},
            batch_max_workers=4,
        )

        with patch.object(
            engine, "score_stock", side_effect=RuntimeError("mock failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "all 2 stocks"):
                engine.score_batch(
                    [
                        ("600519", build_stock_data("600519")),
                        ("AAPL", build_stock_data("AAPL")),
                    ]
                )

    def test_score_stock_reuses_delegate_results_across_dimensions(self) -> None:
        delegate_build_count = 0

        def build_agent(score_0_100: float) -> Mock:
            def run(ctx) -> StageResult:
                nonlocal delegate_build_count
                cached = ctx.get_data("_recommendation_delegate_results")
                if not (isinstance(cached, list) and cached):
                    delegate_build_count += 1
                    ctx.set_data(
                        "_recommendation_delegate_results",
                        [
                            {
                                "agent_name": "technical",
                                "signal": "buy",
                                "confidence": 0.8,
                                "score": 72.0,
                            }
                        ],
                    )
                return completed_stage("buy", 0.8, score_0_100)

            return Mock(run=Mock(side_effect=run))

        agents = {dimension: build_agent(80.0) for dimension in self._DIMENSIONS}
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20,
                fundamental=20,
                sentiment=20,
                macro=20,
                risk=20,
            ),
            agents=agents,
        )

        result = engine.score_stock("600519", build_stock_data("600519"))

        self.assertEqual(delegate_build_count, 1)
        self.assertEqual(result.total_score, 80.0)
        self.assertEqual(len(result.dimension_scores), 5)

    def test_score_stock_retries_delegate_generation_when_first_result_unusable(
        self,
    ) -> None:
        delegate_build_dimensions: list[str] = []

        def build_agent(dimension: str) -> Mock:
            def run(ctx) -> StageResult:
                cached = ctx.get_data("_recommendation_delegate_results")
                if not (isinstance(cached, list) and cached):
                    delegate_build_dimensions.append(dimension)
                    if dimension == "technical":
                        ctx.set_data("_recommendation_delegate_results", [])
                    else:
                        ctx.set_data(
                            "_recommendation_delegate_results",
                            [
                                {
                                    "agent_name": "intel",
                                    "signal": "hold",
                                    "confidence": 0.5,
                                    "score": 50.0,
                                }
                            ],
                        )
                return completed_stage("hold", 0.6, 50.0)

            return Mock(run=Mock(side_effect=run))

        agents = {dimension: build_agent(dimension) for dimension in self._DIMENSIONS}
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20,
                fundamental=20,
                sentiment=20,
                macro=20,
                risk=20,
            ),
            agents=agents,
        )

        result = engine.score_stock("600519", build_stock_data("600519"))

        self.assertEqual(delegate_build_dimensions, ["technical", "fundamental"])
        self.assertEqual(result.total_score, 50.0)
        self.assertEqual(result.priority, RecommendationPriority.WAIT_PULLBACK)


if __name__ == "__main__":
    unittest.main()
