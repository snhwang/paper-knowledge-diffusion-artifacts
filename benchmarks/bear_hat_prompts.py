"""Hat system prompts for the benchmark panels, built by BEAR.

The April benchmark runs took hat prompts from hard-coded dictionaries, so BEAR
was never used. Here each hat's system prompt is retrieved and composed by BEAR
the way BEAR Parlor builds a speaking turn: the ``benchmark-hats`` panel's
instruction directories plus its room context, retrieval against the item text
with the hat id and its default mood as context tags, top 10, hierarchical
composition.

The benchmark panel loads only the hat instructions. The chat panels' common
constraints ("respond ONLY with dialogue ...", "you are a person having a
conversation") would conflict with a required answer format.

BEAR itself must come from the bear-dev checkout: the pinned PyPI-style package
in requirements.txt predates the retrieval gating fixes. use_bear_dev() puts
bear-dev first on sys.path and must run before anything imports ``bear``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACTS_ROOT = HERE.parent
PARLOR_DIR = ARTIFACTS_ROOT / "bear_parlor"
PANEL_ID = "benchmark-hats"
TOP_K = 10                 # Parlor's speaking retrieval
DEFAULT_MOOD = "content"   # Parlor's MoodTracker default
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"


def use_bear_dev(path: str | None = None) -> Path:
    """Import BEAR from the bear-dev checkout; fail if another copy is loaded."""
    root = Path(path or os.environ.get("BEAR_DEV_DIR")
                or ARTIFACTS_ROOT.parent / "bear-dev").resolve()
    if not (root / "bear" / "__init__.py").exists():
        sys.exit(f"bear-dev checkout not found at {root}; pass --bear-dev or set BEAR_DEV_DIR")
    if "bear" in sys.modules:
        loaded = Path(sys.modules["bear"].__file__).resolve()
        if root not in loaded.parents:
            sys.exit(f"bear was already imported from {loaded}, not {root}. "
                     "Call use_bear_dev() before importing bear.")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import bear
    loaded = Path(bear.__file__).resolve()
    if root not in loaded.parents:
        sys.exit(f"imported bear from {loaded}, expected {root}")
    return root


def git_commit(path: Path) -> dict:
    try:
        commit = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--", "bear"],
                                    capture_output=True, text=True, timeout=10).stdout.strip())
        return {"commit": commit or None, "uncommitted_changes_in_bear": dirty}
    except Exception:
        return {"commit": None, "uncommitted_changes_in_bear": None}


class BearHatPrompter:
    """Builds and caches BEAR-composed system prompts per (hat, item)."""

    def __init__(self, bear_dev: Path, panel_id: str = PANEL_ID, parlor_dir: Path = PARLOR_DIR):
        import yaml
        from bear import Composer, Context, Corpus, Retriever
        from bear.composer import CompositionStrategy
        from bear.config import Config
        from bear.models import Instruction, InstructionType

        self.bear_dev = bear_dev
        panels = yaml.safe_load((parlor_dir / "panels.yaml").read_text(encoding="utf-8"))["panels"]
        panel = next((p for p in panels if p["id"] == panel_id), None)
        if panel is None:
            sys.exit(f"panel '{panel_id}' not found in {parlor_dir / 'panels.yaml'}")
        chars = yaml.safe_load((parlor_dir / "characters.yaml").read_text(encoding="utf-8"))["characters"]
        self._names = {c["id"]: c["name"] for c in chars}

        corpus = Corpus()
        self.instruction_dirs = list(panel.get("instruction_dirs") or [])
        for sub in self.instruction_dirs:
            d = parlor_dir / "instructions" / sub
            if not d.is_dir():
                sys.exit(f"instruction dir not found: {d}")
            corpus.add_many(Corpus.from_directory(str(d)).instructions)
        room = (panel.get("room_context") or "").strip()
        if room:
            corpus.add(Instruction(id=f"room-context-{panel_id}", type=InstructionType.CONSTRAINT,
                                   priority=95, content=room, tags=["room-context", "safety"]))

        self._retriever = Retriever(corpus, config=Config(embedding_model=EMBEDDING_MODEL,
                                                          mandatory_tags=["safety"]))
        self._retriever.build_index()
        self._composer = Composer(strategy=CompositionStrategy.HIERARCHICAL)
        self._Context = Context
        self._cache: dict[tuple[str, str], tuple[str, list[str]]] = {}
        self.panel_id = panel_id
        self.n_instructions = len(corpus)
        self.room_context = room

    def system_prompt(self, hat: str, item_text: str) -> tuple[str, list[str]]:
        """(system prompt, retrieved instruction ids) for one hat on one item."""
        hat_id = hat if hat.endswith("-hat") else f"{hat}-hat"
        key = (hat_id, item_text)
        if key not in self._cache:
            ctx = self._Context(domain="conversation", tags=[hat_id, DEFAULT_MOOD], query=item_text)
            scored = self._retriever.retrieve(query=item_text, context=ctx, top_k=TOP_K)
            composed = self._composer.compose(scored)
            guidance = getattr(composed, "guidance", None) or str(composed)
            system = (f"You are {self._names[hat_id]} on a Six Thinking Hats panel.\n"
                      f"Follow the behavioral guidance below.\n\n{guidance}")
            self._cache[key] = (system, [s.instruction.id for s in scored])
        return self._cache[key]

    def describe(self) -> dict:
        return {"source": "bear", "panel_id": self.panel_id, "instruction_dirs": self.instruction_dirs,
                "n_instructions": self.n_instructions, "top_k": TOP_K, "context_mood": DEFAULT_MOOD,
                "embedding_model": EMBEDDING_MODEL, "room_context": self.room_context,
                "bear_dev": str(self.bear_dev), **git_commit(self.bear_dev)}
