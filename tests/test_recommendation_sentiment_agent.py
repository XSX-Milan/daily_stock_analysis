# -*- coding: utf-8 -*-

import unittest
from unittest.mock import Mock

from src.agent.agents.recommendation_sentiment_agent import RecommendationSentimentAgent
from src.agent.protocols import AgentContext


class RecommendationSentimentAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = RecommendationSentimentAgent(
            tool_registry=Mock(), llm_adapter=Mock()
        )

    def test_system_prompt_and_build_user_message_include_news_context(self) -> None:
        ctx = AgentContext(
            stock_code="600519",
            stock_name="Moutai",
            data={
                "news_items": [
                    {"title": "Strong sales", "summary": "Revenue grew", "source": "X"}
                ],
                "sentiment_signals": ["fund inflow"],
            },
        )
        prompt = self.agent.system_prompt(ctx)
        message = self.agent.build_user_message(ctx)

        self.assertIn("SENTIMENT_SCORE", prompt)
        self.assertIn("Strong sales", message)
        self.assertIn("fund inflow", message)

    def test_build_user_message_handles_missing_news(self) -> None:
        ctx = AgentContext(stock_code="AAPL", data={})
        message = self.agent.build_user_message(ctx)
        self.assertIn("No usable news text available", message)

    def test_post_process_parses_sentiment_score_and_maps_signal(self) -> None:
        ctx = AgentContext(stock_code="AAPL", data={"news_items": [{"title": "t"}]})
        opinion = self.agent.post_process(
            ctx,
            "SENTIMENT_SCORE: 82\nRATIONALE: positive earnings outlook",
        )

        self.assertEqual(opinion.signal, "strong_buy")
        self.assertGreater(opinion.confidence, 0.7)
        self.assertEqual(opinion.raw_data["score_0_100"], 82.0)

    def test_post_process_uses_neutral_fallback_when_score_unparsable(self) -> None:
        ctx = AgentContext(stock_code="AAPL", data={})
        opinion = self.agent.post_process(ctx, "No numeric score provided")

        self.assertEqual(opinion.signal, "hold")
        self.assertEqual(opinion.confidence, 0.5)
        self.assertTrue(opinion.raw_data["fallback"])


if __name__ == "__main__":
    unittest.main()
