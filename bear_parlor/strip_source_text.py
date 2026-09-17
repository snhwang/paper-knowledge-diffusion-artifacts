"""Remove copyrighted source-paper text from session logs before committing.

The source PDFs are not redistributable. Session logs carry their text in two
places:
  .knowledge.json   White Hat's ingested PDF chunks (metadata source "pdf")
  .md               per-turn "Knowledge RAG" blocks quoting chunk excerpts

This writes stripped copies: PDF chunks are dropped from each hat's store (the
count is kept as "omitted_pdf_chunks"), and each RAG excerpt is replaced by its
citation. Everything else -- what hats said, BEAR retrieval tables, diffusion
notes, stats -- is unchanged, so every v6 analysis gives identical results.

It then verifies: no excerpt from the original logs and no sampled stretch of
any ingested PDF chunk remains in the stripped copies, and the .md files are
byte-identical to the originals outside the RAG blocks.

Usage:
    python bear_parlor/strip_source_text.py --src <full logs dir> --dst <repo logs dir>
    python bear_parlor/strip_source_text.py --src <dir> --dst <same dir>   # in place
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

HEADER = re.compile(r"\*\*Knowledge RAG\*\* for \w+ \(\d+ chunks?\):\n")
BLOCK_END = re.compile(r"\n(?=> \*\[|---\n|#{1,6} |<details>|\*\*Knowledge RAG\*\*)")
ITEM = re.compile(r"(?m)^- \[(.*?)\] ")
OMITTED = "(excerpt omitted: copyrighted source text)"


def rag_blocks(md: str):
    """Yield (body_start, body_end) for each Knowledge RAG block body."""
    for h in HEADER.finditer(md):
        start = h.end()
        end_m = BLOCK_END.search(md, start)
        yield start, (end_m.start() if end_m else len(md))


def is_generated(label: str) -> bool:
    """RAG items the session itself produced: diffusion notes and insights.

    Knowledge RAG quotes whatever a hat retrieves from its store, which is
    mostly notes the models wrote. Only items carrying a paper citation are
    source text; generated items are labelled "diffused <Hat>" or
    "session insight" and are kept.
    """
    return label.startswith("diffused ") or label == "session insight"


def strip_md(md: str) -> tuple[str, list[str]]:
    out, pos, excerpts = [], 0, []
    for start, end in rag_blocks(md):
        body = md[start:end]
        items = list(ITEM.finditer(body))
        new = []
        for i, it in enumerate(items):
            text_end = items[i + 1].start() if i + 1 < len(items) else len(body)
            if is_generated(it.group(1)):
                new.append(body[it.start():text_end])
                continue
            excerpts.append(body[it.end():text_end])
            new.append(f"- [{it.group(1)}] {OMITTED}\n")
        out.append(md[pos:start])
        out.append("\n" + "".join(new) if body.startswith("\n") else "".join(new))
        pos = end
    out.append(md[pos:])
    return "".join(out), excerpts


def outside_blocks(md: str) -> str:
    parts, pos = [], 0
    for start, end in rag_blocks(md):
        parts.append(md[pos:start])
        pos = end
    parts.append(md[pos:])
    return "".join(parts)


def norm(s: str) -> str:
    return " ".join(s.split())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="directory with the full session logs")
    ap.add_argument("--dst", required=True, help="directory to write stripped copies to")
    args = ap.parse_args()
    src, dst = Path(args.src), Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)
    # --src and --dst may be the same directory: files are read in full before
    # being rewritten, and stats / panel state are simply left where they are.
    in_place = src.resolve() == dst.resolve()

    probes, n_md, n_kj, n_excerpts = set(), 0, 0, 0
    for md_path in sorted(src.glob("brainstorming-hats_*.md")):
        original = md_path.read_text(encoding="utf-8")
        stripped, excerpts = strip_md(original)
        n_excerpts += len(excerpts)
        probes.update(p for p in (norm(e)[:60] for e in excerpts) if len(p) >= 40)
        if outside_blocks(original) != outside_blocks(stripped):
            sys.exit(f"{md_path.name}: content outside RAG blocks changed")
        (dst / md_path.name).write_text(stripped, encoding="utf-8")
        n_md += 1

        kj_path = md_path.with_name(md_path.name[:-3] + ".knowledge.json")
        if kj_path.exists():
            kj = json.loads(kj_path.read_text(encoding="utf-8"))
            for hat, e in kj.items():
                docs, metas = e.get("documents") or [], e.get("metadatas") or []
                keep = [(d, m) for d, m in zip(docs, metas) if (m or {}).get("source") != "pdf"]
                for d, m in zip(docs, metas):
                    if (m or {}).get("source") == "pdf":
                        t = norm(d)
                        probes.update(t[i:i + 60] for i in range(0, max(len(t) - 60, 1), 400) if len(t) >= 60)
                e["omitted_pdf_chunks"] = len(docs) - len(keep)
                e["documents"] = [d for d, _ in keep]
                e["metadatas"] = [m for _, m in keep]
            (dst / kj_path.name).write_text(json.dumps(kj, ensure_ascii=False), encoding="utf-8")
            n_kj += 1

        stats = md_path.with_name(md_path.name[:-3] + ".stats.json")
        if stats.exists() and not in_place:
            shutil.copyfile(stats, dst / stats.name)

    if (src / "panel_state").is_dir() and not in_place:
        shutil.copytree(src / "panel_state", dst / "panel_state", dirs_exist_ok=True)

    # verification ---------------------------------------------------------
    leaks = []
    for f in sorted(dst.glob("brainstorming-hats_*")):
        if f.suffix not in (".md", ".json"):
            continue
        text = norm(f.read_text(encoding="utf-8"))
        hits = [p for p in probes if p in text]
        if hits:
            leaks.append((f.name, len(hits), hits[0]))
    print(f"stripped {n_md} logs ({n_excerpts} excerpts) and {n_kj} knowledge dumps; "
          f"checked {len(probes)} source-text probes")
    if leaks:
        for name, n, example in leaks:
            print(f"  source text still present in {name}: {n} probe(s), e.g. {example!r}")
        sys.exit(1)
    print("no source text found in the stripped copies")


if __name__ == "__main__":
    main()
