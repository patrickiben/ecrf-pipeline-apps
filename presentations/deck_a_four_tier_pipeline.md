# The Four-Tier Pipeline

**Conceptual deck · QC'd build, October 2026**
Companion to [Deck B — Implementation Walkthrough](deck_b_implementation_walkthrough.md) and the runnable apps in [`../`](../README.md).

---

## A1 — Scope

- An on-premises engine: four named tiers run in sequence on local hardware, no network call, no cloud model, no external server.
- Two capabilities over eCRF extracts on disk — propose a MedDRA code for an adverse-event verbatim, and find and scrub PII/PHI in the free-text fields sites leak into (the spec names `AECOM` and `AESPID` as the usual offenders; the scan reaches every non-numeric column by content, not by a hard-coded name list).
- The two are separate programs with separate outputs and separate audit sections; neither reads the other's field. What this deck explains is the tier chain they share.

## A2 — A chain of contracts, not one model

- A single text-to-code model maps the verbatim to a preferred term inside one weight matrix, so “the dictionary lookup matched well” and “this token is a drug name, not a patient name” are not separable — there is no intermediate quantity to read or to set a limit on.
- This stack splits the work so each tier emits named columns the next tier consumes, and the final tier receives only numbers derived from the text, never the text as words.
- The test applied to every tier: does the decision tier see words, or fixed numbers from earlier tiers? Here, numbers only.
- The payoff is that a decision becomes a row of readable columns and its limit becomes a parameter a reviewer can move without retraining.

## A3 — The four tiers, named and identified

| Tier | Product | What it is, in one line | Hands forward |
|---|---|---|---|
| **Tier 1** | eCRF intake / normalizer (the document-mode front-end is **LiteParse**, not exercised here) | aligns each incoming row to its participant, copies the verbatim and every field through unchanged, and discovers which columns to scan by content — every non-numeric column — rather than a name-based rule | the untouched verbatim; the untouched free-text strings; the detected column list |
| **Tier 2** | **Cactus Needle3** | a Laddered Simple Attention Network on CPU/NPU that does Pydantic-schema entity extraction and encodes the verbatim to a 3072-dim unit vector (its own general-purpose embedding, not a biomedical encoder such as SapBERT), retrieving the nearest MedDRA terms from an HNSW inner-product graph | candidate terms with their full hierarchy path (LLT→PT→HLT→HLGT→SOC) + closeness numbers; identifier spans + type + in-field offsets |
| **Tier 3** | **Laya** | a non-autoregressive classifier (ModernBERT backbone + decision head) that answers fixed yes/no, rating and pick questions about a string in one pass (about 0.3 s per question on a 4-vCPU CPU, measured) and returns probabilities calibrated by a temperature fitted on labeled data | `P(direct PHI)`, `P(re-identification risk)`; the ambiguity scalar the coding re-ranker consumes |
| **Tier 4** | **XGBoost** | a boosted-tree ensemble (under 10 ms per record, measured) that reads only the named columns from Tiers 1–3 and applies an explicit, movable rule — re-rank + gate for coding, per-span redaction for PHI | coded fields + status; scrubbed field copies + per-row flag |

- Coding is fed by Tier 2 and Tier 4 (the Tier-3 ambiguity scalar is an extra booster feature); PHI is fed by Tiers 1, 2 and 3 into Tier 4. The two heads share the Tier-4 discipline, not an identical input list.
- Measured on a 4-vCPU CPU with no GPU, one record takes about 0.4 s through the coding chain and 0.9 to 1.6 s through the PHI chain, most of it in Laya and in Needle3's extraction; batched over a cut, coding ran at about 0.23 s per verbatim. That is batch speed, not the sub-50 ms this deck once targeted. The per-stage breakdown is in [EVALUATION.md](../docs/EVALUATION.md); the index tuning knobs live in the app.

## A4 — Tier 1 · eCRF intake & normalization

- Aligns each incoming row to its participant and copies the source text byte-for-byte, so the verbatim Tier 2 will match and the comment strings Tier 4 will scrub are exactly what the site entered.
- Column discovery is **content-based, not name-based**: every column that is *not* strictly numeric — text, dates, coded values, flags — is a scan candidate, because PHI can hide in any of them and a pre-specified list of column names is guaranteed to have gaps. Only columns typed as a number are skipped; the operator confirms or deselects columns in the app's pre-flight before anything runs.
- A missing value is kept as missing, not turned into an empty string that would scan silently clean. Structured fields (dates, IDs) are scanned like any other text and flagged if they match an identifier pattern — review flags before trusting them, or deselect a known-safe column.
- There is no page, no layout and no coordinate map in this scope: the input is eCRF tabular extracts, so Tier 1's only job is faithful alignment and honest column discovery. (LiteParse is the document-mode front-end that builds a spatial map for scanned pages; it is not invoked here.)

## A5 — Tier 2 · Cactus Needle3 — retrieval & extraction

- Coding returns terms that are similar to the verbatim in meaning rather than in spelling, so a mangled entry can still reach the right preferred term without a typo dictionary. Measured on synthetic data, that holds for misspellings (top-1 0.81, against 0.19 for a lexical matcher) and only partly for colloquial phrasing (0.52): the embedding does not separate “calcium down” from “calcium increased”. It encodes the lower-cased verbatim to a 3072-dim unit vector and retrieves the nearest dictionary entries from the HNSW graph; because the stored vectors are L2-normalized, the graph's inner-product distance *is* cosine, so the cheap search returns exact angular closeness.
- The dictionary is the full active MedDRA release (a licensed release the user supplies; none is included here) held in the graph index — ~86,800 LLTs under ~25,700 preferred terms, grouped into High Level Terms by anatomy, pathology, physiology, etiology or function; related HLTs linked to High Level Group Terms (136 of them); and HLGTs grouped into the 27 System Organ Classes — resident in roughly 1 GB at Needle3's 3072 dimensions (measured on random vectors of that width). Every candidate carries its full LLT→PT→HLT→HLGT→SOC path as evidence columns beside the write-back fields; the index's speed-versus-completeness knobs are tuning parameters, not part of what the tier emits.
- PHI returns *typed* spans: you declare the identifier classes and their types (patient name, MRN, DOB, phone, address, …) and it returns values matching that declaration or flags a mismatch — Pydantic-schema parsing, not a pattern library.
- That distinction is the whole reason this tier exists separately: a pattern matcher cannot tell a drug name or a lab result from a patient name or an account number, because they look alike on the surface; only a declared type plus the surrounding text separates them. The walkthrough shows the exact look-alike case.
- This tier proposes candidates and localizes spans; it decides nothing. (Needle3's tool-execution routing is not used in this build.)

## A6 — Tier 3 · Laya — context & calibration

- A non-autoregressive classifier that answers a fixed list of questions about a string or field in one forward pass and emits no text — which is why it is usable here where a generative model is not: the output is repeatable and the numbers are calibratable.
- Each question is declared as yes/no, an ordered rating, or a pick-from-a-list (`noul` / `score` / `choice`), scored in one shot, so there is no decoding step and nothing to parse.
- Raw scores are rescaled by a single learned constant before the logistic function (temperature scaling) so a reported probability tracks its observed frequency — the design target is that an output of 0.85 reflects an ~85% historical rate; calibration is then *measured* on held-out labels (expected calibration error against a pre-specified bound) rather than assumed. Measured here on synthetic labels: the fitted temperature cut the coding question's ECE from 0.12 to 0.08, but Laya's direct-identifier answer stayed poorly calibrated (ECE 0.49, AUROC 0.69), because no temperature fixes a probability that is biased low.
- For PHI it returns the probability that direct identifiers are present and the probability that indirect attributes jointly re-identify someone; the eCRF worked rows exercise both.
- For coding it supplies an ambiguity scalar — the probability the verbatim maps to a single clean concept — which Tier 4's re-ranker consumes as an extra feature alongside the retrieval cosine and the string distances, so a verbatim whose *term* matches well but whose *sentence* is blurred can be pushed below the gate.

## A7 — Tier 4 · XGBoost — the two decision heads

- A boosted-tree ensemble reads only the named columns from Tiers 1–3; it never re-reads the verbatim as words. Both heads share that constraint; they differ in the rule they apply.
- **Coding head.** Re-ranks the retrieved candidates with a boosted-tree classifier (`binary:logistic`, one score per candidate) over retrieval cosine, retrieval rank, normalized edit-distance similarity, Jaro-Winkler similarity, a body-system agreement indicator and the Tier-3 ambiguity scalar; the stand-in uses the first four as a fixed weighted sum whose weights sum to one. Above a reviewer-set confidence gate the coded fields are auto-populated; below it the top candidates are pre-populated into the human coding queue. The gate is a configurable operating point (the build defaults to 0.88; a 0.90 setting is also exercised in the worked routing), recorded in the audit, not a constant invented in code.
- **PHI head.** Predicts, per span, a redaction probability from the Tier-2 span match and type, the two Tier-3 probabilities (direct identifier, re-identification), and in-field lexical cues, and scrubs above a reviewer-set cutoff (default 0.85). Because the input is a database field there is no page to black out, so a positive decision writes a scrubbed copy of the field (`SAN_<field>`) and a per-row flag; the per-token geometry/header rule belongs to the scanned-document path and is not executed here.
- *Note:* the two heads are why Tier 4 is one tier with two rules rather than two tiers — the upstream columns are the same kind of named evidence; only the decision rule differs.

## A8 — Why the tiers are separate

- The look-alike problem and the borderline-match problem are the two reasons the tiers are split. A pattern matcher over a free-text field must decide, token by token, what is an identifier, and it cannot when a drug name and a lab value sit beside a real patient name in the same string; only a declared type plus a field-level probability separates them, and that is Tier 2 plus Tier 3, not one of them alone.
- Likewise a retrieval cosine alone cannot decide coding, because two candidates can be equally close and only a learned comparison plus the ambiguity scalar plus a threshold settles which one is written; a high cosine on a term the surrounding sentence blurs is exactly the case the separate Tier-3 reading is meant to catch.
- Drop Tier 3 and the look-alike false-positive returns; drop Tier 4's explicit rule and the gate stops being a parameter a reviewer can move. The chain is not decoration — it is what keeps each of those judgments a readable number instead of a hidden weight.

## A9 — Governance and limits

- **Determinism and audit:** fixed seeds, frozen compiled artifacts, exact vector arithmetic; the audit records the run, the dictionary it was given (file, rows, detected columns, hash), every effective threshold and term list, the per-decision reasons, and every override with its reason — so a run is reproducible from its audit alone, the two heads keep separate audit sections, and the PHI log records redacted spans *without* retaining raw PHI in secondary storage.
- **Human-in-the-loop by construction:** the engine proposes, a qualified person decides, low-confidence matches arrive pre-populated with their top candidates, overrides are logged and never silent, sign-off is captured under 21 CFR Part 11.
- **MedDRA is licensed:** the engine records the dictionary it was given and does not verify the subscription. The PHI output is compliance-*enabling* — it supports HIPAA/GDPR-aligned de-identification given configuration, validation and access controls — but the stack does not by itself certify compliance; that remains an organizational determination.
- It does not replace the medical coders, does not retain raw identifiers outside the audit-controlled store, does not derive clinical variables or make dosing decisions, and does not send a byte off-network. Without a models dir, Tiers 2 to 4 run as labeled deterministic stand-ins behind the same output contract; with one, the real Needle3, Laya and XGBoost path runs, measured on synthetic data only ([EVALUATION.md](../docs/EVALUATION.md)). Either way the trace validates the chain and the gates, not clinical truth; the audit prints which path ran per tier.
