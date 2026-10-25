# Sample cut: try the apps on this before touching real data

This folder is **one synthetic cut** that the Coding QC assist, the De-identification review assist and
Participant risk screening all read without interfering (Central statistical monitoring can read it too, but has
its own longitudinal demo in [`../anomaly_data/`](../anomaly_data/)). It starts from the worked examples in the
[case study](https://patrickiben.github.io/ecrf-pipeline-apps/case-study.html) (protocol PROTO-2026-X89) and then adds a larger set of participants, so you
can see how the apps behave on more varied data than a few hand-picked rows. Point any app's **Cut folder path**
at this directory and Execute: `meddra_demo.csv` is found automatically as the coding dictionary, and the other
apps ignore it (they need none).

> **Everything here is synthetic.** No real patient, study or licensed dictionary; participant IDs, values and
> clinical notes are invented for demonstration. Regenerate with `python3 generate.py` (deterministic, seed 42):
> a given edit reproduces the same cut.

| file | rows | role |
|---|---|---|
| `ae.csv` | 151 | Adverse events: `STUDYID USUBJID AVISIT VISITNUM AESEQ AETERM AESEV AESER AELIFE AEOUTCOME AEREL AECOM`. The first six rows are the case study's worked rows (preserved exactly for the coding and de-identification traces); the rest is a bulk set plus named teaching anchors. `AECOM` carries free-text clinical notes; row 6 has a **blank** `AECOM` to show that a missing value stays missing. |
| `lb.csv` | 34 | Labs: `USUBJID AVISIT VISITNUM LBTESTCD LBSTRESN LBNRHI ABNORMAL CLINSIG`. `LBNRHI` is the **file-provided upper limit of normal** the risk app scores each lab against; values are a ratio times the ULN, `ABNORMAL` when above the ULN, `CLINSIG` when above the built-in multiple (ALT or AST 3x ULN, creatinine 1.5x ULN; screening criteria, not CTCAE grades). |
| `eg.csv` | 28 | ECG/QTc: `STUDYID USUBJID AVISIT VISITNUM EGSEQ EGQTC EGHRR1 ABNORMAL CLINSIG EGCOM`. `ABNORMAL` when QTc is above 460 ms and `CLINSIG` when it is above 500 ms (flags of this synthetic generator; the risk app's cardiac criterion is QTc above 500 ms, the top ICH E14 categorical tier, and the synthetic QTc is not tied to a correction such as QTcF or QTcB); `EGCOM` carries a short clinical note. |
| `vs.csv` | 29 | Vital signs: `USUBJID AVISIT VISITNUM VSPAR VSSTRESN ABNORMAL CLINSIG`. |
| `pe.csv` | 100 | Physical exam: `USUBJID AVISIT VISITNUM PEDECOD PEFIND`, with realistic findings (for example Tachycardia, Hepatomegaly, Rash) rather than a single present/absent flag. |
| `pr.csv` | 1 | The de-identification mosaic case: initials, an MRN, a date of birth and a ZIP code in one comment. **Static** (not regenerated). |
| `meddra_demo.csv` | 12 | **Synthetic** flattened dictionary carrying the full LLT, PT, HLT, HLGT and SOC chain, covering the demo verbatims. NOT licensed MedDRA; its codes are 99-prefixed placeholders. Must not be used for real coding. **Static.** |

## The fatal and life-threatening distinction (taught by `ae.csv`)

`AELIFE=Y` is always paired with explicit evidence in `AEOUTCOME=DIED`. A **life-threatening severity alone never
implies death**: anchor `SUBJ-9015` (anaphylaxis) is fatal (`AELIFE=Y`, `AEOUTCOME=DIED`) and the risk app forces
it to CRITICAL; anchor `SUBJ-9001` had a life-threatening cardiac arrest but survived, so its fatality flag stays
`N`. This keeps "fatal" backed by evidence rather than inferred from severity.

## What a correct run shows

**Coding QC assist** (`meddra_app.py`, default gate 0.88):
- Pre-flight lists the domains; dictionary source "flattened CSV in cut folder (meddra_demo.csv)"; verbatim
  column `ae :: AETERM`.
- Worked row 5 (`headache`) is **AUTO_COMMIT_TO_SDTM** at S = 1.0 (an exact token match).
- The other worked rows, and bulk verbatims worded differently from every dictionary term, are
  **FLAGGED_FOR_HUMAN_CODER** with the top three candidates pre-filled. That is the honest `[SI]` behavior: the
  lexical stand-in cannot bridge wording gaps such as "marked prolonged heart rhythm interval" to QT prolonged.
  Moving the gate down to about 0.77 auto-codes worked row 1 (S = 0.7726), which shows the gate is a movable
  operating point.
- `ae_coded.csv` has one row per candidate (ranks 1 to 3); rank 1 carries the status and the others are
  `ALT_CANDIDATE`. Each row also carries `HLT` and `HLGT` as **evidence columns**: the full hierarchy path, never
  scored and not SDTM write-back.

**De-identification review assist** (`phi_app.py`, default redaction gate 0.85):
- Content-based discovery scans **every non-numeric column** in each domain (all columns except the numeric
  `AESEQ`/`PRSEQ`/`EGSEQ`/`VISITNUM` and the numeric lab and vital values), including `AETERM`. The visit labels
  (`AVISIT`) are scanned too but carry no identifiers, so they never flag. Only `AECOM` and `PRDSC` contain
  identifiers, so only those produce flags; **many bulk `AECOM` rows**, not just the worked rows, carry invented
  names, phone numbers, MRNs, dates of birth, ZIP codes and initials, so redaction is exercised across dozens of
  rows.
- AE row 1: `Jane Miller` and `(617) 555-0192` are scrubbed, giving `CRC Note: Patient [REDACTED_PATIENT_NAME]
  called site cell phone [REDACTED_PHONE] at 10:15 AM.`
- AE row 2 (the look-alike trap): the name is scrubbed while **Alanine 50 mg** and **glucose 120 mg/dL** survive
  intact.
- PR row: all four spans are scrubbed, the MRN and date of birth on their own merit and the initials and ZIP code
  because two indirect attributes co-occur (the mosaic).
- The EG row and the blank AE row 6 are untouched, with flag `N`; the sanitized cell stays empty (never `"nan"`).
- `phi_flags.csv` and the original columns in `sanitized/` still hold the (invented) identifiers.

**Participant risk screening** (`risk_app.py`) reads `ae`/`lb`/`eg`/`vs`/`pe` from this same folder, with no SAP or
protocol file. Anchor participants land where designed: fatal `SUBJ-9015` is CRITICAL with the fatality cited
alongside its `AEOUTCOME=DIED`; multi-system `SUBJ-9001` is CRITICAL; severe-AE `SUBJ-9002` is HIGH; lab-driven
`SUBJ-9013` cites an ALT breach; ECG-driven `SUBJ-9014` cites QTc. See [USER_GUIDE.md](../USER_GUIDE.md) section 5.

> Every domain here carries `AVISIT`/`VISITNUM`, so **Central statistical monitoring** can read this folder
> directly, or you can mix it with the longitudinal demo in [`../anomaly_data/`](../anomaly_data/) (one row per
> participant per visit, with injected drift) in a single cut.
