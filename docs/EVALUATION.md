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

## The evaluation data (Stages 2 and 3)

Script: [`eval/make_data.py`](../eval/make_data.py) (seed 42; rerunning it reproduces `eval/data/` byte for byte).

- **Dictionary** (`dictionary.csv`): 3,371 lowest-level terms under 519 preferred terms, in the same shape as `sample_data/meddra_demo.csv`. It keeps the 12 demo rows and adds generated terms, about 6.5 lowest-level synonyms per preferred term: body-site pain, stiffness, tenderness, numbness and swelling; fractures, wounds and burns; lab values increased, decreased and abnormal; infections by organ; and common symptoms.
- **Coding set** (`coding_eval.csv`): 1,920 adverse-event verbatims, four per term: **exact** (a dictionary term as typed lower-case), **colloquial** ("calcium down on bloods", "forearm feels weak"), **misspelled** ("icute lower bakc pain", "palpitaitns") and **negated** ("denies nausea"). A negated verbatim has no correct auto-code: the right outcome is to send it to a human coder, so any auto-code of one counts as an error.
- **PHI set** (`phi_fields.csv`, `phi_spans.csv`): 880 free-text eCRF fields from 40 note templates, with 1,166 gold spans: 1,078 redaction targets (patient names, phones, emails, MRNs, dates of birth, ZIP codes, initials, ages) and 88 identifier-shaped spans that are **not** targets on their own (a lone initial or ZIP with no other indirect attribute beside it). The notes also carry look-alikes that are not identifiers at all: drug names, lab values, doses, times, kit and lot numbers.
- **Splits are grouped**, so the test split shares nothing with training: coding rows by preferred term (a test term never appears in training or calibration), PHI fields by note template. **train** fits the XGBoost gates (coding 1,152 verbatims; PHI 484 fields from 22 templates), **calib** fits the Laya temperatures and is the XGBoost early-stopping set (384 verbatims; 176 fields, 8 templates), **test** is reported and nothing is fitted on it (384 verbatims; 220 fields, 10 templates).

How the numbers are produced: [`eval/run_eval.py`](../eval/run_eval.py) loads each app's own tier functions from its file (everything above the UI marker, via `eval/_app.py`), so what is measured is the shipped code. It runs the stand-in path on the test split; builds the real Tier 2 and Tier 3 features on every split from a staging models dir that holds only the two checkpoints; fits the Laya temperatures on calib; trains the XGBoost gate on train; writes the artifacts into the models dir; **reloads the app from that models dir** and runs its real path on the test split. Those reloaded runs are the "real" columns below. The script asserts that the reloaded app's calibrated Tier-3 probabilities match the ones the gate was trained on (to 2e-3).

## Stage 2: Laya calibration

Laya answers each question with a two-option `noul` answer. The reported probability is the softmax of its logits divided by a temperature. The checkpoint ships a temperature of 1.98 for two-option `noul` answers; the script fits a new one on the calib split with Laya's own `records_from_labeled` and `fit_temperatures`, and reports calibration on the test split before (shipped temperature) and after (fitted). ECE is the expected calibration error over 10 equal-width bins of P(true); lower is better.

Laya fits a temperature per answer type and option count only from 2,000 records or more. The calib splits here are smaller (384 verbatims; 176 fields, so 352 PHI answers), so Laya fits its type-level `noul` temperature instead, and that is the value it then applies. One consequence: the two PHI questions share one fitted temperature.

| app · question | labeled as true when | temperature, shipped → fitted | test n | ECE before → after | Brier before → after | AUROC |
|---|---|---|---|---|---|---|
| coding · `unambiguous` | the verbatim is not negated | 1.98 → 1.45 | 384 | 0.119 → **0.084** | 0.173 → 0.172 | 0.736 |
<!-- PHI calibration rows -->

Temperature scaling changes how confident the probabilities are, not their order, so AUROC is the same before and after. On coding it moved ECE down by about 30%. The AUROC of 0.74 is the more important number: Laya's "one specific problem the participant actually had" answer separates negated from plain verbatims only moderately. It is the re-ranker, using that answer together with the retrieval features, that keeps negated verbatims below the gate (next section).

## Stage 3: coding, stand-in vs real

Test split: 384 verbatims (96 each exact, colloquial, misspelled, negated), coded against the 3,371-term dictionary. **Top-1 / top-3** are measured on the 288 verbatims that have a correct code (not negated): the gold preferred term is the rank-1 candidate, or among the three exported. **Auto-code rate** is the share of all 384 whose rank-1 score clears the gate. **Error rate** is the share of auto-coded verbatims that are wrong: a wrong preferred term, or a negated verbatim auto-coded at all.

| path | top-1 | top-3 | gate | auto-code rate | error rate of auto-codes | errors per 100 verbatims | negated verbatims auto-coded |
|---|---|---|---|---|---|---|---|
| stand-in `[SI]` | 0.542 | 0.615 | 0.88 | 25.5% | 7.1% | 1.8 | 7 of 96 |
| stand-in `[SI]` | 0.542 | 0.615 | 0.90 | 24.0% | 1.1% | 0.3 | 1 of 96 |
| real | **0.778** | **0.854** | 0.88 | **38.0%** | **0.0%** | 0.0 | 0 of 96 |
| real | **0.778** | **0.854** | 0.90 | **38.0%** | **0.0%** | 0.0 | 0 of 96 |

By variant (top-1; auto-code rate at 0.90):

| variant | stand-in top-1 | real top-1 | stand-in auto | real auto |
|---|---|---|---|---|
| exact | 0.979 | 1.000 | 90.6% | 100% |
| misspelled | 0.188 | 0.813 | 4.2% | 52.1% |
| colloquial | 0.458 | 0.521 | 0% | 0% |
| negated | (no correct code) | (no correct code) | 1.0% | 0% |

Ablations, real path (top-1 / top-3, same 288 verbatims):

| what runs | top-1 | top-3 |
|---|---|---|
| Needle3 cosine order only, no re-ranker | 0.747 | 0.885 |
| the same, but with terms and verbatims embedded **as typed** (no lower-casing) | 0.622 | 0.729 |
| full real path (Needle3 top 10, re-ranked by the trained XGBoost) | 0.778 | 0.854 |

What this shows:

- **The real path is better, mainly on misspellings.** Needle3 retrieval recovers most misspelled verbatims (0.81 top-1, against 0.19 for the lexical stand-in), and the re-ranker auto-codes half of them with no error. Exact matches are all auto-coded.
- **Colloquial verbatims are not solved.** Top-1 is 0.52, little better than the stand-in's 0.46, and none clear the gate, so all go to a human coder (correctly routed, but not automated). The misses are mostly lab-direction phrases: "calcium down on bloods" retrieves "Blood calcium increased" above "decreased". Needle3's embedding does not separate the direction words.
- **No negated verbatim was auto-coded on the real path,** at either gate; the highest-scoring one reached 0.73. The stand-in auto-coded 7 at 0.88.
- **The gate value does not matter on the real path here.** The trained re-ranker's scores are bimodal: none of the 384 fall between 0.88 and 0.90 (134 are above 0.95, the rest mostly below 0.5). On these data, 0.88 and 0.90 give identical results; on the stand-in, the 0.02 difference moved 6 negated verbatims across the gate.
- **The re-ranker lowers top-3.** It raises top-1 over plain cosine order (0.747 to 0.778) but lowers top-3 (0.885 to 0.854). It ranks lowest-level terms, and several terms under the same preferred term often take the top three places (2.5 distinct preferred terms per verbatim on average), which crowds the right one out of the exported three. Keeping the best term per preferred term would change what the coder queue shows (Deck B shows two terms of one preferred term on purpose), so this build leaves it and reports it.
- **Case matters for Needle3.** Its embedding is case-sensitive: "insomnia" scores 0.948 against "Insomnia", below several unrelated terms. Dictionary terms are capitalized and verbatims usually are not; on retrieval alone, embedding the strings as typed costs 0.125 top-1 (0.622 against 0.747). The first real run had this defect; the app now embeds a lower-cased copy of both sides, like its stand-in and its string features already did.
- **This is a synthetic dictionary of 3,371 terms**, not a 86,800-term MedDRA release with its far denser neighborhoods. Accuracy at release scale was not measured and should be expected to be lower.

Cost on this CPU: the real path coded the 384 test verbatims in 86 s (about 225 ms per verbatim end to end, with Tier 3 batched); the stand-in took 2.5 s.

<!-- PHI results -->
