from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

import pandas as pd

from src.repositories.analysis_repo import AnalysisRepository
from src.repositories.recommendation_repo import RecommendationRepository
from src.recommendation.models import (
    CompositeScore,
    DimensionScore,
    RecommendationPriority,
    StockRecommendation,
)
from src.storage import AnalysisHistory, DatabaseManager


@dataclass(frozen=True)
class AnalysisResultIdentity:
    analysis_id: int
    query_id: str


@dataclass
class _RecommendationAnalysisBridgePayload:
    code: str
    name: str
    sentiment_score: int
    operation_advice: str
    trend_prediction: str
    analysis_summary: str
    raw_payload: dict[str, Any]
    sniper_points: dict[str, float | None]
    data_sources: str = "recommendation_refresh"
    raw_response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw_payload)

    def get_sniper_points(self) -> dict[str, float | None]:
        return dict(self.sniper_points)


class AnalysisResultService:
    RECOMMENDATION_REPORT_TYPE = "recommendation"

    def __init__(
        self,
        analysis_repo: AnalysisRepository | None = None,
        db_manager: DatabaseManager | None = None,
    ) -> None:
        self.db_manager = db_manager or DatabaseManager.get_instance()
        self.analysis_repo = analysis_repo or AnalysisRepository(
            db_manager=self.db_manager
        )

    def save_recommendation_result(
        self,
        recommendation: StockRecommendation,
        recommendation_record_id: int | None = None,
    ) -> AnalysisResultIdentity:
        bridge_result = self._build_recommendation_bridge_payload(recommendation)
        recommendation_date = recommendation.updated_at.date()
        query_id = self._build_recommendation_query_id(
            code=recommendation.code,
            recommendation_date=recommendation_date,
            recommendation_record_id=recommendation_record_id,
        )

        sniper_points = self.db_manager._extract_sniper_points(bridge_result)
        raw_result = self.db_manager._build_raw_result(bridge_result)

        with self.db_manager.session_scope() as session:
            record = AnalysisHistory(
                query_id=query_id,
                code=bridge_result.code,
                name=bridge_result.name,
                report_type=self.RECOMMENDATION_REPORT_TYPE,
                sentiment_score=bridge_result.sentiment_score,
                operation_advice=bridge_result.operation_advice,
                trend_prediction=bridge_result.trend_prediction,
                analysis_summary=bridge_result.analysis_summary,
                raw_result=self.db_manager._safe_json_dumps(raw_result),
                news_content=None,
                context_snapshot=None,
                ideal_buy=sniper_points.get("ideal_buy"),
                secondary_buy=sniper_points.get("secondary_buy"),
                stop_loss=sniper_points.get("stop_loss"),
                take_profit=sniper_points.get("take_profit"),
                created_at=datetime.now(),
            )
            session.add(record)
            session.flush()
            analysis_id = int(cast(int, record.id))

        return AnalysisResultIdentity(analysis_id=analysis_id, query_id=query_id)

    def get_by_id(self, analysis_id: int) -> AnalysisHistory | None:
        return self.analysis_repo.get_by_id(analysis_id)

    def get_latest_recommendation_result(
        self,
        code: str,
        target_date: date,
    ) -> AnalysisHistory | None:
        return self.analysis_repo.get_latest_by_code_and_date(
            code=code,
            target_date=target_date,
            report_type=self.RECOMMENDATION_REPORT_TYPE,
        )

    @staticmethod
    def _build_recommendation_query_id(
        code: str,
        recommendation_date: date,
        recommendation_record_id: int | None,
    ) -> str:
        if recommendation_record_id is not None:
            return RecommendationRepository.build_history_query_id(
                code,
                recommendation_date,
                recommendation_record_id,
            )
        return f"rec_{code}_{recommendation_date.strftime('%Y%m%d')}"

    def _build_recommendation_bridge_payload(
        self,
        recommendation: StockRecommendation,
    ) -> _RecommendationAnalysisBridgePayload:
        sentiment_score = self._extract_sentiment_score(recommendation.composite_score)
        operation_advice = self._map_operation_advice(recommendation.composite_score)
        trend_prediction = self._derive_trend_prediction(recommendation.composite_score)
        analysis_summary = str(recommendation.composite_score.ai_summary or "").strip()
        if not analysis_summary:
            analysis_summary = (
                f"{operation_advice}，综合评分 {recommendation.composite_score.total_score:.2f}，"
                f"趋势判断：{trend_prediction}。"
            )

        sniper_points = {
            "ideal_buy": recommendation.ideal_buy_price,
            "secondary_buy": None,
            "stop_loss": recommendation.stop_loss,
            "take_profit": recommendation.take_profit,
        }

        raw_payload = {
            "source": "recommendation_refresh",
            "code": recommendation.code,
            "name": recommendation.name,
            "region": recommendation.region.value,
            "sector": recommendation.sector,
            "current_price": recommendation.current_price,
            "sentiment_score": sentiment_score,
            "operation_advice": operation_advice,
            "trend_prediction": trend_prediction,
            "analysis_summary": analysis_summary,
            "recommendation": {
                "total_score": recommendation.composite_score.total_score,
                "priority": {
                    "name": recommendation.composite_score.priority.name,
                    "label": recommendation.composite_score.priority.value,
                },
                "dimension_scores": self._serialize_dimension_scores(
                    recommendation.composite_score.dimension_scores
                ),
                "ai_refined": bool(recommendation.composite_score.ai_refined),
                "ai_summary": recommendation.composite_score.ai_summary,
            },
            "sniper_points": sniper_points,
            "generated_at": (
                recommendation.updated_at.isoformat()
                if recommendation.updated_at
                else datetime.utcnow().isoformat()
            ),
        }

        return _RecommendationAnalysisBridgePayload(
            code=recommendation.code,
            name=recommendation.name,
            sentiment_score=sentiment_score,
            operation_advice=operation_advice,
            trend_prediction=trend_prediction,
            analysis_summary=analysis_summary,
            raw_payload=raw_payload,
            sniper_points=sniper_points,
            raw_response={
                "dashboard": {"battle_plan": {"sniper_points": sniper_points}}
            },
        )

    @staticmethod
    def _serialize_dimension_scores(
        dimension_scores: list[DimensionScore],
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for item in dimension_scores:
            payload.append(
                {
                    "dimension": item.dimension,
                    "score": item.score,
                    "weight": item.weight,
                    "details": item.details,
                }
            )
        return payload

    @staticmethod
    def _extract_sentiment_score(composite_score: CompositeScore) -> int:
        sentiment_dimension = next(
            (
                item
                for item in composite_score.dimension_scores
                if str(item.dimension).strip().casefold() == "sentiment"
            ),
            None,
        )
        if sentiment_dimension is None:
            return 50

        try:
            value = float(sentiment_dimension.score)
        except (TypeError, ValueError):
            return 50
        if pd.isna(value):
            return 50
        value = max(0.0, min(100.0, value))
        return int(round(value))

    @staticmethod
    def _map_operation_advice(composite_score: CompositeScore) -> str:
        mapping = {
            RecommendationPriority.BUY_NOW: "强烈买入",
            RecommendationPriority.POSITION: "建仓",
            RecommendationPriority.WAIT_PULLBACK: "观望",
            RecommendationPriority.NO_ENTRY: "回避",
        }
        return mapping.get(composite_score.priority, "观望")

    @staticmethod
    def _derive_trend_prediction(composite_score: CompositeScore) -> str:
        summary = str(composite_score.ai_summary or "").strip().casefold()
        if summary:
            bearish_markers = ("看空", "下跌", "bearish", "strong sell", "sell")
            bullish_markers = ("看多", "上涨", "bullish", "strong buy", "buy")
            if any(marker in summary for marker in bearish_markers):
                return "看空"
            if any(marker in summary for marker in bullish_markers):
                return "看多"

        fallback = {
            RecommendationPriority.BUY_NOW: "看多",
            RecommendationPriority.POSITION: "偏多",
            RecommendationPriority.WAIT_PULLBACK: "震荡",
            RecommendationPriority.NO_ENTRY: "观望",
        }
        return fallback.get(composite_score.priority, "观望")
