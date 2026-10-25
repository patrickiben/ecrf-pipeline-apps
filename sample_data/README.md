# Sample cut — try the apps on this before touching real data

This folder is **one synthetic cut** that all four apps read without interfering. It starts from the
worked examples in the [case study](https://patrickiben.github.io/ecrf-pipeline-apps/case-study.html) (protocol
PROTO-2026-X89) and then appends a larger bulk set of participants so you can see how the apps behave on
more/varied data — not just six hand-picked rows. Point any app's **Cut folder path** at this directory
and Execute: `meddra_demo.csv` is auto-found as the coding dictionary, and every other app ignores it
(it needs none).

> **Everything here is synthetic.** No real patient, study, or licensed dictionary; participant IDs, values
> and clinical notes are invented for demonstration. Regenerate with `python3 generate.py` (deterministic,
> seed 42) — a given edit reproduces the same cut.

| file | rows | role |
|---|---|---|
| `ae.csv` | 151 | Adverse events: `STUDYID USUBJID AVISIT VISITNUM AESEQ AETERM AESEV AESER AELIFE AEOUTCOME AEREL AECOM`. The first six rows are Deck B's worked cut (preserved exactly for the coding/PHI traces); the rest is a bulk set plus named teaching anchors. `AECOM` carries free-text clinical notes; row 6 has a **blank** `AECOM` to demonstrate "missing stays missing". |
| `lb.csv` | 34 | Labs: `USUBJID AVISIT VISITNUM LBTESTCD LBSTRESN LBNRHI ABNORMAL CLINSIG`. `LBNRHI` is the **file-provided reference range (ULN)** the risk app scores each lab against; values are ratio × ULN, `ABNORMAL` when above ULN, `CLINSIG` when past the SAP multiple. |
| `eg.csv` | 28 | ECG/QTc: `STUDYID USUBJID AVISIT VISITNUM EGSEQ EGQTC EGHRR1 ABNORMAL CLINSIG EGCOM`. QTc abnormal ≥460 ms, clinically significant ≥500 ms; `EGCOM` carries a short clinical note. |
| `vs.csv` | 29 | Vital signs: `USUBJID AVISIT VISITNUM VSPAR VSSTRESN ABNORMAL CLINSIG`. |
| `pe.csv` | 100 | Physical exam: `USUBJID AVISIT VISITNUM PEDECOD PEFIND` — realistic findings (e.g. Tachycardia, Hepatomegaly, Rash), not a single "abnormal present/absent" flag. |
| `pr.csv` | 1 | The PHI mosaic case: initials + MRN + DOB + postcode in one comment. **Static** (not regenerated). |
| `meddra_demo.csv` | 12 | **Synthetic** flattened dictionary carrying the full LLT→PT→HLT→HLGT→SOC chain, covering the demo verbatims. NOT licensed MedDRA; its codes are 99-prefixed placeholders. Must not be used for real coding. **Static.** |

## The fatal / life-threatening distinction (taught by `ae.csv`)

`AELIFE=Y` is always paired with explicit evidence in `AEOUTCOME=DIED`. A **life-threatening severity
alone never implies death**: anchor `SUBJ-9015` (anaphylaxis) is genuinely fatal (`AELIFE=Y`,
`AEOUTCOME=DIED`) and the risk app forces it to CRITICAL; anchor `SUBJ-9001` had a life-threatening
cardiac arrest but survived, so its fatality flag stays `N`. This keeps "fatal" evidence-backed rather
than inferred from severity.

## What a correct run shows

**Coding app** (`meddra_app.py`, default gate 0.88):
- Pre-flight lists the domains; dictionary source "flattened CSV in cut folder (meddra_demo.csv)"; verbatim column `ae :: AETERM`.
- The worked row 5 (`headache`) → **AUTO_COMMIT_TO_SDTM** at S = 1.0 (exact token match).
- The other worked rows and the bulk semantic-gap verbatims → **FLAGGED_FOR_HUMAN_CODER** with top-3 candidates pre-populated — honest `[SI]` behavior: the lexical stand-in cannot bridge gaps like "marked prolonged heart rhythm interval" → QT prolonged. Dragging the gate down to ~0.75 auto-codes worked row 1, showing the gate is a movable operating point.
- `ae_coded.csv`: one row per candidate (rank 1–3); rank-1 carries the status, others are `ALT_CANDIDATE`. Each row also carries `HLT` and `HLGT` as **evidence columns** — full hierarchy path, never scored, not SDTM write-back.

**PHI app** (`phi_app.py`, default redaction gate 0.85):
- Content-based discovery scans **every non-numeric column** in each domain (all columns except the numeric `AESEQ`/`PRSEQ`/`EGSEQ`/`VISITNUM` and the numeric lab/vital values), including `AETERM`. The visit labels (`AVISIT`) are scanned too but carry no identifiers, so they never flag. Only `AECOM` and `PRDSC` actually contain identifiers, so only those produce flags — but **many bulk `AECOM` rows** (not just the six worked demos) now carry realistic PHI (names, phones, MRN, DOB, ZIP, initials), so redaction is exercised across dozens of rows.
- AE row 1: `Jane Miller` + `(617) 555-0192` scrubbed → `CRC Note: Patient [REDACTED_PATIENT_NAME] called site cell phone [REDACTED_PHONE] at 10:15 AM.`
- AE row 2 (look-alike trap): the name is scrubbed while **Alanine 50 mg** and **glucose 120 mg/dL** survive intact.
- PR row: all four spans scrubbed — MRN/DOB on their own merit, initials + postcode because two indirect attributes co-occur (the mosaic).
- EG row and the blank AE row 6: untouched, flag `N`, sanitized cell stays empty (never `"nan"`).

**Risk app** (`risk_app.py`): reads `ae`/`lb`/`eg`/`vs`/`pe` from this same folder — no SAP or protocol file. Anchor participants land where designed (fatal `SUBJ-9015` → CRITICAL with the fatality cited alongside its `AEOUTCOME=DIED`; multi-system `SUBJ-9001` → CRITICAL; severe-AE `SUBJ-9002` → HIGH; lab-driven `SUBJ-9013` cites an ALT breach; ECG-driven `SUBJ-9014` cites QTc). See [USER_GUIDE.md](../USER_GUIDE.md) §5.

> Every domain here now carries `AVISIT`/`VISITNUM`, so the **anomaly/drift app** can read this folder directly — or you can mix it with the true-longitudinal demo in [`../anomaly_data/`](../anomaly_data/) (one row per participant per visit, with injected drift) in a single cut.
