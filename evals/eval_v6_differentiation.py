"""v6 sessions: do hats' knowledge stores, and what they say, stay distinct?

Compares the three v6 conditions across the eight topics:
  naive       every utterance stored verbatim
  bear        each hat absorbs through its own BEAR lens
  wrong-lens  each hat absorbs through another hat's lens

Store level (diffusion-sourced notes only, as in the April analyses):
  items per hat, centroid distance, nearest-neighbour similarity and overlap,
  a permutation null that reassigns notes to hats at random, and centroid
  distance at matched store sizes -- differentiation depends on store size,
  so conditions are also compared with every hat truncated to n notes.

Response level (what each hat SAID, logging stripped):
  centroid distance and its permutation null. Stores affect speech only via
  the 4 notes retrieved per turn, so a smaller effect here is expected.

Only sessions that pass check_session_integrity.py are analysed.

Outputs:
    results/v6_differentiation.json   per-session metrics, summaries, paired tests
    results/v6_differentiation.csv    one row per session

Usage:
    python evals/eval_v6_differentiation.py
    python evals/eval_v6_differentiation.py --n-perm 200     # faster
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_session_integrity import check_session  # noqa: E402
from eval_constant_model_reconciled import parse_responses  # noqa: E402
from overlap_metrics import (  # noqa: E402
    centroid_distance, mean_pairwise, nn_overlap, nn_similarity,
    paired_stats, permutation_null,
)

EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
TOPICS = ["dmg", "stroke", "ms", "alzheimers", "epilepsy", "glp1", "crispr", "llm-cds"]
CONDITIONS = ["naive", "bear", "wrong-lens"]
HATS = ["white-hat", "red-hat", "black-hat", "yellow-hat", "green-hat", "blue-hat"]
MIN_HATS_AT_SIZE = 5
PANEL = {"id": "brainstorming-hats"}   # the panel whose sessions are analysed


def configure(panel_id: str, log_dir: Path | None = None) -> None:
    """Point the analysis at another panel (e.g. paper-review): its roles come
    from bear_parlor/panels.yaml, its sessions are named <panel>_*, and its
    topics are whatever the log directory holds a complete condition set for.
    HATS and TOPICS are mutated in place so modules that imported them see
    the change."""
    import yaml
    from check_session_integrity import configure as configure_integrity
    panels = yaml.safe_load((HERE.parent / "bear_parlor" / "panels.yaml").read_text(encoding="utf-8"))["panels"]
    panel = next((p for p in panels if p["id"] == panel_id), None)
    if panel is None:
        sys.exit(f"panel {panel_id!r} not found in panels.yaml")
    PANEL["id"] = panel_id
    PANEL["instruction_dirs"] = list(panel.get("instruction_dirs") or [])
    HATS[:] = list(panel["characters"])
    configure_integrity(panel_id, HATS)
    # the utterance parser keys turns by the display name used in the log
    import eval_constant_model_reconciled as ecm
    chars = yaml.safe_load((HERE.parent / "bear_parlor" / "characters.yaml").read_text(encoding="utf-8"))["characters"]
    ecm.HATS[:] = [str(c["short_name"]).capitalize() for c in chars if c["id"] in HATS]
    if log_dir is not None:
        found = set()
        for st in log_dir.glob(f"{panel_id}_*.stats.json"):
            d = json.loads(st.read_text(encoding="utf-8"))
            if d.get("topic") and d.get("condition") in CONDITIONS:
                found.add((d["topic"], d["condition"]))
        topics = sorted(t for t in {t for t, _ in found} if all((t, c) in found for c in CONDITIONS))
        TOPICS[:] = topics


def select_sessions(log_dir: Path) -> dict:
    """One session per (topic, condition): completed first, then most turns."""
    best = {}
    for st in sorted(log_dir.glob(f"{PANEL['id']}_*.stats.json")):
        d = json.loads(st.read_text(encoding="utf-8"))
        if not d.get("topic") or d.get("condition") not in CONDITIONS:
            continue
        md = Path(str(st)[: -len(".stats.json")] + ".md")
        kj = Path(str(st)[: -len(".stats.json")] + ".knowledge.json")
        if not (md.exists() and kj.exists()):
            continue
        key, score = (d["topic"], d["condition"]), (int(d.get("completed") is True), d.get("n_turns") or 0)
        if key not in best or score > best[key][0]:
            best[key] = (score, md, kj)
    return {k: (v[1], v[2]) for k, v in best.items()}


def store_notes(kj_path: Path) -> dict[str, list[str]]:
    kj = json.loads(kj_path.read_text(encoding="utf-8"))
    out = {}
    for h in HATS:
        e = kj.get(h) or {}
        notes = [d for d, m in zip(e.get("documents") or [], e.get("metadatas") or [])
                 if (m or {}).get("source") == "diffusion"]
        if notes:
            out[h] = notes
    return out


def differentiation(emb: dict, n_perm: int, sizes: list[int] | None = None) -> dict:
    res = {
        "items_per_hat": float(np.mean([len(v) for v in emb.values()])),
        "n_hats": len(emb),
        "centroid": mean_pairwise(emb, centroid_distance),
        "nn_similarity": mean_pairwise(emb, nn_similarity),
        "nn_overlap": mean_pairwise(emb, nn_overlap),
    }
    null = permutation_null(emb, centroid_distance, n_perm=n_perm)
    res.update(null_mean=null["null_mean"], null_sd=null["null_sd"], z=null["z"], p=null["p"])
    if sizes:
        curve = {}
        for n in sizes:
            sub = {h: e[:n] for h, e in emb.items() if len(e) >= n}
            curve[str(n)] = mean_pairwise(sub, centroid_distance) if len(sub) >= MIN_HATS_AT_SIZE else None
        res["centroid_at_size"] = curve
    return res


def paired(results, level, a, b, key):
    xa = [results[a][t][level][key] for t in TOPICS]
    xb = [results[b][t][level][key] for t in TOPICS]
    st = paired_stats(xa, xb)
    st.update(comparison=f"{level} {key}: {a} vs {b}", a_greater_in=int(sum(x > y for x, y in zip(xa, xb))),
              n=len(TOPICS), mean_a=float(np.mean(xa)), mean_b=float(np.mean(xb)))
    return {k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in st.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", default=str(HERE.parent / "bear_parlor" / "session_logs" / "v6"))
    ap.add_argument("--n-perm", type=int, default=1000)
    ap.add_argument("--sizes", type=int, nargs="+", default=[2, 4, 6])
    ap.add_argument("--panel", default="brainstorming-hats",
                    help="panel whose sessions to analyse (roles from panels.yaml; topics discovered)")
    args = ap.parse_args()

    log_dir = Path(args.log_dir)
    if args.panel != "brainstorming-hats":
        configure(args.panel, log_dir)
        if not TOPICS:
            sys.exit(f"no topic in {log_dir} has all of {CONDITIONS} for panel {args.panel}")
    sessions = select_sessions(log_dir)
    missing = [(t, c) for t in TOPICS for c in CONDITIONS if (t, c) not in sessions]
    if missing:
        sys.exit(f"missing sessions for: {missing}")
    failed = []
    for (t, c), (md, _) in sessions.items():
        ok, problems, _ = check_session(md)
        if not ok:
            failed.append((t, c, md.name, problems))
    if failed:
        for f in failed:
            print("FAILED INTEGRITY:", f)
        sys.exit("refusing to analyse sessions that fail check_session_integrity.py")
    print(f"{len(sessions)} sessions from {log_dir}, all pass the integrity check")

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL)

    def embed(texts: dict) -> dict:
        return {h: model.encode(v, normalize_embeddings=True, show_progress_bar=False) for h, v in texts.items()}

    results = {c: {} for c in CONDITIONS}
    rows = []
    for t in TOPICS:
        for c in CONDITIONS:
            md, kj = sessions[(t, c)]
            store = differentiation(embed(store_notes(kj)), args.n_perm, args.sizes)
            speech = differentiation(embed(parse_responses(md)), args.n_perm)
            results[c][t] = {"session": md.name, "store": store, "response": speech}
            rows.append({"topic": t, "condition": c, "session": md.name,
                         **{f"store_{k}": v for k, v in store.items() if k != "centroid_at_size"},
                         **{f"store_centroid_at_{n}": v for n, v in store["centroid_at_size"].items()},
                         **{f"response_{k}": v for k, v in speech.items()}})
            print(f"  {t:<11}{c:<11} store: {store['items_per_hat']:5.1f}/hat  centroid {store['centroid']:.3f}  "
                  f"z {store['z']:+.2f}   response: centroid {speech['centroid']:.3f}  z {speech['z']:+.2f}")

    summary = {}
    for c in CONDITIONS:
        summary[c] = {}
        for level, keys in (("store", ["items_per_hat", "centroid", "nn_similarity", "nn_overlap", "z"]),
                            ("response", ["centroid", "z"])):
            for k in keys:
                v = [results[c][t][level][k] for t in TOPICS]
                summary[c][f"{level}_{k}"] = {"mean": float(np.mean(v)), "sd": float(np.std(v, ddof=1))}
            if level == "store":
                summary[c]["store_significant_topics"] = int(sum(results[c][t]["store"]["p"] < 0.05 for t in TOPICS))
        for n in map(str, args.sizes):
            v = [results[c][t]["store"]["centroid_at_size"][n] for t in TOPICS
                 if results[c][t]["store"]["centroid_at_size"][n] is not None]
            summary[c][f"store_centroid_at_{n}"] = {"mean": float(np.mean(v)) if v else None, "n_topics": len(v)}

    tests = [] if len(TOPICS) < 2 else [
        paired(results, "store", "bear", "naive", "centroid"),
        paired(results, "store", "bear", "wrong-lens", "centroid"),
        paired(results, "store", "naive", "bear", "items_per_hat"),
        paired(results, "store", "bear", "naive", "nn_overlap"),
        paired(results, "store", "bear", "naive", "z"),
        paired(results, "response", "bear", "naive", "centroid"),
        paired(results, "response", "bear", "wrong-lens", "centroid"),
    ]

    print(f"\n{'condition':<11}{'items/hat':>10}{'store cd':>10}{'NN ovl':>8}{'store z':>9}{'resp cd':>9}{'resp z':>8}")
    for c in CONDITIONS:
        s = summary[c]
        print(f"{c:<11}{s['store_items_per_hat']['mean']:>10.1f}{s['store_centroid']['mean']:>10.3f}"
              f"{s['store_nn_overlap']['mean']:>8.3f}{s['store_z']['mean']:>+9.2f}"
              f"{s['response_centroid']['mean']:>9.3f}{s['response_z']['mean']:>+8.2f}")
    print("\nstore centroid at matched size: " + "   ".join(
        f"n={n}: " + ", ".join(f"{c}={summary[c][f'store_centroid_at_{n}']['mean']:.3f}" for c in CONDITIONS)
        for n in args.sizes))
    if tests:
        print("\npaired tests across topics:")
        for st in tests:
            print(f"  {st['comparison']:<42} {st['mean_a']:.3f} vs {st['mean_b']:.3f}  "
                  f"greater in {st['a_greater_in']}/{len(TOPICS)}  t p={st['t_p']:.3g}  Wilcoxon p={st['wilcoxon_p']:.3g}")
    else:
        print("\n(one topic: no paired tests across topics; per-session permutation z and p above)")

    out = HERE / "results"
    out.mkdir(exist_ok=True)
    name = "v6_differentiation.json" if PANEL["id"] == "brainstorming-hats" else f"{PANEL['id']}_differentiation.json"
    (out / name).write_text(json.dumps(
        {"log_dir": str(log_dir), "embedding_model": EMBEDDING_MODEL, "n_perm": args.n_perm,
         "sizes": args.sizes, "summary": summary, "paired_tests": tests, "per_session": results},
        indent=2), encoding="utf-8")
    with open(out / name.replace(".json", ".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {out / name} and .csv")


if __name__ == "__main__":
    main()
