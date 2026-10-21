# eCRF Pipeline Apps — MedDRA Auto-Coding · PII/PHI Redaction · Risk Scoring · Anomaly & Drift

📖 **New here?** Start with the [User Guide](USER_GUIDE.md) for step-by-step usage of all four apps.

Four independent Streamlit apps that run on local, air-gapped hardware and read the
**same cut folder** without interfering (the anomaly app reads its own longitudinal demo):

| App | Reads | Needs | Writes |
|---|---|---|---|
| [meddra_app.py](meddra_app.py) — *MedDRA Auto-Coding* | the one verbatim column you select (`AETERM`-synonym) | domain CSVs **+** a MedDRA dictionary (flattened CSV or `.asc`) | `ae_coded.csv`, `audit_log.csv` |
| [phi_app.py](phi_app.py) — *PII/PHI Redaction* | **every non-numeric column** (content-based; confirmed in pre-flight) | domain CSVs only — **no dictionary**; ignores any `meddra*.csv` | `phi_flags.csv`, `sanitized/<domain>.csv`, `audit_log.csv` |
| [risk_app.py](risk_app.py) — *Risk Scoring* | safety domains (`ae`/`lb`/`eg`/`vs`/`pe`) classified by content | those CSVs only — **no dictionary, no SAP file**; scores against built-in `[SI]` criteria | `risk_scores.csv`, `audit_log.csv` |
| [anomaly_app.py](anomaly_app.py) — *Anomaly & Drift Detection* | measurable numeric columns + optional time/visit, lab/site and free-text columns, aligned by `USUBJID` | longitudinal CSVs/SAS only — **no dictionary**; scores against built-in `[SI]` criteria | `anomalies.csv`, `drift.csv`, `lab_drift.csv`, `lab_compare.csv`, `text_anomalies.csv`, `audit_log.csv` |

Each app writes its own audit log with the files it read, the per-tier path that ran (REAL or
labelled stand-in `[SI]`), and every effective threshold — so a run is reproducible from its audit
alone. The four programs share no module on purpose; see the header comment in each file before
editing.

## Quickstart (60 seconds, sample data included)

**macOS — just double-click:** `Launch Coding App.command`, `Launch PHI App.command`,
`Launch Risk App.command`, or `Launch Anomaly App.command`. Finder runs these in Terminal and opens the app in your browser — no typing needed. The `.bat` files are for Windows; on Mac use the `.command` files (double-clicking a plain `.sh` may open it in an editor instead of running it).

From a terminal instead:

```bash
# macOS / Linux
./run_meddra.sh        # coding app  → http://localhost:8501
./run_phi.sh           # PHI app     → http://localhost:8502
./run_risk.sh          # risk app    → http://localhost:8503
./run_anomaly.sh       # anomaly app → http://localhost:8504

# Windows
run_meddra.bat
run_phi.bat
run_risk.bat
run_anomaly.bat
```

The scripts create a `.venv` on first run and install dependencies themselves. Then, in each app's
sidebar: set **Cut folder path** to [`sample_data/`](sample_data/) — the one synthetic cut the coding, PHI and risk apps read (the worked scenario from [Deck B](presentations/deck_b_implementation_walkthrough.md), plus a larger bulk set of subjects) — or to [`anomaly_data/`](anomaly_data/) for the anomaly app. Confirm the pre-flight panel, then click **Execute**. See each folder's README for exactly what a run should show.

All apps accept **CSV or SAS `.sas7bdat`** (SDTM/ADaM dumps). CSV works out of the box; to load
`.sas7bdat`, install `pyreadstat` (`pip install pyreadstat`). The anomaly app's real detectors are opt-in:
`POT` + `scipy` flip drift to **real Sinkhorn optimal transport**, and `scikit-learn` adds a real
**Isolation Forest** numeric-outlier corroborator; without them it runs labelled `[SI]` stand-ins with
identical output columns.

Manual equivalent: `pip install -r requirements.txt && streamlit run <app>.py`.

## Hosted demo (no install)

Each app can run on [Streamlit Community Cloud](https://streamlit.io/cloud) straight from this repository: deploy it with the app file (`meddra_app.py`, `phi_app.py`, `risk_app.py` or `anomaly_app.py`) as the main file and `requirements.txt` as is. In the sidebar, tick **Use the bundled synthetic sample data**, or open the app link with `?demo=1` appended to start with it ticked. Everything bundled is synthetic: no real patients, no real study and no licensed dictionary. The demo dictionary's codes are 99-prefixed placeholders, not MedDRA codes.

## Using your own cut

1. Put the domain files (CSV or SAS `.sas7bdat`) in one folder — or upload them directly in the sidebar; no code edits either way.
2. **Coding app:** provide exactly one dictionary shape — a flattened CSV with an LLT-name + PT-name
   column (recommended), or a folder of licensed `llt.asc` / `pt.asc` / `hlt.asc` / `hlgt.asc` /
   `soc.asc`. A `meddra*.csv` inside the cut folder is auto-found. Confirm which verbatim column will
   be read in the pre-flight panel; if your header spells it differently, add it to `AETERM_SYNONYMS`
   at the top of `meddra_app.py`.
3. **PHI app:** every column that isn't strictly numeric is scanned by default; in the pre-flight
   multiselect, deselect any known-safe structured column (a date or coded field you don't want
   touched). No rule editing needed.
4. **Risk app:** point at a folder with your safety domains (`ae`/`lb`/`eg`/`vs`/`pe`). Each file is
   classified by its *content* (signature columns), not its name, so oddly-named dumps work. No SAP or
   protocol file is needed — the app scores raw data against clearly-labelled built-in criteria tagged
   `[SI]`, and records that source in the audit.
5. **Anomaly app:** point at a folder of longitudinal files (one row per subject per visit) with a
   subject-id column (`USUBJID`) and one or more numeric columns to measure. Optional signals are detected
   by content/synonym and surfaced in pre-flight: a time/visit column (e.g. `VISITNUM`, `AVISITD`) enables
   drift, a categorical lab/site column (e.g. `LAB`) enables per-lab drift AND between-lab/site comparison,
   and any long free-text column
   (e.g. `LABCOM`, `AECOM`) is scanned for text outliers. Only flagged observations are emitted.
6. Set the operating point where one exists (coding gate default 0.88; redaction gate default 0.85).
   Whatever you end at is written to the audit with the run.

## Stand-in vs real components

Without the trained weights installed, Tiers 2–4 run as **labelled deterministic stand-ins** (`[SI]`
in the banner and audit): lexical retrieval for coding, guarded regexes for PHI spans, rule-based
probabilities, a transparent weighted rule engine for risk scoring, and — for the anomaly app — a robust-z numeric gate, a labelled 1-D-Wasserstein drift stand-in, and a
bag-of-words text-isolation stand-in. The PHI stand-in reproduces its worked trace exactly; the coding
stand-in is honest about being lexical — semantically-gapped verbatims flag to a human coder rather than auto-code. Install the real runtimes (`cactus-needle`, `hnswlib`, `laya`, `xgboost`) and the banner flips tier-by-tier; columns, gates, and exports do not move. The anomaly app's drift path becomes **real Sinkhorn optimal transport** (`ot.sinkhorn2`) with `POT` + `scipy`, its numeric-outlier corroborator becomes real **Isolation Forest** with `scikit-learn`, and its text outlier detector becomes real **Needle3/Laya** retrieval-isolation — install them to flip those tiers to REAL. If a trained artifact file is present but its runtime is missing, the app **stops** rather than silently substituting a stand-in.

## What this build does NOT do

No scanned-document / bounding-box path (input is tabular eCRF), no negation feature, no clinical
variable derivation, and nothing leaves the machine. The PHI output is compliance-*enabling*, not a
certification; that remains an organizational determination. **The risk app is decision support — it
ranks and flags subjects for human review but does NOT make a clinical determination**, and it scores
raw data against built-in `[SI]` criteria rather than parsing free-text PDF/Word protocols or SAPs. See
[Deck A](presentations/deck_a_four_tier_pipeline.md) for the full governance and limits section.

## Files

```
meddra_app.py            coding program   (self-contained; do not share modules with the others)
phi_app.py               PHI program      (self-contained; same rule)
risk_app.py              risk-scoring program (self-contained; same rule)
anomaly_app.py           anomaly & drift-detection program (self-contained; same rule)
requirements.txt         stand-in-path dependencies (+ optional pyreadstat / POT+scipy / scikit-learn blocks)
run_meddra.sh / .bat     one-command launchers (create .venv on first run, opt out of telemetry prompt)
run_phi.sh    / .bat     one-command launchers (same as above, PHI app on port 8502)
run_risk.sh   / .bat     one-command launchers (same as above, risk app on port 8503)
run_anomaly.sh/ .bat     one-command launchers (same as above, anomaly app on port 8504)
Launch *.command         macOS double-click launchers — Finder runs them in Terminal
.streamlit/config.toml   disables Streamlit usage stats — nothing leaves the machine
sample_data/             the one SYNTHETIC cut the coding/PHI/risk apps read (+ generate.py to regenerate ae/lb/eg/vs/pe)
anomaly_data/            the anomaly app's own SYNTHETIC longitudinal demo (labs.csv + generate.py)
presentations/           Deck A (conceptual) and Deck B (implementation walkthrough), MD + HTML
USER_GUIDE.md            step-by-step instruction manual for running all four apps
tests/qc_test.py         portable end-to-end test harness (87 checks; `python tests/qc_test.py`)
QC_REPORT.md             what was tested, what bugs were found and fixed, how to re-run the tests
```
