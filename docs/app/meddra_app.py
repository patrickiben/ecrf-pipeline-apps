# meddra_app.py -- INDEPENDENT program: MedDRA auto-coding of verbatim AE terms.
#
# READ THIS FIRST (for whoever maintains this file):
#   * This is ONE of two separate programs. The other is phi_app.py. They do NOT
#     import each other and share NO module. The small helpers near the bottom of
#     this header (_have, _col, load_domains) are DELIBERATELY DUPLICATED in
#     phi_app.py. Do not "refactor" them into a shared pipeline.py: a shared
#     module is a coupling point that would let a retrain of one head silently
#     change the other's behavior, and the two heads are validated as separate
#     computer-system scopes with separate audit trails. Duplication is the
#     price of that independence, and it is intentional.
#   * This program codes verbatims ONLY. It never opens a free-text comment
#     column and never flags PHI -- that is phi_app.py's job, with its own audit.
#     The pre-flight panel at the bottom enforces this by listing exactly the one
#     verbatim column it will read and nothing else.
#   * No safety/DLT logic, no temporal window, no PDF/bounding-box path, no
#     negation feature. The coding context output of Tier 3 here is an ambiguity
#     scalar, not a negation probability; the gate is a single threshold on the
#     re-rank score.
#   * Hosted-demo safety mode: with ECRF_HOSTED=1 set (or the Streamlit secret
#     hosted = true) every data input (uploaders, folder path, .asc folder,
#     models dir) is locked to the bundled synthetic cut in sample_data/ and
#     outputs go to a per-session temp folder. Nothing set means the normal local
#     behavior. See _hosted().
#
# WHAT IT DOES, TIER BY TIER (the chain is the product; the weights are
# swappable underneath it -- see the [SI]/[RM] discipline in the banner/audit):
#   Tier 1 intake   -> align rows to participants; copy the verbatim through
#                      UNCHANGED (Tier 2 must measure closeness to what the site
#                      actually typed, so rewriting here would corrupt it).
#   Tier 2 Needle3  -> embed the verbatim to a UNIT vector (Cactus Needle3:
#                      3072-dim, measured), HNSW inner-product search -> top-k
#                      candidates + cosine.
#                      Because stored vectors are unit-norm, the graph's cheap
#                      inner-product distance EQUALS cosine, so the search
#                      returns exact angular closeness. Stand-in: a lexical
#                      hashing bag-of-words + brute-force dot product, same
#                      output columns, but it CANNOT reproduce semantic
#                      mappings (e.g. a colloquial verbatim -> the right PT)
#                      without the trained encoder -- that limit is tagged [SI],
#                      never hidden.
#   Tier 3 Laya     -> P(Unambiguous) as ONE extra re-rank feature. Stand-in:
#                      emits None, so Tier 4's row simply lacks that column; the
#                      gate still runs on the remaining named columns.
#   Tier 4 XGBoost  -> re-rank each candidate from Tier-2 cosine + two string
#                      distances + a body-system agreement flag (+ Tier-3
#                      ambiguity when present; real path: a trained binary
#                      booster scoring P(candidate is right)), then one gate:
#                      AUTO_COMMIT_TO_SDTM or FLAGGED_FOR_HUMAN_CODER. Writes
#                      AEDECOD/AEPTCD/AESOC/AECODCONF/AECODSTAT.
#
#   streamlit run meddra_app.py
#   stand-in path (runs anywhere):     pip install numpy pandas streamlit
#   real path: install the pinned runtimes (requirements.txt, real-path block) AND
#   put the trained artifacts in the models dir (layout below, steps in
#   eval/README.md). A tier flips to REAL only when its artifact LOADS; an
#   installed library with no artifact keeps that tier on its stand-in.

# stdlib only for the parts that must not depend on optional ML libs:
#   hashlib -> dictionary content hash for the audit (reproducibility)
#   zlib    -> STABLE token hash for the stand-in encoder (see _bow: this is the
#              one fix vs the prior version; Python's built-in hash() is salted
#              per-process, which made the stand-in non-reproducible across runs)
#   os/re/time -> file walking, column-name normalization, latency measurement
#   tempfile -> per-session output folder in hosted-demo mode (see _hosted)
#   importlib/json/platform/warnings -> binding the optional runtimes, reading
#              the re-ranker's feature contract, the per-OS engine file name
import hashlib, importlib, json, os, platform, re, sys, tempfile, time, warnings, zlib
import numpy as np, pandas as pd, streamlit as st

# --------------------------------------------------------------------------- #
# Air gap. Set BEFORE any optional runtime is imported: the Hugging Face client
# never reaches the network (every model loads from the models dir), and the
# Needle3 package's usage telemetry, which is ON by default, is switched off.
# setdefault, so an operator can still override one deliberately.
# --------------------------------------------------------------------------- #
for _k, _v in (("HF_HUB_OFFLINE", "1"), ("NEEDLE_TELEMETRY", "0"), ("DO_NOT_TRACK", "1")):
    os.environ.setdefault(_k, _v)

# --------------------------------------------------------------------------- #
# Runtime probe. We test each OPTIONAL library by attempting an import inside a
# try/except, WITHOUT importing it at module scope. Consequence: a missing
# optional dependency never crashes the app -- it only downgrades the
# corresponding tier to its deterministic stand-in. (The opposite failure --
# an artifact file present on disk but its runtime missing -- is a HARD STOP
# later, in _guard_artifacts; we never silently substitute a stand-in for a
# model the operator believes is loaded, because that would corrupt the review
# and the audit.)
# --------------------------------------------------------------------------- #
def _have(m):
    try: __import__(m); return True
    except Exception: return False
def _mod(m, *attrs):
    """Import an OPTIONAL runtime and BIND it, or return None. The module must also
    expose the API this file calls, so an unrelated package that shares the import
    name (PyPI's 'needle' is a CSS-testing tool) or an empty stub cannot pass as the
    model. Every attribute check sits INSIDE the try: some are lazy and import more
    code (laya.load pulls in torch), and hasattr() only catches AttributeError."""
    try:
        mod = importlib.import_module(m)
        return mod if all(hasattr(mod, a) for a in attrs) else None
    except Exception: return None
needle  = _mod("needle", "Needle")
hnswlib = _mod("hnswlib", "Index")
# Laya's own import is torch-free by design: torch and transformers load only when
# a checkpoint does. A bare `import laya` therefore passes without them, and the
# first real call would crash, so both are probed explicitly here.
laya    = _mod("laya", "load") if (_have("torch") and _have("transformers")) else None
xgboost = _mod("xgboost", "Booster", "DMatrix")
HAVE = {"needle": needle is not None, "hnswlib": hnswlib is not None, "laya": laya is not None,
        "xgboost": xgboost is not None, "pyreadstat": _have("pyreadstat")}
# A tier is REAL only when its runtime is installed AND its trained artifact has
# LOADED from the models dir (load_real, called once the sidebar names the dir).
# An importable library alone never flips the banner: until then every tier is
# its stand-in. Coding Tier 2 needs BOTH the embedder (needle) and the graph index
# (hnswlib), because a real embedder with no index (or vice versa) cannot serve
# the same contract.
REAL_T2 = REAL_T3 = REAL_T4 = False
_agent = _router = _coder = None

# --------------------------------------------------------------------------- #
# Models-dir CONVENTION (one folder, copied onto the air-gapped machine):
#   needle3/needle3.cact  + needle3/libneedle.so (.dylib macOS, .dll Windows)
#                                  Tier 2: Cactus Needle3 weights + native engine
#   laya/                          Tier 3: Laya English checkpoint (model.safetensors,
#                                  rl_agent_config.json, tokenizer/, encoder/)
#   laya_calibration_coding.json   Tier-3 temperatures fitted for THIS head's question
#   meddra_coder.json              Tier 4: trained re-ranker (XGBoost booster) ...
#   meddra_coder.meta.json         ... and its feature contract (checked, see below)
#   index_cache/                   written BY the app: the embedded dictionary, so a
#                                  full release is embedded once, not on every run
# eval/README.md says how each file is built. Nothing is downloaded at run time.
# --------------------------------------------------------------------------- #
ART_NEEDLE   = os.path.join("needle3", "needle3.cact")
ART_LAYA     = os.path.join("laya", "model.safetensors")
ART_LAYA_CAL = "laya_calibration_coding.json"
ART_CODER    = "meddra_coder.json"
RERANK_POOL  = 10    # real Tier 4 re-ranks this many retrieved terms, then keeps the top 3
def _engine_file():
    return {"Darwin": "libneedle.dylib", "Windows": "libneedle.dll"}.get(platform.system(), "libneedle.so")
def _sha_file(p, n=16):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()[:n]

# --------------------------------------------------------------------------- #
# Reviewer-set STARTING values. These are not magic constants the audit hides:
# whatever the slider ends at is written to audit_log.csv with the run, so a
# run is reproducible from its audit alone and the operating point is a logged
# decision, not a value buried in code.
# --------------------------------------------------------------------------- #
DEF_CODE_GATE = 0.88     # Tier-4 auto-commit gate (a validation-selected
                         # operating point; the build default, editable in UI)
# The verbatim source column is matched by NAME SYNONYM, never by file name, so
# the same program works whether the term lives in ae.csv, a custom domain, or a
# vendor dump that spells it differently. Add to this list for a study with an
# unusual header -- that is the ONLY place column naming is configured.
AETERM_SYNONYMS = ["AETERM","VERBATIM","AE_TERM","REPORTED_TERM"]

# --------------------------------------------------------------------------- #
# Hosted-demo safety mode. ON when the environment variable ECRF_HOSTED=1 is set
# or the Streamlit secret "hosted = true" exists (.streamlit/secrets.toml on a
# server you run; the in-browser pages set ECRF_HOSTED=1). A public demo must never take in real data, so in this
# mode every input that could bring data in (the uploaders, the folder path, the
# models dir and, in the coding app, the .asc folder) is DISABLED in the UI and
# its value is also OVERWRITTEN in code: a disabled widget only stops the
# browser, and a crafted client could still send a value, so it is never
# trusted. The bundled synthetic cut is forced, outputs go to a per-session
# server temp folder (never a path a visitor typed), a banner says so on every
# rerun, and the audit records hosted_mode=true. With nothing set (the local
# default) the app behaves exactly as before; the audit only gains
# hosted_mode=false. Duplicated in each app on purpose (no shared module, same
# rule as _have/_col).
# The switch fails CLOSED. Any ECRF_HOSTED or hosted value other than empty, 0,
# false, no or off turns it on (a typo such as "on" or hosted = 1.0 locks the
# demo instead of opening it), and so does a secrets file that exists but does
# not load (hosted = True with a capital T, a stray bad line): Streamlit only
# logs that parse error on the server, so failing open would leave a public app
# unlocked with nothing on the page to show it. The deploy step in README.md is
# to open the app and confirm the banner.
# --------------------------------------------------------------------------- #
HOSTED_BANNER = ("Public demo: synthetic data only. Do not enter or upload real patient data. "
                 "Run locally for real data.")
_HOSTED_OFF = ("", "0", "false", "no", "off")   # the ONLY values that leave a switch off
# In-browser build (stlite on Pyodide, served from docs/app/ on GitHub Pages): sys.platform is
# "emscripten" there and nowhere else. The flag only rewords text that would be wrong in a browser
# tab ("air-gapped", "nothing leaves the machine", the "Wrote <folder>" message and the Output-folder
# help); a local run is unchanged.
IN_BROWSER = sys.platform == "emscripten"
RUNS_WHERE = "runs in this browser tab" if IN_BROWSER else "air-gapped"
OUT_HELP_BROWSER = ("In this in-browser build the folder lives in the tab's memory, not on your disk, and is "
                    "gone when the tab closes. Save results with the download buttons.")
def _hosted():
    if os.environ.get("ECRF_HOSTED","").strip().lower() not in _HOSTED_OFF: return True
    # load_if_toml_exists() is asked FIRST (it returns False rather than raising when no
    # secrets file loads, the usual local case) because older Streamlit releases also draw
    # an st.error box when st.secrets.get misses the file, which would change the local
    # default view. The try/except covers any other loader failure.
    try:
        if st.secrets.load_if_toml_exists():
            # Streamlit copies root-level secrets into os.environ OVER the host's own value,
            # so an ECRF_HOSTED secret could quietly undo a host-set ECRF_HOSTED=1: the key
            # being there at all counts as on.
            if "ECRF_HOSTED" in st.secrets: return True
            return str(st.secrets.get("hosted", "")).strip().lower() not in _HOSTED_OFF
    except Exception: pass
    # Nothing loaded: local mode ONLY when no secrets file or folder exists at all. One that
    # exists but did not load fails closed (banner shown, inputs locked) instead of open.
    try: return any(os.path.exists(p) for p in st.get_option("secrets.files"))
    except Exception: return True

# ============================ IMPORT LAYER ============================
# The ONLY place this program touches the outside world. It reads (a) domain
# CSVs and (b) a MedDRA dictionary, and NOTHING else -- there is no built-in
# dataset, so every number downstream is computed from the operator's files.

def _col(df, *syn):
    """Return the first column of `df` whose NORMALIZED name (lowercased, all
    non-alphanumerics stripped) equals any synonym. Normalization is why
    'AE Term', 'ae_term', and 'AETERM' all match 'AETERM': EDC vendors and SDTM
    dumps name the same field different ways, and we refuse to assume one
    spelling. Returns None if nothing matches -- callers must handle None."""
    norm = [re.sub(r"[^a-z0-9]","",c.lower()) for c in df.columns]
    for s in syn:
        t = re.sub(r"[^a-z0-9]","",s.lower())
        if t in norm: return df.columns[norm.index(t)]
    return None

# The MedDRA parse is the expensive step on a full ~86k-term release, so it is
# cached by st.cache_data keyed on the source identity (_key). The heavy join
# therefore happens ONCE per distinct dictionary, not on every Streamlit rerun
# (Streamlit reruns the whole script on each widget interaction). max_entries=4
# keeps a few recent dictionaries in memory; show_spinner=False because the
# pre-flight panel already tells the operator what is loading.
@st.cache_data(show_spinner=False, max_entries=4)
def ingest_meddra(source_kind, source_ref, _key=None):
    """Build the active LLT->PT->HLT->HLGT->SOC lookup table the index is built
    over. Two accepted shapes, because CROs hold the dictionary either way:
      'flat_csv' : a pre-joined export, one row per lowest-level term with the
                   PT/HLT/HLGT/SOC columns alongside. Needs an LLT-name +
                   PT-name column; llt_code/pt_code/hlt_name/hlgt_name/soc_name
                   are detected by synonym if present.
      'asc_dir'  : the licensed ASCII release (llt.asc/pt.asc/hlt.asc/
                   hlgt.asc/soc.asc), pipe-delimited, with a `currency` flag;
                   we filter to active terms (currency=='Y') and join LLT->PT
                   on pt_code, PT->HLT on hlt_code, HLT->HLGT on hlgt_code,
                   HLGT->SOC on soc_code.
    The full MedDRA chain is LLT -> PT -> HLT -> HLGT -> SOC: related preferred
    terms are grouped into High Level Terms by anatomy, pathology, physiology,
    etiology or function; related HLTs in turn link to High Level Group Terms;
    and HLGTs group into System Organ Classes (by etiology, manifestation site
    or purpose). HLT/HLGT ride along on every candidate as EVIDENCE columns --
    they are never scored by Tier 4 and are not SDTM write-back fields (the
    write-back stays AEDECOD/AEPTCD/AESOC).
    Returns a DataFrame with columns llt_code, llt_name, pt_code, pt_name,
    hlt_name, hlgt_name, soc_name; codes optional, and any hierarchy level the
    source lacks is simply absent (the pre-flight panel shows exactly what
    loaded). RAISES with a precise message if the shape is unrecognized --
    never a silent empty table, because an empty dictionary would make every
    verbatim retrieve garbage and the operator must know why.
    _key is the cache identity; it is not used by the logic."""
    if source_kind == "asc_dir":
        # dtype=str + keep_default_na=False: the .asc codes are 8-digit strings
        # and must NOT be coerced to float (99019211.0) or have 'NA'-looking
        # tokens turned into NaN; low_memory=False avoids mixed-type warnings on
        # a large pipe-delimited read.
        rd = lambda n: pd.read_csv(os.path.join(source_ref,n), sep="|",
                                   dtype=str, keep_default_na=False, low_memory=False)
        llt, pt, soc = rd("llt.asc"), rd("pt.asc"), rd("soc.asc")
        # HLT/HLGT are the two intermediate levels of the chain. The licensed
        # release always ships hlt.asc/hlgt.asc; a partial .asc set is tolerated
        # -- an absent file simply means that level does not appear in the
        # candidates (pre-flight shows what loaded), and coding still writes
        # back AEDECOD/AEPTCD/AESOC.
        extra={}
        for n in ("hlt","hlgt"):
            if os.path.exists(os.path.join(source_ref,n+".asc")): extra[n]=rd(n+".asc")
        # Filter to ACTIVE terms only. The release carries superseded rows; an
        # inactive LLT must never be retrieved, or we would code to a retired
        # term. The currency column is named differently across releases, so we
        # detect it by synonym and skip the filter if absent (tolerant of a
        # pre-filtered export someone dropped in .asc form).
        for d in (llt,pt,soc,*extra.values()):
            c = _col(d,"currency","curr","active")
            if c: d.drop(d[d[c].str.upper()!="Y"].index, inplace=True)
        # Resolve the join keys by synonym on each file, then validate that the
        # minimum viable schema is present before joining -- a missing code
        # column would produce an empty inner join and a confusing "0 rows".
        l_code,l_name = _col(llt,"llt_code","lltcd"), _col(llt,"llt_name","llt")
        # QC FIX: the LLT file's pt_code LINK column must be selected and carried
        # into the join. The original code never selected it, so every .asc load
        # crashed with KeyError('pt_code') -- a latent bug that only surfaced once
        # the .asc path was actually exercised by the test harness.
        l_ptc = _col(llt,"pt_code","ptcd")
        p_ptc,p_pt,p_soc = _col(pt,"pt_code","ptcd"), _col(pt,"pt_name","pt"), _col(pt,"soc_code","soccd")
        s_soc,s_socn = _col(soc,"soc_code","soccd"), _col(soc,"soc_name","soc")
        if not (l_code and l_name and l_ptc and p_ptc and p_pt and s_soc and s_socn):
            raise ValueError("MedDRA .asc columns not recognized (need llt_code/"
                             "llt_name/pt_code on llt.asc; pt_code/pt_name/soc_code "
                             "on pt.asc; soc_code/soc_name on soc.asc). "
                             "Supply a flattened CSV instead.")
        # Inner joins on the codes: an LLT with no PT, or a PT with no SOC, is
        # dropped, because we cannot emit a complete AEDECOD/AEPTCD/AESOC triple
        # for a partial hierarchy row. reset_index so positional .iloc[i] lookups
        # downstream line up with the index rows we build next.
        # The PT->HLT link lives in pt.asc itself (its hlt_code column); the
        # HLT->HLGT link lives in hlt.asc. If either file or link is missing,
        # that level is skipped -- the chain degrades gracefully instead of
        # failing the whole dictionary load.
        p_hltc=_col(pt,"hlt_code","hltcd")
        pt_cols=[p_ptc,p_pt,p_soc]+([p_hltc] if p_hltc else [])
        pt_ren={p_ptc:"pt_code",p_pt:"pt_name",p_soc:"soc_code"}
        if p_hltc: pt_ren[p_hltc]="hlt_code"
        out=(llt[[l_code,l_name,l_ptc]].rename(
                 columns={l_code:"llt_code",l_name:"llt_name",l_ptc:"pt_code"})
             .merge(pt[pt_cols].rename(columns=pt_ren), on="pt_code", how="inner"))
        if "hlt" in extra and p_hltc:
            h=extra["hlt"]
            h_hc,h_hn = _col(h,"hlt_code","hltcd"), _col(h,"hlt_name","hlt")
            h_gl=_col(h,"hlgt_code","hlgtcd")
            if h_hc and h_hn:
                out=out.merge(h[[h_hc,h_hn]+([h_gl] if h_gl else [])].rename(
                    columns={h_hc:"hlt_code",h_hn:"hlt_name"}), on="hlt_code", how="inner")
        if "hlgt" in extra and "hlgt_code" in out.columns:
            g=extra["hlgt"]
            g_gc,g_gn = _col(g,"hlgt_code","hlgtcd"), _col(g,"hlgt_name","hlgt")
            if g_gc and g_gn:
                out=out.merge(g[[g_gc,g_gn]].rename(columns={g_gc:"hlgt_code",g_gn:"hlgt_name"}),
                              on="hlgt_code", how="inner")
        return (out.merge(soc[[s_soc,s_socn]].rename(columns={s_soc:"soc_code",s_socn:"soc_name"}),
                          on="soc_code", how="inner")).reset_index(drop=True)
    # source_kind == 'flat_csv': detect each logical column by synonym, then
    # normalize the header to the canonical names the rest of the program uses.
    df = source_ref.copy()
    ren = {"llt_code":_col(df,"llt_code","lltcd"),"llt_name":_col(df,"llt_name","llt","lowest_level_term"),
           "pt_code":_col(df,"pt_code","ptcd"),"pt_name":_col(df,"pt_name","pt","preferred_term"),
           "hlt_code":_col(df,"hlt_code","hltcd"),"hlt_name":_col(df,"hlt_name","hlt","high_level_term"),
           "hlgt_code":_col(df,"hlgt_code","hlgtcd"),"hlgt_name":_col(df,"hlgt_name","hlgt","high_level_group_term"),
           "soc_name":_col(df,"soc_name","soc","system_organ_class")}
    # LLT-name and PT-name are the irreducible minimum: without them there is no
    # term to index and no term to write back. Codes/SOC are optional (a
    # name-only dictionary still allows ranking, but see has_codes below -- it
    # forces routing, because a code without a number is not submission-grade).
    if not ren["llt_name"] or not ren["pt_name"]:
        raise ValueError("Flattened MedDRA CSV needs an LLT-name and PT-name column; found: "+", ".join(df.columns))
    keep=[v for v in ren.values() if v]
    return df.rename(columns={v:k for k,v in ren.items() if v})[keep].reset_index(drop=True)

def resolve_meddra(folder, asc_dir, uploaded_flat):
    """Apply a FIXED, documented precedence so the operator can predict which
    source wins when more than one is present (ambiguity here would mean two
    dictionaries silently competing). Order, highest first:
      1. an uploaded flattened CSV          (explicit operator intent)
      2. an explicit .asc folder path       (explicit operator intent)
      3. a meddra*.csv inside the cut folder (convention)
      4. a <folder>/meddra/ subdir of .asc  (convention)
      else -> raise, listing every location searched.
    Returns (meddra_df, human_readable_source_label); the label is written to
    the audit so a reviewer knows exactly which dictionary produced the codes."""
    if uploaded_flat is not None:
        # QC FIX: parse the upload HERE into a DataFrame. Streamlit's UploadedFile
        # has no .copy(), so handing it straight to ingest_meddra (whose flat
        # branch does source_ref.copy()) crashed with AttributeError on every
        # uploaded dictionary. _key still carries name+size for cache identity.
        return ingest_meddra("flat_csv", pd.read_csv(uploaded_flat),
                             _key=("flat",uploaded_flat.name,uploaded_flat.size)), "uploaded flattened CSV"
    if asc_dir:
        return ingest_meddra("asc_dir", asc_dir, _key=("asc",asc_dir)), f".asc release @ {asc_dir}"
    if folder:
        cand=[os.path.join(folder,f) for f in sorted(os.listdir(folder))
              if f.lower().endswith(".csv") and "meddra" in f.lower()]
        if cand:
            return ingest_meddra("flat_csv", pd.read_csv(cand[0]), _key=("flat",cand[0])), f"flattened CSV in cut folder ({os.path.basename(cand[0])})"
        asc=os.path.join(folder,"meddra")
        if os.path.isdir(asc) and os.path.exists(os.path.join(asc,"llt.asc")):
            return ingest_meddra("asc_dir", asc, _key=("asc",asc)), f".asc release in cut folder ({asc})"
    raise ValueError("No MedDRA source found. Searched: uploaded flattened CSV, the "
                     ".asc folder path, meddra*.csv in the cut folder, and a meddra/ subdir.")

# Data files are CSV or SAS .sas7bdat (SDTM/ADaM dumps). A file named *meddra* is
# reference data for the dictionary, never a domain -- excluded here so it is handled only by
# resolve_meddra (one source of truth).
SAS_EXT = ".sas7bdat"
def _is_data_file(name):
    n=name.lower()
    return (n.endswith(".csv") or n.endswith(SAS_EXT)) and "meddra" not in n
def _read_table(p):
    """Read one domain table from CSV or SAS .sas7bdat into a DataFrame. SAS support is
    OPTIONAL: pyreadstat is probed, never imported at module scope (same discipline as the ML
    runtimes), so CSV-only users need nothing extra. A missing runtime with a SAS file present
    raises a clear error -- we never silently skip a data file, because that would be a coverage
    gap and an unexplained hole in what got coded."""
    if str(p).lower().endswith(SAS_EXT):
        if not HAVE.get("pyreadstat", False):
            raise ValueError("SAS .sas7bdat input needs 'pyreadstat' (pip install pyreadstat). "
                             "Install it, or export the table to CSV.")
        import pyreadstat
        df,_meta = pyreadstat.read_sas7bdat(p)
        return df
    return pd.read_csv(p)
def load_domains(folder=None, uploads=None):
    """Read every data file (CSV or SAS .sas7bdat) that is NOT a MedDRA file, keyed by filename
    stem (ae.csv / ae.sas7bdat -> 'ae', pr.csv -> 'pr'). Domain NAMES are irrelevant -- the
    verbatim column is located by synonym inside whatever loaded, not by file. This is what lets
    the same program code terms from a non-'ae' domain if a study stores them elsewhere."""
    doms={}; paths=[]
    if folder:
        paths += [os.path.join(folder,f) for f in sorted(os.listdir(folder)) if _is_data_file(f)]
    for u in (uploads or []):
        if _is_data_file(u.name): paths.append(u)
    for p in paths:
        name=os.path.basename(p) if isinstance(p,str) else p.name
        # re.sub strips any suffix after the first '.' or '_' so 'ae_2026.csv' and 'ae.final.sas7bdat'
        # both key to 'ae'; keeps the dict small and stable.
        doms[re.sub(r"[_.].*$","",name.lower()).strip()] = _read_table(p)
    return doms

# ============================ TIER 1 ============================
# CONSUMES: the loaded domain frames + the operator's verbatim-column choice.
# EMITS:    the verbatim rows to code, each carrying USUBJID + a row key so the
#           coded output can be joined back to its source row.
# INVARIANT: Tier 1 NEVER rewrites the verbatim. The string Tier 2 measures
#           closeness against is exactly the bytes the site entered.
def verbatim_candidates(domains):
    """All (domain, column) pairs whose header matches an AETERM synonym. We
    return the LIST so the operator can SEE and CHOOSE which column the coding
    head reads -- never an automatic guess. A wrong auto-pick (e.g. coding a
    comment column because it happens to be named similarly) would silently
    produce garbage codes, so the choice is surfaced in the UI."""
    out=[]
    for d,df in domains.items():
        c=_col(df,*AETERM_SYNONYMS)
        if c: out.append((d,c))
    return out

def _row_key(r,i):
    """Row key for join-back: the first NON-MISSING of AESEQ/ID, else the 1-based
    row number. QC FIX: this is not r.get("AESEQ", ...) because Series.get() only
    falls back to its default when the COLUMN is absent -- a present-but-NaN value
    would leak into KEY and break the join-back on ae_coded.csv, so we test
    pd.notna explicitly."""
    for c in ("AESEQ","ID"):
        if c in r.index and pd.notna(r[c]): return r[c]
    return int(i)+1

def collect_verbatims(domains, domain, col):
    """Pull verbatim rows from the ONE chosen (domain, column). Keys are carried
    through (USUBJID + AESEQ if present and non-missing, else ID, else the 1-based
    row number) so ae_coded.csv is joinable back to the source. Blank/NaN
    verbatims are dropped -- there is nothing to code, and an empty string would
    retrieve a meaningless nearest neighbor. NOTE: `domain`/`col` arrive from
    splitting the selectbox option string; the option format here ('{d} :: {c}')
    and the split separator in the UI MUST match, or this unpacks wrong -- see
    the UI section comment."""
    df=domains[domain]; rows=[]
    for i,r in df.iterrows():
        v=r[col]
        if pd.isna(v) or not str(v).strip(): continue
        rows.append(dict(SOURCE_DOMAIN=domain, ROW=int(i)+1, USUBJID=r.get("USUBJID"),
                         KEY=_row_key(r,i), VERBATIM=str(v)))
    return pd.DataFrame(rows)

# ============================ TIER 2 ============================
# CONSUMES: a verbatim string (coding) + the dictionary (to build the index).
# EMITS:    candidates[] each with LLT/PT/PT_CODE/SOC + cosine in [0,1].
# CONTRACT: Tier 2 PROPOSES and MEASURES; it decides nothing. The decision is
#           Tier 4's. The two real sub-jobs (embed + graph search) share one
#           model family; the stand-in keeps the SAME output columns with a
#           lexical encoder and no graph, which is exact-but-slow at demo scale
#           and semantically-blind -- that blindness is the documented limit.
def _bow(t, dim=384):
    """[SI] coding encoder: hashing bag-of-words, L2-normalized to a 384-dim
    UNIT vector -- the same unit-norm property the real encoder's vectors have
    (Needle3's are 3072-dim; the width does not matter to the contract), so the
    downstream cosine math (dot product of unit vectors) is identical and the
    tier boundary holds either way.
    DETERMINISM FIX (the one behavior change vs the prior version): token->bucket
    uses zlib.crc32, NOT Python's built-in hash(). hash() of a str is salted
    per-process (PYTHONHASHSEED), so the same verbatim could map to different
    buckets on two runs -> different vectors -> different cosines -> possibly a
    different AUTO/FLAGGED status. That breaks the audit's reproducibility
    claim. crc32 is stable across processes and platforms, so a stand-in run is
    now bit-reproducible. This is NOT a semantic model: it cannot map a
    colloquial verbatim to the right PT (no embedding space); install the real
    weights to get semantic retrieval. The [SI] tag in the banner/audit says so.
    Empty/whitespace-only input -> zero vector -> norm 0 -> we return the zero
    vector rather than divide by zero; its cosine against anything is 0, which
    correctly routes (a blank verbatim should never auto-code)."""
    v=np.zeros(dim)
    for tok in str(t).lower().split(): v[zlib.crc32(tok.encode())%dim]+=1.0
    n=np.linalg.norm(v); return v/n if n>0 else v

# The real embedder is loaded ONCE per process by load_real (cached), before any
# verbatim is processed; if its artifact is absent, _agent stays None and every
# Tier-2 call takes the stand-in branch. We do NOT lazy-load inside the request
# path, because a slow first-call load would look like a hang.
@st.cache_resource(show_spinner="Embedding the dictionary with Needle3 (once per dictionary)...")
def _t2_text(s):
    """The string Needle3 embeds, for a dictionary term and a verbatim alike: lower-cased,
    like every other matcher in this file (_bow, _lev, _jaro). Needle3's embedding is
    case-sensitive (measured: "insomnia" vs "Insomnia" scores 0.948, below several
    unrelated terms), and verbatims are typed in any case. Only the embedded copy is
    folded; the verbatim itself still reaches the output byte for byte."""
    return str(s).lower()
def _real_index(names, cache_dir, weights_tag):
    """Embed every dictionary term with Needle3 and build the HNSW graph, ONCE per
    (dictionary content, weights) pair: cached in memory for the process and on disk
    under models_dir/index_cache, because a full release takes tens of minutes to
    embed on a CPU. add_items runs single-threaded so the graph (and therefore every
    retrieval) is identical run to run; multi-threaded insertion can reorder it."""
    key = hashlib.sha256("\n".join(names).encode()).hexdigest()[:16] + "_" + weights_tag
    vf, gf = os.path.join(cache_dir, key + ".npy"), os.path.join(cache_dir, key + ".hnsw")
    if os.path.isfile(vf) and os.path.isfile(gf):
        V = np.load(vf); idx = hnswlib.Index(space="ip", dim=V.shape[1]); idx.load_index(gf, max_elements=len(V))
    else:
        V = np.vstack([np.asarray(_agent.embed(s), np.float32) for s in names])
        V /= np.linalg.norm(V, axis=1, keepdims=True)   # enforce unit-norm so ip == cosine
        idx = hnswlib.Index(space="ip", dim=V.shape[1])
        idx.init_index(max_elements=len(V), ef_construction=200, M=32)
        idx.add_items(V, np.arange(len(V)), num_threads=1)
        try: os.makedirs(cache_dir, exist_ok=True); np.save(vf, V); idx.save_index(gf)
        except OSError: pass                        # read-only models dir: memory only
    idx.set_ef(64); return V, idx
def t2_index(meddra):
    """Build the retrieval index ONCE over the dictionary's LLT strings, before
    any verbatim is processed (building per-query would be O(dictionary) every
    time). Returns (V, idx):
      V   = the matrix of unit vectors, row i aligned to meddra row i. This is
            the COMMON contract both paths return -- the caller dots a query
            against V (stand-in) or queries idx (real); either way row i of the
            result maps to meddra.iloc[i], so candidate assembly is shared.
      idx = the HNSW graph (real) or None (stand-in).
    Real path: embed every llt_name (lower-cased, _t2_text) to a unit vector, load into an hnswlib graph
    with space='ip' (inner product). Because the vectors are L2-normalized, ip
    distance == 1 - cosine, so the cheap graph search returns EXACT angular
    closeness -- this is why we can use the cheaper metric and still report
    cosine. ef_construction/M are BUILD knobs (graph quality/size); set_ef(64)
    is the QUERY-BREADTH knob (larger = more exhaustive = higher recall, slower);
    these tune the speed/recall trade and do NOT change what the tier emits.
    Stand-in path: stack the _bow vectors; no graph (a brute-force dot product
    over V is exact and fine at demo scale; on a full 86k dictionary it is slow,
    which is itself a reason to install the real index)."""
    if REAL_T2:
        return _real_index(tuple(_t2_text(x) for x in meddra["llt_name"]), _agent._index_cache, _agent._weights_tag)
    return np.vstack([_bow(s) for s in meddra["llt_name"]]), None

def t2_coding(s, meddra, V, idx, k=3):
    """Retrieve the k nearest dictionary terms for verbatim `s` and attach the
    cosine. Real: embed s to a unit vector, HNSW knn (distances are 1-cosine, so
    cos = 1 - dist). Stand-in: dot s's _bow vector against V (both unit-norm, so
    the dot IS the cosine), take the top-k by value. Both branches produce the
    SAME row shape, which is the whole point of the tier boundary: Tier 4 cannot
    tell which path ran except via the [SI]/[RM] tag.
    Emits a DataFrame with columns rank, llt_code, LLT, PT, PT_CODE, SOC, cosine.
    cosine is rounded to 4dp for display/audit stability. PT_CODE/SOC may be
    None if the dictionary was name-only -- Tier 4 handles that via has_codes.
    Proposes and measures; decides nothing (no threshold is applied here)."""
    if REAL_T2:
        # The trained re-ranker (when loaded) re-orders a wider pool and keeps the top k.
        kk=min(max(k, RERANK_POOL if REAL_T4 else k), len(V))
        q=np.asarray(_agent.embed(_t2_text(s)),np.float32); q/=np.linalg.norm(q)
        lab,dist=idx.knn_query(q.reshape(1,-1),k=kk); order=lab[0]; cos=1.0-dist[0]
    else:
        cos=V@_bow(s); order=np.argsort(-cos)[:k]; cos=cos[order]
    rows=[]
    for r,i in enumerate(order):
        # HLT/HLGT ride along as evidence columns (the full hierarchy path a
        # reviewer sees next to each candidate); they are absent -- None -- when
        # the dictionary source did not carry those levels.
        rows.append(dict(rank=r+1,
            llt_code=meddra["llt_code"].iloc[i] if "llt_code" in meddra else None,
            LLT=meddra["llt_name"].iloc[i], PT=meddra["pt_name"].iloc[i],
            PT_CODE=meddra["pt_code"].iloc[i] if "pt_code" in meddra else None,
            HLT=meddra["hlt_name"].iloc[i] if "hlt_name" in meddra else None,
            HLGT=meddra["hlgt_name"].iloc[i] if "hlgt_name" in meddra else None,
            SOC=meddra["soc_name"].iloc[i] if "soc_name" in meddra else None,
            cosine=round(float(cos[r]),4)))
    return pd.DataFrame(rows)

# ============================ TIER 3 ============================
# CONSUMES: a verbatim string. EMITS: P(Unambiguous) (or None in the stand-in).
# CONTRACT: Tier 3 is its own hop because vector similarity (Tier 2) is blind to
#           sentence intent. "X" and "patient denies X" retrieve the same term at
#           the same cosine; only a separate sentence-level reading separates
#           them, and it must be separate so the separation is a READABLE NUMBER
#           Tier 4 can weight, not a hidden weight inside the retrieval.
# The checkpoint is loaded ONCE per process (load_real, cached) so the model load
# is not paid per request; a cold load inside the loop would dominate the latency
# and look like a stall. ONE local English checkpoint is loaded, not Laya's
# Router: the router picks among three checkpoints by language and sends short
# English strings to the multilingual one, which ships with no fitted
# temperatures. CODING_SCHEMA declares the one question the coding head asks; its
# temperatures (laya_calibration_coding.json) are fitted for exactly this wording,
# so editing the text means refitting them (eval/README.md).
CODING_SCHEMA={"unambiguous":{"type":"noul",
    "instructions":"Does this adverse-event text report one specific medical problem that the participant actually had?",
    "criteria":{"false":"negated, denied, ruled out, uncertain, or several problems","true":"one problem the participant had"}}}
def t3_coding_batch(texts):
    """Tier 3 for many verbatims in one batched pass (about half the per-item cost
    of one call each). Real: P(true) of the noul question, calibrated by the fitted
    temperatures. Stand-in: None for every item (see t3_coding)."""
    if not REAL_T3: return [dict(P_UNAMBIGUOUS=None) for _ in texts]
    out=_router.predict_batch([str(t) for t in texts], CODING_SCHEMA)
    return [dict(P_UNAMBIGUOUS=round(float(o["answers"]["unambiguous"]["noul"]),4)) for o in out]
def t3_coding(s):
    """Coding context scalar. Real: Laya answers CODING_SCHEMA on s -> a calibrated
    P(Unambiguous) in [0,1] (one non-autoregressive pass, no text generated, so
    the output is deterministic and the number is calibratable). Stand-in: emits
    None -- the lexical build has no sentence-intent model, and we refuse to fake
    a probability. Consequence downstream: Tier 4's feature row simply OMITS this
    column; the gate still runs on the remaining named columns. This is a
    documented limit of the stand-in, not a silent substitution of a guess."""
    return t3_coding_batch([s])[0]

# ============================ TIER 4 ============================
# CONSUMES: ONLY the named columns from Tiers 1-3 (cosine, the ambiguity scalar,
#           and the string distances/SOC flag computed right here). It NEVER
#           re-reads the verbatim as tokens -- that is the chain's defining
#           constraint and the reason a decision is a row of readable numbers.
# EMITS:    a re-ranked candidate table + a status string.
# CONTRACT: this is where the chain pays off. Because the decision is a function
#           of readable upstream numbers, the THRESHOLD is a parameter the
#           operator moves in the sidebar (and the audit records), not a weight
#           baked into a model. Moving it does not require retraining.
def _lev(a,b):
    """Levenshtein SIMILARITY = 1 - edit_distance(a,b)/max(len a, len b), in
    [0,1]. A Tier-4 string feature computed from the PRESERVED verbatim vs a
    candidate LLT -- i.e. Tier 4 derives this scalar itself from two strings it
    was handed, it does not receive tokens. Classic DP over the edit-distance
    recurrence (insert/delete/substitute); O(len a * len b), fine for short
    terms. Returns 0.0 if either string is empty (no meaningful similarity)."""
    a,b=str(a).lower(),str(b).lower()
    if not a or not b: return 0.0
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur=[i]
        for j,cb in enumerate(b,1): cur.append(min(prev[j]+1,cur[j-1]+1,prev[j-1]+(ca!=cb)))
        prev=cur
    return 1.0-prev[-1]/max(len(a),len(b))
def _jaro(a,b):
    """Jaro-Winkler similarity in [0,1] -- the SECOND Tier-4 string feature,
    complementing edit distance by rewarding shared characters within the match
    window and a common prefix (Winkler boost when Jaro>0.7). Two short terms
    can have identical edit distance but different Jaro-Winkler; carrying both
    gives the ranker two independent lexical signals. Returns 1.0 on exact match,
    0.0 if either is empty or no characters match."""
    a,b=str(a).lower(),str(b).lower()
    if a==b: return 1.0
    la,lb=len(a),len(b)
    if not la or not lb: return 0.0
    win=max(la,lb)//2-1; ma=[False]*la; mb=[False]*lb; m=0
    for i,ca in enumerate(a):
        for j in range(max(0,i-win),min(lb,i+win+1)):
            if not mb[j] and ca==b[j]: ma[i]=mb[j]=True; m+=1; break
    if not m: return 0.0
    k=0;tr=0
    for i in range(la):
        if ma[i]:
            while not mb[k]: k+=1
            if a[i]!=b[k]: tr+=1
            k+=1
    tr//=2; j=(m/la+m/lb+(m-tr)/m)/3; l=0
    while l<4 and a[l]==b[l]: l+=1
    return j+0.1*l*(1-j) if j>0.7 else j

# [SI] composite weights (sum to 1 by construction). These are the STAND-IN's
# declared blend; the REAL path is a TRAINED booster (XGBoost, binary:logistic,
# so its score reads as P(candidate is the right code)) learned from labeled
# examples (eval/README.md), not weights typed here. We
# keep the same four-term structure so the feature CONTRACT is identical either
# way -- only the weight source changes. soc_match is currently always 1 because
# this build does not infer a body-system context to compare against; a trained
# ranker would learn from that column when present, so we keep it in the row
# rather than dropping it (dropping a contract column would change Tier 4's
# input schema between stand-in and real, which is exactly what we avoid).
SI_W=[0.40,0.25,0.20,0.15]
def t4_coding(cands,s,gate,has_codes,amb):
    """Re-rank the retrieved candidates and gate. Per candidate the feature row
    = Tier-2 cosine + _lev + _jaro (both computed here from the preserved verbatim
    `s` and the candidate LLT) + the SOC agreement flag, blended by SI_W (sum=1);
    the Tier-3 ambiguity scalar `amb` is an EXTRA booster feature when present
    (None in the stand-in -> omitted, gate unaffected). The gate is a SINGLE
    threshold on the score: there is NO negation conjunct, because the coding
    context output here is ambiguity, not negation -- a negated/ambiguous verbatim
    is handled by the trained ranker pushing its score down via the ambiguity
    feature, not by a hard-coded if. has_codes=False (a name-only dictionary)
    FORCES routing regardless of score: AEPTCD without a number is not
    submission-grade, so we never auto-commit a code we cannot populate.
    Returns (cands_with_S, status, top_row); status is AUTO_COMMIT_TO_SDTM or
    FLAGGED_FOR_HUMAN_CODER, top_row is rank-1 (the candidate the status is for)."""
    lev=[round(_lev(s,r.LLT),4) for r in cands.itertuples()]
    jar=[round(_jaro(s,r.LLT),4) for r in cands.itertuples()]
    soc=[1]*len(cands)
    if REAL_T4:
        # Trained re-ranker: the feature row is built in the ORDER the booster's
        # contract file names (meddra_coder.meta.json), scored, re-ranked, and the
        # top 3 kept, so the export shape is the same as the stand-in's.
        booster,meta=_coder
        feat=dict(cosine=list(cands["cosine"]),lev=lev,jaro=jar,soc_match=soc,
                  p_unambiguous=[np.nan if amb is None else amb]*len(cands),ret_rank=list(cands["rank"]))
        X=np.array([[feat[f][i] for f in meta["features"]] for i in range(len(cands))],float)
        S=[round(float(v),4) for v in booster.predict(xgboost.DMatrix(X,feature_names=meta["features"]))]
        cands=(cands.assign(lev=lev,jaro=jar,soc_match=soc,S=S)
               .sort_values("S",ascending=False,kind="stable").head(3).reset_index(drop=True))
        cands["rank"]=range(1,len(cands)+1)
    else:
        S=[round(SI_W[0]*r.cosine+SI_W[1]*lv+SI_W[2]*ja+SI_W[3]*so,4)
           for r,lv,ja,so in zip(cands.itertuples(),lev,jar,soc)]
        cands=cands.assign(lev=lev,jaro=jar,soc_match=soc,S=S)
    top=cands.iloc[0]
    auto=(top.S>=gate) and has_codes
    return cands,("AUTO_COMMIT_TO_SDTM" if auto else "FLAGGED_FOR_HUMAN_CODER"),top

def _hierarchy(df):
    """The levels of the MedDRA chain this dictionary actually carries, e.g.
    'LLT > PT > HLT > HLGT > SOC'. Shown in pre-flight and written to the audit
    so a reviewer sees at a glance whether the hierarchy is complete or degraded
    (a source without hlt/hlgt columns still codes fine -- AEDECOD/AEPTCD/AESOC
    write-back does not depend on those levels)."""
    return " > ".join(L for L,c in (("LLT","llt_name"),("PT","pt_name"),("HLT","hlt_name"),
                                    ("HLGT","hlgt_name"),("SOC","soc_name")) if c in df.columns)

def _guard_artifacts(models_dir):
    """HARD STOP, never a silent fallback: if a trained artifact file exists in
    models_dir but the runtime that would load it is NOT installed, we refuse to
    run. Silently substituting a stand-in for a model the operator BELIEVES is
    loaded would corrupt both the review (they'd trust [SI] numbers as real) and
    the audit (which would record REAL because the file is there). The filenames
    below are a CONVENTION the operator must match when dropping real weights;
    an unexpected name is simply not guarded (it would just not be loaded)."""
    if not os.path.isdir(models_dir): return
    for art,libs in [(ART_CODER,("xgboost",)),(ART_NEEDLE,("needle","hnswlib")),(ART_LAYA,("laya",))]:
        miss=[l for l in libs if not HAVE.get(l,False)]
        if os.path.exists(os.path.join(models_dir,art)) and miss:
            st.error(f"{art} present but {', '.join(repr(m) for m in miss)} not installed (laya also needs "
                     f"torch and transformers). Install it or remove the artifact; the engine will NOT "
                     f"silently substitute a stand-in."); st.stop()

def _load_laya(d,cal):
    """laya.load with the fitted calibration file, if there is one. Laya warns when the
    file records a different checkpoint PATH; a models dir moves between machines by
    design, so a path-only mismatch is expected and dropped. A different checkpoint
    CONFIG means the temperatures were fitted for another model, so it is refused like
    any other artifact that cannot be used (the UI stops on it)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ag=laya.load(d,device="cpu",calibration=cal)
    for w in caught:
        m=str(w.message)
        if "Checkpoint config identity differs" in m:
            raise ValueError(f"{ART_LAYA_CAL} was fitted for a different Laya checkpoint (refit it, eval/README.md)")
        if "calibration was fitted for" not in m: warnings.warn_explicit(w.message,w.category,w.filename,w.lineno)
    return ag

def _artifact_stamp(models_dir):
    """The rest of load_real's cache key: size and mtime of each artifact it reads, so
    adding, replacing or removing a file is picked up on the next run instead of a
    stale load being served for the life of the process."""
    md=os.path.abspath(models_dir); out=[]
    for a in (ART_NEEDLE,os.path.join("needle3",_engine_file()),ART_LAYA,ART_LAYA_CAL,ART_CODER,ART_CODER.replace(".json",".meta.json")):
        try: st_=os.stat(os.path.join(md,a)); out.append((a,st_.st_size,st_.st_mtime_ns))
        except OSError: out.append((a,None,None))
    return tuple(out)

@st.cache_resource(show_spinner="Loading the real models from the models dir...")
def load_real(models_dir, stamp=None):
    """Load every trained artifact in models_dir whose runtime is installed, ONCE per
    process (st.cache_resource). Returns dict(T2,T3,T4,info,errors): None for a tier that
    runs its stand-in; info holds what loaded (file names + content hashes) for the audit;
    errors lists any artifact that is PRESENT but failed to load (the UI stops on it).
    Nothing here reaches the network: Needle3 gets explicit file paths (never its
    ~/.cache copy), Laya a local directory, and HF_HUB_OFFLINE is set at the top."""
    R=dict(T2=None,T3=None,T4=None,info={},errors=[]); md=os.path.abspath(models_dir)
    w,eng=os.path.join(md,ART_NEEDLE),os.path.join(md,"needle3",_engine_file())
    try:
        if needle and hnswlib and os.path.isfile(w) and os.path.isfile(eng):
            os.environ["NEEDLE3_LIB_PATH"]=eng          # the engine from the models dir, nowhere else
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")          # "no confidence head": this head only embeds
                ag=needle.Needle(weights=w)
            ag._weights_tag=_sha_file(w); ag._index_cache=os.path.join(md,"index_cache")
            R["T2"]=ag; R["info"]["needle3"]=f"needle3.cact sha256:{ag._weights_tag}"
    except Exception as e: R["errors"].append(f"{os.path.relpath(w,md)}: {type(e).__name__}: {e}")
    if R["T2"] is None and needle and hnswlib and os.path.isfile(w) and not os.path.isfile(eng):
        R["errors"].append(f"{ART_NEEDLE}: its engine {os.path.relpath(eng,md)} is missing")
    lp=os.path.join(md,ART_LAYA)
    try:
        if laya and os.path.isfile(lp):
            cal=os.path.join(md,ART_LAYA_CAL)
            R["T3"]=_load_laya(os.path.dirname(lp),cal if os.path.isfile(cal) else None)
            R["info"]["laya"]=(f"laya/ sha256:{_sha_file(lp)}; calibration "
                               +(f"{ART_LAYA_CAL} sha256:{_sha_file(cal)}" if os.path.isfile(cal) else "NONE (uncalibrated)"))
    except Exception as e: R["errors"].append(f"{os.path.relpath(lp,md)}: {type(e).__name__}: {e}")
    bp=os.path.join(md,ART_CODER)
    try:
        if xgboost and os.path.isfile(bp):
            b=xgboost.Booster(); b.load_model(bp)
            mp=bp.replace(".json",".meta.json"); meta=json.load(open(mp)) if os.path.isfile(mp) else None
            R["T4"]=(b,meta); R["info"]["coder"]=f"{ART_CODER} sha256:{_sha_file(bp)}"
    except Exception as e: R["errors"].append(f"{os.path.relpath(bp,md)}: {type(e).__name__}: {e}")
    return R

def _activate(R):
    """Point the tier functions at what load_real found. They read these module
    globals at call time, so the stand-in stays the default until this runs."""
    global _agent,_router,_coder,REAL_T2,REAL_T3,REAL_T4
    _agent,_router,_coder=R["T2"],R["T3"],R["T4"]
    REAL_T2,REAL_T3,REAL_T4=_agent is not None,_router is not None,_coder is not None

def _contract_error(R):
    """The re-ranker was trained on features from SPECIFIC upstream tiers; scoring
    stand-in cosines with a booster trained on Needle3 cosines would be a silent
    wrong answer. Returns a plain-language reason when the loaded tiers do not match
    the booster's contract file (or it has none), else None."""
    if R["T4"] is None: return None
    meta=R["T4"][1]
    if not meta: return f"{ART_CODER} has no {ART_CODER.replace('.json','.meta.json')} feature contract next to it."
    need=meta.get("requires",{})
    if need.get("T2") and R["T2"] is None: return "the re-ranker was trained on Needle3 retrieval, but no Needle3 artifact loaded."
    if need.get("T3") and R["T3"] is None: return "the re-ranker was trained with the Laya ambiguity scalar, but no Laya checkpoint loaded."
    q=hashlib.sha256(json.dumps(CODING_SCHEMA,sort_keys=True).encode()).hexdigest()[:16]
    if need.get("T3") and meta.get("tier3_question_sha") not in (None,q):
        return "the Tier-3 question text changed since the re-ranker was trained (refit it, eval/README.md)."
    return None

# ============================ UI ============================
# Layout order is deliberate: gather WHERE the data is (1), set the operating
# point + outputs (2), LOAD so the pre-flight panel can show what was actually
# read, then the verbatim selector (3) populated FROM the load, then the banner,
# then the pre-flight CONTRACT panel, then Run. The operator confirms the input
# contract BEFORE any compute, so a mis-pointed folder or a wrong verbatim column
# is caught on screen, not after a silent wrong answer.
st.set_page_config(page_title="Coding QC assist", layout="wide")
HOSTED = _hosted()   # after set_page_config: no Streamlit call may precede it
# Hosted: an uncaught exception shows a generic message, not a traceback with server
# paths (a crafted widget value can raise one). Process-wide, like the switch itself.
if HOSTED: st.set_option("client.showErrorDetails", "none")
st.title("🏷 Coding QC assist")
# In the browser only the [SI] stand-ins can run (see README), so the caption names those instead.
st.caption(("Tier 1 intake → Tier 2 lexical retrieval [SI] → Tier 3 off [SI] → Tier 4 weighted re-rank and gate [SI] · "
            if IN_BROWSER else "Tier 1 intake → Tier 2 Cactus Needle3 → Tier 3 Laya → Tier 4 XGBoost · ")
           + "codes verbatim AETERM only · " + RUNS_WHERE + " · no sample data in this file")
# Hosted banner on EVERY rerun, drawn before any st.stop() below can cut the page short.
if HOSTED: st.warning(HOSTED_BANNER, icon="🔒")

# Built-in, app-specific instruction manual (from USER_GUIDE.md §3), rendered as a
# collapsible panel so the working view stays clean but help is one click away.
_HELP_MD = """
**What this app does.** Proposes a MedDRA code (`LLT → PT → HLT → HLGT → SOC`) for each adverse-event verbatim, then either auto-commits it or routes it to a human coder. It reads only the one verbatim column you select; nothing else in your data is opened or modified.

**What it needs.** Domain CSVs with the terms to code, plus exactly **one** MedDRA dictionary.

### Step by step
1. **Point at your data** (sidebar 📂 1): type a cut-folder path and/or upload domain CSVs. Every `*.csv` except one named `*meddra*` loads as a domain; the verbatim column is found by name synonym inside whatever loads (`AETERM`, `VERBATIM`, `AE_TERM`, `REPORTED_TERM`).
2. **Provide the dictionary** in exactly one shape:
   - *Flattened CSV (recommended):* upload it, or drop a `meddra*.csv` in the cut folder to auto-find it. Needs an LLT-name + PT-name column; codes and SOC are detected by synonym when present.
   - *ASCII release (.asc):* give the folder with `llt.asc / pt.asc / hlt.asc / hlgt.asc / soc.asc`. Filtered to active terms (`currency == 'Y'`) and joined across the full chain; `hlt.asc`/`hlgt.asc` are optional.
3. **Set the operating point** (sidebar ⚖ 2): the Auto-commit gate slider (default **0.88**). Candidates scoring at/above it auto-commit; below it route to a human. The value you end at is written to the audit with the run.
4. **Confirm the input** (sidebar 🎯 3 + pre-flight panel): pick the verbatim column from the dropdown and check the panel: domains loaded, dictionary source + rows, detected columns, the Hierarchy chain this dictionary carries, and whether it has PT codes.
5. **Execute**: click 🚀 Execute MedDRA Auto-Coding. Results render on screen and write to the output folder (default `meddra_output`).

### The hierarchy
MedDRA groups related preferred terms into **High Level Terms (HLT)** by anatomy/pathology/physiology/etiology/function; HLTs link to **High Level Group Terms (HLGT)**; HLGTs group into **System Organ Classes (SOC)**. Every candidate carries the full `LLT → PT → HLT → HLGT → SOC` path as evidence columns.

### Reading ae_coded.csv
One row per candidate (top-3), so a coder sees the whole pre-populated list, not just the winner.

| Column | Meaning |
|---|---|
| `VERBATIM` | The term exactly as typed (never rewritten). |
| `rank` | 1 = top candidate; 2–3 are alternatives. |
| `AEDECOD` / `AEPTCD` | Preferred-term decode + code to write back. |
| `HLT`, `HLGT` | Evidence columns: the full path, never scored and not written back to SDTM. |
| `AESOC` | System Organ Class. |
| `cosine`, `lev`, `jaro`, `S` | The readable numbers the decision is made from. |
| `AECODSTAT` | `AUTO_COMMIT_TO_SDTM` (rank 1 only) or `FLAGGED_FOR_HUMAN_CODER`; ranks 2–3 are `ALT_CANDIDATE`. |

> A **name-only dictionary** (no PT codes) forces every verbatim to route to a human, because there is no code to write to `AEPTCD`. The pre-flight panel warns you up front.

### Stand-in vs real (`[SI]` / `[RM]`)
Without trained weights, Tiers 2–4 run as labeled deterministic stand-ins (`[SI]` in the banner and audit): coding retrieval is lexical, so semantically-gapped verbatims flag to a human rather than auto-code. Install the pinned real-path runtimes and put the trained artifacts in the **Models dir** (layout and build steps: `eval/README.md`); a tier flips to REAL only when its artifact loads, and the audit records which files loaded. Columns, gates and exports do not move. If an artifact file is present but its runtime is missing, the app stops rather than silently substituting a stand-in.

### Troubleshooting
- **"No MedDRA source found":** provide exactly one dictionary shape (upload CSV / set the .asc folder / name it `meddra*.csv` in the cut folder).
- **Everything routes to a human:** your dictionary is likely name-only (pre-flight says "Has PT codes → NO").
- **Verbatim column not detected:** rename it to `AETERM`, or add its spelling to `AETERM_SYNONYMS` at the top of this file.

### What this build does NOT do
No scanned-document path, no safety/DLT logic, no negation feature, nothing leaves the machine. Every proposed code needs a coder's review. What was measured, on synthetic data only, is in the [evaluation](https://patrickiben.github.io/ecrf-pipeline-apps/evaluation.html); the limits are in the [case study](https://patrickiben.github.io/ecrf-pipeline-apps/case-study.html).
"""
if IN_BROWSER: _HELP_MD = _HELP_MD.replace("nothing leaves the machine", "nothing you load is uploaded by the app")
with st.expander("📖 How to use this app"):
    st.markdown(_HELP_MD)

# ---- sidebar 1: WHERE the data is. Folder path AND/OR uploads are additive;
#      a meddra*.csv in the folder is treated as the dictionary, not a domain. ----
if HOSTED: st.sidebar.warning(HOSTED_BANNER, icon="🔒")
st.sidebar.header("📂 1. Point this at your data")
_SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
# Demo toggle: off by default; a link ending in ?demo=1 (e.g. a hosted demo) starts it on.
# Hosted mode: each data input below is disabled AND its value overwritten right after
# the widget (sample forced on, folder pinned to sample_data/, no uploads), because a
# disabled widget only stops the browser; a crafted client could still send a value.
_use_sample = st.sidebar.checkbox("Use the bundled synthetic sample data",
    value=(HOSTED or st.query_params.get("demo") == "1"), disabled=HOSTED,
    help="Fills the folder path with the synthetic demo cut shipped in ./sample_data/ (no real patients or licensed dictionary).")
if HOSTED: _use_sample = True
folder = st.sidebar.text_input("Cut folder path (domain CSVs)", value=(_SAMPLE_DIR if _use_sample else ""), disabled=HOSTED,
    help="Path to a folder of domain CSVs. Every *.csv here EXCEPT one named "
         "*meddra* is loaded as a domain; the verbatim column is found by synonym "
         "inside whatever loaded, not by file name. Leave blank to use uploads.")
if HOSTED: folder = _SAMPLE_DIR            # never trust a client-sent value in hosted mode
up_dom = st.sidebar.file_uploader("...or upload domain files (CSV or SAS .sas7bdat)",
    type=["csv","sas7bdat"], accept_multiple_files=True, disabled=HOSTED)
if HOSTED: up_dom = None
# The dictionary shape is an explicit radio so the operator states intent rather
# than the app guessing between a flat CSV and an .asc release.
st.sidebar.markdown("**MedDRA dictionary**: provide exactly one shape.")
kind = st.sidebar.radio("Source shape", ["Flattened CSV (recommended)","ASCII release (llt/pt/hlt/hlgt/soc.asc)"])
up_med=None; asc_dir=""
# Hosted mode: the radio stays live, but both dictionary inputs are disabled and
# blanked in code, so resolve_meddra falls back to the meddra_demo.csv it
# auto-finds in the forced sample folder.
if kind.startswith("Flattened"):
    up_med = st.sidebar.file_uploader("Upload flattened MedDRA CSV", type="csv", disabled=HOSTED,
        help="Needs an LLT-name + PT-name column; llt_code/pt_code/soc_name detected "
             "by synonym. A meddra*.csv in the cut folder is also auto-found.")
    if HOSTED: up_med = None
else:
    asc_dir = st.sidebar.text_input("Folder with llt.asc / pt.asc / hlt.asc / hlgt.asc / soc.asc", disabled=HOSTED,
        help="Pipe-delimited release; filtered to currency=='Y', joined "
             "LLT→PT→HLT→HLGT→SOC. The hlt/hlgt files are optional; if absent, "
             "those levels simply do not appear on the candidates.")
    if HOSTED: asc_dir = ""

# ---- sidebar 2: the operating point + where outputs land + optional weights. ----
st.sidebar.markdown("---"); st.sidebar.header("⚖ 2. Operating point")
code_gate = st.sidebar.slider("Auto-commit gate",0.70,0.98,DEF_CODE_GATE,0.01,
    help="Tier-4 threshold. A reviewer-set operating point; the value in force is "
         "written to the audit with the run, so a run is reproducible from its audit.")
# Hosted mode: outputs go to a server temp folder made ONCE per browser session
# (kept in session_state so reruns reuse it), and the models dir is pinned to its
# default "models"; neither path ever comes from a visitor.
# A TemporaryDirectory (not a bare mkdtemp) is kept in session_state, so the folder
# is deleted when Streamlit discards the expired session (and at exit) instead of
# piling up in /tmp, one per page view.
if HOSTED and "_hosted_out" not in st.session_state:
    st.session_state["_hosted_tmp"] = tempfile.TemporaryDirectory(prefix="meddra_output_", ignore_cleanup_errors=True)
    st.session_state["_hosted_out"] = st.session_state["_hosted_tmp"].name
out_dir = st.sidebar.text_input("Output folder",(st.session_state["_hosted_out"] if HOSTED else "meddra_output"), disabled=HOSTED,
    help=(OUT_HELP_BROWSER if IN_BROWSER else "Where ae_coded.csv + audit_log.csv are written on Run (also offered as downloads)."))
if HOSTED: out_dir = st.session_state["_hosted_out"]
models_dir = st.sidebar.text_input("Models dir (optional real weights)","models", disabled=HOSTED,
    help="If a trained artifact is present here but its runtime is not installed, "
         "the app STOPS rather than silently substituting a stand-in.")
if HOSTED: models_dir = "models"
_guard_artifacts(models_dir)   # runs on every rerun, before any compute
# Load whatever trained artifacts the models dir holds (cached: once per process),
# point the tiers at them, and refuse to run on a re-ranker whose feature contract
# the loaded tiers do not meet -- same "no silent substitution" rule as the guard.
_R=load_real(os.path.abspath(models_dir), _artifact_stamp(models_dir))   # keyed on content, not the typed path
if _R["errors"]:
    st.error("A trained artifact in the models dir is present but failed to load, so the run stops rather than "
             "fall back to a stand-in: "+" | ".join(_R["errors"])); st.stop()
_activate(_R)
_cerr=_contract_error(_R)
if _cerr:
    st.error(f"Tier 4 re-ranker cannot run: {_cerr} Fix the models dir; the engine will NOT score with a "
             f"mismatched model."); st.stop()

# ---- LOAD now (dictionary cached) so the pre-flight panel + selector are live.
#      Errors are captured into load_err and SURFACED in the panel, not raised as
#      a stack trace, so the operator sees a plain-language reason. ----
domains={}; meddra=None; meddra_label=""; load_err=None
try:
    domains = load_domains(folder or None, up_dom)
    if domains: meddra, meddra_label = resolve_meddra(folder or None, asc_dir or None, up_med)
except Exception as e: load_err=str(e)

# ---- sidebar 3: the verbatim selector, populated from what actually loaded.
#      Option strings are formatted '{domain} :: {column}'. collect_verbatims
#      splits on ' :: ' -- the FORMAT here and the SPLIT there MUST match, or the
#      unpacking silently picks the wrong domain/column. If you change one,
#      change the other. (This is the single easiest thing to break in this file.) ----
st.sidebar.markdown("---"); st.sidebar.header("🎯 3. Confirm the input (pre-flight)")
vopts=[f"{d} :: {c}" for d,c in verbatim_candidates(domains)] if domains else []
verb_sel = st.sidebar.selectbox("Verbatim source column (this program reads ONLY this)",
    options=vopts if vopts else ["(none detected)"], index=0, disabled=not vopts,
    help="Lists every loaded column matching an AETERM synonym. If yours has an "
         "unusual name, rename it to AETERM in the CSV or add it to "
         "AETERM_SYNONYMS at the top of this file; do not hard-code a column.")

# ---- mode banner: which path ran PER TIER, computed from the runtime probe, not
#      from a constant. This is the [SI]/[RM] discipline made visible: a stand-in
#      is never presented as the component. ----
banner = "Tier 2: %s | Tier 3: %s | Tier 4: %s" % (
    "REAL needle3+hnsw" if REAL_T2 else "STAND-IN [SI] (lexical)",
    ("REAL laya" + ("" if "calibration NONE" not in _R["info"].get("laya","") else " (UNCALIBRATED)")) if REAL_T3 else "STAND-IN [SI]",
    "REAL xgboost re-ranker" if REAL_T4 else "STAND-IN [SI]")
st.info("**Mode banner:** "+banner+" · a [SI] stand-in is never the component; the "
        "audit records which path ran per tier. Without the trained encoder, Tier-2 "
        "retrieval is lexical and will not reproduce semantic MedDRA mappings.")

# ---- pre-flight CONTRACT panel: show, before any compute, exactly what the app
#      read, so the operator confirms it matches their cut. If a column is wrong
#      here, fix it in the sidebar (selector / rule inputs), NOT in the code. ----
st.subheader("📋 Input contract (pre-flight)")
if load_err: st.error(f"Import failed: {load_err}")
elif not domains: st.warning("No domain CSVs loaded yet. Set the folder path or upload files.")
else:
    c1,c2=st.columns(2)
    with c1:
        st.markdown("**Domains loaded**")
        st.dataframe(pd.DataFrame([(d,f"{len(df)} rows",", ".join(df.columns)) for d,df in domains.items()],
                     columns=["domain","size","columns"]), width="stretch", hide_index=True)
        st.markdown("**Verbatim source**"); st.write(f"`{verb_sel}`" if vopts else "None detected.")
    with c2:
        st.markdown("**MedDRA dictionary**"); st.write(f"Source → {meddra_label}")
        if meddra is not None:
            st.write(f"Active LLT→PT rows → **{len(meddra):,}**"); st.write("Detected columns → "+", ".join(meddra.columns))
            # The hierarchy chain this dictionary actually carries (e.g.
            # 'LLT > PT > HLT > HLGT > SOC'). Surfaced here so a reviewer sees at
            # a glance whether the full five-level path is present or degraded,
            # and written to the audit with the run.
            st.write("Hierarchy → "+_hierarchy(meddra))
            # has_codes drives Tier-4 routing: a name-only dictionary cannot emit
            # AEPTCD, so every verbatim must route to a human. Surfaced HERE so
            # the operator is not surprised by 100% routing later.
            hc = "pt_code" in meddra.columns and meddra["pt_code"].notna().any()
            st.write("Has PT codes → "+("YES" if hc else "NO (name-only → all coding routes to a human)"))
    st.caption("This program reads ONLY the verbatim column above; nothing else in your data "
               "is opened or modified.")

# ---- Run button: disabled until BOTH a domain and a dictionary are loaded, so
#      an empty/partial input cannot produce a misleading empty result. ----
if not st.button("🚀 Execute MedDRA Auto-Coding", type="primary", disabled=not (domains and meddra is not None)):
    st.stop()

# ---- execute the tiers on the already-loaded frames; time the whole run for the
#      latency figure shown in the results header and written to the audit. ----
t0=time.perf_counter()
# Split the selectbox option on ' :: ' to recover (domain, column); must match
# the option format built in sidebar 3 (see the warning there).
verbatims = collect_verbatims(domains, *verb_sel.split(" :: ",1)) if vopts else pd.DataFrame()
V, idx = t2_index(meddra)            # build the index ONCE over the dictionary
has_codes = "pt_code" in meddra.columns and meddra["pt_code"].notna().any()
coded_rows=[]; log=[]
if len(verbatims):
    # Tier 3 runs as ONE batched pass over every verbatim (real path), before the loop.
    amb_all=t3_coding_batch(list(verbatims["VERBATIM"]))
    for vi,(_,vr) in enumerate(verbatims.iterrows()):
        s=vr["VERBATIM"]
        cands=t2_coding(s,meddra,V,idx)            # Tier 2: retrieve + cosine
        amb=amb_all[vi]                            # Tier 3: ambiguity scalar (or None)
        cands,status,top=t4_coding(cands,s,code_gate,has_codes,amb["P_UNAMBIGUOUS"])  # Tier 4
        # One output row PER CANDIDATE so the human queue can see the full
        # pre-populated top-k, not just the winner; rank-1 carries the status,
        # the rest are marked ALT_CANDIDATE (evidence, not decisions).
        # QC FIX: every cell is read with BRACKET access (cc["rank"]), never dot
        # access. 'rank' collides with pandas' built-in Series.rank() method, so
        # cc.rank silently returned a bound METHOD instead of the integer and
        # ae_coded.csv's rank column came out full of repr garbage. Bracket
        # access is used for ALL columns here (not just rank) so a future column
        # rename onto another method name cannot corrupt the export again.
        for _,cc in cands.iterrows():
            coded_rows.append(dict(SOURCE_DOMAIN=vr["SOURCE_DOMAIN"],USUBJID=vr["USUBJID"],KEY=vr["KEY"],
                VERBATIM=s,rank=int(cc["rank"]),LLT=cc["LLT"],LLT_CODE=cc["llt_code"],AEDECOD=cc["PT"],AEPTCD=cc["PT_CODE"],
                HLT=cc["HLT"],HLGT=cc["HLGT"],AESOC=cc["SOC"],cosine=cc["cosine"],lev=cc["lev"],jaro=cc["jaro"],S=cc["S"],
                AECODSTAT=(status if int(cc["rank"])==1 else "ALT_CANDIDATE")))
        log.append(f"{vr['SOURCE_DOMAIN']} row {vr['KEY']} '{s[:30]}…' -> {top.PT} S={top.S} {status}")
elapsed=(time.perf_counter()-t0)*1000

# ---- results: these tables ARE the tier outputs, computed from the operator's
#      files; no reference/expected table is embedded anywhere in this file. ----
st.subheader(f"Tier 2–4 · results (computed from your files; {elapsed:.2f} ms)")
if coded_rows:
    st.dataframe(pd.DataFrame(coded_rows), width="stretch")
    st.caption("cosine/S are computed from your dictionary by the active Tier-2 path "
               f"({'real' if REAL_T2 else '[SI] lexical'}); no reference table is embedded.")
st.expander("Processing log").write("\n".join(log))

# ---- audit: one row per run, recording the CONTRACT (which files, which column,
#      which dictionary + its hash), the per-tier PATH (REAL/[SI]), and the
#      EFFECTIVE operating point. This is what makes a run reproducible and what
#      keeps this head's validation scope separate from phi_app.py's. ----
sha=lambda df: hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()[:16]
audit=pd.DataFrame([dict(program="meddra_coder", timestamp=pd.Timestamp.now().isoformat(timespec="seconds"),
    hosted_mode=("true" if HOSTED else "false"),
    domains=list(domains.keys()), verbatim_source=verb_sel, n_verbatims=len(verbatims),
    meddra_source=meddra_label, meddra_rows=len(meddra), meddra_sha256=sha(meddra),
    meddra_has_codes="YES" if has_codes else "NO",
    meddra_hierarchy=_hierarchy(meddra),
    mode_T2="REAL" if REAL_T2 else "STAND-IN", mode_T3="REAL" if REAL_T3 else "STAND-IN",
    mode_T4="REAL" if REAL_T4 else "STAND-IN", coding_gate=code_gate,
    coding_note="single threshold on the re-rank score; no negation conjunct",
    real_artifacts=json.dumps(_R["info"]) if _R["info"] else "none (all tiers stand-in)",
    n_coded_rows=len(coded_rows),
    n_auto=sum(1 for r in coded_rows if r.get("AECODSTAT")=="AUTO_COMMIT_TO_SDTM" and r.get("rank")==1),
    measured_latency_ms=round(elapsed,2))])
os.makedirs(out_dir, exist_ok=True)
if coded_rows: pd.DataFrame(coded_rows).to_csv(os.path.join(out_dir,"ae_coded.csv"), index=False)
audit.to_csv(os.path.join(out_dir,"audit_log.csv"), index=False)
if IN_BROWSER: st.success("Done: `ae_coded.csv` and `audit_log.csv` are in this browser tab's memory only. Save them with the download buttons below.")
else: st.success(f"Wrote `{out_dir}/ae_coded.csv` and `{out_dir}/audit_log.csv`")
st.download_button("⬇ ae_coded.csv",(pd.DataFrame(coded_rows) if coded_rows else pd.DataFrame()).to_csv(index=False).encode(),"ae_coded.csv","text/csv", on_click="ignore")
st.download_button("⬇ audit_log.csv",audit.to_csv(index=False).encode(),"audit_log.csv","text/csv", on_click="ignore")
