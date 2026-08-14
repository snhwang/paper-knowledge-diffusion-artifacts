"""Temporal store evolution — reconciled onto the canonical corpus.

WHY THIS SCRIPT EXISTS
----------------------
`eval_temporal_evolution.py` hardcodes a SESSION_MAP of 2026-04-06 sessions,
so the store-growth panel of the published figure came from that corpus, while
the centroid curves shipped in `centroid_curves.json` were computed from the
2026-04-10/11 sessions. The two panels of one figure therefore described
different experiments, and neither matched the corpus used by every other
current analysis.

This script rebuilds both panels from the canonical corpus: the 2026-04-10/11
sessions selected by topic/condition metadata, the same set used by
`eval_interhat_reconciled.py`.

A NOTE ON WHAT THE CURVES CAN AND CANNOT SHOW
---------------------------------------------
Per-turn evolution cannot be read from `.knowledge.json`, which is only a
final snapshot. It has to be reconstructed by parsing the logged diffusion
events. That reconstruction covers diffusion-sourced items only: it cannot see
the literature chunks White Hat ingests directly, because those never appear
as diffusion events.

The endpoint of these curves therefore corresponds to the *diffusion-only*
measurement in `eval_interhat_reconciled.py --diffusion-only`, not to the
all-items values in the manuscript's Table 4. This script prints both so the
relationship is explicit rather than implied, and reports how closely the
reconstructed final item counts track the actual stores.

Outputs:
    results/temporal_reconciled.{pdf,png}
    results/temporal_reconciled.json

Usage:
    python eval_temporal_reconciled.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "results"

DEFAULT_LOG_DIRS = [
    HERE.parent / "bear_parlor" / "session_logs",
    HERE.parent.parent / "examples" / "bear_parlor" / "session_logs",
    Path(r"C:\Users\Scott\Documents\Work\paper-knowledge-diffusion-artifacts")
    / "bear_parlor" / "session_logs",
]

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
TOPICS = ["dmg", "stroke", "ms", "alzheimers", "epilepsy", "glp1", "crispr", "llm-cds"]
HATS = ["White", "Red", "Black", "Yellow", "Green", "Blue"]
HAT_KEY = {h: f"{h.lower()}-hat" for h in HATS}

BEAR_COLOR = "#20808D"
NAIVE_COLOR = "#A84B2F"

_TURN_RE = re.compile(r"^###\s+Turn\s+(\d+)", re.MULTILINE)
_DIFF_RE = re.compile(
    r"\*\[Diffusion[^\]]*\]\*\s*([A-Za-z]+)\s*(?:\u2190|<-)\s*"
    r"([A-Za-z]+):\s*\*\*stored\*\*(?:\s*\(dist=[\d.]+\))?\s*[\u2014-]\s*(.+)"
)


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
    sys.exit(f"ERROR: could not locate usable {what}.")


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
        md = log_dir / f"brainstorming-hats_{ts}.md"
        kj = log_dir / f"brainstorming-hats_{ts}.knowledge.json"
        if not md.exists() or not kj.exists():
            continue
        raw.append((ts, d, md, kj))
    seen: dict = {}
    for ts, d, md, kj in raw:
        key = (d["topic"], d["condition"])
        score = (int(d.get("completed") is True), d["n_turns"])
        if key not in seen or score > seen[key][4]:
            seen[key] = (ts, d, md, kj, score)
    return {k: v[:4] for k, v in seen.items()}


def parse_turn_events(md_path: Path) -> list[tuple[int, str, str]]:
    """Return [(turn, receiving_hat, stored_text), ...] in log order."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    marks = [(m.start(), int(m.group(1))) for m in _TURN_RE.finditer(text)]
    events = []
    for m in _DIFF_RE.finditer(text):
        pos = m.start()
        turn = 0
        for start, t in marks:
            if start <= pos:
                turn = t
            else:
                break
        hat = m.group(1).strip().capitalize()
        if hat in HATS:
            events.append((turn, hat, m.group(3).strip()))
    return events


def mean_pairwise_centroid(store: dict[str, list[np.ndarray]]) -> float:
    hats = [h for h in HATS if store.get(h)]
    if len(hats) < 2:
        return float("nan")
    cents = {}
    for h in hats:
        c = np.mean(np.stack(store[h]), axis=0)
        cents[h] = c / (np.linalg.norm(c) + 1e-10)
    return float(np.mean([1.0 - float(np.dot(cents[a], cents[b]))
                          for a, b in combinations(hats, 2)]))


def pad_stats(curves: list[list[float]]):
    n = max(len(c) for c in curves)
    arr = np.array([c + [c[-1]] * (n - len(c)) for c in curves], dtype=float)
    for row in arr:
        last = np.nan
        for i in range(len(row)):
            if not np.isnan(row[i]):
                last = row[i]
            elif not np.isnan(last):
                row[i] = last
    return np.arange(1, n + 1), np.nanmean(arr, axis=0), np.nanstd(arr, axis=0)


def main():
    from sentence_transformers import SentenceTransformer

    log_dir = resolve_dir(DEFAULT_LOG_DIRS, "session_logs", has_labelled_sessions)
    print("=" * 72)
    print("  Temporal store evolution (reconciled)")
    print(f"  corpus: {log_dir}")
    print("=" * 72)

    sessions = load_best_sessions(log_dir)
    model = SentenceTransformer(EMBEDDING_MODEL)

    size_curves = {"bear": [], "naive": []}
    cent_curves = {"bear": [], "naive": []}
    endpoints = {"bear": {"c": [], "n": [], "kj": []},
                 "naive": {"c": [], "n": [], "kj": []}}
    topics_used = []

    for topic in TOPICS:
        if (topic, "bear") not in sessions or (topic, "naive") not in sessions:
            continue
        ok = True
        staged = {}
        for cond in ("bear", "naive"):
            _, _, md, kj = sessions[(topic, cond)]
            events = parse_turn_events(md)
            if not events:
                ok = False
                break
            embs = model.encode([e[2] for e in events], normalize_embeddings=True,
                                batch_size=256, show_progress_bar=False)
            max_turn = max(e[0] for e in events)
            store: dict[str, list[np.ndarray]] = defaultdict(list)
            sizes, cents = [], []
            for tn in range(1, max_turn + 1):
                for i, (t, hat, _) in enumerate(events):
                    if t == tn:
                        store[hat].append(embs[i])
                sizes.append(float(np.mean([len(store.get(h, [])) for h in HATS])))
                cents.append(mean_pairwise_centroid(store))
            # ground truth: diffusion-sourced item count from the real store
            kjd = json.loads(kj.read_text(encoding="utf-8"))
            kj_counts = []
            for h in HATS:
                e = kjd.get(HAT_KEY[h], {})
                docs, metas = e.get("documents", []) or [], e.get("metadatas", []) or []
                kj_counts.append(sum(1 for m in metas if (m or {}).get("source") != "pdf")
                                 if metas else len(docs))
            staged[cond] = (sizes, cents, float(np.mean(kj_counts)))
        if not ok:
            continue
        for cond, (sizes, cents, kjn) in staged.items():
            size_curves[cond].append(sizes)
            cent_curves[cond].append(cents)
            endpoints[cond]["n"].append(sizes[-1])
            endpoints[cond]["c"].append(cents[-1])
            endpoints[cond]["kj"].append(kjn)
        topics_used.append(topic)
        print(f"  {topic:<11} final centroid bear={staged['bear'][1][-1]:.4f} "
              f"naive={staged['naive'][1][-1]:.4f}")

    if not topics_used:
        sys.exit("ERROR: no topics parsed.")

    print("\n" + "-" * 72)
    print("  FINAL-TURN VALUES (mean over %d topics)" % len(topics_used))
    print("-" * 72)
    summary = {}
    for cond in ("bear", "naive"):
        c = float(np.mean(endpoints[cond]["c"]))
        n = float(np.mean(endpoints[cond]["n"]))
        kj = float(np.mean(endpoints[cond]["kj"]))
        summary[cond] = {"centroid": c, "items_reconstructed": n,
                         "items_in_store": kj}
        print(f"  {cond:<6} centroid {c:.4f}   items: reconstructed {n:.1f} "
              f"vs actual store {kj:.1f}")
    ratio = summary["bear"]["centroid"] / summary["naive"]["centroid"]
    bloat = summary["naive"]["items_reconstructed"] / summary["bear"]["items_reconstructed"]
    print(f"\n  centroid ratio (BEAR/naive): {ratio:.1f}x")
    print(f"  store bloat  (naive/BEAR):   {bloat:.2f}x")
    print("\n  These curves reconstruct diffusion-sourced items only, so compare")
    print("  them with `eval_interhat_reconciled.py --diffusion-only`, not with")
    print("  the all-items Table 4 values.")

    # ------------------------------------------------------------------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, data, ylabel, title in (
        (axes[0], size_curves, "Cumulative items per hat", "Knowledge store growth"),
        (axes[1], cent_curves, "Mean pairwise centroid distance",
         "Inter-hat store differentiation"),
    ):
        for cond, color, label in (("naive", NAIVE_COLOR, "Naive"),
                                   ("bear", BEAR_COLOR, "BEAR-guided")):
            cl = data[cond]
            if not cl:
                continue
            x, mean, sd = pad_stats(cl)
            for c in cl:
                ax.plot(range(1, len(c) + 1), c, color=color, alpha=0.12, lw=0.8)
            ax.fill_between(x, np.clip(mean - sd, 0, None), mean + sd,
                            color=color, alpha=0.18)
            ax.plot(x, mean, color=color, lw=2.2,
                    label=f"{label} (final {mean[-1]:.3g})")
        ax.set_xlabel("Turn")
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.legend(fontsize=9)
        ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
        ax.grid(axis="y", linestyle="--", alpha=0.35)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

    fig.suptitle(f"Mean $\\pm$ 1 SD across {len(topics_used)} topics "
                 "(diffusion-sourced items)", fontsize=10, y=1.02)
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "temporal_reconciled.pdf"
    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight", dpi=150)
    print(f"\n  Figure saved to: {out}")

    (OUT_DIR / "temporal_reconciled.json").write_text(json.dumps({
        "metadata": {"eval": "temporal_reconciled",
                     "supersedes": "eval_temporal_evolution.py (2026-04-06 corpus)",
                     "n_topics": len(topics_used), "topics": topics_used,
                     "items": "diffusion-sourced only (reconstructed from logs)"},
        "final_turn": summary,
        "centroid_ratio": ratio, "store_bloat": bloat,
        "size_curves": size_curves, "centroid_curves": cent_curves,
    }, indent=2, default=float), encoding="utf-8")
    print("  JSON saved.")


if __name__ == "__main__":
    main()
