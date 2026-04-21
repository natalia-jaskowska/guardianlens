# GuardianLens

> On-device AI child safety monitor powered by Gemma 4. Watches a child's screen
> in real time, detects grooming, cyberbullying, and inappropriate content with
> explainable reasoning, and alerts the parent — without ever sending chat data
> to the cloud.

**Pitch:** *Family Link counts minutes. GuardianLens understands what's happening.*

Built for the **Gemma 4 Good Hackathon** (Kaggle x Google DeepMind).
Targeting the Safety & Trust track + Ollama special prize.

---

## What it does

- Captures the child's screen at a fixed interval (default 15 s).
- Sends each screenshot to a local Gemma 4 vision model via Ollama.
- Gemma 4 reads the visible chat text, identifies the platform, and reasons about safety.
- Three structured tool calls produce the final analysis:
  1. `extract_conversations` — platform, participants, visible messages
  2. `update_conversation_status` — threat level, category, confidence, indicators, narrative
  3. `generate_parent_alert` — concise summary the parent actually sees
- A FastAPI dashboard streams the live status, alerts, and the model's full thinking chain.
- Optional email or webhook notification on warning / alert / critical.

Everything runs locally. The child's chats never leave the device.

---

## Architecture

```
┌──────────────────────────┐          ┌────────────────────────────────────┐
│  CLIENT (child's device) │          │        SERVER (home machine)       │
│                          │          │                                    │
│  guardlens-client        │  PNG     │  POST /api/frames                  │
│  ├─ mss screen capture   │─────────▶│  ├─ ConversationPipeline           │
│  └─ httpx sender         │          │  │    └─ Gemma 4 via Ollama        │
│                          │          │  ├─ SQLite database                │
└──────────────────────────┘          │  └─ FastAPI dashboard :7860        │
                                      └────────────────────────────────────┘
```

The client and server can run on the **same machine** (standalone mode) or on
**separate devices** across the local network (client/server mode).

---

## Option A — Docker (recommended for server)

### Requirements

- Docker + Docker Compose
- ~8 GB free disk space for the Ollama model

### 1. Start the server

```bash
git clone https://github.com/natalia-jaskowska/guardianlens.git
cd guardianlens

docker compose up -d
```

This starts two containers:
- `ollama` — serves the Gemma 4 model on port `11434`
- `guardlens` — FastAPI dashboard on port `7860`

> The server starts in **receive mode** (`--no-capture`): it waits for frames
> from a client instead of capturing the local screen.

### 2. Pull the model (first run only)

```bash
docker compose exec ollama ollama pull gemma4:latest
```

To use the larger 26B variant:

```bash
MODEL=gemma4:26b docker compose up -d
```

### 3. Open the dashboard

```
http://localhost:7860
```

Or from another device on the same network:

```
http://<server-ip>:7860
```

---

## Option B — Python (standalone or development)

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) or pip
- [Ollama](https://ollama.com) running locally

### 1. Install Ollama and pull the model

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:latest
```

### 2. Install and run

```bash
git clone https://github.com/natalia-jaskowska/guardianlens.git
cd guardianlens

uv sync          # or: pip install -e .

# Standalone — captures the local screen and analyzes it
python run.py

# Demo mode — no real screen needed (uses synthetic screenshots)
python run.py --demo-mode

# Receive mode — disable local capture, wait for client frames
python run.py --no-capture
```

### Common flags

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `gemma4:latest` | Ollama model name |
| `--ollama-host` | `http://localhost:11434` | Ollama server URL |
| `--interval` | `15` | Seconds between captures |
| `--dashboard-port` | `7860` | Dashboard HTTP port |
| `--demo-mode` | off | Synthetic screenshots, no display required |
| `--no-capture` | off | Receive frames from remote client via API |
| `--log-level` | `INFO` | DEBUG / INFO / WARNING / ERROR |

---

## Option C — Client on child's device

Install and run the lightweight client on the **child's device**. It captures
the screen and streams frames to the server running on another machine.

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

### Install

```bash
cd client
uv sync
```

### Run

```bash
# Basic usage — replace with your server IP
guardlens-client --server 192.168.1.55:7860

# Custom interval
guardlens-client --server 192.168.1.55:7860 --interval 10

# Second monitor
guardlens-client --server 192.168.1.55:7860 --monitor 2

# Demo/headless mode (no real display)
guardlens-client --server 192.168.1.55:7860 --demo-folder /path/to/images
```

### Client flags

| Flag | Default | Description |
|------|---------|-------------|
| `--server` | required | Server address, e.g. `192.168.1.55:7860` |
| `--interval` | `15` | Seconds between captures |
| `--monitor` | `1` | Monitor index (1 = primary) |
| `--output-dir` | `client_screenshots` | Local temp directory |
| `--demo-folder` | off | Cycle through images instead of live capture |
| `--keep` | `20` | Local screenshots to keep before pruning |
| `--log-level` | `INFO` | Log verbosity |

---

## Typical two-device setup

```
Parent's PC (server)            Child's laptop (client)
─────────────────────           ──────────────────────
docker compose up -d            uv sync (in client/)
                                guardlens-client \
                                  --server 192.168.1.55:7860
Open http://192.168.1.55:7860 to watch the live dashboard
```

---

## Project layout

```
run.py                  Server entry point
app/                    FastAPI dashboard (server, templates, static)
src/guardlens/          Core library: pipeline, analyzer, database, config
configs/                Default YAML config
client/                 Standalone capture client (uv, pyproject.toml)
  src/guardlens_client/ capture.py · sender.py · main.py
Dockerfile              Server Docker image
docker-compose.yaml     Ollama + GuardianLens stack
outputs/                Screenshots, SQLite database (gitignored)
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
Override anything via environment variables (`GUARDLENS_OLLAMA__HOST=...`) or
a YAML config file passed to `--config`.

---

## License

MIT.
