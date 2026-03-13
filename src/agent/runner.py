# -*- coding: utf-8 -*-
"""Shared runner for LLM + tool execution loop."""

from __future__ import annotations

import json
import importlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.tools.registry import ToolRegistry
from src.storage import persist_llm_usage as _persist_usage

logger = logging.getLogger(__name__)

_THINKING_TOOL_LABELS: Dict[str, str] = {
    "get_realtime_quote": "行情获取",
    "get_daily_history": "K线数据获取",
    "analyze_trend": "技术指标分析",
    "get_chip_distribution": "筹码分布分析",
    "search_stock_news": "新闻搜索",
    "search_comprehensive_intel": "综合情报搜索",
    "get_market_indices": "市场概览获取",
    "get_sector_rankings": "行业板块分析",
    "get_analysis_context": "历史分析上下文",
    "get_stock_info": "基本信息获取",
    "analyze_pattern": "K线形态识别",
    "get_volume_analysis": "量能分析",
    "calculate_ma": "均线计算",
    "get_strategy_backtest_summary": "策略回测概览",
    "get_stock_backtest_summary": "个股回测数据",
}


@dataclass
class RunLoopResult:
    """Output produced by ``run_agent_loop``."""

    success: bool = False
    content: str = ""
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0
    provider: str = ""
    models_used: List[str] = field(default_factory=list)
    error: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def model(self) -> str:
        return ", ".join(dict.fromkeys(m for m in self.models_used if m))


def serialize_tool_result(result: Any) -> str:
    """Serialize a tool result to string consumable by an LLM."""
    if result is None:
        return json.dumps({"result": None})
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result)
    if hasattr(result, "__dict__"):
        try:
            data = {k: v for k, v in result.__dict__.items() if not k.startswith("_")}
            return json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result)
    return str(result)


def try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON dict extraction from LLM text."""
    if not text:
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


_try_parse_json = try_parse_json


def _try_repair_json(text: str, repair_fn: Callable) -> Optional[Dict[str, Any]]:
    try:
        repaired = repair_fn(text)
        obj = json.loads(repaired)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def parse_dashboard_json(content: str) -> Optional[Dict[str, Any]]:
    """Extract and parse dashboard JSON from agent text."""
    if not content:
        return None

    repair_json = None
    try:
        json_repair_module = importlib.import_module("json_repair")
        repair_json = getattr(json_repair_module, "repair_json", None)
    except Exception:
        repair_json = None

    json_blocks = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if json_blocks:
        for block in json_blocks:
            parsed = _try_parse_json(block)
            if parsed is not None:
                return parsed
            if repair_json is not None:
                parsed = _try_repair_json(block, repair_json)
                if parsed is not None:
                    return parsed

    parsed = _try_parse_json(content)
    if parsed is not None:
        return parsed

    if repair_json is not None:
        parsed = _try_repair_json(content, repair_json)
        if parsed is not None:
            return parsed

    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        candidate = content[start : end + 1]
        parsed = _try_parse_json(candidate)
        if parsed is not None:
            return parsed
        if repair_json is not None:
            parsed = _try_repair_json(candidate, repair_json)
            if parsed is not None:
                return parsed

    logger.warning("Failed to parse dashboard JSON from agent response")
    return None


def run_agent_loop(
    *,
    messages: List[Dict[str, Any]],
    tool_registry: ToolRegistry,
    llm_adapter: LLMToolAdapter,
    max_steps: int = 10,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    thinking_labels: Optional[Dict[str, str]] = None,
) -> RunLoopResult:
    """Execute the ReAct LLM-tool loop."""
    labels = thinking_labels or _THINKING_TOOL_LABELS
    tool_decls = tool_registry.to_openai_tools()

    start_time = time.time()
    tool_calls_log: List[Dict[str, Any]] = []
    total_tokens = 0
    provider_used = ""
    models_used: List[str] = []

    for step in range(max_steps):
        if progress_callback:
            if not tool_calls_log:
                thinking_msg = "正在制定分析路径..."
            else:
                last_tool = tool_calls_log[-1].get("tool", "")
                label = labels.get(last_tool, last_tool)
                thinking_msg = f"「{label}」已完成，继续深入分析..."
            progress_callback(
                {"type": "thinking", "step": step + 1, "message": thinking_msg}
            )

        response = llm_adapter.call_with_tools(messages, tool_decls)
        provider_used = response.provider
        total_tokens += response.usage.get("total_tokens", 0)

        model_name = getattr(response, "model", "") or response.provider
        if model_name and model_name != "error":
            models_used.append(model_name)
        if model_name and model_name != "error" and response.usage:
            _persist_usage(response.usage, model_name, call_type="agent")

        if response.tool_calls:
            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        **(
                            {"thought_signature": tc.thought_signature}
                            if tc.thought_signature is not None
                            else {}
                        ),
                    }
                    for tc in response.tool_calls
                ],
            }
            if response.reasoning_content is not None:
                assistant_msg["reasoning_content"] = response.reasoning_content
            messages.append(assistant_msg)

            tool_results = _execute_tools(
                response.tool_calls,
                tool_registry,
                step + 1,
                progress_callback,
                tool_calls_log,
            )

            tc_order = {tc.id: i for i, tc in enumerate(response.tool_calls)}
            tool_results.sort(key=lambda x: tc_order.get(x["tc"].id, 0))
            for tr in tool_results:
                messages.append(
                    {
                        "role": "tool",
                        "name": tr["tc"].name,
                        "tool_call_id": tr["tc"].id,
                        "content": tr["result_str"],
                    }
                )
        else:
            if progress_callback:
                progress_callback(
                    {
                        "type": "generating",
                        "step": step + 1,
                        "message": "正在生成最终分析...",
                    }
                )

            final_content = response.content or ""
            is_error = response.provider == "error"
            return RunLoopResult(
                success=not is_error and bool(final_content),
                content=final_content if not is_error else "",
                tool_calls_log=tool_calls_log,
                total_steps=step + 1,
                total_tokens=total_tokens,
                provider=provider_used,
                models_used=models_used,
                error=final_content if is_error else None,
                messages=messages,
            )

    logger.warning("Agent hit max steps (%d)", max_steps)
    return RunLoopResult(
        success=False,
        content="",
        tool_calls_log=tool_calls_log,
        total_steps=max_steps,
        total_tokens=total_tokens,
        provider=provider_used,
        models_used=models_used,
        error=f"Agent exceeded max steps ({max_steps})",
        messages=messages,
    )


def _execute_tools(
    tool_calls,
    tool_registry: ToolRegistry,
    step: int,
    progress_callback: Optional[Callable],
    tool_calls_log: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Execute one or more tool calls and return ordered results."""

    def _exec_single(tc_item):
        t0 = time.time()
        try:
            result = tool_registry.execute(tc_item.name, **tc_item.arguments)
            result_str = serialize_tool_result(result)
            success = True
        except Exception as exc:
            result_str = json.dumps({"error": str(exc)})
            success = False
            logger.warning("Tool '%s' failed: %s", tc_item.name, exc)
        duration = round(time.time() - t0, 2)
        return tc_item, result_str, success, duration

    results: List[Dict[str, Any]] = []

    if len(tool_calls) == 1:
        tc = tool_calls[0]
        if progress_callback:
            progress_callback({"type": "tool_start", "step": step, "tool": tc.name})
        _, result_str, success, duration = _exec_single(tc)
        if progress_callback:
            progress_callback(
                {
                    "type": "tool_done",
                    "step": step,
                    "tool": tc.name,
                    "success": success,
                    "duration": duration,
                }
            )
        tool_calls_log.append(
            {
                "step": step,
                "tool": tc.name,
                "arguments": tc.arguments,
                "success": success,
                "duration": duration,
                "result_length": len(result_str),
            }
        )
        results.append({"tc": tc, "result_str": result_str})
    else:
        for tc in tool_calls:
            if progress_callback:
                progress_callback({"type": "tool_start", "step": step, "tool": tc.name})

        with ThreadPoolExecutor(max_workers=min(len(tool_calls), 5)) as pool:
            futures = {pool.submit(_exec_single, tc): tc for tc in tool_calls}
            for future in as_completed(futures):
                tc_item, result_str, success, duration = future.result()
                if progress_callback:
                    progress_callback(
                        {
                            "type": "tool_done",
                            "step": step,
                            "tool": tc_item.name,
                            "success": success,
                            "duration": duration,
                        }
                    )
                tool_calls_log.append(
                    {
                        "step": step,
                        "tool": tc_item.name,
                        "arguments": tc_item.arguments,
                        "success": success,
                        "duration": duration,
                        "result_length": len(result_str),
                    }
                )
                results.append({"tc": tc_item, "result_str": result_str})

    return results
