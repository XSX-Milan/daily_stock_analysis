# -*- coding: utf-8 -*-
"""Recommendation risk agent with legacy risk-rule guidance."""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion, Signal
from src.agent.runner import try_parse_json


class RecommendationRiskAgent(BaseAgent):
    agent_name = "recommendation_risk"

    def system_prompt(self, ctx: AgentContext) -> str:
        _ = ctx
        return (
            "You are a risk analyst for stock recommendation scoring. "
            "Use only the provided context and return strict JSON.\n\n"
            "Legacy risk guidance (ported from prior deterministic scorer):\n"
            "1) Base score starts at 50 (higher means safer entry context).\n"
            "2) Support-distance adjustment: <=2% +20, <=5% +10, <=8% +3, >8% -15.\n"
            "3) Historical volume-ratio (5d) adjustment: 0.8~1.5 +10, <0.6 -8, >2.0 -12, else 0.\n"
            "4) Realtime volume-ratio adjustment: 0.8~1.8 +8, >3.0 -18, >2.2 -10, <0.5 -8, else 0.\n"
            "5) RSI-zone adjustment: OVERBOUGHT -20, NEUTRAL +10, STRONG_BUY +4, OVERSOLD +6, WEAK -4.\n"
            "6) Turnover adjustment: <=3 +8, <=8 +4, <=15 -8, <=20 -14, >20 -20.\n"
            "7) Clamp score to [0,100], then map to signal: >=80 strong_buy, >=65 buy, >=45 hold, >=25 sell, else strong_sell.\n"
            "8) Output JSON fields: signal, confidence, reasoning, key_levels, raw_data.\n"
            "9) confidence may be returned as 0..1 or 0..100."
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        risk_context = self._extract_risk_context(ctx)
        guided_preview = self._guided_score_preview(risk_context)
        payload = {
            "task": "Assess recommendation risk using support, volume, RSI zone, and turnover context.",
            "stock_code": ctx.stock_code,
            "stock_name": ctx.stock_name,
            "query": ctx.query,
            "risk_context": risk_context,
            "guided_preview": guided_preview,
            "output_contract": {
                "signal": [
                    Signal.STRONG_BUY.value,
                    Signal.BUY.value,
                    Signal.HOLD.value,
                    Signal.SELL.value,
                    Signal.STRONG_SELL.value,
                ],
                "confidence": "number in 0..1 or 0..100",
                "reasoning": "short evidence-based explanation",
                "key_levels": {
                    "nearest_support": 0.0,
                    "support_distance_pct": 0.0,
                },
                "raw_data": {
                    "score_0_100": 0.0,
                    "support_adjustment": 0.0,
                    "historical_volume_adjustment": 0.0,
                    "realtime_volume_adjustment": 0.0,
                    "rsi_adjustment": 0.0,
                    "turnover_adjustment": 0.0,
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        parsed_raw = try_parse_json(raw_text)
        parsed: Dict[str, Any] = parsed_raw if isinstance(parsed_raw, dict) else {}
        risk_context = self._extract_risk_context(ctx)
        preview = self._guided_score_preview(risk_context)

        score_0_100 = self._score_from_payload(parsed, preview["guided_score"])
        signal = self._normalize_signal(parsed.get("signal"), score_0_100)
        confidence = self._normalize_confidence(parsed.get("confidence"), score_0_100)

        reasoning = str(parsed.get("reasoning") or "").strip()
        if not reasoning:
            reasoning = (raw_text or "").strip()[:600] or "Risk review completed."

        key_levels = self._extract_key_levels(parsed.get("key_levels"), risk_context)
        raw_data: Dict[str, Any] = {}
        raw_data_value = parsed.get("raw_data")
        if isinstance(raw_data_value, dict):
            raw_data = {str(k): v for k, v in raw_data_value.items()}
        raw_data.update(
            {
                "score_0_100": round(score_0_100, 2),
                "confidence_percent": round(confidence * 100.0, 2),
                "guided_preview": preview,
                "risk_context": risk_context,
                "parsed_payload": parsed,
            }
        )

        return AgentOpinion(
            signal=signal.value,
            confidence=confidence,
            reasoning=reasoning,
            key_levels=key_levels,
            raw_data=raw_data,
        )

    def _extract_risk_context(self, ctx: AgentContext) -> Dict[str, Any]:
        trend_data = self._to_mapping(
            ctx.get_data("trend_result") or ctx.get_data("technical") or {}
        )
        quote_data = self._to_mapping(
            ctx.get_data("quote") or ctx.get_data("realtime_quote") or {}
        )
        risk_data = self._to_mapping(
            ctx.get_data("risk") or ctx.get_data("risk_context") or {}
        )

        support_levels = risk_data.get("support_levels")
        if not isinstance(support_levels, list):
            support_levels = trend_data.get("support_levels")
        if not isinstance(support_levels, list):
            support_levels = []

        price = self._to_float(quote_data.get("price"), None)
        nearest_support = self._to_float(risk_data.get("nearest_support"), None)
        if nearest_support is None:
            nearest_support = self._nearest_support(price, support_levels)

        support_distance_pct = self._to_float(
            risk_data.get("support_distance_pct"), None
        )
        if support_distance_pct is None:
            support_distance_pct = self._support_distance_pct(price, nearest_support)

        return {
            "price": price,
            "support_levels": support_levels,
            "nearest_support": nearest_support,
            "support_distance_pct": support_distance_pct,
            "volume_ratio_5d": self._to_float(
                risk_data.get("volume_ratio_5d") or trend_data.get("volume_ratio_5d"),
                None,
            ),
            "volume_ratio": self._to_float(
                risk_data.get("volume_ratio") or quote_data.get("volume_ratio"), None
            ),
            "rsi_status": self._enum_name(
                risk_data.get("rsi_status") or trend_data.get("rsi_status")
            ),
            "turnover_rate": self._to_float(
                risk_data.get("turnover_rate") or quote_data.get("turnover_rate"), None
            ),
        }

    def _guided_score_preview(
        self, risk_context: Mapping[str, Any]
    ) -> Dict[str, float]:
        support_adjustment = self._support_adjustment(
            self._to_float(risk_context.get("support_distance_pct"), None)
        )
        historical_volume_adjustment = self._historical_volume_adjustment(
            self._to_float(risk_context.get("volume_ratio_5d"), None)
        )
        realtime_volume_adjustment = self._realtime_volume_adjustment(
            self._to_float(risk_context.get("volume_ratio"), None)
        )
        rsi_adjustment = self._rsi_adjustment(
            self._enum_name(risk_context.get("rsi_status"))
        )
        turnover_adjustment = self._turnover_adjustment(
            self._to_float(risk_context.get("turnover_rate"), None)
        )

        guided_score = self._clamp_0_100(
            50.0
            + support_adjustment
            + historical_volume_adjustment
            + realtime_volume_adjustment
            + rsi_adjustment
            + turnover_adjustment
        )
        return {
            "support_adjustment": support_adjustment,
            "historical_volume_adjustment": historical_volume_adjustment,
            "realtime_volume_adjustment": realtime_volume_adjustment,
            "rsi_adjustment": rsi_adjustment,
            "turnover_adjustment": turnover_adjustment,
            "guided_score": round(guided_score, 2),
        }

    def _score_from_payload(self, parsed: Mapping[str, Any], fallback: float) -> float:
        candidate = parsed.get("score")
        if candidate is None:
            candidate = parsed.get("score_0_100")
        if candidate is None:
            candidate = parsed.get("confidence")
        numeric = self._to_float(candidate, None)
        if numeric is None:
            return self._clamp_0_100(fallback)
        if 0.0 <= numeric <= 1.0:
            numeric *= 100.0
        return self._clamp_0_100(numeric)

    def _normalize_signal(self, value: Any, score_0_100: float) -> Signal:
        aliases = {
            "strong buy": Signal.STRONG_BUY,
            "strong_buy": Signal.STRONG_BUY,
            "buy": Signal.BUY,
            "hold": Signal.HOLD,
            "neutral": Signal.HOLD,
            "sell": Signal.SELL,
            "strong sell": Signal.STRONG_SELL,
            "strong_sell": Signal.STRONG_SELL,
            "low_risk": Signal.BUY,
            "high_risk": Signal.SELL,
        }
        if value is not None:
            normalized = aliases.get(str(value).strip().lower())
            if normalized is not None:
                return normalized
            try:
                return Signal(str(value).strip().lower())
            except ValueError:
                pass

        if score_0_100 >= 80:
            return Signal.STRONG_BUY
        if score_0_100 >= 65:
            return Signal.BUY
        if score_0_100 >= 45:
            return Signal.HOLD
        if score_0_100 >= 25:
            return Signal.SELL
        return Signal.STRONG_SELL

    def _normalize_confidence(self, value: Any, score_0_100: float) -> float:
        numeric = self._to_float(value, None)
        if numeric is None:
            return self._clamp_0_1(score_0_100 / 100.0)
        if numeric > 1.0:
            numeric = numeric / 100.0
        return self._clamp_0_1(numeric)

    def _extract_key_levels(
        self,
        parsed_key_levels: Any,
        risk_context: Mapping[str, Any],
    ) -> Dict[str, float]:
        source = parsed_key_levels if isinstance(parsed_key_levels, Mapping) else {}
        key_levels: Dict[str, float] = {}

        for key in ("support", "resistance", "nearest_support", "support_distance_pct"):
            numeric = self._to_float(source.get(key), None)
            if numeric is not None:
                key_levels[key] = numeric

        if "nearest_support" not in key_levels:
            nearest_support = self._to_float(risk_context.get("nearest_support"), None)
            if nearest_support is not None:
                key_levels["nearest_support"] = nearest_support

        if "support_distance_pct" not in key_levels:
            support_distance_pct = self._to_float(
                risk_context.get("support_distance_pct"), None
            )
            if support_distance_pct is not None:
                key_levels["support_distance_pct"] = support_distance_pct

        return key_levels

    @staticmethod
    def _to_mapping(value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        if hasattr(value, "__dict__"):
            return {k: v for k, v in vars(value).items() if not k.startswith("_")}
        return {}

    @staticmethod
    def _to_float(value: Any, default: Optional[float]) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _nearest_support(price: Optional[float], levels: list[Any]) -> Optional[float]:
        if price is None:
            return None
        candidates = [
            float(level)
            for level in levels
            if isinstance(level, (int, float)) and float(level) > 0
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda level: abs(price - level))

    @staticmethod
    def _support_distance_pct(
        price: Optional[float], support: Optional[float]
    ) -> Optional[float]:
        if price is None or support is None or support <= 0:
            return None
        return abs(price - support) / support * 100.0

    @staticmethod
    def _support_adjustment(distance_pct: Optional[float]) -> float:
        if distance_pct is None:
            return 0.0
        if distance_pct <= 2.0:
            return 20.0
        if distance_pct <= 5.0:
            return 10.0
        if distance_pct <= 8.0:
            return 3.0
        return -15.0

    @staticmethod
    def _historical_volume_adjustment(volume_ratio_5d: Optional[float]) -> float:
        if volume_ratio_5d is None:
            return 0.0
        if 0.8 <= volume_ratio_5d <= 1.5:
            return 10.0
        if volume_ratio_5d < 0.6:
            return -8.0
        if volume_ratio_5d > 2.0:
            return -12.0
        return 0.0

    @staticmethod
    def _realtime_volume_adjustment(volume_ratio: Optional[float]) -> float:
        if volume_ratio is None:
            return 0.0
        if 0.8 <= volume_ratio <= 1.8:
            return 8.0
        if volume_ratio > 3.0:
            return -18.0
        if volume_ratio > 2.2:
            return -10.0
        if volume_ratio < 0.5:
            return -8.0
        return 0.0

    @staticmethod
    def _rsi_adjustment(rsi_status: str) -> float:
        if rsi_status == "OVERBOUGHT":
            return -20.0
        if rsi_status == "NEUTRAL":
            return 10.0
        if rsi_status == "STRONG_BUY":
            return 4.0
        if rsi_status == "OVERSOLD":
            return 6.0
        if rsi_status == "WEAK":
            return -4.0
        return 0.0

    @staticmethod
    def _turnover_adjustment(turnover_rate: Optional[float]) -> float:
        if turnover_rate is None:
            return 0.0
        if turnover_rate <= 3.0:
            return 8.0
        if turnover_rate <= 8.0:
            return 4.0
        if turnover_rate <= 15.0:
            return -8.0
        if turnover_rate <= 20.0:
            return -14.0
        return -20.0

    @staticmethod
    def _enum_name(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "name"):
            return str(getattr(value, "name"))
        text = str(value).strip()
        if "." in text:
            text = text.rsplit(".", 1)[-1]
        return text.upper()

    @staticmethod
    def _clamp_0_100(value: float) -> float:
        return max(0.0, min(100.0, float(value)))

    @staticmethod
    def _clamp_0_1(value: float) -> float:
        return max(0.0, min(1.0, float(value)))
