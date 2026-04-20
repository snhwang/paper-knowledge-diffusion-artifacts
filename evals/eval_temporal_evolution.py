"""Temporal evolution of knowledge stores across brainstorming sessions.

This script analyzes how per-hat knowledge stores grow turn-by-turn during
BEAR-guided and naive brainstorming sessions, producing growth curves and
cumulative metrics that show the dynamics of the cognitive filtering mechanism.

Motivation:
  The paper's main evaluation tables report final-state snapshots. Reviewers
  may ask whether the filtering effect is stable across the session or if it
  all happens early/late. This analysis shows how stores evolve over time.

Methodology:
  For each of the 6 session logs (3 BEAR-guided, 3 naive across DMG, Stroke,
  MS topics), we parse the markdown turn-by-turn, tracking:

    1. **Cumulative store size per hat** — number of diffusion items stored
       by each hat up to each turn.
    2. **Cumulative skip rate** — fraction of diffusion candidates skipped
       (BEAR-guided only; naive sessions skip nothing).
    3. **Running inter-hat centroid distance** — pairwise centroid distance
       between hat stores, computed at each turn where >= 2 hats have >= 2
       items each. This shows how differentiation builds over time.

  Diffusion events are logged in the session markdown as blockquotes between
  turn headers, formatted as:
    > *[Diffusion HH:MM:SS]* RecvHat ← SrcHat: **stored** — content text
    > *[Diffusion HH:MM:SS]* RecvHat ← SrcHat: **skipped** (dist=X.XX)

  We associate each diffusion event with the turn that precedes it (i.e.,
  the turn whose response triggered the diffusion batch).

Data sources:
  Uses the same 6 session logs as eval_interhat_differentiation.py, identified
  by the shared SESSION_MAP.

Outputs:
  - Console: per-session growth summary
  - CSV: results/temporal_evolution.csv (one row per turn per session)
  - JSON: results/temporal_evolution.json (includes metadata)
  - PDF/PNG figure: results/temporal_evolution.pdf — multi-panel figure
    showing store growth curves (BEAR vs naive) and inter-hat distance over turns

Usage:
    python paper/evaluation/eval_temporal_evolution.py

    # Skip figure generation
    python paper/evaluation/eval_temporal_evolution.py --no-plot

    # Custom output directory
    python paper/evaluation/eval_temporal_evolution.py --output-dir /tmp/results
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------

project_root = Path(__file__).resolve().parents[1]
eval_dir = Path(__file__).resolve().parent
parlor_dir = project_root / "bear_parlor"
sys.path.insert(0, str(project_root))

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
HATS = ["White", "Red", "Black", "Yellow", "Green", "Blue"]
SCRIPT_VERSION = "1.0.0"

# Same session map as eval_interhat_differentiation.py
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
# Parsing: extract turn-by-turn diffusion events
# ---------------------------------------------------------------------------

_TURN_HEADER_RE = re.compile(
    r"^### Turn (\d+)\s*—\s*(\w[\w-]*)"
    r"(?:\s*→\s*[\w-]+)?"
    r"\s+<sub>[\d:]+</sub>",
    re.MULTILINE,
)

_DIFFUSION_RE = re.compile(
    r">\s*\*\[Diffusion ([\d:]+)\]\*\s+(\S+)\s+←\s+(\S+):\s+"
    r"\*\*(\w+)\*\*"
    r"(?:\s*\(dist=[\d.]+\))?"
    r"(?:\s*—\s*(.*))?"
)


def parse_temporal_events(log_path: Path) -> list[dict]:
    """Parse session log into a chronological list of diffusion events
    associated with the turn that triggered them.

    Returns list of dicts:
      {turn: int, receiving_hat: str, source_hat: str,
       action: 'stored'|'skipped', content: str|None}
    """
    text = log_path.read_text(encoding="utf-8")
    headers = list(_TURN_HEADER_RE.finditer(text))
    events = []

    for i, header in enumerate(headers):
        turn_num = int(header.group(1))
        # The block between this turn header and the next
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        for line in block.splitlines():
            m = _DIFFUSION_RE.match(line)
            if m:
                events.append({
                    "turn": turn_num,
                    "receiving_hat": m.group(2),
                    "source_hat": m.group(3),
                    "action": m.group(4),  # "stored" or "skipped"
                    "content": (m.group(5) or "").strip(),
                })

    return events


# ---------------------------------------------------------------------------
# Temporal analysis
# ---------------------------------------------------------------------------

def compute_temporal_metrics(
    events: list[dict],
    embedder,
) -> list[dict]:
    """Compute cumulative metrics at each turn that has diffusion events.

    Returns list of per-turn snapshots:
      {turn, cumulative_stored, cumulative_skipped, skip_rate,
       per_hat_sizes: {hat: count}, centroid_distance: float|None}
    """
    # Track cumulative state
    hat_contents: dict[str, list[str]] = defaultdict(list)
    hat_embeddings: dict[str, list[np.ndarray]] = defaultdict(list)
    total_stored = 0
    total_skipped = 0

    # Group events by turn
    turns_with_events: dict[int, list[dict]] = defaultdict(list)
    for ev in events:
        turns_with_events[ev["turn"]].append(ev)

    snapshots = []

    for turn_num in sorted(turns_with_events.keys()):
        turn_events = turns_with_events[turn_num]

        # Process events for this turn
        new_stored_texts = []
        new_stored_hats = []

        for ev in turn_events:
            if ev["action"] == "stored" and ev["content"]:
                hat_contents[ev["receiving_hat"]].append(ev["content"])
                new_stored_texts.append(ev["content"])
                new_stored_hats.append(ev["receiving_hat"])
                total_stored += 1
            elif ev["action"] == "skipped":
                total_skipped += 1

        # Embed new stored texts
        if new_stored_texts:
            from eval_embed_only_baseline import embed_texts
            new_embs = embed_texts(new_stored_texts, embedder)
            for idx, hat in enumerate(new_stored_hats):
                hat_embeddings[hat].append(new_embs[idx])

        # Compute per-hat sizes
        per_hat_sizes = {hat: len(hat_contents[hat]) for hat in HATS}
        total_items = sum(per_hat_sizes.values())

        # Compute skip rate
        total_candidates = total_stored + total_skipped
        skip_rate = total_skipped / total_candidates if total_candidates > 0 else 0.0

        # Compute inter-hat centroid distance (if enough data)
        centroid_distance = None
        hats_with_data = [
            h for h in HATS
            if h in hat_embeddings and len(hat_embeddings[h]) >= 2
        ]
        if len(hats_with_data) >= 2:
            pairwise_dists = []
            for ha, hb in combinations(hats_with_data, 2):
                emb_a = np.array(hat_embeddings[ha])
                emb_b = np.array(hat_embeddings[hb])
                centroid_a = np.mean(emb_a, axis=0)
                centroid_b = np.mean(emb_b, axis=0)
                dot = np.dot(centroid_a, centroid_b)
                norm = np.linalg.norm(centroid_a) * np.linalg.norm(centroid_b)
                dist = 1.0 - dot / norm if norm > 0 else 1.0
                pairwise_dists.append(dist)
            centroid_distance = float(np.mean(pairwise_dists))

        snapshots.append({
            "turn": turn_num,
            "cumulative_stored": total_stored,
            "cumulative_skipped": total_skipped,
            "skip_rate": skip_rate,
            "total_items": total_items,
            "per_hat_sizes": per_hat_sizes,
            "centroid_distance": centroid_distance,
        })

    return snapshots


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def run_evaluation(
    output_dir: Path,
    plot: bool = True,
) -> dict:
    """Run temporal evolution analysis on all 6 sessions."""
    from bear.retriever import Embedder

    print("=" * 70)
    print("  Temporal Store Evolution Analysis")
    print("=" * 70)

    embedder = Embedder(model_name=EMBEDDING_MODEL, dim=768)
    print(f"Embedding model: {EMBEDDING_MODEL}\n")

    log_dir = parlor_dir / "session_logs"
    all_results = {}

    for filename, (topic, condition) in SESSION_MAP.items():
        path = log_dir / filename
        if not path.exists():
            print(f"WARNING: {filename} not found, skipping.")
            continue

        print(f"--- {topic} ({condition}) : {filename} ---")

        events = parse_temporal_events(path)
        if not events:
            print("  No diffusion events found.\n")
            continue

        stored_count = sum(1 for e in events if e["action"] == "stored")
        skipped_count = sum(1 for e in events if e["action"] == "skipped")
        print(f"  Events: {len(events)} total "
              f"({stored_count} stored, {skipped_count} skipped)")

        snapshots = compute_temporal_metrics(events, embedder)

        if snapshots:
            final = snapshots[-1]
            print(f"  Final state: {final['total_items']} items across hats, "
                  f"skip rate {final['skip_rate']:.1%}")
            if final["centroid_distance"] is not None:
                print(f"  Final centroid distance: {final['centroid_distance']:.3f}")
        print()

        key = f"{topic}_{condition.replace('-', '_')}"
        all_results[key] = {
            "topic": topic,
            "condition": condition,
            "filename": filename,
            "snapshots": snapshots,
        }

    if not all_results:
        print("ERROR: No results computed.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    for key, data in sorted(all_results.items()):
        snaps = data["snapshots"]
        if not snaps:
            continue
        final = snaps[-1]
        turns_with_diffusion = len(snaps)
        print(f"\n  {data['topic']} ({data['condition']}):")
        print(f"    Diffusion turns: {turns_with_diffusion}")
        print(f"    Final items: {final['total_items']}")
        print(f"    Final skip rate: {final['skip_rate']:.1%}")
        if final["centroid_distance"] is not None:
            print(f"    Final centroid dist: {final['centroid_distance']:.3f}")

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)

    # CSV — one row per turn per session
    csv_path = output_dir / "temporal_evolution.csv"
    with open(csv_path, "w", newline="") as f:
        f.write(f"# Temporal store evolution — "
                f"{datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"# Embedding model: {EMBEDDING_MODEL}\n")
        f.write(f"# Sessions: {', '.join(SESSION_MAP.keys())}\n")
        writer = csv.writer(f)
        writer.writerow([
            "topic", "condition", "turn", "cumulative_stored",
            "cumulative_skipped", "skip_rate", "total_items",
            "centroid_distance",
        ] + [f"size_{hat}" for hat in HATS])

        for data in all_results.values():
            for snap in data["snapshots"]:
                writer.writerow([
                    data["topic"],
                    data["condition"],
                    snap["turn"],
                    snap["cumulative_stored"],
                    snap["cumulative_skipped"],
                    f"{snap['skip_rate']:.4f}",
                    snap["total_items"],
                    f"{snap['centroid_distance']:.4f}"
                    if snap["centroid_distance"] is not None else "",
                ] + [snap["per_hat_sizes"].get(hat, 0) for hat in HATS])

    print(f"\n  CSV saved to: {csv_path}")

    # JSON
    json_path = output_dir / "temporal_evolution.json"
    json_output = {
        "metadata": {
            "eval": "temporal_evolution",
            "version": SCRIPT_VERSION,
            "description": "Turn-by-turn store growth and inter-hat "
                           "differentiation evolution",
            "embedding_model": EMBEDDING_MODEL,
            "session_logs": list(SESSION_MAP.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "sessions": {
            key: {
                "topic": data["topic"],
                "condition": data["condition"],
                "filename": data["filename"],
                "n_snapshots": len(data["snapshots"]),
                "final_items": data["snapshots"][-1]["total_items"]
                if data["snapshots"] else 0,
                "final_skip_rate": data["snapshots"][-1]["skip_rate"]
                if data["snapshots"] else 0,
                "final_centroid_distance":
                    data["snapshots"][-1]["centroid_distance"]
                    if data["snapshots"] else None,
            }
            for key, data in all_results.items()
        },
    }
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=float)
    print(f"  JSON saved to: {json_path}")

    # Figure
    if plot:
        _generate_figure(all_results, output_dir)

    print("\nDone.")
    return all_results


# ---------------------------------------------------------------------------
# Figure generation
# ---------------------------------------------------------------------------

def _generate_figure(
    all_results: dict,
    output_dir: Path,
) -> None:
    """Generate multi-panel temporal evolution figure."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  WARNING: matplotlib not available, skipping figure.")
        return

    topics = ["DMG", "Stroke", "MS", "Alzheimers", "Epilepsy"]
    topic_labels_display = ["DMG", "Stroke", "MS", "Alzheimer's", "Epilepsy"]
    fig, axes = plt.subplots(2, 5, figsize=(18, 7))

    bear_color = "#2196F3"
    naive_color = "#E91E63"

    for col, (topic, display_label) in enumerate(zip(topics, topic_labels_display)):
        ax_size = axes[0, col]
        ax_dist = axes[1, col]

        for condition, color, style in [
            ("BEAR-guided", bear_color, "-"),
            ("Naive", naive_color, "--"),
        ]:
            key = f"{topic}_{condition.replace('-', '_')}"
            if key not in all_results:
                continue

            snaps = all_results[key]["snapshots"]
            if not snaps:
                continue

            turns = [s["turn"] for s in snaps]
            total_items = [s["total_items"] for s in snaps]
            centroids = [s["centroid_distance"] for s in snaps]

            ax_size.plot(turns, total_items, style, color=color,
                        linewidth=2, markersize=4, marker="o",
                        label=condition)

            # Filter out None centroid values
            valid_turns = [t for t, c in zip(turns, centroids) if c is not None]
            valid_centroids = [c for c in centroids if c is not None]
            if valid_centroids:
                ax_dist.plot(valid_turns, valid_centroids, style, color=color,
                            linewidth=2, markersize=4, marker="o",
                            label=condition)

        ax_size.set_title(display_label, fontsize=12, fontweight="bold")
        ax_size.set_ylabel("Cumulative items\n(all hats)" if col == 0 else "")
        ax_size.grid(alpha=0.3)
        if col == 0:
            ax_size.legend(fontsize=9)

        ax_dist.set_xlabel("Turn")
        ax_dist.set_ylabel("Inter-hat centroid\ndistance"
                          if col == 0 else "")
        ax_dist.grid(alpha=0.3)
        if col == 0:
            ax_dist.legend(fontsize=9)

    fig.suptitle("Temporal Evolution of Knowledge Stores",
                fontsize=13, fontweight="bold")
    fig.tight_layout()

    pdf_path = output_dir / "temporal_evolution.pdf"
    png_path = output_dir / "temporal_evolution.png"
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
        description="Temporal evolution of knowledge stores.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=eval_dir / "results",
        help="Output directory for CSV/JSON/PDF "
             "(default: paper/evaluation/results/).",
    )
    parser.add_argument(
        "--no-plot", action="store_true",
        help="Skip matplotlib figure generation.",
    )
    args = parser.parse_args()

    run_evaluation(
        output_dir=args.output_dir,
        plot=not args.no_plot,
    )


if __name__ == "__main__":
    main()
