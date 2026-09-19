# Candidate CC-BY papers for the review scenario (DRAFT)

Requirement: licence must be CC BY (any version) so the full session logs,
including ingested text, can be published in the artifacts repository. PLOS
ONE and Scientific Reports publish under CC BY as a rule; PMC deposits vary,
so the licence line on each article page must be checked before use.

Topic: white-matter diffusion imaging in Alzheimer's disease. Three papers
per topic; four topics are enough for Scenario B. The first topic is
concrete below; the other three follow the same pattern (free-water DTI,
NODDI / advanced models, longitudinal TBSS) and can be filled from the same
journals.

## Topic 1 — diffusion MRI of white matter in Alzheimer's disease

| # | Paper | Journal | Licence | File (`review/dti-ad/`) |
|---|---|---|---|---|
| 1 | Free-water diffusion tensor imaging improves the accuracy and sensitivity of white matter analysis in Alzheimer's disease | Scientific Reports, 2021 | CC BY (statement in PDF) | `freewater-dti-ad-2021.pdf` |
| 2 | Longitudinal tract-based spatial statistics analysis of white matter diffusivity changes and cognitive decline during the transition from MCI to Alzheimer's disease | PLOS ONE, 2025 | CC BY (statement in PDF) | `tbss-mci-ad-2025.pdf` |
| 3 | Analysis of advanced diffusion models assessing white matter microstructure in Alzheimer's disease | Scientific Reports, 2025 | CC BY (statement in PDF) | `advanced-diffusion-ad-2025.pdf` |

Downloaded 2026-09-18; each PDF's own text carries a Creative Commons
Attribution licence statement (checked with pypdf). Confirm the version (4.0)
on the article pages before the logs are published.

Links:
- https://www.nature.com/articles/s41598-021-86505-7
- https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0329893
- https://www.nature.com/articles/s41598-025-09412-1

## Topic 2 — diffusion MRI in Parkinson's disease (`review/dti-pd/`)

| # | Paper | Journal | Licence | File |
|---|---|---|---|---|
| 1 | Progression of regional microstructural degeneration in Parkinson's disease: a multicenter diffusion tensor imaging study | PLOS ONE, 2016 | CC BY (statement in PDF) | `dti-progression-pd-2016.pdf` |
| 2 | White matter alterations in Parkinson's disease with normal cognition precede grey matter atrophy | PLOS ONE, 2018 | CC BY (statement in PDF) | `wm-precedes-gm-pd-2018.pdf` |
| 3 | Diffusion tensor and restriction spectrum imaging reflect different aspects of neurodegeneration in Parkinson's disease | PLOS ONE, 2019 | CC BY (statement in PDF) | `dti-rsi-pd-2019.pdf` |

Links: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0165540 ·
https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0187939 ·
https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0217922

## Topic 3 — diffusion MRI in multiple sclerosis (`review/dti-ms/`)

| # | Paper | Journal | Licence | File |
|---|---|---|---|---|
| 1 | Radial diffusivity reflects general decline rather than specific cognitive deterioration in multiple sclerosis | Scientific Reports, 2022 | CC BY (statement in PDF) | `radial-diffusivity-ms-2022.pdf` |
| 2 | Diffusion tensor imaging metrics associated with future disability in multiple sclerosis | Scientific Reports, 2023 | CC BY (statement in PDF) | `dti-future-disability-ms-2023.pdf` |
| 3 | Regional grey matter microstructural changes and volume loss according to disease duration in multiple sclerosis patients | Scientific Reports, 2021 | CC BY 4.0 (statement in PDF) | `gm-microstructure-duration-ms-2021.pdf` |

Links: https://www.nature.com/articles/s41598-022-26204-z ·
https://www.nature.com/articles/s41598-023-30502-5 ·
https://www.nature.com/articles/s41598-021-96132-x

(A first candidate, "White matter volume and microstructural integrity are
associated with fatigue in relapsing multiple sclerosis", Sci Rep 2025, is
CC BY-NC-ND and was not used.)

## Other candidates

- NODDI-derived measures of microstructural integrity in medial temporal lobe
  white matter pathways are associated with Alzheimer's disease pathology and
  cognition (PMC12550277) — CC BY 4.0 stated on the PMC page.
- Microstructural white matter alterations in preclinical Alzheimer's disease
  detected using free water elimination DTI (PLOS ONE, 2017) — CC BY.
- White matter microstructure and cognition in the Alzheimer's Disease
  Connectome Project (PMC11716738) — licence to verify.
- Microstructural white matter alterations in Alzheimer's disease: a DTI study
  (PMC12724899) — licence to verify.

## Why these suit the roles

Each has an acquisition/processing section (methodologist, replicator),
group statistics with corrections (statistician), findings tied to cognition
(synthesizer, communicator) and explicit limitations (skeptic). Section
provenance can be labelled from the papers' own headings.

## Selection rule

Prefer papers whose full text is available as a PDF with clean section
headings, since section labels are assigned from headings at ingestion.
Avoid reviews for the ingestion set: the roles need primary methods and
results to differ on.
