"""Deduplication-threshold sensitivity, reconciled onto one metric definition.

WHY THIS SUPERSEDES eval_dmin_sensitivity.py
--------------------------------------------
The published d_min table reported nearest-neighbour overlap using the legacy
definition (cosine DISTANCE < 0.35, i.e. similarity > 0.65), which puts its
overlap column in the 0.91-0.99 range. Table 4 of the manuscript reports the
same-named quantity at similarity >= 0.85, where BEAR sits at 0.06. Placing a
BEAR reference row computed the second way beneath embed-only rows computed the
first way implies a ~14x effect that is an artefact of two metrics, not a
result.

Everything here comes from `overlap_metrics.py`, so the d_min table and Table 4
now share one definition.

WHAT IS MEASURED
----------------
Embed-only deduplication is simulated on the naive stores: each hat's items are
taken in order and an item is kept only if it is at least d_min (cosine
distance) from every item already kept. That is deduplication WITHOUT the
LLM reframing step, which is what isolates the contribution of dedup alone.

The BEAR reference row is the actual BEAR-guided store measured identically.

Reported at every threshold:
  store size, skip rate, centroid distance,
  mean nearest-neighbour similarity   (threshold-free, primary),
  NN overlap at tau = 0.85            (for continuity with Table 4),
  the overlap curve across tau,
  and a permutation null for the primary measure.

The permutation null matters most here. Aggressive deduplication shrinks stores
sharply (to ~1-2 items per hat at high thresholds), and small stores trivially
look differentiated. Comparing each observed value against random reassignment
of the same items, at the same store sizes, is what separates real
differentiation from a size artefact.

Corpus: the 2026-04-10/11 sessions, selected exactly as eval_interhat_
reconciled.py selects them. Diffusion-sourced items only, matching Table 4.

Outputs:
    results/dmin_reconciled.json
    results/dmin_reconciled.csv
    console summary + LaTeX table fragment

Usage:
    python evals/eval_dmin_reconciled.py
    python evals/eval_dmin_reconciled.py --n-perm 200      # faster, coarser null
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overlap_metrics import (  # noqa: E402
    TAU_DEFAULT, TAU_SWEEP, bootstrap_ci, centroid_distance, mean_pairwise,
    nn_overlap, nn_similarity, overlap_curve, permutation_null,
)

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "results"

DEFAULT_LOG_DIRS = [
    HERE.parent / "bear_parlor" / "session_logs",
    HERE.parent.parent / "examples" / "bear_parlor" / "session_logs",
]

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
TOPICS = ["dmg", "stroke", "ms", "alzheimers", "epilepsy", "glp1", "crispr", "llm-cds"]
HATS = ["white-hat", "red-hat", "black-hat", "blue-hat", "green-hat", "yellow-hat"]
DMIN_SWEEP = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]


def has_labelled_sessions(p: Path) -> bool:
    for f in p.glob("brainstorming-hats_*.stats.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if d.get("topic") and d.get("condition"):
            return True
    return False


def resolve_dir(candidates, what, validate=None) -> Path:
    for p in candidates:
        if p.exists() and (validate is None or validate(p)):
            return p
    sys.exit(f"ERROR: could not locate usable {what}. Tried:\n  " +
             "\n  ".join(str(c) for c in candidates))


def load_best_sessions(log_dir: Path) -> dict:
    raw = []
    for f in sorted(log_dir.glob("brainstorming-hats_*.stats.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not d.get("topic") or not d.get("n_turns"):
            continue
        ts = f.name.replace("brainstorming-hats_", "").replace(".stats.json", "")
        kj = log_dir / f"brainstorming-hats_{ts}.knowledge.json"
        if not kj.exists():
            continue
        raw.append((ts, d, kj))
    seen: dict = {}
    for ts, d, kj in raw:
        key = (d["topic"], d["condition"])
        score = (int(d.get("completed") is True), d["n_turns"])
        if key not in seen or score > seen[key][3]:
            seen[key] = (ts, d, kj, score)
    return {k: (v[0], v[1], v[2]) for k, v in seen.items()}


def load_hat_docs(kj_path: Path) -> dict[str, list[str]]:
    """Diffusion-sourced documents per hat, matching Table 4's item set."""
    kj = json.loads(kj_path.read_text(encoding="utf-8"))
    out = {}
    for hat in HATS:
        e = kj.get(hat, {})
        docs, metas = e.get("documents", []) or [], e.get("metadatas", []) or []
        keep = [d for d, m in zip(docs, metas)
                if (m or {}).get("source") != "pdf"] if metas else list(docs)
        if keep:
            out[hat] = keep
    return out


def greedy_dedup(embs: np.ndarray, d_min: float) -> list[int]:
    """Indices kept when each item must be >= d_min (cosine distance) from all kept."""
    kept: list[int] = []
    for i in range(len(embs)):
        if kept and float(1.0 - (embs[kept] @ embs[i]).max()) < d_min:
            continue
        kept.append(i)
    return kept


def summarise(hat_embs: dict, n_perm: int) -> dict:
    """All metrics for one session's stores, from the shared definitions."""
    return {
        "items_per_hat": float(np.mean([len(v) for v in hat_embs.values()])),
        "centroid": mean_pairwise(hat_embs, centroid_distance, HATS),
        "nn_similarity": mean_pairwise(hat_embs, nn_similarity, HATS),
        "nn_overlap": mean_pairwise(hat_embs, nn_overlap, HATS, tau=TAU_DEFAULT),
        "overlap_curve": overlap_curve(hat_embs, TAU_SWEEP, HATS),
        "null_nn_similarity": permutation_null(hat_embs, nn_similarity,
                                               n_perm=n_perm, hats=HATS),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-perm", type=int, default=1000,
                    help="Permutations for the null model (default 1000).")
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer

    log_dir = resolve_dir(DEFAULT_LOG_DIRS, "session_logs", has_labelled_sessions)
    print("=" * 74)
    print("  Deduplication-threshold sensitivity (reconciled)")
    print(f"  corpus: {log_dir}")
    print(f"  overlap: tau = {TAU_DEFAULT} (plus threshold-free NN similarity)")
    print(f"  permutations: {args.n_perm}")
    print("=" * 74)

    sessions = load_best_sessions(log_dir)
    model = SentenceTransformer(EMBEDDING_MODEL)

    per_threshold = {d: [] for d in DMIN_SWEEP}
    bear_rows, topics_used = [], []

    for topic in TOPICS:
        if (topic, "naive") not in sessions or (topic, "bear") not in sessions:
            print(f"  SKIP {topic}: missing a condition")
            continue

        naive_docs = load_hat_docs(sessions[(topic, "naive")][2])
        bear_docs = load_hat_docs(sessions[(topic, "bear")][2])
        if not naive_docs or not bear_docs:
            print(f"  SKIP {topic}: empty store")
            continue

        naive_embs = {h: model.encode(v, normalize_embeddings=True,
                                      batch_size=256, show_progress_bar=False)
                      for h, v in naive_docs.items()}
        bear_embs = {h: model.encode(v, normalize_embeddings=True,
                                     batch_size=256, show_progress_bar=False)
                     for h, v in bear_docs.items()}

        n_before = sum(len(v) for v in naive_embs.values())
        for d_min in DMIN_SWEEP:
            dedup = {h: v[greedy_dedup(v, d_min)] for h, v in naive_embs.items()}
            n_after = sum(len(v) for v in dedup.values())
            row = summarise(dedup, args.n_perm)
            row["skip_rate"] = 1.0 - (n_after / n_before) if n_before else float("nan")
            row["topic"] = topic
            per_threshold[d_min].append(row)

        b = summarise(bear_embs, args.n_perm)
        b["skip_rate"] = float("nan")
        b["topic"] = topic
        bear_rows.append(b)
        topics_used.append(topic)
        print(f"  {topic:<11} done")

    if not topics_used:
        sys.exit("ERROR: no topics produced results.")
    n = len(topics_used)

    def agg(rows, key):
        vals = [r[key] for r in rows]
        lo, hi = bootstrap_ci(vals)
        return {"mean": float(np.nanmean(vals)), "ci": [lo, hi], "per_topic": vals}

    print("\n" + "-" * 74)
    print(f"  EMBED-ONLY DEDUP SWEEP (mean over {n} topics)")
    print("-" * 74)
    print(f"  {'d_min':>6} {'items/hat':>10} {'skip':>7} {'centroid':>9} "
          f"{'NN sim':>8} {'overlap':>8} {'null sim':>9} {'z':>7}")
    results = {}
    for d_min in DMIN_SWEEP:
        rows = per_threshold[d_min]
        rec = {k: agg(rows, k) for k in
               ("items_per_hat", "skip_rate", "centroid", "nn_similarity", "nn_overlap")}
        rec["null_nn_similarity_mean"] = float(np.mean(
            [r["null_nn_similarity"]["null_mean"] for r in rows]))
        rec["null_z_mean"] = float(np.mean(
            [r["null_nn_similarity"]["z"] for r in rows]))
        rec["overlap_curve_mean"] = {
            str(t): float(np.mean([r["overlap_curve"][t] for r in rows]))
            for t in TAU_SWEEP}
        results[str(d_min)] = rec
        print(f"  {d_min:>6.2f} {rec['items_per_hat']['mean']:>10.1f} "
              f"{rec['skip_rate']['mean']:>6.1%} {rec['centroid']['mean']:>9.3f} "
              f"{rec['nn_similarity']['mean']:>8.3f} {rec['nn_overlap']['mean']:>8.3f} "
              f"{rec['null_nn_similarity_mean']:>9.3f} {rec['null_z_mean']:>7.1f}")

    bear = {k: agg(bear_rows, k) for k in
            ("items_per_hat", "centroid", "nn_similarity", "nn_overlap")}
    bear["null_nn_similarity_mean"] = float(np.mean(
        [r["null_nn_similarity"]["null_mean"] for r in bear_rows]))
    bear["null_z_mean"] = float(np.mean([r["null_nn_similarity"]["z"] for r in bear_rows]))
    bear["overlap_curve_mean"] = {
        str(t): float(np.mean([r["overlap_curve"][t] for r in bear_rows]))
        for t in TAU_SWEEP}
    print(f"  {'BEAR':>6} {bear['items_per_hat']['mean']:>10.1f} {'---':>6} "
          f"{bear['centroid']['mean']:>9.3f} {bear['nn_similarity']['mean']:>8.3f} "
          f"{bear['nn_overlap']['mean']:>8.3f} "
          f"{bear['null_nn_similarity_mean']:>9.3f} {bear['null_z_mean']:>7.1f}")

    print("\n  NN sim and overlap are now the SAME definitions as Table 4.")
    print("  'null sim' is mean NN similarity under random reassignment of the")
    print("  same items at the same store sizes; z is how far the observed value")
    print("  sits from that null. Differentiation that does not beat the null is")
    print("  a store-size artefact rather than a property of the mechanism.")

    print("\n" + "-" * 74)
    print("  OVERLAP CURVE — is the ordering threshold-invariant?")
    print("-" * 74)
    print("  " + " " * 8 + "".join(f"{t:>8.2f}" for t in TAU_SWEEP))
    for lab, rec in [("dedup .35", results["0.35"]), ("BEAR", bear)]:
        print(f"  {lab:<8}" + "".join(
            f"{rec['overlap_curve_mean'][str(t)]:>8.3f}" for t in TAU_SWEEP))

    # ------------------------------------------------------------------
    OUT_DIR.mkdir(exist_ok=True)
    payload = {
        "metadata": {
            "eval": "dmin_reconciled",
            "supersedes": "eval_dmin_sensitivity.py (legacy overlap definition)",
            "embedding_model": EMBEDDING_MODEL,
            "tau": TAU_DEFAULT, "tau_sweep": list(TAU_SWEEP),
            "n_perm": args.n_perm, "n_topics": n, "topics": topics_used,
            "items": "diffusion-sourced only, matching Table 4",
        },
        "dedup_sweep": results,
        "bear_reference": bear,
    }
    jp = OUT_DIR / "dmin_reconciled.json"
    jp.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    print(f"\n  JSON saved to: {jp}")

    cp = OUT_DIR / "dmin_reconciled.csv"
    with open(cp, "w", encoding="utf-8", newline="") as f:
        f.write("d_min,items_per_hat,skip_rate,centroid,nn_similarity,"
                "nn_overlap_tau085,null_nn_similarity,null_z\n")
        for d_min in DMIN_SWEEP:
            r = results[str(d_min)]
            f.write(f"{d_min},{r['items_per_hat']['mean']:.4f},"
                    f"{r['skip_rate']['mean']:.4f},{r['centroid']['mean']:.4f},"
                    f"{r['nn_similarity']['mean']:.4f},{r['nn_overlap']['mean']:.4f},"
                    f"{r['null_nn_similarity_mean']:.4f},{r['null_z_mean']:.2f}\n")
        f.write(f"BEAR,{bear['items_per_hat']['mean']:.4f},,"
                f"{bear['centroid']['mean']:.4f},{bear['nn_similarity']['mean']:.4f},"
                f"{bear['nn_overlap']['mean']:.4f},"
                f"{bear['null_nn_similarity_mean']:.4f},{bear['null_z_mean']:.2f}\n")
    print(f"  CSV saved to:  {cp}")

    print("\n" + "=" * 74)
    print("  LaTeX table fragment (replaces tab:dmin-sensitivity)")
    print("=" * 74)
    print(r"""\begin{tabular}{@{}rrrrrr@{}}
\toprule
$d_{\min}$ & Store/hat & Skip\% & Centroid & NN sim & NN overlap \\
\midrule""")
    for d_min in DMIN_SWEEP:
        r = results[str(d_min)]
        bold = r"\textbf{" if abs(d_min - 0.35) < 1e-9 else ""
        e = "}" if bold else ""
        print(f"{bold}{d_min:.2f}{e} & {bold}{r['items_per_hat']['mean']:.1f}{e} & "
              f"{bold}{r['skip_rate']['mean']:.1%}{e} & "
              f"{bold}{r['centroid']['mean']:.3f}{e} & "
              f"{bold}{r['nn_similarity']['mean']:.3f}{e} & "
              f"{bold}{r['nn_overlap']['mean']:.3f}{e} \\\\".replace("%", r"\%"))
    print(r"\midrule")
    print(f"BEAR & {bear['items_per_hat']['mean']:.1f} & --- & "
          f"{bear['centroid']['mean']:.3f} & {bear['nn_similarity']['mean']:.3f} & "
          f"{bear['nn_overlap']['mean']:.3f} \\\\")
    print(r"""\bottomrule
\end{tabular}""")
    print("\nDone.")


if __name__ == "__main__":
    main()
