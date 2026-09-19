"""Score paper-review sessions: section provenance and cross-role uptake.

Both measures are read from the logs and need no judge model.

Section provenance
    Every note a role's lens made from a document records the paper section
    of the passage it came from (``section`` metadata, labelled from the
    paper's headings at ingestion). Per role, report the distribution over
    sections. Under BEAR lenses the pattern is expected to follow each role's
    declared interest (methodologist and replicator from Methods, ...);
    under naive diffusion every role shows the same distribution; under the
    wrong-lens control the pattern follows the rotated lens.

Cross-role uptake
    The stats file records, per turn, which knowledge items the speaker
    retrieved. Items labelled ``diffused <role>`` were made by another role's
    lens from that role's utterance. Uptake is the fraction of a speaker's
    retrieved items that came through diffusion from another role — knowledge
    that crossed a lens boundary and was then used.

Usage:
    python evals/eval_review_provenance.py --log-dir <bear-dev>/examples/bear_parlor/session_logs/scenarios
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ["front", "abstract", "introduction", "methods", "results", "discussion",
            "limitations", "conclusion", "references"]


def load(md_path: Path):
    stats_p = md_path.with_suffix("").with_suffix(".stats.json")
    kj_p = md_path.with_suffix("").with_suffix(".knowledge.json")
    if not stats_p.exists() or not kj_p.exists():
        return None
    return json.loads(stats_p.read_text(encoding="utf-8")), json.loads(kj_p.read_text(encoding="utf-8"))


def section_provenance(knowledge: dict) -> dict:
    out = {}
    for role, store in knowledge.items():
        if role == "source":
            continue
        counts = Counter()
        for m in store.get("metadatas", []):
            m = m or {}
            if m.get("source") != "diffusion" or not str(m.get("source_hat", "")).startswith("document:"):
                continue
            counts[m.get("section") or "front"] += 1
        total = sum(counts.values())
        out[role] = {"n_document_notes": total,
                     "by_section": {s: counts.get(s, 0) / total if total else 0.0 for s in SECTIONS}}
    return out


def cross_role_uptake(stats: dict, run_info: dict) -> dict:
    """Per speaker: retrieved items by origin (own document notes, notes
    diffused from another role, other)."""
    names = run_info.get("speaking_llm", {})  # role ids
    by_speaker = defaultdict(Counter)
    for ev in stats.get("rag_events", []):
        sp = ev.get("speaker", "?")
        for it in ev.get("items", []):
            cit = str(it.get("citation") or "")
            src_hat = str(it.get("source_hat") or "")
            if src_hat.startswith("document:"):
                by_speaker[sp]["own_document_note"] += 1
            elif cit.startswith("diffused "):
                by_speaker[sp]["diffused_from_other_role"] += 1
            elif cit == "session insight":
                by_speaker[sp]["own_insight"] += 1
            else:
                by_speaker[sp]["other"] += 1
    out = {}
    for sp, c in by_speaker.items():
        total = sum(c.values())
        out[sp] = {"n_retrieved": total, **{k: v / total for k, v in c.items()},
                   "uptake": c.get("diffused_from_other_role", 0) / total if total else 0.0}
    return out


def section_counts(knowledge: dict) -> dict:
    """role -> {section: count} over document notes."""
    out = {}
    for role, store in knowledge.items():
        if role == "source":
            continue
        c = Counter()
        for m in store.get("metadatas", []):
            m = m or {}
            if m.get("source") == "diffusion" and str(m.get("source_hat", "")).startswith("document:"):
                c[m.get("section") or "front"] += 1
        out[role] = c
    return out


def chi_square_independence(counts: dict) -> dict:
    """Role x section contingency: does where a role's notes come from depend
    on the role? Chi-square with a permutation p-value (labels shuffled over
    notes) so sparse cells do not matter."""
    import random
    roles = sorted(counts)
    secs = sorted({s for c in counts.values() for s in c})
    table = [[counts[r].get(s, 0) for s in secs] for r in roles]

    def stat(tab):
        n = sum(map(sum, tab))
        rs = [sum(row) for row in tab]
        cs = [sum(tab[i][j] for i in range(len(tab))) for j in range(len(secs))]
        x2 = 0.0
        for i in range(len(tab)):
            for j in range(len(secs)):
                e = rs[i] * cs[j] / n if n else 0
                if e:
                    x2 += (tab[i][j] - e) ** 2 / e
        return x2

    obs = stat(table)
    labels = [r for r in roles for _ in range(sum(counts[r].values()))]
    notes = [s for r in roles for s, k in counts[r].items() for _ in range(k)]
    rng, extreme, n_perm = random.Random(20260919), 0, 2000
    for _ in range(n_perm):
        rng.shuffle(labels)
        c = {r: Counter() for r in roles}
        for lab, s in zip(labels, notes):
            c[lab][s] += 1
        extreme += stat([[c[r].get(s, 0) for s in secs] for r in roles]) >= obs - 1e-12
    dof = (len(roles) - 1) * (len(secs) - 1)
    n = len(notes)
    v = math.sqrt(obs / (n * min(len(roles) - 1, len(secs) - 1))) if n else 0.0
    return {"chi2": obs, "dof": dof, "n_notes": n, "cramers_v": v, "p_perm": (extreme + 1) / (n_perm + 1)}


def js_divergence(p: Counter, q: Counter) -> float:
    keys = set(p) | set(q)
    sp, sq = sum(p.values()) or 1, sum(q.values()) or 1
    P = {k: p.get(k, 0) / sp for k in keys}
    Q = {k: q.get(k, 0) / sq for k in keys}
    M = {k: (P[k] + Q[k]) / 2 for k in keys}

    def kl(a, b):
        return sum(a[k] * math.log(a[k] / b[k]) for k in keys if a[k] > 0)
    return (kl(P, M) + kl(Q, M)) / 2


def lens_tracking(bear_counts: dict, wrong_counts: dict, lens_map: dict) -> dict:
    """Under wrong-lens, is each role's section pattern closer to the pattern
    the lens's owner showed under bear than to the role's own bear pattern?"""
    out = {}
    for role, donor in lens_map.items():
        if role not in wrong_counts or role not in bear_counts or donor not in bear_counts:
            continue
        d_own = js_divergence(wrong_counts[role], bear_counts[role])
        d_donor = js_divergence(wrong_counts[role], bear_counts[donor])
        out[role] = {"lens_from": donor, "js_to_own_bear": d_own, "js_to_donor_bear": d_donor,
                     "tracks_lens": d_donor < d_own}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", required=True)
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "review_provenance.json"))
    args = ap.parse_args()
    log_dir = Path(args.log_dir)
    results = []
    counts_by = {}
    lens_maps = {}
    for md in sorted(log_dir.glob("paper-review_*.md")):
        loaded = load(md)
        if not loaded:
            continue
        stats, knowledge = loaded
        key = (stats.get("topic"), stats.get("condition"))
        counts_by[key] = section_counts(knowledge)
        lens_maps[key] = (stats.get("run_info") or {}).get("lens_map") or {}
        results.append({
            "log": md.name, "case": stats.get("topic"), "condition": stats.get("condition"),
            "completed": stats.get("completed"),
            "section_provenance": section_provenance(knowledge),
            "uptake": cross_role_uptake(stats, stats.get("run_info", {})),
            "role_section_independence": chi_square_independence(section_counts(knowledge)),
        })
    if not results:
        sys.exit(f"no paper-review sessions with stats and knowledge files in {log_dir}")
    # wrong-lens tracking against the same case's bear session
    for r in results:
        if r["condition"] == "wrong-lens" and (r["case"], "bear") in counts_by:
            lm = lens_maps[(r["case"], "wrong-lens")]
            r["lens_tracking"] = lens_tracking(counts_by[(r["case"], "bear")], counts_by[(r["case"], "wrong-lens")], lm)

    for r in results:
        print(f"\n{r['case']} / {r['condition']}  ({r['log']})")
        print(f"  {'role':<14} {'notes':>5}  " + "  ".join(f"{s[:6]:>6}" for s in SECTIONS))
        for role, sp in r["section_provenance"].items():
            print(f"  {role:<14} {sp['n_document_notes']:>5}  "
                  + "  ".join(f"{sp['by_section'][s]:6.2f}" for s in SECTIONS))
        ind = r["role_section_independence"]
        print(f"  role x section independence: chi2={ind['chi2']:.1f} dof={ind['dof']} n={ind['n_notes']} "
              f"Cramer's V={ind['cramers_v']:.3f} permutation p={ind['p_perm']:.3g}")
        if r.get("lens_tracking"):
            n_track = sum(v["tracks_lens"] for v in r["lens_tracking"].values())
            print(f"  wrong-lens tracking: {n_track}/{len(r['lens_tracking'])} roles closer to their lens donor's bear pattern than to their own")
            for role, v in r["lens_tracking"].items():
                print(f"    {role:<14} lens from {v['lens_from']:<14} JS to own bear {v['js_to_own_bear']:.3f}  "
                      f"to donor bear {v['js_to_donor_bear']:.3f}  {'tracks lens' if v['tracks_lens'] else 'own pattern'}")
        print("  cross-role uptake (share of a speaker's retrieved items that came through another role's lens):")
        for sp, u in r["uptake"].items():
            print(f"    {sp:<14} n={u['n_retrieved']:<4} uptake={u['uptake']:.2f}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"log_dir": str(log_dir), "sessions": results}, indent=2), encoding="utf-8")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
