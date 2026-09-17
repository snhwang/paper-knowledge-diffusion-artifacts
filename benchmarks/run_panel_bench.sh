#!/usr/bin/env bash
# Run the paper's panel benchmarks (benchmarks/panel_bench.py).
#
# Usage:
#   benchmarks/run_panel_bench.sh <target> [--detach] [panel_bench options...]
#   benchmarks/run_panel_bench.sh status
#
# Targets:
#   sct-haiku           SCT-Bench on Claude Haiku 4.5 (Anthropic API)
#   sct-qwen            SCT-Bench on qwen3.8-flash-next (local model server)
#   brainteaser-haiku   BRAINTEASER, sentence + word puzzles, on Claude Haiku 4.5
#   brainteaser-qwen    BRAINTEASER, sentence + word puzzles, on qwen3.8-flash-next
#   sct-qwen27b         SCT-Bench on Qwen3.8-27B (local server, port 8355)
#   brainteaser-qwen27b BRAINTEASER, sentence + word puzzles, on Qwen3.8-27B
#   sct-gptoss20b         SCT-Bench on gpt-oss:20b (Ollama)
#   brainteaser-gptoss20b BRAINTEASER on gpt-oss:20b -- the April paper's
#   sct-gptoss120b        improving model (single SP 0.574, panel 0.787)
#   brainteaser-gptoss120b  same for gpt-oss:120b (single SP 0.710, panel 0.846)
#     Both need the model pulled first: ollama pull gpt-oss:20b
#
# Examples:
#   benchmarks/run_panel_bench.sh sct-haiku --n 10        # quick check, 10 items
#   benchmarks/run_panel_bench.sh sct-haiku               # full run in this terminal
#   benchmarks/run_panel_bench.sh sct-qwen --detach       # full run in the background
#   benchmarks/run_panel_bench.sh sct-qwen --analyze      # print results so far
#   benchmarks/run_panel_bench.sh status                  # what is running, progress
#
# A full run can be stopped and restarted: finished items are skipped. The
# script refuses to start a benchmark/model that is already running.
# Logs: results/panel_bench_<target>.log. Results: results/panel_bench/.

set -euo pipefail

# --- model access -----------------------------------------------------------
QWEN_MODEL="qwen3.8-flash-next"
QWEN_URL="http://192.168.1.176:9010/v1"
QWEN_KEY_ENV="THEMINDFOLD_API_KEY"   # read from .env; only this variable
QWEN_CONCURRENCY=8
HAIKU_MODEL="claude-haiku-4-5-20251001"   # ANTHROPIC_API_KEY is read from bear-dev/.env
HAIKU_CONCURRENCY=4
# Qwen3.8-27B on the local server. Override with environment variables if the
# server reports another model id or runs elsewhere; the model id names the
# results directory, so keep it the same across runs. Set QWEN27B_KEY_ENV to
# the .env variable holding the key if the server needs one.
QWEN27B_MODEL="${QWEN27B_MODEL:-Qwen3.8-27B}"
QWEN27B_URL="${QWEN27B_URL:-http://localhost:8355/v1}"
QWEN27B_KEY_ENV="${QWEN27B_KEY_ENV:-}"
QWEN27B_CONCURRENCY="${QWEN27B_CONCURRENCY:-4}"
# GPT-OSS through Ollama, as in the April runs (gpt-oss:120b / gpt-oss:20b at
# localhost:11434). These are the models that improved on BRAINTEASER.
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434/v1}"
OLLAMA_CONCURRENCY="${OLLAMA_CONCURRENCY:-2}"
# ------------------------------------------------------------------------------

cd "$(dirname "$0")/.."
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

usage() { sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

status() {
    echo "Running panel_bench processes:"
    pgrep -af "benchmarks/panel_bench.py" | grep -v pgrep || echo "  none"
    echo
    for dir in results/panel_bench/*/*/; do
        [[ -d "$dir" ]] || continue
        echo "${dir#results/panel_bench/}"
        for cond in single consistency role-majority panel; do
            f="$dir$cond.jsonl"
            if [[ -f "$f" ]]; then
                printf "  %-14s %4s items\n" "$cond" "$(grep -c . "$f")"
            fi
        done
        if [[ -f "$dir.lock" ]]; then
            echo "  (locked: $(cat "$dir.lock"))"
        fi
    done
}

[[ $# -ge 1 ]] || usage 1
target="$1"; shift
case "$target" in
    -h|--help) usage 0 ;;
    status) status; exit 0 ;;
    sct-haiku)         bench=sct;         model_args=(--model "$HAIKU_MODEL" --concurrency "$HAIKU_CONCURRENCY") ;;
    sct-qwen)          bench=sct;         model_args=(--model "$QWEN_MODEL" --base-url "$QWEN_URL" --api-key-env "$QWEN_KEY_ENV" --concurrency "$QWEN_CONCURRENCY") ;;
    brainteaser-haiku) bench=brainteaser; model_args=(--model "$HAIKU_MODEL" --concurrency "$HAIKU_CONCURRENCY" --puzzle-type both) ;;
    brainteaser-qwen)  bench=brainteaser; model_args=(--model "$QWEN_MODEL" --base-url "$QWEN_URL" --api-key-env "$QWEN_KEY_ENV" --concurrency "$QWEN_CONCURRENCY" --puzzle-type both) ;;
    sct-qwen27b|brainteaser-qwen27b)
        bench="${target%-qwen27b}"
        model_args=(--model "$QWEN27B_MODEL" --base-url "$QWEN27B_URL" --concurrency "$QWEN27B_CONCURRENCY")
        if [[ -n "$QWEN27B_KEY_ENV" ]]; then model_args+=(--api-key-env "$QWEN27B_KEY_ENV"); fi
        if [[ "$bench" == brainteaser ]]; then model_args+=(--puzzle-type both); fi
        ;;
    sct-gptoss20b|brainteaser-gptoss20b|sct-gptoss120b|brainteaser-gptoss120b)
        bench="${target%%-*}"
        size="${target##*-gptoss}"
        model_args=(--model "gpt-oss:${size}" --base-url "$OLLAMA_URL" --concurrency "$OLLAMA_CONCURRENCY")
        if [[ "$bench" == brainteaser ]]; then model_args+=(--puzzle-type both); fi
        ;;
    *) echo "unknown target: $target"; usage 1 ;;
esac

detach=0; analyze=0; extra=()
for a in "$@"; do
    case "$a" in
        --detach) detach=1 ;;
        --analyze) analyze=1; extra+=("$a") ;;
        *) extra+=("$a") ;;
    esac
done

model="${model_args[1]}"
cmd=(python -u benchmarks/panel_bench.py "$bench" "${model_args[@]}" "${extra[@]+"${extra[@]}"}")

if [[ $analyze -eq 0 ]] && pgrep -f "benchmarks/panel_bench.py $bench --model $model" >/dev/null; then
    echo "A $bench run on $model is already in progress:"
    pgrep -af "benchmarks/panel_bench.py $bench --model $model"
    echo "Wait for it to finish, or stop it first. Check progress with: $0 status"
    exit 1
fi

if [[ $detach -eq 1 && $analyze -eq 0 ]]; then
    log="results/panel_bench_${target}.log"
    mkdir -p results
    setsid nohup "${cmd[@]}" >>"$log" 2>&1 < /dev/null &
    echo "Started $target in the background (pid $!). Log: $log"
    echo "Progress: $0 status    or    tail -f $log"
else
    "${cmd[@]}"
fi
