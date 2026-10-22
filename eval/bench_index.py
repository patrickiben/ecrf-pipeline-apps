#!/usr/bin/env python3
"""Stage 1: real Tier 2 for coding. Measures Needle3 embedding + hnswlib retrieval as the app runs it.

Run (needs the real runtimes and a models dir, see eval/README.md):
    python eval/bench_index.py --models <models_dir>

What is measured, all on this machine and written to eval/results/stage1_index.json:
  * per dictionary (the 12-term demo dictionary and the generated eval dictionary): embedding time
    per term, HNSW build time, resident index size (vectors + graph, from the saved index), and per
    verbatim the embed latency, the HNSW search latency (k=10, efSearch=64) and a brute-force exact
    search for comparison, plus recall@10 of the graph against the exact search. Queries are the
    1,920 generated verbatims in eval/data/coding_eval.csv.
  * at the deck's ~86,800-term scale: build time, resident size and search latency of the SAME index
    settings over random unit vectors of Needle3's real width (3072). This isolates the index cost at
    full-release scale without spending ~35 CPU-minutes embedding term strings; it says nothing about
    retrieval QUALITY, which the evaluation measures on real embeddings.
The app's own functions are used (eval/_app.py): t2_index builds the index exactly as the app does
(M=32, efConstruction=200, single-threaded insertion, efSearch=64).
"""
import argparse, json, os, platform, resource, sys, tempfile, time
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _app import load_app, ROOT

def cpu_name():
    try: return next(l.split(":",1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except Exception: return platform.processor() or platform.machine()

def pct(a, q): return round(float(np.percentile(a, q)), 3)

def rss_mb(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

def bench_dict(ns, df, queries, label):
    """Embed + index one dictionary the way the app does, then time every query."""
    hnswlib, ag = ns["hnswlib"], ns["_agent"]
    ag._index_cache = tempfile.mkdtemp(prefix="ecrf_bench_")      # force a fresh build, timed
    names = [str(x) for x in df["llt_name"]]
    t0 = time.perf_counter(); V, idx = ns["t2_index"](df); build_s = time.perf_counter() - t0
    files = os.listdir(ag._index_cache)
    vec_b = sum(os.path.getsize(os.path.join(ag._index_cache, f)) for f in files if f.endswith(".npy"))
    graph_file_b = sum(os.path.getsize(os.path.join(ag._index_cache, f)) for f in files if f.endswith(".hnsw"))
    emb, srch, brute, rec, Q = [], [], [], [], []
    k = min(10, len(names))
    # three separate passes: interleaving the multi-threaded brute-force matmul with the embed calls
    # lets idle BLAS threads compete with the Needle3 worker process and inflates the embed timings
    for q in queries:
        t = time.perf_counter(); v = np.asarray(ag.embed(q), np.float32); v /= np.linalg.norm(v); emb.append(1000 * (time.perf_counter() - t))
        Q.append(v)
    labs = []
    for v in Q:
        t = time.perf_counter(); lab, _ = idx.knn_query(v.reshape(1, -1), k=k); srch.append(1000 * (time.perf_counter() - t)); labs.append(lab[0])
    for v, lab in zip(Q, labs):
        t = time.perf_counter(); ex = np.argsort(-(V @ v))[:k]; brute.append(1000 * (time.perf_counter() - t))
        rec.append(len(set(lab) & set(ex)) / k)
    n, dim = V.shape
    return dict(dictionary=label, terms=n, dim=dim, embed_build_s=round(build_s, 2),
                embed_ms_per_term=round(1000 * build_s / n, 2),
                resident_mb=round(graph_file_b / 2**20, 2), vectors_mb=round(n * dim * 4 / 2**20, 2),
                graph_edges_mb=round((graph_file_b - n * dim * 4) / 2**20, 2), queries=len(queries),
                embed_ms=dict(median=pct(emb, 50), p90=pct(emb, 90)),
                hnsw_search_ms=dict(median=pct(srch, 50), p90=pct(srch, 90)),
                brute_search_ms=dict(median=pct(brute, 50), p90=pct(brute, 90)),
                recall_at_10=round(float(np.mean(rec)), 4))

def bench_scale(hnswlib, n=86800, dim=3072, nq=500, seed=42):
    """Index cost at full-release scale on random unit vectors of the real width (see docstring)."""
    rng = np.random.default_rng(seed)
    V = rng.standard_normal((n, dim), dtype=np.float32); V /= np.linalg.norm(V, axis=1, keepdims=True)
    Q = rng.standard_normal((nq, dim), dtype=np.float32); Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    idx = hnswlib.Index(space="ip", dim=dim); idx.init_index(max_elements=n, ef_construction=200, M=32)
    t0 = time.perf_counter(); idx.add_items(V, np.arange(n), num_threads=os.cpu_count()); build = time.perf_counter() - t0
    idx.set_ef(64); f = os.path.join(tempfile.mkdtemp(), "scale.hnsw"); idx.save_index(f); size = os.path.getsize(f)
    srch, rec = [], []
    for i, q in enumerate(Q):
        t = time.perf_counter(); lab, _ = idx.knn_query(q.reshape(1, -1), k=10); srch.append(1000 * (time.perf_counter() - t))
        if i < 100: rec.append(len(set(lab[0]) & set(np.argsort(-(V @ q))[:10])) / 10)
    os.remove(f)
    return dict(terms=n, dim=dim, vectors="random unit vectors (index cost only)", build_s=round(build, 1),
                build_threads=os.cpu_count(), resident_mb=round(size / 2**20, 1), vectors_mb=round(n * dim * 4 / 2**20, 1),
                graph_edges_mb=round((size - n * dim * 4) / 2**20, 1),
                hnsw_search_ms=dict(median=pct(srch, 50), p90=pct(srch, 90)), recall_at_10_first100=round(float(np.mean(rec)), 4),
                note="random vectors are a hard case for HNSW (no cluster structure), so recall here is a floor, not the real-data value")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--models", required=True); ap.add_argument("--no-scale", action="store_true")
    a = ap.parse_args()
    ns = load_app("meddra", a.models)
    assert ns["REAL_T2"], "Needle3 + hnswlib did not load from the models dir"
    queries = list(pd.read_csv(os.path.join(ROOT, "eval", "data", "coding_eval.csv"))["verbatim"])
    demo = pd.read_csv(os.path.join(ROOT, "sample_data", "meddra_demo.csv"), dtype=str)
    big = pd.read_csv(os.path.join(ROOT, "eval", "data", "dictionary.csv"), dtype=str)
    out = dict(machine=dict(cpu=cpu_name(), cores=os.cpu_count(), python=platform.python_version()),
               runtimes=ns["_R"]["info"], results=[])
    for df, label in ((demo, "demo (sample_data/meddra_demo.csv)"), (big, "generated (eval/data/dictionary.csv)")):
        r = bench_dict(ns, df, queries, label); out["results"].append(r); print(json.dumps(r))
    out_p = os.path.join(ROOT, "eval", "results", "stage1_index.json")
    if not a.no_scale:
        r = bench_scale(ns["hnswlib"]); out["scale"] = r; print(json.dumps(r))
    elif os.path.exists(out_p) and "scale" in json.load(open(out_p)):
        out["scale"] = json.load(open(out_p))["scale"]          # keep the previous scale run
    out["peak_rss_mb"] = round(rss_mb(), 1)
    os.makedirs(os.path.join(ROOT, "eval", "results"), exist_ok=True)
    json.dump(out, open(out_p, "w"), indent=1)

if __name__ == "__main__":
    main()
