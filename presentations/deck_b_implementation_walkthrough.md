# Implementation Walkthrough — eCRF cut, two traces

**Companion to [Deck A](deck_a_four_tier_pipeline.md) · QC'd build, October 2026.** Every `[SI]` number in this deck is the exact output of the shipped stand-in on [`../sample_data/`](../sample_data/) — run either app against that folder and you will reproduce these tables. See [QC_REPORT](../QC_REPORT.md) for what was verified.

> **About the `[RM]` numbers.** No trained checkpoint was run for this deck. Every value tagged `[RM]`, and the index costs in §1.2, are illustrative of what a trained Needle3 + Laya + XGBoost stack would emit; they are not measurements. Every `[SI]` value is real output of the shipped stand-in.

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

The verbatim is encoded to a 384-dim unit vector; because stored vectors are L2-normalized, the index's inner-product distance *is* cosine, so the cheap `ip` search returns exact angular closeness. The ~85,000 active term vectors sit in a 3-layer HNSW skip-list; a query enters at the top entry point, follows `ip` links greedily while the score improves, steps down at each local maximum, and at layer 0 runs a bounded priority-queue search to return the top-K. Illustrative index parameters and costs for the full model stack (not measured; the stand-in build in this repository does not produce them): `M = 32`, `efConstruction = 200`, `efSearch = 64`; embed 2.4 ms + search 0.8 ms; resident 178.3 MB (133.3 MB vectors + 45.0 MB edges).

Zoomed on AESEQ 1, `"severe throbbing pain in back of head"` — top-3 **[RM]** (each candidate carries its full hierarchy path):

| rank | LLT | PT | PT_CODE | HLT · HLGT | SOC | cosine [RM] |
|---|---|---|---|---|---|---|
| 1 | Pain in back of head | Headache | 99019211 | Cranial pain · Cranial and cerebral disorders | Nervous system disorders | 0.9412 |
| 2 | Throbbing pain in head | Headache | 99019211 | Cranial pain · Cranial and cerebral disorders | Nervous system disorders | 0.8920 |
| 3 | Migraine | Migraine | 99027599 | Cranial pain · Cranial and cerebral disorders | Nervous system disorders | 0.8105 |

Zoomed on AESEQ 2, `"feeling lightheaded when standing up"` — top-1 **[RM]**: `Postural dizziness → Dizziness postural (99013575)`, cosine 0.8910.

Ranks 1–2 of AESEQ 1 share a preferred term but are distinct lowest-level terms; the re-ranker resolves them to the same PT/code, so the write-back is unambiguous whichever LLT ranks first. Tier 2 has appended `LLT, PT, PT_CODE, SOC, cosine` and stopped — it proposes and measures, it decides nothing.

### 1.3 · Tier 3 — Laya: what it adds to a coding row

Tier 4 scores each candidate from a feature row built out of upstream columns, never out of the raw string:

```
x_k = [ cosine(Tier 2),
        LevenshteinSim(Tier 4) = 1 - EditDistance(s,m)/max(len s, len m),
        JaroWinkler(Tier 4),
        I(SOC match)(Tier 4),
        + ambiguity(Tier 3)   # present only when the trained checkpoint is installed
      ]
y_k = XGBoost(x_k)            # learned weights, sum to 1
```

The trained Tier-3 checkpoint supplies the `ambiguity` scalar — the probability the verbatim maps to a single clean concept — which is what lets a row whose *term* matches well but whose *sentence* negates or blurs it be pushed below the gate. This build's deterministic stand-in does not emit that scalar on coding rows, so the `[SI]` trace runs the re-ranker without it; the `[RM]` trace reports the trained re-ranker's output score, whose internal features are not exposed per record. Either way the gate is a single threshold on `y_k`.

### 1.4 · Tier 4 — XGBoost: re-rank and gate

The composite weights are learned at training time and are not re-derived per record, so the trace reports the resulting score, not the weights. This run sets the gate to **0.90** so both branches are exercised; the build's slider default is 0.88, at which the 0.8820 candidate below would also auto-code — the gate is a deployment operating point, recorded in the audit, and AESEQ 2 is the row that discriminates between the two values.

| AESEQ | verbatim | top PT | PT_CODE | re-rank y_k [RM] | status @0.90 |
|---|---|---|---|---|---|
| 1 | severe throbbing pain in back of head | Headache | 99019211 | 0.9580 | AUTO_CODED |
| 4 | marked prolonged heart rhythm interval | Electrocardiogram QT prolonged | 99014387 | 0.9710 | AUTO_CODED |
| 3 | frequent watery bowel movements | Diarrhoea | 99012735 | 0.9340 | AUTO_CODED |
| 2 | feeling lightheaded when standing up | Dizziness postural | 99013575 | 0.8820 | FLAGGED_FOR_HUMAN_CODER |

The stand-in computes the same four feature columns per candidate (cosine via hashed bag-of-words, Levenshtein-sim, Jaro-Winkler, SOC-match) and a weighted composite with Σw = 1; its scores are `[SI]` and will not match the `[RM]` column on semantically-gapped verbatims — `"marked prolonged heart rhythm interval" → QT prolonged` needs the trained encoder, which a lexical stand-in cannot supply.

### 1.5 · Write-back and export

On `AUTO_CODED` the head writes the coded fields onto the AE row; on `FLAGGED_FOR_HUMAN_CODER` it writes the same columns, leaves `AEDECOD` empty, and attaches the top candidates for the human queue. Exported `ae_coded.csv`:

| USUBJID | AESEQ | AETERM | AEDECOD | AEPTCD | AESOC | AECODCONF | AECODSTAT |
|---|---|---|---|---|---|---|---|
| SUBJ-3092 | 1 | severe throbbing pain in back of head | Headache | 99019211 | Nervous system disorders | 0.9580 | AUTO_CODED |
| SUBJ-4110 | 4 | marked prolonged heart rhythm interval | Electrocardiogram QT prolonged | 99014387 | Investigations | 0.9710 | AUTO_CODED |
| SUBJ-1044 | 3 | frequent watery bowel movements | Diarrhoea | 99012735 | Gastrointestinal disorders | 0.9340 | AUTO_CODED |
| SUBJ-3092 | 2 | feeling lightheaded when standing up | *(empty)* | — | — | 0.8820 | FLAGGED_FOR_HUMAN_CODER |

`AECOM` is untouched in this file — scrubbing it is the PHI trace's output, a separate artifact. The exported rows also carry `HLT` and `HLGT` as **evidence columns** next to each candidate so a reviewer sees the full path (LLT → PT → HLT → HLGT → SOC) beside every proposal; they are not standard SDTM variables — the write-back fields remain `AEDECOD`/`AEPTCD`/`AESOC`, and Tier 4 never scores on the hierarchy levels.

### 1.6 · App tie-in (coding)

The MedDRA write-back screen renders 1.5 as an editable table: each `AUTO_CODED` row shows its top PT — with its HLT · HLGT · SOC path alongside — and score for accept; each `FLAGGED` row shows the pre-populated candidates for the coder to pick or override, and an override writes a reason to the audit. The reviewer sets the gate here (default 0.88) and the effective value goes into the audit with the run. The pre-flight panel prints the hierarchy chain the dictionary actually carries (`LLT > PT > HLT > HLGT > SOC`, or a degraded subset if the source lacked those levels), and that chain is written to the audit with every run.

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

### 2.3 · Tier 3 — Laya: calibrated field-level probabilities

One non-generative pass per field returns the probability that direct identifiers are present, the probability that indirect attributes jointly re-identify, and a risk tier. `P(Quasi)` is the joint re-identification probability over indirect attributes; it rises only where two or more co-occur, which in this cut is the PR row alone.

| DOMAIN | FIELD | ROW | P(direct PHI) | P(quasi-ID) | risk tier |
|---|---|---|---|---|---|
| AE | AECOM | 1 | 0.998 (Name) / 0.995 (Phone) [RM] | low [SI] | high (direct) |
| AE | AECOM | 2 | 0.998 [RM] | low [SI] | high (direct) |
| PR | PRDSC | 1 | high [SI] | 0.96 [SI: ≥2 indirect spans] | high (direct + mosaic) |
| EG | EGCOM | 1 | 0.05 [RM] | low [SI] | none |

The single-name rows keep `P(Quasi)` low because no indirect set co-occurs; the PR row raises it because initials and postcode appear together. That joint risk is a field-level judgement Tier 2 cannot produce — Tier 2 flagged the MRN and DOB as direct spans but said nothing about the *combination* of the indirect attributes, which is precisely Tier 3's output.

*(Stand-in note: on the shipped build the direct branch reports `P(direct) = 0.99` whenever a DIRECT span exists — the `[RM]` values above are the trained checkpoint's per-entity outputs and are not exposed by the stand-in.)*

### 2.4 · Tier 4 — XGBoost: per-span redaction and scrub

Per span the head predicts a redaction probability from the Tier-2 span match, the two Tier-3 probabilities, and in-field cues (relative character position, digit ratio, capitalization, a preceding label word). The full per-token feature set also includes page geometry — bounding box and normalized vertical position — which the eCRF path has no page to supply, so in-field position and lexical cues stand in for it and the score reduces to the span-match and direct-identifier test: `P(Redact) = 0.99` when the token falls in a Needle3 span or the field's direct-identifier probability exceeds 0.8, else `0.01`; mask above the configured cutoff (default 0.85, a reviewer parameter). The scrub is a string replace on the field, shown as the exact operation so the result is reproducible:

```
SAN_AECOM = str_replace_all(AECOM, "(?i)Jane Miller", "[REDACTED_PATIENT_NAME]")
SAN_AECOM = str_replace_all(SAN_AECOM,
              "\\(?[0-9]{3}\\)?[-.]?[0-9]{3}[-.]?[0-9]{4}", "[REDACTED_PHONE]")
AEPHI     = if_else(SAN_AECOM != AECOM, "Y", "N")
```

| DOMAIN | FIELD | ROW | span | P(Redact) | action | result |
|---|---|---|---|---|---|---|
| AE | AECOM | 1 | Jane Miller / (617) 555-0192 | 0.99 | scrub | `SAN_AECOM` |
| AE | AECOM | 2 | Jane Miller | 0.99 | scrub | `SAN_AECOM` |
| AE | AECOM | 2 | *Alanine* / *120 mg/dL* | 0.01 | **keep** | unchanged |
| PR | PRDSC | 1 | J.M. / 884-019-22 / 04/12/1972 / 02114 | 0.99 | scrub + mosaic flag | `SAN_PRDSC` |
| EG | EGCOM | 1 | — | — | none | `AEPHI = "N"`, text unchanged |

Resulting sanitized field, AE row 1: `CRC Note: Patient [REDACTED_PATIENT_NAME] called site cell phone [REDACTED_PHONE] at 10:15 AM.`, with `AEPHI = "Y"`; AE row 2 keeps *Alanine 50 mg* and *120 mg/dL* intact while the patient name beside them is scrubbed. The tag vocabulary (`[REDACTED_PATIENT_NAME]`, `[REDACTED_PHONE]`, …) is a configuration choice and the audit records the scheme in force for the run. Because the input is a database field there is no manifest and no text-layer deletion — those belong to a page, which this build does not process.

### 2.5 · Exports (PHI)

Two artifacts, neither of which is the coding file. `phi_flags.csv`, one row per detected span (page and bounding-box columns do not appear, because the input is a field, not a page):

| DOMAIN | USUBJID | ROW | FIELD | SPAN | ENTITY | START | END | P_REDACT | ACTION |
|---|---|---|---|---|---|---|---|---|---|
| AE | SUBJ-3092 | 1 | AECOM | Jane Miller | PERSON_NAME | 18 | 29 | 0.99 | MASK_AND_FLAG |
| AE | SUBJ-3092 | 1 | AECOM | (617) 555-0192 | PHONE | 53 | 67 | 0.99 | MASK_AND_FLAG |
| PR | SUBJ-3092 | 1 | PRDSC | 02114 | ZIP | 56 | 61 | 0.99 | MASK_AND_FLAG |

and a sanitized copy of each scanned domain — `sanitized/ae.csv`, `sanitized/pr.csv`, `sanitized/eg.csv` — carrying the original columns plus `SAN_<field>` and `<field>_PHI_FLAG` per scanned column. The audit row for this trace records the selected-column list, the content-based discovery mode and the tag scheme in force, the redaction cutoff, the per-tier path (trained or stand-in) — so the privacy run is reproducible from its audit alone and shares no audit line with the coding run.

### 2.6 · App tie-in (PHI)

The PHI sanitization screen renders 2.4 as a raw-vs-sanitized inspector per row with an Approve-Redaction action that logs reviewer and time, and shows the 2.1 discovery table so a reviewer can confirm coverage before trusting the scrub. The reviewer confirms or deselects scan columns and sets the cutoff here; those effective choices go into the audit with the run. End users write no code.

---

## Trace legend (properties of this build)

- **[RM]** = an illustrative value for what the trained component would output on this record (not measured; no trained checkpoint was run); **[SI]** = the deterministic stand-in's output on this record; untagged numbers = configured parameters (gate 0.90 in this run, default 0.88; redaction cutoff 0.85; index `M/efC/efS = 32/200/64`).
- The stand-in reproduces the contract and the gates exactly. For PHI it reproduces the trace, because identifier detection is pattern-shaped and the eCRF scrub is a string replace — every `[SI]` offset in §2.2 was verified against a shipped run on 2026-10-13. For coding its retrieval is lexical, so its `[SI]` scores will not match the `[RM]` column on semantically-gapped verbatims; install the trained encoder + index and the Laya checkpoint and the same tables fill with `[RM]` numbers, columns unmoved.
- Two parameters are deployment decisions the audit records, not fixed constants: the coding gate (0.88 vs 0.90, discriminated by the 0.8820 row) and the redaction tag scheme. Both are reviewer-set in the app and written to the audit with the run.

## Verify this walkthrough yourself

Point either app at [`../sample_data/`](../sample_data/) (the worked cut plus a synthetic demo dictionary) and Execute — no code edits, no setup beyond `pip install -r requirements.txt`. The PHI trace reproduces §2.2–§2.5 exactly; the coding trace exercises both routing branches with honest `[SI]` scores. What was checked, what bugs were found and fixed, and how to re-run the 95-check harness: [QC_REPORT.md](../QC_REPORT.md).
