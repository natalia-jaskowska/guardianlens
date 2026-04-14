"""Cross-frame pattern detector for per-participant threat escalation.

One frame says "SAFE"; the next says "CAUTION: age inquiry"; the next
says "WARNING: isolation"; the next says "ALERT: grooming stage 4". In
isolation, any one of those is noise. Together they are an escalating
pattern — the signal the parent actually needs.

:class:`EscalationTracker` keeps a small per-participant history so it
can answer three questions:

- Is this participant's threat level rising over time?
- How fast is it rising (escalation_speed)?
- Has the indicator set grown in a concerning way (e.g., from 0 → 4)?

It deliberately does NOT fire alerts — that is :mod:`guardlens.alerts`'s
job.  The tracker only produces a verdict object the alert gate can read.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque

from guardlens.schema import ThreatLevel

logger = logging.getLogger(__name__)

_LEVEL_ORDER: list[ThreatLevel] = [
    ThreatLevel.SAFE,
    ThreatLevel.CAUTION,
    ThreatLevel.WARNING,
    ThreatLevel.ALERT,
    ThreatLevel.CRITICAL,
]


def _level_rank(level: ThreatLevel) -> int:
    return _LEVEL_ORDER.index(level)


@dataclass
class EscalationVerdict:
    """Summary of one participant's trajectory."""

    escalating: bool
    escalation_speed: float  # levels per observation (0 = flat; 1 = one step per frame)
    highest_level: ThreatLevel
    indicators_growth: int  # net new indicators added since tracking started
    observation_count: int


@dataclass
class _ParticipantHistory:
    levels: Deque[ThreatLevel] = field(default_factory=lambda: deque(maxlen=20))
    indicators_seen: set[str] = field(default_factory=set)
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)


class EscalationTracker:
    """Per-participant trajectory tracker.

    Thread-safe. Memory bounded: each participant keeps the last 20
    observations (sliding window), more than enough to read a trend
    without unbounded growth during a long session.
    """

    def __init__(self, window: int = 20) -> None:
        self._window = window
        self._histories: dict[tuple[str, str], _ParticipantHistory] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ update

    def observe(
        self,
        platform: str,
        participant: str,
        level: ThreatLevel,
        indicators: list[str] | None = None,
    ) -> EscalationVerdict:
        """Record one observation and return the current verdict."""
        key = self._key(platform, participant)
        inds = indicators or []

        with self._lock:
            hist = self._histories.get(key)
            if hist is None:
                hist = _ParticipantHistory(levels=deque(maxlen=self._window))
                self._histories[key] = hist
            hist.levels.append(level)
            for ind in inds:
                if ind:
                    hist.indicators_seen.add(ind)
            hist.last_seen = datetime.now()
            verdict = self._verdict_locked(hist)

        logger.debug(
            "EscalationTracker[%s/%s]: level=%s speed=%.2f highest=%s growth=%d n=%d escalating=%s",
            key[0],
            key[1],
            level.value,
            verdict.escalation_speed,
            verdict.highest_level.value,
            verdict.indicators_growth,
            verdict.observation_count,
            verdict.escalating,
        )
        return verdict

    def verdict_for(
        self, platform: str, participant: str
    ) -> EscalationVerdict | None:
        key = self._key(platform, participant)
        with self._lock:
            hist = self._histories.get(key)
            if hist is None:
                return None
            return self._verdict_locked(hist)

    def reset(self) -> None:
        with self._lock:
            self._histories.clear()
        logger.info("EscalationTracker: reset")

    # ------------------------------------------------------------------ internal

    @staticmethod
    def _key(platform: str, participant: str) -> tuple[str, str]:
        return (platform.strip().lower(), participant.strip())

    def _verdict_locked(self, hist: _ParticipantHistory) -> EscalationVerdict:
        levels = list(hist.levels)
        n = len(levels)
        if n == 0:
            return EscalationVerdict(
                escalating=False,
                escalation_speed=0.0,
                highest_level=ThreatLevel.SAFE,
                indicators_growth=0,
                observation_count=0,
            )

        ranks = [_level_rank(lv) for lv in levels]
        highest = _LEVEL_ORDER[max(ranks)]
        # Speed: average forward delta across the window, clipped at 0.
        deltas = [max(0, ranks[i] - ranks[i - 1]) for i in range(1, n)]
        speed = (sum(deltas) / len(deltas)) if deltas else 0.0
        # Escalating when:
        #   - we have at least 2 observations AND
        #   - the last observation is strictly higher than the first, OR
        #   - average speed > 0.25 (roughly: one full level every 4 frames).
        escalating = n >= 2 and (
            ranks[-1] > ranks[0] or speed > 0.25
        )

        return EscalationVerdict(
            escalating=escalating,
            escalation_speed=float(speed),
            highest_level=highest,
            indicators_growth=len(hist.indicators_seen),
            observation_count=n,
        )


__all__ = ["EscalationTracker", "EscalationVerdict"]
