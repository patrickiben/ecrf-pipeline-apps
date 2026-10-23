# eCRF Pipeline Apps — MedDRA Auto-Coding · PII/PHI Redaction · Risk Scoring · Anomaly & Drift

[![QC](https://github.com/patrickiben/ecrf-pipeline-apps/actions/workflows/qc.yml/badge.svg)](https://github.com/patrickiben/ecrf-pipeline-apps/actions/workflows/qc.yml)

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

**Live demos** (synthetic data only; each opens on the bundled sample cut, then click **Execute**):

- [Coding app](https://ecrf-coding.streamlit.app/?demo=1) (`meddra_app.py`)
- [PHI app](https://ecrf-phi.streamlit.app/?demo=1) (`phi_app.py`)
- [Risk app](https://ecrf-risk.streamlit.app/?demo=1) (`risk_app.py`)
- [Anomaly app](https://ecrf-anomaly.streamlit.app/?demo=1) (`anomaly_app.py`)

An app that has been idle may take about 30 seconds to wake up. Landing page: https://patrickiben.github.io/ecrf-pipeline-apps/

A public demo runs each app in **hosted mode**: every data input (the uploaders, folder paths and models dir) is locked to the bundled synthetic cut, outputs go to a per-session server temp folder (deleted when the session ends), a banner on every page says the demo takes synthetic data only, and the audit records `hosted_mode=true`. Everything bundled is synthetic: no real patients, no real study and no licensed dictionary. The demo dictionary's codes are 99-prefixed placeholders, not MedDRA codes. Hosted mode is off unless a deployment switches it on, so a local run behaves exactly as described in the rest of this README; there, opening the app with `?demo=1` appended simply starts with **Use the bundled synthetic sample data** ticked. Use a local run for real data.

### Deploy your own demo

On [Streamlit Community Cloud](https://streamlit.io/cloud), straight from this repository:

1. **One app per deployment.** Deploy each program as its own app from the same repository and branch, with the main file path set to `meddra_app.py`, `phi_app.py`, `risk_app.py` or `anomaly_app.py`.
2. **Python 3.12.** Choose it under **Advanced settings** when you create the app (it is the version CI tests; changing it later means deleting and redeploying). Leave `requirements.txt` as is: it installs the labeled `[SI]` stand-in path.
3. **Turn on hosted mode.** Add the secret `hosted = true` (the Secrets box takes TOML: paste it under Advanced settings, or later under the app's **Settings > Secrets**). Do not skip this step: without it, a public deployment accepts uploads and folder paths like a local install. On any other host, set the environment variable `ECRF_HOSTED=1` instead. Do not put an `ECRF_HOSTED` key in the secrets: Streamlit copies top-level secrets into the environment over the host's own value, so the apps treat that key as on whatever it says. The switch fails closed: any value other than empty, `0`, `false`, `no` or `off` turns hosted mode on, and so does a secrets file that exists but does not parse (for example `hosted = True` with a capital T), because Streamlit only logs that error on the server.
4. **Check the banner.** Open the deployed app and confirm that the "Public demo: synthetic data only" banner shows on the main page and at the top of the sidebar, and that the uploaders and folder fields are grayed out. If the banner is missing, hosted mode is off: fix the secret before you share the link.
5. **Share the link** with `?demo=1` appended, for example `https://<your-app>.streamlit.app/?demo=1`.

**Hosting it yourself** (a container or server where you control the start command): set `ECRF_HOSTED=1` and also start Streamlit with `--server.maxUploadSize 1` (or `STREAMLIT_SERVER_MAX_UPLOAD_SIZE=1`). In hosted mode the apps never read or process an uploaded file, but Streamlit's upload endpoint still keeps the bytes a crafted client sends, even to a disabled uploader, in server memory until the session expires; the 1 MB cap bounds that. Keep the cap out of `.streamlit/config.toml`, which local runs share.

## Screenshots

Local runs on the bundled synthetic data, opened with `?demo=1` and captured after **Execute**.

![Coding app results table: each adverse-event verbatim with its top three candidate terms, ranks and 99-prefixed placeholder codes](docs/img/meddra_results.png)

*Coding app: top three candidates per verbatim, with placeholder codes; the ranking comes from the `[SI]` lexical stand-in.*

![PHI app results: flagged spans such as invented phone numbers, names, a ZIP code and initials, with entity type, offsets, redaction probability and action](docs/img/phi_results.png)

*PHI app: one row per scrubbed span; every name and number shown is invented.*

![Risk app results: per-subject safety and discontinuation scores and categories with contributing factors, the fatal subject pinned to the top](docs/img/risk_results.png)

*Risk app: per-subject safety and discontinuation scores, sorted highest risk first, with the reasons for each.*

![Anomaly app results: flagged per-subject numeric outliers, cohort-wide drift per column, and per-lab drift](docs/img/anomaly_results.png)

*Anomaly app: flagged numeric outliers, cohort-wide drift per column and per-lab drift on the longitudinal demo.*

## Landing page

[`docs/index.html`](docs/index.html) is a one-page overview for GitHub Pages: the four apps, links to the live demos, the screenshots and both decks. It is published by GitHub Pages from `main`, folder `/docs` (Settings > Pages), at https://patrickiben.github.io/ecrf-pipeline-apps/. `docs/` also holds byte-identical copies of the two HTML decks so they render there; after editing a deck's HTML in `presentations/`, copy it into `docs/` too (QC check D1 fails otherwise).

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
stand-in is honest about being lexical — semantically-gapped verbatims flag to a human coder rather than auto-code. The anomaly app's drift path becomes **real Sinkhorn optimal transport** (`ot.sinkhorn2`) with `POT` + `scipy`, and its numeric-outlier corroborator becomes real **Isolation Forest** with `scikit-learn`; its text detector has no real model path and stays a labelled stand-in.

**The real model path (coding and PHI apps).** With the open-source runtimes installed (Cactus Needle3, hnswlib, Laya, XGBoost) and a **models dir** holding their weights and the trained gates, the coding and PHI apps run their real Tiers 2 to 4, air-gapped. [`eval/README.md`](eval/README.md) says how to install the pinned runtimes and build the models dir (`python eval/fetch_models.py --out models`), and [`docs/EVALUATION.md`](docs/EVALUATION.md) has what was measured, on synthetic data only: the real coding path reached the right preferred term at rank 1 for 78% of held-out verbatims against 54% for the stand-in and auto-coded 38% with no error, and the real PHI path left 91 of 308 held-out identifiers readable against 108 for the stand-in. A tier shows REAL only when its artifact loads; an artifact that is present but cannot be loaded, or a trained gate whose inputs are missing, **stops** the run rather than silently substituting a stand-in. The risk app has no trained-model path: a model file in its models dir stops the run.

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
.github/workflows/qc.yml CI: runs tests/qc_test.py on every push and pull request, stand-in and optional-extras variants
sample_data/             the one SYNTHETIC cut the coding/PHI/risk apps read (+ generate.py to regenerate ae/lb/eg/vs/pe)
anomaly_data/            the anomaly app's own SYNTHETIC longitudinal demo (labs.csv + generate.py)
presentations/           Deck A (conceptual) and Deck B (implementation walkthrough), MD + HTML
docs/                    GitHub Pages landing page (index.html), byte-identical copies of the two HTML decks, screenshots (img/), .nojekyll
USER_GUIDE.md            step-by-step instruction manual for running all four apps
tests/qc_test.py         portable end-to-end test harness (`python tests/qc_test.py` reports passed, failed, and skipped checks for the installed dependencies)
QC_REPORT.md             what was tested, what bugs were found and fixed, how to re-run the tests
```
