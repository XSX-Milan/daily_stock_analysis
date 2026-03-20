from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.agent.agents.recommendation_agent import RecommendationAgent
from src.agent.protocols import AgentContext, StageResult, StageStatus


def failed_stage(name: str) -> StageResult:
    return StageResult(stage_name=name, status=StageStatus.FAILED, error="skip")


class RecommendationAgentWiringTestCase(unittest.TestCase):
    def test_delegated_technical_agent_receives_technical_skill_policy(self) -> None:
        captured_kwargs: dict[str, object] = {}

        def build_technical(*_args, **kwargs):
            captured_kwargs.update(kwargs)
            agent = Mock()
            agent.agent_name = "technical"
            agent.run.return_value = failed_stage("technical")
            return agent

        def build_failed(name: str):
            agent = Mock()
            agent.agent_name = name
            agent.run.return_value = failed_stage(name)
            return agent

        with (
            patch(
                "src.agent.agents.recommendation_agent.AgentMemory.from_config",
                return_value=Mock(),
            ),
            patch(
                "src.agent.agents.recommendation_agent.TechnicalAgent",
                side_effect=build_technical,
            ),
            patch(
                "src.agent.agents.recommendation_agent.RiskAgent",
                side_effect=lambda *_args, **_kwargs: build_failed("risk"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.DecisionAgent",
                side_effect=lambda *_args, **_kwargs: build_failed("decision"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.PortfolioAgent",
                side_effect=lambda *_args, **_kwargs: build_failed("portfolio"),
            ),
        ):
            agent = RecommendationAgent(
                tool_registry=Mock(),
                llm_adapter=Mock(),
                skill_instructions="active skills",
                technical_skill_policy="TECH_POLICY",
                dimension="technical",
            )
            ctx = AgentContext(
                query="score stock",
                stock_code="600519",
                data={"news_items": []},
            )
            _ = agent._run_main_agent_delegation(ctx)

        self.assertEqual(captured_kwargs.get("technical_skill_policy"), "TECH_POLICY")


if __name__ == "__main__":
    unittest.main()
