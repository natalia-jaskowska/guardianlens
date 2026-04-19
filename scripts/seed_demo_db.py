"""Seed the GuardianLens database with a fully-populated demo session.

Writes 11 conversations directly into ``outputs/guardlens.db`` so the
dashboard shows a realistic "parent checks in at 8pm" state the moment
it loads — no waiting for the pipeline to build up activity over 3
minutes of filming.

Each conversation is staggered backwards from "now" so timestamps
read like a real afternoon: 2h ago, 1h30m ago, ... just now. The
``short_summary`` / ``narrative`` / ``reasoning`` fields carry the
same shape the model produces, so the Recommendations panel and
Session Summary render identically to a real session.

Pair with ``scripts/render_demo_script.py`` to regenerate the matching
PNGs in ``outputs/video_feeds/demo_script/``.

Run from repo root::

    python scripts/seed_demo_db.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from guardlens.config import load_config
from guardlens.database import GuardLensDatabase  # triggers schema init


SCREENSHOT_DIR = PROJECT_ROOT / "outputs" / "video_feeds" / "demo_script"


# Every scene in the demo. "minutes_ago" is how far back last_seen sits;
# first_seen is derived as a few minutes earlier to make durations look
# natural. Screenshots reference the matching PNG under demo_script/.
SCENES = [
    {
        "tag": "01_discord_safe_project",
        "platform": "Discord",
        "minutes_ago": 125,  # ~2h
        "duration_min": 8,
        "participants": ["mia_w", "elan.nk"],
        "messages": [
            ("mia_w",   "hey are we still doing cells or did you want to do plants?"),
            ("elan.nk", "cells for sure, easier to draw"),
            ("child",   "same, i made a doc"),
            ("mia_w",   "omg legend"),
            ("elan.nk", "send link pls"),
            ("child",   "[doc link]"),
            ("mia_w",   "ok meeting wednesday 4pm after practice?"),
            ("elan.nk", "cool ill bring snacks"),
        ],
        "status": {
            "threat_level": "safe",
            "category": "none",
            "confidence": 92,
            "short_summary": "Three classmates coordinating a biology project; friendly peer chat.",
            "narrative": "Classmates coordinating a biology project about cells. Friendly and on-topic; planning a real-world meet-up after practice.",
            "reasoning": "Conversation is entirely about schoolwork and logistics. No personal info is shared with outsiders, no age-asking, no pressure. Typical peer planning.",
            "indicators": [],
            "grooming_stage": "none",
            "parent_alert_recommended": False,
            "certainty": "high",
        },
    },
    {
        "tag": "02_minecraft_safe_build",
        "platform": "Minecraft",
        "minutes_ago": 95,  # ~1h35m
        "duration_min": 12,
        "participants": ["cobbly_fern", "bluejaypath"],
        "messages": [
            ("cobbly_fern", "ok the castle needs another tower"),
            ("bluejaypath", "im on stone duty"),
            ("child",       "ill dig a moat"),
            ("cobbly_fern", "creeper behind you!!"),
            ("child",       "got him lol"),
            ("bluejaypath", "gg team"),
        ],
        "status": {
            "threat_level": "safe",
            "category": "none",
            "confidence": 95,
            "short_summary": "Cooperative building session; normal gameplay banter.",
            "narrative": "Three players divide roles to build a castle. Cooperative, on-topic, zero risk indicators.",
            "reasoning": "Collaborative task chat with no personal details exchanged. Standard Minecraft multiplayer etiquette.",
            "indicators": [],
            "grooming_stage": "none",
            "parent_alert_recommended": False,
            "certainty": "high",
        },
    },
    {
        "tag": "03_tiktok_safe_comments",
        "platform": "TikTok",
        "minutes_ago": 70,  # ~1h10m
        "duration_min": 3,
        "participants": ["zoetbh", "malik.writes", "auntie_t"],
        "messages": [
            ("zoetbh",       "the transition at 0:12 icon"),
            ("malik.writes", "teach me that step"),
            ("auntie_t",     "so proud! send me the song name"),
            ("child",        "silk runner - remix, ill text u"),
        ],
        "status": {
            "threat_level": "safe",
            "category": "none",
            "confidence": 94,
            "short_summary": "Friends and family reacting to a dance video; supportive comments.",
            "narrative": "Positive, supportive engagement from known peers and a family member. No strangers, no age-asking, no inappropriate content.",
            "reasoning": "Named family handle and familiar peer usernames. Comments are encouraging. No risk signals.",
            "indicators": [],
            "grooming_stage": "none",
            "parent_alert_recommended": False,
            "certainty": "high",
        },
    },
    {
        "tag": "04_discord_safe_birthday",
        "platform": "Discord",
        "minutes_ago": 50,
        "duration_min": 4,
        "participants": ["skye.parc"],
        "messages": [
            ("skye.parc", "ok so the plan: we distract her at lunch"),
            ("child",     "and hide the cake in the art room?"),
            ("skye.parc", "YES"),
            ("child",     "ms reeves already said ok"),
            ("skye.parc", "ur the best omg"),
        ],
        "status": {
            "threat_level": "safe",
            "category": "none",
            "confidence": 97,
            "short_summary": "Two friends planning a birthday surprise for a classmate.",
            "narrative": "Best-friend DM coordinating a classmate's birthday surprise. A teacher (ms reeves) is in the loop — adult oversight.",
            "reasoning": "Known close friend, wholesome pretext, teacher involvement named explicitly. No red flags.",
            "indicators": [],
            "grooming_stage": "none",
            "parent_alert_recommended": False,
            "certainty": "high",
        },
    },
    {
        "tag": "05_minecraft_caution_teasing",
        "platform": "Minecraft",
        "minutes_ago": 36,
        "duration_min": 3,
        "participants": ["slatepounce"],
        "messages": [
            ("slatepounce", "stop stealing my iron noob"),
            ("child",       "its a shared chest lmaoo"),
            ("slatepounce", "im coming for you"),
            ("child",       "bring it"),
            ("slatepounce", "ok truce wanna go mining together"),
            ("child",       "fine"),
        ],
        "status": {
            "threat_level": "safe",
            "category": "none",
            "confidence": 82,
            "short_summary": "Mutual teasing over in-game loot; ends in cooperation.",
            "narrative": "Two players spar verbally over shared resources, then resolve and team up. Reciprocal tone, not targeted.",
            "reasoning": "Teasing is two-sided and ends with a truce. Language is mild in-game trash talk, not demeaning. Not bullying.",
            "indicators": [],
            "grooming_stage": "none",
            "parent_alert_recommended": False,
            "certainty": "medium",
        },
    },
    {
        "tag": "06_tiktok_warning_stranger",
        "platform": "TikTok",
        "minutes_ago": 22,
        "duration_min": 2,
        "participants": ["x.vibes.z"],
        "messages": [
            ("x.vibes.z", "ur really pretty how old r u"),
            ("x.vibes.z", "dm me ill make u famous"),
        ],
        "status": {
            "threat_level": "warning",
            "category": "grooming",
            "confidence": 74,
            "short_summary": "Unknown adult-seeming account flattering the child and pushing for a DM.",
            "narrative": "Stranger comment opens with physical flattery, immediate age-ask, and a DM-bait 'make you famous' pitch. Classic low-commitment grooming opener on public video comments.",
            "reasoning": "Two-message exchange, but the pattern (flattery + age probe + off-platform DM push) fits stage-1/2 grooming. The child hasn't replied — good — but the account should be flagged so the parent can help block before engagement.",
            "indicators": ["age inquiry", "flattery", "DM migration attempt"],
            "grooming_stage": "trust building",
            "parent_alert_recommended": True,
            "certainty": "medium",
        },
    },
    {
        "tag": "07_discord_warning_scam",
        "platform": "Discord",
        "minutes_ago": 14,
        "duration_min": 2,
        "participants": ["FreeNitroDaily", "kade.x7"],
        "messages": [
            ("FreeNitroDaily", "CONGRATS! You've been selected for FREE DISCORD NITRO"),
            ("FreeNitroDaily", "Claim now before it expires - only 19 spots left"),
            ("FreeNitroDaily", "discordnitro-claim.link/verify"),
            ("kade.x7",        "bruh this is so fake"),
            ("child",          "yeah every server has this bot"),
            ("kade.x7",        "report and move"),
        ],
        "status": {
            "threat_level": "warning",
            "category": "scam",
            "confidence": 91,
            "short_summary": "Phishing bot spamming a fake Nitro giveaway; child recognized it.",
            "narrative": "Fake-giveaway bot posts urgency-driven links. Child and a friend correctly identified it as spam and moved on. Low actual risk, but worth flagging so the parent reinforces the lesson.",
            "reasoning": "Classic phishing signature (fake brand, urgency, credential link). Child's response shows they already know — no click, no interaction. Severity stays warning (not alert) because the child handled it.",
            "indicators": ["phishing link", "urgency", "fake giveaway"],
            "grooming_stage": "none",
            "parent_alert_recommended": True,
            "certainty": "high",
        },
    },
    {
        "tag": "08_discord_alert_grooming",
        "platform": "Discord",
        "minutes_ago": 8,
        "duration_min": 5,
        "participants": ["CoachMarcus"],
        "messages": [
            ("CoachMarcus", "gg out there, you're actually really good"),
            ("CoachMarcus", "how long have you been playing?"),
            ("child",       "like a year ig"),
            ("CoachMarcus", "no way you play that clean after a year lol. age?"),
            ("child",       "13 almost 14"),
            ("CoachMarcus", "cool im 16. dw im not a creep haha"),
            ("CoachMarcus", "i run a private coaching server, invite only. you in?"),
            ("CoachMarcus", "its on telegram tho discord is mid for voice"),
            ("CoachMarcus", "dont tell anyone tho i only pick a few"),
        ],
        "status": {
            "threat_level": "alert",
            "category": "grooming",
            "confidence": 96,
            "short_summary": "Stranger from public match DMs child, asks age, self-reassures 'not a creep', pushes to Telegram with secrecy.",
            "narrative": "A stranger met through public matchmaking has moved to DMs, opened with flattery, extracted the child's exact age, self-reassured ('dw im not a creep'), pitched an 'invite-only' coaching server on Telegram, and explicitly requested secrecy. Every stage of the grooming playbook is present in one conversation.",
            "reasoning": "Sequence hits multiple high-severity markers together: unsolicited compliment, age extraction, scripted 'not a creep' reassurance, platform migration to an unmonitored app, and secrecy request. The child has already disclosed age but has not yet moved platforms. This is the right moment for a parent to intervene before the chat leaves Discord.",
            "indicators": [
                "unsolicited compliment",
                "age inquiry",
                "scripted reassurance",
                "platform migration with secrecy",
                "age-gap deception",
            ],
            "grooming_stage": "isolation",
            "parent_alert_recommended": True,
            "certainty": "high",
        },
    },
    {
        "tag": "09_tiktok_alert_bullying",
        "platform": "TikTok",
        "minutes_ago": 4,
        "duration_min": 2,
        "participants": ["jilliaaan", "tara.k_", "rhiiannn", "mo.lyn"],
        "messages": [
            ("jilliaaan", "why do you always do the same dance lol"),
            ("tara.k_",   "literally cringe"),
            ("rhiiannn",  "nobody asked for this"),
            ("mo.lyn",    "imagine thinking ppl like u"),
            ("jilliaaan", "we made a gc laughing at u btw"),
            ("tara.k_",   "go private loser"),
        ],
        "status": {
            "threat_level": "alert",
            "category": "bullying",
            "confidence": 93,
            "short_summary": "Four peers pile on the child's video with mockery, insults, and exclusion.",
            "narrative": "Coordinated pile-on by four distinct peer accounts on a public video. Mockery of content, direct insults ('loser', 'cringe'), and explicit social exclusion ('we made a gc laughing at u'). Child has not replied.",
            "reasoning": "Meets every bullying threshold simultaneously: pile-on by multiple users, sustained targeting of one child, direct derogatory labels, and social-isolation language. The child is silent — likely overwhelmed. Parent should check in emotionally and help save evidence before messages are deleted.",
            "indicators": [
                "pile-on",
                "mockery",
                "name-calling",
                "social isolation language",
                "private group exclusion",
            ],
            "grooming_stage": "none",
            "parent_alert_recommended": True,
            "certainty": "high",
        },
    },
    {
        "tag": "10_minecraft_safe_trade",
        "platform": "Minecraft",
        "minutes_ago": 2,
        "duration_min": 1,
        "participants": ["emerald.gus"],
        "messages": [
            ("emerald.gus", "2 diamonds for your enchanted book?"),
            ("child",       "make it 3 its mending"),
            ("emerald.gus", "fair deal"),
            ("child",       "nice doing business"),
        ],
        "status": {
            "threat_level": "safe",
            "category": "none",
            "confidence": 96,
            "short_summary": "Quick in-game trade; normal transactional chat.",
            "narrative": "Short, civil trade negotiation for an enchanted book. Game-mechanic vocabulary only.",
            "reasoning": "No personal info, no emotional manipulation, no age-asking. Pure gameplay transaction.",
            "indicators": [],
            "grooming_stage": "none",
            "parent_alert_recommended": False,
            "certainty": "high",
        },
    },
    {
        "tag": "11_discord_safe_goodnight",
        "platform": "Discord",
        "minutes_ago": 0,  # just now
        "duration_min": 1,
        "participants": ["ren_ot"],
        "messages": [
            ("ren_ot", "night, see u tmrw"),
            ("child",  "night ren"),
            ("ren_ot", "dw about the tiktok stuff, theyre miserable"),
            ("child",  "ty"),
        ],
        "status": {
            "threat_level": "safe",
            "category": "none",
            "confidence": 98,
            "short_summary": "Best friend checks in on the child after the TikTok bullying; supportive closer.",
            "narrative": "Close friend references the earlier bullying and offers reassurance. Warm, brief DM.",
            "reasoning": "Supportive peer message. Named friend, emotional reassurance, no risk signals. Good outcome after the alert earlier.",
            "indicators": [],
            "grooming_stage": "none",
            "parent_alert_recommended": False,
            "certainty": "high",
        },
    },
]


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def seed() -> None:
    cfg = load_config(None)
    db_path = cfg.database.path

    # Instantiating the DB class runs schema migrations / creates tables
    # if the file is new. Close it immediately; we'll use a raw sqlite3
    # connection for the bulk inserts.
    GuardLensDatabase(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for table in ("conversations", "analyses", "alerts", "fragments", "sessions"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

        now = datetime.now()
        earliest = now - timedelta(minutes=max(s["minutes_ago"] for s in SCENES) + 5)
        session_cursor = conn.execute(
            "INSERT INTO sessions (started_at, ended_at, notes) VALUES (?, ?, ?)",
            (_iso(earliest), None, "seeded demo session"),
        )
        session_id = session_cursor.lastrowid
        conn.commit()

        for scene in SCENES:
            last_seen = now - timedelta(minutes=scene["minutes_ago"])
            first_seen = last_seen - timedelta(minutes=scene["duration_min"])

            messages = [{"sender": s, "text": t} for s, t in scene["messages"]]

            png_path = SCREENSHOT_DIR / f"{scene['tag']}.png"
            screenshots = [{
                "path": str(png_path),
                "timestamp": _iso(last_seen),
            }] if png_path.exists() else []

            conn.execute(
                """
                INSERT INTO conversations
                    (platform, participants_json, first_seen, last_seen,
                     messages_json, status_json, status_reasoning, screenshots_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scene["platform"],
                    json.dumps(scene["participants"]),
                    _iso(first_seen),
                    _iso(last_seen),
                    json.dumps(messages),
                    json.dumps(scene["status"]),
                    scene["status"].get("reasoning", ""),
                    json.dumps(screenshots),
                ),
            )
            print(f"  seeded {scene['tag']}  ({scene['status']['threat_level']}, "
                  f"{scene['minutes_ago']}m ago)")

        conn.commit()
    finally:
        conn.close()

    print(f"\n{len(SCENES)} conversations seeded into {db_path} (session id={session_id})")
    print("Start the app WITHOUT --watch-folder to browse the seeded session:")
    print("  python run.py")


if __name__ == "__main__":
    seed()
