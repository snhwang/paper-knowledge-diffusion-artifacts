"""Evaluate role adherence of hat responses against their instruction anchors.

Each hat has explicit behavioral instructions that define its cognitive mode.
This script measures how closely each hat's actual dialogue responses align
with its own role instructions vs. other hats' instructions, using embedding
cosine similarity.

Metrics:
  - Self-alignment: cosine similarity of response to own role anchor centroid
  - Cross-alignment: cosine similarity to other hats' role anchor centroids
  - Role discrimination ratio: self-alignment / mean(cross-alignments)
  - Inter-hat response Hausdorff distance: response-level differentiation
  - Topic drift: per-turn cosine similarity to original topic
  - Blue Hat synthesis: coverage of all hats in final summary

Data source: session log markdown files + hat instruction YAML files.

Usage:
    python eval_role_adherence.py
    python eval_role_adherence.py --logs session_logs/bear1.md session_logs/naive1.md
    python eval_role_adherence.py --semantic   # use real embeddings (default)
    python eval_role_adherence.py --no-chart   # skip chart generation
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import yaml

# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------

project_root = Path(__file__).resolve().parents[1]
parlor_dir = project_root / "bear_parlor"
sys.path.insert(0, str(project_root))

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
HATS = ["White", "Red", "Black", "Yellow", "Green", "Blue"]
HAT_YAML = {
    "White": "white_hat.yaml",
    "Red": "red_hat.yaml",
    "Black": "black_hat.yaml",
    "Yellow": "yellow_hat.yaml",
    "Green": "green_hat.yaml",
    "Blue": "blue_hat.yaml",
}
HAT_INSTRUCTION_DIR = parlor_dir / "instructions" / "hats"
MIN_RESPONSE_WORDS = 10  # skip very short responses

# ---------------------------------------------------------------------------
# Session log mapping (same as eval_interhat_differentiation.py)
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
# Role anchor loading
# ---------------------------------------------------------------------------

def load_role_anchors() -> dict[str, list[str]]:
    """Load instruction texts for each hat from YAML files.

    Returns dict mapping hat name -> list of content strings (5 per hat).
    """
    anchors: dict[str, list[str]] = {}
    for hat, filename in HAT_YAML.items():
        path = HAT_INSTRUCTION_DIR / filename
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        texts = []
        for instr in data.get("instructions", []):
            content = instr.get("content", "").strip()
            if content:
                texts.append(content)
        anchors[hat] = texts
    return anchors


# ---------------------------------------------------------------------------
# Session log response parsing
# ---------------------------------------------------------------------------

_TURN_HEADER_RE = re.compile(
    r"^### Turn (\d+)\s*—\s*(\w[\w-]*)"
    r"(?:\s*→\s*[\w-]+)?"
    r"\s+<sub>[\d:]+</sub>",
    re.MULTILINE,
)


def parse_responses(log_path: Path) -> tuple[str, list[dict]]:
    """Parse per-turn response text and speaker from a session log.

    Returns (topic_text, list of {turn, speaker, text}).
    topic_text is the first User turn's text.
    """
    text = log_path.read_text(encoding="utf-8")

    # Find all turn headers and their positions
    headers = list(_TURN_HEADER_RE.finditer(text))
    if not headers:
        return "", []

    topic_text = ""
    responses = []

    for i, match in enumerate(headers):
        turn_num = int(match.group(1))
        speaker = match.group(2)

        # Extract text between this header and the next header (or end of file)
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        # Remove <details>...</details> blocks
        block = re.sub(r"<details>.*?</details>", "", block, flags=re.DOTALL)
        # Remove Knowledge RAG lines
        block = re.sub(r"\*\*Knowledge RAG\*\*.*?(?=\n###|\n---|\Z)",
                       "", block, flags=re.DOTALL)
        # Remove diffusion event lines
        block = re.sub(r">\s*\*\[Diffusion.*", "", block)
        # Remove horizontal rules
        block = re.sub(r"^---\s*$", "", block, flags=re.MULTILINE)
        # Clean up
        response_text = block.strip()

        if not response_text:
            continue

        # Map speaker names: "Blue" from "Blue" or "blue-hat" style
        hat_name = speaker.replace("-hat", "").capitalize()

        if hat_name == "User":
            if turn_num == 1:
                topic_text = response_text
            continue

        if hat_name not in HATS:
            continue

        responses.append({
            "turn": turn_num,
            "speaker": hat_name,
            "text": response_text,
        })

    return topic_text, responses


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str], embedder) -> np.ndarray:
    """Embed texts; returns shape (N, dim)."""
    if not texts:
        return np.array([])
    return embedder.embed(texts, is_query=False)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance (1 - similarity)."""
    return 1.0 - cosine_similarity(a, b)


def hausdorff_distance(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
    """Symmetric Hausdorff distance using cosine metric."""
    if len(emb_a) == 0 or len(emb_b) == 0:
        return 1.0

    def directed(source, target):
        max_dist = 0.0
        for s in source:
            dists = [cosine_distance(s, t) for t in target]
            max_dist = max(max_dist, min(dists))
        return max_dist

    return max(directed(emb_a, emb_b), directed(emb_b, emb_a))


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def compute_per_response_metrics(
    response_emb: np.ndarray,
    own_hat: str,
    anchor_centroids: dict[str, np.ndarray],
) -> dict:
    """Compute self-alignment, cross-alignments, and discrimination ratio."""
    self_align = cosine_similarity(response_emb, anchor_centroids[own_hat])

    cross_aligns = {}
    for hat, centroid in anchor_centroids.items():
        if hat != own_hat:
            cross_aligns[hat] = cosine_similarity(response_emb, centroid)

    mean_cross = np.mean(list(cross_aligns.values())) if cross_aligns else 0.0
    ratio = self_align / mean_cross if mean_cross > 0 else float("inf")

    return {
        "self_alignment": float(self_align),
        "cross_alignments": {k: float(v) for k, v in cross_aligns.items()},
        "mean_cross_alignment": float(mean_cross),
        "discrimination_ratio": float(ratio),
    }


def compute_blue_synthesis(
    blue_last_emb: np.ndarray,
    hat_response_embs: dict[str, np.ndarray],
    topic_emb: np.ndarray,
) -> dict:
    """Assess Blue Hat's final response as synthesis.

    Measures coverage of each hat's contributions and topic fidelity.
    """
    coverage = {}
    for hat, embs in hat_response_embs.items():
        if hat == "Blue" or len(embs) == 0:
            continue
        centroid = np.mean(embs, axis=0)
        coverage[hat] = float(cosine_similarity(blue_last_emb, centroid))

    topic_fidelity = float(cosine_similarity(blue_last_emb, topic_emb))

    return {
        "per_hat_coverage": coverage,
        "mean_coverage": float(np.mean(list(coverage.values()))) if coverage else 0.0,
        "topic_fidelity": topic_fidelity,
    }


# ---------------------------------------------------------------------------
# Session-level computation
# ---------------------------------------------------------------------------

def compute_session_metrics(
    topic_text: str,
    responses: list[dict],
    anchor_centroids: dict[str, np.ndarray],
    embedder,
) -> dict:
    """Compute all metrics for a single session."""

    # Filter short responses
    valid = [r for r in responses if len(r["text"].split()) >= MIN_RESPONSE_WORDS]
    if not valid:
        return {}

    # Embed all response texts
    all_texts = [r["text"] for r in valid]
    all_embs = embed_texts(all_texts, embedder)

    # Embed topic
    topic_emb = embed_texts([topic_text], embedder)[0] if topic_text else None

    # Group embeddings by hat
    hat_embs: dict[str, list[np.ndarray]] = defaultdict(list)
    hat_indices: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(valid):
        hat_embs[r["speaker"]].append(all_embs[i])
        hat_indices[r["speaker"]].append(i)

    # Per-response metrics
    per_turn = []
    for i, r in enumerate(valid):
        metrics = compute_per_response_metrics(
            all_embs[i], r["speaker"], anchor_centroids
        )
        metrics["turn"] = r["turn"]
        metrics["speaker"] = r["speaker"]
        if topic_emb is not None:
            metrics["topic_similarity"] = float(
                cosine_similarity(all_embs[i], topic_emb)
            )
        per_turn.append(metrics)

    # Per-hat aggregates
    per_hat = {}
    for hat in HATS:
        hat_turns = [t for t in per_turn if t["speaker"] == hat]
        if not hat_turns:
            continue
        # Response length in words
        hat_responses = [r for r in valid if r["speaker"] == hat]
        word_counts = [len(r["text"].split()) for r in hat_responses]
        per_hat[hat] = {
            "mean_self_alignment": float(
                np.mean([t["self_alignment"] for t in hat_turns])
            ),
            "mean_discrimination_ratio": float(
                np.mean([t["discrimination_ratio"] for t in hat_turns])
            ),
            "n_turns": len(hat_turns),
            "response_length_mean": float(np.mean(word_counts)),
            "response_length_std": float(np.std(word_counts)),
            "response_length_min": int(np.min(word_counts)),
            "response_length_max": int(np.max(word_counts)),
        }
        if topic_emb is not None:
            per_hat[hat]["mean_topic_similarity"] = float(
                np.mean([t["topic_similarity"] for t in hat_turns])
            )

    # Session-level aggregates
    all_self = [t["self_alignment"] for t in per_turn]
    all_ratios = [t["discrimination_ratio"] for t in per_turn]

    # Inter-hat response Hausdorff
    hat_emb_arrays = {
        h: np.array(embs) for h, embs in hat_embs.items() if embs
    }
    interhat_hausdorff = []
    for ha, hb in combinations(HATS, 2):
        if ha in hat_emb_arrays and hb in hat_emb_arrays:
            hd = hausdorff_distance(hat_emb_arrays[ha], hat_emb_arrays[hb])
            interhat_hausdorff.append({
                "hat_a": ha, "hat_b": hb, "hausdorff": float(hd)
            })

    # Topic drift time series
    topic_drift = []
    if topic_emb is not None:
        for t in per_turn:
            topic_drift.append({
                "turn": t["turn"],
                "speaker": t["speaker"],
                "topic_similarity": t.get("topic_similarity", 0.0),
            })

    # Blue synthesis (last Blue response)
    blue_synthesis = {}
    blue_turns = [i for i, r in enumerate(valid) if r["speaker"] == "Blue"]
    if blue_turns and topic_emb is not None:
        blue_last_idx = blue_turns[-1]
        blue_synthesis = compute_blue_synthesis(
            all_embs[blue_last_idx], hat_emb_arrays, topic_emb
        )

    return {
        "per_hat": per_hat,
        "overall_self_alignment": float(np.mean(all_self)),
        "overall_discrimination_ratio": float(np.mean(all_ratios)),
        "interhat_response_hausdorff": interhat_hausdorff,
        "interhat_hausdorff_mean": float(
            np.mean([h["hausdorff"] for h in interhat_hausdorff])
        ) if interhat_hausdorff else 0.0,
        "topic_drift": topic_drift,
        "blue_synthesis": blue_synthesis,
        "n_responses": len(valid),
    }


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def generate_chart(session_results: list[dict], output_path: Path):
    """Generate multi-panel role adherence chart."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(14, 8))
    gs = fig.add_gridspec(2, 3, hspace=0.35, wspace=0.35)

    # Panel A: Discrimination ratio per hat (BEAR vs Naive)
    ax_a = fig.add_subplot(gs[0, 0:2])

    bear_data = defaultdict(list)
    naive_data = defaultdict(list)
    for s in session_results:
        bucket = bear_data if s["condition"] == "BEAR-guided" else naive_data
        for hat, metrics in s["metrics"]["per_hat"].items():
            bucket[hat].append(metrics["mean_discrimination_ratio"])

    x = np.arange(len(HATS))
    width = 0.35
    bear_means = [np.mean(bear_data[h]) if bear_data[h] else 0 for h in HATS]
    naive_means = [np.mean(naive_data[h]) if naive_data[h] else 0 for h in HATS]

    bars1 = ax_a.bar(x - width / 2, bear_means, width, label="BEAR-guided",
                     color="#2196F3", alpha=0.8)
    bars2 = ax_a.bar(x + width / 2, naive_means, width, label="Naive",
                     color="#FF9800", alpha=0.8)
    ax_a.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5, label="Parity")
    ax_a.set_xticks(x)
    ax_a.set_xticklabels(HATS)
    ax_a.set_ylabel("Role Discrimination Ratio")
    ax_a.set_title("(a) Role Discrimination Ratio by Hat")
    ax_a.legend(fontsize=8)

    # Panel B: Self-alignment per hat
    ax_b = fig.add_subplot(gs[0, 2])

    bear_self = [np.mean([s["metrics"]["per_hat"].get(h, {}).get(
        "mean_self_alignment", 0) for s in session_results
        if s["condition"] == "BEAR-guided"]) for h in HATS]
    naive_self = [np.mean([s["metrics"]["per_hat"].get(h, {}).get(
        "mean_self_alignment", 0) for s in session_results
        if s["condition"] == "Naive"]) for h in HATS]

    ax_b.bar(x - width / 2, bear_self, width, color="#2196F3", alpha=0.8)
    ax_b.bar(x + width / 2, naive_self, width, color="#FF9800", alpha=0.8)
    ax_b.set_xticks(x)
    ax_b.set_xticklabels(HATS, rotation=45, ha="right")
    ax_b.set_ylabel("Cosine Similarity")
    ax_b.set_title("(b) Self-Alignment")

    # Panel C: Topic drift over turns (averaged across sessions)
    ax_c = fig.add_subplot(gs[1, 0:2])

    for condition, color, label in [
        ("BEAR-guided", "#2196F3", "BEAR-guided"),
        ("Naive", "#FF9800", "Naive"),
    ]:
        all_drift = []
        for s in session_results:
            if s["condition"] == condition and s["metrics"].get("topic_drift"):
                drift = s["metrics"]["topic_drift"]
                all_drift.append([d["topic_similarity"] for d in drift])
        if all_drift:
            # Pad to same length and average
            max_len = max(len(d) for d in all_drift)
            padded = np.full((len(all_drift), max_len), np.nan)
            for i, d in enumerate(all_drift):
                padded[i, : len(d)] = d
            means = np.nanmean(padded, axis=0)
            ax_c.plot(range(1, len(means) + 1), means, color=color,
                      label=label, alpha=0.8)

    ax_c.set_xlabel("Response #")
    ax_c.set_ylabel("Cosine Similarity to Topic")
    ax_c.set_title("(c) Topic Drift Over Session")
    ax_c.legend(fontsize=8)

    # Panel D: Blue synthesis coverage
    ax_d = fig.add_subplot(gs[1, 2])

    other_hats = [h for h in HATS if h != "Blue"]
    bear_cov = []
    naive_cov = []
    for s in session_results:
        syn = s["metrics"].get("blue_synthesis", {})
        cov = syn.get("per_hat_coverage", {})
        bucket = bear_cov if s["condition"] == "BEAR-guided" else naive_cov
        bucket.append([cov.get(h, 0) for h in other_hats])

    if bear_cov:
        bear_cov_mean = np.mean(bear_cov, axis=0)
        ax_d.bar(np.arange(len(other_hats)) - width / 2, bear_cov_mean,
                 width, color="#2196F3", alpha=0.8, label="BEAR")
    if naive_cov:
        naive_cov_mean = np.mean(naive_cov, axis=0)
        ax_d.bar(np.arange(len(other_hats)) + width / 2, naive_cov_mean,
                 width, color="#FF9800", alpha=0.8, label="Naive")
    ax_d.set_xticks(np.arange(len(other_hats)))
    ax_d.set_xticklabels(other_hats, rotation=45, ha="right")
    ax_d.set_ylabel("Cosine Similarity")
    ax_d.set_title("(d) Blue Synthesis Coverage")
    ax_d.legend(fontsize=8)

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved to: {output_path}")


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def run_evaluation(log_dir: Path | None = None, log_files: list[Path] | None = None,
                   no_chart: bool = False):
    """Run the role adherence evaluation."""
    from bear.retriever import Embedder

    print("=" * 70)
    print("  Role Adherence Evaluation")
    print("=" * 70)

    # Load role anchors
    print("\nLoading role anchor instructions...")
    anchor_texts = load_role_anchors()
    for hat, texts in anchor_texts.items():
        print(f"  {hat}: {len(texts)} instructions")

    # Initialize embedder
    print(f"\nEmbedding model: {EMBEDDING_MODEL}")
    embedder = Embedder(model_name=EMBEDDING_MODEL, dim=768)
    print("Embedder loaded.")

    # Embed role anchors -> centroids
    print("\nEmbedding role anchors...")
    anchor_embs: dict[str, np.ndarray] = {}
    anchor_centroids: dict[str, np.ndarray] = {}
    for hat, texts in anchor_texts.items():
        embs = embed_texts(texts, embedder)
        anchor_embs[hat] = embs
        anchor_centroids[hat] = np.mean(embs, axis=0)

    # Resolve session logs
    if log_files:
        paths = log_files
    else:
        log_dir = log_dir or (parlor_dir / "session_logs")
        paths = sorted(log_dir.glob("brainstorming-hats_*.md"))

    if not paths:
        print("ERROR: No session log files found.")
        sys.exit(1)

    # Process each session
    session_results = []

    for path in paths:
        filename = path.name
        info = SESSION_MAP.get(filename)
        if info is None:
            continue

        topic, condition = info
        print(f"\n--- {topic} ({condition}): {filename} ---")

        # Parse responses
        topic_text, responses = parse_responses(path)
        if not responses:
            print("  WARNING: No responses parsed, skipping.")
            continue

        print(f"  Topic: {topic_text[:80]}...")
        hat_counts = {h: sum(1 for r in responses if r["speaker"] == h) for h in HATS}
        hat_summary = ", ".join(f"{h}={c}" for h, c in hat_counts.items() if c > 0)
        print(f"  Responses: {len(responses)} (by hat: {hat_summary})")

        # Compute metrics
        metrics = compute_session_metrics(
            topic_text, responses, anchor_centroids, embedder
        )
        if not metrics:
            print("  WARNING: No valid responses after filtering.")
            continue

        result = {
            "topic": topic,
            "condition": condition,
            "filename": filename,
            "metrics": metrics,
        }
        session_results.append(result)

        # Print per-hat summary
        print(f"  Overall discrimination ratio: "
              f"{metrics['overall_discrimination_ratio']:.3f}")
        print(f"  Overall self-alignment: "
              f"{metrics['overall_self_alignment']:.3f}")
        for hat in HATS:
            if hat in metrics["per_hat"]:
                ph = metrics["per_hat"][hat]
                print(f"    {hat:8s}: self={ph['mean_self_alignment']:.3f}  "
                      f"ratio={ph['mean_discrimination_ratio']:.3f}  "
                      f"n={ph['n_turns']}")

    if not session_results:
        print("ERROR: No valid sessions to analyze.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    for condition in ["BEAR-guided", "Naive"]:
        cond_results = [s for s in session_results if s["condition"] == condition]
        if not cond_results:
            continue
        print(f"\n  {condition} (n={len(cond_results)} sessions):")
        all_ratios = [s["metrics"]["overall_discrimination_ratio"]
                      for s in cond_results]
        all_self = [s["metrics"]["overall_self_alignment"]
                    for s in cond_results]
        print(f"    Mean discrimination ratio: {np.mean(all_ratios):.3f}")
        print(f"    Mean self-alignment:       {np.mean(all_self):.3f}")

        # Per-hat means across sessions
        print(f"    Per-hat discrimination ratios:")
        for hat in HATS:
            vals = [s["metrics"]["per_hat"][hat]["mean_discrimination_ratio"]
                    for s in cond_results
                    if hat in s["metrics"]["per_hat"]]
            if vals:
                print(f"      {hat:8s}: {np.mean(vals):.3f}")

    # ------------------------------------------------------------------
    # LaTeX table
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  LaTeX Table")
    print("=" * 70)

    print(r"""
\begin{table}[t]
\caption{Role adherence: mean self-alignment (cosine similarity to own role
anchor) and role discrimination ratio (self-alignment / mean cross-alignment)
per hat, averaged across three biomedical topics. Higher values indicate
stronger role adherence. BEAR-guided sessions show [stronger/comparable]
role adherence compared to naive diffusion.}
\label{tab:role-adherence}
\centering
\begin{tabular}{@{}llcc@{}}
\toprule
Hat & Condition & Self-Alignment & Discrimination Ratio \\
\midrule""")

    for hat in HATS:
        for condition in ["BEAR-guided", "Naive"]:
            cond_results = [s for s in session_results
                            if s["condition"] == condition]
            self_vals = [s["metrics"]["per_hat"][hat]["mean_self_alignment"]
                         for s in cond_results
                         if hat in s["metrics"]["per_hat"]]
            ratio_vals = [s["metrics"]["per_hat"][hat]["mean_discrimination_ratio"]
                          for s in cond_results
                          if hat in s["metrics"]["per_hat"]]
            if self_vals and ratio_vals:
                label = "BEAR" if condition == "BEAR-guided" else "Naive"
                print(f"{hat:8s} & {label:5s} & {np.mean(self_vals):.3f} "
                      f"& {np.mean(ratio_vals):.3f} \\\\")
        if hat != HATS[-1]:
            print(r"\cmidrule(lr){1-4}")

    # Overall means
    print(r"\midrule")
    for condition in ["BEAR-guided", "Naive"]:
        cond_results = [s for s in session_results if s["condition"] == condition]
        if cond_results:
            mean_self = np.mean([s["metrics"]["overall_self_alignment"]
                                 for s in cond_results])
            mean_ratio = np.mean([s["metrics"]["overall_discrimination_ratio"]
                                  for s in cond_results])
            label = "BEAR" if condition == "BEAR-guided" else "Naive"
            bold = r"\textbf" if condition == "BEAR-guided" else ""
            if bold:
                print(f"\\textbf{{Mean}} & \\textbf{{{label}}} "
                      f"& \\textbf{{{mean_self:.3f}}} "
                      f"& \\textbf{{{mean_ratio:.3f}}} \\\\")
            else:
                print(f"\\textbf{{Mean}} & {label} "
                      f"& {mean_self:.3f} & {mean_ratio:.3f} \\\\")

    print(r"""\bottomrule
\end{tabular}
\end{table}""")

    # ------------------------------------------------------------------
    # JSON output
    # ------------------------------------------------------------------
    results_dir = project_root / "results"
    results_dir.mkdir(exist_ok=True)
    json_path = results_dir / "role_adherence.json"

    # Prepare JSON-safe output
    json_output = {
        "metadata": {
            "eval": "role_adherence",
            "description": "Hat role adherence against instruction anchors",
            "embedding_model": EMBEDDING_MODEL,
            "min_response_words": MIN_RESPONSE_WORDS,
        },
        "sessions": [],
        "summary": {},
    }

    for s in session_results:
        json_output["sessions"].append({
            "topic": s["topic"],
            "condition": s["condition"],
            "filename": s["filename"],
            "per_hat": s["metrics"]["per_hat"],
            "overall_self_alignment": s["metrics"]["overall_self_alignment"],
            "overall_discrimination_ratio": s["metrics"][
                "overall_discrimination_ratio"
            ],
            "interhat_hausdorff_mean": s["metrics"]["interhat_hausdorff_mean"],
            "blue_synthesis": s["metrics"].get("blue_synthesis", {}),
            "n_responses": s["metrics"]["n_responses"],
        })

    # Summary with CIs
    import random as _random
    _random.seed(42)

    def _bootstrap_ci(values, n_boot=10000, alpha=0.05):
        n = len(values)
        if n < 2:
            m = float(np.mean(values))
            return {"mean": m, "ci_low": m, "ci_high": m}
        means = sorted(
            sum(_random.choices(values, k=n)) / n for _ in range(n_boot)
        )
        return {
            "mean": float(np.mean(values)),
            "ci_low": means[int(n_boot * alpha / 2)],
            "ci_high": means[int(n_boot * (1 - alpha / 2))],
        }

    for condition in ["BEAR-guided", "Naive"]:
        cond = [s for s in session_results if s["condition"] == condition]
        if cond:
            key = "bear" if condition == "BEAR-guided" else "naive"
            sa_vals = [s["metrics"]["overall_self_alignment"] for s in cond]
            dr_vals = [s["metrics"]["overall_discrimination_ratio"]
                       for s in cond]
            hd_vals = [s["metrics"]["interhat_hausdorff_mean"] for s in cond]
            json_output["summary"][f"{key}_self_alignment"] = _bootstrap_ci(sa_vals)
            json_output["summary"][f"{key}_discrimination_ratio"] = _bootstrap_ci(dr_vals)
            json_output["summary"][f"{key}_interhat_hausdorff"] = _bootstrap_ci(hd_vals)

            # Per-hat response length summary across sessions
            hat_lengths = defaultdict(list)
            for s in cond:
                for hat, metrics in s["metrics"]["per_hat"].items():
                    hat_lengths[hat].append(metrics["response_length_mean"])
            json_output["summary"][f"{key}_response_length"] = {
                hat: _bootstrap_ci(vals) for hat, vals in hat_lengths.items()
            }

    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2)
    print(f"\n  JSON saved to: {json_path}")

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------
    if not no_chart:
        chart_path = project_root / "results" / "role_adherence.png"
        try:
            generate_chart(session_results, chart_path)
        except Exception as e:
            print(f"  WARNING: Chart generation failed: {e}")

    print("\nDone.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate role adherence of hat responses against "
                    "instruction anchors."
    )
    parser.add_argument(
        "--logs", nargs="+", type=Path,
        help="Session log .md files. Default: all in session_logs/.",
    )
    parser.add_argument(
        "--no-chart", action="store_true",
        help="Skip chart generation.",
    )
    args = parser.parse_args()
    run_evaluation(log_files=args.logs, no_chart=args.no_chart)


if __name__ == "__main__":
    main()
