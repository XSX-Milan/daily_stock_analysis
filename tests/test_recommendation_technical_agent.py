# -*- coding: utf-8 -*-
import json
import unittest
from unittest.mock import Mock

from src.agent.agents.recommendation_technical_agent import RecommendationTechnicalAgent
from src.agent.protocols import AgentContext


class RecommendationTechnicalAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = RecommendationTechnicalAgent(
            tool_registry=Mock(), llm_adapter=Mock()
        )
        self.ctx = AgentContext(
            query="technical check",
            stock_code="600519",
            stock_name="Moutai",
            data={
                "trend_result": {
                    "trend_status": "STRONG_BULL",
                    "macd_status": "GOLDEN_CROSS",
                    "rsi_status": "NEUTRAL",
                    "buy_signal": "BUY",
                    "volume_ratio_5d": 1.35,
                }
            },
        )

    def test_system_prompt_contains_output_schema_contract(self) -> None:
        prompt = self.agent.system_prompt(self.ctx)
        self.assertIn("Output schema", prompt)
        self.assertIn('"rule_trace"', prompt)

    def test_build_user_message_contains_rule_hint_preview(self) -> None:
        message = self.agent.build_user_message(self.ctx)
        payload = json.loads(message)

        self.assertEqual(payload["stock_code"], "600519")
        self.assertIn("trend_result", payload)
        self.assertIn("rule_hint_preview", payload)
        self.assertGreater(payload["rule_hint_preview"]["guided_score"], 0)

    def test_post_process_parses_and_normalizes_payload(self) -> None:
        raw_text = json.dumps(
            {
                "signal": "strong buy",
                "confidence": 130,
                "reasoning": "Trend and momentum are aligned.",
                "key_levels": {"support": "98.5", "resistance": 106.2},
            }
        )

        opinion = self.agent.post_process(self.ctx, raw_text)
        assert opinion is not None
        self.assertEqual(opinion.signal, "strong_buy")
        self.assertEqual(opinion.confidence, 1.0)
        self.assertEqual(opinion.key_levels["support"], 98.5)
        self.assertIn("guided_score", opinion.key_levels)

    def test_post_process_handles_invalid_json_with_defaults(self) -> None:
        opinion = self.agent.post_process(self.ctx, "not-json")
        assert opinion is not None
        self.assertEqual(opinion.signal, "hold")
        self.assertEqual(opinion.reasoning, "Technical trend review completed.")


if __name__ == "__main__":
    unittest.main()
