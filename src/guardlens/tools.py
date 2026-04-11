"""Function-calling tool definitions for the Gemma 4 safety analyzer.

These dictionaries are passed to :func:`ollama.Client.chat` via the ``tools``
argument. They use the standard OpenAI/Ollama function-calling JSON Schema
format, which Gemma 4 supports natively.

Three tools, one per analysis stage:

1. ``classify_threat`` — always called.
2. ``identify_grooming_stage`` — only if a grooming risk is detected.
3. ``generate_parent_alert`` — only if a parent should actually be notified.
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


ASSESS_CONVERSATION_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "assess_conversation",
        "description": (
            "Produce a SINGLE verdict for an entire conversation accumulated "
            "across multiple screenshots. Unlike classify_threat which sees "
            "one frame, this tool sees the full accumulated chat log as "
            "plain text. Prefer this for alert decisions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "overall_level": {
                    "type": "string",
                    "enum": _enum_values(ThreatLevel),
                    "description": "Overall threat level for the whole conversation.",
                },
                "overall_category": {
                    "type": "string",
                    "enum": _enum_values(ThreatCategory),
                    "description": "Dominant category of concern across the conversation.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Confidence in the overall_level, 0-100.",
                },
                "certainty": {
                    "type": "string",
                    "enum": _enum_values(SessionCertainty),
                    "description": (
                        "How much evidence supports the verdict. LOW when you "
                        "have only 1-2 messages regardless of how suspicious "
                        "they look. MEDIUM when 3-5 messages consistently "
                        "suggest the same concern. HIGH when 6+ messages show "
                        "a clear pattern."
                    ),
                },
                "narrative": {
                    "type": "string",
                    "description": (
                        "Plain-English summary of the pattern (e.g. 'Over 6 "
                        "messages, ShadowPro escalated from greeting to "
                        "asking age to requesting platform migration')."
                    ),
                },
                "key_indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific indicators supporting the verdict.",
                },
                "parent_alert_recommended": {
                    "type": "boolean",
                    "description": (
                        "True only when you have at least MEDIUM certainty and "
                        "the overall_level is warning/alert/critical."
                    ),
                },
            },
            "required": [
                "overall_level",
                "overall_category",
                "confidence",
                "certainty",
                "narrative",
                "parent_alert_recommended",
            ],
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
