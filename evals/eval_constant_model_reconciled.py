"""Constant-model control: does BEAR differentiate hats when the model is held fixed?

WHAT THIS TESTS
---------------
The primary evaluation gives the six hats six different LLMs. That leaves open
whether the measured differentiation comes from the BEAR instructions or simply
from using different models. This control re-runs the same DMG session with all
six hats on ONE model, twice: a cloud model (Claude Sonnet 4.6) and a local 12B
model (Mistral NeMo Instruct 2407). If differentiation survives model
homogeneity, it is not a model-diversity artefact.

WHAT IS MEASURED, AND WHY IT DIFFERS FROM TABLE 4
-------------------------------------------------
This control measures hat **dialogue responses** (what agents say), whereas
Table 4 measures hat **knowledge store items** (what agents retain). They are
complementary questions, and their numbers are not comparable: responses are
long, on-topic and share the conversation's vocabulary, so cross-hat similarity
is high in absolute terms regardless of condition.

That last point is why this script reports a permutation null for every
statistic. Response-level overlap near 0.9 sounds alarming next to Table 4's
0.06, but the meaningful question is not the absolute value, it is whether the
assignment of responses to hats beats random assignment of the same responses.

Metrics come from `overlap_metrics.py`, so this control and Table 4 share one
definition. The published version of this table used tau = 0.9 for overlap;
that value is reported alongside the shared default of 0.85 rather than
silently substituted.

SESSIONS
--------
Six DMG sessions on the v1 prompt, identified from EXPERIMENT_LOG.md. The
session logs record no model metadata themselves, so that file is the only
means of telling them apart.

REPRODUCIBILITY
---------------
This analysis is deterministic and fully reproducible from the logs. The
sessions themselves are NOT reproducible: the local model's quantization and
the sampling parameters were never recorded. See the correction note in
EXPERIMENT_LOG.md.

Outputs:
    results/constant_model_reconciled.json
    results/constant_model_reconciled.csv
    console summary + LaTeX table fragment

Usage:
    python evals/eval_constant_model_reconciled.py
    python evals/eval_constant_model_reconciled.py --n-perm 200
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overlap_metrics import (  # noqa: E402
    bootstrap_ci, centroid_distance, mean_pairwise, nn_overlap, nn_similarity,
    permutation_null,
)

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "results"
LOG_DIRS = [HERE.parent / "bear_parlor" / "session_logs",
            HERE.parent.parent / "examples" / "bear_parlor" / "session_logs"]

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
HATS = ["White", "Red", "Black", "Yellow", "Green", "Blue"]
TAU_PUBLISHED = 0.90   # threshold used by the published version of this table
TAU_SHARED = 0.85      # the shared default, for comparability with Table 4

# From EXPERIMENT_LOG.md. All DMG, all v1 prompt, so the only variable across
# rows is which model(s) the hats use.
SESSIONS = [
    ("Heterogeneous",        "BEAR-guided", "20260308_131430"),
    ("Heterogeneous",        "Naive",       "20260308_133940"),
    ("Uniform (Sonnet 4.6)", "BEAR-guided", "20260313_013537"),
    ("Uniform (Sonnet 4.6)", "Naive",       "20260313_014207"),
    ("Uniform (12B local)",  "BEAR-guided", "20260313_003943"),
    ("Uniform (12B local)",  "Naive",       "20260313_010034"),
]

_TURN_RE = re.compile(
    r"^###\s+Turn\s+(\d+)\s*[—-]\s*([A-Za-z]+)[^\n]*\n(.*?)(?=^###\s+Turn|\Z)",
    re.MULTILINE | re.DOTALL,
)


def resolve_log_dir() -> Path:
    for p in LOG_DIRS:
        if p.exists() and any(p.glob("brainstorming-hats_*.md")):
            return p
    sys.exit("ERROR: could not locate session_logs.")


def parse_responses(md: Path) -> dict[str, list[str]]:
    """Dialogue responses per hat, with logging apparatus stripped."""
    text = md.read_text(encoding="utf-8", errors="replace")
    out: dict[str, list[str]] = {h: [] for h in HATS}
    for _, speaker, body in _TURN_RE.findall(text):
        hat = speaker.strip().capitalize()
        if hat not in HATS:
            continue
        # Remove retrieval tables, knowledge-RAG blocks and diffusion lines so
        # only what the agent actually said is embedded.
        b = re.sub(r"<details>.*?</details>", " ", body, flags=re.DOTALL)
        b = re.sub(r"^\s*\|.*$", " ", b, flags=re.MULTILINE)
        b = re.sub(r"\*\*Knowledge RAG\*\*.*?(?=\n###|\n---|\Z)", " ", b, flags=re.DOTALL)
        b = re.sub(r"^\s*>\s*\*\[Diffusion.*$", " ", b, flags=re.MULTILINE)
        b = re.sub(r"^\s*---\s*$", " ", b, flags=re.MULTILINE)
        b = " ".join(b.split())
        if len(b.split()) >= 10:
            out[hat].append(b)
    return {h: v for h, v in out.items() if v}


def hausdorff(a: np.ndarray, b: np.ndarray) -> float:
    """Symmetric Hausdorff distance in cosine space."""
    a, b = np.asarray(a), np.asarray(b)
    if not len(a) or not len(b):
        return float("nan")
    d = 1.0 - (a @ b.T)
    return float(max(d.min(axis=1).max(), d.min(axis=0).max()))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-perm", type=int, default=1000,
                    help="Permutations for the null model (0 to skip).")
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer

    log_dir = resolve_log_dir()
    print("=" * 78)
    print("  Constant-model control (reconciled) — DMG, v1 prompt")
    print(f"  logs: {log_dir}")
    print("  measured over DIALOGUE RESPONSES (Table 4 measures stored items)")
    print("=" * 78)

    model = SentenceTransformer(EMBEDDING_MODEL)
    rows = []

    for models, condition, ts in SESSIONS:
        md = log_dir / f"brainstorming-hats_{ts}.md"
        if not md.exists():
            print(f"  MISSING {ts} ({models}, {condition}) — skipped")
            continue
        resp = parse_responses(md)
        if len(resp) < 2:
            print(f"  {ts}: too few hats parsed — skipped")
            continue
        embs = {h: model.encode(v, normalize_embeddings=True,
                                show_progress_bar=False) for h, v in resp.items()}

        rec = {
            "models": models, "condition": condition, "session": ts,
            "responses_per_hat": float(np.mean([len(v) for v in resp.values()])),
            "n_hats": len(resp),
            "centroid": mean_pairwise(embs, centroid_distance, HATS),
            "hausdorff": mean_pairwise(embs, hausdorff, HATS),
            "nn_similarity": mean_pairwise(embs, nn_similarity, HATS),
            "overlap_090": mean_pairwise(embs, nn_overlap, HATS, tau=TAU_PUBLISHED),
            "overlap_085": mean_pairwise(embs, nn_overlap, HATS, tau=TAU_SHARED),
        }
        if args.n_perm:
            for name, fn, kw in (("centroid", centroid_distance, {}),
                                 ("nn_similarity", nn_similarity, {}),
                                 ("overlap_090", nn_overlap, {"tau": TAU_PUBLISHED})):
                rec[f"null_{name}"] = permutation_null(
                    embs, fn, n_perm=args.n_perm, hats=HATS, **kw)
        rows.append(rec)
        print(f"  {models:<22} {condition:<12} {rec['n_hats']} hats, "
              f"{rec['responses_per_hat']:.1f} responses/hat")

    if not rows:
        sys.exit("ERROR: no sessions parsed.")

    print("\n" + "-" * 78)
    print("  OBSERVED (dialogue responses)")
    print("-" * 78)
    print(f"  {'Models':<22}{'Condition':<13}{'Centroid':>9}{'Hausd.':>8}"
          f"{'NN sim':>8}{'Ovl.90':>8}{'Ovl.85':>8}")
    for r in rows:
        print(f"  {r['models']:<22}{r['condition']:<13}{r['centroid']:>9.3f}"
              f"{r['hausdorff']:>8.3f}{r['nn_similarity']:>8.3f}"
              f"{r['overlap_090']:>8.3f}{r['overlap_085']:>8.3f}")

    if args.n_perm:
        print("\n" + "-" * 78)
        print("  VS PERMUTATION NULL — does assigning responses to these hats matter?")
        print("-" * 78)
        print(f"  {'Models':<22}{'Condition':<13}{'statistic':<15}"
              f"{'obs':>8}{'null':>8}{'z':>8}{'p':>8}")
        for r in rows:
            for name in ("centroid", "nn_similarity", "overlap_090"):
                nl = r.get(f"null_{name}")
                if not nl:
                    continue
                z = nl["z"]; p = nl["p"]
                zs = "  n/a" if np.isnan(z) else f"{z:>8.2f}"
                ps = "  n/a" if np.isnan(p) else f"{p:>8.3f}"
                print(f"  {r['models']:<22}{r['condition']:<13}{name:<15}"
                      f"{nl['observed']:>8.3f}{nl['null_mean']:>8.3f}{zs}{ps}")
        print("\n  Absolute response-level overlap is high in every condition,")
        print("  because all six hats discuss one topic in one conversation. What")
        print("  distinguishes the conditions is whether the observed value beats")
        print("  random reassignment of the same responses.")

    OUT_DIR.mkdir(exist_ok=True)
    payload = {
        "metadata": {
            "eval": "constant_model_reconciled",
            "measures": "hat dialogue responses (NOT knowledge store items)",
            "topic": "DMG", "prompt_version": "v1",
            "embedding_model": EMBEDDING_MODEL,
            "tau_published": TAU_PUBLISHED, "tau_shared": TAU_SHARED,
            "n_perm": args.n_perm,
            "sessions_from": "EXPERIMENT_LOG.md",
            "reproducibility": "Analysis is deterministic. The sessions are not "
                               "reproducible: local-model quantization and sampling "
                               "parameters were never recorded.",
        },
        "rows": rows,
    }
    jp = OUT_DIR / "constant_model_reconciled.json"
    jp.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    print(f"\n  JSON saved to: {jp}")

    cp = OUT_DIR / "constant_model_reconciled.csv"
    with open(cp, "w", encoding="utf-8", newline="") as f:
        f.write("models,condition,session,responses_per_hat,centroid,hausdorff,"
                "nn_similarity,overlap_090,overlap_085,null_centroid_z\n")
        for r in rows:
            z = r.get("null_centroid", {}).get("z", float("nan"))
            f.write(f"\"{r['models']}\",{r['condition']},{r['session']},"
                    f"{r['responses_per_hat']:.2f},{r['centroid']:.4f},"
                    f"{r['hausdorff']:.4f},{r['nn_similarity']:.4f},"
                    f"{r['overlap_090']:.4f},{r['overlap_085']:.4f},{z:.2f}\n")
    print(f"  CSV saved to:  {cp}")

    print("\n" + "=" * 78)
    print("  LaTeX table fragment (replaces tab:constant-model)")
    print("=" * 78)
    print(r"""\begin{tabular}{@{}llcccc@{}}
\toprule
Condition & Models & Centroid & Hausdorff & Overlap & $z$ vs null \\
\midrule""")
    for cond in ("BEAR-guided", "Naive"):
        for r in [x for x in rows if x["condition"] == cond]:
            z = r.get("null_centroid", {}).get("z", float("nan"))
            zs = "---" if np.isnan(z) else f"{z:.1f}"
            print(f"{cond} & {r['models']} & {r['centroid']:.3f} & "
                  f"{r['hausdorff']:.3f} & {r['overlap_090']:.3f} & {zs} \\\\")
        if cond == "BEAR-guided":
            print(r"\midrule")
    print(r"""\bottomrule
\end{tabular}""")
    print("\nDone.")


if __name__ == "__main__":
    main()
