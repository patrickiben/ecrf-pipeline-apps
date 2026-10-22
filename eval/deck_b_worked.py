#!/usr/bin/env python3
"""Stage 4: re-run the Deck B worked examples on the REAL path and record the measured values.

Run (after eval/run_eval.py has written the trained artifacts into the models dir):
    python eval/deck_b_worked.py --models <models_dir>

Drives both apps END TO END with Streamlit's AppTest on sample_data/ (the cut Deck B walks through)
with the given models dir, exactly as a user would, and reads their written outputs. Tier-3 field
probabilities are not exported by the PHI app, so they come from the app's own t3_phi_batch on the
same texts. Writes eval/results/deck_b_worked.json; the RM checks in tests/qc_test.py assert that a
real-path run reproduces these values.
"""
import argparse, json, os, sys, tempfile
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _app import load_app, ROOT
from streamlit.testing.v1 import AppTest

SAMPLE = os.path.join(ROOT, "sample_data")
WORKED_AE = ["severe throbbing pain in back of head", "feeling lightheaded when standing up",
             "frequent watery bowel movements", "marked prolonged heart rhythm interval"]

def run(app, models, gate=None):
    out = tempfile.mkdtemp(prefix="deckb_")
    at = AppTest.from_file(os.path.join(ROOT, app), default_timeout=3600); at.run()
    f = lambda kind, lab: next(w for w in getattr(at, kind) if w.label == lab)
    f("text_input", "Cut folder path (domain CSVs)").set_value(SAMPLE).run()
    f("text_input", "Models dir (optional real weights)").set_value(models).run()
    f("text_input", "Output folder").set_value(out).run()
    if gate is not None: f("slider", "Auto-commit gate").set_value(gate).run()
    btn = next(b for b in at.button if b.label.startswith("🚀")); btn.set_value(True).run()
    assert not at.exception, [str(e.value) for e in at.exception]
    banner = next(i.value for i in at.info if "Mode banner" in i.value)
    return out, banner

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--models", required=True); a = ap.parse_args()
    rec = {}
    out, banner = run("meddra_app.py", a.models, gate=0.90)
    cod = pd.read_csv(os.path.join(out, "ae_coded.csv")); aud = pd.read_csv(os.path.join(out, "audit_log.csv")).iloc[0]
    w = cod[cod.VERBATIM.isin(WORKED_AE)]
    rec["coding_banner"] = banner; rec["coding_artifacts"] = aud["real_artifacts"]; rec["coding_gate"] = 0.90
    rec["coding_top3"] = {v: [dict(rank=int(r["rank"]), LLT=r.LLT, PT=r.AEDECOD, PT_CODE=str(r.AEPTCD), cosine=round(float(r.cosine), 4),
                                   S=round(float(r.S), 4)) for _, r in g.sort_values("rank").iterrows()] for v, g in w.groupby("VERBATIM")}
    r1 = w[w["rank"] == 1]
    rec["coding"] = {r.VERBATIM: dict(AEDECOD=r.AEDECOD, AEPTCD=str(r.AEPTCD), AESOC=r.AESOC, S=round(float(r.S), 4),
                                      AECODSTAT=r.AECODSTAT) for r in r1.itertuples()}
    ns = load_app("meddra", a.models)
    rec["coding_p_unambiguous"] = dict(zip(WORKED_AE, [x["P_UNAMBIGUOUS"] for x in ns["t3_coding_batch"](WORKED_AE)]))
    out, banner = run("phi_app.py", a.models)
    fl = pd.read_csv(os.path.join(out, "phi_flags.csv"))
    rec["phi_banner"] = banner
    keep = ((fl.FIELD.isin(["AECOM"]) & fl.USUBJID.isin(["SUBJ-3092"]) & fl.ROW.isin([1, 2])) | (fl.FIELD == "PRDSC"))
    rec["phi_redact"] = {f"{r.DOMAIN}|{r.ROW}|{r.FIELD}|{r.SPAN}": round(float(r.P_REDACT), 4) for r in fl[keep].itertuples()}
    rec["phi_flags_total"] = int(len(fl))
    san = pd.read_csv(os.path.join(out, "sanitized", "ae.csv"))
    rec["phi_sanitized_ae"] = {f"{r.USUBJID}|{r.AESEQ}": r.SAN_AECOM for r in san.itertuples() if r.USUBJID == "SUBJ-3092" and r.AESEQ in (1, 2)}
    texts = {"AE|1|AECOM": "CRC Note: Patient Jane Miller called site cell phone (617) 555-0192 at 10:15 AM.",
             "AE|2|AECOM": "Patient Jane Miller tolerating well; continued Alanine 50 mg; repeat glucose 120 mg/dL.",
             "PR|1|PRDSC": pd.read_csv(os.path.join(SAMPLE, "pr.csv")).PRDSC.iloc[0],
             "EG|1|EGCOM": "Sinus rhythm, no artifact."}
    ns = load_app("phi", a.models)
    sp = [ns["t2_phi"](t) for t in texts.values()]
    rec["phi_tier3"] = dict(zip(texts, ns["t3_phi_batch"](list(texts.values()), sp)))
    rec["phi_tier2_sources"] = {k: [(s[0], s[1], s[2], s[3], s[4]) for s in v] for k, v in zip(texts, sp)}
    json.dump(rec, open(os.path.join(ROOT, "eval", "results", "deck_b_worked.json"), "w"), indent=1, default=str)
    print(json.dumps(rec, indent=1, default=str))

if __name__ == "__main__":
    main()
