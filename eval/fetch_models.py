#!/usr/bin/env python3
"""Build a models dir for the REAL path, on a machine WITH network access, then copy it air-gapped.

    python eval/fetch_models.py --out <models_dir>            # download weights + copy trained artifacts

Downloads, using the model packages' own pinned download code (Needle3) and a pinned commit (Laya):
  <out>/needle3/needle3.cact      Cactus Needle3 weights        (Hugging Face Cactus-Compute/needle3)
  <out>/needle3/libneedle.so      its native CPU engine (.dylib on macOS, .dll on Windows), extracted by
                                  cactus-needle's own fetch from the engine wheel in the same repo
  <out>/laya/                     Laya's English checkpoint only (convaiinnovations/laya, repository
                                  root at the reviewed commit laya pins in laya/revisions.py); the
                                  multilingual and typed-decisions checkpoints are NOT downloaded
and copies the trained, synthetic-data artifacts committed in eval/artifacts/ (Laya temperatures and
the two XGBoost gates with their feature contracts). Prints a SHA-256 for every file, for the record.

Telemetry is switched off for the downloads (NEEDLE_TELEMETRY=0, DO_NOT_TRACK=1). After this, the apps
need no network: they read only <out> (set it as the Models dir in the sidebar).
"""
import argparse, glob, hashlib, os, shutil, sys

os.environ.setdefault("NEEDLE_TELEMETRY", "0"); os.environ.setdefault("DO_NOT_TRACK", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
LAYA_REPO = "convaiinnovations/laya"
LAYA_FILES = ["rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*"]

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True)
    ap.add_argument("--no-artifacts", action="store_true", help="weights only (to retrain with eval/run_eval.py)")
    a = ap.parse_args(); out = os.path.abspath(a.out)
    from needle.agent import fetch                     # cactus-needle's own pinned engine/weights download
    from laya.revisions import PINNED_REVISIONS
    from huggingface_hub import snapshot_download
    nd = os.path.join(out, "needle3"); os.makedirs(nd, exist_ok=True)
    lib = fetch.fetch_library(fetch.engine_version(3), nd, generation=3)
    w = fetch.fetch_weights(3, nd)
    if os.path.abspath(w) != os.path.join(nd, "needle3.cact"): shutil.copy(w, os.path.join(nd, "needle3.cact"))
    rev = PINNED_REVISIONS[LAYA_REPO]
    snapshot_download(LAYA_REPO, revision=rev, local_dir=os.path.join(out, "laya"), allow_patterns=LAYA_FILES)
    if not a.no_artifacts:
        for f in glob.glob(os.path.join(HERE, "artifacts", "*.json")): shutil.copy(f, out)
    print(f"engine: {lib}\nLaya revision: {rev}")
    for p in sorted(glob.glob(os.path.join(out, "**", "*"), recursive=True)):
        if os.path.isfile(p) and "/.cache/" not in p: print(f"{sha(p)}  {os.path.getsize(p):>11,}  {os.path.relpath(p, out)}")

if __name__ == "__main__":
    sys.exit(main())
