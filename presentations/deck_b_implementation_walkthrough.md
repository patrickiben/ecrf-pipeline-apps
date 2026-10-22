# Implementation Walkthrough — eCRF cut, two traces

**Companion to [Deck A](deck_a_four_tier_pipeline.md) · QC'd build, October 2026.** Every `[SI]` number in this deck is the exact output of the shipped stand-in on [`../sample_data/`](../sample_data/) — run either app against that folder and you will reproduce these tables. See [QC_REPORT](../QC_REPORT.md) for what was verified.

> **About the `[RM]` numbers.** `[RM]` = measured output of the named model versions on the named hardware and date: Cactus Needle3 (`cactus-needle` 3.2.8, weights `needle3.cact` SHA-256 `c9d915ec…`), Laya 0.4.13 (English checkpoint `convaiinnovations/laya` at commit `55cf4c4e`, temperatures fitted on a synthetic calibration split) and XGBoost 3.4.1 (`xgboost-cpu`; the re-ranker and the span gate trained on synthetic data), run on an Intel Xeon @ 2.80GHz cloud CPU with 4 vCPU and no GPU, on 2026-10-22. They are what both apps wrote when run end to end on `sample_data/` with that models dir ([`eval/results/deck_b_worked.json`](../eval/results/deck_b_worked.json)); how the models dir was built, and the held-out evaluation behind it, are in [EVALUATION.md](../docs/EVALUATION.md). Every `[SI]` value is real output of the shipped stand-in. A number with neither tag is a configured parameter or dictionary content.

**Scenario.** Protocol PROTO-2026-X89. A cut is on disk as `ae.csv`, `pr.csv`, `eg.csv` plus the MedDRA release. Two programs read that folder. The coding program consumes `ae.csv`'s `AETERM` column and the dictionary; the PHI program scans every non-numeric column it finds across `ae`/`pr`/`eg` (content-based discovery). They read different columns of the same files, compute independently, and write separate outputs and separate audit sections. No scanned page, no bounding box, no dose-escalation logic anywhere in this build.

---

## Trace 1 — MedDRA auto-coding

### 1.0 The input on disk

`ae.csv` as DM delivers it. `AECOM` is present but is the PHI trace's column — the coding trace never reads it. The code columns are absent because deriving them is this trace's job.

| STUDYID | USUBJID | AESEQ | AETERM *(coding reads this)* | AESEV | AESER | AECOM *(PHI reads this)* |
|---|---|---|---|---|---|---|
| PROTO-2026-X89 | SUBJ-3092 | 1 | severe throbbing pain in back of head | SEVERE | Y | CRC Note: Patient Jane Miller called site cell phone (617) 555-0192 at 10:15 AM. |
| PROTO-2026-X89 | SUBJ-3092 | 2 | feeling lightheaded when standing up | MODERATE | N | Patient Jane Miller tolerating well; continued Alanine 50 mg; repeat glucose 120 mg/dL. |
| PROTO-2026-X89 | SUBJ-1044 | 3 | frequent watery bowel movements | MODERATE | N | Four episodes; no intervention required. |
| PROTO-2026-X89 | SUBJ-4110 | 4 | marked prolonged heart rhythm interval | MILD | N | Repeat ECG ordered; subject resting comfortably. |

Tier 2 indexes the MedDRA release assembled from the licensed ASCII conversions, the first artifact it needs on disk:

| file | columns | active rows |
|---|---|---|
| `llt.asc` | `llt_code` · `llt_name` · `pt_code` | ~86,800 |
| `pt.asc` | `pt_code` · `pt_name` · `hlt_code` · `soc_code` | ~25,700 |
| `hlt.asc` | `hlt_code` · `hlt_name` · `hlgt_code` | ~2,400 |
| `hlgt.asc` | `hlgt_code` · `hlgt_name` · `soc_code` | 136 |
| `soc.asc` | `soc_code` · `soc_name` | 27 |

merged on `currency = 'Y'`, joined LLT→PT on `pt_code`, PT→HLT on `hlt_code`, HLT→HLGT on `hlgt_code`, HLGT→SOC on `soc_code`; each term is indexed under `llt_name + "[PT: " + pt_name + "]"`. The full chain is LLT → PT → **HLT** → **HLGT** → SOC: related preferred terms are grouped into High Level Terms by anatomy, pathology, physiology, aetiology or function; related HLTs in turn link to High Level Group Terms; and HLGTs group into System Organ Classes (by aetiology, manifestation site or purpose).

### 1.1 · Tier 1 — eCRF intake

Keys `ae.csv` on `STUDYID/USUBJID/AESEQ`, copies `AETERM` through byte-for-byte, withholds `AECOM` from this trace. No columns added — the verbatim reaches Tier 2 exactly as typed, because Tier 2 measures closeness to what the site wrote. (The spatial/PDF front-end is not invoked: the input is tabular.)

### 1.2 · Tier 2 — Cactus Needle3: embed, index, retrieve

The verbatim, lower-cased (Needle3's embedding is case-sensitive), is encoded to a 3072-dim unit vector; because stored vectors are L2-normalized, the index's inner-product distance *is* cosine, so the cheap `ip` search returns exact angular closeness. The active term vectors sit in a layered HNSW graph; a query enters at the top entry point, follows `ip` links greedily while the score improves, steps down at each local maximum, and at layer 0 runs a bounded priority-queue search to return the top-K. Index parameters: `M = 32`, `efConstruction = 200`, `efSearch = 64`. Measured costs **[RM]**: embed 31 ms + search 0.5 ms per verbatim over a 3,371-term synthetic dictionary (index resident 40.4 MB, recall@10 0.994 against exact search). At a full release's ~86,800 terms, measured on random vectors of the same width (index cost only, not retrieval quality): search 5.8 ms, resident 1,040 MB (1,017 MB vectors + 23 MB graph). On the real path Tier 2 hands its top 10 to the re-ranker; the tables show the three exported after re-ranking.

Zoomed on AESEQ 1, `"severe throbbing pain in back of head"` — top-3 **[RM]** (each candidate carries its full hierarchy path):

| rank | LLT | PT | PT_CODE | HLT · HLGT | SOC | cosine [RM] |
|---|---|---|---|---|---|---|
| 1 | Throbbing pain in head | Headache | 99019211 | Cranial pain · Cranial and cerebral disorders | Nervous system disorders | 0.9629 |
| 2 | Pain in back of head | Headache | 99019211 | Cranial pain · Cranial and cerebral disorders | Nervous system disorders | 0.9605 |
| 3 | Electrocardiogram QT prolonged | Electrocardiogram QT prolonged | 99014387 | QT interval prolongation · Cardiac investigations | Investigations | 0.9326 |

Zoomed on AESEQ 2, `"feeling lightheaded when standing up"` — top-1 **[RM]**: `Lightheadedness → Dizziness postural (99013575)`, cosine 0.9582.

Ranks 1–2 of AESEQ 1 share a preferred term but are distinct lowest-level terms; the re-ranker resolves them to the same PT/code, so the write-back is unambiguous whichever LLT ranks first. Tier 2 has appended `LLT, PT, PT_CODE, SOC, cosine` and stopped — it proposes and measures, it decides nothing.

Needle3's cosines are compressed: every candidate in this trace, the unrelated QT term included, scores between 0.93 and 0.97. A cosine on its own separates little, and no fixed cosine cutoff carries over from one dictionary to another; ordering and gating are the re-ranker's job.

### 1.3 · Tier 3 — Laya: what it adds to a coding row

Tier 4 scores each candidate from a feature row built out of upstream columns, never out of the raw string:

```
x_k = [ cosine(Tier 2),
        LevenshteinSim(Tier 4) = 1 - EditDistance(s,m)/max(len s, len m),
        JaroWinkler(Tier 4),
        I(SOC match)(Tier 4),
        retrieval rank(Tier 2),
        + P(unambiguous)(Tier 3)   # real path only; the stand-in has no Tier-3 scalar
      ]
y_k = XGBoost(x_k)            # real: binary:logistic booster, 164 trees
                              # stand-in: fixed weights on the first four, summing to 1
```

Laya supplies `P(unambiguous)`: the probability that the verbatim reports one specific problem the participant actually had. That is what lets a row whose *term* matches well but whose *sentence* negates or blurs it be pushed below the gate. Measured **[RM]** on the four worked verbatims, all plain reports: 0.911 (AESEQ 1), 0.872 (AESEQ 2), 0.919 (AESEQ 3), 0.861 (AESEQ 4). On the held-out set it separates negated from plain verbatims only moderately (AUROC 0.74), and no negated verbatim was auto-coded there. The stand-in does not emit the scalar, so the `[SI]` trace runs its fixed-weight composite without it. Either way the gate is a single threshold on `y_k`.

### 1.4 · Tier 4 — XGBoost: re-rank and gate

The re-ranker is trained once (here on synthetic data) and is not re-derived per record, so the trace reports its score, not its trees. This run sets the gate to **0.90**; the build's slider default is 0.88. On the real path the trained re-ranker scores all four worked verbatims far below either value, so all four go to the human coding queue at 0.88 and at 0.90 alike, each with the right preferred term ranked first. That is the measured behavior for paraphrased verbatims: on the held-out set, colloquial verbatims reached the right term at rank 1 about half the time and none cleared the gate ([EVALUATION.md](../docs/EVALUATION.md), Stage 3).

| AESEQ | verbatim | top PT [RM] | PT_CODE | re-rank y_k [RM] | status @0.90 [RM] | stand-in top PT · score [SI] |
|---|---|---|---|---|---|---|
| 1 | severe throbbing pain in back of head | Headache | 99019211 | 0.1235 | FLAGGED_FOR_HUMAN_CODER | Headache · 0.7726 |
| 4 | marked prolonged heart rhythm interval | Electrocardiogram QT prolonged | 99014387 | 0.0901 | FLAGGED_FOR_HUMAN_CODER | Electrocardiogram QT prolonged · 0.4285 |
| 3 | frequent watery bowel movements | Diarrhoea | 99012735 | 0.0418 | FLAGGED_FOR_HUMAN_CODER | Diarrhoea · 0.4672 |
| 2 | feeling lightheaded when standing up | Dizziness postural | 99013575 | 0.0913 | FLAGGED_FOR_HUMAN_CODER | Headache (wrong) · 0.2972 |

The stand-in computes the same four lexical feature columns per candidate (cosine via hashed bag-of-words, Levenshtein-sim, Jaro-Winkler, SOC-match) and a fixed composite with Σw = 1. Its `[SI]` scores are on a different scale from the trained re-ranker's, so the two columns are not comparable number for number; at 0.90 the stand-in also flags all four. Where the real path does what a lexical matcher cannot is retrieval: it ranks `Dizziness postural` first for `"feeling lightheaded when standing up"`, which the stand-in codes as Headache, and `Electrocardiogram QT prolonged` first for `"marked prolonged heart rhythm interval"`. What it does not yet do is score those right answers high enough to auto-code them.

### 1.5 · Write-back and export

`ae_coded.csv` carries the top three candidates per verbatim. Rank 1 has status `AUTO_COMMIT_TO_SDTM` (the coded fields are committed) or `FLAGGED_FOR_HUMAN_CODER` (they are a proposal for the coder to accept or override); ranks 2–3 are `ALT_CANDIDATE`. Rank-1 rows written on the real path in this run **[RM]**:

| USUBJID | AESEQ | AETERM | AEDECOD | AEPTCD | AESOC | S | AECODSTAT |
|---|---|---|---|---|---|---|---|
| SUBJ-3092 | 1 | severe throbbing pain in back of head | Headache | 99019211 | Nervous system disorders | 0.1235 | FLAGGED_FOR_HUMAN_CODER |
| SUBJ-4110 | 4 | marked prolonged heart rhythm interval | Electrocardiogram QT prolonged | 99014387 | Investigations | 0.0901 | FLAGGED_FOR_HUMAN_CODER |
| SUBJ-1044 | 3 | frequent watery bowel movements | Diarrhoea | 99012735 | Gastrointestinal disorders | 0.0418 | FLAGGED_FOR_HUMAN_CODER |
| SUBJ-3092 | 2 | feeling lightheaded when standing up | Dizziness postural | 99013575 | Nervous system disorders | 0.0913 | FLAGGED_FOR_HUMAN_CODER |

`AECOM` is untouched in this file — scrubbing it is the PHI trace's output, a separate artifact. The exported rows also carry `HLT` and `HLGT` as **evidence columns** next to each candidate so a reviewer sees the full path (LLT → PT → HLT → HLGT → SOC) beside every proposal; they are not standard SDTM variables — the write-back fields remain `AEDECOD`/`AEPTCD`/`AESOC`, and Tier 4 never scores on the hierarchy levels.

### 1.6 · App tie-in (coding)

The MedDRA write-back screen renders 1.5 as an editable table: each `AUTO_COMMIT_TO_SDTM` row shows its top PT — with its HLT · HLGT · SOC path alongside — and score for accept; each `FLAGGED` row shows the pre-populated candidates for the coder to pick or override, and an override writes a reason to the audit. The reviewer sets the gate here (default 0.88) and the effective value goes into the audit with the run. The pre-flight panel prints the hierarchy chain the dictionary actually carries (`LLT > PT > HLT > HLGT > SOC`, or a degraded subset if the source lacked those levels), and that chain is written to the audit with every run.

---

## Trace 2 — PII/PHI detection and redaction

### 2.0 · The free-text on disk, across domains

These are the boxes a coordinator types into. The cut deliberately contains four cases: a direct leak, a look-alike trap, a mosaic, and a clean negative — all in eCRF fields, no page.

| DOMAIN | USUBJID | ROW | FIELD | free-text value as typed | case |
|---|---|---|---|---|---|
| AE | SUBJ-3092 | 1 | AECOM | CRC Note: Patient Jane Miller called site cell phone (617) 555-0192 at 10:15 AM. | direct |
| AE | SUBJ-3092 | 2 | AECOM | Patient Jane Miller tolerating well; continued Alanine 50 mg; repeat glucose 120 mg/dL. | look-alike |
| PR | SUBJ-3092 | 1 | PRDSC | Subject J.M. (MRN 884-019-22), DOB 04/12/1972, residing 02114, missed the 09:00 dose window. | mosaic + direct |
| EG | SUBJ-1044 | 1 | EGCOM | Sinus rhythm, no artifact. | clean |

The entity schema is the HIPAA safe-harbour set (Name, DOB, Phone, MRN, Address, …). Every non-numeric column in each domain is scanned — content-based discovery, not a hard-coded `AECOM` list or a name-suffix rule — which is what makes the scan both domain-agnostic and gap-free.

### 2.1 · Tier 1 — intake + content-based discovery

Discovery is **content-based**: every column that is *not* strictly numeric (text, dates, coded values, flags) is scanned; only columns typed as a number are skipped. A pre-specified list of column names was removed because it is guaranteed to miss PHI hiding in any column whose header did not match — and missing PHI is exactly the failure this program exists to prevent. Applied per domain on the sample cut:

| DOMAIN | columns scanned (every non-numeric column) | identifiers found |
|---|---|---|
| AE | STUDYID, USUBJID, AETERM, AESEV, AESER, AECOM | AECOM only |
| PR | STUDYID, USUBJID, PRDSC | PRDSC only |
| EG | STUDYID, USUBJID, EGCOM | none (clean) |

The operator confirms or deselects columns in the app's pre-flight before compute — so a known-safe structured column (a date you don't want touched) can be excluded interactively. A missing value stays missing, not an empty string that would scan silently clean. No page, no layout, no coordinate map — the input is tabular.

### 2.2 · Tier 2 — Cactus Needle3: typed span extraction

The extractor is schema-typed, not a regex library; the stand-in implements the declaration as explicit patterns, shown verbatim so a reviewer can audit exactly what matches — phone `\(?[0-9]{3}\)?[-. ]?[0-9]{3}[-. ]?[0-9]{4}`, MRN `\b[0-9]{3}-[0-9]{3}-[0-9]{2}\b`, DOB `\b[0-9]{2}/[0-9]{2}/[0-9]{4}\b`, postcode `(?<!\d)[0-9]{5}(?!\d)`, initials `\b[A-Z]\.[A-Z](?:\.(?=[^0-9a-zA-Z]|$))?`, and a patient name only when introduced by a title keyword (`Patient|Mr|Ms|Mrs|Dr`) or in surname-comma form. The title-keyword guard is what stops a bare capitalized clinical word from being read as a name. Spans carry in-field character offsets; there is no page and no bounding box.

The offsets below are the **exact output of the shipped stand-in** on `sample_data/` (verified 2026-10-13):

| DOMAIN | FIELD | ROW | span | entity | direct / indirect | in-field offset [SI] |
|---|---|---|---|---|---|---|
| AE | AECOM | 1 | Jane Miller | PERSON_NAME | direct | 18–29 |
| AE | AECOM | 1 | (617) 555-0192 | PHONE | direct | 53–67 |
| AE | AECOM | 2 | Jane Miller | PERSON_NAME | direct | 8–19 |
| AE | AECOM | 2 | *Alanine* | *(drug — no name match)* | **none** | — |
| AE | AECOM | 2 | *120 mg/dL* | *(lab — no MRN/DOB/ZIP match)* | **none** | — |
| PR | PRDSC | 1 | J.M. | INITIALS | indirect | 8–12 |
| PR | PRDSC | 1 | 884-019-22 | MRN | direct | 18–28 |
| PR | PRDSC | 1 | 04/12/1972 | DOB | direct | 35–45 |
| PR | PRDSC | 1 | 02114 | ZIP | indirect | 56–61 |
| EG | EGCOM | 1 | — | — | none | — |

The two italicised *none* rows are the look-alike test the typed schema exists to pass: a mid-sentence *Alanine* matches no name pattern (the title-keyword guard) and *120 mg/dL* matches no MRN/DOB/ZIP pattern, so both survive while the patient name beside them is flagged. The PR row mixes direct (MRN, DOB) and indirect (initials, postcode) attributes — that is the mosaic case Tier 3 must score.

On the real path Tier 2 is the union of Needle3's typed extraction and the same patterns; a range both proposed is marked `both`. Its proposals on these fields **[RM]**: Jane Miller and the phone on AE row 1, Jane Miller on AE row 2, and the PR row's initials, DOB and postcode were found by both; the PR row's MRN by the pattern alone. Needle3 also proposed four look-alikes the patterns do not: `10:15 AM` and `50` (from *Alanine 50 mg*) as dates of birth, `120` (from *120 mg/dL*) as a ZIP, and `Sinus rhythm` on the EG row as a person name. Tier 4 rejects all four (§2.4). Needle3's extraction alone is not a redactor: on the held-out set its precision was 0.42.

### 2.3 · Tier 3 — Laya: calibrated field-level probabilities

One non-generative pass per field returns the probability that direct identifiers are present and the probability that indirect attributes jointly re-identify. `P(Quasi)` is the joint re-identification probability over indirect attributes; it should rise only where two or more co-occur, which in this cut is the PR row alone.

| DOMAIN | FIELD | ROW | what the field holds | P(direct PHI) [RM] | P(quasi-ID) [RM] | P(direct) / P(quasi) [SI] |
|---|---|---|---|---|---|---|
| AE | AECOM | 1 | direct (name, phone) | 0.673 | 0.404 | 0.99 / none |
| AE | AECOM | 2 | direct (name) | 0.013 | 0.048 | 0.99 / none |
| PR | PRDSC | 1 | direct (MRN, DOB) + mosaic (initials, postcode) | 0.036 | 0.713 | 0.99 / 0.96 |
| EG | EGCOM | 1 | nothing | 0.012 | 0.086 | 0.05 / none |

The single-name rows keep `P(Quasi)` low because no indirect set co-occurs; the PR row raises it because initials and postcode appear together. That joint risk is a field-level judgement Tier 2 cannot produce — Tier 2 flagged the MRN and DOB as direct spans but said nothing about the *combination* of the indirect attributes, which is precisely Tier 3's output.

Measured, `P(Quasi)` behaves as designed. `P(direct)` does not: it is 0.67 on AE row 1 and close to zero on AE row 2 and the PR row, though all three hold direct identifiers. That matches the held-out evaluation, where Laya's direct-identifier answer was weak and biased low (AUROC 0.69). The redactions in §2.4 are right anyway, because the trained span gate leans on Tier 2's span evidence more than on `P(direct)`.

*(Stand-in note: the stand-in reports `P(direct) = 0.99` whenever a direct span exists and `P(quasi) = 0.96` when two or more indirect spans co-occur, none when there is no indirect span. The `[RM]` values are Laya's field-level answers, one per question, not per entity.)*

### 2.4 · Tier 4 — XGBoost: per-span redaction and scrub

Per span the head predicts a redaction probability from the Tier-2 span match, the two Tier-3 probabilities, and in-field cues (relative character position, digit ratio, capitalization, a preceding label word). The full per-token feature set also includes page geometry — bounding box and normalized vertical position — which the eCRF path has no page to supply, so in-field position and lexical cues stand in for it and the score reduces to the span-match and direct-identifier test: `P(Redact) = 0.99` when the token falls in a Needle3 span or the field's direct-identifier probability exceeds 0.8, else `0.01`; mask above the configured cutoff (default 0.85, a reviewer parameter). The scrub is a string replace on the field, shown as the exact operation so the result is reproducible:

```
SAN_AECOM = str_replace_all(AECOM, "(?i)Jane Miller", "[REDACTED_PATIENT_NAME]")
SAN_AECOM = str_replace_all(SAN_AECOM,
              "\\(?[0-9]{3}\\)?[-.]?[0-9]{3}[-.]?[0-9]{4}", "[REDACTED_PHONE]")
AEPHI     = if_else(SAN_AECOM != AECOM, "Y", "N")
```

The 0.99 / 0.01 rule above is the stand-in's. On the real path a trained XGBoost gate scores each Tier-2 candidate from 18 named features (which proposer found it, its entity type, `P(direct)`, `P(quasi)`, the number of indirect spans in the field, digit ratio, capitalization, relative position, length and a preceding label word) and masks above the same 0.85 cutoff.

| DOMAIN | FIELD | ROW | span | P(Redact) [RM] | P(Redact) [SI] | action | result |
|---|---|---|---|---|---|---|---|
| AE | AECOM | 1 | Jane Miller / (617) 555-0192 | 0.962 / 0.962 | 0.99 | scrub | `SAN_AECOM` |
| AE | AECOM | 1 | *10:15 AM* (Needle3: date of birth) | below 0.85 | — | **keep** | unchanged |
| AE | AECOM | 2 | Jane Miller | 0.949 | 0.99 | scrub | `SAN_AECOM` |
| AE | AECOM | 2 | *Alanine 50 mg* / *120 mg/dL* (Needle3: `50` DOB, `120` ZIP) | below 0.85 | 0.01 | **keep** | unchanged |
| PR | PRDSC | 1 | J.M. / 884-019-22 / 04/12/1972 / 02114 | 0.918 / 0.949 / 0.949 / 0.929 | 0.99 | scrub + mosaic flag | `SAN_PRDSC` |
| EG | EGCOM | 1 | *Sinus rhythm* (Needle3: person name) | below 0.85 | — | none | `AEPHI = "N"`, text unchanged |

Resulting sanitized field, AE row 1: `CRC Note: Patient [REDACTED_PATIENT_NAME] called site cell phone [REDACTED_PHONE] at 10:15 AM.`, with `AEPHI = "Y"`; AE row 2 keeps *Alanine 50 mg* and *120 mg/dL* intact while the patient name beside them is scrubbed. The tag vocabulary (`[REDACTED_PATIENT_NAME]`, `[REDACTED_PHONE]`, …) is a configuration choice and the audit records the scheme in force for the run. Because the input is a database field there is no manifest and no text-layer deletion — those belong to a page, which this build does not process.

### 2.5 · Exports (PHI)

Two artifacts, neither of which is the coding file. `phi_flags.csv`, one row per detected span (page and bounding-box columns do not appear, because the input is a field, not a page):

| DOMAIN | USUBJID | ROW | FIELD | SPAN | ENTITY | START | END | P_REDACT [RM] (stand-in: 0.99) | ACTION |
|---|---|---|---|---|---|---|---|---|---|
| AE | SUBJ-3092 | 1 | AECOM | Jane Miller | PERSON_NAME | 18 | 29 | 0.9624 | MASK_AND_FLAG |
| AE | SUBJ-3092 | 1 | AECOM | (617) 555-0192 | PHONE | 53 | 67 | 0.9618 | MASK_AND_FLAG |
| PR | SUBJ-3092 | 1 | PRDSC | 02114 | ZIP | 56 | 61 | 0.9293 | MASK_AND_FLAG |

and a sanitized copy of each scanned domain — `sanitized/ae.csv`, `sanitized/pr.csv`, `sanitized/eg.csv` — carrying the original columns plus `SAN_<field>` and `<field>_PHI_FLAG` per scanned column. The audit row for this trace records the selected-column list, the content-based discovery mode and the tag scheme in force, the redaction cutoff, the per-tier path (trained or stand-in) — so the privacy run is reproducible from its audit alone and shares no audit line with the coding run.

### 2.6 · App tie-in (PHI)

The PHI sanitization screen renders 2.4 as a raw-vs-sanitized inspector per row with an Approve-Redaction action that logs reviewer and time, and shows the 2.1 discovery table so a reviewer can confirm coverage before trusting the scrub. The reviewer confirms or deselects scan columns and sets the cutoff here; those effective choices go into the audit with the run. End users write no code.

---

## Trace legend (properties of this build)

- **[RM]** = measured output of the named model versions on the named hardware and date: Needle3 (`cactus-needle` 3.2.8), Laya 0.4.13 (`convaiinnovations/laya@55cf4c4e`, temperatures fitted on synthetic data) and XGBoost 3.4.1 gates trained on synthetic data, on an Intel Xeon @ 2.80GHz, 4 vCPU, no GPU, 2026-10-22 ([EVALUATION.md](../docs/EVALUATION.md)); **[SI]** = the deterministic stand-in's output on this record; untagged numbers = configured parameters (gate 0.90 in this run, default 0.88; redaction cutoff 0.85; index `M/efC/efS = 32/200/64`) or dictionary content.
- The stand-in reproduces the contract and the gates exactly. For PHI it reproduces the trace, because identifier detection is pattern-shaped and the eCRF scrub is a string replace — every `[SI]` offset in §2.2 was verified against a shipped run on 2026-10-13. For coding its retrieval is lexical, so its `[SI]` scores are not comparable with the `[RM]` column; with the models dir built by `eval/fetch_models.py` the same tables fill with `[RM]` numbers, columns unmoved, as they do in this deck.
- Two parameters are deployment decisions the audit records, not fixed constants: the coding gate (0.88 vs 0.90; on the real path no score in this cut or in the held-out set fell between them) and the redaction tag scheme. Both are reviewer-set in the app and written to the audit with the run.

## Verify this walkthrough yourself

Point either app at [`../sample_data/`](../sample_data/) (the worked cut plus a synthetic demo dictionary) and Execute: no code edits, no setup beyond `pip install -r requirements.txt`. The PHI trace reproduces the `[SI]` values in §2.2–§2.5 exactly; the coding trace runs both routing branches with honest `[SI]` scores. For the `[RM]` values, build a models dir as in [`../eval/README.md`](../eval/README.md), set it as **Models dir** in the sidebar and run again; `ECRF_MODELS_DIR=<models dir> python tests/qc_test.py` checks that the run reproduces them. What was checked, what bugs were found and fixed, and how to re-run the QC harness (`tests/qc_test.py`): [QC_REPORT.md](../QC_REPORT.md).
