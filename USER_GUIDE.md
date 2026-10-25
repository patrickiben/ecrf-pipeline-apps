# User guide: eCRF pipeline apps

A step-by-step manual for running the four apps in this folder:

- **Coding QC assist** ([`meddra_app.py`](meddra_app.py)): proposes a MedDRA-style code
  (LLT, PT, HLT, HLGT, SOC) for each adverse-event verbatim, for a coder to review.
- **De-identification review assist** ([`phi_app.py`](phi_app.py)): finds and scrubs
  patient identifiers in free-text fields, for a person to review.
- **Participant risk screening** ([`risk_app.py`](risk_app.py)): scores each participant on risk to their safety
  (0 to 100) and risk of discontinuing (0 to 1) from AE, lab, ECG, vital-sign and physical-exam data. Both scores
  are capped, weighted rule sums, not probabilities.
- **Central statistical monitoring** ([`anomaly_app.py`](anomaly_app.py)): flags per-participant outliers and
  unusual free-text notes and measures cohort and per-lab drift over time, on longitudinal (per-visit) data.

They are **four independent programs** that read the same cut folder without interfering (Central statistical
monitoring reads its own longitudinal demo), run entirely on your machine with no network calls, and each write
their own audit log. To try them first with nothing installed, open the in-browser versions on the bundled
synthetic data (see *Try it in your browser* below). This guide covers installing, running all four apps on your
own files, reading the outputs, and troubleshooting. For *why* the coding and de-identification apps are built
this way, and a worked trace of exactly what a run produces, see the
[case study](https://patrickiben.github.io/ecrf-pipeline-apps/case-study.html) ([`docs/case-study.html`](docs/case-study.html));
for what was measured, see the [evaluation case study](https://patrickiben.github.io/ecrf-pipeline-apps/evaluation.html).

> **Tip:** each app also carries its own instructions: open the **"📖 How to use this app"** panel at the top of
> any app for the steps for that app. This file is the combined, printable reference for all four.

> **Before you use your own files:** the bundled data is synthetic, and none of these apps is a validated system
> or built to 21 CFR Part 11. The apps propose; they have no review, override or sign-off step, so review happens
> on the exported files.

---

## 1. Requirements and install

- **Python 3.10 or newer** (developed and tested on 3.14 with Streamlit 1.65 and pandas 3.0).
- The stand-in path needs only `pip install -r requirements.txt` (pandas, numpy, streamlit). No GPU, no network
  and no API keys.

Two ways to launch; pick one:

**Option A: one-command launchers (recommended).** Each script creates a `.venv` on first run and installs the
dependencies itself, then opens the app in your browser:

```bash
./run_meddra.sh        # Coding QC assist                 -> http://localhost:8501
./run_phi.sh           # De-identification review assist  -> http://localhost:8502
./run_risk.sh          # Participant risk screening       -> http://localhost:8503
./run_anomaly.sh       # Central statistical monitoring   -> http://localhost:8504
# Windows: run_meddra.bat / run_phi.bat / run_risk.bat / run_anomaly.bat
```

**Option B: manual.** `pip install -r requirements.txt`, then `streamlit run <app>.py`.

> The launchers opt out of Streamlit's first-run telemetry prompt and pin ports 8501 to 8504, so a fresh machine
> goes from double-click to running app with no interactive prompts.

**Optional extras (all apps still run without them):** `pip install pyreadstat` lets every app load SAS
`.sas7bdat` files (SDTM/ADaM dumps) as well as CSV; `pip install POT scipy` switches the monitoring app's drift
tier from its labeled `[SI]` 1-D Wasserstein stand-in to **real Sinkhorn optimal transport**; `pip install
scikit-learn` adds a real Isolation Forest corroborator to its numeric outliers. See
[requirements.txt](requirements.txt).

---

## 2. Quickstart: try the sample data first (60 seconds)

Before touching your own files, run each app against its demo cut:

1. Launch an app (`./run_meddra.sh`, `./run_phi.sh`, `./run_risk.sh` or `./run_anomaly.sh`).
2. In the sidebar, set **Cut folder path** to the matching demo cut: `sample_data` for the coding,
   de-identification and risk apps; `anomaly_data` for Central statistical monitoring.
3. For the Coding QC assist only, leave the dictionary as it is; the app finds `meddra_demo.csv` by itself. The
   risk and monitoring apps need no extra file; they score raw data against built-in `[SI]` criteria.
4. Confirm the **pre-flight** panel looks right, then click **Execute**.

[sample_data/README.md](sample_data/README.md) and [anomaly_data/README.md](anomaly_data/README.md) list exactly
what each run should show. Both demo cuts are synthetic; see their READMEs.

### Try it in your browser (no install)

The same four programs also run inside your browser tab, on the bundled synthetic data only:
[Coding QC assist](https://patrickiben.github.io/ecrf-pipeline-apps/app/meddra.html),
[De-identification review assist](https://patrickiben.github.io/ecrf-pipeline-apps/app/phi.html),
[Participant risk screening](https://patrickiben.github.io/ecrf-pipeline-apps/app/risk.html) and
[Central statistical monitoring](https://patrickiben.github.io/ecrf-pipeline-apps/app/anomaly.html).
Each page uses stlite (Streamlit on Pyodide, Python compiled to WebAssembly) to run the same program on your
device, so there is no server. The first visit downloads about 30 MB, then the app opens on the sample cut; click
**Execute** and save results with the download buttons (the output folder lives in the tab's memory). Only the
labeled `[SI]` stand-ins run in the browser.
Privacy: runs in your browser; files are processed on your device and not uploaded by the app; the page is
downloaded from GitHub Pages and the CDN, which see your IP address; synthetic data only; not a validated or Part 11
system.

> **Hosted demo mode.** The in-browser pages, and any public server deployment you run yourself, run with hosted
> mode on (the environment variable `ECRF_HOSTED=1`, or the Streamlit secret `hosted = true` on a server). The app
> then shows a banner ("Public demo: synthetic data only..."), locks every uploader and path input to the bundled
> synthetic cut, writes its outputs to a per-session temporary folder and records `hosted_mode=true` in the audit;
> you only confirm the pre-flight panel and click **Execute**. On your own machine nothing is set, so everything in
> this guide applies unchanged and the audit records `hosted_mode=false`. Use a local run for real data. Server
> deployment notes are in the [README](README.md#serving-the-apps-from-your-own-server).

---

## 3. Coding QC assist (`meddra_app.py`)

### What it needs
- **Domain CSVs** containing the verbatim terms to code (for example `ae.csv`). The verbatim column is located by
  *name synonym* inside whatever loads, not by file name, so a non-`ae` domain works too. Recognized synonyms:
  `AETERM`, `VERBATIM`, `AE_TERM`, `REPORTED_TERM`.
- **One MedDRA dictionary**, in exactly one of two shapes (see below). MedDRA is licensed; the app records the
  dictionary it was given and does not check a subscription. The bundled `meddra_demo.csv` is synthetic, not MedDRA.

### Step by step

1. **Point at your data** (sidebar section *📂 1*). Type a folder path or upload the domain CSVs directly. Every
   `*.csv` in the folder except one named `*meddra*` is loaded as a domain; a `meddra*.csv` is treated as the
   dictionary, not as data.

2. **Provide the dictionary** in exactly one shape:
   - **Flattened CSV (recommended):** upload it, or put a `meddra*.csv` in the cut folder and the app finds it.
     It needs an LLT-name and a PT-name column; `llt_code`, `pt_code`, `hlt_name`, `hlgt_name` and `soc_name` are
     detected by synonym when present.
   - **ASCII release (`.asc`):** give the folder containing `llt.asc / pt.asc / hlt.asc / hlgt.asc / soc.asc`
     (pipe-delimited). It is filtered to active terms (`currency == 'Y'`) and joined across the full chain. The
     `hlt.asc` and `hlgt.asc` files are optional; if they are absent, those levels simply do not appear on the
     candidates.

   > **The hierarchy.** MedDRA groups related preferred terms into **High Level Terms (HLT)** by anatomy,
   > pathology, physiology, etiology or function; HLTs link to **High Level Group Terms (HLGT)**; HLGTs group into
   > **System Organ Classes (SOC)**. The app carries the full LLT, PT, HLT, HLGT and SOC path on every candidate as
   > *evidence columns*.

3. **Set the operating point** (sidebar section *⚖ 2*). The **Auto-commit gate** slider (default **0.88**) is a
   reviewer-set threshold: candidates scoring at or above it auto-commit, and those below it go to a human coder.
   Whatever you end at is written to the audit with the run.

4. **Confirm the input (pre-flight)** (sidebar section *🎯 3* and the main panel). Pick the verbatim column from
   the dropdown (it lists every loaded column matching an AETERM synonym). The pre-flight panel shows the domains
   loaded, the dictionary source and row count, the detected columns, the **Hierarchy** chain this dictionary
   carries (for example `LLT > PT > HLT > HLGT > SOC`), and whether it has PT codes. *If your header spells the
   verbatim differently*, add it to `AETERM_SYNONYMS` at the top of `meddra_app.py`.

5. **Execute.** Click **🚀 Execute MedDRA Auto-Coding**. Results render on screen and are written to the output
   folder (default `meddra_output`).

### Reading the results (`ae_coded.csv`)
One row **per candidate** (top three), so a coder sees the full pre-filled list, not just the winner. Key columns:

| Column | Meaning |
|---|---|
| `VERBATIM` | The term exactly as typed (never rewritten). |
| `rank` | 1 is the top candidate; 2 and 3 are alternatives. |
| `LLT` / `AEDECOD` | Lowest-level term, and the preferred-term decode to write back. |
| `AEPTCD` | Preferred-term code. |
| `HLT`, `HLGT` | **Evidence columns**: the full hierarchy path; never scored and not SDTM write-back. |
| `AESOC` | System Organ Class. |
| `cosine`, `lev`, `jaro`, `S` | The readable numbers the decision is made from. |
| `AECODSTAT` | `AUTO_COMMIT_TO_SDTM` (rank 1 only) or `FLAGGED_FOR_HUMAN_CODER`; ranks 2 and 3 are `ALT_CANDIDATE`. |

> A **name-only dictionary** (no PT codes) forces *every* verbatim to a human coder, because there is no code to
> write to `AEPTCD`. The pre-flight panel warns you up front.

---

## 4. De-identification review assist (`phi_app.py`)

### What it needs
- **Domain CSVs only.** It needs **no dictionary** and ignores any `meddra*.csv` in the folder, so the apps can
  share one cut folder safely.

### How columns are discovered (content-based)
The app scans **every column that is not strictly numeric** (text, dates, coded values and flags alike), because
identifiers can hide in any of them and a pre-specified list of column names is bound to have gaps. Only columns
pandas typed as a number are skipped. There is no name rule to edit; your control point is the confirmation
multiselect below.

> ⚠ Structured fields (dates, IDs) are scanned too. If one matches an identifier pattern (for example an ISO date
> matching the date-of-birth rule), it will be flagged. Review flags before trusting them, or deselect a known-safe
> column in step 4.

### Step by step

1. **Point at your data** (sidebar section *📂 1*: folder path, uploads, or both).
2. **Read how discovery works** (sidebar section *🔎 2* explains the content-based rule).
3. **Set the operating point** (sidebar section *⚖ 3*). The **Redaction gate** slider (default **0.85**) is a
   reviewer-set threshold, recorded in the audit.
4. **Confirm the columns to scan** (sidebar section *🎯 4* and the main pre-flight panel). Every non-numeric
   column is pre-selected; **deselect any you do not want scrubbed** (for example a date or coded field you know
   is safe). The panel shows exactly which columns will be scanned in each domain.
5. **Execute.** Click **🚀 Execute PII/PHI Flagging**.

### Reading the results
- **`phi_flags.csv`** has one row **per scrubbed span**: `DOMAIN`, `USUBJID`, `ROW`, `FIELD`, `SPAN`, `ENTITY`,
  in-field `START`/`END`, `P_REDACT` and `ACTION`. It is the record of exactly what was masked, with what
  confidence, at what position.
- **`sanitized/<domain>.csv`** is a copy of each scanned domain carrying the original columns plus `SAN_<field>`
  (the scrubbed text) and `<field>_PHI_FLAG` (`Y` if that cell changed, else `N`). Missing values stay missing,
  never `"nan"`.

> **Both files still contain the identifiers:** `SPAN` holds each redacted value, and the sanitized files keep the
> original column beside the scrubbed copy. Treat them as PHI. To share a scrubbed table, keep only the `SAN_`
> columns and the ones you know are safe.

**Direct and indirect identifiers.** A *direct* identifier (name, phone, email, MRN, date of birth) is scrubbed on
its own merit. An *indirect* attribute (age, ZIP code, initials) is scrubbed **only when two or more co-occur in the
same field**: the "mosaic" rule that catches a re-identification risk no single value shows.

**What the stand-in finds.** Names only after a title (Patient, Mr, Ms, Mrs, Dr) or in surname-comma form; phone
numbers with ten digits; emails; MRNs only as `123-456-78`; dates of birth as `MM/DD/YYYY` or `YYYY-MM-DD`; five-digit
ZIP codes; initials such as `J.M.`; ages written "NN-year-old" or "NN yo". It has no pattern for addresses, SSNs or
rare conditions. On held-out synthetic notes it left 108 of 308 identifiers readable, mostly 8-digit MRNs, 7-digit
phone numbers, M/D/YYYY dates and untitled names; the real model path left 91. Every output needs human review.

---

## 5. Participant risk screening (`risk_app.py`)

> ⚠ This app is **decision support, not a clinical determination.** It ranks and flags participants for human
> review; it does not diagnose, predict an outcome with validated accuracy, or replace medical judgment.

### What it needs
- **Safety-domain CSVs:** `ae` (adverse events), `lb` (labs), `eg` (ECG/QTc), `vs` (vital signs) and/or `pe`
  (physical exam), each with a participant ID column (`USUBJID`). At least one is required; the rest are optional
  but recommended. Labs and vitals carry source-system flags (`ABNORMAL`, `CLINSIG`) when present, and AEs carry an
  outcome field (`AEOUTCOME`) that backs up any fatal flag with explicit evidence. There is **no SAP or protocol
  file**: the app scores raw data against clearly labeled built-in criteria tagged `[SI]`.

### How files are classified (content-based)
Each CSV is classified by its **signature columns**, not its file name, so `ae.csv`, `adverse_events.csv` or an
oddly named vendor dump all work. A file with a severity or term column is AE; one with an upper-limit-of-normal
column is labs; one with a QTc column is ECG; and so on. A stray `meddra*.csv` is ignored (it belongs to the Coding
QC assist).

### Step by step

1. **Point at your data** (sidebar section *📂 1*: folder path, uploads, or both). Every `*.csv` or `.sas7bdat`
   except one named `*meddra*` loads; each is classified by content. No SAP or protocol file is needed.
2. **Set outputs** (sidebar section *⚖ 2*): the output folder (default `risk_output`) and a models dir field. This
   build has no trained risk model, so leave the models dir empty: a `risk_model.json` there stops the run rather
   than being ignored. There is no gate slider; the operating point is the built-in `[SI]` criteria, recorded in
   the audit.
3. **Confirm the input (pre-flight).** Check which domains loaded and how each was classified, plus the
   participant count.
4. **Execute.** Click **🚀 Execute Risk Scoring**.

### How scoring works (`[SI]` transparent engine)
- **Safety score (0 to 100)** is the sum of four capped components: adverse events (severity-weighted, times 1.5
  if serious), labs breaching their built-in multiple of the upper limit of normal, QTc at or over the cardiac
  limit, and vital-sign breaches. A **fatal outcome sets the safety score to 100 and the category to CRITICAL**, so
  a fatal participant always ranks at or above every non-fatal one.
- **Discontinuation score (0 to 1)** adds serious-AE burden, the share of related AEs, maximum severity, a fatal
  flag, grade 3 or higher labs, QTc and vital-sign breaches and source-system clinically significant findings, and
  caps the total at 1.
- Neither score is a probability. A fatal outcome's contributing factors cite its `AEOUTCOME=DIED` evidence, so
  "fatal" is backed by data rather than inferred from severity alone. Categories come from built-in `[SI]` cuts; a
  human-readable **contributing factors** column explains *why* each participant landed where they did.

### Reading the results (`risk_scores.csv`)
One row per participant: `USUBJID`, both scores and categories, and a human-readable **`contributing_factors`**
string that explains *why* each participant landed where they did (including any fatal outcome with its
`AEOUTCOME=DIED` evidence). The raw counts, maximum severity and fatal flag drive the scores but are not exported;
read the reasoning from `contributing_factors`. Sort by `safety_risk_score` to triage. The on-screen table is
pre-sorted highest risk first (fatal participants pinned to the top), with a category summary.

---

## 6. Central statistical monitoring (`anomaly_app.py`)

> ⚠ This app is **decision support, not a data-quality certification or a clinical determination.** It ranks and
> flags participants and columns for human review; it does not certify your data or make a medical judgment. Its
> checks are of the kind ICH E6(R3) calls centralized monitoring (section 3.11.4.2); it is not a risk-based quality
> management system.

### What it needs
- A folder (or upload) of **longitudinal** files, one row per participant per visit, with a participant ID column
  (`USUBJID`) and one or more numeric columns to measure. CSV or SAS `.sas7bdat`.
- Optional signals, each shown in pre-flight when present: a **time/visit column** (for example `VISITNUM` or
  `AVISITD`) enables drift; a categorical **lab/site column** (for example `LAB`) enables per-lab drift; any long
  **free-text column** (for example `LABCOM` or `AECOM`) is scanned for text outliers. A missing optional column
  turns that signal off and shows "OFF" in pre-flight, so nothing is hidden.

### What it detects (three separate signals)
Data can be unusual in many ways, so the app runs three independent detectors with fast, scalable algorithms:
- **Numeric outliers:** a participant whose change from baseline deviates far from the cohort's own distribution
  of changes (robust z-score, median and MAD), corroborated by an **Isolation Forest** when `scikit-learn` is
  installed. A uniform shift of the whole population does NOT flag everyone; only participants who jump beyond the
  typical within-participant change do.
- **Distributional drift:** for each measurable column, how far the whole cohort's distribution moved between an
  early ("reference") and a late ("current") window, measured with **Sinkhorn optimal transport** when `POT` and
  `scipy` are installed. It runs cohort-wide AND per `LAB × column`, so a site or lab assay change that cohort-wide
  drift dilutes still stands out.
- **Text outliers:** free-text notes whose content is isolated from the other notes in that field (retrieval
  isolation), catching unusual or erroneous entries no numeric check sees.

Only **flagged** observations are written; normal participants and routine notes do not appear in the output.

### Step by step

1. **Point at your data** (sidebar section *📂 1*: folder path, uploads, or both). Every `*.csv` or `.sas7bdat`
   except one named `*meddra*` loads; columns are located by content or synonym, not by file name.
2. **Set outputs** (sidebar section *⚖ 2*): the output folder (default `anomaly_output`) and a models dir field.
   This build has no trained anomaly model, so leave the models dir empty: an `anomaly_model.json` there stops the
   run rather than being ignored. There is no gate slider; the operating point is the built-in `[SI]` criteria,
   recorded in the audit.
3. **Confirm the input (pre-flight).** Check which measurable numeric columns were found, whether a time column
   was detected (drift on or off), whether a lab/site column was detected (per-lab drift on or off), and which
   free-text columns will be scanned for text outliers.
4. **Execute.** Click **🚀 Execute Anomaly & Drift Detection**.

### How it works (`[SI]` and real)
- **Numeric outlier score (0 to 1)** = `min(1, max|robust z| / ANOM_Z_TOP)`, where the robust z compares each
  participant's change from baseline with the cohort's distribution of changes and `ANOM_Z_TOP` defaults to 8. A
  participant is flagged when their worst |z| is at least `ANOM_Z` (3). This mapping keeps scores
  **discriminative** in [0, 1] instead of every flagged participant sitting at exactly 1.0. The **Isolation
  Forest** (scikit-learn) corroborates each flag; the `detectors` column says which detectors agreed.
- **Drift** = the transport distance between the reference and current windows for each measurable column:
  **Sinkhorn optimal transport** (`ot.sinkhorn2`, a linear L1 cost regularized to the reference window's robust
  spread) when Python Optimal Transport and scipy are installed, else a labeled **1-D Wasserstein stand-in
  `[SI]`**. It is reported as a unitless **drift ratio** (distance divided by the reference spread), cohort-wide
  AND per `LAB × column` (drift over time within each lab or site).
- **Between-lab/site comparison** = for each numeric column and each lab, the transport distance from that lab's
  current-window distribution to the pooled distribution of all other labs (leave-one-out), divided by the robust
  spread, giving a unitless `between_lab_ratio`. A lab or site that systematically measures differently from all
  the others shows a high ratio; labs that agree with the rest show about 0. This answers *"how different is this
  lab or site from all the others?"*, which is different from per-lab drift (how much one lab moved over time).
- **Text outlier score (0 to 1)** = retrieval isolation of each note against the other notes in its field, by a
  labeled **bag-of-words isolation stand-in `[SI]`**. A routine note is a near-duplicate of others (isolation
  about 0); an unusual or erroneous note has no close neighbor (isolation near 1). Only notes at or above the flag
  threshold are written. This build has no real text model, so this tier stays `[SI]` whatever is installed.
- Categories come from built-in `[SI]` cuts; `extreme_columns`, the drift rows and the flagged notes explain *why*
  each observation landed where it did.

### Reading the results (`anomalies.csv`, `drift.csv`, `lab_drift.csv`, `lab_compare.csv`, `text_anomalies.csv`)
- **`anomalies.csv`**, one row per FLAGGED participant: anomaly score, category, which detectors fired, and the
  extreme columns.
- **`drift.csv`**, one row per measurable column (cohort-wide): window sizes, transport distance, drift ratio,
  category.
- **`lab_drift.csv`**, one row per `LAB × column`: drift over time within each lab or site (same shape as drift).
- **`lab_compare.csv`**, one row per `LAB × column`: the between-lab comparison, each lab's current window against
  the pooled others (leave-one-out transport distance, ratio, category).
- **`text_anomalies.csv`**, one row per FLAGGED note: participant, field, isolation score, category and the note
  text.

The on-screen tables are pre-sorted highest first, with a category summary. See
[anomaly_data/README.md](anomaly_data/README.md) for the demo's injected signals and what a correct run shows.

---

## 7. Stand-in vs real components (`[SI]` / `[RM]`)

Without trained weights installed, Tiers 2 to 4 run as **labeled deterministic stand-ins**, shown as `[SI]` in the
mode banner and recorded per tier in every audit row:

- **Coding:** lexical retrieval (a hashed bag-of-words and cosine). Because it is lexical, verbatims that differ in
  wording from every dictionary term go to a human coder rather than being auto-coded.
- **De-identification:** guarded regular expressions for spans plus rule-based probabilities. It reproduces its
  worked trace exactly, because identifier detection here is pattern-shaped and the scrub is a string replace.
- **Risk screening:** a transparent weighted rule engine driven by declared criteria. Its weights are constants
  written to the audit, not hidden. This build has no trained-model path for it.
- **Central statistical monitoring:** numeric outliers use a robust z-score (median and MAD) as the interpretable
  gate, corroborated by an **Isolation Forest** when `scikit-learn` is installed. Drift uses a labeled **1-D
  Wasserstein stand-in** by default; install `POT` and `scipy` and it becomes **real Sinkhorn optimal transport**
  (`ot.sinkhorn2`). Text outliers use a labeled **bag-of-words isolation stand-in**; this build has no real
  text-isolation model, so that tier stays `[SI]` whatever is installed. The other two switch their tier to REAL
  with identical output columns.

**Coding and de-identification: the real path.** Install the pinned real runtimes (Cactus Needle3, `hnswlib`, Laya,
XGBoost), build a models dir with `python eval/fetch_models.py --out models` (see [eval/README.md](eval/README.md)),
copy it to the machine that runs the app and type its path into **Models dir** in the sidebar. The banner then
switches tier by tier to **REAL**, and only for a tier whose artifact actually loaded; columns, gates and exports do
not move. The apps read only that folder and never reach the network. A trained artifact that is present but whose
runtime is missing, or that fails to load, or a trained gate whose inputs did not load, **stops** the run rather than
silently substituting a stand-in: the app never presents a `[SI]` number as real. In the de-identification app,
Needle3's proposals are used only behind the trained gate. The real path runs locally only, not in the browser.

What the real path does on synthetic data, measured, is in the
[evaluation case study](https://patrickiben.github.io/ecrf-pipeline-apps/evaluation.html)
([docs/EVALUATION.md](docs/EVALUATION.md) is the long form). In short: better than the stand-in on misspelled
verbatims and on names without a title, no better on colloquial verbatims (they still go to a human coder), still
leaving 91 of 308 identifiers readable, and slow on a CPU (about 0.4 s per verbatim and 1 to 1.6 s per note, one
at a time). The risk and monitoring apps have no trained-model path; a model file in their models dir stops the
run.

---

## 8. Outputs reference

| App | File | Contents |
|---|---|---|
| Coding QC assist | `ae_coded.csv` | One row per candidate (top three) with decode, codes, HLT/HLGT evidence, scores and status. |
| Coding QC assist | `audit_log.csv` | Files read, verbatim column, dictionary source and hash, hierarchy, per-tier path, gate, latency. |
| De-identification review assist | `phi_flags.csv` | One row per scrubbed span (field, span text, entity, offsets, confidence, action). Contains identifiers. |
| De-identification review assist | `sanitized/<domain>.csv` | Original columns plus `SAN_<field>` and `<field>_PHI_FLAG`. Contains identifiers in the original columns. |
| De-identification review assist | `audit_log.csv` | Files read, selected columns, discovery mode, per-tier path, gate, tag scheme, latency. |
| Participant risk screening | `risk_scores.csv` | One row per participant: both scores and categories and a human-readable contributing-factors string (counts, severity and fatal flag are internal signals, not exported). |
| Participant risk screening | `audit_log.csv` | Files and classifications read, criteria source (`[SI]`) and every threshold in force, path, category distribution, latency. |
| Central statistical monitoring | `anomalies.csv` | One row per FLAGGED participant: anomaly score, category, which detectors fired, extreme columns. |
| Central statistical monitoring | `drift.csv` | One row per measurable column (cohort-wide): window sizes, transport distance, drift ratio, category. |
| Central statistical monitoring | `lab_drift.csv` | One row per `LAB × column`: drift over time within each lab or site (same shape as drift). |
| Central statistical monitoring | `lab_compare.csv` | One row per `LAB × column`: each lab against the pooled others (leave-one-out transport distance, ratio, category). |
| Central statistical monitoring | `text_anomalies.csv` | One row per FLAGGED note: participant, field, isolation score, category, note text. |
| Central statistical monitoring | `audit_log.csv` | Files read, measurable, time, lab and free-text columns, numeric/drift/text paths (`[SI]` or real), every threshold in force, distributions, latency. |

Each audit log records the **contract** (which files and columns), the **per-tier path** that ran (REAL or `[SI]`)
and every **effective threshold**, so a run is reproducible from its audit alone. The four apps write separate
`audit_log.csv` files in their own output folders; they share no module. An audit log is a plain CSV, not a
protected audit trail.

---

## 9. Troubleshooting and FAQ

- **"No MedDRA source found"** (Coding QC assist): provide exactly one dictionary shape. Upload a flattened CSV,
  set the `.asc` folder path, or name your file `meddra*.csv` inside the cut folder.
- **Everything goes to a human coder:** your dictionary is probably name-only (no PT codes); the pre-flight panel
  says "Has PT codes → NO". Add a code column or accept manual coding.
- **My verbatim column is not detected:** rename it to `AETERM` in the CSV, or add its spelling to
  `AETERM_SYNONYMS` at the top of `meddra_app.py`. Do not hard-code a column elsewhere.
- **A date or ID column got flagged (De-identification review assist):** that is content-based discovery working
  as designed; it scans every non-numeric field. If you know that column is safe, deselect it in the pre-flight
  multiselect and run again; review any flags before trusting a scrub.
- **"No safety domains loaded" (Participant risk screening):** point at a folder with at least one of
  `ae`/`lb`/`eg`/`vs`/`pe`, or upload files. A file is only scored if it has a participant ID column (`USUBJID`).
- **A domain shows as unrecognized (Participant risk screening):** its columns do not match the synonyms. Rename
  them (for example severity to `AESEV`) or add the spelling to `SYN` at the top of `risk_app.py`.
- **"No measurable columns", or drift shows OFF (Central statistical monitoring):** your numeric columns may be
  stored as text (convert them), or no time/visit column was detected; add one (for example `VISITNUM`) to enable
  drift. Per-participant outliers still run without it. Add an unusual header spelling to `SYN` at the top of
  `anomaly_app.py`.
- **Blank cells:** missing values stay missing through all four apps (never `"nan"`), so an empty field correctly
  reports flag `N` or no code rather than scanning silently clean.

---

## 10. What this build does NOT do

No scanned-document or bounding-box path (the input is tabular eCRF data), no negation feature and no clinical
variable derivation, and nothing leaves the machine (in the browser build, nothing you load is uploaded by the app).
No review, override or sign-off step, and no reviewer identity. Not a validated system and not built to 21 CFR
Part 11. The de-identification output supports a review; it is not a certification, which remains an
organizational determination, and its files still contain the identifiers. **Participant risk screening is
decision support only:** it makes no clinical determination and scores raw data against built-in `[SI]` criteria
rather than parsing a protocol or SAP. **Central statistical monitoring is decision support too:** it ranks and
flags participants and columns for human review but does not certify data quality, make a clinical determination
or replace a validated model (install `POT` and `scipy` for real Sinkhorn drift; the default `[SI]` path is a
labeled 1-D Wasserstein stand-in). See the [case study](https://patrickiben.github.io/ecrf-pipeline-apps/case-study.html)
for the full limits.

---

## 11. Verifying your install

A portable end-to-end test harness ships in [`tests/qc_test.py`](tests/qc_test.py). With the app dependencies
installed:

```bash
pip install -r requirements.txt && python tests/qc_test.py
```

Exit code **0 means every check passed**; the last line reports how many passed, failed and were skipped for the
installed dependencies (with `requirements.txt` only, the checks that need `pyreadstat` or `scikit-learn` do not
run). The harness drives all four apps end to end, including a synthetic `.asc` release with HLT/HLGT and the
currency filter, content-based column discovery in the de-identification app, SAS `.sas7bdat` input routing, the
risk app against `sample_data/` (anchor participants landing in their expected categories, valid score ranges, full
category coverage, `[SI]` criteria recorded in the audit log) and the monitoring app catching its injected drift
column and per-participant outliers. Output is checked to be bit-identical across two runs; hosted demo mode, the
`docs/` pages and the in-browser build in `docs/app/` are checked too. Leave `ECRF_HOSTED` unset and keep any
Streamlit secrets file away while you run it: the hosted checks set both themselves. What was checked and what bugs
were found and fixed: [QC_REPORT.md](QC_REPORT.md).
