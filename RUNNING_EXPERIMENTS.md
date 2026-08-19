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
| Analysis of recorded sessions (`evals/`) | **Yes** | Reads fixed text; embeddings are pinned to `BAAI/bge-base-en-v1.5`. No Mathpix account or LLM API needed. Agreement is to ~7 significant figures, not bit-for-bit — see below. |
| Benchmark harnesses (`benchmarks/`) | Approximately | Require live LLM APIs. Sampling is stochastic, and providers update models behind stable names. |
| Regenerating panel sessions | **No** | Needs the non-redistributable source PDFs and a Mathpix account, and is stochastic besides. See below. |

### Why panel sessions cannot be regenerated exactly

1. **The source PDFs are not redistributable.** Each session was seeded with
   three copyrighted manuscripts. `bear_parlor/topics/README.md` lists them with
   DOIs so they can be obtained independently, but they are not in this repo.
2. **PDF extraction used Mathpix, a paid third-party API.** Without Mathpix
   credentials the ingestion path silently falls back to pypdf, which extracts
   roughly a quarter as much text per document. See section 2 — this is the
   reason most likely to be overlooked, because nothing fails loudly.
3. **Sampling is stochastic**, and several hats ran at non-zero temperature.
4. **Local-model builds were not recorded.** The constant-model control used a
   local Mistral NeMo Instruct 2407 whose quantization was never written down;
   LM Studio and ollama ship different quantizations of that model
   (Q4_K_M vs Q4_0) which do not produce identical output.
5. **Cloud models drift.** `claude-sonnet-4-6` today is not guaranteed to be
   byte-identical to the endpoint that served these sessions.

Re-running therefore produces a **new experiment**, not a reproduction. That is
normal for LLM work, but it should be stated rather than implied, so treat the
recorded logs as the primary evidence.

### Precision of the analysis scripts

The `evals/` scripts are deterministic in the sense that matters, but not
bit-for-bit. Re-running them on the same inputs reproduces every value to about
seven significant figures, with the last digits moving from floating-point
nondeterminism in the embedding backend. A regeneration of the temporal
evolution results, for instance, moved the BEAR final centroid from
`0.09751095` to `0.09751097`. Every value the manuscript reports is given to
three or four significant figures, so nothing published is affected, and
`verify_paper_values.py` uses tolerances set to the manuscript's own rounding.
Do not expect `git diff` on the JSON files to come back empty after a re-run.

---

## 2. PDF extraction — Mathpix is needed to come close

**Every session reported in the paper ingested its PDFs through the Mathpix
OCR API.** Reproducing the sessions without it will not reproduce the reported
numbers, and the failure is silent.

This does **not** affect anything in `evals/`. Those scripts read the recorded
logs and store snapshots, so every number in the paper reproduces from this
repository with no Mathpix account. Mathpix matters only if you regenerate
sessions from the source PDFs.

`KnowledgeStore.ingest_pdf` in `examples/bear_parlor/knowledge_rag.py` checks
for credentials and chooses the extractor itself:

```python
if os.environ.get("MATHPIX_APP_ID") and os.environ.get("MATHPIX_APP_KEY"):
    text = extract_pdf_text_mathpix(pdf_path)   # markdown: headings, tables, LaTeX
else:
    text = extract_pdf_text(pdf_path)           # pypdf: plain text
```

There is no warning and no error. A run without credentials completes normally
on a much thinner knowledge base.

### How much it matters

The archive spans both extractors, because the project switched to Mathpix
partway through. The same PDF, ingested before and after the switch:

| Source PDF | pypdf (to 2026-04-06) | Mathpix (from 2026-04-11) |
|---|---|---|
| `CRISPR ethics.pdf` | 17 chunks | 59 chunks |
| `Liu et al adaptive immunotherapeutic paradigms in DMG.pdf` | 12 | 54 |
| `remyelination.pdf` | 12 | 60 |
| `laurent CRISPR-based gene therapies.pdf` | 15 | 66 |
| `Alzheimer's disease etiology hypotheses...pdf` | 17 | 91 |

Roughly a 4x difference in retained text at a 1,200-character chunk size.
pypdf drops tables, figure captions and equation-heavy passages, which in this
corpus is where much of the quantitative content lives. Different knowledge
bases produce different diffusion events, different stores, and therefore
different values in every store-level table.

**All 16 sessions the paper reports are from 2026-04-11**, so extraction is
uniform within the evaluated corpus. The older sessions still in
`bear_parlor/session_logs/` are pypdf-era and are not what any table reports.
You can tell them apart directly: Mathpix-era chunks in the `.knowledge.json`
snapshots contain `cdn.mathpix.com` image links and LaTeX math, which pypdf
cannot produce.

```bash
export MATHPIX_APP_ID="..."      # https://mathpix.com — paid, free tier available
export MATHPIX_APP_KEY="..."
```

```powershell
$env:MATHPIX_APP_ID  = "..."
$env:MATHPIX_APP_KEY = "..."
```

`ingest.py` used standalone takes an explicit `--mathpix` flag instead; the
session path above reads the environment and needs no flag.

Even with credentials, Mathpix is a hosted service whose OCR models change, so
identical output is not guaranteed either. Treat Mathpix as the difference
between a comparable run and a clearly different one, not as a route to exact
reproduction.

---

## 3. Endpoints for local models — READ THIS FIRST

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

## 4. Generating panel sessions

The generation machinery is **not** in this repository. It lives in the BEAR
repository under `examples/bear_parlor/`: the panel server (`parlor.py`), the
diffusion layer (`knowledge_rag.py`), PDF ingestion (`ingest.py`) and the
scripted drivers (`run_demo_session.py`, `run_demo_session_v2.py`).

```bash
git clone https://github.com/snhwang/bear.git
cd bear && git checkout v0.1.0        # the version that produced these sessions
```

Place the topic PDFs in `examples/bear_parlor/<TOPIC>/` using the filenames in
`bear_parlor/topics/README.md`. **Set `MATHPIX_APP_ID` and `MATHPIX_APP_KEY`
first** (section 2). `ingest_pdf` reuses any chunks already stored for the same
paper rather than re-extracting, so without `--clean` a store seeded by a
pypdf run keeps serving pypdf chunks even after credentials are set. Then:

```bash
cd examples/bear_parlor

# Heterogeneous panel, BEAR-guided (per-hat models from characters.yaml)
python run_demo_session.py --topic dmg --clean

# Naive diffusion ablation
python run_demo_session.py --topic dmg --naive-diffusion --clean
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
# the environment, so set it first (section 3).
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

## 5. Coverage: which results have a script here

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
