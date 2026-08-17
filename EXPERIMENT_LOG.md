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

### v4 (current) — batched diffusion

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

### Uniform Sonnet 4.6

All per-hat overrides removed from `characters.yaml`. All hats use session
default: anthropic / claude-sonnet-4-6.

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

---

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
