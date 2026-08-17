"""Store-differentiation metrics — one definition, used by every eval.

WHY THIS MODULE EXISTS
----------------------
The manuscript previously carried two different definitions of "nearest-
neighbour overlap" in different tables:

  * cosine DISTANCE < 0.35  (i.e. similarity > 0.65)  -- legacy
  * cosine SIMILARITY >= 0.85                          -- Table 4

Under the first, BEAR-guided overlap is 0.93; under the second it is 0.06.
Same data, same name, values an order of magnitude apart. Every script now
imports its metrics from here so that cannot recur.

THE ROBUSTNESS PROBLEM WITH THRESHOLDED OVERLAP
-----------------------------------------------
Any single threshold is arbitrary, and the choice is not innocent: it moved
the headline number by 14x. Three further properties make a bare thresholded
count fragile:

  1. It is size-sensitive. A store with more items offers more chances for a
     match, so overlap correlates with store size independently of content.
     BEAR stores are about half the size of naive stores, so part of any
     measured difference could be an artefact of size alone.
  2. It has no null model. "6% overlap" means nothing without knowing what
     overlap random assignment of the same items would produce.
  3. It discards magnitude. An item matched at 0.86 and one matched at 0.99
     count identically.

WHAT THIS MODULE PROVIDES
-------------------------
`nn_similarity`   Threshold-free. Mean nearest-neighbour cosine similarity,
                  symmetrised over the pair. No magic number, retains
                  magnitude. This is the primary measure.

`nn_overlap`      The thresholded fraction, symmetrised, with tau explicit at
                  every call site. Retained for continuity with the published
                  table and because it is easy to interpret.

`overlap_curve`   `nn_overlap` swept across a range of tau, so a reported
                  ordering can be shown to hold at every threshold rather
                  than at one chosen one.

`permutation_null` The important one. Pools all items in a session and
                  randomly reassigns them to hats *preserving each hat's store
                  size*, then recomputes the statistic. This controls for both
                  store size and topic vocabulary, and answers the question a
                  reviewer should ask: is this differentiation greater than
                  splitting the same items at random would give? Reports the
                  observed value, the null distribution, a z-score and an
                  empirical p-value.

Report the observed statistic against its permutation null. A differentiation
claim that does not beat the null is not a claim about the mechanism.

All functions take L2-normalised embeddings, so cosine similarity is a dot
product.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np

# The manuscript's thresholded overlap uses this value. Kept as a named
# constant so no script can quietly pick a different one.
TAU_DEFAULT = 0.85

# Sweep used for robustness curves.
TAU_SWEEP = (0.70, 0.75, 0.80, 0.85, 0.90, 0.95)


# ---------------------------------------------------------------------------
# Pairwise measures
# ---------------------------------------------------------------------------

def nn_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Mean nearest-neighbour cosine similarity between two stores.

    For each item in `a`, its greatest similarity to any item in `b`; averaged,
    then symmetrised with the same quantity computed b->a. Threshold-free, so
    it cannot be tuned, and it keeps magnitude information a count discards.

    Higher means the stores are more alike, i.e. LESS differentiated.
    """
    a, b = np.asarray(a), np.asarray(b)
    if not len(a) or not len(b):
        return float("nan")
    sim = a @ b.T
    return float((sim.max(axis=1).mean() + sim.max(axis=0).mean()) / 2)


def nn_overlap(a: np.ndarray, b: np.ndarray, tau: float = TAU_DEFAULT) -> float:
    """Symmetrised fraction of items having a near-duplicate at similarity >= tau."""
    a, b = np.asarray(a), np.asarray(b)
    if not len(a) or not len(b):
        return float("nan")
    sim = a @ b.T
    return float(((sim.max(axis=1) >= tau).mean()
                  + (sim.max(axis=0) >= tau).mean()) / 2)


def centroid_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance between the L2-normalised mean vectors of two stores."""
    a, b = np.asarray(a), np.asarray(b)
    if not len(a) or not len(b):
        return float("nan")
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    ca = ca / (np.linalg.norm(ca) + 1e-10)
    cb = cb / (np.linalg.norm(cb) + 1e-10)
    return float(1.0 - np.dot(ca, cb))


# ---------------------------------------------------------------------------
# Aggregation over all hat pairs in one session
# ---------------------------------------------------------------------------

def mean_pairwise(hat_embs: dict, fn, hats: list[str] | None = None, **kw) -> float:
    """Apply `fn` to every unordered pair of non-empty stores and average."""
    keys = [h for h in (hats or sorted(hat_embs))
            if h in hat_embs and len(hat_embs[h])]
    if len(keys) < 2:
        return float("nan")
    return float(np.mean([fn(hat_embs[x], hat_embs[y], **kw)
                          for x, y in combinations(keys, 2)]))


def overlap_curve(hat_embs: dict, taus=TAU_SWEEP, hats=None) -> dict:
    """Mean pairwise thresholded overlap at each tau in the sweep."""
    return {float(t): mean_pairwise(hat_embs, nn_overlap, hats, tau=t)
            for t in taus}


# ---------------------------------------------------------------------------
# Null model
# ---------------------------------------------------------------------------

def permutation_null(hat_embs: dict, fn, n_perm: int = 1000, seed: int = 20261025,
                     hats: list[str] | None = None, **kw) -> dict:
    """Null distribution from reassigning items to hats at random.

    Pools every item in the session and redistributes them to hats keeping each
    hat's store size fixed, then recomputes the mean pairwise statistic. This
    holds constant the number of items, their sizes, and the session's topical
    vocabulary, so what remains is whether items are assigned to hats in a way
    that matters.

    Returns the observed value, the null mean and SD, a z-score, and a
    two-sided empirical p-value. The empirical p is bounded below by
    1 / (n_perm + 1); with the default it cannot report below ~0.001.
    """
    keys = [h for h in (hats or sorted(hat_embs))
            if h in hat_embs and len(hat_embs[h])]
    if len(keys) < 2:
        return {"observed": float("nan"), "null_mean": float("nan"),
                "null_sd": float("nan"), "z": float("nan"), "p": float("nan"),
                "n_perm": 0}

    observed = mean_pairwise(hat_embs, fn, keys, **kw)
    sizes = [len(hat_embs[h]) for h in keys]
    pool = np.vstack([np.asarray(hat_embs[h]) for h in keys])
    rng = np.random.default_rng(seed)

    null = np.empty(n_perm, dtype=float)
    for i in range(n_perm):
        perm = rng.permutation(len(pool))
        shuffled, start = {}, 0
        for h, n in zip(keys, sizes):
            shuffled[h] = pool[perm[start:start + n]]
            start += n
        null[i] = mean_pairwise(shuffled, fn, keys, **kw)

    mu, sd = float(null.mean()), float(null.std(ddof=1))
    # A null with zero spread is degenerate, not infinitely significant. It
    # happens when stores hold one or two items and every permutation gives the
    # same answer. Report NaN so such rows are visibly uninterpretable rather
    # than appearing as an infinite effect.
    z = float((observed - mu) / sd) if sd > 0 else float("nan")
    p = (float((np.sum(np.abs(null - mu) >= abs(observed - mu)) + 1) / (n_perm + 1))
         if sd > 0 else float("nan"))
    return {"observed": observed, "null_mean": mu, "null_sd": sd,
            "z": z, "p": p, "n_perm": n_perm,
            "degenerate": bool(sd == 0)}


# ---------------------------------------------------------------------------
# Statistics shared across evals
# ---------------------------------------------------------------------------

def bootstrap_ci(values, n_boot: int = 10000, seed: int = 20261025):
    arr = np.asarray([v for v in values if not np.isnan(v)], dtype=float)
    if len(arr) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def paired_stats(a, b) -> dict:
    """Paired t-test, Wilcoxon signed-rank and Cohen's d for two paired arrays."""
    pairs = [(x, y) for x, y in zip(a, b) if not (np.isnan(x) or np.isnan(y))]
    if len(pairs) < 2:
        return {"n": len(pairs), "t_p": float("nan"),
                "wilcoxon_p": float("nan"), "cohens_d": float("nan"),
                "mean_diff": float("nan")}
    x = np.array([p[0] for p in pairs]); y = np.array([p[1] for p in pairs])
    diff = x - y
    sd = diff.std(ddof=1)
    out = {"n": len(pairs), "mean_diff": float(diff.mean()),
           "cohens_d": float(diff.mean() / sd) if sd > 0 else float("inf")}
    try:
        from scipy.stats import ttest_rel, wilcoxon
        out["t_p"] = float(ttest_rel(x, y).pvalue)
        out["wilcoxon_p"] = float(wilcoxon(x, y).pvalue)
    except ImportError:
        out["t_p"] = out["wilcoxon_p"] = float("nan")
    return out