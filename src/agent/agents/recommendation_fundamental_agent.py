# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion, Signal
from src.agent.runner import try_parse_json


class RecommendationFundamentalAgent(BaseAgent):
    agent_name = "recommendation_fundamental"

    def system_prompt(self, ctx: AgentContext) -> str:
        return (
            "You are a fundamental valuation analyst for stock recommendation scoring. "
            "Use only provided context data and avoid fabricating numbers.\n\n"
            "Legacy heuristic guidance to follow (ported from old scorer):\n"
            "1) PE score rules: PE<=0 => 10, 0<PE<15 => 80, 15<=PE<=25 => 60, "
            "25<PE<=40 => 40, PE>40 => 20.\n"
            "2) PB score rules: PB<1 => 85, 1<=PB<=2 => 70, 2<PB<=4 => 50, PB>4 => 30.\n"
            "3) Market-cap bonus: total_mv>100B => +10, 10B<=total_mv<=100B => +5, "
            "otherwise +0.\n"
            "4) Composite valuation score reference: "
            "pe_score*0.50 + pb_score*0.35 + (market_cap_bonus*10)*0.15.\n"
            "5) Map score to signal with balanced judgment: >=80 strong_buy, >=60 buy, "
            ">=40 hold, >=20 sell, else strong_sell.\n\n"
            "Output MUST be strict JSON with fields: "
            "signal, confidence, reasoning, key_levels.\n"
            "- signal: one of strong_buy/buy/hold/sell/strong_sell\n"
            "- confidence: numeric in [0,100] or [0,1]\n"
            "- reasoning: concise explanation\n"
            "- key_levels: dict with pe_ratio, pb_ratio, total_mv when available"
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        valuation = self._extract_valuation(ctx)
        payload = {
            "stock_code": ctx.stock_code,
            "stock_name": ctx.stock_name,
            "query": ctx.query,
            "valuation_context": valuation,
        }
        return (
            "Please evaluate the stock's fundamental valuation quality using PE/PB/market-cap context.\n"
            "Provide your output as strict JSON only.\n"
            f"Input payload:\n{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        parsed = try_parse_json(raw_text) or {}
        signal = self._normalize_signal(parsed.get("signal"))
        confidence = self._normalize_confidence(parsed.get("confidence"))
        reasoning = str(parsed.get("reasoning") or "").strip()
        if not reasoning:
            reasoning = raw_text.strip()[:600]
        if not signal:
            signal = self._signal_from_text(raw_text)
        if not signal:
            signal = Signal.HOLD

        key_levels = self._extract_key_levels(parsed.get("key_levels"), ctx)
        return AgentOpinion(
            agent_name=self.agent_name,
            signal=signal.value,
            confidence=confidence,
            reasoning=reasoning,
            key_levels=key_levels,
            raw_data={
                "parsed": parsed,
                "valuation_context": self._extract_valuation(ctx),
            },
        )

    def _extract_valuation(self, ctx: AgentContext) -> dict[str, Any]:
        valuation: dict[str, Any] = {}

        for key in ("valuation_data", "fundamental_data", "quote"):
            source = ctx.get_data(key)
            if source is None:
                continue
            source_map = self._to_mapping(source)
            if source_map:
                self._merge_valuation_fields(valuation, source_map)

        direct_pe = ctx.get_data("pe_ratio")
        direct_pb = ctx.get_data("pb_ratio")
        direct_mv = ctx.get_data("total_mv") or ctx.get_data("market_cap")
        if direct_pe is not None:
            valuation.setdefault("pe_ratio", direct_pe)
        if direct_pb is not None:
            valuation.setdefault("pb_ratio", direct_pb)
        if direct_mv is not None:
            valuation.setdefault("total_mv", direct_mv)

        return valuation

    @staticmethod
    def _to_mapping(value: Any) -> Optional[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            return value
        if hasattr(value, "__dict__"):
            return {k: v for k, v in vars(value).items() if not k.startswith("_")}
        return None

    @staticmethod
    def _merge_valuation_fields(
        target: dict[str, Any], source: Mapping[str, Any]
    ) -> None:
        pe = source.get("pe_ratio")
        pb = source.get("pb_ratio")
        mv = source.get("total_mv") or source.get("market_cap")
        if pe is not None and "pe_ratio" not in target:
            target["pe_ratio"] = pe
        if pb is not None and "pb_ratio" not in target:
            target["pb_ratio"] = pb
        if mv is not None and "total_mv" not in target:
            target["total_mv"] = mv

    def _extract_key_levels(
        self,
        parsed_key_levels: Any,
        ctx: AgentContext,
    ) -> dict[str, float]:
        key_levels: dict[str, float] = {}
        source_map = parsed_key_levels if isinstance(parsed_key_levels, Mapping) else {}
        for key in ("pe_ratio", "pb_ratio", "total_mv"):
            value = source_map.get(key)
            numeric = self._as_float(value)
            if numeric is not None:
                key_levels[key] = numeric

        if key_levels:
            return key_levels

        valuation = self._extract_valuation(ctx)
        for key in ("pe_ratio", "pb_ratio", "total_mv"):
            numeric = self._as_float(valuation.get(key))
            if numeric is not None:
                key_levels[key] = numeric
        return key_levels

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_signal(value: Any) -> Optional[Signal]:
        if value is None:
            return None
        text = str(value).strip().lower()
        alias = {
            "strong_buy": Signal.STRONG_BUY,
            "strongbuy": Signal.STRONG_BUY,
            "buy": Signal.BUY,
            "hold": Signal.HOLD,
            "neutral": Signal.HOLD,
            "sell": Signal.SELL,
            "strong_sell": Signal.STRONG_SELL,
            "strongsell": Signal.STRONG_SELL,
        }
        if text in alias:
            return alias[text]
        try:
            return Signal(text)
        except ValueError:
            return None

    @staticmethod
    def _signal_from_text(raw_text: str) -> Optional[Signal]:
        lowered = raw_text.lower()
        if "strong_sell" in lowered or "strong sell" in lowered:
            return Signal.STRONG_SELL
        if "strong_buy" in lowered or "strong buy" in lowered:
            return Signal.STRONG_BUY
        if re.search(r"\bbuy\b", lowered):
            return Signal.BUY
        if re.search(r"\bsell\b", lowered):
            return Signal.SELL
        if re.search(r"\bhold\b|\bneutral\b", lowered):
            return Signal.HOLD
        return None

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        if value is None:
            return 0.5
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.5

        if numeric > 1.0:
            numeric = numeric / 100.0
        return max(0.0, min(1.0, numeric))
