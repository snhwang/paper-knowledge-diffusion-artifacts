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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", required=True)
    ap.add_argument("--out", default=str(ROOT / "evals" / "results" / "review_provenance.json"))
    args = ap.parse_args()
    log_dir = Path(args.log_dir)
    results = []
    for md in sorted(log_dir.glob("paper-review_*.md")):
        loaded = load(md)
        if not loaded:
            continue
        stats, knowledge = loaded
        results.append({
            "log": md.name, "case": stats.get("topic"), "condition": stats.get("condition"),
            "completed": stats.get("completed"),
            "section_provenance": section_provenance(knowledge),
            "uptake": cross_role_uptake(stats, stats.get("run_info", {})),
        })
    if not results:
        sys.exit(f"no paper-review sessions with stats and knowledge files in {log_dir}")

    for r in results:
        print(f"\n{r['case']} / {r['condition']}  ({r['log']})")
        print(f"  {'role':<14} {'notes':>5}  " + "  ".join(f"{s[:6]:>6}" for s in SECTIONS))
        for role, sp in r["section_provenance"].items():
            print(f"  {role:<14} {sp['n_document_notes']:>5}  "
                  + "  ".join(f"{sp['by_section'][s]:6.2f}" for s in SECTIONS))
        print("  cross-role uptake (share of a speaker's retrieved items that came through another role's lens):")
        for sp, u in r["uptake"].items():
            print(f"    {sp:<14} n={u['n_retrieved']:<4} uptake={u['uptake']:.2f}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"log_dir": str(log_dir), "sessions": results}, indent=2), encoding="utf-8")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
