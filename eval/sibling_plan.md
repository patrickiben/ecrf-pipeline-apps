# Within-sibling evaluation of the Coding QC assist: registered plan

Registered 2026-10-25, before any scoring. Synthetic data only: the dictionary is invented terms with 99-prefixed placeholder codes, not MedDRA.

This file is locked by `eval/sibling_plan.sha256`. `eval/sibling_eval.py` and `eval/sibling_knownanswer.py` compute the SHA-256 of this file and refuse to run when it differs from the committed value. The parameters in section 15 are read from this file after that check, so the scripts cannot drift from it. Any change after scoring needs a new plan and must be reported as a deviation next to the results.

The design is adapted from the within-site permutation design of the AlphaGenome audit (Iben P., Human Genomics, submitted; preprint doi:10.5281/zenodo.23543154): a statistic over a fixed choice set per unit, the label relabeled within the unit under stated nulls, exact tails by convolution, false discovery control within a family, readings set in advance, and a model-free rule reported beside the scorer.

## 1. Question

The evaluation in `docs/EVALUATION.md` shows that the assist often finds the right neighborhood and then picks the wrong sibling: "calcium down on bloods" retrieves "Blood calcium increased" above "Blood calcium decreased". This plan asks one narrower question per family of sibling terms: once the right neighborhood is given, does the tool pick the right member, how much better than chance and than a keyword rule, and is it accurate enough to auto-code that family?

## 2. Sibling sets

Fixed by `eval/sibling_sets.py`, which reads PT names in `eval/data/dictionary.csv` only, and committed as `eval/data/sibling_sets.csv`.

- **lab**: "<stem> increased", "<stem> decreased", "<stem> abnormal"; a stem forms a set only as a complete triplet. 44 sets of 3 (132 PTs).
- **site**: "Pain in", "Swelling of", "Numbness of", "Tenderness of", "Weakness of" and "Cramp in" followed by one body site; a site forms a set when two or more exist. 51 sets: 28 of 4 and 23 of 6.

A member's **role** is its direction (increased, decreased, abnormal) or its finding (pain, swelling, numbness, tenderness, weakness, cramp).

## 3. Items, clusters and split

- Source: `eval/data/coding_eval.csv`, **test split only** (grouped by PT, so no test PT is seen in training).
- Eligible items: variants exact, colloquial and misspelled whose gold PT is a member of a set. Negated verbatims are excluded, because they have no correct code.
- Item i has gold term g_i in set S_i, with K_i = |S_i| members. Its **cluster** c(i) is its gold term; the three variants of one gold term share a cluster.
- Registered counts: lab 66 items in 22 clusters; site 144 items in 48 clusters. Every cluster holds 3 items, one per variant.
- The train split is used only for the base rates of null N2 (section 6). The calib split is not used.

The generator's "abnormal" colloquial templates carry no direction (for example "{a} off on labs"), and their gold is the "abnormal" PT. That is the correct coding outcome: code what is reported and query the site when the direction is unclear. The tool must not infer a direction from linked lab values, and nothing here does.

## 4. The tool's scores

T_ik is the tool's own PT-level score for item i and member k of S_i: the maximum, over the lowest-level terms (LLTs) under PT k, of the shipped scorer's score for that LLT. Every LLT of every member is scored, not only the retrieved top 3. The app's functions are loaded from `meddra_app.py` through `eval/_app.py`, so the shipped code is measured.

- **Stand-in path** (always run): the stand-in Tier 4 score S from `t4_coding`, computed from the stand-in Tier 2 cosine (the `_bow` vectors from `t2_index`, rounded to 4 decimals as `t2_coding` does) with the shipped weights.
- **Real path** (run only when a models dir is given): if every feature in the loaded re-ranker's contract (`meddra_coder.meta.json`) can be computed for an arbitrary candidate (cosine, lev, jaro, soc_match, p_unambiguous), T is the re-ranker's score, rounded to 4 decimals as `t4_coding` does. Otherwise T is the Needle3 cosine (the app's Tier 2 score: the dot product of the unit vectors of the lower-cased verbatim and the lower-cased LLT, rounded to 4 decimals). The shipped contract includes `ret_rank`, the candidate's rank within the retrieved top 10, which a sibling outside that pool does not have, so the cosine is expected. The summary records which score was used and why.

## 5. Statistics

- **Pick.** k-hat_i = argmax over k of T_ik. Ties at the maximum (exact equality of the rounded scores) are broken by a seeded uniform draw among the tied members. The **tie rate** is the share of items with two or more members tied at the maximum.
- **Within-set accuracy.** F = (1/n) sum over items of 1{k-hat_i = g_i}.
- **Fractional credit** (sensitivity analysis only): F_frac = (1/n) sum of 1{g_i is tied at the maximum} / (number tied).
- **Margin.** M = (1/n) sum over items of [T_{i,g_i} - max over k != g_i of T_ik].
- Reported for each family and path on all items and separately for each variant (exact, colloquial, misspelled).

## 6. Nulls

Each null draws one pseudo-gold g*_c per cluster, shared by all items in the cluster, from a distribution pi_c over the cluster's set. The picks and scores stay as observed.

- **N1 uniform.** pi_ck = 1/K.
- **N2 base rate.** pi_ck is proportional to w_k, where w_k is the count of train-split gold terms with role k among sets of the same composition (lab triplets; 4-member sites; 6-member sites), plus 1. Sensitivity: pi = lambda w_norm + (1 - lambda)/K for lambda in {0, 0.5, 1}; lambda = 1 is N2 and lambda = 0 is N1. On this synthetic set the base rates are close to uniform by construction, so N1 and N2 should nearly agree.
- **N3 lexical tie set.** Colloquial items only (one item per cluster, so items are independent). lex(k) is the maximum, over the LLTs of k, of the token Jaccard index between the verbatim and the LLT, where tokens are the runs of `[a-z0-9]` in the lower-cased text and Jaccard is computed exactly as a fraction. L_c = {k in S_c : lex(k) = lex(g_c)}, and pi_c is uniform on L_c. Clusters with |L_c| < 2 drop out of N3, and the number dropped is reported.

## 7. Tail probabilities

- **F, exact.** For cluster c, X_c = sum over its items of 1{k-hat_i = g*_c}, with P(X_c = x) = sum over k of pi_ck 1{#(items in c with k-hat_i = k) = x}. The integer pmfs are convolved across clusters, and p = P(sum of X_c >= observed count). One-sided (the tool is better than the null).
- **M, Monte Carlo.** B = 9,999 draws of the pseudo-golds; p = (b + 1)/(B + 1), where b counts draws with M* >= M (to within 1e-12); MCSE = sqrt(p(1 - p)/B).

## 8. Multiplicity

Benjamini-Hochberg within each family x path x null, with Benjamini-Yekutieli as a check. The tests in one such group are F and M on all items and on each variant (8 tests) under N1 and N2, and F and M on the N3 items (2 tests) under N3. The lambda = 0.5 sensitivity is reported without adjustment. The q-values are diagnostics only: they do not route anything (section 10).

## 9. Comparator: the keyword rule

Written before scoring. Each role has a lexicon:

| role | lexicon |
|---|---|
| increased | high, raised, elevated, increased, up, above |
| decreased | low, decreased, reduced, down, below, dropped |
| abnormal | abnormal, off, out of range |
| pain | pain, hurts, aching, ache, sore, sharp |
| swelling | swollen, swelling, puffy, blown |
| numbness | numb, feel, dead |
| tenderness | tender, touch, pressed |
| weakness | weak, strength |
| cramp | cramp, cramping |

- Tokens as in N3. A one-word entry hits when any token of the verbatim starts with it ("tender" hits "tenderness"); a multi-word entry hits when its words appear as consecutive tokens.
- A role's score is the number of its entries that hit. The rule picks the member with the most hits among the item's set; ties, including no hits at all, are broken by a seeded uniform draw.
- Caveat to state with the results: the lexicon was written with the generator's templates visible, so this baseline is optimistic here.

## 10. Routing gates and kill rule

Gates apply to a family as a whole (all three variants pooled), per path.

- **Gate A, accuracy floor.** The one-sided 95% Clopper-Pearson lower bound on within-set accuracy must be at least a_min = 0.90. a_min is fixed here and may change only before scoring.
  - Effective size: n_eff = n/deff with Kish deff = 1 + (m-bar - 1) rho-hat, where m-bar = n/m and rho-hat is the one-way ANOVA intraclass correlation of correctness across clusters, (MSB - MSW)/(MSB + (n0 - 1) MSW), truncated to [0, 1]. When every item is correct or none is, rho is set to 1, so n_eff = m.
  - x_eff = floor(F n_eff). The bound is the 0.05 quantile of Beta(x_eff, n_eff - x_eff + 1), and 0 when x_eff = 0.
- **Attainability** (section 11): with every item correct and rho = 1, the bound is 0.05^(1/m). A family whose best attainable bound is below a_min is "not assessable at this size".
- **Gate B, beats the keyword rule.** d_i = 1{tool correct} - 1{rule correct}. The one-sided 95% cluster-bootstrap lower bound of the mean of d must be above 0: B = 9,999 resamples of the m gold-term clusters with replacement; each resample's statistic is the sum of d over the resampled items divided by their number; the bound is the 500th smallest of the 9,999 values.
- **Kill rule.** A family that is not assessable, fails Gate A or fails Gate B is excluded from auto-coding on that path and routes to human coding. Only a family that is assessable and passes both gates may auto-code.

## 11. Attainability, computed before scoring

Best attainable Gate A bound = 0.05^(1/m). a_min = 0.90 needs m >= 29 clusters; 0.95 needs m >= 59.

| m (clusters) | 10 | 20 | 22 | 28 | 29 | 40 | 48 | 58 | 59 | 120 |
|---|---|---|---|---|---|---|---|---|---|---|
| best bound | 0.741 | 0.861 | 0.873 | 0.899 | 0.902 | 0.928 | 0.940 | 0.950 | 0.951 | 0.975 |

| family | items n | clusters m | best attainable bound | assessable at a_min = 0.90 |
|---|---|---|---|---|
| lab | 66 | 22 | 0.873 | no: not assessable at this size; routes to human coding |
| site | 144 | 48 | 0.940 | yes |

## 12. Negative control

For the shipped stand-in scorer on the test items: in each of 400 permutations, one uniform random permutation of the set's members per cluster is applied to the score vectors of every item in that cluster. This keeps the scorer's agreement across a cluster's variants and breaks its link to the gold. The F test under N1 should then reject (p < 0.05) at most 0.05 + 0.022 = 0.072 of the time, per family; the exact F test is discrete, so the rate may fall below 0.05. The rates under N2 and N3, and for M with B = 999, are reported alongside.

## 13. Known-answer demo

`eval/sibling_knownanswer.py`, seed 20261025, 400 datasets per scorer unless noted. Each dataset has 120 lab clusters built from the real lab sets (a stem drawn uniformly from the 44 for its labels), gold roles drawn with probabilities 0.60 increased, 0.25 decreased and 0.15 abnormal, and 3 items per cluster. N2's weights come from a separate 1,000-draw "historical" sample of roles with the same probabilities, plus 1 per role. N3 uses a synthetic lexical tie set per cluster: the gold plus each other member independently with probability 1/2 (clusters with |L_c| < 2 drop out), applied to the second item of each cluster. The keyword rule is simulated: each item is correct independently with probability 0.85. q-values use BH over {F, M} within each null. M's p-values use B = 9,999 draws and Gate B uses B = 9,999 resamples, as in the real run. The Kolmogorov-Smirnov p-value comes from the asymptotic Kolmogorov distribution with Stephens' correction, lambda = (sqrt(N) + 0.12 + 0.11/sqrt(N)) D.

| scorer | construction | must recover |
|---|---|---|
| (a) accurate but not enough | q_c ~ Beta(8, 2), mean 0.80; each item correct with probability q_c, otherwise a uniform other member is picked; the pick scores 0.9 + N(0, 0.05^2), the others 0.5 + N(0, 0.05^2) | q_F < 0.05 under both N1 and N2 in at least 95% of datasets, and Gate A fails in at least 95% |
| (b) direction-blind base-rate follower | always ranks increased > decreased > abnormal (scores 3, 2, 1) | mean F in [0.58, 0.62]; N1 rejects (p_F < 0.05) in at least 99%; N2 rejects in 0.05 +/- 0.022, that is [0.028, 0.072]; Gates A and B each fail in at least 95% |
| (c) pure noise | T_ik iid N(0, 1) | p_F < 0.05 in at most 0.072 under each of N1, N2 and N3; a Kolmogorov-Smirnov test of the M p-values against uniform is not rejected at 0.01 under each null |
| (d) good enough | q_c ~ Beta(97, 3), mean 0.97; scores as in (a) | Gate A passes in more than half of the datasets (the rate is reported); Gate B passes in at least 95% |
| (e) bound coverage | q_c ~ Beta(3.4, 0.6): true accuracy 0.85, intraclass correlation 1/(3.4 + 0.6 + 1) = 0.2; 2,000 datasets | the Gate A lower bound is below 0.85 in at least 93% of datasets |

`tests/test_sibling.py` runs the same demo at reduced replicates with wider tolerances, stated in that file.

## 14. Expected known answer

`docs/EVALUATION.md` reports that on the real path "calcium down on bloods" retrieves "Blood calcium increased" above "decreased", and colloquial top-1 is 0.52. The lab family must therefore come out failing or not assessable on every path; by section 11 it is not assessable at this size. Any other result is a bug to find before the results are published. The summary records the scores of that item's three siblings on each path that ran.

## 15. Machine-readable parameters

The scripts read this block after the hash check. Random streams: `numpy.random.default_rng([seed, stream, ...])` with the stream numbers below and the indexes noted (family: lab 0, site 1; path: standin 0, real 1; null: N1 0, N2 1, N3 2, N2 at lambda 0.5 is 3; subset: all 0, exact 1, colloquial 2, misspelled 3). Draws use `random()` only.

```json
{
  "plan_version": "2026-10-25",
  "seed": 20261025,
  "streams": {"tie_break": 1, "keyword_tie_break": 2, "mc_margin": 3, "gate_b_bootstrap": 4,
              "negative_control": 5, "knownanswer": 100},
  "alpha": 0.05,
  "a_min": 0.90,
  "B_mc": 9999,
  "B_boot": 9999,
  "split": "test",
  "variants": ["exact", "colloquial", "misspelled"],
  "families": ["lab", "site"],
  "registered_counts": {"lab": {"items": 66, "clusters": 22}, "site": {"items": 144, "clusters": 48}},
  "n2_lambdas": [0, 0.5, 1],
  "tie_tolerance": 1e-12,
  "reranker_features_any_candidate": ["cosine", "lev", "jaro", "soc_match", "p_unambiguous"],
  "keyword_lexicon": {
    "increased": ["high", "raised", "elevated", "increased", "up", "above"],
    "decreased": ["low", "decreased", "reduced", "down", "below", "dropped"],
    "abnormal": ["abnormal", "off", "out of range"],
    "pain": ["pain", "hurts", "aching", "ache", "sore", "sharp"],
    "swelling": ["swollen", "swelling", "puffy", "blown"],
    "numbness": ["numb", "feel", "dead"],
    "tenderness": ["tender", "touch", "pressed"],
    "weakness": ["weak", "strength"],
    "cramp": ["cramp", "cramping"]
  },
  "negative_control": {"permutations": 400, "B_mc": 999, "max_rejection": 0.072},
  "knownanswer": {
    "datasets": 400, "coverage_datasets": 2000, "clusters": 120, "items_per_cluster": 3,
    "role_probs": {"increased": 0.60, "decreased": 0.25, "abnormal": 0.15},
    "historical_draws": 1000, "keyword_accuracy": 0.85, "n3_member_prob": 0.5, "n3_item": 1,
    "a_beta": [8, 2], "d_beta": [97, 3], "e_beta": [3.4, 0.6], "e_true_accuracy": 0.85,
    "pick_score": [0.9, 0.05], "other_score": [0.5, 0.05], "b_scores": [3, 2, 1],
    "criteria": {
      "a_joint_q_rate_min": 0.95, "a_gate_a_fail_min": 0.95,
      "b_mean_f": [0.58, 0.62], "b_n1_reject_min": 0.99, "b_n2_reject": [0.028, 0.072],
      "b_gate_a_fail_min": 0.95, "b_gate_b_fail_min": 0.95,
      "c_reject_max": 0.072, "c_ks_p_min": 0.01,
      "d_gate_a_pass_min": 0.50, "d_gate_b_pass_min": 0.95,
      "e_coverage_min": 0.93
    }
  },
  "known_answer_item": {"verbatim": "calcium down on bloods", "gold_pt": "Blood calcium decreased"},
  "inputs_sha256": {
    "eval/data/coding_eval.csv": "ef0fb304e8ec1fd40037fcfd31f70d795400edb89d750d4aeef27bb6cb8f82c8",
    "eval/data/dictionary.csv": "0213dde1fd0d91e2ebbee09ca8ddf79a48db419f357119dc312171c44beaaec5",
    "eval/data/sibling_sets.csv": "6da73287863d4199c45d62e83dbd9cd91ba231b4374569e1dc28b95a9bc95e0c"
  },
  "scorer_fingerprint": "ce19a95181a279e0020587aa54a434dfbbe3705191fe1cb3d7c56f49ec443343"
}
```

`inputs_sha256` pins the input files; a mismatch stops the run. `scorer_fingerprint` is the SHA-256 of the token stream of `meddra_app.py` above its UI marker, comments and blank lines left out, so an edit to the scoring code is detected and a comment edit is not. A mismatch stops the run unless `--allow-scorer-change` is passed, and that run is then recorded as a deviation from this plan.

## 16. Outputs

- `eval/results/sibling_summary.json`: per family and path, n, m, F and its Gate A bound, deff, M, p and q under N1 to N3, keyword F, Gates A and B, the routing decision, tie rate and best attainable bound; the negative control; the known-answer item; the plan and input hashes.
- `eval/results/sibling_items.csv`: one row per item and path, with every member's score, the pick, the keyword rule's hits and pick, and the N3 tie set.
- `eval/results/sibling_knownanswer.csv`: one row per scorer and criterion, with the observed rate, its Monte Carlo standard error, the criterion and whether it was met.

## 17. What this does not establish

The dictionary is synthetic and not MedDRA. The gold codes were generated, so they are independent of the tool by construction. Real use needs gold codes adjudicated without the tool's suggestions, a licensed MedDRA release and a sibling rule registered before scoring, as this one is.
