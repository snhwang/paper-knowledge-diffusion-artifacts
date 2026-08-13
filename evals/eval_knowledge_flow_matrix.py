"""Role-differentiated knowledge flow: who absorbs from whom.

Motivation
----------
The paper's claim is not that BEAR retrieves better than other architectures.
It is that each agent maintains *its own memory with its own retention
preferences*. Store-content metrics are an awkward instrument for that claim
because BEAR rewrites what it stores, so embedding distance partly measures
vocabulary divergence introduced by the reframing LLM rather than genuine
selectivity.

This evaluation sidesteps that confound entirely. It never looks at stored
text. It only counts *decisions*: for each ordered pair (receiver, source),
how much of what the source said did the receiver actually retain?

Session logs record every diffusion decision as

    > *[Diffusion 08:09:53]* Red <- White: **stored** (dist=0.55) - <text>
    > *[Diffusion 08:10:04]* Black <- White: **skipped** (dist=0.35)

and turn headers give how many times each hat spoke. Retention rate for the
pair (receiver r, source s) is therefore

    retained(r, s) / utterances_spoken(s)

which is a pure count ratio. No embeddings, no LLM calls, no text comparison.

What the numbers mean
---------------------
Under unfiltered broadcast every hat stores everything from everyone, so the
matrix is flat and every receiver's source distribution is maximum entropy.
If BEAR-guided hats have genuine retention preferences, the matrix acquires
structure: some hats absorb heavily from some colleagues and barely at all
from others, and each receiver's source distribution has measurably lower
entropy than the naive baseline.

That structure IS the "role-differentiated knowledge flow" of the title, and
here it is measured as a flow matrix rather than inferred from store contents.

Outputs (paper/evaluation/results/)
    knowledge_flow_matrix.json   per-topic matrices, entropies, tests
    knowledge_flow_matrix.csv    long-form (topic, condition, receiver, source)
    knowledge_flow_matrix.pdf    6x6 heatmaps, BEAR vs naive

Usage:
    python eval_knowledge_flow_matrix.py
    python eval_knowledge_flow_matrix.py --no-figure
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "results"

# Candidates are tried in order; the first two are relative to this script so
# the evaluation is portable, and the absolute path is a development fallback.
DEFAULT_LOG_DIRS = [
    HERE.parent / "bear_parlor" / "session_logs",              # artifacts repo
    HERE.parent.parent / "examples" / "bear_parlor" / "session_logs",  # bear-dev
    Path(r"C:\Users\Scott\Documents\Work\paper-knowledge-diffusion-artifacts")
    / "bear_parlor" / "session_logs",
]

TOPICS = ["dmg", "stroke", "ms", "alzheimers", "epilepsy", "glp1", "crispr", "llm-cds"]
# Display order; log lines use the bare colour name.
HATS = ["White", "Red", "Black", "Yellow", "Green", "Blue"]

# > *[Diffusion 08:09:53]* Red <- White: **stored** (dist=0.55) - text
_DIFFUSION_RE = re.compile(
    r"\*\[Diffusion[^\]]*\]\*\s*"
    r"([A-Za-z]+)\s*"           # receiver
    r"(?:\u2190|<-|&larr;)\s*"  # arrow
    r"([A-Za-z]+)\s*:\s*"       # source
    r"\*\*(stored|skipped)\*\*"
)

# ### Turn 12 - Black-hat <sub>08:09:53</sub>
_TURN_RE = re.compile(
    r"^###\s+Turn\s+(\d+)\s*[\u2014\-]\s*([A-Za-z]+)",
    re.MULTILINE,
)


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


def resolve_dir(candidates: list[Path], what: str, validate=None) -> Path:
    for p in candidates:
        if p.exists() and (validate is None or validate(p)):
            return p
    sys.exit(f"ERROR: could not locate usable {what}. Tried:\n  " +
             "\n  ".join(str(c) for c in candidates))


def load_best_sessions(log_dir: Path) -> dict:
    """One session per (topic, condition); same rule as eval_interhat_v2.py."""
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
        if not md.exists():
            continue
        raw.append((ts, d, md))

    seen: dict = {}
    for ts, d, md in raw:
        key = (d["topic"], d["condition"])
        score = (int(d.get("completed") is True), d["n_turns"])
        if key not in seen or score > seen[key][3]:
            seen[key] = (ts, d, md, score)
    return {k: (v[0], v[1], v[2]) for k, v in seen.items()}


def norm_hat(name: str) -> str | None:
    """Normalise a log token to a canonical hat name."""
    n = name.strip().replace("-hat", "").replace("-Hat", "").capitalize()
    return n if n in HATS else None


def parse_session(md_path: Path) -> tuple[np.ndarray, dict[str, int]]:
    """Return (retained[receiver, source], spoken[source]).

    retained counts **stored** diffusion decisions; spoken counts turns taken
    by each hat, which is the denominator of the retention rate.
    """
    text = md_path.read_text(encoding="utf-8", errors="replace")

    spoken: dict[str, int] = defaultdict(int)
    for _, speaker in _TURN_RE.findall(text):
        hat = norm_hat(speaker)
        if hat:
            spoken[hat] += 1

    idx = {h: i for i, h in enumerate(HATS)}
    retained = np.zeros((len(HATS), len(HATS)), dtype=float)
    for recv_raw, src_raw, decision in _DIFFUSION_RE.findall(text):
        if decision != "stored":
            continue
        r, s = norm_hat(recv_raw), norm_hat(src_raw)
        if r is None or s is None or r == s:
            continue
        retained[idx[r], idx[s]] += 1

    return retained, dict(spoken)


def retention_rates(retained: np.ndarray, spoken: dict[str, int]) -> np.ndarray:
    """rate[r, s] = retained(r, s) / spoken(s); diagonal is NaN."""
    rate = np.full_like(retained, np.nan)
    for si, s in enumerate(HATS):
        denom = spoken.get(s, 0)
        if denom <= 0:
            continue
        for ri in range(len(HATS)):
            if ri == si:
                continue
            rate[ri, si] = retained[ri, si] / denom
    return rate


def row_entropy(rate_row: np.ndarray) -> float:
    """Normalised Shannon entropy of one receiver's source distribution.

    1.0 = absorbs uniformly from every colleague (no preference).
    0.0 = absorbs from exactly one colleague (maximal preference).
    """
    vals = np.array([v for v in rate_row if not np.isnan(v)], dtype=float)
    vals = vals[vals > 0]
    if len(vals) <= 1:
        return 0.0
    p = vals / vals.sum()
    h = -(p * np.log(p)).sum()
    return float(h / np.log(len(vals)))


def bootstrap_ci(values: list[float], n_boot: int = 10000,
                 seed: int = 20261025) -> tuple[float, float]:
    arr = np.asarray([v for v in values if not np.isnan(v)], dtype=float)
    if len(arr) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def paired_test(a: list[float], b: list[float]) -> dict:
    pairs = [(x, y) for x, y in zip(a, b) if not (np.isnan(x) or np.isnan(y))]
    if len(pairs) < 2:
        return {"n": len(pairs), "p": float("nan"), "cohens_d": float("nan"),
                "mean_diff": float("nan")}
    x = np.array([p[0] for p in pairs]); y = np.array([p[1] for p in pairs])
    diff = x - y
    sd = diff.std(ddof=1)
    d = float(diff.mean() / sd) if sd > 0 else float("inf")
    p = float("nan")
    if np.any(diff != 0):
        try:
            from scipy.stats import wilcoxon
            p = float(wilcoxon(x, y).pvalue)
        except ImportError:
            pass
        except ValueError:
            pass
    return {"n": len(pairs), "p": p, "cohens_d": d,
            "mean_diff": float(diff.mean())}


def chi_square_independence(retained: np.ndarray) -> dict:
    """Is retention independent of source? Off-diagonal cells only.

    Rejecting independence means receivers do not draw uniformly from their
    colleagues, i.e. they have source preferences.
    """
    try:
        from scipy.stats import chi2_contingency
    except ImportError:
        return {"chi2": float("nan"), "p": float("nan"), "cramers_v": float("nan")}
    # Flatten to a receivers x sources table, zeroing the diagonal.
    tbl = retained.copy()
    np.fill_diagonal(tbl, 0)
    # Drop all-zero rows/cols so the test is defined.
    keep_r = tbl.sum(axis=1) > 0
    keep_c = tbl.sum(axis=0) > 0
    tbl = tbl[np.ix_(keep_r, keep_c)]
    if tbl.shape[0] < 2 or tbl.shape[1] < 2 or tbl.sum() == 0:
        return {"chi2": float("nan"), "p": float("nan"), "cramers_v": float("nan")}
    try:
        chi2, p, dof, _ = chi2_contingency(tbl)
    except ValueError:
        return {"chi2": float("nan"), "p": float("nan"), "cramers_v": float("nan")}
    n = tbl.sum()
    v = float(np.sqrt(chi2 / (n * (min(tbl.shape) - 1)))) if n > 0 else float("nan")
    return {"chi2": float(chi2), "p": float(p), "dof": int(dof), "cramers_v": v}


def make_figure(mean_rate: dict[str, np.ndarray], out_path: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  NOTE: matplotlib unavailable, skipping figure.")
        return None

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    vmax = np.nanmax([np.nanmax(m) for m in mean_rate.values()])
    for ax, cond, title in [
        (axes[0], "bear", "BEAR-guided diffusion"),
        (axes[1], "naive", "Unfiltered broadcast"),
    ]:
        m = mean_rate[cond]
        im = ax.imshow(m, cmap="viridis", vmin=0, vmax=vmax)
        ax.set_xticks(range(len(HATS))); ax.set_xticklabels(HATS, rotation=45, ha="right")
        ax.set_yticks(range(len(HATS))); ax.set_yticklabels(HATS)
        ax.set_xlabel("Source (speaker)")
        if ax is axes[0]:
            ax.set_ylabel("Receiver (absorber)")
        ax.set_title(title, fontsize=11, fontweight="bold")
        for i in range(len(HATS)):
            for j in range(len(HATS)):
                if i == j:
                    ax.text(j, i, "--", ha="center", va="center",
                            color="0.6", fontsize=8)
                elif not np.isnan(m[i, j]):
                    ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                            color="white" if m[i, j] < vmax * 0.6 else "black",
                            fontsize=7.5)
    fig.colorbar(im, ax=axes, shrink=0.85,
                 label="Retention rate (items kept per utterance heard)")
    fig.suptitle("Role-differentiated knowledge flow: who absorbs from whom "
                 f"(mean over topics)", fontsize=11, y=1.02)
    fig.savefig(out_path, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".png"), bbox_inches="tight", dpi=150)
    print(f"  Figure saved to: {out_path}")
    return out_path


def run(make_fig: bool = True):
    log_dir = resolve_dir(DEFAULT_LOG_DIRS, "session_logs", has_labelled_sessions)
    print("=" * 74)
    print("  Role-differentiated knowledge flow — retention decision analysis")
    print(f"  logs={log_dir}")
    print("=" * 74)

    sessions = load_best_sessions(log_dir)

    per_topic: list[dict] = []
    rates: dict[str, list[np.ndarray]] = {"bear": [], "naive": []}
    counts: dict[str, list[np.ndarray]] = {"bear": [], "naive": []}
    entropies: dict[str, list[float]] = {"bear": [], "naive": []}
    per_hat_entropy: dict[str, dict[str, list[float]]] = {
        "bear": defaultdict(list), "naive": defaultdict(list)}
    topics_used: list[str] = []

    for topic in TOPICS:
        if (topic, "bear") not in sessions or (topic, "naive") not in sessions:
            print(f"  SKIP {topic}: missing a condition")
            continue

        row = {"topic": topic}
        ok = True
        staged = {}
        for cond in ("bear", "naive"):
            retained, spoken = parse_session(sessions[(topic, cond)][2])
            if retained.sum() == 0 or not spoken:
                print(f"  SKIP {topic}/{cond}: no diffusion decisions parsed")
                ok = False
                break
            rate = retention_rates(retained, spoken)
            ents = [row_entropy(rate[i]) for i in range(len(HATS))]
            staged[cond] = (retained, rate, ents, spoken)
        if not ok:
            continue

        for cond in ("bear", "naive"):
            retained, rate, ents, spoken = staged[cond]
            rates[cond].append(rate)
            counts[cond].append(retained)
            mean_ent = float(np.mean(ents))
            entropies[cond].append(mean_ent)
            for i, h in enumerate(HATS):
                per_hat_entropy[cond][h].append(ents[i])
            chi = chi_square_independence(retained)
            row[f"{cond}_mean_entropy"] = mean_ent
            row[f"{cond}_total_retained"] = float(retained.sum())
            row[f"{cond}_cramers_v"] = chi["cramers_v"]
            row[f"{cond}_chi2_p"] = chi["p"]

        per_topic.append(row)
        topics_used.append(topic)
        print(f"  {topic:<11} source-entropy  bear={row['bear_mean_entropy']:.3f}  "
              f"naive={row['naive_mean_entropy']:.3f}   "
              f"Cramer's V  bear={row['bear_cramers_v']:.3f}  "
              f"naive={row['naive_cramers_v']:.3f}")

    if not per_topic:
        sys.exit("ERROR: no topics parsed. Check the diffusion log format.")

    n = len(per_topic)
    with np.errstate(invalid="ignore"):
        import warnings
        with warnings.catch_warnings():
            # The diagonal is NaN in every topic by construction (a hat does
            # not diffuse to itself), so nanmean warns on an all-NaN slice.
            warnings.simplefilter("ignore", RuntimeWarning)
            mean_rate = {c: np.nanmean(np.stack(rates[c]), axis=0)
                         for c in ("bear", "naive")}
    pooled_counts = {c: np.sum(np.stack(counts[c]), axis=0)
                     for c in ("bear", "naive")}

    # ------------------------------------------------------------------
    print("\n" + "-" * 74)
    print(f"  SOURCE-SELECTIVITY  (normalised entropy, n={n} topics)")
    print("  1.0 = absorbs uniformly from all colleagues (no preference)")
    print("  lower = stronger, more selective retention preferences")
    print("-" * 74)
    for cond, label in (("bear", "BEAR-guided"), ("naive", "Unfiltered broadcast")):
        m = float(np.mean(entropies[cond]))
        lo, hi = bootstrap_ci(entropies[cond])
        print(f"  {label:<24} {m:>7.3f}  [{lo:.3f}, {hi:.3f}]")
    t_ent = paired_test(entropies["bear"], entropies["naive"])
    pstr = "n/a" if np.isnan(t_ent["p"]) else f"{t_ent['p']:.4f}"
    print(f"\n  Paired BEAR vs naive: diff={t_ent['mean_diff']:+.3f}  "
          f"p={pstr}  d={t_ent['cohens_d']:+.2f}")

    print("\n" + "-" * 74)
    print("  PER-HAT SOURCE SELECTIVITY (entropy; lower = more selective)")
    print("-" * 74)
    print(f"  {'Hat':<8} {'BEAR':>8} {'Naive':>8} {'diff':>8}")
    per_hat_summary = {}
    for h in HATS:
        b = float(np.mean(per_hat_entropy["bear"][h]))
        nv = float(np.mean(per_hat_entropy["naive"][h]))
        per_hat_summary[h] = {"bear": b, "naive": nv, "diff": b - nv,
                              "bear_per_topic": per_hat_entropy["bear"][h],
                              "naive_per_topic": per_hat_entropy["naive"][h]}
        print(f"  {h:<8} {b:>8.3f} {nv:>8.3f} {b - nv:>+8.3f}")

    print("\n" + "-" * 74)
    print("  RETENTION RATE MATRIX — items kept per utterance heard")
    print("  rows = receiver (absorber), cols = source (speaker)")
    print("-" * 74)
    for cond, label in (("bear", "BEAR-guided"), ("naive", "Unfiltered broadcast")):
        print(f"\n  {label}")
        print("  " + " " * 8 + "".join(f"{h:>9}" for h in HATS))
        for i, h in enumerate(HATS):
            cells = "".join(
                "     --  " if i == j else
                ("      .  " if np.isnan(mean_rate[cond][i, j])
                 else f"{mean_rate[cond][i, j]:>9.2f}")
                for j in range(len(HATS)))
            print(f"  {h:<8}{cells}")

    print("\n" + "-" * 74)
    print("  DEPENDENCE OF RETENTION ON SOURCE")
    print("  Cramer's V: 0 = retention independent of who spoke")
    print("-" * 74)
    pooled_chi = {}
    for cond, label in (("bear", "BEAR-guided"), ("naive", "Unfiltered broadcast")):
        vs = [r[f"{cond}_cramers_v"] for r in per_topic
              if not np.isnan(r[f"{cond}_cramers_v"])]
        lo, hi = bootstrap_ci(vs)
        pooled_chi[cond] = chi_square_independence(pooled_counts[cond])
        pc = pooled_chi[cond]
        pstr = "n/a" if np.isnan(pc["p"]) else (
            "<0.001" if pc["p"] < 0.001 else f"{pc['p']:.4f}")
        print(f"  {label:<24} V={np.mean(vs):.3f}  [{lo:.3f}, {hi:.3f}]  "
              f"(per-topic mean)")
        print(f"  {'':<24} pooled across {n} topics: N={pooled_counts[cond].sum():.0f}, "
              f"chi2={pc['chi2']:.1f}, df={pc.get('dof', 0)}, p={pstr}")
    print("\n  Per-topic chi-square is underpowered (31-66 retained items over a")
    print("  30-cell table, expected counts ~1-2), so only the pooled test is")
    print("  interpretable. Per-topic Cramer's V is reported descriptively and")
    print("  compared across topics with a paired test below.")
    t_v = paired_test([r["bear_cramers_v"] for r in per_topic],
                      [r["naive_cramers_v"] for r in per_topic])
    pstr_v = "n/a" if np.isnan(t_v["p"]) else f"{t_v['p']:.4f}"
    print(f"\n  Paired BEAR vs naive (Cramer's V): diff={t_v['mean_diff']:+.3f}  "
          f"p={pstr_v}  d={t_v['cohens_d']:+.2f}")

    print("\n" + "=" * 74)
    print("  This analysis counts retention DECISIONS only. It never compares")
    print("  stored text, so it is immune to the objection that BEAR's")
    print("  advantage comes from the reframing LLM injecting role-specific")
    print("  vocabulary into what it stores.")
    print("=" * 74)

    # ------------------------------------------------------------------
    OUT_DIR.mkdir(exist_ok=True)
    payload = {
        "metadata": {
            "eval": "knowledge_flow_matrix",
            "purpose": "Measure per-agent retention preferences from diffusion "
                       "decisions, independent of stored text",
            "hats": HATS,
            "topics": topics_used,
            "n_topics": n,
            "sessions": {f"{t}_{c}": sessions[(t, c)][0]
                         for (t, c) in sessions if t in topics_used},
        },
        "source_entropy": {
            c: {"mean": float(np.mean(entropies[c])),
                "ci": bootstrap_ci(entropies[c]),
                "per_topic": entropies[c]}
            for c in ("bear", "naive")
        },
        "entropy_bear_vs_naive": t_ent,
        "cramers_v_bear_vs_naive": t_v,
        "pooled_chi_square": {c: pooled_chi[c] for c in ("bear", "naive")},
        "pooled_counts": {c: pooled_counts[c].tolist() for c in ("bear", "naive")},
        "per_hat_entropy": per_hat_summary,
        "mean_retention_rate": {c: mean_rate[c].tolist() for c in ("bear", "naive")},
        "per_topic": per_topic,
    }
    jpath = OUT_DIR / "knowledge_flow_matrix.json"
    jpath.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    print(f"\n  JSON saved to: {jpath}")

    cpath = OUT_DIR / "knowledge_flow_matrix.csv"
    with open(cpath, "w", encoding="utf-8", newline="") as f:
        f.write("topic,condition,receiver,source,retention_rate\n")
        for cond in ("bear", "naive"):
            for ti, topic in enumerate(topics_used):
                m = rates[cond][ti]
                for i, r in enumerate(HATS):
                    for j, s in enumerate(HATS):
                        if i == j or np.isnan(m[i, j]):
                            continue
                        f.write(f"{topic},{cond},{r},{s},{m[i, j]:.4f}\n")
    print(f"  CSV saved to:  {cpath}")

    if make_fig:
        make_figure(mean_rate, OUT_DIR / "knowledge_flow_matrix.pdf")

    print("\nDone.")
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-figure", action="store_true", help="Skip the heatmap.")
    args = ap.parse_args()
    run(make_fig=not args.no_figure)


if __name__ == "__main__":
    main()
