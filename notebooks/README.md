# Notebooks

Three Kaggle notebooks support the Unsloth fine-tuning workflow. They are
intentionally Kaggle-only — fine-tuning runs on a free T4, not on the dev
server (the server is reserved for inference and demo recording).

| Notebook                  | Purpose                                                  |
|---------------------------|----------------------------------------------------------|
| `01_prepare_data.ipynb`   | Load PAN12, generate synthetic chats, write JSONL.       |
| `02_finetune.ipynb`       | Unsloth QLoRA on Gemma 4 E4B.                            |
| `03_evaluate.ipynb`       | Baseline vs fine-tuned metrics. Charts for the writeup.  |

The notebooks consume the Pydantic models from `src/guardlens/schema.py`
where it makes sense — keep the data format aligned with the runtime.
