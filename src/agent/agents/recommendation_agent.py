# -*- coding: utf-8 -*-
"""Unified recommendation agent for per-dimension scoring."""

from __future__ import annotations

import logging
import math
from typing import Any, Iterable, Mapping, Optional

import pandas as pd

from src.agent.agents.base_agent import BaseAgent
from src.agent.memory import AgentMemory
from src.agent.protocols import (
    AgentContext,
    AgentOpinion,
    Signal,
    StageResult,
    StageStatus,
)
from src.agent.agents.decision_agent import DecisionAgent
from src.agent.agents.intel_agent import IntelAgent
from src.agent.agents.portfolio_agent import PortfolioAgent
from src.agent.agents.risk_agent import RiskAgent
from src.agent.agents.technical_agent import TechnicalAgent
from src.recommendation.constants import (
    TECHNICAL_BASE_WEIGHT,
    TECHNICAL_COUNTER_TREND_MA20_BONUS,
    TECHNICAL_COUNTER_TREND_MA20_MAX,
    TECHNICAL_COUNTER_TREND_MA60_BONUS,
    TECHNICAL_COUNTER_TREND_MA60_MAX,
    TECHNICAL_DELEGATED_WEIGHT,
    TECHNICAL_HEAVY_VOLUME_PENALTY_HIGH,
    TECHNICAL_HEAVY_VOLUME_PENALTY_HIGH_SCORE,
    TECHNICAL_HEAVY_VOLUME_PENALTY_LOW_SCORE,
    TECHNICAL_HEAVY_VOLUME_PENALTY_MIN,
    TECHNICAL_MODERATE_VOLUME_DELTA,
    TECHNICAL_MODERATE_VOLUME_MAX,
    TECHNICAL_MODERATE_VOLUME_MIN,
    TECHNICAL_PULLBACK_NEAR_MA10_MAX_ABS,
    TECHNICAL_SHRINK_VOLUME_BONUS,
    TECHNICAL_SHRINK_VOLUME_MAX,
    TECHNICAL_SHRINK_VOLUME_PULLBACK_BONUS,
)
from src.recommendation.market_utils import detect_market_region
from src.recommendation.models import MarketRegion
from src.stock_analyzer import StockTrendAnalyzer


logger = logging.getLogger(__name__)


_DIMENSION_PROFILES: dict[str, dict[str, str]] = {
    "technical": {
        "name": "technical",
        "title": "Technical",
        "focus": "price trend, momentum, and pattern quality",
    },
    "fundamental": {
        "name": "fundamental",
        "title": "Fundamental",
        "focus": "valuation and earnings-quality context",
    },
    "sentiment": {
        "name": "sentiment",
        "title": "Sentiment",
        "focus": "news/event sentiment and narrative stability",
    },
    "macro": {
        "name": "macro",
        "title": "Macro",
        "focus": "index regime and market breadth context",
    },
    "risk": {
        "name": "risk",
        "title": "Risk",
        "focus": "entry risk, downside pressure, and exposure control",
    },
}


class RecommendationAgent(BaseAgent):
    agent_name = "recommendation"
    tool_names = None
    max_steps = 1

    def __init__(
        self,
        tool_registry,
        llm_adapter,
        skill_instructions: str = "",
        dimension: str = "technical",
    ):
        super().__init__(tool_registry, llm_adapter, skill_instructions)
        normalized_dimension = str(dimension or "technical").strip().lower()
        self.dimension = (
            normalized_dimension
            if normalized_dimension in _DIMENSION_PROFILES
            else "technical"
        )
        self.profile = dict(_DIMENSION_PROFILES[self.dimension])
        self.agent_name = f"recommendation_{self.dimension}"
        self._trend_analyzer = StockTrendAnalyzer()
        self._agent_memory = AgentMemory.from_config()

    def system_prompt(self, ctx: AgentContext) -> str:
        del ctx
        return (
            f"You are a {self.profile['title']} recommendation specialist. "
            f"Focus on {self.profile['focus']}. "
            "Return one stable 0-100 score with clear evidence."
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        stock_label = ctx.stock_code or "UNKNOWN"
        if ctx.stock_name:
            stock_label = f"{ctx.stock_name} ({stock_label})"
        return f"Dimension={self.dimension}; stock={stock_label}; query={ctx.query or 'N/A'}"

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        del ctx
        del raw_text
        return None

    def run(self, ctx: AgentContext, progress_callback=None) -> StageResult:
        del progress_callback
        result = StageResult(stage_name=self.agent_name, status=StageStatus.RUNNING)
        try:
            delegated = self._collect_delegated_opinions(ctx)
            trend_score = self._analyze_trend_score(ctx)
            dimension_score = self._dimension_score(ctx, trend_score, delegated)
            raw_confidence = self._confidence_score(ctx, delegated)
            confidence = self._calibrate_confidence(raw_confidence, ctx.stock_code)
            signal = self._score_to_signal(dimension_score)

            opinion = AgentOpinion(
                agent_name=self.agent_name,
                signal=signal,
                confidence=confidence,
                reasoning=self._build_reasoning(
                    ctx, dimension_score, trend_score, delegated
                ),
                key_levels=self._build_key_levels(ctx, trend_score),
                raw_data={
                    "dimension": self.dimension,
                    "score": round(dimension_score, 2),
                    "score_0_100": round(dimension_score, 2),
                    "trend_score": trend_score,
                    "delegated_agents": delegated,
                },
            )
            ctx.add_opinion(opinion)

            result.status = StageStatus.COMPLETED
            result.opinion = opinion
            result.meta["dimension"] = self.dimension
            result.meta["trend_score"] = trend_score
            result.meta["delegate_count"] = len(delegated)
            return result
        except Exception as exc:
            result.status = StageStatus.FAILED
            result.error = str(exc)
            return result

    def _analyze_trend_score(self, ctx: AgentContext) -> float:
        daily_df = self._extract_price_dataframe(ctx)
        if daily_df is not None and not daily_df.empty:
            analyzed = self._trend_analyzer.analyze(
                daily_df, ctx.stock_code or "UNKNOWN"
            )
            return self._clamp_0_100(analyzed.signal_score)

        trend_payload = self._as_mapping(
            ctx.get_data("trend_result") or ctx.get_data("technical") or {}
        )
        for key in ("signal_score", "score", "trend_strength"):
            value = self._to_float(trend_payload.get(key), None)
            if value is not None:
                return self._clamp_0_100(value)
        return 50.0

    def _extract_price_dataframe(self, ctx: AgentContext) -> Optional[pd.DataFrame]:
        for key in ("daily_history", "history", "kline", "ohlcv"):
            raw = ctx.get_data(key)
            if isinstance(raw, pd.DataFrame):
                return self._normalize_ohlcv(raw)
            if isinstance(raw, list) and raw and isinstance(raw[0], Mapping):
                return self._normalize_ohlcv(pd.DataFrame(raw))
        return None

    def _normalize_ohlcv(self, frame: pd.DataFrame) -> Optional[pd.DataFrame]:
        if frame is None or frame.empty:
            return None
        df = frame.copy()
        columns = {str(c).lower(): c for c in df.columns}
        rename_map: dict[str, str] = {}
        for standard, candidates in {
            "date": ("date", "trade_date", "datetime", "time"),
            "open": ("open", "open_price"),
            "high": ("high", "high_price"),
            "low": ("low", "low_price"),
            "close": ("close", "price", "close_price"),
            "volume": ("volume", "vol", "turnover_volume"),
        }.items():
            for candidate in candidates:
                if candidate in columns:
                    rename_map[columns[candidate]] = standard
                    break
        df = df.rename(columns=rename_map)
        required = {"date", "open", "high", "low", "close", "volume"}
        if not required.issubset(set(df.columns)):
            return None
        subset = df.loc[:, ["date", "open", "high", "low", "close", "volume"]]
        if isinstance(subset, pd.DataFrame):
            return subset
        return None

    def _dimension_score(
        self,
        ctx: AgentContext,
        trend_score: float,
        delegated: list[dict[str, Any]],
    ) -> float:
        if self.dimension == "technical":
            return self._technical_score(ctx, trend_score, delegated)
        if self.dimension == "fundamental":
            return self._fundamental_score(ctx, delegated)
        if self.dimension == "sentiment":
            return self._sentiment_score(ctx, delegated)
        if self.dimension == "macro":
            return self._macro_score(ctx, delegated)
        return self._risk_score(ctx, trend_score, delegated)

    def _technical_score(
        self, ctx: AgentContext, trend_score: float, delegated: list[dict[str, Any]]
    ) -> float:
        score = trend_score
        quote = self._as_mapping(ctx.get_data("quote") or {})
        technical = self._as_mapping(ctx.get_data("technical") or {})
        risk_context = self._as_mapping(ctx.get_data("risk_context") or {})
        volume_ratio = self._to_float(quote.get("volume_ratio"), None)
        price_vs_ma10 = self._to_float(technical.get("price_vs_ma10"), None)
        price_vs_ma20 = self._to_float(technical.get("price_vs_ma20"), None)
        price_vs_ma60 = self._to_float(technical.get("price_vs_ma60"), None)
        ma_alignment = str(technical.get("ma_alignment") or "").strip().lower()
        trading_days = self._to_float(
            risk_context.get("trading_days", ctx.get_data("trading_days")),
            None,
        )
        has_sufficient_history = trading_days is None or trading_days >= 5
        if self._is_cn_market_stock(ctx.stock_code):
            if has_sufficient_history and volume_ratio is not None:
                if volume_ratio < TECHNICAL_SHRINK_VOLUME_MAX:
                    if (
                        price_vs_ma10 is not None
                        and abs(price_vs_ma10) <= TECHNICAL_PULLBACK_NEAR_MA10_MAX_ABS
                        and ma_alignment == "bullish"
                    ):
                        score += TECHNICAL_SHRINK_VOLUME_PULLBACK_BONUS
                    else:
                        score += TECHNICAL_SHRINK_VOLUME_BONUS
                elif volume_ratio > TECHNICAL_HEAVY_VOLUME_PENALTY_HIGH:
                    score += TECHNICAL_HEAVY_VOLUME_PENALTY_HIGH_SCORE
                elif volume_ratio > TECHNICAL_HEAVY_VOLUME_PENALTY_MIN:
                    score += TECHNICAL_HEAVY_VOLUME_PENALTY_LOW_SCORE
                elif (
                    TECHNICAL_MODERATE_VOLUME_MIN
                    < volume_ratio
                    < TECHNICAL_MODERATE_VOLUME_MAX
                ):
                    score += TECHNICAL_MODERATE_VOLUME_DELTA

            if (
                has_sufficient_history
                and price_vs_ma20 is not None
                and price_vs_ma20 <= TECHNICAL_COUNTER_TREND_MA20_MAX
            ):
                score += TECHNICAL_COUNTER_TREND_MA20_BONUS
            if (
                has_sufficient_history
                and price_vs_ma60 is not None
                and price_vs_ma60 <= TECHNICAL_COUNTER_TREND_MA60_MAX
            ):
                score += TECHNICAL_COUNTER_TREND_MA60_BONUS

        score = (
            score * TECHNICAL_BASE_WEIGHT
            + self._delegated_score(delegated) * TECHNICAL_DELEGATED_WEIGHT
        )
        return self._clamp_0_100(score)

    def _fundamental_score(
        self, ctx: AgentContext, delegated: list[dict[str, Any]]
    ) -> float:
        quote = self._as_mapping(ctx.get_data("quote") or {})
        valuation = self._as_mapping(ctx.get_data("valuation_data") or {})
        pe = self._to_float(valuation.get("pe_ratio", quote.get("pe_ratio")), None)
        pb = self._to_float(valuation.get("pb_ratio", quote.get("pb_ratio")), None)

        score = 50.0
        if pe is not None:
            if pe <= 0:
                score += 0
            elif pe < 15:
                score += 20
            elif pe <= 25:
                score += 12
            elif pe <= 40:
                score += 4
            else:
                score -= 12
        if pb is not None:
            if pb < 1:
                score += 15
            elif pb <= 2:
                score += 10
            elif pb <= 4:
                score += 2
            else:
                score -= 8

        score = score * 0.7 + self._delegated_score(delegated) * 0.3
        return self._clamp_0_100(score)

    def _sentiment_score(
        self, ctx: AgentContext, delegated: list[dict[str, Any]]
    ) -> float:
        news_items = ctx.get_data("news_items") or ctx.get_data("news") or []
        if not isinstance(news_items, list):
            news_items = []

        positive_tokens = (
            "beat",
            "growth",
            "upgrade",
            "buyback",
            "突破",
            "利好",
            "增持",
        )
        negative_tokens = (
            "downgrade",
            "fraud",
            "probe",
            "lawsuit",
            "下调",
            "利空",
            "减持",
        )

        positive = 0
        negative = 0
        for item in news_items[:20]:
            text = ""
            if isinstance(item, Mapping):
                text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
            for token in positive_tokens:
                if token.lower() in text:
                    positive += 1
            for token in negative_tokens:
                if token.lower() in text:
                    negative += 1

        score = 50.0 + min(25.0, positive * 4.0) - min(25.0, negative * 5.0)
        score = score * 0.7 + self._delegated_score(delegated) * 0.3
        return self._clamp_0_100(score)

    def _macro_score(self, ctx: AgentContext, delegated: list[dict[str, Any]]) -> float:
        index_data = ctx.get_data("index_data") or {}
        if not isinstance(index_data, Mapping):
            index_data = {}

        changes: list[float] = []
        for payload in index_data.values():
            if not isinstance(payload, Mapping):
                continue
            change = self._to_float(payload.get("change_pct"), None)
            if change is not None:
                changes.append(change)

        score = 50.0
        if changes:
            avg_change = sum(changes) / len(changes)
            score += max(-25.0, min(25.0, avg_change * 10.0))

        score = score * 0.7 + self._delegated_score(delegated) * 0.3
        return self._clamp_0_100(score)

    def _risk_score(
        self, ctx: AgentContext, trend_score: float, delegated: list[dict[str, Any]]
    ) -> float:
        score = 100.0 - (100.0 - trend_score) * 0.6
        quote = self._as_mapping(ctx.get_data("quote") or {})
        turnover = self._to_float(quote.get("turnover_rate"), None)
        if turnover is not None:
            if turnover > 20:
                score -= 20
            elif turnover > 12:
                score -= 10
            elif turnover < 3:
                score += 5

        score = score * 0.65 + self._delegated_score(delegated) * 0.35
        return self._clamp_0_100(score)

    def _collect_delegated_opinions(self, ctx: AgentContext) -> list[dict[str, Any]]:
        delegated = self._collect_cached_delegates(ctx)
        if delegated:
            return delegated

        delegated = self._run_main_agent_delegation(ctx)
        if delegated:
            ctx.set_data("_recommendation_delegate_results", delegated)
            return delegated

        delegated = self._collect_context_delegate_fallback(ctx)
        if delegated:
            ctx.set_data("_recommendation_delegate_results", delegated)
        return delegated

    def _run_main_agent_delegation(self, ctx: AgentContext) -> list[dict[str, Any]]:
        delegate_ctx = AgentContext(
            query=ctx.query,
            stock_code=ctx.stock_code,
            stock_name=ctx.stock_name,
            session_id=ctx.session_id,
            data=dict(ctx.data),
            opinions=[],
            risk_flags=list(ctx.risk_flags),
            meta=dict(ctx.meta),
        )

        main_agents = [
            TechnicalAgent(
                self.tool_registry, self.llm_adapter, self.skill_instructions
            ),
            RiskAgent(self.tool_registry, self.llm_adapter, self.skill_instructions),
            DecisionAgent(
                self.tool_registry, self.llm_adapter, self.skill_instructions
            ),
            PortfolioAgent(
                self.tool_registry, self.llm_adapter, self.skill_instructions
            ),
        ]
        if not self._has_preloaded_news_context(ctx):
            main_agents.insert(
                1,
                IntelAgent(
                    self.tool_registry,
                    self.llm_adapter,
                    self.skill_instructions,
                ),
            )

        delegated: list[dict[str, Any]] = []
        for agent in main_agents:
            if agent.agent_name == "portfolio" and delegated:
                delegate_ctx.set_data(
                    "stock_opinions",
                    self._to_stock_opinion_map(ctx.stock_code, delegated),
                )
                delegate_ctx.set_data(
                    "stock_list", [ctx.stock_code] if ctx.stock_code else []
                )

            stage = agent.run(delegate_ctx)
            if stage.status != StageStatus.COMPLETED or stage.opinion is None:
                continue
            delegated.append(self._normalize_delegate_opinion(stage.opinion))

        return delegated

    @staticmethod
    def _has_preloaded_news_context(ctx: AgentContext) -> bool:
        if not isinstance(ctx.data, Mapping):
            return False
        return "news_items" in ctx.data or "news" in ctx.data

    def _collect_context_delegate_fallback(
        self, ctx: AgentContext
    ) -> list[dict[str, Any]]:
        delegated: list[dict[str, Any]] = []
        delegate_names = {"technical", "intel", "decision", "risk", "portfolio"}

        for opinion in ctx.opinions:
            if not isinstance(opinion, AgentOpinion):
                continue
            name = str(opinion.agent_name or "").strip().lower()
            if name not in delegate_names:
                continue
            delegated.append(self._normalize_delegate_opinion(opinion))

        extra_opinions = ctx.get_data("delegate_opinions")
        if isinstance(extra_opinions, Iterable):
            for item in extra_opinions:
                if not isinstance(item, Mapping):
                    continue
                name = str(item.get("agent_name") or "").strip().lower()
                if name and name not in delegate_names:
                    continue
                signal = str(item.get("signal") or Signal.HOLD.value)
                delegated.append(
                    {
                        "agent_name": name or "delegate",
                        "signal": signal,
                        "confidence": self._clamp_0_1(
                            self._to_float(item.get("confidence"), 0.5) or 0.5
                        ),
                        "score": self._signal_to_score(signal),
                    }
                )
        return delegated

    def _collect_cached_delegates(self, ctx: AgentContext) -> list[dict[str, Any]]:
        cached = ctx.get_data("_recommendation_delegate_results")
        if not isinstance(cached, list):
            return []
        delegates: list[dict[str, Any]] = []
        for item in cached:
            if isinstance(item, Mapping):
                agent_name = str(item.get("agent_name") or "delegate")
                signal = str(item.get("signal") or Signal.HOLD.value)
                confidence = self._clamp_0_1(
                    self._to_float(item.get("confidence"), 0.5) or 0.5
                )
                delegates.append(
                    {
                        "agent_name": agent_name,
                        "signal": signal,
                        "confidence": confidence,
                        "score": self._signal_to_score(signal),
                    }
                )
        return delegates

    def _normalize_delegate_opinion(self, opinion: AgentOpinion) -> dict[str, Any]:
        return {
            "agent_name": str(opinion.agent_name or "delegate").strip().lower(),
            "signal": opinion.signal,
            "confidence": self._clamp_0_1(opinion.confidence),
            "score": self._signal_to_score(opinion.signal),
        }

    def _to_stock_opinion_map(
        self, stock_code: str, delegated: list[dict[str, Any]]
    ) -> dict[str, AgentOpinion]:
        code = stock_code or "CURRENT"
        mapping: dict[str, AgentOpinion] = {}
        for item in delegated:
            mapping[code] = AgentOpinion(
                agent_name=str(item.get("agent_name") or "delegate"),
                signal=str(item.get("signal") or Signal.HOLD.value),
                confidence=self._clamp_0_1(
                    self._to_float(item.get("confidence"), 0.5) or 0.5
                ),
                reasoning="Delegated stage opinion",
                raw_data={"score": item.get("score", 50.0)},
            )
        return mapping

    def _delegated_score(self, delegated: list[dict[str, Any]]) -> float:
        if not delegated:
            return 50.0
        weighted_scores = [item["score"] * item["confidence"] for item in delegated]
        weights = [item["confidence"] for item in delegated]
        total_weight = sum(weights)
        if total_weight <= 0:
            return 50.0
        return self._clamp_0_100(sum(weighted_scores) / total_weight)

    def _confidence_score(
        self, ctx: AgentContext, delegated: list[dict[str, Any]]
    ) -> float:
        completeness = 0.0
        for key in ("trend_result", "quote", "news_items", "index_data"):
            if ctx.get_data(key) is not None:
                completeness += 0.12
        delegated_bonus = min(0.28, len(delegated) * 0.07)
        confidence = 0.45 + completeness + delegated_bonus
        return self._clamp_0_1(confidence)

    def _calibrate_confidence(
        self, raw_confidence: float, stock_code: Optional[str]
    ) -> float:
        calibrated_confidence = raw_confidence
        try:
            calibrated_confidence = self._agent_memory.calibrate_confidence(
                self.agent_name,
                raw_confidence,
                stock_code,
            )
        except Exception as exc:
            logger.debug("[%s] confidence calibration failed: %s", self.agent_name, exc)
            calibrated_confidence = raw_confidence

        calibration_applied = abs(calibrated_confidence - raw_confidence) > 1e-9
        logger.info(
            "[%s] confidence calibration applied=%s raw=%.4f final=%.4f stock=%s",
            self.agent_name,
            calibration_applied,
            raw_confidence,
            calibrated_confidence,
            stock_code or "UNKNOWN",
        )
        return self._clamp_0_1(calibrated_confidence)

    def _build_reasoning(
        self,
        ctx: AgentContext,
        score: float,
        trend_score: float,
        delegated: list[dict[str, Any]],
    ) -> str:
        parts = [
            f"{self.profile['title']} dimension score={score:.1f}/100",
            f"trend_analyzer_score={trend_score:.1f}",
            f"delegated_opinions={len(delegated)}",
        ]
        if ctx.stock_code:
            parts.append(f"stock={ctx.stock_code}")
        return "; ".join(parts)

    def _build_key_levels(
        self, ctx: AgentContext, trend_score: float
    ) -> dict[str, float]:
        key_levels: dict[str, float] = {"trend_score": round(trend_score, 2)}
        trend_payload = self._as_mapping(
            ctx.get_data("trend_result") or ctx.get_data("technical") or {}
        )
        for key in ("support", "resistance", "ma5", "ma10", "ma20"):
            numeric = self._to_float(trend_payload.get(key), None)
            if numeric is not None and math.isfinite(numeric):
                key_levels[key] = round(float(numeric), 4)
        return key_levels

    def _score_to_signal(self, score: float) -> str:
        if score >= 85:
            return Signal.STRONG_BUY.value
        if score >= 65:
            return Signal.BUY.value
        if score >= 45:
            return Signal.HOLD.value
        if score >= 25:
            return Signal.SELL.value
        return Signal.STRONG_SELL.value

    def _signal_to_score(self, signal: str) -> float:
        signal_map = {
            Signal.STRONG_BUY.value: 90.0,
            Signal.BUY.value: 72.0,
            Signal.HOLD.value: 50.0,
            Signal.SELL.value: 28.0,
            Signal.STRONG_SELL.value: 10.0,
        }
        return signal_map.get(str(signal or "").strip().lower(), 50.0)

    @staticmethod
    def _as_mapping(value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        if hasattr(value, "to_dict"):
            try:
                converted = value.to_dict()
                if isinstance(converted, Mapping):
                    return converted
            except Exception:
                return {}
        return {}

    @staticmethod
    def _to_float(value: Any, default: Optional[float]) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_0_100(value: float) -> float:
        return max(0.0, min(100.0, float(value)))

    @staticmethod
    def _clamp_0_1(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _is_cn_market_stock(stock_code: Optional[str]) -> bool:
        try:
            return detect_market_region(str(stock_code or "")) == MarketRegion.CN
        except Exception:
            return True
