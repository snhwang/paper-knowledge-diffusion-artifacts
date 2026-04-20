"""Evaluate inter-hat response divergence: do different hats produce different responses?

This script measures whether BEAR-guided cognitive filtering causes hats to
respond more differently from each other than naive diffusion does. Unlike
the knowledge store differentiation metric (which measures what hats *store*),
this measures what hats actually *say*.

For each conversation turn where multiple hats respond, we compute pairwise
cosine distance between their response embeddings. BEAR should produce
greater inter-hat response divergence because each hat's knowledge store
contains differently filtered information that informs its responses.

Metrics:
  - Per-turn pairwise response distance: cosine distance between all hat
    pairs responding at the same conversation phase
  - Mean response divergence: averaged across all phases and pairs
  - Per-hat unique information: fraction of a hat's response embedding
    not explained by other hats' responses (residual after projection)
  - Knowledge utilization: semantic overlap between stored knowledge
    items and subsequent responses

Data source: session log markdown files (same format as other eval scripts).

Usage:
    python eval_response_divergence.py
    python eval_response_divergence.py --logs session_logs/bear1.md session_logs/naive1.md
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

# ---------------------------------------------------------------------------
# Session log mapping
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
# Parsing: extract per-turn responses and per-hat diffusion content
# ---------------------------------------------------------------------------

_TURN_HEADER_RE = re.compile(
    r"^### Turn (\d+)\s*—\s*(\w[\w-]*)"
    r"(?:\s*→\s*[\w-]+)?"
    r"\s+<sub>[\d:]+</sub>",
    re.MULTILINE,
)

# Match user prompt turns to identify conversation phases
_USER_TURN_RE = re.compile(
    r"^### Turn (\d+)\s*—\s*User\s+<sub>[\d:]+</sub>",
    re.MULTILINE,
)

_DIFFUSION_RE = re.compile(
    r">\s*\*\[Diffusion ([\d:]+)\]\*\s+(\S+)\s+←\s+(\S+):\s+"
    r"\*\*(\w+)\*\*"
    r"(?:\s*\(dist=[\d.]+\))?"
    r"(?:\s*—\s*(.*))?"
)


def parse_responses_by_phase(log_path: Path) -> list[dict]:
    """Parse responses grouped by conversation phase (between user messages).

    Returns list of phases, each containing:
      - phase_num: 1-indexed phase number
      - user_prompt: the user's message that started this phase
      - responses: list of {speaker, text, turn} for hat responses in this phase
    """
    text = log_path.read_text(encoding="utf-8")
    headers = list(_TURN_HEADER_RE.finditer(text))
    if not headers:
        return []

    # Parse all turns
    turns = []
    for i, match in enumerate(headers):
        turn_num = int(match.group(1))
        speaker = match.group(2)
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        # Clean response text
        block = re.sub(r"<details>.*?</details>", "", block, flags=re.DOTALL)
        block = re.sub(r"\*\*Knowledge RAG\*\*.*?(?=\n###|\n---|\Z)",
                       "", block, flags=re.DOTALL)
        block = re.sub(r">\s*\*\[Diffusion.*", "", block)
        block = re.sub(r"^---\s*$", "", block, flags=re.MULTILINE)
        response_text = block.strip()

        if not response_text:
            continue

        hat_name = speaker.replace("-hat", "").capitalize()
        turns.append({
            "turn": turn_num,
            "speaker": hat_name,
            "text": response_text,
        })

    # Group into phases (each user message starts a new phase)
    phases = []
    current_phase = None

    for t in turns:
        if t["speaker"] == "User":
            if current_phase is not None:
                phases.append(current_phase)
            current_phase = {
                "phase_num": len(phases) + 1,
                "user_prompt": t["text"],
                "responses": [],
            }
        elif t["speaker"] in HATS and current_phase is not None:
            if len(t["text"].split()) >= 10:  # skip very short responses
                current_phase["responses"].append(t)

    if current_phase is not None:
        phases.append(current_phase)

    return phases


def parse_diffusion_content(log_path: Path) -> dict[str, list[str]]:
    """Parse stored diffusion items per receiving hat from a session log."""
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
# Embedding + metrics
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str], embedder) -> np.ndarray:
    """Embed texts; returns shape (N, dim)."""
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


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    return 1.0 - cosine_distance(a, b)


def compute_phase_divergence(
    response_embeddings: dict[str, np.ndarray],
) -> dict:
    """Compute pairwise response distances for hats responding in one phase.

    Returns dict with:
      - pairwise_distances: list of {hat_a, hat_b, distance}
      - mean_distance: mean pairwise cosine distance
      - n_hats: number of hats that responded
      - n_pairs: number of pairs
    """
    hats = [h for h in HATS if h in response_embeddings]
    if len(hats) < 2:
        return {"pairwise_distances": [], "mean_distance": None,
                "n_hats": len(hats), "n_pairs": 0}

    pairwise = []
    for h1, h2 in combinations(hats, 2):
        dist = cosine_distance(response_embeddings[h1], response_embeddings[h2])
        pairwise.append({"hat_a": h1, "hat_b": h2, "distance": dist})

    return {
        "pairwise_distances": pairwise,
        "mean_distance": float(np.mean([p["distance"] for p in pairwise])),
        "n_hats": len(hats),
        "n_pairs": len(pairwise),
    }


def compute_knowledge_utilization(
    response_emb: np.ndarray,
    knowledge_embs: np.ndarray,
) -> float:
    """Mean max-similarity between response and stored knowledge items.

    High value = the response draws on stored knowledge.
    Returns mean of max cosine similarity for each knowledge item against
    the response.
    """
    if len(knowledge_embs) == 0:
        return 0.0
    similarities = [cosine_similarity(response_emb, k) for k in knowledge_embs]
    return float(np.mean(similarities))


def compute_unique_information(
    target_emb: np.ndarray,
    other_embs: list[np.ndarray],
) -> float:
    """Fraction of target response not explained by other hats' responses.

    Computed as 1 - max_similarity(target, others).
    High value = this hat says something unique.
    """
    if not other_embs:
        return 1.0
    max_sim = max(cosine_similarity(target_emb, o) for o in other_embs)
    return 1.0 - max_sim


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def run_evaluation(log_dir: Path | None = None, log_files: list[Path] | None = None):
    """Run the response divergence evaluation."""
    from bear.retriever import Embedder

    print("=" * 70)
    print("  Inter-Hat Response Divergence Evaluation")
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

    # Collect results across sessions
    all_session_results = []

    for path in paths:
        filename = path.name
        info = SESSION_MAP.get(filename)
        if info is None:
            continue  # skip sessions not in our map

        topic, condition = info
        print(f"--- {topic} ({condition}) : {filename} ---")

        # Parse responses grouped by conversation phase
        phases = parse_responses_by_phase(path)
        if not phases:
            print("  WARNING: No responses found, skipping.\n")
            continue

        # Parse diffusion content for knowledge utilization
        diffusion_content = parse_diffusion_content(path)

        # Embed all knowledge items per hat
        hat_knowledge_embs: dict[str, np.ndarray] = {}
        for hat in HATS:
            texts = diffusion_content.get(hat, [])
            if texts:
                hat_knowledge_embs[hat] = embed_texts(texts, embedder)

        # Process each phase
        phase_results = []
        for phase in phases:
            responses = phase["responses"]
            if len(responses) < 2:
                continue

            # For response divergence: if multiple responses from same hat in
            # one phase, concatenate them
            hat_texts: dict[str, str] = {}
            for r in responses:
                hat = r["speaker"]
                if hat in hat_texts:
                    hat_texts[hat] += " " + r["text"]
                else:
                    hat_texts[hat] = r["text"]

            # Embed each hat's concatenated response for this phase
            hat_embs: dict[str, np.ndarray] = {}
            for hat, text in hat_texts.items():
                emb = embed_texts([text], embedder)
                if len(emb) > 0:
                    hat_embs[hat] = emb[0]

            # Compute pairwise divergence
            divergence = compute_phase_divergence(hat_embs)
            if divergence["mean_distance"] is None:
                continue

            # Compute per-hat unique information
            unique_info = {}
            for hat in hat_embs:
                others = [hat_embs[h] for h in hat_embs if h != hat]
                unique_info[hat] = compute_unique_information(
                    hat_embs[hat], others
                )

            # Compute knowledge utilization per hat
            knowledge_util = {}
            for hat in hat_embs:
                if hat in hat_knowledge_embs:
                    knowledge_util[hat] = compute_knowledge_utilization(
                        hat_embs[hat], hat_knowledge_embs[hat]
                    )

            phase_results.append({
                "phase_num": phase["phase_num"],
                "user_prompt": phase["user_prompt"][:80],
                "divergence": divergence,
                "unique_info": unique_info,
                "knowledge_util": knowledge_util,
                "n_hats": divergence["n_hats"],
            })

        if not phase_results:
            print("  WARNING: No valid phases for analysis.\n")
            continue

        # Aggregate per-session
        mean_divergence = float(np.mean(
            [p["divergence"]["mean_distance"] for p in phase_results]
        ))
        all_unique = [v for p in phase_results
                      for v in p["unique_info"].values()]
        mean_unique = float(np.mean(all_unique)) if all_unique else 0.0
        all_knowledge = [v for p in phase_results
                         for v in p["knowledge_util"].values()]
        mean_knowledge = float(np.mean(all_knowledge)) if all_knowledge else 0.0

        session_result = {
            "topic": topic,
            "condition": condition,
            "filename": filename,
            "n_phases": len(phase_results),
            "mean_divergence": mean_divergence,
            "mean_unique_info": mean_unique,
            "mean_knowledge_util": mean_knowledge,
            "phase_details": phase_results,
        }
        all_session_results.append(session_result)

        print(f"  Phases: {len(phase_results)} | "
              f"Divergence: {mean_divergence:.4f} | "
              f"Unique: {mean_unique:.4f} | "
              f"Knowledge util: {mean_knowledge:.4f}")

        # Per-phase detail
        for p in phase_results:
            print(f"    Phase {p['phase_num']} ({p['n_hats']} hats): "
                  f"div={p['divergence']['mean_distance']:.4f}  "
                  f"unique={np.mean(list(p['unique_info'].values())):.4f}")
        print()

    if not all_session_results:
        print("ERROR: No valid sessions to analyze.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Summary by condition
    # ------------------------------------------------------------------
    print("=" * 70)
    print("  SUMMARY BY CONDITION")
    print("=" * 70)

    conditions = sorted(set(s["condition"] for s in all_session_results))
    for cond in conditions:
        sessions = [s for s in all_session_results if s["condition"] == cond]
        divs = [s["mean_divergence"] for s in sessions]
        uniq = [s["mean_unique_info"] for s in sessions]
        kutil = [s["mean_knowledge_util"] for s in sessions]
        print(f"\n  {cond} (n={len(sessions)} sessions):")
        print(f"    Response divergence: {np.mean(divs):.4f}  "
              f"(per-session: {', '.join(f'{v:.4f}' for v in divs)})")
        print(f"    Unique information:  {np.mean(uniq):.4f}  "
              f"(per-session: {', '.join(f'{v:.4f}' for v in uniq)})")
        if any(k > 0 for k in kutil):
            print(f"    Knowledge utiliz.:   {np.mean(kutil):.4f}  "
                  f"(per-session: {', '.join(f'{v:.4f}' for v in kutil)})")

    # ------------------------------------------------------------------
    # BEAR vs Naive comparison
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  BEAR vs NAIVE COMPARISON")
    print("=" * 70)

    # Group by base condition (BEAR-* vs Naive-*)
    bear_divs = [s["mean_divergence"] for s in all_session_results
                 if s["condition"].startswith("BEAR")]
    naive_divs = [s["mean_divergence"] for s in all_session_results
                  if s["condition"].startswith("Naive") or s["condition"] == "Naive"]
    bear_uniq = [s["mean_unique_info"] for s in all_session_results
                 if s["condition"].startswith("BEAR")]
    naive_uniq = [s["mean_unique_info"] for s in all_session_results
                  if s["condition"].startswith("Naive") or s["condition"] == "Naive"]

    if bear_divs and naive_divs:
        print(f"\n  Response Divergence:")
        print(f"    BEAR:  {np.mean(bear_divs):.4f} ± {np.std(bear_divs):.4f}  "
              f"(n={len(bear_divs)})")
        print(f"    Naive: {np.mean(naive_divs):.4f} ± {np.std(naive_divs):.4f}  "
              f"(n={len(naive_divs)})")

        # Welch's t-test
        from scipy import stats
        t_stat, p_val = stats.ttest_ind(bear_divs, naive_divs, equal_var=False)
        print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")
        if p_val < 0.05:
            direction = "BEAR > Naive" if np.mean(bear_divs) > np.mean(naive_divs) else "Naive > BEAR"
            print(f"    → Significant difference ({direction})")
        else:
            print(f"    → No significant difference (p ≥ 0.05)")

        # Effect size (Cohen's d)
        pooled_std = np.sqrt(
            (np.std(bear_divs)**2 + np.std(naive_divs)**2) / 2
        )
        if pooled_std > 0:
            cohens_d = (np.mean(bear_divs) - np.mean(naive_divs)) / pooled_std
            print(f"    Cohen's d = {cohens_d:.3f}")

    if bear_uniq and naive_uniq:
        print(f"\n  Unique Information:")
        print(f"    BEAR:  {np.mean(bear_uniq):.4f} ± {np.std(bear_uniq):.4f}")
        print(f"    Naive: {np.mean(naive_uniq):.4f} ± {np.std(naive_uniq):.4f}")
        t_stat, p_val = stats.ttest_ind(bear_uniq, naive_uniq, equal_var=False)
        print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")

    # ------------------------------------------------------------------
    # Per-phase analysis (more statistical power)
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PER-PHASE ANALYSIS")
    print("=" * 70)

    from scipy import stats as sp_stats

    bear_phase_divs = []
    naive_phase_divs = []
    bear_phase_uniq = []
    naive_phase_uniq = []

    for s in all_session_results:
        is_bear = s["condition"].startswith("BEAR")
        is_naive = (s["condition"].startswith("Naive")
                    or s["condition"] == "Naive")
        for p in s["phase_details"]:
            div = p["divergence"]["mean_distance"]
            uniq_vals = list(p["unique_info"].values())
            mean_uniq = float(np.mean(uniq_vals)) if uniq_vals else 0.0
            if is_bear:
                bear_phase_divs.append(div)
                bear_phase_uniq.append(mean_uniq)
            elif is_naive:
                naive_phase_divs.append(div)
                naive_phase_uniq.append(mean_uniq)

    # Also collect phases with 4+ hats (less noise)
    bear_phase_divs_4plus = []
    naive_phase_divs_4plus = []
    bear_phase_uniq_4plus = []
    naive_phase_uniq_4plus = []

    for s in all_session_results:
        is_bear = s["condition"].startswith("BEAR")
        is_naive = (s["condition"].startswith("Naive")
                    or s["condition"] == "Naive")
        for p in s["phase_details"]:
            if p["n_hats"] >= 4:
                div = p["divergence"]["mean_distance"]
                uniq_vals = list(p["unique_info"].values())
                mean_uniq = float(np.mean(uniq_vals)) if uniq_vals else 0.0
                if is_bear:
                    bear_phase_divs_4plus.append(div)
                    bear_phase_uniq_4plus.append(mean_uniq)
                elif is_naive:
                    naive_phase_divs_4plus.append(div)
                    naive_phase_uniq_4plus.append(mean_uniq)

    if bear_phase_divs and naive_phase_divs:
        print(f"\n  Response Divergence (per-phase, ALL phases):")
        print(f"    BEAR:  {np.mean(bear_phase_divs):.4f} ± "
              f"{np.std(bear_phase_divs):.4f}  (n={len(bear_phase_divs)} phases)")
        print(f"    Naive: {np.mean(naive_phase_divs):.4f} ± "
              f"{np.std(naive_phase_divs):.4f}  (n={len(naive_phase_divs)} phases)")

        # Welch's t-test
        t_stat, p_val = sp_stats.ttest_ind(
            bear_phase_divs, naive_phase_divs, equal_var=False
        )
        print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")

        # Mann-Whitney U (non-parametric)
        u_stat, u_pval = sp_stats.mannwhitneyu(
            bear_phase_divs, naive_phase_divs, alternative="greater"
        )
        print(f"    Mann-Whitney U={u_stat:.0f}, p={u_pval:.4f} (one-sided: BEAR > Naive)")

        # Effect size
        pooled_std = np.sqrt(
            (np.std(bear_phase_divs)**2 + np.std(naive_phase_divs)**2) / 2
        )
        if pooled_std > 0:
            d = (np.mean(bear_phase_divs) - np.mean(naive_phase_divs)) / pooled_std
            print(f"    Cohen's d = {d:.3f}")

        # Median comparison
        print(f"    BEAR median:  {np.median(bear_phase_divs):.4f}")
        print(f"    Naive median: {np.median(naive_phase_divs):.4f}")

    if bear_phase_uniq and naive_phase_uniq:
        print(f"\n  Unique Information (per-phase):")
        print(f"    BEAR:  {np.mean(bear_phase_uniq):.4f} ± "
              f"{np.std(bear_phase_uniq):.4f}  (n={len(bear_phase_uniq)} phases)")
        print(f"    Naive: {np.mean(naive_phase_uniq):.4f} ± "
              f"{np.std(naive_phase_uniq):.4f}  (n={len(naive_phase_uniq)} phases)")
        t_stat, p_val = sp_stats.ttest_ind(
            bear_phase_uniq, naive_phase_uniq, equal_var=False
        )
        print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")
        u_stat, u_pval = sp_stats.mannwhitneyu(
            bear_phase_uniq, naive_phase_uniq, alternative="greater"
        )
        print(f"    Mann-Whitney U={u_stat:.0f}, p={u_pval:.4f} (one-sided: BEAR > Naive)")

    # Filtered: phases with 4+ hats only
    if bear_phase_divs_4plus and naive_phase_divs_4plus:
        print(f"\n  Response Divergence (phases with 4+ hats only):")
        print(f"    BEAR:  {np.mean(bear_phase_divs_4plus):.4f} ± "
              f"{np.std(bear_phase_divs_4plus):.4f}  "
              f"(n={len(bear_phase_divs_4plus)} phases)")
        print(f"    Naive: {np.mean(naive_phase_divs_4plus):.4f} ± "
              f"{np.std(naive_phase_divs_4plus):.4f}  "
              f"(n={len(naive_phase_divs_4plus)} phases)")

        t_stat, p_val = sp_stats.ttest_ind(
            bear_phase_divs_4plus, naive_phase_divs_4plus, equal_var=False
        )
        print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")

        u_stat, u_pval = sp_stats.mannwhitneyu(
            bear_phase_divs_4plus, naive_phase_divs_4plus, alternative="greater"
        )
        print(f"    Mann-Whitney U={u_stat:.0f}, p={u_pval:.4f} (one-sided: BEAR > Naive)")

        pooled_std = np.sqrt(
            (np.std(bear_phase_divs_4plus)**2 +
             np.std(naive_phase_divs_4plus)**2) / 2
        )
        if pooled_std > 0:
            d = (np.mean(bear_phase_divs_4plus) -
                 np.mean(naive_phase_divs_4plus)) / pooled_std
            print(f"    Cohen's d = {d:.3f}")

        print(f"    BEAR median:  {np.median(bear_phase_divs_4plus):.4f}")
        print(f"    Naive median: {np.median(naive_phase_divs_4plus):.4f}")

    if bear_phase_uniq_4plus and naive_phase_uniq_4plus:
        print(f"\n  Unique Information (phases with 4+ hats only):")
        print(f"    BEAR:  {np.mean(bear_phase_uniq_4plus):.4f} ± "
              f"{np.std(bear_phase_uniq_4plus):.4f}  "
              f"(n={len(bear_phase_uniq_4plus)} phases)")
        print(f"    Naive: {np.mean(naive_phase_uniq_4plus):.4f} ± "
              f"{np.std(naive_phase_uniq_4plus):.4f}  "
              f"(n={len(naive_phase_uniq_4plus)} phases)")
        t_stat, p_val = sp_stats.ttest_ind(
            bear_phase_uniq_4plus, naive_phase_uniq_4plus, equal_var=False
        )
        print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")
        u_stat, u_pval = sp_stats.mannwhitneyu(
            bear_phase_uniq_4plus, naive_phase_uniq_4plus, alternative="greater"
        )
        print(f"    Mann-Whitney U={u_stat:.0f}, p={u_pval:.4f} (one-sided: BEAR > Naive)")

    # ------------------------------------------------------------------
    # LaTeX table
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  LaTeX Table")
    print("=" * 70)

    print(r"""
\begin{table}[t]
\caption{Inter-hat response divergence: pairwise cosine distance between hat
responses at the same conversation phase. Higher divergence indicates hats
are contributing more distinct perspectives. Unique information measures the
fraction of each response not explained by other hats' responses.}
\label{tab:response-divergence}
\begin{tabular}{@{}llccc@{}}
\toprule
Topic & Condition & Resp.\ Divergence & Unique Info & Knowledge Util \\
\midrule""")

    for s in all_session_results:
        ku_str = f"{s['mean_knowledge_util']:.4f}" if s['mean_knowledge_util'] > 0 else "---"
        print(f"{s['topic']:<7} & {s['condition']:<16} "
              f"& {s['mean_divergence']:.4f} & {s['mean_unique_info']:.4f} "
              f"& {ku_str} \\\\")

    print(r"""\bottomrule
\end{tabular}
\end{table}""")

    # ------------------------------------------------------------------
    # CSV output
    # ------------------------------------------------------------------
    results_dir = project_root / "results"
    results_dir.mkdir(exist_ok=True)
    csv_path = results_dir / "response_divergence.csv"
    with open(csv_path, "w") as f:
        f.write("topic,condition,n_phases,mean_divergence,mean_unique_info,"
                "mean_knowledge_util\n")
        for s in all_session_results:
            f.write(f"{s['topic']},{s['condition']},{s['n_phases']},"
                    f"{s['mean_divergence']:.4f},{s['mean_unique_info']:.4f},"
                    f"{s['mean_knowledge_util']:.4f}\n")
    print(f"\n  CSV saved to: {csv_path}")

    # ------------------------------------------------------------------
    # JSON output (all stats for reproducibility)
    # ------------------------------------------------------------------
    import json

    json_output = {
        "metadata": {
            "eval": "response_divergence",
            "description": "Inter-hat response divergence: do BEAR-guided hats "
                           "produce more different responses than naive hats?",
            "embedding_model": EMBEDDING_MODEL,
        },
        "sessions": [],
        "comparisons": {},
    }

    # Per-session results
    for s in all_session_results:
        json_output["sessions"].append({
            "topic": s["topic"],
            "condition": s["condition"],
            "filename": s["filename"],
            "n_phases": s["n_phases"],
            "mean_divergence": s["mean_divergence"],
            "mean_unique_info": s["mean_unique_info"],
            "mean_knowledge_util": s["mean_knowledge_util"],
        })

    # Helper for bootstrap CI on a single sample
    def _bootstrap_ci(values, n_boot=10000, alpha=0.05):
        import random
        rng = random.Random(42)
        n = len(values)
        means = sorted(
            sum(rng.choices(values, k=n)) / n for _ in range(n_boot)
        )
        return {
            "ci_low": means[int(n_boot * alpha / 2)],
            "ci_high": means[int(n_boot * (1 - alpha / 2))],
        }

    # Helper for bootstrap CI on a difference
    def _bootstrap_diff_ci(a, b, n_boot=10000, alpha=0.05):
        import random
        rng = random.Random(42)
        diffs = [x - y for x, y in zip(a, b)]
        n = len(diffs)
        means = sorted(
            sum(rng.choices(diffs, k=n)) / n for _ in range(n_boot)
        )
        return {
            "mean_diff": sum(diffs) / n,
            "ci_low": means[int(n_boot * alpha / 2)],
            "ci_high": means[int(n_boot * (1 - alpha / 2))],
        }

    # Session-level comparison
    if bear_divs and naive_divs:
        from scipy import stats as _stats

        t_stat, p_val = _stats.ttest_ind(bear_divs, naive_divs, equal_var=False)
        pooled_std = float(np.sqrt(
            (np.std(bear_divs)**2 + np.std(naive_divs)**2) / 2
        ))
        cohens_d = float(
            (np.mean(bear_divs) - np.mean(naive_divs)) / pooled_std
        ) if pooled_std > 0 else None

        json_output["comparisons"]["session_level_divergence"] = {
            "bear": {
                "mean": float(np.mean(bear_divs)),
                "std": float(np.std(bear_divs)),
                "n": len(bear_divs),
                "values": [float(v) for v in bear_divs],
                **_bootstrap_ci(bear_divs),
            },
            "naive": {
                "mean": float(np.mean(naive_divs)),
                "std": float(np.std(naive_divs)),
                "n": len(naive_divs),
                "values": [float(v) for v in naive_divs],
                **_bootstrap_ci(naive_divs),
            },
            "welch_t": float(t_stat),
            "p_value": float(p_val),
            "cohens_d": cohens_d,
            "diff_ci": _bootstrap_diff_ci(bear_divs, naive_divs),
        }

    if bear_uniq and naive_uniq:
        t_stat, p_val = _stats.ttest_ind(bear_uniq, naive_uniq, equal_var=False)
        pooled_std = float(np.sqrt(
            (np.std(bear_uniq)**2 + np.std(naive_uniq)**2) / 2
        ))
        cohens_d = float(
            (np.mean(bear_uniq) - np.mean(naive_uniq)) / pooled_std
        ) if pooled_std > 0 else None

        json_output["comparisons"]["session_level_unique_info"] = {
            "bear": {
                "mean": float(np.mean(bear_uniq)),
                "std": float(np.std(bear_uniq)),
                "n": len(bear_uniq),
                **_bootstrap_ci(bear_uniq),
            },
            "naive": {
                "mean": float(np.mean(naive_uniq)),
                "std": float(np.std(naive_uniq)),
                "n": len(naive_uniq),
                **_bootstrap_ci(naive_uniq),
            },
            "welch_t": float(t_stat),
            "p_value": float(p_val),
            "cohens_d": cohens_d,
        }

    # Per-phase comparison (more statistical power)
    if bear_phase_divs and naive_phase_divs:
        t_stat, p_val = sp_stats.ttest_ind(
            bear_phase_divs, naive_phase_divs, equal_var=False
        )
        u_stat, u_pval = sp_stats.mannwhitneyu(
            bear_phase_divs, naive_phase_divs, alternative="greater"
        )
        pooled_std = float(np.sqrt(
            (np.std(bear_phase_divs)**2 + np.std(naive_phase_divs)**2) / 2
        ))
        cohens_d = float(
            (np.mean(bear_phase_divs) - np.mean(naive_phase_divs)) / pooled_std
        ) if pooled_std > 0 else None

        json_output["comparisons"]["phase_level_divergence"] = {
            "bear": {
                "mean": float(np.mean(bear_phase_divs)),
                "std": float(np.std(bear_phase_divs)),
                "median": float(np.median(bear_phase_divs)),
                "n": len(bear_phase_divs),
            },
            "naive": {
                "mean": float(np.mean(naive_phase_divs)),
                "std": float(np.std(naive_phase_divs)),
                "median": float(np.median(naive_phase_divs)),
                "n": len(naive_phase_divs),
            },
            "welch_t": float(t_stat),
            "welch_p": float(p_val),
            "mann_whitney_u": float(u_stat),
            "mann_whitney_p": float(u_pval),
            "cohens_d": cohens_d,
        }

    # 4+ hats phases
    if bear_phase_divs_4plus and naive_phase_divs_4plus:
        t_stat, p_val = sp_stats.ttest_ind(
            bear_phase_divs_4plus, naive_phase_divs_4plus, equal_var=False
        )
        u_stat, u_pval = sp_stats.mannwhitneyu(
            bear_phase_divs_4plus, naive_phase_divs_4plus, alternative="greater"
        )
        pooled_std = float(np.sqrt(
            (np.std(bear_phase_divs_4plus)**2 +
             np.std(naive_phase_divs_4plus)**2) / 2
        ))
        cohens_d = float(
            (np.mean(bear_phase_divs_4plus) -
             np.mean(naive_phase_divs_4plus)) / pooled_std
        ) if pooled_std > 0 else None

        json_output["comparisons"]["phase_level_divergence_4plus_hats"] = {
            "bear": {
                "mean": float(np.mean(bear_phase_divs_4plus)),
                "std": float(np.std(bear_phase_divs_4plus)),
                "median": float(np.median(bear_phase_divs_4plus)),
                "n": len(bear_phase_divs_4plus),
            },
            "naive": {
                "mean": float(np.mean(naive_phase_divs_4plus)),
                "std": float(np.std(naive_phase_divs_4plus)),
                "median": float(np.median(naive_phase_divs_4plus)),
                "n": len(naive_phase_divs_4plus),
            },
            "welch_t": float(t_stat),
            "welch_p": float(p_val),
            "mann_whitney_u": float(u_stat),
            "mann_whitney_p": float(u_pval),
            "cohens_d": cohens_d,
        }

    json_path = results_dir / "response_divergence.json"
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2)
    print(f"  JSON saved to: {json_path}")

    print("\nDone.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate inter-hat response divergence."
    )
    parser.add_argument(
        "--logs", nargs="+", type=Path,
        help="Session log .md files to analyze. If omitted, uses all mapped logs.",
    )
    args = parser.parse_args()
    run_evaluation(log_files=args.logs)


if __name__ == "__main__":
    main()
