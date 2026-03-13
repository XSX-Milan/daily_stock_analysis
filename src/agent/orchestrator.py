# -*- coding: utf-8 -*-
"""Multi-agent pipeline orchestrator."""

from __future__ import annotations

import importlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.protocols import AgentContext, AgentRunStats, StageResult, StageStatus
from src.agent.runner import parse_dashboard_json
from src.agent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from src.agent.executor import AgentResult

logger = logging.getLogger(__name__)

VALID_MODES = ("quick", "standard", "full", "strategy")


@dataclass
class OrchestratorResult:
    """Unified result from a multi-agent pipeline run."""

    success: bool = False
    content: str = ""
    dashboard: Optional[Dict[str, Any]] = None
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0
    provider: str = ""
    model: str = ""
    error: Optional[str] = None
    stats: Optional[AgentRunStats] = None


class AgentOrchestrator:
    """Drop-in replacement for AgentExecutor in multi-agent mode."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: LLMToolAdapter,
        skill_instructions: str = "",
        max_steps: int = 10,
        mode: str = "standard",
        skill_manager=None,
        config=None,
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.skill_instructions = skill_instructions
        self.max_steps = max_steps
        self.mode = mode if mode in VALID_MODES else "standard"
        self.skill_manager = skill_manager
        self.config = config
        self._strategy_agent_names: set[str] = set()

    def _get_timeout_seconds(self) -> int:
        raw_value = getattr(self.config, "agent_orchestrator_timeout_s", 0)
        try:
            return max(0, int(raw_value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _build_timeout_result(
        stats: AgentRunStats,
        all_tool_calls: List[Dict[str, Any]],
        models_used: List[str],
        elapsed_s: float,
        timeout_s: int,
    ) -> OrchestratorResult:
        stats.total_duration_s = round(elapsed_s, 2)
        stats.models_used = list(dict.fromkeys(models_used))
        return OrchestratorResult(
            success=False,
            error=f"Pipeline timed out after {elapsed_s:.2f}s (limit: {timeout_s}s)",
            stats=stats,
            total_steps=stats.total_stages,
            total_tokens=stats.total_tokens,
            tool_calls_log=all_tool_calls,
            provider=stats.models_used[0] if stats.models_used else "",
            model=", ".join(stats.models_used),
        )

    def _prepare_agent(self, agent: Any) -> Any:
        if hasattr(agent, "max_steps"):
            agent.max_steps = self.max_steps
        return agent

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> "AgentResult":
        from src.agent.executor import AgentResult

        ctx = self._build_context(task, context)
        orch_result = self._execute_pipeline(ctx, parse_dashboard=True)
        return AgentResult(
            success=orch_result.success,
            content=orch_result.content,
            dashboard=orch_result.dashboard,
            tool_calls_log=orch_result.tool_calls_log,
            total_steps=orch_result.total_steps,
            total_tokens=orch_result.total_tokens,
            provider=orch_result.provider,
            model=orch_result.model,
            error=orch_result.error,
        )

    def chat(
        self,
        message: str,
        session_id: str,
        progress_callback: Optional[Callable] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> "AgentResult":
        from src.agent.conversation import conversation_manager
        from src.agent.executor import AgentResult

        ctx = self._build_context(message, context)
        ctx.session_id = session_id
        conversation_manager.add_message(session_id, "user", message)

        orch_result = self._execute_pipeline(
            ctx, parse_dashboard=False, progress_callback=progress_callback
        )
        if orch_result.success:
            conversation_manager.add_message(
                session_id, "assistant", orch_result.content
            )
        else:
            conversation_manager.add_message(
                session_id, "assistant", f"[分析失败] {orch_result.error or '未知错误'}"
            )

        return AgentResult(
            success=orch_result.success,
            content=orch_result.content,
            dashboard=orch_result.dashboard,
            tool_calls_log=orch_result.tool_calls_log,
            total_steps=orch_result.total_steps,
            total_tokens=orch_result.total_tokens,
            provider=orch_result.provider,
            model=orch_result.model,
            error=orch_result.error,
        )

    def _execute_pipeline(
        self,
        ctx: AgentContext,
        parse_dashboard: bool = True,
        progress_callback: Optional[Callable] = None,
    ) -> OrchestratorResult:
        stats = AgentRunStats()
        all_tool_calls: List[Dict[str, Any]] = []
        models_used: List[str] = []
        t0 = time.time()
        timeout_s = self._get_timeout_seconds()

        agents = self._build_agent_chain(ctx)
        for agent in agents:
            elapsed_s = time.time() - t0
            if timeout_s and elapsed_s >= timeout_s:
                return self._build_timeout_result(
                    stats, all_tool_calls, models_used, elapsed_s, timeout_s
                )

            if agent.agent_name == "decision" and self._strategy_agent_names:
                self._aggregate_strategy_opinions(ctx)

            if progress_callback:
                progress_callback({"type": "stage_start", "stage": agent.agent_name})

            result: StageResult = agent.run(ctx, progress_callback=progress_callback)
            stats.record_stage(result)
            all_tool_calls.extend(
                tc for tc in (result.meta.get("tool_calls_log") or [])
            )
            models_used.extend(result.meta.get("models_used", []))

            if progress_callback:
                progress_callback(
                    {
                        "type": "stage_done",
                        "stage": agent.agent_name,
                        "status": result.status.value,
                        "duration": result.duration_s,
                    }
                )

            if result.status == StageStatus.FAILED and agent.agent_name not in (
                "intel",
                "risk",
            ):
                return OrchestratorResult(
                    success=False,
                    error=f"Stage '{agent.agent_name}' failed: {result.error}",
                    stats=stats,
                    total_tokens=stats.total_tokens,
                    tool_calls_log=all_tool_calls,
                )

        stats.total_duration_s = round(time.time() - t0, 2)
        stats.models_used = list(dict.fromkeys(models_used))

        content = ""
        dashboard = None
        final_dashboard = ctx.get_data("final_dashboard")
        final_raw = ctx.get_data("final_dashboard_raw")

        if final_dashboard:
            dashboard = final_dashboard
            content = json.dumps(final_dashboard, ensure_ascii=False, indent=2)
        elif final_raw:
            content = final_raw
            if parse_dashboard:
                dashboard = parse_dashboard_json(final_raw)
        elif ctx.opinions:
            content = self._fallback_summary(ctx)

        model_str = ", ".join(dict.fromkeys(m for m in models_used if m))
        return OrchestratorResult(
            success=bool(content),
            content=content,
            dashboard=dashboard,
            tool_calls_log=all_tool_calls,
            total_steps=stats.total_stages,
            total_tokens=stats.total_tokens,
            provider=stats.models_used[0] if stats.models_used else "",
            model=model_str,
            stats=stats,
        )

    def _load_class(self, module_name: str, class_name: str):
        module = importlib.import_module(module_name)
        return getattr(module, class_name)

    def _build_agent_chain(self, ctx: AgentContext) -> List[Any]:
        self._strategy_agent_names = set()
        common_kwargs = {
            "tool_registry": self.tool_registry,
            "llm_adapter": self.llm_adapter,
            "skill_instructions": self.skill_instructions,
        }

        try:
            technical = self._prepare_agent(
                self._load_class("src.agent.agents.technical_agent", "TechnicalAgent")(
                    **common_kwargs
                )
            )
            decision = self._prepare_agent(
                self._load_class("src.agent.agents.decision_agent", "DecisionAgent")(
                    **common_kwargs
                )
            )
        except Exception as exc:
            logger.warning(
                "[Orchestrator] core agent classes unavailable, fallback to empty chain: %s",
                exc,
            )
            return []

        try:
            intel = self._prepare_agent(
                self._load_class("src.agent.agents.intel_agent", "IntelAgent")(
                    **common_kwargs
                )
            )
        except Exception:
            intel = None
        try:
            risk = self._prepare_agent(
                self._load_class("src.agent.agents.risk_agent", "RiskAgent")(
                    **common_kwargs
                )
            )
        except Exception:
            risk = None

        if self.mode == "quick":
            return [technical, decision]
        if self.mode == "standard":
            return [technical] + ([intel] if intel else []) + [decision]
        if self.mode == "full":
            chain = [technical]
            if intel:
                chain.append(intel)
            if risk:
                chain.append(risk)
            chain.append(decision)
            return chain
        if self.mode == "strategy":
            chain = [technical]
            if intel:
                chain.append(intel)
            if risk:
                chain.append(risk)
            strategy_agents = self._build_strategy_agents(ctx, common_kwargs)
            chain.extend(strategy_agents)
            self._strategy_agent_names = {a.agent_name for a in strategy_agents}
            chain.append(decision)
            return chain
        return [technical] + ([intel] if intel else []) + [decision]

    def _build_strategy_agents(
        self, ctx: AgentContext, common_kwargs: Dict[str, Any]
    ) -> List[Any]:
        try:
            router_cls = self._load_class(
                "src.agent.strategies.router", "StrategyRouter"
            )
            selected = router_cls().select_strategies(ctx)
            if not selected:
                return []
            strategy_agent_cls = self._load_class(
                "src.agent.strategies.strategy_agent", "StrategyAgent"
            )
            return [
                self._prepare_agent(
                    strategy_agent_cls(strategy_id=sid, **common_kwargs)
                )
                for sid in selected[:3]
            ]
        except Exception as exc:
            logger.warning("[Orchestrator] failed to build strategy agents: %s", exc)
            return []

    def _aggregate_strategy_opinions(self, ctx: AgentContext) -> None:
        try:
            aggregator_cls = self._load_class(
                "src.agent.strategies.aggregator", "StrategyAggregator"
            )
            consensus = aggregator_cls().aggregate(ctx)
            if consensus:
                ctx.opinions.append(consensus)
                ctx.set_data(
                    "strategy_consensus",
                    {
                        "signal": consensus.signal,
                        "confidence": consensus.confidence,
                        "reasoning": consensus.reasoning,
                    },
                )
        except Exception as exc:
            logger.warning("[Orchestrator] strategy aggregation failed: %s", exc)

    def _build_context(
        self, task: str, context: Optional[Dict[str, Any]] = None
    ) -> AgentContext:
        ctx = AgentContext(query=task)
        if context:
            ctx.stock_code = context.get("stock_code", "")
            ctx.stock_name = context.get("stock_name", "")
            ctx.meta["strategies_requested"] = context.get("strategies", [])
            for data_key in (
                "realtime_quote",
                "daily_history",
                "chip_distribution",
                "trend_result",
                "news_context",
            ):
                if context.get(data_key):
                    ctx.set_data(data_key, context[data_key])

        if not ctx.stock_code:
            ctx.stock_code = _extract_stock_code(task)
        return ctx

    @staticmethod
    def _fallback_summary(ctx: AgentContext) -> str:
        lines = [f"# Analysis Summary: {ctx.stock_code} ({ctx.stock_name})", ""]
        for op in ctx.opinions:
            lines.append(f"## {op.agent_name}")
            lines.append(f"Signal: {op.signal} (confidence: {op.confidence:.0%})")
            lines.append(op.reasoning)
            lines.append("")
        if ctx.risk_flags:
            lines.append("## Risk Flags")
            for rf in ctx.risk_flags:
                lines.append(f"- [{rf['severity']}] {rf['description']}")
        return "\n".join(lines)


_COMMON_WORDS: set[str] = {
    "THE",
    "AND",
    "FOR",
    "ARE",
    "BUT",
    "NOT",
    "YOU",
    "ALL",
    "CAN",
    "HAD",
    "HER",
    "WAS",
    "ONE",
    "OUR",
    "OUT",
    "HAS",
    "HIS",
    "HOW",
    "ITS",
    "LET",
    "MAY",
    "NEW",
    "NOW",
    "OLD",
    "SEE",
    "WAY",
    "WHO",
    "DID",
    "GET",
    "HIM",
    "USE",
    "SAY",
    "SHE",
    "TOO",
    "ANY",
    "WITH",
    "FROM",
    "THAT",
    "THAN",
    "THIS",
    "WHAT",
    "WHEN",
    "WILL",
    "JUST",
    "ALSO",
    "BEEN",
    "EACH",
    "HAVE",
    "MUCH",
    "ONLY",
    "OVER",
    "SOME",
    "SUCH",
    "THEM",
    "THEN",
    "THEY",
    "VERY",
    "WERE",
    "YOUR",
    "ABOUT",
    "AFTER",
    "COULD",
    "EVERY",
    "OTHER",
    "THEIR",
    "THERE",
    "THESE",
    "THOSE",
    "WHICH",
    "WOULD",
    "BEING",
    "STILL",
    "WHERE",
    "BUY",
    "SELL",
    "HOLD",
    "LONG",
    "PUT",
    "CALL",
    "ETF",
    "IPO",
    "RSI",
    "EPS",
    "PEG",
    "ROE",
    "ROA",
    "USA",
    "USD",
    "CNY",
    "HKD",
    "EUR",
    "GBP",
    "STOCK",
    "TRADE",
    "PRICE",
    "INDEX",
    "FUND",
    "HIGH",
    "LOW",
    "OPEN",
    "CLOSE",
    "STOP",
    "LOSS",
    "TREND",
    "BULL",
    "BEAR",
    "RISK",
    "CASH",
    "BOND",
    "MACD",
    "VWAP",
    "BOLL",
}


def _extract_stock_code(text: str) -> str:
    """Best-effort stock code extraction from free text."""
    import re

    match = re.search(r"(?<!\d)([036]\d{5})(?!\d)", text)
    if match:
        return match.group(1)
    match = re.search(r"(?<![a-zA-Z])(hk\d{5})(?!\d)", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    match = re.search(r"(?<![a-zA-Z])([A-Z]{2,5})(?![a-zA-Z])", text)
    if match:
        candidate = match.group(1)
        if candidate not in _COMMON_WORDS:
            return candidate
    return ""
