# QC Report — meddra_app.py · phi_app.py · risk_app.py · anomaly_app.py

**Date:** 2026-10-15 · **Method:** all four apps executed end-to-end with Streamlit's
`AppTest` harness (Python 3.14, Streamlit 1.65, pandas 3.0, scikit-learn) against the unified sample cut in
`sample_data/` and the anomaly app's longitudinal demo in `anomaly_data/`, plus targeted edge cases
(uploaded dictionary, name-only dictionary, missing dictionary, blank fields, a synthetic
`.asc` release with HLT/HLGT + an inactive term, SAS `.sas7bdat` input routing, risk-app anchor participants, and the anomaly app's injected numeric outliers + cohort/per-lab/between-lab drift + text outliers + a mixed longitudinal/cross-sectional upload). **Result: 95/95 checks pass.**

**Update, 2026-10-21:** the harness now runs 247 checks with the optional extras installed and 244 with `requirements.txt` only, all passing; see [New this pass: hosted-demo safety mode, CI and docs checks](#new-this-pass-hosted-demo-safety-mode-ci-and-docs-checks).

**Update, 2026-10-22:** the coding and PHI apps' real model path is wired and measured, and the harness adds 16 always-run wiring checks and 5 real-model checks that are reported as skipped when no models dir is given; see [New this pass: the real model path](#new-this-pass-the-real-model-path).

**Update, 2026-10-24:** the four apps also run in the browser from GitHub Pages (stlite), every download button keeps the results on screen, and the harness adds D4, which checks the browser build in `docs/app/` against the apps and their data; see [New this pass: the apps in the browser](#new-this-pass-the-apps-in-the-browser).

**Update, 2026-10-24 (review fixes):** each in-browser page states its measured limits, the docs and app text say participant, the anomaly app counts participants rather than rows, and CI adds a leg on the browser's Python 3.14 stack; see [New this pass: review fixes to the browser build](#new-this-pass-review-fixes-to-the-browser-build).

**Sample-cut enrichment (this pass):** every domain in `sample_data/` now carries an `AVISIT` + `VISITNUM` visit/timepoint dimension, assigned deterministically from row position — deliberately *not* the seeded RNG stream — so no existing value, anchor participant, or PHI-bearing note moved. Labs keep their file-provided reference range (`LBNRHI`), which is exactly what the risk app scores each lab against (option: ranges live in a column of the lab file). All 95 checks still pass on the enriched cut.

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
| 10 | risk generator | **Lost fatal flag** | `sample_data/generate.py` wrote a hardcoded `"N"` into every row's `AELIFE` column, so the anchor participant designed as fatal (`SUBJ-9015`) never carried its fatal flag and scored MODERATE instead of CRITICAL. | The generator now writes each anchor's declared `life` value (seeded participants stay `"N"`). |
| 11 | risk | **Negative safety scores** | Tier 3 summed lab points over *all* labs without a breach guard, so a sub-threshold lab contributed negative points and two participants scored −1/−2. | Lab component now counts only breaches (`ratio > declared threshold`); every score is clamped to [0,100]. |
| 12 | risk | **Relatedness never counted** | Tier 1's AE column list omitted `AEREL`, so the discontinuation model's relatedness term was always zero (e.g. a QTc-only participant scored LOW instead of MODERATE). | Added `AEREL` to the aligned AE columns; relatedness now feeds the discontinuation score. |
| 13 | risk | **Crash on first render** | The pre-flight panel computed the participant count from an undefined frame variable (`df`) left over from when domains loaded into a single frame, so the app raised `NameError` before any domain aligned. | Participant count now derived from the per-domain views; pre-flight renders cleanly (check R2). |
| 14 | anomaly data | **Fatal flag not evidence-backed** | The synthetic cut set `AELIFE=Y` on a participant with only life-threatening severity and no death record, so "fatal" was inferred from severity rather than backed by an outcome. A reviewer correctly flagged this as wrong. | Added an SDTM-standard `AEOUTCOME` column: `AELIFE=Y` now always pairs with `AEOUTCOME=DIED`; a life-threatening-but-survived participant (e.g. SUBJ-9001's cardiac arrest) stays non-fatal. The risk app cites the evidence in its contributing factors (checks R10b/R10d). |
| 15 | anomaly | **Crash on mixed upload** | Uploading a longitudinal file (`labs.csv`, with `VISITNUM`) together with cross-sectional safety files crashed `_change_matrix` at `np.nanargmin`: participants present only in a domain without the detected time column had an all-NaN time slice. | Per-participant time-axis guard (fall back to first-row + a static-outlier flag when no valid time value exists); Tier 2 now picks change-vs-static **per column** from whether that column's participants carry a time axis, so mixed cuts score every column honestly without crashing (checks A19–A20b). |

## Behavior change: PHI discovery is now content-based

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

**`anomaly_app.py`** is a fourth independent program (no shared module, same `[SI]`/real discipline). It detects two separate signals over longitudinal data: per-participant anomalies (robust z-score of each participant's change-from-baseline vs the cohort's distribution of changes) and distributional drift (transport distance between an early "reference" window and a late "current" window, per measurable column). Anomaly uses `anomaly_data/labs.csv` — its own longitudinal demo — because drift needs a time axis the cross-sectional shared cut lacks.

**Sinkhorn regularization decision.** The real drift path calls `ot.sinkhorn2` with a linear (L1) cost. Regularization must scale to the data's typical inter-point spacing, not its full range: scaling it to the **range** lets one tail/outlier stretch reg far beyond the bulk spread, which smears mass and inflates the transport cost — measured **+140…+186% vs exact 1-D Wasserstein** on tight columns (CREAT/AST/SYSBP), falsely pushing them toward HIGH drift. Scaling reg to the **reference window's robust spread** (IQR-based, already computed for the ratio denominator) keeps Sinkhorn within ~5–28% of exact W1 across all demo columns while staying numerically stable even when a column has drifted far (`ALT`). Verified against exact 1-D Wasserstein ground truth; checks A9/A10 assert `ALT` is the top drift column and every stable column stays LOW/MODERATE.

## New this pass: anomaly ensemble redesign (numeric + lab drift + text outliers)

The anomaly app was redesigned from a two-signal detector into an **ensemble of fast, scalable detectors** across numeric AND free-text fields — there are many ways data can be anomalous. What changed and what the harness now asserts:

- **Numeric outliers corroborated by Isolation Forest.** The robust-z change-from-baseline gate is unchanged as the interpretable score; a real **Isolation Forest** (scikit-learn) now fits the participant×column change matrix and corroborates each flag, with the `detectors` column citing which detector(s) agreed. Check A16 asserts flagged rows cite IsolationForest when sklearn is installed.
- **Discriminative, flagged-only scoring.** The old score was `min(1, |z|/3)`, so every flagged participant saturated at exactly 1.0 (uninformative). It is now `min(1, max|z| / ANOM_Z_TOP)` with `ANOM_Z_TOP=8`, and **only flagged participants are emitted** (worst |z| ≥ `ANOM_Z`). Check A8b asserts no LOW-category participant leaks into the output.
- **Per-lab drift.** In addition to cohort-wide Sinkhorn drift, a categorical `LAB` column enables per-`LAB × column` drift (`lab_drift.csv`), isolating a site/lab assay change that cohort-wide drift dilutes away. Checks A12/A13 assert LAB-C×AST is CRITICAL while the other labs' AST stays LOW/MODERATE.
- **Text outliers.** Free-text columns (e.g. `LABCOM`) are scanned for retrieval-isolation — Needle3/Laya when installed, else a labeled bag-of-words isolation stand-in `[SI]` — emitting only flagged notes to `text_anomalies.csv`. Checks A14/A15 assert exactly the three injected anomalous notes are flagged in LABCOM.
- **Bug found & fixed (pandas 3 StringDtype).** Free-text detection used `is_object_dtype`, which is False for pandas-3's dedicated string dtype, so `LABCOM` was silently not detected and no text outliers ran. Detection now accepts both object and string dtypes (`is_object_dtype OR is_string_dtype`).

## New this pass: between-lab/site comparison + mixed-upload robustness

Two additions to the anomaly app, both verified end-to-end by the harness:

- **Between-lab/site comparison (`lab_compare.csv`).** Per-lab drift asks *how much one lab moved over time*; it cannot see a site that systematically measures differently from every other site. The new Tier-3 signal compares each `LAB × column` current-window distribution against the POOLED-OTHERS (leave-one-out) distribution via the same Sinkhorn/Wasserstein transport distance, normalized by the robust spread → a unitless `between_lab_ratio`. A lab that agrees with the rest shows ~0; an outlier site stands out. Checks A17/A18 assert LAB-C×AST is the between-lab standout (HIGH/CRITICAL) while the other labs' AST stays LOW/MODERATE.
- **Mixed-upload robustness (bug found & fixed).** Uploading a longitudinal file (`labs.csv`, with `VISITNUM`) together with cross-sectional safety files used to crash: `_change_matrix` called `np.nanargmin` on an all-NaN time slice for participants present only in a domain without the detected time column. The change matrix now guards each participant's time axis (falls back to first-row + a static-outlier flag when no valid time value exists), and Tier 2 picks change-vs-static **per column** from whether that column's participants carry a time axis — so mixed cuts score every column honestly without crashing or mixing signal definitions within one column. Checks A19–A20b build a temp cut of `labs.csv` + the cross-sectional safety files, assert no exception on load/execute, and confirm the three injected numeric outliers are still flagged (the longitudinal signal survives alongside cross-sectional data).

## New this pass: hosted-demo safety mode, CI and docs checks

**Date:** 2026-10-21 · **Method:** the same `AppTest` harness on Python 3.12.3 with Streamlit 1.66.1, pandas 3.0.6 and numpy 2.5.4, run in the two configurations below. No bug was found in the apps' existing behavior this pass, and no widget label, header or button text changed. Two bugs outside the apps were found and fixed: `requirements.txt` allowed Streamlit 1.36 to 1.48, on which every app crashes on load (see CI below), and the Deck B HTML build, now published on GitHub Pages, had dropped the first letter of four slide headings ("race 1" for "Trace 1", "erify" for "Verify"), closed 14 headings with a malformed `</h3 class="slide-h">` tag, and turned part of the initials regex on slide 2.2 into a stray link. The HTML now matches the `.md`.

**Hosted-demo safety mode (all four apps).** A public demo must never take in real data. Hosted mode is switched on by the Streamlit secret `hosted = true` (Streamlit Community Cloud: the app's Settings > Secrets) or by the environment variable `ECRF_HOSTED=1`. When it is on:

- every input that could bring data in (the domain uploader, the folder path, the models dir and, in the coding app, the dictionary uploader and the `.asc` folder) is disabled in the UI, and its value is also overwritten in code, because a disabled widget only stops the browser and a crafted client could still send a value;
- the bundled synthetic cut is forced (`sample_data/`, or `anomaly_data/` for the anomaly app), with the sample box locked on;
- outputs go to a per-session server temp folder, never a path a visitor typed, and the folder is deleted when Streamlit discards the expired session (and at process exit), so page views do not pile folders up in `/tmp`;
- an uncaught exception shows a generic message instead of a traceback with server paths (`client.showErrorDetails` is set to `none`);
- a banner ("Public demo: synthetic data only. Do not enter or upload real patient data. Run locally for real data.") shows on the main page and as the first sidebar element on every rerun;
- the audit records `hosted_mode=true`, right after `timestamp`.

With nothing set (the local default) every app behaves as before; its audit only gains `hosted_mode=false`. The switch is duplicated in each app on purpose (no shared module, same rule as the other helpers).

**The switch fails closed** (see `_hosted()` in each app). A security review found three ways a public app could end up unlocked with nothing on the page to show it, all fixed this pass: (1) a secrets file that exists but does not parse (`hosted = True` with a capital T, or any stray bad line) made Streamlit's loader report "no secrets", so the app ran in local mode while Streamlit only logged the parse error on the server; (2) `ECRF_HOSTED` values such as `on` or `y` were read as off; (3) a top-level `ECRF_HOSTED` key in the secrets overwrote a host-set `ECRF_HOSTED=1`, because Streamlit copies top-level secrets into the environment. Now any `ECRF_HOSTED` or `hosted` value other than empty, `0`, `false`, `no` or `off` turns hosted mode on, so does a secrets file or folder that exists but does not load, and so does an `ECRF_HOSTED` key in the secrets. With no secrets file at all, a local run is unchanged. The README deploy steps now end with opening the app and confirming the banner, and say how to cap upload sizes on a self-managed host (`--server.maxUploadSize 1`): Streamlit's upload endpoint keeps bytes a crafted client sends to a disabled uploader in server memory until the session expires, although the apps never read them.

**CI.** `.github/workflows/qc.yml` runs `python tests/qc_test.py` on Python 3.12 on every push and pull request, in two matrix variants: `stand-in` (`requirements.txt` only, what a plain install gets) and `optional-extras` (plus `pyreadstat`, `scikit-learn`, `POT` and `scipy`). A guard step fails the job if the runner has `ECRF_HOSTED` set, so every run starts from the local default; the hosted checks set and clear it inside the harness process. `requirements.txt` now asks for `streamlit>=1.49`, the oldest release that accepts `st.dataframe(width="stretch")` (1.36 to 1.48 raise `TypeError` on load). The harness itself needs Streamlit 1.56 or newer (`AppTest.file_uploader`), which a fresh install satisfies.

**New check groups (152 checks).**

- **H, hosted mode (149 checks).** Per app (HM coding, HP PHI, HR risk, HA anomaly), checks 1 to 21:
  - 1 to 3: the local default is unchanged (no banner, every input live, `?demo=1` still fills the folder, audit `hosted_mode=false`);
  - 4 to 11: the hosted view end to end (banner on the main page and in the sidebar, no uploader or path input enabled, the sample cut loads and executes, audit `hosted_mode=true` in the temp Output folder);
  - 12 to 16: a crafted client forges widget values (folder path, domain upload, unticked sample box, Output folder, models dir) and every one is ignored. 12 and 13 run on stock Streamlit, where the disabled flag already drops the forged value (so they fail only if the flag and the app's override are both missing); 14 to 16 switch Streamlit's server-side drop of disabled-widget values off, so the apps' code overrides are the only defense. 14 also checks that an unticked sample box alone leaves the folder field on the sample;
  - 17: the Output folder is a per-session temp folder, stable across reruns and new for each session;
  - 18: hosted mode sets `client.showErrorDetails` to `none`, and a local run leaves it alone;
  - 19: both banners still show when the artifact guard's `st.stop()` cuts the page short (hosted mode pins the models dir to `models`, which is relative to the working folder);
  - 20: the per-session temp folder is deleted once its session is discarded;
  - 21: the placement rules, read from the source because a misplaced line has no runtime symptom on 1.66.1: `HOSTED = _hosted()` on the line after `st.set_page_config(...)`, then the main banner, then the sidebar banner as the first sidebar call right before the first sidebar header, all above every `st.stop()`.

  The coding app adds HM9b, HM11b, HM15b and HM15c for its dictionary inputs. HX1 is a control: it proves a forged value really reaches a disabled widget once the server-side drop is off, so 14 to 16 cannot pass vacuously. The switch itself is tested per app: HS1 to HS32 inject secret values through `AppTest` (`true`, `"true"`, `" Yes "` and `"on"` lock each app; `false`, `"false"`, `"0"` and a secrets file with only an unrelated key keep local behavior); HE1 to HE8 try other `ECRF_HOSTED` spellings (`" True "`, `yes`, `on` and `2` lock; `0`, `" false "`, `no` and `OFF` do not); HF1 to HF20 run Streamlit's real secrets loader on scratch `secrets.toml` files: a valid `hosted = true`, the two malformed files above, a valid file with an unrelated key only, and `ECRF_HOSTED = "0"` over a host-set `ECRF_HOSTED=1`. Each HF check also asserts what the loader itself reported, so a case cannot pass because its file was not what it claims to be.
- **D, docs and GitHub Pages (3 checks).** D1: `docs/` holds exactly the `presentations/` decks, each a byte-identical copy, so a deck edit cannot silently drift from the Pages copy and no stale deck lingers there. D2: `docs/index.html` loads no external script, stylesheet, font or image (including SVG `href`/`xlink:href`, a `<meta http-equiv=refresh>` target and inline scripts that name a URL). D3: every local link and image in `README.md` (inline and reference-style) and every local reference in `docs/index.html` (`href`, `src`, `srcset`, CSS `url()`) exists on disk; each file must hold at least one, and every `docs/img/` file must be used.

Each new check was also seen to fail when what it guards is broken: the hosted checks against scratch copies of the apps with parts of hosted mode removed, and D1 to D3 against a drifted or missing deck copy, an added CDN script, stylesheet, font or image, and a deleted screenshot. A second round of reviews found mutations that still passed; each now fails at least one check, verified the same way on scratch copies: the old fail-open switch, a `hosted` default of true for a file without the key, a bool-only secret test, the old `ECRF_HOSTED` test, the `ECRF_HOSTED` secret rule removed, the fail-closed fallback removed, the sample-box override removed, `HOSTED = _hosted()` moved above `set_page_config`, the main banner moved below the artifact guard, `mkdtemp` instead of the self-deleting folder, the error-detail setting removed or made unconditional, and in `docs/` a broken deck link, a missing reference-style README image, CSS `url()`, `srcset` entry or icon, an off-site SVG image, a meta refresh, an inline fetch script, a stale deck copy and an unused screenshot.

**Results.**

| Configuration | Result |
|---|---|
| `requirements.txt` plus the optional extras `pyreadstat`, `scikit-learn`, `POT`, `scipy` (CI variant `optional-extras`) | **247 passed, 0 failed** (95 app + 149 hosted + 3 docs) |
| `requirements.txt` only (CI variant `stand-in`) | **244 passed, 0 failed** (SAS2, SAS3 and A16 need `pyreadstat` or `scikit-learn` and do not run; SAS1 asserts the "install pyreadstat" message instead) |

The "Verified working" list below still describes the 95 app checks; all of them pass in this pass too.

## New this pass: the real model path

**Date:** 2026-10-22 · **Method:** the same harness, plus the evaluation scripts in [`eval/`](eval/README.md), on Python 3.12.3, Streamlit 1.66.1, an Intel Xeon @ 2.80GHz with 4 vCPU and no GPU. The coding and PHI apps now run their real Tiers 2 to 4 (Cactus Needle3 `cactus-needle` 3.2.8, hnswlib 0.8.0, Laya 0.4.13, XGBoost 3.4.1) from a models dir; what that path does on synthetic data is in [`docs/EVALUATION.md`](docs/EVALUATION.md). The five wiring defects that [`docs/FEASIBILITY.md`](docs/FEASIBILITY.md) found at Stage 0 are fixed, and building and measuring the path found more:

- **Needle3's embedding is case-sensitive.** "insomnia" scored 0.948 against "Insomnia", below several unrelated terms, and verbatims are typed lower-case while dictionary terms are capitalized. The coding app now embeds a lower-cased copy of both, like its stand-in and its string features already did (retrieval top-1 0.622 to 0.747 on the held-out set).
- **The real-path load was cached on the typed models-dir string.** A relative path such as hosted mode's `models`, or a models dir whose files changed while the app ran, could be served a stale load for the life of the process. The cache key is now the absolute path plus each artifact's size and modification time (found by HM19/HP19 failing in an environment with the real runtimes; pinned by RW16).
- **Laya warns on every load when a calibration file was fitted under another path,** which is always the case once a models dir is copied to another machine. The apps now drop that path-only warning and stop on a calibration fitted for a different checkpoint config (RW14, RW15). The evaluation script also reads the temperature Laya actually applies: Laya fits a per-bucket temperature only from 2,000 records, and otherwise its type-level one.
- **Needle3's PHI extraction is noisy** (it proposed "Sinus rhythm" as a name and "120" from "120 mg/dL" as a ZIP code; extraction alone had precision 0.42 on held-out notes), so the PHI app uses Needle3's proposals only behind the trained span gate, and keeps Tier 2 on its stand-in when there is no gate.

**New checks.** RW1 to RW16 run always, including in CI, with small stub packages named `needle`, `hnswlib`, `laya` and `xgboost` put first on the path. They drive the apps with models dirs in different states and pin: modules bound, REAL only when an artifact loads, Laya probed with torch and transformers, an unrelated `needle` package rejected, a trained gate refused when its inputs did not load, a corrupt artifact or a missing runtime stopping the run, the calibration identity rule, a changed models dir reloaded, the PHI app's Needle3 kept behind its gate, Tier 3 feeding the re-ranker (a negated verbatim routed to a human), and the risk and anomaly apps never claiming a model they cannot load. RM1 to RM5 run only when `ECRF_MODELS_DIR` names a models dir holding the trained artifacts and the real runtimes import; otherwise each is reported **SKIPPED**, never passed. They assert REAL on every tier in the banner and audit, artifact hashes in the audit, a bit-identical `ae_coded.csv` across two runs, and that the Deck B worked rows reproduce the values in `eval/results/deck_b_worked.json`.

**Results.**

| Configuration | Result |
|---|---|
| `requirements.txt` plus the optional extras (CI variant `optional-extras`) | **263 passed, 0 failed, 5 skipped** (247 earlier checks + 16 RW; RM1 to RM5 skipped: no models dir) |
| `requirements.txt` only (CI variant `stand-in`) | **260 passed, 0 failed, 5 skipped** (244 + 16 RW; RM skipped) |
| the real runtimes, no optional extras, `ECRF_MODELS_DIR` set to a models dir built with `eval/fetch_models.py` and trained with `eval/run_eval.py` | **265 passed, 0 failed, 0 skipped** (244 + 16 RW + 5 RM) |

## New this pass: the apps in the browser

**Date:** 2026-10-24 · **Method:** the `AppTest` harness on Python 3.14.7 with Streamlit 1.65.0, pandas 3.0.6 and numpy 2.5.4 (the optional extras and the real runtimes installed, no models dir), plus headless Chrome 155 driven by puppeteer-core 25.16.0 against `docs/` served locally under `/ecrf-pipeline-apps/`, as GitHub Pages serves it.

The Streamlit Community Cloud links had started to answer with a sign-in page, so the four apps now run in the visitor's browser instead. stlite 1.12.0 runs Streamlit 1.65.0 on Pyodide 314.0.3 (Python 3.14) inside the tab, and GitHub Pages serves one page per app from `docs/app/`. What changed:

- **Downloads keep the results (all four apps).** Every `st.download_button` now passes `on_click="ignore"`. Before, a click reran the script and, because the results sit behind the Execute button, wiped the tables and the other download buttons, so a second file needed a second run.
- **Accurate wording in the browser.** Under Pyodide (`sys.platform == "emscripten"`) the caption says "runs in this browser tab" instead of "air-gapped", the help panel says nothing you load is uploaded instead of "nothing leaves the machine", the Output-folder help explains that the folder is in the tab's memory, and the success message says the files are in the tab's memory and points to the download buttons instead of "Wrote /tmp/...". A local run is unchanged; no widget label, header or button text changed.
- **The browser build.** `tools/sync_browser_apps.py` copies the four `.py` files and every CSV in `sample_data/` and `anomaly_data/` into `docs/app/`, renders the four pages from `tools/browser_app_template.html` and checks three pinned pure-Python wheels (`itsdangerous`, `python-multipart`, `toml`) that the Streamlit build needs and Pyodide does not ship. Serving those from Pages means a visit contacts only GitHub Pages and cdn.jsdelivr.net, never PyPI. The pages set `ECRF_HOSTED=1`, pin stlite and Pyodide by exact version, check stlite's stylesheet and two core modules with Subresource Integrity, and carry a Content-Security-Policy that allows connections only to the site and the CDN.
- **New check D4.** `tools/sync_browser_apps.py --check` must pass: byte-identical copies, pages exactly as rendered, wheel hashes, and no stray file. It also runs as its own CI job (`browser-build`). It was seen to fail on scratch copies for an edited app, a new source CSV, a deleted copy, a stray copy, a hand-edited page, a corrupted wheel and a missing screenshot, and to pass again after a sync.

**Browser checks** (each app, run outside the harness; screenshots kept outside the repository):

- Each page shows the loading notice ("Starting Python in your browser; first visit downloads about 30 MB.") and the privacy note word for word, and becomes interactive in 4.1 to 5.3 seconds on this machine (29.3 seconds with the network throttled to 10 Mbps and 100 ms).
- In hosted mode both banners show, the sample box is ticked and locked, and Execute renders the results with no exception.
- The first download button saves its file, and the results, the success message and every download button are still on screen afterward. The four downloaded files (`ae_coded.csv`, `phi_flags.csv`, `risk_scores.csv`, `anomalies.csv`) are byte-identical to a native run of the same apps in hosted mode with the optional extras hidden, so every tier ran its `[SI]` path in both.
- `?demo=1` works at 390 px phone width, with no horizontal scroll while loading, when ready or with results on screen, and the last download button can be scrolled into view. With hosted mode switched off for a test run only, `?demo=1` ticks the sample box and its absence leaves it unticked, so the query parameter reaches Python in the browser.
- There were zero page errors. Every request went to the local server or cdn.jsdelivr.net (none to PyPI), and none was a POST or other non-GET request. An off-site fetch from the page, or from a worker it creates, is refused by the policy. Changed copies of `stlite.css`, `stlite.js` or its core chunk are refused by the browser.
- With the CDN blocked, the page keeps the screenshot and explains that the app could not start. The test sandbox's own network dropped an occasional CDN request: in the final run, 2 of 10 page loads failed to start on the first try, showed that message with the advice to reload, and passed after one reload.
- Known, harmless console noise: each download button logs a blocked request to stlite's placeholder host `stlite.invalid` when it appears; the download itself works. Only headless Chrome was tested; Safari and Firefox were not.

**Results.**

| Configuration | Result |
|---|---|
| `requirements.txt` plus the optional extras and the real runtimes, no models dir (Python 3.14.7, Streamlit 1.65.0) | **264 passed, 0 failed, 5 skipped** (the 263 earlier checks + D4; RM1 to RM5 skipped: no models dir) |

## New this pass: review fixes to the browser build

**Date:** 2026-10-24 · **Method:** the `AppTest` harness in three configurations (table below), plus headless Chrome 155 driven by puppeteer-core 25.16.0 against `docs/` served locally under `/ecrf-pipeline-apps/`, as GitHub Pages serves it.

What changed after review:

- **Measured limits on each page.** Every in-browser page carries a "Limits" line under the privacy note. The PHI page says that on held-out synthetic text the stand-in left 108 of 308 identifiers readable (the real model path: 91 of 308); the coding page gives the stand-in's 54% top-1 (real path: 78%) and its 7 of 96 auto-coded negated verbatims; the risk page says both scores are capped, weighted rule sums, not probabilities; the anomaly page says every detector runs its `[SI]` stand-in. The landing page repeats the coding and PHI figures.
- **"Participant", not "subject".** The docs and the text the apps show say participant(s) and per-participant ("Participants aligned", "per-participant risk"). Identifiers (`n_subjects`), CDISC names (`USUBJID`, `SUBJ-` IDs), the PHI title regexes and the synthetic note text are unchanged. British spellings in the same places became American (labeled, behavior, neighbor, judgment, etiology).
- **Anomaly app counted rows as participants (bug fixed).** The pre-flight panel and the audit's `n_subjects` reported 600 for the 150-participant, 4-visit demo. It now counts unique `USUBJID`. New checks A2c (pre-flight shows 150) and A6d (audit records 150).
- **Page names and captions.** The pages are titled Coding QC Assist (MedDRA-style, demo dictionary), De-identification Review Assist, Participant Risk Screening and Anomaly and Drift Checks, and the apps' tab titles match. In the browser the coding, PHI and anomaly captions name the `[SI]` stand-ins that run there instead of Needle3, Laya, XGBoost, Isolation Forest and Sinkhorn.
- **Stylesheet retry.** If stlite's stylesheet fails to load, the page fetches it again (after 1 s, then 4 s) and otherwise shows a notice with a Reload button above the app, instead of looking ready while unstyled.
- **CI.** Actions pinned to release commits (checkout v7.0.1, setup-python v7.1.0, both Node 24), and a third harness leg, `browser-stack`: Python 3.14.0 with Streamlit 1.65.0, pandas 3.0.2, numpy 2.4.3 and pyarrow 22.0.0, the versions stlite 1.12.0 runs on Pyodide 314.0.3.
- **Screenshots** in `docs/img/` were recaptured from the in-browser pages, so they say "per-participant" and show the hosted-mode banner and the in-tab "Done" message.
- `CHANGES_FOR_PUBLIC.md` was removed from the tree (a copy is kept privately; it remains in git history).

**Browser checks** (each app, run outside the harness):

- Every page shows the loading notice and the privacy note word for word, its Limits line, and the new tab title; each became interactive in 5.1 to 5.6 s on this machine, at desktop width and with `?demo=1` at 390 px, with no reload needed. Execute rendered results with no exception; the pre-flight panels read "Participants aligned → 52" (risk) and "→ 150" (anomaly); no visible app text outside the tables says "subject".
- The first download saved its file and the results stayed on screen. The four files are byte-identical to a native run of the same apps in hosted mode on the browser stack (Python 3.14.0, Streamlit 1.65.0, pandas 3.0.2), with the optional extras hidden.
- No horizontal scroll at 390 px while loading, when ready or with results; the last download button can be scrolled into view. `?demo=1` reaches Python when hosted mode is switched off for a test run. With the CDN blocked, the page keeps the screenshot and says the app could not start. Zero page errors; every request went to the local server or cdn.jsdelivr.net, none to PyPI, all GET. Off-site fetches from the page and from a worker are refused by the policy, and changed copies of `stlite.js`, its core chunk or `stlite.css` are refused by Subresource Integrity.
- Stylesheet failure: with the first `stlite.css` request aborted, the retry styled the app and no notice showed; with every request aborted, or the file changed so SRI refused it, the notice and Reload button showed (desktop and 390 px) and the app stayed usable. In the final verifier run the test sandbox's network dropped the first `stlite.css` request in 5 of 8 page loads; the retry recovered all 5, so none needed a reload.

**Results.**

| Configuration | Result |
|---|---|
| `requirements.txt` only (Python 3.14.7, Streamlit 1.65.0, pandas 3.1.0) | **263 passed, 0 failed, 5 skipped** |
| `requirements.txt` plus `pyreadstat`, `scikit-learn`, `POT`, `scipy` (Python 3.12.13, Streamlit 1.66.1), the CI `optional-extras` leg | **266 passed, 0 failed, 5 skipped** |
| browser stack: Python 3.14.0, Streamlit 1.65.0, pandas 3.0.2, numpy 2.4.3, pyarrow 22.0.0, the CI `browser-stack` leg | **263 passed, 0 failed, 5 skipped** |

The two new checks are A2c and A6d; RM1 to RM5 are skipped because no models dir was given.

## Verified working (95 checks)

**meddra_app.py:** domain + dictionary load from folder and via upload · verbatim
selector populated from synonyms · pre-flight contract panel · execute produces
one row per candidate (top-3) with integer ranks · exact-match verbatim
AUTO_COMMIT_TO_SDTM, semantic-gap verbatims FLAGGED_FOR_HUMAN_CODER (honest `[SI]`
behavior) · name-only dictionary forces 100% routing and warns in pre-flight ·
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
pre-flight shows the classification + participant count and records the `[SI]` criteria source in the audit ·
every safety score lands in [0,100] and every discontinuation score in [0,1] · all four
safety categories (LOW/MODERATE/HIGH/CRITICAL) are present across the bulk cut · anchor
participants land where designed — fatal `SUBJ-9015` → CRITICAL with its fatality cited alongside the
`AEOUTCOME=DIED` evidence, multi-system `SUBJ-9001` → CRITICAL (its life-threatening cardiac arrest
correctly NOT called fatal since it survived), severe-AE `SUBJ-9002` → HIGH, lab-driven `SUBJ-9013`
cites an ALT breach, ECG-driven `SUBJ-9014` cites QTc · the fatal participant ranks at/above every
non-fatal participant · discontinuation categories for the anchors are correct (fatal → HIGH,
QTc-only → MODERATE) · the raw count/severity/fatal signals are internal and not exported (R5b) · outputs (`risk_scores.csv`, `audit_log.csv`) written · **bit-identical output across two runs**.

**anomaly_app.py:** loads its longitudinal demo from `anomaly_data/` and detects the time column, measurable columns, lab column (per-lab drift ON) and free-text column (text outliers ON) in pre-flight · execute produces flagged-only numeric outliers, cohort + per-lab drift + between-lab/site comparison, and text outliers with no exception · all three injected numeric outliers (`SUBJ-A003`, `SUBJ-A017`, `SUBJ-A029`) are the only participants emitted and each cites its extreme column/z plus the IsolationForest corroborator (A8/A8b/A16) · scores stay discriminative in [0,1] rather than saturating at 1.0 · `ALT` is the top cohort drift column while every stable column stays LOW/MODERATE (A9/A10) — confirming anomaly and drift are separate signals · per-lab drift isolates LAB-C×AST as CRITICAL while the other labs' AST stays LOW/MODERATE (A12/A13) · between-lab/site comparison flags LAB-C×AST as the standout vs the pooled others while the other labs stay LOW/MODERATE (A17/A18) · a mixed longitudinal + cross-sectional upload runs with no exception and still flags all three injected numeric outliers (A19–A20b) · exactly the three injected anomalous notes are flagged in `LABCOM` (A14/A15) · the audit records which numeric/drift/text path ran, matching the installed runtimes (A6/A6b/A6c) · outputs (`anomalies.csv`, `drift.csv`, `lab_drift.csv`, `lab_compare.csv`, `text_anomalies.csv`, `audit_log.csv`) written · **bit-identical output across two runs**.

## How to re-run the tests

The harness lives in [`tests/qc_test.py`](tests/qc_test.py) (portable — its paths
derive from its own location). With the app dependencies installed:

    pip install -r requirements.txt && python tests/qc_test.py

Exit code 0 = every check passes, and the last line reports how many passed, failed and were skipped. With `requirements.txt` only, SAS2, SAS3 and A16 do not run (they need `pyreadstat` or `scikit-learn`); without a models dir, the 5 real-model checks (RM1 to RM5) are reported as skipped. The latest counts are in the newest "New this pass" section above. To run them, build a models dir as in [`eval/README.md`](eval/README.md) and run `ECRF_MODELS_DIR=<models dir> python tests/qc_test.py` with the real runtimes installed. It drives each app end-to-end via
`streamlit.testing.v1.AppTest.from_file(...)`, points the coding/PHI/risk apps at `sample_data/`
and the anomaly app at `anomaly_data/`, clicks Execute, and asserts on the rendered dataframes and
written CSVs — including a synthetic `.asc` release (HLT/HLGT + currency filter), content-based
PHI discovery, SAS `.sas7bdat` input routing, the risk-app anchor participants, and the anomaly app's injected drift column + per-participant outliers. It also runs each app in hosted mode (the H checks, which set and clear `ECRF_HOSTED` and their own scratch secrets themselves, so leave `ECRF_HOSTED` unset and keep any secrets file out of `~/.streamlit/` and `.streamlit/` while it runs) and checks `docs/`, including the in-browser build in `docs/app/` (the D checks). The assertions above are the acceptance criteria; keep them green before sharing a change.

## Known limits (unchanged by QC)

- Coding stand-in retrieval is lexical: `[SI]` scores will not match trained-run
  (`[RM]`) numbers on semantically-gapped verbatims — documented in-app and in
  the audit, never hidden. The real path is measured on synthetic data only
  ([`docs/EVALUATION.md`](docs/EVALUATION.md)); it is not validated on a licensed
  MedDRA release or on real site notes.
- eCRF path only; no scanned-document/bounding-box capability exists here.
- The risk app is **decision support**, not a clinical determination: its `[SI]` weighted
  engine ranks and flags participants for human review but does not predict outcomes with validated
  accuracy, and it scores raw data against built-in `[SI]` criteria rather than parsing free-text PDF/Word protocols or SAPs.
- The anomaly app's detectors default to labeled `[SI]` stand-ins where the runtime is absent: drift uses a 1-D-Wasserstein stand-in (install `POT` + `scipy` for real Sinkhorn optimal transport), numeric outliers run the robust-z gate alone (install `scikit-learn` to add a real Isolation Forest corroborator), and text outliers use bag-of-words isolation (install the internal `cactus-needle`/`laya` packages for real retrieval-isolation). It is decision support — it does not certify data quality or make a clinical determination.
- `sample_data/meddra_demo.csv` is synthetic demo data, not licensed MedDRA.
- Everything in `sample_data/` and `anomaly_data/` is **synthetic** — no real patient, study, or licensed dictionary; regenerate with `python3 sample_data/generate.py` (ae/lb/eg/vs/pe) and `python3 anomaly_data/generate.py` (labs.csv), both deterministic at seed 42.
