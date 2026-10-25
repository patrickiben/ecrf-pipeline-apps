# phi_app.py -- INDEPENDENT program: PII/PHI detection & redaction of free-text
# eCRF fields.
#
# READ THIS FIRST (for whoever maintains this file):
#   * This is ONE of two separate programs. The other is meddra_app.py. They do
#     NOT import each other and share NO module. The helpers _have/_col/
#     load_domains are DELIBERATELY DUPLICATED from meddra_app.py. Do not factor
#     them into a shared module: a shared module is a coupling point that would
#     let a retrain of one head silently change the other's behavior, and the
#     two heads are validated as separate computer-system scopes with separate
#     audit trails. Duplication is intentional.
#   * This program scrubs free text ONLY. It never codes a verbatim and never
#     reads AETERM -- that is meddra_app.py's job. It needs NO MedDRA dictionary;
#     a stray meddra*.csv in the cut folder is IGNORED here so the two programs
#     can share one folder without interfering.
#   * eCRF path only: the input is a database FIELD, so a positive redaction is
#     a string scrub + a per-row flag. The scanned-document path (bounding-box
#     manifest, opaque black rectangle, text-layer deletion, header-band prior,
#     normalized vertical position) is NOT implemented here -- a field has no
#     page, so those features do not exist. The per-token feature set below
#     substitutes in-field position + lexical cues for the page geometry the
#     document path would use, and the audit records that scope explicitly.
#   * No safety/DLT logic, no temporal window, no negation.
#   * Hosted-demo safety mode exists: set ECRF_HOSTED=1 (or the Streamlit secret
#     hosted = true) and every data input is locked to the bundled synthetic cut
#     (disabled in the UI and overwritten in code). See _hosted().
#
# WHAT IT DOES, TIER BY TIER:
#   Tier 1 intake   -> copy each field through UNCHANGED; discover which columns
#                      to scan by CONTENT, not name -- every column that is NOT
#                      strictly numeric (text, dates, coded values, flags) is a
#                      candidate, because PHI can hide in any of them. A pre-
#                      specified list of column names is guaranteed to have gaps;
#                      scanning everything non-numeric does not. The operator still
#                      confirms/deselects columns before Run (see the multiselect).
#   Tier 2 Needle3  -> typed-schema extraction; each extracted value is kept only
#                      if it appears VERBATIM in the field (its in-field offsets
#                      are then exact), and the declared patterns run as a second
#                      proposer so recall is not capped by either one. Stand-in:
#                      the guarded patterns alone. Same (span, entity, start, end,
#                      source) tuple shape either way.
#   Tier 3 Laya     -> P(Direct_PHI), P(Quasi_Identifier), risk tier. Stand-in:
#                      a direct-span rule + a mosaic (>=2 indirect) rule.
#   Tier 4 XGBoost  -> per-span P(Redact); >= gate -> string scrub + AEPHI flag.
#                      Real path: a trained per-span booster (binary:logistic).
#
#   streamlit run phi_app.py
#   stand-in path (runs anywhere):     pip install pandas streamlit
#   real path: install the pinned runtimes (requirements.txt, real-path block) AND
#   put the trained artifacts in the models dir (layout below, steps in
#   eval/README.md). A tier flips to REAL only when its artifact LOADS.
#   (hashlib hashes the loaded artifacts for the audit; numpy builds the Tier-4
#    feature matrix on the real path. Both ship with pandas.)

import hashlib, importlib, json, os, platform, re, sys, tempfile, time, warnings
import numpy as np, pandas as pd, streamlit as st

# Air gap -- same as meddra_app.py: set BEFORE any optional runtime is imported, so
# the Hugging Face client never reaches the network and Needle3's default-on usage
# telemetry is off. setdefault, so an operator can override one deliberately.
for _k, _v in (("HF_HUB_OFFLINE", "1"), ("NEEDLE_TELEMETRY", "0"), ("DO_NOT_TRACK", "1")):
    os.environ.setdefault(_k, _v)

# Runtime probe -- same pattern as meddra_app.py (see the comments there): bind each
# optional runtime and check it exposes the API this file calls. PHI Tier 2 needs
# ONLY the extractor (no graph index), so it keys on needle alone; that asymmetry vs
# meddra_app.py is correct, not a copy-paste bug.
def _have(m):
    try: __import__(m); return True
    except Exception: return False
def _mod(m, *attrs):
    try:
        mod = importlib.import_module(m)
        return mod if all(hasattr(mod, a) for a in attrs) else None
    except Exception: return None
needle  = _mod("needle", "Needle")
laya    = _mod("laya", "load") if (_have("torch") and _have("transformers")) else None
xgboost = _mod("xgboost", "Booster", "DMatrix")
HAVE={"needle": needle is not None, "laya": laya is not None, "xgboost": xgboost is not None,
      "pyreadstat": _have("pyreadstat")}
# REAL only once an artifact LOADS from the models dir (load_real); never on import.
REAL_T2=REAL_T3=REAL_T4=False
_agent=_router=_gatebooster=None

# Models-dir CONVENTION (same folder the coding app reads; this head's files only):
#   needle3/needle3.cact + needle3/libneedle.so (.dylib/.dll)   Tier 2 extractor
#   laya/                                                        Tier 3 checkpoint
#   laya_calibration_phi.json    Tier-3 temperatures fitted for THIS head's questions
#   phi_token_classifier.json + phi_token_classifier.meta.json   Tier 4 gate + contract
ART_NEEDLE=os.path.join("needle3","needle3.cact")
ART_LAYA=os.path.join("laya","model.safetensors")
ART_LAYA_CAL="laya_calibration_phi.json"
ART_GATE="phi_token_classifier.json"
def _engine_file():
    return {"Darwin":"libneedle.dylib","Windows":"libneedle.dll"}.get(platform.system(),"libneedle.so")
def _sha_file(p,n=16):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda: f.read(1<<20), b""): h.update(b)
    return h.hexdigest()[:n]

# Reviewer-set starting values; the effective values are written to the audit.
DEF_REDACT_GATE=0.85
# Discovery is CONTENT-BASED, not name-based: every column that is NOT strictly
# numeric is scanned (see discover_scan_cols). The old suffix/exact-name rule was
# removed because a pre-specified list of column names is guaranteed to miss PHI
# hiding in any column whose header did not match. (meddra_app.py has no such
# discovery at all; it locates its one verbatim column by AETERM synonym.)

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
def _col(df,*syn):
    """Normalized-name column matcher (identical logic to meddra_app.py; kept
    duplicated on purpose -- see the header). Returns None if no match."""
    norm=[re.sub(r"[^a-z0-9]","",c.lower()) for c in df.columns]
    for s in syn:
        t=re.sub(r"[^a-z0-9]","",s.lower())
        if t in norm: return df.columns[norm.index(t)]
    return None

# Data files are CSV or SAS .sas7bdat (SDTM/ADaM dumps). A file named *meddra* is reference
# data, never a domain -- excluded here so it does not leak into the PHI scan.
SAS_EXT = ".sas7bdat"
def _is_data_file(name):
    n=name.lower()
    return (n.endswith(".csv") or n.endswith(SAS_EXT)) and "meddra" not in n
def _read_table(p):
    """Read one domain table from CSV or SAS .sas7bdat into a DataFrame. SAS support is
    OPTIONAL: pyreadstat is probed, never imported at module scope (same discipline as the ML
    runtimes), so CSV-only users need nothing extra. A missing runtime with a SAS file present
    raises a clear error -- we never silently skip a data file, because that would be a coverage
    gap and an unexplained hole in what got scanned."""
    if str(p).lower().endswith(SAS_EXT):
        if not HAVE.get("pyreadstat", False):
            raise ValueError("SAS .sas7bdat input needs 'pyreadstat' (pip install pyreadstat). "
                             "Install it, or export the table to CSV.")
        import pyreadstat
        df,_meta = pyreadstat.read_sas7bdat(p)
        return df
    return pd.read_csv(p)
def load_domains(folder=None, uploads=None):
    """Read every data file (CSV or SAS .sas7bdat) that is NOT a MedDRA file (this program has no
    dictionary; excluding meddra*.csv means a shared cut folder does not feed a dictionary into the
    PHI scan by accident). Domain names are irrelevant -- the columns to scan are discovered by
    CONTENT (every non-numeric column) inside whatever loads. Same stem-normalization as meddra_app.py."""
    doms={}; paths=[]
    if folder:
        paths += [os.path.join(folder,f) for f in sorted(os.listdir(folder)) if _is_data_file(f)]
    for u in (uploads or []):
        if _is_data_file(u.name): paths.append(u)
    for p in paths:
        name=os.path.basename(p) if isinstance(p,str) else p.name
        doms[re.sub(r"[_.].*$","",name.lower()).strip()] = _read_table(p)
    return doms

# ============================ TIER 1 ============================
# CONSUMES: a domain frame.
# EMITS:    the list of SCANNABLE column NAMES -- every column that is NOT
#           strictly numeric (text, dates, coded values, flags).
# INVARIANT: a missing value stays NaN, never an empty string -- an empty string
#           would scan "clean" and silently pass, hiding a coverage gap.
def discover_scan_cols(df):
    """Which columns to scan for PHI. CONTENT-BASED rule: skip ONLY the columns
    pandas has typed as strictly numeric (int/float); scan everything else --
    text, dates, coded values, Y/N flags. This replaces the old name-based rule
    (a suffix list + an exact-name list), which could miss PHI hiding in any
    column whose header did not match: a pre-specified list is guaranteed to have
    gaps, and missing PHI is exactly the failure this program exists to prevent.
    Scanning more than necessary is cheap and safe -- a structured field that
    matches no identifier pattern simply comes back clean with flag N. The
    operator still confirms/deselects columns in the multiselect before Run, so a
    known-safe structured column (e.g. a date you do not want touched) can be
    excluded interactively without any code change."""
    out=[]
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]): continue   # strictly numeric -> skip
        out.append(c)
    return out

# ============================ TIER 2 ============================
# CONSUMES: a free-text string. EMITS: typed spans as (text, entity, start, end)
#           4-tuples with IN-FIELD character offsets (no page, no bbox).
# CONTRACT: Tier 2 LOCATES and TYPES; it does not decide redaction. The split
#           between DIRECT and INDIRECT classes is the load-bearing design:
#           a DIRECT span scrubs on its own merit; an INDIRECT span scrubs ONLY
#           when Tier 3 says the field's JOINT re-identification risk is high.
#           That judgment is Tier 3's, never Tier 2's -- which is exactly why
#           the two are separate tiers.
DIRECT={"PERSON_NAME","PHONE","EMAIL","MRN","DOB","ADDRESS","SSN"}
INDIRECT={"AGE","RARE_CONDITION","ZIP","INITIALS"}
# The patterns below are the STAND-IN's realization of the declared Pydantic
# schema (PHISchema: patient_full_name, medical_record_number, date_of_birth,
# geographic_data, treating_physician, ...). The REAL path is
# needle.extract(text=..., schema=PHISchema) returning the SAME 4-tuple shape,
# so Tier 3/Tier 4 cannot tell which path ran except via the [SI]/[RM] tag.
# The NAME pattern is the subtle one and is GUARDED: a name is matched only when
# introduced by a title keyword (Patient|Mr|Ms|Mrs|Dr) OR in surname-comma form
# ("Doe, John"). That guard is what stops a mid-sentence capitalized DRUG name
# (e.g. "Alanine") or a lab value from being read as a patient name -- the exact
# over-redaction failure a bare "[A-Z][a-z]+ [A-Z][a-z]+" pattern would cause.
# Do not "simplify" RE_NAME by dropping the keyword alternation; it is the
# precision mechanism. The two capture groups exist because the keyword form and
# the comma form put the name in different groups; t2_phi's add() resolves that
# (see the group(1) or group(2) comment there).
RE_PHONE=r"\(?[0-9]{3}\)?[-. ]?[0-9]{3}[-. ]?[0-9]{4}"; RE_EMAIL=r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
RE_MRN=r"\b[0-9]{3}-[0-9]{3}-[0-9]{2}\b"; RE_DOB=r"\b[0-9]{2}/[0-9]{2}/[0-9]{4}\b|\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b"
RE_ZIP=r"(?<!\d)[0-9]{5}(?!\d)"   # negative lookbehind so a 5-digit run inside a
                                  # longer number (an MRN, a phone) is not clipped
RE_AGE=r"\b[0-9]{2,3}[- ]?(?:year-old|year old|yo)\b"
# QC FIX: the trailing dot is optional but only consumed when it ENDS the
# initials (not followed by a word char). The old "\.?\\b" backtracked and
# dropped the final dot of "J.M.", so scrubbing left an orphaned "." behind in
# the sanitized text. (?=[^0-9a-zA-Z]|$) keeps "U.S.A" matching only "U.S"
# (same heuristic as before for chained initials).
RE_INIT=r"\b[A-Z]\.[A-Z](?:\.(?=[^0-9a-zA-Z]|$))?"
RE_NAME=r"\b(?:Patient|Mr|Ms|Mrs|Dr\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)|\b([A-Z][a-z]+,\s*[A-Z][a-z]+)\b"
def _t2_patterns(text):
    """[SI] proposer: locate typed identifier spans with in-field character offsets.
    eCRF input has NO page, so offsets are positions WITHIN the string, not bounding boxes.
    add() runs each pattern, extracts the matched text (group(1) or group(2) for
    the two-group NAME pattern -- whichever actually matched; group(0) for the
    single/no-group patterns), and records (start,end). The seen-set de-overlaps
    so one character range = one span = one downstream decision (nested/overlapping
    matches would otherwise double-count and double-replace). Returns a list of
    5-tuples (span_text, entity, start, end, source) with source='pattern'."""
    spans=[]
    def add(pat,ent,flags=0):
        for mm in re.finditer(pat,text,flags):
            # QC FIX: record the offsets of the CAPTURED GROUP (the identifier
            # itself), not of the full match. The NAME pattern's full match also
            # includes the title keyword ("Patient Jane Miller"), so START/END
            # used to point at the keyword while SPAN held only the name --
            # inconsistent audit offsets. lastindex is 1 or 2 for the two-group
            # NAME pattern (exactly one alternative matched) and None otherwise,
            # in which case group(0)/start(0)/end(0) are the whole match.
            gi = mm.lastindex if mm.lastindex else 0
            g = mm.group(gi)
            spans.append((g,ent,mm.start(gi),mm.end(gi)))
    add(RE_NAME,"PERSON_NAME"); add(RE_PHONE,"PHONE"); add(RE_EMAIL,"EMAIL")
    add(RE_MRN,"MRN"); add(RE_DOB,"DOB"); add(RE_ZIP,"ZIP"); add(RE_AGE,"AGE",re.I); add(RE_INIT,"INITIALS")
    seen,out=set(),[]
    for sp,ent,a,b in spans:
        if (a,b) in seen: continue
        seen.add((a,b)); out.append((sp,ent,a,b,"pattern"))
    return out

# Real proposer: Needle3 extraction with a typed schema. The engine is a small
# tool-calling model, measured to fill a field with the wrong thing (a clock time
# as a date of birth, a phone number copied into the MRN field) and to "repair"
# values, so its output is never trusted as-is: a value is kept only if it occurs
# VERBATIM in the field (then its offsets are exact), titles are stripped from
# names, and Tier 4 decides every candidate. stateless + complete() resets the
# engine between fields (the internal _complete() does not, and leaked values from
# one note into the next in testing); auto_date=False stops it adding a date fact
# that it then reports as a birth date.
PHI_EXTRACT_SCHEMA={"name":"record_identifiers","description":(
    "Record personal identifiers that appear verbatim in a clinical trial note. Leave a field empty if "
    "the note has none. Drug names, lab values, times, doses and kit numbers are not identifiers."),
    "parameters":{"type":"object","properties":{
    "person_name":{"type":"string","description":"a person's name exactly as written, e.g. Jane Miller"},
    "phone":{"type":"string","description":"a telephone number exactly as written"},
    "email":{"type":"string","description":"an email address exactly as written"},
    "mrn":{"type":"string","description":"a medical record number exactly as written"},
    "date_of_birth":{"type":"string","description":"a date of birth exactly as written"},
    "zip_code":{"type":"string","description":"a 5-digit postal code exactly as written"},
    "initials":{"type":"string","description":"a person's initials exactly as written, e.g. J.M."},
    "age":{"type":"string","description":"a person's age exactly as written, e.g. 54-year-old"}}}}
NEEDLE_FIELDS={"person_name":"PERSON_NAME","phone":"PHONE","email":"EMAIL","mrn":"MRN",
               "date_of_birth":"DOB","zip_code":"ZIP","initials":"INITIALS","age":"AGE"}
_TITLE=re.compile(r"^(?:patient|subject|participant|mr|mrs|ms|dr|daughter|son|husband|wife|caregiver)\.?\s+",re.I)
def _t2_needle(text):
    """Needle3 extraction -> grounded 5-tuples (source='needle'). An ungrounded value
    (not found verbatim in the field) is dropped, never guessed into place."""
    r=_agent.complete(text,256); calls=r.get("function_calls") or r.get("suppressed_calls") or []
    args=(calls[0].get("arguments") or {}) if calls else {}
    out=[]
    for fld,ent in NEEDLE_FIELDS.items():
        vals=args.get(fld); vals=vals if isinstance(vals,list) else [vals]
        for v in vals:
            if not isinstance(v,str): continue
            v=_TITLE.sub("",v.strip()).rstrip(",;:)").strip()
            if len(v)<2: continue
            out += [(v,ent,mm.start(),mm.end(),"needle") for mm in re.finditer(re.escape(v),text)]
    return out
def t2_phi(text):
    """Tier 2. Stand-in: the patterns. Real: Needle3 candidates UNION the pattern
    candidates, merged per character range; a range both proposed is source 'both',
    and its entity is the pattern's (patterns are typed by construction)."""
    pat=_t2_patterns(text)
    if not REAL_T2: return pat
    merged={(a,b):[sp,ent,a,b,src] for sp,ent,a,b,src in _t2_needle(text)}
    for sp,ent,a,b,src in pat:
        if (a,b) in merged: merged[(a,b)][1]=ent; merged[(a,b)][4]="both"
        else: merged[(a,b)]=[sp,ent,a,b,src]
    return [tuple(v) for _,v in sorted(merged.items())]

# ============================ TIER 3 ============================
# CONSUMES: a free-text string + the Tier-2 spans (to count indirect attrs).
# EMITS:    P(Direct_PHI), P(Quasi_Identifier) (or None), as named scalars.
# CONTRACT: Tier 3 is its own hop because span localization (Tier 2) cannot see
#           JOINT risk: initials + a ZIP code + a rare condition are each harmless
#           alone and none is a DIRECT span, yet together they re-identify. That
#           is a field-level judgment and must come back as its own number so
#           Tier 4 can weigh it explicitly rather than as a hidden weight.
# ONE local English checkpoint, loaded once per process by load_real (not Laya's
# Router, which sends short English text to the uncalibrated multilingual model).
# The temperatures in laya_calibration_phi.json are fitted for exactly this wording.
PHI_SCHEMA={"direct_pii":{"type":"noul",
    "instructions":"Does this clinical-trial note contain a direct identifier of a person: a name, phone number, email address, medical record number or date of birth?",
    "criteria":{"false":"no direct identifier","true":"at least one direct identifier"}},
    "reident_risk":{"type":"noul",
    "instructions":"Does this note contain two or more indirect details about the participant, such as initials, a postal code or an exact age, that together could identify them?",
    "criteria":{"false":"fewer than two indirect details","true":"two or more indirect details"}}}
def t3_phi_batch(texts,spans_list):
    """Tier 3 for many fields in one batched pass. Real: Laya's calibrated P(true) for
    both questions. Stand-in: the direct-span and mosaic rules in t3_phi."""
    if not REAL_T3: return [t3_phi(t,sp) for t,sp in zip(texts,spans_list)]
    out=_router.predict_batch([str(t) for t in texts],PHI_SCHEMA)
    return [dict(P_DIRECT=round(float(o["answers"]["direct_pii"]["noul"]),4),
                 P_QUASI=round(float(o["answers"]["reident_risk"]["noul"]),4)) for o in out]
def t3_phi(text,spans):
    """Field-level PHI risk. Real: route the text against PHI_SCHEMA -> two
    calibrated probabilities (one non-autoregressive pass, no text generated, so
    deterministic and calibratable). Stand-in: P(direct) high iff a DIRECT span
    exists; P(quasi) high iff >=2 INDIRECT spans CO-OCCUR (the mosaic), medium
    for exactly one, None for zero. None (not 0.0) for zero is deliberate: it
    distinguishes 'no indirect set present, signal genuinely absent' from 'a
    computed low probability', so Tier 4's mosaic branch cannot fire on a field
    that has no indirect attributes. The eCRF worked rows are typically
    direct-only, so P(quasi) is often None here -- that is correct, not missing."""
    if REAL_T3: return t3_phi_batch([text],[spans])[0]
    direct=any(sp[1] in DIRECT for sp in spans); nq=sum(1 for sp in spans if sp[1] in INDIRECT)
    return dict(P_DIRECT=0.99 if direct else 0.05, P_QUASI=(0.96 if nq>=2 else 0.55 if nq==1 else None))

# ============================ TIER 4 ============================
# CONSUMES: ONLY the named columns from Tiers 1-3 (span match/type, the two
#           probabilities, in-field lexical cues). Never re-reads the text as a
#           model input -- the scrub is a string replace on a field we already
#           have, driven by a number computed from upstream columns.
# EMITS:    a scrubbed copy of the field + a per-span flag list + AEPHI.
# CONTRACT: the redaction cutoff is a reviewer-set operating point recorded in
#           the audit, not a weight in a model -- moving it needs no retrain.
# Redaction tag vocabulary. ONE scheme is chosen here and the audit records it,
# so a run is reproducible and the spelling is a logged decision (the source
# material spells the patient-name tag two ways across its panels; we pick one).
TAG={"PERSON_NAME":"[REDACTED_PATIENT_NAME]","PHONE":"[REDACTED_PHONE]","EMAIL":"[REDACTED_EMAIL]",
     "MRN":"[REDACTED_MRN]","DOB":"[REDACTED_DOB]","ZIP":"[REDACTED_ZIP]","AGE":"[REDACTED_AGE]",
     "RARE_CONDITION":"[REDACTED_RARE_CONDITION]","INITIALS":"[REDACTED_INITIALS]",
     "ADDRESS":"[REDACTED_ADDRESS]","SSN":"[REDACTED_SSN]"}
def t4_phi(text,spans,ctx,gate):
    """Per-span redaction on the eCRF path. A DIRECT span scrubs on its own merit
    (P=0.99); an INDIRECT span scrubs ONLY when the field's joint re-identification
    probability is high -- that is the single place Tier 3's P(quasi) changes an
    outcome, and the reason the mosaic case is not lost. The full per-token
    feature set in the document path ALSO includes page geometry (bounding box,
    normalized vertical position, header-band prior); those are ABSENT here
    because a database field has no page, so in-field position + digit ratio +
    capitalization stand in (recorded in the flags for audit). A positive decision
    rewrites the field via string replace and sets the flag; there is NO manifest
    and NO text-layer deletion, because there is no document to burn a box into.
    Sorting spans LONGEST-FIRST is an invariant: it ensures an outer span is
    replaced before any span nested inside it, so a nested replacement cannot
    corrupt the offsets of the outer match (replace() is by text, and the longest
    match is the safest to apply first). Returns (sanitized_text, flag_list,
    AEPHI) where AEPHI is 'Y' iff the text actually changed -- so a field whose
    spans all fell below the gate correctly reports 'N', not a false positive."""
    san=text; flags=[]
    prs=_t4_real_scores(text,spans,ctx) if REAL_T4 else None
    order=sorted(range(len(spans)),key=lambda i:-len(spans[i][0]))   # longest-first
    for i in order:
        sp,ent,a,b=spans[i][:4]
        if prs is not None: pr=prs[i]   # trained per-span booster
        else: pr=0.99 if ent in DIRECT else (0.99 if (ctx["P_QUASI"] or 0)>0.8 else 0.01)
        if pr>=gate:
            san=san.replace(sp,TAG.get(ent,"[REDACTED]"))
            flags.append(dict(SPAN=sp,ENTITY=ent,START=a,END=b,P_REDACT=round(pr,4),
                              DIGIT_RATIO=round(sum(c.isdigit() for c in sp)/max(len(sp),1),3),
                              CAPITALIZED=1 if sp[:1].isupper() else 0,ACTION="MASK_AND_FLAG"))
    return san,flags,("Y" if san!=text else "N")

# Tier-4 feature row per candidate span (names are the booster's contract; the
# order comes from phi_token_classifier.meta.json). Lexical cue = a label word for
# the candidate's entity in the 24 characters before it ("MRN", "DOB", "call" ...).
ENTS=["PERSON_NAME","PHONE","EMAIL","MRN","DOB","ZIP","INITIALS","AGE"]
CUES={"PERSON_NAME":r"patient|mr|ms|mrs|dr|daughter|son|husband|wife|caregiver|spouse|spoke with|called|reached|coordinator|belongs to",
      "PHONE":r"phone|cell|call|callback|contact|tel|reached|on ","EMAIL":r"email|emailed|at ","MRN":r"mrn|record",
      "DOB":r"dob|born|birth","ZIP":r"zip|postal|residing|lives|from","INITIALS":r"initials|subject|participant","AGE":r"age|aged"}
def _span_features(text,spans,ctx):
    nind=sum(1 for sp in spans if sp[1] in INDIRECT); L=max(len(text),1); rows=[]
    for sp,ent,a,b,src in spans:
        r=dict(src_needle=int(src in ("needle","both")),src_pattern=int(src in ("pattern","both")),
               p_direct=ctx["P_DIRECT"] if ctx["P_DIRECT"] is not None else np.nan,
               p_quasi=ctx["P_QUASI"] if ctx["P_QUASI"] is not None else np.nan,n_indirect=nind,
               digit_ratio=sum(c.isdigit() for c in sp)/max(len(sp),1),capitalized=int(sp[:1].isupper()),
               rel_pos=a/L,span_len=len(sp),cue=int(bool(re.search(CUES.get(ent,"$^"),text[max(0,a-24):a].lower()))))
        r.update({f"ent_{e}":int(ent==e) for e in ENTS}); rows.append(r)
    return rows
def _t4_real_scores(text,spans,ctx):
    if not spans: return []
    booster,meta=_gatebooster; rows=_span_features(text,spans,ctx)
    X=np.array([[r[f] for f in meta["features"]] for r in rows],float)
    return [round(float(v),4) for v in booster.predict(xgboost.DMatrix(X,feature_names=meta["features"]))]

def _guard_artifacts(models_dir):
    """HARD STOP, never a silent fallback (same discipline as meddra_app.py; the
    artifact names differ because this head's real model is a per-span redaction
    gate, not a coding ranker). Filenames are a CONVENTION the operator must match
    when dropping real weights (see the models-dir layout at the top)."""
    if not os.path.isdir(models_dir): return
    for art,libs in [(ART_GATE,("xgboost",)),(ART_NEEDLE,("needle",)),(ART_LAYA,("laya",))]:
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
    for a in (ART_NEEDLE,os.path.join("needle3",_engine_file()),ART_LAYA,ART_LAYA_CAL,ART_GATE,ART_GATE.replace(".json",".meta.json")):
        try: st_=os.stat(os.path.join(md,a)); out.append((a,st_.st_size,st_.st_mtime_ns))
        except OSError: out.append((a,None,None))
    return tuple(out)

@st.cache_resource(show_spinner="Loading the real models from the models dir...")
def load_real(models_dir, stamp=None):
    """Same contract as meddra_app.py's load_real (duplicated on purpose): load each
    artifact whose runtime is installed, once per process, from local paths only; an
    artifact that is present but fails to load goes to errors and the UI stops on it."""
    R=dict(T2=None,T3=None,T4=None,info={},errors=[]); md=os.path.abspath(models_dir)
    w,eng=os.path.join(md,ART_NEEDLE),os.path.join(md,"needle3",_engine_file())
    try:
        if needle and os.path.isfile(w) and os.path.isfile(eng):
            os.environ["NEEDLE3_LIB_PATH"]=eng
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")      # "no confidence head": unused here
                R["T2"]=needle.Needle(tools=[PHI_EXTRACT_SCHEMA],weights=w,auto_date=False,stateless=True)
            R["info"]["needle3"]=f"needle3.cact sha256:{_sha_file(w)}"
    except Exception as e: R["errors"].append(f"{os.path.relpath(w,md)}: {type(e).__name__}: {e}")
    if R["T2"] is None and needle and os.path.isfile(w) and not os.path.isfile(eng):
        R["errors"].append(f"{ART_NEEDLE}: its engine {os.path.relpath(eng,md)} is missing")
    lp=os.path.join(md,ART_LAYA)
    try:
        if laya and os.path.isfile(lp):
            cal=os.path.join(md,ART_LAYA_CAL)
            R["T3"]=_load_laya(os.path.dirname(lp),cal if os.path.isfile(cal) else None)
            R["info"]["laya"]=(f"laya/ sha256:{_sha_file(lp)}; calibration "
                               +(f"{ART_LAYA_CAL} sha256:{_sha_file(cal)}" if os.path.isfile(cal) else "NONE (uncalibrated)"))
    except Exception as e: R["errors"].append(f"{os.path.relpath(lp,md)}: {type(e).__name__}: {e}")
    bp=os.path.join(md,ART_GATE)
    try:
        if xgboost and os.path.isfile(bp):
            b=xgboost.Booster(); b.load_model(bp)
            mp=bp.replace(".json",".meta.json"); meta=json.load(open(mp)) if os.path.isfile(mp) else None
            R["T4"]=(b,meta); R["info"]["gate"]=f"{ART_GATE} sha256:{_sha_file(bp)}"
    except Exception as e: R["errors"].append(f"{os.path.relpath(bp,md)}: {type(e).__name__}: {e}")
    # Measured: Needle3's proposals pushed through the stand-in rule read a study ID
    # ("PROTO-2026-X89") as a person's name on every row (1,212 flags on the sample cut,
    # against the patterns' 80). So the extractor is used ONLY behind the trained Tier-4
    # gate; without the gate, Tier 2 stays on its stand-in and the audit says why.
    if R["T2"] is not None and R["T4"] is None:
        R["T2"]=None; R["info"]["needle3"]+=" (loaded but NOT used: its proposals run only behind the trained Tier-4 gate)"
    return R

def _activate(R):
    global _agent,_router,_gatebooster,REAL_T2,REAL_T3,REAL_T4
    _agent,_router,_gatebooster=R["T2"],R["T3"],R["T4"]
    REAL_T2,REAL_T3,REAL_T4=_agent is not None,_router is not None,_gatebooster is not None

def _contract_error(R):
    """The gate was trained on features from SPECIFIC upstream tiers (Needle3 as a
    proposer, Laya's two probabilities); scoring stand-in inputs with it would be a
    silent wrong answer. Returns a reason when the loaded tiers do not match."""
    if R["T4"] is None: return None
    meta=R["T4"][1]
    if not meta: return f"{ART_GATE} has no {ART_GATE.replace('.json','.meta.json')} feature contract next to it."
    need=meta.get("requires",{})
    if need.get("T2") and R["T2"] is None: return "the gate was trained with Needle3 proposals, but no Needle3 artifact loaded."
    if need.get("T3") and R["T3"] is None: return "the gate was trained with Laya's probabilities, but no Laya checkpoint loaded."
    q=hashlib.sha256(json.dumps(PHI_SCHEMA,sort_keys=True).encode()).hexdigest()[:16]
    if need.get("T3") and meta.get("tier3_question_sha") not in (None,q):
        return "the Tier-3 question text changed since the gate was trained (refit it, eval/README.md)."
    return None

# ============================ UI ============================
# Same deliberate order as meddra_app.py: locate data (1), explain how columns are
# discovered by content (2), operating point + outputs (3), LOAD, then the scan-
# column multi-select (4) populated FROM the load, then the banner, then the pre-flight CONTRACT
# panel, then Run. The operator confirms which columns will be scanned/scrubbed
# BEFORE compute, so a column that should not be touched (or one the operator wants
# excluded) is caught on screen and deselected there.
st.set_page_config(page_title="De-identification review assist", layout="wide")
HOSTED = _hosted()   # after set_page_config: no Streamlit call may precede it
# Hosted: an uncaught exception shows a generic message, not a traceback with server
# paths (a crafted widget value can raise one). Process-wide, like the switch itself.
if HOSTED: st.set_option("client.showErrorDetails", "none")
st.title("🛡 De-identification review assist")
# In the browser only the [SI] stand-ins can run (see README), so the caption names those instead.
st.caption(("Tier 1 intake → Tier 2 guarded patterns [SI] → Tier 3 direct and mosaic rules [SI] → Tier 4 redaction gate [SI] · "
            if IN_BROWSER else "Tier 1 intake → Tier 2 Cactus Needle3 → Tier 3 Laya → Tier 4 XGBoost · ")
           + "scrubs free-text eCRF fields only · " + RUNS_WHERE + " · no sample data in this file")
if HOSTED: st.warning(HOSTED_BANNER, icon="🔒")

# Built-in, app-specific instruction manual (from USER_GUIDE.md §4), rendered as a
# collapsible panel so the working view stays clean but help is one click away.
_HELP_MD = """
**What this app does.** Finds and scrubs patient identifiers (PII/PHI) in free-text fields, writing a per-span flag table plus sanitized copies of each scanned domain. It reads only the columns you confirm below; its single purpose is finding and removing PHI from text.

**What it needs.** Domain CSVs only. No dictionary or reference file of any kind is required. Files named `*meddra*` are skipped automatically (they're reference data, not fields to scrub).

### How columns are discovered (content-based)
This app scans **every column that is not strictly numeric** (text, dates, coded values and flags alike), because PHI can hide anywhere and a pre-specified list of column names is guaranteed to have gaps. Only columns pandas typed as a number are skipped. There is no name rule to edit; your control point is the confirmation multi-select in step 4.

> ⚠ Structured fields (dates, IDs) are scanned too. If one matches an identifier pattern (for example an ISO date matching the DOB rule), it will be flagged. Review flags before trusting them, or deselect a known-safe column.

### Step by step
1. **Point at your data** (sidebar 📂 1): type a cut-folder path and/or upload domain CSVs.
2. **Read how discovery works** (sidebar 🔎 2): it explains the content-based rule above.
3. **Set the operating point** (sidebar ⚖ 3): the Redaction gate slider (default **0.85**), recorded in the audit with the run.
4. **Confirm the columns to scan** (sidebar 🎯 4 + pre-flight panel): every non-numeric column is pre-selected; deselect any you do not want scrubbed (e.g. a date or coded field you know is safe). The panel shows exactly which columns will be scanned per domain.
5. **Execute**: click 🚀 Execute PII/PHI Flagging.

### Direct vs indirect identifiers
A *direct* identifier (name, phone, email, MRN, DOB) scrubs on its own merit. An *indirect* attribute (age, ZIP code, initials) scrubs **only when two or more co-occur in the same field**: the "mosaic" rule that catches re-identification risk no single value shows. The stand-in's patterns find names only after a title (Patient, Mr, Ms, Mrs, Dr) or in surname-comma form, MRNs only as `123-456-78`, dates of birth only as `MM/DD/YYYY` or `YYYY-MM-DD`, and ages only as "NN-year-old" or "NN yo"; it has no pattern for addresses, SSNs or rare conditions, so those are never flagged.

### Reading the outputs
- **`phi_flags.csv`** has one row per scrubbed span: `DOMAIN`, `USUBJID`, `ROW`, `FIELD`, `SPAN`, `ENTITY`, in-field `START`/`END`, `P_REDACT`, `ACTION`. The audit evidence of exactly what was masked, with what confidence, at what position.
- **`sanitized/<domain>.csv`** is a copy of each scanned domain carrying the original columns plus `SAN_<field>` (scrubbed text) and `<field>_PHI_FLAG` (`Y` if that cell changed, else `N`). Missing values stay missing, never `"nan"`.

### Stand-in vs real (`[SI]` / `[RM]`)
Without trained weights, Tiers 2–4 run as labeled deterministic stand-ins (`[SI]` in the banner and audit): guarded regexes for spans + rule-based probabilities. It reproduces its worked trace exactly because identifier detection is pattern-shaped and the scrub is a string replace. Install the pinned real-path runtimes and put the trained artifacts in the **Models dir** (layout and build steps: `eval/README.md`); a tier flips to REAL only when its artifact loads, and the audit records which files loaded. Columns, gates and exports do not move. If an artifact file is present but its runtime is missing, the app stops rather than silently substituting a stand-in.

### Troubleshooting
- **A date / ID column got flagged:** that is content-based discovery working as designed: it scans every non-numeric field. If you know that column is safe, deselect it in step 4 and re-run; review any flags before trusting a scrub.
- **Blank cells:** missing values stay missing through the run (never `"nan"`), so an empty field correctly reports flag `N` rather than scanning silently clean.

### What this build does NOT do
No scanned-document / bounding-box path, no safety/DLT logic, nothing leaves the machine. The output supports a de-identification review; it is not a certification, which remains an organizational determination. Every redaction needs human review: on held-out synthetic text the stand-in left 108 of 308 identifiers readable (the real model path: 91 of 308). What was measured is in the [evaluation](https://patrickiben.github.io/ecrf-pipeline-apps/evaluation.html); the limits are in the [case study](https://patrickiben.github.io/ecrf-pipeline-apps/case-study.html).
"""
if IN_BROWSER: _HELP_MD = _HELP_MD.replace("nothing leaves the machine", "nothing you load is uploaded by the app")
with st.expander("📖 How to use this app"):
    st.markdown(_HELP_MD)

# ---- sidebar 1: WHERE the data is. No dictionary input here at all -- this
#      program needs none, and a meddra*.csv in the folder is ignored. ----
# Hosted banner is the FIRST sidebar element and sits above every st.stop(), so it
# shows on every rerun.
if HOSTED: st.sidebar.warning(HOSTED_BANNER, icon="🔒")
st.sidebar.header("📂 1. Point this at your data")
_SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")
# Demo toggle: off by default; a link ending in ?demo=1 (e.g. a hosted demo) starts it on.
# Hosted mode (see _hosted): each data input is disabled AND its value is overwritten
# on the line after it, because a disabled widget only stops the browser and a crafted
# client could still send a value. The bundled synthetic cut is forced; no upload.
_use_sample = st.sidebar.checkbox("Use the bundled synthetic sample data",
    value=(HOSTED or st.query_params.get("demo") == "1"), disabled=HOSTED,
    help="Fills the folder path with the synthetic demo cut shipped in ./sample_data/ (no real patients or licensed dictionary).")
if HOSTED: _use_sample = True
folder = st.sidebar.text_input("Cut folder path (domain CSVs)", value=(_SAMPLE_DIR if _use_sample else ""), disabled=HOSTED,
    help="Path to a folder of domain CSVs. A meddra*.csv here is IGNORED (this "
         "program needs no dictionary). Domain names are irrelevant; the "
         "columns to scan are discovered by content (see section 2).")
if HOSTED: folder = _SAMPLE_DIR            # never trust a client-sent value in hosted mode
up_dom = st.sidebar.file_uploader("...or upload domain files (CSV or SAS .sas7bdat)",
    type=["csv","sas7bdat"], accept_multiple_files=True, disabled=HOSTED)
if HOSTED: up_dom = None

# ---- sidebar 2: how discovery works. It is CONTENT-BASED and deliberately not
#      configurable by column name -- a pre-specified list of names is guaranteed to
#      miss PHI hiding elsewhere. The operator's control point is the multiselect in
#      section 4 (confirm / deselect), not an allow-list here. ----
st.sidebar.markdown("---"); st.sidebar.header("🔎 2. How columns are discovered")
st.caption("**Every column that is NOT strictly numeric is scanned**: text, dates, "
           "coded values and flags alike, because PHI can hide in any of them. Only "
           "columns pandas typed as a number (int/float) are skipped. This replaces the "
           "old suffix/exact-name rule, which could miss an identifier in any column "
           "whose header did not match.")
st.caption("⚠ Structured fields are scanned too: if one matches an identifier pattern "
           "(e.g. an ISO date matching the DOB rule) it will be flagged. Review the flags "
           "before trusting them, or deselect a known-safe column in section 4.")

# ---- sidebar 3: operating point + outputs + optional weights. ----
st.sidebar.markdown("---"); st.sidebar.header("⚖ 3. Operating point")
redact_gate = st.sidebar.slider("Redaction gate",0.50,0.99,DEF_REDACT_GATE,0.01,
    help="Tier-4 threshold; reviewer-set, recorded in the audit.")
# Hosted mode: outputs go to a per-session server temp folder (made once per browser
# session), never a path a visitor typed, and the models dir is pinned to "models";
# both inputs are disabled and overwritten in code, as in sidebar 1.
# A TemporaryDirectory (not a bare mkdtemp) is kept in session_state, so the folder
# is deleted when Streamlit discards the expired session (and at exit) instead of
# piling up in /tmp, one per page view.
if HOSTED and "_hosted_out" not in st.session_state:
    st.session_state["_hosted_tmp"] = tempfile.TemporaryDirectory(prefix="phi_output_", ignore_cleanup_errors=True)
    st.session_state["_hosted_out"] = st.session_state["_hosted_tmp"].name
out_dir = st.sidebar.text_input("Output folder",(st.session_state["_hosted_out"] if HOSTED else "phi_output"), disabled=HOSTED,
    help=(OUT_HELP_BROWSER if IN_BROWSER else "Where phi_flags.csv + sanitized/*.csv + audit_log.csv are written on Run."))
if HOSTED: out_dir = st.session_state["_hosted_out"]
models_dir = st.sidebar.text_input("Models dir (optional real weights)","models", disabled=HOSTED,
    help="If a trained artifact is present here but its runtime is not installed, "
         "the app STOPS rather than silently substituting a stand-in.")
if HOSTED: models_dir = "models"
_guard_artifacts(models_dir)
# Load the models dir's trained artifacts (cached: once per process), point the tiers
# at them, and refuse to run a gate whose feature contract the loaded tiers miss.
_R=load_real(os.path.abspath(models_dir), _artifact_stamp(models_dir))   # keyed on content, not the typed path
if _R["errors"]:
    st.error("A trained artifact in the models dir is present but failed to load, so the run stops rather than "
             "fall back to a stand-in: "+" | ".join(_R["errors"])); st.stop()
_activate(_R)
_cerr=_contract_error(_R)
if _cerr:
    st.error(f"Tier 4 gate cannot run: {_cerr} Fix the models dir; the engine will NOT score with a "
             f"mismatched model."); st.stop()

# ---- LOAD so the pre-flight panel + the multi-select are live. Errors captured
#      into load_err and surfaced in the panel, not as a stack trace. ----
domains={}; load_err=None
try: domains = load_domains(folder or None, up_dom)
except Exception as e: load_err=str(e)
# Run content-based discovery on the loaded frames to populate the multi-select
# default (every non-numeric column), so the operator sees exactly what will be
# scanned and can deselect any known-safe column before compute.
discovered={d:discover_scan_cols(df) for d,df in domains.items()} if domains else {}
# Option strings are '{domain}::{column}' (NO spaces around ::). The split in the
# Run block uses '::' with maxsplit=1 -- the FORMAT here and the SPLIT there MUST
# match, or a column name containing '::' or a spacing change silently mis-routes
# a selection. If you change one, change the other. (Mirror-image warning to the
# one in meddra_app.py, which uses ' :: ' WITH spaces -- the two programs
# intentionally use different separators because their option builders and their
# splitters are paired within each file; do not "unify" them across files.)
ft_flat=[f"{d}::{c}" for d,cs in discovered.items() for c in cs]

# ---- sidebar 4: the scan-column multi-select, pre-selected with EVERY non-numeric
#      column, deselection allowed (e.g. a date or coded column you know is safe).
#      This is the coverage check made interactive -- and now MORE important, since
#      discovery is comprehensive by default rather than name-gated. ----
st.sidebar.markdown("---"); st.sidebar.header("🎯 4. Confirm the inputs (pre-flight)")
ft_sel = st.sidebar.multiselect("Columns to scan for PHI (this program reads ONLY these)",
    options=ft_flat, default=ft_flat,
    help="Pre-selected: every non-numeric column in each domain. Deselect any "
         "column you do NOT want scanned or scrubbed, for example a date or coded column "
         "you know is safe.")

# ---- mode banner: per-tier path from the runtime probe (see meddra_app.py for
#      the same discipline). Notes the eCRF-vs-document scope so the bounding-box
#      capability is not over-claimed by silence. ----
banner = "Tier 2: %s | Tier 3: %s | Tier 4: %s" % (
    "REAL needle3 extraction + [SI] patterns" if REAL_T2 else "STAND-IN [SI] (guarded regex)",
    ("REAL laya" + ("" if "calibration NONE" not in _R["info"].get("laya","") else " (UNCALIBRATED)")) if REAL_T3 else "STAND-IN [SI]",
    "REAL xgboost span gate" if REAL_T4 else "STAND-IN [SI]")
st.info("**Mode banner:** "+banner+" · a [SI] stand-in is never the component; the "
        "audit records which path ran per tier. eCRF path = string scrub + flag; the "
        "bounding-box burn-in is the PDF path and is not exercised here.")

# ---- pre-flight CONTRACT panel: show what loaded + what the rule caught, before
#      any compute. Fixes belong in the sidebar (rule inputs / multiselect), not
#      in the code. ----
st.subheader("📋 Input contract (pre-flight)")
if load_err: st.error(f"Import failed: {load_err}")
elif not domains: st.warning("No domain CSVs loaded yet. Set the folder path or upload files.")
else:
    c1,c2=st.columns(2)
    with c1:
        st.markdown("**Domains loaded**")
        st.dataframe(pd.DataFrame([(d,f"{len(df)} rows",", ".join(df.columns)) for d,df in domains.items()],
                     columns=["domain","size","columns"]), width="stretch", hide_index=True)
    with c2:
        st.markdown("**Columns to scan (every non-numeric column)**")
        st.dataframe(pd.DataFrame([(d,", ".join(cs) if cs else "(none)") for d,cs in discovered.items()],
                     columns=["domain","columns scanned"]), width="stretch", hide_index=True)
        st.write(f"Selected to scrub → {len(ft_sel)} column(s)")
    st.caption("This program reads ONLY the columns selected above and scrubs them; its sole job is "
               "finding and removing PHI from free text. Because discovery is content-based, it may scan "
               "any column you select purely to strip identifiers embedded in its text. No dictionary or "
               "reference file is required or loaded here.")

# ---- Run button: disabled until a domain is loaded AND at least one column is
#      selected, so an empty selection cannot produce a misleading 'no PHI' run. ----
if not st.button("🚀 Execute PII/PHI Flagging", type="primary", disabled=not (domains and ft_sel)):
    st.stop()

# ---- execute the tiers; rebuild the per-domain column lists FROM the
#      multi-select so deselections actually take effect (the rule may have
#      caught a column the operator chose not to scrub). Split on '::' must
#      match the option format in sidebar 4 (see the warning there). ----
t0=time.perf_counter()
sel_by_dom={}
for item in ft_sel:
    d,c=item.split("::",1); sel_by_dom.setdefault(d,[]).append(c)
phi_rows=[]; san_dfs={}; log=[]; memo={}
for d,df in domains.items():
    cols=[c for c in sel_by_dom.get(d,[]) if c in df.columns]
    if not cols: continue
    # Work on a COPY so the original loaded frame is never mutated -- the
    # sanitized columns are added to the copy, and the raw field is preserved
    # alongside them for the side-by-side inspector and the audit.
    sdf=df.copy()
    for col in cols:
        sancol="SAN_"+col; aephi=["N"]*len(df); san_vals=[None]*len(df)
        # QC FIX: missing stays missing. The old code initialized the sanitized
        # column with df[col].astype(str), which turned every NaN into the literal
        # string "nan" -- a fake value that would scan, export, and join as if it
        # were real text (and violate the Tier-1 invariant stated above). Missing
        # and blank cells are skipped here, so they write back as empty cells.
        rows_i=[i for i in range(len(df)) if not pd.isna(df[col].iloc[i]) and str(df[col].iloc[i])]
        texts=[str(df[col].iloc[i]) for i in rows_i]
        # Tiers 2-3 depend only on the text, so each DISTINCT text is processed once
        # per run (a cut repeats STUDYID, visit labels and flags thousands of times;
        # on the real path every model call costs a fraction of a second).
        new=[t for t in dict.fromkeys(texts) if t not in memo]
        new_spans=[t2_phi(t) for t in new]                             # Tier 2: typed spans + offsets
        for t,sp,cx in zip(new,new_spans,t3_phi_batch(new,new_spans)):  # Tier 3: one batched pass
            memo[t]=(sp,cx)
        for i,txt in zip(rows_i,texts):
            spans,ctx=memo[txt]
            san,flags,flag=t4_phi(txt,spans,ctx,redact_gate)  # Tier 4: scrub
            san_vals[i]=san; aephi[i]=flag
            # One flag row PER SCRUBBED SPAN (not per field), so phi_flags.csv is
            # the audit evidence of exactly what was masked and with what
            # confidence and in-field position.
            for f in flags:
                phi_rows.append(dict(DOMAIN=d,USUBJID=df["USUBJID"].iloc[i] if "USUBJID" in df else None,
                    ROW=i+1,FIELD=col,**f))
        sdf[sancol]=san_vals
        sdf[col+"_PHI_FLAG"]=aephi
    san_dfs[d]=sdf
    log.append(f"domain {d}: scrubbed {cols}")
elapsed=(time.perf_counter()-t0)*1000

# ---- results: the flag table + the sanitized domain rows (original columns +
#      SAN_<field> + <field>_PHI_FLAG), computed from the operator's files. ----
st.subheader(f"Tier 2–4 · results (computed from your files; {elapsed:.2f} ms)")
if phi_rows:
    st.markdown("**PHI flags**: one row per scrubbed span")
    st.dataframe(pd.DataFrame(phi_rows), width="stretch")
if san_dfs:
    st.markdown("**Sanitized domain rows**: original columns + SAN_<field> + flag")
    for d,sdf in san_dfs.items(): st.write(f"`{d}.csv`"); st.dataframe(sdf, width="stretch")
st.expander("Processing log").write("\n".join(log))

# ---- audit: one row per run, recording the CONTRACT (which files, which columns
#      selected, the rule in force), the per-tier PATH, the EFFECTIVE cutoff, the
#      TAG SCHEME chosen, and the eCRF-vs-document SCOPE. The scope line is the
#      explicit statement that the mosaic signal fires only on co-occurring
#      indirect spans and that page geometry is absent -- so neither capability
#      is over-claimed. This is what keeps this head's validation scope separate
#      from meddra_app.py's (separate program, separate audit_log.csv). ----
audit=pd.DataFrame([dict(program="phi_scanner", timestamp=pd.Timestamp.now().isoformat(timespec="seconds"),
    hosted_mode=("true" if HOSTED else "false"),
    domains=list(domains.keys()),
    # QC FIX: json.dumps so the audit cell is a clean machine-readable string;
    # a raw Python dict would serialize into its repr ({'ae': 6, ...}) with
    # single quotes that break CSV consumers expecting JSON.
    domain_rows=json.dumps({d:len(df) for d,df in domains.items()}),
    free_text_selected=ft_sel,
    # Discovery is content-based (every non-numeric column); there is no name rule
    # to record. The selected list above IS the contract for this run.
    phi_discovery="content-based: every non-strictly-numeric column scanned",
    mode_T2="REAL" if REAL_T2 else "STAND-IN", mode_T3="REAL" if REAL_T3 else "STAND-IN",
    mode_T4="REAL" if REAL_T4 else "STAND-IN", phi_redact_gate=redact_gate,
    phi_tag_scheme="; ".join(sorted(set(TAG.values()))),
    phi_scope="eCRF direct-identifier scrub; joint re-identification (P_QUASI) fires "
        "only on co-occurring indirect spans; page geometry absent (no PDF)",
    real_artifacts=json.dumps(_R["info"]) if _R["info"] else "none (all tiers stand-in)",
    n_phi_flags=len(phi_rows), measured_latency_ms=round(elapsed,2),
    audit_policy="logs redacted spans WITHOUT retaining raw PHI in secondary storage")])
os.makedirs(out_dir, exist_ok=True)
if phi_rows: pd.DataFrame(phi_rows).to_csv(os.path.join(out_dir,"phi_flags.csv"), index=False)
for d,sdf in san_dfs.items():
    os.makedirs(os.path.join(out_dir,"sanitized"), exist_ok=True)
    sdf.to_csv(os.path.join(out_dir,"sanitized",f"{d}.csv"), index=False)
audit.to_csv(os.path.join(out_dir,"audit_log.csv"), index=False)
if IN_BROWSER: st.success("Done: `phi_flags.csv`, `sanitized/*.csv` and `audit_log.csv` are in this browser tab's memory only. "
                          "Save `phi_flags.csv` and `audit_log.csv` with the download buttons below; the sanitized tables are shown on this page.")
else: st.success(f"Wrote `{out_dir}/phi_flags.csv`, `{out_dir}/sanitized/*.csv`, `{out_dir}/audit_log.csv`")
st.download_button("⬇ phi_flags.csv",(pd.DataFrame(phi_rows) if phi_rows else pd.DataFrame()).to_csv(index=False).encode(),"phi_flags.csv","text/csv", on_click="ignore")
st.download_button("⬇ audit_log.csv",audit.to_csv(index=False).encode(),"audit_log.csv","text/csv", on_click="ignore")
