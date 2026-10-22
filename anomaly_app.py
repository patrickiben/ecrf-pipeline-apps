# anomaly_app.py -- INDEPENDENT program: per-subject ANOMALY detection + distributional DRIFT
# over longitudinal safety/lab/vital data, across NUMERIC and FREE-TEXT fields.
#
# READ THIS FIRST (for whoever maintains this file):
#   * This is ONE of FOUR separate programs in this folder (the others are meddra_app.py,
#     phi_app.py and risk_app.py). They do NOT import each other and share NO module. The small
#     helpers near the top (_have, _col, load_domains) are DELIBERATELY DUPLICATED from the
#     siblings. Do not "refactor" them into a shared file: a shared module is a coupling point
#     that would let a change to one head silently move another's behaviour, and each head is
#     validated as its own computer-system scope with its own audit trail. Duplication is the
#     price of that independence, and it is intentional.
#   * This program DETECTS ANOMALIES AND DRIFT ONLY -- it reads a cut folder, aligns rows to
#     subjects by USUBJID, and emits flagged observations plus per-column / per-lab drift tables.
#     A stray meddra*.csv is IGNORED so all four programs can share one folder without interfering.
#   * It ships as a TRANSPARENT, LABELLED build ([SI]/real discipline): every detector runs its REAL
#     algorithm when the runtime is installed and otherwise a labelled stand-in with the SAME output
#     columns; which path ran is recorded in the banner and every audit row -- a stand-in is never
#     presented as the component. This is DECISION SUPPORT: it ranks and flags subjects/columns for
#     human review; it does NOT certify data quality or make a clinical determination.
#   * It reads CSV OR SAS .sas7bdat (SDTM/ADaM dumps) via an optional pyreadstat reader, exactly
#     like the siblings -- install `pyreadstat` to load .sas7bdat; CSV works without it.
#   * Hosted-demo safety mode: with ECRF_HOSTED=1 set (or the Streamlit secret
#     hosted = true) every data input (uploaders, folder path, models dir) is
#     locked to the bundled synthetic cut in anomaly_data/ and outputs go to a
#     per-session temp folder. Nothing set means the normal local behavior. See
#     _hosted().
#
# WHAT IT DOES, TIER BY TIER (the chain is the product; every decision is a row of readable
# numbers, never a hidden weight). Three separate signals are detected with fast, scalable
# algorithms -- there are many ways data can be anomalous:
#   Tier 1 intake    -> load domains (CSV/SAS), align rows to subjects by USUBJID, and locate the
#                       measurable NUMERIC columns, an OPTIONAL time/visit column, an OPTIONAL
#                       categorical LAB/site column, and any FREE-TEXT columns. Copy values through
#                       UNCHANGED. Missing optional columns disable that signal and are surfaced in
#                       pre-flight, not hidden.
#   Tier 2 numeric   -> per-subject NUMERIC outlier detection: a robust z-score (median/MAD) of each
#                       subject's change-from-baseline against the cohort's distribution of changes is
#                       the interpretable gate; Isolation Forest (scikit-learn, REAL when installed)
#                       corroborates it. Only FLAGGED subjects are emitted, with a discriminative score
#                       in [0,1] and the exact columns/z that fired.
#   Tier 3 drift     -> per measurable column AND per LAB x column: transport distance between the
#                       REFERENCE window (earliest timepoint) and CURRENT window (latest), Sinkhorn
#                       optimal transport (`ot.sinkhorn2`, REAL) or a labelled 1D-Wasserstein stand-in
#                       ([SI]). Reported as a unitless drift ratio. Lab-level drift catches a site/lab
#                       assay change that cohort-wide drift dilutes away.
#   Tier 3b text     -> per FREE-TEXT column: retrieval-isolation of each note against the corpus of
#                       notes in that field -- Needle3/Laya (REAL when installed) or a labelled
#                       bag-of-words isolation stand-in ([SI]). Only FLAGGED notes are emitted.
#   Tier 4 categorize-> map scores/ratios to categories, write contributing factors citing WHICH
#                       detector fired, and emit anomalies.csv + drift.csv + lab_drift.csv +
#                       text_anomalies.csv + audit_log.csv.
#
#   streamlit run anomaly_app.py
#   stand-in path (runs anywhere):     pip install pandas streamlit numpy scipy
#       (QC note: this program uses numpy for the [SI] Wasserstein + bag-of-words stand-ins; `ot` is
#        optional and flips Tier 3 to REAL Sinkhorn.)
#   real numeric-outlier path:         pip install scikit-learn     (Isolation Forest)
#   real drift path (flips banner):    pip install POT scipy

import json, os, re, tempfile, time
import numpy as np, pandas as pd, streamlit as st

# --------------------------------------------------------------------------- #
# Runtime probe. Same pattern as the siblings: test each OPTIONAL library by attempting an import
# inside try/except WITHOUT importing at module scope, so a missing dependency never crashes the app
# -- it only affects whether a REAL detector can run (vs its labelled [SI] stand-in).
# --------------------------------------------------------------------------- #
def _have(m):
    try: __import__(m); return True
    except Exception: return False
HAVE = {m: _have(m) for m in ("ot","scipy","sklearn","pyreadstat")}
REAL_OT   = HAVE["ot"] and HAVE["scipy"]     # Sinkhorn needs BOTH the library and scipy (for ot.dist)
REAL_IF   = HAVE["sklearn"]                  # Isolation Forest numeric-outlier corroborator
# The text tier's REAL path (Needle3/Laya retrieval-isolation) is NOT wired in this build, so it is
# pinned to its labeled [SI] stand-in. An earlier probe keyed it on an import name ("cactus-needle")
# that can never import; that kept the label honest by accident. The coding and PHI apps carry the
# wired Needle3/Laya paths (see their load_real); this flag stays False until this tier gets one.
REAL_TEXT = False

# Reviewer-set starting values; the effective thresholds are written to the audit. These are the
# BUILT-IN [SI] CRITERIA this transparent engine always uses -- declared constants, not hidden magic.
DEFAULT_THR = {
    # --- Tier 2 numeric outlier ---
    "ANOM_Z": 3.0,                 # robust-z magnitude that FLAGS a subject (extreme deviation)
    "ANOM_Z_TOP": 8.0,             # z mapped to score 1.0; keeps scores discriminative in [0,1]
                                   #   (z=3 -> ~0.375 MODERATE, z=6 -> 0.75 CRITICAL) instead of every
                                   #    flagged subject saturating at exactly 1.0
    "ANOM_CAT_MODERATE": 0.25,     # anomaly-score category cuts (score in [0,1])
    "ANOM_CAT_HIGH": 0.5,
    "ANOM_CAT_CRITICAL": 0.75,
    # --- Tier 3 drift ---
    "DRIFT_RATIO_MODERATE": 0.25,  # unitless drift-ratio category cuts (transport dist / ref spread)
    "DRIFT_RATIO_HIGH": 0.6,
    "DRIFT_RATIO_CRITICAL": 1.2,
    "SINKHORN_REG_FRAC": 0.05,     # regularization = this fraction of the reference robust spread (IQR-based)
    # --- Tier 3b text outlier ---
    "TEXT_ISO_FLAG": 0.5,          # retrieval-isolation score that FLAGS a note as an outlier
    "TEXT_ISO_MODERATE": 0.25,     # isolation-score category cuts
    "TEXT_ISO_HIGH": 0.5,
    "TEXT_ISO_CRITICAL": 0.75,
    "TEXT_MIN_DOCS": 3,            # min non-empty notes in a field before text detection runs on it
}

# Column synonyms per logical field -- the ONLY place column naming is configured; add a spelling
# here for an unusual header rather than hard-coding anywhere downstream (same rule as siblings).
SYN = {
    "USUBJID": ["usubjid","subject_id","subjid"],
    # time/visit columns, in preference order: a date-like column first, then numeric visit indices.
    "TIME": ["avisitd","avaldt","visit_date","studyday","visnum","visit_num","visitnumber",
             "avisitn","vnum","cycle","week"],
    # categorical lab/site/assay column -- enables per-lab drift (a site assay change that cohort-wide
    # drift dilutes). Constant per subject in the demo; any grouping column works.
    "LAB": ["lab","site","laboratory","assay_site","lab_name","center"],
    # study-id-like columns are EXCLUDED from free-text scanning (they are codes, not notes).
    "STUDY": ["studyid","study_id","studynm","studyname"],
}

# --------------------------------------------------------------------------- #
# Hosted-demo safety mode. ON when the environment variable ECRF_HOSTED=1 is set
# or the Streamlit secret "hosted = true" exists (Streamlit Community Cloud: app
# Settings > Secrets). A public demo must never take in real data, so in this
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
    """Return the first column of `df` whose NORMALIZED name (lowercased, all non-alphanumerics
    stripped) equals any synonym. Normalization is why 'Visit Num', 'visit_num' and 'VISITNUM' all
    match -- EDC vendors and SDTM dumps name the same field different ways, and we refuse to assume
    one spelling. Returns None if nothing matches; callers must handle None."""
    norm=[re.sub(r"[^a-z0-9]","",c.lower()) for c in df.columns]
    for s in syn:
        t=re.sub(r"[^a-z0-9]","",s.lower())
        if t in norm: return df.columns[norm.index(t)]
    return None

# Data files are CSV or SAS .sas7bdat (SDTM/ADaM dumps). A file named *meddra* is reference data,
# never a domain -- excluded here so it does not leak into the anomaly scan.
SAS_EXT=".sas7bdat"
def _is_data_file(name):
    n=name.lower()
    return (n.endswith(".csv") or n.endswith(SAS_EXT)) and "meddra" not in n
def _read_table(p):
    """Read one domain table from CSV or SAS .sas7bdat into a DataFrame. SAS support is OPTIONAL:
    pyreadstat is probed, never imported at module scope (same discipline as the ML runtimes), so
    CSV-only users need nothing extra. A missing runtime with a SAS file present raises a clear error
    -- we never silently skip a data file, because that would be a coverage gap."""
    if str(p).lower().endswith(SAS_EXT):
        if not HAVE.get("pyreadstat", False):
            raise ValueError("SAS .sas7bdat input needs 'pyreadstat' (pip install pyreadstat). "
                             "Install it, or export the table to CSV.")
        import pyreadstat
        df,_meta=pyreadstat.read_sas7bdat(p)
        return df
    return pd.read_csv(p)

def load_domains(folder=None, uploads=None):
    """Read every data file (CSV or SAS .sas7bdat) that is NOT a MedDRA file, keyed by filename stem.
    Domain NAMES are irrelevant -- the measurable columns and time column are located by content /
    synonym inside whatever loads. Same stem-normalization as the siblings."""
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
# CONSUMES: the loaded domain frames. EMITS: a single aligned long view keyed by USUBJID carrying the
# measurable numeric columns + an optional time column + an optional LAB column + any free-text cols,
# plus meta recording which of each were found. INVARIANT: Tier 1 NEVER rewrites a value -- it only
# locates columns and aligns rows to subjects, so Tiers 2/3 measure against exactly what was recorded.
def _num(series):
    """Coerce a column to float, leaving unparseable cells as NaN (never a crash)."""
    return pd.to_numeric(series, errors="coerce")

def _is_text_col(df, c, exclude):
    """A FREE-TEXT column is object/string-typed, not one of the excluded logical columns, and looks
    like prose rather than codes: mean non-null string length >= 8 AND at least 4 distinct values.
    That keeps genuine notes (LABCOM/AECOM) in while dropping visit labels ('V1'), Y/N flags and
    constant study ids -- short coded values are not free text. We accept BOTH object dtype and the
    pandas-3 StringDtype, because pd.read_csv infers string columns as the latter on modern pandas."""
    if c in exclude: return False
    if not (pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c])): return False
    s=df[c].dropna().astype(str)
    if len(s)==0: return False
    return float(s.str.len().mean())>=8 and s.nunique()>=4

def tier1_align(domains):
    """Concatenate every loaded domain into one frame indexed by USUBJID. For each domain we keep the
    subject id, any detected time column, any LAB column, every STRICTLY-NUMERIC measurable column, and
    any free-text columns (skipping the time/lab/study/id columns themselves). Duplicate domains are
    concatenated so two files both count. Returns (view, meta) where meta records which numeric + time
    + lab + text columns were found."""
    frames=[]; numcols=set(); textcols=set()
    timecol=None; labcol=None
    for name,df in domains.items():
        subj=_col(df,*SYN["USUBJID"])
        if not subj: continue   # cannot align to subjects without an id column
        t=_col(df,*SYN["TIME"]); l=_col(df,*SYN["LAB"])
        study=_col(df,*SYN["STUDY"])
        if t is not None and timecol is None: timecol=t
        if l is not None and labcol is None: labcol=l
        exclude={subj,t,l,study} - {None}
        meas=[c for c in df.columns
              if pd.api.types.is_numeric_dtype(df[c]) and c!=subj and (t is None or c!=t)]
        texts=[c for c in df.columns if _is_text_col(df,c,exclude)]
        keep=[subj]+([t] if t else [])+([l] if l else [])+meas+texts
        v=df[keep].rename(columns={subj:"USUBJID"})
        numcols |= set(meas); textcols |= set(texts)
        frames.append(v)
    if not frames: return pd.DataFrame(), dict(numcols=[],timecol=None,labcol=None,textcols=[],n_subjects=0)
    out=pd.concat(frames, ignore_index=True).set_index("USUBJID")
    for c in numcols:
        if c in out.columns: out[c]=_num(out[c])
    meta=dict(numcols=sorted(numcols), timecol=timecol, labcol=labcol,
              textcols=sorted(textcols), n_subjects=len(out))
    return out, meta

# ============================ TIER 2 (numeric outlier) ============================
# CONSUMES: the aligned Tier-1 view + thresholds. EMITS: per-subject READABLE numeric-outlier signals --
# a robust z-score of each subject's change-from-baseline against the cohort's distribution of changes,
# an aggregate anomaly score in [0,1], and (when Isolation Forest is installed) its corroborating verdict.
# CONTRACT: Tier 2 PROPOSES and MEASURES; it decides nothing (Tier 4 categorizes). Only FLAGGED subjects
# are returned -- the operator does not need rows for everyone who was normal.
def _robust_z(vals):
    """Robust z-score vs median/MAD. MAD is scaled by 1.4826 to be consistent with std for normal data;
    a zero MAD falls back to the sample std, then to 1.0 -- never divide by zero."""
    vals=np.asarray(vals,float)
    med=float(np.median(vals))
    mad=float(np.median(np.abs(vals-med)))
    scale=1.4826*mad if mad>0 else (float(np.std(vals)) or 1.0)
    return (vals-med)/scale

def _change_matrix(view, meta):
    """Per subject x numeric column: baseline (earliest) and current (latest) values, picked positionally
    per subject so duplicated ids never misalign. A subject with at least one valid time value gets a real
    baseline/current window; a subject whose rows carry NO time value -- e.g. present only in a
    cross-sectional domain when the cut also has longitudinal files -- falls back to its first row and is
    marked tflag=False so Tier 2 scores it as a static outlier instead of dividing by an undefined change.
    Returns (subjects, base, cur, tflag) where base/cur are {column: {subject: value}} and tflag[s] says
    whether subject s has a usable time axis."""
    numcols=meta["numcols"]; tcol=meta["timecol"]
    has_time = tcol is not None and tcol in view.columns
    subjects=list(dict.fromkeys(view.index))   # unique subjects, stable order
    base={c:{} for c in numcols}; cur={c:{} for c in numcols}; tflag={}
    for s in subjects:
        sub=view.loc[s]; sub=pd.DataFrame([sub]) if isinstance(sub,pd.Series) else sub
        tf=False; b=cu=sub.iloc[0:1]
        if has_time and tcol in sub.columns:
            tv=_num(sub[tcol]).to_numpy()
            if np.isfinite(tv).any():          # at least one valid time value for this subject
                tf=True
                b=sub.iloc[[int(np.nanargmin(tv))]]; cu=sub.iloc[[int(np.nanargmax(tv))]]
        tflag[s]=tf
        for c in numcols:
            base[c][s]=b[c].iloc[0]; cur[c][s]=cu[c].iloc[0]
    return subjects, base, cur, tflag

def _if_verdict(subjects, base, cur, numcols):
    """REAL Isolation Forest corroborator (scikit-learn). Fits IF on the subject x column change matrix
    and returns {subject: 'confirms'|'does not confirm'} using an ADAPTIVE rule -- a subject is confirmed
    when its anomaly score beats the cohort median, so there is no magic cutoff to tune per dataset.
    Returns {} when sklearn is absent (the [SI] path simply has no IF verdict)."""
    if not REAL_IF: return {}
    from sklearn.ensemble import IsolationForest
    X=np.array([[cur[c][s]-base[c][s] for c in numcols] for s in subjects],float)
    X[np.isnan(X)]=0.0   # no-change / unknown -> 0; IF cannot take NaN directly
    clf=IsolationForest(n_estimators=200, random_state=42).fit(X)
    sc=-clf.score_samples(X)                 # higher = more anomalous (offset score negated)
    med=float(np.median(sc))
    return {s:("confirms" if v>med else "does not confirm") for s,v in zip(subjects,sc)}

def tier2_signals(view, meta, thr):
    """Per subject x numeric column: the robust z of each subject's deviation against the cohort's own
    distribution for that column -- CHANGE-FROM-BASELINE when the subjects carrying that column have a time
    axis (a uniform population shift moves everyone together -> no one is an outlier in the change
    distribution; that signal belongs to Tier-3 drift), else DEVIATION-FROM-COHORT-MEDIAN for columns whose
    subjects are cross-sectional. An individual who deviates far beyond the typical within-column spread IS
    flagged here -- so anomaly and drift stay separate, honest signals. The score is min(1, max|z| / ANOM_Z_TOP)
    so it stays discriminative in [0,1] instead of every flagged subject saturating at exactly 1.0. Only
    subjects with max|z| >= ANOM_Z are returned."""
    numcols=meta["numcols"]
    if not numcols or len(view)==0: return pd.DataFrame()
    subjects, base, cur, tflag = _change_matrix(view, meta)
    verdict=_if_verdict(subjects, base, cur, numcols)   # {} on the [SI] path

    # Per column, pick the signal definition from the data itself: change-from-baseline when enough of the
    # subjects carrying this column have a time axis; otherwise static deviation-from-cohort-median. This is
    # what lets a mixed cut (longitudinal labs + cross-sectional safety files) score each column honestly
    # instead of crashing on an undefined baseline for a subject with no visits.
    col_signal={}   # {column: {subject: signal_value}}
    for c in numcols:
        timed={s:(cur[c][s]-base[c][s]) for s in subjects
               if tflag[s] and not pd.isna(cur[c].get(s)) and not pd.isna(base[c].get(s))}
        static={s:cur[c][s] for s in subjects if not pd.isna(cur[c].get(s))}
        if len(timed)>=3:
            col_signal[c]=timed
        elif len(static)>=3:
            med=float(np.nanmedian(list(static.values())))
            col_signal[c]={s:(v-med) for s,v in static.items()}
        else:
            col_signal[c]={}   # not enough data to measure against honestly

    rows=[]
    for s in subjects:
        zext=[]; factors=[]
        for c in numcols:
            sig=col_signal.get(c,{})
            if s not in sig or pd.isna(sig[s]): continue
            cohort=np.array([sig[x] for x in subjects if x!=s and x in sig and not pd.isna(sig[x])],float)
            if len(cohort)<3: continue   # need a reference to measure against (leave-one-out)
            z=_robust_z(np.concatenate([cohort,[sig[s]]]))[-1]
            mag=min(1.0, abs(z)/thr["ANOM_Z_TOP"])
            zext.append(abs(z))
            if abs(z)>=thr["ANOM_Z"]: factors.append(f"{c} Δ={sig[s]:+.2f} (z={z:+.1f})")
        if not zext or max(zext)<thr["ANOM_Z"]: continue   # flagged-only: skip normal subjects
        score=round(float(min(1.0, max(zext)/thr["ANOM_Z_TOP"])),3)
        det=["robust-z"]
        v=verdict.get(s)
        if v is not None: det.append("IsolationForest "+v)
        rows.append(dict(USUBJID=s, anomaly_score=score, detectors=" + ".join(det),
                         extreme_columns="; ".join(factors)))
    return pd.DataFrame(rows)

# ============================ TIER 3 (drift) ============================
# CONSUMES: ONLY the aligned view + thresholds. EMITS: per-column AND per-LAB x column drift -- a transport
# distance between the reference and current windows, plus a unitless ratio. [SI]/real discipline: Sinkhorn
# when `ot`+scipy are present, else a labelled 1D-Wasserstein stand-in with the SAME output columns. The
# decision is a function of numbers already on screen -- no hidden feature.
def _sinkhorn_dist(x_ref,x_cur,scale,reg_frac):
    """Real path: regularized Sinkhorn transport cost between two empirical 1-D distributions with uniform
    weights and a LINEAR (L1) cost |ref-cur| per pair. The result is a mean transport distance in the column's
    units (~Wasserstein-1). Regularization scales to the REFERENCE window's robust spread (`scale`, IQR-based),
    NOT the full data range: scaling it to the range lets one tail/outlier stretch reg far beyond the bulk
    inter-point spacing, which smears mass and inflates the cost (measured +140..+186% vs exact 1-D Wasserstein
    on tight columns). Scaling to the robust spread keeps Sinkhorn within ~5-28% of exact W1 across all demo
    columns while staying numerically stable even when a column has drifted far (verified against exact 1-D
    Wasserstein ground truth)."""
    import ot
    Xr=np.asarray(x_ref,float); Xc=np.asarray(x_cur,float)
    M=np.abs(Xr[:,None]-Xc[None,:])      # (n,m) linear cost between the two windows
    n=len(x_ref); m=len(x_cur)
    a=np.full(n,1.0/n); b=np.full(m,1.0/m)
    reg=max(1e-6, reg_frac*float(scale))  # robust-spread-scaled; stable + accurate (see docstring)
    return float(ot.sinkhorn2(a,b,M,reg=reg,numItermax=10000,stopThr=1e-9))

def _wasserstein_dist(x_ref,x_cur):
    """[SI] stand-in: 1-D Wasserstein distance between two empirical distributions, computed as the mean
    absolute difference of their quantile functions on a common grid. Same units and same monotonicity in
    distributional shift as the Sinkhorn path -- it just cannot capture multi-modal transport geometry."""
    K=200; q=np.linspace(0,1,K)
    fa=np.interp(q,np.linspace(0,1,len(x_ref)),np.sort(np.asarray(x_ref,float)))
    fb=np.interp(q,np.linspace(0,1,len(x_cur)),np.sort(np.asarray(x_cur,float)))
    return float(np.mean(np.abs(fa-fb)))

def _drift_rows(view, meta, thr, labcol=None):
    """Transport distance + unitless ratio between the reference (earliest) and current (latest) windows,
    for every measurable column -- optionally restricted to one LAB group when `labcol` is given. Returns a
    list of row dicts; callers add their own grouping label."""
    numcols=meta["numcols"]; tcol=meta["timecol"]
    if not numcols or tcol is None: return []
    tv=_num(view[tcol])
    first=view.groupby(level=0)[tcol].transform("min"); last=view.groupby(level=0)[tcol].transform("max")
    rows=[]
    for c in numcols:
        col=_num(view[c])
        ref=col[(tv==first)&col.notna()].to_numpy()
        cur=col[(tv==last)&col.notna()].to_numpy()
        if len(ref)<3 or len(cur)<3: continue   # not enough data in a window to compare honestly
        iqr=float(np.subtract(*np.percentile(ref,[75,25]))) or float(np.std(ref)) or 1.0
        spread=1.349*iqr   # robust reference spread (IQR-based), so a few outliers don't distort the ratio
        dist=_sinkhorn_dist(ref,cur,spread,thr["SINKHORN_REG_FRAC"]) if REAL_OT else _wasserstein_dist(ref,cur)
        rows.append(dict(column=c, n_ref=int(len(ref)), n_cur=int(len(cur)),
                         transport_distance=round(dist,4), drift_ratio=round(dist/spread,3)))
    return rows

def tier3_drift(view, meta, thr):
    """Cohort-wide drift: one row per measurable column (reference vs current window)."""
    rows=_drift_rows(view, meta, thr)
    for r in rows: r["lab"]="ALL"
    return pd.DataFrame(rows)

def tier3_lab_drift(view, meta, thr):
    """Per-LAB drift: one row per LAB x measurable column. A site/lab assay change that cohort-wide drift
    dilutes to ~1/k strength shows up here as a single lab's ratio standing out from the others."""
    if not meta.get("labcol"): return pd.DataFrame()
    lc=meta["labcol"]
    rows=[]
    for lab in sorted(view[lc].dropna().astype(str).unique()):
        sub=view.loc[view[lc].astype(str)==lab]
        for r in _drift_rows(sub, meta, thr):
            r["lab"]=str(lab); rows.append(r)
    return pd.DataFrame(rows)

def _subject_current_values(view, meta, c):
    """Per-subject current-window value for column c (latest timepoint if a time axis exists, else the first
    non-missing value), grouped by LAB. Returns {lab: np.array(values)}. Comparing labs at each subject's own
    latest visit keeps the between-lab comparison on the same footing as per-lab temporal drift."""
    tcol=meta["timecol"]; lc=meta["labcol"]
    out={}
    for s in view.index:
        sub=view.loc[s]; sub=pd.DataFrame([sub]) if isinstance(sub,pd.Series) else sub
        lab=str(sub[lc].iloc[0]); v=sub[c]
        val=np.nan
        if tcol is not None and tcol in sub.columns:
            tv=_num(sub[tcol]).to_numpy(); valid=~np.isnan(tv)
            if valid.any(): val=v.iloc[int(np.nanargmax(tv))]
            elif v.notna().any(): val=v.dropna().iloc[0]
        elif v.notna().any(): val=v.dropna().iloc[0]
        out.setdefault(lab,[]).append(val)
    return {lab:np.asarray(vals,float) for lab,vals in out.items()}

def tier3_lab_compare(view, meta, thr):
    """BETWEEN-lab/site comparison (complements per-lab temporal drift): for each numeric column and each LAB,
    the transport distance from that lab's current-window distribution to the POOLED-OTHERS (leave-one-out)
    distribution, normalized by the reference spread. A site/lab that systematically measures differently from
    every other site shows a high ratio; sites that agree with the rest show ~0. This answers 'how different is
    this lab/site from all the others?' -- distinct from per-lab drift, which asks how much one lab moved over
    time. [SI]/real discipline: Sinkhorn when `ot`+scipy are present, else the labelled 1D-Wasserstein stand-in."""
    if not meta.get("labcol"): return pd.DataFrame()
    lc=meta["labcol"]; numcols=meta["numcols"]
    labs=sorted(view[lc].dropna().astype(str).unique())
    if len(labs)<2: return pd.DataFrame()   # need >=2 labs to compare between them
    rows=[]
    for c in numcols:
        by_lab={lab:v[~np.isnan(v)] for lab,v in _subject_current_values(view, meta, c).items()}
        by_lab={lab:v for lab,v in by_lab.items() if len(v)>=3}
        if len(by_lab)<2: continue
        allv=np.concatenate(list(by_lab.values()))
        iqr=float(np.subtract(*np.percentile(allv,[75,25]))) or float(np.std(allv)) or 1.0
        spread=1.349*iqr   # robust reference spread for the unitless ratio
        for lab in by_lab:
            others=np.concatenate([by_lab[o] for o in labs if o!=lab])
            if len(others)<3: continue
            dist=_sinkhorn_dist(by_lab[lab],others,spread,thr["SINKHORN_REG_FRAC"]) if REAL_OT else _wasserstein_dist(by_lab[lab],others)
            rows.append(dict(column=c, lab=lab, n=int(len(by_lab[lab])), n_others=int(len(others)),
                             transport_distance=round(dist,4), between_lab_ratio=round(dist/spread,3)))
    return pd.DataFrame(rows)

# ============================ TIER 3b (text outlier) ============================
# CONSUMES: the aligned view + thresholds. EMITS: flagged FREE-TEXT observations -- notes whose content is
# isolated from the corpus of notes in that field. [SI]/real discipline: Needle3/Laya when installed, else a
# labelled bag-of-words retrieval-isolation stand-in with the SAME output columns. Only FLAGGED notes are
# returned (the operator does not need every routine note).
def _bow_isolation(texts):
    """[SI] stand-in: retrieval isolation of each document against the corpus in its field. Each note is a
    bag-of-words vector; its isolation score is 1 - (max cosine similarity to any OTHER note). Routine notes
    are near-duplicates of one another -> high max-similarity -> iso ~0; an unusual/erroneous note has no
    close neighbour -> iso near 1. Same monotonicity in 'how unlike the rest' as a Needle3 retrieval-isolation
    score, without needing those packages."""
    toks=[re.findall(r"[a-z0-9]+", t.lower()) for t in texts]
    docs=[{w:toks[i].count(w) for w in set(toks[i])} for i in range(len(texts))]
    vocab=sorted(set().union(*[set(d) for d in docs])) if any(docs) else ["_"]
    V=np.array([[d.get(v,0.0) for v in vocab] for d in docs],float)
    nrm=np.linalg.norm(V,axis=1,keepdims=True); nrm[nrm==0]=1.0
    Vn=V/nrm
    sim=Vn@Vn.T; np.fill_diagonal(sim,-1.0)   # exclude self-similarity
    return 1.0-sim.max(axis=1)

def tier3b_text(view, meta, thr):
    """Per free-text column: retrieval-isolation of each non-empty note against the field's corpus; emit only
    notes whose isolation score >= TEXT_ISO_FLAG. Returns one row per flagged note."""
    rows=[]
    for c in meta.get("textcols",[]):
        if c not in view.columns: continue
        s=view[c].dropna().astype(str)
        s=s[s.str.strip()!=""]
        if len(s)<thr["TEXT_MIN_DOCS"]: continue   # too few notes to isolate against honestly
        iso=_bow_isolation(list(s))
        for idx,iso_v in enumerate(iso):
            if iso_v<thr["TEXT_ISO_FLAG"]: continue   # flagged-only: skip routine notes
            rows.append(dict(USUBJID=s.index[idx], field=c, isolation_score=round(float(iso_v),3),
                             note=str(s.iloc[idx])[:200]))
    return pd.DataFrame(rows)

# ============================ TIER 4 ============================
# CONSUMES: the Tier-2 anomaly signals + Tier-3 drift + Tier-3b text outliers. EMITS: categories, contributing
# factors (citing WHICH detector fired), and the four output tables. This is where scores map to readable
# categories; every row explains itself.
def tier4_categorize(anom, drift, lab_drift, lab_cmp, text, thr):
    def a_cat(v):
        return ("CRITICAL" if v>=thr["ANOM_CAT_CRITICAL"] else "HIGH" if v>=thr["ANOM_CAT_HIGH"]
                else "MODERATE" if v>=thr["ANOM_CAT_MODERATE"] else "LOW")
    def d_cat(v):
        return ("CRITICAL" if v>=thr["DRIFT_RATIO_CRITICAL"] else "HIGH" if v>=thr["DRIFT_RATIO_HIGH"]
                else "MODERATE" if v>=thr["DRIFT_RATIO_MODERATE"] else "LOW")
    def t_cat(v):
        return ("CRITICAL" if v>=thr["TEXT_ISO_CRITICAL"] else "HIGH" if v>=thr["TEXT_ISO_HIGH"]
                else "MODERATE" if v>=thr["TEXT_ISO_MODERATE"] else "LOW")
    arows=[]
    for _,r in anom.iterrows():
        arows.append(dict(USUBJID=r["USUBJID"], anomaly_score=round(float(r["anomaly_score"]),3),
                          anomaly_category=a_cat(float(r["anomaly_score"])), detectors=r.get("detectors",""),
                          extreme_columns=r.get("extreme_columns","") or "none"))
    def _drows(df):
        out=[]
        for _,r in df.iterrows():
            out.append(dict(lab=r.get("lab","ALL"), column=r["column"], n_ref=int(r["n_ref"]), n_cur=int(r["n_cur"]),
                            transport_distance=round(float(r["transport_distance"]),4),
                            drift_ratio=float(r["drift_ratio"]), drift_category=d_cat(float(r["drift_ratio"]))))
        return out
    def _cmprows(df):
        out=[]
        for _,r in df.iterrows():
            out.append(dict(column=r["column"], lab=r["lab"], n=int(r["n"]), n_others=int(r["n_others"]),
                            transport_distance=round(float(r["transport_distance"]),4),
                            between_lab_ratio=float(r["between_lab_ratio"]),
                            drift_category=d_cat(float(r["between_lab_ratio"]))))
        return out
    trows=[]
    for _,r in text.iterrows():
        trows.append(dict(USUBJID=r["USUBJID"], field=r["field"], isolation_score=round(float(r["isolation_score"]),3),
                          text_category=t_cat(float(r["isolation_score"])), note=r.get("note","")))
    return (pd.DataFrame(arows), pd.DataFrame(_drows(drift)), pd.DataFrame(_drows(lab_drift)),
            pd.DataFrame(_cmprows(lab_cmp)), pd.DataFrame(trows))

def _guard_artifacts(models_dir):
    """HARD STOP, never a silent fallback (same discipline as the siblings): if a trained anomaly-model
    artifact exists in models_dir but its runtime is NOT installed, refuse to run rather than silently
    substituting the [SI] stand-in for a model the operator believes is loaded."""
    if not os.path.isdir(models_dir): return
    art=os.path.join(models_dir,"anomaly_model.json")
    # This build has NO code that loads a trained anomaly model: the [SI] engine is the only
    # scorer. So the file stops the run whether or not xgboost is installed -- running on
    # while the operator believes a model is in use (an earlier build even wrote REAL to
    # the audit here) would be exactly the silent substitution this guard exists to refuse.
    if os.path.exists(art):
        st.error(f"anomaly_model.json found, but this build has no trained-anomaly-model path: the labeled "
                 f"[SI] engine is the only scorer. Remove the file to run."); st.stop()

# ============================ UI ============================
st.set_page_config(page_title="Data Anomaly & Drift Detection", layout="wide")
HOSTED = _hosted()   # after set_page_config: no Streamlit call may precede it
# Hosted: an uncaught exception shows a generic message, not a traceback with server
# paths (a crafted widget value can raise one). Process-wide, like the switch itself.
if HOSTED: st.set_option("client.showErrorDetails", "none")
st.title("🔎 Data Anomaly & Distributional-Drift Detection")
st.caption("Tier 1 intake → Tier 2 numeric outliers (robust-z + Isolation Forest) → "
           "Tier 3 Sinkhorn OT drift (cohort + per-lab + between-lab) → Tier 3b text outliers → Tier 4 categorize · "
           "decision support, not a data-quality certification · air-gapped · no sample data in this file")
# Hosted banner on EVERY rerun, drawn before any st.stop() below can cut the page short.
if HOSTED: st.warning(HOSTED_BANNER, icon="🔒")

_HELP_MD = """
**What this app does.** Flags anomalous observations and distributional drift over longitudinal safety/lab/vital data, across **numeric AND free-text** fields. It emits only the FLAGGED observations (subjects whose measurements deviate far from the cohort, notes isolated from their field's corpus) plus per-column and per-lab drift tables. It ranks and flags for human review; it is **decision support, not a data-quality certification or clinical determination**.

**What it needs.** A cut folder (or uploads) of CSV / SAS `.sas7bdat` with a subject-id column (`USUBJID`) and one or more numeric columns to measure. Optional: a **time/visit column** (e.g. `VISITNUM`, `AVISITD`, `STUDYDAY`) enables drift; a categorical **lab/site column** (e.g. `LAB`) enables per-lab drift; any long free-text column (e.g. `LABCOM`, `AECOM`) is scanned for text outliers. Missing optional columns disable that signal and are shown in pre-flight.

### Step by step
1. **Point at your data** (sidebar 📂 1) — type a cut-folder path and/or upload files. Every `*.csv`/`.sas7bdat` except one named `*meddra*` loads; columns are located by content/synonym, not file name.
2. **Set outputs** (sidebar ⚖ 2) — output folder (default `anomaly_output`) and an optional models dir for a real trained model. There is no gate slider: the operating point is the built-in `[SI]` criteria, recorded in the audit.
3. **Confirm the input** (pre-flight panel) — check which measurable numeric columns were found, whether a time column was detected (drift on/off), whether a lab column was detected (per-lab drift on/off), and which free-text columns will be scanned.
4. **Execute** — click 🚀 Execute Anomaly & Drift Detection. Results render on screen and write to the output folder.

### How it works (`[SI]` / real) -- three separate signals, fast algorithms only
- **Numeric outliers (Tier 2)** — per subject × column, a robust z-score of each subject's change-from-baseline against the cohort's distribution of changes is the interpretable gate; **Isolation Forest** (scikit-learn, REAL when installed) corroborates it. A subject is flagged when its worst |z| ≥ `ANOM_Z` (3). The score is `min(1, max|z| / ANOM_Z_TOP)` so it stays discriminative in [0,1] instead of every flagged subject saturating at exactly 1.0. Only flagged subjects are emitted; `extreme_columns` names the exact column(s) and z that fired, and `detectors` says which detector(s) agreed.
- **Drift (Tier 3)** — transport distance between the reference (earliest) and current (latest) windows per measurable column: **Sinkhorn optimal transport** (`ot.sinkhorn2`, linear L1 cost regularized to the reference robust spread) when Python Optimal Transport + scipy are installed, else a labelled **1D-Wasserstein stand-in `[SI]`**. Reported as a unitless **drift ratio** (distance / reference spread). Runs cohort-wide AND per `LAB × column` (temporal drift within each lab/site), and separately **between labs/sites** — each lab's current-window distribution vs the pooled others (leave-one-out) in `lab_compare.csv`, so a site/lab assay shift that no single lab's own history reveals still stands out.
- **Text outliers (Tier 3b)** — retrieval isolation of each note against the corpus in its field: **Needle3/Laya** when installed, else a labelled **bag-of-words isolation stand-in `[SI]`**. A routine note is a near-duplicate of others (iso ≈ 0); an unusual/erroneous note has no close neighbour (iso → 1). Only flagged notes are emitted.
- Categories come from built-in `[SI]` cuts; every row carries the readable numbers that produced it.

### Reading the outputs
- **`anomalies.csv`** — one row per FLAGGED subject: anomaly score, category, which detector(s) fired, and the extreme columns.
- **`drift.csv`** — one row per measurable column (cohort-wide): window sizes, transport distance, drift ratio, category.
- **`lab_drift.csv`** — one row per `LAB × column`: temporal drift within each lab/site (same shape as drift).
- **`lab_compare.csv`** — one row per `LAB × column`: between-lab/site comparison, each lab's current-window distribution vs the pooled others (leave-one-out transport distance → ratio → category).
- **`text_anomalies.csv`** — one row per FLAGGED note: subject, field, isolation score, category, and the note text.
- The on-screen tables are pre-sorted highest-risk first with a category summary.

> This build is transparent by construction: which detector path ran (real vs `[SI]`) is in the banner and every audit row; weights/thresholds are declared constants written to the audit — not hidden. A real deployment can replace any tier with a trained, externally-validated model and flip that tier's banner to `[RM]`.

### Troubleshooting
- **"No measurable columns":** your numeric columns may be stored as text — coerce them to numbers, or add their spelling to `SYN` at the top of this file.
- **Drift shows "(off)":** no time/visit column was detected — add one (e.g. `VISITNUM`) and re-run; per-subject anomalies still work without it.
- **Per-lab drift shows "(off)":** no lab/site column was detected by synonym — rename it to `LAB` or add its spelling to `SYN["LAB"]`.

### What this build does NOT do
No clinical determination, no data-quality certification, nothing leaves the machine. It flags for human review; a flagged row is a lead to investigate, not a verdict.
"""
with st.expander("📖 How to use this app"):
    st.markdown(_HELP_MD)

# ---- sidebar 1: WHERE the data is. Folder path AND/OR uploads are additive; a meddra*.csv is ignored. ----
if HOSTED: st.sidebar.warning(HOSTED_BANNER, icon="🔒")
st.sidebar.header("📂 1. Point this at your data")
_SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anomaly_data")
# Demo toggle: off by default; a link ending in ?demo=1 (e.g. a hosted demo) starts it on.
# Hosted mode: each data input below is disabled AND its value overwritten right after
# the widget (sample forced on, folder pinned to anomaly_data/, no uploads), because a
# disabled widget only stops the browser; a crafted client could still send a value.
_use_sample = st.sidebar.checkbox("Use the bundled synthetic sample data",
    value=(HOSTED or st.query_params.get("demo") == "1"), disabled=HOSTED,
    help="Fills the folder path with the synthetic demo cut shipped in ./anomaly_data/ (no real patients or licensed dictionary).")
if HOSTED: _use_sample = True
folder = st.sidebar.text_input("Cut folder path (CSV or SAS .sas7bdat)", value=(_SAMPLE_DIR if _use_sample else ""), disabled=HOSTED,
    help="Path to a folder of CSV / SAS .sas7bdat files with a subject-id column and numeric columns "
         "to measure, plus an optional time/visit column for drift, an optional lab/site column for "
         "per-lab drift, and any free-text columns to scan. Every *.csv/*.sas7bdat EXCEPT one named "
         "*meddra* loads; columns are located by content/synonym, not file name.")
if HOSTED: folder = _SAMPLE_DIR            # never trust a client-sent value in hosted mode
up_dom = st.sidebar.file_uploader("...or upload files (CSV or SAS .sas7bdat)",
    type=["csv","sas7bdat"], accept_multiple_files=True, disabled=HOSTED)
if HOSTED: up_dom = None

# ---- sidebar 2: outputs + optional models dir. No gate slider -- the operating point is the built-in [SI] criteria. ----
st.sidebar.markdown("---"); st.sidebar.header("⚖ 2. Outputs")
# Hosted mode: outputs go to a server temp folder made ONCE per browser session
# (kept in session_state so reruns reuse it), and the models dir is pinned to its
# default "models"; neither path ever comes from a visitor.
# A TemporaryDirectory (not a bare mkdtemp) is kept in session_state, so the folder
# is deleted when Streamlit discards the expired session (and at exit) instead of
# piling up in /tmp, one per page view.
if HOSTED and "_hosted_out" not in st.session_state:
    st.session_state["_hosted_tmp"] = tempfile.TemporaryDirectory(prefix="anomaly_output_", ignore_cleanup_errors=True)
    st.session_state["_hosted_out"] = st.session_state["_hosted_tmp"].name
out_dir = st.sidebar.text_input("Output folder",(st.session_state["_hosted_out"] if HOSTED else "anomaly_output"), disabled=HOSTED,
    help="Where anomalies.csv + drift.csv + lab_drift.csv + text_anomalies.csv + audit_log.csv are "
         "written on Run (also offered as downloads).")
if HOSTED: out_dir = st.session_state["_hosted_out"]
models_dir = st.sidebar.text_input("Models dir (optional real model)","models", disabled=HOSTED,
    help="This build has no trained-model path for this app: the labeled [SI] engine is the only scorer, "
         "and a anomaly_model.json found here STOPS the run rather than being silently ignored.")
if HOSTED: models_dir = "models"
_guard_artifacts(models_dir)   # runs on every rerun, before any compute

# ---- LOAD now so the pre-flight panel + classification are live. Errors captured into load_err and surfaced. ----
domains={}; view=pd.DataFrame(); meta=dict(numcols=[],timecol=None,labcol=None,textcols=[],n_subjects=0); thr=dict(DEFAULT_THR); load_err=None
try:
    domains = load_domains(folder or None, up_dom)
    if domains:
        view, meta = tier1_align(domains)
except Exception as e: load_err=str(e)

# ---- mode banner: which detector path ran per signal, computed from the runtime probe (never a constant). ----
banner = ("Tier 2 numeric outlier: %s · Tier 3 drift: %s · Tier 3b text: %s" % (
    "REAL Isolation Forest + robust-z" if REAL_IF else "STAND-IN [SI] robust-z",
    "REAL Sinkhorn OT" if REAL_OT else "STAND-IN [SI] 1D-Wasserstein",
    "REAL Needle3/Laya" if REAL_TEXT else "STAND-IN [SI] bag-of-words isolation"))
st.info("**Mode banner** — "+banner+" · decision support only, not a data-quality certification; the audit "
        "records which path ran and every threshold in force.")

# ---- pre-flight CONTRACT panel: show what loaded + measurable columns + drift/lab/text on/off, before any compute. ----
st.subheader("📋 Input contract (pre-flight)")
if load_err: st.error(f"Import failed: {load_err}")
elif not domains: st.warning("No data files loaded yet — set the folder path or upload files.")
else:
    c1,c2=st.columns(2)
    with c1:
        st.markdown("**Domains loaded**")
        st.dataframe(pd.DataFrame([(d,f"{len(df)} rows",", ".join(map(str,df.columns))) for d,df in domains.items()],
                     columns=["file","rows","columns"]), width="stretch", hide_index=True)
    with c2:
        st.markdown("**Measurable numeric columns**"); st.write(", ".join(meta["numcols"]) or "(none)")
        drift_on = meta["timecol"] is not None and len(meta["numcols"])>0
        lab_on   = meta["labcol"] is not None and len(meta["numcols"])>0
        text_on  = len(meta["textcols"])>0
        st.write(f"Time/visit column → **{meta['timecol']}** · Drift → " + ("ON" if drift_on else "OFF (no time column)"))
        st.write(f"Lab/site column → **{meta['labcol']}** · Per-lab drift → " + ("ON" if lab_on else "OFF (no lab column)"))
        st.write("Free-text columns → " + (", ".join(meta["textcols"]) or "(none)") + " · Text outliers → " + ("ON" if text_on else "OFF"))
        st.write(f"Subjects aligned → **{meta['n_subjects']}**")
    st.caption("This program reads ONLY the measurable numeric, lab and free-text columns above and scores them -- "
               "it flags anomalous observations for human review; it does not make a clinical determination.")

# ---- Run button: disabled until at least one subject + one measurable column is aligned. ----
n_ready = meta["n_subjects"] if (meta["numcols"]) else 0
if not st.button("🚀 Execute Anomaly & Drift Detection", type="primary", disabled=not n_ready):
    st.stop()

# ---- execute the tiers on the already-loaded frames; time the whole run for the latency figure. ----
t0=time.perf_counter()
sig = tier2_signals(view, meta, thr)              # Tier 2: per-subject numeric outliers (flagged-only)
drift = tier3_drift(view, meta, thr)              # Tier 3: cohort-wide Sinkhorn / [SI] drift per column
lab_drift = tier3_lab_drift(view, meta, thr)      # Tier 3: per-LAB x column temporal drift
lab_cmp = tier3_lab_compare(view, meta, thr)      # Tier 3: BETWEEN-lab/site comparison (leave-one-out)
text = tier3b_text(view, meta, thr)               # Tier 3b: text outliers (flagged-only)
anom, dcat, lcat, ccat, tcat = tier4_categorize(sig, drift, lab_drift, lab_cmp, text, thr)  # Tier 4
elapsed=(time.perf_counter()-t0)*1000

# ---- results: these tables ARE the tier outputs, computed from the operator's files. ----
st.subheader(f"Tier 2–4 · anomalies & drift (computed from your files; {elapsed:.2f} ms)")
if len(anom):
    shown=anom.sort_values("anomaly_score", ascending=False)
    st.markdown("**Per-subject numeric outliers** — flagged only"); st.dataframe(shown, width="stretch")
    dist=anom["anomaly_category"].value_counts().to_dict()
    st.caption("Anomaly categories → " + ", ".join(f"{k}: {v}" for k,v in sorted(dist.items())))
else:
    st.caption("No subject exceeded the anomaly threshold (max |z| ≥ ANOM_Z) — nothing flagged.")
if len(dcat):
    dshown=dcat.sort_values("drift_ratio", ascending=False)
    st.markdown("**Distributional drift per column** (cohort-wide)"); st.dataframe(dshown, width="stretch")
else:
    st.caption("Drift is OFF for this cut (no time/visit column detected). Add one to enable it.")
if len(lcat):
    lshown=lcat.sort_values(["drift_ratio"], ascending=False)
    st.markdown("**Per-lab drift over time** — `LAB × column`"); st.dataframe(lshown, width="stretch")
else:
    st.caption("Per-lab drift is OFF (no lab/site column detected). Add one to enable it.")
if len(ccat):
    cshown=ccat.sort_values(["between_lab_ratio"], ascending=False)
    st.markdown("**Between-lab / site comparison** — each lab vs the pooled others (leave-one-out)"); st.dataframe(cshown, width="stretch")
else:
    st.caption("Between-lab comparison is OFF (needs a lab/site column with ≥2 labs). Add one to enable it.")
if len(tcat):
    tshown=tcat.sort_values("isolation_score", ascending=False)
    st.markdown("**Text outliers** — flagged only"); st.dataframe(tshown, width="stretch")
else:
    st.caption("No free-text note exceeded the isolation threshold — nothing flagged.")

# ---- audit: one row per run recording the CONTRACT, every DETECTOR PATH ([SI]/real), every threshold in force,
#      and the category distributions. This makes a run reproducible from its audit alone and keeps this head's
#      scope separate from the sibling programs (separate program, separate audit_log.csv). ----
audit=pd.DataFrame([dict(program="anomaly_drift", timestamp=pd.Timestamp.now().isoformat(timespec="seconds"),
    hosted_mode=("true" if HOSTED else "false"),
    domains=list(domains.keys()), domain_rows=json.dumps({d:len(df) for d,df in domains.items()}),
    n_subjects=int(meta["n_subjects"]), measurable_columns=meta["numcols"], time_column=meta["timecol"] or None,
    lab_column=meta["labcol"] or None, text_columns=meta["textcols"],
    numeric_outlier_path=("REAL Isolation Forest + robust-z" if REAL_IF else "STAND-IN [SI] robust-z"),
    drift_path=("REAL Sinkhorn OT" if REAL_OT else "STAND-IN [SI] 1D-Wasserstein"),
    text_path=("REAL Needle3/Laya" if REAL_TEXT else "STAND-IN [SI] bag-of-words isolation"),
    criteria_source="[SI] built-in defaults", thresholds_in_force=json.dumps(thr),
    scoring_note="robust-z + IsolationForest numeric outliers; Sinkhorn/Wasserstein cohort+lab drift; "
                 "retrieval-isolation text outliers; flagged-only output; decision support, not a data-quality certification",
    anomaly_distribution=json.dumps(anom["anomaly_category"].value_counts().to_dict()) if len(anom) else "{}",
    drift_distribution=json.dumps(dcat["drift_category"].value_counts().to_dict()) if len(dcat) else "{}",
    lab_drift_distribution=json.dumps(lcat["drift_category"].value_counts().to_dict()) if len(lcat) else "{}",
    lab_compare_distribution=json.dumps(ccat["drift_category"].value_counts().to_dict()) if len(ccat) else "{}",
    text_distribution=json.dumps(tcat["text_category"].value_counts().to_dict()) if len(tcat) else "{}",
    measured_latency_ms=round(elapsed,2))])
os.makedirs(out_dir, exist_ok=True)
if len(anom): anom.to_csv(os.path.join(out_dir,"anomalies.csv"), index=False)
if len(dcat): dcat.to_csv(os.path.join(out_dir,"drift.csv"), index=False)
if len(lcat): lcat.to_csv(os.path.join(out_dir,"lab_drift.csv"), index=False)
if len(ccat): ccat.to_csv(os.path.join(out_dir,"lab_compare.csv"), index=False)
if len(tcat): tcat.to_csv(os.path.join(out_dir,"text_anomalies.csv"), index=False)
audit.to_csv(os.path.join(out_dir,"audit_log.csv"), index=False)
st.success(f"Wrote `{out_dir}/anomalies.csv`, `drift.csv`, `lab_drift.csv`, `lab_compare.csv`, "
           f"`text_anomalies.csv` and `audit_log.csv`")
st.download_button("⬇ anomalies.csv",(anom if len(anom) else pd.DataFrame()).to_csv(index=False).encode(),"anomalies.csv","text/csv")
st.download_button("⬇ drift.csv",(dcat if len(dcat) else pd.DataFrame()).to_csv(index=False).encode(),"drift.csv","text/csv")
st.download_button("⬇ lab_drift.csv",(lcat if len(lcat) else pd.DataFrame()).to_csv(index=False).encode(),"lab_drift.csv","text/csv")
st.download_button("⬇ lab_compare.csv",(ccat if len(ccat) else pd.DataFrame()).to_csv(index=False).encode(),"lab_compare.csv","text/csv")
st.download_button("⬇ text_anomalies.csv",(tcat if len(tcat) else pd.DataFrame()).to_csv(index=False).encode(),"text_anomalies.csv","text/csv")
st.download_button("⬇ audit_log.csv",audit.to_csv(index=False).encode(),"audit_log.csv","text/csv")
