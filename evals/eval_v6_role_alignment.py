"""v6 sessions: whose role does each stored note reflect?

Store differentiation cannot tell a hat that absorbed through its own lens from
one that absorbed through a swapped lens: the wrong-lens condition is a
rotation, so the six stores are just as distinct. This analysis asks which
role each note is closest to.

Reference text per hat: its persona and method instructions -- how it SPEAKS
-- which are separate from the diffusion lens text. Each diffusion-sourced note
is embedded and assigned to the most similar reference. No LLM judges anything.

  bear        notes should match the storing hat
  wrong-lens  notes should match the hat whose LENS was used (WRONG_LENS_MAP),
              not the storing hat, if the lens instruction controls absorption
  naive       verbatim utterances, for reference

Two scorings are reported:
  raw         argmax of cosine similarity
  corrected   each reference's similarity standardised by its mean and SD over
              all notes from all 24 sessions pooled. Without this one reference
              attracts notes from every hat ("hubness"); pooling across
              conditions keeps the correction independent of any condition.

Only sessions that pass check_session_integrity.py are analysed.

Outputs:
    results/v6_role_alignment.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_session_integrity import check_session  # noqa: E402
from eval_v6_differentiation import (  # noqa: E402
    CONDITIONS, EMBEDDING_MODEL, HATS, TOPICS, select_sessions, store_notes,
)
from overlap_metrics import paired_stats  # noqa: E402

# Same rotation as parlor.py WRONG_LENS_MAP (bear-dev d90058c).
WRONG_LENS_MAP = {"white-hat": "red-hat", "red-hat": "black-hat", "black-hat": "blue-hat",
                  "blue-hat": "green-hat", "green-hat": "yellow-hat", "yellow-hat": "white-hat"}
CHANCE = 1 / len(HATS)


def reference_texts(hat_dir: Path) -> dict[str, str]:
    refs = {}
    for h in HATS:
        data = yaml.safe_load((hat_dir / f"{h.replace('-', '_')}.yaml").read_text(encoding="utf-8"))
        parts = [i["content"] for i in data["instructions"]
                 if i["id"] in (f"persona-{h}-core", f"directive-{h}-method")]
        if len(parts) != 2:
            sys.exit(f"{h}: expected persona and method instructions, found {len(parts)}")
        refs[h] = "\n".join(parts)
    return refs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", default=str(HERE.parent / "bear_parlor" / "session_logs" / "v6"))
    ap.add_argument("--hat-dir", default=str(HERE.parent / "bear_parlor" / "instructions" / "hats"))
    args = ap.parse_args()

    sessions = select_sessions(Path(args.log_dir))
    missing = [(t, c) for t in TOPICS for c in CONDITIONS if (t, c) not in sessions]
    if missing:
        sys.exit(f"missing sessions for: {missing}")
    bad = [md.name for md, _ in sessions.values() if not check_session(md)[0]]
    if bad:
        sys.exit(f"refusing to analyse sessions that fail the integrity check: {bad}")

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL)
    refs = reference_texts(Path(args.hat_dir))
    R = model.encode([refs[h] for h in HATS], normalize_embeddings=True)

    notes = {}
    for (t, c), (_, kj) in sessions.items():
        for h, texts in store_notes(kj).items():
            notes[(c, t, h)] = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    pooled = np.vstack(list(notes.values())) @ R.T
    col_mean, col_sd = pooled.mean(axis=0), pooled.std(axis=0)

    scorings = {
        "raw": lambda S: S,
        "corrected": lambda S: (S - col_mean) / col_sd,
    }
    out = {"log_dir": args.log_dir, "embedding_model": EMBEDDING_MODEL, "chance": CHANCE,
           "reference": "persona + method instructions per hat",
           "reference_mean_similarity": {h: float(m) for h, m in zip(HATS, col_mean)},
           "wrong_lens_map": WRONG_LENS_MAP, "scorings": {}}

    for name, score in scorings.items():
        per = {c: {"storing_hat": [], "lens_hat": []} for c in CONDITIONS}
        confusion = {c: Counter() for c in CONDITIONS}
        for c in CONDITIONS:
            for t in TOPICS:
                own = lens = n = 0
                for h in HATS:
                    if (c, t, h) not in notes:
                        continue
                    pred = [HATS[i] for i in score(notes[(c, t, h)] @ R.T).argmax(axis=1)]
                    lens_hat = WRONG_LENS_MAP[h] if c == "wrong-lens" else h
                    own += sum(p == h for p in pred)
                    lens += sum(p == lens_hat for p in pred)
                    n += len(pred)
                    confusion[c].update((h, p) for p in pred)
                per[c]["storing_hat"].append(own / n)
                per[c]["lens_hat"].append(lens / n)

        def test(a, ka, b, kb, label):
            st = paired_stats(per[a][ka], per[b][kb])
            return {"comparison": label, "mean_a": float(np.mean(per[a][ka])), "mean_b": float(np.mean(per[b][kb])),
                    "a_greater_in": int(sum(x > y for x, y in zip(per[a][ka], per[b][kb]))),
                    **{k: float(v) for k, v in st.items()}}

        tests = [
            test("bear", "storing_hat", "naive", "storing_hat", "match to storing hat: bear vs naive"),
            test("bear", "storing_hat", "wrong-lens", "storing_hat", "match to storing hat: bear vs wrong lens"),
            test("wrong-lens", "lens_hat", "wrong-lens", "storing_hat", "wrong lens: match to lens hat vs storing hat"),
        ]
        out["scorings"][name] = {
            "per_topic": {c: {k: dict(zip(TOPICS, v)) for k, v in per[c].items()} for c in CONDITIONS},
            "mean": {c: {k: float(np.mean(v)) for k, v in per[c].items()} for c in CONDITIONS},
            "paired_tests": tests,
            "confusion": {c: {h: {p: confusion[c][(h, p)] for p in HATS} for h in HATS} for c in CONDITIONS},
        }

        print(f"\n[{name}] share of notes closest to ... (chance {CHANCE:.3f})")
        print(f"  {'condition':<11}{'storing hat':>13}{'lens hat':>10}")
        for c in CONDITIONS:
            m = out["scorings"][name]["mean"][c]
            print(f"  {c:<11}{m['storing_hat']:>13.3f}{m['lens_hat']:>10.3f}")
        for st in tests:
            print(f"  {st['comparison']:<46} {st['mean_a']:.3f} vs {st['mean_b']:.3f}  "
                  f"{st['a_greater_in']}/8  Wilcoxon p={st['wilcoxon_p']:.3g}")

    dest = HERE / "results" / "v6_role_alignment.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nWrote {dest}")


if __name__ == "__main__":
    main()
