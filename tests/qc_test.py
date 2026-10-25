"""QC harness: runs all four apps (meddra, phi, risk, anomaly) end-to-end via streamlit AppTest.

Portable -- paths derive from this file's location, so it can live anywhere next to
the apps. Run with a Python that has the app deps installed:
    pip install -r ../requirements.txt && python tests/qc_test.py
Exit code 0 = all checks pass.
"""
import os, re, sys, json, shutil, hashlib, tempfile
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))      # .../biostat_pipeline_apps/tests
APP_DIR = os.path.dirname(HERE)                        # .../biostat_pipeline_apps
SAMPLE = os.path.join(APP_DIR, "sample_data")
SCRATCH = tempfile.mkdtemp(prefix="qc_out_")

from streamlit.testing.v1 import AppTest
from streamlit import config as _stcfg
# the stock error-detail option, read before ANY app runs: hosted mode changes it process-wide (H18)
_ERR0 = _stcfg.get_option("client.showErrorDetails")

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)[:300]) if detail and not cond else ""))

def find(at, kind, label):
    for w in getattr(at, kind):
        if w.label == label: return w
    raise KeyError(f"{kind} '{label}'")

def sha(p):
    with open(p,"rb") as f: return hashlib.sha256(f.read()).hexdigest()[:16]

def expected_scan(folder):
    """Replicate phi_app's content-based discovery so P2 stays correct as the cut grows:
    every non-strictly-numeric column of every non-meddra CSV, keyed '{domain}::{col}'
    with the same stem rule load_domains uses. Plain pd.read_csv matches the app's dtype
    inference exactly, so this set is what the multiselect pre-selects."""
    exp=set()
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(".csv") or "meddra" in f.lower(): continue
        dom=re.sub(r"[_.].*$","",f.lower()).strip()
        df=pd.read_csv(os.path.join(folder,f))
        exp |= {f"{dom}::{c}" for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])}
    return exp

# ---------------------------------------------------------------- meddra T1
out1 = os.path.join(SCRATCH, "meddra_run1"); shutil.rmtree(out1, ignore_errors=True)
at = AppTest.from_file(os.path.join(APP_DIR,"meddra_app.py"), default_timeout=120); at.run()
find(at,"text_input","Cut folder path (domain CSVs)").set_value(SAMPLE).run()
check("M1 no exception on load", not at.exception, [str(e.value) for e in at.exception])
sel = find(at,"selectbox","Verbatim source column (this program reads ONLY this)")
check("M2 verbatim selector populated", sel.value == "ae :: AETERM", sel.value)
md1 = "\n".join(m.value for m in at.markdown)
check("M2b pre-flight shows full hierarchy chain", "Hierarchy → LLT > PT > HLT > HLGT > SOC" in md1, "")
find(at,"text_input","Output folder").set_value(out1).run()
btn = find(at,"button","🚀 Execute Coding QC assist")
check("M3 run button enabled with data+dict", not btn.disabled)
btn.set_value(True).run()
check("M4 no exception on execute", not at.exception, [str(e.value) for e in at.exception])
pdfs = [d.value for d in at.dataframe]
res = next((df for df in pdfs if "rank" in getattr(df,"columns",[])), None)
if res is not None:
    # ae.csv is now the full bulk cut, so the row count scales with its non-blank verbatims
    # (each yields top-3 candidates) -- compute it from the data instead of hard-coding 18.
    _ae = pd.read_csv(os.path.join(SAMPLE,"ae.csv"))
    n_verb = int(_ae["AETERM"].notna().sum() - (_ae["AETERM"].astype(str).str.strip()=="").sum())
    check("M5 results rows = non-blank verbatims x 3 candidates", len(res)==n_verb*3, f"got {len(res)}, expected {n_verb}x3")
    check("M5b results carry HLT/HLGT evidence columns", "HLT" in res.columns and "HLGT" in res.columns and res["HLT"].notna().all() and res["HLGT"].notna().all(), list(res.columns))
    r1 = res[(res["rank"]==1)]
    # KEY (AESEQ) is no longer unique across the bulk cut, so key the worked rows by their
    # VERBATIM text instead -- lowercase 'headache' matches only the worked exact-match row.
    hd = r1[r1["VERBATIM"]=="headache"]
    check("M6 exact-match 'headache' AUTO_CODED", len(hd)==1 and hd.iloc[0]["AECODSTAT"]=="AUTO_COMMIT_TO_SDTM", list(r1.loc[r1["VERBATIM"]=="headache","AECODSTAT"]))
    GAP = {"severe throbbing pain in back of head","feeling lightheaded when standing up",
           "frequent watery bowel movements","marked prolonged heart rhythm interval","rash on forearm"}
    r1gap = r1[r1["VERBATIM"].isin(GAP)]
    check("M7 semantic-gap verbatims FLAGGED (honest [SI])", len(r1gap)==5 and set(r1gap["AECODSTAT"])=={"FLAGGED_FOR_HUMAN_CODER"}, sorted(set(r1gap["AECODSTAT"])))
else:
    check("M5 results table present", False, "no dataframe rendered")
check("M8 ae_coded.csv written", os.path.exists(os.path.join(out1,"ae_coded.csv")))
check("M9 audit_log.csv written", os.path.exists(os.path.join(out1,"audit_log.csv")))

# ---------------------------------------------------------------- meddra T2 determinism
out2 = os.path.join(SCRATCH, "meddra_run2"); shutil.rmtree(out2, ignore_errors=True)
at2 = AppTest.from_file(os.path.join(APP_DIR,"meddra_app.py"), default_timeout=120); at2.run()
find(at2,"text_input","Cut folder path (domain CSVs)").set_value(SAMPLE).run()
find(at2,"text_input","Output folder").set_value(out2).run()
find(at2,"button","🚀 Execute Coding QC assist").set_value(True).run()
c1 = os.path.join(out1,"ae_coded.csv"); c2 = os.path.join(out2,"ae_coded.csv")
check("M10 deterministic across runs (crc32 fix)", sha(c1)==sha(c2), f"{sha(c1)} vs {sha(c2)}")

# ---------------------------------------------------------------- meddra T3 uploaded flat CSV (.copy() bug probe)
updir = os.path.join(SCRATCH, "upload_only"); shutil.rmtree(updir, ignore_errors=True); os.makedirs(updir)
shutil.copy(os.path.join(SAMPLE,"ae.csv"), updir)   # NO dictionary in folder -> must come from upload
out3 = os.path.join(SCRATCH, "meddra_run3")
at3 = AppTest.from_file(os.path.join(APP_DIR,"meddra_app.py"), default_timeout=120); at3.run()
find(at3,"text_input","Cut folder path (domain CSVs)").set_value(updir).run()
fus = [w for w in at3.file_uploader]
check("M11 upload widget present", len(fus)>=2, f"{len(fus)} file_uploaders")
# uploader order: domain csvs first, then meddra flat csv (radio default = Flattened)
med_up = fus[1] if len(fus)>1 else None
if med_up is not None:
    with open(os.path.join(SAMPLE,"meddra_demo.csv"),"rb") as f: content=f.read()
    med_up.upload("meddra_demo.csv", content, "text/csv").run()
    check("M12 no exception after upload", not at3.exception, [str(e.value) for e in at3.exception])
    find(at3,"text_input","Output folder").set_value(out3).run()
    b3 = find(at3,"button","🚀 Execute Coding QC assist")
    check("M13 button enabled with uploaded dict", not b3.disabled)
    if not b3.disabled:
        b3.set_value(True).run()
        check("M14 execute OK with uploaded dict", not at3.exception, [str(e.value) for e in at3.exception])
else:
    check("M12 upload widget found", False)

# ---------------------------------------------------------------- meddra T4 name-only dictionary
nodir = os.path.join(SCRATCH, "name_only"); shutil.rmtree(nodir, ignore_errors=True); os.makedirs(nodir)
shutil.copy(os.path.join(SAMPLE,"ae.csv"), nodir)
with open(os.path.join(nodir,"meddra_names.csv"),"w") as f:
    f.write("llt_name,pt_name\nHeadache,Headache\nMigraine,Migraine\n")
out4 = os.path.join(SCRATCH, "meddra_run4")
at4 = AppTest.from_file(os.path.join(APP_DIR,"meddra_app.py"), default_timeout=120); at4.run()
find(at4,"text_input","Cut folder path (domain CSVs)").set_value(nodir).run()
check("M15 no exception, name-only dict", not at4.exception, [str(e.value) for e in at4.exception])
md = "\n".join(m.value for m in at4.markdown)
check("M16 pre-flight warns name-only routes to human", "name-only" in md, "")
find(at4,"text_input","Output folder").set_value(out4).run()
b4 = find(at4,"button","🚀 Execute Coding QC assist")
if not b4.disabled:
    b4.set_value(True).run()
    dfs4=[d.value for d in at4.dataframe]
    res4 = next((df for df in dfs4 if "rank" in getattr(df,"columns",[])), None)
    if res4 is not None:
        r14 = res4[res4["rank"]==1]
        check("M17 name-only dict forces all FLAGGED", (r14["AECODSTAT"]=="FLAGGED_FOR_HUMAN_CODER").all(), "")

# ---------------------------------------------------------------- meddra T5 missing dictionary error surfaced
nodict = os.path.join(SCRATCH, "no_dict"); shutil.rmtree(nodict, ignore_errors=True); os.makedirs(nodict)
shutil.copy(os.path.join(SAMPLE,"ae.csv"), nodict)
at5 = AppTest.from_file(os.path.join(APP_DIR,"meddra_app.py"), default_timeout=120); at5.run()
find(at5,"text_input","Cut folder path (domain CSVs)").set_value(nodict).run()
errs = "\n".join(e.value for e in at5.error)
check("M18 missing-dict error surfaced plainly", "No MedDRA source found" in errs, errs[:200])

# ---------------------------------------------------------------- meddra T6: .asc release with HLT/HLGT + currency filter
ascdir = os.path.join(SCRATCH, "asc_cut"); shutil.rmtree(ascdir, ignore_errors=True)
os.makedirs(os.path.join(ascdir,"meddra"))
shutil.copy(os.path.join(SAMPLE,"ae.csv"), ascdir)
def wasc(name, header, rows):
    with open(os.path.join(ascdir,"meddra",name),"w") as f:
        f.write(header+"\n"); [f.write("|".join(r)+"\n") for r in rows]
wasc("llt.asc","llt_code|llt_name|pt_code|currency",[("99000001","Headache","99019211","Y"),("99000004","Migraine","99027599","Y")])
wasc("pt.asc","pt_code|pt_name|hlt_code|soc_code|currency",[("99019211","Headache","99030001","99026879","Y"),("99027599","Migraine","99030001","99026879","N")])
wasc("hlt.asc","hlt_code|hlt_name|hlgt_code|currency",[("99030001","Cranial pain","99040001","Y")])
wasc("hlgt.asc","hlgt_code|hlgt_name|soc_code|currency",[("99040001","Cranial and cerebral disorders","99026879","Y")])
wasc("soc.asc","soc_code|soc_name|currency",[("99026879","Nervous system disorders","Y")])
out5 = os.path.join(SCRATCH,"meddra_run_asc"); shutil.rmtree(out5, ignore_errors=True)
at6 = AppTest.from_file(os.path.join(APP_DIR,"meddra_app.py"), default_timeout=120); at6.run()
find(at6,"text_input","Cut folder path (domain CSVs)").set_value(ascdir).run()
md6 = "\n".join(m.value for m in at6.markdown)
check("M19 .asc release auto-found, hierarchy shown", "Hierarchy → LLT > PT > HLT > HLGT > SOC" in md6 and ".asc release in cut folder" in md6, "")
find(at6,"text_input","Output folder").set_value(out5).run()
b6 = find(at6,"button","🚀 Execute Coding QC assist")
check("M20 run button enabled with .asc dict", not b6.disabled)
if not b6.disabled:
    b6.set_value(True).run()
    check("M21 execute OK on .asc path", not at6.exception, [str(e.value) for e in at6.exception])
    coded = pd.read_csv(os.path.join(out5,"ae_coded.csv"))
    check("M22 ae_coded.csv carries HLT/HLGT columns", "HLT" in coded.columns and "HLGT" in coded.columns and coded["HLT"].notna().all(), list(coded.columns))
    r1 = coded[coded["rank"]==1]
    row5 = r1[r1["VERBATIM"]=="headache"]   # key by verbatim text; AESEQ is not unique in the bulk cut
    check("M23 inactive PT dropped by currency filter", len(row5)==1 and row5.iloc[0]["AEDECOD"]=="Headache" and row5.iloc[0]["AECODSTAT"]=="AUTO_COMMIT_TO_SDTM", "")

# ---------------------------------------------------------------- SAS .sas7bdat input (S-checks)
# All four apps accept CSV OR SAS .sas7bdat via an optional pyreadstat reader. We verify the
# routing end-to-end on the coding app: if pyreadstat is installed we stub ONLY its binary parse
# to return real AE data and confirm a .sas7bdat domain loads, classifies by content, and codes;
# otherwise we confirm the app degrades with a clear "install pyreadstat" message (never a silent skip).
try:
    import pyreadstat as _pyrs; HAVE_PYRS=True
except Exception:
    HAVE_PYRS=False
sasdir = os.path.join(SCRATCH,"sas_cut"); shutil.rmtree(sasdir, ignore_errors=True); os.makedirs(sasdir)
open(os.path.join(sasdir,"ae.sas7bdat"),"wb").close()   # placeholder; the reader is stubbed below
shutil.copy(os.path.join(SAMPLE,"meddra_demo.csv"), sasdir)
out_s = os.path.join(SCRATCH,"sas_run"); shutil.rmtree(out_s, ignore_errors=True)
ats = AppTest.from_file(os.path.join(APP_DIR,"meddra_app.py"), default_timeout=120); ats.run()
find(ats,"text_input","Cut folder path (domain CSVs)").set_value(sasdir).run()
if HAVE_PYRS:
    _real_ae = pd.read_csv(os.path.join(SAMPLE,"ae.csv"))
    _pyrs.read_sas7bdat = lambda p: (_real_ae, None)   # stub only the binary parse; routing is real
    find(ats,"text_input","Output folder").set_value(out_s).run()
    ssel = [w for w in ats.selectbox if "Verbatim source" in w.label][0]
    check("SAS1 .sas7bdat domain loads + verbatim found", ssel.value=="ae :: AETERM", ssel.value)
    bs = find(ats,"button","🚀 Execute Coding QC assist")
    if not bs.disabled:
        bs.set_value(True).run()
        check("SAS2 execute OK on .sas7bdat input", not ats.exception, [str(e.value)[:150] for e in ats.exception])
        cs = pd.read_csv(os.path.join(out_s,"ae_coded.csv")) if os.path.exists(os.path.join(out_s,"ae_coded.csv")) else None
        n_verb=int(_real_ae["AETERM"].notna().sum())
        check("SAS3 .sas7bdat codes like CSV (rows = verbatims x 3)", cs is not None and len(cs)==n_verb*3, f"got {0 if cs is None else len(cs)}, expect {n_verb}x3")
else:
    errs="\n".join(e.value for e in ats.error)+"\n"+"\n".join(m.value for m in ats.markdown)
    check("SAS1 no pyreadstat -> clear install message (no silent skip)", "pyreadstat" in errs, errs[:200])

# ---------------------------------------------------------------- phi T6
outp = os.path.join(SCRATCH, "phi_run"); shutil.rmtree(outp, ignore_errors=True)
ap = AppTest.from_file(os.path.join(APP_DIR,"phi_app.py"), default_timeout=120); ap.run()
find(ap,"text_input","Cut folder path (domain CSVs)").set_value(SAMPLE).run()
check("P1 no exception on load", not ap.exception, [str(e.value) for e in ap.exception])
# Content-based discovery: EVERY non-strictly-numeric column is scanned. The expected set is computed
# from the data itself below (replicating phi_app's discovery), so it stays correct as the cut grows --
# including AETERM, which the old suffix/exact-name rule would have MISSED (the whole point of the change).
ms = find(ap,"multiselect","Columns to scan for PHI (this program reads ONLY these)")
# The cut now carries lb/vs/pe + ABNORMAL/CLINSIG columns, so compute the expected scan set
# from the data itself (replicating phi_app's discovery) instead of hard-coding it.
EXPECTED_SCAN=expected_scan(SAMPLE)
check("P2 content-based discovery scans every non-numeric column", set(ms.value)==EXPECTED_SCAN, ms.value)
check("P2b AETERM now scanned (old name-rule missed it)", "ae::AETERM" in set(ms.value), ms.value)
find(ap,"text_input","Output folder").set_value(outp).run()
bp = find(ap,"button","🚀 Execute De-identification review assist")
check("P3 run button enabled", not bp.disabled)
bp.set_value(True).run()
check("P4 no exception on execute", not ap.exception, [str(e.value) for e in ap.exception])
pdfs=[d.value for d in ap.dataframe]
flags = pdfs[1] if len(pdfs)>1 else None   # 0=domains loaded, 1=discovered cols, 2=phi flags...
# locate the phi-flags frame by columns
flags = next((df for df in pdfs if "ENTITY" in getattr(df,"columns",[])), None)
check("P5 phi flags table present", flags is not None and len(flags)>0)
if flags is not None:
    ents = set(zip(flags["FIELD"],flags["ENTITY"]))
    check("P6 name+phone flagged on AE row1", ("AECOM","PERSON_NAME") in ents and ("AECOM","PHONE") in ents, ents)
    check("P7 mosaic PRDSC spans (MRN/DOB/ZIP/INITIALS)", {e for f,e in ents if f=="PRDSC"}=={"MRN","DOB","ZIP","INITIALS"}, ents)
    check("P8 look-alike NOT flagged (Alanine/glucose/Sinus clean)", not any(e in {"PERSON_NAME"} and f=="EGCOM" for f,e in ents) and len(flags[flags["FIELD"]=="EGCOM"])==0, "")
    # robustness on varied data: many BULK AECOM rows (not just the six worked demos) now carry PHI
    n_aecom = flags[flags["FIELD"]=="AECOM"]["ROW"].nunique() if "ROW" in flags.columns else 0
    check("P8b many bulk AECOM rows flagged (robustness on varied data)", n_aecom>=30, f"{n_aecom} distinct AECOM rows flagged")
san = next((df for df in pdfs if "SAN_AECOM" in getattr(df,"columns",[])), None)
check("P9 sanitized ae frame present", san is not None)
if san is not None:
    # Key the worked rows by USUBJID+AESEQ (not iloc) so they stay correct now that ae.csv
    # has 155 rows with the bulk participants appended after the six worked rows.
    def arow(subj,seq): return san[(san["USUBJID"].astype(str)==subj)&(san["AESEQ"]==seq)].iloc[0]
    row1 = arow("SUBJ-3092",1)["SAN_AECOM"]
    check("P10 AE row1 scrubbed exactly", row1=="CRC Note: Patient [REDACTED_PATIENT_NAME] called site cell phone [REDACTED_PHONE] at 10:15 AM.", row1)
    row2 = arow("SUBJ-3092",2)["SAN_AECOM"]
    check("P11 Alanine + glucose survive scrub", "Alanine 50 mg" in row2 and "glucose 120 mg/dL" in row2, row2)
    v6 = arow("SUBJ-5227",6)["SAN_AECOM"]
    check("P12 missing AECOM stays missing (not 'nan')", (not isinstance(v6,str)) and pd.isna(v6), repr(v6))
    worked_flags=[arow(s,q)["AECOM_PHI_FLAG"] for s,q in [("SUBJ-3092",1),("SUBJ-3092",2),("SUBJ-1044",3),("SUBJ-4110",4),("SUBJ-5227",5),("SUBJ-5227",6)]]
    check("P13 worked-row PHI flags Y/Y/N/N/N/N", worked_flags==["Y","Y","N","N","N","N"], worked_flags)
sanp = next((df for df in pdfs if "SAN_PRDSC" in getattr(df,"columns",[])), None)
if sanp is not None:
    pr1 = sanp.iloc[0]["SAN_PRDSC"]
    check("P14 PR mosaic fully scrubbed", "[REDACTED_INITIALS]" in pr1 and "[REDACTED_MRN]" in pr1 and "[REDACTED_DOB]" in pr1 and "[REDACTED_ZIP]" in pr1, pr1)
check("P15 phi_flags.csv + sanitized/ written", os.path.exists(os.path.join(outp,"phi_flags.csv")) and os.path.isdir(os.path.join(outp,"sanitized")))

# ---------------------------------------------------------------- risk app (R-checks)
# The risk app now reads the SAME unified cut as the other two apps (sample_data), not a
# separate safety folder -- one consistent dataset with identical columns throughout.
SAFETY = SAMPLE
outr1 = os.path.join(SCRATCH, "risk_run1"); shutil.rmtree(outr1, ignore_errors=True)
ar = AppTest.from_file(os.path.join(APP_DIR,"risk_app.py"), default_timeout=120); ar.run()
find(ar,"text_input","Cut folder path (safety domains)").set_value(SAFETY).run()
check("R1 no exception on load", not ar.exception, [str(e.value) for e in ar.exception])
# pre-flight renders a domains-loaded table with columns file/domain/rows BEFORE execute
pre = next((df for df in (d.value for d in ar.dataframe)
            if {"file","domain","rows"} <= set(getattr(df,"columns",[]))), None)
check("R2 pre-flight classifies all five safety domains",
      pre is not None and {"ae","lb","eg","vs","pe"} <= set(pre["domain"]), list(getattr(pre,"domain",[])))
find(ar,"text_input","Output folder").set_value(outr1).run()
br = find(ar,"button","🚀 Execute Participant risk screening")
check("R3 run button enabled with safety data", not br.disabled)
br.set_value(True).run()
check("R4 no exception on execute", not ar.exception, [str(e.value) for e in ar.exception])
pdfs=[d.value for d in ar.dataframe]
res = next((df for df in pdfs if "safety_category" in getattr(df,"columns",[])), None)
check("R5 results table present with expected columns",
      res is not None and {"USUBJID","safety_risk_score","safety_category",
                           "discontinuation_risk_score","disc_category","contributing_factors"} <= set(res.columns),
      list(getattr(res,"columns",[])))
# the raw count/severity/fatal columns are internal signals only -- they must NOT be exported
check("R5b dropped n_AE/n_SAE/max_severity/fatal columns not in output",
      res is not None and not ({"n_AE","n_SAE","max_severity","fatal"} & set(res.columns)), list(getattr(res,"columns",[])))
if res is not None:
    check("R6 risk_scores.csv + audit_log.csv written",
          os.path.exists(os.path.join(outr1,"risk_scores.csv")) and os.path.exists(os.path.join(outr1,"audit_log.csv")))
    # No external SAP/protocol file is imported -- scoring uses built-in [SI] criteria, and
    # the audit must record that source (verified via the audit log).
    aud = pd.read_csv(os.path.join(outr1,"audit_log.csv"))
    check("R6b criteria source recorded as [SI] built-in defaults", "[SI] built-in defaults" in str(aud.iloc[0]["criteria_source"]), str(aud.iloc[0]["criteria_source"]))
    # valid ranges for every participant
    check("R7 safety scores in [0,100]", res["safety_risk_score"].between(0,100).all(), "")
    check("R8 disc scores in [0,1]", res["discontinuation_risk_score"].between(0,1).all(), "")
    # all four safety categories present across the bulk cut
    cats=set(res["safety_category"])
    check("R9 all four safety categories present", {"LOW","MODERATE","HIGH","CRITICAL"} <= cats, sorted(cats))
    # The in-browser page's Limits line (tools/sync_browser_apps.py) and docs/evaluation.html give this count.
    check("R9b one row per participant: 52 in the bundled cut (the count the Limits line states)",
          len(res)==52 and res["USUBJID"].is_unique, (len(res), int(res["USUBJID"].nunique())))
    def subj(uid): return res[res["USUBJID"].astype(str)==uid]
    # anchor assertions (clinically-meaningful; each lands with margin in its band)
    check("R10 fatal SUBJ-9015 -> CRITICAL", len(subj("SUBJ-9015"))==1 and subj("SUBJ-9015").iloc[0]["safety_category"]=="CRITICAL", "")
    # The fatal call must be backed by explicit evidence in the row (AEOUTCOME=DIED), not just a bare flag.
    _f9015 = str(subj("SUBJ-9015").iloc[0]["contributing_factors"])
    check("R10b fatality cited WITH its AEOUTCOME evidence", "Fatal" in _f9015 and "AEOUTCOME=DIED" in _f9015, _f9015)
    # A life-threatening SEVERITY that did NOT result in death must NOT be called fatal. The `fatal`
    # column is no longer exported; the evidence lives in contributing_factors, which must lack it.
    check("R10d life-threatening-but-survived SUBJ-9001 is not fatal", "Fatal outcome" not in str(subj("SUBJ-9001").iloc[0]["contributing_factors"]), str(subj("SUBJ-9001").iloc[0]["contributing_factors"]))
    # A fatal outcome must rank at/above EVERY non-fatal participant (death outranks any comorbidity load).
    _f = subj("SUBJ-9015").iloc[0]
    _nf_max = res[res["USUBJID"].astype(str)!="SUBJ-9015"]["safety_risk_score"].max()
    check("R10c fatal ranks at/above every non-fatal participant", _f["safety_category"]=="CRITICAL" and _f["safety_risk_score"]>=_nf_max, f"fatal={_f['safety_risk_score']} vs max_nonfatal={_nf_max}")
    check("R11 multi-system SUBJ-9001 -> CRITICAL", subj("SUBJ-9001").iloc[0]["safety_category"]=="CRITICAL", "")
    check("R12 severe-AE SUBJ-9002 -> HIGH", subj("SUBJ-9002").iloc[0]["safety_category"]=="HIGH", "")
    # lab-driven: SUBJ-9013's dominant signal is an ALT breach
    check("R13 lab-driven SUBJ-9013 cites ALT breach", "ALT" in str(subj("SUBJ-9013").iloc[0]["contributing_factors"]), str(subj("SUBJ-9013").iloc[0]["contributing_factors"]))
    # ECG-driven: SUBJ-9014's signal is QTc
    check("R14 ECG-driven SUBJ-9014 cites QTc", "QTc" in str(subj("SUBJ-9014").iloc[0]["contributing_factors"]), str(subj("SUBJ-9014").iloc[0]["contributing_factors"]))
    # discontinuation categories for anchors
    check("R15 fatal SUBJ-9015 disc HIGH", subj("SUBJ-9015").iloc[0]["disc_category"]=="HIGH", "")
    check("R16 QTc-only SUBJ-9014 disc MODERATE", subj("SUBJ-9014").iloc[0]["disc_category"]=="MODERATE", "")

# determinism: run twice, compare risk_scores.csv hash (pure arithmetic -> bit-reproducible)
outr2 = os.path.join(SCRATCH,"risk_run2"); shutil.rmtree(outr2, ignore_errors=True)
ar2 = AppTest.from_file(os.path.join(APP_DIR,"risk_app.py"), default_timeout=120); ar2.run()
find(ar2,"text_input","Cut folder path (safety domains)").set_value(SAFETY).run()
find(ar2,"text_input","Output folder").set_value(outr2).run()
find(ar2,"button","🚀 Execute Participant risk screening").set_value(True).run()
check("R17 deterministic across runs", sha(os.path.join(outr1,"risk_scores.csv"))==sha(os.path.join(outr2,"risk_scores.csv")), "")

# ---------------------------------------------------------------- risk app (unrecognized wide-format file, R18)
# Regression for the "won't work with mixed numeric+categorical in one file" report: a WIDE longitudinal lab
# file (analytes as column names, no ULN/test-code columns -- e.g. anomaly_data/labs.csv) matches NO domain
# signature and is unrecognized. The app must NOT crash on it, and pre-flight must EXPLAIN why (which
# signatures were looked for) instead of silently dropping the file out of the scan.
wide = os.path.join(SCRATCH, "risk_wide"); shutil.rmtree(wide, ignore_errors=True); os.makedirs(wide)
shutil.copy(os.path.join(APP_DIR, "anomaly_data", "labs.csv"), wide)
ar3 = AppTest.from_file(os.path.join(APP_DIR,"risk_app.py"), default_timeout=120); ar3.run()
find(ar3,"text_input","Cut folder path (safety domains)").set_value(wide).run()
check("R18 no exception loading an unrecognized wide-format file", not ar3.exception, [str(e.value)[:200] for e in ar3.exception])
pre3 = next((df for df in (d.value for d in ar3.dataframe)
             if {"file","domain","rows"} <= set(getattr(df,"columns",[]))), None)
check("R18b pre-flight explains WHY the file is unrecognized",
      pre3 is not None and "why classified this way" in getattr(pre3,"columns",[])
      and any("no signature matched" in str(x) for x in pre3["why classified this way"]),
      list(getattr(pre3,"columns",[])))

# ---------------------------------------------------------------- anomaly app (A-checks)
# The anomaly/drift app reads its OWN longitudinal demo cut (anomaly_data/labs.csv), because drift needs a
# time axis the cross-sectional shared cut lacks. We verify end-to-end: load, execute, and assert the
# injected signals are caught -- ALT is THE drift column (cohort trend) and the three injected per-participant
# outliers rank at/near the top of anomalies. Conditional on `ot`+scipy like the SAS checks: with Python
# Optimal Transport installed we exercise the REAL Sinkhorn path; otherwise the labeled [SI] Wasserstein
# stand-in runs (same output columns, same ordering) and A6 confirms the audit records which path ran.
try:
    import ot as _ot; HAVE_OT=True
except Exception: HAVE_OT=False
try:
    import scipy as _sp; HAVE_SCIPY=True
except Exception: HAVE_SCIPY=False
try:
    import sklearn as _sk; HAVE_SKLEARN=True   # REAL Isolation-Forest numeric-outlier corroborator
except Exception: HAVE_SKLEARN=False
REAL = HAVE_OT and HAVE_SCIPY
ANOM = os.path.join(APP_DIR,"anomaly_data")
outa1 = os.path.join(SCRATCH,"anom_run1"); shutil.rmtree(outa1, ignore_errors=True)
aa = AppTest.from_file(os.path.join(APP_DIR,"anomaly_app.py"), default_timeout=120); aa.run()
find(aa,"text_input","Cut folder path (CSV or SAS .sas7bdat)").set_value(ANOM).run()
check("A1 no exception on load", not aa.exception, [str(e.value) for e in aa.exception])
mda = "\n".join(m.value for m in aa.markdown)
check("A2 pre-flight detects time column + measurable cols", "VISITNUM" in mda and "ALT" in mda, mda[:300])
check("A2b pre-flight detects lab col (per-lab drift ON) + free-text col (text outliers ON)",
      "Per-lab drift → ON" in mda and "Text outliers → ON" in mda, mda[:400])
# labs.csv has 600 rows: 150 participants x 4 visits. The pre-flight count (and the audit's n_subjects) is
# participants, not rows.
check("A2c pre-flight counts participants, not rows (150 in the 600-row demo)",
      "Participants aligned → **150**" in mda, [l for l in mda.splitlines() if "aligned" in l])
find(aa,"text_input","Output folder").set_value(outa1).run()
ba = find(aa,"button","🚀 Execute Central statistical monitoring")
check("A3 run button enabled with longitudinal data", not ba.disabled)
ba.set_value(True).run()
check("A4 no exception on execute", not aa.exception, [str(e.value)[:150] for e in aa.exception])
auda = pd.read_csv(os.path.join(outa1,"audit_log.csv")) if os.path.exists(os.path.join(outa1,"audit_log.csv")) else None
check("A5 audit_log.csv written", auda is not None)
if auda is not None:
    path_ran = str(auda.iloc[0]["drift_path"])
    check("A6 drift path recorded matches runtime ([SI]/real discipline)", ("REAL Sinkhorn" in path_ran)==REAL, path_ran)
    nop = str(auda.iloc[0]["numeric_outlier_path"]) if "numeric_outlier_path" in auda else ""
    check("A6b numeric-outlier path recorded matches runtime", ("Isolation Forest" in nop)==HAVE_SKLEARN, nop)
    tpath = str(auda.iloc[0]["text_path"]) if "text_path" in auda else ""
    check("A6c text path recorded as [SI] bag-of-words (internal pkgs absent here)", "bag-of-words" in tpath, tpath)
    check("A6d audit n_subjects is the participant count (150), not the row count (600)",
          "n_subjects" in auda and int(auda.iloc[0]["n_subjects"])==150, auda.iloc[0].get("n_subjects"))
labf = pd.read_csv(os.path.join(outa1,"lab_drift.csv")) if os.path.exists(os.path.join(outa1,"lab_drift.csv")) else None
cmpf = pd.read_csv(os.path.join(outa1,"lab_compare.csv")) if os.path.exists(os.path.join(outa1,"lab_compare.csv")) else None
txf  = pd.read_csv(os.path.join(outa1,"text_anomalies.csv")) if os.path.exists(os.path.join(outa1,"text_anomalies.csv")) else None
anomf = pd.read_csv(os.path.join(outa1,"anomalies.csv")) if os.path.exists(os.path.join(outa1,"anomalies.csv")) else None
driftf = pd.read_csv(os.path.join(outa1,"drift.csv")) if os.path.exists(os.path.join(outa1,"drift.csv")) else None
check("A7 anomalies + drift + lab_drift + lab_compare + text_anomalies all written",
      anomf is not None and driftf is not None and labf is not None and cmpf is not None and txf is not None, "")
if anomf is not None:
    inj = {"SUBJ-A003","SUBJ-A017","SUBJ-A029"}
    top6 = set(anomf.sort_values("anomaly_score",ascending=False).head(6)["USUBJID"])
    check("A8 all 3 injected outliers in top-6 anomalies", inj <= top6, sorted(inj & top6))
    # flagged-only: every emitted participant is at least MODERATE (no LOW rows leak into the output)
    check("A8b flagged-only output (no LOW-category participants emitted)", int((anomf["anomaly_category"]=="LOW").sum())==0, sorted(set(anomf["anomaly_category"])))
    # The in-browser page's Limits line and docs/evaluation.html say the demo flags the 3 injected outliers plus
    # 1 participant with none injected (SUBJ-A150, MODERATE: a side effect of the injected LAB-C AST shift).
    check("A8c exactly 4 participants flagged: the 3 injected outliers plus SUBJ-A150 at MODERATE (as the Limits line states)",
          set(anomf["USUBJID"])==inj|{"SUBJ-A150"} and len(anomf)==4
          and anomf.loc[anomf["USUBJID"]=="SUBJ-A150","anomaly_category"].tolist()==["MODERATE"],
          anomf[["USUBJID","anomaly_category"]].values.tolist())
    if HAVE_SKLEARN:
        check("A16 numeric outliers cite the IsolationForest detector", anomf["detectors"].astype(str).str.contains("IsolationForest").all(), list(anomf["detectors"]))
if driftf is not None:
    alt = driftf[driftf["column"]=="ALT"]
    check("A9 ALT is the top drift column (cohort trend)", len(alt)==1 and alt.iloc[0]["drift_ratio"]==driftf["drift_ratio"].max(), "")
    others = driftf[~driftf["column"].isin(["ALT"])]
    check("A10 non-ALT columns LOW/MODERATE (no false cohort drift)", set(others["drift_category"]) <= {"LOW","MODERATE"}, sorted(set(others["drift_category"])))
if labf is not None:
    ast_c  = labf[(labf["column"]=="AST")&(labf["lab"]=="LAB-C")]
    ast_ab = labf[(labf["column"]=="AST")&(~labf["lab"].isin(["LAB-C"]))]
    check("A12 per-lab drift: LAB-C x AST stands out (CRITICAL)", len(ast_c)==1 and ast_c.iloc[0]["drift_category"]=="CRITICAL", str(ast_c[["lab","column","drift_ratio","drift_category"]].to_dict("records")))
    check("A13 other labs' AST LOW/MODERATE (site signal isolated)", len(ast_ab)>0 and set(ast_ab["drift_category"]) <= {"LOW","MODERATE"}, sorted(set(ast_ab["drift_category"])))
if cmpf is not None:
    # between-lab/site comparison: LAB-C x AST should be the standout (each lab vs the pooled others), while
    # the other labs' AST stays LOW/MODERATE -- a site that measures differently from everyone else.
    bc  = cmpf[(cmpf["column"]=="AST")&(cmpf["lab"]=="LAB-C")]
    b_ab= cmpf[(cmpf["column"]=="AST")&(~cmpf["lab"].isin(["LAB-C"]))]
    check("A17 between-lab: LAB-C x AST stands out (HIGH/CRITICAL)", len(bc)==1 and bc.iloc[0]["drift_category"] in {"HIGH","CRITICAL"}, str(bc[["lab","column","between_lab_ratio","drift_category"]].to_dict("records")))
    check("A18 between-lab: other labs' AST LOW/MODERATE", len(b_ab)>0 and set(b_ab["drift_category"]) <= {"LOW","MODERATE"}, sorted(set(b_ab["drift_category"])))
if txf is not None:
    inj_text = {"SUBJ-A011","SUBJ-A042","SUBJ-A077"}
    check("A14 text outliers: exactly the 3 injected notes flagged", set(txf["USUBJID"])==inj_text and len(txf)==3, sorted(set(txf["USUBJID"])))
    check("A15 flagged text rows are all in LABCOM with a category", (txf["field"]=="LABCOM").all() and txf["text_category"].isin(["MODERATE","HIGH","CRITICAL"]).all(), list(txf[["USUBJID","field","isolation_score","text_category"]]))

# determinism: run twice, compare anomalies.csv + drift.csv hashes (pure arithmetic -> bit-reproducible)
outa2 = os.path.join(SCRATCH,"anom_run2"); shutil.rmtree(outa2, ignore_errors=True)
aa2 = AppTest.from_file(os.path.join(APP_DIR,"anomaly_app.py"), default_timeout=120); aa2.run()
find(aa2,"text_input","Cut folder path (CSV or SAS .sas7bdat)").set_value(ANOM).run()
find(aa2,"text_input","Output folder").set_value(outa2).run()
find(aa2,"button","🚀 Execute Central statistical monitoring").set_value(True).run()
# determinism now covers every output table that was written (pure arithmetic -> bit-reproducible)
_cmp=[f for f in ["anomalies.csv","drift.csv","lab_drift.csv","lab_compare.csv","text_anomalies.csv"] if os.path.exists(os.path.join(outa1,f))]
check("A11 deterministic across runs", len(_cmp)>=2 and all(sha(os.path.join(outa1,f))==sha(os.path.join(outa2,f)) for f in _cmp), str(_cmp))

# ---------------------------------------------------------------- anomaly app (mixed-upload regression, A19-A20)
# Regression: uploading the LONGITUDINAL labs.csv together with CROSS-SECTIONAL safety files used to crash
# (_change_matrix -> nanargmin on an all-NaN time slice for participants present only in a domain without VISITNUM).
# Build a temp cut mixing both shapes, run end-to-end, and assert NO exception AND that the 3 injected numeric
# outliers are still flagged (the longitudinal signal must survive alongside cross-sectional files).
mixed = os.path.join(SCRATCH, "anom_mixed"); shutil.rmtree(mixed, ignore_errors=True); os.makedirs(mixed)
shutil.copy(os.path.join(ANOM, "labs.csv"), mixed)
for _f in ["ae.csv", "lb.csv", "eg.csv", "vs.csv", "pe.csv"]:
    shutil.copy(os.path.join(SAMPLE, _f), mixed)
outa3 = os.path.join(SCRATCH, "anom_run_mixed"); shutil.rmtree(outa3, ignore_errors=True)
aa3 = AppTest.from_file(os.path.join(APP_DIR, "anomaly_app.py"), default_timeout=120); aa3.run()
find(aa3, "text_input", "Cut folder path (CSV or SAS .sas7bdat)").set_value(mixed).run()
check("A19 mixed longitudinal+cross-sectional upload: no exception on load", not aa3.exception, [str(e.value)[:200] for e in aa3.exception])
find(aa3, "text_input", "Output folder").set_value(outa3).run()
b3 = find(aa3, "button", "\U0001F680 Execute Central statistical monitoring")
check("A19b run button enabled with mixed upload", not b3.disabled)
b3.set_value(True).run()
check("A20 mixed upload: no exception on execute", not aa3.exception, [str(e.value)[:200] for e in aa3.exception])
anomm = pd.read_csv(os.path.join(outa3, "anomalies.csv")) if os.path.exists(os.path.join(outa3, "anomalies.csv")) else None
if anomm is not None:
    inj = {"SUBJ-A003", "SUBJ-A017", "SUBJ-A029"}
    top6 = set(anomm.sort_values("anomaly_score", ascending=False).head(6)["USUBJID"])
    check("A20b mixed upload: 3 injected numeric outliers still flagged in top-6", inj <= top6, sorted(inj & top6))

# ---------------------------------------------------------------- hosted-demo safety mode (H-checks)
# Every app has a hosted mode (ECRF_HOSTED=1, or the Streamlit secret hosted = true; see _hosted() in each
# app) that locks every data input to the bundled synthetic cut, writes outputs to a per-session server
# temp folder and shows a banner. Per app (HM coding, HP PHI, HR risk, HA anomaly; the b/c-suffixed checks
# are coding-app extras for its dictionary inputs):
#   1-3   the LOCAL default is unchanged (no banner, every input live, audit records hosted_mode false)
#   4-11  the hosted view end-to-end (banner, nothing enabled that brings data in, sample cut, run, audit)
#   12-16 a crafted client: widget values are forged by assigning _value/_files directly, which skips
#         AppTest's own disabled guard. Recent Streamlit releases (1.66.1, for one) discard values sent for a
#         disabled widget on the server, so 12-13 test that stock path (the disabled flag with the app's
#         override behind it; only both missing at once fails them), and 14-16 repeat the forgery with that
#         server-side drop switched off (as on a release that trusted the client), so there the app's own
#         overrides are the only defense. HX1 proves a forged value then really reaches a disabled widget,
#         so 14-16 cannot pass vacuously.
#   17    the Output folder is a per-session temp folder: stable across reruns, new for each session.
#   18    hosted mode redacts uncaught-error details (client.showErrorDetails none); a local run leaves it.
#   19    the banners still show when the artifact guard's st.stop() cuts the page short.
#   20    the per-session temp folder is deleted once the session is discarded (no /tmp growth).
#   21    source order (read from the file, since a misplaced line has no runtime symptom on 1.66.1):
#         set_page_config, then HOSTED = _hosted() on the next line, then the main banner, then the sidebar
#         banner as the first sidebar call right before the "📂 1." header, all above every st.stop().
# The switch itself (fail closed: see _hosted() in each app): HS1-HS32 inject secret values through
# AppTest (bool and string forms, and a secrets file with an unrelated key only); HE1-HE8 try other
# ECRF_HOSTED spellings; HF1-HF20 run Streamlit's REAL secrets loader on scratch secrets.toml files,
# malformed ones included, and the ECRF_HOSTED secret that Streamlit copies over the host's own value.
# Every block removes ECRF_HOSTED (and restores the server-side drop, the secrets store and the error
# option) in a finally, and a block that raises is recorded as a FAIL instead of aborting, so later
# checks still run locally. The apps' temp folders land under SCRATCH (tempfile.tempdir points there for
# this section).
import uuid, dataclasses, gc
import streamlit as _st
from streamlit.runtime.secrets import Secrets
from streamlit.runtime.state.session_state import SessionState
HOSTED_BANNER = ("Public demo: synthetic data only. Do not enter or upload real patient data. "
                 "Run locally for real data.")
_SEC0, _SECFILES0 = _st.secrets, _stcfg.get_option("secrets.files")
_REG_WIDGET = getattr(SessionState, "register_widget", None)
def _trust_client(on):
    """on=True: hand register_widget the widget metadata with disabled=False, so Streamlit KEEPS a value a
    client sent for a disabled widget (a release without the server-side drop); the app's own
    'if HOSTED: x = ...' overrides are then the only defense. on=False restores the stock method. If a
    future Streamlit moves this internal hook, the patch is skipped and HX1 fails loudly (never a silent pass)."""
    if _REG_WIDGET is None: return
    if not on: SessionState.register_widget = _REG_WIDGET; return
    def _reg(self, metadata, *a, **k):
        if dataclasses.is_dataclass(metadata) and getattr(metadata, "disabled", False):
            metadata = dataclasses.replace(metadata, disabled=False)
        return _REG_WIDGET(self, metadata, *a, **k)
    SessionState.register_widget = _reg
def _dis(w): return bool(getattr(w.proto, "disabled", False))
def _banners(blk): return [w for w in blk.warning if w.value == HOSTED_BANNER]
def _opt(at, kind, label): return next((w for w in getattr(at, kind) if w.label == label), None)
def _forge_text(at, label, v): find(at, "text_input", label)._value = v      # bypasses _assert_can_interact
def _forge_files(w, name, content): w._files = [(str(uuid.uuid4()), name, content, "text/csv")]   # (file_id, name, bytes, mime)
def _md(at): return "\n".join(m.value for m in at.markdown)
def _stems(folder):
    return {re.sub(r"[_.].*$","",f.lower()) for f in os.listdir(folder) if f.lower().endswith(".csv") and "meddra" not in f.lower()}
def _loaded(at):
    """Every domain/file name the app reports as loaded: the pre-flight 'Domains loaded' table plus the
    coding/PHI selector options ('{domain} :: col' / '{domain}::col'), which list a domain even when the
    table is not drawn (e.g. a cut without a dictionary)."""
    s=set()
    for d in at.dataframe:
        v=d.value; cols=set(getattr(v,"columns",[]))
        if {"domain","size"} <= cols or {"file","rows"} <= cols:
            for c in ("domain","file"):
                if c in cols: s |= {str(x).lower() for x in v[c]}
    for w in list(at.selectbox)+list(at.multiselect):
        s |= {re.split(r"\s*::", str(o))[0].strip().lower() for o in (w.options or [])}
    return s
def _audit(d):
    p = os.path.join(d,"audit_log.csv") if d else ""
    return pd.read_csv(p) if p and os.path.exists(p) else None
def _hm_ok(aud, want):
    """hosted_mode == want, compared as a lowercase string (pandas parses true/false as bool), and placed
    right after timestamp as the spec says."""
    if aud is None or "hosted_mode" not in aud.columns or "timestamp" not in aud.columns: return False
    cols=list(aud.columns)
    return str(aud.iloc[0]["hosted_mode"]).strip().lower()==want and cols.index("hosted_mode")==cols.index("timestamp")+1
def _hm_detail(aud): return None if aud is None else (list(aud.columns)[:4], aud.iloc[0].get("hosted_mode"))

# Decoys under SCRATCH: a complete alternative cut (and a longitudinal one for the anomaly app), a models
# dir holding every guarded artifact name (it would trip _guard_artifacts if a forged path got through),
# and the redirected temp root the apps' per-session Output folders are made in.
HDECOY = os.path.join(SCRATCH,"hosted_decoy"); shutil.rmtree(HDECOY, ignore_errors=True)
for _sub,_src in (("cut",os.path.join(SAMPLE,"ae.csv")),("labs",os.path.join(ANOM,"labs.csv"))):
    os.makedirs(os.path.join(HDECOY,_sub)); shutil.copy(_src, os.path.join(HDECOY,_sub,"decoyfolder.csv"))
shutil.copy(os.path.join(SAMPLE,"meddra_demo.csv"), os.path.join(HDECOY,"cut"))
os.makedirs(os.path.join(HDECOY,"models"))
# Every artifact name a guard looks for (the coding/PHI real-path layout keeps the model weights in
# needle3/ and laya/ subfolders of the models dir).
GUARD_ARTS = ("meddra_coder.json",os.path.join("needle3","needle3.cact"),os.path.join("laya","model.safetensors"),
              "phi_token_classifier.json","risk_model.json","anomaly_model.json")
def _touch_arts(models):
    for _art in GUARD_ARTS:
        os.makedirs(os.path.dirname(os.path.join(models,_art)), exist_ok=True); open(os.path.join(models,_art),"w").close()
_touch_arts(os.path.join(HDECOY,"models"))
# A guard fires with "<artifact> present but <runtime> not installed" (coding/PHI) or, for an app with no
# trained-model path at all (risk/anomaly), "<artifact> found, but this build has no trained-... path".
def _guard_msgs(at): return [e.value for e in at.error if "present but" in e.value or "found, but" in e.value]
HTMP = os.path.join(SCRATCH,"hosted_tmp"); os.makedirs(HTMP, exist_ok=True)
SRC_AE = os.path.join(SAMPLE,"ae.csv"); SRC_LABS = os.path.join(ANOM,"labs.csv")
ASC_RADIO = "ASCII release (llt/pt/hlt/hlgt/soc.asc)"
ASC_LABEL = "Folder with llt.asc / pt.asc / hlt.asc / hlgt.asc / soc.asc"
DICT_UP = "Upload flattened MedDRA CSV"
HAPPS = [
    dict(c="M", app="coding", file="meddra_app.py", folder="Cut folder path (domain CSVs)",
         up="...or upload domain files (CSV or SAS .sas7bdat)", models="Models dir (optional real weights)",
         btn="🚀 Execute Coding QC assist", out="meddra_output", sample=SAMPLE, local_run=out1,
         decoy="cut", src=SRC_AE, pre="verbatim selector = 'ae :: AETERM'"),
    dict(c="P", app="PHI", file="phi_app.py", folder="Cut folder path (domain CSVs)",
         up="...or upload domain files (CSV or SAS .sas7bdat)", models="Models dir (optional real weights)",
         btn="🚀 Execute De-identification review assist", out="phi_output", sample=SAMPLE, local_run=outp,
         decoy="cut", src=SRC_AE, pre="PHI scan set = expected_scan(sample)"),
    dict(c="R", app="risk", file="risk_app.py", folder="Cut folder path (safety domains)",
         up="...or upload safety files (CSV or SAS .sas7bdat)", models="Models dir (no trained model in this build)",
         btn="🚀 Execute Participant risk screening", out="risk_output", sample=SAMPLE, local_run=outr1,
         decoy="cut", src=SRC_AE, pre="pre-flight classifies ae/lb/eg/vs/pe"),
    dict(c="A", app="anomaly", file="anomaly_app.py", folder="Cut folder path (CSV or SAS .sas7bdat)",
         up="...or upload files (CSV or SAS .sas7bdat)", models="Models dir (no trained model in this build)",
         btn="🚀 Execute Central statistical monitoring", out="anomaly_output", sample=ANOM, local_run=outa1,
         decoy="labs", src=SRC_LABS, pre="pre-flight detects VISITNUM + ALT"),
]
def _preflight(c, at):
    """App-specific proof that the bundled sample cut loaded: (ok, detail)."""
    if c=="M":
        v=find(at,"selectbox","Verbatim source column (this program reads ONLY this)").value; return v=="ae :: AETERM", v
    if c=="P":
        v=set(find(at,"multiselect","Columns to scan for PHI (this program reads ONLY these)").value); e=expected_scan(SAMPLE)
        return v==e, sorted(v ^ e)
    if c=="R":
        pre=next((d.value for d in at.dataframe if {"file","domain","rows"} <= set(getattr(d.value,"columns",[]))), None)
        return pre is not None and {"ae","lb","eg","vs","pe"} <= set(pre["domain"]), list(getattr(pre,"domain",[]))
    # the pre-flight lines themselves: the How-to-use text also mentions VISITNUM, so a bare substring
    # test would pass without the cut
    ms=[m.value for m in at.markdown]; i=ms.index("**Measurable numeric columns**") if "**Measurable numeric columns**" in ms else -1
    nums=ms[i+1].split(", ") if 0 <= i < len(ms)-1 else []
    return any(m.startswith("Time/visit column → **VISITNUM**") for m in ms) and "ALT" in nums, (nums, [m for m in ms if m.startswith("Time/visit")])
def _view(at, A):
    """('hosted' | 'local' | 'error' | 'mixed', detail) for one finished run. hosted = both banners, every
    uploader and the folder disabled, the folder pinned to the sample cut; local = no banner, uploaders and
    folder enabled, folder empty (the untouched default)."""
    ups=list(at.file_uploader); fo=find(at,"text_input",A["folder"])
    d=dict(exc=[str(e.value)[:80] for e in at.exception], banners=(len(_banners(at.main)),len(_banners(at.sidebar))),
           ups=[_dis(u) for u in ups], folder=(fo.value,_dis(fo)))
    if at.exception: return "error", d
    if (len(_banners(at.main))==1 and len(_banners(at.sidebar))==1 and ups and all(_dis(u) for u in ups) and _dis(fo)
            and os.path.realpath(fo.value or "")==os.path.realpath(A["sample"])): return "hosted", d
    if not _banners(at) and ups and not any(_dis(u) for u in ups) and not _dis(fo) and fo.value=="": return "local", d
    return "mixed", d
def _order(path):
    """(ok, detail): the spec's placement rules, read from the source (comments stripped; none of the
    lines tested holds a '#' inside a string)."""
    L=[l.split("#",1)[0] for l in open(path, encoding="utf-8").read().splitlines()]
    def first(s, start=0): return next((i for i in range(start, len(L)) if s in L[i]), -1)
    cfg=first("st.set_page_config("); h=first("HOSTED = _hosted()"); mb=first('if HOSTED: st.warning(HOSTED_BANNER, icon="🔒")')
    sb=first('if HOSTED: st.sidebar.warning(HOSTED_BANNER, icon="🔒")'); s1=first("st.sidebar.", max(cfg,0))
    guard=first("_guard_artifacts(models_dir)", max(cfg,0)+1)          # the call (the def sits above the UI)
    stops=[i for i in range(max(cfg,0), len(L)) if "st.stop()" in L[i]]
    nxt=next((L[i].strip() for i in range(sb+1, len(L)) if L[i].strip()), "") if sb >= 0 else ""
    ok=(cfg >= 0 and h==cfg+1 and cfg < mb < sb < guard and s1==sb and nxt.startswith('st.sidebar.header("📂 1.')
        and len(stops) >= 1 and all(sb < s for s in stops))
    return ok, dict(set_page_config=cfg, HOSTED=h, main_banner=mb, sidebar_banner=sb, first_sidebar=s1, guard=guard, stops=stops, after_sidebar_banner=nxt[:40])
def _real_secrets(body, sp, host_env=None):
    """Point Streamlit's REAL secrets loader at secrets file `sp` holding `body`, the way a fresh server sees
    it: a new secrets store (file watchers off), the host's ECRF_HOSTED (None: unset), and the server's own
    start-up load done first, which is when Streamlit copies root-level secrets into os.environ. Returns
    what that load reported; _restore_secrets() undoes all of it."""
    with open(sp,"w") as f: f.write(body)
    os.environ.pop("ECRF_HOSTED", None)
    if host_env is not None: os.environ["ECRF_HOSTED"]=host_env
    _stcfg.set_option("secrets.files", [sp]); sec=Secrets(); sec._file_watchers_installed=True; _st.secrets=sec
    return sec.load_if_toml_exists()
def _restore_secrets():
    try: _st.secrets._reset()            # drops what the load copied into os.environ
    except Exception: pass
    _st.secrets=_SEC0; _stcfg.set_option("secrets.files", _SECFILES0)
    for k in ("ECRF_HOSTED","some_api_key","hosted"): os.environ.pop(k, None)

_saved_tmp = tempfile.tempdir; tempfile.tempdir = HTMP
try:
    # HX1: the forgery harness itself. A throwaway app with a disabled text_input + file_uploader echoes
    # what it received; with the server-side drop off, the forged values must come through.
    _CTRL = ('import streamlit as st\n'
             't = st.text_input("t", "safe", disabled=True)\n'
             'u = st.file_uploader("u", accept_multiple_files=True, disabled=True)\n'
             'st.write(f"t={t} u={len(u or [])}")\n')
    mdx = ""
    _trust_client(True)
    try:
        ax = AppTest.from_string(_CTRL, default_timeout=120); ax.run()
        find(ax,"text_input","t")._value = "forged"; _forge_files(find(ax,"file_uploader","u"), "x.csv", b"a\n1\n"); ax.run()
        mdx = _md(ax)
    except Exception as e: mdx = "raised: "+repr(e)
    finally: _trust_client(False)
    check("HX1 control: with the server-side drop off, a forged value reaches a disabled text_input + file_uploader", "t=forged u=1" in mdx, mdx)

    for A in HAPPS:
        c=A["c"]; P=f"H{c}"; path=os.path.join(APP_DIR,A["file"]); exp=_stems(A["sample"])
        dsrc=open(A["src"],"rb").read(); want_ups={A["up"]} | ({DICT_UP} if c=="M" else set())
        # ---- 1-3: local default (nothing set) must look exactly as before ----
        os.environ.pop("ECRF_HOSTED", None); _stcfg.set_option("client.showErrorDetails", _ERR0); err_l=err_h=None
        try:
            al = AppTest.from_file(path, default_timeout=120); al.run(); err_l=_stcfg.get_option("client.showErrorDetails")
            ups=list(al.file_uploader); box=find(al,"checkbox","Use the bundled synthetic sample data")
            fo=find(al,"text_input",A["folder"]); od=find(al,"text_input","Output folder"); mdl=find(al,"text_input",A["models"])
            check(f"{P}1 local default unchanged: no banner, sample box unticked, folder empty, every uploader and path input enabled",
                  not al.exception and not _banners(al) and box.value is False and not _dis(box) and fo.value=="" and not _dis(fo)
                  and want_ups <= {u.label for u in ups} and not any(_dis(u) for u in ups)
                  and od.value==A["out"] and not _dis(od) and mdl.value=="models" and not _dis(mdl),
                  dict(exc=[str(e.value)[:80] for e in al.exception], banner=len(_banners(al)), box=(box.value,_dis(box)), folder=(fo.value,_dis(fo)),
                       ups=[(u.label,_dis(u)) for u in ups], out=(od.value,_dis(od)), models=(mdl.value,_dis(mdl))))
            ad = AppTest.from_file(path, default_timeout=120); ad.query_params["demo"]="1"; ad.run()
            fo=find(ad,"text_input",A["folder"]); box=find(ad,"checkbox","Use the bundled synthetic sample data")
            check(f"{P}2 local ?demo=1 fills the folder with the sample path (no banner, inputs still editable)",
                  not ad.exception and not _banners(ad) and os.path.realpath(fo.value or "")==os.path.realpath(A["sample"])
                  and box.value is True and not _dis(box) and not _dis(fo), (fo.value, _dis(fo), box.value))
            aud=_audit(A["local_run"])
            check(f"{P}3 local audit (earlier local run in this harness) records hosted_mode false, right after timestamp", _hm_ok(aud,"false"), _hm_detail(aud))
        except Exception as e: check(f"{P} local block raised", False, repr(e))

        # ---- 4-11: hosted view end-to-end ----
        hout=out_v=out_after=fout=None
        os.environ["ECRF_HOSTED"]="1"
        try:
            ah = AppTest.from_file(path, default_timeout=120); ah.run(); err_h=_stcfg.get_option("client.showErrorDetails")
            check(f"{P}4 hosted: no exception on load", not ah.exception, [str(e.value)[:200] for e in ah.exception])
            side0 = ah.sidebar.children.get(0)
            check(f"{P}5 hosted: exact banner on the main page and as the first sidebar element",
                  len(_banners(ah.main))==1 and getattr(side0,"value",None)==HOSTED_BANNER and all(w.icon=="🔒" for w in _banners(ah)),
                  [w.value for w in ah.warning])
            ups=list(ah.file_uploader)
            check(f"{P}6 hosted: no file_uploader enabled ({'domain + dictionary' if c=='M' else 'domain'} uploader present, disabled)",
                  want_ups <= {u.label for u in ups} and all(_dis(u) for u in ups), [(u.label,_dis(u)) for u in ups])
            box=find(ah,"checkbox","Use the bundled synthetic sample data"); fo=find(ah,"text_input",A["folder"])
            od=find(ah,"text_input","Output folder"); mdl=find(ah,"text_input",A["models"])
            check(f"{P}7 hosted: folder path, models dir and Output folder disabled; sample box locked on",
                  _dis(fo) and _dis(mdl) and _dis(od) and box.value is True and _dis(box),
                  dict(folder=_dis(fo), models=_dis(mdl), out=_dis(od), box=(box.value,_dis(box))))
            check(f"{P}8 hosted: folder value is the bundled sample folder ({os.path.basename(A['sample'])}), models dir 'models'",
                  os.path.realpath(fo.value or "")==os.path.realpath(A["sample"]) and mdl.value=="models", (fo.value, mdl.value))
            ok,det=_preflight(c, ah); t=_loaded(ah)
            check(f"{P}9 hosted: the sample cut loads ({A['pre']})", ok and exp <= t, (det, sorted(t)))
            if c=="M": check("HM9b hosted: dictionary label names the bundled meddra_demo.csv", "meddra_demo.csv" in _md(ah), _md(ah)[:300])
            hout = ah.session_state["_hosted_out"] if "_hosted_out" in ah.session_state else None; out_v = od.value
            b=_opt(ah,"button",A["btn"])
            if b is not None and not b.disabled: b.set_value(True).run()
            check(f"{P}10 hosted: execute OK and the banner is still shown after the run",
                  b is not None and not b.disabled and not ah.exception and len(_banners(ah.main))==1 and len(_banners(ah.sidebar))==1,
                  dict(button=None if b is None else b.disabled, exc=[str(e.value)[:150] for e in ah.exception], banners=len(_banners(ah))))
            out_after = find(ah,"text_input","Output folder").value; aud=_audit(out_after)
            check(f"{P}11 hosted: audit_log.csv in the disabled temp Output folder records hosted_mode true", _hm_ok(aud,"true"), (out_after, _hm_detail(aud)))
            if c=="M":
                # the radio stays live in hosted mode; the .asc input it reveals must still be locked
                find(ah,"radio","Source shape").set_value(ASC_RADIO).run()
                asc=_opt(ah,"text_input",ASC_LABEL); mdm=_md(ah)
                check("HM11b hosted: ASCII radio reveals a disabled .asc folder input, dictionary stays meddra_demo.csv",
                      not ah.exception and asc is not None and _dis(asc) and "meddra_demo.csv" in mdm and all(_dis(u) for u in ah.file_uploader),
                      (None if asc is None else _dis(asc), mdm[:200]))
        except Exception as e: check(f"{P} hosted block raised", False, repr(e))
        finally: os.environ.pop("ECRF_HOSTED", None); _stcfg.set_option("client.showErrorDetails", _ERR0)
        check(f"{P}18 hosted: uncaught errors show no details (client.showErrorDetails none); a local run leaves the option as it was",
              err_l==_ERR0 and err_h=="none", dict(stock=_ERR0, local=err_l, hosted=err_h))

        # ---- 12-16: crafted client (stock Streamlit first, then with the server-side drop off) ----
        dout=os.path.join(HDECOY,f"out_{c}"); shutil.rmtree(dout, ignore_errors=True)
        os.environ["ECRF_HOSTED"]="1"
        try:
            af = AppTest.from_file(path, default_timeout=120); af.run()
            def _forge(at):
                _forge_text(at, A["folder"], os.path.join(HDECOY,A["decoy"]))
                _forge_files(find(at,"file_uploader",A["up"]), "decoyupload.csv", dsrc)
            _forge(af); af.run(); t=_loaded(af)
            check(f"{P}12 crafted client, stock Streamlit (disabled flag plus app override, AppTest guard bypassed): forged folder value dropped, only the sample loads",
                  not af.exception and exp <= t and "decoyfolder" not in t, sorted(t))
            check(f"{P}13 crafted client, stock Streamlit (disabled flag plus app override, AppTest guard bypassed): forged domain upload dropped",
                  not af.exception and exp <= t and "decoyupload" not in t, sorted(t))
            _trust_client(True)
            _forge(af)   # the tree is rebuilt on every run, so forge the new widgets
            find(af,"checkbox","Use the bundled synthetic sample data")._value = False
            if c=="M": _forge_files(find(af,"file_uploader",DICT_UP), "decoydict.csv", b"llt_name,pt_name\nHeadache,Headache\n")
            _forge_text(af,"Output folder",dout)
            af.run(); t=_loaded(af)
            # the unticked box alone, in a fresh session: the folder override hides a missing box override from
            # the data, but not from the folder field, whose default would flip to "" (shown empty, sample loaded)
            ab = AppTest.from_file(path, default_timeout=120); ab.run()
            find(ab,"checkbox","Use the bundled synthetic sample data")._value = False; ab.run()
            fo14 = find(ab,"text_input",A["folder"]).value; ab = None
            check(f"{P}14 crafted client, server-side drop off: forged folder value and unticked sample box ignored (the box alone leaves the folder field on the sample)",
                  not af.exception and exp <= t and "decoyfolder" not in t and os.path.realpath(fo14 or "")==os.path.realpath(A["sample"]), (sorted(t), fo14))
            check(f"{P}15 crafted client, server-side drop off: forged domain upload ignored",
                  not af.exception and exp <= t and "decoyupload" not in t, sorted(t))
            if c=="M":
                mdm=_md(af)
                check("HM15b crafted client, server-side drop off: forged dictionary upload ignored (meddra_demo.csv kept)",
                      "meddra_demo.csv" in mdm and "uploaded flattened CSV" not in mdm, mdm[:300])
            fout = af.session_state["_hosted_out"] if "_hosted_out" in af.session_state else None
            b=_opt(af,"button",A["btn"])
            if b is not None and not b.disabled: b.set_value(True).run()
            ran = b is not None and not b.disabled and not af.exception; aud=_audit(fout)
            if c=="M":
                find(af,"radio","Source shape").set_value(ASC_RADIO).run()
                _forge_text(af, ASC_LABEL, os.path.join(ascdir,"meddra")); af.run(); mdm=_md(af)   # a real .asc release (M19)
                check("HM15c crafted client, server-side drop off: forged .asc folder ignored (meddra_demo.csv kept)",
                      not af.exception and "meddra_demo.csv" in mdm and ".asc release @" not in mdm, mdm[:300])
            # the models dir is forged LAST: if it got through, the artifact guard stops every later rerun
            _forge_text(af, A["models"], os.path.join(HDECOY,"models")); af.run()
            guard = _guard_msgs(af)
            check(f"{P}16 crafted client, server-side drop off: forged Output folder + models dir ignored (outputs only in the session temp folder)",
                  ran and not guard and not af.exception and not os.path.exists(dout)
                  and _hm_ok(aud,"true") and "decoy" not in aud.to_csv(index=False).lower(),
                  dict(ran=ran, guard=guard, wrote_decoy=os.path.exists(dout), audit=_hm_detail(aud)))
        except Exception as e: check(f"{P} crafted-client block raised", False, repr(e))
        finally:
            _trust_client(False); os.environ.pop("ECRF_HOSTED", None); _stcfg.set_option("client.showErrorDetails", _ERR0)
        check(f"{P}17 hosted: Output folder is a per-session server temp folder (stable across reruns, new per session)",
              hout is not None and fout is not None and out_v==hout==out_after and fout!=hout and os.path.isdir(hout)
              and os.path.dirname(hout)==HTMP and os.path.basename(hout).startswith(A["out"]+"_"), (out_v, hout, out_after, fout))

        # ---- 19-20: the artifact guard's st.stop() keeps the banners; the temp folder goes with its session ----
        gdir=os.path.join(HDECOY,f"guard_{c}"); os.makedirs(os.path.join(gdir,"models"), exist_ok=True); cwd0=os.getcwd()
        _touch_arts(os.path.join(gdir,"models"))
        os.environ["ECRF_HOSTED"]="1"
        try:
            os.chdir(gdir)   # hosted mode pins models_dir to the cwd-relative "models", here full of guarded artifacts
            ag = AppTest.from_file(path, default_timeout=120); ag.run()
            guard=_guard_msgs(ag)
            check(f"{P}19 hosted: the artifact guard's st.stop() still leaves both banners on the page",
                  bool(guard) and len(_banners(ag.main))==1 and len(_banners(ag.sidebar))==1,
                  dict(guard=guard or "did not fire (is the runtime installed?)", banners=(len(_banners(ag.main)),len(_banners(ag.sidebar)))))
            os.chdir(cwd0); ag=None
            ac = AppTest.from_file(path, default_timeout=120); ac.run()
            cout = ac.session_state["_hosted_out"] if "_hosted_out" in ac.session_state else None
            cex = cout is not None and os.path.isdir(cout)
            ac = None; gc.collect()   # what Streamlit does when it discards an expired session's state
            check(f"{P}20 hosted: the per-session temp folder is deleted once the session is discarded",
                  cex and not os.path.exists(cout), dict(folder=cout, existed=cex, after=cout is not None and os.path.exists(cout)))
        except Exception as e: check(f"{P} guard/cleanup block raised", False, repr(e))
        finally:
            os.chdir(cwd0); os.environ.pop("ECRF_HOSTED", None); _stcfg.set_option("client.showErrorDetails", _ERR0)
        ok,det=_order(path)
        check(f"{P}21 source order: HOSTED right after set_page_config, both banners above every st.stop(), sidebar banner first", ok, det)

    # ---- HS1-HS32: the Streamlit-secret switch, values injected through AppTest (env var unset) ----
    # (value, tag, hosted expected); None = the secrets file holds only an unrelated key (AppTest swaps
    # st.secrets in only when its dict is non-empty, so that case still exercises a loaded store).
    HS_CASES = [(True,"true",True), (False,"false",False), ("true",'"true" (a string)',True), (" Yes ",'" Yes "',True),
                ("on",'"on" (fails closed)',True), ("false",'"false" (a string)',False), ("0",'"0"',False),
                (None,"absent (only an unrelated key in the file)",False)]
    os.environ.pop("ECRF_HOSTED", None)
    for i,(val,tag,want) in enumerate(HS_CASES):
        for j,A in enumerate(HAPPS):
            n=f"HS{i*len(HAPPS)+j+1} {A['app']} app: secret hosted = {tag} (env var unset)"
            try:
                s = AppTest.from_file(os.path.join(APP_DIR,A["file"]), default_timeout=120)
                if val is None: s.secrets["some_api_key"]="x"
                else: s.secrets["hosted"]=val
                s.run(); v,d=_view(s,A)
                if want: check(n+" shows the banner and disables every uploader", v=="hosted", (v,d))
                else: check(n+" keeps local behavior (no banner, uploaders and folder enabled, folder empty)", v=="local", (v,d))
            except Exception as e: check(n+" block raised", False, repr(e))
            finally: os.environ.pop("ECRF_HOSTED", None); _stcfg.set_option("client.showErrorDetails", _ERR0)

    # ---- HE1-HE8: other ECRF_HOSTED spellings. Anything but empty/0/false/no/off locks (fails closed). ----
    k=0
    for A in HAPPS:
        for want,vals in (("hosted",[" True ","yes","on","2"]), ("local",["0"," false ","no","OFF"])):
            k+=1; res=[]
            for v in vals:
                os.environ["ECRF_HOSTED"]=v
                try: e=AppTest.from_file(os.path.join(APP_DIR,A["file"]), default_timeout=120); e.run(); res.append((v,)+_view(e,A))
                except Exception as ex: res.append((v,"raised",repr(ex)))
                finally: os.environ.pop("ECRF_HOSTED", None); _stcfg.set_option("client.showErrorDetails", _ERR0)
            check(f"HE{k} {A['app']} app: ECRF_HOSTED = " + ", ".join(repr(v) for v in vals)
                  + (" each lock the app (banner, inputs disabled)" if want=="hosted" else " each keep the local view"),
                  all(r[1]==want for r in res), [r for r in res if r[1]!=want])

    # ---- HF1-HF20: Streamlit's REAL secrets loader on scratch secrets.toml files ----
    # (tag, file body, host ECRF_HOSTED, what the start-up load must report, hosted expected). The load
    # result is asserted too, so a case cannot pass because the file was not what it claims to be.
    HSEC=os.path.join(SCRATCH,"hosted_secrets"); os.makedirs(HSEC, exist_ok=True)
    HF_CASES = [("'hosted = true' (valid)", "hosted = true\n", None, True, True),
                ("'hosted = True' (capital T: does not parse)", "hosted = True\n", None, False, True),
                ("'hosted = true' plus a bad line (does not parse)", "hosted = true\nAPI_KEY = abc\n", None, False, True),
                ("an unrelated key only (valid)", 'some_api_key = "x"\n', None, True, False),
                ("'ECRF_HOSTED = \"0\"', copied by Streamlit over the host's ECRF_HOSTED=1", 'ECRF_HOSTED = "0"\n', "1", True, True)]
    k=0
    for tag,body,henv,want_load,want in HF_CASES:
        for A in HAPPS:
            k+=1; n=(f"HF{k} {A['app']} app, real secrets loader, secrets.toml = {tag}: "
                     + ("hosted view (banner, inputs locked)" if want else "local view"))
            try:
                loaded=_real_secrets(body, os.path.join(HSEC,f"secrets_{k}.toml"), henv); env1=os.environ.get("ECRF_HOSTED")
                s = AppTest.from_file(os.path.join(APP_DIR,A["file"]), default_timeout=120); s.run(); v,d=_view(s,A)
                check(n, loaded is want_load and (henv is None or env1=="0") and v==("hosted" if want else "local"),
                      dict(loaded=loaded, env_after_load=env1, view=v, **d))
            except Exception as e: check(n+" block raised", False, repr(e))
            finally: _restore_secrets(); _stcfg.set_option("client.showErrorDetails", _ERR0)
finally:
    tempfile.tempdir = _saved_tmp; _trust_client(False); _restore_secrets(); os.environ.pop("ECRF_HOSTED", None)
    _stcfg.set_option("client.showErrorDetails", _ERR0)

# ---------------------------------------------------------------- docs / GitHub Pages (D-checks)
# docs/ is served as-is by GitHub Pages (main branch, /docs; docs/.nojekyll turns Jekyll off). These checks
# read files only, no app runs:
#   D1  docs/ holds exactly the published pages (DOC_PAGES: the landing page, the evaluation, the case
#       study and the custom 404 page) plus one redirect stub per retired URL (RETIRED: the two old deck pages, merged into the case
#       study), and each stub's <meta http-equiv=refresh> points at its listed page, which must exist. So a
#       retired link keeps working and no stray or stale page lingers on the site (fix: add the page to
#       DOC_PAGES, or delete it, or restore the stub).
#   D2  every page in D1 stays self-contained: no src/srcset/poster/data attribute, no href/xlink:href on a
#       non-link tag (<link>, SVG <image>/<use>) and no <meta http-equiv=refresh> target points off-site
#       (http:, https:, //), its CSS has no @import and no off-site url(), and no inline <script> names a
#       URL. Plain <a>/<area> links (GitHub) are navigation, not resources, so they are allowed.
#   D3  every LOCAL reference resolves on disk, against its file's folder: in README.md every Markdown link
#       and image (inline and reference-style) and <img src>; in each docs page every href, src, srcset
#       entry, poster, data, refresh target and CSS url(). Remote URLs (the CI badge), #anchors and
#       mailto:/data: are skipped. A site-absolute reference under /ecrf-pipeline-apps/ (the project site's
#       base path) resolves against docs/. 404.html must use only such site-absolute local links, because
#       GitHub Pages serves it for a missing address at any depth, where a relative link would point to the
#       wrong folder. README.md and each published page must hold at least one local reference,
#       and every docs/img/ file must be used by at least one of them, so the check cannot pass with nothing
#       to check.
#   D4  the in-browser build in docs/app/ is in step with its sources: tools/sync_browser_apps.py --check
#       passes (byte-identical copies of the four apps and of every sample_data/ and anomaly_data/ CSV, the
#       four pages exactly as rendered from tools/browser_app_template.html, the pinned wheels by sha256,
#       no stray file). Fix: run python tools/sync_browser_apps.py and commit what it changes.
from html.parser import HTMLParser
from urllib.parse import unquote
DOCS = os.path.join(APP_DIR,"docs")
DOC_PAGES = ["index.html", "evaluation.html", "case-study.html", "404.html"]     # published pages
SITE_BASE = "/ecrf-pipeline-apps/"   # GitHub Pages serves docs/ at this path (a project site)
RETIRED = {"deck_a_four_tier_pipeline.html": "case-study.html",                 # retired URL -> where it redirects
           "deck_b_implementation_walkthrough.html": "case-study.html"}
def _offsite(v): v=(v or "").strip().lower(); return v.startswith(("http:","https:","//")) or "://" in v
def _skip(v):
    """True for a reference D3 does not resolve: empty, an #anchor, off-site, or any other URI scheme (mailto:, data:)."""
    v=(v or "").strip(); return not v or v.startswith("#") or _offsite(v) or bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", v))
class _Refs(HTMLParser):
    """Collects (tag, attr, value) for every attribute that loads a resource (res), every reference to check
    on disk (refs: resources plus <a>/<area> links), the text of <style> blocks plus style="" attributes
    (css, for the @import / url() test) and the text of inline <script> blocks (js)."""
    def __init__(self):
        super().__init__(convert_charrefs=True); self.res=[]; self.refs=[]; self.css=[]; self.js=[]; self._in=None
    def _attrs(self, tag, attrs):
        a={k:(v or "") for k,v in attrs}
        for k,v in a.items():
            if k in ("src","srcset","poster","data") or (k in ("href","xlink:href") and tag not in ("a","area")): self.res.append((tag,k,v))
            if k in ("src","poster","data","href","xlink:href"): self.refs.append(v)
            if k=="srcset": self.refs += [(e.split() or [""])[0] for e in v.split(",")]   # "url 2x, url 3x"
            if k=="style": self.css.append(v)
        if tag=="meta" and a.get("http-equiv","").strip().lower()=="refresh":
            m=re.search(r"url\s*=\s*['\"]?([^'\"\s;]+)", a.get("content",""), re.I)
            if m: self.res.append((tag,"content",m.group(1))); self.refs.append(m.group(1))
    def handle_starttag(self, tag, attrs):
        self._attrs(tag, attrs)
        if tag in ("style","script"): self._in=tag
    def handle_startendtag(self, tag, attrs): self._attrs(tag, attrs)
    def handle_endtag(self, tag):
        if tag==self._in: self._in=None
    def handle_data(self, data):
        if self._in=="style": self.css.append(data)
        elif self._in=="script": self.js.append(data)
def _resolve(base_dir, r):
    """A local reference -> its normalized path on disk (query/fragment stripped, %-escapes decoded). A
    site-absolute one under SITE_BASE resolves against docs/; any other absolute path stays as it is."""
    r = unquote(re.split(r"[?#]", r.strip())[0])
    if r.startswith(SITE_BASE): base_dir, r = DOCS, r[len(SITE_BASE):]
    return os.path.normpath(os.path.join(base_dir, r))
def _local_missing(base_dir, refs):
    """refs -> the local ones that do not exist (a file, or a folder such as sample_data/)."""
    return [r for r in refs if not _skip(r) and not os.path.exists(_resolve(base_dir, r))]
_CSS_URL = r"url\(\s*['\"]?([^'\")]+)"

def _read(p):
    with open(p,"rb") as f: return f.read()
parsed, parse_err = {}, {}   # every docs page D1 lists -> its _Refs (shared by D1 to D3)
for _f in DOC_PAGES + sorted(RETIRED):
    try:
        _p = _Refs(); _p.feed(_read(os.path.join(DOCS,_f)).decode("utf-8")); _p.close(); parsed[_f] = _p
    except Exception as e: parse_err[_f] = repr(e)

try:
    have = sorted(f for f in os.listdir(DOCS) if f.lower().endswith(".html"))
    want = sorted(DOC_PAGES + list(RETIRED))
    def _refresh(f): return [v for t,k,v in parsed[f].res if t=="meta" and k=="content"] if f in parsed else []
    bad_stub = {f: _refresh(f) for f,to in RETIRED.items()
                if _refresh(f) != [to] or not os.path.isfile(os.path.join(DOCS,to))}
    check("D1 docs/ holds exactly the published pages plus a redirect stub per retired URL, each pointing at an existing page",
          have == want and not bad_stub and not parse_err,
          dict(missing=sorted(set(want)-set(have)), stray=sorted(set(have)-set(want)), bad_stubs=bad_stub, unreadable=parse_err))
except Exception as e: check("D1 docs pages block raised", False, repr(e))

try:
    if parse_err: raise RuntimeError(f"docs pages not parsed: {parse_err}")
    bad = {}
    for f,ix in parsed.items():
        # srcset holds "url 2x, url 3x": test the first token of every comma-separated entry
        ext = [(t,k,v) for t,k,v in ix.res if any(_offsite((e.split() or [""])[0]) for e in v.split(","))]
        css = " ".join(ix.css)
        bad_css = re.findall(r"@import[^;]*", css, re.I) + [u for u in re.findall(_CSS_URL, css, re.I) if _offsite(u)]
        bad_js = [j.strip()[:80] for j in ix.js if "://" in j]
        if ext or bad_css or bad_js: bad[f] = dict(external=ext, css=bad_css, inline_script=bad_js)
    check("D2 every docs page references no external script, stylesheet, font or image", len(parsed)==len(DOC_PAGES)+len(RETIRED) and not bad, bad)
except Exception as e: check("D2 docs pages block raised", False, repr(e))

try:
    if parse_err: raise RuntimeError(f"docs pages not parsed: {parse_err}")
    rd = _read(os.path.join(APP_DIR,"README.md")).decode("utf-8")
    rd_refs = (re.findall(r"\]\(\s*<?([^)\s>]+)", rd)                              # [text](..) and ![alt](..)
               + re.findall(r"(?m)^ {0,3}\[[^\]]+\]:\s*<?([^\s>]+)", rd)            # [label]: target
               + re.findall(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)", rd, re.I))
    pg_refs = {f: ix.refs + re.findall(_CSS_URL, " ".join(ix.css), re.I) for f,ix in parsed.items()}
    miss = [("README.md",m) for m in _local_missing(APP_DIR, rd_refs)]
    for f,refs in pg_refs.items(): miss += [("docs/"+f,m) for m in _local_missing(DOCS, refs)]
    nloc = dict(readme=sum(1 for r in rd_refs if not _skip(r)), **{f: sum(1 for r in pg_refs[f] if not _skip(r)) for f in DOC_PAGES})
    rel404 = [r for r in pg_refs.get("404.html", []) if not _skip(r) and not r.strip().startswith(SITE_BASE)]
    used = {_resolve(APP_DIR,r) for r in rd_refs if not _skip(r)} | {_resolve(DOCS,r) for refs in pg_refs.values() for r in refs if not _skip(r)}
    IMG = os.path.join(DOCS,"img")
    unused = sorted(f for f in (os.listdir(IMG) if os.path.isdir(IMG) else []) if os.path.normpath(os.path.join(IMG,f)) not in used)
    check("D3 every local link and image in README.md and the docs pages exists on disk (and every docs/img/ file is used)",
          not miss and all(n>=1 for n in nloc.values()) and not unused and not rel404,
          dict(local_refs=nloc, missing=miss, unused_images=unused, relative_links_in_404=rel404))
except Exception as e: check("D3 docs references block raised", False, repr(e))

try:
    import subprocess
    _sync = subprocess.run([sys.executable, os.path.join(APP_DIR,"tools","sync_browser_apps.py"), "--check"],
                           capture_output=True, text=True, timeout=120)
    check("D4 docs/app/ (the in-browser build) matches the apps, the bundled data and the pinned wheels",
          _sync.returncode==0, (_sync.stdout + _sync.stderr).strip()[-300:])
except Exception as e: check("D4 browser-build block raised", False, repr(e))

# ---------------------------------------------------------------- real model path (RM / RW checks)
# Two kinds of check for the coding and PHI apps' REAL path (Needle3 + hnswlib + Laya + XGBoost):
#   RM  real models. Run ONLY when ECRF_MODELS_DIR names a models dir holding the trained artifacts
#       (layout: eval/README.md) and the real runtimes import; otherwise each is reported SKIPPED, never
#       passed. They assert the REAL banner/audit and that the Deck B worked rows reproduce the measured
#       values recorded in eval/results/deck_b_worked.json.
#   RW  wiring, ALWAYS run (CI has no models): small stub packages named needle/hnswlib/laya/xgboost
#       (plus torch/transformers) are put first on sys.path, and the apps are driven with models dirs in
#       different states. They pin the fixes for the defects in docs/FEASIBILITY.md: modules bound (no
#       NameError), REAL only when an artifact LOADS, Laya probed with its torch/transformers runtime,
#       an unrelated 'needle' rejected, a trained gate refused when its feature contract is not met, a
#       corrupt artifact stopping the run, a Laya calibration fitted for another checkpoint refused (one
#       fitted on another machine accepted), a changed models dir reloaded rather than served from a stale
#       cache, the risk/anomaly apps never claiming a model they cannot load.
# RM runs first: the RW block swaps the stub packages in and the real modules back out afterwards
# (sys.modules is restored, so a real torch is never re-imported in this process).
SKIP = []
def skip(name, why):
    SKIP.append((name, why)); print("SKIP " + name + " | " + why)

RP_MODULES = ("needle","hnswlib","laya","xgboost","torch","transformers")
def _rp_find(at, kind, label):
    for w in getattr(at, kind):
        if w.label == label: return w
    return None
def _rp_banner(at):
    return next((i.value for i in at.info if "Mode banner" in i.value), "")
def _rp_run(app, folder, models, out, execute=True):
    A = AppTest.from_file(os.path.join(APP_DIR, app), default_timeout=1800); A.run()
    lab = {"meddra_app.py":"Cut folder path (domain CSVs)","phi_app.py":"Cut folder path (domain CSVs)",
           "risk_app.py":"Cut folder path (safety domains)","anomaly_app.py":"Cut folder path (CSV or SAS .sas7bdat)"}[app]
    find(A,"text_input",lab).set_value(folder).run()
    mlabel = "Models dir (optional real weights)" if app in ("meddra_app.py","phi_app.py") else "Models dir (no trained model in this build)"
    find(A,"text_input",mlabel).set_value(models).run()
    find(A,"text_input","Output folder").set_value(out).run()
    if execute and not A.exception and not [e for e in A.error if "cannot run" in e.value or "failed to load" in e.value
                                             or "present but" in e.value or "found, but" in e.value]:
        btn = next((b for b in A.button if b.label.startswith("🚀")), None)
        if btn is not None and not btn.disabled: btn.set_value(True).run()
    return A
def _rp_audit(out):
    p = os.path.join(out, "audit_log.csv"); return pd.read_csv(p).iloc[0] if os.path.exists(p) else None

# ---- RM: real models (skip cleanly when absent) ----
RM_DIR = os.environ.get("ECRF_MODELS_DIR", "")
def _real_runtimes():
    try:
        import importlib
        for m, a in (("needle","Needle"),("hnswlib","Index"),("laya","load"),("xgboost","Booster"),("torch",None),("transformers",None)):
            mod = importlib.import_module(m)
            if a and not hasattr(mod, a): return f"'{m}' has no {a}"
        return None
    except Exception as e: return f"{type(e).__name__}: {e}"
_need = ["needle3/needle3.cact","laya/model.safetensors","meddra_coder.json","phi_token_classifier.json",
         "laya_calibration_coding.json","laya_calibration_phi.json"]
_why = ("ECRF_MODELS_DIR not set" if not RM_DIR else
        f"ECRF_MODELS_DIR={RM_DIR} lacks {[n for n in _need if not os.path.exists(os.path.join(RM_DIR,n))]}"
        if any(not os.path.exists(os.path.join(RM_DIR,n)) for n in _need) else _real_runtimes())
RM_NAMES = ["RM1 coding real path: banner + audit REAL on every tier, artifacts hashed in the audit",
            "RM2 coding real path: Deck B worked rows reproduce the recorded measured values",
            "RM3 coding real path: bit-identical ae_coded.csv across two runs",
            "RM4 PHI real path: banner + audit REAL on every tier",
            "RM5 PHI real path: Deck B worked fields reproduce the recorded measured values"]
WORKED = os.path.join(APP_DIR, "eval", "results", "deck_b_worked.json")
if _why:
    for n in RM_NAMES: skip(n, _why)
else:
    try:
        rec = json.load(open(WORKED)) if os.path.exists(WORKED) else {}
        o1, o2 = os.path.join(SCRATCH,"rm_meddra1"), os.path.join(SCRATCH,"rm_meddra2")
        A = _rp_run("meddra_app.py", SAMPLE, RM_DIR, o1); aud = _rp_audit(o1)
        check(RM_NAMES[0], not A.exception and aud is not None and (aud["mode_T2"],aud["mode_T3"],aud["mode_T4"])==("REAL","REAL","REAL")
              and "sha256:" in str(aud["real_artifacts"]) and "UNCALIBRATED" not in _rp_banner(A),
              dict(exc=[str(e.value)[:150] for e in A.exception], banner=_rp_banner(A)[:160]))
        cod = pd.read_csv(os.path.join(o1,"ae_coded.csv")) if os.path.exists(os.path.join(o1,"ae_coded.csv")) else None
        got = {} if cod is None else {r.VERBATIM: [round(float(r.S),4), r.AEDECOD, r.AECODSTAT] for r in cod[cod["rank"]==1].itertuples()}
        want = rec.get("coding", {})
        check(RM_NAMES[1], bool(want) and all(v in got and abs(got[v][0]-w["S"])<1e-3 and got[v][1]==w["AEDECOD"] for v,w in want.items()),
              dict(want=want, got={v:got.get(v) for v in want}))
        _rp_run("meddra_app.py", SAMPLE, RM_DIR, o2)
        check(RM_NAMES[2], os.path.exists(os.path.join(o2,"ae_coded.csv")) and sha(os.path.join(o1,"ae_coded.csv"))==sha(os.path.join(o2,"ae_coded.csv")), "")
        o3 = os.path.join(SCRATCH,"rm_phi"); A = _rp_run("phi_app.py", SAMPLE, RM_DIR, o3); aud = _rp_audit(o3)
        check(RM_NAMES[3], not A.exception and aud is not None and (aud["mode_T2"],aud["mode_T3"],aud["mode_T4"])==("REAL","REAL","REAL"),
              dict(exc=[str(e.value)[:150] for e in A.exception], banner=_rp_banner(A)[:160]))
        fl = pd.read_csv(os.path.join(o3,"phi_flags.csv")) if os.path.exists(os.path.join(o3,"phi_flags.csv")) else pd.DataFrame()
        gotp = {f"{r.DOMAIN}|{r.ROW}|{r.FIELD}|{r.SPAN}": round(float(r.P_REDACT),4) for r in fl.itertuples()} if len(fl) else {}
        wantp = rec.get("phi_redact", {})
        check(RM_NAMES[4], bool(wantp) and all(k in gotp and abs(gotp[k]-v)<1e-3 for k,v in wantp.items()),
              dict(missing=[k for k in wantp if k not in gotp][:5], diff={k:(gotp.get(k),v) for k,v in wantp.items() if k in gotp and abs(gotp[k]-v)>=1e-3}))
    except Exception as e: check("RM real-path block raised", False, repr(e))

# ---- RW: wiring with stub packages (always run) ----
STUB_SRC = {
 "needle/__init__.py": '''
import numpy as np, re, zlib
class Needle:
    def __init__(self, tools=None, system=None, weights=None, auto_date=True, stateless=False, **kw):
        self.weights = weights; self.tools = tools
    def embed(self, text=""):
        v = np.zeros(32)
        t = str(text).lower()
        for i in range(len(t) - 2): v[zlib.crc32(t[i:i+3].encode()) % 32] += 1.0
        n = np.linalg.norm(v); return list(v / n if n else v)
    def complete(self, text="", max_new_tokens=512):
        m = re.search(r"Patient ([A-Z][a-z]+ [A-Z][a-z]+)", text)
        return {"function_calls": [{"name": "record_identifiers", "arguments": {"person_name": m.group(1) if m else None}}]}
''',
 "hnswlib/__init__.py": '''
import numpy as np
class Index:
    def __init__(self, space, dim): self.dim = dim; self.V = np.zeros((0, dim)); self.ef = 10
    def init_index(self, max_elements, ef_construction=200, M=16): pass
    def add_items(self, V, ids=None, num_threads=-1): self.V = np.asarray(V, np.float32)
    def set_ef(self, ef): self.ef = ef
    def knn_query(self, q, k=1):
        s = self.V @ np.asarray(q, np.float32).reshape(-1); o = np.argsort(-s)[:k]
        return o.reshape(1, -1), (1.0 - s[o]).reshape(1, -1)
    def save_index(self, p): np.save(p + ".npy", self.V); open(p, "w").write("stub")
    def load_index(self, p, max_elements=0): self.V = np.load(p + ".npy")
''',
 "laya/__init__.py": '''
import json, warnings
def load(path, device=None, calibration=None, **kw):
    d = json.load(open(calibration)) if calibration else {}
    if d.get("model_id_or_path"):            # Laya's identity warning, path-only or config too
        warnings.warn("calibration was fitted for model_id_or_path=%r subfolder=None but this agent is "
                      "model_id_or_path=%r subfolder=None.%s Loading the temperatures anyway."
                      % (d["model_id_or_path"], path, " Checkpoint config identity differs." if d.get("config") == "other" else ""), UserWarning)
    return _Agent()
class _Agent:
    temperature_by_options = {"noul:2": 1.0}
    def predict_batch(self, states, questions):
        out = []
        for s in states:
            neg = any(w in str(s).lower() for w in ("denies", "no ", "ruled out", "negative"))
            out.append({"answers": {q: {"type": "noul", "noul": (0.1 if neg else 0.9) if q == "unambiguous" else 0.5} for q in questions}})
        return out
    def predict(self, state, questions): return self.predict_batch([state], questions)[0]
''',
 "xgboost/__init__.py": '''
import json, math
class DMatrix:
    def __init__(self, X, label=None, feature_names=None): self.X = X; self.names = feature_names
class Booster:
    def load_model(self, p):
        self.w = json.load(open(p))["stub_weights"]
    def predict(self, d):
        out = []
        for row in d.X:
            z = sum(self.w.get(n, 0.0) * (0.0 if v != v else v) for n, v in zip(d.names, row)) + self.w.get("bias", 0.0)
            out.append(1.0 / (1.0 + math.exp(-z)))
        return out
''',
 "torch/__init__.py": "\n", "transformers/__init__.py": "\n"}
RW = os.path.join(SCRATCH, "realpath_stubs")
def _rw_pkgs(variant):
    """Write one stub package set. variant: 'full' | 'no_torch' (torch import fails) | 'css_needle' (an
    unrelated 'needle' without the Needle class)."""
    root = os.path.join(RW, "pkgs_" + variant); shutil.rmtree(root, ignore_errors=True)
    for rel, src in STUB_SRC.items():
        if variant == "no_torch" and rel.startswith("torch"): src = "raise ImportError('stub: torch absent')\n"
        if variant == "css_needle" and rel.startswith("needle"): src = "__version__ = '0.5.0'  # unrelated CSS-testing package\n"
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True); open(os.path.join(root, rel), "w").write(src)
    return root
def _rw_models(name, arts):
    """A models dir holding the named artifacts (empty weight files; stub-readable booster JSON)."""
    md = os.path.join(RW, "models_" + name); shutil.rmtree(md, ignore_errors=True)
    for a in arts:
        p = os.path.join(md, a); os.makedirs(os.path.dirname(p), exist_ok=True)
        if a.endswith("coder.json") or a.endswith("classifier.json"):
            w = ({"cosine": 6.0, "p_unambiguous": 3.0, "bias": -5.0} if "coder" in a else {"src_pattern": 6.0, "bias": -3.0})
            open(p, "w").write(json.dumps({"stub_weights": w}))
            feats = (["cosine","lev","jaro","soc_match","p_unambiguous","ret_rank"] if "coder" in a else
                     ["src_needle","src_pattern","p_direct","p_quasi","n_indirect","digit_ratio","capitalized","rel_pos","span_len","cue"]
                     + [f"ent_{e}" for e in ("PERSON_NAME","PHONE","EMAIL","MRN","DOB","ZIP","INITIALS","AGE")])
            open(p.replace(".json", ".meta.json"), "w").write(json.dumps({"features": feats, "requires": {"T2": "needle3", "T3": "laya"}}))
        elif a in ("CAL_OTHER_PATH", "CAL_OTHER_CKPT"):    # a calibration fitted elsewhere / for another checkpoint
            open(os.path.join(md, "laya_calibration_coding.json"), "w").write(json.dumps(
                {"model_id_or_path": "/elsewhere/laya", "config": "other" if a == "CAL_OTHER_CKPT" else "same"}))
        elif a == "BROKEN_coder":
            open(os.path.join(md, "meddra_coder.json"), "w").write("{not json")
        elif a.endswith(".json"): open(p, "w").write("{}")
        else: open(p, "wb").write(b"stub")
    return md
FULL_CODING = ["needle3/needle3.cact", "needle3/libneedle.so", "needle3/libneedle.dylib", "needle3/libneedle.dll",
               "laya/model.safetensors", "laya_calibration_coding.json", "meddra_coder.json"]
FULL_PHI = ["needle3/needle3.cact", "needle3/libneedle.so", "needle3/libneedle.dylib", "needle3/libneedle.dll",
            "laya/model.safetensors", "laya_calibration_phi.json", "phi_token_classifier.json"]
_saved = {m: sys.modules[m] for m in list(sys.modules) if m.split(".")[0] in RP_MODULES}
_env0 = {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE","NEEDLE_TELEMETRY","DO_NOT_TRACK","NEEDLE3_LIB_PATH")}
def _rw_use(variant):
    for m in [m for m in list(sys.modules) if m.split(".")[0] in RP_MODULES]: del sys.modules[m]
    sys.path[:] = [p for p in sys.path if not p.startswith(RW)]
    if variant: sys.path.insert(0, _rw_pkgs(variant))
try:
    n_verb = int(pd.read_csv(os.path.join(SAMPLE,"ae.csv"))["AETERM"].notna().sum())
    _rw_use("full")
    for k in ("HF_HUB_OFFLINE","NEEDLE_TELEMETRY","DO_NOT_TRACK"): os.environ.pop(k, None)   # the app must set them itself
    o = os.path.join(SCRATCH,"rw1"); A = _rp_run("meddra_app.py", SAMPLE, _rw_models("empty", []), o); aud = _rp_audit(o)
    check("RW5 air gap: the app sets HF_HUB_OFFLINE=1, NEEDLE_TELEMETRY=0 and DO_NOT_TRACK=1 before any runtime loads",
          (os.environ.get("HF_HUB_OFFLINE"), os.environ.get("NEEDLE_TELEMETRY"), os.environ.get("DO_NOT_TRACK"))==("1","0","1"),
          {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE","NEEDLE_TELEMETRY","DO_NOT_TRACK")})
    check("RW1 coding: runtimes installed but no artifacts -> every tier STAND-IN (a library alone never flips REAL)",
          not A.exception and aud is not None and (aud["mode_T2"],aud["mode_T3"],aud["mode_T4"])==("STAND-IN",)*3
          and "STAND-IN [SI] (lexical)" in _rp_banner(A), dict(exc=[str(e.value)[:150] for e in A.exception], banner=_rp_banner(A)[:120]))
    o = os.path.join(SCRATCH,"rw2"); A = _rp_run("meddra_app.py", SAMPLE, _rw_models("coding_full", FULL_CODING), o); aud = _rp_audit(o)
    cod = pd.read_csv(os.path.join(o,"ae_coded.csv")) if os.path.exists(os.path.join(o,"ae_coded.csv")) else None
    check("RW2 coding: full models dir -> modules bound (no NameError), REAL on every tier in banner and audit",
          not A.exception and aud is not None and (aud["mode_T2"],aud["mode_T3"],aud["mode_T4"])==("REAL",)*3
          and "REAL needle3+hnsw" in _rp_banner(A) and "REAL xgboost re-ranker" in _rp_banner(A),
          dict(exc=[str(e.value)[:200] for e in A.exception], banner=_rp_banner(A)[:160]))
    check("RW3 coding real path: re-ranked export keeps the stand-in's shape (top 3 per verbatim, S in [0,1]) and hashes the artifacts",
          cod is not None and len(cod)==n_verb*3 and cod["S"].between(0,1).all() and set(cod["rank"])=={1,2,3}
          and "sha256:" in str(aud["real_artifacts"]), None if cod is None else (len(cod), n_verb*3))
    # A two-row cut: the stub Laya scores "denies ..." low through predict_batch(), and the stub re-ranker
    # weighs that scalar, so the plain verbatim auto-codes and the negated one routes to a human.
    neg = os.path.join(SCRATCH,"rw_negcut"); shutil.rmtree(neg, ignore_errors=True); os.makedirs(neg)
    shutil.copy(os.path.join(SAMPLE,"meddra_demo.csv"), neg)
    pd.DataFrame(dict(STUDYID=["S"]*2, USUBJID=["U1","U2"], AESEQ=[1,2], AETERM=["headache","denies headache"])).to_csv(os.path.join(neg,"ae.csv"), index=False)
    o = os.path.join(SCRATCH,"rw4"); _rp_run("meddra_app.py", neg, _rw_models("coding_full_neg", FULL_CODING), o)
    c4 = pd.read_csv(os.path.join(o,"ae_coded.csv")) if os.path.exists(os.path.join(o,"ae_coded.csv")) else None
    st4 = {} if c4 is None else dict(zip(c4[c4["rank"]==1]["VERBATIM"], c4[c4["rank"]==1]["AECODSTAT"]))
    check("RW4 coding real path: Tier 3 (Laya predict_batch) feeds the re-ranker: 'headache' auto-codes, 'denies headache' routes to a human",
          st4.get("headache")=="AUTO_COMMIT_TO_SDTM" and st4.get("denies headache")=="FLAGGED_FOR_HUMAN_CODER", st4)
    o = os.path.join(SCRATCH,"rw6"); A = _rp_run("meddra_app.py", SAMPLE, _rw_models("coder_only", ["meddra_coder.json"]), o)
    check("RW6 coding: a re-ranker whose feature contract the loaded tiers miss STOPS the run",
          any("re-ranker cannot run" in e.value for e in A.error) and not os.path.exists(os.path.join(o,"ae_coded.csv")), [e.value[:120] for e in A.error])
    o = os.path.join(SCRATCH,"rw7"); A = _rp_run("meddra_app.py", SAMPLE, _rw_models("broken", ["BROKEN_coder"]), o)
    check("RW7 coding: a present but unreadable artifact STOPS the run (no fallback to a stand-in)",
          any("failed to load" in e.value for e in A.error), [e.value[:120] for e in A.error])
    md16 = _rw_models("reload", [])            # one models dir path, two states, one process
    o = os.path.join(SCRATCH,"rw16a"); _rp_run("meddra_app.py", SAMPLE, md16, o); aud_a = _rp_audit(o)
    _rw_models("reload", FULL_CODING)
    o = os.path.join(SCRATCH,"rw16b"); _rp_run("meddra_app.py", SAMPLE, md16, o); aud_b = _rp_audit(o)
    check("RW16 coding: artifacts added to the same models dir in a running process are loaded on the next run (no stale cache)",
          aud_a is not None and aud_b is not None and aud_a["mode_T2"]=="STAND-IN" and aud_b["mode_T2"]=="REAL",
          None if aud_a is None or aud_b is None else (aud_a["mode_T2"], aud_b["mode_T2"]))
    cal_arts = [x for x in FULL_CODING if x != "laya_calibration_coding.json"]
    o = os.path.join(SCRATCH,"rw14"); A = _rp_run("meddra_app.py", SAMPLE, _rw_models("cal_path", cal_arts + ["CAL_OTHER_PATH"]), o); aud = _rp_audit(o)
    check("RW14 coding: a Laya calibration fitted on another machine (checkpoint path differs, config same) loads and runs REAL",
          not A.exception and not A.error and aud is not None and aud["mode_T3"]=="REAL", dict(err=[e.value[:140] for e in A.error]))
    o = os.path.join(SCRATCH,"rw15"); A = _rp_run("meddra_app.py", SAMPLE, _rw_models("cal_ckpt", cal_arts + ["CAL_OTHER_CKPT"]), o)
    check("RW15 coding: a Laya calibration fitted for a DIFFERENT checkpoint config STOPS the run",
          any("fitted for a different Laya checkpoint" in e.value for e in A.error) and not os.path.exists(os.path.join(o,"ae_coded.csv")),
          [e.value[:160] for e in A.error])
    _rw_use("no_torch")
    o = os.path.join(SCRATCH,"rw8"); A = _rp_run("meddra_app.py", SAMPLE, _rw_models("coding_full_b", FULL_CODING), o)
    check("RW8 coding: laya importable but torch missing -> laya NOT bound, and its checkpoint in the models dir STOPS the run",
          any("laya/model.safetensors present but" in e.value for e in A.error), [e.value[:140] for e in A.error])
    _rw_use("css_needle")
    o = os.path.join(SCRATCH,"rw9"); A = _rp_run("meddra_app.py", SAMPLE, _rw_models("coding_full_c", FULL_CODING), o)
    check("RW9 coding: an unrelated package named 'needle' is not taken for Needle3 (its weights then STOP the run)",
          any("needle3/needle3.cact present but" in e.value and "'needle'" in e.value for e in A.error), [e.value[:140] for e in A.error])
    _rw_use("full")
    o = os.path.join(SCRATCH,"rw10"); A = _rp_run("phi_app.py", SAMPLE, _rw_models("phi_full", FULL_PHI), o); aud = _rp_audit(o)
    check("RW10 PHI: full models dir -> REAL on every tier, no exception, flags + sanitized domains written",
          not A.exception and aud is not None and (aud["mode_T2"],aud["mode_T3"],aud["mode_T4"])==("REAL",)*3
          and os.path.exists(os.path.join(o,"phi_flags.csv")), dict(exc=[str(e.value)[:200] for e in A.exception], banner=_rp_banner(A)[:160]))
    o = os.path.join(SCRATCH,"rw11"); A = _rp_run("phi_app.py", SAMPLE, _rw_models("phi_nogate", [a for a in FULL_PHI if "classifier" not in a]), o); aud = _rp_audit(o)
    check("RW11 PHI: Needle3 without its trained gate is NOT used (Tier 2 stays STAND-IN and the audit says why)",
          aud is not None and aud["mode_T2"]=="STAND-IN" and "loaded but NOT used" in str(aud["real_artifacts"]), None if aud is None else aud["real_artifacts"])
    o = os.path.join(SCRATCH,"rw12"); A = _rp_run("risk_app.py", SAMPLE, _rw_models("risk", ["risk_model.json"]), o)
    check("RW12 risk: a risk_model.json STOPS the run even with xgboost installed (no trained-model path to load it)",
          any("found, but" in e.value for e in A.error) and not os.path.exists(os.path.join(o,"audit_log.csv")), [e.value[:120] for e in A.error])
    o = os.path.join(SCRATCH,"rw13"); A = _rp_run("anomaly_app.py", ANOM, _rw_models("anom_empty", []), o); aud = _rp_audit(o)
    check("RW13 anomaly: with needle + laya installed the text tier still reports its [SI] stand-in (no real text path wired)",
          aud is not None and "STAND-IN [SI] bag-of-words" in str(aud["text_path"]), None if aud is None else aud["text_path"])
except Exception as e: check("RW wiring block raised", False, repr(e))
finally:
    _rw_use(None); sys.modules.update(_saved)
    for k, v in _env0.items():
        if v is None: os.environ.pop(k, None)
        else: os.environ[k] = v

print("\n==== SUMMARY:", len(PASS), "passed,", len(FAIL), "failed,", len(SKIP), "skipped ====")
for n,d in SKIP: print("  SKIPPED:", n, "|", str(d)[:160])
for n,d in FAIL: print("  FAILED:", n, "|", str(d)[:200])
sys.exit(1 if FAIL else 0)
