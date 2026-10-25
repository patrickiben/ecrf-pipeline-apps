#!/usr/bin/env python3
"""Keep the in-browser build in docs/app/ in step with the source apps.

GitHub Pages serves docs/ (main branch), and docs/app/ holds the four in-browser apps: stlite runs
Streamlit on Pyodide (CPython compiled to WebAssembly) inside the visitor's tab, so there is no server.
Each page fetches its program and synthetic data from docs/app/ itself, so docs/app/ holds:

  meddra_app.py, phi_app.py, risk_app.py, anomaly_app.py  byte-identical COPIES of the repository-root files
  sample_data/*.csv, anomaly_data/*.csv                     byte-identical COPIES of the bundled synthetic data
  meddra.html, phi.html, risk.html, anomaly.html            RENDERED from tools/browser_app_template.html
  launch.js, app.css                                        the shared loader and page style (edited by hand)
  wheels/*.whl                                              three small pure-Python wheels, pinned below

The wheels are dependencies of the Streamlit build that are not in the Pyodide distribution. stlite would
otherwise fetch them from PyPI on every cold load; serving them from Pages keeps the page to two hosts,
GitHub Pages and the jsDelivr CDN, which is what the privacy note on each page says.

    python tools/sync_browser_apps.py                 copy what changed, delete stale copies, re-render the pages
    python tools/sync_browser_apps.py --check         change nothing; list every difference and exit 1 if any (CI)
    python tools/sync_browser_apps.py --fetch-wheels  also download a missing pinned wheel from PyPI (hash-checked)
    python tools/sync_browser_apps.py --verify-cdn    fetch the pinned stlite files from the CDN and check the
                                                      SRI hashes below (network; run it when changing STLITE_*)

Standard library only, so CI can run it before installing anything.
"""
import argparse, base64, hashlib, html, json, os, re, shutil, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "docs", "app")
TEMPLATE = os.path.join(ROOT, "tools", "browser_app_template.html")

# ---- pins. Change them together, then run --verify-cdn and the browser check in the README. ----
# @stlite/browser 1.12.0 (npm, 2026-10-18) bundles Streamlit 1.65.0 for Pyodide 314.0.3 (CPython 3.14,
# pandas 3.0.2, numpy 2.4.3, pyarrow 22.0.0). The Pyodide URL is the one this stlite release uses by
# default; it is passed explicitly so the pin is visible here.
CDN = "https://cdn.jsdelivr.net"
STLITE_VERSION = "1.12.0"
STLITE_BUILD = f"{CDN}/npm/@stlite/browser@{STLITE_VERSION}/build"
PYODIDE_URL = f"{CDN}/pyodide/v314.0.3/full/pyodide.mjs"
# Subresource Integrity for the stylesheet and for the two module files that hold the kernel and the
# inlined worker (stlite.js and the chunk it imports statically). Checked against the npm tarball and the
# CDN copy; a changed file is refused by the browser.
STLITE_SRI = {
    "stlite.css": "sha384-nMY1QbA8+CIsSUwemJXUxjUlxoaTVytN3oKA4RhBMsdJgRaucGjAuus4FPhQV8Ui",
    "stlite.js": "sha384-3IQsZ2w/7wJJ4Fxwpnzw+hHGanfH1/gZx90qxuEwmIdnsD1C+mMpZTk5+rMRPNOC",
    "index-B1FrxEMd-BsPMjC5n.js": "sha384-An7Ztv5V2jtm0k4yPzlb/6bULPYO9ABz8trQtKGWiz3zY1pxDZcFhZC35qT7iSl6",
}
# Not in the Pyodide 314.0.3 distribution, so pinned and served from Pages. itsdangerous and
# python-multipart are Requires-Dist of the stlite Streamlit wheel; toml lets Streamlit scan component
# manifests (without it the boot logs "No module named toml"). Hashes are PyPI's published sha256.
WHEELS = [
    ("itsdangerous-2.2.0-py3-none-any.whl", "c6242fc49e35958c8b15141343aa660db5fc54d4f13a1db01a3f5891b98700ef",
     "https://files.pythonhosted.org/packages/04/96/92447566d16df59b2a776c0fb82dbc4d9e07cd95062562af01e408583fc4/itsdangerous-2.2.0-py3-none-any.whl"),
    ("python_multipart-0.0.32-py3-none-any.whl", "ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23",
     "https://files.pythonhosted.org/packages/e1/04/e8135ebd1ad02c56ec633277529b2602ff99ff634be76cdba5744cf554fd/python_multipart-0.0.32-py3-none-any.whl"),
    ("toml-0.10.2-py2.py3-none-any.whl", "806143ae5bfb6a3c6e736a764057db0e6a0e05e338b5630894a5f779cabb4f9b",
     "https://files.pythonhosted.org/packages/44/6f/7120676b6d73228c96e17f1f794d8ab046fc910d781c8d151120c3f1569e/toml-0.10.2-py2.py3-none-any.whl"),
]
# numpy and pandas are what the apps import (both come from the Pyodide distribution on the CDN); toml as above.
REQUIREMENTS = ["numpy", "pandas", "toml"]

# What each page must say about its own limits, next to the privacy note, so a visitor reads the measured
# shortfall before the results (docs/EVALUATION.md has the numbers; they are synthetic-data results).
EVALUATION = "https://github.com/patrickiben/ecrf-pipeline-apps/blob/main/docs/EVALUATION.md"
APPS = {
    "meddra": dict(entry="meddra_app.py", data="sample_data", title="Coding QC Assist (MedDRA-style, demo dictionary)",
        description="A coding QC assist running in your browser on synthetic adverse-event data: the top three candidate terms per verbatim from a demo dictionary with placeholder codes (not MedDRA), and a gate that sends each verbatim to a coder or auto-commits it.",
        img="meddra_results.png",
        limits="Measured on held-out synthetic verbatims, this lexical stand-in ranked the right preferred term first "
               "for 54% (the real model path: 78%) and auto-coded 7 of 96 negated verbatims at the default gate; every "
               "code needs a coder's review.", limits_link=EVALUATION,
        alt="Coding app results table: each adverse-event verbatim with its top three candidate terms, ranks and 99-prefixed placeholder codes, followed by the success message and download buttons."),
    "phi": dict(entry="phi_app.py", data="sample_data", title="De-identification Review Assist",
        description="A de-identification review assist running in your browser on synthetic eCRF text: flagged identifier spans and sanitized copies of each table, for a person to review.",
        img="phi_results.png",
        limits="On held-out synthetic text this stand-in left 108 of 308 identifiers readable (the real model path: "
               "91 of 308); every output needs human review.", limits_link=EVALUATION,
        alt="PHI app results: a table of flagged spans such as invented phone numbers, names, a ZIP code and initials, each with its entity type, offsets, redaction probability and action, above the sanitized domain rows."),
    "risk": dict(entry="risk_app.py", data="sample_data", title="Participant Risk Screening",
        description="Participant risk screening running in your browser on synthetic safety domains: a safety listing that ranks participants against built-in criteria standing in for a protocol's, with the reasons for each flag.",
        img="risk_results.png",
        limits="Both scores are capped, weighted sums of built-in [SI] rules, not probabilities or a validated model; every "
               "flag needs clinical review.",
        alt="Risk app results: per-participant safety and discontinuation scores and categories with contributing factors, the fatal case pinned to the top, and a category summary."),
    "anomaly": dict(entry="anomaly_app.py", data="anomaly_data", title="Anomaly and Drift Checks",
        description="Central statistical monitoring checks running in your browser on a synthetic longitudinal lab cut: numeric outliers, cohort drift, per-lab drift and unusual free-text notes.",
        img="anomaly_results.png",
        limits="Here every detector runs its [SI] stand-in (robust z, 1-D Wasserstein drift, bag-of-words text "
               "isolation) with built-in thresholds; every flag needs human review.",
        alt="Anomaly app results: flagged per-participant numeric outliers with their extreme columns, a cohort-wide drift table per column, and the start of the per-lab drift table."),
}
HAND_EDITED = ["launch.js", "app.css"]          # live in docs/app/ only; must exist
LOADING_NOTICE = "Starting Python in your browser; first visit downloads about 30 MB."
PRIVACY_NOTE = ("Runs in your browser; files are processed on your device and not uploaded by the app; the page is "
                "downloaded from GitHub Pages and the CDN, which see your IP address; synthetic data only; not a "
                "validated or Part 11 system.")
RUN_LOCALLY = "https://github.com/patrickiben/ecrf-pipeline-apps#run-locally"


def _read(p):
    with open(p, "rb") as f: return f.read()

def _sha256(b): return hashlib.sha256(b).hexdigest()

def _sri(b): return "sha384-" + base64.b64encode(hashlib.sha384(b).digest()).decode()

def _data_files(folder):
    """The CSVs an app mounts: every *.csv in the source folder (README.md and generate.py stay out)."""
    src = os.path.join(ROOT, folder)
    return sorted(f"{folder}/{f}" for f in os.listdir(src) if f.lower().endswith(".csv"))

def expected_copies():
    """{path under docs/app/: source path} for every byte-identical copy."""
    rels = [a["entry"] for a in APPS.values()]
    for folder in sorted({a["data"] for a in APPS.values()}): rels += _data_files(folder)
    return {r: os.path.join(ROOT, *r.split("/")) for r in rels}

def render_page(key):
    a = APPS[key]
    imports = {f"{STLITE_BUILD}/{f}": h for f, h in STLITE_SRI.items() if f.endswith(".js")}
    importmap = json.dumps({"integrity": imports}, indent=2)
    importmap_hash = "'sha256-" + base64.b64encode(hashlib.sha256(importmap.encode()).digest()).decode() + "'"
    csp = "; ".join([
        "default-src 'none'",
        f"script-src 'self' {CDN} 'wasm-unsafe-eval' blob: data: {importmap_hash}",
        f"style-src 'self' {CDN} 'unsafe-inline'",
        f"font-src {CDN} data:",
        f"img-src 'self' {CDN} data: blob:",
        f"connect-src 'self' {CDN} blob: data:",
        "worker-src blob: data:",
        "base-uri 'none'", "form-action 'none'", "object-src 'none'",
    ])
    config = {
        "app": key, "entry": a["entry"], "data": _data_files(a["data"]),
        "stlite": f"{STLITE_BUILD}/stlite.js", "pyodide": PYODIDE_URL,
        "requirements": REQUIREMENTS, "wheels": [f"wheels/{w[0]}" for w in WHEELS],
    }
    cfg = json.dumps(config, indent=2).replace("<", "\\u003c")
    fill = {
        "TITLE": html.escape(a["title"]), "DESCRIPTION": html.escape(a["description"]),
        "CSP": html.escape(csp, quote=False), "STLITE_CSS": f"{STLITE_BUILD}/stlite.css", "STLITE_CSS_SRI": STLITE_SRI["stlite.css"],
        "CDN": CDN, "IMPORTMAP": importmap, "CONFIG": cfg, "IMG": a["img"], "ALT": html.escape(a["alt"]),
        "LOADING_NOTICE": html.escape(LOADING_NOTICE), "PRIVACY_NOTE": html.escape(PRIVACY_NOTE),
        "LIMITS": html.escape(a["limits"]) + (f' <a href="{a["limits_link"]}">How this was measured</a>.'
                                               if a.get("limits_link") else ""),
        "RUN_LOCALLY": RUN_LOCALLY, "STLITE_VERSION": STLITE_VERSION,
    }
    out = _read(TEMPLATE).decode("utf-8")
    for k, v in fill.items(): out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left: raise SystemExit(f"template placeholders not filled: {sorted(set(left))}")
    return out.encode("utf-8")

def _local_refs(page_bytes):
    """Local src/href targets in a rendered page (off-site, data:, #anchors skipped)."""
    refs = re.findall(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""", page_bytes.decode("utf-8"))
    return [r for r in refs if not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", r, re.I)]

def compare():
    """Every difference between docs/app/ and what it should hold, as (kind, path, detail) tuples."""
    problems, copies = [], expected_copies()
    pages = {f"{k}.html": render_page(k) for k in APPS}
    wheels = {f"wheels/{w[0]}": w for w in WHEELS}
    for rel, src in copies.items():
        dst = os.path.join(APP_DIR, *rel.split("/"))
        if not os.path.isfile(dst): problems.append(("missing copy", rel, f"copy {os.path.relpath(src, ROOT)}"))
        elif _read(dst) != _read(src): problems.append(("stale copy", rel, f"differs from {os.path.relpath(src, ROOT)}"))
    for rel, body in pages.items():
        dst = os.path.join(APP_DIR, rel)
        if not os.path.isfile(dst): problems.append(("missing page", rel, "render it"))
        elif _read(dst) != body: problems.append(("stale page", rel, "differs from tools/browser_app_template.html as rendered"))
        for r in _local_refs(body):
            if not os.path.exists(os.path.normpath(os.path.join(APP_DIR, r.split("?")[0].split("#")[0]))):
                problems.append(("broken reference", rel, r))
    for rel, (name, sha, _url) in wheels.items():
        dst = os.path.join(APP_DIR, "wheels", name)
        if not os.path.isfile(dst): problems.append(("missing wheel", rel, "run with --fetch-wheels"))
        elif _sha256(_read(dst)) != sha: problems.append(("wheel hash mismatch", rel, f"want sha256 {sha}"))
    for f in HAND_EDITED:
        if not os.path.isfile(os.path.join(APP_DIR, f)): problems.append(("missing file", f, "hand-edited; restore it from git"))
    known = set(copies) | set(pages) | set(wheels) | set(HAND_EDITED)
    if os.path.isdir(APP_DIR):
        for dp, _dn, fn in os.walk(APP_DIR):
            for f in fn:
                rel = os.path.relpath(os.path.join(dp, f), APP_DIR).replace(os.sep, "/")
                if rel not in known and f != ".DS_Store": problems.append(("stray file", rel, "not part of the browser build"))
    return problems, copies, pages

def _managed(rel):
    """Stray files the sync may delete by itself: old copies, pages and wheels, never anything else."""
    return (rel.endswith((".py", ".html")) and "/" not in rel) or rel.split("/")[0] in ("sample_data", "anomaly_data", "wheels")

def sync(fetch_wheels):
    problems, copies, pages = compare()
    for kind, rel, _ in problems:
        dst = os.path.join(APP_DIR, *rel.split("/"))
        if kind in ("missing copy", "stale copy"):
            os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copyfile(copies[rel], dst); print("copied ", rel)
        elif kind in ("missing page", "stale page"):
            with open(dst, "wb") as f: f.write(pages[rel])
            print("rendered", rel)
        elif kind == "stray file" and _managed(rel):
            os.remove(dst); print("removed ", rel)
        elif kind in ("missing wheel", "wheel hash mismatch") and fetch_wheels:
            name, sha, url = next(w for w in WHEELS if f"wheels/{w[0]}" == rel)
            with urllib.request.urlopen(url, timeout=60) as r: body = r.read()
            if _sha256(body) != sha: raise SystemExit(f"{name}: downloaded sha256 {_sha256(body)} != pinned {sha}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f: f.write(body)
            print("fetched ", rel)
    left, _, _ = compare()
    for kind, rel, detail in left: print(f"NOT FIXED  {kind}: {rel} ({detail})")
    return 1 if left else 0

def verify_cdn():
    bad = 0
    for f, want in STLITE_SRI.items():
        with urllib.request.urlopen(f"{STLITE_BUILD}/{f}", timeout=60) as r: got = _sri(r.read())
        print(("ok   " if got == want else "DIFF ") + f, got); bad += got != want
    with urllib.request.urlopen(f"{STLITE_BUILD}/stlite.js", timeout=60) as r: js = r.read().decode("utf-8")
    statics = sorted(set(re.findall(r'from\s+"\./([^"]+\.js)"', js)))
    pinned = sorted(f for f in STLITE_SRI if f.endswith(".js") and f != "stlite.js")
    print("stlite.js static imports:", statics, "| pinned:", pinned); bad += statics != pinned
    return 1 if bad else 0

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 if docs/app/ is out of step")
    ap.add_argument("--fetch-wheels", action="store_true", help="download a missing pinned wheel from PyPI")
    ap.add_argument("--verify-cdn", action="store_true", help="check the stlite SRI pins against the CDN")
    a = ap.parse_args()
    if a.verify_cdn: return verify_cdn()
    if a.check:
        problems, copies, pages = compare()
        for kind, rel, detail in problems: print(f"FAIL {kind}: docs/app/{rel} ({detail})")
        if problems:
            print(f"{len(problems)} problem(s). Run: python tools/sync_browser_apps.py"
                  + (" --fetch-wheels" if any("wheel" in p[0] for p in problems) else ""))
            return 1
        print(f"OK docs/app/ matches: {len(copies)} byte-identical copies, {len(pages)} rendered pages, "
              f"{len(WHEELS)} pinned wheels, stlite {STLITE_VERSION}")
        return 0
    return sync(a.fetch_wheels)

if __name__ == "__main__":
    sys.exit(main())
