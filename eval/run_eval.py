#!/usr/bin/env python3
"""Stages 2-3: calibrate Laya, train the Tier-4 gates, and evaluate stand-in vs real on held-out data.

Run (needs the real runtimes and a models dir holding needle3/ and laya/, see eval/README.md):
    python eval/run_eval.py --models <models_dir>

Reproducible: fixed seeds, deterministic CPU inference, single-threaded HNSW insertion, and the
data in eval/data/ (regenerate with eval/make_data.py, seed 42). Every number in docs/EVALUATION.md
comes from eval/results/stage2_3.json written by this script.

Splits (see make_data.py): train fits the XGBoost gates, calib fits the Laya temperatures (and is
the early-stopping set for XGBoost), test is reported and nothing is fitted on it.

Order of work, per app:
  1. stand-in: the shipped [SI] path, run with the app's own functions on the test split;
  2. features: the real Tier 2 (Needle3) and Tier 3 (Laya, UNCALIBRATED, i.e. the checkpoint's shipped
     temperatures) on every split, from a staging models dir that holds only the two checkpoints;
  3. Laya temperatures fitted on calib (Laya's own fit_temperatures), ECE before/after on test;
  4. XGBoost gate trained on train with the calibrated Tier-3 probabilities as features;
  5. the trained artifacts are written to the models dir and the app is RELOADED from it, and its own
     real path (load_real, t2/t3/t4) runs on the test split: those are the reported real numbers.
"""
import argparse, hashlib, json, os, platform, shutil, sys, tempfile, time
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _app import load_app, ROOT

SEED = 42
DATA = os.path.join(ROOT, "eval", "data")
GATES = (0.88, 0.90)
XGB = dict(objective="binary:logistic", eval_metric="logloss", max_depth=4, eta=0.05, subsample=0.9,
           min_child_weight=1, seed=SEED, nthread=4)

# ------------------------------------------------------------------ helpers
def softmax_true(z, T):
    z = np.asarray(z, float) / T; z -= z.max(); e = np.exp(z); return float(e[-1] / e.sum())

def ece(p, y, bins=10):
    """Expected calibration error, equal-width bins on P(true)."""
    p, y = np.asarray(p, float), np.asarray(y, float); edges = np.linspace(0, 1, bins + 1); tot = 0.0
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= edges[i + 1]))
        if m.any(): tot += m.sum() / len(p) * abs(p[m].mean() - y[m].mean())
    return round(float(tot), 4)

def auroc(p, y):
    p, y = np.asarray(p, float), np.asarray(y, int); pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg): return None
    return round(float((np.sum(pos[:, None] > neg[None, :]) + 0.5 * np.sum(pos[:, None] == neg[None, :])) / (len(pos) * len(neg))), 4)

def brier(p, y): return round(float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2)), 4)

def staging(models, keep):
    """A temp models dir holding symlinks to ONLY the named entries of the real one."""
    d = tempfile.mkdtemp(prefix="ecrf_stage_")
    for k in keep: os.symlink(os.path.join(os.path.abspath(models), k), os.path.join(d, k))
    return d

def laya_records(ns, texts, schema, targets):
    """(qtype, logits, target, k) per (text, question) via Laya's own records_from_labeled."""
    from laya.calibrate import records_from_labeled
    pairs = [(t, schema, {q: ([0.0, 1.0] if targets[q][i] else [1.0, 0.0]) for q in schema}) for i, t in enumerate(texts)]
    recs = records_from_labeled(ns["_router"], pairs)
    assert len(recs) == len(texts) * len(schema), "Laya skipped a record; the logits would misalign"
    return recs

def train_booster(xgb, Xtr, ytr, Xva, yva, names):
    dtr, dva = xgb.DMatrix(Xtr, label=ytr, feature_names=names), xgb.DMatrix(Xva, label=yva, feature_names=names)
    b = xgb.train(XGB, dtr, num_boost_round=600, evals=[(dva, "calib")], early_stopping_rounds=40, verbose_eval=False)
    return xgb.train(XGB, dtr, num_boost_round=b.best_iteration + 1)   # refit to the chosen size, no eval coupling

def question_sha(schema): return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:16]

# ------------------------------------------------------------------ coding
def coding_metrics(rows, gate):
    d = pd.DataFrame(rows); pos = d[d.negated == "N"]
    auto = d.S1 >= gate
    wrong = (d.top1_pt != d.pt_code) | (d.negated == "Y")
    out = dict(n=len(d), top1_acc=round(float((pos.top1_pt == pos.pt_code).mean()), 4),
               top3_acc=round(float(pos.apply(lambda r: r.pt_code in r.top3_pts, axis=1).mean()), 4),
               auto_code_rate=round(float(auto.mean()), 4),
               error_rate_of_auto=round(float((auto & wrong).sum() / max(auto.sum(), 1)), 4),
               errors_per_100=round(float(100 * (auto & wrong).mean()), 2),
               negated_auto_coded=int((auto & (d.negated == "Y")).sum()))
    out["by_variant"] = {v: dict(n=int(len(g)), top1_acc=round(float((g.top1_pt == g.pt_code).mean()), 4) if v != "negated" else None,
                                 auto_code_rate=round(float((g.S1 >= gate).mean()), 4),
                                 errors=int(((g.S1 >= gate) & ((g.top1_pt != g.pt_code) | (g.negated == "Y"))).sum()))
                         for v, g in d.groupby("variant")}
    return out

def run_coding(ns, test, dict_df, use_batch_t3=True):
    """The app's own Tier 2-4 on each test verbatim; returns per-verbatim rows."""
    V, idx = ns["t2_index"](dict_df)
    amb = ns["t3_coding_batch"](list(test.verbatim))
    rows = []
    for i, r in enumerate(test.itertuples()):
        c = ns["t2_coding"](r.verbatim, dict_df, V, idx)
        c, status, top = ns["t4_coding"](c, r.verbatim, 0.0, True, amb[i]["P_UNAMBIGUOUS"])
        rows.append(dict(id=r.id, variant=r.variant, negated=r.negated, pt_code=str(r.pt_code), top1_pt=str(top["PT_CODE"]),
                         top3_pts=[str(x) for x in c["PT_CODE"]], S1=float(top["S"]), p_unamb=amb[i]["P_UNAMBIGUOUS"]))
    return rows

def coding(models, xgb, results):
    print("== coding", flush=True)
    data = pd.read_csv(os.path.join(DATA, "coding_eval.csv"), dtype=str)
    dict_df = pd.read_csv(os.path.join(DATA, "dictionary.csv"), dtype=str)
    test = data[data.split == "test"].reset_index(drop=True)
    # 1. stand-in
    si = load_app("meddra")
    t0 = time.perf_counter(); si_rows = run_coding(si, test, dict_df); si_s = time.perf_counter() - t0
    # 2. real features, Laya uncalibrated, no re-ranker
    os.makedirs(os.path.join(models, "index_cache"), exist_ok=True)      # shared, so the dictionary is embedded once
    st_dir = staging(models, ["needle3", "laya", "index_cache"])
    ns = load_app("meddra", st_dir); assert ns["REAL_T2"] and ns["REAL_T3"] and not ns["REAL_T4"]
    T0 = float(ns["_router"].temperature_by_options["noul:2"])
    lab = {"unambiguous": list(data.negated == "N")}
    t0 = time.perf_counter(); recs = laya_records(ns, list(data.verbatim), ns["CODING_SCHEMA"], lab); laya_s = time.perf_counter() - t0
    z = [r[1] for r in recs]
    # 3. temperatures on calib, ECE on test
    calib_i = list(np.where(data.split == "calib")[0]); test_i = list(np.where(data.split == "test")[0])
    fit = ns["_router"].fit_temperatures([recs[i] for i in calib_i])
    T1 = float(ns["_router"].temperature_by_options["noul:2"])
    p0 = [softmax_true(z[i], T0) for i in range(len(z))]; p1 = [softmax_true(z[i], T1) for i in range(len(z))]
    y = [int(v) for v in lab["unambiguous"]]
    cal = dict(question="unambiguous", temperature_before=round(T0, 4), temperature_after=round(T1, 4), fitted_on=len(calib_i),
               test_n=len(test_i), ece_before=ece([p0[i] for i in test_i], [y[i] for i in test_i]),
               ece_after=ece([p1[i] for i in test_i], [y[i] for i in test_i]),
               brier_before=brier([p0[i] for i in test_i], [y[i] for i in test_i]),
               brier_after=brier([p1[i] for i in test_i], [y[i] for i in test_i]),
               auroc=auroc([p1[i] for i in test_i], [y[i] for i in test_i]), laya_forward_s=round(laya_s, 1))
    os.makedirs(os.path.join(models, "_new"), exist_ok=True)
    ns["_router"].save_calibration(os.path.join(models, "_new", ns["ART_LAYA_CAL"]))
    # 4. re-ranker features on every split (top-RERANK_POOL Needle3 candidates)
    V, idx = ns["t2_index"](dict_df)
    feats, labels, split = [], [], []
    names = ["cosine", "lev", "jaro", "soc_match", "p_unambiguous", "ret_rank"]
    t0 = time.perf_counter()
    for i, r in enumerate(data.itertuples()):
        c = ns["t2_coding"](r.verbatim, dict_df, V, idx, k=ns["RERANK_POOL"])
        for cr in c.itertuples():
            feats.append([cr.cosine, round(ns["_lev"](r.verbatim, cr.LLT), 4), round(ns["_jaro"](r.verbatim, cr.LLT), 4), 1,
                          round(p1[i], 4), cr.rank])
            labels.append(int(str(cr.PT_CODE) == str(r.pt_code) and r.negated == "N")); split.append(r.split)
    feat_s = time.perf_counter() - t0
    X, Y, S = np.array(feats, float), np.array(labels), np.array(split)
    b = train_booster(xgb, X[S == "train"], Y[S == "train"], X[S == "calib"], Y[S == "calib"], names)
    b.save_model(os.path.join(models, "_new", "meddra_coder.json"))
    json.dump(dict(features=names, objective="binary:logistic", requires=dict(T2="needle3", T3="laya"),
                   tier3_question_sha=question_sha(ns["CODING_SCHEMA"]), label="candidate PT == gold PT and verbatim not negated",
                   trained_on=f"eval/data/coding_eval.csv split=train ({int((S=='train').sum())} candidate rows)",
                   early_stopping="calib split", rounds=int(b.num_boosted_rounds()), xgb_params=XGB, seed=SEED),
              open(os.path.join(models, "_new", "meddra_coder.meta.json"), "w"), indent=1)
    # 5. install artifacts and reload the app from the models dir: the reported real path
    for f in os.listdir(os.path.join(models, "_new")): shutil.move(os.path.join(models, "_new", f), os.path.join(models, f))
    os.rmdir(os.path.join(models, "_new"))
    ns = load_app("meddra", models); assert ns["REAL_T2"] and ns["REAL_T3"] and ns["REAL_T4"]
    t0 = time.perf_counter(); real_rows = run_coding(ns, test, dict_df); real_s = time.perf_counter() - t0
    # the reloaded app's calibrated Tier 3 must equal what the re-ranker was trained on
    drift = max(abs(rr["p_unamb"] - p1[test_i[k]]) for k, rr in enumerate(real_rows))
    assert drift < 2e-3, f"calibrated P(unambiguous) in the app differs from training by {drift}"
    # retrieval-only ablation: Needle3 cosine order, no re-rank
    abl = []
    V, idx = ns["t2_index"](dict_df)
    for r in test.itertuples():
        c = ns["t2_coding"](r.verbatim, dict_df, V, idx, k=3)
        abl.append(dict(id=r.id, variant=r.variant, negated=r.negated, pt_code=str(r.pt_code), top1_pt=str(c.iloc[0]["PT_CODE"]),
                        top3_pts=[str(x) for x in c["PT_CODE"]], S1=float(c.iloc[0]["cosine"])))
    results["coding"] = dict(
        data=dict(dictionary_terms=len(dict_df), dictionary_pts=int(dict_df.pt_code.nunique()), test_verbatims=len(test),
                  train_candidate_rows=int((S == "train").sum()), splits=data.split.value_counts().to_dict()),
        calibration=cal, reranker=dict(rounds=int(b.num_boosted_rounds()), features=names),
        timing_s=dict(standin_test=round(si_s, 1), real_test=round(real_s, 1), laya_records_all=round(laya_s, 1), features_all=round(feat_s, 1)),
        gates={str(g): dict(standin=coding_metrics(si_rows, g), real=coding_metrics(real_rows, g)) for g in GATES},
        retrieval_only=dict(top1_acc=coding_metrics(abl, 2.0)["top1_acc"], top3_acc=coding_metrics(abl, 2.0)["top3_acc"],
                            note="Needle3 cosine order, no re-rank; gate not applicable"))
    pd.DataFrame(real_rows).to_csv(os.path.join(ROOT, "eval", "results", "coding_test_real.csv"), index=False)
    pd.DataFrame(si_rows).to_csv(os.path.join(ROOT, "eval", "results", "coding_test_standin.csv"), index=False)
    shutil.rmtree(st_dir, ignore_errors=True)

# ------------------------------------------------------------------ PHI
def phi_eval(pred, gold):
    """Strict span match: (field, start, end, entity) must all agree. Per entity + micro."""
    ents = sorted({g[3] for g in gold} | {p[3] for p in pred}); out = {}
    for e in ents + ["ALL"]:
        P = {p for p in pred if e == "ALL" or p[3] == e}; G = {g for g in gold if e == "ALL" or g[3] == e}
        tp = len(P & G); prec = tp / len(P) if P else None; rec = tp / len(G) if G else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if (P or G) else None)
        out[e] = dict(gold=len(G), predicted=len(P), tp=tp, precision=None if prec is None else round(prec, 4),
                      recall=None if rec is None else round(rec, 4), f1=None if f1 is None else round(f1, 4))
    return out

def leaked(pred, gold):
    """Gold redaction targets with NO overlapping redaction of any type (left readable in the output)."""
    by = {}
    for p in pred: by.setdefault(p[0], []).append(p)
    return sum(1 for g in gold if not any(p[1] < g[2] and g[1] < p[2] for p in by.get(g[0], [])))

def run_phi(ns, fields, gate=0.85):
    texts = list(fields.text); spans = [ns["t2_phi"](t) for t in texts]
    ctx = ns["t3_phi_batch"](texts, spans); pred = []
    for fid, t, sp, cx in zip(fields.field_id, texts, spans, ctx):
        _, flags, _ = ns["t4_phi"](t, sp, cx, gate)
        pred += [(fid, f["START"], f["END"], f["ENTITY"]) for f in flags]
    return pred, spans, ctx

def phi(models, xgb, results):
    print("== phi", flush=True)
    fields = pd.read_csv(os.path.join(DATA, "phi_fields.csv"), dtype={"field_id": str})
    spans = pd.read_csv(os.path.join(DATA, "phi_spans.csv"), dtype={"field_id": str})
    tgt = spans[spans.target == "Y"]
    gold_all = {(r.field_id, int(r.start), int(r.end), r.entity) for r in tgt.itertuples()}
    test = fields[fields.split == "test"].reset_index(drop=True)
    gold_test = {g for g in gold_all if g[0] in set(test.field_id)}
    # 1. stand-in
    si = load_app("phi")
    t0 = time.perf_counter(); si_pred, _, _ = run_phi(si, test); si_s = time.perf_counter() - t0
    # 2. real features: Needle3 + Laya (uncalibrated). Without a gate the app keeps Needle3 OFF on purpose
    #    (load_real), so the proposer is switched on here, exactly as load_real builds it, to collect features.
    st_dir = staging(models, ["needle3", "laya"]); ns = load_app("phi", st_dir)
    os.environ["NEEDLE3_LIB_PATH"] = os.path.join(os.path.abspath(models), "needle3", ns["_engine_file"]())
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ns["_agent"] = ns["needle"].Needle(tools=[ns["PHI_EXTRACT_SCHEMA"]], weights=os.path.join(models, ns["ART_NEEDLE"]),
                                           auto_date=False, stateless=True)
    ns["REAL_T2"] = True; assert ns["REAL_T3"] and not ns["REAL_T4"]
    T0 = float(ns["_router"].temperature_by_options["noul:2"])
    lab = {"direct_pii": list(fields.has_direct == "Y"), "reident_risk": list(fields.has_quasi == "Y")}
    t0 = time.perf_counter(); recs = laya_records(ns, list(fields.text), ns["PHI_SCHEMA"], lab); laya_s = time.perf_counter() - t0
    qs = list(ns["PHI_SCHEMA"]); nq = len(qs)
    zq = {q: [recs[i * nq + j][1] for i in range(len(fields))] for j, q in enumerate(qs)}
    calib_i = list(np.where(fields.split == "calib")[0]); test_i = list(np.where(fields.split == "test")[0])
    ns["_router"].fit_temperatures([recs[i * nq + j] for i in calib_i for j in range(nq)])
    T1 = float(ns["_router"].temperature_by_options["noul:2"])
    os.makedirs(os.path.join(models, "_new"), exist_ok=True)
    ns["_router"].save_calibration(os.path.join(models, "_new", ns["ART_LAYA_CAL"]))
    pq = {q: [softmax_true(z, T1) for z in zq[q]] for q in qs}; pq0 = {q: [softmax_true(z, T0) for z in zq[q]] for q in qs}
    cal = {}
    for q in qs:
        y = [int(v) for v in lab[q]]; yt = [y[i] for i in test_i]
        cal[q] = dict(temperature_before=round(T0, 4), temperature_after=round(T1, 4), fitted_on=len(calib_i), test_n=len(test_i),
                      ece_before=ece([pq0[q][i] for i in test_i], yt), ece_after=ece([pq[q][i] for i in test_i], yt),
                      brier_before=brier([pq0[q][i] for i in test_i], yt), brier_after=brier([pq[q][i] for i in test_i], yt),
                      auroc=auroc([pq[q][i] for i in test_i], yt))
    # candidates + gate features on every split, with the calibrated Tier-3 probabilities
    t0 = time.perf_counter(); cand = [ns["t2_phi"](t) for t in fields.text]; needle_s = time.perf_counter() - t0
    names = None; X, Y, S, abl = [], [], [], []
    for i, (fid, t, sp) in enumerate(zip(fields.field_id, fields.text, cand)):
        cx = dict(P_DIRECT=round(pq["direct_pii"][i], 4), P_QUASI=round(pq["reident_risk"][i], 4))
        rows = ns["_span_features"](t, sp, cx)
        if rows and names is None: names = list(rows[0].keys())
        for c, r in zip(sp, rows):
            X.append([r[n] for n in names]); Y.append(int((fid, c[2], c[3], c[1]) in gold_all)); S.append(fields.split[i])
        if fields.split[i] == "test": abl += [(fid, c[2], c[3], c[1]) for c in sp if c[4] in ("needle", "both")]
    X, Y, S = np.array(X, float), np.array(Y), np.array(S)
    b = train_booster(xgb, X[S == "train"], Y[S == "train"], X[S == "calib"], Y[S == "calib"], names)
    b.save_model(os.path.join(models, "_new", "phi_token_classifier.json"))
    json.dump(dict(features=names, objective="binary:logistic", requires=dict(T2="needle3", T3="laya"),
                   tier3_question_sha=question_sha(ns["PHI_SCHEMA"]), label="candidate (start,end,entity) is a gold redaction target",
                   trained_on=f"eval/data/phi_fields.csv split=train ({int((S=='train').sum())} candidate spans)",
                   early_stopping="calib split", rounds=int(b.num_boosted_rounds()), xgb_params=XGB, seed=SEED),
              open(os.path.join(models, "_new", "phi_token_classifier.meta.json"), "w"), indent=1)
    for f in os.listdir(os.path.join(models, "_new")): shutil.move(os.path.join(models, "_new", f), os.path.join(models, f))
    os.rmdir(os.path.join(models, "_new"))
    # 5. reload from the models dir and run the app's own real path on test
    ns = load_app("phi", models); assert ns["REAL_T2"] and ns["REAL_T3"] and ns["REAL_T4"]
    t0 = time.perf_counter(); real_pred, _, real_ctx = run_phi(ns, test); real_s = time.perf_counter() - t0
    drift = max(max(abs(c["P_DIRECT"] - pq["direct_pii"][test_i[k]]), abs(c["P_QUASI"] - pq["reident_risk"][test_i[k]]))
                for k, c in enumerate(real_ctx))
    assert drift < 2e-3, f"calibrated Tier-3 probabilities in the app differ from training by {drift}"
    gold_by_kind = lambda kind: {g for g in gold_test if (g[3] in ns["DIRECT"]) == (kind == "direct")}
    results["phi"] = dict(
        data=dict(test_fields=len(test), test_targets=len(gold_test), splits=fields.split.value_counts().to_dict(),
                  train_candidate_spans=int((S == "train").sum()), test_templates=sorted(test.template.unique())),
        calibration=cal, gate=dict(rounds=int(b.num_boosted_rounds()), features=names),
        timing_s=dict(standin_test=round(si_s, 1), real_test=round(real_s, 1), laya_records_all=round(laya_s, 1), needle_all=round(needle_s, 1)),
        standin=dict(per_entity=phi_eval(set(si_pred), gold_test), leaked_targets=leaked(si_pred, gold_test),
                     leaked_direct=leaked(si_pred, gold_by_kind("direct"))),
        real=dict(per_entity=phi_eval(set(real_pred), gold_test), leaked_targets=leaked(real_pred, gold_test),
                  leaked_direct=leaked(real_pred, gold_by_kind("direct"))),
        needle_extraction_only=dict(per_entity=phi_eval(set(abl), gold_test),
                                    note="grounded Needle3 values used directly as redactions (no gate); shows the extractor alone"))
    shutil.rmtree(st_dir, ignore_errors=True)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--models", required=True); ap.add_argument("--only", choices=["coding", "phi"])
    a = ap.parse_args()
    import xgboost as xgb, needle, laya, hnswlib, torch, transformers
    from importlib.metadata import version
    os.makedirs(os.path.join(ROOT, "eval", "results"), exist_ok=True)
    out_p = os.path.join(ROOT, "eval", "results", "stage2_3.json")
    results = json.load(open(out_p)) if (a.only and os.path.exists(out_p)) else {}
    try: cpu = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except Exception: cpu = platform.machine()
    results["environment"] = dict(cpu=cpu, cores=os.cpu_count(), python=platform.python_version(), torch_threads=torch.get_num_threads(),
                                  versions={p: version(p) for p in ("cactus-needle", "laya", "hnswlib", "xgboost-cpu", "torch", "transformers")
                                            if _has_dist(p)})
    if a.only in (None, "coding"): coding(a.models, xgb, results)
    if a.only in (None, "phi"): phi(a.models, xgb, results)
    json.dump(results, open(out_p, "w"), indent=1, default=str)
    art = os.path.join(ROOT, "eval", "artifacts"); os.makedirs(art, exist_ok=True)
    for f in ("laya_calibration_coding.json", "meddra_coder.json", "meddra_coder.meta.json",
              "laya_calibration_phi.json", "phi_token_classifier.json", "phi_token_classifier.meta.json"):
        if os.path.exists(os.path.join(a.models, f)): shutil.copy(os.path.join(a.models, f), art)
    print("wrote", out_p)

def _has_dist(p):
    try:
        from importlib.metadata import version; version(p); return True
    except Exception: return False

if __name__ == "__main__":
    main()
