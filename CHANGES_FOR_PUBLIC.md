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

## Verification

- `tests/qc_test.py`: **95 passed, 0 failed**, run on this copy with the original `.venv` interpreter.
- The toggle was tested in all four apps with Streamlit's `AppTest`: off by default with an empty path; ticked, it fills the right folder; `?demo=1` fills it on load. Zero exceptions.
- A search finds no `10xxxxxx` codes left, no Syneos mentions and no keys or tokens.

## License

Apache-2.0 (`LICENSE`). `NOTICE` adds the copyright line and notes that the sample data is synthetic and MedDRA is not included.
