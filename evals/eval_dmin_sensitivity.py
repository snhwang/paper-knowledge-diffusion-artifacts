"""Deduplication threshold (d_min) sensitivity sweep.

This script evaluates how the cosine-distance deduplication threshold d_min
affects knowledge store size and inter-hat differentiation in BEAR's cross-hat
diffusion mechanism.

Methodology:
  We replay the three naive session logs (DMG, Stroke, MS) — which store every
  cross-hat utterance verbatim — and simulate embed-only dedup at each threshold
  value. For each threshold, we compute:

    - Mean store size per hat (items retained after dedup)
    - Mean skip rate (fraction of items rejected by dedup)
    - Inter-hat differentiation metrics (centroid distance, Hausdorff distance,
      nearest-neighbor overlap) averaged over all 15 hat pairs × 3 topics

  Embeddings are computed once using BAAI/bge-base-en-v1.5 and reused across
  all threshold values, ensuring that the only variable is the threshold itself.

  BEAR-guided results (from interhat_differentiation.csv) are included as a
  reference line, showing the differentiation achieved by full cognitive
  filtering (dedup + LLM reframing).

Relationship to eval_embed_only_baseline.py:
  This script imports parsing, embedding, dedup simulation, and metric functions
  from eval_embed_only_baseline.py. The baseline script runs at a single
  threshold; this script sweeps across multiple thresholds.

Outputs:
  - Console: summary table (threshold × metrics)
  - CSV: results/dmin_sensitivity.csv
  - JSON: results/dmin_sensitivity.json (includes metadata for reproducibility)
  - PDF figure: results/dmin_sensitivity.pdf (dual-axis tradeoff curve)
  - LaTeX table fragment (printed to console)

Usage:
    # Default sweep: d_min = 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50
    python paper/evaluation/eval_dmin_sensitivity.py

    # Custom thresholds
    python paper/evaluation/eval_dmin_sensitivity.py --thresholds 0.15 0.20 0.25 0.30 0.35 0.40 0.45 0.50 0.55

    # Skip figure generation (headless environments)
    python paper/evaluation/eval_dmin_sensitivity.py --no-plot

    # Custom output directory
    python paper/evaluation/eval_dmin_sensitivity.py --output-dir /tmp/results
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------

project_root = Path(__file__).resolve().parents[1]
eval_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Import reusable infrastructure from eval_embed_only_baseline
from eval_embed_only_baseline import (  # noqa: E402
    EMBEDDING_MODEL,
    HATS,
    NAIVE_SESSIONS,
    cosine_distance,
    embed_texts,
    parse_hat_utterances,
    simulate_embed_only_dedup,
    compute_centroid_distance,
    compute_hausdorff_distance,
    compute_nn_overlap,
    compute_pairwise_metrics,
)

SCRIPT_VERSION = "1.0.0"
DEFAULT_THRESHOLDS = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
PARLOR_DIR = project_root / "bear_parlor"


# ---------------------------------------------------------------------------
# Load BEAR-guided reference data
# ---------------------------------------------------------------------------

def load_bear_reference() -> dict | None:
    """Load BEAR-guided inter-hat differentiation results from CSV.

    Returns mean metrics across topics, or None if CSV not found.
    """
    csv_path = eval_dir / "results" / "interhat_differentiation.csv"
    if not csv_path.exists():
        return None

    centroids, hausdorffs, overlaps = [], [], []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["condition"] == "BEAR-guided":
                centroids.append(float(row["centroid_mean"]))
                hausdorffs.append(float(row["hausdorff_mean"]))
                overlaps.append(float(row["overlap_mean"]))

    if not centroids:
        return None

    return {
        "centroid_mean": float(np.mean(centroids)),
        "hausdorff_mean": float(np.mean(hausdorffs)),
        "overlap_mean": float(np.mean(overlaps)),
    }


# ---------------------------------------------------------------------------
# Sweep logic
# ---------------------------------------------------------------------------

def run_sweep(
    thresholds: list[float],
    output_dir: Path,
    plot: bool = True,
) -> list[dict]:
    """Run the d_min sensitivity sweep.

    Args:
        thresholds: List of d_min values to evaluate.
        output_dir: Directory for CSV/JSON/PDF outputs.
        plot: Whether to generate the matplotlib figure.

    Returns:
        List of per-threshold result dicts.
    """
    from bear.retriever import Embedder

    print("=" * 70)
    print("  d_min Sensitivity Sweep")
    print(f"  Thresholds: {thresholds}")
    print("=" * 70)

    embedder = Embedder(model_name=EMBEDDING_MODEL, dim=768)
    print(f"Embedding model: {EMBEDDING_MODEL}\n")

    log_dir = PARLOR_DIR / "session_logs"

    # ------------------------------------------------------------------
    # Step 1: Parse and embed all naive session utterances (once)
    # ------------------------------------------------------------------
    print("--- Parsing and embedding naive session logs (one-time) ---\n")

    session_data = []  # list of (topic, utterances, embeddings)
    for filename, topic in NAIVE_SESSIONS.items():
        path = log_dir / filename
        if not path.exists():
            print(f"WARNING: {filename} not found, skipping.")
            continue

        utterances = parse_hat_utterances(path)
        texts = [u["text"] for u in utterances]
        embeddings = embed_texts(texts, embedder)

        print(f"  {topic}: {len(utterances)} utterances embedded")
        session_data.append((topic, utterances, embeddings))

    if not session_data:
        print("ERROR: No session data found.")
        sys.exit(1)

    print()

    # ------------------------------------------------------------------
    # Step 2: Sweep thresholds
    # ------------------------------------------------------------------
    sweep_results = []

    for threshold in thresholds:
        print(f"--- d_min = {threshold:.2f} ---")

        topic_results = []
        total_stored = 0
        total_candidates = 0

        for topic, utterances, embeddings in session_data:
            # Simulate dedup at this threshold
            stored_indices = simulate_embed_only_dedup(
                utterances, embeddings, threshold=threshold
            )

            # Count total candidates: each utterance is offered to 5 other hats
            n_candidates = len(utterances) * (len(HATS) - 1)
            n_stored = sum(len(v) for v in stored_indices.values())
            n_skipped = n_candidates - n_stored

            total_stored += n_stored
            total_candidates += n_candidates

            # Build per-hat embedding arrays
            hat_embeddings: dict[str, np.ndarray] = {}
            hat_sizes: dict[str, int] = {}
            for hat in HATS:
                indices = stored_indices.get(hat, [])
                hat_sizes[hat] = len(indices)
                if indices:
                    hat_embeddings[hat] = embeddings[indices]

            # Compute pairwise metrics
            pairwise = compute_pairwise_metrics(hat_embeddings)
            if pairwise:
                centroids = [p["centroid_distance"] for p in pairwise]
                hausdorffs = [p["hausdorff_distance"] for p in pairwise]
                overlaps = [p["nn_overlap"] for p in pairwise]
                topic_results.append({
                    "topic": topic,
                    "centroid_mean": float(np.mean(centroids)),
                    "hausdorff_mean": float(np.mean(hausdorffs)),
                    "overlap_mean": float(np.mean(overlaps)),
                    "hat_sizes": hat_sizes,
                    "n_stored": n_stored,
                    "n_skipped": n_skipped,
                    "n_candidates": n_candidates,
                })

        if not topic_results:
            continue

        # Aggregate across topics
        mean_store_size = float(np.mean([
            np.mean(list(tr["hat_sizes"].values()))
            for tr in topic_results
        ]))
        mean_skip_rate = float(
            (total_candidates - total_stored) / total_candidates
            if total_candidates > 0 else 0
        )
        mean_centroid = float(np.mean([tr["centroid_mean"] for tr in topic_results]))
        mean_hausdorff = float(np.mean([tr["hausdorff_mean"] for tr in topic_results]))
        mean_overlap = float(np.mean([tr["overlap_mean"] for tr in topic_results]))

        result = {
            "threshold": threshold,
            "mean_store_size_per_hat": mean_store_size,
            "mean_skip_rate": mean_skip_rate,
            "centroid_mean": mean_centroid,
            "hausdorff_mean": mean_hausdorff,
            "overlap_mean": mean_overlap,
            "per_topic": topic_results,
        }
        sweep_results.append(result)

        print(f"  Store/hat: {mean_store_size:.1f} | "
              f"Skip: {mean_skip_rate:.1%} | "
              f"Centroid: {mean_centroid:.3f} | "
              f"Hausdorff: {mean_hausdorff:.3f} | "
              f"Overlap: {mean_overlap:.3f}")

    print()

    # ------------------------------------------------------------------
    # Step 3: Load BEAR-guided reference
    # ------------------------------------------------------------------
    bear_ref = load_bear_reference()
    if bear_ref:
        print(f"BEAR-guided reference: "
              f"Centroid={bear_ref['centroid_mean']:.3f} | "
              f"Hausdorff={bear_ref['hausdorff_mean']:.3f} | "
              f"Overlap={bear_ref['overlap_mean']:.3f}\n")

    # ------------------------------------------------------------------
    # Step 4: Console summary table
    # ------------------------------------------------------------------
    print("=" * 70)
    print("  SUMMARY TABLE")
    print("=" * 70)
    print(f"\n  {'d_min':>6}  {'Store/hat':>10}  {'Skip%':>7}  "
          f"{'Centroid':>9}  {'Hausdorff':>10}  {'Overlap':>9}")
    print(f"  {'-'*6}  {'-'*10}  {'-'*7}  {'-'*9}  {'-'*10}  {'-'*9}")

    for r in sweep_results:
        marker = " ◀" if abs(r["threshold"] - 0.35) < 0.001 else ""
        print(f"  {r['threshold']:>6.2f}  {r['mean_store_size_per_hat']:>10.1f}  "
              f"{r['mean_skip_rate']:>7.1%}  {r['centroid_mean']:>9.3f}  "
              f"{r['hausdorff_mean']:>10.3f}  {r['overlap_mean']:>9.3f}{marker}")

    if bear_ref:
        print(f"\n  {'BEAR':>6}  {'(guided)':>10}  {'---':>7}  "
              f"{bear_ref['centroid_mean']:>9.3f}  "
              f"{bear_ref['hausdorff_mean']:>10.3f}  "
              f"{bear_ref['overlap_mean']:>9.3f}")

    # ------------------------------------------------------------------
    # Step 5: LaTeX table
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  LaTeX Table")
    print("=" * 70)

    print(r"""
\begin{table}[t]
\caption{Sensitivity of embed-only dedup to threshold $d_{\min}$.
As $d_{\min}$ increases, more items pass dedup (larger stores, lower skip rate)
and inter-hat differentiation decreases (lower centroid distance, higher overlap).
The default $d_{\min} = 0.35$ (bold) balances store compactness with content retention.
BEAR-guided results (bottom row) include cognitive reframing, which produces
substantially higher differentiation than dedup alone at any threshold.}
\label{tab:dmin-sensitivity}
\centering
\begin{tabular}{@{}rrrrrr@{}}
\toprule
$d_{\min}$ & Store/hat & Skip\% & Centroid & Hausdorff & Overlap \\
\midrule""")

    for r in sweep_results:
        if abs(r["threshold"] - 0.35) < 0.001:
            print(f"\\textbf{{{r['threshold']:.2f}}} & "
                  f"\\textbf{{{r['mean_store_size_per_hat']:.1f}}} & "
                  f"\\textbf{{{r['mean_skip_rate']:.1%}}} & "
                  f"\\textbf{{{r['centroid_mean']:.3f}}} & "
                  f"\\textbf{{{r['hausdorff_mean']:.3f}}} & "
                  f"\\textbf{{{r['overlap_mean']:.3f}}} \\\\")
        else:
            print(f"{r['threshold']:.2f} & "
                  f"{r['mean_store_size_per_hat']:.1f} & "
                  f"{r['mean_skip_rate']:.1%} & "
                  f"{r['centroid_mean']:.3f} & "
                  f"{r['hausdorff_mean']:.3f} & "
                  f"{r['overlap_mean']:.3f} \\\\")

    if bear_ref:
        print(r"\midrule")
        print(f"BEAR & --- & --- & "
              f"{bear_ref['centroid_mean']:.3f} & "
              f"{bear_ref['hausdorff_mean']:.3f} & "
              f"{bear_ref['overlap_mean']:.3f} \\\\")

    print(r"""\bottomrule
\end{tabular}
\end{table}""")

    # ------------------------------------------------------------------
    # Step 6: Save outputs
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)

    # CSV
    csv_path = output_dir / "dmin_sensitivity.csv"
    with open(csv_path, "w", newline="") as f:
        f.write(f"# d_min sensitivity sweep — {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"# Embedding model: {EMBEDDING_MODEL}\n")
        f.write(f"# Sessions: {', '.join(NAIVE_SESSIONS.keys())}\n")
        writer = csv.writer(f)
        writer.writerow([
            "threshold", "mean_store_size_per_hat", "mean_skip_rate",
            "centroid_mean", "hausdorff_mean", "overlap_mean",
        ])
        for r in sweep_results:
            writer.writerow([
                f"{r['threshold']:.2f}",
                f"{r['mean_store_size_per_hat']:.2f}",
                f"{r['mean_skip_rate']:.4f}",
                f"{r['centroid_mean']:.4f}",
                f"{r['hausdorff_mean']:.4f}",
                f"{r['overlap_mean']:.4f}",
            ])
    print(f"\n  CSV saved to: {csv_path}")

    # JSON
    json_path = output_dir / "dmin_sensitivity.json"
    json_output = {
        "metadata": {
            "eval": "dmin_sensitivity",
            "version": SCRIPT_VERSION,
            "description": "d_min threshold sensitivity sweep for embed-only dedup",
            "embedding_model": EMBEDDING_MODEL,
            "thresholds": thresholds,
            "session_logs": list(NAIVE_SESSIONS.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "sweep_results": [
            {k: v for k, v in r.items() if k != "per_topic"}
            for r in sweep_results
        ],
        "bear_reference": bear_ref,
    }
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=float)
    print(f"  JSON saved to: {json_path}")

    # Figure
    if plot:
        _generate_figure(sweep_results, bear_ref, output_dir)

    print("\nDone.")
    return sweep_results


# ---------------------------------------------------------------------------
# Figure generation
# ---------------------------------------------------------------------------

def _generate_figure(
    sweep_results: list[dict],
    bear_ref: dict | None,
    output_dir: Path,
) -> None:
    """Generate dual-axis sensitivity figure."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  WARNING: matplotlib not available, skipping figure.")
        return

    thresholds = [r["threshold"] for r in sweep_results]
    store_sizes = [r["mean_store_size_per_hat"] for r in sweep_results]
    centroids = [r["centroid_mean"] for r in sweep_results]
    overlaps = [r["overlap_mean"] for r in sweep_results]

    fig, ax1 = plt.subplots(figsize=(7, 4.5))

    # Left axis: store size
    color1 = "#2196F3"
    ax1.set_xlabel(r"Deduplication threshold $d_{\min}$", fontsize=12)
    ax1.set_ylabel("Mean store size per hat", color=color1, fontsize=12)
    line1 = ax1.plot(thresholds, store_sizes, "o-", color=color1, linewidth=2,
                     markersize=7, label="Store size / hat")
    ax1.tick_params(axis="y", labelcolor=color1)

    # Right axis: centroid distance
    ax2 = ax1.twinx()
    color2 = "#E91E63"
    color3 = "#4CAF50"
    ax2.set_ylabel("Inter-hat metric", fontsize=12)
    line2 = ax2.plot(thresholds, centroids, "s--", color=color2, linewidth=2,
                     markersize=7, label="Centroid distance")
    line3 = ax2.plot(thresholds, overlaps, "^--", color=color3, linewidth=2,
                     markersize=7, label="NN overlap")

    # BEAR-guided reference lines
    if bear_ref:
        ax2.axhline(y=bear_ref["centroid_mean"], color=color2, linestyle=":",
                    alpha=0.5, linewidth=1)
        ax2.text(thresholds[-1] + 0.005, bear_ref["centroid_mean"],
                "BEAR", color=color2, fontsize=9, va="center", alpha=0.7)
        ax2.axhline(y=bear_ref["overlap_mean"], color=color3, linestyle=":",
                    alpha=0.5, linewidth=1)
        ax2.text(thresholds[-1] + 0.005, bear_ref["overlap_mean"],
                "BEAR", color=color3, fontsize=9, va="center", alpha=0.7)

    # Mark d_min = 0.35
    ax1.axvline(x=0.35, color="gray", linestyle="--", alpha=0.5, linewidth=1)
    ax1.text(0.35, ax1.get_ylim()[1] * 0.95, r"$d_{\min}=0.35$",
             ha="center", va="top", fontsize=10, color="gray",
             bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                       edgecolor="gray", alpha=0.8))

    # Combined legend
    lines = line1 + line2 + line3
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="center right", fontsize=9)

    ax1.set_xticks(thresholds)
    ax1.grid(axis="x", alpha=0.3)
    fig.tight_layout()

    pdf_path = output_dir / "dmin_sensitivity.pdf"
    png_path = output_dir / "dmin_sensitivity.png"
    fig.savefig(pdf_path, dpi=300, bbox_inches="tight")
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Figure saved to: {pdf_path}")
    print(f"  PNG saved to: {png_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="d_min sensitivity sweep for embed-only dedup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--thresholds", nargs="+", type=float, default=DEFAULT_THRESHOLDS,
        help=f"d_min values to sweep (default: {DEFAULT_THRESHOLDS}).",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=eval_dir / "results",
        help="Output directory for CSV/JSON/PDF (default: paper/evaluation/results/).",
    )
    parser.add_argument(
        "--no-plot", action="store_true",
        help="Skip matplotlib figure generation.",
    )
    args = parser.parse_args()

    run_sweep(
        thresholds=sorted(args.thresholds),
        output_dir=args.output_dir,
        plot=not args.no_plot,
    )


if __name__ == "__main__":
    main()
