# eCRF Pipeline Apps — MedDRA Auto-Coding · PII/PHI Redaction · Risk Scoring · Anomaly & Drift

[![QC](https://github.com/patrickiben/ecrf-pipeline-apps/actions/workflows/qc.yml/badge.svg)](https://github.com/patrickiben/ecrf-pipeline-apps/actions/workflows/qc.yml)

📖 **New here?** Start with the [User Guide](USER_GUIDE.md) for step-by-step usage of all four apps.

Four independent Streamlit apps that run on local, air-gapped hardware and read the
**same cut folder** without interfering (the anomaly app reads its own longitudinal demo). They also
[run in your browser](#run-in-your-browser-no-install) on the bundled synthetic data, with nothing to install:

| App | Reads | Needs | Writes |
|---|---|---|---|
| [meddra_app.py](meddra_app.py) — *MedDRA Auto-Coding* | the one verbatim column you select (`AETERM`-synonym) | domain CSVs **+** a MedDRA dictionary (flattened CSV or `.asc`) | `ae_coded.csv`, `audit_log.csv` |
| [phi_app.py](phi_app.py) — *PII/PHI Redaction* | **every non-numeric column** (content-based; confirmed in pre-flight) | domain CSVs only — **no dictionary**; ignores any `meddra*.csv` | `phi_flags.csv`, `sanitized/<domain>.csv`, `audit_log.csv` |
| [risk_app.py](risk_app.py) — *Risk Scoring* | safety domains (`ae`/`lb`/`eg`/`vs`/`pe`) classified by content | those CSVs only — **no dictionary, no SAP file**; scores against built-in `[SI]` criteria | `risk_scores.csv`, `audit_log.csv` |
| [anomaly_app.py](anomaly_app.py) — *Anomaly & Drift Detection* | measurable numeric columns + optional time/visit, lab/site and free-text columns, aligned by `USUBJID` | longitudinal CSVs/SAS only — **no dictionary**; scores against built-in `[SI]` criteria | `anomalies.csv`, `drift.csv`, `lab_drift.csv`, `lab_compare.csv`, `text_anomalies.csv`, `audit_log.csv` |

Each app writes its own audit log with the files it read, the per-tier path that ran (REAL or
labeled stand-in `[SI]`), and every effective threshold — so a run is reproducible from its audit
alone. The four programs share no module on purpose; see the header comment in each file before
editing.

## Run locally

Quickstart: 60 seconds, sample data included.

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
sidebar: set **Cut folder path** to [`sample_data/`](sample_data/) — the one synthetic cut the coding, PHI and risk apps read (the worked scenario from [Deck B](presentations/deck_b_implementation_walkthrough.md), plus a larger bulk set of participants) — or to [`anomaly_data/`](anomaly_data/) for the anomaly app. Confirm the pre-flight panel, then click **Execute**. See each folder's README for exactly what a run should show.

All apps accept **CSV or SAS `.sas7bdat`** (SDTM/ADaM dumps). CSV works out of the box; to load
`.sas7bdat`, install `pyreadstat` (`pip install pyreadstat`). The anomaly app's real detectors are opt-in:
`POT` + `scipy` flip drift to **real Sinkhorn optimal transport**, and `scikit-learn` adds a real
**Isolation Forest** numeric-outlier corroborator; without them it runs labeled `[SI]` stand-ins with
identical output columns.

Manual equivalent: `pip install -r requirements.txt && streamlit run <app>.py`.

## Run in your browser (no install)

- [Coding app](https://patrickiben.github.io/ecrf-pipeline-apps/app/meddra.html) (`meddra_app.py`)
- [PHI app](https://patrickiben.github.io/ecrf-pipeline-apps/app/phi.html) (`phi_app.py`)
- [Risk app](https://patrickiben.github.io/ecrf-pipeline-apps/app/risk.html) (`risk_app.py`)
- [Anomaly app](https://patrickiben.github.io/ecrf-pipeline-apps/app/anomaly.html) (`anomaly_app.py`)

Each page runs the same Python program inside your browser tab with [stlite](https://github.com/whitphx/stlite), which is Streamlit on Pyodide (CPython compiled to WebAssembly), so there is no server to sleep, wake or sign in to. The page downloads Python and the app's packages from a CDN, fetches the program and its synthetic data from GitHub Pages, and runs everything on your device.

Each opens on the bundled synthetic cut; click **Execute**. The first visit downloads about 30 MB and was measured at about 5 seconds to a usable app on a fast connection and about 30 seconds at 10 Mbps; later visits load from the browser cache. The pages need WebAssembly and module workers (current Chrome, Edge, Firefox or Safari); they were tested in Chrome. Landing page: https://patrickiben.github.io/ecrf-pipeline-apps/

**Privacy:** Runs in your browser; files are processed on your device and not uploaded by the app; the page is downloaded from GitHub Pages and the CDN, which see your IP address; synthetic data only; not a validated or Part 11 system.

The pages run each app in **hosted mode** (`ECRF_HOSTED=1`): every data input (the uploaders, folder paths and models dir) is locked to the bundled synthetic cut, outputs go to a folder in the tab's memory (save them with the download buttons), a banner says the demo takes synthetic data only, and the audit records `hosted_mode=true`. Only the labeled `[SI]` stand-in path runs in the browser, and the pages load numpy and pandas only. The real model path cannot run there as built: the coding and PHI apps load Needle3's native engine library (`libneedle`) from the models dir, Laya needs torch, hnswlib has no Pyodide build, and Pyodide's xgboost (2.1.4) is older than the 3.4.1 used to train the models. Everything bundled is synthetic: no real patients, no real study and no licensed dictionary. The demo dictionary's codes are 99-prefixed placeholders, not MedDRA codes. Hosted mode is off unless a deployment switches it on, so a local run behaves exactly as described in the rest of this README; there, opening the app with `?demo=1` appended simply starts with **Use the bundled synthetic sample data** ticked. Use a local run for real data.

### How the browser build is put together

`docs/app/` holds what GitHub Pages serves for the four apps:

- `meddra.html`, `phi.html`, `risk.html`, `anomaly.html`: one page per app, rendered from `tools/browser_app_template.html`. Each shows a loading notice and a screenshot of the app's results until Python is ready, and keeps the screenshot with a short explanation if the app cannot start. If stlite's stylesheet does not load (the app then runs unstyled), the page fetches it again, twice at most and after a pause, and if that fails shows a notice with a Reload button above the app.
- `launch.js` and `app.css`: the shared loader and page style.
- Byte-identical copies of the four `.py` files and of every CSV in `sample_data/` and `anomaly_data/`, which the pages load from Pages.
- `wheels/`: three small pure-Python wheels the Streamlit build needs that Pyodide does not ship (`itsdangerous` 2.2.0, BSD-3-Clause; `python-multipart` 0.0.32, Apache-2.0; `toml` 0.10.2, MIT), pinned by sha256 and served from Pages so a visit never contacts PyPI. Each wheel carries its license text in its `.dist-info` folder.

After editing an app or its sample data, run `python tools/sync_browser_apps.py` and commit what it changes. CI fails while `docs/app/` is out of step (the `browser-build` job, and QC check D4). The pages pin stlite 1.12.0 (Streamlit 1.65.0 on Pyodide 314.0.3, Python 3.14) by exact version, check its stylesheet and core modules with Subresource Integrity, and carry a Content-Security-Policy that lets them connect only to GitHub Pages and cdn.jsdelivr.net. To move to a newer stlite, change the pins at the top of `tools/sync_browser_apps.py`, run it with `--verify-cdn`, re-render, and test the four pages in a browser before merging. One harmless quirk: each download button logs a console error when it appears (stlite probes a placeholder URL that the page's policy blocks); the file still downloads.

### Serving the apps from your own server

The apps also support a public server deployment. Set the environment variable `ECRF_HOSTED=1` (or the Streamlit secret `hosted = true`) and start Streamlit with `--server.maxUploadSize 1` (or `STREAMLIT_SERVER_MAX_UPLOAD_SIZE=1`), keeping the cap out of `.streamlit/config.toml`, which local runs share. In hosted mode the apps never read or process an uploaded file, but Streamlit's upload endpoint still keeps the bytes a crafted client sends, even to a disabled uploader, in server memory until the session expires; the 1 MB cap bounds that. Do not put an `ECRF_HOSTED` key in the secrets: Streamlit copies top-level secrets into the environment over the host's own value, so the apps treat that key as on whatever it says. The switch fails closed: any value other than empty, `0`, `false`, `no` or `off` turns hosted mode on, and so does a secrets file that exists but does not parse (for example `hosted = True` with a capital T), because Streamlit only logs that error on the server. Before you share the link, open the app and confirm that the "Public demo: synthetic data only" banner shows on the main page and at the top of the sidebar and that the uploaders and folder fields are grayed out; if the banner is missing, hosted mode is off.

## Screenshots

Captured from the in-browser pages (hosted mode, bundled synthetic data) after **Execute**; a local run on the stand-in path shows the same tables.

![Coding app results table: each adverse-event verbatim with its top three candidate terms, ranks and 99-prefixed placeholder codes](docs/img/meddra_results.png)

*Coding app: top three candidates per verbatim, with placeholder codes; the ranking comes from the `[SI]` lexical stand-in.*

![PHI app results: flagged spans such as invented phone numbers, names, a ZIP code and initials, with entity type, offsets, redaction probability and action](docs/img/phi_results.png)

*PHI app: one row per scrubbed span; every name and number shown is invented.*

![Risk app results: per-participant safety and discontinuation scores and categories with contributing factors, the fatal participant pinned to the top](docs/img/risk_results.png)

*Risk app: per-participant safety and discontinuation scores, sorted highest risk first, with the reasons for each.*

![Anomaly app results: flagged per-participant numeric outliers, cohort-wide drift per column, and per-lab drift](docs/img/anomaly_results.png)

*Anomaly app: flagged numeric outliers, cohort-wide drift per column and per-lab drift on the longitudinal demo.*

## Landing page

[`docs/index.html`](docs/index.html) is a one-page overview for GitHub Pages: the four apps, links to the in-browser apps in [`docs/app/`](docs/app/), the screenshots and both decks. It is published by GitHub Pages from `main`, folder `/docs` (Settings > Pages), at https://patrickiben.github.io/ecrf-pipeline-apps/. `docs/` also holds byte-identical copies of the two HTML decks so they render there; after editing a deck's HTML in `presentations/`, copy it into `docs/` too (QC check D1 fails otherwise).

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
   protocol file is needed — the app scores raw data against clearly-labeled built-in criteria tagged
   `[SI]`, and records that source in the audit.
5. **Anomaly app:** point at a folder of longitudinal files (one row per participant per visit) with a
   participant ID column (`USUBJID`) and one or more numeric columns to measure. Optional signals are detected
   by content/synonym and surfaced in pre-flight: a time/visit column (e.g. `VISITNUM`, `AVISITD`) enables
   drift, a categorical lab/site column (e.g. `LAB`) enables per-lab drift AND between-lab/site comparison,
   and any long free-text column
   (e.g. `LABCOM`, `AECOM`) is scanned for text outliers. Only flagged observations are emitted.
6. Set the operating point where one exists (coding gate default 0.88; redaction gate default 0.85).
   Whatever you end at is written to the audit with the run.

## Stand-in vs real components

Without the trained weights installed, Tiers 2–4 run as **labeled deterministic stand-ins** (`[SI]`
in the banner and audit): lexical retrieval for coding, guarded regexes for PHI spans, rule-based
probabilities, a transparent weighted rule engine for risk scoring, and — for the anomaly app — a robust-z numeric gate, a labeled 1-D-Wasserstein drift stand-in, and a
bag-of-words text-isolation stand-in. The PHI stand-in reproduces its worked trace exactly; the coding
stand-in is honest about being lexical — semantically-gapped verbatims flag to a human coder rather than auto-code. The anomaly app's drift path becomes **real Sinkhorn optimal transport** (`ot.sinkhorn2`) with `POT` + `scipy`, and its numeric-outlier corroborator becomes real **Isolation Forest** with `scikit-learn`; its text detector has no real model path and stays a labeled stand-in.

**The real model path (coding and PHI apps).** With the open-source runtimes installed (Cactus Needle3, hnswlib, Laya, XGBoost) and a **models dir** holding their weights and the trained gates, the coding and PHI apps run their real Tiers 2 to 4, air-gapped. [`eval/README.md`](eval/README.md) says how to install the pinned runtimes and build the models dir (`python eval/fetch_models.py --out models`), and [`docs/EVALUATION.md`](docs/EVALUATION.md) has what was measured, on synthetic data only: the real coding path reached the right preferred term at rank 1 for 78% of held-out verbatims against 54% for the stand-in and auto-coded 38% with no error, and the real PHI path left 91 of 308 held-out identifiers readable against 108 for the stand-in. A tier shows REAL only when its artifact loads; an artifact that is present but cannot be loaded, or a trained gate whose inputs are missing, **stops** the run rather than silently substituting a stand-in. The risk app has no trained-model path: a model file in its models dir stops the run.

## What this build does NOT do

No scanned-document / bounding-box path (input is tabular eCRF), no negation feature, no clinical
variable derivation, and nothing leaves the machine (in the browser build, nothing you load is uploaded
by the app). The PHI output is compliance-*enabling*, not a
certification; that remains an organizational determination. **The risk app is decision support — it
ranks and flags participants for human review but does NOT make a clinical determination**, and it scores
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
.github/workflows/qc.yml CI: runs tests/qc_test.py on every push and pull request in three variants (stand-in and
                         optional-extras on Python 3.12; browser-stack on Python 3.14.0 with the Streamlit, pandas,
                         numpy and pyarrow versions the in-browser pages run), and checks docs/app/ against the apps
                         (tools/sync_browser_apps.py --check)
sample_data/             the one SYNTHETIC cut the coding/PHI/risk apps read (+ generate.py to regenerate ae/lb/eg/vs/pe)
anomaly_data/            the anomaly app's own SYNTHETIC longitudinal demo (labs.csv + generate.py)
presentations/           Deck A (conceptual) and Deck B (implementation walkthrough), MD + HTML
docs/                    GitHub Pages landing page (index.html), byte-identical copies of the two HTML decks, screenshots (img/), .nojekyll
docs/app/                the in-browser build: four pages, launch.js, app.css, copies of the apps and data, pinned wheels
tools/                   sync_browser_apps.py (keeps docs/app/ in step; --check for CI) and the page template
USER_GUIDE.md            step-by-step instruction manual for running all four apps
tests/qc_test.py         portable end-to-end test harness (`python tests/qc_test.py` reports passed, failed, and skipped checks for the installed dependencies)
QC_REPORT.md             what was tested, what bugs were found and fixed, how to re-run the tests
```
