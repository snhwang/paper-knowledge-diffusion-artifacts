"""Paired tests for the incident-response scenario.

The paired unit is a (case, fact, role) cell: the same planted fact, judged
for the same role, under two conditions run on the same case. For each cell
the outcome is binary (the fact is present in the role's store; the role's
answer contains it; the role refused), so condition contrasts are exact
McNemar tests on the discordant cells, plus the difference in rates. Case-
level means are reported as well for the paper table.

Reads the same session files as eval_incident_routing.py (governed sessions
only; one session per case and condition — the latest if several).

Usage:
    python evals/eval_incident_stats.py --log-dir <bear-dev>/examples/bear_parlor/session_logs/scenarios
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_incident_routing import (ROLE_BY_NAME, REFUSAL_PATTERNS, SCENARIOS, load_session,  # noqa: E402
                                   present, store_text)

ROOT = Path(__file__).resolve().parent.parent
CONDITIONS = ["bear", "naive", "shared-memory", "no-gate", "wrong-lens"]
CONTRASTS = [("bear", "naive"), ("bear", "shared-memory"), ("bear", "no-gate"), ("bear", "wrong-lens"),
             ("no-gate", "naive")]


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p for discordant counts b (a only) and c (b only)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) * 2 / 2 ** n
    return min(1.0, p)


def cells_for(sess: dict, facts: list) -> dict:
    """{(fact_id, role): {"deliver": bool|None, "deny": bool|None, "in_store": bool,
    "in_answer": bool|None, "refused": bool|None}}"""
    answers = defaultdict(dict)
    for a in sess["answers"]:
        role = ROLE_BY_NAME.get(str(a.get("hat", "")).strip().lower(), a.get("hat", ""))
        answers[role][a.get("question_id")] = a.get("answer", "") or ""
    out = {}
    roles = sorted({r for f in facts for r in f["deliver"] + f["deny"]})
    texts = {r: store_text(sess["stores"].get(r, {})) for r in roles}
    for f in facts:
        for role in roles:
            kind = "deliver" if role in f["deliver"] else "deny" if role in f["deny"] else None
            if kind is None:
                continue
            ans = answers.get(role, {}).get(f["id"])
            out[(f["id"], role)] = {
                "kind": kind,
                "in_store": present(texts[role], f),
                "in_answer": (present(ans, f) if ans is not None else None),
                "refused": ((not present(ans, f)) and bool(REFUSAL_PATTERNS.search(ans)) if ans is not None else None),
            }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", required=True)
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "incident_stats.json"))
    args = ap.parse_args()
    log_dir = Path(args.log_dir)

    # latest governed session per (case, condition)
    latest: dict[tuple, dict] = {}
    for p in sorted(log_dir.glob("incident-response_*.md")):
        s = load_session(p)
        if not s or not s.get("governed") or not s.get("completed"):
            continue
        latest[(s["topic"], s["condition"])] = s
    cases = sorted({c for c, _ in latest})
    specs = {c: json.loads((SCENARIOS / c / "facts.json").read_text(encoding="utf-8"))["facts"] for c in cases}
    cells = {k: cells_for(s, specs[k[0]]) for k, s in latest.items()}

    # per-case, per-condition rates
    rates = defaultdict(dict)
    for (case, cond), cc in cells.items():
        deliver = [v for v in cc.values() if v["kind"] == "deliver"]
        deny = [v for v in cc.values() if v["kind"] == "deny"]
        d_ans = [v for v in deliver if v["in_answer"] is not None]
        n_ans = [v for v in deny if v["in_answer"] is not None]
        rates[cond][case] = {
            "delivery_store": sum(v["in_store"] for v in deliver) / len(deliver),
            "delivery_answer": sum(v["in_answer"] for v in d_ans) / len(d_ans) if d_ans else None,
            "leak_store": sum(v["in_store"] for v in deny) / len(deny),
            "leak_answer": sum(v["in_answer"] for v in n_ans) / len(n_ans) if n_ans else None,
            "refusal": sum(v["refused"] for v in n_ans) / len(n_ans) if n_ans else None,
        }
    measures = ["delivery_store", "delivery_answer", "leak_store", "leak_answer", "refusal"]
    print(f"cases: {cases}\n")
    print("per-condition means over cases (governed sessions):")
    print(f"  {'condition':<14}" + "".join(f"{m:>17}" for m in measures) + "   n")
    means = {}
    for cond in CONDITIONS:
        if cond not in rates:
            continue
        row = {}
        for m in measures:
            vals = [r[m] for r in rates[cond].values() if r[m] is not None]
            row[m] = sum(vals) / len(vals) if vals else None
        means[cond] = row
        print(f"  {cond:<14}" + "".join(f"{(row[m] if row[m] is not None else float('nan')):>17.3f}" for m in measures)
              + f"   {len(rates[cond])}")

    # cell-level paired contrasts
    print("\npaired contrasts on (case, fact, role) cells, exact McNemar on discordant cells:")
    print(f"  {'contrast':<26}{'measure':<16}{'cells':>6}{'rate A':>8}{'rate B':>8}{'diff':>8}{'b/c':>9}{'p':>10}")
    tests = []
    for a, b in CONTRASTS:
        for m, key, kind in [("delivery_store", "in_store", "deliver"), ("delivery_answer", "in_answer", "deliver"),
                             ("leak_store", "in_store", "deny"), ("leak_answer", "in_answer", "deny"),
                             ("refusal", "refused", "deny")]:
            pa = pb = n = only_a = only_b = 0
            for case in cases:
                ca, cb = cells.get((case, a)), cells.get((case, b))
                if not ca or not cb:
                    continue
                if m == "leak_store" and (latest[(case, a)]["run_info"].get("shared_knowledge")
                                          or latest[(case, b)]["run_info"].get("shared_knowledge")):
                    continue  # store leak is not defined for the shared read path
                for cell, va in ca.items():
                    vb = cb.get(cell)
                    if vb is None or va["kind"] != kind or va[key] is None or vb[key] is None:
                        continue
                    n += 1
                    pa += va[key]
                    pb += vb[key]
                    only_a += va[key] and not vb[key]
                    only_b += vb[key] and not va[key]
            if n == 0:
                continue
            p = mcnemar_exact(only_a, only_b)
            tests.append({"contrast": f"{a} vs {b}", "measure": m, "cells": n, "rate_a": pa / n, "rate_b": pb / n,
                          "diff": (pa - pb) / n, "only_a": only_a, "only_b": only_b, "p": p})
            print(f"  {a + ' vs ' + b:<26}{m:<16}{n:>6}{pa / n:>8.3f}{pb / n:>8.3f}{(pa - pb) / n:>+8.3f}"
                  f"{f'{only_a}/{only_b}':>9}{p:>10.3g}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"cases": cases, "per_case_rates": rates, "means": means, "tests": tests}, indent=2),
                   encoding="utf-8")
    with open(out.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["condition"] + measures + ["n_cases"])
        for cond, row in means.items():
            w.writerow([cond] + [("" if row[m] is None else f"{row[m]:.3f}") for m in measures] + [len(rates[cond])])
    print(f"\nwritten: {out} and {out.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
