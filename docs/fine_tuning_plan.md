# Fine-Tuning Plan (Unsloth Prize)

## Goal

Train a Gemma 4 E4B variant that detects grooming + bullying patterns with
substantially higher accuracy than the base model. Target: **base 64% -> fine-tuned 91%**
on our held-out test set. Numbers go straight into the demo video and writeup.

## Datasets

| Source                          | Type        | ~Size       | Notes                          |
|---------------------------------|-------------|-------------|--------------------------------|
| PAN12 sexual predator ID corpus | text chats  | 28k convos  | <https://pan.webis.de>         |
| Synthetic safe gaming chats     | text chats  | 300+        | Hand-written, varied styles    |
| Synthetic bullying chats        | text chats  | 100+        | Include subtle exclusion cases |
| Multimodal screenshots          | image+text  | 50+         | Game/Discord screenshots + ideal analysis |

All sources get normalized to JSONL with the GuardianLens prompt format
(system + user + assistant tool calls).

## Training config

```python
model_name = "unsloth/gemma-4-E4B-it"
lora_r = 16
lora_alpha = 16
lora_dropout = 0
learning_rate = 2e-4
num_epochs = 3
per_device_train_batch_size = 2
gradient_accumulation_steps = 4
max_seq_length = 2048
```

Single Kaggle T4 (16 GB). E4B QLoRA fits comfortably.

## Notebooks

- `notebooks/01_prepare_data.ipynb` — load PAN12, generate synthetic chats,
  combine, deduplicate, write JSONL.
- `notebooks/02_finetune.ipynb` — Unsloth QLoRA training.
- `notebooks/03_evaluate.ipynb` — baseline vs fine-tuned per-category metrics.

## Metrics to report

- Overall accuracy (base vs fine-tuned).
- Per-category: grooming detection rate, bullying detection rate, false-positive rate.
- Training loss curve.
- Inference speed (tokens/sec) on the same hardware as the base model.

## Export pipeline

```
Gemma 4 E4B-IT (HuggingFace)
  -> Unsloth QLoRA fine-tuning (Kaggle T4)
    -> Save adapter weights
      -> Merge adapter + export GGUF (q4_k_m)
        -> Copy GGUF to server
          -> ollama create guardlens -f models/Modelfile
            -> ollama run guardlens
```

The Modelfile already exists at `models/Modelfile`. Update the `FROM` line
to point at the produced GGUF.

## Risks

- **PAN12 distribution mismatch.** Old IRC chats look nothing like modern
  game chat. Mitigation: heavy synthetic augmentation + multimodal pairs.
- **Tool-call format drift after fine-tuning.** Unsloth/QLoRA can erode the
  model's instruction-following. Mitigation: include 50+ examples in the
  training set where the assistant emits the exact GuardianLens tool calls.
- **GGUF tool-call quirks.** Validate tool-call output on the GGUF before the
  demo recording — `analyzer._extract_classification` falls back to SAFE if
  parsing fails, which would be visible on the live dashboard.
