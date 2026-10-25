#!/usr/bin/env python3
"""Generate the SYNTHETIC longitudinal dataset for anomaly_app.py (deterministic, seed 42).

Run from anywhere:   python3 generate.py     (writes labs.csv next to this file)

WHY THIS IS ITS OWN FOLDER (not merged into sample_data/): distributional DRIFT needs a
LONGITUDINAL time axis. The shared sample_data/ cut is deliberately cross-sectional (one row per
participant per domain, no visit dimension) so the coding / PHI / risk apps stay focused on that shape.
This app's demo therefore carries its own small longitudinal file with injected signals -- additive
and orthogonal to the shared cut, not a competing version of it.

EVERYTHING HERE IS SYNTHETIC. No real patient, study, or licensed dictionary; participant IDs, values and
the injected signals are invented for demonstration. Widen SUBJS / VISITS below (seeded) to add more
/varied data -- a given edit reproduces the same cut.

Injected signals (what a correct run should catch):
  * COHORT drift on ALT (+14/visit for everyone) -> top cohort-wide drift column.
  * LAB-specific drift: LAB-C's AST rises over visits while the rest of the cohort stays stable --
    only per-LAB drift detection catches it cleanly (cohort-wide it is diluted to ~1/3 strength).
  * Three numeric per-participant outliers at a participant's last visit -> high Isolation-Forest anomaly.
  * Three TEXT outliers in LABCOM (unusual/erroneous notes) -> flagged by the text-outlier tier.
"""
import csv, os, random

random.seed(42)
OUT = os.path.dirname(os.path.abspath(__file__))   # .../biostat_pipeline_apps/anomaly_data
STUDY = "PROTO-2026-X89"                            # synthetic study id (not real)

SUBJS = [f"SUBJ-A{n:03d}" for n in range(1, 151)]   # 150 participants
VISITS = [1, 2, 3, 4]                               # longitudinal visits (numeric -> robust windowing)
AVISIT_LABEL = {1: "V1", 2: "V2", 3: "V3", 4: "V4"}

# Each participant is enrolled at one site/lab; the lab is a CATEGORICAL column, constant per participant.
LABS = ["LAB-A", "LAB-B", "LAB-C"]
lab_of = {s: LABS[i % 3] for i, s in enumerate(SUBJS)}

# Baseline means/spreads per measurable numeric column.
BASE = {"ALT": (35.0, 8.0), "AST": (28.0, 6.0), "CREAT": (1.0, 0.15), "SYSBP": (125.0, 10.0)}
# Cohort-wide drift: ALT rises for everyone -> the cohort-level Sinkhorn signal.
TREND = {"ALT": 14.0}
# Lab-specific drift: LAB-C's AST rises over visits while the rest of the cohort stays stable -- a
# site/lab assay change that only per-LAB drift detection should catch (cohort-wide it is diluted).
LAB_TREND = {"AST": {"LAB-C": 5.0}}

# A few participants get an EXTREME numeric outlier at their last visit -> high per-participant anomaly score.
OUTLIERS = {"SUBJ-A003": ("ALT", 420.0), "SUBJ-A017": ("SYSBP", 215.0), "SUBJ-A029": ("CREAT", 6.8)}

# Free-text lab comment field: mostly routine notes + a few injected TEXT outliers (unusual/erroneous
# content) that the text-outlier tier (Needle3/Laya, or [SI] bag-of-words isolation) should flag.
LABCOM_NORMAL = ["Routine panel; values within expected range.", "Sample received on time.",
                 "No hemolysis noted.", "Repeat ordered per protocol.", "Specimen adequate."]
LABCOM_ANOMALY = {
    ("SUBJ-A011", 3): "SAMPLE HEMOLYZED -- RESULT UNRELIABLE, RECOLLECT IMMEDIATELY",
    ("SUBJ-A042", 2): "value entered in wrong units; see correction log 9999-99-99",
    ("SUBJ-A077", 4): "patient not found at site; data may be from a prior study",
}

def clamp(x, lo): return max(lo, x)

rows = []
for s in SUBJS:
    lab = lab_of[s]
    # each participant has a stable personal baseline offset so participants differ but the cohort is coherent
    off = {c: random.gauss(0, BASE[c][1] * 0.4) for c in BASE}
    for v in VISITS:
        rec = [STUDY, s, AVISIT_LABEL[v], v, lab]   # LAB categorical column at index 4
        for c in ("ALT", "AST", "CREAT", "SYSBP"):
            mean, sd = BASE[c]
            trend = TREND.get(c, 0.0) + LAB_TREND.get(c, {}).get(lab, 0.0)
            val = clamp(random.gauss(mean + trend * (v - 1) + off[c], sd), 5.0 if c != "CREAT" else 0.3)
            rec.append(round(val, 2))
        # inject a per-participant numeric outlier at the last visit for the chosen participants
        if s in OUTLIERS and v == VISITS[-1]:
            col, extreme = OUTLIERS[s]
            idx = ["ALT", "AST", "CREAT", "SYSBP"].index(col) + 5   # +5: STUDYID/USUBJID/AVISIT/VISITNUM/LAB
            rec[idx] = round(extreme, 2)
        # free-text lab comment (the text-outlier signal lives here)
        rec.append(LABCOM_ANOMALY.get((s, v), random.choice(LABCOM_NORMAL)))
        rows.append(rec)

with open(os.path.join(OUT, "labs.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["STUDYID", "USUBJID", "AVISIT", "VISITNUM", "LAB", "ALT", "AST", "CREAT", "SYSBP", "LABCOM"])
    w.writerows(rows)

print(f"labs.csv rows={len(rows)} participants={len(SUBJS)} visits={len(VISITS)} labs={len(LABS)} -> {OUT}")
