# Anomaly & drift demo — longitudinal data for `anomaly_app.py`

This folder holds the **synthetic longitudinal** dataset that [`anomaly_app.py`](../anomaly_app.py) reads by default: one row per subject per visit, so distributional **drift over time** can be measured. Everything here is invented for demonstration — no real patient, study, or licensed dictionary.

## Why this is its own folder (not merged into `sample_data/`)

Drift needs a **time axis**. The shared [`../sample_data/`](../sample_data/) cut is deliberately cross-sectional — one row per subject per domain, no visit dimension — so the coding / PHI / risk apps stay focused on that shape. This app's demo therefore carries its own small longitudinal file with an injected drift signal and a few per-subject outliers. It is **additive and orthogonal** to the shared cut, not a competing version of it: the two folders answer different questions (cross-sectional safety vs. longitudinal change).

## `labs.csv` — columns

| column | meaning |
|---|---|
| `STUDYID` | synthetic study id (`PROTO-2026-X89`). |
| `USUBJID` | subject id (`SUBJ-A001`…`SUBJ-A150`, 150 subjects). |
| `AVISIT` / `VISITNUM` | visit label (V1–V4) and numeric index — the **time column** the app uses to pick reference vs current windows. |
| `ALT`, `AST`, `CREAT`, `SYSBP` | measurable numeric columns (alanine transaminase, aspartate transaminase, creatinine, systolic BP). |
| `LAB` | categorical lab/site column (`LAB-A`/`LAB-B`/`LAB-C`) — enables **per-lab drift** AND **between-lab/site comparison**. |
| `LABCOM` | free-text lab comment — scanned for **text outliers**. Mostly routine notes + a few injected anomalous ones. |

150 subjects × 4 visits = **600 rows**.

## Injected signals (what a correct run should catch)

- **Cohort drift on `ALT`:** every subject's ALT rises ~+14 per visit, so the whole distribution shifts across visits. The Sinkhorn/Wasserstein path should rank **`ALT` as the top cohort drift column**, with the stable columns (`AST`, `CREAT`, `SYSBP`) at LOW/MODERATE.
- **Lab-specific drift on `LAB-C × AST`:** only LAB-C's AST rises over visits while the rest of the cohort stays stable — a site/lab assay change that cohort-wide drift dilutes to ~1/3 strength. Only **per-lab drift** (`lab_drift.csv`) isolates it cleanly: LAB-C×AST should be CRITICAL while LAB-A/B×AST stay LOW/MODERATE.
- **Between-lab/site comparison on `LAB-C × AST`:** because LAB-C's current-window AST distribution sits above the pooled others, the leave-one-out transport distance (`lab_compare.csv`) ranks **LAB-C×AST as the between-lab standout** (HIGH/CRITICAL) while LAB-A/B×AST stay LOW/MODERATE — answering *"how different is this lab/site from all the others?"* separately from how much one lab moved over time.
- **Three individual numeric outliers** (a spike at a subject's last visit → flagged per-subject anomaly, not cohort drift):
  - `SUBJ-A003` — ALT = 420
  - `SUBJ-A017` — SYSBP = 215
  - `SUBJ-A029` — CREAT = 6.8

  These are the **only** subjects emitted to `anomalies.csv` (flagged-only output); each cites its extreme column/z and the IsolationForest corroborator.
- **Three text outliers in `LABCOM`:** unusual/erroneous notes with no close neighbour in the field's corpus → flagged by retrieval-isolation (`text_anomalies.csv`):
  - `SUBJ-A011` V3 — "SAMPLE HEMOLYZED -- RESULT UNRELIABLE, RECOLLECT IMMEDIATELY"
  - `SUBJ-A042` V2 — "value entered in wrong units; see correction log 9999-99-99"
  - `SUBJ-A077` V4 — "patient not found at site; data may be from a prior study"

A correct run flags exactly the three numeric outliers and the three anomalous notes, shows `ALT` as the dominant cohort drift column, and isolates LAB-C×AST in per-lab drift — demonstrating that anomaly (one subject), drift (the whole cohort vs one lab), and text isolation are separate, honest signals.

## Regenerate

`python3 generate.py` rewrites `labs.csv` deterministically (seed 42). Widen `SUBJS` / `VISITS` at the top of the script to add more/varied data; a given edit reproduces the same cut.
