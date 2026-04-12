"""Pydantic models that describe the output of one safety analysis.

Every model output that crosses a module boundary should be one of these
types. We never pass raw ``dict``s around — Pydantic validation at the
boundary catches malformed tool calls before they reach the dashboard.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class ThreatLevel(str, Enum):
    """Coarse-grained safety verdict for a single screenshot."""

    SAFE = "safe"
    CAUTION = "caution"
    WARNING = "warning"
    ALERT = "alert"
    CRITICAL = "critical"


class ThreatCategory(str, Enum):
    """Specific category of harmful content, if any."""

    NONE = "none"
    GROOMING = "grooming"
    BULLYING = "bullying"
    INAPPROPRIATE_CONTENT = "inappropriate_content"
    PERSONAL_INFO_SHARING = "personal_info_sharing"
    SCAM = "scam"


class GroomingStage(str, Enum):
    """Stage of the grooming pipeline (Olson et al. taxonomy)."""

    NONE = "none"
    TARGETING = "targeting"
    TRUST_BUILDING = "trust_building"
    ISOLATION = "isolation"
    DESENSITIZATION = "desensitization"
    MAINTAINING_CONTROL = "maintaining_control"


class AlertUrgency(str, Enum):
    """How quickly a parent should look at the alert."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    IMMEDIATE = "immediate"


class ChatMessage(BaseModel):
    """One message inside the captured conversation.

    Used by:

    - The dashboard's "fake browser" capture view, which renders the
      conversation as platform-styled chat bubbles. Each message can be
      tagged with a ``flag`` (e.g. "age inquiry", "isolation") so the
      front-end can outline it in red and show the indicator label.
    - The conversation-level analyzer, which accumulates messages across
      frames (via :class:`guardlens.conversation_store.ConversationStore`)
      and re-analyzes the full chat log to catch patterns that any single
      frame misses.
    """

    sender: str
    text: str
    flag: str | None = None


class ThreatClassification(BaseModel):
    """Output of the ``classify_threat`` tool call."""

    threat_level: ThreatLevel
    category: ThreatCategory
    confidence: float = Field(..., ge=0.0, le=100.0)
    reasoning: str
    indicators_found: list[str] = Field(default_factory=list)
    platform_detected: str | None = Field(
        None,
        description="The app/platform visible on screen, as identified by the model.",
    )
    visible_messages: list[ChatMessage] = Field(
        default_factory=list,
        description=(
            "Every distinct chat message visible on screen, extracted by the "
            "vision model. Feeds the conversation-level analyzer."
        ),
    )


class GroomingStageResult(BaseModel):
    """Output of the ``identify_grooming_stage`` tool call."""

    stage: GroomingStage
    evidence: list[str] = Field(default_factory=list)
    risk_escalation: bool = False


class ParentAlert(BaseModel):
    """Output of the ``generate_parent_alert`` tool call.

    Designed so the parent gets a useful summary *without* leaking the
    child's raw chat content.
    """

    alert_title: str
    summary: str
    recommended_action: str
    urgency: AlertUrgency


class SessionCertainty(str, Enum):
    """How much evidence the conversation-level verdict is based on.

    Distinct from per-verdict ``confidence``: a single frame can be 100%
    confidently classified but still have LOW session certainty because
    one frame is not enough evidence for a conversation-level decision.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SessionVerdict(BaseModel):
    """Output of a conversation-level safety analysis.

    Produced by :class:`guardlens.conversation_analyzer.ConversationAnalyzer`
    from the accumulated set of visible chat messages across frames.
    """

    overall_level: ThreatLevel
    overall_category: ThreatCategory
    confidence: float = Field(..., ge=0.0, le=100.0)
    certainty: SessionCertainty
    narrative: str = Field(
        ...,
        description="Short plain-English summary of the pattern observed across messages.",
    )
    key_indicators: list[str] = Field(default_factory=list)
    messages_analyzed: int = 0
    parent_alert_recommended: bool = False
    timestamp: datetime = Field(default_factory=datetime.now)


class ScreenAnalysis(BaseModel):
    """Full analysis result for one screenshot.

    This is what flows through the rest of the pipeline (session tracker,
    alerts, dashboard). Anything the parent or judge sees is rendered from
    a :class:`ScreenAnalysis`.
    """

    timestamp: datetime
    screenshot_path: Path
    platform: str | None = None
    raw_thinking: str | None = None
    classification: ThreatClassification
    grooming_stage: GroomingStageResult | None = None
    parent_alert: ParentAlert | None = None
    inference_seconds: float = Field(..., ge=0.0)
    chat_messages: list[ChatMessage] | None = Field(
        None,
        description=(
            "Reconstructed conversation as structured messages. Populated "
            "by the worker from demo scenario scripts or watch-folder "
            "metadata; may be None in real-screenshot mode."
        ),
    )

    @property
    def is_safe(self) -> bool:
        """``True`` when no follow-up action is needed."""
        return self.classification.threat_level == ThreatLevel.SAFE

    @property
    def needs_parent_attention(self) -> bool:
        """``True`` for warning/alert/critical verdicts."""
        return self.classification.threat_level in {
            ThreatLevel.WARNING,
            ThreatLevel.ALERT,
            ThreatLevel.CRITICAL,
        }
