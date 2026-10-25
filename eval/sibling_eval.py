#!/usr/bin/env python3
"""Within-sibling evaluation of the Coding QC assist, run to the registered plan (SYNTHETIC data, not MedDRA).

Run from anywhere:
    python eval/sibling_eval.py                         # stand-in path  -> eval/results/sibling_summary.json, sibling_items.csv
    python eval/sibling_eval.py --models <models_dir>   # adds the real path (needs the real runtimes, eval/README.md)

The plan is eval/sibling_plan.md. This script refuses to run unless the SHA-256 of that file equals the value
committed in eval/sibling_plan.sha256 (the fetch-guard pattern of the AlphaGenome audit), and it then reads every
parameter (seeds, B, a_min, the keyword lexicon, the input hashes) from the plan's JSON block, so the code cannot
drift from what was registered. It also refuses when an input file's SHA-256 differs from the plan, or when the
scoring code in meddra_app.py differs from the registered fingerprint (unless --allow-scorer-change, which is then
recorded as a deviation).

What is measured, in one line: for every eligible test verbatim, the tool's own score for EACH member of its sibling
set (lab direction, or the finding at one body site), the member it picks, how that compares with chance (three
nulls), with a keyword rule, and with a pre-set accuracy floor that decides whether the family may auto-code.
The statistics below are plain numpy, shared with eval/sibling_knownanswer.py and tests/test_sibling.py.

Exit codes: 0 done; 2 plan hash mismatch; 3 input hash mismatch; 4 scorer changed; 5 ran, but the registered
expected answer (the lab family routes to human coding) was not met, which is a bug to find before publishing.
"""
import argparse, csv, hashlib, io, json, math, os, platform, re, sys, tokenize
from fractions import Fraction
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLAN = os.path.join(HERE, "sibling_plan.md")
PLAN_HASH = os.path.join(HERE, "sibling_plan.sha256")
DATA = os.path.join(HERE, "data")
RESULTS = os.path.join(HERE, "results")
UI_MARKER = "# ============================ UI ============================"
FAMILIES = ("lab", "site")
PATHS = ("standin", "real")
NULLS = ("N1", "N2", "N3", "N2_lambda_0.5")
SUBSETS = ("all", "exact", "colloquial", "misspelled")

# ============================================================ plan guard
class Refusal(Exception):
    """Raised before anything is loaded or written; .code is the exit status."""
    def __init__(self, msg, code): super().__init__(msg); self.code = code

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def check_plan(plan_path=PLAN, hash_path=PLAN_HASH):
    """Return (params, sha) when the plan's SHA-256 equals the committed hash; raise Refusal otherwise.
    The committed hash file is always eval/sibling_plan.sha256 unless a caller passes another one."""
    if not os.path.isfile(hash_path): raise Refusal(f"{os.path.relpath(hash_path, ROOT)} is missing: refusing to run.", 2)
    if not os.path.isfile(plan_path): raise Refusal(f"plan {plan_path} is missing: refusing to run.", 2)
    want = (open(hash_path, encoding="utf-8").read().split() or [""])[0].strip().lower()
    got = sha256_file(plan_path)
    if got != want:
        raise Refusal(f"the SHA-256 of {os.path.relpath(plan_path, ROOT) if plan_path.startswith(ROOT) else plan_path} is {got}, "
                      f"but eval/sibling_plan.sha256 registers {want}. The plan changed after it was locked: refusing to run. "
                      f"A change to the plan needs a new registration before any scoring.", 2)
    text = open(plan_path, encoding="utf-8").read()
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
    if len(blocks) != 1: raise Refusal("the plan must hold exactly one ```json parameter block.", 2)
    return json.loads(blocks[0]), got

def check_inputs(P):
    out = {}
    for rel, want in P["inputs_sha256"].items():
        got = sha256_file(os.path.join(ROOT, rel))
        if got != want: raise Refusal(f"{rel} has SHA-256 {got}, the plan registers {want}: refusing to run.", 3)
        out[rel] = got
    return out

def scorer_fingerprint(path=os.path.join(ROOT, "meddra_app.py")):
    """SHA-256 of the token stream of the app's code above its UI marker, comments and blank lines left out:
    an edit to the scoring code changes it, an edit to a comment does not."""
    src = open(path, encoding="utf-8").read(); code = src[:src.index(UI_MARKER)]
    keep = [f"{tokenize.tok_name[t.type]}:{t.string}" for t in tokenize.generate_tokens(io.StringIO(code).readline)
            if t.type not in (tokenize.COMMENT, tokenize.NL)]
    return hashlib.sha256("\n".join(keep).encode()).hexdigest()

# ============================================================ statistics (numpy only)
def rng_for(P, stream, *idx):
    """The plan's random streams: default_rng([seed, stream number, indexes...]); draws use random() only."""
    return np.random.default_rng([int(P["seed"]), int(P["streams"][stream]) if isinstance(stream, str) else int(stream), *map(int, idx)])

def pick_with_ties(T, u, tol=1e-12):
    """Index of the maximum of T; ties at the maximum broken by the uniform draw u. Returns (pick, n_tied)."""
    T = np.asarray(T, float); tied = np.flatnonzero(T >= T.max() - tol)
    return int(tied[min(int(u * len(tied)), len(tied) - 1)]), int(len(tied))

def cluster_pmf(counts, pi):
    """pmf of X_c = #items whose pick equals the pseudo-gold, when the pseudo-gold is k with probability pi[k]
    and counts[k] items picked k."""
    counts = np.asarray(counts, int); pmf = np.zeros(int(counts.sum()) + 1)
    for c, p in zip(counts, pi):
        if p > 0: pmf[c] += p
    return pmf

def exact_tail(pmfs, observed):
    """P(sum of independent integer variables >= observed), by convolving their pmfs."""
    tot = np.array([1.0])
    for p in pmfs: tot = np.convolve(tot, p)
    return float(min(1.0, max(0.0, tot[int(observed):].sum()))) if observed < len(tot) else 0.0

def mc_margin_p(margin, pi, n, observed, B, rng, tol=1e-12):
    """Monte Carlo p for M: margin[c, k] is the summed margin of cluster c's items if member k were gold (padded
    with zeros), pi[c, k] the null's draw probabilities (zeros on padding). One pseudo-gold per cluster per draw.
    Returns (p, mcse, b)."""
    margin = np.asarray(margin, float); pi = np.asarray(pi, float)
    cum = np.cumsum(pi, axis=1); cum = cum / cum[:, -1:]; cum[:, -1] = 1.0
    u = rng.random((B, margin.shape[0]))
    k = (u[:, :, None] >= cum[None, :, :]).sum(axis=2)
    k = np.minimum(k, margin.shape[1] - 1)
    Mstar = margin[np.arange(margin.shape[0])[None, :], k].sum(axis=1) / n
    b = int((Mstar >= observed - tol).sum()); p = (b + 1) / (B + 1)
    return p, math.sqrt(p * (1 - p) / B), b

def bh(p):
    """Benjamini-Hochberg q-values (step-up), in input order."""
    p = np.asarray(p, float); m = len(p)
    if not m: return []
    o = np.argsort(p); q = np.empty(m); run = 1.0
    for r in range(m - 1, -1, -1):
        run = min(run, p[o[r]] * m / (r + 1)); q[o[r]] = run
    return list(np.minimum(q, 1.0))

def by(p):
    """Benjamini-Yekutieli q-values: BH times sum_{i<=m} 1/i, capped at 1."""
    m = len(p); c = sum(1.0 / i for i in range(1, m + 1))
    return [min(1.0, q * c) for q in bh(p)]

def _betacf(a, b, x, iters=300, eps=3e-16):
    """Continued fraction for the incomplete beta (modified Lentz), vectorized over x."""
    x = np.asarray(x, float); tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = np.ones_like(x); d = 1.0 - qab * x / qap; d = np.where(np.abs(d) < tiny, tiny, d); d = 1.0 / d; h = d.copy()
    for m in range(1, iters + 1):
        m2 = 2 * m; aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d; d = np.where(np.abs(d) < tiny, tiny, d); c = 1.0 + aa / c; c = np.where(np.abs(c) < tiny, tiny, c)
        d = 1.0 / d; h = h * d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d; d = np.where(np.abs(d) < tiny, tiny, d); c = 1.0 + aa / c; c = np.where(np.abs(c) < tiny, tiny, c)
        d = 1.0 / d; delta = d * c; h = h * delta
        if np.all(np.abs(delta - 1.0) < eps): break
    return h

def betainc(a, b, x):
    """Regularized incomplete beta I_x(a, b), vectorized over x."""
    x = np.clip(np.asarray(x, float), 0.0, 1.0); out = np.zeros_like(x)
    inner = (x > 0) & (x < 1); out[x >= 1] = 1.0
    if inner.any():
        xi = x[inner]
        lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * np.log(xi) + b * np.log1p(-xi)
        bt = np.exp(lbt); direct = xi < (a + 1.0) / (a + b + 2.0)
        res = np.empty_like(xi)
        if direct.any(): res[direct] = bt[direct] * _betacf(a, b, xi[direct]) / a
        if (~direct).any(): res[~direct] = 1.0 - bt[~direct] * _betacf(b, a, 1.0 - xi[~direct]) / b
        out[inner] = res
    return out

def beta_ppf(q, a, b, iters=60):
    """Quantile of Beta(a, b) by bisection on betainc, vectorized over q."""
    q = np.asarray(q, float); lo = np.zeros_like(q); hi = np.ones_like(q)
    for _ in range(iters):
        mid = 0.5 * (lo + hi); below = betainc(a, b, mid) < q
        lo = np.where(below, mid, lo); hi = np.where(below, hi, mid)
    return 0.5 * (lo + hi)

def cp_lower(x, n, alpha=0.05):
    """One-sided (1 - alpha) Clopper-Pearson lower bound: the alpha quantile of Beta(x, n - x + 1); 0 when x = 0.
    n may be fractional (an effective size)."""
    if x <= 0: return 0.0
    return float(beta_ppf(np.array([alpha]), float(x), float(n - x + 1))[0])

def anova_icc(y, cluster):
    """One-way ANOVA intraclass correlation, (MSB - MSW)/(MSB + (n0 - 1) MSW), truncated to [0, 1].
    Returns 1 when every value is equal (all correct or none), as the plan sets it."""
    y = np.asarray(y, float); cl = np.asarray(cluster)
    keys, inv = np.unique(cl, return_inverse=True); m = len(keys); N = len(y)
    if m < 2 or np.all(y == y[0]): return 1.0
    nc = np.bincount(inv).astype(float); mc = np.bincount(inv, weights=y) / nc; g = y.mean()
    msb = float((nc * (mc - g) ** 2).sum() / (m - 1)); msw = float(((y - mc[inv]) ** 2).sum() / (N - m)) if N > m else 0.0
    n0 = (N - (nc ** 2).sum() / N) / (m - 1)
    den = msb + (n0 - 1) * msw
    if den <= 0: return 1.0
    return float(min(1.0, max(0.0, (msb - msw) / den)))

def gate_a(y, cluster, alpha, a_min):
    """Gate A: Clopper-Pearson lower bound on accuracy at the Kish effective size. y may be fractional (sensitivity)."""
    y = np.asarray(y, float); n = len(y); m = len(set(cluster)); F = float(y.mean())
    rho = anova_icc(y, cluster); deff = 1.0 + (n / m - 1.0) * rho; n_eff = n / deff
    x_eff = math.floor(F * n_eff + 1e-9); bound = cp_lower(x_eff, n_eff, alpha)
    attain = alpha ** (1.0 / m)
    return dict(n=n, m=m, F=F, rho_hat=rho, deff=deff, n_eff=n_eff, x_eff=x_eff, bound=bound, a_min=a_min,
                attainable_bound=attain, assessable=attain >= a_min, passed=bound >= a_min)

def gate_b(d, cluster, B, rng, alpha=0.05):
    """Gate B: one-sided (1 - alpha) cluster-bootstrap lower bound of the mean paired difference d (tool minus
    rule), resampling clusters with replacement; the bound is the ceil(alpha (B + 1))-th smallest value."""
    d = np.asarray(d, float); keys, inv = np.unique(np.asarray(cluster), return_inverse=True); m = len(keys)
    D = np.bincount(inv, weights=d); nc = np.bincount(inv).astype(float)
    idx = np.minimum((rng.random((B, m)) * m).astype(int), m - 1)
    stat = np.sort(D[idx].sum(axis=1) / nc[idx].sum(axis=1))
    lb = float(stat[max(0, math.ceil(alpha * (B + 1)) - 1)])
    return dict(mean_diff=float(d.mean()), lower_bound=lb, B=B, passed=lb > 0)

def ks_uniform(p):
    """Kolmogorov-Smirnov test of p against Uniform(0, 1): (D, p-value from the asymptotic Kolmogorov
    distribution with Stephens' correction)."""
    x = np.sort(np.asarray(p, float)); N = len(x)
    if not N: return float("nan"), float("nan")
    i = np.arange(1, N + 1); D = float(max((i / N - x).max(), (x - (i - 1) / N).max()))
    lam = (math.sqrt(N) + 0.12 + 0.11 / math.sqrt(N)) * D
    if lam < 0.2: return D, 1.0
    s = sum((-1) ** (j - 1) * math.exp(-2 * j * j * lam * lam) for j in range(1, 101))
    return D, float(min(1.0, max(0.0, 2 * s)))

# ============================================================ text rules (keyword comparator, N3)
_TOK = re.compile(r"[a-z0-9]+")
def tokens(s): return _TOK.findall(str(s).lower())

def jaccard(a, b):
    A, Bs = set(tokens(a)), set(tokens(b))
    return Fraction(len(A & Bs), len(A | Bs)) if (A | Bs) else Fraction(0)

def keyword_hits(verbatim, role, lexicon):
    """Number of the role's lexicon entries that hit: a one-word entry hits when a token starts with it, a
    multi-word entry when its words appear as consecutive tokens."""
    toks = tokens(verbatim); n = 0
    for e in lexicon[role]:
        w = e.split()
        if len(w) == 1: n += any(t.startswith(w[0]) for t in toks)
        else: n += any(toks[i:i + len(w)] == w for i in range(len(toks) - len(w) + 1))
    return n

# ============================================================ data
def load_items(P):
    """Eligible test items, sorted by family then id, with their sibling set (member order as in sibling_sets.csv)."""
    sys.path.insert(0, HERE)
    import sibling_sets
    sets = sibling_sets.load(os.path.join(DATA, "sibling_sets.csv"))
    where = {}
    for fam, by_id in sets.items():
        for sid, members in by_id.items():
            for role, code, name in members: where[code] = (fam, sid, role)
    rows = list(csv.DictReader(open(os.path.join(DATA, "coding_eval.csv"), encoding="utf-8", newline="")))
    items = []
    for r in rows:
        if r["split"] != P["split"] or r["variant"] not in P["variants"] or r["pt_code"] not in where: continue
        fam, sid, role = where[r["pt_code"]]
        items.append(dict(id=r["id"], verbatim=r["verbatim"], variant=r["variant"], family=fam, set_id=sid,
                          gold_code=r["pt_code"], gold_pt=r["pt_name"], gold_role=role, members=sets[fam][sid]))
    items.sort(key=lambda it: (FAMILIES.index(it["family"]), it["id"]))
    for fam in FAMILIES:
        got = dict(items=sum(it["family"] == fam for it in items), clusters=len({it["gold_code"] for it in items if it["family"] == fam}))
        want = P["registered_counts"][fam]
        if got != want: raise Refusal(f"{fam}: {got} eligible items/clusters, the plan registers {want}: refusing to run.", 3)
    # N2 base rates: train-split gold terms by set composition and role, +1 smoothing
    train = {r["pt_code"] for r in rows if r["split"] == "train"}
    comp = lambda fam, k: "lab" if fam == "lab" else f"site{k}"
    w = {}
    for fam, by_id in sets.items():
        for sid, members in by_id.items():
            c = w.setdefault(comp(fam, len(members)), {role: 1 for role, _, _ in members})
            for role, code, _ in members: c[role] += code in train
    for it in items: it["w"] = w[comp(it["family"], len(it["members"]))]
    return items, w

def dictionary_rows():
    import pandas as pd
    return pd.read_csv(os.path.join(DATA, "dictionary.csv"), dtype=str)

def _member_rows(dict_df):
    rows = {}
    for i, c in enumerate(dict_df["pt_code"]): rows.setdefault(c, []).append(i)
    return rows

def _cands(dict_df, rows, cos):
    import pandas as pd
    g = lambda col: [dict_df[col].iloc[i] for i in rows]
    return pd.DataFrame(dict(rank=list(range(1, len(rows) + 1)), llt_code=g("llt_code"), LLT=g("llt_name"), PT=g("pt_name"),
                             PT_CODE=g("pt_code"), HLT=g("hlt_name"), HLGT=g("hlgt_name"), SOC=g("soc_name"),
                             cosine=[round(float(c), 4) for c in cos]))

def score_standin(ns, items, dict_df):
    """T[i][k]: max over PT k's LLTs of the stand-in's Tier 4 score S (t4_coding on the stand-in Tier 2 cosines)."""
    V, _ = ns["t2_index"](dict_df); rows = _member_rows(dict_df); out = []
    for it in items:
        rr = [i for _, code, _ in it["members"] for i in rows[code]]
        c2, _, _ = ns["t4_coding"](_cands(dict_df, rr, V[rr] @ ns["_bow"](it["verbatim"])), it["verbatim"], 0.0, True, None)
        best = {}
        for code, s in zip(c2["PT_CODE"], c2["S"]): best[code] = max(best.get(code, -math.inf), float(s))
        out.append([best[code] for _, code, _ in it["members"]])
    return out, "stand-in Tier 4 score S (t4_coding, shipped [SI] weights) on the stand-in Tier 2 cosine (_bow)"

def score_real(ns, items, dict_df, P):
    """T[i][k] on the real path: the re-ranker's score when its feature contract can be computed for any candidate,
    else the Needle3 cosine (the app's Tier 2 score). Returns (T, source) or (None, reason) when it cannot run."""
    if not ns.get("REAL_T2"): return None, "not run: the models dir holds no loadable Needle3 artifact (Tier 2)"
    coder = ns.get("_coder"); meta = coder[1] if coder else None
    feats = list(meta.get("features", [])) if meta else []
    outside = [f for f in feats if f not in P["reranker_features_any_candidate"]]
    use_booster = bool(ns.get("REAL_T4")) and bool(meta) and not outside
    if use_booster: source = f"trained re-ranker score (contract {feats}), every LLT of every member scored one at a time by t4_coding"
    elif not meta: source = "Needle3 cosine (app Tier 2): no trained re-ranker loaded"
    else:
        why = ("ret_rank, the candidate's rank within the retrieved top 10, which a sibling outside that pool does not have"
               if "ret_rank" in outside else ", ".join(outside))
        source = f"Needle3 cosine (app Tier 2): the re-ranker's contract includes {why}"
    V, _ = ns["t2_index"](dict_df); rows = _member_rows(dict_df)
    amb = ns["t3_coding_batch"]([it["verbatim"] for it in items]) if use_booster else None
    out = []
    for n_i, it in enumerate(items):
        q = np.asarray(ns["_agent"].embed(ns["_t2_text"](it["verbatim"])), np.float32); q = q / np.linalg.norm(q)
        best = {}
        for _, code, _ in it["members"]:
            rr = rows[code]; cos = np.asarray(V[rr], np.float32) @ q
            if use_booster:
                s = [float(ns["t4_coding"](_cands(dict_df, [r], [c]), it["verbatim"], 0.0, True, amb[n_i]["P_UNAMBIGUOUS"])[2]["S"])
                     for r, c in zip(rr, cos)]
            else: s = [round(float(c), 4) for c in cos]
            best[code] = max(s)
        out.append([best[code] for _, code, _ in it["members"]])
    return out, source

# ============================================================ per-path analysis
def pi_for(it, null, P, lex_set=None):
    K = len(it["members"])
    if null == "N1": return np.full(K, 1.0 / K)
    if null in ("N2", "N2_lambda_0.5"):
        w = np.array([it["w"][role] for role, _, _ in it["members"]], float); w = w / w.sum()
        lam = 1.0 if null == "N2" else 0.5
        return lam * w + (1 - lam) / K
    if null == "N3":
        pi = np.array([1.0 if k in lex_set else 0.0 for k in range(K)]); return pi / pi.sum()
    raise KeyError(null)

def lex_tie_set(it, dict_df_names):
    """N3: members whose best LLT token Jaccard with the verbatim equals the gold's."""
    lex = [max(jaccard(it["verbatim"], llt) for llt in dict_df_names[code]) for _, code, _ in it["members"]]
    g = [code for _, code, _ in it["members"]].index(it["gold_code"])
    return {k for k, v in enumerate(lex) if v == lex[g]}, [str(v) for v in lex]

def analyze(items, T, P, fam_idx, path_idx, picks, B_mc=None, rng_tag=None, only=None):
    """Statistics for one family on one path. items/T aligned; picks = (pick, n_tied) per item.
    only: {null: [subsets]} to run a subset of the tests (the negative control). Returns F, M, the null
    tests and the per-item vectors."""
    B_mc = B_mc or int(P["B_mc"]); tol = float(P["tie_tolerance"])
    gold = [[code for _, code, _ in it["members"]].index(it["gold_code"]) for it in items]
    n = len(items); correct = np.array([picks[i][0] == gold[i] for i in range(n)], float)
    frac = np.array([(1.0 / picks[i][1]) if (np.asarray(T[i]) >= max(T[i]) - tol)[gold[i]] else 0.0 for i in range(n)])
    margin_i = []
    for i in range(n):
        t = np.asarray(T[i], float); others = np.delete(t, gold[i])
        margin_i.append(float(t[gold[i]] - others.max()))
    def margin_if(i, k):
        t = np.asarray(T[i], float); return float(t[k] - np.delete(t, k).max())
    res = dict(n=n, F=float(correct.mean()), F_frac=float(frac.mean()), M=float(np.mean(margin_i)),
               tie_rate=float(np.mean([p[1] > 1 for p in picks])), correct=correct, frac=frac, margin=margin_i, gold=gold)
    subsets = {s: [i for i, it in enumerate(items) if s == "all" or it["variant"] == s] for s in SUBSETS}
    res["subsets"] = {s: dict(n=len(ix), F=float(correct[ix].mean()), F_frac=float(frac[ix].mean()),
                              M=float(np.mean([margin_i[i] for i in ix])), tie_rate=float(np.mean([picks[i][1] > 1 for i in ix])))
                      for s, ix in subsets.items()}
    res["null_tests"] = {}
    for null_idx, null in enumerate(NULLS):
        if null == "N3":
            ix_all = [i for i in subsets["colloquial"] if len(items[i]["lex_set"]) >= 2]
            plan_subsets = {"colloquial": ix_all}
        elif null == "N2_lambda_0.5": plan_subsets = {"all": subsets["all"]}
        else: plan_subsets = subsets
        if only is not None:
            if null not in only: continue
            plan_subsets = {s: v for s, v in plan_subsets.items() if s in only[null]}
        rows = []
        for s_idx, (s, ix) in enumerate(plan_subsets.items()):
            if not ix: rows.append(dict(stat="F", subset=s, n=0, p=None)); continue
            clusters = {}
            for i in ix: clusters.setdefault(items[i]["gold_code"], []).append(i)
            pmfs, Kmax = [], max(len(items[i]["members"]) for i in ix)
            mg = np.zeros((len(clusters), Kmax)); pim = np.zeros((len(clusters), Kmax))
            for c_idx, (code, cix) in enumerate(clusters.items()):
                it0 = items[cix[0]]; K = len(it0["members"])
                pi = pi_for(it0, null, P, it0.get("lex_set"))
                counts = np.bincount([picks[i][0] for i in cix], minlength=K)
                pmfs.append(cluster_pmf(counts, pi))
                pim[c_idx, :K] = pi
                mg[c_idx, :K] = [sum(margin_if(i, k) for i in cix) for k in range(K)]
            obs = int(correct[ix].sum()); pF = exact_tail(pmfs, obs)
            rng = rng_for(P, "mc_margin", fam_idx, path_idx, null_idx, SUBSETS.index(s)) if rng_tag is None else rng_for(P, *rng_tag, null_idx, SUBSETS.index(s))
            Mobs = float(np.mean([margin_i[i] for i in ix]))
            pM, mcse, _ = mc_margin_p(mg, pim, len(ix), Mobs, B_mc, rng, tol)
            rows.append(dict(stat="F", subset=s, n=len(ix), clusters=len(clusters), value=float(correct[ix].mean()), p=pF))
            rows.append(dict(stat="M", subset=s, n=len(ix), clusters=len(clusters), value=Mobs, p=pM, mcse=mcse, B=B_mc))
        ps = [r["p"] for r in rows if r.get("p") is not None]
        if null != "N2_lambda_0.5":
            qb, qy = bh(ps), by(ps); j = 0
            for r in rows:
                if r.get("p") is not None: r["q_bh"], r["q_by"] = float(qb[j]), float(qy[j]); j += 1
        res["null_tests"][null] = rows
    return res

def picks_for(T, P, stream, *idx):
    rng = rng_for(P, stream, *idx); tol = float(P["tie_tolerance"])
    return [pick_with_ties(t, rng.random(), tol) for t in T]

def keyword_picks(items, P):
    rng = rng_for(P, "keyword_tie_break"); lex = P["keyword_lexicon"]; out = []
    for it in items:
        hits = [keyword_hits(it["verbatim"], role, lex) for role, _, _ in it["members"]]
        k, nt = pick_with_ties(hits, rng.random())
        out.append((k, nt, hits))
    return out

def negative_control(items_f, T_f, P, fam_idx):
    """Per cluster, one random permutation of the members applied to every item's scores; F (exact) and M
    (B = negative_control.B_mc) re-tested under N1, N2, N3 for each permutation."""
    NC = P["negative_control"]; R = int(NC["permutations"]); rng = rng_for(P, "negative_control", fam_idx)
    clusters = {}
    for i, it in enumerate(items_f): clusters.setdefault(it["gold_code"], []).append(i)
    rej = {n: {"F": 0, "M": 0} for n in ("N1", "N2", "N3")}; pF1 = []
    tol = float(P["tie_tolerance"])
    for r in range(R):
        Tp = [None] * len(items_f)
        for code, cix in clusters.items():
            K = len(items_f[cix[0]]["members"]); perm = np.argsort(rng.random(K))
            for i in cix: Tp[i] = list(np.asarray(T_f[i], float)[perm])
        pk = [pick_with_ties(t, rng.random(), tol) for t in Tp]
        a = analyze(items_f, Tp, P, fam_idx, 0, pk, B_mc=int(NC["B_mc"]), rng_tag=("negative_control", fam_idx, r + 1),
                    only={"N1": ["all"], "N2": ["all"], "N3": ["colloquial"]})
        for null in ("N1", "N2", "N3"):
            for row in a["null_tests"][null]:
                if row["subset"] == ("colloquial" if null == "N3" else "all") and row.get("p") is not None:
                    rej[null][row["stat"]] += row["p"] < float(P["alpha"])
                    if null == "N1" and row["stat"] == "F": pF1.append(row["p"])
    rate = lambda x: dict(rate=x / R, mcse=math.sqrt((x / R) * (1 - x / R) / R))
    out = dict(permutations=R, B_mc=int(NC["B_mc"]), max_rejection=float(NC["max_rejection"]),
               reject={n: {s: rate(v) for s, v in d.items()} for n, d in rej.items()})
    out["met"] = out["reject"]["N1"]["F"]["rate"] <= float(NC["max_rejection"])
    return out

# ============================================================ run
SIG_KEYS = ("p", "q_bh", "q_by")    # p- and q-values keep 6 significant figures, so an exact tail of 3e-11 is not written as 0

def _r(x, nd=6, key=None):
    """Floats for the JSON: 6 decimals, except the p- and q-values (SIG_KEYS), which keep 6 significant figures."""
    if isinstance(x, (float, np.floating)): return float(f"{float(x):.6g}") if key in SIG_KEYS else round(float(x), nd)
    if isinstance(x, dict): return {k: _r(v, nd, k) for k, v in x.items()}
    if isinstance(x, list): return [_r(v, nd, key) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.bool_,)): return bool(x)
    return x

def evaluate_path(items, T, P, path, kw, negctl):
    """Family-level results on one path, plus per-item rows."""
    path_idx = PATHS.index(path); fam_out, item_rows = {}, []
    tol = float(P["tie_tolerance"])
    picks_all = picks_for(T, P, "tie_break", path_idx)
    for fam_idx, fam in enumerate(FAMILIES):
        ix = [i for i, it in enumerate(items) if it["family"] == fam]
        it_f = [items[i] for i in ix]; T_f = [T[i] for i in ix]; pk = [picks_all[i] for i in ix]
        a = analyze(it_f, T_f, P, fam_idx, path_idx, pk)
        kw_correct = np.array([kw[i][0] == a["gold"][j] for j, i in enumerate(ix)], float)
        clusters = [it["gold_code"] for it in it_f]
        A = gate_a(a["correct"], clusters, float(P["alpha"]), float(P["a_min"]))
        A_frac = gate_a(a["frac"], clusters, float(P["alpha"]), float(P["a_min"]))
        Bg = gate_b(a["correct"] - kw_correct, clusters, int(P["B_boot"]), rng_for(P, "gate_b_bootstrap", fam_idx, path_idx), float(P["alpha"]))
        reasons = []
        if not A["assessable"]: reasons.append(f"not assessable at this size: m = {A['m']} clusters, best attainable bound {A['attainable_bound']:.3f} < a_min {A['a_min']:.2f}")
        if not A["passed"]: reasons.append(f"Gate A failed: lower bound {A['bound']:.3f} < a_min {A['a_min']:.2f}")
        if not Bg["passed"]: reasons.append(f"Gate B failed: tool minus keyword rule lower bound {Bg['lower_bound']:+.3f} is not above 0")
        decision = "auto-coding allowed" if not reasons else "excluded from auto-coding: routes to human coding"
        by_var = {}
        for v in ("exact", "colloquial", "misspelled"):
            jv = [j for j, it in enumerate(it_f) if it["variant"] == v]
            by_var[v] = dict(a["subsets"][v], keyword_F=float(kw_correct[jv].mean()))
        sizes = {}
        for it in it_f: sizes[str(len(it["members"]))] = sizes.get(str(len(it["members"])), 0) + 1
        fam_out[fam] = dict(
            n=a["n"], m=A["m"], items_per_cluster=a["n"] / A["m"], set_size_items=sizes,
            F=a["F"], F_frac_sensitivity=a["F_frac"], tie_rate=a["tie_rate"], M=a["M"], keyword_F=float(kw_correct.mean()),
            gate_a=dict({k: A[k] for k in ("rho_hat", "deff", "n_eff", "x_eff", "bound", "a_min", "attainable_bound", "assessable", "passed")},
                        frac_credit_sensitivity=dict(F=A_frac["F"], rho_hat=A_frac["rho_hat"], bound=A_frac["bound"])),
            gate_b=Bg, decision=decision, decision_reasons=reasons, by_variant=by_var,
            n2_weights=dict(it_f[0]["w"]) if fam == "lab" else {f"site{k}": dict(w) for k, w in
                           sorted({len(it["members"]): it["w"] for it in it_f}.items())},
            null_tests=a["null_tests"],
            n3=dict(colloquial_items=sum(it["variant"] == "colloquial" for it in it_f),
                    used=sum(1 for it in it_f if it["variant"] == "colloquial" and len(it["lex_set"]) >= 2),
                    dropped_singleton=sum(1 for it in it_f if it["variant"] == "colloquial" and len(it["lex_set"]) < 2)))
        if negctl: fam_out[fam]["negative_control"] = negative_control(it_f, T_f, P, fam_idx)
        for j, it in enumerate(it_f):
            roles = [role for role, _, _ in it["members"]]; i = ix[j]
            item_rows.append(dict(path=path, family=fam, id=it["id"], cluster=it["gold_code"], set_id=it["set_id"],
                set_size=len(roles), variant=it["variant"], verbatim=it["verbatim"], gold_role=it["gold_role"],
                scores=";".join(f"{r}={s:.4f}" for r, s in zip(roles, T_f[j])), pick_role=roles[pk[j][0]], tied=pk[j][1],
                correct=int(a["correct"][j]), frac_credit=round(float(a["frac"][j]), 6), margin=round(a["margin"][j], 4),
                keyword_hits=";".join(f"{r}={h}" for r, h in zip(roles, kw[i][2])), keyword_pick_role=roles[kw[i][0]],
                keyword_correct=int(kw_correct[j]),
                lex_tie_set=("|".join(roles[k] for k in sorted(it["lex_set"])) if it["variant"] == "colloquial" else "")))
    return fam_out, item_rows

def run(P, plan_sha, inputs, models=None, out_dir=RESULTS, deviations=()):
    sys.path.insert(0, HERE)
    from _app import load_app
    items, w = load_items(P)
    dict_df = dictionary_rows()
    names = {}
    for code, llt in zip(dict_df["pt_code"], dict_df["llt_name"]): names.setdefault(code, []).append(llt)
    for it in items:
        if it["variant"] == "colloquial": it["lex_set"], it["lex"] = lex_tie_set(it, names)
        else: it["lex_set"], it["lex"] = set(), []
    kw = keyword_picks(items, P)
    summary = dict(plan=dict(file="eval/sibling_plan.md", sha256=plan_sha, version=P["plan_version"]),
                   inputs_sha256=inputs, scorer_fingerprint=scorer_fingerprint(), deviations=list(deviations),
                   environment=dict(python=platform.python_version(), numpy=np.__version__),
                   synthetic="Synthetic data only: invented terms with 99-prefixed placeholder codes, not MedDRA.",
                   parameters={k: P[k] for k in ("seed", "alpha", "a_min", "B_mc", "B_boot", "split", "variants")},
                   results={fam: {} for fam in FAMILIES})
    item_rows = []
    ns = load_app("meddra"); T, src = score_standin(ns, items, dict_df)
    fam_out, rows = evaluate_path(items, T, P, "standin", kw, negctl=True); item_rows += rows
    for fam in FAMILIES: summary["results"][fam]["standin"] = dict(score_source=src, **fam_out[fam])
    T_by_path = {"standin": T}
    if models:
        nsr = load_app("meddra", models); Tr, srcr = score_real(nsr, items, dict_df, P)
        if Tr is None:
            for fam in FAMILIES: summary["results"][fam]["real"] = dict(status=srcr)
        else:
            fam_out, rows = evaluate_path(items, Tr, P, "real", kw, negctl=False); item_rows += rows
            for fam in FAMILIES: summary["results"][fam]["real"] = dict(score_source=srcr, models_dir_artifacts=nsr["_R"]["info"], **fam_out[fam])
            T_by_path["real"] = Tr
    else:
        for fam in FAMILIES:
            summary["results"][fam]["real"] = dict(status="not run: no models dir was given (python eval/sibling_eval.py --models <dir>; eval/README.md)")
    # the registered known answer
    ka = P["known_answer_item"]; kai = [i for i, it in enumerate(items) if it["verbatim"] == ka["verbatim"] and it["gold_pt"] == ka["gold_pt"]]
    kao = dict(verbatim=ka["verbatim"], gold_pt=ka["gold_pt"], found=bool(kai))
    if kai:
        i = kai[0]; roles = [role for role, _, _ in items[i]["members"]]
        for path, TT in T_by_path.items(): kao[path] = dict(zip(roles, [round(float(x), 4) for x in TT[i]]))
    lab_paths = {p: v for p, v in summary["results"]["lab"].items() if "decision" in v}
    kao["lab_family_routes_to_human_on_every_path_run"] = all(v["decision"] != "auto-coding allowed" for v in lab_paths.values())
    kao["expected"] = "lab family failing or not assessable on every path (plan section 14)"
    kao["met"] = kao["lab_family_routes_to_human_on_every_path_run"]
    summary["known_answer"] = kao
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "sibling_summary.json"), "w", encoding="utf-8") as f:
        json.dump(_r(summary), f, indent=1); f.write("\n")
    cols = ["path", "family", "id", "cluster", "set_id", "set_size", "variant", "verbatim", "gold_role", "scores", "pick_role", "tied",
            "correct", "frac_credit", "margin", "keyword_hits", "keyword_pick_role", "keyword_correct", "lex_tie_set"]
    with open(os.path.join(out_dir, "sibling_items.csv"), "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, lineterminator="\n"); wr.writeheader(); wr.writerows(item_rows)
    return summary

def main(argv=None):
    ap = argparse.ArgumentParser(description="Within-sibling evaluation of the Coding QC assist (registered plan: eval/sibling_plan.md)")
    ap.add_argument("--models", help="a models dir with the real artifacts (eval/README.md); without it only the stand-in path runs")
    ap.add_argument("--out", default=RESULTS, help="output folder (default eval/results)")
    ap.add_argument("--plan", default=PLAN, help=argparse.SUPPRESS)       # tests only; the hash file is always eval/sibling_plan.sha256
    ap.add_argument("--allow-scorer-change", action="store_true",
                    help="run although meddra_app.py's scoring code differs from the plan's fingerprint (recorded as a deviation)")
    a = ap.parse_args(argv)
    try:
        P, plan_sha = check_plan(a.plan, PLAN_HASH)
        inputs = check_inputs(P)
        fp = scorer_fingerprint(); dev = []
        if fp != P["scorer_fingerprint"]:
            if not a.allow_scorer_change:
                raise Refusal(f"meddra_app.py's scoring code has fingerprint {fp}, the plan registers {P['scorer_fingerprint']}: "
                              f"refusing to run (re-register the plan, or pass --allow-scorer-change to record a deviation).", 4)
            dev.append(f"scorer fingerprint {fp} differs from the registered {P['scorer_fingerprint']} (--allow-scorer-change)")
    except Refusal as e:
        print("REFUSED: " + str(e), file=sys.stderr); return e.code
    s = run(P, plan_sha, inputs, models=a.models, out_dir=a.out, deviations=dev)
    for fam in FAMILIES:
        for path, v in s["results"][fam].items():
            if "decision" not in v: print(f"{fam:4s} {path:7s} {v.get('status')}"); continue
            print(f"{fam:4s} {path:7s} n={v['n']} m={v['m']} F={v['F']:.3f} keywordF={v['keyword_F']:.3f} "
                  f"boundA={v['gate_a']['bound']:.3f} (best {v['gate_a']['attainable_bound']:.3f}) "
                  f"LB_B={v['gate_b']['lower_bound']:+.3f} -> {v['decision']}")
    print("known answer:", s["known_answer"])
    print("wrote", os.path.join(a.out, "sibling_summary.json"), "and sibling_items.csv")
    if not s["known_answer"]["met"]:
        print("EXPECTED ANSWER NOT MET: the lab family did not route to human coding. Find the bug before publishing.", file=sys.stderr)
        return 5
    return 0

if __name__ == "__main__":
    sys.exit(main())
