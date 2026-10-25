#!/usr/bin/env python3
"""Known-answer demo for the within-sibling evaluation (SYNTHETIC; registered in eval/sibling_plan.md, section 13).

Run from anywhere:   python eval/sibling_knownanswer.py      (writes eval/results/sibling_knownanswer.csv)

Five planted scorers on simulated lab clusters, each with an answer the statistics must recover:
  (a) accurate but not enough  q_c ~ Beta(8, 2): beats chance clearly, yet must fail the 0.90 accuracy floor
  (b) base-rate follower       always increased > decreased > abnormal: beats uniform chance (N1) but not the
                               base-rate null (N2), and fails both gates
  (c) pure noise               iid N(0, 1) scores: every null holds its size; M's p-values are uniform
  (d) good enough              q_c ~ Beta(97, 3): passes the floor at 120 clusters and beats the keyword rule
  (e) bound coverage           true accuracy 0.85 with intraclass correlation 0.2: the Gate A bound sits below
                               0.85 in at least 93% of datasets (also reported, outside the plan: the coverage
                               with the design effect left out, which shows what this criterion alone can detect)
Like eval/sibling_eval.py it refuses to run unless the plan's SHA-256 matches eval/sibling_plan.sha256 and every
input file's SHA-256 matches the plan (it reads the lab sets from eval/data/sibling_sets.csv), and it reads every
parameter from the plan. It never calls the coding app's scorer, so unlike sibling_eval.py it does not check the
scorer fingerprint. The statistics are the ones sibling_eval.py uses, imported from it.
tests/test_sibling.py runs the same demo at reduced replicates.
"""
import argparse, csv, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sibling_eval as S

ROLES = ("increased", "decreased", "abnormal")
SCORERS = "abcde"
VARIANTS = ("exact", "colloquial", "misspelled")   # labels for the 3 items of a cluster; item 1 carries N3

def normal(rng, shape):
    """Standard normal draws by Box-Muller from random() (the plan's streams use random() only)."""
    u1 = 1.0 - rng.random(shape); u2 = rng.random(shape)
    return np.sqrt(-2.0 * np.log(u1)) * np.cos(2.0 * np.pi * u2)

def categorical(u, probs):
    cum = np.cumsum(probs); cum = cum / cum[-1]; cum[-1] = 1.0
    return np.minimum((np.asarray(u)[..., None] >= cum).sum(-1), len(probs) - 1)

def dataset(kind, rng, K, n_stems):
    """One simulated dataset: (items, T, keyword_correct). items mimic sibling_eval's item dicts."""
    m, r = int(K["clusters"]), int(K["items_per_cluster"]); probs = np.array([K["role_probs"][x] for x in ROLES])
    stem = np.minimum((rng.random(m) * n_stems).astype(int), n_stems - 1)            # a real lab set, for its label only
    gold = categorical(rng.random(m), probs)
    hist = np.bincount(categorical(rng.random(int(K["historical_draws"])), probs), minlength=3) + 1
    if kind in "ade":
        a, b = K[f"{kind}_beta"]; q = S.beta_ppf(rng.random(m), float(a), float(b))
        correct = rng.random((m, r)) < q[:, None]
        other = np.minimum((rng.random((m, r)) * 2).astype(int), 1)
        pick = np.where(correct, gold[:, None], (gold[:, None] + 1 + other) % 3)
        (mu1, sd1), (mu0, sd0) = K["pick_score"], K["other_score"]
        T = mu0 + sd0 * normal(rng, (m, r, 3))
        np.put_along_axis(T, pick[:, :, None], mu1 + sd1 * normal(rng, (m, r, 1)), axis=2)
    elif kind == "b": T = np.broadcast_to(np.array(K["b_scores"], float), (m, r, 3)).copy()
    else: T = normal(rng, (m, r, 3))
    kw = rng.random((m, r)) < float(K["keyword_accuracy"])
    member_draw = rng.random((m, 3)) < float(K["n3_member_prob"])
    items, TT = [], []
    for c in range(m):
        code = lambda role: f"KA{c:03d}:{role}"
        members = [(role, code(role), f"stem{stem[c]} {role}") for role in ROLES]
        lex = {int(gold[c])} | {k for k in range(3) if k != gold[c] and member_draw[c, k]}
        for j in range(r):
            items.append(dict(id=f"KA{c:03d}{j}", variant=VARIANTS[j % 3], family="lab", gold_code=code(ROLES[gold[c]]),
                              gold_role=ROLES[gold[c]], members=members, w=dict(zip(ROLES, hist.tolist())),
                              lex_set=lex if j == int(K["n3_item"]) else set()))
            TT.append(list(T[c, j]))
    return items, TT, kw.reshape(-1).astype(float)

def one(kind, s_idx, ds, P, B_mc, B_boot, n_stems):
    """All statistics for one dataset of one scorer."""
    K = P["knownanswer"]; rng = S.rng_for(P, "knownanswer", s_idx, ds)
    items, T, kw = dataset(kind, rng, K, n_stems)
    clusters = [it["gold_code"] for it in items]
    picks = [S.pick_with_ties(t, rng.random(), float(P["tie_tolerance"])) for t in T]
    if kind == "e":
        gold = [[c for _, c, _ in it["members"]].index(it["gold_code"]) for it in items]
        correct = np.array([p[0] == g for p, g in zip(picks, gold)], float)
        A = S.gate_a(correct, clusters, float(P["alpha"]), float(P["a_min"]))
        n = len(correct)          # the same bound with the design effect left out (deff = 1): reported, not registered
        no_deff = S.cp_lower(math.floor(A["F"] * n + 1e-9), n, float(P["alpha"]))
        return dict(F=A["F"], bound=A["bound"], gate_a=A["passed"], rho=A["rho_hat"], bound_no_deff=no_deff)
    a = S.analyze(items, T, P, 0, 0, picks, B_mc=B_mc, rng_tag=("knownanswer", s_idx, ds),
                  only={"N1": ["all"], "N2": ["all"], "N3": ["colloquial"]})
    out = dict(F=a["F"], M=a["M"])
    for null, rows in a["null_tests"].items():
        for r in rows:
            if r.get("p") is None: continue
            out[f"p{r['stat']}_{null}"] = r["p"]; out[f"q{r['stat']}_{null}"] = r.get("q_bh")
    A = S.gate_a(a["correct"], clusters, float(P["alpha"]), float(P["a_min"]))
    Bg = S.gate_b(a["correct"] - kw, clusters, B_boot, S.rng_for(P, "knownanswer", s_idx, ds, 9), float(P["alpha"]))
    out.update(bound=A["bound"], gate_a=A["passed"], gate_b=Bg["passed"], gate_b_lb=Bg["lower_bound"])
    return out

def _rate(x):
    x = np.asarray(x, float); r = float(x.mean()); return r, math.sqrt(r * (1 - r) / len(x))

def criteria(res, P, R, Rcov, crit=None):
    """Rows: scorer, check, value, mcse, criterion, met. crit defaults to the plan's registered criteria."""
    C = crit or P["knownanswer"]["criteria"]; al = float(P["alpha"]); rows = []
    def add(s, check, val, se, text, met): rows.append(dict(scorer=s, check=check, value=val, mcse=se, criterion=text,
                                                          met=None if met is None else bool(met), datasets=Rcov if s == "e" else R))
    if "a" in res:
        d = res["a"]; v, se = _rate([x["qF_N1"] < al and x["qF_N2"] < al for x in d])
        add("a", "q_F < 0.05 under both N1 and N2", v, se, f">= {C['a_joint_q_rate_min']}", v >= C["a_joint_q_rate_min"])
        v, se = _rate([not x["gate_a"] for x in d]); add("a", "Gate A fails", v, se, f">= {C['a_gate_a_fail_min']}", v >= C["a_gate_a_fail_min"])
        v = float(np.mean([x["F"] for x in d])); add("a", "mean F (reported)", v, float(np.std([x["F"] for x in d]) / math.sqrt(len(d))), "reported", None)
    if "b" in res:
        d = res["b"]; F = [x["F"] for x in d]; v = float(np.mean(F)); lo, hi = C["b_mean_f"]
        add("b", "mean F", v, float(np.std(F) / math.sqrt(len(F))), f"in [{lo}, {hi}]", lo <= v <= hi)
        v, se = _rate([x["pF_N1"] < al for x in d]); add("b", "N1 rejects (p_F < 0.05)", v, se, f">= {C['b_n1_reject_min']}", v >= C["b_n1_reject_min"])
        lo, hi = C["b_n2_reject"]; v, se = _rate([x["pF_N2"] < al for x in d])
        add("b", "N2 rejects (p_F < 0.05)", v, se, f"in [{lo}, {hi}]", lo <= v <= hi)
        v, se = _rate([not x["gate_a"] for x in d]); add("b", "Gate A fails", v, se, f">= {C['b_gate_a_fail_min']}", v >= C["b_gate_a_fail_min"])
        v, se = _rate([not x["gate_b"] for x in d]); add("b", "Gate B fails", v, se, f">= {C['b_gate_b_fail_min']}", v >= C["b_gate_b_fail_min"])
        v, se = _rate([x["pM_N2"] < al for x in d]); add("b", "N2 rejects on M (p_M < 0.05, reported)", v, se, "reported", None)
    if "c" in res:
        d = res["c"]
        for null in ("N1", "N2", "N3"):
            v, se = _rate([x[f"pF_{null}"] < al for x in d if f"pF_{null}" in x])
            add("c", f"{null} rejects on F (p_F < 0.05)", v, se, f"<= {C['c_reject_max']}", v <= C["c_reject_max"])
        for null in ("N1", "N2", "N3"):
            D, pks = S.ks_uniform([x[f"pM_{null}"] for x in d if f"pM_{null}" in x])
            add("c", f"KS of p_M under {null} against uniform (p-value; D = {D:.4f})", pks, None, f">= {C['c_ks_p_min']}", pks >= C["c_ks_p_min"])
            v, se = _rate([x[f"pM_{null}"] < al for x in d if f"pM_{null}" in x]); add("c", f"{null} rejects on M (reported)", v, se, "reported", None)
    if "d" in res:
        d = res["d"]; v, se = _rate([x["gate_a"] for x in d]); add("d", "Gate A passes", v, se, f"> {C['d_gate_a_pass_min']} (rate reported)", v > C["d_gate_a_pass_min"])
        v, se = _rate([x["gate_b"] for x in d]); add("d", "Gate B passes", v, se, f">= {C['d_gate_b_pass_min']}", v >= C["d_gate_b_pass_min"])
        v = float(np.mean([x["F"] for x in d])); add("d", "mean F (reported)", v, float(np.std([x["F"] for x in d]) / math.sqrt(len(d))), "reported", None)
        v = float(np.mean([x["bound"] for x in d])); add("d", "mean Gate A bound (reported)", v, float(np.std([x["bound"] for x in d]) / math.sqrt(len(d))), "reported", None)
    if "e" in res:
        d = res["e"]; t = float(P["knownanswer"]["e_true_accuracy"]); v, se = _rate([x["bound"] < t for x in d])
        add("e", f"Gate A bound below the true accuracy {t}", v, se, f">= {C['e_coverage_min']}", v >= C["e_coverage_min"])
        v = float(np.mean([x["rho"] for x in d])); add("e", "mean estimated intraclass correlation (reported; true 0.2)", v, float(np.std([x["rho"] for x in d]) / math.sqrt(len(d))), "reported", None)
        v, se = _rate([x["bound_no_deff"] < t for x in d])
        add("e", f"Gate A bound below {t} with the design effect left out (reported, added after review, not registered: what (e) alone can detect)", v, se, "reported", None)
    return rows

def run_knownanswer(P, datasets=None, coverage_datasets=None, B_mc=None, B_boot=None, scorers=SCORERS, crit=None):
    K = P["knownanswer"]; R = int(datasets or K["datasets"]); Rcov = int(coverage_datasets or K["coverage_datasets"])
    B_mc = int(B_mc or P["B_mc"]); B_boot = int(B_boot or P["B_boot"])
    import sibling_sets
    n_stems = len(sibling_sets.load(os.path.join(S.DATA, "sibling_sets.csv"))["lab"])
    res = {}
    for s in scorers:
        s_idx = SCORERS.index(s)
        res[s] = [one(s, s_idx, ds, P, B_mc, B_boot, n_stems) for ds in range(Rcov if s == "e" else R)]
    return criteria(res, P, R, Rcov, crit), res

def main(argv=None):
    ap = argparse.ArgumentParser(description="Known-answer demo for the within-sibling evaluation (eval/sibling_plan.md, section 13)")
    ap.add_argument("--out", default=S.RESULTS); ap.add_argument("--plan", default=S.PLAN, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    try:
        P, sha = S.check_plan(a.plan, S.PLAN_HASH)
        S.check_inputs(P)                       # exit 3 on a changed input; the demo reads eval/data/sibling_sets.csv
    except S.Refusal as e: print("REFUSED: " + str(e), file=sys.stderr); return e.code
    rows, _ = run_knownanswer(P)
    os.makedirs(a.out, exist_ok=True); p = os.path.join(a.out, "sibling_knownanswer.csv")
    cols = ["scorer", "check", "value", "mcse", "criterion", "met", "datasets", "B_mc", "B_boot", "seed", "plan_sha256"]
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n"); w.writeheader()
        for r in rows:
            w.writerow(dict(r, value=round(r["value"], 6), mcse="" if r["mcse"] is None else round(r["mcse"], 6),
                            met="" if r["met"] is None else r["met"], B_mc=P["B_mc"], B_boot=P["B_boot"], seed=P["seed"], plan_sha256=sha))
    for r in rows: print(f"({r['scorer']}) {r['check']}: {r['value']:.4f}" + (f" +/- {r['mcse']:.4f}" if r["mcse"] else "")
                         + f"  [{r['criterion']}]" + ("" if r["met"] is None else ("  met" if r["met"] else "  NOT MET")))
    print("wrote", p)
    return 0 if all(r["met"] is not False for r in rows) else 1

if __name__ == "__main__":
    sys.exit(main())
