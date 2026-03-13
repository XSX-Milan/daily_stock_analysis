# -*- coding: utf-8 -*-

import json
import unittest
from unittest.mock import Mock

from src.agent.agents.recommendation_risk_agent import RecommendationRiskAgent
from src.agent.protocols import AgentContext


class RecommendationRiskAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = RecommendationRiskAgent(tool_registry=Mock(), llm_adapter=Mock())
        self.ctx = AgentContext(
            stock_code="600519",
            stock_name="Moutai",
            query="risk check",
            data={
                "trend_result": {
                    "support_levels": [98.0, 95.0],
                    "volume_ratio_5d": 1.1,
                    "rsi_status": "NEUTRAL",
                },
                "quote": {"price": 100.0, "volume_ratio": 1.0, "turnover_rate": 2.8},
            },
        )

    def test_system_prompt_and_build_user_message_include_guidance(self) -> None:
        prompt = self.agent.system_prompt(self.ctx)
        message = self.agent.build_user_message(self.ctx)
        payload = json.loads(message)

        self.assertIn("Base score starts at 50", prompt)
        self.assertIn("guided_preview", payload)
        self.assertIn("risk_context", payload)

    def test_post_process_parses_payload_and_normalizes_outputs(self) -> None:
        raw_text = json.dumps(
            {
                "signal": "high_risk",
                "confidence": 70,
                "reasoning": "Turnover is elevated.",
                "key_levels": {"nearest_support": 98, "support_distance_pct": 2.04},
                "raw_data": {"score": 41},
            }
        )
        opinion = self.agent.post_process(self.ctx, raw_text)
        assert opinion is not None

        self.assertEqual(opinion.signal, "sell")
        self.assertEqual(opinion.confidence, 0.7)
        self.assertEqual(opinion.key_levels["nearest_support"], 98.0)
        self.assertIn("guided_preview", opinion.raw_data)

    def test_post_process_uses_guided_fallback_when_payload_invalid(self) -> None:
        opinion = self.agent.post_process(self.ctx, "not-json-response")
        assert opinion is not None

        self.assertIn(
            opinion.signal, {"strong_buy", "buy", "hold", "sell", "strong_sell"}
        )
        self.assertIn("risk_context", opinion.raw_data)
        self.assertIn("score_0_100", opinion.raw_data)


if __name__ == "__main__":
    unittest.main()
