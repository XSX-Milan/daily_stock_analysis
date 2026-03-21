from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.agent.agents.recommendation_agent import RecommendationAgent
from src.agent.factory import build_recommendation_agent
from src.agent.protocols import AgentContext, StageResult, StageStatus


def failed_stage(name: str) -> StageResult:
    return StageResult(stage_name=name, status=StageStatus.FAILED, error="skip")


class RecommendationAgentWiringTestCase(unittest.TestCase):
    def test_factory_build_recommendation_agent_injects_default_technical_skill_policy(
        self,
    ) -> None:
        config = SimpleNamespace(
            agent_skills=None,
            agent_skill_dir=None,
            agent_arch="single",
        )

        with (
            patch(
                "src.agent.factory.get_tool_registry",
                return_value=Mock(),
            ),
            patch(
                "src.agent.factory.get_skill_manager",
            ) as get_skill_manager_mock,
            patch(
                "src.agent.factory.LLMToolAdapter",
                return_value=Mock(),
                create=True,
            ),
            patch(
                "src.agent.agents.recommendation_agent.AgentMemory.from_config",
                return_value=Mock(),
            ),
        ):
            agent = build_recommendation_agent(config=config, dimension="technical")

        self.assertIsInstance(agent, RecommendationAgent)
        self.assertTrue(agent.technical_skill_policy.strip())
        self.assertEqual(agent.skill_instructions, "")
        get_skill_manager_mock.assert_not_called()

    def test_delegated_technical_agent_receives_technical_skill_policy(self) -> None:
        captured_kwargs: dict[str, object] = {}
        captured_skill_text: dict[str, str] = {}

        def build_technical(*args, **kwargs):
            if len(args) >= 3:
                captured_skill_text["value"] = str(args[2])
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
        self.assertIn(
            "Built-in Quant Recommendation Framework",
            captured_skill_text.get("value", ""),
        )
        self.assertNotIn("active skills", captured_skill_text.get("value", ""))

    def test_system_prompt_contains_builtin_framework_policy(self) -> None:
        with patch(
            "src.agent.agents.recommendation_agent.AgentMemory.from_config",
            return_value=Mock(),
        ):
            agent = RecommendationAgent(
                tool_registry=Mock(),
                llm_adapter=Mock(),
                skill_instructions="legacy recommendation skill text",
                technical_skill_policy="TECH_POLICY",
                dimension="technical",
            )

        prompt = agent.system_prompt(AgentContext())
        self.assertIn("Built-in Quant Recommendation Framework", prompt)
        self.assertIn("TECH_POLICY", prompt)

    def test_delegated_agents_receive_timeout_budget(self) -> None:
        delegated_agents: list[Mock] = []

        def build_delegate(name: str, **kwargs):
            if name == "technical":
                self.assertEqual(kwargs.get("technical_skill_policy"), "TECH_POLICY")
            agent = Mock()
            agent.agent_name = name
            agent.run.return_value = failed_stage(name)
            delegated_agents.append(agent)
            return agent

        with (
            patch(
                "src.agent.agents.recommendation_agent.AgentMemory.from_config",
                return_value=Mock(),
            ),
            patch(
                "src.agent.agents.recommendation_agent.TechnicalAgent",
                side_effect=lambda *_args, **kwargs: build_delegate(
                    "technical", **kwargs
                ),
            ),
            patch(
                "src.agent.agents.recommendation_agent.RiskAgent",
                side_effect=lambda *_args, **_kwargs: build_delegate("risk"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.DecisionAgent",
                side_effect=lambda *_args, **_kwargs: build_delegate("decision"),
            ),
            patch(
                "src.agent.agents.recommendation_agent.PortfolioAgent",
                side_effect=lambda *_args, **_kwargs: build_delegate("portfolio"),
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
            _ = agent._run_main_agent_delegation(ctx, timeout_seconds=12.5)

        self.assertEqual(len(delegated_agents), 4)
        for delegated_agent in delegated_agents:
            self.assertIn("timeout_seconds", delegated_agent.run.call_args.kwargs)
            self.assertGreater(
                delegated_agent.run.call_args.kwargs["timeout_seconds"],
                0,
            )

    def test_delegated_legacy_agents_without_timeout_kwarg_still_run(self) -> None:
        ran_agents: list[str] = []

        def _delegate_cls(name: str):
            class _DelegateAgent:
                agent_name = name

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                def run(self, ctx, progress_callback=None):
                    del ctx
                    del progress_callback
                    ran_agents.append(name)
                    return failed_stage(name)

            return _DelegateAgent

        with (
            patch(
                "src.agent.agents.recommendation_agent.AgentMemory.from_config",
                return_value=Mock(),
            ),
            patch(
                "src.agent.agents.recommendation_agent.TechnicalAgent",
                _delegate_cls("technical"),
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
            _ = agent._run_main_agent_delegation(ctx, timeout_seconds=12.5)

        self.assertEqual(ran_agents, ["technical", "risk", "decision", "portfolio"])


if __name__ == "__main__":
    unittest.main()
