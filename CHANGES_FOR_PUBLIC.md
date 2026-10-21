# Changes from `~/biostat_pipeline_apps` for the public copy (2026-10-21)

The original folder is untouched. This copy differs in the following ways. Port any of them back by hand if you want them in the original.

1. **Placeholder dictionary codes.** Every 8-digit code of the form `10xxxxxx` became `99xxxxxx` (same last six digits, so the hierarchy links stay consistent). That is 98 codes across `sample_data/meddra_demo.csv`, `tests/qc_test.py`, one comment in `meddra_app.py`, and the Deck B `.md`/`.html`. Several of the originals were real MedDRA codes (e.g. 10019211 Headache, 10027599 Migraine, 10012735 Diarrhoea), which contradicted the "NOT licensed MedDRA" label.
2. **Deck B performance figures.** "Deployed index parameters and measured costs:" now reads "Reference parameters and costs for the full model stack (not produced by the stand-in build in this repository):", in both `.md` and `.html`. The numbers themselves are unchanged. **Patrick to decide:** if you measured them on a real setup, say where and when instead.
3. **Deck A dictionary sentence.** The "full active MedDRA release" sentence now adds "(a licensed release the user supplies; none is included here)", in both `.md` and `.html`.
4. **"Internal packages."** `cactus-needle`/`laya` are now described as "packages not distributed with this repository", in `anomaly_app.py`, `USER_GUIDE.md` and `requirements.txt`. **Patrick to confirm** what these packages are and where they come from before publishing. One test label in `tests/qc_test.py` still says "internal pkgs"; it is harmless.
5. **Sample-data toggle.** Each app's sidebar has a new checkbox, "Use the bundled synthetic sample data". It is off by default and fills the folder path with `sample_data/` (or `anomaly_data/` for the anomaly app). Opening the app with `?demo=1` starts it ticked, for hosted demos. Tests find widgets by label, so nothing else moved.
6. **Docs and housekeeping.**
   - `README.md` has a new "Hosted demo (no install)" section.
   - `sample_data/README.md` notes the placeholder codes.
   - `.gitignore` now ignores `.DS_Store`, `.claude/`, `.agents/` and `meddra_output/`.
   - Left out of the copy: `.venv`, `__pycache__`, the `*_output` folders, `.claude/` and `.agents/` (agent skill folders).

## Verification

- `tests/qc_test.py`: **95 passed, 0 failed**, run on this copy with the original `.venv` interpreter.
- The toggle was tested in all four apps with Streamlit's `AppTest`: off by default with an empty path; ticked, it fills the right folder; `?demo=1` fills it on load. Zero exceptions.
- A search finds no `10xxxxxx` codes left, no Syneos mentions and no keys or tokens.

## Still open before publishing

- Items 2 and 4 above.
- The timing question for your attorney: the apps were built Oct 13 to 15, during employment, and the severance release is still unsigned.
- Pick a license. None is included.
