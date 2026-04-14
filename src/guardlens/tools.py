"""Ollama function-calling tool definitions for GuardianLens.

Production pipeline tools (used by :mod:`guardlens.pipeline`):
  PIPELINE_FRAME_TOOLS, PIPELINE_MATCH_TOOLS, PIPELINE_MERGE_TOOLS,
  PIPELINE_STATUS_TOOLS

Legacy per-frame tools (used by :mod:`guardlens.analyzer` for eval scripts):
  GUARDLENS_TOOLS (CLASSIFY_THREAT_TOOL, IDENTIFY_GROOMING_STAGE_TOOL,
  GENERATE_PARENT_ALERT_TOOL)
"""

from __future__ import annotations

from typing import Any

from guardlens.schema import (
    AlertUrgency,
    GroomingStage,
    SessionCertainty,
    ThreatCategory,
    ThreatLevel,
)


def _enum_values(enum_cls: type) -> list[str]:
    """Helper: dump an Enum's values into a JSON-Schema-friendly list."""
    return [member.value for member in enum_cls]


CLASSIFY_THREAT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "classify_threat",
        "description": "Classify the safety threat level of the screen content.",
        "parameters": {
            "type": "object",
            "properties": {
                "threat_level": {
                    "type": "string",
                    "enum": _enum_values(ThreatLevel),
                    "description": "Coarse-grained verdict for this screenshot.",
                },
                "category": {
                    "type": "string",
                    "enum": _enum_values(ThreatCategory),
                    "description": "Specific category of harmful content, if any.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Confidence in the verdict, 0-100.",
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "Concise (3-5 sentences) explanation of the verdict — "
                        "this is shown verbatim to the parent."
                    ),
                },
                "indicators_found": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Short bullet list of the specific indicators that triggered the verdict.",
                },
                "platform_detected": {
                    "type": "string",
                    "description": "What app/platform is visible on screen (Minecraft, Discord, Instagram, ...).",
                },
                "visible_messages": {
                    "type": "array",
                    "description": (
                        "Every distinct chat message currently visible on screen, "
                        "in the order they appear, as {sender, text} objects. "
                        "Extract faithfully — do not paraphrase. This is the only "
                        "place the conversation-level analyzer gets the text from."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "sender": {
                                "type": "string",
                                "description": "Username / handle of the message author.",
                            },
                            "text": {
                                "type": "string",
                                "description": "The exact text of the message as shown on screen.",
                            },
                        },
                        "required": ["sender", "text"],
                    },
                },
            },
            "required": ["threat_level", "category", "confidence", "reasoning"],
        },
    },
}



IDENTIFY_GROOMING_STAGE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "identify_grooming_stage",
        "description": (
            "If grooming is detected, identify which stage of the grooming "
            "process the conversation is in and provide supporting evidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": _enum_values(GroomingStage),
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Quoted or paraphrased evidence supporting the stage.",
                },
                "risk_escalation": {
                    "type": "boolean",
                    "description": "True if the conversation has moved to a more dangerous stage since the last screenshot.",
                },
            },
            "required": ["stage"],
        },
    },
}


GENERATE_PARENT_ALERT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_parent_alert",
        "description": (
            "Generate a concise alert for the parent. Do NOT include the raw "
            "chat content — only a high-level summary, recommended action, "
            "and urgency."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "alert_title": {"type": "string"},
                "summary": {"type": "string"},
                "recommended_action": {"type": "string"},
                "urgency": {
                    "type": "string",
                    "enum": _enum_values(AlertUrgency),
                },
            },
            "required": ["alert_title", "summary", "recommended_action", "urgency"],
        },
    },
}


GUARDLENS_TOOLS: list[dict[str, Any]] = [
    CLASSIFY_THREAT_TOOL,
    IDENTIFY_GROOMING_STAGE_TOOL,
    GENERATE_PARENT_ALERT_TOOL,
]
"""All tools, in the order Gemma 4 should consider them."""


# ====================== New conversation-first pipeline tools ======================

EXTRACT_CONVERSATIONS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "extract_conversations",
        "description": (
            "Extract ALL distinct chat conversations visible on screen. "
            "Each conversation is a distinct chat window or thread. "
            "Call this once with ALL conversations you can identify. "
            "Even if only one conversation is visible, return a list of one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "platform": {
                                "type": "string",
                                "description": "The platform (Discord, Instagram, Minecraft, etc.).",
                            },
                            "participants": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "All non-child usernames visible in this conversation."
                                ),
                            },
                            "messages": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "sender": {"type": "string"},
                                        "text": {"type": "string"},
                                    },
                                    "required": ["sender", "text"],
                                },
                                "description": (
                                    "Every chat message visible in this conversation, "
                                    "in order. Copy exact text — do not paraphrase."
                                ),
                            },
                        },
                        "required": ["platform", "participants", "messages"],
                    },
                },
            },
            "required": ["conversations"],
        },
    },
}


MATCH_CONVERSATION_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "match_conversation",
        "description": (
            "Decide whether a conversation fragment matches an existing "
            "tracked conversation, or is new. Return the matching "
            "conversation_id (integer) or null to create a new one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": ["integer", "null"],
                    "description": (
                        "ID of the matching existing conversation, or null "
                        "if this is a new conversation."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": "One sentence explaining the match/no-match decision.",
                },
            },
            "required": ["conversation_id", "reasoning"],
        },
    },
}


MERGE_MESSAGES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "merge_messages",
        "description": (
            "Produce a single deduplicated, chronologically ordered list of "
            "chat messages by merging the prior accumulated list with the new "
            "messages from the current frame. Remove exact or near-exact "
            "duplicates. Preserve all unique messages. Do not paraphrase."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "merged_messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sender": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "required": ["sender", "text"],
                    },
                    "description": "The full deduplicated ordered message list.",
                },
            },
            "required": ["merged_messages"],
        },
    },
}


UPDATE_CONVERSATION_STATUS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_conversation_status",
        "description": (
            "Produce an updated safety status for a tracked conversation, "
            "given the full accumulated message history and the prior status. "
            "You may revise the prior status up OR down based on new evidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "threat_level": {
                    "type": "string",
                    "enum": _enum_values(ThreatLevel),
                },
                "category": {
                    "type": "string",
                    "enum": _enum_values(ThreatCategory),
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                },
                "grooming_stage": {
                    "type": "string",
                    "enum": _enum_values(GroomingStage),
                },
                "indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific indicator labels supporting this verdict.",
                },
                "narrative": {
                    "type": "string",
                    "description": (
                        "2-4 sentence plain-English summary of the conversation "
                        "pattern. Parent-facing. No raw message text."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "Internal chain-of-thought: how the prior status + "
                        "new messages led to this verdict. Audit trail only."
                    ),
                },
                "parent_alert_recommended": {
                    "type": "boolean",
                    "description": (
                        "True only with medium/high certainty and "
                        "warning/alert/critical level."
                    ),
                },
                "certainty": {
                    "type": "string",
                    "enum": _enum_values(SessionCertainty),
                },
            },
            "required": [
                "threat_level", "category", "confidence",
                "narrative", "reasoning",
                "parent_alert_recommended", "certainty",
            ],
        },
    },
}


PIPELINE_FRAME_TOOLS: list[dict[str, Any]] = [EXTRACT_CONVERSATIONS_TOOL]
PIPELINE_MATCH_TOOLS: list[dict[str, Any]] = [MATCH_CONVERSATION_TOOL]
PIPELINE_MERGE_TOOLS: list[dict[str, Any]] = [MERGE_MESSAGES_TOOL]
PIPELINE_STATUS_TOOLS: list[dict[str, Any]] = [UPDATE_CONVERSATION_STATUS_TOOL]
