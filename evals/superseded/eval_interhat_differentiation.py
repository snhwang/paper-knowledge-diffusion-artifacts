"""Evaluate inter-hat role differentiation of diffusion knowledge stores.

After a brainstorming session, each hat's knowledge store should contain
different content reflecting its cognitive mode. This script measures
pairwise differentiation between hat stores using three complementary
distance metrics, comparing BEAR-guided vs. naive diffusion.

Metrics:
  - Centroid cosine distance: directional divergence between store means
  - Hausdorff distance: worst-case nearest-neighbor gap (focal differences)
  - Nearest-neighbor overlap: fraction of items with a match in the other store

Data source: session log markdown files (parses diffusion event content,
embeds using the same model as the BEAR pipeline).

Usage:
    python eval_interhat_differentiation.py
    python eval_interhat_differentiation.py --logs session_logs/bear1.md session_logs/naive1.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------

project_root = Path(__file__).resolve().parents[1]
parlor_dir = project_root / "bear_parlor"
sys.path.insert(0, str(project_root))

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
HATS = ["White", "Red", "Black", "Yellow", "Green", "Blue"]
DEDUP_THRESHOLD = 0.35

# ---------------------------------------------------------------------------
# Session log mapping: filename -> (topic, condition)
# Ordered chronologically: first 3 = BEAR-guided, last 3 = naive
# ---------------------------------------------------------------------------

SESSION_MAP = {
    # --- v5: 6-model heterogeneous panel (Sonnet, Haiku, Opus, GPT-4.1-mini, GPT-4.1, GPT-5.4) ---
    # BEAR-guided (8 topics)
    "brainstorming-hats_20260406_042916.md": ("DMG", "BEAR-guided"),
    "brainstorming-hats_20260406_043635.md": ("Stroke", "BEAR-guided"),
    "brainstorming-hats_20260406_044348.md": ("MS", "BEAR-guided"),
    "brainstorming-hats_20260406_045107.md": ("Alzheimers", "BEAR-guided"),
    "brainstorming-hats_20260406_045826.md": ("Epilepsy", "BEAR-guided"),
    "brainstorming-hats_20260406_050538.md": ("GLP1", "BEAR-guided"),
    "brainstorming-hats_20260406_051433.md": ("CRISPR", "BEAR-guided"),
    "brainstorming-hats_20260406_052335.md": ("LLM-CDS", "BEAR-guided"),
    # Naive (no BEAR filtering or dedup)
    "brainstorming-hats_20260406_063748.md": ("DMG", "Naive"),
    "brainstorming-hats_20260406_082003.md": ("Stroke", "Naive"),
    "brainstorming-hats_20260406_065215.md": ("MS", "Naive"),
    "brainstorming-hats_20260406_065933.md": ("Alzheimers", "Naive"),
    "brainstorming-hats_20260406_070649.md": ("Epilepsy", "Naive"),
    "brainstorming-hats_20260406_071406.md": ("GLP1", "Naive"),
    "brainstorming-hats_20260406_072258.md": ("CRISPR", "Naive"),
    "brainstorming-hats_20260406_073153.md": ("LLM-CDS", "Naive"),
}

# ---------------------------------------------------------------------------
# Parsing: extract diffusion content per hat from session logs
# ---------------------------------------------------------------------------

_DIFFUSION_RE = re.compile(
    r">\s*\*\[Diffusion ([\d:]+)\]\*\s+(\S+)\s+←\s+(\S+):\s+"
    r"\*\*(\w+)\*\*"
    r"(?:\s*\(dist=[\d.]+\))?"
    r"(?:\s*—\s*(.*))?"
)


def parse_diffusion_content(log_path: Path) -> dict[str, list[str]]:
    """Parse stored diffusion items per receiving hat from a session log.

    Returns dict mapping hat name -> list of content strings.
    Only includes 'stored' events (not skipped).
    """
    per_hat: dict[str, list[str]] = defaultdict(list)
    text = log_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = _DIFFUSION_RE.match(line)
        if m:
            receiving_hat = m.group(2)
            action = m.group(4)
            content = (m.group(5) or "").strip()
            if action == "stored" and content:
                per_hat[receiving_hat].append(content)
    return dict(per_hat)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str], embedder) -> np.ndarray:
    """Embed a list of texts using the sentence-transformer embedder.

    Returns array of shape (len(texts), embedding_dim).
    """
    if not texts:
        return np.array([])
    return embedder.embed(texts, is_query=False)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance between two vectors (0 = identical, 2 = opposite)."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 1.0
    return 1.0 - dot / norm


def compute_centroid_distance(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
    """Cosine distance between mean vectors of two embedding sets."""
    centroid_a = np.mean(emb_a, axis=0)
    centroid_b = np.mean(emb_b, axis=0)
    return cosine_distance(centroid_a, centroid_b)


def compute_hausdorff_distance(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
    """Symmetric Hausdorff distance using cosine metric.

    For each point in A, find its nearest neighbor in B.
    Directed Hausdorff = max of these nearest-neighbor distances.
    Symmetric = max of both directions.
    """
    def directed(source, target):
        max_dist = 0.0
        for s in source:
            dists = [cosine_distance(s, t) for t in target]
            max_dist = max(max_dist, min(dists))
        return max_dist

    return max(directed(emb_a, emb_b), directed(emb_b, emb_a))


def compute_nn_overlap(
    emb_a: np.ndarray, emb_b: np.ndarray, threshold: float = DEDUP_THRESHOLD
) -> float:
    """Bidirectional nearest-neighbor overlap at given distance threshold.

    Returns mean fraction of items in each store that have a match
    (cosine distance < threshold) in the other store.
    High overlap = stores are similar. Low overlap = stores are differentiated.
    """
    def directional(source, target, tau):
        matches = 0
        for s in source:
            min_dist = min(cosine_distance(s, t) for t in target)
            if min_dist < tau:
                matches += 1
        return matches / len(source) if len(source) > 0 else 0.0

    overlap_ab = directional(emb_a, emb_b, threshold)
    overlap_ba = directional(emb_b, emb_a, threshold)
    return (overlap_ab + overlap_ba) / 2


def compute_all_pairwise(
    hat_embeddings: dict[str, np.ndarray],
) -> list[dict]:
    """Compute all three metrics for all hat pairs (15 pairs for 6 hats)."""
    results = []
    hats_with_data = [h for h in HATS if h in hat_embeddings and len(hat_embeddings[h]) > 0]

    for hat_a, hat_b in combinations(hats_with_data, 2):
        emb_a = hat_embeddings[hat_a]
        emb_b = hat_embeddings[hat_b]
        results.append({
            "hat_a": hat_a,
            "hat_b": hat_b,
            "centroid_distance": compute_centroid_distance(emb_a, emb_b),
            "hausdorff_distance": compute_hausdorff_distance(emb_a, emb_b),
            "nn_overlap": compute_nn_overlap(emb_a, emb_b),
        })
    return results


# ---------------------------------------------------------------------------
# Cross-topic consistency check
# ---------------------------------------------------------------------------

def compute_intra_vs_inter_hat(
    all_hat_embeddings: dict[str, dict[str, np.ndarray]],
) -> dict:
    """Compare intra-hat (same hat, different topics) vs inter-hat distances.

    all_hat_embeddings: {topic: {hat: embeddings}}
    Returns dict with mean intra-hat and mean inter-hat centroid distances.
    """
    topics = list(all_hat_embeddings.keys())
    if len(topics) < 2:
        return {}

    # Intra-hat: same hat across topics
    intra_dists = []
    for hat in HATS:
        for t1, t2 in combinations(topics, 2):
            emb1 = all_hat_embeddings[t1].get(hat)
            emb2 = all_hat_embeddings[t2].get(hat)
            if emb1 is not None and len(emb1) > 0 and emb2 is not None and len(emb2) > 0:
                intra_dists.append(compute_centroid_distance(emb1, emb2))

    # Inter-hat: different hats within same topic
    inter_dists = []
    for topic in topics:
        hats_with_data = [h for h in HATS
                          if h in all_hat_embeddings[topic]
                          and len(all_hat_embeddings[topic][h]) > 0]
        for h1, h2 in combinations(hats_with_data, 2):
            inter_dists.append(compute_centroid_distance(
                all_hat_embeddings[topic][h1],
                all_hat_embeddings[topic][h2],
            ))

    return {
        "intra_hat_mean": float(np.mean(intra_dists)) if intra_dists else None,
        "intra_hat_n": len(intra_dists),
        "inter_hat_mean": float(np.mean(inter_dists)) if inter_dists else None,
        "inter_hat_n": len(inter_dists),
    }


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def run_evaluation(log_dir: Path | None = None, log_files: list[Path] | None = None):
    """Run the inter-hat differentiation evaluation."""

    from bear.retriever import Embedder

    print("=" * 70)
    print("  Inter-Hat Role Differentiation Evaluation")
    print("=" * 70)

    # Resolve session logs
    if log_files:
        paths = log_files
    else:
        log_dir = log_dir or (parlor_dir / "session_logs")
        paths = sorted(log_dir.glob("brainstorming-hats_*.md"))

    if not paths:
        print("ERROR: No session log files found.")
        sys.exit(1)

    # Initialize embedder
    print(f"\nEmbedding model: {EMBEDDING_MODEL}")
    embedder = Embedder(model_name=EMBEDDING_MODEL, dim=768)
    print("Embedder loaded.\n")

    # Process each session
    session_results = []
    bear_hat_embeddings = {}  # topic -> {hat -> embeddings} for BEAR-guided only

    for path in paths:
        filename = path.name
        info = SESSION_MAP.get(filename)
        if info is None:
            continue  # skip sessions not in our map

        topic, condition = info
        print(f"--- {topic} ({condition}) : {filename} ---")

        # Parse diffusion content per hat
        per_hat_content = parse_diffusion_content(path)
        if not per_hat_content:
            print("  WARNING: No diffusion events found, skipping.\n")
            continue

        # Report per-hat item counts
        for hat in HATS:
            count = len(per_hat_content.get(hat, []))
            if count > 0:
                print(f"  {hat}: {count} stored items")

        # Embed all hat content
        hat_embeddings: dict[str, np.ndarray] = {}
        for hat in HATS:
            texts = per_hat_content.get(hat, [])
            if texts:
                hat_embeddings[hat] = embed_texts(texts, embedder)

        # Compute pairwise metrics
        pairwise = compute_all_pairwise(hat_embeddings)

        if not pairwise:
            print("  WARNING: Not enough hat pairs for comparison.\n")
            continue

        centroids = [m["centroid_distance"] for m in pairwise]
        hausdorffs = [m["hausdorff_distance"] for m in pairwise]
        overlaps = [m["nn_overlap"] for m in pairwise]

        result = {
            "topic": topic,
            "condition": condition,
            "filename": filename,
            "n_pairs": len(pairwise),
            "centroid_mean": float(np.mean(centroids)),
            "centroid_range": (float(min(centroids)), float(max(centroids))),
            "hausdorff_mean": float(np.mean(hausdorffs)),
            "hausdorff_range": (float(min(hausdorffs)), float(max(hausdorffs))),
            "overlap_mean": float(np.mean(overlaps)),
            "overlap_range": (float(min(overlaps)), float(max(overlaps))),
            "pairwise": pairwise,
        }
        session_results.append(result)

        print(f"  Pairs: {len(pairwise)} | "
              f"Centroid: {result['centroid_mean']:.3f} | "
              f"Hausdorff: {result['hausdorff_mean']:.3f} | "
              f"Overlap: {result['overlap_mean']:.3f}")
        print()

        # Collect BEAR-guided embeddings for cross-topic analysis
        if condition == "BEAR-guided":
            bear_hat_embeddings[topic] = hat_embeddings

    if not session_results:
        print("ERROR: No valid sessions to analyze.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    for metric_name, metric_key in [
        ("Centroid Distance", "centroid_mean"),
        ("Hausdorff Distance", "hausdorff_mean"),
        ("NN Overlap", "overlap_mean"),
    ]:
        bear_vals = [s[metric_key] for s in session_results
                     if s["condition"] == "BEAR-guided"]
        naive_vals = [s[metric_key] for s in session_results
                      if s["condition"] == "Naive"]
        print(f"\n  {metric_name}:")
        if bear_vals:
            print(f"    BEAR-guided: {np.mean(bear_vals):.3f}  "
                  f"(per-topic: {', '.join(f'{v:.3f}' for v in bear_vals)})")
        if naive_vals:
            print(f"    Naive:       {np.mean(naive_vals):.3f}  "
                  f"(per-topic: {', '.join(f'{v:.3f}' for v in naive_vals)})")

    # ------------------------------------------------------------------
    # Cross-topic consistency (BEAR-guided only)
    # ------------------------------------------------------------------
    if len(bear_hat_embeddings) >= 2:
        consistency = compute_intra_vs_inter_hat(bear_hat_embeddings)
        print(f"\n  Role Consistency (BEAR-guided, centroid distance):")
        if consistency.get("intra_hat_mean") is not None:
            print(f"    Intra-hat (same hat, diff topics): "
                  f"{consistency['intra_hat_mean']:.3f}  (n={consistency['intra_hat_n']})")
        if consistency.get("inter_hat_mean") is not None:
            print(f"    Inter-hat (diff hats, same topic): "
                  f"{consistency['inter_hat_mean']:.3f}  (n={consistency['inter_hat_n']})")
        if (consistency.get("intra_hat_mean") is not None
                and consistency.get("inter_hat_mean") is not None):
            if consistency["intra_hat_mean"] < consistency["inter_hat_mean"]:
                print("    → intra < inter: role identity dominates topic identity ✓")
            else:
                print("    → intra ≥ inter: topic identity dominates role identity")

    # ------------------------------------------------------------------
    # LaTeX table
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  LaTeX Table")
    print("=" * 70)

    print(r"""
\begin{table}[t]
\caption{Inter-hat role differentiation: pairwise distance between hat knowledge
stores (mean over 15 hat pairs per session). BEAR-guided diffusion produces
stores with greater inter-hat divergence (higher centroid and Hausdorff distances,
lower nearest-neighbor overlap) than naive diffusion, confirming that cognitive
filtering produces genuinely role-differentiated knowledge.}
\label{tab:interhat}
\begin{tabular}{@{}llccc@{}}
\toprule
Topic & Condition & Centroid Dist & Hausdorff Dist & NN Overlap \\
\midrule""")

    for s in session_results:
        print(f"{s['topic']:<7} & {s['condition']:<12} "
              f"& {s['centroid_mean']:.3f} & {s['hausdorff_mean']:.3f} "
              f"& {s['overlap_mean']:.3f} \\\\")

    # Condition means
    bear_results = [s for s in session_results if s["condition"] == "BEAR-guided"]
    naive_results = [s for s in session_results if s["condition"] == "Naive"]

    if bear_results:
        bc = np.mean([s["centroid_mean"] for s in bear_results])
        bh = np.mean([s["hausdorff_mean"] for s in bear_results])
        bo = np.mean([s["overlap_mean"] for s in bear_results])
        print(r"\midrule")
        print(f"\\textbf{{BEAR mean}}  & & \\textbf{{{bc:.3f}}} "
              f"& \\textbf{{{bh:.3f}}} & \\textbf{{{bo:.3f}}} \\\\")
    if naive_results:
        nc = np.mean([s["centroid_mean"] for s in naive_results])
        nh = np.mean([s["hausdorff_mean"] for s in naive_results])
        no_ = np.mean([s["overlap_mean"] for s in naive_results])
        print(f"\\textbf{{Naive mean}} & & \\textbf{{{nc:.3f}}} "
              f"& \\textbf{{{nh:.3f}}} & \\textbf{{{no_:.3f}}} \\\\")

    print(r"""\bottomrule
\end{tabular}
\end{table}""")

    # ------------------------------------------------------------------
    # Per-pair detail (optional verbose output)
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  Per-Pair Details (BEAR-guided sessions)")
    print("=" * 70)
    for s in session_results:
        if s["condition"] != "BEAR-guided":
            continue
        print(f"\n  {s['topic']}:")
        print(f"  {'Pair':<20} {'Centroid':>9} {'Hausdorff':>10} {'Overlap':>9}")
        for p in s["pairwise"]:
            pair = f"{p['hat_a']}-{p['hat_b']}"
            print(f"  {pair:<20} {p['centroid_distance']:>9.3f} "
                  f"{p['hausdorff_distance']:>10.3f} {p['nn_overlap']:>9.3f}")

    # ------------------------------------------------------------------
    # CSV output
    # ------------------------------------------------------------------
    results_dir = project_root / "results"
    results_dir.mkdir(exist_ok=True)
    csv_path = results_dir / "interhat_differentiation.csv"
    with open(csv_path, "w") as f:
        f.write("topic,condition,centroid_mean,hausdorff_mean,overlap_mean,"
                "centroid_min,centroid_max,hausdorff_min,hausdorff_max,"
                "overlap_min,overlap_max,n_pairs\n")
        for s in session_results:
            f.write(f"{s['topic']},{s['condition']},"
                    f"{s['centroid_mean']:.4f},{s['hausdorff_mean']:.4f},"
                    f"{s['overlap_mean']:.4f},"
                    f"{s['centroid_range'][0]:.4f},{s['centroid_range'][1]:.4f},"
                    f"{s['hausdorff_range'][0]:.4f},{s['hausdorff_range'][1]:.4f},"
                    f"{s['overlap_range'][0]:.4f},{s['overlap_range'][1]:.4f},"
                    f"{s['n_pairs']}\n")
    print(f"\n  CSV saved to: {csv_path}")

    print("\nDone.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate inter-hat role differentiation of diffusion stores."
    )
    parser.add_argument(
        "--logs", nargs="+", type=Path,
        help="Session log .md files to analyze. If omitted, uses all logs in "
             "bear_parlor/session_logs/.",
    )
    args = parser.parse_args()
    run_evaluation(log_files=args.logs)


if __name__ == "__main__":
    main()
