"""Shared data models for AiQA test results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Check:
    name: str
    expected: str
    actual: str
    passed: bool


@dataclass
class TestResult:
    test_id: str
    name: str
    status: str          # "pass", "fail", "skip", "error"
    duration_seconds: float = 0.0
    checks: list[Check] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    notes: str = ""
    error: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)

    @property
    def passed_checks(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total_checks(self) -> int:
        return len(self.checks)
