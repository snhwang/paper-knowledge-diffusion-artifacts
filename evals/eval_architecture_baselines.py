"""Architecture baselines: BEAR-guided diffusion vs. existing multi-agent
knowledge-management designs.

Addresses Expert Systems Reviewer 1, comment 3 ("direct comparisons with
existing multi-agent knowledge management methods").

The comparison is run at the **knowledge-representation level**, not the
task-accuracy level, because that is where this paper's claim lives: role
differentiation is architecturally fragile under naive knowledge sharing.

Four conditions
---------------
bear            Per-agent store. Incoming utterances are filtered and reframed
                through the receiving hat's BEAR-retrieved cognitive lens
                before storage. (This paper.)
naive           Per-agent store. Incoming utterances stored verbatim, no
                filtering. (Unfiltered broadcast.)
shared-store    ONE global store shared by all agents, cosine-deduped at
                d_min. Agents differ only in what they retrieve from it.
                Abstracts the consolidated shared long-term memory topology.
shared-full     ONE global store shared by all agents, NO deduplication, so
                retrieval selects from the entire utterance pool. This is the
                strongest fair competitor: it gives role-specific retrieval
                the largest possible corpus to differentiate over, and it
                rules out the objection that the shared baseline was crippled
                by aggressive consolidation.
shared-context  No store. The full transcript is available to every agent.
                Abstracts the shared-conversation-context topology.

IMPORTANT — what these conditions are and are not
-------------------------------------------------
These are abstracted knowledge-sharing *topologies*, not reimplementations of
any specific published system. We do not run MemGPT, Letta, AutoGen, or
MetaGPT here, and we do not reproduce their distinguishing mechanisms
(self-editing memory with context paging and recursive summarisation;
configurable conversation-based message routing; SOP-structured messaging).
Those systems are cited in the paper as examples that adopt a shared-pool
topology, and the claim made from these numbers is about the topology only.

Describing a condition as "MemGPT-style" in the manuscript would overclaim,
because a reviewer familiar with those systems would correctly object that
they were never executed. Keep the topology framing in any write-up.

Two levels of measurement
-------------------------
store       Differentiation of the full per-agent knowledge stores. For the
            two shared conditions this is 0 by construction (every agent holds
            the identical store), which is the architectural point rather than
            an empirical finding, and is reported as such.

retrieved   Differentiation of what each agent actually receives at generation
            time. Every agent issues a role-specific query built from its BEAR
            behavioral profile and retrieves top-k. This is the fair,
            non-degenerate comparison: retrieving from a shared store with a
            role-specific query DOES produce some differentiation, so the
            question is how much, relative to role-specific encoding at write
            time.

The headline claim the numbers support or refute: role-specific *retrieval*
from a shared store is not sufficient to preserve differentiation. Role-
specific *encoding* at write time is what does the work.

Outputs (paper/evaluation/results/)
    architecture_baselines.json   full results incl. per-topic arrays
    architecture_baselines.csv    per-topic per-condition metrics
    console summary + LaTeX table fragment

Usage:
    python eval_architecture_baselines.py
    python eval_architecture_baselines.py --top-k 8 --include-pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "results"

# Session logs live in the artifacts repo (they are gitignored in bear-dev).
# Candidates are tried in order; the first two are relative to this script so
# the evaluation is portable, and the absolute path is a development fallback.
DEFAULT_LOG_DIRS = [
    HERE.parent / "bear_parlor" / "session_logs",              # artifacts repo
    HERE.parent.parent / "examples" / "bear_parlor" / "session_logs",  # bear-dev
    Path(r"C:\Users\Scott\Documents\Work\paper-knowledge-diffusion-artifacts")
    / "bear_parlor" / "session_logs",
]

# Hat instruction corpora (for role-specific retrieval queries).
DEFAULT_HAT_DIRS = [
    HERE.parent / "bear_parlor" / "instructions" / "hats",     # artifacts repo
    HERE.parent.parent / "examples" / "bear_parlor" / "instructions" / "hats",
    Path(r"C:\Users\Scott\Documents\Work\paper-knowledge-diffusion-artifacts")
    / "bear_parlor" / "instructions" / "hats",
]

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
TOPICS = ["dmg", "stroke", "ms", "alzheimers", "epilepsy", "glp1", "crispr", "llm-cds"]
HATS = ["white-hat", "red-hat", "black-hat", "blue-hat", "green-hat", "yellow-hat"]

# Matches KnowledgeStore.query(top_k=4) in examples/bear_parlor/knowledge_rag.py
DEFAULT_TOP_K = 4
# Matches the paper's d_min dedup threshold (cosine distance).
DEFAULT_DMIN = 0.35
# NN-overlap similarity threshold, matching eval_interhat_v2.py.
NN_SIM_THRESHOLD = 0.85

CONDITIONS = ["bear", "naive", "shared-store", "shared-full", "shared-context"]
CONDITION_LABELS = {
    "bear": "BEAR-guided (this paper)",
    "naive": "Unfiltered broadcast",
    "shared-store": "Shared store, consolidated",
    "shared-full": "Shared store, full pool",
    "shared-context": "Shared conversation context",
}


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def has_labelled_sessions(p: Path) -> bool:
    """True if the directory holds at least one topic/condition-labelled run.

    Existence alone is not enough: bear-dev keeps a session_logs directory of
    unrelated later runs whose stats carry empty topic/condition fields, and it
    would otherwise shadow the real corpus in the artifacts repo.
    """
    for f in p.glob("brainstorming-hats_*.stats.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if d.get("topic") and d.get("condition"):
            return True
    return False


def has_hat_corpora(p: Path) -> bool:
    return (p / "white_hat.yaml").exists()


def resolve_dir(candidates: list[Path], what: str, validate=None) -> Path:
    for p in candidates:
        if p.exists() and (validate is None or validate(p)):
            return p
    sys.exit(f"ERROR: could not locate usable {what}. Tried:\n  " +
             "\n  ".join(str(c) for c in candidates))


def load_best_sessions(log_dir: Path) -> dict:
    """Select one session per (topic, condition).

    Mirrors load_best_sessions() in eval_interhat_v2.py so the bear/naive arms
    reproduce the published numbers. Preference: completed, then most turns.
    """
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


def load_hat_docs(kj_path: Path, include_pdf: bool) -> dict[str, list[str]]:
    """Load per-hat documents from a knowledge.json snapshot.

    By default keeps only diffusion-sourced documents. PDF chunks are
    per-hat ingested domain knowledge that never travels the diffusion
    pathway, so including them conflates the mechanism under test with
    the White Hat's private literature corpus.
    """
    kj = json.loads(kj_path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for hat in HATS:
        entry = kj.get(hat, {})
        docs = entry.get("documents", []) or []
        metas = entry.get("metadatas", []) or []
        if include_pdf or not metas:
            kept = list(docs)
        else:
            kept = [
                d for d, m in zip(docs, metas)
                if (m or {}).get("source") != "pdf"
            ]
        if kept:
            out[hat] = kept
    return out


def load_role_queries(hat_dir: Path) -> dict[str, str]:
    """Build a role-specific retrieval query per hat from its BEAR profile.

    Concatenates persona and directive instruction content, which is what the
    live system composes into the hat's system prompt. Falls back to a plain
    role descriptor if PyYAML or the corpora are unavailable.
    """
    fallback = {
        "white-hat": "objective facts, data, evidence, what is known and what is missing",
        "red-hat": "feelings, intuition, emotional reaction, gut response",
        "black-hat": "risks, flaws, failure modes, obstacles, critical analysis",
        "blue-hat": "process facilitation, structure, synthesis, keeping the session on track",
        "green-hat": "creative alternatives, novel ideas, lateral possibilities",
        "yellow-hat": "benefits, value, optimism, why this could work",
    }
    try:
        import yaml
    except ImportError:
        print("  NOTE: PyYAML unavailable, using fallback role queries.")
        return fallback

    queries: dict[str, str] = {}
    for hat in HATS:
        path = hat_dir / f"{hat.replace('-', '_')}.yaml"
        if not path.exists():
            queries[hat] = fallback[hat]
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            queries[hat] = fallback[hat]
            continue
        parts = [
            str(ins.get("content", "")).strip()
            for ins in (data.get("instructions") or [])
            if ins.get("type") in ("persona", "directive")
        ]
        text = "\n".join(p for p in parts if p)
        queries[hat] = text if text else fallback[hat]
    return queries


# ---------------------------------------------------------------------------
# Metrics (unit-normalised embeddings throughout)
# ---------------------------------------------------------------------------

def cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
    return 1.0 - float(np.dot(a, b))


def mean_pairwise_centroid(hat_embs: dict[str, np.ndarray]) -> float:
    hats = [h for h in HATS if h in hat_embs and len(hat_embs[h])]
    if len(hats) < 2:
        return float("nan")
    centroids = {}
    for h in hats:
        c = np.asarray(hat_embs[h]).mean(axis=0)
        centroids[h] = c / (np.linalg.norm(c) + 1e-10)
    dists = [cosine_dist(centroids[a], centroids[b])
             for a, b in combinations(hats, 2)]
    return float(np.mean(dists))


def nn_overlap_directional(a: np.ndarray, b: np.ndarray,
                           threshold: float = NN_SIM_THRESHOLD) -> float:
    if not len(a) or not len(b):
        return 0.0
    sim = np.asarray(a) @ np.asarray(b).T
    return float((sim.max(axis=1) >= threshold).mean())


def mean_pairwise_nn_overlap(hat_embs: dict[str, np.ndarray]) -> float:
    hats = [h for h in HATS if h in hat_embs and len(hat_embs[h])]
    if len(hats) < 2:
        return float("nan")
    vals = []
    for a, b in combinations(hats, 2):
        ov = (nn_overlap_directional(hat_embs[a], hat_embs[b]) +
              nn_overlap_directional(hat_embs[b], hat_embs[a])) / 2
        vals.append(ov)
    return float(np.mean(vals))


# ---------------------------------------------------------------------------
# Condition construction
# ---------------------------------------------------------------------------

def greedy_dedup(embs: np.ndarray, texts: list[str], d_min: float
                 ) -> tuple[np.ndarray, list[str]]:
    """Greedy cosine dedup: keep an item only if it is at least d_min
    (cosine distance) from every already-kept item."""
    kept_idx: list[int] = []
    for i in range(len(texts)):
        if kept_idx:
            sims = embs[kept_idx] @ embs[i]
            if float(1.0 - sims.max()) < d_min:
                continue
        kept_idx.append(i)
    return embs[kept_idx], [texts[i] for i in kept_idx]


def build_shared_corpus(naive_docs: dict[str, list[str]]) -> list[str]:
    """The global utterance pool a shared-memory architecture would hold.

    Under naive diffusion every hat stores a verbatim copy of the utterances
    it received, so the exact-text union across hats reconstructs the full
    utterance set exactly once.
    """
    seen: set[str] = set()
    corpus: list[str] = []
    for hat in HATS:
        for d in naive_docs.get(hat, []):
            key = d.strip()
            if key and key not in seen:
                seen.add(key)
                corpus.append(d)
    return corpus


def retrieve_top_k(store_embs: np.ndarray, query_emb: np.ndarray,
                   top_k: int) -> np.ndarray:
    """Return embeddings of the top_k store items nearest the query."""
    if not len(store_embs):
        return np.empty((0, query_emb.shape[0]))
    sims = store_embs @ query_emb
    k = min(top_k, len(store_embs))
    idx = np.argpartition(-sims, k - 1)[:k]
    return store_embs[idx]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def bootstrap_ci(values: list[float], n_boot: int = 10000,
                 seed: int = 20261025) -> tuple[float, float]:
    arr = np.asarray([v for v in values if not np.isnan(v)], dtype=float)
    if len(arr) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def paired_test(a: list[float], b: list[float]) -> dict:
    """Wilcoxon signed-rank plus paired Cohen's d for a vs b."""
    pairs = [(x, y) for x, y in zip(a, b)
             if not (np.isnan(x) or np.isnan(y))]
    if len(pairs) < 2:
        return {"n": len(pairs), "p": float("nan"), "cohens_d": float("nan")}
    x = np.array([p[0] for p in pairs], dtype=float)
    y = np.array([p[1] for p in pairs], dtype=float)
    diff = x - y
    sd = diff.std(ddof=1)
    d = float(diff.mean() / sd) if sd > 0 else float("inf")
    p = float("nan")
    if np.any(diff != 0):
        try:
            from scipy.stats import wilcoxon
            p = float(wilcoxon(x, y).pvalue)
        except ImportError:
            print("  NOTE: scipy unavailable, skipping Wilcoxon p-values.")
        except ValueError:
            pass
    return {"n": len(pairs), "p": p, "cohens_d": d,
            "mean_diff": float(diff.mean())}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(top_k: int, d_min: float, include_pdf: bool):
    from sentence_transformers import SentenceTransformer

    log_dir = resolve_dir(DEFAULT_LOG_DIRS, "session_logs", has_labelled_sessions)
    hat_dir = resolve_dir(DEFAULT_HAT_DIRS, "hat instruction corpora",
                          has_hat_corpora)

    print("=" * 74)
    print("  Architecture Baselines — knowledge-representation comparison")
    print(f"  logs={log_dir}")
    print(f"  top_k={top_k}  d_min={d_min}  include_pdf={include_pdf}")
    print("=" * 74)

    sessions = load_best_sessions(log_dir)
    print(f"\n{len(sessions)} sessions selected "
          f"({len({t for t, _ in sessions})} topics)\n")

    print(f"Loading {EMBEDDING_MODEL} ...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    role_queries = load_role_queries(hat_dir)
    q_embs = model.encode([role_queries[h] for h in HATS],
                          normalize_embeddings=True, show_progress_bar=False)
    query_emb = {h: q_embs[i] for i, h in enumerate(HATS)}

    # per-topic per-condition metric arrays
    store_centroid: dict[str, list[float]] = defaultdict(list)
    store_overlap: dict[str, list[float]] = defaultdict(list)
    retr_centroid: dict[str, list[float]] = defaultdict(list)
    retr_overlap: dict[str, list[float]] = defaultdict(list)
    store_sizes: dict[str, list[float]] = defaultdict(list)
    per_topic_rows: list[dict] = []
    topics_used: list[str] = []

    for topic in TOPICS:
        bear_key, naive_key = (topic, "bear"), (topic, "naive")
        if bear_key not in sessions or naive_key not in sessions:
            print(f"  SKIP {topic}: missing bear and/or naive session")
            continue

        bear_docs = load_hat_docs(sessions[bear_key][2], include_pdf)
        naive_docs = load_hat_docs(sessions[naive_key][2], include_pdf)
        if not bear_docs or not naive_docs:
            print(f"  SKIP {topic}: empty stores after filtering")
            continue

        shared_corpus = build_shared_corpus(naive_docs)
        if not shared_corpus:
            print(f"  SKIP {topic}: empty shared corpus")
            continue

        # ---- embed everything for this topic ----
        def embed(texts: list[str]) -> np.ndarray:
            return model.encode(texts, normalize_embeddings=True,
                                batch_size=256, show_progress_bar=False)

        bear_embs = {h: embed(d) for h, d in bear_docs.items()}
        naive_embs = {h: embed(d) for h, d in naive_docs.items()}
        shared_all = embed(shared_corpus)
        shared_dedup, _ = greedy_dedup(shared_all, shared_corpus, d_min)

        # ---- per-condition stores ----
        stores = {
            "bear": bear_embs,
            "naive": naive_embs,
            # every hat holds the identical global store
            "shared-store": {h: shared_dedup for h in HATS},
            "shared-full": {h: shared_all for h in HATS},
            "shared-context": {h: shared_all for h in HATS},
        }

        # ---- retrieved context per condition ----
        retrieved = {
            cond: {h: retrieve_top_k(st[h], query_emb[h], top_k)
                   for h in HATS if h in st and len(st[h])}
            for cond, st in stores.items()
        }
        # shared-context has no retrieval step: every agent sees everything
        retrieved["shared-context"] = {h: shared_all for h in HATS}

        row = {"topic": topic}
        for cond in CONDITIONS:
            sc = mean_pairwise_centroid(stores[cond])
            so = mean_pairwise_nn_overlap(stores[cond])
            rc = mean_pairwise_centroid(retrieved[cond])
            ro = mean_pairwise_nn_overlap(retrieved[cond])
            sz = float(np.mean([len(v) for v in stores[cond].values()]))

            store_centroid[cond].append(sc)
            store_overlap[cond].append(so)
            retr_centroid[cond].append(rc)
            retr_overlap[cond].append(ro)
            store_sizes[cond].append(sz)
            row.update({
                f"{cond}_store_centroid": sc, f"{cond}_store_overlap": so,
                f"{cond}_retr_centroid": rc, f"{cond}_retr_overlap": ro,
                f"{cond}_store_size": sz,
            })

        per_topic_rows.append(row)
        topics_used.append(topic)
        print(f"  {topic:<11} retrieved centroid: "
              f"bear={row['bear_retr_centroid']:.3f}  "
              f"naive={row['naive_retr_centroid']:.3f}  "
              f"shared-full={row['shared-full_retr_centroid']:.3f}  "
              f"shared-dedup={row['shared-store_retr_centroid']:.3f}")

    if not per_topic_rows:
        sys.exit("ERROR: no topics produced results.")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def summarize(arrs: dict[str, list[float]], name: str) -> dict:
        print(f"\n{'-' * 74}\n  {name}   (n={len(per_topic_rows)} topics)\n{'-' * 74}")
        print(f"  {'Condition':<34} {'Mean':>8}  {'95% CI':>18}")
        out = {}
        for cond in CONDITIONS:
            vals = arrs[cond]
            m = float(np.nanmean(vals))
            lo, hi = bootstrap_ci(vals)
            out[cond] = {"mean": m, "ci_low": lo, "ci_high": hi,
                         "per_topic": vals}
            print(f"  {CONDITION_LABELS[cond]:<34} {m:>8.3f}  "
                  f"[{lo:>7.3f}, {hi:>7.3f}]")
        # paired tests vs BEAR
        print(f"\n  Paired vs BEAR-guided (Wilcoxon signed-rank, n={len(per_topic_rows)}):")
        for cond in CONDITIONS[1:]:
            t = paired_test(arrs["bear"], arrs[cond])
            out[cond]["vs_bear"] = t
            pstr = "n/a" if np.isnan(t["p"]) else f"{t['p']:.4f}"
            print(f"    BEAR vs {CONDITION_LABELS[cond]:<34} "
                  f"diff={t['mean_diff']:+.3f}  p={pstr}  d={t['cohens_d']:+.2f}")
        return out

    results = {
        "store_centroid": summarize(store_centroid, "STORE-LEVEL centroid distance (higher = more differentiated)"),
        "store_overlap": summarize(store_overlap, "STORE-LEVEL NN overlap (lower = more differentiated)"),
        "retrieved_centroid": summarize(retr_centroid, "RETRIEVED-CONTEXT centroid distance (higher = more differentiated)"),
        "retrieved_overlap": summarize(retr_overlap, "RETRIEVED-CONTEXT NN overlap (lower = more differentiated)"),
        "store_size": summarize(store_sizes, "Mean per-agent store size (items)"),
    }

    print("\n" + "=" * 74)
    print("  NOTE: store-level differentiation for the two shared conditions is")
    print("  0 / 1.0 by construction (identical stores). Report it as an")
    print("  architectural property, not an empirical finding. The retrieved-")
    print("  context rows are the substantive comparison.")
    print("=" * 74)

    # ------------------------------------------------------------------
    # Sanity check against published numbers
    # ------------------------------------------------------------------
    pub = HERE / "results" / "interhat_v2.csv"
    if pub.exists() and include_pdf:
        import csv
        published = {}
        with open(pub) as f:
            for r in csv.DictReader(f):
                published[(r["topic"], r["condition"])] = float(r["centroid"])
        deltas = []
        for row in per_topic_rows:
            for cond in ("bear", "naive"):
                key = (row["topic"], cond)
                if key in published:
                    deltas.append(abs(row[f"{cond}_store_centroid"] - published[key]))
        if deltas:
            print(f"\n  Reproduction check vs interhat_v2.csv: "
                  f"max |delta| = {max(deltas):.4f} (expect < 0.005)")

    # ------------------------------------------------------------------
    # LaTeX table
    # ------------------------------------------------------------------
    rc = results["retrieved_centroid"]
    ro = results["retrieved_overlap"]
    print("\n" + "=" * 74)
    print("  LaTeX table fragment")
    print("=" * 74)
    print(r"""
\begin{table}[t]
\caption{Comparison against existing multi-agent knowledge-management
architectures. Metrics are computed on the context each agent actually
receives at generation time (top-$k$ retrieval with a role-specific query),
so architectures without per-agent stores are compared fairly rather than
scored as differentiation-zero by construction. Centroid distance higher is
more differentiated; NN overlap lower is more differentiated. Means over
""" + f"{len(per_topic_rows)}" + r""" topics with bootstrap 95\% CIs;
$p$-values are Wilcoxon signed-rank against BEAR-guided.}
\label{tab:arch-baselines}
\centering
\begin{tabular}{@{}lccc@{}}
\toprule
Architecture & Centroid dist. & NN overlap & $p$ vs BEAR \\
\midrule""")
    for cond in CONDITIONS:
        c, o = rc[cond], ro[cond]
        if cond == "bear":
            pstr = "---"
        else:
            pv = c.get("vs_bear", {}).get("p", float("nan"))
            pstr = "n/a" if np.isnan(pv) else (
                "$<0.001$" if pv < 0.001 else f"${pv:.3f}$")
        label = CONDITION_LABELS[cond].replace("&", r"\&")
        bold = r"\textbf{" if cond == "bear" else ""
        end = "}" if cond == "bear" else ""
        print(f"{label} & {bold}{c['mean']:.3f}{end} "
              f"[{c['ci_low']:.3f}, {c['ci_high']:.3f}] & "
              f"{bold}{o['mean']:.3f}{end} "
              f"[{o['ci_low']:.3f}, {o['ci_high']:.3f}] & {pstr} \\\\")
    print(r"""\bottomrule
\end{tabular}
\end{table}""")

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    OUT_DIR.mkdir(exist_ok=True)
    payload = {
        "metadata": {
            "eval": "architecture_baselines",
            "purpose": "Expert Systems R1 comment 3 — direct comparison with "
                       "existing multi-agent knowledge management methods",
            "embedding_model": EMBEDDING_MODEL,
            "top_k": top_k,
            "d_min": d_min,
            "include_pdf": include_pdf,
            "nn_sim_threshold": NN_SIM_THRESHOLD,
            "topics": topics_used,
            "n_topics": len(topics_used),
            "conditions": {c: CONDITION_LABELS[c] for c in CONDITIONS},
            "sessions": {f"{t}_{c}": sessions[(t, c)][0]
                         for (t, c) in sessions if t in topics_used},
        },
        "results": results,
        "per_topic": per_topic_rows,
    }
    suffix = "_withpdf" if include_pdf else ""
    jpath = OUT_DIR / f"architecture_baselines{suffix}.json"
    jpath.write_text(json.dumps(payload, indent=2, default=float),
                     encoding="utf-8")
    print(f"\n  JSON saved to: {jpath}")

    cpath = OUT_DIR / f"architecture_baselines{suffix}.csv"
    fields = ["topic"] + [
        f"{c}_{m}" for c in CONDITIONS
        for m in ("store_centroid", "store_overlap", "retr_centroid",
                  "retr_overlap", "store_size")
    ]
    with open(cpath, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(fields) + "\n")
        for row in per_topic_rows:
            f.write(",".join(
                row["topic"] if k == "topic" else f"{row.get(k, float('nan')):.4f}"
                for k in fields) + "\n")
    print(f"  CSV saved to:  {cpath}")
    print("\nDone.")
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                    help=f"Retrieval depth per agent (default {DEFAULT_TOP_K}, "
                         "matching KnowledgeStore.query).")
    ap.add_argument("--d-min", type=float, default=DEFAULT_DMIN,
                    help=f"Cosine dedup threshold for the shared store "
                         f"(default {DEFAULT_DMIN}).")
    ap.add_argument("--include-pdf", action="store_true",
                    help="Include per-hat ingested PDF chunks. Default is "
                         "diffusion-sourced documents only, which isolates "
                         "the mechanism under test. Use this flag to "
                         "reproduce the published interhat_v2 numbers.")
    args = ap.parse_args()
    run(top_k=args.top_k, d_min=args.d_min, include_pdf=args.include_pdf)


if __name__ == "__main__":
    main()
