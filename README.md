# Knowledge Diffusion — Paper Artifacts

**Provisional Patent Pending (filed April 15, 2026)** | Copyright (c) 2026 The Pennsylvania State University. All rights reserved.
Inventor: Scott N. Hwang

Licensed under the Open Core Ventures Source Available License (OCVSAL) v1.0. See [LICENSE](LICENSE). Production use requires a commercial agreement. For commercial licensing, contact the Penn State Office of Technology Transfer at ottinfo@psu.edu.

Evaluation scripts, benchmark harnesses, and result files for the knowledge-
diffusion paper series, which covers Six Thinking Hats panel deliberation
(main paper, `bear_tiis.tex`) and its application to two LLM benchmarks:
Big-Bench Hard (`bear_tiis_bbh.tex`) and Student–Clinician Transfer
(`bear_tiis_sct.tex`). Preprint links TBD. Uses the BEAR library at
[snhwang/bear](https://github.com/snhwang/bear), pinned to `v0.1.0`.

## Layout

```
evals/                          # 10 paper/evaluation scripts + stat_utils
├── eval_interhat_differentiation.py  # inter-hat centroid distance
├── eval_role_adherence.py            # role self-alignment, discrimination
├── eval_significance.py              # t-tests, Wilcoxon, bootstrap, Holm
├── eval_embed_only_baseline.py       # naive vs embed-only vs BEAR dedup
├── eval_dmin_sensitivity.py          # d_min threshold sweep (0.20 – 0.50)
├── eval_temporal_evolution.py        # store growth over turns
├── eval_response_divergence.py       # BEAR vs Naive inter-hat distance
├── eval_role_divergence.py           # BEAR vs Role vs Static prompt
├── eval_architecture_baselines.py    # [rev1] vs shared-memory topologies
├── eval_knowledge_flow_matrix.py     # [rev1] retention-decision flow matrix
├── results/                          # [rev1] outputs of the two above
└── stat_utils.py                     # bootstrap CIs shared across evals

benchmarks/                     # 10 experiments scripts + input data
├── bbh_data/                         # Big-Bench Hard JSONs
│   ├── causal_judgement.json
│   ├── disambiguation_qa.json
│   ├── logical_deduction_five_objects.json
│   ├── logical_deduction_seven_objects.json
│   └── snarks.json
├── sct_data/
│   └── sct_cleaned_full.csv          # cleaned SCT dataset
├── brainteaser_puzzles.json          # frozen brainteaser SP puzzles
├── brainteaser_wp_puzzles.json       # frozen brainteaser WP puzzles
├── bbh_eval.py                       # single vs panel on BBH
├── brainteaser_eval.py               # single vs panel on brainteaser
├── sct_eval.py, sct_eval_v2.py       # SCT evaluation (v1 + v2)
├── sct_repair_panel.py, sct_repair_panel_trunc.py, sct_rerun_nulls.py
├── analyze_panel.py                  # cross-model panel analysis
├── llm_rejudge_brainteaser.py        # LLM re-judging
├── download_brainteaser.py           # regenerates brainteaser puzzles
└── sct_results_analysis.md

bear_parlor/                    # data subset of the bear_parlor example
├── session_logs/                     # 240 brainstorming-hats session logs
├── instructions/                     # hat / common / barbershop corpora
├── panel_data/                       # panel configuration data
├── panels.yaml                       # panel definitions
├── characters.yaml                   # character/hat assignments
└── topics/README.md                  # DOIs of source papers for the 8 topics

pet_sim/                        # pet-sim corpus (used by eval_role_divergence)
└── instructions/                     # 8 YAML files, frozen for role-divergence eval

results/                        # 33 result subdirs (~175 MB)
├── bbh_{gptoss120b,haiku,medgemma,sonnet}/
├── bt_*/                             # brainteaser runs across models
├── sct_v2_*/                         # SCT v2 runs across models
├── six_hats_panels/                  # main-paper panel results
└── cloud_optimal/

run_evals.sh                    # runner for paper/evaluation suite
requirements.txt                # bear@v0.1.0 + scipy/numpy/matplotlib/PyYAML/python-dotenv/openai
```

## Topic source papers

The 8 topics used in `bear_parlor/session_logs/` (CRISPR, DMG, GLP-1, MS,
Alzheimer's, Epilepsy, Stroke, LLMs in Clinical Decision Support) were seeded
with small sets of peer-reviewed papers. Those PDFs are **not redistributed
here** (third-party copyright). See `bear_parlor/topics/README.md` for the
per-topic list and DOIs so the inputs can be retrieved independently. The
eval scripts do not need the PDFs — they read session logs only.

## Reproduce

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
./run_evals.sh                  # Part A (session-log analysis, no LLM)
./run_evals.sh --all            # Part A + eval_role_divergence (needs LM Studio)
```

### Running experiments, and local-model endpoints

See **[RUNNING_EXPERIMENTS.md](RUNNING_EXPERIMENTS.md)**. It covers what is and
is not reproducible, how to regenerate panel sessions from the BEAR repository,
and a coverage table of which manuscript result has which script.

**If a local model fails to connect, start there.** BEAR defaults to
`http://127.0.0.1:1234/v1` for LM Studio and `http://localhost:11434` for
ollama, but recent LM Studio releases have changed the default server address
and port, so these need not match your installation. Set `LM_STUDIO_URL` or
`OLLAMA_HOST` explicitly; both are read before any default is applied.

### Metric definitions

All store-differentiation metrics come from `evals/overlap_metrics.py`. Nothing
should define its own overlap: two different definitions of "nearest-neighbour
overlap" previously coexisted in the manuscript (cosine distance < 0.35 versus
similarity >= 0.85), differing by 14x on the same data.

It provides a threshold-free primary measure (mean nearest-neighbour
similarity), the thresholded overlap at an explicit tau, a sweep across tau to
show orderings are not threshold artefacts, and a **permutation null** that
reassigns items to hats at random while preserving store sizes. The null is the
important one: small stores look differentiated trivially, so an observed value
only means something relative to random assignment of the same items.

### Revision 1 analyses (Expert Systems, 2026-08)

Two analyses added during the first revision. Both are deterministic, need no
LLM, and read the same session logs as the rest of Part A. Outputs land in
`evals/results/`.

```bash
python evals/eval_architecture_baselines.py     # Table 7: vs shared-memory designs
python evals/eval_architecture_baselines.py --include-pdf   # secondary variant
python evals/eval_knowledge_flow_matrix.py      # Figure 6: retention flow matrix
```

`eval_architecture_baselines.py` compares BEAR-guided diffusion against
shared-store and shared-context topologies on the context each agent receives
at generation time. `eval_knowledge_flow_matrix.py` measures retention
decisions only, never stored text, so it is independent of the reframing step.
Add `--top-k` to either to reproduce the retrieval-depth sensitivity check.

### Benchmark scripts (BBH, brainteaser, SCT)

These run separately from the main `run_evals.sh` and typically require an
LLM backend (Anthropic API, LM Studio, or Ollama). See each script's docstring
for invocation examples. Representative commands:

```bash
# BBH single vs panel on Claude Sonnet
python benchmarks/bbh_eval.py --mode all --model claude-sonnet-4-6 \
    --results-dir results/bbh_sonnet

# Brainteaser analyze mode against pre-existing results
python benchmarks/brainteaser_eval.py --mode analyze --results-dir results/bt_sonnet_5hat

# SCT v2 single-model run
python benchmarks/sct_eval_v2.py --mode single --model claude-haiku-4-5-20251001

# Cross-model panel analysis (reads from results/)
python benchmarks/analyze_panel.py
```

## Bear version

Pinned to bear `v0.1.0` (commit `515366e`). Bumping bear may change numeric
results; update the pin in `requirements.txt` and re-run to compare.
