# Evaluation: the real model path, measured

This file reports what the coding and PHI apps do on their **real** model path (open-source Cactus Needle3, hnswlib, Laya and XGBoost), measured on this repository's synthetic data. It follows [`FEASIBILITY.md`](FEASIBILITY.md) (Stage 0: can the models be obtained, loaded offline and called) and covers Stages 1 to 4. The headline metrics below are read from files in [`../eval/results/`](../eval/results/) written by scripts in [`../eval/`](../eval/); the per-format breakdowns of leaks and false positives, the mean P(direct) and the case-sensitivity example are recorded only in this report (no script writes them to a results file); [`../eval/README.md`](../eval/README.md) says how to rebuild the models dir and rerun each one. The same results, failures first, are on the published [evaluation case study](https://patrickiben.github.io/ecrf-pipeline-apps/evaluation.html) (`docs/evaluation.html`); the worked examples are in the [case study](https://patrickiben.github.io/ecrf-pipeline-apps/case-study.html) (`docs/case-study.html`), which replaced the two retired decks.

**Everything here is synthetic.** The dictionary is invented terms with 99-prefixed placeholder codes, not MedDRA, and its groupings are not MedDRA's hierarchy. The notes, names, phone numbers and identifiers are invented. Nothing here says how the stack would do on a real MedDRA release or real site notes; it says how the shipped code behaves on a controlled, labeled test set built to probe the failure modes the design is meant to handle (colloquial, misspelled and negated verbatims; identifier look-alikes).

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
| demo, `sample_data/meddra_demo.csv` | 12 | 22.8 ms | 0.3 s | 0.14 MB | 31.6 / 47.0 ms | 0.009 / 0.012 ms | 0.007 ms | 1.000 |
| generated, `eval/data/dictionary.csv` | 3,371 | 28.1 ms | 94.7 s | 40.4 MB (39.5 MB vectors + 0.9 MB graph) | 30.9 / 44.1 ms | 0.54 / 0.88 ms | 0.60 ms | 0.994 |

**Index cost at a full release's size.** A MedDRA release has about 86,800 active lowest-level terms. Embedding that many term strings would take about 40 minutes at the measured 28 ms per term, so the index cost at that size was measured on 86,800 random unit vectors of Needle3's real width, with the same index settings:

| terms | dim | build (4 threads) | resident index | HNSW search, median / p90 |
|---|---|---|---|---|
| 86,800 | 3072 | 496 s | 1,040 MB (1,017 MB vectors + 23 MB graph) | 5.8 / 7.0 ms |

Random vectors have no cluster structure, which is the hard case for a graph index; their recall@10 (0.06 at `efSearch = 64`) says nothing about retrieval quality on real embeddings and is not a prediction of it. The app inserts single-threaded for a reproducible graph, so a first build at this size would take roughly four times the 4-thread figure, plus the embedding; both are paid once per dictionary release, because the app caches the embedded dictionary and the graph in the models dir (`index_cache/`).

**What this changed in the original design.**
- The vectors are **3072-dim**, not 384. At 3072 dims and float32, the vectors alone are 12 KB per term, so a full release is about 1 GB resident, not the 178 MB an earlier version of Deck A had illustrated for 384 dims (corrected on 2026-10-22, before the deck was retired).
- Per verbatim, the cost is the **embedding** (about 30 ms median on this CPU), not the search: HNSW search is under 1 ms at 3,371 terms and about 6 ms at 86,800.
- At a few thousand terms, exact brute-force search costs about the same as HNSW (0.60 ms vs 0.54 ms) and is exact; the graph pays off at release scale.

*Measurement notes.* A first run timed the brute-force matmul right after each embed call. Its idle BLAS threads then competed with Needle3's worker process for the 4 cores and inflated the embed median on the 3,371-term dictionary to 65 ms. The script now times the three operations in separate passes. The table is from the last run, after the app began lower-casing what it embeds (Stage 3); an earlier run of the same script on the same machine gave a 26.5 ms embed median, so treat the embed figures as about ±15% run to run on a shared cloud CPU. The 86,800-term figures come from the first run's scale phase, which embeds nothing and is unaffected by either change.

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
| PHI · `direct_pii` | the field holds a direct identifier | 1.98 → 1.36 (shared) | 220 | 0.445 → **0.485** (worse) | 0.411 → 0.467 | 0.686 |
| PHI · `reident_risk` | the field holds two or more indirect attributes | 1.98 → 1.36 (shared) | 220 | 0.154 → **0.093** | 0.045 → 0.031 | 0.998 |

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
- **The re-ranker lowers top-3.** It raises top-1 over plain cosine order (0.747 to 0.778) but lowers top-3 (0.885 to 0.854). It ranks lowest-level terms, and several terms under the same preferred term often take the top three places (2.5 distinct preferred terms per verbatim on average), which crowds the right one out of the exported three. Keeping the best term per preferred term would change what the coder queue shows (the case study's first worked example shows two terms of one preferred term), so this build leaves it and reports it.
- **Case matters for Needle3.** Its embedding is case-sensitive: "insomnia" scores 0.948 against "Insomnia", below several unrelated terms. Dictionary terms are capitalized and verbatims usually are not; on retrieval alone, embedding the strings as typed costs 0.125 top-1 (0.622 against 0.747). The first real run had this defect; the app now embeds a lower-cased copy of both sides, like its stand-in and its string features already did.
- **This is a synthetic dictionary of 3,371 terms**, not a 86,800-term MedDRA release with its far denser neighborhoods. Accuracy at release scale was not measured and should be expected to be lower.

Cost on this CPU: the real path coded the 384 test verbatims in 86 s (about 225 ms per verbatim end to end, with Tier 3 batched); the stand-in took 2.5 s.

## Stage 3: PHI, stand-in vs real

Test split: 220 fields from 10 note templates never seen in training, holding 308 redaction targets. A predicted redaction counts as correct only on a **strict match**: same field, same start and end offset, same entity type. **Leaked** counts the gold targets with no overlapping redaction of any type, so they stay readable in the sanitized output; that is the number that matters for privacy, and it forgives a boundary or type slip that the strict scores do not.

| entity | gold | stand-in P / R / F1 | real P / R / F1 | Needle3 extraction alone P / R |
|---|---|---|---|---|
| PERSON_NAME | 66 | 1.00 / 0.33 / 0.50 | 0.94 / **0.74** / **0.83** | 0.45 / 0.70 |
| PHONE | 44 | 1.00 / 0.50 / 0.67 | 0.92 / 0.50 / 0.65 | 0.30 / 0.55 |
| EMAIL | 22 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 0.95 / 0.86 |
| MRN | 44 | 1.00 / 0.50 / 0.67 | 1.00 / 0.50 / 0.67 | 0.00 / 0.00 |
| DOB | 44 | 1.00 / 0.55 / 0.71 | 0.92 / 0.55 / 0.69 | 0.31 / 0.34 |
| ZIP | 22 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 0.21 / 0.55 |
| INITIALS | 44 | 1.00 / 1.00 / 1.00 | 0.91 / 0.89 / 0.90 | 0.60 / 0.64 |
| AGE | 22 | 1.00 / 1.00 / 1.00 | 1.00 / 0.73 / 0.84 | 0.69 / 1.00 |
| **all** | **308** | **1.00 / 0.65 / 0.79** | **0.95 / 0.70 / 0.81** | 0.42 / 0.54 |
| **leaked targets** (of 308) | | 108 (all direct identifiers) | **91** (80 direct, 11 indirect) | |

"Needle3 extraction alone" uses Needle3's grounded values directly as redactions, with no patterns and no gate: it shows what the extractor contributes on its own.

What this shows:

- **The real path finds more names.** Needle3 proposes names that have no title before them ("Spoke with Linda Miller", "Reached David Quinn"), which the stand-in's patterns require, and the trained gate keeps most of them: name recall goes from 0.33 to 0.74 at 0.94 precision.
- **It leaks less, but still leaks 91 of 308.** The leaks are formats that neither proposer covers: 8-digit MRNs ("MRN: 21428912", 22 leaked), 7-digit phone numbers ("555-0185", 22), dates of birth written M/D/YYYY ("9/13/1940", 19) and the untitled names Needle3 missed (17). None of Needle3's 5 MRN proposals was right. The stand-in leaks the same formats plus most untitled names.
- **It is not clean on look-alikes.** Of the 11 false positives, 3 are drug names passed as patient names ("Alanine" twice, "Levothyroxine", all in one template), 2 are doses passed as phone numbers ("20 mg prescribed", "100 mg"), 2 are bare years passed as dates of birth, 1 is an MRN typed as initials, and 3 are boundary slips on initials (Needle3 returned "H.K. enrolled at the north site" for "H.K."). The stand-in had no false positive here, because its patterns are narrow.
- **It lost some indirect attributes the stand-in kept**: age recall 1.00 to 0.73 and initials 1.00 to 0.89. The stand-in redacts any indirect attribute when two co-occur; the trained gate learned a softer rule and rejected some.
- **Laya's direct-identifier answer is weak.** P(direct) has an AUROC of 0.69 and is biased low: fields that do hold a direct identifier get a mean P(direct) of 0.24. A temperature cannot fix a bias, and the temperature it shares with the indirect question made its ECE slightly worse. The indirect question works well (AUROC 0.998, ECE 0.093), but on templated synthetic notes that is an easy task. The gate leans on the span features, not on P(direct).

Cost on this CPU: the real path processed the 220 test fields in 279 s (1.3 s per field, with Tier 3 batched); the stand-in took under 0.1 s.

## Per-record latency

Script: [`eval/deck_b_worked.py`](../eval/deck_b_worked.py), output `per_record_ms` in [`deck_b_worked.json`](../eval/results/deck_b_worked.json). One record at a time through each real tier (the apps' own functions, single-record calls, 25 timed calls after a warm-up), on the worked rows (the case study's examples, first written for the retired Deck B) and the 12-term demo dictionary:

| app | Tier 2 | Tier 3 (Laya, one call) | Tier 4 (XGBoost, incl. features) | per record |
|---|---|---|---|---|
| coding (4 verbatims) | Needle3 embed + search: 40 to 48 ms | 328 to 346 ms (1 question) | 7 to 9 ms | **about 390 ms** |
| PHI (4 fields) | Needle3 extraction + patterns: 434 to 1,077 ms | 449 to 523 ms (2 questions) | under 1 ms | **about 0.9 to 1.6 s** |

Medians; ranges are across the four records. Laya dominates coding, and Needle3's generative extraction dominates PHI. Batching Tier 3, as the apps do over a whole cut, roughly halves its per-record cost (coding: 225 ms per verbatim end to end on the test split). None of this is near the "sub-50 ms target / sub-100 ms ceiling" an earlier version of Deck A stated; on this 4-vCPU CPU the real path is a batch job, not an interactive one.

## Stage 4: the worked examples on the real path

Script: [`eval/deck_b_worked.py`](../eval/deck_b_worked.py), output [`deck_b_worked.json`](../eval/results/deck_b_worked.json). It drives both apps end to end with Streamlit's AppTest on `sample_data/` and the models dir, exactly as a user would (coding gate 0.90, the worked run's setting), and reads their written outputs. The `RM` checks in `tests/qc_test.py` assert that a real-path run reproduces these values.

**Coding.** All four worked verbatims get the right preferred term at rank 1 on the real path, and **all four are routed to a human coder**: the trained re-ranker scores them 0.04 to 0.12. That matches the held-out result for colloquial verbatims (top-1 0.52, none auto-coded). These four are paraphrases ("feeling lightheaded when standing up"), the re-ranker was trained on a dictionary where most correct matches are lexically close, and its score on a semantically right but lexically distant candidate stays low. The illustrative scores in an earlier version of Deck B (0.958, 0.971, 0.934, 0.882), its "three auto-code, one flags" routing and its "0.8820 row separates 0.88 from 0.90" story were not reproduced; the case study shows the measured values.

**PHI.** The real path redacts every target in the three worked fields, at P(redact) 0.92 to 0.96, and keeps both look-alikes: Needle3 proposed "50" (from "Alanine 50 mg") as a date of birth and "120" (from "120 mg/dL") as a ZIP, and the gate rejected both, so the sanitized text matches the stand-in's. In the clean EG field Needle3 proposed "Sinus rhythm" as a person name, and the gate rejected that too. Laya's field probabilities are where an earlier version of Deck B's illustrative numbers failed most: P(direct) is 0.67 on AE row 1 and 0.01 on AE row 2 and the PR row, though all three hold direct identifiers (that earlier version had 0.998; the deck was corrected on 2026-10-22, before it was retired). The redactions are right anyway because the gate leans on the span evidence.

## What ran for real, and what did not

Ran for real, measured here: Needle3 embeddings and the hnswlib index (Stage 1); Laya on both apps' questions, with temperatures fitted (Stage 2); the XGBoost re-ranker and span gate, trained on synthetic train splits (Stage 3); both apps end to end on the real path, air-gapped from the models dir (Stage 4).

Not measured, or still illustrative:

- **Real MedDRA and real site notes.** Everything is synthetic. Accuracy on a licensed release or on real notes is unknown and should be expected to be lower; the dictionary here is 3,371 terms, a release about 86,800.
- **Retrieval quality at release scale.** The 86,800-term figures are index cost on random vectors only.
- **The risk and anomaly apps** have no trained model path. They run their labeled stand-ins (and, in the anomaly app, the optional scikit-learn and POT detectors); a trained-model file in their models dir stops the run instead of being half-loaded.
- **Index costs at full scale** are the measured random-vector figures, labeled as such. The HLT and HLGT names, the gates and every `[SI]` value are configuration or stand-in output, unchanged.
- **Laya's per-question temperatures.** With fewer than 2,000 labeled answers, Laya fits one temperature per answer type, so the PHI questions share one. A larger labeled set would let it fit separate ones.
