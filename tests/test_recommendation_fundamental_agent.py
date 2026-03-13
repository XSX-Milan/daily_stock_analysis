# -*- coding: utf-8 -*-

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.agent.agents.recommendation_fundamental_agent import (
    RecommendationFundamentalAgent,
)
from src.agent.protocols import AgentContext


class RecommendationFundamentalAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = RecommendationFundamentalAgent(
            tool_registry=Mock(), llm_adapter=Mock()
        )
        self.ctx = AgentContext(
            query="fundamental check",
            stock_code="AAPL",
            stock_name="Apple",
            data={
                "valuation_data": {
                    "pe_ratio": 14.2,
                    "pb_ratio": 2.0,
                    "total_mv": 120000000000,
                },
                "quote": SimpleNamespace(
                    pe_ratio=16.0, pb_ratio=2.2, total_mv=110000000000
                ),
            },
        )

    def test_system_prompt_contains_legacy_heuristics(self) -> None:
        prompt = self.agent.system_prompt(self.ctx)
        self.assertIn("PE score rules", prompt)
        self.assertIn("strict JSON", prompt)

    def test_build_user_message_contains_valuation_context(self) -> None:
        message = self.agent.build_user_message(self.ctx)
        self.assertIn("valuation_context", message)
        self.assertIn("14.2", message)

    def test_post_process_parses_json_and_confidence_percent(self) -> None:
        raw_text = (
            '{"signal":"buy","confidence":80,"reasoning":"Valuation is fair",'
            '"key_levels":{"pe_ratio":15,"pb_ratio":1.8,"total_mv":100000000000}}'
        )
        opinion = self.agent.post_process(self.ctx, raw_text)
        assert opinion is not None
        self.assertEqual(opinion.signal, "buy")
        self.assertEqual(opinion.confidence, 0.8)
        self.assertEqual(opinion.key_levels["pe_ratio"], 15.0)

    def test_post_process_falls_back_to_text_signal_and_ctx_levels(self) -> None:
        opinion = self.agent.post_process(self.ctx, "Strong buy setup from valuation.")
        assert opinion is not None
        self.assertEqual(opinion.signal, "strong_buy")
        self.assertEqual(opinion.confidence, 0.5)
        self.assertEqual(opinion.key_levels["pe_ratio"], 14.2)


if __name__ == "__main__":
    unittest.main()
