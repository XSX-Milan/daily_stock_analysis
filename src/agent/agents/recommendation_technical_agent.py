# -*- coding: utf-8 -*-
"""Recommendation technical agent based on trend-analysis context data."""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion, Signal


class RecommendationTechnicalAgent(BaseAgent):
    agent_name = "recommendation_technical"

    _TREND_BASE_SCORES: Dict[str, float] = {
        "STRONG_BULL": 90.0,
        "BULL": 75.0,
        "WEAK_BULL": 60.0,
        "CONSOLIDATION": 45.0,
        "WEAK_BEAR": 30.0,
        "BEAR": 15.0,
        "STRONG_BEAR": 5.0,
    }

    _MACD_ADJUSTMENTS: Dict[str, float] = {
        "GOLDEN_CROSS_ZERO": 15.0,
        "GOLDEN_CROSS": 15.0,
        "DEATH_CROSS": -15.0,
    }

    _RSI_ADJUSTMENTS: Dict[str, float] = {
        "OVERBOUGHT": -10.0,
        "OVERSOLD": -10.0,
        "WEAK": 10.0,
        "NEUTRAL": 10.0,
        "STRONG_BUY": 10.0,
    }

    _BUY_SIGNAL_BONUS: Dict[str, float] = {
        "STRONG_BUY": 15.0,
        "BUY": 10.0,
        "HOLD": 5.0,
    }

    _UPTREND_STATUSES = {"STRONG_BULL", "BULL", "WEAK_BULL"}

    def system_prompt(self, ctx: AgentContext) -> str:
        return (
            "You are a technical recommendation analyst for stock selection. "
            "Evaluate trend_result data and produce ONE strict JSON object.\n\n"
            "Use this rule guidance from legacy technical scoring (guidance only):\n"
            "1) Trend base score:\n"
            "   STRONG_BULL=90, BULL=75, WEAK_BULL=60, CONSOLIDATION=45, "
            "WEAK_BEAR=30, BEAR=15, STRONG_BEAR=5.\n"
            "2) MACD adjustment: GOLDEN_CROSS_ZERO or GOLDEN_CROSS +15, "
            "DEATH_CROSS -15, otherwise 0.\n"
            "3) RSI adjustment: OVERBOUGHT or OVERSOLD -10; WEAK/NEUTRAL/STRONG_BUY +10; "
            "otherwise 0.\n"
            "4) Volume adjustment: if trend is STRONG_BULL/BULL/WEAK_BULL and volume_ratio_5d>1.2, +10; else 0.\n"
            "5) Buy-signal bonus: STRONG_BUY +15, BUY +10, HOLD +5, else 0.\n"
            "6) Clamp guidance score to [0, 100], then map to signal:\n"
            "   >=85 strong_buy; >=65 buy; >=45 hold; >=25 sell; else strong_sell.\n\n"
            "Output schema (valid JSON only):\n"
            "{\n"
            '  "signal": "strong_buy|buy|hold|sell|strong_sell",\n'
            '  "confidence": <number 0-100>,\n'
            '  "reasoning": "short explanation",\n'
            '  "key_levels": {"support": <number>, "resistance": <number>},\n'
            '  "rule_trace": {"trend_base": <number>, "macd_adjustment": <number>, '
            '"rsi_adjustment": <number>, "volume_adjustment": <number>, "buy_signal_bonus": <number>, '
            '"guided_score": <number>}\n'
            "}\n"
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        trend_payload = self._extract_trend_payload(ctx.data)
        prompt_payload = {
            "stock_code": ctx.stock_code,
            "stock_name": ctx.stock_name,
            "query": ctx.query,
            "trend_result": trend_payload,
            "rule_hint_preview": self._rule_hint_preview(trend_payload),
            "task": "Provide technical recommendation JSON based on trend_result.",
        }
        return json.dumps(prompt_payload, ensure_ascii=False, default=str, indent=2)

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        payload = self._try_parse_json(raw_text)

        signal_value = self._normalize_signal(payload.get("signal", "hold"))
        confidence_percent = self._clamp_0_100(payload.get("confidence", 55.0))

        reasoning = str(
            payload.get("reasoning", "Technical trend review completed.")
        ).strip()
        if not reasoning:
            reasoning = "Technical trend review completed."

        key_levels = payload.get("key_levels", {})
        if not isinstance(key_levels, dict):
            key_levels = {}

        clean_levels = self._clean_key_levels(key_levels)
        clean_levels.setdefault("guided_score", round(confidence_percent, 2))

        return AgentOpinion(
            signal=signal_value.value,
            confidence=confidence_percent / 100.0,
            reasoning=reasoning,
            key_levels=clean_levels,
            raw_data={
                "confidence_percent": confidence_percent,
                "parsed_payload": payload,
            },
        )

    def _extract_trend_payload(self, data: Mapping[str, Any]) -> Dict[str, Any]:
        raw = data.get("trend_result") or data.get("technical") or {}

        if isinstance(raw, Mapping):
            return dict(raw)

        if hasattr(raw, "to_dict"):
            try:
                converted = raw.to_dict()
                if isinstance(converted, Mapping):
                    return dict(converted)
            except Exception:
                return {"raw": str(raw)}

        return {"raw": str(raw)} if raw else {}

    def _rule_hint_preview(self, trend_payload: Mapping[str, Any]) -> Dict[str, float]:
        trend_key = self._enum_name(trend_payload.get("trend_status"))
        macd_key = self._enum_name(trend_payload.get("macd_status"))
        rsi_key = self._enum_name(trend_payload.get("rsi_status"))
        buy_key = self._enum_name(trend_payload.get("buy_signal"))
        volume_ratio = self._to_float(trend_payload.get("volume_ratio_5d"), 0.0) or 0.0

        trend_base = self._TREND_BASE_SCORES.get(trend_key, 45.0)
        macd_adjustment = self._MACD_ADJUSTMENTS.get(macd_key, 0.0)
        rsi_adjustment = self._RSI_ADJUSTMENTS.get(rsi_key, 0.0)
        volume_adjustment = (
            10.0 if trend_key in self._UPTREND_STATUSES and volume_ratio > 1.2 else 0.0
        )
        buy_signal_bonus = self._BUY_SIGNAL_BONUS.get(buy_key, 0.0)

        guided_score = self._clamp_0_100(
            trend_base
            + macd_adjustment
            + rsi_adjustment
            + volume_adjustment
            + buy_signal_bonus
        )
        return {
            "trend_base": trend_base,
            "macd_adjustment": macd_adjustment,
            "rsi_adjustment": rsi_adjustment,
            "volume_adjustment": volume_adjustment,
            "buy_signal_bonus": buy_signal_bonus,
            "guided_score": guided_score,
        }

    def _try_parse_json(self, raw_text: str) -> Dict[str, Any]:
        text = (raw_text or "").strip()
        if not text:
            return {}

        try:
            loaded = json.loads(text)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}

        try:
            loaded = json.loads(text[start : end + 1])
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _normalize_signal(self, value: Any) -> Signal:
        signal_str = str(value or "").strip().lower()
        if signal_str in {member.value for member in Signal}:
            return Signal(signal_str)

        aliases = {
            "strong buy": Signal.STRONG_BUY,
            "buy": Signal.BUY,
            "hold": Signal.HOLD,
            "neutral": Signal.HOLD,
            "sell": Signal.SELL,
            "strong sell": Signal.STRONG_SELL,
        }
        return aliases.get(signal_str, Signal.HOLD)

    def _clean_key_levels(self, levels: Mapping[str, Any]) -> Dict[str, float]:
        cleaned: Dict[str, float] = {}
        for key in ("support", "resistance", "stop_loss", "target", "guided_score"):
            if key in levels:
                val = self._to_float(levels.get(key), None)
                if val is not None:
                    cleaned[key] = val
        return cleaned

    @staticmethod
    def _to_float(value: Any, default: Optional[float]) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_0_100(value: Any) -> float:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(100.0, num))

    @staticmethod
    def _enum_name(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "name"):
            return str(getattr(value, "name"))
        text = str(value)
        if "." in text:
            return text.rsplit(".", 1)[-1]
        return text.strip().upper()
