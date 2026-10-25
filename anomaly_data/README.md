# Central statistical monitoring demo: longitudinal data for `anomaly_app.py`

This folder holds the **synthetic longitudinal** dataset that [`anomaly_app.py`](../anomaly_app.py) (Central
statistical monitoring) reads by default: one row per participant per visit, so distributional **drift over time**
can be measured. Everything here is invented for demonstration: no real patient, study or licensed dictionary.

## Why this is its own folder (not merged into `sample_data/`)

Drift needs repeated measurements of the same columns over time, with known signals to find. The shared
[`../sample_data/`](../sample_data/) cut is built for the coding, de-identification and risk apps: it carries visit
labels, but each participant has only a few lab and vital rows and nothing is injected to drift. This app's demo
therefore carries its own longitudinal file with an injected drift signal, a lab-specific shift and a few
per-participant outliers. It adds to the shared cut rather than competing with it: the two folders answer
different questions (cross-sectional safety, and change over time).

## `labs.csv` columns

| column | meaning |
|---|---|
| `STUDYID` | synthetic study ID (`PROTO-2026-X89`). |
| `USUBJID` | participant ID (`SUBJ-A001` to `SUBJ-A150`, 150 participants). |
| `AVISIT` / `VISITNUM` | visit label (V1 to V4) and numeric index: the **time column** the app uses to pick the reference and current windows. |
| `ALT`, `AST`, `CREAT`, `SYSBP` | measurable numeric columns (alanine aminotransferase, aspartate aminotransferase, creatinine, systolic blood pressure). |
| `LAB` | categorical lab/site column (`LAB-A`, `LAB-B`, `LAB-C`): enables **per-lab drift** AND the **between-lab/site comparison**. |
| `LABCOM` | free-text lab comment, scanned for **text outliers**: mostly routine notes plus a few injected unusual ones. |

150 participants times 4 visits = **600 rows**.

## Injected signals (what a correct run should catch)

- **Cohort drift on `ALT`:** every participant's ALT rises by about 14 per visit, so the whole distribution shifts
  across visits. The Sinkhorn or Wasserstein path should rank **`ALT` as the top cohort drift column**, with the
  stable columns (`AST`, `CREAT`, `SYSBP`) at LOW or MODERATE.
- **Lab-specific drift on `LAB-C × AST`:** only LAB-C's AST rises over visits while the rest of the cohort stays
  stable, like a site or lab assay change that cohort-wide drift dilutes to about a third of its strength. Only
  **per-lab drift** (`lab_drift.csv`) isolates it cleanly: LAB-C × AST should be CRITICAL while LAB-A and LAB-B ×
  AST stay LOW or MODERATE.
- **Between-lab/site comparison on `LAB-C × AST`:** because LAB-C's current-window AST distribution sits above the
  pooled others, the leave-one-out transport distance (`lab_compare.csv`) ranks **LAB-C × AST as the between-lab
  standout** (HIGH or CRITICAL) while LAB-A and LAB-B × AST stay LOW or MODERATE. This answers *"how different is
  this lab or site from all the others?"* separately from how much one lab moved over time.
- **Three individual numeric outliers** (a spike at a participant's last visit, which is a per-participant anomaly,
  not cohort drift):
  - `SUBJ-A003`: ALT = 420
  - `SUBJ-A017`: SYSBP = 215
  - `SUBJ-A029`: CREAT = 6.8

  These are the **only** participants written to `anomalies.csv` (flagged-only output); each cites its extreme
  column and z, and the Isolation Forest corroborator when `scikit-learn` is installed.
- **Three text outliers in `LABCOM`:** unusual or erroneous notes with no close neighbor among the field's notes,
  flagged by retrieval isolation (`text_anomalies.csv`). The note text is quoted exactly as stored:
  - `SUBJ-A011` V3: "SAMPLE HEMOLYZED -- RESULT UNRELIABLE, RECOLLECT IMMEDIATELY"
  - `SUBJ-A042` V2: "value entered in wrong units; see correction log 9999-99-99"
  - `SUBJ-A077` V4: "patient not found at site; data may be from a prior study"

A correct run flags exactly the three numeric outliers and the three unusual notes, shows `ALT` as the dominant
cohort drift column, and isolates LAB-C × AST in per-lab drift. That shows the three signals are separate: an
outlier is one participant, drift is the whole cohort or one lab, and text isolation is one note.

## Regenerate

`python3 generate.py` rewrites `labs.csv` deterministically (seed 42). Widen `SUBJS` or `VISITS` at the top of the
script to add more varied data; a given edit reproduces the same cut.
