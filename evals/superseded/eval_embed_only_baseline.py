"""Embed-only dedup baseline: cosine dedup without LLM cognitive reframing.

This script simulates a middle-ground diffusion condition between BEAR-guided
and naive diffusion:

  - **Naive**: store everything verbatim (no filtering, no dedup)
  - **Embed-only** (this baseline): apply cosine-distance dedup at d_min,
    but store items verbatim (no LLM reframing through cognitive lens)
  - **BEAR-guided**: apply cosine dedup + LLM reframing through hat's
    BEAR-retrieved cognitive instructions

By comparing all three conditions, we can attribute gains to:
  (a) deduplication alone (embed-only vs. naive), vs.
  (b) cognitive reframing (BEAR-guided vs. embed-only).

Methodology:
  We replay naive session logs, simulating what would have been stored
  if cosine dedup were applied to the verbatim utterances. For each
  utterance in the naive log (which stores everything), we check if it
  would pass the dedup threshold against previously accepted items.
  Items that pass are "stored"; items that fail are "skipped".

  We then compute the same inter-hat differentiation metrics as
  eval_interhat_differentiation.py on the resulting stores.

Outputs:
  - Console summary comparing all three conditions
  - LaTeX table fragment
  - JSON results in paper/evaluation/results/embed_only_baseline.json
  - CSV results in paper/evaluation/results/embed_only_baseline.csv

Usage:
    python eval_embed_only_baseline.py
    python eval_embed_only_baseline.py --threshold 0.35
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

# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------

project_root = Path(__file__).resolve().parents[1]
parlor_dir = project_root / "bear_parlor"
sys.path.insert(0, str(project_root))

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
HATS = ["White", "Red", "Black", "Yellow", "Green", "Blue"]
DEFAULT_THRESHOLD = 0.35

# Naive session files (we replay these)
NAIVE_SESSIONS = {
    "brainstorming-hats_20260308_133940.md": "DMG",
    "brainstorming-hats_20260308_134610.md": "Stroke",
    "brainstorming-hats_20260308_135226.md": "MS",
    "brainstorming-hats_20260314_165328.md": "Alzheimers",
    "brainstorming-hats_20260314_170001.md": "Epilepsy",
}

# BEAR-guided sessions (for comparison table) — v4 batched diffusion
BEAR_SESSIONS = {
    "brainstorming-hats_20260313_084633.md": "DMG",
    "brainstorming-hats_20260313_085257.md": "Stroke",
    "brainstorming-hats_20260313_085916.md": "MS",
    "brainstorming-hats_20260314_164032.md": "Alzheimers",
    "brainstorming-hats_20260314_164701.md": "Epilepsy",
}

# ---------------------------------------------------------------------------
# Parsing: extract ALL hat utterances from session logs
# ---------------------------------------------------------------------------

_TURN_HEADER_RE = re.compile(
    r"^### Turn (\d+)\s*—\s*(\w[\w-]*)"
    r"(?:\s*→\s*[\w-]+)?"
    r"\s+<sub>[\d:]+</sub>",
    re.MULTILINE,
)


def parse_hat_utterances(log_path: Path) -> list[dict]:
    """Parse hat response texts from a session log.

    Returns list of {turn, speaker, text} for all hat turns.
    """
    text = log_path.read_text(encoding="utf-8")
    headers = list(_TURN_HEADER_RE.finditer(text))
    utterances = []

    for i, match in enumerate(headers):
        turn_num = int(match.group(1))
        speaker = match.group(2).replace("-hat", "").capitalize()

        if speaker not in HATS:
            continue

        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        # Clean: remove metadata blocks
        block = re.sub(r"<details>.*?</details>", "", block, flags=re.DOTALL)
        block = re.sub(r"\*\*Knowledge RAG\*\*.*?(?=\n###|\n---|\Z)",
                       "", block, flags=re.DOTALL)
        block = re.sub(r">\s*\*\[Diffusion.*", "", block)
        block = re.sub(r"^---\s*$", "", block, flags=re.MULTILINE)
        response_text = block.strip()

        if response_text and len(response_text.split()) >= 10:
            utterances.append({
                "turn": turn_num,
                "speaker": speaker,
                "text": response_text,
            })

    return utterances


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str], embedder) -> np.ndarray:
    """Embed texts. Returns (N, dim) array."""
    if not texts:
        return np.array([])
    return embedder.embed(texts, is_query=False)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 1.0
    return 1.0 - dot / norm


# ---------------------------------------------------------------------------
# Embed-only dedup simulation
# ---------------------------------------------------------------------------

def simulate_embed_only_dedup(
    utterances: list[dict],
    embeddings: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, list[int]]:
    """Simulate embed-only dedup: for each receiving hat, store utterances
    from other hats if they pass cosine dedup against previously stored items.

    Returns dict mapping hat -> list of utterance indices that were stored.
    """
    per_hat_stored: dict[str, list[int]] = defaultdict(list)
    per_hat_store_embs: dict[str, list[np.ndarray]] = defaultdict(list)

    for i, utt in enumerate(utterances):
        source_hat = utt["speaker"]
        emb = embeddings[i]

        # Each other hat receives this utterance
        for recv_hat in HATS:
            if recv_hat == source_hat:
                continue

            # Check dedup against receiver's existing store
            store = per_hat_store_embs[recv_hat]
            if store:
                min_dist = min(cosine_distance(emb, s) for s in store)
                if min_dist < threshold:
                    continue  # Too similar, skip

            # Passes dedup — store verbatim
            per_hat_stored[recv_hat].append(i)
            per_hat_store_embs[recv_hat].append(emb)

    return dict(per_hat_stored)


# ---------------------------------------------------------------------------
# Metrics (reuse from eval_interhat_differentiation)
# ---------------------------------------------------------------------------

def compute_centroid_distance(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
    centroid_a = np.mean(emb_a, axis=0)
    centroid_b = np.mean(emb_b, axis=0)
    return cosine_distance(centroid_a, centroid_b)


def compute_hausdorff_distance(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
    def directed(source, target):
        max_dist = 0.0
        for s in source:
            dists = [cosine_distance(s, t) for t in target]
            max_dist = max(max_dist, min(dists))
        return max_dist
    return max(directed(emb_a, emb_b), directed(emb_b, emb_a))


def compute_nn_overlap(
    emb_a: np.ndarray, emb_b: np.ndarray, threshold: float = DEFAULT_THRESHOLD,
) -> float:
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


def compute_pairwise_metrics(hat_embeddings: dict[str, np.ndarray]) -> list[dict]:
    results = []
    hats_with_data = [h for h in HATS
                      if h in hat_embeddings and len(hat_embeddings[h]) > 0]
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
# Main evaluation
# ---------------------------------------------------------------------------

def run_evaluation(threshold: float = DEFAULT_THRESHOLD):
    from bear.retriever import Embedder

    print("=" * 70)
    print("  Embed-Only Dedup Baseline Evaluation")
    print(f"  Dedup threshold: {threshold}")
    print("=" * 70)

    embedder = Embedder(model_name=EMBEDDING_MODEL, dim=768)
    print(f"Embedding model: {EMBEDDING_MODEL}\n")

    log_dir = parlor_dir / "session_logs"

    # ------------------------------------------------------------------
    # Load pre-computed BEAR-guided and naive results for comparison
    # ------------------------------------------------------------------
    interhat_csv = project_root / "results" / "interhat_differentiation.csv"
    existing_results = {}
    if interhat_csv.exists():
        import csv
        with open(interhat_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["topic"], row["condition"])
                existing_results[key] = {
                    "centroid_mean": float(row["centroid_mean"]),
                    "hausdorff_mean": float(row["hausdorff_mean"]),
                    "overlap_mean": float(row["overlap_mean"]),
                }
        print(f"Loaded {len(existing_results)} existing results from CSV.\n")

    # ------------------------------------------------------------------
    # Simulate embed-only dedup on naive sessions
    # ------------------------------------------------------------------
    embed_only_results = []

    for filename, topic in NAIVE_SESSIONS.items():
        path = log_dir / filename
        if not path.exists():
            print(f"WARNING: {filename} not found, skipping.")
            continue

        print(f"--- {topic} (Embed-only simulation from naive log) ---")

        # Parse all hat utterances
        utterances = parse_hat_utterances(path)
        print(f"  Total hat utterances: {len(utterances)}")

        # Embed all utterances
        texts = [u["text"] for u in utterances]
        all_embs = embed_texts(texts, embedder)

        # Simulate dedup
        stored_indices = simulate_embed_only_dedup(
            utterances, all_embs, threshold=threshold
        )

        # Build per-hat embedding arrays from stored indices
        hat_embeddings: dict[str, np.ndarray] = {}
        for hat in HATS:
            indices = stored_indices.get(hat, [])
            if indices:
                hat_embeddings[hat] = all_embs[indices]
                print(f"  {hat}: {len(indices)} items stored")
            else:
                print(f"  {hat}: 0 items stored")

        # Compute pairwise metrics
        pairwise = compute_pairwise_metrics(hat_embeddings)
        if not pairwise:
            print("  WARNING: Not enough hat pairs.\n")
            continue

        centroids = [p["centroid_distance"] for p in pairwise]
        hausdorffs = [p["hausdorff_distance"] for p in pairwise]
        overlaps = [p["nn_overlap"] for p in pairwise]

        result = {
            "topic": topic,
            "condition": "Embed-only",
            "n_pairs": len(pairwise),
            "centroid_mean": float(np.mean(centroids)),
            "hausdorff_mean": float(np.mean(hausdorffs)),
            "overlap_mean": float(np.mean(overlaps)),
            "per_hat_store_sizes": {
                hat: len(stored_indices.get(hat, [])) for hat in HATS
            },
        }
        embed_only_results.append(result)

        print(f"  Centroid: {result['centroid_mean']:.3f} | "
              f"Hausdorff: {result['hausdorff_mean']:.3f} | "
              f"Overlap: {result['overlap_mean']:.3f}\n")

    if not embed_only_results:
        print("ERROR: No results computed.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Summary: three-way comparison
    # ------------------------------------------------------------------
    print("=" * 70)
    print("  THREE-WAY COMPARISON")
    print("=" * 70)

    print(f"\n  {'Condition':<15} {'Centroid':>10} {'Hausdorff':>10} {'NN Overlap':>12}")
    print(f"  {'-'*15} {'-'*10} {'-'*10} {'-'*12}")

    # BEAR-guided
    bear_keys = [(t, "BEAR-guided") for t in ["DMG", "Stroke", "MS"]]
    bear_avail = [existing_results[k] for k in bear_keys if k in existing_results]
    if bear_avail:
        bc = np.mean([r["centroid_mean"] for r in bear_avail])
        bh = np.mean([r["hausdorff_mean"] for r in bear_avail])
        bo = np.mean([r["overlap_mean"] for r in bear_avail])
        print(f"  {'BEAR-guided':<15} {bc:>10.3f} {bh:>10.3f} {bo:>12.3f}")

    # Embed-only
    ec = np.mean([r["centroid_mean"] for r in embed_only_results])
    eh = np.mean([r["hausdorff_mean"] for r in embed_only_results])
    eo = np.mean([r["overlap_mean"] for r in embed_only_results])
    print(f"  {'Embed-only':<15} {ec:>10.3f} {eh:>10.3f} {eo:>12.3f}")

    # Naive
    naive_keys = [(t, "Naive") for t in ["DMG", "Stroke", "MS"]]
    naive_avail = [existing_results[k] for k in naive_keys if k in existing_results]
    if naive_avail:
        nc = np.mean([r["centroid_mean"] for r in naive_avail])
        nh = np.mean([r["hausdorff_mean"] for r in naive_avail])
        no_ = np.mean([r["overlap_mean"] for r in naive_avail])
        print(f"  {'Naive':<15} {nc:>10.3f} {nh:>10.3f} {no_:>12.3f}")

    # Attribution
    if bear_avail and naive_avail:
        total_centroid_gain = bc - nc
        dedup_centroid_gain = ec - nc
        reframe_centroid_gain = bc - ec

        total_overlap_reduction = no_ - bo
        dedup_overlap_reduction = no_ - eo
        reframe_overlap_reduction = eo - bo

        print(f"\n  Attribution (centroid distance, higher = more differentiated):")
        print(f"    Total gain (BEAR vs Naive):     {total_centroid_gain:+.3f}")
        print(f"    From dedup alone:               {dedup_centroid_gain:+.3f} "
              f"({100*dedup_centroid_gain/total_centroid_gain:.0f}%)"
              if total_centroid_gain != 0 else "")
        print(f"    From cognitive reframing:        {reframe_centroid_gain:+.3f} "
              f"({100*reframe_centroid_gain/total_centroid_gain:.0f}%)"
              if total_centroid_gain != 0 else "")

        print(f"\n  Attribution (NN overlap reduction, higher = more differentiated):")
        print(f"    Total reduction (BEAR vs Naive): {total_overlap_reduction:+.3f}")
        print(f"    From dedup alone:                {dedup_overlap_reduction:+.3f} "
              f"({100*dedup_overlap_reduction/total_overlap_reduction:.0f}%)"
              if total_overlap_reduction != 0 else "")
        print(f"    From cognitive reframing:         {reframe_overlap_reduction:+.3f} "
              f"({100*reframe_overlap_reduction/total_overlap_reduction:.0f}%)"
              if total_overlap_reduction != 0 else "")

    # ------------------------------------------------------------------
    # LaTeX table
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  LaTeX Table")
    print("=" * 70)

    print(r"""
\begin{table}[t]
\caption{Three-way comparison of diffusion conditions. Embed-only applies
cosine dedup at $d_{\min} = """ + f"{threshold}" + r"""$ but stores items
verbatim (no LLM reframing). The gap between embed-only and BEAR-guided
reflects the contribution of cognitive filtering beyond simple deduplication.}
\label{tab:three-way}
\centering
\begin{tabular}{@{}llccc@{}}
\toprule
Topic & Condition & Centroid Dist & Hausdorff Dist & NN Overlap \\
\midrule""")

    for topic in ["DMG", "Stroke", "MS"]:
        # BEAR
        bk = (topic, "BEAR-guided")
        if bk in existing_results:
            r = existing_results[bk]
            print(f"{topic:<7} & BEAR-guided & {r['centroid_mean']:.3f} "
                  f"& {r['hausdorff_mean']:.3f} & {r['overlap_mean']:.3f} \\\\")

        # Embed-only
        eo_r = [r for r in embed_only_results if r["topic"] == topic]
        if eo_r:
            r = eo_r[0]
            print(f"        & Embed-only  & {r['centroid_mean']:.3f} "
                  f"& {r['hausdorff_mean']:.3f} & {r['overlap_mean']:.3f} \\\\")

        # Naive
        nk = (topic, "Naive")
        if nk in existing_results:
            r = existing_results[nk]
            print(f"        & Naive       & {r['centroid_mean']:.3f} "
                  f"& {r['hausdorff_mean']:.3f} & {r['overlap_mean']:.3f} \\\\")

        if topic != "MS":
            print(r"\cmidrule(lr){1-5}")

    # Means
    print(r"\midrule")
    if bear_avail:
        print(f"\\textbf{{Mean}} & BEAR-guided & \\textbf{{{bc:.3f}}} "
              f"& \\textbf{{{bh:.3f}}} & \\textbf{{{bo:.3f}}} \\\\")
    print(f"        & Embed-only  & {ec:.3f} & {eh:.3f} & {eo:.3f} \\\\")
    if naive_avail:
        print(f"        & Naive       & {nc:.3f} & {nh:.3f} & {no_:.3f} \\\\")

    print(r"""\bottomrule
\end{tabular}
\end{table}""")

    # ------------------------------------------------------------------
    # Per-hat store sizes (embed-only vs BEAR vs naive)
    # ------------------------------------------------------------------
    print("\n  Per-hat mean store sizes (embed-only):")
    for hat in HATS:
        sizes = [r["per_hat_store_sizes"][hat] for r in embed_only_results]
        print(f"    {hat:8s}: {np.mean(sizes):.1f}")

    # ------------------------------------------------------------------
    # JSON output
    # ------------------------------------------------------------------
    results_dir = project_root / "results"
    results_dir.mkdir(exist_ok=True)

    json_output = {
        "metadata": {
            "eval": "embed_only_baseline",
            "description": "Embed-only dedup baseline (no LLM reframing)",
            "embedding_model": EMBEDDING_MODEL,
            "dedup_threshold": threshold,
        },
        "embed_only_sessions": embed_only_results,
        "three_way_means": {
            "embed_only": {"centroid": ec, "hausdorff": eh, "overlap": eo},
        },
    }
    if bear_avail:
        json_output["three_way_means"]["bear_guided"] = {
            "centroid": float(bc), "hausdorff": float(bh), "overlap": float(bo),
        }
    if naive_avail:
        json_output["three_way_means"]["naive"] = {
            "centroid": float(nc), "hausdorff": float(nh), "overlap": float(no_),
        }

    json_path = results_dir / "embed_only_baseline.json"
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=float)
    print(f"\n  JSON saved to: {json_path}")

    # CSV
    csv_path = results_dir / "embed_only_baseline.csv"
    with open(csv_path, "w") as f:
        f.write("topic,condition,centroid_mean,hausdorff_mean,overlap_mean\n")
        for r in embed_only_results:
            f.write(f"{r['topic']},Embed-only,{r['centroid_mean']:.4f},"
                    f"{r['hausdorff_mean']:.4f},{r['overlap_mean']:.4f}\n")
    print(f"  CSV saved to: {csv_path}")

    print("\nDone.")
    return json_output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Embed-only dedup baseline evaluation."
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Cosine dedup threshold (default: {DEFAULT_THRESHOLD}).",
    )
    args = parser.parse_args()
    run_evaluation(threshold=args.threshold)


if __name__ == "__main__":
    main()
