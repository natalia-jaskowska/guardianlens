# Architecture

```
+-------------------+      +-------------------+      +----------------------+
|  Screen capture   | ---> |   GuardLens       | ---> |    Gradio UI         |
|  (mss, every 15s) |      |   Analyzer        |      |  - status badge      |
|                   |      |  (Ollama + Gemma) |      |  - latest screenshot |
+-------------------+      +-------------------+      |  - timeline          |
                                    |                 |  - thinking chain    |
                                    v                 +----------------------+
                            +---------------+                  |
                            | SessionTracker|                  v
                            |  sliding win  |          +---------------+
                            +---------------+          |  AlertSender  |
                                                       | email/webhook |
                                                       +---------------+
```

## Module map

| Module                                | Purpose                                              |
|--------------------------------------|------------------------------------------------------|
| `guardlens.config`                    | Pydantic Settings — single source of truth.          |
| `guardlens.schema`                    | Typed analysis results (`ScreenAnalysis`, ...).      |
| `guardlens.prompts`                   | Versioned prompt templates.                          |
| `guardlens.tools`                     | Function-calling tool definitions.                   |
| `guardlens.monitor`                   | `mss` capture loop generator.                        |
| `guardlens.analyzer`                  | `GuardLensAnalyzer` — only place that talks to Ollama. |
| `guardlens.session_tracker`           | Sliding window of recent analyses.                   |
| `guardlens.alerts`                    | Email + webhook dispatch.                            |
| `guardlens.utils`                     | `seed_everything`, logging setup.                    |
| `app.dashboard`                       | Gradio Blocks app + background `MonitorWorker`.      |

## Threading model

- **Main thread:** Gradio event loop + UI rendering.
- **Monitor thread:** runs `capture_loop`, calls the analyzer, and pushes
  results onto a `queue.Queue`. Started by `MonitorWorker.start()`. Daemon
  thread, so it dies with the process.
- The dashboard polls the worker via `worker.latest()` every 2 seconds (Gradio
  `Timer`). Side effect of polling: latest analysis is pushed into the session
  tracker and the alert sender.

This single-worker model is intentional — it keeps Ollama load predictable
(one in-flight request at a time) and means we never have to reason about
concurrent writes to the session window.

## Configuration flow

```
configs/default.yaml -----.
                          v
.env / env vars  -----> load_config() -----> GuardLensConfig (Pydantic)
                          ^
                          |
              kwargs passed in code
```

Every module takes the relevant *sub-section* of the config (e.g.
`MonitorConfig`, `OllamaConfig`) rather than the full object — keeps tests
isolated and signatures honest.

## Why this shape

- **One analyzer class, no global state.** Easy to swap models for the
  fine-tuned demo (`use_finetuned=True`), and easy to mock in tests.
- **Pydantic at every boundary.** Tool calls from Ollama get validated as
  soon as they enter the codebase. The dashboard never has to deal with raw
  dicts.
- **Sliding window in its own class.** Lets us add escalation heuristics
  without touching the analyzer.
- **No Docker yet.** Per CONTEXT.md the local Ollama install is good enough
  through demo recording. Containerization is a Week 6 stretch goal.
