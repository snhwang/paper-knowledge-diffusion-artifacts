"""Panel benchmarks with BEAR-built hats and one task instruction for every condition.

Replaces the April harnesses (sct_eval_v2.py, brainteaser_eval.py), kept for the
record, which had three flaws:
  - hat prompts were hard-coded, so BEAR was never used;
  - role conditions asked for "2-3 sentences" while baselines asked for full
    reasoning, so every panel-vs-baseline difference mixed in answer length;
  - SCT-Bench had no role-majority condition, so roles and flow could not be
    separated, and BRAINTEASER's panel answered by Blue Hat synthesis while
    role-majority answered by vote.

Conditions (same model, same task text, same answer format, same output limit,
same parse-retry policy; aggregation is majority vote everywhere):

  single          one call, temperature 0, no system prompt
  consistency     N independent samples at temperature T, no system prompt
  role-majority   six hats, each with its BEAR-built system prompt, answering
                  independently at temperature T
  panel           the same six hats answering in turn at temperature T, each
                  seeing the earlier hats' answers

  consistency vs role-majority   isolates roles
  role-majority vs panel         isolates flow between hats

Every user message is: item text, [panel only: earlier answers], task
instruction. The task instruction is identical across conditions, and a hat's
system prompt is the only role content.

Results go to results/panel_bench/<benchmark>/<model>/<condition>.jsonl, one
line per item; rerunning skips items already done. A config.json per model
records the task text, prompt source and code versions, and a run refuses to
append to results produced under a different configuration.

Usage (from the artifacts repo root, with its .venv):
    python benchmarks/panel_bench.py sct --model claude-haiku-4-5-20251001
    python benchmarks/panel_bench.py brainteaser --model gpt-oss-120b \\
        --base-url <server>/v1 --api-key-env <VAR> --puzzle-type both
    python benchmarks/panel_bench.py sct --model claude-haiku-4-5-20251001 --analyze

Add --n 10 for a quick check, --conditions to run a subset.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from bear_hat_prompts import BearHatPrompter, git_commit, use_bear_dev  # noqa: E402

VERSION = "panel_bench 1.0"
CONDITIONS = ["single", "consistency", "role-majority", "panel"]
HAT_COUNT = 6


# ---------------------------------------------------------------------------
# Benchmarks: data, item text, task instruction, answer extraction, scoring.
# Data handling and scoring are imported from the April harnesses so scores
# stay comparable; their hat prompts are NOT used.
# ---------------------------------------------------------------------------

class SCT:
    name = "sct"
    hat_order = ["white", "red", "black", "yellow", "green", "blue"]
    max_tokens = 2048

    def __init__(self, args):
        import sct_eval_v2 as sct
        self.sct = sct
        self.task = (
            "Think through how the new information affects the hypothesis, then state "
            "your final rating in the format: Rating: X (where X is -2, -1, 0, +1, or +2)."
        )
        self.items = sct.load_questions(Path(args.data) if args.data else sct.DATA_PATH)

    def item_id(self, q):
        return str(q["id"])

    def item_text(self, q):
        return self.sct.SCT_GUIDELINE + self.sct.format_question(q)

    def extract(self, text):
        return self.sct.extract_rating(text)

    def score(self, q, answer):
        return self.sct.sct_score(q["expert_dist_norm"], answer) if answer is not None else 0.0

    def record(self, q):
        return {"source": q["source"]}


class Brainteaser:
    name = "brainteaser"
    hat_order = ["green", "white", "red", "black", "yellow", "blue"]
    max_tokens = 4096

    def __init__(self, args):
        import brainteaser_eval as bt
        self.bt = bt
        self.task = (
            "Think carefully about this puzzle. It requires lateral thinking — the obvious "
            "answer is likely wrong. Consider wordplay, double meanings, and unconventional "
            "interpretations. After your reasoning, state your final answer as a single letter "
            "(A, B, C, or D)."
        )
        files = {"sp": ["brainteaser_puzzles.json"], "wp": ["brainteaser_wp_puzzles.json"],
                 "both": ["brainteaser_puzzles.json", "brainteaser_wp_puzzles.json"]}[args.puzzle_type]
        self.items = [p for f in files for p in json.loads((HERE / f).read_text(encoding="utf-8"))]

    def item_id(self, p):
        return str(p["id"])

    def item_text(self, p):
        return self.bt.format_puzzle(p)

    def extract(self, text):
        return self.bt.extract_answer(text, 4)

    def score(self, p, answer):
        return 1.0 if answer is not None and answer == p["correct_index"] else 0.0

    def record(self, p):
        return {"type": p["id"].split("-")[0], "correct_index": p["correct_index"]}


BENCHMARKS = {"sct": SCT, "brainteaser": Brainteaser}


def user_message(bench, item, discussion=None) -> str:
    parts = [bench.item_text(item).rstrip(), ""]
    if discussion:
        parts.append("=== Panel discussion so far ===")
        for hat, text in discussion:
            parts += ["", f"[{hat.upper()} HAT]: {text}"]
        parts += ["", "=== End of discussion ===", ""]
    parts.append(bench.task)
    return "\n".join(parts)


def majority(votes: list) -> object | None:
    """Most common valid vote; ties go to the first seen. Same rule everywhere."""
    valid = [v for v in votes if v is not None]
    return Counter(valid).most_common(1)[0][0] if valid else None


# ---------------------------------------------------------------------------
# Model access. A self-hosted server always gets an explicit key, so the
# OpenAI backend never falls back to a cloud OPENAI_API_KEY from .env.
# ---------------------------------------------------------------------------

def read_env_var(name: str, bear_dev: Path) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    pat = re.compile(r"^(?:export\s+)?" + re.escape(name) + r"\s*=\s*(.*)$")
    for env in (ROOT / ".env", bear_dev / ".env"):
        if env.is_file():
            for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
                m = pat.match(line.strip())
                if m and m.group(1).strip().strip("'\""):
                    return m.group(1).strip().strip("'\"")
    return None


def make_backend(args, bear_dev: Path):
    if args.base_url:
        from bear.backends.llm.openai_backend import OpenAIBackend
        key = read_env_var(args.api_key_env, bear_dev) if args.api_key_env else None
        if args.api_key_env and not key:
            sys.exit(f"{args.api_key_env} not found in the environment or .env")
        return OpenAIBackend(model=args.model, base_url=args.base_url, api_key=key or "no-key",
                             no_system_role=args.no_system_role)
    if args.model.startswith("claude"):
        from bear.backends.llm.anthropic_backend import AnthropicBackend
        key = read_env_var("ANTHROPIC_API_KEY", bear_dev)
        if not key:
            sys.exit("ANTHROPIC_API_KEY not found")
        return AnthropicBackend(model=args.model, api_key=key)
    if args.model.startswith(("gpt-", "o1", "o3", "o4")):
        from bear.backends.llm.openai_backend import OpenAIBackend
        key = read_env_var("OPENAI_API_KEY", bear_dev)
        if not key:
            sys.exit("OPENAI_API_KEY not found")
        return OpenAIBackend(model=args.model, api_key=key)
    sys.exit(f"don't know how to reach model {args.model!r}; pass --base-url for a server")


class Caller:
    """One model call with the shared retry policy: up to 2 retries on errors
    and on answers that cannot be parsed, identical for every condition."""

    def __init__(self, backend, bench, args):
        from bear.backends.llm.base import GenerateRequest
        self.GenerateRequest, self.backend, self.bench, self.args = GenerateRequest, backend, bench, args
        self.sem = asyncio.Semaphore(args.concurrency)

    async def __call__(self, system: str, user: str, temperature: float) -> dict:
        last = ""
        async with self.sem:
            for attempt in range(3):
                try:
                    resp = await self.backend.generate(self.GenerateRequest(
                        system=system, user=user, temperature=temperature, top_p=self.args.top_p,
                        max_tokens=self.bench.max_tokens, thinking=self.args.thinking))
                    last = resp.content or ""
                    answer = self.bench.extract(last)
                    if answer is not None:
                        return {"answer": answer, "response": last, "attempts": attempt + 1}
                except Exception as e:  # noqa: BLE001
                    last = f"[error: {e}]"
                    await asyncio.sleep(3 * (attempt + 1))
        return {"answer": None, "response": last, "attempts": 3}


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

async def run_item(condition, bench, item, call, prompter, args):
    base = {"item_id": bench.item_id(item), **bench.record(item)}
    if condition == "single":
        r = await call("", user_message(bench, item), 0.0)
        return {**base, "answer": r["answer"], "score": bench.score(item, r["answer"]), "calls": [r]}

    if condition == "consistency":
        rs = await asyncio.gather(*[call("", user_message(bench, item), args.temperature)
                                    for _ in range(args.samples)])
        ans = majority([r["answer"] for r in rs])
        return {**base, "answer": ans, "score": bench.score(item, ans),
                "votes": [r["answer"] for r in rs], "calls": list(rs)}

    hats = bench.hat_order
    systems = {h: prompter.system_prompt(h, bench.item_text(item)) for h in hats}
    retrieved = {h: systems[h][1] for h in hats}

    if condition == "role-majority":
        rs = await asyncio.gather(*[call(systems[h][0], user_message(bench, item), args.temperature)
                                    for h in hats])
        by_hat = dict(zip(hats, rs))
    else:  # panel
        by_hat, discussion = {}, []
        for h in hats:
            r = await call(systems[h][0], user_message(bench, item, discussion), args.temperature)
            by_hat[h] = r
            discussion.append((h, r["response"]))
    votes = [by_hat[h]["answer"] for h in hats]
    ans = majority(votes)
    return {**base, "answer": ans, "score": bench.score(item, ans),
            "votes": dict(zip(hats, votes)), "bear_instructions": retrieved,
            "calls": [{"hat": h, **by_hat[h]} for h in hats]}


# ---------------------------------------------------------------------------
# Running, resuming, analysing
# ---------------------------------------------------------------------------

def run_config(bench, args, prompter, bear_dev):
    return {
        "version": VERSION, "benchmark": bench.name, "model": args.model, "base_url": args.base_url,
        "task_instruction": bench.task, "max_tokens": bench.max_tokens,
        "temperature_sampled": args.temperature, "temperature_single": 0.0,
        "consistency_samples": args.samples, "top_p": args.top_p, "thinking": args.thinking,
        "hat_order": bench.hat_order, "aggregation": "majority vote, ties to first seen",
        "parse_retries": 2, "puzzle_type": getattr(args, "puzzle_type", None),
        "role_prompts": prompter.describe(),
        "artifacts": git_commit(ROOT), "bear_dev": git_commit(bear_dev),
    }


def acquire_lock(out_dir: Path) -> None:
    """One run per results directory. Two runs appending to the same files would
    both work through the same unfinished items and duplicate them."""
    import atexit
    import socket
    lock = out_dir / ".lock"
    host = socket.gethostname()
    if lock.exists():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
            pid, lock_host = int(info["pid"]), info.get("host")
        except (ValueError, KeyError, OSError):
            pid, lock_host = None, None
        alive = False
        if pid is not None and lock_host == host:
            try:
                os.kill(pid, 0)
                alive = True
            except (OSError, SystemError):
                alive = False
        if alive or (pid is not None and lock_host != host):
            sys.exit(f"{out_dir} is locked by pid {pid} on {lock_host}. If that run is really gone, "
                     f"delete {lock}.")
    lock.write_text(json.dumps({"pid": os.getpid(), "host": host,
                                "started": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    atexit.register(lambda: lock.unlink(missing_ok=True))


def comparable(a: dict, b: dict) -> list[str]:
    """Config fields that must match for results to be appended."""
    keys = ["version", "benchmark", "model", "base_url", "task_instruction", "max_tokens",
            "temperature_sampled", "consistency_samples", "top_p", "thinking", "hat_order", "puzzle_type"]
    diffs = [k for k in keys if a.get(k) != b.get(k)]
    for k in ("instruction_dirs", "n_instructions", "top_k", "room_context", "commit"):
        if a["role_prompts"].get(k) != b["role_prompts"].get(k):
            diffs.append(f"role_prompts.{k}")
    return diffs


async def run(args):
    bear_dev = use_bear_dev(args.bear_dev)
    bench = BENCHMARKS[args.benchmark](args)
    items = bench.items[: args.n] if args.n else bench.items
    out_dir = Path(args.results_dir) / bench.name / args.model.replace("/", "_").replace(":", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    acquire_lock(out_dir)

    prompter = BearHatPrompter(bear_dev)
    cfg = run_config(bench, args, prompter, bear_dev)
    cfg_path = out_dir / "config.json"
    if cfg_path.exists():
        diffs = comparable(json.loads(cfg_path.read_text(encoding="utf-8")), cfg)
        if diffs and not args.force:
            sys.exit(f"{out_dir} holds results from a different configuration ({', '.join(diffs)}). "
                     "Use another --results-dir, or --force to append anyway.")
    else:
        cfg["created"] = datetime.now(timezone.utc).isoformat()
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    backend = make_backend(args, bear_dev)
    call = Caller(backend, bench, args)
    for condition in args.conditions:
        path = out_dir / f"{condition}.jsonl"
        done = set()
        if path.exists():
            done = {json.loads(l)["item_id"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
        todo = [it for it in items if bench.item_id(it) not in done]
        print(f"{bench.name} / {args.model} / {condition}: {len(done)} done, {len(todo)} to run")
        lock = asyncio.Lock()
        progress = {"n": 0}

        async def one(item):
            rec = await run_item(condition, bench, item, call, prompter, args)
            async with lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
                progress["n"] += 1
                if progress["n"] % 10 == 0 or progress["n"] == len(todo):
                    print(f"  {condition}: {progress['n']}/{len(todo)}")

        await asyncio.gather(*[one(it) for it in todo])
    analyze(args)


def paired_test(x, y, n_perm=20000, seed=20261025):
    """Mean difference y - x with a sign-flip permutation p-value (two-sided)."""
    import random
    d = [b - a for a, b in zip(x, y)]
    if not d:
        return None
    obs = sum(d) / len(d)
    rng, extreme = random.Random(seed), 0
    for _ in range(n_perm):
        s = sum(v if rng.random() < 0.5 else -v for v in d) / len(d)
        extreme += abs(s) >= abs(obs) - 1e-12
    return {"mean_difference": obs, "p": (extreme + 1) / (n_perm + 1), "n_items": len(d)}


def analyze(args):
    out_dir = Path(args.results_dir) / args.benchmark / args.model.replace("/", "_").replace(":", "_")
    recs = {}
    for c in CONDITIONS:
        p = out_dir / f"{c}.jsonl"
        if p.exists():
            recs[c] = {r["item_id"]: r for r in map(json.loads, p.read_text(encoding="utf-8").splitlines()) if r}
    if not recs:
        sys.exit(f"no results in {out_dir}")
    summary = {"conditions": {}, "comparisons": {}}
    print(f"\n{args.benchmark} / {args.model}   (score = {'SCT score' if args.benchmark == 'sct' else 'accuracy'})")
    for c, r in recs.items():
        scores = [v["score"] for v in r.values()]
        unparsed = sum(v["answer"] is None for v in r.values())
        summary["conditions"][c] = {"n_items": len(scores), "mean_score": sum(scores) / len(scores),
                                    "no_answer": unparsed}
        print(f"  {c:<14} n={len(scores):<4} mean={sum(scores)/len(scores):.3f}  no answer={unparsed}")
        if args.benchmark == "brainteaser":
            for t in sorted({v["type"] for v in r.values()}):
                s = [v["score"] for v in r.values() if v["type"] == t]
                summary["conditions"][c][f"mean_score_{t}"] = sum(s) / len(s)
                print(f"      {t}: n={len(s)} accuracy={sum(s)/len(s):.3f}")
    for a, b, label in [("single", "consistency", "sampling"), ("consistency", "role-majority", "roles"),
                        ("role-majority", "panel", "flow"), ("consistency", "panel", "roles + flow")]:
        if a in recs and b in recs:
            ids = sorted(set(recs[a]) & set(recs[b]))
            t = paired_test([recs[a][i]["score"] for i in ids], [recs[b][i]["score"] for i in ids])
            summary["comparisons"][f"{b} vs {a} ({label})"] = t
            print(f"  {label:<13} {b} - {a}: {t['mean_difference']:+.3f}  p={t['p']:.3g}  (n={t['n_items']})")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("benchmark", choices=sorted(BENCHMARKS))
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible server")
    ap.add_argument("--api-key-env", default=None, help="variable holding that server's key")
    ap.add_argument("--no-system-role", action="store_true",
                    help="for servers without a system role: system text is prefixed to the user message")
    ap.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=CONDITIONS)
    ap.add_argument("--n", type=int, default=0, help="first N items only (0 = all)")
    ap.add_argument("--temperature", type=float, default=0.5, help="for consistency, role-majority and panel")
    ap.add_argument("--samples", type=int, default=HAT_COUNT, help="consistency samples (default = number of hats)")
    ap.add_argument("--top-p", type=float, default=None)
    ap.add_argument("--thinking", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4, help="simultaneous model calls")
    ap.add_argument("--puzzle-type", choices=["sp", "wp", "both"], default="both", help="brainteaser only")
    ap.add_argument("--data", default=None, help="SCT CSV (default: the bundled dataset)")
    ap.add_argument("--results-dir", default=str(ROOT / "results" / "panel_bench"))
    ap.add_argument("--bear-dev", default=None, help="bear-dev checkout (default: sibling of this repo)")
    ap.add_argument("--analyze", action="store_true", help="summarise existing results only")
    ap.add_argument("--force", action="store_true", help="append despite a configuration mismatch")
    args = ap.parse_args()
    if args.analyze:
        analyze(args)
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
