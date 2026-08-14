"""Inter-hat store differentiation — single reconciled measurement.

WHY THIS SCRIPT EXISTS
----------------------
Two earlier scripts measured inter-hat differentiation and disagreed, and the
published Table drew one column from each:

  eval_interhat_differentiation.py ("v1")
      Data:   session log MARKDOWN, parsed for diffusion events.
      Corpus: 16 sessions hardcoded from 2026-04-06. Those logs have no
              .knowledge.json and no .stats.json, so the per-hat stores are
              reconstructed from the log text rather than read.
      Overlap metric: cosine DISTANCE < 0.35, i.e. similarity > 0.65.
      Reported: centroid BEAR 0.096 / naive 0.010, overlap 0.930 / 0.980.

  eval_interhat_v2.py ("v2")
      Data:   .knowledge.json snapshots, the actual per-hat ChromaDB stores.
      Corpus: 2026-04-10/11 sessions, selected by topic/condition metadata.
      Overlap metric: cosine SIMILARITY >= 0.85.
      Reported: centroid BEAR 0.080 / naive 0.021, overlap 0.055 / 0.706.

The published table took its centroid column from v1 and its NN-overlap column
from v2. Those are different experimental runs measured different ways, so the
two columns were not mutually consistent.

RECONCILIATION
--------------
This script supersedes both. It measures every metric from one corpus with one
method:

  * Corpus: the 2026-04-10/11 sessions, selected exactly as v2 selects them
    (one session per topic/condition, preferring completed runs then more
    turns). This is the only corpus with .knowledge.json, i.e. the only one
    where the per-hat stores are read rather than reconstructed, and it is the
    corpus every other current analysis uses.

  * Items: the documents actually held in each hat's store.

  * NN overlap: fraction of a store's items having a near-duplicate in the
    other store at cosine similarity >= 0.85. This is the definition stated in
    the manuscript's table caption, and it is v2's definition, not v1's.

  * Centroid distance: cosine distance between the (L2-normalised) mean
    embedding of each pair of stores.

Statistics are paired across the 8 topics: paired t-test (as originally
reported) plus Wilcoxon signed-rank, Cohen's d, and bootstrap 95% CIs.

Outputs:
    results/interhat_reconciled.json
    results/interhat_reconciled.csv
    console summary + LaTeX table fragment

Usage:
    python eval_interhat_reconciled.py
    python eval_interhat_reconciled.py --diffusion-only
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "results"

DEFAULT_LOG_DIRS = [
    HERE.parent / "bear_parlor" / "session_logs",                      # artifacts
    HERE.parent.parent / "examples" / "bear_parlor" / "session_logs",  # bear-dev
    Path(r"C:\Users\Scott\Documents\Work\paper-knowledge-diffusion-artifacts")
    / "bear_parlor" / "session_logs",
]

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
TOPICS = ["dmg", "stroke", "ms", "alzheimers", "epilepsy", "glp1", "crispr", "llm-cds"]
HATS = ["white-hat", "red-hat", "black-hat", "blue-hat", "green-hat", "yellow-hat"]
NN_SIM_THRESHOLD = 0.85


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
    """One session per (topic, condition): completed first, then most turns."""
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


def load_hat_docs(kj_path: Path, diffusion_only: bool) -> dict[str, list[str]]:
    kj = json.loads(kj_path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for hat in HATS:
        entry = kj.get(hat, {})
        docs = entry.get("documents", []) or []
        metas = entry.get("metadatas", []) or []
        if diffusion_only and metas:
            docs = [d for d, m in zip(docs, metas)
                    if (m or {}).get("source") != "pdf"]
        if docs:
            out[hat] = docs
    return out


def centroid_distance(hat_embs: dict[str, np.ndarray]) -> float:
    hats = [h for h in HATS if h in hat_embs and len(hat_embs[h])]
    if len(hats) < 2:
        return float("nan")
    cents = {}
    for h in hats:
        c = np.asarray(hat_embs[h]).mean(axis=0)
        cents[h] = c / (np.linalg.norm(c) + 1e-10)
    return float(np.mean([1.0 - float(np.dot(cents[a], cents[b]))
                          for a, b in combinations(hats, 2)]))


def nn_overlap(hat_embs: dict[str, np.ndarray],
               thr: float = NN_SIM_THRESHOLD) -> float:
    hats = [h for h in HATS if h in hat_embs and len(hat_embs[h])]
    if len(hats) < 2:
        return float("nan")
    vals = []
    for a, b in combinations(hats, 2):
        ea, eb = np.asarray(hat_embs[a]), np.asarray(hat_embs[b])
        ab = float(((ea @ eb.T).max(axis=1) >= thr).mean())
        ba = float(((eb @ ea.T).max(axis=1) >= thr).mean())
        vals.append((ab + ba) / 2)
    return float(np.mean(vals))


def bootstrap_ci(vals, n_boot=10000, seed=20261025):
    arr = np.asarray([v for v in vals if not np.isnan(v)], dtype=float)
    if len(arr) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    m = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return (float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)))


def paired_stats(a, b) -> dict:
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    diff = x - y
    sd = diff.std(ddof=1)
    out = {"n": len(x), "mean_diff": float(diff.mean()),
           "cohens_d": float(diff.mean() / sd) if sd > 0 else float("inf")}
    try:
        from scipy.stats import ttest_rel, wilcoxon
        out["t_p"] = float(ttest_rel(x, y).pvalue)
        out["wilcoxon_p"] = float(wilcoxon(x, y).pvalue)
    except ImportError:
        out["t_p"] = out["wilcoxon_p"] = float("nan")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--diffusion-only", action="store_true",
                    help="Exclude per-hat ingested PDF chunks. Default keeps "
                         "all stored items, matching the published table.")
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer

    log_dir = resolve_dir(DEFAULT_LOG_DIRS, "session_logs", has_labelled_sessions)
    print("=" * 72)
    print("  Inter-hat store differentiation (reconciled)")
    print(f"  corpus: {log_dir}")
    print(f"  items:  {'diffusion-sourced only' if args.diffusion_only else 'all stored items'}")
    print(f"  NN overlap threshold: cosine similarity >= {NN_SIM_THRESHOLD}")
    print("=" * 72)

    sessions = load_best_sessions(log_dir)
    model = SentenceTransformer(EMBEDDING_MODEL)

    rows, topics_used = [], []
    per_cond = {"bear": {"c": [], "o": [], "n": []},
                "naive": {"c": [], "o": [], "n": []}}

    for topic in TOPICS:
        if (topic, "bear") not in sessions or (topic, "naive") not in sessions:
            print(f"  SKIP {topic}: missing a condition")
            continue
        row = {"topic": topic}
        ok = True
        for cond in ("bear", "naive"):
            docs = load_hat_docs(sessions[(topic, cond)][2], args.diffusion_only)
            if not docs:
                ok = False
                break
            embs = {h: model.encode(v, normalize_embeddings=True,
                                    batch_size=256, show_progress_bar=False)
                    for h, v in docs.items()}
            c, o = centroid_distance(embs), nn_overlap(embs)
            n = float(np.mean([len(v) for v in embs.values()]))
            per_cond[cond]["c"].append(c)
            per_cond[cond]["o"].append(o)
            per_cond[cond]["n"].append(n)
            row.update({f"{cond}_centroid": c, f"{cond}_nn_overlap": o,
                        f"{cond}_items_per_hat": n})
        if not ok:
            continue
        rows.append(row)
        topics_used.append(topic)
        print(f"  {topic:<11} centroid bear={row['bear_centroid']:.4f} "
              f"naive={row['naive_centroid']:.4f} | overlap "
              f"bear={row['bear_nn_overlap']:.4f} naive={row['naive_nn_overlap']:.4f}")

    if not rows:
        sys.exit("ERROR: no topics produced results.")
    n = len(rows)

    print("\n" + "-" * 72)
    print(f"  POOLED ACROSS {n} TOPICS (mean +/- SD, bootstrap 95% CI)")
    print("-" * 72)
    summary = {}
    for key, label, better in (("c", "Centroid distance", "higher"),
                               ("o", "NN overlap", "lower"),
                               ("n", "Items per hat", "")):
        b, nv = per_cond["bear"][key], per_cond["naive"][key]
        bl, bh = bootstrap_ci(b)
        nl, nh = bootstrap_ci(nv)
        st = paired_stats(b, nv)
        summary[key] = {
            "bear": {"mean": float(np.mean(b)), "sd": float(np.std(b, ddof=1)),
                     "ci": [bl, bh], "per_topic": b},
            "naive": {"mean": float(np.mean(nv)), "sd": float(np.std(nv, ddof=1)),
                      "ci": [nl, nh], "per_topic": nv},
            "paired": st,
        }
        arrow = f" ({better} = more differentiated)" if better else ""
        print(f"\n  {label}{arrow}")
        print(f"    BEAR-guided  {np.mean(b):.4f} +/- {np.std(b, ddof=1):.4f}"
              f"   [{bl:.4f}, {bh:.4f}]")
        print(f"    Naive        {np.mean(nv):.4f} +/- {np.std(nv, ddof=1):.4f}"
              f"   [{nl:.4f}, {nh:.4f}]")
        if np.mean(nv) != 0:
            print(f"    Ratio (BEAR/Naive)  {np.mean(b) / np.mean(nv):.2f}x")
        print(f"    paired t p={st['t_p']:.3e}  Wilcoxon p={st['wilcoxon_p']:.4f}"
              f"  d={st['cohens_d']:+.2f}")

    # ------------------------------------------------------------------
    c, o = summary["c"], summary["o"]
    print("\n" + "=" * 72)
    print("  LaTeX table fragment (replaces tab:interhat)")
    print("=" * 72)
    print(r"""
\begin{tabular}{@{}lcc@{}}
\toprule
Condition & Centroid Dist & NN Overlap \\
\midrule""")
    print(f"BEAR-guided & ${c['bear']['mean']:.3f} \\pm {c['bear']['sd']:.3f}$ "
          f"& ${o['bear']['mean']:.3f} \\pm {o['bear']['sd']:.3f}$ \\\\")
    print(f"Naive       & ${c['naive']['mean']:.3f} \\pm {c['naive']['sd']:.3f}$ "
          f"& ${o['naive']['mean']:.3f} \\pm {o['naive']['sd']:.3f}$ \\\\")
    print(r"\midrule")
    print(f"\\textbf{{Ratio (BEAR/Naive)}} & "
          f"\\textbf{{{c['bear']['mean'] / c['naive']['mean']:.1f}$\\times$}} & "
          f"\\textbf{{{o['bear']['mean'] / o['naive']['mean']:.2f}$\\times$}} \\\\")
    print(r"\midrule")
    print(f"$p$ (paired $t$-test, $n{{=}}{n}$) & ${c['paired']['t_p']:.2e}$ "
          f"& ${o['paired']['t_p']:.2e}$ \\\\")
    print(r"""\bottomrule
\end{tabular}""".replace("e-0", r"\times 10^{-"))

    # ------------------------------------------------------------------
    OUT_DIR.mkdir(exist_ok=True)
    payload = {
        "metadata": {
            "eval": "interhat_reconciled",
            "supersedes": ["eval_interhat_differentiation.py (v1)",
                           "eval_interhat_v2.py (v2)"],
            "why": "v1 and v2 measured different corpora with different overlap "
                   "definitions; the published table took centroid from v1 and "
                   "NN overlap from v2.",
            "embedding_model": EMBEDDING_MODEL,
            "nn_sim_threshold": NN_SIM_THRESHOLD,
            "diffusion_only": args.diffusion_only,
            "n_topics": n,
            "topics": topics_used,
            "sessions": {f"{t}_{cd}": sessions[(t, cd)][0]
                         for (t, cd) in sessions if t in topics_used},
        },
        "summary": summary,
        "per_topic": rows,
    }
    suffix = "_diffusion_only" if args.diffusion_only else ""
    jp = OUT_DIR / f"interhat_reconciled{suffix}.json"
    jp.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    print(f"\n  JSON saved to: {jp}")

    cp = OUT_DIR / f"interhat_reconciled{suffix}.csv"
    fields = ["topic"] + [f"{c}_{m}" for c in ("bear", "naive")
                          for m in ("centroid", "nn_overlap", "items_per_hat")]
    with open(cp, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(fields) + "\n")
        for r in rows:
            f.write(",".join(r["topic"] if k == "topic" else f"{r[k]:.4f}"
                             for k in fields) + "\n")
    print(f"  CSV saved to:  {cp}")
    print("\nDone.")


if __name__ == "__main__":
    main()
