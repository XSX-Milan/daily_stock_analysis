# -*- coding: utf-8 -*-
"""Recommendation sentiment agent built on the BaseAgent loop."""

from __future__ import annotations

import re
from typing import Any

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion, Signal


class RecommendationSentimentAgent(BaseAgent):
    agent_name = "recommendation_sentiment"

    def system_prompt(self, ctx: AgentContext) -> str:
        del ctx
        return (
            "You are a financial sentiment analyst for stock recommendations.\n"
            "Assess the provided recent news and sentiment hints for one stock.\n"
            "Generate a sentiment score in range 0-100 where 0 is extremely bearish, "
            "50 is neutral, and 100 is extremely bullish.\n"
            "Be stable, concise, and avoid overreacting to a single headline.\n"
            "Output format (plain text):\n"
            "SENTIMENT_SCORE: <number between 0 and 100>\n"
            "RATIONALE: <short explanation>"
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        news_items = self._extract_news_items(ctx)
        sentiment_signals = ctx.get_data("sentiment_signals", [])

        lines: list[str] = []
        for idx, item in enumerate(news_items[:8], start=1):
            title = str(item.get("title") or item.get("headline") or "").strip()
            summary = str(item.get("summary") or item.get("content") or "").strip()
            source = str(item.get("source") or "").strip()
            published_at = str(
                item.get("published_at")
                or item.get("publish_time")
                or item.get("time")
                or ""
            ).strip()

            merged = title
            if summary:
                merged = f"{merged}; {summary}" if merged else summary
            if source:
                merged = (
                    f"{merged} (source: {source})" if merged else f"source: {source}"
                )
            if published_at:
                merged = (
                    f"{merged} [time: {published_at}]"
                    if merged
                    else f"time: {published_at}"
                )

            if merged:
                lines.append(f"{idx}. {merged}")

        if not lines:
            lines.append("1. No usable news text available.")

        signals_text = "None"
        if sentiment_signals:
            signals_text = "\n".join(
                f"- {str(signal)}" for signal in sentiment_signals[:10]
            )

        stock_label = (ctx.stock_name or "").strip()
        if stock_label:
            stock_label = f"{stock_label} ({ctx.stock_code})"
        else:
            stock_label = ctx.stock_code or "UNKNOWN"

        news_block = "\n".join(lines)
        return (
            f"Stock: {stock_label}\n"
            "Task: infer one stable market sentiment score from the news payload.\n"
            "Recent news:\n"
            f"{news_block}\n\n"
            "Additional sentiment signals:\n"
            f"{signals_text}\n\n"
            "Important: return SENTIMENT_SCORE first."
        )

    def post_process(self, ctx: AgentContext, raw_text: str) -> AgentOpinion:
        news_items = self._extract_news_items(ctx)

        try:
            parsed_score = self._parse_sentiment_score(raw_text)
            score = self._clamp_score(parsed_score)
            fallback = False
        except Exception:
            score = 50.0
            parsed_score = 50.0
            fallback = True

        signal = self._score_to_signal(score)
        confidence = self._score_to_confidence(score, fallback)

        return AgentOpinion(
            signal=signal.value,
            confidence=confidence,
            reasoning=(raw_text or "").strip()
            or "Neutral fallback because sentiment parsing failed.",
            raw_data={
                "dimension": "sentiment",
                "news_count": len(news_items),
                "parsed_score": round(parsed_score, 2),
                "score_0_100": round(score, 2),
                "fallback": fallback,
            },
        )

    @staticmethod
    def _extract_news_items(ctx: AgentContext) -> list[dict[str, Any]]:
        candidates = (
            ctx.get_data("news_items"),
            ctx.get_data("news"),
            ctx.get_data("recent_news"),
        )
        for candidate in candidates:
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return []

    @staticmethod
    def _parse_sentiment_score(response: str) -> float:
        text = (response or "").strip()
        if not text:
            raise ValueError("Empty sentiment response")

        direct_number = re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text)
        if direct_number:
            return float(direct_number.group(0))

        labeled_number = re.search(
            r"(?:sentiment_score|score|sentiment|评分|分数)\s*[:=：]?\s*([+-]?\d+(?:\.\d+)?)",
            text,
            flags=re.IGNORECASE,
        )
        if labeled_number:
            return float(labeled_number.group(1))

        generic_number = re.search(r"[+-]?\d+(?:\.\d+)?", text)
        if generic_number:
            return float(generic_number.group(0))

        raise ValueError(f"Unable to parse sentiment score from response: {text}")

    @staticmethod
    def _clamp_score(score: float) -> float:
        return max(0.0, min(100.0, float(score)))

    @staticmethod
    def _score_to_signal(score: float) -> Signal:
        if score >= 80:
            return Signal.STRONG_BUY
        if score >= 60:
            return Signal.BUY
        if score >= 40:
            return Signal.HOLD
        if score >= 20:
            return Signal.SELL
        return Signal.STRONG_SELL

    @staticmethod
    def _score_to_confidence(score: float, fallback: bool) -> float:
        if fallback:
            return 0.5
        distance = abs(score - 50.0) / 50.0
        return max(0.35, min(0.95, round(0.35 + distance * 0.6, 4)))
