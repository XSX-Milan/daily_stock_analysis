# -*- coding: utf-8 -*-
"""Base class for specialized agents in the multi-agent pipeline."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.agent.runner import RunLoopResult, run_agent_loop
from src.agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all specialized agents."""

    agent_name: str = "base"
    tool_names: Optional[List[str]] = None
    max_steps: int = 6

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: LLMToolAdapter,
        skill_instructions: str = "",
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.skill_instructions = skill_instructions

    @abstractmethod
    def system_prompt(self, ctx: AgentContext) -> str:
        """Build the system prompt for this agent."""

    @abstractmethod
    def build_user_message(self, ctx: AgentContext) -> str:
        """Build the user message for this agent."""

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        """Extract structured opinion from model raw text."""
        return None

    def run(
        self,
        ctx: AgentContext,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> StageResult:
        """Execute this agent and return a stage result."""
        t0 = time.time()
        result = StageResult(stage_name=self.agent_name, status=StageStatus.RUNNING)

        try:
            messages = self._build_messages(ctx)
            registry = self._filtered_registry()

            loop_result: RunLoopResult = run_agent_loop(
                messages=messages,
                tool_registry=registry,
                llm_adapter=self.llm_adapter,
                max_steps=self.max_steps,
                progress_callback=progress_callback,
            )

            result.tokens_used = loop_result.total_tokens
            result.tool_calls_count = len(loop_result.tool_calls_log)
            result.meta["raw_text"] = loop_result.content
            result.meta["models_used"] = loop_result.models_used
            result.meta["tool_calls_log"] = loop_result.tool_calls_log

            if not loop_result.success:
                result.status = StageStatus.FAILED
                result.error = (
                    loop_result.error or "Agent loop did not produce a final answer"
                )
                return result

            opinion = self.post_process(ctx, loop_result.content)
            if opinion is not None:
                opinion.agent_name = self.agent_name
                ctx.add_opinion(opinion)
                result.opinion = opinion

            result.status = StageStatus.COMPLETED

        except Exception as exc:
            logger.error(
                "[%s] execution failed: %s", self.agent_name, exc, exc_info=True
            )
            result.status = StageStatus.FAILED
            result.error = str(exc)
        finally:
            result.duration_s = round(time.time() - t0, 2)

        return result

    def _build_messages(self, ctx: AgentContext) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt(ctx)}
        ]

        cached_data = self._inject_cached_data(ctx)
        if cached_data:
            messages.append({"role": "user", "content": cached_data})
            messages.append(
                {
                    "role": "assistant",
                    "content": "Understood, I have the pre-fetched data. Proceeding with analysis.",
                }
            )

        messages.append({"role": "user", "content": self.build_user_message(ctx)})
        return messages

    def _inject_cached_data(self, ctx: AgentContext) -> str:
        parts: List[str] = []
        for key, value in ctx.data.items():
            if value is not None:
                try:
                    serialized = json.dumps(value, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    serialized = str(value)
                if len(serialized) > 8000:
                    serialized = serialized[:8000] + "...(truncated)"
                parts.append(f"[Pre-fetched: {key}]\n{serialized}")
        return "\n\n".join(parts) if parts else ""

    def _filtered_registry(self) -> ToolRegistry:
        if self.tool_names is None:
            return self.tool_registry

        filtered = ToolRegistry()
        for name in self.tool_names:
            tool_def = self.tool_registry.get(name)
            if tool_def:
                filtered.register(tool_def)
            else:
                logger.warning(
                    "[%s] requested tool '%s' not found in registry",
                    self.agent_name,
                    name,
                )
        return filtered
