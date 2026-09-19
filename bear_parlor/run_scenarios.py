r"""Run the scenario sessions (incident response, paper review) against BEAR Parlor.

A case is a folder with a ``session.yaml``::

    panel: incident-response          # panel id in panels.yaml
    documents:                        # ingested in order into the shared "source" store
      - file: 01-alert.md             # .md/.txt (front matter gives classification) or .pdf
        title: First alert            # optional; default: file stem
        hat_id: source                # optional; a role id ingests into that role's store
    prompts:                          # phase 1: facilitator prompts over the bridge/panel
      - "What happened, and what is the current state?"
    questions:                        # phase 2 (optional): each role alone, own store only
      comms:
        - {id: X01-F07, text: "What vulnerability was exploited?"}

Phase 1 runs over the WebSocket like the v6 sessions: documents are posted
to /ingest (document diffusion offers every chunk to every role's lens,
gated), then each prompt is sent and the panel talks. Phase 2 posts each
question to /ask, where the role answers with no history and only its own
knowledge store and memories. Everything is recorded by the server in the
session log, its .stats.json (gate events, RAG provenance, answers) and the
.knowledge.json snapshot; answers are also written beside the logs.

Conditions (server flags; document diffusion is on in all of them):
    bear           lenses + access gate
    naive          verbatim copying, no lens, no gate
    shared-memory  lenses, but every role reads the union of all stores
    no-gate        lenses, access gate off
    wrong-lens     lenses rotated one role, gate on

Usage (from the artifacts repo root, with its .venv, in WSL):
    python bear_parlor/run_scenarios.py --scenario incident --case xyz-01 \
        --condition bear naive shared-memory no-gate wrong-lens \
        --backend openai --model Qwen3.8-27B --base-url http://localhost:8355/v1

    python bear_parlor/run_scenarios.py --scenario review --case dti-ad \
        --condition bear naive wrong-lens --backend openai --model Qwen3.8-27B \
        --base-url http://localhost:8355/v1

The Parlor server is driven from the bear-dev checkout (see run_sessions.py
for --parlor-dir / BEAR_PARLOR_DIR).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Reuses the v6 runner's helpers: Parlor directory resolution, env, waiting
# for the server, state isolation. Importing it resolves --parlor-dir.
import run_sessions as v6  # noqa: E402

HERE = v6.HERE
ARTIFACTS_ROOT = v6.ARTIFACTS_ROOT
SCENARIOS_ROOT = ARTIFACTS_ROOT / "scenarios"
SERVER_URL = v6.SERVER_URL   # replaced per run once a port is chosen
WS_URL = v6.WS_URL


def free_port() -> int:
    """A port nothing is listening on. The v6 runner assumed 8000, and a
    stray service there made its readiness check pass against the wrong
    server."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def use_port(port: int) -> None:
    global SERVER_URL, WS_URL
    SERVER_URL = f"http://localhost:{port}"
    WS_URL = f"ws://localhost:{port}/ws"
    v6.SERVER_URL, v6.WS_URL = SERVER_URL, WS_URL


async def wait_for_parlor(panel: str, timeout: int = 300) -> None:
    """Wait until /health answers from a BEAR Parlor serving this panel."""
    import time
    import aiohttp
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{SERVER_URL}/health", timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status == 200:
                        d = await r.json()
                        if d.get("service") == "bear-parlor" and d.get("panel") == panel and d.get("ready"):
                            return
                        if d.get("service") != "bear-parlor":
                            raise RuntimeError(f"{SERVER_URL} is not a BEAR Parlor server")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            pass
        await asyncio.sleep(1)
    raise RuntimeError(f"Parlor did not become ready on {SERVER_URL} within {timeout}s")

# In every condition, gated diffusion is the only path into a role's stores:
# the session-insight extractor and the memory manager, which write from the
# shared conversation outside the gate, are off. The first live session showed
# insights carrying hostnames and ticket ids into Support's store that way.
COMMON = ["--document-diffusion", "--no-insights", "--no-memories"]
CONDITIONS = {
    "bear":          COMMON,
    "naive":         ["--naive-diffusion"] + COMMON,
    "shared-memory": ["--shared-knowledge"] + COMMON,
    "no-gate":       ["--no-gate"] + COMMON,
    "wrong-lens":    ["--wrong-lens"] + COMMON,
}
_OPTS: dict = {}


def load_case(scenario: str, case: str) -> tuple[Path, dict]:
    folder = SCENARIOS_ROOT / scenario / case
    spec_path = folder / "session.yaml"
    if not spec_path.exists():
        sys.exit(f"no session.yaml in {folder}")
    import yaml
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    for key in ("panel", "documents", "prompts"):
        if key not in spec:
            sys.exit(f"{spec_path}: missing '{key}'")
    for d in spec["documents"]:
        if not (folder / d["file"]).exists():
            sys.exit(f"{spec_path}: document not found: {d['file']}")
    return folder, spec


# ── HTTP / WS ────────────────────────────────────────────────────────────────

async def ingest_http(hat_id: str, path: Path, title: str | None = None,
                      classification: list[str] | None = None) -> dict:
    """POST one document to /ingest. Markdown carries its own classification."""
    import aiohttp
    ctype = {"pdf": "application/pdf", "md": "text/markdown",
             "txt": "text/plain"}.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    async with aiohttp.ClientSession() as s:
        with open(path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("hat_id", hat_id)
            data.add_field("title", title or path.stem)
            data.add_field("classification", ",".join(classification or []))
            data.add_field("file", f, filename=path.name, content_type=ctype)
            async with s.post(f"{SERVER_URL}/ingest", data=data,
                              timeout=aiohttp.ClientTimeout(total=1800)) as resp:
                result = await resp.json()
                print(f"  [Ingest] {path.name} -> {hat_id}: {result}")
                return result


async def ask_http(hat_id: str, question: str, question_id: str | None) -> dict:
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{SERVER_URL}/ask",
                          json={"hat_id": hat_id, "question": question, "question_id": question_id},
                          timeout=aiohttp.ClientTimeout(total=600)) as resp:
            return await resp.json()


async def run_phase1(folder: Path, spec: dict) -> int:
    """Ingest the documents, then run the facilitator prompts. Returns turns."""
    import aiohttp
    turn_count = 0
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(WS_URL) as ws:
            async def reader():
                nonlocal turn_count
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("type") == "message":
                            turn_count += 1
                            print(f"  [{turn_count}] {data.get('sender_name', '?')}: "
                                  f"{data.get('content', '')[:80]}...")
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break

            reader_task = asyncio.create_task(reader())
            await asyncio.sleep(_OPTS["settle"])

            for d in spec["documents"]:
                path = folder / d["file"]
                tags = d.get("classification")
                await ingest_http(d.get("hat_id", "source"), path, d.get("title"),
                                  list(tags) if tags else None)
                await asyncio.sleep(_OPTS["ingest_wait"])

            for prompt in spec["prompts"]:
                print(f"\n>>> FACILITATOR: {prompt}")
                await ws.send_str(json.dumps({"type": "chat", "content": prompt}))
                await asyncio.sleep(_OPTS["chat_wait"])

            # let background utterance diffusion drain before phase 2
            await asyncio.sleep(_OPTS["drain"])
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
    return turn_count


async def run_phase2(spec: dict) -> list[dict]:
    answers = []
    for role, qs in (spec.get("questions") or {}).items():
        for q in qs:
            r = await ask_http(role, q["text"], q.get("id"))
            if not r.get("success"):
                print(f"  [Ask] {role} {q.get('id')}: {r}")
                answers.append({"hat_id": role, "question_id": q.get("id"),
                                "question": q["text"], "answer": None, "error": r.get("error")})
                continue
            print(f"  [Ask] {role} {q.get('id')}: {r['answer'][:90]}...")
            answers.append({k: r.get(k) for k in ("hat_id", "hat_name", "question_id",
                                                  "question", "answer", "retrieved")})
    return answers


# ── one session ───────────────────────────────────────────────────────────────

def build_server_cmd(panel: str, case: str, condition: str, port: int) -> list[str]:
    cmd = [
        sys.executable, "-u", "parlor.py",
        "--panel", panel,
        "--port", str(port),
        "--backend", _OPTS["backend"],
        "--model", _OPTS["model"],
        "--override-model",
        "--topic-meta", case,
        "--condition-meta", condition,
        "--log-subdir", _OPTS["log_subdir"],
    ]
    cmd.extend(CONDITIONS[condition])
    return cmd


def wipe_knowledge(panel: str) -> None:
    import platform
    import tempfile
    is_wsl = ("microsoft" in platform.uname().release.lower()
              or os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop"))
    kb = (Path(tempfile.gettempdir()) / "bear_knowledge" / panel if is_wsl
          else HERE / "panel_data" / "knowledge")
    if kb.exists():
        shutil.rmtree(kb)
        print(f"  Wiped knowledge store: {kb}")


def _newest_log(panel: str, started_after: float) -> Path | None:
    logs = sorted((HERE / "session_logs" / _OPTS["log_subdir"]).glob(f"{panel}_*.md"),
                  key=lambda p: p.stat().st_mtime)
    logs = [p for p in logs if p.stat().st_mtime >= started_after - 5]
    return logs[-1] if logs else None


async def run_session(scenario: str, case: str, condition: str) -> None:
    folder, spec = load_case(scenario, case)
    panel = spec["panel"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n{'=' * 60}\nStarting: {scenario}/{case} / {condition} / {timestamp}\n{'=' * 60}")

    wipe_knowledge(panel)
    v6.PANEL_ID = panel            # isolate/collect look for this panel's state files
    v6._OPTS["log_subdir"] = _OPTS["log_subdir"]
    v6.isolate_panel_state()

    import time
    t0 = time.time()
    port = _OPTS.get("port") or free_port()
    use_port(port)
    print(f"  Parlor server on port {port}")
    server = subprocess.Popen(build_server_cmd(panel, case, condition, port), cwd=str(HERE), env=v6.server_env())
    answers: list[dict] = []
    try:
        await wait_for_parlor(panel, timeout=_OPTS["start_timeout"])
        await asyncio.sleep(2)
        turns = await run_phase1(folder, spec)
        print(f"\n  Phase 1 complete: {turns} turns")
        if spec.get("questions"):
            print("\n  Phase 2: each role answers alone")
            answers = await run_phase2(spec)
    finally:
        print("\nShutting down server (session summary and knowledge snapshot are written)...")
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
        v6.collect_panel_state(case, condition, timestamp)
        log = _newest_log(panel, t0)
        if answers and log:
            out = log.with_suffix("").with_suffix(".answers.json")
            out.write_text(json.dumps({"scenario": scenario, "case": case, "condition": condition,
                                       "panel": panel, "log": log.name, "answers": answers},
                                      indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  Answers written to {out}")
        print("Done.")


async def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True, choices=["incident", "review"])
    ap.add_argument("--case", nargs="+", required=True, help="case folder(s) under scenarios/<scenario>/")
    ap.add_argument("--condition", nargs="+", default=list(CONDITIONS), choices=list(CONDITIONS))
    ap.add_argument("--backend", default="openai")
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible server for every role")
    ap.add_argument("--api-key-env", default=None, help="variable holding that server's key (read narrowly)")
    ap.add_argument("--log-subdir", default="scenarios")
    ap.add_argument("--chat-wait", type=float, default=50.0, help="seconds after each prompt")
    ap.add_argument("--ingest-wait", type=float, default=5.0, help="seconds after each document")
    ap.add_argument("--settle", type=float, default=8.0, help="seconds after connecting")
    ap.add_argument("--drain", type=float, default=45.0, help="seconds for diffusion to drain before phase 2")
    ap.add_argument("--port", type=int, default=None, help="Parlor port (default: a free one)")
    ap.add_argument("--start-timeout", type=int, default=300,
                    help="seconds to wait for the server (imports from /mnt/c are slow)")
    args = ap.parse_args()

    _OPTS.update(vars(args))
    _OPTS["api_key"] = v6._read_env_var(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not _OPTS["api_key"]:
        sys.exit(f"{args.api_key_env} not found in the environment or a .env file")
    v6._OPTS.update({"backend": args.backend, "model": args.model, "base_url": args.base_url,
                     "api_key": _OPTS["api_key"], "log_subdir": args.log_subdir, "per_hat_models": False})

    for case in args.case:
        for condition in args.condition:
            await run_session(args.scenario, case, condition)
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
