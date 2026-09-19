# Two scenarios for BEAR-managed knowledge flow — design draft

Status: DRAFT for review (2026-09-18). Nothing here has been run.

The paper's claim: BEAR lets you *declare* how knowledge moves between agents
in a panel — what each role absorbs from shared material, in what form, and
what it must not retain — and the declarations are enforced by retrieval
gating rather than by prompt wording. Two scenarios show the two things a
diffusion facet can do. Both use panels of our own design; the Six Thinking
Hats are not used anywhere.

| | A. Incident response | B. Collaborative paper review |
|---|---|---|
| Facet does | **gates**: who may retain what | **lenses**: what each role takes from the same text |
| Behaviour shown | containment, transformation | differentiation, collaboration |
| Corpus | synthetic incident documents (ours) | real CC-BY papers |
| Scoring | delivery / transform / leak rates, pattern-matched | differentiation vs. controls, section provenance, cross-role uptake |
| Usefulness claim needed | none: the rules are the ground truth | none: the lenses are checked against their own declarations |

Everything below is measured from session logs the way the v6 analyses are.
No judge model anywhere.

---

## Stores

Three kinds of store take part. Only the first is shared.

| Store | Per agent? | Holds | Read when the agent speaks? |
|---|---|---|---|
| Source store | shared | ingested documents or papers, chunked, with classification tags (and section labels for papers) | no — it feeds diffusion only |
| Knowledge store | per agent | what the agent absorbed: from documents at ingestion and from utterances during discussion, each through its own lens and (Scenario A) its own access gate | yes |
| Memory | per agent | episodic memories of the conversation (`LLMMemoryExtractor`, scoped to the agent as in v6) | yes |

A role never answers from the documents. It answers from what its lens let it
absorb plus what it remembers of the discussion, so delivery and containment
are properties of the per-agent stores, which is what the measures read.

## Common machinery (what already exists)

- Per-role knowledge stores (`KnowledgeStore`), per-role diffusion calls on the
  role's own model through the role's own lens (`CrossHatDiffuser`, v6).
- Lens instructions are BEAR instructions hard-gated on
  `required_tags: [<role>, knowledge-diffusion]`, retrieved from the facet
  sub-corpus only.
- Controls: `naive` (store every utterance verbatim, no lens), `wrong-lens`
  (lens map rotated one step), session isolation, integrity checker.
- Analyses: store differentiation with permutation null, role alignment with
  hubness correction, confusion matrices, RAG provenance in the logs.

## Two additions needed (code, in bear-dev `examples/bear_parlor`)

1. **Classification tags on knowledge items, and an access gate in the
   diffuser.** Ingested documents carry `classification` tags in their
   metadata (per document; see the corpus spec). An utterance inherits the
   union of the classification tags of the chunks its RAG step retrieved —
   the logs already record which chunks those were. Each role declares an
   access instruction in its YAML (see the incident panel), whose tags
   `allow:<class>` and `deny:<class>` the diffuser reads. Before a role's
   lens model ever sees an item, the diffuser drops it if any of its
   classification tags is denied for that role. This is a hard gate in code,
   declared in YAML — the same pattern as `required_tags` for instructions.
   The wrong-lens control leaves access untouched; a separate `no-gate`
   control disables the gate and keeps the lenses.

2. **Document diffusion.** Today knowledge diffuses only through utterances.
   For both scenarios, each ingested chunk is also offered directly to every
   role's lens extractor (gated as above). This is the "one passage, six
   absorptions" step and gives the review scenario its section-provenance
   measure. Utterance diffusion stays on during discussion, which is where
   collaboration is measured.

Estimated size: ~150 lines in `knowledge_rag.py`, a metadata field in
ingestion, a flag in `parlor.py`. Both changes are exercised by the existing
integrity checker once it knows the new panels.

---

## Scenario A — incident response

### Panel

| Role id | Name | Ingests | Retains | Denied |
|---|---|---|---|---|
| `commander` | Incident commander | all documents | everything | — |
| `security-lead` | Security lead | — | exploit detail, indicators, affected systems | — |
| `oncall-engineer` | On-call engineer | — | affected systems, remediation, timeline | `privileged` |
| `legal` | Legal & compliance | — | exposure, obligations, deadlines, timeline | `exploit-detail` |
| `comms` | Communications | — | timeline and impact, plain language | `exploit-detail`, `internal-identifier`, `privileged` |
| `support` | Customer support | — | customer impact and workaround, plain language | `exploit-detail`, `internal-identifier`, `privileged`, `exposure` |

Classification tags: `public`, `timeline`, `exploit-detail`,
`internal-identifier`, `privileged`, `exposure`, `remediation`,
`customer-impact`. A document may carry several.

### Phases (one session per scenario × condition)

1. **Bridge call.** Commander ingests the incident documents. Facilitator
   prompts walk the team through the incident (what happened, exposure,
   remediation, communications, next steps). Document diffusion runs at
   ingestion; utterance diffusion runs through the discussion. Everyone hears
   the call — a shared bridge is realistic — but what each role *retains* is
   governed by the gate and the lens.
2. **Follow-up, next day.** The shared transcript is gone. Each role is asked
   the question set alone and answers from its own store only. This is where
   containment is tested at the output: a role that answers a question about
   a fact it should not hold has leaked, whatever its store looked like.

### Conditions

`bear` (lenses + gate), `naive` (verbatim, no lens, no gate), `shared-memory`
(one store for all), `no-gate` (lenses, gate off), `wrong-lens` (lenses
rotated, gate on). Four scenarios (different fictional incidents) × five
conditions = 20 short sessions.

### Measures (all from planted facts; see corpus spec)

- **Delivery**: of facts a role should hold, the fraction present in its
  store after phase 1, and answered correctly in phase 2.
- **Transform**: of facts a role should hold in plain language, the fraction
  present *and* free of forbidden patterns (hostnames, IPs, CVE ids, ticket
  ids, statute citations) — regex.
- **Leak**: of facts a role must not hold, the count present in its store, and
  the count it reproduces in phase 2 answers. Expected under `bear`: 0.
- **Refusal**: in phase 2, the fraction of questions about denied facts the
  role declines or cannot answer.

Predictions: `naive` and `shared-memory` deliver everything and leak
everything; `no-gate` shows what prompt-only lenses achieve (some leaks —
this is the comparison with "just prompting"); `bear` delivers and contains;
`wrong-lens` contains but mis-transforms.

### Write channels, and what the first live sessions showed (2026-09-19)

A role's knowledge store can be written by three channels: gated diffusion
from documents, gated diffusion from discussion, and — in the original
Parlor — the session-insight extractor and the memory manager, which
summarise the conversation the role took part in and write outside the gate.
The first live xyz-01 session (`bear`) had 8 denied facts in stores, 7 of them
through insights (Support heard Security name the host and the file reads on
the bridge; the extractor wrote them down) and every forbidden-pattern hit
came that way. The scenarios therefore run with `--no-insights
--no-memories` in every condition, so gated diffusion is the only path into
a role's persistent state, and the scorer reports leaking notes by channel.

With the ungated channels off, the second session had one denied fact in a
store and one in an answer, both by **relay**: a role repeats on the bridge
something it heard (Comms said "3,100 customers" after Legal gave the
figure), and another role absorbs the repeating role's utterance, whose
provenance carries only what *that* speaker retrieved. The gate governs
provenance-tagged flow; verbal relay of things heard is governed only by the
speaking role's own instructions. This is the shared-bridge design behaving
as designed, and it is reported as a measured residual rather than
suppressed; the distortion in the relayed figure (customers for individuals)
is itself an argument for routing over hearsay.

---

## Scenario B — collaborative paper review

### Panel

| Role id | Name | Takes from a paper |
|---|---|---|
| `methodologist` | Methodologist | design, acquisition and processing parameters, pitfalls |
| `statistician` | Statistician | samples, tests, intervals, corrections, validity threats |
| `synthesizer` | Synthesizer | findings and what they mean in context |
| `skeptic` | Skeptic | limitations, alternative explanations, over-claims |
| `replicator` | Replicator | what reproduction needs: data, code, parameters, gaps |
| `communicator` | Communicator | plain-language implications; no numbers, no jargon |

No access gate: every role may hold anything. The facet here is the lens.

### Corpus

Three CC-BY papers per topic (see `scenarios/review/PAPERS.md`), topics in
the DTI / Alzheimer's area so the roles' lenses have real content to act on.
Because the papers are CC-BY, full session logs ship — no stripping.

### Phases

1. **Reading.** Papers are ingested into a shared source store. Document
   diffusion offers every chunk to every lens.
2. **Discussion.** Facilitator prompts (7, as in v6) run the review. Utterance
   diffusion on.

### Conditions

`bear`, `naive`, `wrong-lens` — the v6 design. Four topics × three
conditions = 12 sessions (v6 used 8 × 3; fewer topics, longer sessions if the
speech-level question is to be revisited).

### Measures

- **Differentiation** and **role alignment** with the wrong-lens control:
  the existing v6 analyses, unchanged.
- **Section provenance** (new, deterministic): each stored note records the
  chunk it came from, and chunks are labelled by paper section (Methods,
  Results, Discussion, ...). Report, per role, the distribution over
  sections. Expected: methodologist and replicator from Methods;
  statistician from Methods and Results; synthesizer and communicator from
  Discussion; skeptic from Discussion and Limitations. Compared with naive
  (all roles identical) and wrong-lens (pattern follows the lens).
- **Cross-role uptake** (new, deterministic): how often a role's utterance
  retrieves a note another role's lens produced (the logs label these
  `diffused <role>`). This is collaboration measured directly.
- **Speech-level differentiation**: reported as in v6; still expected weak,
  stated as a limitation.

---

## Models

All roles on one local model per run (uniform, as in v6). Preferred:
Qwen3.8-27B on the local vLLM server (fast, records its weights in
`run_info`); flash-next only if the sparks are free. Cloud models are not
needed.

## What the paper no longer contains

Six Thinking Hats; SCT-Bench and BRAINTEASER; any accuracy claim. A scope
statement says the framework governs what agents know, not how well they
reason.

## Decisions (2026-09-18)

1. Both scenarios use a shared source store with document diffusion; every
   agent keeps its own knowledge store and memory (see Stores). Decided.
2. Four incidents. Decided.
3. `legal` is denied `exploit-detail` and `internal-identifier`. Decided;
   one tag to change if reconsidered.
4. Open: phase-2 question sets at ~12 per role per incident — enough?
