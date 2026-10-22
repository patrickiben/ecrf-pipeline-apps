#!/usr/bin/env python3
"""Generate the SYNTHETIC evaluation data for the real-model path (deterministic, seed 42).

Run from anywhere:   python3 eval/make_data.py     (writes eval/data/*.csv)

Three artifacts, all invented for evaluation and all safe to publish:
  dictionary.csv    a flattened coding dictionary in the same shape as sample_data/meddra_demo.csv
                    (llt_code, llt_name, pt_code, pt_name, hlt_*, hlgt_*, soc_*). It is a SUPERSET
                    of the 12 demo rows (kept byte-for-byte, same codes) plus a few thousand
                    generated lowest-level terms. Every code is a 99-prefixed PLACEHOLDER, and the
                    HLT/HLGT/SOC groupings outside the demo rows are invented for this file: this is
                    NOT MedDRA and must not be read as its hierarchy.
  coding_eval.csv   adverse-event verbatims with a known answer (the preferred term they should code
                    to), in four variants per term: exact, colloquial, misspelled and negated. A
                    negated verbatim ("denies nausea") has no correct auto-code: the right outcome is
                    to route it to a human coder, and the evaluation scores it that way.
  phi_fields.csv    free-text eCRF fields with gold identifier spans (phi_spans.csv), including
  phi_spans.csv     look-alikes that are NOT identifiers (drug names, lab values, doses, times, kit
                    numbers) and identifier formats the shipped stand-in patterns do not cover.

Splits are GROUPED so the held-out test split never shares a group with training: coding rows are
grouped by preferred term (a test term is never seen in training), PHI fields by note template (a
test template is never seen in training). train fits the XGBoost gates, calib fits the Laya
temperatures, test is reported and nothing is fitted on it.

EVERYTHING HERE IS SYNTHETIC: no real patient, no real study, no licensed dictionary content.
Names are invented combinations of common given names and surnames; phone numbers use the
fictional 555-01xx range.
"""
import csv, os, random, re

SEED = 42
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
DEMO = os.path.join(os.path.dirname(HERE), "sample_data", "meddra_demo.csv")
COLS = ["llt_code","llt_name","pt_code","pt_name","hlt_code","hlt_name","hlgt_code","hlgt_name","soc_code","soc_name"]

# --------------------------------------------------------------------------- #
# Placeholder codes. The demo rows already use 990xxxxx; generated rows use separate 99-prefixed
# blocks per level so nothing can collide with a demo code (and nothing is 10xxxxxx, the real
# MedDRA range). Codes are assigned in generation order, so the file is reproducible.
# --------------------------------------------------------------------------- #
class Codes:
    def __init__(self): self.n = {"llt": 99100000, "pt": 99300000, "hlt": 99500000, "hlgt": 99700000, "soc": 99800000}
    def next(self, lvl): self.n[lvl] += 1; return str(self.n[lvl])

def cap(s): return s[:1].upper() + s[1:]

# --------------------------------------------------------------------------- #
# Vocabulary. Plain clinical English written for this file; groupings are invented.
# --------------------------------------------------------------------------- #
PAIRED = ["shoulder","elbow","wrist","hand","finger","hip","knee","ankle","foot","toe","arm","leg",
          "thigh","calf","forearm","heel","upper arm","lower leg","shin","palm","sole","thumb","big toe"]
UNPAIRED = ["neck","back","lower back","upper back","chest","abdomen","upper abdomen","lower abdomen",
            "jaw","groin","pelvis","buttock","scalp","face","mouth","tongue","gum","tooth","flank",
            "side","rib cage","sacrum","tailbone","temple","forehead","cheek","nose","lip"]
JOINTS = ["shoulder","elbow","wrist","hip","knee","ankle","neck","back","finger"]
SKIN = ["arm","leg","face","chest","back","hand","foot","neck","scalp","abdomen","thigh","forearm","trunk","groin"]
BONES = ["wrist","ankle","rib","hip","femur","tibia","fibula","radius","ulna","humerus","clavicle",
         "finger","toe","foot","hand","nose","vertebra","pelvis","skull","jaw"]
WOUND_SITES = ["finger","hand","forearm","arm","leg","knee","shin","foot","head","face","lip","chin",
               "scalp","thumb","palm","elbow","eyebrow","toe","wrist","ankle"]
QUALIFIERS = ["acute","chronic","intermittent","mild","severe"]
# analyte, abbreviation (or None), group
ANALYTES = [("alanine aminotransferase","ALT","liver"),("aspartate aminotransferase","AST","liver"),
    ("blood bilirubin",None,"liver"),("alkaline phosphatase","ALP","liver"),("gamma-glutamyltransferase","GGT","liver"),
    ("blood creatinine",None,"renal"),("blood urea",None,"renal"),("blood uric acid",None,"renal"),
    ("blood glucose",None,"metabolic"),("blood potassium",None,"electrolyte"),("blood sodium",None,"electrolyte"),
    ("blood calcium",None,"electrolyte"),("blood magnesium",None,"electrolyte"),("blood phosphate",None,"electrolyte"),
    ("blood chloride",None,"electrolyte"),("blood bicarbonate",None,"electrolyte"),("haemoglobin","Hb","haematology"),
    ("platelet count",None,"haematology"),("white blood cell count","WBC","haematology"),("neutrophil count",None,"haematology"),
    ("lymphocyte count",None,"haematology"),("eosinophil count",None,"haematology"),("haematocrit",None,"haematology"),
    ("lipase",None,"pancreatic"),("amylase",None,"pancreatic"),("blood creatine phosphokinase","CK","muscle"),
    ("blood lactate dehydrogenase","LDH","muscle"),("blood cholesterol",None,"lipid"),("blood triglycerides",None,"lipid"),
    ("blood albumin",None,"protein"),("total protein",None,"protein"),("troponin",None,"cardiac"),
    ("C-reactive protein","CRP","inflammation"),("serum ferritin",None,"haematology"),("blood iron",None,"haematology"),
    ("blood thyroid stimulating hormone","TSH","endocrine"),("prothrombin time",None,"coagulation"),
    ("international normalised ratio","INR","coagulation"),("blood pressure",None,"vital"),("heart rate",None,"vital"),
    ("body temperature",None,"vital"),("weight",None,"vital"),("respiratory rate",None,"vital"),("blood insulin",None,"endocrine")]
ORGANS = [("urinary tract","bladder"),("upper respiratory tract","chest"),("lower respiratory tract","lung"),
          ("ear","ear"),("eye","eye"),("skin","skin"),("sinus","sinuses"),("tooth","tooth"),("gum","gums"),
          ("kidney","kidney"),("wound","wound"),("throat","throat"),("lung","lungs"),("vaginal","vaginal"),
          ("fungal skin","feet"),("gastrointestinal","stomach bug"),("nail bed","nail"),("bone","bone"),
          ("joint","joint"),("injection site","shot site")]
# PT name, [extra LLT synonyms], [colloquial verbatims], group
SYMPTOMS = [
 ("Vomiting",["Emesis","Throwing up"],["threw up twice overnight","keeps being sick after meals"],"gi"),
 ("Constipation",["Hard stools","Difficulty passing stool"],["could not go to the toilet for days","bowels blocked up"],"gi"),
 ("Dyspepsia",["Indigestion","Upset stomach"],["stomach upset after eating","burning feeling after food"],"gi"),
 ("Abdominal distension",["Bloating","Bloated abdomen"],["tummy feels blown up","belly very bloated"],"gi"),
 ("Flatulence",["Passing wind","Excess gas"],["lots of gas","passing wind all day"],"gi"),
 ("Dry mouth",["Mouth dryness","Xerostomia"],["mouth feels like cotton","no saliva"],"gi"),
 ("Decreased appetite",["Loss of appetite","Appetite reduced"],["not hungry at all","off my food"],"metabolic"),
 ("Dehydration",["Fluid loss","Dehydrated"],["very thirsty and not drinking enough","dried out"],"metabolic"),
 ("Dizziness",["Dizzy spell","Feeling dizzy"],["head spinning a bit","felt woozy"],"neuro"),
 ("Vertigo",["Spinning sensation","Room spinning"],["room going round and round","everything spinning"],"neuro"),
 ("Somnolence",["Drowsiness","Sleepiness"],["sleepy all afternoon","can't keep eyes open"],"neuro"),
 ("Tremor",["Shaking","Shakiness"],["hands shaking","shaky hands"],"neuro"),
 ("Paraesthesia",["Pins and needles","Tingling"],["pins and needles in fingers","tingly feeling in feet"],"neuro"),
 ("Hypoaesthesia",["Numbness","Reduced sensation"],["can't feel my fingertips","numb patch"],"neuro"),
 ("Dysgeusia",["Taste disturbance","Metallic taste"],["everything tastes like metal","food tastes wrong"],"neuro"),
 ("Syncope",["Fainting","Loss of consciousness transient"],["passed out briefly","blacked out for a moment"],"neuro"),
 ("Memory impairment",["Forgetfulness","Poor memory"],["keeps forgetting things","memory not great"],"neuro"),
 ("Insomnia",["Sleeplessness","Unable to sleep"],["couldn't sleep","awake most of the night"],"psych"),
 ("Anxiety",["Feeling anxious","Nervousness"],["very on edge","worried and jittery"],"psych"),
 ("Depressed mood",["Low mood","Feeling down"],["feeling blue","mood very low"],"psych"),
 ("Irritability",["Feeling irritable","Short temper"],["snapping at everyone","very cranky"],"psych"),
 ("Confusional state",["Confusion","Disorientation"],["muddled and confused","didn't know where he was"],"psych"),
 ("Nightmare",["Bad dreams","Disturbing dreams"],["horrible dreams","waking from bad dreams"],"psych"),
 ("Agitation",["Restlessness","Feeling agitated"],["can't sit still","very restless"],"psych"),
 ("Pyrexia",["Fever","High temperature"],["running a temperature","felt hot and feverish"],"general"),
 ("Chills",["Shivering","Rigors"],["shivery and cold","teeth chattering"],"general"),
 ("Asthenia",["Weakness","Generalised weakness"],["no strength","feels weak all over"],"general"),
 ("Malaise",["Feeling unwell","Generally unwell"],["just feels off","under the weather"],"general"),
 ("Influenza like illness",["Flu-like symptoms","Flu like illness"],["feels like flu","flu-ish aches"],"general"),
 ("Hyperhidrosis",["Excessive sweating","Sweating increased"],["sweating buckets","drenched in sweat"],"skin"),
 ("Night sweats",["Nocturnal sweating","Sweating at night"],["soaked sheets at night","sweaty nights"],"skin"),
 ("Alopecia",["Hair loss","Hair thinning"],["hair falling out","losing hair"],"skin"),
 ("Urticaria",["Hives","Nettle rash"],["hives all over","welts on skin"],"skin"),
 ("Dry skin",["Skin dryness","Xerosis"],["skin flaky and dry","rough dry skin"],"skin"),
 ("Cough",["Coughing","Dry cough"],["hacking cough","coughing at night"],"resp"),
 ("Dyspnoea",["Shortness of breath","Breathlessness"],["can't catch breath","short of breath on stairs"],"resp"),
 ("Rhinorrhoea",["Runny nose","Nasal discharge"],["nose running","drippy nose"],"resp"),
 ("Nasal congestion",["Stuffy nose","Blocked nose"],["nose all blocked up","stuffed up"],"resp"),
 ("Sneezing",["Sneeze","Frequent sneezing"],["sneezing a lot","keeps sneezing"],"resp"),
 ("Epistaxis",["Nosebleed","Nose bleed"],["nose started bleeding","bleeding from nose"],"resp"),
 ("Oropharyngeal pain",["Sore throat","Throat pain"],["throat really sore","scratchy painful throat"],"resp"),
 ("Wheezing",["Wheeze","Wheezy breathing"],["whistling when breathing","wheezy chest"],"resp"),
 ("Palpitations",["Heart racing","Pounding heart"],["heart fluttering","heart pounding in chest"],"cardiac"),
 ("Tachycardia",["Fast heart rate","Rapid heartbeat"],["heart going really fast","pulse racing"],"cardiac"),
 ("Bradycardia",["Slow heart rate","Slow heartbeat"],["pulse very slow","heart rate in the 40s"],"cardiac"),
 ("Chest discomfort",["Chest tightness","Tight chest"],["chest feels tight","pressure in chest"],"cardiac"),
 ("Hypertension",["High blood pressure","Raised blood pressure"],["pressure up today","blood pressure through the roof"],"vascular"),
 ("Hypotension",["Low blood pressure","Blood pressure low"],["pressure dropped","bp low on standing"],"vascular"),
 ("Hot flush",["Hot flashes","Flushing"],["sudden hot flashes","face going red and hot"],"vascular"),
 ("Tinnitus",["Ringing in ears","Ear ringing"],["ears ringing","buzzing in ears"],"ear"),
 ("Ear discomfort",["Ear pressure","Blocked ear sensation"],["ears feel full","popping in ears"],"ear"),
 ("Vision blurred",["Blurred vision","Blurry vision"],["eyes blurry","can't see clearly"],"eye"),
 ("Dry eye",["Eye dryness","Gritty eyes"],["eyes feel gritty","sandy eyes"],"eye"),
 ("Eye pruritus",["Itchy eyes","Eye itching"],["eyes itching","itchy eyelids"],"eye"),
 ("Conjunctivitis",["Pink eye","Red eye"],["red sticky eye","eye red and weepy"],"eye"),
 ("Dysuria",["Painful urination","Burning on urination"],["stings when passing water","burns to pee"],"renal"),
 ("Pollakiuria",["Frequent urination","Urinary frequency"],["always running to the toilet","peeing a lot"],"renal"),
 ("Haematuria",["Blood in urine","Urine bloody"],["pink urine","blood when peeing"],"renal"),
 ("Muscle spasms",["Muscle cramp","Cramping"],["cramps in legs","calf cramping at night"],"msk"),
 ("Myalgia",["Muscle pain","Muscle ache"],["muscles aching all over","sore muscles"],"msk"),
 ("Arthralgia",["Joint pain","Aching joints"],["joints aching","sore joints"],"msk"),
 ("Hypersensitivity",["Allergic reaction","Allergy"],["had an allergic reaction","allergic to it"],"immune"),
 ("Infusion related reaction",["Infusion reaction","Reaction during infusion"],["reaction while drip running","felt bad during infusion"],"immune"),
 ("Nasopharyngitis",["Common cold","Head cold"],["caught a cold","cold symptoms"],"infection"),
 ("Fall",["Fell","Fall at home"],["tripped and fell","slipped on stairs"],"injury"),
]
# demo PTs that gain extra generated LLTs (their demo rows stay as they are)
DEMO_EXTRA = {"Headache":["Head pain","Headache tension type","Cephalgia"],
              "Nausea":["Feeling sick","Queasiness","Sick to stomach"],
              "Fatigue":["Tiredness","Exhaustion","Lack of energy"],
              "Diarrhoea":["Frequent loose stools","Runny stools"],
              "Dizziness postural":["Dizziness on standing","Orthostatic dizziness"],
              "Electrocardiogram QT prolonged":["QT prolongation","Prolonged QT interval"]}
DEMO_COLLOQ = {"Headache":["head is pounding","really bad head"],"Nausea":["feel like throwing up","stomach churning"],
               "Fatigue":["wiped out all day","so tired"],"Diarrhoea":["runs all day","frequent watery bowel movements"],
               "Dizziness postural":["feeling lightheaded when standing up","woozy getting out of bed"],
               "Electrocardiogram QT prolonged":["marked prolonged heart rhythm interval","QT long on the trace"],
               "Migraine":["one of my bad migraines","sick headache with flashing lights"]}
GROUP_SOC = {"gi":"Gastrointestinal disorders","metabolic":"Metabolic disorders","neuro":"Nervous system disorders",
             "psych":"Psychiatric disorders","general":"General disorders and administration site conditions",
             "skin":"Skin disorders","resp":"Respiratory disorders","cardiac":"Cardiac disorders","vascular":"Vascular disorders",
             "ear":"Ear disorders","eye":"Eye disorders","renal":"Urinary disorders","msk":"Musculoskeletal disorders",
             "immune":"Immune disorders","infection":"Infections","injury":"Injuries","lab":"Investigations"}

def build_dictionary():
    """Return (rows, concepts). rows = flattened dictionary rows (demo rows first, unchanged);
    concepts = {pt_name: dict(pt_code, family, slots, collo)} used to write colloquial verbatims."""
    C = Codes(); rows = []; concepts = {}
    demo = list(csv.DictReader(open(DEMO, encoding="utf-8")))
    rows += demo
    pt_codes = {r["pt_name"]: r for r in demo}
    soc_code = {r["soc_name"]: r["soc_code"] for r in demo}
    hl = {}   # (group, hlt_name) -> (hlt_code, hlgt_code, hlgt_name, soc_code, soc_name)
    def grouping(group, hlt_name):
        soc = GROUP_SOC[group]
        if soc not in soc_code: soc_code[soc] = C.next("soc")
        key = (group, hlt_name)
        if key not in hl:
            hlgt_name = f"{GROUP_SOC[group]} (generated group)"
            hgk = ("HLGT", group)
            if hgk not in hl: hl[hgk] = C.next("hlgt")
            hl[key] = (C.next("hlt"), hl[hgk], hlgt_name, soc_code[soc], soc)
        return hl[key]
    seen_llt = {r["llt_name"].lower() for r in demo}
    def add_pt(pt, llts, group, hlt_name, family, slots=None, collo=None, pt_code=None):
        g = grouping(group, hlt_name) if pt_code is None else None
        if pt_code is None:
            pt_code = C.next("pt"); hlt_code, hlgt_code, hlgt_name, sc, sn = g
        else:   # extend a demo PT: reuse its hierarchy exactly
            d = pt_codes[pt]; hlt_code, hlgt_code, hlgt_name, sc, sn = d["hlt_code"], d["hlgt_code"], d["hlgt_name"], d["soc_code"], d["soc_name"]
            hlt_name = d["hlt_name"]
        for l in llts:
            if l.lower() in seen_llt: continue
            seen_llt.add(l.lower())
            rows.append(dict(llt_code=C.next("llt"), llt_name=l, pt_code=pt_code, pt_name=pt, hlt_code=hlt_code,
                             hlt_name=hlt_name, hlgt_code=hlgt_code, hlgt_name=hlgt_name, soc_code=sc, soc_name=sn))
        concepts[pt] = dict(pt_code=pt_code, family=family, slots=slots or {}, collo=collo or [])
    # demo PTs (extra LLTs, same codes and hierarchy)
    for d in demo:
        pt = d["pt_name"]
        if pt in concepts: continue
        add_pt(pt, DEMO_EXTRA.get(pt, []), None, None, "symptom", collo=DEMO_COLLOQ.get(pt, []), pt_code=d["pt_code"])
    # pain / swelling / stiffness by site, with laterality and qualifier variants
    for s in PAIRED + UNPAIRED:
        paired = s in PAIRED
        llts = [f"Pain in {s}", f"{cap(s)} pain", f"{cap(s)} ache", f"Sore {s}", f"{cap(s)} discomfort"]
        llts += [f"{cap(q)} {s} pain" for q in QUALIFIERS]
        if paired: llts += [f"Pain in left {s}", f"Pain in right {s}", f"Left {s} pain", f"Right {s} pain"]
        add_pt(f"Pain in {s}", llts, "msk", "Pain by body site", "pain", slots={"site": s})
        llts = [f"Swelling of {s}", f"{cap(s)} swelling", f"Swollen {s}", f"Puffiness of {s}"]
        if paired: llts += [f"Swelling of left {s}", f"Swelling of right {s}", f"Left {s} swollen", f"Right {s} swollen"]
        llts += [f"{cap(q)} swelling of {s}" for q in ("mild", "severe", "painful")]
        add_pt(f"Swelling of {s}", llts, "general", "Swelling by body site", "swelling", slots={"site": s})
        llts = [f"Numbness of {s}", f"Numb {s}", f"{cap(s)} numbness", f"Loss of feeling in {s}"]
        if paired: llts += [f"Numbness of left {s}", f"Numbness of right {s}", f"Left {s} numb", f"Right {s} numb"]
        add_pt(f"Numbness of {s}", llts, "neuro", "Sensory disturbance by body site", "numbness", slots={"site": s})
        llts = [f"Tenderness of {s}", f"Tender {s}", f"{cap(s)} tenderness"]
        if paired: llts += [f"Left {s} tender", f"Right {s} tender"]
        add_pt(f"Tenderness of {s}", llts, "msk", "Tenderness by body site", "tenderness", slots={"site": s})
        if paired:
            add_pt(f"Weakness of {s}", [f"Weakness of {s}", f"{cap(s)} weakness", f"Weak {s}", f"Left {s} weak", f"Right {s} weak"],
                   "msk", "Muscle weakness by body site", "weakness", slots={"site": s})
            add_pt(f"Cramp in {s}", [f"Cramp in {s}", f"{cap(s)} cramp", f"Cramping of {s}"],
                   "msk", "Muscle cramps by body site", "cramp", slots={"site": s})
    for s in JOINTS:
        add_pt(f"{cap(s)} stiffness", [f"{cap(s)} stiffness", f"Stiffness of {s}", f"Stiff {s}", f"Reduced movement of {s}"],
               "msk", "Joint stiffness", "stiffness", slots={"site": s})
    # skin: one PT per concept, LLTs per site
    for pt, pats, fam in [("Rash", ["Rash on {s}", "{S} rash"], "rash"), ("Pruritus", ["Itching of {s}", "Itchy {s}"], "pruritus"),
                          ("Erythema", ["Redness of {s}", "Erythema of {s}"], "erythema"), ("Skin lesion", ["Lesion on {s}", "Skin lesion of {s}"], "lesion")]:
        llts = [pt] + [p.format(s=s, S=cap(s)) for s in SKIN for p in pats]
        add_pt(pt, llts, "skin", "Skin reactions", fam, slots={"site": SKIN})
    # injuries
    for b in BONES:
        llts = [f"Fracture of {b}", f"{cap(b)} fracture", f"Broken {b}", f"{cap(b)} fractured"]
        llts += [f"{k} fracture of {b}" for k in ("Closed", "Open", "Stress", "Hairline")]
        if b in ("wrist","ankle","hip","foot","hand","finger","toe","rib"): llts += [f"Left {b} fracture", f"Right {b} fracture"]
        add_pt(f"{cap(b)} fracture", llts, "injury", "Fractures", "fracture", slots={"site": b})
    for pt, pats, fam in [("Laceration", ["Laceration of {s}", "Cut on {s}", "{S} laceration"], "laceration"),
                          ("Contusion", ["Contusion of {s}", "Bruise on {s}", "Bruised {s}"], "contusion"),
                          ("Skin abrasion", ["Abrasion of {s}", "Graze on {s}", "Scraped {s}"], "abrasion"),
                          ("Thermal burn", ["Burn of {s}", "Burnt {s}", "Scald on {s}"], "burn"),
                          ("Blister", ["Blister on {s}", "{S} blister"], "blister"),
                          ("Abscess", ["Abscess of {s}", "{S} abscess"], "abscess")]:
        add_pt(pt, [pt] + [p.format(s=s, S=cap(s)) for s in WOUND_SITES for p in pats], "injury", "Skin injuries", fam, slots={"site": WOUND_SITES})
    # investigations
    for a, abbr, grp in ANALYTES:
        hlt = f"{cap(grp)} investigations"
        up = [f"{cap(a)} increased", f"Increased {a}", f"High {a}", f"Elevated {a}", f"{cap(a)} above normal", f"Raised {a}"]
        dn = [f"{cap(a)} decreased", f"Decreased {a}", f"Low {a}", f"{cap(a)} below normal", f"Reduced {a}"]
        if abbr: up += [f"{abbr} increased", f"Raised {abbr}"]; dn += [f"{abbr} decreased", f"Low {abbr}"]
        add_pt(f"{cap(a)} increased", up, "lab", hlt, "lab_up", slots={"analyte": a, "abbr": abbr})
        add_pt(f"{cap(a)} decreased", dn, "lab", hlt, "lab_down", slots={"analyte": a, "abbr": abbr})
        ab = [f"{cap(a)} abnormal", f"Abnormal {a}", f"{cap(a)} out of range"] + ([f"{abbr} abnormal"] if abbr else [])
        add_pt(f"{cap(a)} abnormal", ab, "lab", hlt, "lab_abn", slots={"analyte": a, "abbr": abbr})
    # infections
    for org, coll in ORGANS:
        llts = [f"{cap(org)} infection", f"Infection of {org}", f"{cap(org)} infection bacterial", f"{cap(org)} infection viral"]
        add_pt(f"{cap(org)} infection", llts, "infection", "Infections by site", "infection", slots={"site": org, "coll": coll})
    # standalone symptoms
    for pt, syn, coll, grp in SYMPTOMS:
        add_pt(pt, [pt] + syn, grp, f"{cap(grp)} signs and symptoms", "symptom", collo=coll)
    # injection-site family
    for kind, coll in [("pain", "sore where the needle went in"), ("swelling", "lump where the shot was given"),
                       ("erythema", "red patch around the jab"), ("bruising", "bruise at the needle site"),
                       ("pruritus", "itchy spot where injected"), ("induration", "hard bump at injection spot")]:
        pt = f"Injection site {kind}"
        add_pt(pt, [pt, f"{cap(kind)} at injection site", f"Injection site {kind} mild"], "general",
               "Injection site reactions", "symptom", collo=[coll])
    return rows, concepts

# --------------------------------------------------------------------------- #
# Coding verbatims. Colloquial text is written per family; misspellings are seeded character
# edits; negations wrap the term in a denial. Each verbatim records the PT it should code to.
# --------------------------------------------------------------------------- #
COLLO = {
 "pain": ["{s} hurts a lot","aching in my {s}","{s} has been sore all week","sharp pain in the {s}","{s} killing me"],
 "swelling": ["{s} looks puffy","{s} is swollen up","{s} blown up and tender","puffy {s} since yesterday"],
 "stiffness": ["{s} won't bend properly","{s} feels locked","can't move my {s} freely"],
 "rash": ["red bumps on {s}","{s} breaking out in spots","blotchy patch on {s}"],
 "pruritus": ["{s} itches like mad","itchy patch on {s}","can't stop scratching {s}"],
 "erythema": ["{s} gone red","red skin on {s}","{s} looks flushed red"],
 "lesion": ["sore spot on {s} skin","odd mark on {s}"],
 "fracture": ["broke my {s}","{s} broken after fall","cracked {s}"],
 "laceration": ["cut my {s} on glass","gash on {s}","sliced {s} with knife"],
 "contusion": ["bruised {s} after bumping it","{s} black and blue","banged {s}, now bruised"],
 "abrasion": ["scraped skin off {s}","grazed {s} on pavement"],
 "lab_up": ["{a} came back high","{a} above upper limit","raised {a} on labs","{a} up on bloods"],
 "lab_down": ["{a} came back low","{a} below lower limit","{a} dropped on labs","{a} down on bloods"],
 "infection": ["{c} infection, on antibiotics","{c} infected","infection in {c}"],
 "numbness": ["can't feel my {s}","{s} gone numb","{s} feels dead"],
 "tenderness": ["{s} sore to touch","{s} tender when pressed"],
 "weakness": ["{s} feels weak","no strength in {s}"],
 "cramp": ["{s} cramping up","cramp in my {s} at night"],
 "burn": ["burnt {s} on the stove","scalded {s} with hot water"],
 "blister": ["blister came up on {s}","bubble of skin on {s}"],
 "abscess": ["boil on {s}","pus-filled lump on {s}"],
 "lab_abn": ["{a} off on labs","{a} out of range on bloods"],
}
NEG = ["denies {t}","no {t}","{t} ruled out","no evidence of {t}","patient reports no {t}","negative for {t}"]

def misspell(term, rng):
    """1 or 2 seeded character edits on words of 4+ letters (transpose, drop, double, swap vowel)."""
    words = term.split(); cand = [i for i, w in enumerate(words) if len(w) >= 4 and w.isalpha()]
    if not cand: return term[:-1] if len(term) > 3 else term + term[-1]
    for _ in range(rng.choice([1, 2])):
        i = rng.choice(cand); w = list(words[i]); j = rng.randrange(1, len(w) - 1); op = rng.choice(["tr", "drop", "dbl", "vow"])
        if op == "tr": w[j], w[j + 1] = w[j + 1], w[j]
        elif op == "drop": del w[j]
        elif op == "dbl": w.insert(j, w[j])
        else:
            vs = [k for k, c in enumerate(w) if c in "aeiou"]
            if vs: k = rng.choice(vs); w[k] = rng.choice([v for v in "aeiou" if v != w[k]])
        words[i] = "".join(w)
    out = " ".join(words)
    return out if out != term else term + term[-1]

def colloquial(pt, c, rng):
    fam = c["family"]; sl = c["slots"]
    if c["collo"]: return rng.choice(c["collo"])
    if fam not in COLLO: return None
    tmpl = rng.choice(COLLO[fam])
    if fam in ("lab_up", "lab_down", "lab_abn"):
        a = sl["abbr"] if sl.get("abbr") and rng.random() < 0.5 else sl["analyte"].replace("blood ", "")
        return tmpl.format(a=a)
    if fam == "infection": return tmpl.format(c=sl["coll"])
    s = sl["site"]; s = rng.choice(s) if isinstance(s, list) else s
    return tmpl.format(s=s)

def build_coding(rows, concepts, rng):
    by_pt = {}
    for r in rows: by_pt.setdefault(r["pt_name"], []).append(r["llt_name"])
    pts = sorted(p for p in concepts if colloquial(p, concepts[p], random.Random(0)) is not None)
    rng.shuffle(pts); pts = pts[:480]
    n = len(pts); cut1, cut2 = int(n * 0.6), int(n * 0.8)
    split = {p: ("train" if i < cut1 else "calib" if i < cut2 else "test") for i, p in enumerate(pts)}
    out = []; k = 0
    for p in sorted(pts):
        c = concepts[p]; llts = sorted(by_pt[p])
        src = rng.choice(llts)
        variants = [("exact", src.lower(), src),
                    ("colloquial", colloquial(p, c, rng), None),
                    ("misspelled", misspell(rng.choice(llts).lower(), rng), None),
                    ("negated", rng.choice(NEG).format(t=rng.choice(llts).lower()), None)]
        for v, text, s in variants:
            k += 1
            out.append(dict(id=f"C{k:05d}", verbatim=text, variant=v, negated="Y" if v == "negated" else "N",
                            pt_code=c["pt_code"], pt_name=p, split=split[p]))
    return out

# --------------------------------------------------------------------------- #
# PHI fields. Each template is a list of literal text and typed slots; a slot either produces a
# gold identifier span (entity + direct/indirect) or a look-alike (no span). Offsets are recorded
# while the string is assembled, so the gold spans are exact by construction.
# --------------------------------------------------------------------------- #
FIRST = ["Jane","Robert","Maria","David","Linda","James","Ana","Thomas","Grace","Daniel","Helen","Samuel",
         "Laura","Victor","Nadia","Oscar","Irene","Paul","Rosa","Henry","Clara","Martin","Elena","Felix"]
LAST = ["Miller","Chen","Gonzalez","Okafor","Novak","Patel","Hughes","Lindqvist","Moreau","Tanaka","Brennan",
        "Silva","Kowalski","Haddad","Fischer","Duarte","Ivanova","Mensah","Larsen","Romero","Weber","Quinn"]
DRUGS = ["Lisinopril","Metformin","Atorvastatin","Alanine","Ondansetron","Amlodipine","Sertraline","Omeprazole",
         "Ibuprofen","Paracetamol","Levothyroxine","Cetirizine"]
LABS = ["glucose 120 mg/dL","ALT 54 U/L","creatinine 1.1 mg/dL","potassium 4.2 mmol/L","QTc 452 ms",
        "BP 128/84","Hb 13.2 g/dL","platelets 210","temp 37.8 C","HR 88 bpm"]
DIRECT = {"PERSON_NAME","PHONE","EMAIL","MRN","DOB"}
INDIRECT = {"ZIP","INITIALS","AGE"}

def slot(kind, rng):
    """Return (text, entity or None). entity None = look-alike / no identifier."""
    f, l = rng.choice(FIRST), rng.choice(LAST)
    d3 = lambda: f"{rng.randrange(100,999)}"
    if kind == "NAME": return f"{f} {l}", "PERSON_NAME"
    if kind == "LAST": return l, "PERSON_NAME"
    if kind == "PHONE":
        a, n = rng.choice(["617","800","415","312","646","206"]), f"555-01{rng.randrange(0,100):02d}"
        return rng.choice([f"({a}) {n}", f"{a}-{n}", f"{a}.{n.replace('-', '.')}"]), "PHONE"
    if kind == "PHONE7": return f"555-01{rng.randrange(0,100):02d}", "PHONE"
    if kind == "MRN": return f"{d3()}-{d3()}-{rng.randrange(10,99)}", "MRN"
    if kind == "MRN8": return f"{rng.randrange(10**7, 10**8)}", "MRN"
    y, m, dd = rng.randrange(1938, 2004), rng.randrange(1, 13), rng.randrange(1, 29)
    if kind == "DOB": return f"{m:02d}/{dd:02d}/{y}", "DOB"
    if kind == "DOB_ISO": return f"{y}-{m:02d}-{dd:02d}", "DOB"
    if kind == "DOB_SHORT": return f"{m}/{dd}/{y}", "DOB"
    if kind == "EMAIL": return f"{f.lower()}.{l.lower()}@example.org", "EMAIL"
    if kind == "ZIP": return f"{rng.choice(['02','10','60','94','30','98'])}{rng.randrange(100,999)}", "ZIP"
    if kind == "INIT": return f"{f[0]}.{l[0]}.", "INITIALS"
    if kind == "INIT_NODOT": return f"{f[0]}{l[0]}", "INITIALS"
    if kind == "AGE": return f"{rng.randrange(19, 86)}-year-old", "AGE"
    if kind == "DRUG": return rng.choice(DRUGS), None
    if kind == "LAB": return rng.choice(LABS), None
    if kind == "DOSE": return f"{rng.choice([5,10,20,25,50,100,250,500])} mg", None
    if kind == "TIME": return f"{rng.randrange(6,22):02d}:{rng.choice(['00','15','30','45'])}", None
    if kind == "KIT": return f"{rng.randrange(10000, 99999)}", None
    if kind == "VISIT": return f"Visit {rng.randrange(2, 12)}", None
    raise KeyError(kind)

# (template id, parts). "{X}" = slot X; anything else is literal text.
TEMPLATES = [
 ("T01", ["CRC Note: Patient ","{NAME}"," called site cell phone ","{PHONE}"," at ","{TIME}","."]),
 ("T02", ["Patient ","{NAME}"," tolerating well; continued ","{DRUG}"," ","{DOSE}","; repeat ","{LAB}","."]),
 ("T03", ["Subject ","{INIT}"," (MRN ","{MRN}","), DOB ","{DOB}",", residing ","{ZIP}",", missed the ","{TIME}"," dose window."]),
 ("T04", ["Spoke with ","{NAME}"," about the rash; callback ","{PHONE}","."]),
 ("T05", ["Sinus rhythm, no artifact."]),
 ("T06", ["{AGE}"," participant, initials ","{INIT}",", lives in ","{ZIP}","; headache resolved."]),
 ("T07", ["Kit ","{KIT}"," dispensed; ","{DRUG}"," ","{DOSE}"," taken at ","{TIME}","."]),
 ("T08", ["Dr. ","{LAST}"," reviewed ECG; ","{LAB}","; no action needed."]),
 ("T09", ["Daughter ","{NAME}"," reported a fall at home; contact ","{PHONE}","."]),
 ("T10", ["MRN: ","{MRN8}","; participant ","{INIT_NODOT}"," seen for follow-up."]),
 ("T11", ["Lab draw at ","{TIME}","; ","{LAB}","; ","{LAB}","; within range."]),
 ("T12", ["Mr. ","{LAST}"," asked to reschedule ","{VISIT}","; prefers mornings."]),
 ("T13", ["Repeat ECG ordered; participant resting comfortably."]),
 ("T14", ["Participant emailed ","{EMAIL}"," to report nausea after ","{DRUG}","."]),
 ("T15", ["Born ","{DOB_ISO}","; zip ","{ZIP}","; initials ","{INIT}","."]),
 ("T16", ["Reached ","{NAME}"," on ","{PHONE7}","; symptoms improving."]),
 ("T17", ["DOB ","{DOB_SHORT}"," confirmed against source; ","{LAB}","."]),
 ("T18", ["Started ","{DRUG}"," ","{DOSE}"," daily; ","{LAB}"," at baseline."]),
 ("T19", ["Ms. ","{NAME}"," (","{AGE}",") withdrew consent at ","{VISIT}","."]),
 ("T20", ["No issues reported; next dose at ","{TIME}","."]),
 ("T21", ["Caregiver ","{NAME}",", phone ","{PHONE}",", will bring participant to ","{VISIT}","."]),
 ("T22", ["Initials ","{INIT}"," and postal code ","{ZIP}"," noted on the paper CRF."]),
 ("T23", ["Medical record ","{MRN}"," pulled for the SAE narrative."]),
 ("T24", ["Kit ","{KIT}"," and kit ","{KIT}"," returned unused."]),
 ("T25", ["Participant ","{INIT_NODOT}",", ","{AGE}",", from ","{ZIP}",", reported dizziness."]),
 ("T26", ["Called ","{NAME}","'s spouse at ","{PHONE}"," about missed ","{VISIT}","."]),
 ("T27", ["","{DRUG}"," held for ","{LAB}","; restarted after review."]),
 ("T28", ["Patient ","{NAME}",", DOB ","{DOB}",", MRN ","{MRN}",", admitted overnight."]),
 ("T29", ["Mild nausea after the ","{TIME}"," dose; resolved without treatment."]),
 ("T30", ["Contact the site coordinator ","{NAME}"," at ","{EMAIL}"," with questions."]),
 ("T31", ["Seen by Dr. ","{LAST}","; ","{DRUG}"," ","{DOSE}"," prescribed."]),
 ("T32", ["","{AGE}"," with initials ","{INIT}"," enrolled at the north site."]),
 ("T33", ["Vitals stable: ","{LAB}",", ","{LAB}","."]),
 ("T34", ["Record number ","{MRN8}"," belongs to ","{NAME}","."]),
 ("T35", ["Participant lives at zip ","{ZIP}"," and works nights."]),
 ("T36", ["Reminder sent; ","{NAME}"," confirmed ","{VISIT}"," by phone ","{PHONE}","."]),
 ("T37", ["Dose reduced to ","{DOSE}"," after ","{LAB}","."]),
 ("T38", ["DOB on ID was ","{DOB}","; initials ","{INIT}"," match the log."]),
 ("T39", ["Rash on left forearm, photographed for the file."]),
 ("T40", ["Husband ","{NAME}"," says she has been dizzy since ","{VISIT}","."]),
]

# Template -> split, assigned BY HAND rather than at random: with only 40 templates a random draw
# left whole identifier types (and the mosaic case) out of a split. Each split covers names,
# phones, record numbers, birth dates, the mosaic, look-alikes and a clean note; test also holds
# formats training never sees (a 7-digit phone, a short-form DOB, an undotted record number
# template), so the test numbers measure generalization, not memorized templates.
SPLIT_TEST = {"T03","T04","T07","T10","T13","T14","T16","T17","T31","T32"}
SPLIT_CALIB = {"T01","T06","T09","T11","T15","T23","T27","T39"}

def build_phi(rng, per_template=22):
    split = {t: ("test" if t in SPLIT_TEST else "calib" if t in SPLIT_CALIB else "train") for t, _ in TEMPLATES}
    fields, spans = [], []; k = 0
    for tid, parts in TEMPLATES:
        for _ in range(per_template):
            k += 1; fid = f"P{k:05d}"; text = ""; gs = []
            for p in parts:
                m = re.fullmatch(r"\{([A-Z0-9_]+)\}", p)
                if not m: text += p; continue
                val, ent = slot(m.group(1), rng)
                if ent: gs.append((len(text), len(text) + len(val), val, ent))
                text += val
            ndir = sum(1 for g in gs if g[3] in DIRECT); nind = sum(1 for g in gs if g[3] in INDIRECT)
            quasi = nind >= 2
            fields.append(dict(field_id=fid, template=tid, split=split[tid], text=text,
                               has_direct="Y" if ndir else "N", has_quasi="Y" if quasi else "N"))
            for a, b, val, ent in gs:
                kind = "direct" if ent in DIRECT else "indirect"
                # Redaction target = the app's declared policy: a DIRECT identifier always; an INDIRECT
                # one only when two or more indirect attributes co-occur in the field (the mosaic).
                spans.append(dict(field_id=fid, start=a, end=b, span=val, entity=ent, kind=kind,
                                  target="Y" if (kind == "direct" or quasi) else "N"))
    return fields, spans

def write(name, rows, cols):
    with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)

def main():
    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(SEED)
    rows, concepts = build_dictionary()
    assert len({r["llt_code"] for r in rows}) == len(rows), "duplicate llt_code"
    assert all(re.fullmatch(r"99\d{6}", r[c]) for r in rows for c in COLS if c.endswith("_code")), "non-placeholder code"
    write("dictionary.csv", rows, COLS)
    coding = build_coding(rows, concepts, rng)
    write("coding_eval.csv", coding, ["id","verbatim","variant","negated","pt_code","pt_name","split"])
    fields, spans = build_phi(rng)
    write("phi_fields.csv", fields, ["field_id","template","split","text","has_direct","has_quasi"])
    write("phi_spans.csv", spans, ["field_id","start","end","span","entity","kind","target"])
    npt = len({r["pt_code"] for r in rows})
    print(f"dictionary: {len(rows)} LLTs, {npt} PTs | coding: {len(coding)} verbatims | "
          f"PHI: {len(fields)} fields, {len(spans)} gold spans")

if __name__ == "__main__":
    main()
