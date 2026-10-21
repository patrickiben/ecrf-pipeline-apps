# Changes from `~/biostat_pipeline_apps` for the public copy (2026-10-21)

The original folder is untouched. This copy differs in the following ways. Port any of them back by hand if you want them in the original.

1. **Placeholder dictionary codes.** Every 8-digit code of the form `10xxxxxx` became `99xxxxxx` (same last six digits, so the hierarchy links stay consistent). That is 98 codes across `sample_data/meddra_demo.csv`, `tests/qc_test.py`, one comment in `meddra_app.py`, and the Deck B `.md`/`.html`. Several of the originals were real MedDRA codes (e.g. 10019211 Headache, 10027599 Migraine, 10012735 Diarrhoea), which contradicted the "NOT licensed MedDRA" label.
2. **Deck B `[RM]` numbers marked illustrative.** These first appeared in the Oct 13 AI chat export (`~/Desktop/chat-Biostatistics Pipeline Improvement.txt`). No trained checkpoint or measurement log exists on this Mac, so they are not measurements. The changes:
   - A note under the Deck B title explains this.
   - The legend now defines `[RM]` as "an illustrative value for what the trained component would output on this record (not measured; no trained checkpoint was run)".
   - The index-cost sentence says "Illustrative … (not measured …)".
   - The verify slide now says 95 checks instead of 41.
   - All edits are in both `.md` and `.html`; the numbers themselves are unchanged. Every `[SI]` number remains real stand-in output.
   - Deck A: Laya's "~33 ms" is attributed to its authors.
3. **Deck A dictionary sentence.** The "full active MedDRA release" sentence now adds "(a licensed release the user supplies; none is included here)", in both `.md` and `.html`.
4. **"Internal packages" corrected.** Needle3 (Cactus Compute, Apache-2.0) and Laya are public open-source models. They are now described as "open-source … not bundled with this repository" in `anomaly_app.py`, `USER_GUIDE.md` and `requirements.txt`. The pip names in `requirements.txt` (`cactus-needle`, `laya`) were not checked against PyPI.
5. **Sample-data toggle.** Each app's sidebar has a new checkbox, "Use the bundled synthetic sample data". It is off by default and fills the folder path with `sample_data/` (or `anomaly_data/` for the anomaly app). Opening the app with `?demo=1` starts it ticked, for hosted demos. Tests find widgets by label, so nothing else moved.
6. **Docs and housekeeping.**
   - `README.md` has a new "Hosted demo (no install)" section.
   - `sample_data/README.md` notes the placeholder codes.
   - `.gitignore` now ignores `.DS_Store`, `.claude/`, `.agents/` and `meddra_output/`.
   - Left out of the copy: `.venv`, `__pycache__`, the `*_output` folders, `.claude/` and `.agents/` (agent skill folders).
7. **Hosted-demo safety mode, CI and landing page.** These make a public demo safe to share and keep the copy tested.
   - Hosted mode, in all four apps, is switched on by the Streamlit secret `hosted = true` or the environment variable `ECRF_HOSTED=1`. It locks every data input (uploaders, folder path, models dir and, in the coding app, the dictionary inputs) to the bundled synthetic cut, both in the UI and in code, writes outputs to a per-session temp folder, shows a "synthetic data only" banner and records `hosted_mode=true` in the audit. It is off by default; a local run only gains `hosted_mode=false` in its audit. No widget label changed.
   - `.github/workflows/qc.yml` runs `tests/qc_test.py` on every push and pull request, with and without the optional extras. `requirements.txt` now asks for `streamlit>=1.49`, because older releases crash on `st.dataframe(width="stretch")`.
   - The switch fails closed after a security review: any `ECRF_HOSTED` or `hosted` value other than empty, `0`, `false`, `no` or `off` turns it on, and so do a secrets file that exists but does not parse and an `ECRF_HOSTED` key in the secrets. Hosted mode also hides uncaught-error details from visitors and deletes each session's temp folder when the session ends. The README deploy steps add a banner check and an upload-size cap for self-managed hosts.
   - `tests/qc_test.py` gained 149 hosted-mode checks and 3 docs checks: **247 passed, 0 failed** with the optional extras (`pyreadstat`, `scikit-learn`, `POT`, `scipy`) installed, and **244 passed, 0 failed** with `requirements.txt` only.
   - The Deck B verify slide no longer quotes a check count (it said 95), in both `.md` and `.html` and in the `docs/` copy, so it cannot go stale again.
   - Deck B HTML rendering fixes (the `.md` was already right): four slide headings had lost their first letter ("race 1", "race 2", "race legend", "erify this walkthrough yourself"), 14 headings closed with a malformed `</h3 class="slide-h">` tag, and the initials regex on slide 2.2 had turned into a stray link. Fixed in `presentations/` and the `docs/` copy.
   - `docs/` is a GitHub Pages landing page: `index.html` (self-contained, no external resources), byte-identical copies of the two HTML decks, four screenshots of local runs on the synthetic data, and an empty `.nojekyll`. The owner must enable Pages (Settings > Pages > Deploy from a branch, `main`, `/docs`); the demo links on the page are placeholders until the apps are deployed.
   - `README.md` has a QC badge and new "Deploy your own demo", Screenshots and Landing page sections. `QC_REPORT.md` and `USER_GUIDE.md` describe hosted mode and the new check counts.

## Verification

- `tests/qc_test.py`: **95 passed, 0 failed**, run on this copy with the original `.venv` interpreter (at the time of the public copy, before item 7; item 7 has the current 247/244).
- The toggle was tested in all four apps with Streamlit's `AppTest`: off by default with an empty path; ticked, it fills the right folder; `?demo=1` fills it on load. Zero exceptions.
- A search finds no `10xxxxxx` codes left, no Syneos mentions and no keys or tokens.

## License

Apache-2.0 (`LICENSE`). `NOTICE` adds the copyright line and notes that the sample data is synthetic and MedDRA is not included.
