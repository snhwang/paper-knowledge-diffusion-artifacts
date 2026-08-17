# Running the experiments

This repository is **analysis-first**. Everything in `evals/` reads recorded
session logs and store snapshots and is deterministic: given this repository and
the dependencies in `requirements.txt`, anyone can reproduce every reported
number exactly.

**Generating new sessions is a different matter**, and this file is explicit
about what is and is not reproducible, because the distinction is easy to blur.

---

## 1. What is reproducible

| | Reproducible? | Why |
|---|---|---|
| Analysis of recorded sessions (`evals/`) | **Yes, exactly** | Deterministic. Reads fixed text; embeddings are pinned to `BAAI/bge-base-en-v1.5`. |
| Benchmark harnesses (`benchmarks/`) | Approximately | Require live LLM APIs. Sampling is stochastic, and providers update models behind stable names. |
| Regenerating panel sessions | **No** | See below. |

### Why panel sessions cannot be regenerated exactly

1. **The source PDFs are not redistributable.** Each session was seeded with
   three copyrighted manuscripts. `bear_parlor/topics/README.md` lists them with
   DOIs so they can be obtained independently, but they are not in this repo.
2. **Sampling is stochastic**, and several hats ran at non-zero temperature.
3. **Local-model builds were not recorded.** The constant-model control used a
   local Mistral NeMo Instruct 2407 whose quantization was never written down;
   LM Studio and ollama ship different quantizations of that model
   (Q4_K_M vs Q4_0) which do not produce identical output.
4. **Cloud models drift.** `claude-sonnet-4-6` today is not guaranteed to be
   byte-identical to the endpoint that served these sessions.

Re-running therefore produces a **new experiment**, not a reproduction. That is
normal for LLM work, but it should be stated rather than implied, so treat the
recorded logs as the primary evidence.

---

## 2. Endpoints for local models — READ THIS FIRST

Local-model endpoints are the most common reason a run fails on different
hardware. **The defaults below are what the original runs used and are not
guaranteed to match your installation.** Recent LM Studio releases have changed
the default server address and port, so the values baked into BEAR may be wrong
for you.

| Runtime | BEAR's default | Override with |
|---|---|---|
| LM Studio | `http://127.0.0.1:1234/v1` | `LM_STUDIO_URL` |
| Ollama | `http://localhost:11434` | `OLLAMA_HOST` |

Both are read from the environment before any default is applied, so setting
them is always sufficient. Check the address your server actually reports and
set it explicitly rather than relying on the default:

```bash
# LM Studio -> Developer tab shows the server URL it is listening on
export LM_STUDIO_URL="http://127.0.0.1:1234/v1"      # adjust host AND port
export OLLAMA_HOST="http://localhost:11434"

# Windows PowerShell
$env:LM_STUDIO_URL = "http://127.0.0.1:1234/v1"
$env:OLLAMA_HOST   = "http://localhost:11434"
```

Under WSL, `localhost` does not reach a server running on the Windows host.
BEAR attempts to detect WSL and substitute the default-gateway address, but if
that fails set `LM_STUDIO_URL` to the gateway explicitly:

```bash
export LM_STUDIO_URL="http://$(ip route show default | awk '/default/{print $3}'):1234/v1"
```

Verify before a long run:

```bash
curl "$LM_STUDIO_URL/models"        # should list the loaded model
curl "$OLLAMA_HOST/api/tags"        # should list ollama models
```

---

## 3. Generating panel sessions

The generation machinery is **not** in this repository. It lives in the BEAR
repository under `examples/bear_parlor/`: the panel server (`parlor.py`), the
diffusion layer (`knowledge_rag.py`), PDF ingestion (`ingest.py`) and the
scripted drivers (`run_demo_session.py`, `run_demo_session_v2.py`).

```bash
git clone https://github.com/snhwang/bear.git
cd bear && git checkout v0.1.0        # the version that produced these sessions
```

Place the topic PDFs in `examples/bear_parlor/<TOPIC>/` using the filenames in
`bear_parlor/topics/README.md`, then:

```bash
cd examples/bear_parlor

# Heterogeneous panel, BEAR-guided (per-hat models from characters.yaml)
python run_demo_session.py --topic dmg

# Naive diffusion ablation
python run_demo_session.py --topic dmg --naive-diffusion
```

### Constant-model controls

All six hats on one model, which is what `--override-model` is for: it ignores
the per-hat `llm_backend`/`llm_model` entries in `characters.yaml` and forces
the session default everywhere.

```bash
# Uniform cloud model
python parlor.py --backend anthropic --model claude-sonnet-4-6 --override-model

# Uniform local model via LM Studio
# There is no --base-url flag: the lmstudio backend reads LM_STUDIO_URL from
# the environment, so set it first (section 2).
python parlor.py --backend lmstudio --model mistral-nemo-instruct-2407 --override-model

# Uniform local model via ollama (reads OLLAMA_HOST from the environment)
python parlor.py --backend ollama --model mistral-nemo:latest --override-model
```

`--backend` accepts `openai`, `anthropic`, `gemini`, `ollama` and `lmstudio`.
The parlor's own `--help` lists only the first four, but `lmstudio` is a valid
backend and is the one to use for an LM Studio server.

then drive the session with `run_demo_session.py` as above. **Record the exact
model build and quantization**, which is precisely what was not done originally.

`EXPERIMENT_LOG.md` in this repository is the index mapping every session log
filename to its topic, condition, prompt version and model configuration. The
session logs themselves carry no model metadata, so without that file the runs
are indistinguishable.

---

## 4. Coverage: which results have a script here

| Manuscript item | Script | Status |
|---|---|---|
| Table: inter-hat differentiation | `evals/eval_interhat_reconciled.py` | current |
| Table: three-way ablation | `evals/eval_embed_only_baseline.py` | legacy metric |
| Table: d_min sensitivity | `evals/eval_dmin_reconciled.py` | current |
| Table: role adherence | `evals/eval_role_adherence.py` | legacy metric |
| Table: significance | `evals/eval_significance.py` | legacy metric |
| Table: architecture baselines | `evals/eval_architecture_baselines.py` | current |
| Table: constant-model control | `evals/eval_constant_model_reconciled.py` | current |
| Table: SCT-Bench | `benchmarks/sct_eval_v2.py` | needs LLM APIs |
| Table: BRAINTEASER | `benchmarks/brainteaser_eval.py` | needs LLM APIs |
| Figure: temporal evolution | `evals/eval_temporal_reconciled.py` | current |
| Figure: knowledge flow matrix | `evals/eval_knowledge_flow_matrix.py` | current |
| Figure: motivation (Fig. 1) | none — TikZ, drawn in the manuscript | quotes are verbatim from `bear_parlor/session_logs/brainstorming-hats_20260411_080827.md` |
| Figure: BEAR pipeline | none — schematic | no data |
| Figure: YAML example | none — listing | no data |
| Figure: session excerpt | none — quoted log | from the session logs |

"legacy metric" means the script predates `overlap_metrics.py` and uses the
older overlap definition (cosine distance < 0.35, i.e. similarity > 0.65) rather
than the shared `cos >= 0.85`. Its numbers are internally consistent but are not
comparable with the current tables. Reconciling those three is outstanding.

`evals/verify_paper_values.py` checks the manuscript's reported numbers against
regenerated outputs and is the fastest way to confirm a working setup.
