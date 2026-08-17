"""Role prompting behavioral divergence: compare BEAR vs Role vs Static.

For each scenario pair, generates LLM responses using three system prompt
strategies and measures output divergence:
  - BEAR: context-dependent composed prompts (different per context)
  - Role: single-sentence role description (same within species)
  - Static: all instructions concatenated (same for all contexts)

Requires a running LM Studio (or OpenAI-compatible) server.

Usage:
    python eval_role_divergence.py
    python eval_role_divergence.py --base-url http://localhost:1234/v1
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from bear import Corpus, Config, Context, Retriever, Composer, CompositionStrategy, EmbeddingBackend
from bear.models import ScoredInstruction
from bear.retriever import Embedder

try:
    from bear.utils import detect_local_llm_url
    DEFAULT_LOCAL_URL = detect_local_llm_url()
except ImportError:
    DEFAULT_LOCAL_URL = "http://127.0.0.1:1234/v1"
DEFAULT_MODEL = "mistral-nemo-instruct-2407"

ROLE_PROMPTS = {
    "dog": (
        "You are a playful, loyal golden retriever named Buddy. You love balls, "
        "treats, belly rubs, and your owner. You are friendly to familiar people "
        "but cautious around strangers. You obey basic commands enthusiastically. "
        "Always stay within the play area and never be aggressive."
    ),
    "cat": (
        "You are an independent, dignified tabby cat named Whiskers. You are "
        "aloof but affectionate with those you trust. You enjoy perching on high "
        "surfaces, ignoring commands, and batting at small objects. You tolerate "
        "the dog. Always stay within the play area and never be aggressive."
    ),
}

SCENARIOS = [
    ("Ball: dog vs cat",
     "A ball has appeared nearby. Describe what happens.",
     ["dog", "ball_present", "stimulus_present"],
     ["cat", "ball_present", "stimulus_present"]),
    ("Treat: dog vs cat",
     "A treat has appeared nearby. Describe the reaction.",
     ["dog", "treat_present", "stimulus_present"],
     ["cat", "treat_present", "stimulus_present"]),
    ("Idle: dog vs cat",
     "The pet is idle with nothing to do. What does it do?",
     ["dog", "idle"],
     ["cat", "idle"]),
    ("Petted: bonded vs wary (dog)",
     "A player is petting the dog. Describe the reaction.",
     ["dog", "being_petted", "player_bonded"],
     ["dog", "being_petted", "player_wary"]),
    ("Petted: bonded vs wary (cat)",
     "A player is petting the cat. Describe the reaction.",
     ["cat", "being_petted", "player_bonded"],
     ["cat", "being_petted", "player_wary"]),
    ("Mood: excited vs sleepy (dog)",
     "The dog is in a strong mood. Describe its behavior.",
     ["dog", "mood_excited"],
     ["dog", "mood_sleepy"]),
    ("Mood: playful vs cautious (cat)",
     "The cat is in a distinctive mood. Describe its behavior.",
     ["cat", "mood_playful"],
     ["cat", "mood_cautious"]),
    ("Near cat: playful vs default (dog)",
     "The dog is near the cat. Describe the interaction.",
     ["dog", "cat_nearby", "mood_playful"],
     ["dog", "cat_nearby"]),
    ("Near dog: content vs annoyed (cat)",
     "The cat is near the dog. Describe the behavior.",
     ["cat", "dog_nearby", "mood_content"],
     ["cat", "dog_nearby", "mood_annoyed"]),
    ("Command: sit (dog)",
     "The owner gives a command. Describe the reaction.",
     ["dog", "verbal_command"],
     ["dog", "verbal_command"]),
]


def call_llm(system_prompt, user_message, model, base_url, temp=0.0):
    """Call OpenAI-compatible local server."""
    import urllib.request
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temp,
        "max_tokens": 200,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


def content_diff(a, b):
    ta, tb = a.split(), b.split()
    if not ta and not tb:
        return 0.0
    ca, cb = Counter(ta), Counter(tb)
    diff = sum(abs(ca.get(t, 0) - cb.get(t, 0)) for t in set(ca) | set(cb))
    return diff / (len(ta) + len(tb))


def cosine_dist(a, b):
    d = np.dot(a, b)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - d / (na * nb)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_LOCAL_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    corpus = Corpus.from_directory(
        str(project_root / "pet_sim" / "instructions")
    )

    config = Config(
        embedding_model="hash", embedding_backend=EmbeddingBackend.NUMPY,
        priority_weight=0.3, default_threshold=0.3, default_top_k=10,
        mandatory_tags=["safety"],
    )
    retriever = Retriever(corpus, config=config)
    retriever.build_index()
    composer = Composer(strategy=CompositionStrategy.HIERARCHICAL)
    embedder = Embedder(model_name="hash", dim=768)

    # Static baseline
    all_scored = [
        ScoredInstruction(
            instruction=inst, similarity=1.0,
            scope_match=True, final_score=inst.priority / 100.0,
        )
        for inst in corpus
    ]
    static_prompt = str(composer.compose(all_scored))

    for temp in [0.0, 0.7]:
        print(f"\n{'=' * 70}")
        print(f"Temperature = {temp}")
        print(f"{'=' * 70}")

        bear_cd, bear_cos = [], []
        role_cd, role_cos = [], []
        static_cd, static_cos = [], []

        for name, user_msg, tags_a, tags_b in SCENARIOS:
            species_a = "dog" if "dog" in tags_a else "cat"
            species_b = "dog" if "dog" in tags_b else "cat"

            # BEAR
            prompt_a = str(composer.compose(
                retriever.retrieve(user_msg, Context(tags=tags_a))))
            prompt_b = str(composer.compose(
                retriever.retrieve(user_msg, Context(tags=tags_b))))
            resp_bear_a = call_llm(prompt_a, user_msg, args.model, args.base_url, temp)
            resp_bear_b = call_llm(prompt_b, user_msg, args.model, args.base_url, temp)

            # Role
            resp_role_a = call_llm(ROLE_PROMPTS[species_a], user_msg, args.model, args.base_url, temp)
            resp_role_b = call_llm(ROLE_PROMPTS[species_b], user_msg, args.model, args.base_url, temp)

            # Static
            resp_static_a = call_llm(static_prompt, user_msg, args.model, args.base_url, temp)
            resp_static_b = call_llm(static_prompt, user_msg, args.model, args.base_url, temp)

            # Metrics
            b_cd = content_diff(resp_bear_a, resp_bear_b)
            b_cos = cosine_dist(embedder.embed_single(resp_bear_a), embedder.embed_single(resp_bear_b))
            bear_cd.append(b_cd)
            bear_cos.append(b_cos)

            r_cd = content_diff(resp_role_a, resp_role_b)
            r_cos = cosine_dist(embedder.embed_single(resp_role_a), embedder.embed_single(resp_role_b))
            role_cd.append(r_cd)
            role_cos.append(r_cos)

            s_cd = content_diff(resp_static_a, resp_static_b)
            s_cos = cosine_dist(embedder.embed_single(resp_static_a), embedder.embed_single(resp_static_b))
            static_cd.append(s_cd)
            static_cos.append(s_cos)

            print(f"  {name}: "
                  f"BEAR cd={b_cd:.3f} cos={b_cos:.3f} | "
                  f"Role cd={r_cd:.3f} cos={r_cos:.3f} | "
                  f"Static cd={s_cd:.3f} cos={s_cos:.3f}")

        avg = lambda x: sum(x) / len(x)
        print(f"\n  Mean:")
        print(f"    BEAR:   cd={avg(bear_cd):.3f}  cos={avg(bear_cos):.3f}")
        print(f"    Role:   cd={avg(role_cd):.3f}  cos={avg(role_cos):.3f}")
        print(f"    Static: cd={avg(static_cd):.3f}  cos={avg(static_cos):.3f}")


if __name__ == "__main__":
    main()
