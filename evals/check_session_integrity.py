"""Check that a panel session actually used BEAR the way the paper describes.

Run this on every session before analysing it. It reads the session's markdown
log (which records each speaking turn's BEAR retrieval), its .stats.json run
record and its .knowledge.json dump, and fails the session if any of these hold:

  speaking   a hat's retrieved instructions include another hat's instructions
             (method, speech, persona, memory, evolved -- identified by tags)
  isolation  a retrieved memory or evolved instruction was created before the
             session started, i.e. it carried over from another session
  corpus     instructions from outside the panel's hat/common corpus were
             retrieved (e.g. the DTI-paper "knowledge-*" files)
  persona    a hat's own persona instruction was missing from its prompt
  diffusion  the run record does not show per-hat BEAR diffusion (or naive,
             for the naive condition), or diffusion batches were dropped
  models     hats did not all run on the one recorded model
  pdfs       a source PDF was not extracted with Mathpix
  record     the run record or knowledge dump is missing

The April 2026 sessions fail the speaking, isolation and corpus checks; that is
the point of the checker.

Usage:
    python evals/check_session_integrity.py <session .md or .stats.json> [...]
    python evals/check_session_integrity.py --dir <session_logs/v6>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HATS = ["white-hat", "red-hat", "black-hat", "yellow-hat", "green-hat", "blue-hat"]
BLOCK = re.compile(r"<summary>BEAR retrieval for (\w+) \((\d+) instructions\)</summary>(.*?)</details>", re.S)
ROW = re.compile(r"^\|\s*(\w+)\s*\|\s*([\w.:-]+)\s*\|\s*([\d.]+)\s*\|\s*([^|]*)\|", re.M)
PANEL_PREFIXES = ("persona-", "directive-", "protocol-", "constraint-", "room-context-",
                  "memory-", "evolved-")
MAX_DROPPED_FRACTION = 0.05


def check_session(md_path: Path) -> tuple[bool, list[str], dict]:
    stem = str(md_path)[:-3]
    stats_path, kj_path = Path(stem + ".stats.json"), Path(stem + ".knowledge.json")
    problems, info = [], {}

    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else None
    if stats is None:
        return False, ["record: .stats.json missing"], info
    info.update(topic=stats.get("topic"), condition=stats.get("condition"), turns=stats.get("n_turns"))
    started = time.mktime(time.strptime(stats["started"], "%Y-%m-%d %H:%M:%S"))
    run = stats.get("run_info") or {}
    if not run:
        problems.append("record: no run_info (session predates the v6 pipeline)")
    if not kj_path.exists():
        problems.append("record: .knowledge.json missing")

    # ---- models and diffusion mode ---------------------------------------------
    if run:
        speaking = run.get("speaking_llm") or {}
        if len(set(speaking.values())) != 1:
            problems.append(f"models: hats ran on {len(set(speaking.values()))} different models: {sorted(set(speaking.values()))}")
        want = "naive" if stats.get("condition") == "naive" else "per-hat"
        if run.get("diffusion") != want:
            problems.append(f"diffusion: expected '{want}', run record says '{run.get('diffusion')}'")
        if stats.get("condition") == "wrong-lens" and not run.get("lens_map"):
            problems.append("diffusion: wrong-lens session has no lens_map")
        if stats.get("condition") == "bear" and run.get("lens_map"):
            problems.append("diffusion: bear session has a lens_map (should use each hat's own lens)")
        if not run.get("mathpix_credentials"):
            problems.append("pdfs: Mathpix credentials were not available to the server")
        if run.get("uncommitted_changes"):
            info["warning"] = "code had uncommitted changes when this session ran"
    extractors = [i.get("extractor") for i in stats.get("ingestions", [])]
    if stats.get("ingestions") and any(e != "mathpix" for e in extractors):
        problems.append(f"pdfs: extractors used {extractors}")
    dropped = sum((stats.get("diffusion_errors") or {}).values())
    stored = stats.get("n_diffusion_stored", 0) + stats.get("n_diffusion_skipped", 0)
    info["diffusion_dropped"] = dropped
    if stored and dropped / max(stored + dropped, 1) > MAX_DROPPED_FRACTION:
        problems.append(f"diffusion: {dropped} batches dropped ({stats.get('diffusion_errors')})")

    # ---- speaking retrieval ------------------------------------------------------
    md = md_path.read_text(encoding="utf-8")
    turns = cross = stale = foreign = no_persona = 0
    examples = {"speaking": None, "isolation": None, "corpus": None}
    for speaker, _, body in BLOCK.findall(md):
        hat = speaker.lower() + "-hat"
        rows = [(t, i, tags) for t, i, _, tags in ROW.findall(body) if t != "Type"]
        if not rows:
            continue
        turns += 1
        if not any(i == f"persona-{hat}-core" for _, i, _ in rows):
            no_persona += 1
        for _, iid, tags in rows:
            owners = {h for h in HATS if h in tags}
            if owners and hat not in owners:
                cross += 1
                examples["speaking"] = examples["speaking"] or f"{hat} got {iid}"
            if not iid.startswith(PANEL_PREFIXES):
                foreign += 1
                examples["corpus"] = examples["corpus"] or f"{hat} got {iid}"
            m = re.match(r"^(?:memory-[\w-]+?-hat|evolved-[\w-]+?-hat)-(\d{9,})", iid)
            if m and int(m.group(1)) < started - 60:
                stale += 1
                examples["isolation"] = examples["isolation"] or f"{hat} got {iid}"
    info["speaking_turns"] = turns
    if turns == 0:
        problems.append("record: no BEAR retrieval tables in the log")
    if cross:
        problems.append(f"speaking: {cross} retrieved instructions belonged to another hat (e.g. {examples['speaking']})")
    if stale:
        problems.append(f"isolation: {stale} retrieved memories/evolved instructions predate the session (e.g. {examples['isolation']})")
    if foreign:
        problems.append(f"corpus: {foreign} retrieved instructions from outside the panel corpus (e.g. {examples['corpus']})")
    if no_persona:
        problems.append(f"persona: speaker's own persona missing in {no_persona} of {turns} turns")
    return not problems, problems, info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--dir", default=None, help="check every labelled session in a directory")
    args = ap.parse_args()
    paths = [Path(p) for p in args.paths]
    if args.dir:
        for s in sorted(Path(args.dir).glob("*.stats.json")):
            d = json.loads(s.read_text(encoding="utf-8"))
            if d.get("topic") and d.get("condition"):
                paths.append(Path(str(s)[:-len(".stats.json")] + ".md"))
    if not paths:
        ap.error("give session files or --dir")
    n_ok = 0
    for p in paths:
        p = Path(str(p).replace(".stats.json", ".md"))
        ok, problems, info = check_session(p)
        n_ok += ok
        label = f"{info.get('topic')}/{info.get('condition')}"
        print(f"{'PASS' if ok else 'FAIL'}  {p.name}  {label}  turns={info.get('turns')}")
        for prob in problems:
            print(f"      - {prob}")
        if info.get("warning"):
            print(f"      ! {info['warning']}")
    print(f"\n{n_ok} of {len(paths)} sessions passed")
    sys.exit(0 if n_ok == len(paths) else 1)


if __name__ == "__main__":
    main()
