"""Batch-evaluate every generated scenario frame against the live analyzer.

Feeds each PNG under ``outputs/video_feeds/<scenario>/`` through
:class:`guardlens.analyzer.GuardLensAnalyzer` one frame at a time and
collects the full :class:`ScreenAnalysis` for each. Writes three outputs:

- **Console summary** — live per-frame verdict as it runs, plus a
  per-scenario totals table at the end.
- **HTML report** at ``outputs/eval/report.html`` — scenario-grouped,
  thumbnail next to the model's verdict, reasoning, indicators and parent
  alert. This is the primary debugging view.
- **JSON report** at ``outputs/eval/report.json`` — the same data in a
  machine-readable format so you can diff two runs after changing the
  prompt, scenario text, or model version.

Usage::

    .venv/bin/python scripts/eval_scenarios.py
    .venv/bin/python scripts/eval_scenarios.py --scenarios discord_grooming discord_safe
    .venv/bin/python scripts/eval_scenarios.py --host http://192.168.1.55:11434 --model gemma4

Does **not** write to the production SQLite database. Session tracking is
intentionally not applied — each frame is analysed in isolation so you see
exactly what the vision model sees without cross-frame state muddying the
picture.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from guardlens.analyzer import GuardLensAnalyzer
from guardlens.config import OllamaConfig
from guardlens.schema import ScreenAnalysis, ThreatLevel
from guardlens.utils import configure_logging


# ---------------------------------------------------------------------------
# Expectations per scenario (used for pass/fail flagging in the summary).
# ---------------------------------------------------------------------------

# Map scenario stem -> (expected category, min alerts that should fire)
EXPECTATIONS: dict[str, tuple[str, int]] = {
    "discord_safe": ("none", 0),
    "discord_grooming": ("grooming", 1),
    "discord_bullying": ("bullying", 1),
    "discord_scam": ("scam", 1),
}


@dataclass
class FrameResult:
    """One analysis outcome for one frame."""

    scenario: str
    index: int                    # 1-based, matches filename
    path: Path
    analysis: ScreenAnalysis | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0

    def verdict_label(self) -> str:
        if self.error or self.analysis is None:
            return "error"
        return self.analysis.classification.threat_level.value

    def is_alert(self) -> bool:
        if self.analysis is None:
            return False
        return self.analysis.classification.threat_level in (
            ThreatLevel.ALERT,
            ThreatLevel.CRITICAL,
        )


@dataclass
class ScenarioResult:
    """All frames for a single scenario."""

    name: str
    frames: list[FrameResult] = field(default_factory=list)

    def alert_count(self) -> int:
        return sum(1 for f in self.frames if f.is_alert())

    def max_level(self) -> str:
        order = ("safe", "caution", "warning", "alert", "critical")
        levels = [f.verdict_label() for f in self.frames if f.verdict_label() in order]
        if not levels:
            return "error"
        return max(levels, key=lambda lv: order.index(lv))

    def dominant_category(self) -> str:
        counts: dict[str, int] = {}
        for f in self.frames:
            if f.analysis is None:
                continue
            c = f.analysis.classification.category.value
            counts[c] = counts.get(c, 0) + 1
        if not counts:
            return "none"
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def expectation(self) -> tuple[str, int] | None:
        return EXPECTATIONS.get(self.name)

    def passes_expectation(self) -> bool:
        exp = self.expectation()
        if exp is None:
            return True
        expected_category, min_alerts = exp
        if min_alerts == 0:
            return self.alert_count() == 0
        return (
            self.alert_count() >= min_alerts
            and self.dominant_category() == expected_category
        )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_scenarios(root: Path, subset: list[str] | None = None) -> list[ScenarioResult]:
    """Scan ``root`` for scenario directories with numbered frame_*.png files."""
    scenarios: list[ScenarioResult] = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        if subset and sub.name not in subset:
            continue
        frames = sorted(sub.glob("frame_*.png"))
        if not frames:
            continue
        sr = ScenarioResult(name=sub.name)
        for i, p in enumerate(frames, start=1):
            sr.frames.append(FrameResult(scenario=sub.name, index=i, path=p))
        scenarios.append(sr)
    return scenarios


# ---------------------------------------------------------------------------
# Analysis loop
# ---------------------------------------------------------------------------


def analyse_scenarios(
    scenarios: list[ScenarioResult],
    analyzer: GuardLensAnalyzer,
) -> None:
    """Run the analyzer over every frame and mutate results in place."""
    total = sum(len(s.frames) for s in scenarios)
    done = 0
    print(f"\n[eval] analysing {total} frames across {len(scenarios)} scenarios")
    print(f"[eval] model={analyzer.config.inference_model} host={analyzer.config.host}\n")

    for scenario in scenarios:
        print(f"=== {scenario.name} ===")
        for frame in scenario.frames:
            done += 1
            start = time.perf_counter()
            try:
                frame.analysis = analyzer.analyze(frame.path)
                frame.elapsed_seconds = time.perf_counter() - start
            except Exception as exc:  # noqa: BLE001 — we want to keep going
                frame.error = f"{type(exc).__name__}: {exc}"
                frame.elapsed_seconds = time.perf_counter() - start
                print(
                    f"  [{done:02d}/{total}] frame_{frame.index:04d}  ERROR  "
                    f"{frame.error}"
                )
                continue
            _print_frame_summary(done, total, frame)
        _print_scenario_summary(scenario)
        print()


def _print_frame_summary(done: int, total: int, frame: FrameResult) -> None:
    a = frame.analysis
    if a is None:
        return
    verdict = a.classification.threat_level.value
    category = a.classification.category.value
    conf = int(a.classification.confidence)
    platform = a.platform or "?"
    # Truncate reasoning to ~70 chars for one-line preview
    reasoning = (a.classification.reasoning or "").replace("\n", " ")
    if len(reasoning) > 70:
        reasoning = reasoning[:67] + "..."
    color = _ansi_color(verdict)
    reset = "\033[0m"
    print(
        f"  [{done:02d}/{total}] frame_{frame.index:04d}  "
        f"{color}{verdict:8s}{reset} {category:10s} {conf:3d}%  "
        f"{frame.elapsed_seconds:5.1f}s  {platform:10s}  {reasoning}"
    )


def _print_scenario_summary(scenario: ScenarioResult) -> None:
    exp = scenario.expectation()
    max_lv = scenario.max_level()
    alerts = scenario.alert_count()
    cat = scenario.dominant_category()
    ok = scenario.passes_expectation()
    mark = "\033[92mPASS\033[0m" if ok else "\033[91mFAIL\033[0m"
    exp_str = "—"
    if exp:
        expected_category, min_alerts = exp
        if min_alerts == 0:
            exp_str = f"expect 0 alerts, category=none"
        else:
            exp_str = f"expect >={min_alerts} alerts, category={expected_category}"
    print(
        f"  summary: {len(scenario.frames)} frames, {alerts} alerts, "
        f"max={max_lv}, category={cat}  [{mark}]  ({exp_str})"
    )


def _ansi_color(verdict: str) -> str:
    return {
        "safe": "\033[92m",
        "caution": "\033[93m",
        "warning": "\033[33m",
        "alert": "\033[91m",
        "critical": "\033[95m",
        "error": "\033[90m",
    }.get(verdict, "")


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------


def _analysis_to_dict(result: FrameResult) -> dict[str, Any]:
    a = result.analysis
    out: dict[str, Any] = {
        "scenario": result.scenario,
        "frame_index": result.index,
        "frame_path": str(result.path),
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "error": result.error,
    }
    if a is None:
        return out
    c = a.classification
    out.update(
        {
            "threat_level": c.threat_level.value,
            "category": c.category.value,
            "confidence": c.confidence,
            "platform": a.platform,
            "reasoning": c.reasoning,
            "indicators": list(c.indicators_found),
            "platform_detected": c.platform_detected,
            "raw_thinking": a.raw_thinking,
        }
    )
    if a.grooming_stage is not None:
        out["grooming_stage"] = {
            "stage": a.grooming_stage.stage.value,
            "evidence": list(a.grooming_stage.evidence),
            "risk_escalation": a.grooming_stage.risk_escalation,
        }
    if a.parent_alert is not None:
        out["parent_alert"] = {
            "urgency": a.parent_alert.urgency.value,
            "alert_title": a.parent_alert.alert_title,
            "summary": a.parent_alert.summary,
            "recommended_action": a.parent_alert.recommended_action,
        }
    return out


def write_json_report(scenarios: list[ScenarioResult], path: Path) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scenarios": [
            {
                "name": s.name,
                "frame_count": len(s.frames),
                "alert_count": s.alert_count(),
                "max_level": s.max_level(),
                "dominant_category": s.dominant_category(),
                "passes_expectation": s.passes_expectation(),
                "frames": [_analysis_to_dict(f) for f in s.frames],
            }
            for s in scenarios
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    print(f"[eval] wrote JSON report -> {path}")


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


HTML_STYLE = """
:root {
  --bg: #0b0d13;
  --panel: #161a26;
  --panel-2: #1f2332;
  --text: #dbdee1;
  --muted: #949ba4;
  --border: #2a2e3d;
  --safe: #23a55a;
  --caution: #f0b232;
  --warning: #ff9840;
  --alert: #f23f43;
  --critical: #c9208d;
  --error: #7a7f8a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, system-ui, sans-serif;
  background: radial-gradient(circle at 50% -30%, #161a26, #0b0d13);
  color: var(--text);
  padding: 40px 60px;
}
h1 { font-weight: 500; font-size: 28px; margin: 0 0 4px; }
.meta { color: var(--muted); font-size: 13px; margin-bottom: 30px; }
.summary {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 36px;
}
.summary table { width: 100%; border-collapse: collapse; }
.summary th, .summary td {
  text-align: left;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
}
.summary th {
  color: var(--muted);
  font-weight: 500;
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 1.5px;
}
.summary tr:last-child td { border-bottom: none; }
.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.badge.safe     { background: rgba(35,165,90,0.18);  color: var(--safe); }
.badge.caution  { background: rgba(240,178,50,0.18); color: var(--caution); }
.badge.warning  { background: rgba(255,152,64,0.18); color: var(--warning); }
.badge.alert    { background: rgba(242,63,67,0.20);  color: var(--alert); }
.badge.critical { background: rgba(201,32,141,0.22); color: var(--critical); }
.badge.error    { background: rgba(122,127,138,0.22); color: var(--error); }
.badge.pass     { background: rgba(35,165,90,0.18);  color: var(--safe); }
.badge.fail     { background: rgba(242,63,67,0.20);  color: var(--alert); }

.scenario {
  margin-bottom: 48px;
}
.scenario h2 {
  font-size: 18px;
  font-weight: 500;
  margin: 0 0 4px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.scenario .topic {
  color: var(--muted);
  font-size: 13px;
  margin-bottom: 18px;
}
.frame {
  display: grid;
  grid-template-columns: 420px 1fr;
  gap: 24px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px;
  margin-bottom: 16px;
}
.frame img {
  width: 100%;
  border-radius: 6px;
  border: 1px solid var(--border);
}
.analysis { min-width: 0; }
.analysis .head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}
.analysis .head .frame-id { font-family: 'JetBrains Mono', monospace; color: var(--text); }
.analysis .head .elapsed { margin-left: auto; font-family: 'JetBrains Mono', monospace; }
.analysis h3 { margin: 0 0 6px; font-size: 17px; font-weight: 500; }
.analysis .category {
  font-size: 13px;
  color: var(--muted);
  margin-bottom: 14px;
  font-family: 'JetBrains Mono', monospace;
}
.analysis p.reasoning {
  line-height: 1.55;
  font-size: 14px;
  margin: 10px 0;
}
.indicators { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.indicators span {
  background: var(--panel-2);
  border: 1px solid var(--border);
  padding: 3px 9px;
  border-radius: 12px;
  font-size: 12px;
  color: var(--muted);
}
.parent-alert {
  margin-top: 12px;
  padding: 12px 14px;
  background: rgba(242,63,67,0.08);
  border-left: 3px solid var(--alert);
  border-radius: 4px;
}
.parent-alert .urgency {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--alert);
  font-weight: 600;
}
.parent-alert .title { font-weight: 500; margin: 4px 0; }
.parent-alert .summary { color: var(--muted); font-size: 13px; }
.error-block {
  background: rgba(242,63,67,0.08);
  border-left: 3px solid var(--alert);
  padding: 12px 14px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  border-radius: 4px;
}
"""


def _h(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _rel_path(frame_path: Path, report_path: Path) -> str:
    try:
        return str(frame_path.resolve().relative_to(report_path.parent.resolve()))
    except ValueError:
        # Different trees — fall back to file:// URI
        return frame_path.resolve().as_uri()


def _render_frame_html(frame: FrameResult, report_path: Path) -> str:
    rel = _rel_path(frame.path, report_path)
    if frame.error or frame.analysis is None:
        return f"""
        <div class="frame">
          <img src="{_h(rel)}" alt="frame {frame.index}" />
          <div class="analysis">
            <div class="head">
              <span class="frame-id">frame_{frame.index:04d}</span>
              <span class="badge error">ERROR</span>
              <span class="elapsed">{frame.elapsed_seconds:.1f}s</span>
            </div>
            <div class="error-block">{_h(frame.error or "no analysis")}</div>
          </div>
        </div>
        """
    a = frame.analysis
    c = a.classification
    level = c.threat_level.value
    indicators_html = "".join(
        f"<span>{_h(ind)}</span>" for ind in (c.indicators_found or [])
    )
    parent_html = ""
    if a.parent_alert is not None:
        pa = a.parent_alert
        parent_html = f"""
            <div class="parent-alert">
              <div class="urgency">{_h(pa.urgency.value)} urgency</div>
              <div class="title">{_h(pa.alert_title)}</div>
              <div class="summary">{_h(pa.summary)}</div>
              <div class="summary" style="margin-top:6px"><em>→ {_h(pa.recommended_action)}</em></div>
            </div>
        """
    stage_html = ""
    if a.grooming_stage is not None:
        gs = a.grooming_stage
        escalating = " — escalating" if gs.risk_escalation else ""
        stage_html = (
            f"<div class=\"category\">grooming stage: "
            f"{_h(gs.stage.value)}{escalating}</div>"
        )
    return f"""
    <div class="frame">
      <img src="{_h(rel)}" alt="frame {frame.index}" />
      <div class="analysis">
        <div class="head">
          <span class="frame-id">frame_{frame.index:04d}</span>
          <span class="badge {level}">{_h(level)}</span>
          <span class="elapsed">{frame.elapsed_seconds:.1f}s</span>
        </div>
        <h3>{_h(c.category.value)} — {int(c.confidence)}% confidence</h3>
        <div class="category">platform: {_h(a.platform or "?")}</div>
        {stage_html}
        <p class="reasoning">{_h(c.reasoning)}</p>
        <div class="indicators">{indicators_html}</div>
        {parent_html}
      </div>
    </div>
    """


def _render_summary_table(scenarios: list[ScenarioResult]) -> str:
    rows: list[str] = []
    for s in scenarios:
        exp = s.expectation()
        exp_str = "—"
        if exp:
            cat, n = exp
            exp_str = f"{n}+ alerts, {cat}" if n > 0 else "0 alerts"
        ok = "pass" if s.passes_expectation() else "fail"
        rows.append(f"""
          <tr>
            <td><a href="#{_h(s.name)}">{_h(s.name)}</a></td>
            <td>{len(s.frames)}</td>
            <td>{s.alert_count()}</td>
            <td><span class="badge {_h(s.max_level())}">{_h(s.max_level())}</span></td>
            <td>{_h(s.dominant_category())}</td>
            <td>{_h(exp_str)}</td>
            <td><span class="badge {ok}">{ok.upper()}</span></td>
          </tr>
        """)
    return f"""
    <div class="summary">
      <table>
        <thead>
          <tr>
            <th>Scenario</th>
            <th>Frames</th>
            <th>Alerts</th>
            <th>Max level</th>
            <th>Dominant category</th>
            <th>Expectation</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>
    """


def write_html_report(
    scenarios: list[ScenarioResult],
    report_path: Path,
    *,
    model_name: str,
    host: str,
) -> None:
    summary = _render_summary_table(scenarios)
    sections: list[str] = []
    for s in scenarios:
        frames_html = "\n".join(_render_frame_html(f, report_path) for f in s.frames)
        sections.append(f"""
        <section class="scenario" id="{_h(s.name)}">
          <h2>
            {_h(s.name)}
            <span class="badge {_h(s.max_level())}">{_h(s.max_level())}</span>
          </h2>
          <div class="topic">
            {len(s.frames)} frames, {s.alert_count()} alert(s),
            dominant category: {_h(s.dominant_category())}
          </div>
          {frames_html}
        </section>
        """)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>GuardianLens scenario eval — {generated}</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<h1>GuardianLens scenario evaluation</h1>
<div class="meta">
  generated {generated} · model <code>{_h(model_name)}</code> · host <code>{_h(host)}</code>
</div>
{summary}
{"".join(sections)}
</body>
</html>
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(doc)
    print(f"[eval] wrote HTML report -> {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--feeds-root",
        type=Path,
        default=Path("outputs/video_feeds"),
        help="directory containing discord_*/frame_*.png subfolders",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        help="subset of scenario directory names to evaluate (default: all)",
    )
    parser.add_argument(
        "--host",
        default="http://192.168.1.55:11434",
        help="Ollama host URL",
    )
    parser.add_argument("--model", default="gemma4", help="inference model name")
    parser.add_argument(
        "--report-html",
        type=Path,
        default=Path("outputs/eval/report.html"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("outputs/eval/report.json"),
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()

    configure_logging(args.log_level)

    # Self-create the report directory up front so callers that redirect or
    # tee the script output don't fail on "no such file or directory".
    args.report_html.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)

    scenarios = discover_scenarios(args.feeds_root, args.scenarios)
    if not scenarios:
        print(f"[eval] no scenarios found under {args.feeds_root}", file=sys.stderr)
        return 1

    config = OllamaConfig(
        host=args.host,
        inference_model=args.model,
    )
    analyzer = GuardLensAnalyzer(config)

    try:
        analyse_scenarios(scenarios, analyzer)
    except KeyboardInterrupt:
        print("\n[eval] interrupted — writing partial report", file=sys.stderr)

    write_json_report(scenarios, args.report_json)
    write_html_report(
        scenarios,
        args.report_html,
        model_name=args.model,
        host=args.host,
    )

    # Final pass/fail summary line
    passed = sum(1 for s in scenarios if s.passes_expectation())
    total = len(scenarios)
    print(f"\n[eval] {passed}/{total} scenarios met their expectations")
    return 0 if passed == total else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(3)
