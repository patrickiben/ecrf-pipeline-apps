#!/usr/bin/env python3
"""Sibling sets for the within-sibling evaluation of the Coding QC assist (SYNTHETIC, not MedDRA).

Run from anywhere:   python eval/sibling_sets.py            (writes eval/data/sibling_sets.csv)
                     python eval/sibling_sets.py --check    (exit 1 if the committed file is out of date)

A sibling set is a group of preferred terms (PTs) that share one neighborhood and differ in exactly
the choice a coder has to get right once the neighborhood is found. Two families, each defined by a
rule on PT NAMES only:

  lab    "<stem> increased", "<stem> decreased", "<stem> abnormal": the direction of a lab finding.
         A stem forms a set only when all three PTs exist (a complete triplet).
  site   "Pain in <site>", "Swelling of <site>", "Numbness of <site>", "Tenderness of <site>",
         "Weakness of <site>", "Cramp in <site>": the finding at one body site. A site forms a set
         when two or more of the six PTs exist.

The rule reads eval/data/dictionary.csv and nothing else: no verbatim, no gold code, no score. So the
sets are fixed before anything is scored (eval/sibling_plan.md registers them by checksum). This
script never runs or changes eval/make_data.py, and its outputs are unaffected.

Output columns: family, set_id (the stem or the site), set_size, role, pt_code, pt_name, n_llt
(the number of lowest-level terms under the PT). Rows are sorted by family, set_id and role order.
"""
import argparse, csv, io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DICT = os.path.join(HERE, "data", "dictionary.csv")
OUT = os.path.join(HERE, "data", "sibling_sets.csv")
COLS = ["family", "set_id", "set_size", "role", "pt_code", "pt_name", "n_llt"]

LAB_ROLES = ("increased", "decreased", "abnormal")
# role -> the PT-name prefix that carries it
SITE_ROLES = (("pain", "Pain in"), ("swelling", "Swelling of"), ("numbness", "Numbness of"),
              ("tenderness", "Tenderness of"), ("weakness", "Weakness of"), ("cramp", "Cramp in"))
ROLES = {"lab": LAB_ROLES, "site": tuple(r for r, _ in SITE_ROLES)}

_LAB = re.compile(r"(.+) (increased|decreased|abnormal)")
_SITE = re.compile(r"(" + "|".join(p for _, p in SITE_ROLES) + r") (.+)")
_PREFIX_ROLE = {p: r for r, p in SITE_ROLES}

def build(dict_path=DICT):
    """Return the sibling-set rows (list of dicts, COLS order) derived from the dictionary's PT names."""
    pts, n_llt = {}, {}
    with open(dict_path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            pts.setdefault(r["pt_name"], r["pt_code"])
            n_llt[r["pt_name"]] = n_llt.get(r["pt_name"], 0) + 1
    lab, site = {}, {}
    for name in pts:
        m = _LAB.fullmatch(name)
        if m: lab.setdefault(m.group(1), {})[m.group(2)] = name
        m = _SITE.fullmatch(name)
        if m: site.setdefault(m.group(2), {})[_PREFIX_ROLE[m.group(1)]] = name
    rows = []
    for stem in sorted(lab):
        if set(lab[stem]) != set(LAB_ROLES): continue                 # incomplete triplet: not a set
        for role in LAB_ROLES:
            p = lab[stem][role]
            rows.append(dict(family="lab", set_id=stem, set_size=3, role=role, pt_code=pts[p], pt_name=p, n_llt=n_llt[p]))
    for s in sorted(site):
        members = [r for r in ROLES["site"] if r in site[s]]
        if len(members) < 2: continue                                 # a singleton has no sibling
        for role in members:
            p = site[s][role]
            rows.append(dict(family="site", set_id=s, set_size=len(members), role=role, pt_code=pts[p], pt_name=p, n_llt=n_llt[p]))
    return rows

def render(rows):
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=COLS, lineterminator="\n"); w.writeheader(); w.writerows(rows)
    return buf.getvalue()

def load(path=OUT):
    """The committed sets: {family: {set_id: [(role, pt_code, pt_name), ...]}} in file order."""
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["family"], {}).setdefault(r["set_id"], []).append((r["role"], r["pt_code"], r["pt_name"]))
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="compare with the committed file instead of writing it")
    a = ap.parse_args()
    rows = build(); text = render(rows)
    sets = {(r["family"], r["set_id"]): r["set_size"] for r in rows}
    sizes = {}
    for (fam, _), k in sets.items(): sizes.setdefault(fam, {}).setdefault(k, 0); sizes[fam][k] += 1
    summary = "; ".join(f"{fam}: {sum(v.values())} sets ({', '.join(f'{n} of size {k}' for k, n in sorted(v.items()))})"
                        for fam, v in sorted(sizes.items()))
    if a.check:
        same = os.path.exists(OUT) and open(OUT, encoding="utf-8", newline="").read() == text
        print(("OK " if same else "STALE ") + os.path.relpath(OUT, os.path.dirname(HERE)) + " | " + summary)
        sys.exit(0 if same else 1)
    with open(OUT, "w", encoding="utf-8", newline="") as f: f.write(text)
    print(f"wrote {os.path.relpath(OUT, os.path.dirname(HERE))}: {len(rows)} PTs | {summary}")

if __name__ == "__main__":
    main()
