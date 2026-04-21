# Architecture

```
+-------------------+      +----------------------------+      +-------------------+
|  Screen capture   | ---> |  ConversationPipeline      | ---> |  FastAPI dashboard|
|  (mss / client /  |      |  (Ollama + Gemma 4)        |      |  SSE stream       |
|   demo / folder)  |      |  1. extract_conversations  |      |  :7860            |
+-------------------+      |  2. match & merge history  |      +-------------------+
                           |  3. update_conv_status     |              |
                           |  4. generate_parent_alert  |              v
                           +----------------------------+      +-------------------+
                                        |                      |   AlertSender     |
                                        v                      | Telegram/email/   |
                                 +-----------+                 | webhook           |
                                 |  SQLite   |                 +-------------------+
                                 |  database |
                                 +-----------+
```

## Module map

| Module                         | Purpose                                                        |
|-------------------------------|----------------------------------------------------------------|
| `guardlens.config`             | Pydantic Settings — single source of truth for all settings.  |
| `guardlens.schema`             | Typed results: `ScreenAnalysis`, `ThreatClassification`, etc. |
| `guardlens.prompts`            | Versioned system prompt templates.                            |
| `guardlens.tools`              | Ollama function-calling tool definitions.                     |
| `guardlens.ollama_utils`       | Helpers: `find_call`, `extract_thinking`, `get_tool_calls`.   |
| `guardlens.pipeline`           | `ConversationPipeline` — orchestrates 4 LLM calls per frame.  |
| `guardlens.monitor`            | `mss` capture loop (generator); symlinks watch-folder images. |
| `guardlens.database`           | `GuardLensDatabase` — all state persisted in SQLite.          |
| `guardlens.alerts`             | `AlertSender` — Telegram, email, webhook dispatch.            |
| `guardlens.privacy`            | Privacy-by-design enforcement (redaction, byte counter).      |
| `guardlens.demo`               | Synthetic screenshot generator for demo / headless mode.      |
| `guardlens.utils`              | `seed_everything`, logging setup.                             |
| `app.server`                   | FastAPI app factory; SSE stream, REST API, frame receiver.    |
| `app.state`                    | `AppState` + `MonitorWorker` — thread-safe bridge to pipeline.|
| `app.serializers`              | Convert `ScreenAnalysis` → JSON-friendly dicts for the UI.    |

## Threading model

- **Main thread:** `asyncio` event loop running FastAPI (uvicorn).
- **Monitor thread:** daemon thread running `MonitorWorker._run()`. Drives the
  capture loop, calls `ConversationPipeline.push_screenshot()`, and updates
  shared state (scan count, latest screenshot path, latest conversation IDs).
- **SSE clients** poll `GET /api/stream` (server-sent events). The event
  generator reads `AppState` and serializes it every second. No queue needed —
  each SSE tick reads current state directly.

This single-worker model is intentional: one in-flight Ollama request at a
time keeps GPU load predictable and avoids concurrent writes to SQLite.

## Configuration flow

```
configs/default.yaml ---------.
                               v
env vars / .env  ---------> GuardLensConfig (pydantic-settings)
                               ^
                               |
                  CLI flags (argparse → override dict)
```

Environment variables take priority over the YAML file. CLI flags are passed
as override kwargs but `settings_customise_sources` ensures env vars win.
Every sub-module receives only its own config slice (`OllamaConfig`,
`MonitorConfig`, etc.) to keep tests isolated and signatures honest.

## Analysis pipeline (per frame)

`ConversationPipeline.push_screenshot(path)` runs up to 4 sequential LLM calls:

1. **`extract_conversations`** — vision model identifies all visible chat
   fragments, platform, and participants from the screenshot.
2. **Match & merge** — each fragment is fuzzy-matched to an existing
   conversation in the database (or a new one is created). New messages are
   deduplicated against stored history.
3. **`update_conversation_status`** — full conversation history is reassessed:
   threat level, category, confidence, grooming stage, indicators, narrative.
4. **`generate_parent_alert`** — if threat level ≥ WARNING, a concise
   parent-facing summary is generated and dispatched via `AlertSender`.

All intermediate state is committed to SQLite after each step so a crash
mid-pipeline loses at most one frame.

## Docker deployment

`docker-compose.yaml` starts two containers:

- `ollama` — Gemma 4 model server on port `11434`
- `guardlens` — FastAPI dashboard on port `7860`, `--no-capture` by default
  (receives frames from `guardlens-client` running on the child's device)

The server and client can also run on the same machine for standalone use.
