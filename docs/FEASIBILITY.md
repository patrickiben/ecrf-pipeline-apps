# Feasibility: real Needle3 and Laya runtimes (Stage 0)

The Stage 0 record, written before any build work: can the two open-source models behind the coding and
de-identification apps' real model path be obtained, loaded offline on a CPU and called the way the apps
assumed, and what did reading the apps' real-path code find? It was checked on 2026-10-21 (code read only;
the model hosts were not yet reachable from the build environment) and 2026-10-22 (both models downloaded,
loaded offline and measured). All data used here is synthetic.

**Status.** Stage 0 is closed. Stages 1 to 4 were then built: the five wiring defects below are fixed in the
apps, each pinned by an always-run `RW` check in `tests/qc_test.py`, and the measured results are in
[`EVALUATION.md`](EVALUATION.md) and on the published
[evaluation case study](https://patrickiben.github.io/ecrf-pipeline-apps/evaluation.html). How to build the
models dir and rerun everything is in [`../eval/README.md`](../eval/README.md). Where this file describes the
apps, it describes them as they were before those stages.

This file was trimmed on 2026-10-25 for the portfolio: the build environment's network-allowlist notes,
host-by-host probe logs, redirect traces, install timings and a long evidence index were removed. The full
version is in the git history (`git show 3c104c5:docs/FEASIBILITY.md`).

The checks ran in AI-assisted coding sessions (Claude Code; commits authored "Claude" in the history).

## Environment (2026-10-22)

| Item | Value |
|---|---|
| Machine | Intel Xeon @ 2.80GHz, 4 vCPU, AVX2 and AVX-512, no GPU; every statement below is about CPU-only use |
| Memory | 15 GiB RAM, no swap |
| OS | Ubuntu 24.04.5 LTS, kernel 6.18, x86_64 |
| Python | 3.12.3 in a dedicated virtual environment |
| Packages | `torch==2.14.1+cpu`, `cactus-needle==3.2.8`, `laya==0.4.13`, `hnswlib==0.8.0`, `transformers==5.20.2`, `huggingface_hub==2.2.0`, `numpy==2.5.4` |

"Measured" below means measured on this machine on 2026-10-22, offline (`HF_HUB_OFFLINE=1`), with
`NEEDLE_TELEMETRY=0` and `DO_NOT_TRACK=1` set for every command. "Cold load" means a fresh Python process with
the model files probably in the OS page cache, not a cold disk.

## Verdict

Both runtimes work from Python on a CPU, fully offline once the files are staged:

- **Needle3** (`cactus-needle` 3.2.8, engine 3.3.3): 36.0 MB downloaded; weights Apache-2.0 per the model card;
  **embedding dimension 3072**; `embed("Patient denies headache.")` median 23.3 ms; cold load 0.40 s; peak RSS
  112 MiB.
- **Laya** (`laya` 0.4.13, English root checkpoint): 846.2 MB downloaded; weights Apache-2.0 per the model card;
  one `predict()` with 1 question median 268.9 ms, with 4 questions 531.4 ms (4 torch threads); cold load 8.4 s;
  peak RSS 2,866 MiB.
- An `hnswlib` inner-product index over Needle3 embeddings of the 12 demo dictionary terms returned sensible
  top-1 matches (a sanity check, not an evaluation).

Working models did not make the apps' real path work: reading the code found five wiring defects that stopped or
mislabeled it (below). One measured example also showed the negation risk is real.

## Needle3 (PyPI `cactus-needle`)

| Question | Finding |
|---|---|
| What it is | Official PyPI package `cactus-needle` 3.2.8: a pure-Python wrapper that loads a prebuilt native CPU engine (`libneedle.so`; `.dylib` on macOS, `.dll` on Windows) with `ctypes` and feeds it a `.cact` weights archive. No torch or JAX at inference. Import name `needle` |
| API | `needle.Needle(...)`; `agent.embed(text) -> list[float]`; `agent.complete(text)` for tool calls; `needle.extract(text, schema)` for structured extraction |
| Embedding | **3072-dim**, unit norm (L2 norm 1.0000002 measured), identical vectors on repeat calls. The apps' header and the original decks said "384-dim (SapBERT)"; Needle3 is not SapBERT and makes no biomedical claim |
| Span extraction | `extract()` returns field values, not character offsets, and the engine may "repair" values (its docs: a truncated phone number is completed). Offsets must be recovered by accepting only values found verbatim in the field |
| Files | Repository `Cactus-Compute/needle3` (commit `d6c7d6a2`): engine `libneedle.so` 1,590,584 bytes, SHA-256 `87476ff7...b260`; weights `needle3.cact` 35,335,380 bytes, SHA-256 `c9d915ec...0c38`. No ONNX export exists |
| Offline | Works with the files staged and `HF_HUB_OFFLINE=1`. Every base load otherwise asks the Hugging Face Hub for a `config.json`, even with a warm cache |
| License | Package, weights and engine: Apache-2.0 (model card front matter, Hub metadata, `LICENSE` file in the repository) |

**Needle3 risks.**
- The engine is an unsigned prebuilt native library, and the package's fetch code checks no hash. Stage the
  file, check it against the SHA-256 above, and load only the staged copy (the apps load it from the models dir).
- The Python package sends usage telemetry unless `NEEDLE_TELEMETRY=0`, `DO_NOT_TRACK=1` or `CI` is set. The
  engine library itself has no network code (`strings` and `nm` find no URL and no socket symbol).
- **Scores are compressed.** Unrelated terms scored 0.93 to 0.94 against a query whose right match scored 0.96,
  so no fixed similarity threshold carries over; thresholds have to be fitted on Needle3's own scores.
- Fast release cadence (37 PyPI releases in about ten weeks): pin the package (3.2.8) and engine (3.3.3) together.
- An unrelated PyPI project named `needle` ("Automated testing for your CSS") installs the same import name, so
  a bare import probe cannot tell the two apart.

## Laya (PyPI `laya`)

| Question | Finding |
|---|---|
| What it is | Official PyPI package `laya` 0.4.13 (Convai Innovations): a non-autoregressive classifier (ModernBERT backbone plus a decision head) on PyTorch and `transformers`. It answers typed questions about a whole string; it is not an embedder or a span extractor |
| API | `laya.load(model_dir, device="cpu")`, then `agent.predict(state, questions)`; or `laya.Router(...).predict(state, questions, model="english")`. `Router.route()` only picks a checkpoint and returns a routing decision, not answers |
| Measured answer | `predict("Patient denies headache.", {"headache": {"type": "noul", "instructions": "Does the patient report a headache?"}})` returned `noul` 0.6553: more likely yes than no for a denied symptom |
| Files | Repository `convaiinnovations/laya`, English checkpoint at the reviewed commit `55cf4c4e` pinned in the package: `model.safetensors` 842,609,210 bytes, SHA-256 `891102d3...8d86c`, plus tokenizer and encoder config. No ONNX file is published |
| Offline | Works from a local directory with `HF_HUB_OFFLINE=1`; no telemetry found in the package |
| License | Package Apache-2.0; weights Apache-2.0 per the model card (the repository has no separate `LICENSE` file) |

The crates.io crate named `laya` is an unrelated third-party Rust port that reads the same checkpoint files.

**Laya risks.**
- **Over-confident as shipped**, in its authors' own words; refitting temperatures is required. The English
  checkpoint also warns at load that one shipped temperature is invalid.
- **Near chance zero-shot** on its authors' typed-decision benchmark (0.362 accuracy against a 0.461
  majority-class baseline); the authors present it as a base to fine-tune, not a zero-shot decision engine.
- **Negation.** The one measured example above went the wrong way, so Laya had to be tested on a labeled
  negation set before any of its outputs could drive a decision.
- **Routing.** The router's default picked the multilingual checkpoint (which has no fitted temperatures) for an
  English sentence. Pin `model="english"` or load one local checkpoint.
- **Memory and speed.** One checkpoint peaked at 2,866 MiB; `Router(preload=True)`, as the apps first called it,
  loads all three. About 0.27 s per question means about 9 minutes per 1,000 records at 4 questions each.
- Fast release cadence (51 releases in five weeks): pin the package and the checkpoint commit.

## hnswlib smoke test (sanity check only)

The 12 dictionary names in `sample_data/meddra_demo.csv`, embedded by Needle3 (12 x 3072, float32), in an
`hnswlib.Index(space="ip", dim=3072)` with `M=32`, `ef_construction=200`, `ef=64`. For both queries the index's
top 3 equaled an exact brute-force ranking:

| Query | Top 3 (inner product) |
|---|---|
| "headache" | Headache (0.9593), Nausea (0.9292), Lightheadedness (0.9286) |
| "severe throbbing pain in back of head" | Pain in back of head (0.9601), Throbbing pain in head (0.9418), Watery diarrhoea (0.9365) |

Top-1 is right for both; the narrow range (an unrelated term at 0.9365) is the compression noted above.

## Package names in `requirements.txt`

| pip name | Import name | Finding |
|---|---|---|
| `cactus-needle` | `needle` | Right project (not `cactus-compute`, `cactus` or the CSS-testing `needle`). The coding and de-identification apps probed `needle` but could not tell it from the unrelated package; the anomaly app probed `cactus-needle`, which can never import |
| `laya` | `laya` | Right project. Importing it does not import torch, so a bare probe reports it available with torch absent |
| `hnswlib` | `hnswlib` | Right project; ships no wheels and builds from source (needs a C++ compiler) |
| `xgboost` | `xgboost` | Right project; 3.4.1 needs Python 3.12 or newer. On CPU-only Linux `xgboost-cpu` (same import name, no CUDA dependencies) is the smaller choice; install one, not both |

## Defects found in the apps' real-path wiring

Found by reading the probes on 2026-10-21 and reproduced with Streamlit's `AppTest` and stub modules; defect 2
was re-verified against the real loaded checkpoint on 2026-10-22. All five are fixed, each pinned by an
always-run check with stub packages (no models needed).

| # | Defect | Fix (check) |
|---|---|---|
| 1 | **Module names never bound.** The probe imported each runtime and discarded the result, so with the packages installed the apps stopped with `NameError: name 'needle' is not defined` (coding) and `name 'laya' is not defined` (de-identification) | Modules bound and their API checked inside the same `try` as the import (RW2) |
| 2 | **Wrong Laya call.** The apps called `Router.route()` and read answer attributes from its result, which is a routing decision: `AttributeError` with the real model | `predict(..., model="english")` and the answer's `noul` value (RW4) |
| 3 | **Banners claimed REAL with no real code path.** Tier 4 showed "REAL xgboost" when the library merely imported, though no code loaded a trained gate; the de-identification Tier 2 label changed while the regex stand-in still ran | A tier shows REAL only when its artifact loads (RW1, RW11) |
| 4 | **Guarded artifact names that cannot exist.** The guard looked for `needle3.onnx` and `laya.onnx`; neither model repository publishes an ONNX file | Guard and loader use the real artifacts: `needle3.cact` plus the engine, and the Laya checkpoint directory (RW8, RW9) |
| 5 | **Laya reported REAL with torch absent**, because `import laya` does not import torch; the first real call then raised `ModuleNotFoundError` | The probe also requires torch and transformers (RW8) |

The same reading fixed the "384-dim (SapBERT)" description in the coding app's header.

## Evidence

Package wheels and source distributions were downloaded into empty scratch folders, hash-checked against PyPI and
read as data before anything was installed. Model files were fetched with each package's own download code and
hashed (SHA-256 values above). Every model run used `python -I` from an empty working directory with the
telemetry and offline variables set. The full list of files read, commands run and host probes is in the git
history of this file.
