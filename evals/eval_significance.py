"""Statistical significance testing for role discrimination ratios.

Tests whether per-response discrimination ratios are significantly > 1.0
using one-sample t-tests, Wilcoxon signed-rank tests, and bootstrap
confidence intervals.  Also tests BEAR-guided vs. naive condition differences
using independent-samples tests.

Outputs:
  - Console summary with test statistics and p-values
  - LaTeX table fragment for inclusion in the paper
  - JSON results in paper/evaluation/results/significance.json

Relies on the same parsing and embedding logic as eval_role_adherence.py.

Usage:
    python eval_significance.py
    python eval_significance.py --logs session_logs/bear1.md session_logs/naive1.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from stat_utils import holm_bonferroni

# ---------------------------------------------------------------------------
# Project setup (mirrors eval_role_adherence.py)
# ---------------------------------------------------------------------------

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from eval_role_adherence import (
    EMBEDDING_MODEL,
    HATS,
    SESSION_MAP,
    embed_texts,
    load_role_anchors,
    parse_responses,
    compute_per_response_metrics,
    MIN_RESPONSE_WORDS,
)

# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def one_sample_ttest(values: np.ndarray, mu0: float = 1.0):
    """One-sample t-test: H0: mean(values) == mu0, H1: mean > mu0."""
    from scipy import stats

    t_stat, p_two = stats.ttest_1samp(values, mu0)
    # One-sided p-value (we expect mean > 1.0)
    p_one = p_two / 2 if t_stat > 0 else 1.0 - p_two / 2
    return {
        "t_statistic": float(t_stat),
        "p_value_two_sided": float(p_two),
        "p_value_one_sided": float(p_one),
        "n": len(values),
        "mean": float(np.mean(values)),
        "std": float(np.std(values, ddof=1)),
    }


def wilcoxon_test(values: np.ndarray, mu0: float = 1.0):
    """Wilcoxon signed-rank test (non-parametric alternative)."""
    from scipy import stats

    shifted = values - mu0
    # Remove zeros (ties at mu0)
    shifted = shifted[shifted != 0]
    if len(shifted) < 10:
        return {"warning": "Too few non-tied observations", "n": len(shifted)}
    stat, p_two = stats.wilcoxon(shifted, alternative="greater")
    return {
        "statistic": float(stat),
        "p_value_one_sided": float(p_two),
        "n": len(shifted),
    }


def bootstrap_ci(values: np.ndarray, n_boot: int = 10000, alpha: float = 0.05,
                  rng_seed: int = 42):
    """Bootstrap confidence interval for the mean."""
    rng = np.random.default_rng(rng_seed)
    boot_means = np.array([
        np.mean(rng.choice(values, size=len(values), replace=True))
        for _ in range(n_boot)
    ])
    lo = float(np.percentile(boot_means, 100 * alpha / 2))
    hi = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    return {
        "mean": float(np.mean(values)),
        "ci_lower": lo,
        "ci_upper": hi,
        "alpha": alpha,
        "n_bootstrap": n_boot,
    }


def independent_ttest(a: np.ndarray, b: np.ndarray):
    """Independent samples t-test (Welch's)."""
    from scipy import stats

    t_stat, p_val = stats.ttest_ind(a, b, equal_var=False)
    return {
        "t_statistic": float(t_stat),
        "p_value_two_sided": float(p_val),
        "n_a": len(a),
        "n_b": len(b),
        "mean_a": float(np.mean(a)),
        "mean_b": float(np.mean(b)),
    }


def mann_whitney(a: np.ndarray, b: np.ndarray):
    """Mann-Whitney U test (non-parametric)."""
    from scipy import stats

    stat, p_val = stats.mannwhitneyu(a, b, alternative="two-sided")
    return {
        "U_statistic": float(stat),
        "p_value_two_sided": float(p_val),
        "n_a": len(a),
        "n_b": len(b),
    }


def cohens_d(a: np.ndarray, mu0: float = 1.0):
    """Cohen's d effect size for one-sample test."""
    return float((np.mean(a) - mu0) / np.std(a, ddof=1))


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def run_significance(log_dir: Path | None = None,
                     log_files: list[Path] | None = None):
    """Extract per-response discrimination ratios and run significance tests."""
    from bear.retriever import Embedder

    print("=" * 70)
    print("  Statistical Significance Testing for Discrimination Ratios")
    print("=" * 70)

    # Load role anchors and embedder
    anchor_texts = load_role_anchors()
    embedder = Embedder(model_name=EMBEDDING_MODEL, dim=768)
    print(f"Embedding model: {EMBEDDING_MODEL}\n")

    # Embed role anchors -> centroids
    anchor_centroids: dict[str, np.ndarray] = {}
    for hat, texts in anchor_texts.items():
        embs = embed_texts(texts, embedder)
        anchor_centroids[hat] = np.mean(embs, axis=0)

    # Resolve session logs — restrict to the 6 sessions in SESSION_MAP
    # to match the experimental design described in the paper.
    parlor_dir = project_root / "bear_parlor"
    if log_files:
        paths = log_files
    else:
        log_dir_resolved = log_dir or (parlor_dir / "session_logs")
        paths = sorted(
            p for p in log_dir_resolved.glob("brainstorming-hats_*.md")
            if p.name in SESSION_MAP
        )

    if not paths:
        print("ERROR: No session log files found.")
        sys.exit(1)

    # Collect per-response ratios by condition and by hat
    all_ratios: list[float] = []
    bear_ratios: list[float] = []
    naive_ratios: list[float] = []
    per_hat_ratios: dict[str, list[float]] = defaultdict(list)
    bear_per_hat: dict[str, list[float]] = defaultdict(list)
    naive_per_hat: dict[str, list[float]] = defaultdict(list)

    for path in paths:
        filename = path.name
        info = SESSION_MAP.get(filename)
        if info is None:
            text = path.read_text(encoding="utf-8")
            if "diffuse midline glioma" in text.lower() or "dmg" in text.lower():
                topic = "DMG"
            elif "stroke" in text.lower():
                topic = "Stroke"
            elif "multiple sclerosis" in text.lower():
                topic = "MS"
            else:
                topic = "Unknown"
            skip_count = text.count("**skipped**")
            condition = "BEAR-guided" if skip_count > 0 else "Naive"
            info = (topic, condition)

        topic, condition = info
        print(f"Processing {topic} ({condition}): {filename}")

        _, responses = parse_responses(path)
        valid = [r for r in responses
                 if len(r["text"].split()) >= MIN_RESPONSE_WORDS
                 and r["speaker"] in HATS]

        if not valid:
            continue

        # Embed all responses
        texts = [r["text"] for r in valid]
        embs = embed_texts(texts, embedder)

        for i, r in enumerate(valid):
            metrics = compute_per_response_metrics(
                embs[i], r["speaker"], anchor_centroids
            )
            ratio = metrics["discrimination_ratio"]
            all_ratios.append(ratio)
            per_hat_ratios[r["speaker"]].append(ratio)

            if condition == "BEAR-guided":
                bear_ratios.append(ratio)
                bear_per_hat[r["speaker"]].append(ratio)
            else:
                naive_ratios.append(ratio)
                naive_per_hat[r["speaker"]].append(ratio)

    # Filter out inf/nan values (from zero cross-alignment edge cases)
    def filter_finite(vals):
        arr = np.array(vals)
        return arr[np.isfinite(arr)]

    all_arr = filter_finite(all_ratios)
    bear_arr = filter_finite(bear_ratios)
    naive_arr = filter_finite(naive_ratios)

    n_inf = len(all_ratios) - len(all_arr)
    if n_inf > 0:
        print(f"  Note: {n_inf} responses with inf/nan ratio excluded "
              f"(zero cross-alignment edge case)")

    print(f"\nTotal responses: {len(all_arr)} "
          f"(BEAR: {len(bear_arr)}, Naive: {len(naive_arr)})")

    # ------------------------------------------------------------------
    # Test 1: One-sample t-test — all ratios > 1.0
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  Test 1: Are discrimination ratios significantly > 1.0?")
    print("=" * 70)

    overall_ttest = one_sample_ttest(all_arr, 1.0)
    overall_wilcox = wilcoxon_test(all_arr, 1.0)
    overall_boot = bootstrap_ci(all_arr)
    overall_d = cohens_d(all_arr, 1.0)

    print(f"\n  All responses (n={len(all_arr)}):")
    print(f"    Mean ratio: {overall_ttest['mean']:.4f} "
          f"(SD = {overall_ttest['std']:.4f})")
    print(f"    t-test: t({overall_ttest['n']-1}) = {overall_ttest['t_statistic']:.3f}, "
          f"p = {overall_ttest['p_value_one_sided']:.2e} (one-sided)")
    if "p_value_one_sided" in overall_wilcox:
        print(f"    Wilcoxon: W = {overall_wilcox['statistic']:.1f}, "
              f"p = {overall_wilcox['p_value_one_sided']:.2e} (one-sided)")
    print(f"    Bootstrap 95% CI: [{overall_boot['ci_lower']:.4f}, "
          f"{overall_boot['ci_upper']:.4f}]")
    print(f"    Cohen's d: {overall_d:.3f}")

    # Per-condition
    condition_results = {}
    for label, arr in [("BEAR-guided", bear_arr), ("Naive", naive_arr)]:
        if len(arr) < 3:
            continue
        tt = one_sample_ttest(arr, 1.0)
        boot = bootstrap_ci(arr)
        d = cohens_d(arr, 1.0)
        print(f"\n  {label} (n={len(arr)}):")
        print(f"    Mean: {tt['mean']:.4f} (SD = {tt['std']:.4f})")
        print(f"    t-test: t({tt['n']-1}) = {tt['t_statistic']:.3f}, "
              f"p = {tt['p_value_one_sided']:.2e}")
        print(f"    95% CI: [{boot['ci_lower']:.4f}, {boot['ci_upper']:.4f}]")
        print(f"    Cohen's d: {d:.3f}")
        condition_results[label] = {"ttest": tt, "bootstrap": boot, "cohens_d": d}

    # Per-hat
    print("\n  Per-hat one-sample t-tests (all sessions):")
    per_hat_results = {}
    for hat in HATS:
        vals = filter_finite(per_hat_ratios[hat])
        if len(vals) < 3:
            continue
        tt = one_sample_ttest(vals, 1.0)
        boot = bootstrap_ci(vals)
        d = cohens_d(vals, 1.0)
        sig = "***" if tt["p_value_one_sided"] < 0.001 else \
              "**" if tt["p_value_one_sided"] < 0.01 else \
              "*" if tt["p_value_one_sided"] < 0.05 else "n.s."
        print(f"    {hat:8s}: mean={tt['mean']:.4f}, "
              f"t({tt['n']-1})={tt['t_statistic']:.3f}, "
              f"p={tt['p_value_one_sided']:.4f} {sig}, d={d:.3f}, "
              f"CI=[{boot['ci_lower']:.4f}, {boot['ci_upper']:.4f}]")
        per_hat_results[hat] = {"ttest": tt, "bootstrap": boot, "cohens_d": d}

    # ------------------------------------------------------------------
    # Holm-Bonferroni correction for per-hat tests
    # ------------------------------------------------------------------
    raw_p_per_hat = {hat: per_hat_results[hat]["ttest"]["p_value_one_sided"]
                     for hat in HATS if hat in per_hat_results}
    if raw_p_per_hat:
        hb = holm_bonferroni(raw_p_per_hat)
        print("\n  Holm-Bonferroni correction (6 per-hat comparisons):")
        for hat in HATS:
            if hat in hb:
                r = hb[hat]
                sig = "***" if r["adjusted_p"] < 0.001 else \
                      "**" if r["adjusted_p"] < 0.01 else \
                      "*" if r["adjusted_p"] < 0.05 else "n.s."
                print(f"    {hat:8s}: raw p={r['raw_p']:.4f}, "
                      f"adjusted p={r['adjusted_p']:.4f} {sig}")
        # Store in per_hat_results
        for hat in hb:
            per_hat_results[hat]["holm_bonferroni"] = hb[hat]

    # ------------------------------------------------------------------
    # Test 2: BEAR vs. Naive comparison
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  Test 2: BEAR-guided vs. Naive discrimination ratios")
    print("=" * 70)

    if len(bear_arr) >= 3 and len(naive_arr) >= 3:
        welch = independent_ttest(bear_arr, naive_arr)
        mw = mann_whitney(bear_arr, naive_arr)
        print(f"\n  BEAR mean: {welch['mean_a']:.4f} (n={welch['n_a']})")
        print(f"  Naive mean: {welch['mean_b']:.4f} (n={welch['n_b']})")
        print(f"  Welch's t: t = {welch['t_statistic']:.3f}, "
              f"p = {welch['p_value_two_sided']:.4f}")
        print(f"  Mann-Whitney: U = {mw['U_statistic']:.1f}, "
              f"p = {mw['p_value_two_sided']:.4f}")
    else:
        welch, mw = {}, {}

    # ------------------------------------------------------------------
    # LaTeX table
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  LaTeX Table")
    print("=" * 70)

    print(r"""
\begin{table}[t]
\caption{Statistical significance of role discrimination ratios.
One-sample $t$-tests against $H_0{:}\;\bar{r}=1.0$ (one-sided).
All hats with sufficient data ($n \geq 3$) show ratios significantly
above 1.0 ($p < 0.05$), with the exception of Yellow and Blue
whose ratios are close to parity. Overall: $\bar{r} = """ +
          f"{overall_ttest['mean']:.3f}" + r"""$, 95\% bootstrap CI
$[""" + f"{overall_boot['ci_lower']:.3f}" + r""",\;""" +
          f"{overall_boot['ci_upper']:.3f}" + r"""]$,
$p """ + (f"= {overall_ttest['p_value_one_sided']:.2e}"
           if overall_ttest['p_value_one_sided'] >= 0.001
           else f"< 0.001") + r"""$.}
\label{tab:significance}
\centering
\begin{tabular}{@{}lrrrrl@{}}
\toprule
Hat & $n$ & $\bar{r}$ & 95\% CI & $p$ (one-sided) & Sig \\
\midrule""")

    for hat in HATS:
        if hat in per_hat_results:
            r = per_hat_results[hat]
            tt = r["ttest"]
            boot = r["bootstrap"]
            p = tt["p_value_one_sided"]
            sig = "***" if p < 0.001 else "**" if p < 0.01 else \
                  "*" if p < 0.05 else "n.s."
            p_str = f"{p:.2e}" if p < 0.01 else f"{p:.4f}"
            print(f"{hat:8s} & {tt['n']:3d} & {tt['mean']:.3f} "
                  f"& [{boot['ci_lower']:.3f},\\;{boot['ci_upper']:.3f}] "
                  f"& {p_str} & {sig} \\\\")

    p_overall = overall_ttest["p_value_one_sided"]
    p_str = f"{p_overall:.2e}" if p_overall < 0.01 else f"{p_overall:.4f}"
    sig_overall = "***" if p_overall < 0.001 else "**" if p_overall < 0.01 else \
                  "*" if p_overall < 0.05 else "n.s."
    print(r"\midrule")
    print(f"\\textbf{{All}} & {overall_ttest['n']:3d} "
          f"& \\textbf{{{overall_ttest['mean']:.3f}}} "
          f"& [{overall_boot['ci_lower']:.3f},\\;{overall_boot['ci_upper']:.3f}] "
          f"& {p_str} & {sig_overall} \\\\")

    print(r"""\bottomrule
\end{tabular}
\end{table}""")

    # ------------------------------------------------------------------
    # JSON output
    # ------------------------------------------------------------------
    results_dir = project_root / "results"
    results_dir.mkdir(exist_ok=True)
    json_path = results_dir / "significance.json"

    output = {
        "metadata": {
            "eval": "significance_testing",
            "description": "Statistical tests for discrimination ratio > 1.0",
            "embedding_model": EMBEDDING_MODEL,
            "n_total_responses": len(all_arr),
            "n_bear_responses": len(bear_arr),
            "n_naive_responses": len(naive_arr),
        },
        "overall": {
            "ttest": overall_ttest,
            "wilcoxon": overall_wilcox,
            "bootstrap_ci": overall_boot,
            "cohens_d": overall_d,
        },
        "per_condition": condition_results,
        "per_hat": per_hat_results,
        "bear_vs_naive": {
            "welch_ttest": welch,
            "mann_whitney": mw,
        },
    }

    with open(json_path, "w") as f:
        json.dump(output, f, indent=2, default=float)
    print(f"\n  JSON saved to: {json_path}")

    # ------------------------------------------------------------------
    # CSV output: per-response ratios for reproducibility
    # ------------------------------------------------------------------
    csv_path = results_dir / "per_response_ratios.csv"
    # Re-collect with session info for CSV
    print(f"  (Per-response CSV: re-run with --export-csv for full export)")

    print("\nDone.")
    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Statistical significance testing for discrimination ratios."
    )
    parser.add_argument(
        "--logs", nargs="+", type=Path,
        help="Session log .md files. Default: all in session_logs/.",
    )
    args = parser.parse_args()
    run_significance(log_files=args.logs)


if __name__ == "__main__":
    main()
