"""End-to-end smoke test against a real Ollama server.

Generates a synthetic 'fake Minecraft chat' PNG with Pillow, sends it to the
analyzer, prints the parsed result, and persists it to a temporary SQLite
database. This is what to run on a fresh checkout to verify the full
pipeline works end-to-end without needing a display server (mss screen
capture won't work over SSH).

Usage::

    .venv/bin/python scripts/smoke_test.py \\
        --host http://192.168.1.55:11434 --model gemma4
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from guardlens.analyzer import GuardLensAnalyzer
from guardlens.config import OllamaConfig
from guardlens.database import GuardLensDatabase
from guardlens.demo import render_demo_chat
from guardlens.utils import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://192.168.1.55:11434")
    parser.add_argument("--model", default="gemma4")
    parser.add_argument(
        "--scenario",
        choices=("safe", "grooming", "bullying"),
        default="grooming",
    )
    args = parser.parse_args()

    configure_logging("INFO")

    config = OllamaConfig(host=args.host, inference_model=args.model)
    analyzer = GuardLensAnalyzer(config)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        screenshot_path = render_demo_chat(tmp_path / "chat.png", scenario=args.scenario)
        print(f"Rendered synthetic screenshot: {screenshot_path} (scenario={args.scenario})")
        print(f"Calling Ollama at {args.host} with model={args.model} ...")

        result = analyzer.analyze(screenshot_path)

        print()
        print("=" * 60)
        print(f"THREAT LEVEL : {result.classification.threat_level.value}")
        print(f"CATEGORY     : {result.classification.category.value}")
        print(f"CONFIDENCE   : {result.classification.confidence:.0f}%")
        print(f"PLATFORM     : {result.platform or 'Unknown'}")
        print(f"INFERENCE    : {result.inference_seconds:.2f}s")
        print("=" * 60)
        print()
        print("REASONING:")
        print(result.classification.reasoning)
        print()
        if result.classification.indicators_found:
            print("INDICATORS:")
            for ind in result.classification.indicators_found:
                print(f"  - {ind}")
            print()
        if result.grooming_stage:
            print("GROOMING STAGE:")
            print(f"  stage      : {result.grooming_stage.stage.value}")
            print(f"  escalating : {result.grooming_stage.risk_escalation}")
            for ev in result.grooming_stage.evidence:
                print(f"  evidence   : {ev}")
            print()
        if result.parent_alert:
            print("PARENT ALERT:")
            print(f"  title      : {result.parent_alert.alert_title}")
            print(f"  summary    : {result.parent_alert.summary}")
            print(f"  action     : {result.parent_alert.recommended_action}")
            print(f"  urgency    : {result.parent_alert.urgency.value}")
            print()

        # Exercise the database persistence path too.
        db_path = tmp_path / "smoke.db"
        db = GuardLensDatabase(db_path)
        db.start_session(notes="smoke test")
        analysis_id = db.record_analysis(result)
        if result.parent_alert is not None:
            db.record_alert(analysis_id, result, delivered=False)
        print("DATABASE:")
        print(f"  rows in analyses : {len(db.recent_analyses())}")
        print(f"  rows in alerts   : {len(db.recent_alerts())}")
        print(f"  session summary  : {db.session_summary()}")
        db.end_session()
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
