# -*- coding: utf-8 -*-
"""Shared factory for building configured agent executors/orchestrators."""

import copy
import importlib
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level caches
# ---------------------------------------------------------------------------
_TOOL_REGISTRY = None
_SKILL_MANAGER_PROTOTYPE = None
# Sentinel used as initial value so None (i.e. no custom dir) compares as "changed"
# on the very first call, forcing a build rather than accidentally skipping it.
_SENTINEL = object()
# Track which custom_dir the prototype was built with so we can invalidate
# the cache if AGENT_STRATEGY_DIR changes at runtime (e.g. via config reload).
_SKILL_MANAGER_CUSTOM_DIR: object = _SENTINEL

DEFAULT_AGENT_SKILLS = [
    "bull_trend",
    "ma_golden_cross",
    "volume_breakout",
    "shrink_pullback",
]


def _get_runtime_config():
    config_module = importlib.import_module("src.config")
    return config_module.get_config()


def get_tool_registry():
    """Return a cached ToolRegistry (built once, shared across requests)."""
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY is not None:
        return _TOOL_REGISTRY

    from src.agent.tools.registry import ToolRegistry
    from src.agent.tools.data_tools import ALL_DATA_TOOLS
    from src.agent.tools.analysis_tools import ALL_ANALYSIS_TOOLS
    from src.agent.tools.search_tools import ALL_SEARCH_TOOLS
    from src.agent.tools.market_tools import ALL_MARKET_TOOLS
    from src.agent.tools.backtest_tools import ALL_BACKTEST_TOOLS

    registry = ToolRegistry()
    for tool_fn in (
        ALL_DATA_TOOLS
        + ALL_ANALYSIS_TOOLS
        + ALL_SEARCH_TOOLS
        + ALL_MARKET_TOOLS
        + ALL_BACKTEST_TOOLS
    ):
        registry.register(tool_fn)

    _TOOL_REGISTRY = registry
    logger.info(
        "[AgentFactory] ToolRegistry cached (%d tools)",
        len(registry._tools) if hasattr(registry, "_tools") else -1,
    )
    return _TOOL_REGISTRY


def get_skill_manager(config=None):
    """Return a deepcopy-clone of the cached SkillManager prototype.

    The prototype is initialised from disk on first call; subsequent calls
    return ``copy.deepcopy(prototype)`` which is ~10× faster than re-reading
    YAML files.  Each clone is independent so ``.activate()`` calls do not
    bleed between requests.

    Cache invalidation: if ``config.agent_strategy_dir`` changes at runtime
    (e.g. via the web settings reload), the prototype is rebuilt automatically.
    """
    global _SKILL_MANAGER_PROTOTYPE, _SKILL_MANAGER_CUSTOM_DIR

    if config is None:
        config = _get_runtime_config()

    current_custom_dir = getattr(config, "agent_strategy_dir", None)
    if (
        _SKILL_MANAGER_PROTOTYPE is not None
        and current_custom_dir == _SKILL_MANAGER_CUSTOM_DIR
    ):
        return copy.deepcopy(_SKILL_MANAGER_PROTOTYPE)

    from src.agent.skills.base import SkillManager

    if _SKILL_MANAGER_PROTOTYPE is not None:
        logger.info(
            "[AgentFactory] SkillManager prototype invalidated (agent_strategy_dir changed: %r → %r)",
            _SKILL_MANAGER_CUSTOM_DIR,
            current_custom_dir,
        )

    skill_manager = SkillManager()
    skill_manager.load_builtin_strategies()

    if current_custom_dir:
        try:
            skill_manager.load_custom_strategies(current_custom_dir)
        except Exception as exc:
            logger.warning(
                "[AgentFactory] Failed to load custom strategies from %s: %s",
                current_custom_dir,
                exc,
            )

    _SKILL_MANAGER_PROTOTYPE = skill_manager
    _SKILL_MANAGER_CUSTOM_DIR = current_custom_dir
    logger.info(
        "[AgentFactory] SkillManager prototype cached (%d strategies)",
        len(skill_manager._skills),
    )
    return copy.deepcopy(_SKILL_MANAGER_PROTOTYPE)


def build_agent_executor(config=None, skills: Optional[List[str]] = None):
    """Build and return a configured AgentExecutor (or future orchestrator).

    When ``AGENT_ARCH=multi``, this returns an orchestrator that manages
    multiple specialised agents. Otherwise it returns the legacy single-agent
    executor.

    Args:
        config: Application config object.  When *None*, ``get_config()`` is
                called automatically.
        skills: Strategy ids to activate.  When *None* falls back to
                ``config.agent_skills``; if that is also empty falls back to
                ``DEFAULT_AGENT_SKILLS``.

    Returns:
        A ready-to-call executor/orchestrator instance exposing ``run`` and ``chat``.
    """
    if config is None:
        config = _get_runtime_config()

    arch = getattr(config, "agent_arch", "single")
    from src.agent.llm_adapter import LLMToolAdapter

    registry = get_tool_registry()
    skill_manager = get_skill_manager(config)

    skills_to_activate = (
        skills
        if skills is not None
        else (getattr(config, "agent_skills", None) or DEFAULT_AGENT_SKILLS)
    )
    skill_manager.activate(skills_to_activate if skills_to_activate else ["all"])
    logger.info(
        "[AgentFactory] Activated strategies: %s (arch=%s)", skills_to_activate, arch
    )

    llm_adapter = LLMToolAdapter(config)

    if arch == "multi":
        return _build_orchestrator(config, registry, llm_adapter, skill_manager)

    from src.agent.executor import AgentExecutor

    return AgentExecutor(
        tool_registry=registry,
        llm_adapter=llm_adapter,
        skill_instructions=skill_manager.get_skill_instructions(),
        max_steps=getattr(config, "agent_max_steps", 10),
    )


def _build_orchestrator(config, registry, llm_adapter, skill_manager):
    """Build and return an :class:`AgentOrchestrator` (multi-agent mode).

    The orchestrator presents the same ``run()`` / ``chat()`` interface as
    :class:`AgentExecutor` so callers need no changes.
    """
    from src.agent.orchestrator import AgentOrchestrator

    mode = getattr(config, "agent_orchestrator_mode", "standard")
    logger.info("[AgentFactory] Building AgentOrchestrator (mode=%s)", mode)

    return AgentOrchestrator(
        tool_registry=registry,
        llm_adapter=llm_adapter,
        skill_instructions=skill_manager.get_skill_instructions(),
        max_steps=getattr(config, "agent_max_steps", 10),
        mode=mode,
        skill_manager=skill_manager,
        config=config,
    )


def build_recommendation_agent(
    config=None,
    dimension: Optional[str] = None,
    skills: Optional[List[str]] = None,
):
    """Build and return a recommendation agent instance.

    Prefers unified ``RecommendationAgent`` when available and falls back to
    legacy recommendation agent classes for compatibility during migration.
    """
    if config is None:
        config = _get_runtime_config()

    from src.agent.llm_adapter import LLMToolAdapter

    registry = get_tool_registry()
    skill_manager = get_skill_manager(config)

    skills_to_activate = (
        skills
        if skills is not None
        else (getattr(config, "agent_skills", None) or DEFAULT_AGENT_SKILLS)
    )
    skill_manager.activate(skills_to_activate if skills_to_activate else ["all"])

    llm_adapter = LLMToolAdapter(config)
    common_kwargs = {
        "tool_registry": registry,
        "llm_adapter": llm_adapter,
        "skill_instructions": skill_manager.get_skill_instructions(),
    }

    recommendation_cls = None
    try:
        recommendation_module = importlib.import_module(
            "src.agent.agents.recommendation_agent"
        )
        recommendation_cls = getattr(recommendation_module, "RecommendationAgent")
    except Exception:
        if dimension:
            legacy_map = {
                "technical": "RecommendationTechnicalAgent",
                "fundamental": "RecommendationFundamentalAgent",
                "sentiment": "RecommendationSentimentAgent",
                "macro": "RecommendationMacroAgent",
                "risk": "RecommendationRiskAgent",
            }
            legacy_name = legacy_map.get(str(dimension).lower())
            if legacy_name:
                legacy_module = importlib.import_module("src.agent.agents")
                recommendation_cls = getattr(legacy_module, legacy_name, None)

    if recommendation_cls is None:
        raise ImportError("Recommendation agent implementation is not available")

    if dimension is not None:
        try:
            return recommendation_cls(dimension=dimension, **common_kwargs)
        except TypeError:
            pass

    return recommendation_cls(**common_kwargs)


# Keep legacy alias so any external callers using the old name still work.
build_executor = build_agent_executor
