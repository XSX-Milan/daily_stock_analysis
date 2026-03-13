# -*- coding: utf-8 -*-

import unittest
from unittest.mock import Mock, patch

from data_provider.realtime_types import UnifiedRealtimeQuote
from src.agent.protocols import AgentOpinion, StageResult, StageStatus
from src.recommendation.engine import ScoringEngine, StockScoringData
from src.recommendation.models import (
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


class RecommendationEngineTestCase(unittest.TestCase):
    @patch("src.recommendation.engine.get_tool_registry")
    @patch("src.recommendation.engine.RecommendationRiskAgent")
    @patch("src.recommendation.engine.RecommendationMacroAgent")
    @patch("src.recommendation.engine.RecommendationSentimentAgent")
    @patch("src.recommendation.engine.RecommendationFundamentalAgent")
    @patch("src.recommendation.engine.RecommendationTechnicalAgent")
    def test_init_builds_default_recommendation_agents(
        self,
        technical_cls: Mock,
        fundamental_cls: Mock,
        sentiment_cls: Mock,
        macro_cls: Mock,
        risk_cls: Mock,
        registry_fn: Mock,
    ) -> None:
        registry_fn.return_value = Mock()
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=20, fundamental=20, sentiment=20, macro=20, risk=20
            )
        )
        self.assertIsNotNone(engine)
        technical_cls.assert_called_once()
        fundamental_cls.assert_called_once()
        sentiment_cls.assert_called_once()
        macro_cls.assert_called_once()
        risk_cls.assert_called_once()

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


if __name__ == "__main__":
    unittest.main()
