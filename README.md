# GuardianLens

> On-device AI child safety monitor powered by Gemma 4. Watches a child's screen
> in real time, detects grooming, cyberbullying, and inappropriate content with
> explainable reasoning, and alerts the parent — without ever sending chat data
> to the cloud.

**Pitch:** *Family Link counts minutes. GuardianLens understands what's happening.*

Built for the **Gemma 4 Good Hackathon** (Kaggle x Google DeepMind).
Targeting the Safety & Trust track + Ollama and Unsloth special prizes.

---

## What it does

- Captures the child's screen at a fixed interval (default 15s).
- Sends each screenshot to a local Gemma 4 vision model via Ollama.
- Gemma 4 reads the visible chat text, identifies the platform, and reasons about safety.
- Three structured tool calls produce the final analysis:
  1. `classify_threat` — level, category, confidence, indicators
  2. `identify_grooming_stage` — stage in the grooming pipeline + evidence
  3. `generate_parent_alert` — concise summary the parent actually sees
- A Gradio dashboard streams the live status, alerts, and the model's
  full thinking chain so a parent (or judge) can audit any decision.
- Optional email or webhook notification on warning/alert/critical.

Everything runs locally. The child's chats never leave the device.

---

## Quick start

```bash
# 1. Install Ollama and pull the inference model
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:26b   # or `gemma4` for the smaller E4B build

# 2. Install the project
uv sync                  # or: pip install -e ".[dev]"

# 3. Launch the dashboard (also starts the monitor loop)
uv run python -m app.dashboard
```

The dashboard opens at <http://localhost:7860>. Use `share=True` in
`app/dashboard.py` to expose a public Gradio link for demo recording.

---

## Project layout

See [CONTEXT.md](CONTEXT.md) for the full project context (competition rules,
project goals, demo script, weekly plan, coding principles). That file is the
single source of truth for any work in this repo.

```
src/guardlens/   # Typed Python package: monitor, analyzer, schema, tools, ...
app/             # Gradio dashboard
configs/         # Default YAML config
notebooks/       # Kaggle notebooks for Unsloth fine-tuning
models/          # Ollama Modelfile for the fine-tuned variant
docs/            # Architecture, fine-tuning plan, weekly plan
demo/            # Video script and demo assets
data/            # Training/test data (gitignored)
```

---

## Development

```bash
ruff check . --fix
ruff format .
mypy src/guardlens app
pytest
```

All configuration lives in `src/guardlens/config.py` (Pydantic Settings).
Override anything via environment variables (see `.env.example`) or by passing
a YAML file to `load_config(Path("configs/default.yaml"))`.

---

## License

MIT.
