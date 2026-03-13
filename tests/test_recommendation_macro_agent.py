# -*- coding: utf-8 -*-

import json
import unittest
from unittest.mock import Mock

from src.agent.agents.recommendation_macro_agent import RecommendationMacroAgent
from src.agent.protocols import AgentContext


class RecommendationMacroAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = RecommendationMacroAgent(tool_registry=Mock(), llm_adapter=Mock())

    def test_system_prompt_and_build_user_message_contract(self) -> None:
        ctx = AgentContext(
            stock_code="600519",
            stock_name="Moutai",
            data={
                "market_index_data": {
                    "000001": {"price": 3200, "ma20": 3150, "change_pct": 0.6}
                }
            },
        )
        prompt = self.agent.system_prompt(ctx)
        message = self.agent.build_user_message(ctx)
        payload = json.loads(message)

        self.assertIn("strict JSON", prompt)
        self.assertIn("output_contract", payload)
        self.assertIn("000001", payload["index_data"])

    def test_post_process_parses_json_aliases_and_confidence_percent(self) -> None:
        ctx = AgentContext(stock_code="600519", data={})
        raw_text = json.dumps(
            {
                "signal": "risk_on",
                "confidence": "85%",
                "reasoning": "Broad indices are above MA20.",
                "key_levels": {"support": "3150", "resistance": 3320},
                "raw_data": {"trend": "bull"},
            }
        )
        opinion = self.agent.post_process(ctx, raw_text)
        assert opinion is not None

        self.assertEqual(opinion.signal, "buy")
        self.assertEqual(opinion.confidence, 0.85)
        self.assertEqual(opinion.key_levels["support"], 3150.0)
        self.assertEqual(opinion.raw_data["source"], "recommendation_macro_agent")

    def test_post_process_falls_back_to_text_inference(self) -> None:
        ctx = AgentContext(stock_code="AAPL", data={})
        opinion = self.agent.post_process(ctx, "macro looks bear and risk-off")
        assert opinion is not None

        self.assertEqual(opinion.signal, "sell")
        self.assertEqual(opinion.confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
