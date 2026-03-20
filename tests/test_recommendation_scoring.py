import unittest
from datetime import datetime
from typing import Any, cast
from unittest.mock import Mock, patch

from api.v1.endpoints.recommendation import _to_recommendation_response
from api.v1.schemas.recommendation import RecommendationResponse
from data_provider.realtime_types import UnifiedRealtimeQuote
from src.agent.agents.base_agent import BaseAgent
from src.agent.agents.recommendation_agent import RecommendationAgent
from src.agent.agents.risk_agent import RiskAgent
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.recommendation.engine import ScoringEngine, StockScoringData
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
    StockRecommendation,
)
from src.services.recommendation_service import RecommendationService
from src.stock_analyzer import TrendAnalysisResult


class RecommendationScoringRedTestCase(unittest.TestCase):
    @staticmethod
    def _build_engine_with_recommendation_agents() -> ScoringEngine:
        registry = Mock()
        llm_adapter = Mock()
        agents = {
            "technical": RecommendationAgent(
                registry, llm_adapter, dimension="technical"
            ),
            "fundamental": RecommendationAgent(
                registry,
                llm_adapter,
                dimension="fundamental",
            ),
            "sentiment": RecommendationAgent(
                registry, llm_adapter, dimension="sentiment"
            ),
            "macro": RecommendationAgent(registry, llm_adapter, dimension="macro"),
            "risk": RecommendationAgent(registry, llm_adapter, dimension="risk"),
        }
        return ScoringEngine(
            weights=ScoringWeights(
                technical=30,
                fundamental=25,
                sentiment=20,
                macro=15,
                risk=10,
            ),
            agents=agents,
        )

    @staticmethod
    def _build_stock_scoring_data(code: str, region: MarketRegion) -> StockScoringData:
        trend_result = TrendAnalysisResult(code=code, signal_score=70)
        trend_result.support_levels = [95.0]
        return StockScoringData(
            region=region,
            trend_result=trend_result,
            quote=UnifiedRealtimeQuote(
                code=code,
                price=100.0,
                volume_ratio=0.6,
                turnover_rate=2.0,
            ),
            news_items=[{"title": "sample"}],
            index_data={"IDX": {"change_pct": 0.5}},
            price_vs_ma10=0.01,
            price_vs_ma20=-0.03,
            trading_days=30,
        )

    def _technical_score(
        self,
        *,
        stock_code: str,
        volume_ratio: float | None,
        technical_data: dict | None = None,
        trading_days: int = 120,
    ) -> float:
        quote = {}
        if volume_ratio is not None:
            quote["volume_ratio"] = volume_ratio
        ctx = AgentContext(
            stock_code=stock_code,
            data={
                "quote": quote,
                "technical": dict(technical_data or {}),
                "risk_context": {"trading_days": trading_days},
                "trading_days": trading_days,
            },
        )
        agent = RecommendationAgent.__new__(RecommendationAgent)
        return agent._technical_score(ctx, trend_score=70.0, delegated=[])

    def test_shrink_volume_pullback_bonus(self) -> None:
        pullback_score = self._technical_score(
            stock_code="600519",
            volume_ratio=0.6,
            technical_data={"price_vs_ma10": 0.01, "ma_alignment": "bullish"},
        )
        baseline_score = self._technical_score(
            stock_code="600519",
            volume_ratio=1.0,
            technical_data={"price_vs_ma10": 0.05, "ma_alignment": "mixed"},
        )
        self.assertGreaterEqual(pullback_score, baseline_score + 5.0)

    def test_heavy_volume_penalty(self) -> None:
        heavy_volume_score = self._technical_score(
            stock_code="600519",
            volume_ratio=2.2,
        )
        moderate_volume_score = self._technical_score(
            stock_code="600519",
            volume_ratio=1.2,
        )
        self.assertLessEqual(heavy_volume_score, moderate_volume_score - 4.0)

    def test_very_heavy_volume_penalty_tier(self) -> None:
        very_heavy_volume_score = self._technical_score(
            stock_code="600519",
            volume_ratio=3.2,
        )
        heavy_volume_score = self._technical_score(
            stock_code="600519",
            volume_ratio=2.2,
        )
        self.assertLessEqual(very_heavy_volume_score, heavy_volume_score - 4.0)

    def test_counter_trend_bonus(self) -> None:
        counter_trend_score = self._technical_score(
            stock_code="600519",
            volume_ratio=1.2,
            technical_data={"price_vs_ma20": -0.03},
        )
        neutral_score = self._technical_score(
            stock_code="600519",
            volume_ratio=1.2,
            technical_data={"price_vs_ma20": 0.02},
        )
        self.assertGreaterEqual(counter_trend_score, neutral_score + 3.0)

    def test_counter_trend_ma60_bonus(self) -> None:
        ma60_counter_trend_score = self._technical_score(
            stock_code="600519",
            volume_ratio=1.2,
            technical_data={"price_vs_ma60": -0.01},
        )
        neutral_score = self._technical_score(
            stock_code="600519",
            volume_ratio=1.2,
            technical_data={"price_vs_ma60": 0.02},
        )
        self.assertGreaterEqual(ma60_counter_trend_score, neutral_score + 2.0)

    def test_moderate_volume_expansion_neutral(self) -> None:
        moderate_score = self._technical_score(
            stock_code="600519",
            volume_ratio=1.5,
        )
        no_volume_score = self._technical_score(
            stock_code="600519",
            volume_ratio=None,
        )
        self.assertAlmostEqual(moderate_score, no_volume_score, places=2)

    def test_cn_market_rules_applied(self) -> None:
        cn_score = self._technical_score(
            stock_code="600519",
            volume_ratio=0.6,
            technical_data={"price_vs_ma10": 0.01, "ma_alignment": "bullish"},
        )
        hk_score = self._technical_score(
            stock_code="hk00700",
            volume_ratio=0.6,
            technical_data={"price_vs_ma10": 0.01, "ma_alignment": "bullish"},
        )
        self.assertGreaterEqual(cn_score, hk_score + 5.0)

    def test_hk_us_market_rules_skipped(self) -> None:
        hk_signal_score = self._technical_score(
            stock_code="hk00700",
            volume_ratio=0.6,
            technical_data={
                "price_vs_ma10": 0.01,
                "ma_alignment": "bullish",
                "price_vs_ma20": -0.03,
            },
        )
        hk_baseline_score = self._technical_score(
            stock_code="hk00700",
            volume_ratio=1.0,
            technical_data={
                "price_vs_ma10": 0.05,
                "ma_alignment": "mixed",
                "price_vs_ma20": 0.02,
            },
        )
        us_signal_score = self._technical_score(
            stock_code="AAPL",
            volume_ratio=0.6,
            technical_data={
                "price_vs_ma10": 0.01,
                "ma_alignment": "bullish",
                "price_vs_ma20": -0.03,
            },
        )
        us_baseline_score = self._technical_score(
            stock_code="AAPL",
            volume_ratio=1.0,
            technical_data={
                "price_vs_ma10": 0.05,
                "ma_alignment": "mixed",
                "price_vs_ma20": 0.02,
            },
        )
        self.assertAlmostEqual(hk_signal_score, hk_baseline_score, places=2)
        self.assertAlmostEqual(us_signal_score, us_baseline_score, places=2)

    def test_no_volume_data_fallback(self) -> None:
        scoring_data_factory = cast(Any, StockScoringData)
        data = scoring_data_factory(
            region=MarketRegion.CN,
            trend_result=TrendAnalysisResult(code="600519"),
            quote=UnifiedRealtimeQuote(code="600519", price=100.0),
            news_items=[],
            index_data={},
            volume_trend="unknown",
            volume_ma5_ratio=None,
            price_vs_ma10=None,
            price_vs_ma20=None,
            ma_alignment="unknown",
            trading_days=None,
            max_hold_days=10,
        )
        self.assertEqual(cast(Any, data).volume_trend, "unknown")

    def test_ipo_stock_guard(self) -> None:
        ipo_score = self._technical_score(
            stock_code="600519",
            volume_ratio=3.2,
            technical_data={"price_vs_ma10": 0.01, "ma_alignment": "bullish"},
            trading_days=3,
        )
        baseline_score = self._technical_score(
            stock_code="600519",
            volume_ratio=None,
            technical_data={"price_vs_ma10": 0.01, "ma_alignment": "bullish"},
            trading_days=3,
        )
        self.assertAlmostEqual(ipo_score, baseline_score, places=2)

    def test_price_levels_stop_loss_7pct(self) -> None:
        _, stop_loss, _ = RecommendationService._price_levels(100.0, [95.0])
        self.assertEqual(stop_loss, 93.0)

    def test_price_levels_take_profit_10pct(self) -> None:
        _, _, take_profit = RecommendationService._price_levels(100.0, [])
        self.assertEqual(take_profit, 110.0)

    def test_price_levels_max_hold_10days(self) -> None:
        engine = ScoringEngine(
            weights=ScoringWeights(
                technical=30,
                fundamental=25,
                sentiment=20,
                macro=15,
                risk=10,
            ),
            agents={},
        )
        opinion = AgentOpinion(
            agent_name="recommendation_risk",
            signal="hold",
            confidence=0.8,
            reasoning="risk test",
            raw_data={"score_0_100": 66.0},
        )
        stage_result = StageResult(
            stage_name="recommendation_risk",
            status=StageStatus.COMPLETED,
            opinion=opinion,
        )
        dimension_score = engine._opinion_to_dimension_score(
            dimension="risk",
            opinion=opinion,
            stage_result=stage_result,
        )
        self.assertIn("max_hold_days", dimension_score.details)
        self.assertEqual(dimension_score.details.get("max_hold_days"), 10)

    def test_full_scoring_pipeline_cn_stock(self) -> None:
        with (
            patch.object(
                RecommendationAgent,
                "_collect_delegated_opinions",
                return_value=[],
            ),
            patch.object(
                RecommendationAgent,
                "_calibrate_confidence",
                side_effect=lambda raw_confidence, stock_code: raw_confidence,
            ),
        ):
            engine = self._build_engine_with_recommendation_agents()
            result = engine.score_stock(
                "600519",
                self._build_stock_scoring_data("600519", MarketRegion.CN),
            )

        technical = {item.dimension: item.score for item in result.dimension_scores}[
            "technical"
        ]
        self.assertAlmostEqual(technical, 74.0, places=2)

        _, stop_loss, take_profit = RecommendationService._price_levels(
            100.0,
            [95.0],
            region=MarketRegion.CN,
        )
        self.assertEqual(stop_loss, 93.0)
        self.assertEqual(take_profit, 110.0)

    def test_full_scoring_pipeline_us_stock(self) -> None:
        with (
            patch.object(
                RecommendationAgent,
                "_collect_delegated_opinions",
                return_value=[],
            ),
            patch.object(
                RecommendationAgent,
                "_calibrate_confidence",
                side_effect=lambda raw_confidence, stock_code: raw_confidence,
            ),
        ):
            engine = self._build_engine_with_recommendation_agents()
            result = engine.score_stock(
                "AAPL",
                self._build_stock_scoring_data("AAPL", MarketRegion.US),
            )

        technical = {item.dimension: item.score for item in result.dimension_scores}[
            "technical"
        ]
        self.assertAlmostEqual(technical, 66.0, places=2)

        _, stop_loss, take_profit = RecommendationService._price_levels(
            100.0,
            [95.0],
            region=MarketRegion.US,
        )
        self.assertEqual(stop_loss, 90.25)
        self.assertEqual(take_profit, 112.0)

    def test_skill_instructions_reach_delegated_agents(self) -> None:
        captured_messages: list[list[dict[str, Any]]] = []
        skill_text = "Use strict risk controls before final judgment."

        def _delegate_cls(name: str):
            class _DelegateAgent(BaseAgent):
                agent_name = name

                def system_prompt(self, ctx: AgentContext) -> str:
                    del ctx
                    return f"{name} system prompt"

                def build_user_message(self, ctx: AgentContext) -> str:
                    del ctx
                    return f"{name} user prompt"

                def run(self, ctx: AgentContext, progress_callback=None) -> StageResult:
                    del progress_callback
                    captured_messages.append(self._build_messages(ctx))
                    return StageResult(
                        stage_name=name,
                        status=StageStatus.COMPLETED,
                        opinion=AgentOpinion(
                            agent_name=name,
                            signal="hold",
                            confidence=0.6,
                            reasoning="ok",
                        ),
                    )

            return _DelegateAgent

        with (
            patch(
                "src.agent.agents.recommendation_agent.TechnicalAgent",
                _delegate_cls("technical"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.IntelAgent",
                _delegate_cls("intel"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.RiskAgent",
                _delegate_cls("risk"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.DecisionAgent",
                _delegate_cls("decision"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.PortfolioAgent",
                _delegate_cls("portfolio"),
            ),
            patch.object(
                RecommendationAgent,
                "_calibrate_confidence",
                side_effect=lambda raw_confidence, stock_code: raw_confidence,
            ),
        ):
            agent = RecommendationAgent(
                Mock(),
                Mock(),
                skill_instructions=skill_text,
                dimension="technical",
            )
            result = agent.run(
                AgentContext(
                    query="test",
                    stock_code="600519",
                    data={
                        "quote": {"volume_ratio": 1.0},
                        "technical": {},
                        "risk_context": {"trading_days": 30},
                    },
                )
            )

        self.assertEqual(result.status, StageStatus.COMPLETED)
        self.assertEqual(len(captured_messages), 5)
        for messages in captured_messages:
            self.assertGreaterEqual(len(messages), 3)
            self.assertEqual(messages[1]["role"], "system")
            self.assertEqual(
                messages[1]["content"],
                f"[Skill Instructions]\n{skill_text}",
            )

    def test_preloaded_news_items_skip_intel_delegation(self) -> None:
        ran_agents: list[str] = []

        def _delegate_cls(name: str):
            class _DelegateAgent(BaseAgent):
                agent_name = name

                def system_prompt(self, ctx: AgentContext) -> str:
                    del ctx
                    return f"{name} system prompt"

                def build_user_message(self, ctx: AgentContext) -> str:
                    del ctx
                    return f"{name} user prompt"

                def run(self, ctx: AgentContext, progress_callback=None) -> StageResult:
                    del ctx
                    del progress_callback
                    ran_agents.append(name)
                    return StageResult(
                        stage_name=name,
                        status=StageStatus.COMPLETED,
                        opinion=AgentOpinion(
                            agent_name=name,
                            signal="hold",
                            confidence=0.6,
                            reasoning="ok",
                        ),
                    )

            return _DelegateAgent

        with (
            patch(
                "src.agent.agents.recommendation_agent.TechnicalAgent",
                _delegate_cls("technical"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.IntelAgent",
                _delegate_cls("intel"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.RiskAgent",
                _delegate_cls("risk"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.DecisionAgent",
                _delegate_cls("decision"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.PortfolioAgent",
                _delegate_cls("portfolio"),
            ),
            patch.object(
                RecommendationAgent,
                "_calibrate_confidence",
                side_effect=lambda raw_confidence, stock_code: raw_confidence,
            ),
        ):
            agent = RecommendationAgent(
                Mock(),
                Mock(),
                dimension="technical",
            )
            result = agent.run(
                AgentContext(
                    query="test",
                    stock_code="AAPL",
                    data={
                        "news_items": [],
                        "quote": {"volume_ratio": 1.0},
                        "technical": {},
                        "risk_context": {"trading_days": 30},
                    },
                )
            )

        self.assertEqual(result.status, StageStatus.COMPLETED)
        self.assertEqual(ran_agents, ["technical", "risk", "decision", "portfolio"])
        self.assertNotIn("intel", ran_agents)

    def test_missing_preloaded_news_keeps_intel_delegation(self) -> None:
        ran_agents: list[str] = []

        def _delegate_cls(name: str):
            class _DelegateAgent(BaseAgent):
                agent_name = name

                def system_prompt(self, ctx: AgentContext) -> str:
                    del ctx
                    return f"{name} system prompt"

                def build_user_message(self, ctx: AgentContext) -> str:
                    del ctx
                    return f"{name} user prompt"

                def run(self, ctx: AgentContext, progress_callback=None) -> StageResult:
                    del ctx
                    del progress_callback
                    ran_agents.append(name)
                    return StageResult(
                        stage_name=name,
                        status=StageStatus.COMPLETED,
                        opinion=AgentOpinion(
                            agent_name=name,
                            signal="hold",
                            confidence=0.6,
                            reasoning="ok",
                        ),
                    )

            return _DelegateAgent

        with (
            patch(
                "src.agent.agents.recommendation_agent.TechnicalAgent",
                _delegate_cls("technical"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.IntelAgent",
                _delegate_cls("intel"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.RiskAgent",
                _delegate_cls("risk"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.DecisionAgent",
                _delegate_cls("decision"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.PortfolioAgent",
                _delegate_cls("portfolio"),
            ),
            patch.object(
                RecommendationAgent,
                "_calibrate_confidence",
                side_effect=lambda raw_confidence, stock_code: raw_confidence,
            ),
        ):
            agent = RecommendationAgent(
                Mock(),
                Mock(),
                dimension="technical",
            )
            result = agent.run(
                AgentContext(
                    query="test",
                    stock_code="AAPL",
                    data={
                        "quote": {"volume_ratio": 1.0},
                        "technical": {},
                        "risk_context": {"trading_days": 30},
                    },
                )
            )

        self.assertEqual(result.status, StageStatus.COMPLETED)
        self.assertEqual(
            ran_agents,
            ["technical", "intel", "risk", "decision", "portfolio"],
        )
        self.assertIn("intel", ran_agents)

    def test_risk_agent_preloaded_news_keys_skip_live_search_instruction(self) -> None:
        agent = RiskAgent(Mock(), Mock())
        live_search_instruction = (
            "Search for latest news if you haven't received intel data yet."
        )

        message_with_news_items = agent.build_user_message(
            AgentContext(stock_code="AAPL", data={"news_items": []})
        )
        message_with_news = agent.build_user_message(
            AgentContext(stock_code="AAPL", data={"news": []})
        )

        self.assertNotIn(live_search_instruction, message_with_news_items)
        self.assertNotIn(live_search_instruction, message_with_news)

    def test_risk_agent_missing_preloaded_news_keeps_live_search_instruction(
        self,
    ) -> None:
        agent = RiskAgent(Mock(), Mock())
        live_search_instruction = (
            "Search for latest news if you haven't received intel data yet."
        )

        message = agent.build_user_message(AgentContext(stock_code="AAPL", data={}))

        self.assertIn(live_search_instruction, message)

    def test_backward_compatibility_api_schema(self) -> None:
        schema = RecommendationResponse.model_json_schema()
        self.assertEqual(
            set(schema.get("required", [])),
            {
                "stock_code",
                "name",
                "market",
                "composite_score",
                "priority",
                "updated_at",
            },
        )
        self.assertEqual(
            set(schema.get("properties", {}).keys()),
            {
                "stock_code",
                "code",
                "name",
                "stock_name",
                "market",
                "region",
                "sector",
                "scores",
                "composite_score",
                "priority",
                "suggested_buy",
                "ideal_buy_price",
                "current_price",
                "stop_loss",
                "take_profit",
                "ai_refined",
                "ai_summary",
                "updated_at",
            },
        )

        item = StockRecommendation(
            code="AAPL",
            name="Apple",
            region=MarketRegion.US,
            sector="Technology",
            current_price=100.0,
            composite_score=CompositeScore(
                total_score=88.0,
                priority=RecommendationPriority.BUY_NOW,
                dimension_scores=[
                    DimensionScore(
                        dimension="technical",
                        score=80.0,
                        weight=0.3,
                    )
                ],
            ),
            ideal_buy_price=98.0,
            stop_loss=93.0,
            take_profit=112.0,
            updated_at=datetime(2026, 1, 1),
        )
        response = _to_recommendation_response(item)
        self.assertEqual(response.stock_code, response.code)
        self.assertEqual(response.stock_name, response.name)
        self.assertEqual(response.region, response.market)
        self.assertEqual(response.ideal_buy_price, response.suggested_buy)


if __name__ == "__main__":
    unittest.main()
