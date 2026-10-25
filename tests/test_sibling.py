"""Tests for the within-sibling evaluation of the Coding QC assist (eval/sibling_*.py; SYNTHETIC data only).

Run with a Python that has the app deps installed (requirements.txt):
    python tests/test_sibling.py
Exit code 0 = all checks pass. CI runs this beside tests/qc_test.py (.github/workflows/qc.yml).

What is checked (S-checks):
  S1   the sibling sets: 44 complete lab triplets, 51 body sites (28 of 4, 23 of 6), no set under 2 members,
       every eligible test gold term inside a set, and eval/data/sibling_sets.csv current with its generator
  S2   the exact tail of F (convolution) equals brute-force enumeration, for 1 to 8 clusters
  S3   one item per cluster under N1: the tail equals the Poisson-binomial tail with p_c = 1/K_c (by DFT)
  S4   the plan guard: an edited plan is refused (function and both scripts, exit 2, nothing written); the
       committed plan passes; an input file whose hash differs is refused (function and both scripts, exit 3,
       nothing written); the scorer fingerprint matches the registration, ignores a comment edit and catches a
       code edit
  S5   the statistics: Clopper-Pearson attainability 0.05^(1/m), Gate A with every item correct, BH/BY on a
       hand-checked case, KS on uniform draws, the keyword rule's matching; and, added after review so that a
       broken gate cannot pass (none of these is in the registered plan): the Clopper-Pearson bound against its
       binomial tail, the intraclass correlation on a hand-worked unbalanced example, Gate A's design effect,
       Gate B against hand-checked bootstrap quantiles and at the boundary where the tool and the rule are
       equally accurate (pass rate about 0.05), and the accuracy and margin tails inside analyze() against
       enumeration
  S6   the known-answer demo (a) to (e) at reduced replicates (60 datasets, 300 for coverage, B = 999), with
       the reduced tolerances below; and (added after review) that (e) depends on the design effect: leaving
       it out lowers the coverage, and the mean estimated intraclass correlation is near the true 0.2
  S7   eval/make_data.py still writes byte-identical coding_eval.csv and dictionary.csv
  S8   the real-path scoring wiring, with stand-in runtimes: the cosine is used when the re-ranker's contract
       has ret_rank (and why is recorded), the re-ranker score when its contract fits any candidate
  S9   the committed results: produced under the committed plan and inputs; the lab family routes to human
       coding (the registered known answer); every known-answer criterion met; a rerun of
       eval/sibling_eval.py into a temp folder reproduces the committed decisions and statistics; and no p- or
       q-value is written as 0 (lab's N1 accuracy tail on all items is (1/3)^22, about 3.2e-11)
"""
import csv, io, itertools, json, math, os, shutil, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EVAL = os.path.join(ROOT, "eval")
sys.path.insert(0, EVAL)
import sibling_eval as S, sibling_knownanswer as KA, sibling_sets as SS

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)[:300]) if detail and not cond else ""))
def block(name, fn):
    try: fn()
    except Exception as e: check(name + " block raised", False, repr(e))

TMP = tempfile.mkdtemp(prefix="sibling_test_")
P, PLAN_SHA = S.check_plan()

# ---------------------------------------------------------------- S1 sibling sets
def s1():
    sets = SS.load()
    lab, site = sets["lab"], sets["site"]
    check("S1a 44 complete lab triplets (increased, decreased, abnormal)",
          len(lab) == 44 and all([r for r, _, _ in m] == list(SS.LAB_ROLES) for m in lab.values()), len(lab))
    sizes = sorted(len(m) for m in site.values())
    check("S1b 51 body-site sets: 28 with 4 members and 23 with 6", len(site) == 51 and sizes.count(4) == 28 and sizes.count(6) == 23,
          dict(n=len(site), sizes={k: sizes.count(k) for k in set(sizes)}))
    check("S1c no set has fewer than 2 members", all(len(m) >= 2 for f in sets.values() for m in f.values()))
    codes = {c for f in sets.values() for m in f.values() for _, c, _ in m}
    check("S1d no PT sits in two sets", sum(len(m) for f in sets.values() for m in f.values()) == len(codes))
    items, _ = S.load_items(P)
    rows = list(csv.DictReader(open(os.path.join(EVAL, "data", "coding_eval.csv"), encoding="utf-8")))
    import re
    fam_rx = re.compile(r"(.+ (increased|decreased|abnormal))|((Pain in|Swelling of|Numbness of|Tenderness of|Weakness of|Cramp in) .+)")
    eligible = {r["pt_code"] for r in rows if r["split"] == "test" and r["negated"] == "N" and fam_rx.fullmatch(r["pt_name"])}
    check("S1e every eligible test gold term sits in a set (70 PTs: 22 lab, 48 site)",
          eligible <= codes and len(eligible) == 70 and {it["gold_code"] for it in items} == eligible, len(eligible))
    check("S1f eligible items: lab 66 in 22 clusters, site 144 in 48 clusters, 3 per cluster, no negated verbatim",
          sum(it["family"] == "lab" for it in items) == 66 and sum(it["family"] == "site" for it in items) == 144
          and all(it["variant"] in ("exact", "colloquial", "misspelled") for it in items))
    r = subprocess.run([sys.executable, os.path.join(EVAL, "sibling_sets.py"), "--check"], capture_output=True, text=True, timeout=120)
    check("S1g eval/data/sibling_sets.csv is current with eval/sibling_sets.py", r.returncode == 0, (r.stdout + r.stderr)[-200:])
block("S1", s1)

# ---------------------------------------------------------------- S2 / S3 exact tail
def s2():
    rng = np.random.default_rng(7); worst = 0.0; n = 0
    for m in range(1, 9):
        for _ in range(6):
            K = [int(rng.integers(2, 5)) for _ in range(m)]; nc = [int(rng.integers(1, 4)) for _ in range(m)]
            if np.prod(K) > 70000: continue
            picks = [rng.integers(0, K[c], nc[c]) for c in range(m)]
            pis = [rng.dirichlet(np.ones(K[c])) for c in range(m)]
            pmfs = [S.cluster_pmf(np.bincount(picks[c], minlength=K[c]), pis[c]) for c in range(m)]
            for obs in range(sum(nc) + 2):
                bf = 0.0
                for combo in itertools.product(*[range(k) for k in K]):
                    if sum(int((picks[c] == combo[c]).sum()) for c in range(m)) >= obs:
                        bf += float(np.prod([pis[c][combo[c]] for c in range(m)]))
                worst = max(worst, abs(bf - S.exact_tail(pmfs, obs))); n += 1
    check("S2 convolution tail equals brute-force enumeration for 1 to 8 clusters (|diff| < 1e-12)", worst < 1e-12, dict(worst=worst, cases=n))
block("S2", s2)

def s3():
    rng = np.random.default_rng(11); worst = 0.0
    for _ in range(25):
        m = int(rng.integers(5, 60)); K = rng.choice([3, 4, 6], m); picks = [int(rng.integers(0, k)) for k in K]
        pmfs = [S.cluster_pmf(np.bincount([picks[c]], minlength=int(K[c])), np.full(int(K[c]), 1.0 / K[c])) for c in range(m)]
        p = 1.0 / K; N = m + 1; w = np.exp(2j * np.pi * np.arange(N) / N)
        cf = np.prod(1 - p[None, :] + p[None, :] * w[:, None], axis=1)            # characteristic function on the DFT grid
        pb = np.real(np.fft.fft(cf)) / N                                          # Poisson-binomial pmf
        for obs in range(m + 1): worst = max(worst, abs(S.exact_tail(pmfs, obs) - float(pb[obs:].sum())))
    check("S3 one item per cluster under N1: tail equals the Poisson-binomial tail with p_c = 1/K_c (|diff| < 1e-10)", worst < 1e-10, worst)
block("S3", s3)

# ---------------------------------------------------------------- S4 plan guard
def s4():
    plan = open(S.PLAN, encoding="utf-8").read()
    copy = os.path.join(TMP, "plan_copy.md"); open(copy, "w", encoding="utf-8").write(plan)
    edited = os.path.join(TMP, "plan_edited.md"); open(edited, "w", encoding="utf-8").write(plan.replace('"a_min": 0.90', '"a_min": 0.85'))
    ok_copy = S.check_plan(copy, S.PLAN_HASH)[1] == PLAN_SHA
    try: S.check_plan(edited, S.PLAN_HASH); refused = False
    except S.Refusal as e: refused = e.code == 2
    check("S4a the committed plan (and an unedited copy) passes the guard; its hash equals eval/sibling_plan.sha256",
          ok_copy and PLAN_SHA == open(S.PLAN_HASH).read().split()[0], PLAN_SHA)
    check("S4b an edited plan (a_min 0.90 -> 0.85) is refused by check_plan (Refusal, code 2)", refused)
    for script in ("sibling_eval.py", "sibling_knownanswer.py"):
        out = os.path.join(TMP, "refused_" + script); os.makedirs(out)
        r = subprocess.run([sys.executable, os.path.join(EVAL, script), "--plan", edited, "--out", out], capture_output=True, text=True, timeout=300)
        check(f"S4c {script} refuses an edited plan: exit 2, says why, writes nothing",
              r.returncode == 2 and "REFUSED" in r.stderr and "sibling_plan.sha256" in r.stderr and not os.listdir(out),
              dict(rc=r.returncode, err=r.stderr[-200:], files=os.listdir(out)))
    bad = dict(P, inputs_sha256=dict(P["inputs_sha256"], **{"eval/data/coding_eval.csv": "0" * 64}))
    try: S.check_inputs(bad); refused = False
    except S.Refusal as e: refused = e.code == 3
    check("S4d an input file whose SHA-256 differs from the plan is refused (code 3); the committed inputs pass",
          refused and S.check_inputs(P) == P["inputs_sha256"])
    app = open(os.path.join(ROOT, "meddra_app.py"), encoding="utf-8").read()
    fp0 = S.scorer_fingerprint()
    c1 = os.path.join(TMP, "app_comment.py"); open(c1, "w", encoding="utf-8").write(app.replace("SI_W=[0.40,0.25,0.20,0.15]", "SI_W=[0.40,0.25,0.20,0.15]  # a comment", 1))
    c2 = os.path.join(TMP, "app_code.py"); open(c2, "w", encoding="utf-8").write(app.replace("SI_W=[0.40,0.25,0.20,0.15]", "SI_W=[0.45,0.20,0.20,0.15]", 1))
    check("S4e the scorer fingerprint matches the registration, ignores a comment edit and catches a code edit",
          fp0 == P["scorer_fingerprint"] and S.scorer_fingerprint(c1) == fp0 and S.scorer_fingerprint(c2) != fp0, fp0)
    # S4f: each script's main() refuses a changed input file before it computes anything. The inputs are copied to
    # a scratch root with sibling_sets.csv edited, and sibling_eval's ROOT points there; the run functions are
    # replaced by ones that raise, so a script that got past its guard fails this check instead of running.
    fake = os.path.join(TMP, "fake_root"); os.makedirs(os.path.join(fake, "eval", "data"))
    for rel in P["inputs_sha256"]: shutil.copy(os.path.join(ROOT, rel), os.path.join(fake, rel))
    with open(os.path.join(fake, "eval", "data", "sibling_sets.csv"), "a", encoding="utf-8") as f: f.write("lab,X,increased,0,x\n")
    def ran(*a, **k): raise AssertionError("ran past the input guard")
    for name, mod, fn in (("sibling_eval.py", S, "run"), ("sibling_knownanswer.py", KA, "run_knownanswer")):
        out = os.path.join(TMP, "refused_input_" + name); os.makedirs(out)
        saved_root, saved_fn, err, se = S.ROOT, getattr(mod, fn), io.StringIO(), sys.stderr
        S.ROOT = fake; setattr(mod, fn, ran); sys.stderr = err
        try: rc = mod.main(["--out", out])
        except AssertionError as e: rc = repr(e)
        finally: S.ROOT = saved_root; setattr(mod, fn, saved_fn); sys.stderr = se
        check(f"S4f {name} refuses an input file whose SHA-256 differs from the plan: exit 3, names the file, writes nothing",
              rc == 3 and "sibling_sets.csv" in err.getvalue() and not os.listdir(out), dict(rc=rc, err=err.getvalue()[-200:]))
block("S4", s4)

# ---------------------------------------------------------------- S5 statistics
def s5():
    att = all(abs(S.cp_lower(m, m) - 0.05 ** (1 / m)) < 1e-9 for m in (5, 22, 29, 48, 59, 120))
    check("S5a Clopper-Pearson with every item correct at n_eff = m gives 0.05^(1/m); a_min 0.90 needs m >= 29, 0.95 needs 59",
          att and S.cp_lower(28, 28) < 0.90 <= S.cp_lower(29, 29) and S.cp_lower(58, 58) < 0.95 <= S.cp_lower(59, 59))
    A = S.gate_a(np.ones(66), np.repeat(np.arange(22), 3), 0.05, 0.90)
    check("S5b Gate A with every item correct: rho = 1, n_eff = m, bound = attainable bound (lab: 0.873, not assessable)",
          A["rho_hat"] == 1.0 and abs(A["n_eff"] - 22) < 1e-12 and abs(A["bound"] - A["attainable_bound"]) < 1e-9
          and abs(A["bound"] - 0.8727) < 1e-4 and not A["assessable"] and not A["passed"], A)
    q = S.bh([0.01, 0.04, 0.03, 0.20]); qy = S.by([0.01, 0.04, 0.03, 0.20])
    check("S5c BH and BY q-values on a hand-checked case", np.allclose(q, [0.04, 0.0533333, 0.0533333, 0.20])
          and np.allclose(qy, np.minimum(1, np.array([0.04, 0.0533333, 0.0533333, 0.20]) * (1 + 1/2 + 1/3 + 1/4))), (q, qy))
    D, p = S.ks_uniform(np.random.default_rng(3).random(500)); D2, p2 = S.ks_uniform(np.random.default_rng(3).random(500) ** 2)
    check("S5d KS: uniform draws are not rejected, squared uniforms are", p > 0.01 and p2 < 1e-6, (p, p2))
    lexi = P["keyword_lexicon"]
    kh = (S.keyword_hits("knee tenderness", "tenderness", lexi), S.keyword_hits("ALT out of range on bloods", "abnormal", lexi),
          S.keyword_hits("range out of bloods", "abnormal", lexi), S.keyword_hits("ALT above upper limit", "increased", lexi),
          S.keyword_hits("puffiness of knee", "swelling", lexi))
    check("S5e keyword rule: prefix hits ('tender' in 'tenderness'), a phrase hits only in order, counts per entry", kh == (1, 1, 0, 2, 0), kh)
    pk = [S.pick_with_ties([0.5, 0.5, 0.1], u)[0] for u in (0.0, 0.49, 0.51, 0.99)]
    check("S5f a tie at the maximum is broken by the draw, among the tied members only", pk == [0, 0, 1, 1], pk)
block("S5", s5)

def s5_gates():
    # S5g Clopper-Pearson: at the bound, the binomial tail P(X >= x | n, p = bound) is exactly alpha
    worst = max(abs(sum(math.comb(n, k) * b ** k * (1 - b) ** (n - k) for k in range(x, n + 1)) - 0.05)
                for x, n in ((60, 66), (124, 144), (5, 10), (1, 3), (29, 29), (118, 120)) for b in [S.cp_lower(x, n)])
    check("S5g Clopper-Pearson lower bound: P(X >= x) at the bound equals 0.05 for six (x, n), including lab's 60 of 66 and site's 124 of 144",
          worst < 1e-9 and abs(S.cp_lower(60, 66) - 0.828441) < 1e-6, worst)
    # S5h one-way ANOVA ICC, hand-worked on an unbalanced example (clusters of 3, 3, 2 and 4 items):
    # grand mean 1/2; SSB = 19/12 on 3 df, so MSB = 19/36; SSW = 17/12 on 8 df, so MSW = 17/96;
    # n0 = (12 - 38/12)/3 = 53/18; ICC = (MSB - MSW)/(MSB + (n0 - 1) MSW) = 606/1507 = 0.402123
    y = [1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0]; cl = [0, 0, 0, 1, 1, 1, 2, 2, 3, 3, 3, 3]
    r = S.anova_icc(y, cl); r_neg = S.anova_icc([1, 0, 1, 0, 1, 0], [0, 0, 1, 1, 2, 2])
    check("S5h intraclass correlation on a hand-worked unbalanced example equals 606/1507 = 0.402123; a negative estimate is truncated to 0",
          abs(r - 606 / 1507) < 1e-12 and r_neg == 0.0, (r, r_neg))
    # S5i Gate A applies the Kish design effect with m-bar = n/m
    A = S.gate_a(y, cl, 0.05, 0.90); deff = 1 + (12 / 4 - 1) * 606 / 1507
    check("S5i Gate A uses the design effect: deff = 1 + (n/m - 1) rho, n_eff = n/deff, x_eff = floor(F n_eff), and the bound is below the one that ignores clustering",
          abs(A["deff"] - deff) < 1e-12 and abs(A["n_eff"] - 12 / deff) < 1e-12 and A["x_eff"] == math.floor(0.5 * 12 / deff)
          and abs(A["bound"] - S.cp_lower(A["x_eff"], 12 / deff)) < 1e-12 and A["bound"] < S.cp_lower(6, 12), A)
    # S5j Gate B's bound is the LOWER 5% bootstrap quantile. Two clusters with means +1 and -1: the resampled mean is
    # -1, 0 or +1 with probabilities 1/4, 1/2, 1/4, so the 5% quantile is -1 (the 95% quantile is +1). Three
    # one-item clusters -1, 0, +1: the resampled mean is at most -2/3 with probability 4/27 = 0.148 and at most -1
    # with 1/27 = 0.037, so the 5% quantile is -2/3 (the 95% quantile is +2/3).
    g1 = S.gate_b([1, 1, -1, -1], [0, 0, 1, 1], 9999, np.random.default_rng(1))
    g2 = S.gate_b([-1, 0, 1], [0, 1, 2], 9999, np.random.default_rng(2))
    g3 = S.gate_b([1, 1, 1, 1], [0, 0, 1, 1], 999, np.random.default_rng(3))
    check("S5j Gate B lower bound equals the hand-checked 5% bootstrap quantile (-1 and -2/3; the upper quantile would give +1 and +2/3); all +1 passes",
          g1["lower_bound"] == -1.0 and not g1["passed"] and abs(g2["lower_bound"] + 2 / 3) < 1e-12 and not g2["passed"]
          and g3["lower_bound"] == 1.0 and g3["passed"], (g1, g2, g3))
    # S5k Gate B at the boundary: tool and rule equally accurate (both correct with probability q_c ~ Beta(8, 2)),
    # 48 clusters of 3 items, 1,000 families, B = 999. A one-sided 5% bound should pass about 5% of the time.
    rng = np.random.default_rng(20261026); R5 = 1000; passes = 0
    for _ in range(R5):
        q = rng.beta(8, 2, 48); tool = rng.random((48, 3)) < q[:, None]; rule = rng.random((48, 3)) < q[:, None]
        passes += S.gate_b((tool.astype(float) - rule).reshape(-1), np.repeat(np.arange(48), 3), 999, rng)["passed"]
    sd = math.sqrt(0.05 * 0.95 / R5); rate = passes / R5
    check(f"S5k Gate B passes in 0.05 +/- 3 SD ({0.05 - 3 * sd:.3f} to {0.05 + 3 * sd:.3f}) of 1,000 families where the tool and the rule are equally accurate",
          abs(rate - 0.05) <= 3 * sd, rate)
    # S5l the tails inside analyze(): 5 clusters of 3 members with 2 items each, random scores; under N1 every one of
    # the 3^5 pseudo-gold assignments has probability 1/243. The F tail must be P(sum >= observed) exactly, and the
    # Monte Carlo M tail must agree with the enumerated P(M* >= M) within 4 MCSE plus the (b + 1)/(B + 1) offset.
    rng = np.random.default_rng(5); roles = ("increased", "decreased", "abnormal"); items, T = [], []
    for c in range(5):
        mem = [(ro, f"W{c}:{ro}", f"stem{c} {ro}") for ro in roles]; g = int(rng.integers(0, 3))
        for j in range(2):
            items.append(dict(id=f"W{c}{j}", variant=("exact", "misspelled")[j], family="lab", gold_code=mem[g][1], gold_role=roles[g],
                              members=mem, w=dict(zip(roles, (1, 1, 1))), lex_set=set()))
            T.append(list(rng.random(3)))
    picks = [S.pick_with_ties(t, 0.5) for t in T]
    a = S.analyze(items, T, P, 0, 0, picks, B_mc=9999, rng_tag=("knownanswer", 99, 0), only={"N1": ["all"]})
    rF = next(x for x in a["null_tests"]["N1"] if x["stat"] == "F"); rM = next(x for x in a["null_tests"]["N1"] if x["stat"] == "M")
    gold = [[cd for _, cd, _ in it["members"]].index(it["gold_code"]) for it in items]
    mif = lambda i, k: T[i][k] - max(T[i][j] for j in range(3) if j != k)
    obs = sum(picks[i][0] == gold[i] for i in range(10)); Mobs = sum(mif(i, gold[i]) for i in range(10)) / 10
    tF = tM = 0.0
    for combo in itertools.product(range(3), repeat=5):
        tF += (sum(picks[i][0] == combo[i // 2] for i in range(10)) >= obs) / 243
        tM += (sum(mif(i, combo[i // 2]) for i in range(10)) / 10 >= Mobs - 1e-12) / 243
    check("S5l analyze(): the N1 accuracy p is P(sum >= observed) by enumeration of all 243 pseudo-gold draws, and the margin p agrees with enumeration",
          abs(rF["p"] - tF) < 1e-12 and abs(rM["p"] - tM) <= 4 * rM["mcse"] + 1 / 10000, dict(pF=rF["p"], enumF=tF, pM=rM["p"], enumM=tM, obs=obs))
block("S5 gates", s5_gates)

# ---------------------------------------------------------------- S6 known-answer demo, reduced
R, RCOV, BR = 60, 300, 999
SD = 3 * math.sqrt(0.05 * 0.95 / R)                     # 3 binomial SDs at 0.05 with R datasets
REDUCED = dict(a_joint_q_rate_min=0.90, a_gate_a_fail_min=0.90, b_mean_f=[0.57, 0.63], b_n1_reject_min=0.95,
               b_n2_reject=[0.0, round(0.05 + SD, 4)], b_gate_a_fail_min=0.90, b_gate_b_fail_min=0.90,
               c_reject_max=round(0.05 + SD, 4), c_ks_p_min=0.001, d_gate_a_pass_min=0.50, d_gate_b_pass_min=0.90,
               e_coverage_min=0.90)
def s6():
    rows, res = KA.run_knownanswer(P, datasets=R, coverage_datasets=RCOV, B_mc=BR, B_boot=BR, crit=REDUCED)
    for s in "abcde":
        got = [r for r in rows if r["scorer"] == s and r["met"] is not None]
        bad = [(r["check"], round(r["value"], 4), r["criterion"]) for r in got if not r["met"]]
        check(f"S6{s} known-answer scorer ({s}) recovered at {RCOV if s == 'e' else R} datasets, B = {BR}: "
              + "; ".join(f"{r['check']} {r['criterion']}" for r in got), got and not bad, bad)
    # (e) alone cannot tell whether the design effect is applied (its 0.93 floor still holds without it), so check
    # that leaving it out lowers the coverage and that the intraclass correlation is estimated near its true 0.2.
    e = res["e"]; cov = float(np.mean([x["bound"] < 0.85 for x in e])); cov0 = float(np.mean([x["bound_no_deff"] < 0.85 for x in e]))
    rho = float(np.mean([x["rho"] for x in e]))
    check(f"S6f (e) depends on the design effect: coverage drops when it is left out, and the mean estimated intraclass correlation is within 0.05 of 0.2",
          cov0 < cov and abs(rho - 0.2) < 0.05, dict(coverage=cov, coverage_no_deff=cov0, mean_rho=rho))
block("S6", s6)

# ---------------------------------------------------------------- S7 make_data byte-identical
def s7():
    import make_data
    out = os.path.join(TMP, "make_data_out"); os.makedirs(out)
    saved = make_data.OUT; make_data.OUT = out
    try:
        buf = io.StringIO(); so = sys.stdout; sys.stdout = buf
        try: make_data.main()
        finally: sys.stdout = so
    finally: make_data.OUT = saved
    same = {f: S.sha256_file(os.path.join(out, f)) == S.sha256_file(os.path.join(EVAL, "data", f))
            for f in ("coding_eval.csv", "dictionary.csv", "phi_fields.csv", "phi_spans.csv")}
    check("S7 eval/make_data.py writes byte-identical coding_eval.csv and dictionary.csv (and the PHI files)", all(same.values()), same)
block("S7", s7)

# ---------------------------------------------------------------- S8 real-path wiring (stand-in runtimes)
def s8():
    import warnings, zlib
    from _app import load_app
    with warnings.catch_warnings():
        warnings.simplefilter("ignore"); ns = load_app("meddra")
    d = S.dictionary_rows()
    def emb(t):
        v = np.zeros(64); t = str(t)
        for i in range(len(t) - 2): v[zlib.crc32(t[i:i + 3].encode()) % 64] += 1.0
        return list(v)
    class Agent:
        def embed(self, t): return emb(t)
    V = np.array([emb(ns["_t2_text"](x)) for x in d["llt_name"]], np.float32); V /= np.linalg.norm(V, axis=1, keepdims=True)
    items = [it for it in S.load_items(P)[0] if it["variant"] == "colloquial"][:6]
    ns.update(REAL_T2=True, _agent=Agent(), t2_index=lambda df: (V, None))
    ns["_coder"] = (None, {"features": ["cosine", "lev", "jaro", "soc_match", "p_unambiguous", "ret_rank"]}); ns["REAL_T4"] = True
    T, src = S.score_real(ns, items, d, P)
    rows = S._member_rows(d)
    def cos_max(it, code):
        q = np.asarray(emb(ns["_t2_text"](it["verbatim"])), np.float32); q /= np.linalg.norm(q)
        return max(round(float(c), 4) for c in V[rows[code]] @ q)
    want = [[cos_max(it, c) for _, c, _ in it["members"]] for it in items]
    check("S8a real path, contract with ret_rank: T is the Needle3 cosine (max over LLTs) and the reason names ret_rank",
          T == want and "Needle3 cosine" in src and "ret_rank" in src, src)
    class DM:
        def __init__(self, X, feature_names=None): self.X = np.asarray(X, float); self.names = feature_names
    class Booster:
        def predict(self, dm): return [1 / (1 + math.exp(-(4 * r[0] + 2 * r[4] - 3))) for r in dm.X]
    feats = ["cosine", "lev", "jaro", "soc_match", "p_unambiguous"]
    ns.update(_coder=(Booster(), {"features": feats}), xgboost=type("X", (), {"DMatrix": DM}),
              t3_coding_batch=lambda texts: [dict(P_UNAMBIGUOUS=0.8) for _ in texts])
    T2, src2 = S.score_real(ns, items, d, P)
    want2 = [[max(round(1 / (1 + math.exp(-(4 * round(float(c), 4) + 2 * 0.8 - 3))), 4)
                  for c in V[rows[code]] @ (lambda q: q / np.linalg.norm(q))(np.asarray(emb(ns["_t2_text"](it["verbatim"])), np.float32)))
              for _, code, _ in it["members"]] for it in items]
    check("S8b real path, contract that fits any candidate: T is the re-ranker's score through t4_coding", T2 == want2 and "trained re-ranker" in src2,
          dict(src=src2, got=T2[:1], want=want2[:1]))
    ns.update(REAL_T2=False)
    check("S8c real path without a loadable Needle3: not run, and the summary says why", S.score_real(ns, items, d, P)[0] is None)
block("S8", s8)

# ---------------------------------------------------------------- S9 committed results
def s9():
    res = os.path.join(EVAL, "results")
    s = json.load(open(os.path.join(res, "sibling_summary.json"), encoding="utf-8"))
    check("S9a committed summary was produced under the committed plan, inputs and scorer, with no deviation",
          s["plan"]["sha256"] == PLAN_SHA and s["inputs_sha256"] == P["inputs_sha256"] and s["scorer_fingerprint"] == P["scorer_fingerprint"]
          and s["deviations"] == [], s["plan"])
    lab = [v for v in s["results"]["lab"].values() if "decision" in v]
    check("S9b registered known answer: the lab family routes to human coding on every path that ran (not assessable at m = 22)",
          lab and all(v["decision"] != "auto-coding allowed" and not v["gate_a"]["assessable"] for v in lab) and s["known_answer"]["met"])
    kr = list(csv.DictReader(open(os.path.join(res, "sibling_knownanswer.csv"), encoding="utf-8")))
    check("S9c committed known-answer run: every registered criterion met, under the committed plan, 400 datasets (2,000 for coverage)",
          kr and all(r["met"] in ("True", "") for r in kr) and all(r["plan_sha256"] == PLAN_SHA for r in kr)
          and {r["datasets"] for r in kr if r["scorer"] != "e"} == {"400"} and {r["datasets"] for r in kr if r["scorer"] == "e"} == {"2000"},
          [r["check"] for r in kr if r["met"] == "False"])
    nc = all(s["results"][f]["standin"]["negative_control"]["met"] for f in ("lab", "site"))
    check("S9d committed negative control: the N1 F test rejects at most 0.072 of 400 within-cluster permutations, per family", nc)
    out = os.path.join(TMP, "rerun")
    r = subprocess.run([sys.executable, os.path.join(EVAL, "sibling_eval.py"), "--out", out], capture_output=True, text=True, timeout=900)
    ok = r.returncode == 0 and os.path.exists(os.path.join(out, "sibling_summary.json"))
    diffs = []
    if ok:
        n = json.load(open(os.path.join(out, "sibling_summary.json"), encoding="utf-8"))
        for fam in ("lab", "site"):
            a, b = s["results"][fam]["standin"], n["results"][fam]["standin"]
            for k in ("n", "m", "F", "keyword_F", "tie_rate", "decision"):
                if a[k] != b[k]: diffs.append((fam, k, a[k], b[k]))
            for k in ("bound", "deff", "assessable", "passed"):
                if a["gate_a"][k] != b["gate_a"][k]: diffs.append((fam, "gate_a." + k, a["gate_a"][k], b["gate_a"][k]))
            for k in ("lower_bound", "passed"):
                if a["gate_b"][k] != b["gate_b"][k]: diffs.append((fam, "gate_b." + k, a["gate_b"][k], b["gate_b"][k]))
            for null in a["null_tests"]:
                for ra, rb in zip(a["null_tests"][null], b["null_tests"][null]):
                    tol = 1e-9 if ra["stat"] == "F" else 3 * max(ra.get("mcse") or 0, 1e-4)
                    if abs(ra["p"] - rb["p"]) > tol: diffs.append((fam, null, ra["stat"], ra["subset"], ra["p"], rb["p"]))
        same_items = open(os.path.join(out, "sibling_items.csv"), encoding="utf-8").read() == open(os.path.join(res, "sibling_items.csv"), encoding="utf-8").read()
        if not same_items: diffs.append("sibling_items.csv differs")
    check("S9e a rerun of eval/sibling_eval.py reproduces the committed decisions, gates, p-values (M within 3 MCSE) and item rows",
          ok and not diffs, dict(rc=r.returncode, err=r.stderr[-300:], diffs=diffs[:5]))
    # Every lab term has at least 2 of its 3 variants picked right, so the observed 60 of 66 is the most any null
    # draw can reach, and only when all 22 pseudo-golds are the gold: the exact N1 tail is (1/3)^22.
    tests = [r for f in ("lab", "site") for rows in s["results"][f]["standin"]["null_tests"].values() for r in rows if r.get("p") is not None]
    zero = [(r["stat"], r["subset"], k, r[k]) for r in tests for k in ("p", "q_bh", "q_by") if k in r and not r[k] > 0]
    lab_all = s["results"]["lab"]["standin"]["null_tests"]["N1"][0]
    check("S9f no p- or q-value in the committed summary is written as 0, and lab's N1 accuracy tail on all items is (1/3)^22 to 6 significant figures",
          tests and not zero and (lab_all["stat"], lab_all["subset"]) == ("F", "all") and abs(lab_all["p"] / (1 / 3) ** 22 - 1) < 1e-5,
          dict(zero=zero[:4], lab_all=lab_all))
block("S9", s9)

shutil.rmtree(TMP, ignore_errors=True)
print("\n==== SUMMARY:", len(PASS), "passed,", len(FAIL), "failed ====")
for n, d in FAIL: print("  FAILED:", n, "|", str(d)[:200])
sys.exit(1 if FAIL else 0)
