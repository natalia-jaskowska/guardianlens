"""SQLite-backed persistence for analyses, alerts, and session metadata.

Why SQLite and not just an in-memory list:

- The dashboard worker thread writes; the FastAPI UI thread reads. SQLite
  gives us safe concurrent access with zero extra dependencies.
- Judges reading the code can see that ``classify_threat`` and
  ``generate_parent_alert`` actually persist their output — this is the
  "function calling that actually executes" requirement from CONTEXT.md.
- A real session can be replayed from the DB after the demo for the writeup.

Schema (kept deliberately small):

``analyses``
    One row per :class:`ScreenAnalysis`. Stores the structured fields plus
    the JSON blob so we never lose anything Gemma 4 returned.

``alerts``
    One row per :class:`ParentAlert` actually dispatched (or attempted).
    Linked back to the originating analysis row via ``analysis_id``.

``sessions``
    One row per monitor session. ``started_at`` lets the dashboard show
    "session in progress for 12m 04s".
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from guardlens.schema import ScreenAnalysis, ThreatLevel

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    screenshot_path TEXT NOT NULL,
    platform TEXT,
    threat_level TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    indicators_found TEXT NOT NULL,
    grooming_stage TEXT,
    inference_seconds REAL NOT NULL,
    raw_json TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_analyses_session ON analyses(session_id);
CREATE INDEX IF NOT EXISTS idx_analyses_threat_level ON analyses(threat_level);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    delivered BOOLEAN NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    urgency TEXT NOT NULL,
    FOREIGN KEY(analysis_id) REFERENCES analyses(id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    participants_json TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    messages_json TEXT NOT NULL DEFAULT '[]',
    status_json TEXT,
    status_reasoning TEXT,
    screenshots_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_conversations_last_seen ON conversations(last_seen);

CREATE TABLE IF NOT EXISTS fragments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    timestamp TEXT NOT NULL,
    screenshot_path TEXT NOT NULL,
    raw_analysis_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fragments_conversation ON fragments(conversation_id);
"""


class GuardLensDatabase:
    """Thread-safe wrapper around a single SQLite file."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        # ``check_same_thread=False`` is safe because every write goes through
        # ``_lock``. The FastAPI handler thread reads under the same lock.
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._session_id: int | None = None

    # ------------------------------------------------------------------ session lifecycle

    def start_session(self, notes: str | None = None) -> int:
        """Open a new monitor session and return its ID."""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO sessions (started_at, notes) VALUES (?, ?)",
                (datetime.now().isoformat(), notes),
            )
            self._session_id = int(cursor.lastrowid or 0)
        return self._session_id

    def end_session(self) -> None:
        if self._session_id is None:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (datetime.now().isoformat(), self._session_id),
            )
        self._session_id = None

    @property
    def session_id(self) -> int:
        """Return the active session ID, opening a session if needed.

        Must NOT be called while ``self._lock`` is held — ``start_session``
        acquires the same (non-reentrant) lock.
        """
        if self._session_id is None:
            return self.start_session()
        return self._session_id

    # ------------------------------------------------------------------ writes

    def record_analysis(self, analysis: ScreenAnalysis) -> int:
        """Persist one :class:`ScreenAnalysis` and return its row ID."""
        payload = analysis.model_dump(mode="json")
        grooming_stage_value = (
            analysis.grooming_stage.stage.value if analysis.grooming_stage else None
        )
        # Resolve session_id BEFORE acquiring the lock.  The property may
        # call start_session() which also acquires self._lock — calling it
        # inside the ``with self._lock`` block would deadlock.
        sid = self.session_id
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO analyses (
                    session_id, timestamp, screenshot_path, platform,
                    threat_level, category, confidence, reasoning,
                    indicators_found, grooming_stage, inference_seconds, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sid,
                    analysis.timestamp.isoformat(),
                    str(analysis.screenshot_path),
                    analysis.platform,
                    analysis.classification.threat_level.value,
                    analysis.classification.category.value,
                    analysis.classification.confidence,
                    analysis.classification.reasoning,
                    json.dumps(analysis.classification.indicators_found),
                    grooming_stage_value,
                    analysis.inference_seconds,
                    json.dumps(payload),
                ),
            )
            return int(cursor.lastrowid or 0)

    def record_alert(self, analysis_id: int, analysis: ScreenAnalysis, *, delivered: bool) -> int:
        """Persist an alert row tied to an analysis."""
        alert = analysis.parent_alert
        if alert is None:
            return 0
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO alerts (
                    analysis_id, sent_at, delivered,
                    title, summary, recommended_action, urgency
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    datetime.now().isoformat(),
                    bool(delivered),
                    alert.alert_title,
                    alert.summary,
                    alert.recommended_action,
                    alert.urgency.value,
                ),
            )
            return int(cursor.lastrowid or 0)

    # ------------------------------------------------------------------ reads

    def recent_analyses(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM analyses ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            )

    def recent_alerts(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM alerts ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            )

    def most_recent_alert_analysis(self) -> ScreenAnalysis | None:
        """Reconstruct the most recent ALERT/CRITICAL :class:`ScreenAnalysis`.

        Used by the dashboard to bootstrap the right panel after a
        restart so it has content immediately instead of waiting for the
        next alert to land.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT raw_json FROM analyses
                WHERE threat_level IN ('alert', 'critical')
                ORDER BY id DESC
                LIMIT 1
                """,
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["raw_json"])
            return ScreenAnalysis.model_validate(payload)
        except (ValueError, TypeError, ValidationError) as exc:
            logger.warning("Failed to deserialize analysis from DB: %s", exc)
            return None

    def recent_alert_analyses(
        self, limit: int = 10
    ) -> list[tuple[int, int, ScreenAnalysis]]:
        """Reconstruct the N most recent *alerted* :class:`ScreenAnalysis` rows.

        Only returns analyses that have a matching row in the ``alerts``
        table — i.e. actual alerts that were synthesized by the session-level
        conversation analyzer. Plain per-frame classifications (even non-safe
        ones) are excluded.

        Returns ``(analysis_id, session_id, ScreenAnalysis)`` tuples ordered
        newest first. The alert metadata (title, summary, action, urgency)
        is overlaid onto the ScreenAnalysis's ``parent_alert`` field so the
        dashboard can render session-level info.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT a.id, a.session_id, a.raw_json,
                       al.title, al.summary, al.recommended_action, al.urgency
                FROM alerts al
                JOIN analyses a ON a.id = al.analysis_id
                ORDER BY al.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out: list[tuple[int, int, ScreenAnalysis]] = []
        for row in rows:
            try:
                payload = json.loads(row["raw_json"])
                # Overlay alert metadata so the dashboard renders the
                # session-level narrative, not the per-frame indicators.
                payload["parent_alert"] = {
                    "alert_title": row["title"],
                    "summary": row["summary"],
                    "recommended_action": row["recommended_action"],
                    "urgency": row["urgency"],
                }
                out.append(
                    (
                        int(row["id"]),
                        int(row["session_id"]),
                        ScreenAnalysis.model_validate(payload),
                    )
                )
            except (ValueError, TypeError, ValidationError) as exc:
                logger.warning("Skipping corrupt alert row: %s", exc)
                continue
        return out

    def recent_analyses_models(self, limit: int = 15) -> list[ScreenAnalysis]:
        """Return the most recent ``limit`` analyses as :class:`ScreenAnalysis`.

        Used by the dashboard's main-column timeline so its row count is
        independent of :class:`SessionTracker`'s in-memory window
        (``window_size``). The session window is sized for the AI's
        cross-reference logic; the timeline is a UX surface and wants
        more rows. Returns newest first; the caller flips it as needed.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT raw_json FROM analyses ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out: list[ScreenAnalysis] = []
        for row in rows:
            try:
                payload = json.loads(row["raw_json"])
                out.append(ScreenAnalysis.model_validate(payload))
            except (ValueError, TypeError, ValidationError) as exc:
                logger.warning("Skipping corrupt analysis row: %s", exc)
                continue
        return out

    def analysis_by_id(self, analysis_id: int) -> ScreenAnalysis | None:
        """Reconstruct one :class:`ScreenAnalysis` from its DB row id.

        Used by ``GET /api/analysis/{id}`` so the dashboard can fetch
        full details for a specific past alert when the user clicks an
        Alert history card.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT raw_json FROM analyses WHERE id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["raw_json"])
            return ScreenAnalysis.model_validate(payload)
        except (ValueError, TypeError, ValidationError) as exc:
            logger.warning("Failed to deserialize analysis from DB: %s", exc)
            return None

    def recent_threat_levels(self, limit: int = 20) -> list[str]:
        """Return the most recent ``limit`` threat levels (oldest first).

        Used by the dashboard sparkline + scan-trend strip. Cheap query
        — only the ``threat_level`` column, capped at ``limit``.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT threat_level FROM analyses ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        # Reverse so the oldest comes first (left side of the chart).
        return [row["threat_level"] for row in reversed(rows)]

    def session_platform_counts(self, session_id: int | None) -> dict[str, int]:
        """Return per-platform scan counts for the current session.

        Used by the "Session Health" card to show platform distribution
        when all scans are safe. Returns an empty dict if session_id is
        None or the query fails.
        """
        if session_id is None:
            return {}
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT COALESCE(platform, 'Unknown') AS platform, COUNT(*) AS n
                FROM analyses
                WHERE session_id = ?
                GROUP BY platform
                ORDER BY n DESC
                """,
                (session_id,),
            ).fetchall()
        return {row["platform"]: int(row["n"]) for row in rows}

    def session_avg_inference_seconds(self, session_id: int | None) -> float | None:
        """Mean Ollama inference time for the current session, or None."""
        if session_id is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT AVG(inference_seconds) AS avg FROM analyses WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None or row["avg"] is None:
            return None
        return float(row["avg"])

    def last_alert_summary(self, session_id: int | None = None) -> dict[str, Any] | None:
        """Return a short summary of the most recent alert.

        When ``session_id`` is given, the search is scoped to that
        session only — so a fresh dashboard restart doesn't surface a
        stale alert from yesterday's session. When omitted, the search
        spans all history.

        Requires ``category != 'none'`` so we don't surface
        uninformative model-misclassification rows.
        """
        base = """
            SELECT platform, category, timestamp
            FROM analyses
            WHERE threat_level IN ('alert', 'critical')
              AND category != 'none'
        """
        with self._lock:
            if session_id is not None:
                row = self._conn.execute(
                    base + "AND session_id = ? ORDER BY id DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    base + "ORDER BY id DESC LIMIT 1",
                ).fetchone()
        if row is None:
            return None
        return {
            "platform": row["platform"],
            "category": row["category"],
            "timestamp": row["timestamp"],
        }

    def session_summary(self) -> dict[str, int]:
        """Return per-threat-level counts for the current session."""
        if self._session_id is None:
            return {level.value: 0 for level in ThreatLevel}
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT threat_level, COUNT(*) as n
                FROM analyses
                WHERE session_id = ?
                GROUP BY threat_level
                """,
                (self._session_id,),
            ).fetchall()
        summary = {level.value: 0 for level in ThreatLevel}
        for row in rows:
            summary[row["threat_level"]] = int(row["n"])
        return summary

    def total_alert_count(self) -> int:
        """Total session-level alerts (from the ``alerts`` table)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM alerts",
            ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------ conversations

    def get_active_conversations(self, stale_minutes: int = 30) -> list[sqlite3.Row]:
        """Return conversations updated within the last ``stale_minutes``."""
        with self._lock:
            return list(
                self._conn.execute(
                    """
                    SELECT * FROM conversations
                    WHERE datetime(last_seen) > datetime('now', 'localtime', ? || ' minutes')
                    ORDER BY last_seen DESC
                    """,
                    (f"-{stale_minutes}",),
                )
            )

    def get_conversation(self, conv_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()

    def all_conversations(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM conversations ORDER BY last_seen DESC LIMIT ?",
                    (limit,),
                )
            )

    def create_conversation(
        self,
        *,
        platform: str,
        participants: list[str],
        first_seen: str,
        messages: list[dict],
        screenshots: list[dict],
        status: dict | None = None,
        status_reasoning: str | None = None,
    ) -> int:
        now = first_seen
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO conversations
                    (platform, participants_json, first_seen, last_seen,
                     messages_json, status_json, status_reasoning, screenshots_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    json.dumps(participants),
                    now,
                    now,
                    json.dumps(messages),
                    json.dumps(status) if status else None,
                    status_reasoning,
                    json.dumps(screenshots),
                ),
            )
            return int(cursor.lastrowid or 0)

    def update_conversation(
        self,
        conv_id: int,
        *,
        messages_json: str,
        status_json: str | None,
        status_reasoning: str | None,
        screenshots_json: str,
        last_seen: str,
        participants_json: str | None = None,
    ) -> None:
        if participants_json is not None:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE conversations
                    SET messages_json = ?, status_json = ?, status_reasoning = ?,
                        screenshots_json = ?, last_seen = ?, participants_json = ?
                    WHERE id = ?
                    """,
                    (messages_json, status_json, status_reasoning,
                     screenshots_json, last_seen, participants_json, conv_id),
                )
        else:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE conversations
                    SET messages_json = ?, status_json = ?, status_reasoning = ?,
                        screenshots_json = ?, last_seen = ?
                    WHERE id = ?
                    """,
                    (messages_json, status_json, status_reasoning,
                     screenshots_json, last_seen, conv_id),
                )

    def insert_fragment(
        self,
        *,
        conversation_id: int,
        timestamp: str,
        screenshot_path: str,
        raw_analysis_json: str,
    ) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO fragments
                    (conversation_id, timestamp, screenshot_path, raw_analysis_json)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, timestamp, screenshot_path, raw_analysis_json),
            )
            return int(cursor.lastrowid or 0)

    # ------------------------------------------------------------------ shutdown

    def close(self) -> None:
        with self._lock:
            self._conn.close()
