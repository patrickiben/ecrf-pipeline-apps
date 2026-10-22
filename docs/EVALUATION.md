# Evaluation: the real model path, measured

This file reports what the coding and PHI apps do on their **real** model path (open-source Cactus Needle3, hnswlib, Laya and XGBoost), measured on this repository's synthetic data. It follows [`FEASIBILITY.md`](FEASIBILITY.md) (Stage 0: can the models be obtained, loaded offline and called) and covers Stages 1 to 4. Every number below is read from a file in [`../eval/results/`](../eval/results/) written by a script in [`../eval/`](../eval/); [`../eval/README.md`](../eval/README.md) says how to rebuild the models dir and rerun each one.

**Everything here is synthetic.** The dictionary is invented terms with 99-prefixed placeholder codes, not MedDRA, and its groupings are not MedDRA's hierarchy. The notes, names, phone numbers and identifiers are invented. Nothing here says how the stack would do on a real MedDRA release or real site notes; it says how the shipped code behaves on a controlled, labeled test set built to probe the failure modes the decks talk about (colloquial, misspelled and negated verbatims; identifier look-alikes).

## Environment

Measured on 2026-10-22, on one cloud container:

| item | value |
|---|---|
| CPU | Intel Xeon Processor @ 2.80GHz, 4 vCPU, no GPU |
| RAM | 15 GB |
| OS | Linux 6.18 |
| Python | 3.12.3 |
| Needle3 | `cactus-needle` 3.2.8, engine `libneedle.so` 3.3.3 (SHA-256 `87476ff7…`), weights `needle3.cact` (SHA-256 `c9d915ec…`), 3072-dim embeddings |
| Laya | `laya` 0.4.13, English checkpoint `convaiinnovations/laya` at commit `55cf4c4e` (`model.safetensors` SHA-256 `891102d3…`), CPU |
| hnswlib | 0.8.0 (`M = 32`, `efConstruction = 200`, `efSearch = 64`, inner-product space) |
| XGBoost | `xgboost-cpu` 3.4.1 |
| torch / transformers | 2.14.1+cpu / 5.20.2 |

The apps ran air-gapped from the models dir (`HF_HUB_OFFLINE=1`, Needle3 telemetry off), exactly as a user would run them.

## Stage 1: Needle3 + hnswlib retrieval (coding Tier 2)

Script: [`eval/bench_index.py`](../eval/bench_index.py), output [`stage1_index.json`](../eval/results/stage1_index.json). It uses the app's own `t2_index` and the loaded Needle3 agent, so the index is built exactly as the app builds it (single-threaded insertion, so the graph is identical on every run). Queries are the 1,920 generated verbatims in `eval/data/coding_eval.csv`. Embed, HNSW search and the brute-force comparison are timed in separate passes (see the note below the table).

| dictionary | terms | embed per term (build) | build total | resident index | embed per verbatim, median / p90 | HNSW search (k = 10), median / p90 | exact brute force, median | recall@10 vs exact |
|---|---|---|---|---|---|---|---|---|
| demo, `sample_data/meddra_demo.csv` | 12 | 23.4 ms | 0.3 s | 0.14 MB | 27.6 / 39.4 ms | 0.009 / 0.011 ms | 0.007 ms | 1.000 |
| generated, `eval/data/dictionary.csv` | 3,371 | 26.0 ms | 87.6 s | 40.4 MB (39.5 MB vectors + 0.9 MB graph) | 26.5 / 38.5 ms | 0.47 / 0.65 ms | 0.59 ms | 0.993 |

**Index cost at a full release's size.** A MedDRA release has about 86,800 active lowest-level terms. Embedding that many term strings would take about 38 CPU-minutes at the measured 26 ms per term, so the index cost at that size was measured on 86,800 random unit vectors of Needle3's real width, with the same index settings:

| terms | dim | build (4 threads) | resident index | HNSW search, median / p90 |
|---|---|---|---|---|
| 86,800 | 3072 | 496 s | 1,040 MB (1,017 MB vectors + 23 MB graph) | 5.8 / 7.0 ms |

Random vectors have no cluster structure, which is the hard case for a graph index; their recall@10 (0.06 at `efSearch = 64`) says nothing about retrieval quality on real embeddings and is not a prediction of it. The app inserts single-threaded for a reproducible graph, so a first build at this size would take roughly four times the 4-thread figure, plus the embedding; both are paid once per dictionary release, because the app caches the embedded dictionary and the graph in the models dir (`index_cache/`).

**What this changes in the decks.**
- The vectors are **3072-dim**, not 384. At 3072 dims and float32, the vectors alone are 12 KB per term, so a full release is about 1 GB resident, not the 178 MB the decks had illustrated for 384 dims.
- Per verbatim, the cost is the **embedding** (about 26 ms median on this CPU), not the search: HNSW search is under 1 ms at 3,371 terms and about 6 ms at 86,800.
- At a few thousand terms, exact brute-force search costs about the same as HNSW (0.59 ms vs 0.47 ms) and is exact; the graph pays off at release scale.

*Measurement note.* A first run timed the brute-force matmul right after each embed call. Its idle BLAS threads then competed with Needle3's worker process for the 4 cores and inflated the embed median on the 3,371-term dictionary to 65 ms. The script now times the three operations in separate passes; the figures above are from that run. The 86,800-term figures come from the first run's scale phase, which is unaffected (it embeds nothing).
