"""Sliding-window context tracker across screenshots.

Grooming is rarely visible from a single chat line — it builds across
minutes or hours of conversation. The :class:`SessionTracker` keeps the most
recent ``window_size`` analyses so the dashboard can:

- Show a timeline of recent verdicts.
- Detect escalation patterns (consecutive non-safe verdicts).
- Provide context to the analyzer for the next call (future work).

Memory is bounded — only the latest N analyses are retained.
"""

from __future__ import annotations

from collections import deque

from guardlens.config import SessionConfig
from guardlens.schema import GroomingStage, ScreenAnalysis, ThreatLevel


class SessionTracker:
    """Bounded sliding window over recent :class:`ScreenAnalysis` results."""

    def __init__(self, config: SessionConfig) -> None:
        self._config = config
        self._window: deque[ScreenAnalysis] = deque(maxlen=config.window_size)

    # ------------------------------------------------------------------ writes

    def add(self, analysis: ScreenAnalysis) -> None:
        """Append a new analysis to the window, dropping the oldest if full."""
        self._window.append(analysis)

    def clear(self) -> None:
        self._window.clear()

    # ------------------------------------------------------------------ reads

    def __len__(self) -> int:
        return len(self._window)

    def recent(self) -> list[ScreenAnalysis]:
        """Return all retained analyses, oldest first."""
        return list(self._window)

    def latest(self) -> ScreenAnalysis | None:
        return self._window[-1] if self._window else None

    # ------------------------------------------------------------------ derived signals

    def consecutive_unsafe(self) -> int:
        """How many of the most recent analyses were non-SAFE."""
        count = 0
        for analysis in reversed(self._window):
            if analysis.classification.threat_level == ThreatLevel.SAFE:
                break
            count += 1
        return count

    def has_escalating_pattern(self) -> bool:
        """``True`` if the recent window suggests an escalating threat.

        Two heuristics:
        1. ``escalation_threshold`` consecutive non-SAFE verdicts in a row.
        2. Any analysis explicitly flagged ``risk_escalation=True`` by the model.
        """
        if self.consecutive_unsafe() >= self._config.escalation_threshold:
            return True
        return any(
            a.grooming_stage is not None and a.grooming_stage.risk_escalation
            for a in self._window
        )

    def latest_grooming_stage(self) -> GroomingStage | None:
        """Most recent grooming stage detected, if any."""
        for analysis in reversed(self._window):
            if analysis.grooming_stage is not None:
                return analysis.grooming_stage.stage
        return None
