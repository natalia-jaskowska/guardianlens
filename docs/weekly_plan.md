# Weekly Plan

Cross-reference: [CONTEXT.md](../CONTEXT.md). This file is the working
checklist; CONTEXT.md is the strategic version.

## Week 1 (Apr 8-14): Validate + data

- [ ] Install Ollama on the dev server.
- [ ] Pull `gemma4` (E4B) and `gemma4:26b`.
- [ ] Take a Minecraft screenshot with visible chat.
- [ ] Verify Gemma 4 can read the chat text. **Go / no-go gate.**
- [ ] Download PAN12.
- [ ] Write 300+ safe gaming chats.
- [ ] Write 100+ bullying chats.
- [ ] Capture 50+ multimodal training screenshots.
- [ ] Format everything as JSONL.
- [ ] Run baseline accuracy on E4B.

## Week 2 (Apr 15-21): Fine-tune

- [ ] Set up Kaggle T4 notebook with Unsloth.
- [ ] Train E4B QLoRA on the safety dataset.
- [ ] Compare fine-tuned vs baseline per category.
- [ ] Export GGUF, register Ollama model `guardlens`.
- [ ] Sanity-check function calling on the fine-tuned model.

## Week 3 (Apr 22-28): Build pipeline

- [ ] `monitor.py` capture loop runs end-to-end.
- [ ] `analyzer.py` returns valid `ScreenAnalysis` for staged screenshots.
- [ ] `session_tracker.py` reflects escalation patterns.
- [ ] `alerts.py` round-trips an email + webhook against a test inbox.
- [ ] End-to-end test: launch dashboard, play game, see live analyses.

## Week 4 (Apr 29 - May 5): Dashboard + demo prep

- [ ] Polish the Gradio dashboard (status badge, timeline, thinking panel).
- [ ] Record 3 demo scenarios (safe, grooming, bullying).
- [ ] Cross-platform spot checks (Minecraft, Discord, browser).
- [ ] Smooth out error handling — never blank out on the live demo.

## Week 5 (May 6-12): Video + writeup (highest priority)

- [ ] Cut the 2-minute video using `demo/video_script.md`.
- [ ] Write the Kaggle submission writeup.
- [ ] README screenshots refreshed.
- [ ] Final repo cleanup pass.

## Week 6 (May 13-18): Submit

- [ ] Final video review with at least one outside set of eyes.
- [ ] Submit to Safety & Trust track.
- [ ] Mention Unsloth + Ollama prominently in the writeup.
- [ ] Verify: video link works, repo is public, demo is reproducible.
