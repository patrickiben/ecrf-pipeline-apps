# QC Report — meddra_app.py · phi_app.py · risk_app.py · anomaly_app.py

**Date:** 2026-10-15 · **Method:** all four apps executed end-to-end with Streamlit's
`AppTest` harness (Python 3.14, Streamlit 1.65, pandas 3.0, scikit-learn) against the unified sample cut in
`sample_data/` and the anomaly app's longitudinal demo in `anomaly_data/`, plus targeted edge cases
(uploaded dictionary, name-only dictionary, missing dictionary, blank fields, a synthetic
`.asc` release with HLT/HLGT + an inactive term, SAS `.sas7bdat` input routing, risk-app anchor subjects, and the anomaly app's injected numeric outliers + cohort/per-lab/between-lab drift + text outliers + a mixed longitudinal/cross-sectional upload). **Result: 95/95 checks pass.**

**Sample-cut enrichment (this pass):** every domain in `sample_data/` now carries an `AVISIT` + `VISITNUM` visit/timepoint dimension, assigned deterministically from row position — deliberately *not* the seeded RNG stream — so no existing value, anchor subject, or PHI-bearing note moved. Labs keep their file-provided reference range (`LBNRHI`), which is exactly what the risk app scores each lab against (option: ranges live in a column of the lab file). All 95 checks still pass on the enriched cut.

## Bugs found and fixed

| # | App | Severity | Bug | Fix |
|---|---|---|---|---|
| 1 | meddra | **Data corruption** | `cc.rank` (dot access on a pandas Series) resolves to the built-in `Series.rank()` *method*, not the column named `rank`. The exported `ae_coded.csv` rank column contained bound-method repr strings instead of integers. | Bracket access (`cc["rank"]`) for **every** cell in the export loop, so a future rename onto another method name cannot corrupt it again. |
| 2 | meddra | **Crash on upload** | `ingest_meddra`'s flat-CSV branch does `source_ref.copy()`, but Streamlit's `UploadedFile` has no `.copy()` — uploading a flattened MedDRA CSV crashed with `AttributeError`. | Upload is parsed to a DataFrame in `resolve_meddra` before the cached call; `_key` still carries name+size for cache identity. |
| 3 | phi | **Data corruption** | Sanitized columns were initialized with `df[col].astype(str)`, turning every missing value into the literal string `"nan"` — a fake value that scans, exports, and joins as real text (violating the Tier-1 "missing stays missing" invariant). | Sanitized values built row-by-row; missing/blank cells stay empty (`None` → blank CSV cell), flag `N`. |
| 4 | phi | Audit accuracy | For the NAME pattern, span START/END offsets covered the full match *including the title keyword* ("Patient Jane Miller") while SPAN held only the name — inconsistent audit offsets. | Offsets now taken from the captured group (`mm.start(gi)/mm.end(gi)`), so they point at exactly what SPAN contains. |
| 5 | meddra | Join-back risk | `KEY=r.get("AESEQ", …)` falls back only when the *column* is absent; a present-but-NaN AESEQ leaked into KEY and would break the join-back on `ae_coded.csv`. | New `_row_key()`: first **non-missing** of AESEQ/ID, else 1-based row number. |
| 6 | phi | Audit hygiene | `domain_rows` audit cell was a raw Python dict → serialized as single-quoted repr in CSV. | `json.dumps(...)` — clean machine-readable JSON cell. |
| 7 | phi | Cosmetic scrub artifact | `RE_INIT` (`\b[A-Z]\.[A-Z]\.?\b`) backtracked and dropped the trailing dot of "J.M.", so scrubbing left an orphaned "." in sanitized text ("[REDACTED_INITIALS]."). | Trailing dot now consumed only when it ends the initials (`(?:\.(?=[^0-9a-zA-Z]|$))?`); chained initials like "U.S.A" keep the previous heuristic. |
| 8 | meddra | **Crash on .asc load** | The `.asc` branch never selected `llt.asc`'s `pt_code` LINK column, so every ASCII-release load crashed with `KeyError('pt_code')`. Latent — it only surfaced once the `.asc` path was actually exercised by a test (M19–M23). | Select and carry the link column (`l_ptc = _col(llt,"pt_code","ptcd")`) into the join, and validate all required keys before joining. |
| 9 | sample data | **Silent column shift** | `sample_data/eg.csv` declared 3 headers (`STUDYID,USUBJID,EGCOM`) but each row had 4 values, so pandas shifted every value left and dropped `PROTO-2026-X89`, leaving `USUBJID` holding the numeric sequence. The old name-based PHI discovery hid it (it never scanned USUBJID); content-based discovery surfaced it. | Added the missing `EGSEQ` header column; eg.csv now parses with correct alignment. |
| 10 | risk generator | **Lost fatal flag** | `sample_data/generate.py` wrote a hardcoded `"N"` into every row's `AELIFE` column, so the anchor subject designed as fatal (`SUBJ-9015`) never carried its fatal flag and scored MODERATE instead of CRITICAL. | The generator now writes each anchor's declared `life` value (seeded subjects stay `"N"`). |
| 11 | risk | **Negative safety scores** | Tier 3 summed lab points over *all* labs without a breach guard, so a sub-threshold lab contributed negative points and two subjects scored −1/−2. | Lab component now counts only breaches (`ratio > declared threshold`); every score is clamped to [0,100]. |
| 12 | risk | **Relatedness never counted** | Tier 1's AE column list omitted `AEREL`, so the discontinuation model's relatedness term was always zero (e.g. a QTc-only subject scored LOW instead of MODERATE). | Added `AEREL` to the aligned AE columns; relatedness now feeds the discontinuation score. |
| 13 | risk | **Crash on first render** | The pre-flight panel computed the subject count from an undefined frame variable (`df`) left over from when domains loaded into a single frame, so the app raised `NameError` before any domain aligned. | Subject count now derived from the per-domain views; pre-flight renders cleanly (check R2). |
| 14 | anomaly data | **Fatal flag not evidence-backed** | The synthetic cut set `AELIFE=Y` on a subject with only life-threatening severity and no death record, so "fatal" was inferred from severity rather than backed by an outcome. A reviewer correctly flagged this as wrong. | Added an SDTM-standard `AEOUTCOME` column: `AELIFE=Y` now always pairs with `AEOUTCOME=DIED`; a life-threatening-but-survived subject (e.g. SUBJ-9001's cardiac arrest) stays non-fatal. The risk app cites the evidence in its contributing factors (checks R10b/R10d). |
| 15 | anomaly | **Crash on mixed upload** | Uploading a longitudinal file (`labs.csv`, with `VISITNUM`) together with cross-sectional safety files crashed `_change_matrix` at `np.nanargmin`: subjects present only in a domain without the detected time column had an all-NaN time slice. | Per-subject time-axis guard (fall back to first-row + a static-outlier flag when no valid time value exists); Tier 2 now picks change-vs-static **per column** from whether that column's subjects carry a time axis, so mixed cuts score every column honestly without crashing (checks A19–A20b). |

## Behaviour change: PHI discovery is now content-based

Per reviewer direction, the PHI app no longer gates on column names. The old rule
(a suffix list `COM;DESC;DSC` + an exact-name list) was removed because a
pre-specified list of names is guaranteed to miss PHI hiding in any column whose
header did not match — and missing PHI is exactly the failure this program exists
to prevent. **Every column that is not strictly numeric** (text, dates, coded
values, flags) is now scanned; only columns pandas typed as a number are skipped.
The operator confirms or deselects columns in the pre-flight multiselect instead of
editing a name rule. This change surfaced bug #9 above and is covered by checks P2/P2b.

## Refinements (no behavior change)

- Removed unused imports from `phi_app.py` (`numpy`, `hashlib`) so each file's
  dependencies are exactly what it uses; header install line updated to match.
- Replaced deprecated `use_container_width=True` with `width="stretch"` on all
  dataframes (Streamlit ≥1.42 API; the old kwarg now emits deprecation warnings).
- Launchers (`run_*.sh` / `.bat`) opt out of Streamlit's first-run telemetry email
  prompt up front and pin ports 8501–8504 (one per app), so a fresh machine goes from double-click
  to running app with no interactive prompts — consistent with the air-gapped design.
- Deck B (§2.2 offsets, §2.5 flag rows) now carries the **exact** stand-in output
  verified against this build on 2026-10-13; a verbatim-quote inconsistency in §1.2
  ("feel" vs "feeling lightheaded…") was corrected to match the worked cut.
- The HTML deck builds were themselves QC'd headlessly: a `match()` index bug that
  blanked every slide (`m[1]` → `m[0]`) and a `file://` `replaceState` hazard were
  found and fixed before delivery.

## New this pass: anomaly & drift app + Sinkhorn metric decision

**`anomaly_app.py`** is a fourth independent program (no shared module, same `[SI]`/real discipline). It detects two separate signals over longitudinal data: per-subject anomalies (robust z-score of each subject's change-from-baseline vs the cohort's distribution of changes) and distributional drift (transport distance between an early "reference" window and a late "current" window, per measurable column). Anomaly uses `anomaly_data/labs.csv` — its own longitudinal demo — because drift needs a time axis the cross-sectional shared cut lacks.

**Sinkhorn regularization decision.** The real drift path calls `ot.sinkhorn2` with a linear (L1) cost. Regularization must scale to the data's typical inter-point spacing, not its full range: scaling it to the **range** lets one tail/outlier stretch reg far beyond the bulk spread, which smears mass and inflates the transport cost — measured **+140…+186% vs exact 1-D Wasserstein** on tight columns (CREAT/AST/SYSBP), falsely pushing them toward HIGH drift. Scaling reg to the **reference window's robust spread** (IQR-based, already computed for the ratio denominator) keeps Sinkhorn within ~5–28% of exact W1 across all demo columns while staying numerically stable even when a column has drifted far (`ALT`). Verified against exact 1-D Wasserstein ground truth; checks A9/A10 assert `ALT` is the top drift column and every stable column stays LOW/MODERATE.

## New this pass: anomaly ensemble redesign (numeric + lab drift + text outliers)

The anomaly app was redesigned from a two-signal detector into an **ensemble of fast, scalable detectors** across numeric AND free-text fields — there are many ways data can be anomalous. What changed and what the harness now asserts:

- **Numeric outliers corroborated by Isolation Forest.** The robust-z change-from-baseline gate is unchanged as the interpretable score; a real **Isolation Forest** (scikit-learn) now fits the subject×column change matrix and corroborates each flag, with the `detectors` column citing which detector(s) agreed. Check A16 asserts flagged rows cite IsolationForest when sklearn is installed.
- **Discriminative, flagged-only scoring.** The old score was `min(1, |z|/3)`, so every flagged subject saturated at exactly 1.0 (uninformative). It is now `min(1, max|z| / ANOM_Z_TOP)` with `ANOM_Z_TOP=8`, and **only flagged subjects are emitted** (worst |z| ≥ `ANOM_Z`). Check A8b asserts no LOW-category subject leaks into the output.
- **Per-lab drift.** In addition to cohort-wide Sinkhorn drift, a categorical `LAB` column enables per-`LAB × column` drift (`lab_drift.csv`), isolating a site/lab assay change that cohort-wide drift dilutes away. Checks A12/A13 assert LAB-C×AST is CRITICAL while the other labs' AST stays LOW/MODERATE.
- **Text outliers.** Free-text columns (e.g. `LABCOM`) are scanned for retrieval-isolation — Needle3/Laya when installed, else a labelled bag-of-words isolation stand-in `[SI]` — emitting only flagged notes to `text_anomalies.csv`. Checks A14/A15 assert exactly the three injected anomalous notes are flagged in LABCOM.
- **Bug found & fixed (pandas 3 StringDtype).** Free-text detection used `is_object_dtype`, which is False for pandas-3's dedicated string dtype, so `LABCOM` was silently not detected and no text outliers ran. Detection now accepts both object and string dtypes (`is_object_dtype OR is_string_dtype`).

## New this pass: between-lab/site comparison + mixed-upload robustness

Two additions to the anomaly app, both verified end-to-end by the harness:

- **Between-lab/site comparison (`lab_compare.csv`).** Per-lab drift asks *how much one lab moved over time*; it cannot see a site that systematically measures differently from every other site. The new Tier-3 signal compares each `LAB × column` current-window distribution against the POOLED-OTHERS (leave-one-out) distribution via the same Sinkhorn/Wasserstein transport distance, normalized by the robust spread → a unitless `between_lab_ratio`. A lab that agrees with the rest shows ~0; an outlier site stands out. Checks A17/A18 assert LAB-C×AST is the between-lab standout (HIGH/CRITICAL) while the other labs' AST stays LOW/MODERATE.
- **Mixed-upload robustness (bug found & fixed).** Uploading a longitudinal file (`labs.csv`, with `VISITNUM`) together with cross-sectional safety files used to crash: `_change_matrix` called `np.nanargmin` on an all-NaN time slice for subjects present only in a domain without the detected time column. The change matrix now guards each subject's time axis (falls back to first-row + a static-outlier flag when no valid time value exists), and Tier 2 picks change-vs-static **per column** from whether that column's subjects carry a time axis — so mixed cuts score every column honestly without crashing or mixing signal definitions within one column. Checks A19–A20b build a temp cut of `labs.csv` + the cross-sectional safety files, assert no exception on load/execute, and confirm the three injected numeric outliers are still flagged (the longitudinal signal survives alongside cross-sectional data).

## Verified working (95 checks)

**meddra_app.py:** domain + dictionary load from folder and via upload · verbatim
selector populated from synonyms · pre-flight contract panel · execute produces
one row per candidate (top-3) with integer ranks · exact-match verbatim
AUTO_COMMIT_TO_SDTM, semantic-gap verbatims FLAGGED_FOR_HUMAN_CODER (honest `[SI]`
behaviour) · name-only dictionary forces 100% routing and warns in pre-flight ·
missing-dictionary error surfaced as plain text, not a stack trace · `.asc`
release auto-discovered with the full LLT→PT→HLT→HLGT→SOC hierarchy shown in
pre-flight and an inactive PT dropped by the currency filter · `ae_coded.csv`
carries HLT/HLGT evidence columns · outputs (`ae_coded.csv`, `audit_log.csv`)
written · **bit-identical output across two runs** (the earlier `zlib.crc32`
determinism fix holds).

**phi_app.py:** initials scrub cleanly with no orphaned punctuation ("J.M." →
`[REDACTED_INITIALS]`) · content-based discovery scans every non-numeric column
(including AETERM, which the old name-rule missed); only AECOM and PRDSC contain
identifiers so only they flag ·
direct spans (name, phone, MRN, DOB) scrubbed on their own merit · mosaic case:
initials + postcode scrubbed only because two indirect attributes co-occur ·
look-alike trap passes — Alanine and a glucose value survive while the patient name
beside them is redacted · clean negative (EGCOM) untouched with flag `N` · blank
field stays missing, never `"nan"` · PHI flags Y/Y/N/N/N/N as designed · outputs
(`phi_flags.csv`, `sanitized/*.csv`, `audit_log.csv`) written.

**risk_app.py:** all five safety domains classified by content from `sample_data/` ·
pre-flight shows the classification + subject count and records the `[SI]` criteria source in the audit ·
every safety score lands in [0,100] and every discontinuation score in [0,1] · all four
safety categories (LOW/MODERATE/HIGH/CRITICAL) are present across the bulk cut · anchor
subjects land where designed — fatal `SUBJ-9015` → CRITICAL with its fatality cited alongside the
`AEOUTCOME=DIED` evidence, multi-system `SUBJ-9001` → CRITICAL (its life-threatening cardiac arrest
correctly NOT called fatal since it survived), severe-AE `SUBJ-9002` → HIGH, lab-driven `SUBJ-9013`
cites an ALT breach, ECG-driven `SUBJ-9014` cites QTc · the fatal subject ranks at/above every
non-fatal subject · discontinuation categories for the anchors are correct (fatal → HIGH,
QTc-only → MODERATE) · the raw count/severity/fatal signals are internal and not exported (R5b) · outputs (`risk_scores.csv`, `audit_log.csv`) written · **bit-identical output across two runs**.

**anomaly_app.py:** loads its longitudinal demo from `anomaly_data/` and detects the time column, measurable columns, lab column (per-lab drift ON) and free-text column (text outliers ON) in pre-flight · execute produces flagged-only numeric outliers, cohort + per-lab drift + between-lab/site comparison, and text outliers with no exception · all three injected numeric outliers (`SUBJ-A003`, `SUBJ-A017`, `SUBJ-A029`) are the only subjects emitted and each cites its extreme column/z plus the IsolationForest corroborator (A8/A8b/A16) · scores stay discriminative in [0,1] rather than saturating at 1.0 · `ALT` is the top cohort drift column while every stable column stays LOW/MODERATE (A9/A10) — confirming anomaly and drift are separate signals · per-lab drift isolates LAB-C×AST as CRITICAL while the other labs' AST stays LOW/MODERATE (A12/A13) · between-lab/site comparison flags LAB-C×AST as the standout vs the pooled others while the other labs stay LOW/MODERATE (A17/A18) · a mixed longitudinal + cross-sectional upload runs with no exception and still flags all three injected numeric outliers (A19–A20b) · exactly the three injected anomalous notes are flagged in `LABCOM` (A14/A15) · the audit records which numeric/drift/text path ran, matching the installed runtimes (A6/A6b/A6c) · outputs (`anomalies.csv`, `drift.csv`, `lab_drift.csv`, `lab_compare.csv`, `text_anomalies.csv`, `audit_log.csv`) written · **bit-identical output across two runs**.

## How to re-run the tests

The harness lives in [`tests/qc_test.py`](tests/qc_test.py) (portable — its paths
derive from its own location). With the app dependencies installed:

    pip install -r requirements.txt && python tests/qc_test.py

Exit code 0 = all 95 checks pass. It drives each app end-to-end via
`streamlit.testing.v1.AppTest.from_file(...)`, points the coding/PHI/risk apps at `sample_data/`
and the anomaly app at `anomaly_data/`, clicks Execute, and asserts on the rendered dataframes and
written CSVs — including a synthetic `.asc` release (HLT/HLGT + currency filter), content-based
PHI discovery, SAS `.sas7bdat` input routing, the risk-app anchor subjects, and the anomaly app's injected drift column + per-subject outliers. The assertions above are the acceptance criteria; keep them green before sharing a change.

## Known limits (unchanged by QC)

- Coding stand-in retrieval is lexical: `[SI]` scores will not match trained-run
  (`[RM]`) numbers on semantically-gapped verbatims — documented in-app and in
  the audit, never hidden.
- eCRF path only; no scanned-document/bounding-box capability exists here.
- The risk app is **decision support**, not a clinical determination: its `[SI]` weighted
  engine ranks and flags subjects for human review but does not predict outcomes with validated
  accuracy, and it scores raw data against built-in `[SI]` criteria rather than parsing free-text PDF/Word protocols or SAPs.
- The anomaly app's detectors default to labelled `[SI]` stand-ins where the runtime is absent: drift uses a 1-D-Wasserstein stand-in (install `POT` + `scipy` for real Sinkhorn optimal transport), numeric outliers run the robust-z gate alone (install `scikit-learn` to add a real Isolation Forest corroborator), and text outliers use bag-of-words isolation (install the internal `cactus-needle`/`laya` packages for real retrieval-isolation). It is decision support — it does not certify data quality or make a clinical determination.
- `sample_data/meddra_demo.csv` is synthetic demo data, not licensed MedDRA.
- Everything in `sample_data/` and `anomaly_data/` is **synthetic** — no real patient, study, or licensed dictionary; regenerate with `python3 sample_data/generate.py` (ae/lb/eg/vs/pe) and `python3 anomaly_data/generate.py` (labs.csv), both deterministic at seed 42.
