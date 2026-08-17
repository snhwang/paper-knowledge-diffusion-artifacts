# Superseded evaluation scripts

**Nothing here produces a number in the current manuscript.** These are kept so
that superseded results remain traceable: if a value in an earlier version of
the paper needs explaining, the script that produced it is here.

Do not use these for new work. Their metric definitions predate
`evals/overlap_metrics.py` and are not comparable with the current tables.

| Script | Superseded by | Why |
|---|---|---|
| `eval_interhat_differentiation.py` | `eval_interhat_reconciled.py` | Hardcodes a 2026-04-06 SESSION_MAP and reconstructs stores by parsing markdown, because those logs have no `.knowledge.json`. Uses the legacy overlap definition. |
| `eval_temporal_evolution.py` | `eval_temporal_reconciled.py` | Same hardcoded 2026-04-06 corpus, so its store-growth panel described a different experiment from the centroid curves shipped alongside it. |
| `eval_dmin_sensitivity.py` | `eval_dmin_reconciled.py` | Legacy overlap definition, which put its overlap column on a different scale from the inter-hat table it was printed beside. |
| `eval_embed_only_baseline.py` | `eval_interhat_reconciled.py` + `eval_dmin_reconciled.py` | The three-way ablation is now computed from those two on the canonical corpus. This script replayed a third corpus (2026-03-08, five topics). Retained because the two scripts above import it. |
| `eval_response_divergence.py` | — | Produces divergence, unique-information and knowledge-utilisation metrics that the current manuscript does not report. |
| `eval_role_divergence.py` | — | Compares BEAR against Role, Role+Tags and Static prompting. Belongs to the companion retrieval paper rather than this one, and requires a local LM Studio server. |

## The metric change that made most of these obsolete

Two definitions of "nearest-neighbour overlap" once coexisted:

- cosine **distance** < 0.35, i.e. similarity > 0.65 — used by the scripts here
- cosine **similarity** >= 0.85 — used by `overlap_metrics.py` and every current table

On the same data these differ by roughly an order of magnitude: BEAR-guided
overlap reads 0.93 under the first and 0.06 under the second. Numbers produced
by the scripts in this folder therefore cannot be compared with the current
manuscript, and should not be quoted alongside it.
