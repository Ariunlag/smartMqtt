# Research notebooks

## `embedding_strategies.ipynb` — Research Question 1

Benchmarks how to embed IoT tag `key:value` pairs so semantically distinct streams don't
collapse (the `temp=22.5` vs `voltage=22.5` problem). Compares, on **accuracy** and
**computational cost**, at both the **pair** and **stream** level:

| id | approach |
|----|----------|
| `S0_value` | value only — the baseline being critiqued |
| `S1_concat` | **Approach 1** — `embed("key: value")` |
| `S2a_dual_concat` / `S2b_dual_weighted` | **Approach 2** — static dual-channel fusion |
| `S3_template` | **Approach 3** — templated sentence |
| §4 learned fusion | **Approach 2** — supervised upper bound |

Uses the **same model as production** (`BAAI/bge-small-en-v1.5`) and a reproducible synthetic
dataset generated in-notebook.

### Run it

The notebook needs `sentence-transformers`, `torch`, `scikit-learn`, `numpy` (from
`backend/requirements.txt`) plus the extras in `notebooks/requirements.txt`.

> ⚠️ The existing `backend/.venv` was built with Python 3.12.6, which is no longer installed on
> this machine, so it can't be used as-is. Create a fresh environment:

```bash
# from repo root
python -m venv .venv-nb
.venv-nb/Scripts/activate          # Windows;  source .venv-nb/bin/activate on macOS/Linux
pip install -r backend/requirements.txt -r notebooks/requirements.txt
python -m ipykernel install --user --name influxai-nb
jupyter lab notebooks/embedding_strategies.ipynb
```

First run downloads the embedding model (~130 MB) and takes a couple of minutes on CPU;
re-runs are fast (vectors are cached in-process).

Plots and pretty tables (`matplotlib`, `pandas`) are optional — the notebook degrades to plain
text if they're missing.
