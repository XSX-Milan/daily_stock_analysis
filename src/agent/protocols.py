# -*- coding: utf-8 -*-
"""
Shared protocols — common data structures for multi-agent communication.

Provides the foundational types that all agents, runners, and orchestrators
share. These are intentionally plain dataclasses so they can be serialized,
logged, and passed across process boundaries.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Signal(str, Enum):
    """Standardized trading signal labels."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class StageStatus(str, Enum):
    """Lifecycle status of a pipeline stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentContext:
    """Shared context carried across all agents in a single run."""

    query: str = ""
    stock_code: str = ""
    stock_name: str = ""
    session_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    opinions: List["AgentOpinion"] = field(default_factory=list)
    risk_flags: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def add_opinion(self, opinion: "AgentOpinion") -> None:
        """Append an opinion and auto-set timestamp if missing."""
        if opinion.timestamp == 0:
            opinion.timestamp = time.time()
        self.opinions.append(opinion)

    def add_risk_flag(
        self, category: str, description: str, severity: str = "medium"
    ) -> None:
        self.risk_flags.append(
            {
                "category": category,
                "description": description,
                "severity": severity,
                "timestamp": time.time(),
            }
        )

    def get_data(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        self.data[key] = value

    @property
    def has_risk_flags(self) -> bool:
        return len(self.risk_flags) > 0


@dataclass
class AgentOpinion:
    """One agent's structured analysis opinion on a stock."""

    agent_name: str = ""
    signal: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    key_levels: Dict[str, float] = field(default_factory=dict)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    @property
    def signal_enum(self) -> Optional[Signal]:
        """Try to parse ``signal`` into ``Signal``; return None if unknown."""
        try:
            return Signal(self.signal)
        except ValueError:
            return None


@dataclass
class StageResult:
    """Outcome of one pipeline stage (agent execution)."""

    stage_name: str = ""
    status: StageStatus = StageStatus.PENDING
    opinion: Optional[AgentOpinion] = None
    error: Optional[str] = None
    duration_s: float = 0.0
    tokens_used: int = 0
    tool_calls_count: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == StageStatus.COMPLETED


@dataclass
class AgentRunStats:
    """Aggregate run statistics across all agents in a pipeline."""

    total_stages: int = 0
    completed_stages: int = 0
    failed_stages: int = 0
    skipped_stages: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_duration_s: float = 0.0
    models_used: List[str] = field(default_factory=list)
    stage_results: List[StageResult] = field(default_factory=list)

    def record_stage(self, result: StageResult) -> None:
        """Record a stage result and update counters."""
        self.stage_results.append(result)
        self.total_stages += 1
        self.total_tokens += result.tokens_used
        self.total_tool_calls += result.tool_calls_count
        self.total_duration_s += result.duration_s

        if result.status == StageStatus.COMPLETED:
            self.completed_stages += 1
        elif result.status == StageStatus.FAILED:
            self.failed_stages += 1
        elif result.status == StageStatus.SKIPPED:
            self.skipped_stages += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_stages": self.total_stages,
            "completed_stages": self.completed_stages,
            "failed_stages": self.failed_stages,
            "skipped_stages": self.skipped_stages,
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "total_duration_s": round(self.total_duration_s, 2),
            "models_used": self.models_used,
        }
