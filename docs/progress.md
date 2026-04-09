# Progress Log

> Append-only project changelog. Newest entries at the top.
> Entry format: ISO date header, short summary, then a `Files` block listing
> every file created or modified, then any blockers / next steps.
>
> When you start a session, read the **most recent two entries** before doing
> anything else — they capture the state of the repo and any open threads.

---

## 2026-04-08 — Migrated dashboard from Gradio to FastAPI + vanilla JS

### Summary

Replaced the Gradio dashboard with a FastAPI server + Jinja2 template +
vanilla JS front-end. Reasons (per the user): the Gradio version felt
"too Gradio-ish", and CONTEXT_UI.md anticipated this fork ("if it looks
too Gradio-ish, switch to FastAPI + custom HTML in week 4").

The FastAPI version is **easier to manage** (cleaner separation of
concerns: backend API + JSON serializers + DOM-rendering JS), **looks
more professional** (Inter font, CSS Grid layout, subtle gradient
backgrounds, real CSS shadows, no Gradio chrome to fight), and uses
**Server-Sent Events instead of polling** so the UI updates push down
from the server with no client-side timer loop.

### Architecture

```
app/
├── server.py          # FastAPI app: /, /api/state, /api/stream, /static, /screenshots
├── state.py           # AppState + MonitorWorker; lifespan-managed
├── serializers.py     # ScreenAnalysis -> JSON dict
├── templates/
│   └── index.html     # Jinja2 page with server-rendered initial state
└── static/
    ├── dashboard.css  # Vanilla CSS, no framework overrides
    └── dashboard.js   # SSE client + DOM render functions
```

**Endpoints**

| Route             | Purpose                                                  |
|-------------------|----------------------------------------------------------|
| `GET /`           | Jinja2 page; baked-in initial state (no flash of empty)  |
| `GET /api/state`  | One-shot JSON snapshot                                   |
| `GET /api/stream` | SSE stream — yields a fresh snapshot every 2 s           |
| `GET /static/*`   | CSS / JS / assets                                        |
| `GET /screenshots/*` | Read-only mount of `outputs/screenshots/`             |
| `GET /healthz`    | `{"status": "ok"}` for monitoring                        |

**SSE not WebSocket.** One direction (server -> client), auto-reconnect
built into the browser's `EventSource`, no connection lifecycle to
manage. Right tool for live-status broadcasting.

**Lifespan-managed worker.** The monitor thread starts inside FastAPI's
`lifespan` context and stops cleanly on shutdown — no global state, no
import-time side effects, easy to test.

### Design system (rewritten dashboard.css)

Same color tokens as before (CONTEXT_UI.md), but the CSS is now ~10
sections of clean, vendor-free rules instead of Gradio overrides:

- **Inter** for body text (Linear / Vercel / Stripe family).
- **JetBrains Mono** for timestamps, metrics, footer.
- **CSS Grid** for the 65/35 main split — proper grid, not flex hacks.
- **Subtle radial gradient background** — `radial-gradient(circle at 50% -30%, #161a26, #0b0d13)` — gives depth without being noisy.
- **Drop shadows** on cards (`0 8px 24px -16px rgba(0,0,0,0.6)`) — soft,
  designer-grade depth.
- **Sticky header** with `backdrop-filter: blur(8px)` so it sits above
  scrolled content like a real product.
- **Hover lifts** on the metric cards (`translateY(-1px)`).
- **The wow alert state** survives the rewrite: when `is_alert` flips
  true, the shell switches to `gl-alert-active` and the radial gradient
  warms to a faint red, header border turns reddish, side panel border
  turns red. CSS transitions over 0.6 s — subliminal but unmistakable.

### Front-end JS

Vanilla, ~250 lines, no build step. One-time initial render from the
JSON blob baked into the template, then an `EventSource` connection to
`/api/stream` that re-renders on every push.

Render functions, one per region:
`renderHeader`, `renderMetrics`, `renderScreenshot`, `renderTimeline`,
`renderThreatCard`, `renderStageBar`, `renderReasoning`,
`renderParentAlert`. Each one is idempotent — re-running with the same
state is a no-op for the DOM.

### Files

**Created**

- `app/server.py` — FastAPI app + lifespan + SSE endpoint.
- `app/state.py` — `AppState` + `MonitorWorker` (worker code lifted
  from the old Gradio dashboard, no semantic changes).
- `app/serializers.py` — JSON serializers replacing the old HTML
  render helpers.
- `app/templates/index.html` — single-page Jinja2 template.
- `app/static/dashboard.css` — fully rewritten (no Gradio overrides).
- `app/static/dashboard.js` — vanilla SSE client + DOM render
  functions.
- `tests/test_serializers.py` — 8 tests for the JSON serializers.
- `tests/test_server.py` — 5 tests using FastAPI's `TestClient`
  (patches `ollama.Client` so no real Ollama call happens).

**Modified**

- `pyproject.toml` — removed `gradio>=4.44.0`, added
  `fastapi>=0.115.0`, `uvicorn[standard]>=0.30.0`, `jinja2>=3.1.0`.
  Dev extras gained `httpx>=0.27.0` for `TestClient`.
- `requirements.txt` — same swap.
- `run.py` — replaces `app.dashboard.build_app` + Gradio `launch()`
  with `app.server.create_app` + `uvicorn.run()`. New CLI flags:
  `--ollama-host` (override Ollama base URL), `--bind` (override
  FastAPI bind address). `--share` flag removed (Gradio-only).

**Deleted**

- `app/dashboard.py` — Gradio Blocks app, no longer needed.
- `app/theme.py` — Gradio theme + CSS bundle loader.
- `app/components.py` — server-side HTML render helpers.
- `tests/test_components.py` — replaced by `test_serializers.py`.

**Dependency churn (uv)**

Uninstalled: `gradio`, `gradio-client`, `safehttpx`, `semantic-version`,
`ffmpy`. Reinstalled `starlette` (needed by FastAPI). Net: smaller
install footprint.

### Verified locally

- `py_compile` clean across all changed files.
- **20/20 tests pass** (was 17 before — added 8 serializer tests + 5
  server tests, removed 10 Gradio component tests).
- `from app.server import create_app` constructs a FastAPI instance
  with all 7 routes mounted (`/openapi.json`, `/static`, `/screenshots`,
  `/`, `/api/state`, `/api/stream`, `/healthz`) and an `AppState`
  attached at `app.state.guardlens`.
- **Dashboard NOT launched.** Per the user's earlier "stop that don't
  run it" instruction. To launch:
  `.venv/bin/python run.py --demo-mode --model gemma4`
  then open `http://192.168.1.55:7860/` from the laptop.

### How to view it

```bash
.venv/bin/python run.py --demo-mode --model gemma4
```

Then on the laptop browser: `http://192.168.1.55:7860/`. The page
should:

1. Render immediately (server-rendered initial state, no flash).
2. Open an `EventSource` to `/api/stream`.
3. Update every ~2 s as the monitor thread drains new analyses.
4. Switch to the `gl-alert-active` atmosphere when an ALERT or
   CRITICAL verdict lands.

### Open / next

- Click through the new UI in a browser. CSS Grid + sticky header +
  Inter font + radial gradient should all be visible.
- **Streaming Gemma 4 thinking tokens** — biggest "wow" moment still
  available. Easier to do over SSE than it was over Gradio. Add a
  `/api/stream-thinking` endpoint that emits chunked tokens during a
  single analysis.
- **Real screenshots** in `data/demo_scenarios/` — capture from real
  Minecraft / Discord on the laptop.
- **Phone-side parent notification** — email-to-phone for the demo
  video (Option A in CONTEXT_UI.md).

---

## 2026-04-08 — UI redesign: CONTEXT_UI.md design system, full custom CSS

### Summary

Saved the user-provided **CONTEXT_UI.md** as a second source of truth and
rebuilt the dashboard end-to-end against it. The previous Gradio default
look ("2018 ML demo aesthetic") is gone — the dashboard now uses a dark
security-tool theme with status-driven color, monospace data, micro-
animations, and a wow-state alert atmosphere.

CONTEXT.md now points at CONTEXT_UI.md in the header so future sessions
read it before any UI work.

### Architecture

The dashboard is split into three layers:

- **`app/static/dashboard.css`** — the entire design system. ~14k chars,
  edited as a real CSS file. Contains: CSS custom properties (color +
  typography + spacing tokens), Gradio overrides, layout, every
  component class, status dots, animations, and the `.gl-alert-active`
  wow state. CONTEXT_UI.md is the spec; this file is the implementation.
- **`app/theme.py`** — exports `DASHBOARD_CSS` (loaded from the file
  above) and `GUARDLENS_THEME` (a `gr.themes.Base` subclass with the
  same color tokens applied to Gradio's own form elements so they don't
  visually clash with our HTML components).
- **`app/components.py`** — pure HTML render helpers, no Gradio imports,
  unit-testable. One function per component:
  - `render_header(monitoring, session_duration, model_name, alert_active)`
  - `render_metric_cards(summary)`
  - `render_timeline(analyses)`
  - `render_side_panel(analysis)`
  - `render_footer(model_name, db_path, bytes_to_cloud)`
  - Internal: `_render_threat_card`, `_render_stage_bar`,
    `_render_reasoning`, `_render_alert_preview`
  - Helpers: `is_alert_active`, `format_session_duration`

`app/dashboard.py` is now thin Gradio plumbing only — it builds the
Blocks layout (header, metric cards, screenshot + timeline column,
side-panel column, footer), drives the refresh on a 2 s timer, and
swaps in the `gl-alert-active` shell class when an ALERT or CRITICAL
verdict lands. The MonitorWorker / database / alert wiring is unchanged
from the previous entry.

### Layout (matches CONTEXT_UI.md exactly)

```
+----------------------------------------------------+
| HEADER (48px)  [logo] GuardianLens   o active  14m |
+--------------------------------------+-------------+
| Screenshots Safe  Caution  Alerts    | THREAT      |
| LATEST CAPTURE                       | CARD        |
| [latest screenshot]                  |             |
| LIVE TIMELINE                        | STAGE BAR   |
| 14:32 o safe   Minecraft - ...       |             |
| 14:32 o alert  Minecraft - GROOM...  | REASONING   |
+--------------------------------------+ (mono)      |
| FOOTER  gemma4 via Ollama   bytes:0  | PARENT ALERT|
+--------------------------------------+-------------+
```

### Design system implemented

- **Colors:** all 5 status families (`safe / caution / alert / info / brand`)
  with `*-bg` and `*-border` low-opacity variants. Bright status colors
  only on dots / numbers / borders, never on large fills.
- **Typography:** system sans for body, JetBrains Mono for timestamps and
  data. Section labels uppercase + 1.5px letter-spacing. No bold (700)
  anywhere — `--weight-medium: 500` is the heaviest weight as the spec
  requires.
- **Animations:**
  - `gl-pulse-safe` (gentle opacity pulse on safe/caution dots)
  - `gl-pulse-alert` (expanding ring pulse on alert/critical dots)
  - `gl-slide-in-alert` (alert timeline rows slide in)
  - `gl-analyzing` (loading state, defined for future use)
- **The wow moment:** when `is_alert_active(latest) == True`, the shell
  div gets the `gl-alert-active` class. CSS transitions the background
  to a slightly warmer tone, the header border shifts to faint red, and
  the side panel border-left turns red. Subliminal but noticeable.
- **Privacy receipt** in the footer — "bytes sent to cloud: 0" + the
  local DB path. Hammers the on-device story for any judge who looks at
  the screenshot.

### Files

**Created**

- `CONTEXT_UI.md` — UI/UX design spec (verbatim from user).
- `app/static/dashboard.css` — full design system, ~14 KB.
- `app/theme.py` — Gradio theme + CSS bundle loader.
- `app/components.py` — HTML render helpers, no Gradio dependency.
- `tests/test_components.py` — 10 sanity tests covering every component
  + helper. Tests assert class names appear in the output so a CSS
  rename can't silently break the dashboard.

**Modified**

- `app/dashboard.py` — fully rewritten. Old `_render_*` helpers removed
  (moved to `components.py`). Layout matches CONTEXT_UI.md exactly.
  Refresh function now returns 7 outputs (header / metrics / timeline /
  screenshot / side / footer / hidden last-refresh label) so each
  region can update independently.
- `CONTEXT.md` — added a paragraph in the header pointing at
  CONTEXT_UI.md for any UI work.

### Verified locally

- `py_compile` clean across all changed files.
- `from app.theme import DASHBOARD_CSS, GUARDLENS_THEME` works
  (CSS loaded: 14356 chars, theme: `Base`).
- All 17 unit tests pass — 7 existing + 10 new component tests.
- Component smoke test: rendered every helper against synthetic
  `ScreenAnalysis` objects (safe, warning, alert) and confirmed every
  expected CSS class name appears in the output.
- **I have NOT launched the dashboard.** Per the user's earlier
  "stop that dont run it" instruction, I'm leaving live verification
  to the user. To launch:
  `.venv/bin/python run.py --demo-mode --model gemma4`
  then open `http://192.168.1.55:7860/` from the laptop.

### Open / next

- **Click through the new UI in a browser.** Confirm the layout doesn't
  collapse, the colors render correctly, and the wow alert state
  actually triggers visibly when a grooming scenario lands.
- **Confidence count-up animation** is described in CONTEXT_UI.md but
  not implemented yet (it requires a small inline JS snippet, not just
  CSS). Add when polishing for the demo recording.
- **Stream Gemma 4's thinking tokens** to the reasoning panel in real
  time — this is the highest-leverage technical change for the Safety &
  Trust track. Currently the reasoning text appears all at once.
- **Real screenshots in `data/demo_scenarios/`** — capture from real
  Minecraft / Discord on the laptop. The synthetic Pillow chats from
  `guardlens.demo` will look fake on a recorded video.
- **Phone-side parent notification rendering** for the demo video —
  CONTEXT_UI.md recommends Option A (real email to your phone),
  scaffolded in `guardlens.alerts` but disabled by default.

---

## 2026-04-08 — Demo mode: Gradio dashboard runs headless, end-to-end verified

### Summary

The dashboard now launches and runs cleanly on this headless server. Two
problems blocked it before:

1. **`mss` needs `DISPLAY`.** SSH sessions don't have one, so the monitor
   loop crashed on the first capture.
2. **No way to inject realistic chats** for the dashboard to analyze
   without a live display.

Both solved by adding a `--demo-mode` flag. In demo mode the monitor loop
swaps `mss` for synthetic Pillow chat screenshots that cycle through
SAFE -> GROOMING -> SAFE -> BULLYING. The rest of the pipeline (analyzer
-> Ollama -> Pydantic parsing -> SQLite -> Gradio UI) is identical to
real mode, so the demo recording will be 100% representative of how the
dashboard behaves on a real desktop.

The chat-rendering code that used to live inline in `scripts/smoke_test.py`
moved to `src/guardlens/demo.py` so both the smoke test and the monitor
loop share one source of truth.

### Live verification

Launched the dashboard with:

```bash
.venv/bin/python run.py --demo-mode --model gemma4
```

Two minutes later, with no manual interaction:

| Metric                  | Value                                   |
|-------------------------|-----------------------------------------|
| Gradio bound to         | `0.0.0.0:7860` (HTTP 200 from LAN IP)   |
| Analyses persisted      | 35                                      |
| Alerts persisted        | 17                                      |
| Session totals          | safe: 18, warning: 14, alert: 3         |
| Errors / exceptions     | 0                                       |
| Avg inference per call  | ~13 s on `gemma4` 8B (within 8 s interval — Ollama queues) |

Sample of recent rows from `outputs/guardlens.db`:

```
35: safe     none      98%  Minecraft Chat
34: warning  grooming  98%  Minecraft
33: safe     none     100%  Minecraft
32: warning  bullying  98%  Minecraft
```

Sample alerts:

```
[immediate] High Risk: Potential Grooming Attempt Detected
[high     ] Potential Grooming Attempt Detected
[medium   ] Cyberbullying Detected in Minecraft
```

Every grooming scenario triggered a `high` or `immediate` urgency alert.
Every bullying scenario triggered a `medium` or `high` urgency alert.
Every safe scenario stayed at `safe / none` with no alert (no false
positives across 18 safe runs).

### How to view the dashboard from a different machine

The Gradio server binds to `0.0.0.0:7860` on this host. From the laptop:

- **Direct LAN URL** — open `http://192.168.1.55:7860/` in a browser.
- **SSH tunnel** (if the LAN URL is firewalled) — from the laptop:
  `ssh -L 7860:localhost:7860 <user>@192.168.1.55`, then open
  `http://localhost:7860/` locally.
- **Public Gradio share link** — pass `--share` to `run.py`. Gradio will
  print a `https://*.gradio.live` URL good for ~72 hours. Use this for
  remote demo previews.

To stop the dashboard, send SIGINT (Ctrl-C) to the foreground process or
`kill <pid>` if it was started in the background.

### Files

**Created**

- `src/guardlens/demo.py` — `render_demo_chat(path, scenario)` plus the
  `DEMO_SCENARIOS` rotation. Three scenarios: `safe`, `grooming`,
  `bullying`. Pillow-rendered, no display required.

**Modified**

- `src/guardlens/config.py` — added `MonitorConfig.demo_mode: bool = False`.
- `src/guardlens/monitor.py` — `capture_loop` branches on `demo_mode`;
  added `_demo_capture_loop` that cycles through `DEMO_SCENARIOS`.
- `run.py` — added `--demo-mode` CLI flag. When set, defaults the
  capture interval to 8 s (so the UI feels live) unless `--interval` is
  also passed.
- `scripts/smoke_test.py` — refactored to import `render_demo_chat`
  from `guardlens.demo`. Added `bullying` to the scenario choices.

### Open / next

- The page renders and the demo loop is firing, but I haven't actually
  *clicked through* the UI from a browser — the user should open
  `http://192.168.1.55:7860/` and confirm the status badge / timeline /
  thinking-chain panels look right.
- Inference latency on the 8B model averaged ~13 s per call, slower than
  the 8 s capture interval. Ollama queues the requests so the UI keeps
  up, but for the demo recording either bump `--interval` to 15 s or
  pull `gemma4:26b` (which has the same TPS but renders the demo more
  impressively).
- Real `mss` capture path is still untested. It will only run on a
  desktop session. Test it from the laptop before demo recording.

---

## 2026-04-08 — WEEK 1 GO/NO-GO GATE: PASSED. End-to-end pipeline verified live.

### Summary

The Week 1 critical question from CONTEXT.md — *"Can Gemma 4 read chat text
from a game screenshot?"* — has been answered **YES** against the live
Ollama at `http://192.168.1.55:11434` (model `gemma4:latest`, 8B Q4_K_M).
The full pipeline works end-to-end: vision OCR -> structured tool calls
-> Pydantic parsing -> SQLite persistence.

Project venv was created with `uv venv` (Python 3.11.15). All deps
installed via `uv pip install -e ".[dev]"`. All 7 unit tests pass.

A new permanent smoke test asset (`scripts/smoke_test.py`) renders a
synthetic Pillow PNG of a fake Minecraft chat (two scenarios: `safe` and
`grooming`), sends it to Ollama, prints the parsed `ScreenAnalysis`, and
exercises the SQLite persistence path. Use it to re-validate the
pipeline on any fresh checkout.

### Environment

| Item            | Value                                              |
|-----------------|----------------------------------------------------|
| Ollama host     | `http://192.168.1.55:11434` (Docker, `--net=host`) |
| Available model | `gemma4:latest` (8B params, Q4_K_M, 9.6 GB)        |
| Python          | 3.11.15 (uv-managed venv at `.venv/`)              |
| Display         | None — server is headless, `mss` capture won't work over SSH |

> **Note:** The 26B variant (`gemma4:26b`) referenced in CONTEXT.md as the
> demo-quality model is not yet pulled on this server. The 8B model is
> already producing the right verdicts and is fast enough for the demo
> (4-11 s per analysis). Pull 26B before final demo recording.

### Live test results

**Grooming scenario** (synthetic chat with: age question + Discord
proposal + free skins + "don't tell your parents"):

```
THREAT LEVEL : warning
CATEGORY     : grooming
CONFIDENCE   : 98%
PLATFORM     : Minecraft
INFERENCE    : 11.27s
INDICATORS   : Asking about age (Stage 1), Excessive compliments (Stage 2),
               Request to move conversation off-platform (Discord) (Stage 3),
               Request for secrecy (Stage 3)
GROOMING STG : isolation, escalating=True
PARENT ALERT : "High Risk: Potential Grooming Attempt Detected" (urgency=high)
DATABASE     : 1 analysis row, 1 alert row persisted
```

**Safe scenario** (normal Minecraft trading + raid planning):

```
THREAT LEVEL : safe
CATEGORY     : none
CONFIDENCE   : 98%
PLATFORM     : Minecraft
INFERENCE    : 4.80s
INDICATORS   : In-game resource trading discussion, Planning collaborative gameplay
GROOMING STG : (not called — correct)
PARENT ALERT : (not called — correct, false positive avoided)
DATABASE     : 1 analysis row, 0 alert rows persisted
```

What this proves:

1. **Vision OCR works.** Gemma 4 8B reads every chat line off the
   Pillow-rendered PNG with no extra prompting tricks.
2. **All three function calls work end-to-end.** `classify_threat`,
   `identify_grooming_stage`, and `generate_parent_alert` all fire when
   appropriate, parse cleanly into the Pydantic models, and round-trip
   through SQLite.
3. **Reasoning quality is high enough for the demo.** The model cites
   specific quoted text and maps each indicator to its grooming stage.
4. **False positives controlled.** The safe scenario returned `safe / 98%`
   with zero alert tools called.
5. **Privacy story holds.** `parent_alert.summary` describes the concern
   without quoting raw chat content (it summarizes "moved conversation to
   Discord and pressured the child to keep it secret" rather than copying
   the messages).
6. **Latency is fine.** 4-11 s on the 8B is well under the 15 s capture
   interval, so the dashboard will keep up in real time.

### Files

**Created**

- `scripts/smoke_test.py` — permanent end-to-end smoke test. Renders a
  synthetic Pillow PNG of a fake Minecraft chat (`--scenario safe` or
  `grooming`), sends it to Ollama, prints the parsed `ScreenAnalysis`,
  and exercises the SQLite persistence path. Run with:
  `.venv/bin/python scripts/smoke_test.py --host http://192.168.1.55:11434 --model gemma4 --scenario grooming`

**Generated (gitignored)**

- `.venv/` — uv-managed Python 3.11.15 venv with all project deps.

### Open / next

- **Pull `gemma4:26b`** on the Ollama host for demo-quality reasoning
  before recording the video. The 8B is already good enough for testing
  but the 26B will look better in the demo.
- **Headless caveat.** `app/dashboard.py` cannot launch on this server
  because `mss` requires a display server. Two paths forward:
  - Run the dashboard from a machine with a desktop (laptop), pointed at
    the same Ollama via `--host`.
  - Build a "screenshot ingestion" alt-input mode where the monitor
    watches a folder for new images instead of capturing the screen
    directly. This would also allow demo recording from pre-captured
    footage.
- **Real screenshots** — replace the synthetic Pillow chat with an
  actual Minecraft / Discord screenshot to confirm the model handles
  small-text rendering and busy backgrounds. Capture on the laptop and
  copy over.
- **The ollama-instruction file in the repo root** documents the actual
  Docker run command. We should leave it as-is and not add Docker
  config files yet (per CONTEXT.md).

---

## 2026-04-08 — v3 spec alignment: SQLite persistence, run.py, platform_detected

### Summary

CONTEXT.md was upgraded to **v3 FINAL**. The v3 spec raised the bar from
"compelling demo" to "real working system judges can audit." Three concrete
gaps vs v1/v2 were closed:

1. **Function calling now actually executes.** Every `classify_threat` and
   `generate_parent_alert` tool call is persisted to a real on-disk SQLite
   row via the new `GuardLensDatabase`. The dashboard worker writes on
   every drained analysis, so the database doubles as the audit trail.
2. **Single-command startup.** `python run.py` (project root) launches the
   monitor loop + Gradio dashboard with one command, with CLI flags for
   model / interval / port / share / fine-tuned variant.
3. **Model-reported platform.** `classify_threat` now exposes
   `platform_detected`; the analyzer prefers it over the heuristic.

System prompt (`prompts.py`) was rewritten to match v3's 5-stage grooming
taxonomy and the "MINIMIZE false positives" rule. Bumped to
`PROMPT_VERSION = "2026-04-08.v3"`.

`src/guardlens/__init__.py` was emptied of eager re-exports. Reason: the
old `from guardlens import GuardLensAnalyzer` shortcut forced every
consumer (including the Kaggle eval notebooks) to install
`pydantic-settings`. Use `from guardlens.<submodule> import ...` directly.

### Files

**Created**

- `CONTEXT.md` — overwritten with v3 FINAL (real-application requirements,
  SQLite persistence, run.py entry point, updated grooming stages, weekly
  plan).
- `src/guardlens/database.py` — `GuardLensDatabase` SQLite store.
  Three tables: `sessions`, `analyses`, `alerts`. Thread-safe single-lock
  autocommit. API: `start_session`, `end_session`, `record_analysis`,
  `record_alert`, `recent_analyses`, `recent_alerts`, `session_summary`,
  `close`.
- `run.py` (project root) — single CLI entry point. Adds `src/` to
  `sys.path`, parses CLI flags, applies overrides, hands off to
  `app.dashboard.build_app`.
- `tests/test_database.py` — round-trips a SAFE + ALERT + delivered alert
  through SQLite, verifies `session_summary` returns the expected counts.
- `tests/test_pipeline.py` — patches `analyzer._client.chat` with a
  synthetic Ollama response containing all three tool calls; asserts a
  fully-parsed `ScreenAnalysis`. Also covers `SessionTracker` escalation
  streak + reset.
- `docs/progress.md` — this file.

**Modified**

- `src/guardlens/schema.py` — added
  `ThreatClassification.platform_detected: str | None`.
- `src/guardlens/tools.py` — added `platform_detected` to the
  `classify_threat` JSON schema.
- `src/guardlens/analyzer.py` — prefers
  `classification.platform_detected`, falls back to the regex heuristic.
- `src/guardlens/prompts.py` — system prompt rewritten to v3 (5 grooming
  stages, false-positive guidance). `PROMPT_VERSION = "2026-04-08.v3"`.
- `src/guardlens/config.py` — added `DatabaseConfig` section and the
  `database` field on `GuardLensConfig`.
- `src/guardlens/__init__.py` — emptied of eager re-exports (was forcing
  pydantic-settings on every consumer).
- `app/dashboard.py` — `MonitorWorker` now takes a `GuardLensDatabase`,
  persists every analysis, records alert outcomes (delivered or not),
  shows per-level session counters from the DB.
- `pyproject.toml` — `guardlens` console script repointed from
  `app.dashboard:main` to `run:main`; `run.py` added to wheel includes.
- `configs/default.yaml` — added `database.path: outputs/guardlens.db`.

### Verified locally

- Every `.py` file byte-compiles cleanly (`python -m py_compile ...`).
- `from guardlens.schema import ThreatClassification` works without
  `pydantic-settings` installed (the leaf-import refactor took).
- `GuardLensDatabase` round-trip works against a real temp SQLite file:
  insert analysis -> read back -> session summary returns correct counts.

### Open / next

- `pytest` was not run end-to-end (no venv set up in this session). The
  test suite is expected to pass once `pip install -e ".[dev]"` is run.
- No live Ollama call has been made yet — that is the **Week 1 go/no-go
  gate**: pull `gemma4:26b`, take a Minecraft screenshot, verify the
  model can read the chat text. Until that gate passes, every other
  Week 1 task is on hold.
- Docker for Ollama is intentionally still **not** wired up (per the
  CONTEXT.md "Don't add Docker yet" note).

---

## 2026-04-08 — Initial repo scaffold

### Summary

Created the GuardianLens repo from scratch following the v1 CONTEXT.md.
Built a typed `src/guardlens/` core package, a Gradio dashboard, project
metadata files (`pyproject.toml` with ruff + mypy + pydantic-mypy),
config scaffolding, model deployment file, demo video script, and
weekly planning docs. Inspiration drawn from the
`python-code-cleanup` skill (Pydantic config, ruff, type hints
everywhere, centralized config in one module).

### Files

**Created**

- `CONTEXT.md` — v1 of the project context (later replaced by v3).
- `README.md` — Kaggle-writeup-oriented top-level README.
- `pyproject.toml` — single source of truth for deps + ruff + mypy +
  pydantic-mypy + ANN rules. Python 3.11+, hatchling backend.
- `requirements.txt`, `.python-version`, `.gitignore`, `.env.example`.
- `src/guardlens/__init__.py` — public surface (later emptied for v3).
- `src/guardlens/config.py` — Pydantic Settings with `OllamaConfig`,
  `MonitorConfig`, `SessionConfig`, `AlertConfig`, `DashboardConfig`.
  Layered loading: defaults -> YAML -> env vars (`GUARDLENS_*`).
- `src/guardlens/schema.py` — `ThreatLevel`, `ThreatCategory`,
  `GroomingStage`, `AlertUrgency` enums + `ThreatClassification`,
  `GroomingStageResult`, `ParentAlert`, `ScreenAnalysis` Pydantic
  models with `is_safe` / `needs_parent_attention` helpers.
- `src/guardlens/prompts.py` — v1 versioned `SYSTEM_PROMPT` and
  `ANALYSIS_PROMPT`.
- `src/guardlens/tools.py` — three function-calling tool dicts derived
  from the schema enums.
- `src/guardlens/monitor.py` — `mss` capture loop generator with
  old-screenshot pruning (`keep_last_n`).
- `src/guardlens/analyzer.py` — `GuardLensAnalyzer` (the only module
  that talks to Ollama). Parses tool calls into Pydantic models with a
  SAFE fallback so the demo never blanks out on a malformed response.
- `src/guardlens/session_tracker.py` — bounded sliding window +
  escalation heuristic (`consecutive_unsafe`, `has_escalating_pattern`,
  `latest_grooming_stage`).
- `src/guardlens/alerts.py` — `AlertSender` with SMTP + webhook
  channels, `minimum_urgency` gating, never includes raw chat content.
- `src/guardlens/utils.py` — `seed_everything`, `configure_logging`
  (rich-aware).
- `app/__init__.py`, `app/dashboard.py` — Gradio Blocks UI with daemon
  `MonitorWorker` thread, status badge, latest screenshot, timeline
  dataframe, thinking-chain markdown panel, 2s polling timer.
- `configs/default.yaml` — default config mirroring the Pydantic
  models.
- `models/Modelfile` — Ollama deployment config for the fine-tuned
  variant.
- `demo/video_script.md` — beat sheet + production checklist for the
  2-minute demo.
- `docs/architecture.md` — system architecture, threading model,
  configuration flow.
- `docs/fine_tuning_plan.md` — Unsloth plan, dataset sources, training
  config, export pipeline, risks.
- `docs/weekly_plan.md` — week-by-week working checklist.
- `notebooks/README.md` — placeholder describing the three Kaggle
  notebooks (data prep, fine-tune, evaluate).
- `data/.gitkeep` — placeholder so the data folder exists in git.
- `tests/__init__.py`, `tests/test_schema.py` — sanity tests for the
  Pydantic models.

### Open / next

- Validate Gemma 4 vision OCR on a Minecraft screenshot. **Week 1
  go/no-go gate.**
