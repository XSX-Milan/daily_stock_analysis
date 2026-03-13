# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion, Signal


class RecommendationMacroAgent(BaseAgent):
    agent_name = "recommendation_macro"

    def system_prompt(self, ctx: AgentContext) -> str:
        _ = ctx
        return (
            "You are a macro strategist for stock recommendation scoring. "
            "Use only provided index snapshots and output strict JSON with fields: "
            "signal, confidence, reasoning, key_levels, raw_data.\n\n"
            "Scoring guidance from the legacy macro scorer (convert to judgment, do not do rigid formula copy):\n"
            "1) Trend base from index price vs MA20 across tracked indices:\n"
            "   - all above MA20 => bull bias\n"
            "   - all below/equal MA20 => bear bias\n"
            "   - mixed => neutral bias\n"
            "2) Momentum tilt from average change_pct:\n"
            "   - > 0 supports risk-on\n"
            "   - < -1 supports risk-off\n"
            "3) MA alignment bonus when price > MA5 > MA20 > MA60 on more indices.\n"
            "4) Produce one signal in: strong_buy, buy, hold, sell, strong_sell.\n"
            "5) confidence must be a number in [0, 1].\n"
            "6) Keep reasoning concise and evidence-based; avoid fabrication."
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        code = ctx.stock_code or str(ctx.data.get("code", ""))
        region = ctx.data.get("region")
        index_data = self._pick_index_data(ctx.data)

        payload: Dict[str, Any] = {
            "task": "Assess macro environment for recommendation scoring.",
            "stock_code": code,
            "stock_name": ctx.stock_name,
            "region": getattr(region, "value", region),
            "index_data": index_data,
            "focus": {
                "trend": "price vs MA20",
                "momentum": "average change_pct",
                "ma_alignment": "price > MA5 > MA20 > MA60 ratio",
            },
            "output_contract": {
                "signal": [
                    Signal.STRONG_BUY.value,
                    Signal.BUY.value,
                    Signal.HOLD.value,
                    Signal.SELL.value,
                    Signal.STRONG_SELL.value,
                ],
                "confidence": "float in [0, 1]",
                "reasoning": "short evidence summary",
                "key_levels": {"support": 0.0, "resistance": 0.0},
                "raw_data": {
                    "trend": "bull/neutral/bear",
                    "average_change_pct": 0.0,
                    "ma_alignment_ratio": 0.0,
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        parsed = self._extract_json(raw_text)

        if parsed:
            signal_value = self._normalize_signal(parsed.get("signal"))
            confidence_value = self._normalize_confidence(parsed.get("confidence"))
            reasoning = str(parsed.get("reasoning") or raw_text).strip()
            key_levels = parsed.get("key_levels")
            raw_data = parsed.get("raw_data")
        else:
            signal_value = self._infer_signal_from_text(raw_text)
            confidence_value = 0.5
            reasoning = raw_text.strip()
            key_levels = {}
            raw_data = {}

        if signal_value is None:
            signal_value = Signal.HOLD.value

        if not isinstance(key_levels, dict):
            key_levels = {}
        if not isinstance(raw_data, dict):
            raw_data = {}

        raw_data.setdefault("source", "recommendation_macro_agent")
        raw_data.setdefault("stock_code", ctx.stock_code)

        return AgentOpinion(
            signal=signal_value,
            confidence=confidence_value,
            reasoning=reasoning,
            key_levels=self._coerce_key_levels(key_levels),
            raw_data=raw_data,
        )

    @staticmethod
    def _pick_index_data(data: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("index_data", "market_index_data", "indices", "market_indices"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _extract_json(raw_text: str) -> Optional[Dict[str, Any]]:
        text = raw_text.strip()
        if not text:
            return None

        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()

        try:
            loaded = json.loads(text)
            return loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    loaded = json.loads(text[start : end + 1])
                    return loaded if isinstance(loaded, dict) else None
                except json.JSONDecodeError:
                    return None
            return None

    @staticmethod
    def _normalize_signal(value: Any) -> Optional[str]:
        if value is None:
            return None
        candidate = str(value).strip().lower()
        aliases = {
            "strong buy": Signal.STRONG_BUY.value,
            "strong_buy": Signal.STRONG_BUY.value,
            "buy": Signal.BUY.value,
            "hold": Signal.HOLD.value,
            "neutral": Signal.HOLD.value,
            "sell": Signal.SELL.value,
            "strong sell": Signal.STRONG_SELL.value,
            "strong_sell": Signal.STRONG_SELL.value,
            "risk_on": Signal.BUY.value,
            "risk_off": Signal.SELL.value,
        }
        candidate = aliases.get(candidate, candidate)
        try:
            return Signal(candidate).value
        except ValueError:
            return None

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.5

        if confidence > 1:
            confidence = confidence / 100.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _infer_signal_from_text(raw_text: str) -> str:
        lower_text = raw_text.lower()
        if "strong_sell" in lower_text or "strong sell" in lower_text:
            return Signal.STRONG_SELL.value
        if "strong_buy" in lower_text or "strong buy" in lower_text:
            return Signal.STRONG_BUY.value
        if "sell" in lower_text or "bear" in lower_text or "risk-off" in lower_text:
            return Signal.SELL.value
        if "buy" in lower_text or "bull" in lower_text or "risk-on" in lower_text:
            return Signal.BUY.value
        return Signal.HOLD.value

    @staticmethod
    def _coerce_key_levels(levels: Dict[str, Any]) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for key, value in levels.items():
            try:
                result[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return result
