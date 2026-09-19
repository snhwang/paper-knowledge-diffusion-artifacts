# Experiment Log — BEAR TiiS Evaluation

Documents all experimental conditions, prompt versions, and session runs
for reproducibility. Each session log is stored in
`examples/bear_parlor/session_logs/`.

---

## Diffusion Prompt Versions

### v1 (original) — commit `e8887bf`

- **Architecture**: One LLM call per receiving hat (`_extract_for_hat`)
- **Selection**: "Identify 0-2 facts, claims, or ideas that are relevant to YOUR
  cognitive mode and worth remembering."
- **Reframing**: "Restate each through YOUR analytical lens — not verbatim, but
  filtered through how you think."
- **Temperature**: 0.3
- **max_tokens**: 400
- **Item cap**: `items[:2]` — hard limit of 2 items per batch per hat
- **Hat filters**: None (single generic prompt for all hats)
- **LLM**: Per-hat LLM (each hat uses its own model via `self._hat_llms`)

### v2 — hat-specific filters, no item cap

- **Architecture**: One LLM call per receiving hat (`_extract_for_hat`)
- **Selection**: Same as v1
- **Reframing**: Hat-specific filter criteria added (e.g., White: "Extract factual
  claims. Ignore opinions." etc.)
- **Temperature**: 0.5
- **max_tokens**: 800
- **Item cap**: Removed (no `items[:2]` cap)
- **Hat filters**: Per-hat extraction criteria
- **LLM**: Per-hat LLM

### v3 — wider-net selection (INCOMPLETE)

- Same as v2 but changed selection to: "relevant, interesting, or useful — even
  if it originated from a different cognitive mode."
- Changed hat filters from "Extract X. Ignore Y." to "Reframe everything as X."
- **Status**: Session stalled at turn 21 due to API rate limits — 5+ concurrent
  Sonnet API calls (one per hat) overwhelmed capacity. Abandoned in favor of v4.

### v4 — batched diffusion

- **Architecture**: Single LLM call for ALL hats (`_extract_batch`). All
  cognitive lenses presented simultaneously in one prompt.
- **Selection**: "Select anything relevant, interesting, or useful. The value is
  in producing DISTINCTLY DIFFERENT reframings for each hat."
- **Reframing**: Per-hat lens descriptions in prompt (e.g., White: "Reframe
  everything as factual claims, data points, evidence levels, or data gaps.")
- **Temperature**: 0.5
- **max_tokens**: 1500
- **Item cap**: None (per-hat arrays in JSON response)
- **Hat filters**: Integrated into batched prompt as "Cognitive lenses"
- **LLM**: Default session LLM (NOT per-hat LLMs) — the batch call uses a
  single model. Individual hat response generation still uses per-hat LLMs.
- **Key change**: Eliminates N separate API calls, solving rate-limit bottleneck.
  Single call sees all lenses simultaneously, encouraging more distinctive
  reframings.

### v5 — hat lenses managed as a BEAR diffusion facet (2026-09-16)

- **Architecture, prompt, sampling**: Unchanged from v4. One batched call,
  same prompt text, temperature 0.5, max_tokens 1500, no item cap, default
  session LLM.
- **Hat filters**: No longer a hard-coded `HAT_FILTERS` dict in
  `knowledge_rag.py`. Each hat's lens is a BEAR instruction,
  `diffusion-<hat>-lens`, in that hat's YAML beside its response instructions,
  with `scope.required_tags: [<hat-id>, knowledge-diffusion]`. The lens text is
  byte-identical to the v4 dict.
- **Retrieval**: `CrossHatDiffuser` retrieves each hat's lens from a sub-corpus
  of `knowledge-diffusion`-tagged instructions, with no mandatory injection.
  Retrieving from the full corpus would add the hat's persona, speech and mood
  instructions and the room context.
- **Rendering**: Lens content is placed inline in the batched prompt, one
  bullet per hat, rather than through `Composer`, whose per-instruction labels
  would change the prompt.
- **Runtime edits**: Editing a lens in the Parlor instruction editor rebuilds
  the facet index, so the next batch uses the new text.
- **Verification** (offline, no LLM calls):
  - The April v4 `_extract_batch` (commit `5c91a19`) and v5 were run on the
    same 59 real batches across all eight topics. System and user prompts
    were byte-identical in all 59. Sessions recorded under v4 are therefore
    what v5 produces for the same inputs, up to sampling.
  - Across 1,200 retrieval contexts (each hat speaking, with and without mood
    tags, and the replay's `[hat, content]` context), adding the six facet
    instructions changed no retrieved instruction and no composed guidance,
    and no facet instruction was retrieved outside diffusion.
  - An edited lens is served after the index rebuild. A soft-scoped lens
    refinement for one hat reaches that hat only.
- **Also fixed**: `bear/corpus.py` opened instruction YAML without an
  encoding, so on Windows (cp1252) non-ASCII text such as em dashes loaded as
  mojibake. Sessions run under WSL/Linux, where the default is UTF-8, were
  unaffected.

### v6 (current) — per-hat diffusion, gated retrieval, isolated sessions (2026-09-16)

v5 moved the lenses into BEAR but kept the April pipeline. v6 changes the
pipeline itself, so v6 sessions are a new experiment, not a rerun of v4.

- **Architecture**: When a hat has buffered 6 statements from other hats, that
  hat's own model reframes *its own* buffer through *its own* lens, retrieved
  from the BEAR `knowledge-diffusion` facet. One call per hat, at most 3
  concurrent. The v4 batched call sent every ready hat the FIRST ready hat's
  buffer, so hats were sometimes handed their own statements (59 times in a
  replay of the April turn order).
- **Prompt**: The v4 wording made single-hat: same selection and
  self-contained rules, JSON array output. It shows only the receiving hat's
  lens, does not name the hat, and drops "The value is in producing
  DISTINCTLY DIFFERENT reframings for each hat".
- **Temperature / max_tokens / item cap**: 0.5 / 1500 / none (unchanged).
- **Wrong-lens control**: `--wrong-lens` gives each hat the next hat's lens
  (`WRONG_LENS_MAP` in parlor.py; the same rotation as the replay's
  `MISMATCH_MAP`).
- **Retrieval gating**: Every hat-specific instruction is hard-gated on its
  hat (`required_tags`); mood variants also on their mood. Memories and
  evolved instructions are gated on their hat. Mandatory injection now respects
  hard gates, and generated topic tags cannot take reserved tags. In April, 24%
  of instructions retrieved for speaking belonged to another hat.
- **Corpus**: Three instruction files derived from Alzheimer's DTI papers
  (`hats/domains/`) were loaded into every April session and retrieved in all
  16 (609 retrievals). They are moved to `instructions_archive/`.
- **Isolation**: Persisted memories and affinities are archived before each
  session and the state a session creates is saved beside its logs
  (`session_logs/v6/panel_state/`). In April, 576 retrievals were memories
  formed in other sessions.
- **PDF text**: Extracted once per file content and cached; the extractor is
  recorded per ingestion.
- **Run record**: `run_info` in each `.stats.json` gives the models, lens
  map, base URL, Mathpix availability and code commit.
- **Code**: bear-dev commit `d90058c` (branch `v6-bear-diffusion`). The v6
  sessions ran before that commit was made, from a working tree whose session
  code is identical to it; their `run_info` therefore records the parent
  `aed4b9c` with `uncommitted_changes: true`. No session-relevant file changed
  between the start of the run (13:35) and the commit.

---

## Model Configurations

### Heterogeneous (default)

Per-hat LLM overrides in `characters.yaml`:

| Hat    | Backend   | Model                              |
|--------|-----------|------------------------------------|
| White  | anthropic | claude-opus-4-6                  |
| Red    | gemini    | gemini-3.1-flash-lite-preview      |
| Black  | anthropic | claude-sonnet-4-6                |
| Yellow | ollama    | gemma3:4b                          |
| Green  | anthropic | claude-haiku-4-5                 |
| Blue   | gemini    | gemini-3.1-flash-image-preview     |

Session default LLM: anthropic / claude-sonnet-4-6

> **Correction (2026-09-16).** This table does not describe the 2026-04-10/11
> sessions the evaluation scripts use. Those ran with `characters.yaml` at
> commit `5c91a19`, which matches the manuscript: White `claude-sonnet-4-6`,
> Red `claude-haiku-4-5`, Black `claude-opus-4-6` (Anthropic); Yellow
> `gpt-4.1-mini`, Green `gpt-4.1`, Blue `gpt-5.4` (OpenAI). Their session
> default -- which ran ALL diffusion calls -- was not Sonnet 4.6.
> `run_demo_session_v2.py` passed `--backend anthropic` with no `--model`, so
> it was the Anthropic backend's built-in default, `claude-haiku-4-5-20251001`.

### Uniform Sonnet 4.6

All per-hat overrides removed from `characters.yaml`. All hats use session
default: anthropic / claude-sonnet-4-6.

### Uniform qwen3.8-flash-next (v6)

Every hat and every background task (diffusion, insights, query refinement)
on `qwen3.8-flash-next`, served by an OpenAI-compatible server
(`--backend openai --model qwen3.8-flash-next --override-model`, base URL
recorded in `run_info`). Session environment: WSL Ubuntu 24.04, Python
3.12.13, `bear_parlor/requirements-sessions.lock.txt`.

**Sampling in the panel benchmarks (2026-09-17).** BEAR's OpenAI-compatible
backend disables thinking for local servers (`enable_thinking: false`), so
qwen runs in instruct mode. The benchmarks use the harness's own settings,
identical for Haiku 4.5 and qwen: temperature 0 for `single`, 0.5 for the
sampled conditions; top_p, top_k and presence_penalty are not sent (server
defaults). The model card's instruct preset (temperature 0.7, top_p 0.80,
top_k 20, presence_penalty 1.5; greedy decoding discouraged) was deliberately
not used: every comparison is within one model at one temperature, and one
setting for both models keeps the method simple. Greedy decoding caused no
visible problems: in BRAINTEASER `single`, all 301 items gave a parseable
answer on the first attempt.

### Qwen3.8-27B (panel benchmarks)

Model id `Qwen3.8-27B`, served by vLLM at `http://localhost:8355/v1` (reached
from WSL), max_model_len 262144, no API key. Thinking is disabled
(localhost), and sampling is the same as for the other benchmark models (see
above). Targets: `run_panel_bench.sh sct-qwen27b` / `brainteaser-qwen27b`.

**Weights (2026-09-17).** The same model id was served by two different NVFP4
builds on the same day. The first deployment served
`nvidia/Qwen3.8-27B-NVFP4`; it produced the BRAINTEASER smoke test (10 items,
all conditions) and a partial SCT run (single 174/174, consistency 94/174)
before the server stalled and was restarted with
`unsloth/Qwen3.8-27B-NVFP4`. The nvidia-build SCT results are kept, unused, in
`results/panel_bench/sct/Qwen3.8-27B_nvidia-build-partial/`; the reported 27B
runs use the unsloth build. `panel_bench.py` now records the server's reported
weights in `config.json` and refuses to append results produced under a
different build.

### Uniform local 12B

All hats use: `mistral-nemo-instruct-2407`.

> **Correction (2026-08-17).** The backend was recorded here as `ollama`, but
> that is inconsistent with the model identifier on the same line:
> `mlx-community/...` is LM Studio's naming convention, not an ollama tag
> (ollama would read `mistral-nemo:latest`). `run_paper2_evals.sh` names LM
> Studio at `localhost:1234` in four places, and the manuscript says LM Studio.
> The model was therefore almost certainly served by **LM Studio**, and the
> `ollama` label above is an error.
>
> **The quantization was never recorded**, here or anywhere else, and neither
> were the sampling parameters for these runs. Local builds of this model
> differ (LM Studio Q4_K_M vs ollama Q4_0), so these sessions **cannot be
> reproduced exactly**. Re-running produces a new experiment rather than a
> reproduction. The session logs below are the record; analysis of them is
> fully deterministic and reproducible.

---

## Session Log Index

### Primary sessions (heterogeneous models, v1 prompt)

| Filename | Topic | Condition | Prompt | Models |
|----------|-------|-----------|--------|--------|
| `brainstorming-hats_20260308_131430.md` | DMG | BEAR-guided | v1 | Heterogeneous |
| `brainstorming-hats_20260308_132051.md` | Stroke | BEAR-guided | v1 | Heterogeneous |
| `brainstorming-hats_20260308_132705.md` | MS | BEAR-guided | v1 | Heterogeneous |
| `brainstorming-hats_20260308_133940.md` | DMG | Naive | v1 | Heterogeneous |
| `brainstorming-hats_20260308_134610.md` | Stroke | Naive | v1 | Heterogeneous |
| `brainstorming-hats_20260308_135226.md` | MS | Naive | v1 | Heterogeneous |

### Constant-model control — local 12B (v1 prompt)

| Filename | Topic | Condition | Prompt | Models |
|----------|-------|-----------|--------|--------|
| `brainstorming-hats_20260313_003943.md` | DMG | BEAR-guided | v1 | Uniform local 12B |
| `brainstorming-hats_20260313_010034.md` | DMG | Naive | v1 | Uniform local 12B |

### Constant-model control — Sonnet 4.6 (v1 prompt)

| Filename | Topic | Condition | Prompt | Models |
|----------|-------|-----------|--------|--------|
| `brainstorming-hats_20260313_013537.md` | DMG | BEAR-guided | v1 | Uniform Sonnet |
| `brainstorming-hats_20260313_014207.md` | DMG | Naive | v1 | Uniform Sonnet |

### Prompt ablation — v2 (Sonnet 4.6)

| Filename | Topic | Condition | Prompt | Models |
|----------|-------|-----------|--------|--------|
| `brainstorming-hats_20260313_071341.md` | DMG | BEAR-guided | v2 | Uniform Sonnet |
| `brainstorming-hats_20260313_072012.md` | DMG | Naive | v2 | Uniform Sonnet |

### Prompt ablation — v3 (INCOMPLETE, Sonnet 4.6)

| Filename | Topic | Condition | Prompt | Models | Notes |
|----------|-------|-----------|--------|--------|-------|
| `brainstorming-hats_20260313_073201.md` | DMG | BEAR-guided | v3 | Uniform Sonnet | Stalled at turn 21 |

### Prompt ablation — v4 batched (Sonnet 4.6)

| Filename | Topic | Condition | Prompt | Models |
|----------|-------|-----------|--------|--------|
| `brainstorming-hats_20260313_081554.md` | DMG | BEAR-guided | v4 | Uniform Sonnet |
| `brainstorming-hats_20260313_082240.md` | DMG | Naive | v4 | Uniform Sonnet |

### Primary sessions (heterogeneous models, v4 prompt)

| Filename | Topic | Condition | Prompt | Models |
|----------|-------|-----------|--------|--------|
| `brainstorming-hats_20260313_084633.md` | DMG | BEAR-guided | v4 | Heterogeneous |
| `brainstorming-hats_20260313_085257.md` | Stroke | BEAR-guided | v4 | Heterogeneous |
| `brainstorming-hats_20260313_085916.md` | MS | BEAR-guided | v4 | Heterogeneous |
| `brainstorming-hats_20260314_164032.md` | Alzheimers | BEAR-guided | v4 | Heterogeneous |
| `brainstorming-hats_20260314_164701.md` | Epilepsy | BEAR-guided | v4 | Heterogeneous |
| `brainstorming-hats_20260314_165328.md` | Alzheimers | Naive | v4 | Heterogeneous |
| `brainstorming-hats_20260314_170001.md` | Epilepsy | Naive | v4 | Heterogeneous |

These are the primary paper results. Naive sessions for DMG/Stroke/MS are the
v1 sessions (20260308) since the diffusion mode does not use BEAR retrieval
and the prompt version only affects BEAR-guided sessions. Alzheimers and
Epilepsy have their own naive sessions (20260314).

> **Correction (2026-09-16).** The evaluation scripts do not use these March
> sessions. `load_best_sessions` selects, per topic and condition, the
> 2026-04-10/11 sessions generated by `run_demo_session_v2.py` (v4 prompt,
> heterogeneous models as corrected above), which are the ones with
> `.knowledge.json` dumps.

### v6 sessions (uniform qwen3.8-flash-next, v6 pipeline)

Run 2026-09-16 with `bear_parlor/run_sessions.py`, 8 topics x 3 conditions.
Logs in `bear_parlor/session_logs/v6/`. All 24 pass
`evals/check_session_integrity.py`: no instruction retrieved from another
hat, no memory from another session, nothing from outside the panel corpus,
every hat's persona present, one model throughout, per-hat BEAR diffusion
(naive for naive), all PDFs via Mathpix, no dropped diffusion batches.

| Filename | Topic | Condition | Turns | Diffusion stored |
|----------|-------|-----------|-------|------------------|
| `brainstorming-hats_20260916_133551.md` | dmg | bear | 34 | 47 |
| `brainstorming-hats_20260916_134310.md` | dmg | naive | 35 | 114 |
| `brainstorming-hats_20260916_135029.md` | dmg | wrong-lens | 35 | 51 |
| `brainstorming-hats_20260916_135757.md` | stroke | bear | 37 | 67 |
| `brainstorming-hats_20260916_140545.md` | stroke | naive | 36 | 114 |
| `brainstorming-hats_20260916_141316.md` | stroke | wrong-lens | 35 | 56 |
| `brainstorming-hats_20260916_142035.md` | ms | bear | 39 | 57 |
| `brainstorming-hats_20260916_142829.md` | ms | naive | 35 | 108 |
| `brainstorming-hats_20260916_143548.md` | ms | wrong-lens | 36 | 53 |
| `brainstorming-hats_20260916_144308.md` | alzheimers | bear | 37 | 57 |
| `brainstorming-hats_20260916_145054.md` | alzheimers | naive | 36 | 114 |
| `brainstorming-hats_20260916_145815.md` | alzheimers | wrong-lens | 35 | 65 |
| `brainstorming-hats_20260916_150534.md` | epilepsy | bear | 38 | 72 |
| `brainstorming-hats_20260916_151325.md` | epilepsy | naive | 36 | 114 |
| `brainstorming-hats_20260916_152043.md` | epilepsy | wrong-lens | 36 | 63 |
| `brainstorming-hats_20260916_152801.md` | glp1 | bear | 37 | 54 |
| `brainstorming-hats_20260916_153548.md` | glp1 | naive | 36 | 114 |
| `brainstorming-hats_20260916_154303.md` | glp1 | wrong-lens | 36 | 45 |
| `brainstorming-hats_20260916_155021.md` | crispr | bear | 38 | 59 |
| `brainstorming-hats_20260916_155800.md` | crispr | naive | 35 | 114 |
| `brainstorming-hats_20260916_160514.md` | crispr | wrong-lens | 35 | 60 |
| `brainstorming-hats_20260916_161226.md` | llm-cds | bear | 38 | 66 |
| `brainstorming-hats_20260916_162005.md` | llm-cds | naive | 36 | 114 |
| `brainstorming-hats_20260916_162721.md` | llm-cds | wrong-lens | 36 | 71 |

---

### Scenario sessions — incident response (2026-09-18/19)

Panels of our own design replace the Six Thinking Hats (see
`scenarios/DESIGN.md` and `scenarios/incident/WALKTHROUGH.md`). Four
fictional incidents at "XYZ" (`scenarios/incident/xyz-01..04`), each seven
classification-tagged documents, 27-30 planted facts with routing rules, a
seven-prompt bridge call (phase 1) and 53-54 questions asked of each role
alone from its own store (phase 2).

**Model.** Every role on `Qwen3.8-27B` served by vLLM at `localhost:8355`
(weights `unsloth/Qwen3.8-27B-NVFP4`, recorded in each session's
`run_info`). Runner `bear_parlor/run_scenarios.py`; bear-dev `3c6fd06`
(`238d02e` for the first exploratory session).

**Conditions** (`--document-diffusion` in all): `bear` (lenses + access
gate), `naive` (verbatim, no lens, no gate), `shared-memory` (lenses, gate,
shared read path), `no-gate` (lenses only), `wrong-lens` (gate, lenses
rotated one role). 4 cases × 5 conditions = 20 sessions, ~8.5 min each,
plus two exploratory `xyz-01 / bear` sessions (below). All 22 completed;
logs, stats, knowledge snapshots and answers are in
`bear_parlor/session_logs/scenarios/` in full (the documents are ours).

**Write channels.** The first exploratory session ran with Parlor's
session-insight extractor and memory manager on; 7 of its 8 store leaks and
all of its forbidden-pattern hits came through the insight extractor, which
writes conversation summaries into a role's store outside the gate. From the
second session on, every condition runs with `--no-insights --no-memories`,
so gated diffusion is the only path into a role's persistent state. The
first session is kept as evidence and is flagged and excluded from means by
the scorer (`run_info.insight_extractor`).

**Results** (`evals/eval_incident_routing.py`, `evals/eval_incident_stats.py`;
`evals/results/incident_routing.json`, `incident_stats.json/.csv`): see the
per-condition table there. Under `bear`, no denied fact reached any store
(0.00) and 1% of denied questions were answered with the fact, against 1.00
/ 0.34 for `naive` and 0.16 / 0.17 for `no-gate`; `wrong-lens` contained as
well as `bear` but delivered two-thirds as much. The residual leak under
`bear` is relay: a role repeats on the bridge something it heard, and
another role absorbs that utterance, whose provenance carries only what the
repeating role retrieved.

Dropped diffusion batches (one unparseable model reply each): 12 across the
22 sessions, in `diffusion_errors` per session.

## Embedding Model

All evaluations use **BAAI/bge-base-en-v1.5** (768-dim) via `bear.retriever.Embedder`.
Dedup threshold: d_min = 0.35 (cosine distance).

## Evaluation Scripts

| Script | Purpose |
|--------|---------|
| `eval_interhat_differentiation.py` | Pairwise centroid/Hausdorff/overlap between hat stores |
| `eval_temporal_evolution.py` | Store size growth over session turns |
| `eval_role_adherence.py` | Per-hat discrimination ratio (self vs cross alignment) |
| `eval_embed_only_baseline.py` | Embed-only dedup baseline (no LLM filtering) |
| `eval_dmin_sensitivity.py` | d_min threshold sensitivity sweep |
