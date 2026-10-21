# User Guide — eCRF Pipeline Apps

A step-by-step manual for running the four apps in this folder:

- **[meddra_app.py](meddra_app.py)** — *MedDRA Auto-Coding Engine*: proposes a MedDRA code
  (LLT → PT → HLT → HLGT → SOC) for each adverse-event verbatim.
- **[phi_app.py](phi_app.py)** — *PII/PHI Flagging & Redaction Engine*: finds and scrubs
  patient identifiers in free-text fields.
- **[risk_app.py](risk_app.py)** — *Participant Safety & Discontinuation Risk Scoring*: scores each
  subject on risk to their safety (0–100) and risk of discontinuing (0–1) from AE + lab/ECG/vitals/PE.
- **[anomaly_app.py](anomaly_app.py)** — *Data Anomaly & Distributional-Drift Detection*: flags
  per-subject anomalies and measures cohort drift over time with Sinkhorn optimal transport, on
  longitudinal (per-visit) data.

They are **four independent programs** that read the same cut folder without interfering (the anomaly app reads its own longitudinal demo), run entirely on your machine (air-gapped), and each write their own audit log. This guide covers installing, running all four apps on real data, reading the outputs, and troubleshooting. For *why* it is built this way, see [Deck A](presentations/deck_a_four_tier_pipeline.md); for a worked trace of exactly what a run produces, see [Deck B](presentations/deck_b_implementation_walkthrough.md).

> **Tip:** each app also carries its own instructions built in — open the **“📖 How to use this
> app”** panel at the top of any app for the steps relevant to that specific app. This file is the
> combined, printable reference covering all four apps.

---

## 1. Requirements & install

- **Python 3.10+** (developed and tested on 3.14 with Streamlit 1.65 / pandas 3.0).
- The stand-in path needs only: `pip install -r requirements.txt`
  (pandas, numpy, streamlit). No GPU, no network, no API keys.

Two ways to launch — pick one:

**Option A — one-command launchers (recommended).** Each script creates a `.venv` on first run and
installs dependencies itself, then opens the app in your browser:

```bash
./run_meddra.sh        # coding app  → http://localhost:8501
./run_phi.sh           # PHI app     → http://localhost:8502
./run_risk.sh          # risk app    → http://localhost:8503
./run_anomaly.sh       # anomaly app → http://localhost:8504
# Windows: run_meddra.bat / run_phi.bat / run_risk.bat / run_anomaly.bat
```

**Option B — manual.** `pip install -r requirements.txt` then `streamlit run <app>.py`.

> The launchers opt out of Streamlit's first-run telemetry prompt and pin ports 8501–8504, so a
> fresh machine goes from double-click to running app with no interactive prompts.

**Optional extras (all apps still run without them):** `pip install pyreadstat` lets every app load SAS `.sas7bdat` files (SDTM/ADaM dumps) in addition to CSV; `pip install POT scipy` flips the anomaly app's drift tier from its labelled `[SI]` 1-D-Wasserstein stand-in to **real Sinkhorn optimal transport**. See [requirements.txt](requirements.txt).

---

## 2. Quickstart — try the sample data first (60 seconds)

Before touching real data, run each app against its demo cut:

1. Launch an app (`./run_meddra.sh`, `./run_phi.sh`, `./run_risk.sh`, or `./run_anomaly.sh`).
2. In the sidebar, set **Cut folder path** to the matching demo cut — `sample_data` for the coding, PHI and risk apps; `anomaly_data` for the anomaly app.
3. For the coding app only: leave the dictionary as-is — it auto-finds `meddra_demo.csv`. The risk and anomaly apps need no extra file — they score raw data against built-in `[SI]` criteria.
4. Confirm the **pre-flight** panel looks right, then click **Execute**.

[sample_data/README.md](sample_data/README.md) and [anomaly_data/README.md](anomaly_data/README.md) list precisely what each run should show. Both demo cuts are synthetic — see their READMEs.

> **Hosted demo mode.** A public deployment (for example on Streamlit Community Cloud) should run with the Streamlit
> secret `hosted = true`, or the environment variable `ECRF_HOSTED=1` on other hosts. The app then shows a banner
> ("Public demo: synthetic data only..."), locks every uploader and path input to the bundled synthetic cut, writes
> its outputs to a per-session temporary folder and records `hosted_mode=true` in the audit; you only confirm the
> pre-flight panel and click **Execute**. On your own machine nothing is set, so everything in this guide applies
> unchanged and the audit records `hosted_mode=false`. Use a local run for real data. Deployment steps are in the
> [README](README.md#deploy-your-own-demo).

---

## 3. App 1 — MedDRA Auto-Coding (`meddra_app.py`)

### What it needs
- **Domain CSVs** containing the verbatim terms to code (e.g. `ae.csv`). The verbatim column is located
  by *name synonym* inside whatever loads — not by file name — so a non-`ae` domain works too.
  Recognised synonyms: `AETERM`, `VERBATIM`, `AE_TERM`, `REPORTED_TERM`.
- **One MedDRA dictionary**, in exactly one of two shapes (see below).

### Step-by-step

1. **Point at your data** — sidebar section *📂 1*. Either type a folder path or upload the domain CSVs
   directly. Every `*.csv` in the folder except one named `*meddra*` is loaded as a domain; a
   `meddra*.csv` is treated as the dictionary, not data.

2. **Provide the dictionary** — choose exactly one shape:
   - **Flattened CSV (recommended):** upload it, or drop a `meddra*.csv` in the cut folder and it is
     auto-found. It needs an LLT-name + PT-name column; `llt_code`, `pt_code`, `hlt_name`, `hlgt_name`,
     `soc_name` are detected by synonym when present.
   - **ASCII release (`.asc`):** give the folder containing `llt.asc / pt.asc / hlt.asc / hlgt.asc /
     soc.asc` (pipe-delimited). It is filtered to active terms (`currency == 'Y'`) and joined across the
     full chain. The `hlt.asc`/`hlgt.asc` files are optional — if absent, those levels simply don't appear
     on the candidates.

   > **The hierarchy.** MedDRA groups related preferred terms into **High Level Terms (HLT)** by
   > anatomy/pathology/physiology/aetiology/function; HLTs link to **High Level Group Terms (HLGT)**;
   > HLGTs group into **System Organ Classes (SOC)**. The app carries the full `LLT → PT → HLT → HLGT →
   > SOC` path on every candidate as *evidence columns*.

3. **Set the operating point** — sidebar section *⚖ 2*. The **Auto-commit gate** slider (default
   **0.88**) is a reviewer-set threshold: candidates scoring at/above it auto-commit, below it route to a
   human coder. Whatever you end at is written to the audit with the run.

4. **Confirm the input (pre-flight)** — sidebar section *🎯 3* and the main panel. Pick the verbatim
   column from the dropdown (it lists every loaded column matching an AETERM synonym). The pre-flight
   panel shows: domains loaded, dictionary source + row count, detected columns, the **Hierarchy** chain
   this dictionary carries (e.g. `LLT > PT > HLT > HLGT > SOC`), and whether it has PT codes. *If your
   header spells the verbatim differently*, add it to `AETERM_SYNONYMS` at the top of `meddra_app.py`.

5. **Execute** — click **🚀 Execute MedDRA Auto-Coding**. Results render on screen and are written to the
   output folder (default `meddra_output`).

### Reading the results (`ae_coded.csv`)
One row **per candidate** (top-3), so a human coder sees the full pre-populated list, not just the winner.
Key columns:

| Column | Meaning |
|---|---|
| `VERBATIM` | The term exactly as typed (never rewritten). |
| `rank` | 1 = top candidate; 2–3 are alternatives. |
| `LLT` / `AEDECOD` | Lowest-level term / the preferred-term decode to write back. |
| `AEPTCD` | Preferred-term code. |
| `HLT`, `HLGT` | **Evidence columns** — full hierarchy path; never scored, not SDTM write-back. |
| `AESOC` | System Organ Class. |
| `cosine`, `lev`, `jaro`, `S` | The readable numbers the decision is made from. |
| `AECODSTAT` | `AUTO_COMMIT_TO_SDTM` (rank 1 only) or `FLAGGED_FOR_HUMAN_CODER`; ranks 2–3 are `ALT_CANDIDATE`. |

> A **name-only dictionary** (no PT codes) forces *every* verbatim to route to a human — an `AEPTCD`
> without a number is not submission-grade. The pre-flight panel warns you up front.

---

## 4. App 2 — PII/PHI Flagging & Redaction (`phi_app.py`)

### What it needs
- **Domain CSVs only.** It needs **no dictionary** and ignores any `meddra*.csv` in the folder, so all
  three apps can share one cut folder safely.

### How columns are discovered (content-based)
The PHI app scans **every column that is not strictly numeric** — text, dates, coded values and flags
alike — because PHI can hide in any of them and a pre-specified list of column names is guaranteed to have
gaps. Only columns pandas typed as a number are skipped. There is no name rule to edit; your control point
is the confirmation multiselect below.

> ⚠ Structured fields (dates, IDs) are scanned too. If one matches an identifier pattern — e.g. an ISO date
> matching the DOB rule — it will be flagged. Review flags before trusting them, or deselect a known-safe
> column in step 4.

### Step-by-step

1. **Point at your data** — sidebar section *📂 1* (folder path and/or upload).
2. **Read how discovery works** — sidebar section *🔎 2* explains the content-based rule.
3. **Set the operating point** — sidebar section *⚖ 3*. The **Redaction gate** slider (default **0.85**) is
   a reviewer-set threshold, recorded in the audit.
4. **Confirm the columns to scan** — sidebar section *🎯 4* and the main pre-flight panel. Every non-numeric
   column is pre-selected; **deselect any you do not want scrubbed** (e.g. a date or coded field you know is
   safe). The panel shows exactly which columns will be scanned per domain.
5. **Execute** — click **🚀 Execute PII/PHI Flagging**.

### Reading the results
- **`phi_flags.csv`** — one row **per scrubbed span**: `DOMAIN`, `USUBJID`, `ROW`, `FIELD`, `SPAN`, `ENTITY`,
  in-field `START`/`END`, `P_REDACT`, and `ACTION`. This is the audit evidence of exactly what was masked, with
  what confidence, at what position.
- **`sanitized/<domain>.csv`** — a copy of each scanned domain carrying the original columns plus `SAN_<field>`
  (the scrubbed text) and `<field>_PHI_FLAG` (`Y` if that cell changed, else `N`). Missing values stay missing —
  never turned into `"nan"`.

**Direct vs indirect identifiers.** A *direct* identifier (name, phone, MRN, DOB, address, SSN) is scrubbed on
its own merit. An *indirect* attribute (age, postcode/ZIP, initials, rare condition) is scrubbed **only when two
or more co-occur in the same field** — the "mosaic" rule that catches re-identification risk no single value shows.

---

## 5. App 3 — Participant Safety & Discontinuation Risk Scoring (`risk_app.py`)

> ⚠ This app is **decision support, not a clinical determination.** It ranks and flags subjects for human
> review; it does not diagnose, predict an outcome with validated accuracy, or replace medical judgement.

### What it needs
- **Safety-domain CSVs** — `ae` (adverse events), `lb` (labs), `eg` (ECG/QTc), `vs` (vital signs), and/or
  `pe` (physical exam) — each with a subject-id column (`USUBJID`). At least one is required; the rest are
  optional but recommended. Labs/vitals carry source-system flags (`ABNORMAL`, `CLINSIG`) when present, and AEs
  carry an outcome field (`AEOUTCOME`) that backs up any fatal flag with explicit evidence. There is **no SAP or
  protocol file** — the app scores raw data against clearly-labelled built-in criteria tagged `[SI]`.

### How files are classified (content-based)
Each CSV is classified by its **signature columns**, not its file name — so `ae.csv`, `adverse_events.csv`, or an
oddly-named vendor dump all work. A file with a severity/term column → AE; one with an upper-limit-of-normal
column → labs; one with a QTc column → ECG; and so on. A stray `meddra*.csv` is ignored (it belongs to the coding
app).

### Step-by-step

1. **Point at your data** — sidebar section *📂 1* (folder path and/or upload). Every `*.csv`/`.sas7bdat` except one named
   `*meddra*` loads; each is classified by content. No SAP or protocol file is needed.
2. **Set outputs** — sidebar section *⚖ 2*: output folder (default `risk_output`) and an optional models dir for a
   real trained model. There is no gate slider here — the operating point is the built-in `[SI]` criteria, recorded in
   the audit.
3. **Confirm the input (pre-flight)** — check which domains loaded and how each classified, plus the subject count.
4. **Execute** — click **🚀 Execute Risk Scoring**.

### How scoring works (`[SI]` transparent engine)
- **Safety score (0–100)** = four capped components: adverse events (severity-weighted, ×1.5 if serious, **+35 for a
  fatal outcome**), labs breaching their SAP multiple, QTc at/over the cardiac limit, and vital-sign breaches. A
  **fatal outcome forces CRITICAL** regardless of score — death is by definition the highest safety risk.
- **Discontinuation score (0–1)** = serious-AE burden + relatedness fraction + max severity + fatal flag + grade≥3 labs
  + QTc/vital breaches, squashed to [0,1].
- A fatal outcome's contributing factors cite its `AEOUTCOME=DIED` evidence, so "fatal" is backed by data rather than inferred from severity alone. Categories come from built-in `[SI]` cuts; a human-readable **contributing factors** column explains *why* each subject landed where it did.

### Reading the results (`risk_scores.csv`)
One row per subject: `USUBJID`, both scores + categories, and a human-readable **`contributing_factors`** string that explains *why* each subject landed where it did (including any fatal outcome with its `AEOUTCOME=DIED` evidence). The raw counts / max-severity / fatal signals are internal — they drive scoring but are not exported; read the reasoning from `contributing_factors`. Sort by `safety_risk_score` to triage. The on-screen table is pre-sorted highest-risk first (fatal subjects pinned to the top) with a category summary.

---

## 6. App 4 — Data Anomaly & Distributional-Drift Detection (`anomaly_app.py`)

> ⚠ This app is **decision support, not a data-quality certification or clinical determination.** It ranks and flags subjects/columns for human review; it does not certify your data or make a medical judgement.

### What it needs
- A folder (or upload) of **longitudinal** files — one row per subject per visit — with a subject-id column (`USUBJID`) and one or more numeric columns to measure. CSV or SAS `.sas7bdat`.
- Optional signals, each surfaced in pre-flight when present: a **time/visit column** (e.g. `VISITNUM`, `AVISITD`) enables drift; a categorical **lab/site column** (e.g. `LAB`) enables per-lab drift; any long **free-text column** (e.g. `LABCOM`, `AECOM`) is scanned for text outliers. A missing optional column disables that signal and shows "OFF" in pre-flight — surfaced, not hidden.

### What it detects (three separate signals)
There are many ways data can be anomalous, so the app runs three independent detectors with fast, scalable algorithms:
- **Numeric outliers** — a subject whose change-from-baseline deviates far from the cohort's own distribution of changes (robust z-score, median/MAD), corroborated by **Isolation Forest**. A uniform population shift does NOT flag everyone; only individuals who jump beyond the typical within-subject change do.
- **Distributional drift** — per measurable column, how far the whole cohort's distribution moved between an early ("reference") and a late ("current") window, measured with **Sinkhorn optimal transport**. Runs cohort-wide AND per `LAB × column`, so a site/lab assay change that cohort-wide drift dilutes away still stands out.
- **Text outliers** — free-text notes whose content is isolated from the corpus of notes in that field (retrieval isolation), catching unusual or erroneous entries no numeric check sees.

Only **flagged** observations are emitted — normal subjects and routine notes do not appear in the output.

### Step-by-step

1. **Point at your data** — sidebar section *📂 1* (folder path and/or upload). Every `*.csv`/`.sas7bdat` except one named `*meddra*` loads; columns are located by content/synonym, not file name.
2. **Set outputs** — sidebar section *⚖ 2*: output folder (default `anomaly_output`) and an optional models dir for a real trained model. There is no gate slider — the operating point is the built-in `[SI]` criteria, recorded in the audit.
3. **Confirm the input (pre-flight)** — check which measurable numeric columns were found, whether a time column was detected (drift on/off), whether a lab/site column was detected (per-lab drift on/off), and which free-text columns will be scanned for text outliers.
4. **Execute** — click **🚀 Execute Anomaly & Drift Detection**.

### How it works (`[SI]` / real)
- **Numeric outlier score (0–1)** = `min(1, max|robust z| / ANOM_Z_TOP)` where the robust z is each subject's change-from-baseline against the cohort's distribution of changes and `ANOM_Z_TOP` defaults to 8. A subject is flagged when its worst |z| ≥ `ANOM_Z` (3). The mapping keeps scores **discriminative** in [0,1] instead of every flagged subject saturating at exactly 1.0. **Isolation Forest** (scikit-learn) corroborates each flag; the `detectors` column says which detector(s) agreed.
- **Drift** = transport distance between the reference and current windows per measurable column: **Sinkhorn optimal transport** (`ot.sinkhorn2`, linear L1 cost regularized to the reference robust spread) when Python Optimal Transport + scipy are installed, else a labelled **1-D-Wasserstein stand-in `[SI]`**. Reported as a unitless **drift ratio** (distance / reference spread). Runs cohort-wide AND per `LAB × column` (temporal drift within each lab/site).
- **Between-lab/site comparison** = for each numeric column and each lab, the transport distance from that lab's current-window distribution to the POOLED-OTHERS (leave-one-out) distribution, normalized by the robust spread → a unitless `between_lab_ratio`. A site/lab that systematically measures differently from every other site shows a high ratio; sites that agree with the rest show ~0. This answers *"how different is this lab/site from all the others?"* — distinct from per-lab drift, which asks how much one lab moved over time.
- **Text outlier score (0–1)** = retrieval isolation of each note against the corpus in its field: **Needle3/Laya** when installed, else a labelled **bag-of-words isolation stand-in `[SI]`**. A routine note is a near-duplicate of others (iso ≈ 0); an unusual/erroneous note has no close neighbour (iso → 1). Only notes at/above the flag threshold are emitted.
- Categories come from built-in `[SI]` cuts; `extreme_columns`, the drift rows, and the flagged notes explain *why* each observation landed where it did.

### Reading the results (`anomalies.csv`, `drift.csv`, `lab_drift.csv`, `lab_compare.csv`, `text_anomalies.csv`)
- **`anomalies.csv`** — one row per FLAGGED subject: anomaly score, category, which detector(s) fired, and the extreme columns.
- **`drift.csv`** — one row per measurable column (cohort-wide): window sizes, transport distance, drift ratio, category.
- **`lab_drift.csv`** — one row per `LAB × column`: temporal drift within each lab/site (same shape as drift).
- **`lab_compare.csv`** — one row per `LAB × column`: between-lab/site comparison, each lab's current-window distribution vs the pooled others (leave-one-out transport distance → ratio → category).
- **`text_anomalies.csv`** — one row per FLAGGED note: subject, field, isolation score, category, and the note text.

The on-screen tables are pre-sorted highest first with a category summary. See [anomaly_data/README.md](anomaly_data/README.md) for the demo's injected signals and what a correct run shows.

---

## 7. Stand-in vs real components (`[SI]` / `[RM]`)

Without trained weights installed, Tiers 2–4 run as **labelled deterministic stand-ins** — shown as `[SI]` in the mode
banner and recorded per tier in every audit row:

- **Coding:** lexical retrieval (a hashing bag-of-words + cosine). It is honest about being lexical — semantically-gapped
  verbatims flag to a human coder rather than auto-code.
- **PHI:** guarded regexes for spans + rule-based probabilities. It reproduces its worked trace exactly, because identifier
  detection is pattern-shaped and the scrub is a string replace.
- **Risk scoring:** a transparent weighted rule engine driven by declared criteria. Its weights are constants written to the
  audit — not hidden. A real deployment replaces Tier 3 with a trained, externally-validated survival/risk model and flips
  the banner to `[RM]`.
- **Anomaly & drift:** numeric outliers use a robust z-score (median/MAD) as the interpretable gate, corroborated by
  **Isolation Forest** — install `scikit-learn` and that detector runs for real. Drift uses a labelled **1-D-Wasserstein stand-in**
  by default; install `POT` + `scipy` and it becomes **real Sinkhorn optimal transport** (`ot.sinkhorn2`). Text outliers use a
  labelled **bag-of-words isolation stand-in**; install the open-source Needle3 (Cactus Compute) and Laya runtimes (not bundled with this repository) for real retrieval-isolation.
  Each flips its tier to REAL with identical output columns.

Install the real runtimes (`cactus-needle`, `hnswlib`, `laya`, `xgboost`) and the banner flips tier-by-tier to **REAL**;
columns, gates and exports do not move. If a trained artifact file is present in your models dir but its runtime is missing,
the app **stops** rather than silently substituting a stand-in — it will never present a `[SI]` number as real.

---

## 8. Outputs reference

| App | File | Contents |
|---|---|---|
| Coding | `ae_coded.csv` | One row per candidate (top-3) with decode, codes, HLT/HLGT evidence, scores, status. |
| Coding | `audit_log.csv` | Files read, verbatim column, dictionary source + hash, hierarchy, per-tier path, gate, latency. |
| PHI | `phi_flags.csv` | One row per scrubbed span (field, entity, offsets, confidence, action). |
| PHI | `sanitized/<domain>.csv` | Original columns + `SAN_<field>` + `<field>_PHI_FLAG`. |
| PHI | `audit_log.csv` | Files read, selected columns, discovery mode, per-tier path, gate, tag scheme, latency. |
| Risk | `risk_scores.csv` | One row per subject: both scores + categories and a human-readable contributing-factors string (counts/severity/fatal are internal signals, not exported). |
| Risk | `audit_log.csv` | Files/classifications read, criteria source (`[SI]`) + every threshold in force, path (`[SI]`/`[RM]`), category distribution, latency. |
| Anomaly | `anomalies.csv` | One row per FLAGGED subject: anomaly score, category, which detector(s) fired, extreme columns. |
| Anomaly | `drift.csv` | One row per measurable column (cohort-wide): window sizes, transport distance, drift ratio, category. |
| Anomaly | `lab_drift.csv` | One row per `LAB × column`: temporal drift within each lab/site (same shape as drift). |
| Anomaly | `lab_compare.csv` | One row per `LAB × column`: between-lab/site comparison, each lab vs the pooled others (leave-one-out transport distance → ratio → category). |
| Anomaly | `text_anomalies.csv` | One row per FLAGGED note: subject, field, isolation score, category, note text. |
| Anomaly | `audit_log.csv` | Files read, measurable + time + lab + free-text columns, numeric/drift/text paths (`[SI]`/real), every threshold in force, distributions, latency. |

Each audit log records the **contract** (which files/columns), the **per-tier path** that ran (REAL or `[SI]`), and every
**effective threshold** — so a run is reproducible from its audit alone. The four apps write separate `audit_log.csv` files
in their own output folders; they share no module.

---

## 9. Troubleshooting / FAQ

- **"No MedDRA source found"** (coding app): provide exactly one dictionary shape — upload a flattened CSV, set the `.asc`
  folder path, or name your file `meddra*.csv` inside the cut folder.
- **Everything routes to a human coder:** your dictionary is likely name-only (no PT codes). The pre-flight panel says "Has
  PT codes → NO". Add a code column or accept manual coding.
- **My verbatim column isn't detected:** rename it to `AETERM` in the CSV, or add its spelling to `AETERM_SYNONYMS` at the top
  of `meddra_app.py`. Do not hard-code a column elsewhere.
- **A date / ID column got flagged (PHI app):** that is content-based discovery working as designed — it scans every non-numeric
  field. If you know that column is safe, deselect it in the pre-flight multiselect and re-run; review any flags before trusting
  a scrub.
- **"No safety domains loaded" (risk app):** point at a folder with at least one of `ae`/`lb`/`eg`/`vs`/`pe`, or upload files. A
  file is only scored if it has a subject-id column (`USUBJID`).
- **A domain shows as unrecognized (risk app):** its columns don't match the synonyms — rename them (e.g. severity → `AESEV`) or
  add the spelling to `SYN` at the top of `risk_app.py`.
- **"No measurable columns" / drift shows OFF (anomaly app):** your numeric columns may be stored as text (coerce them), and/or no
  time/visit column was detected — add one (e.g. `VISITNUM`) to enable drift; per-subject anomalies still run without it. Add an
  unusual header spelling to `SYN` at the top of `anomaly_app.py`.
- **Blank cells:** missing values stay missing through all four apps (never `"nan"`), so an empty field correctly reports flag `N` /
  no code rather than scanning silently clean.

---

## 10. What this build does NOT do

No scanned-document / bounding-box path (input is tabular eCRF), no negation feature, no clinical variable derivation — and nothing
leaves the machine. The PHI output is compliance-*enabling*, not a certification; that remains an organizational determination. **The
risk app is decision support only** — it does not make a clinical determination and scores raw data against built-in `[SI]` criteria
rather than parsing free-text PDF/Word protocols or SAPs. **The anomaly app is decision support too** — it ranks and flags subjects/columns for human review but does not certify data quality, make a clinical determination, or replace a validated anomaly model (install `POT` + `scipy` to run real Sinkhorn drift; the default `[SI]` path is a labelled 1-D-Wasserstein stand-in). See [Deck A](presentations/deck_a_four_tier_pipeline.md) for the full governance and limits section.

---

## 11. Verifying your install

A portable end-to-end test harness ships in [`tests/qc_test.py`](tests/qc_test.py). With the app dependencies installed:

```bash
pip install -r requirements.txt && python tests/qc_test.py
```

Exit code **0 = every check passes**: 247 checks with the optional extras (`pyreadstat`, `scikit-learn`, `POT`, `scipy`) installed, 244 with `requirements.txt` only (all four apps driven end-to-end, including a synthetic `.asc` release with HLT/HLGT + currency filter, content-based PHI discovery, SAS `.sas7bdat` input routing, the risk app against `sample_data/` (anchor subjects landing in their expected categories, valid score ranges, full category coverage, `[SI]` criteria sourcing via the audit log) and the anomaly app catching its injected drift column + per-subject outliers. Every run is bit-identical across two runs; hosted demo mode and the `docs/` landing page are checked too). Leave `ECRF_HOSTED` unset and keep any Streamlit secrets file away while you run it: the hosted checks set both themselves. What was checked and what bugs were found and fixed: [QC_REPORT.md](QC_REPORT.md).
