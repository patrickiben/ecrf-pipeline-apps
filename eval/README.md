# eval/: the real model path, setup, training and evaluation

This folder holds everything needed to run the Coding QC assist and the De-identification review assist on their **real** model path (Cactus Needle3, hnswlib, Laya, XGBoost) and to reproduce the measured numbers in [`docs/EVALUATION.md`](../docs/EVALUATION.md) and in the [evaluation case study](https://patrickiben.github.io/ecrf-pipeline-apps/evaluation.html) and the [case study](https://patrickiben.github.io/ecrf-pipeline-apps/case-study.html). All data here is **synthetic**: invented terms with 99-prefixed placeholder codes (not MedDRA) and invented notes.

The stand-in path needs none of this. Without a models dir the apps run their labeled `[SI]` stand-ins, and `python tests/qc_test.py` passes with no model installed.

## 1. Install the real-path runtimes

Python 3.12. CPU-only torch first, so pip does not pull about 1.8 GB of CUDA wheels:

```bash
pip install -r requirements.txt
pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
pip install cactus-needle==3.2.8 laya==0.4.13 hnswlib==0.8.0 transformers==5.20.2 \
            "xgboost-cpu==3.4.1; platform_system == 'Linux'" "xgboost==3.4.1; platform_system != 'Linux'"
```

`hnswlib` ships no wheels and builds from source (it needs a C++ compiler). Never `pip install needle`: that is an unrelated CSS-testing package with the same import name, and the apps reject it.

## 2. Build the models dir (needs network once)

```bash
python eval/fetch_models.py --out models
```

| path in the models dir | what | from |
|---|---|---|
| `needle3/needle3.cact` | Needle3 weights (35.3 MB) | Hugging Face `Cactus-Compute/needle3`, via cactus-needle's own fetch |
| `needle3/libneedle.so` (`.dylib`, `.dll`) | Needle3's native CPU engine (1.6 MB) | the engine wheel in the same repo |
| `laya/` | Laya English checkpoint only (846 MB) | `convaiinnovations/laya`, repository root at the reviewed commit `55cf4c4e` pinned in `laya/revisions.py` |
| `laya_calibration_coding.json`, `laya_calibration_phi.json` | Laya temperatures fitted on the synthetic calibration splits | copied from `eval/artifacts/` |
| `meddra_coder.json` + `.meta.json` | coding re-ranker (XGBoost) and its feature contract | copied from `eval/artifacts/` |
| `phi_token_classifier.json` + `.meta.json` | PHI per-span gate (XGBoost) and its feature contract | copied from `eval/artifacts/` |
| `index_cache/` | written by the coding app: the embedded dictionary, so a release is embedded once | the app |

The script prints a SHA-256 for every file. Copy the folder to the air-gapped machine and set it as **Models dir** in either app's sidebar. The apps then read only that folder: they set `HF_HUB_OFFLINE=1` and switch off Needle3's default-on telemetry (`NEEDLE_TELEMETRY=0`, `DO_NOT_TRACK=1`) before any runtime loads, and they give Needle3 explicit file paths, so nothing is fetched from `~/.cache` or the network.

A tier shows **REAL** in the banner and audit only when its artifact actually loaded. An artifact that is present but whose runtime is missing, or that fails to load, **stops** the run; a gate whose feature contract the loaded tiers do not meet (for example the re-ranker without Needle3) also stops it. On the PHI app, Needle3's proposals are used only behind the trained gate: without `phi_token_classifier.json`, PHI Tier 2 stays on its stand-in and the audit says why.

## 3. Reproduce the numbers

```bash
python eval/make_data.py                       # regenerate eval/data/ (seed 42; byte-identical)
python eval/bench_index.py --models models     # Stage 1: index latency and size -> results/stage1_index.json
python eval/run_eval.py   --models models --smoke   # optional: the whole pipeline on a small slice (about 5 min)
python eval/run_eval.py   --models models      # Stages 2-3: calibrate, train, evaluate -> results/stage2_3.json
python eval/deck_b_worked.py --models models   # Stage 4: the case study's worked rows -> results/deck_b_worked.json
ECRF_MODELS_DIR=models python tests/qc_test.py # adds the RM real-path checks (skipped without it)
```

The within-sibling check of the Coding QC assist (`docs/EVALUATION.md`, "Within-sibling discrimination") needs no models for its stand-in path:

```bash
python eval/sibling_sets.py --check            # the sibling sets in data/sibling_sets.csv are current
python eval/sibling_eval.py                    # stand-in path -> results/sibling_summary.json, sibling_items.csv
python eval/sibling_eval.py --models models    # adds the real path
python eval/sibling_knownanswer.py             # known-answer demo -> results/sibling_knownanswer.csv (about 3 min)
python tests/test_sibling.py                   # its checks, also run in CI
```

Both scripts refuse to run unless the SHA-256 of `sibling_plan.md` equals the committed `sibling_plan.sha256`, and they read every parameter from the plan. A change to the plan, to an input file or to the coding app's scoring code needs a new registration before any scoring.

`run_eval.py` re-fits the Laya temperatures and retrains both gates, writing them into the models dir (and copying them to `eval/artifacts/`). Everything is seeded and CPU inference is deterministic, so a rerun on the same versions reproduces the committed files. A `--smoke` run writes `*_smoke` result files and leaves `eval/artifacts/` alone, but it does overwrite the artifacts in the models dir, so finish with a full run.

Two Laya details matter when you refit. Laya fits a temperature per answer type and option count (the `noul:2` bucket) only from 2,000 records or more; below that it fits the type-level `noul` scalar, and that is what it applies. The calibration splits here are smaller, so the files hold the type-level scalar, and the two PHI questions share it. Each calibration file also records the checkpoint it was fitted for (`convaiinnovations/laya@<commit>` and the checkpoint config). The apps accept a file whose only difference is the path, because a models dir moves between machines, and stop on one fitted for a different checkpoint config.

## Files

| file | role |
|---|---|
| `make_data.py` | generates the synthetic dictionary (3,371 terms, 519 preferred terms), the coding set (1,920 verbatims: exact, colloquial, misspelled, negated) and the PHI set (880 fields, 1,166 gold spans, with look-alikes); grouped train/calib/test splits |
| `_app.py` | loads an app's own tier functions from its file (everything above its UI marker), so the evaluation measures the shipped code, not a copy |
| `bench_index.py` | Stage 1 |
| `run_eval.py` | Stages 2 and 3 |
| `deck_b_worked.py` | Stage 4: runs both apps end to end on `sample_data/` and records the worked values shown in the case study (named for the retired Deck B, which the case study replaced) |
| `fetch_models.py` | builds a models dir |
| `sibling_sets.py` | the within-sibling check's sibling sets (lab direction, body site), from preferred-term names only -> `data/sibling_sets.csv` |
| `sibling_plan.md`, `sibling_plan.sha256` | the within-sibling check's plan, registered before any scoring, and its SHA-256 lock |
| `sibling_eval.py` | the within-sibling check: scores, nulls, keyword comparator, routing gates, negative control (refuses on a plan hash mismatch) |
| `sibling_knownanswer.py` | the within-sibling check's known-answer demo (planted scorers a to e) |
| `data/` | the generated data (committed; regenerate with `make_data.py`) |
| `artifacts/` | the trained, synthetic-data artifacts (committed, small) |
| `results/` | measured outputs (committed) |
