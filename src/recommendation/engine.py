# -*- coding: utf-8 -*-
"""Composite scoring engine for stock recommendations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Mapping

from data_provider.realtime_types import UnifiedRealtimeQuote
from src.agent.agents.base_agent import BaseAgent
from src.agent.agents.recommendation_agent import RecommendationAgent
from src.agent.factory import get_tool_registry
from src.agent.llm_adapter import LLMToolAdapter
from src.agent.protocols import (
    AgentContext,
    AgentOpinion,
    Signal,
    StageResult,
    StageStatus,
)
from src.recommendation.constants import (
    BUY_NOW_MIN_SCORE,
    POSITION_MIN_SCORE,
    RISK_MAX_HOLD_DAYS,
    WAIT_PULLBACK_MIN_SCORE,
)
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    MarketRegion,
    RecommendationPriority,
    ScoringWeights,
)
from src.stock_analyzer import TrendAnalysisResult


@dataclass
class StockScoringData:
    """Container of normalized inputs required for scoring."""

    region: MarketRegion
    trend_result: TrendAnalysisResult
    quote: UnifiedRealtimeQuote
    news_items: list[dict[str, Any]] = field(default_factory=list)
    index_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    volume_trend: str | None = None
    volume_ma5_ratio: float | None = None
    price_vs_ma10: float | None = None
    price_vs_ma20: float | None = None
    ma_alignment: str | None = None
    trading_days: int | None = None
    max_hold_days: int | None = None


class ScoringEngine:
    """Combine dimension agent opinions into one recommendation score."""

    _REQUIRED_DIMENSIONS = ("technical", "fundamental", "sentiment", "macro", "risk")
    _SIGNAL_BASE_SCORE = {
        Signal.STRONG_BUY.value: 90.0,
        Signal.BUY.value: 72.0,
        Signal.HOLD.value: 50.0,
        Signal.SELL.value: 28.0,
        Signal.STRONG_SELL.value: 10.0,
    }

    def __init__(
        self,
        weights: ScoringWeights,
        scorers: Mapping[str, Any] | None = None,
        ai_refiner: Any | None = None,
        agents: Mapping[str, BaseAgent] | None = None,
        llm_adapter: LLMToolAdapter | None = None,
        batch_max_workers: int = 4,
    ) -> None:
        self._weights = weights
        _ = scorers
        self._ai_refiner = ai_refiner
        self._llm_adapter = llm_adapter or LLMToolAdapter()
        self._batch_max_workers = max(1, int(batch_max_workers))
        self._agents = self._build_agents(agents)

    def score_stock(self, code: str, data: StockScoringData) -> CompositeScore:
        """Score one stock and return its composite recommendation result."""
        dimension_scores = self._dimension_scores(code, data)
        fractions = self._weights.to_fractions()

        total_score = 0.0
        for dimension_score in dimension_scores:
            weight = fractions.get(dimension_score.dimension, 0.0)
            dimension_score.weight = weight
            total_score += dimension_score.score * weight

        total_score = round(total_score, 2)
        composite_score = CompositeScore(
            total_score=total_score,
            priority=self._priority_for_score(total_score),
            dimension_scores=dimension_scores,
        )

        if total_score >= POSITION_MIN_SCORE and self._ai_refiner is not None:
            self._apply_ai_refinement(code, composite_score)

        return composite_score

    def score_batch(
        self, stocks: list[tuple[str, StockScoringData]]
    ) -> list[CompositeScore]:
        """Score a batch of stocks in input order."""
        if not stocks:
            return []

        worker_count = min(self._batch_max_workers, len(stocks))
        if worker_count <= 1:
            return [self.score_stock(code, data) for code, data in stocks]

        results: list[CompositeScore | None] = [None] * len(stocks)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(self.score_stock, code, data): index
                for index, (code, data) in enumerate(stocks)
            }
            for future in as_completed(future_map):
                results[future_map[future]] = future.result()

        output: list[CompositeScore] = []
        for item in results:
            if item is None:
                raise RuntimeError("Batch scoring produced an incomplete result set")
            output.append(item)
        return output

    def _dimension_scores(
        self, code: str, data: StockScoringData
    ) -> list[DimensionScore]:
        missing = [
            name for name in self._REQUIRED_DIMENSIONS if name not in self._agents
        ]
        if missing:
            raise ValueError(
                f"Missing recommendation agents for dimensions: {', '.join(missing)}"
            )

        return [
            self._score_dimension(code, data, dimension)
            for dimension in self._REQUIRED_DIMENSIONS
        ]

    def _build_agents(
        self,
        agents: Mapping[str, BaseAgent] | None,
    ) -> dict[str, BaseAgent]:
        if agents is not None:
            return dict(agents)

        registry = get_tool_registry()
        return {
            "technical": RecommendationAgent(
                registry, self._llm_adapter, dimension="technical"
            ),
            "fundamental": RecommendationAgent(
                registry, self._llm_adapter, dimension="fundamental"
            ),
            "sentiment": RecommendationAgent(
                registry, self._llm_adapter, dimension="sentiment"
            ),
            "macro": RecommendationAgent(
                registry, self._llm_adapter, dimension="macro"
            ),
            "risk": RecommendationAgent(registry, self._llm_adapter, dimension="risk"),
        }

    def _score_dimension(
        self,
        code: str,
        data: StockScoringData,
        dimension: str,
    ) -> DimensionScore:
        ctx = self._build_agent_context(code=code, data=data, dimension=dimension)
        agent = self._agents[dimension]

        try:
            stage_result = agent.run(ctx)
        except Exception as exc:
            return self._fallback_dimension_score(
                dimension=dimension,
                reason=f"agent-run-error: {exc}",
            )

        if stage_result.status != StageStatus.COMPLETED:
            return self._fallback_dimension_score(
                dimension=dimension,
                reason=stage_result.error or "agent-stage-not-completed",
                stage_result=stage_result,
            )

        if stage_result.opinion is None:
            return self._fallback_dimension_score(
                dimension=dimension,
                reason="missing-agent-opinion",
                stage_result=stage_result,
            )

        return self._opinion_to_dimension_score(
            dimension=dimension,
            opinion=stage_result.opinion,
            stage_result=stage_result,
        )

    def _build_agent_context(
        self,
        code: str,
        data: StockScoringData,
        dimension: str,
    ) -> AgentContext:
        quote_payload = data.quote.to_dict() if hasattr(data.quote, "to_dict") else {}
        trend_payload = (
            data.trend_result.to_dict() if hasattr(data.trend_result, "to_dict") else {}
        )
        technical_payload: dict[str, Any] = dict(trend_payload)
        for key in ("price_vs_ma10", "price_vs_ma20"):
            value = getattr(data, key, None)
            if value is not None:
                technical_payload[key] = value

        risk_context: dict[str, Any] = {
            "support_levels": trend_payload.get("support_levels", []),
            "volume_ratio_5d": trend_payload.get("volume_ratio_5d"),
            "rsi_status": trend_payload.get("rsi_status"),
            "nearest_support": None,
            "support_distance_pct": None,
            "volume_ratio": quote_payload.get("volume_ratio"),
            "turnover_rate": quote_payload.get("turnover_rate"),
        }
        for key in (
            "volume_trend",
            "volume_ma5_ratio",
            "ma_alignment",
            "trading_days",
            "max_hold_days",
        ):
            value = getattr(data, key, None)
            if value is not None:
                risk_context[key] = value

        context_data: dict[str, Any] = {
            "code": code,
            "region": data.region,
            "dimension": dimension,
            "trend_result": trend_payload,
            "technical": technical_payload,
            "quote": quote_payload,
            "news_items": list(data.news_items or []),
            "news": list(data.news_items or []),
            "index_data": dict(data.index_data or {}),
            "valuation_data": {
                "pe_ratio": quote_payload.get("pe_ratio"),
                "pb_ratio": quote_payload.get("pb_ratio"),
                "total_mv": quote_payload.get("total_mv"),
            },
            "pe_ratio": quote_payload.get("pe_ratio"),
            "pb_ratio": quote_payload.get("pb_ratio"),
            "total_mv": quote_payload.get("total_mv"),
            "risk_context": risk_context,
        }

        for key in (
            "volume_trend",
            "volume_ma5_ratio",
            "price_vs_ma10",
            "price_vs_ma20",
            "ma_alignment",
            "trading_days",
            "max_hold_days",
        ):
            value = getattr(data, key, None)
            if value is not None:
                context_data[key] = value

        stock_name = str(getattr(data.quote, "name", "") or "").strip()
        return AgentContext(
            query=f"Generate {dimension} recommendation score for {code}.",
            stock_code=code,
            stock_name=stock_name,
            data=context_data,
        )

    def _opinion_to_dimension_score(
        self,
        dimension: str,
        opinion: AgentOpinion,
        stage_result: StageResult,
    ) -> DimensionScore:
        raw_score = self._extract_score_0_100(opinion)
        confidence_0_1 = self._clamp_0_1(opinion.confidence)
        signal_base = self._signal_score(opinion.signal)

        if raw_score is None:
            confidence_0_100 = confidence_0_1 * 100.0
            score = round(
                self._clamp_0_100(signal_base * 0.7 + confidence_0_100 * 0.3), 2
            )
            score_source = "signal_confidence_blend"
        else:
            score = round(self._clamp_0_100(raw_score), 2)
            score_source = "agent_raw_score"

        details: dict[str, Any] = {
            "agent_name": opinion.agent_name,
            "signal": opinion.signal,
            "confidence": round(confidence_0_1, 4),
            "confidence_percent": round(confidence_0_1 * 100.0, 2),
            "reasoning": opinion.reasoning,
            "key_levels": dict(opinion.key_levels or {}),
            "score_source": score_source,
            "stage_status": stage_result.status.value,
            "stage_duration_s": stage_result.duration_s,
            "tokens_used": stage_result.tokens_used,
            "tool_calls_count": stage_result.tool_calls_count,
            "raw_data": dict(opinion.raw_data or {}),
        }
        if dimension == "risk":
            details["max_hold_days"] = RISK_MAX_HOLD_DAYS
        return DimensionScore(
            dimension=dimension, score=score, weight=0.0, details=details
        )

    def _fallback_dimension_score(
        self,
        dimension: str,
        reason: str,
        stage_result: StageResult | None = None,
    ) -> DimensionScore:
        details: dict[str, Any] = {
            "fallback": True,
            "fallback_reason": reason,
            "signal": Signal.HOLD.value,
            "confidence": 0.5,
            "confidence_percent": 50.0,
            "score_source": "fallback_default",
        }
        if stage_result is not None:
            details.update(
                {
                    "stage_status": stage_result.status.value,
                    "stage_error": stage_result.error,
                    "stage_duration_s": stage_result.duration_s,
                    "tokens_used": stage_result.tokens_used,
                    "tool_calls_count": stage_result.tool_calls_count,
                }
            )
        return DimensionScore(
            dimension=dimension, score=50.0, weight=0.0, details=details
        )

    def _extract_score_0_100(self, opinion: AgentOpinion) -> float | None:
        candidates: list[Any] = []
        raw_data = opinion.raw_data or {}

        for key in (
            "score_0_100",
            "score",
            "guided_score",
            "parsed_score",
            "confidence_percent",
        ):
            if key in raw_data:
                candidates.append(raw_data.get(key))

        parsed_payload = raw_data.get("parsed_payload")
        if isinstance(parsed_payload, Mapping):
            for key in ("score", "score_0_100", "guided_score", "confidence"):
                if key in parsed_payload:
                    candidates.append(parsed_payload.get(key))

        for value in candidates:
            numeric = self._to_float(value)
            if numeric is None:
                continue
            if 0.0 <= numeric <= 1.0:
                numeric *= 100.0
            return self._clamp_0_100(numeric)

        return None

    def _signal_score(self, signal: str) -> float:
        normalized = str(signal or "").strip().lower()
        return self._SIGNAL_BASE_SCORE.get(normalized, 50.0)

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_0_100(value: float) -> float:
        return max(0.0, min(100.0, float(value)))

    @staticmethod
    def _clamp_0_1(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _priority_for_score(score: float) -> RecommendationPriority:
        if score >= BUY_NOW_MIN_SCORE:
            return RecommendationPriority.BUY_NOW
        if score >= POSITION_MIN_SCORE:
            return RecommendationPriority.POSITION
        if score >= WAIT_PULLBACK_MIN_SCORE:
            return RecommendationPriority.WAIT_PULLBACK
        return RecommendationPriority.NO_ENTRY

    def _apply_ai_refinement(
        self,
        code: str,
        composite_score: CompositeScore,
    ) -> None:
        if self._ai_refiner is None:
            return

        dimensions = ", ".join(
            f"{item.dimension}:{item.score:.2f}"
            for item in composite_score.dimension_scores
        )
        prompt = (
            f"Stock code: {code}\n"
            f"Composite score: {composite_score.total_score:.2f}\n"
            f"Priority: {composite_score.priority.value}\n"
            f"Dimension scores: {dimensions}\n"
            "Provide one concise recommendation summary in plain text."
        )
        try:
            summary = self._ai_refiner.generate_text(
                prompt,
                max_tokens=128,
                temperature=0.0,
            )
        except Exception:
            return
        if not summary:
            return

        normalized_summary = str(summary).strip()
        if not normalized_summary:
            return

        composite_score.ai_refined = True
        composite_score.ai_summary = normalized_summary
