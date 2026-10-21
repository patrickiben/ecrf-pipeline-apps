"""QC harness: runs all four apps (meddra, phi, risk, anomaly) end-to-end via streamlit AppTest.

Portable -- paths derive from this file's location, so it can live anywhere next to
the apps. Run with a Python that has the app deps installed:
    pip install -r ../requirements.txt && python tests/qc_test.py
Exit code 0 = all checks pass.
"""
import os, re, sys, shutil, hashlib, tempfile
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))      # .../biostat_pipeline_apps/tests
APP_DIR = os.path.dirname(HERE)                        # .../biostat_pipeline_apps
SAMPLE = os.path.join(APP_DIR, "sample_data")
SCRATCH = tempfile.mkdtemp(prefix="qc_out_")

from streamlit.testing.v1 import AppTest

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
btn = find(at,"button","🚀 Execute MedDRA Auto-Coding")
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
find(at2,"button","🚀 Execute MedDRA Auto-Coding").set_value(True).run()
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
    b3 = find(at3,"button","🚀 Execute MedDRA Auto-Coding")
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
b4 = find(at4,"button","🚀 Execute MedDRA Auto-Coding")
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
b6 = find(at6,"button","🚀 Execute MedDRA Auto-Coding")
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
    bs = find(ats,"button","🚀 Execute MedDRA Auto-Coding")
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
bp = find(ap,"button","🚀 Execute PII/PHI Flagging")
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
    # has 155 rows with the bulk subjects appended after the six worked rows.
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
br = find(ar,"button","🚀 Execute Risk Scoring")
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
    # valid ranges for every subject
    check("R7 safety scores in [0,100]", res["safety_risk_score"].between(0,100).all(), "")
    check("R8 disc scores in [0,1]", res["discontinuation_risk_score"].between(0,1).all(), "")
    # all four safety categories present across the bulk cut
    cats=set(res["safety_category"])
    check("R9 all four safety categories present", {"LOW","MODERATE","HIGH","CRITICAL"} <= cats, sorted(cats))
    def subj(uid): return res[res["USUBJID"].astype(str)==uid]
    # anchor assertions (clinically-meaningful; each lands with margin in its band)
    check("R10 fatal SUBJ-9015 -> CRITICAL", len(subj("SUBJ-9015"))==1 and subj("SUBJ-9015").iloc[0]["safety_category"]=="CRITICAL", "")
    # The fatal call must be backed by explicit evidence in the row (AEOUTCOME=DIED), not just a bare flag.
    _f9015 = str(subj("SUBJ-9015").iloc[0]["contributing_factors"])
    check("R10b fatality cited WITH its AEOUTCOME evidence", "Fatal" in _f9015 and "AEOUTCOME=DIED" in _f9015, _f9015)
    # A life-threatening SEVERITY that did NOT result in death must NOT be called fatal. The `fatal`
    # column is no longer exported; the evidence lives in contributing_factors, which must lack it.
    check("R10d life-threatening-but-survived SUBJ-9001 is not fatal", "Fatal outcome" not in str(subj("SUBJ-9001").iloc[0]["contributing_factors"]), str(subj("SUBJ-9001").iloc[0]["contributing_factors"]))
    # A fatal outcome must rank at/above EVERY non-fatal subject (death outranks any comorbidity load).
    _f = subj("SUBJ-9015").iloc[0]
    _nf_max = res[res["USUBJID"].astype(str)!="SUBJ-9015"]["safety_risk_score"].max()
    check("R10c fatal ranks at/above every non-fatal subject", _f["safety_category"]=="CRITICAL" and _f["safety_risk_score"]>=_nf_max, f"fatal={_f['safety_risk_score']} vs max_nonfatal={_nf_max}")
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
find(ar2,"button","🚀 Execute Risk Scoring").set_value(True).run()
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
# injected signals are caught -- ALT is THE drift column (cohort trend) and the three injected per-subject
# outliers rank at/near the top of anomalies. Conditional on `ot`+scipy like the SAS checks: with Python
# Optimal Transport installed we exercise the REAL Sinkhorn path; otherwise the labelled [SI] Wasserstein
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
find(aa,"text_input","Output folder").set_value(outa1).run()
ba = find(aa,"button","🚀 Execute Anomaly & Drift Detection")
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
    # flagged-only: every emitted subject is at least MODERATE (no LOW rows leak into the output)
    check("A8b flagged-only output (no LOW-category subjects emitted)", int((anomf["anomaly_category"]=="LOW").sum())==0, sorted(set(anomf["anomaly_category"])))
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
find(aa2,"button","🚀 Execute Anomaly & Drift Detection").set_value(True).run()
# determinism now covers every output table that was written (pure arithmetic -> bit-reproducible)
_cmp=[f for f in ["anomalies.csv","drift.csv","lab_drift.csv","lab_compare.csv","text_anomalies.csv"] if os.path.exists(os.path.join(outa1,f))]
check("A11 deterministic across runs", len(_cmp)>=2 and all(sha(os.path.join(outa1,f))==sha(os.path.join(outa2,f)) for f in _cmp), str(_cmp))

# ---------------------------------------------------------------- anomaly app (mixed-upload regression, A19-A20)
# Regression: uploading the LONGITUDINAL labs.csv together with CROSS-SECTIONAL safety files used to crash
# (_change_matrix -> nanargmin on an all-NaN time slice for subjects present only in a domain without VISITNUM).
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
b3 = find(aa3, "button", "\U0001F680 Execute Anomaly & Drift Detection")
check("A19b run button enabled with mixed upload", not b3.disabled)
b3.set_value(True).run()
check("A20 mixed upload: no exception on execute", not aa3.exception, [str(e.value)[:200] for e in aa3.exception])
anomm = pd.read_csv(os.path.join(outa3, "anomalies.csv")) if os.path.exists(os.path.join(outa3, "anomalies.csv")) else None
if anomm is not None:
    inj = {"SUBJ-A003", "SUBJ-A017", "SUBJ-A029"}
    top6 = set(anomm.sort_values("anomaly_score", ascending=False).head(6)["USUBJID"])
    check("A20b mixed upload: 3 injected numeric outliers still flagged in top-6", inj <= top6, sorted(inj & top6))

print("\n==== SUMMARY:", len(PASS), "passed,", len(FAIL), "failed ====")
for n,d in FAIL: print("  FAILED:", n, "|", str(d)[:200])
sys.exit(1 if FAIL else 0)
