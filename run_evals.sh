#!/usr/bin/env bash
# =============================================================================
# run_evals.sh — Knowledge Diffusion (BEAR paper series)
#
# Reproduces the session-log analyses from the knowledge-diffusion paper series
# (Six Thinking Hats panel deliberation, main paper bear_tiis.tex). The BBH
# and SCT benchmark papers (bear_tiis_bbh.tex, bear_tiis_sct.tex) use the
# scripts in benchmarks/ directly; see README for invocation.
#
# LLM REQUIREMENTS:
#   - Part A (session-log analysis) is deterministic (no LLM needed). It
#     analyzes pre-recorded logs in bear_parlor/session_logs/.
#   - eval_role_divergence.py requires:
#       LM Studio with: mistral-nemo-instruct-2407 at http://127.0.0.1:1234/v1
#
# EMBEDDING MODELS (downloaded automatically):
#   - BAAI/bge-base-en-v1.5 (768-dim) — all session-log analyses
#
# REQUIRED DATA (shipped in this repo):
#   - bear_parlor/session_logs/
#   - bear_parlor/instructions/hats/
#   - pet_sim/instructions/ (for eval_role_divergence corpus)
#
# Usage:
#   ./run_evals.sh                              # deterministic session-log analysis
#   ./run_evals.sh --all                        # include eval_role_divergence (LLM)
#   ./run_evals.sh --all --model nemotron-super # use specific model
# =============================================================================

set -e
cd "$(dirname "$0")"

# Detect WSL and resolve Windows host IP for LM Studio / Ollama
if grep -qi microsoft /proc/version 2>/dev/null; then
    WSL_HOST=$(ip route show default 2>/dev/null | awk '/default/{print $3}')
    if [[ -n "$WSL_HOST" ]]; then
        export LM_STUDIO_URL="http://${WSL_HOST}:1234/v1"
    fi
fi

ALL=false
MODEL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --all) ALL=true; shift ;;
        --model) MODEL="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

MODEL_ARGS=""
if [[ -n "$MODEL" ]]; then
    MODEL_ARGS="--model $MODEL"
fi

EVAL_DIR="evals"
PARLOR_DIR="bear_parlor"
RESULTS_DIR="results"
mkdir -p "$RESULTS_DIR"

echo "========================================"
echo "  Knowledge Diffusion (paper series)"
echo "========================================"
echo ""

# Check session logs exist
LOG_COUNT=$(ls "$PARLOR_DIR/session_logs"/brainstorming-hats_*.md 2>/dev/null | wc -l)
if [[ "$LOG_COUNT" -eq 0 ]]; then
    echo "ERROR: No session logs found in $PARLOR_DIR/session_logs/"
    exit 1
fi
echo "Found $LOG_COUNT session log(s)"
echo ""

# =====================================================================
# Part A: Session-log analysis (no LLM, uses BAAI/bge-base-en-v1.5)
# =====================================================================

echo "===== Part A: Session Log Analysis (no LLM) ====="
echo ""

echo "--- Inter-Hat Differentiation (centroid distances) ---"
python3 "$EVAL_DIR/eval_interhat_differentiation.py" | tee "$RESULTS_DIR/eval_interhat_output.txt"
echo ""

echo "--- Role Adherence (self-alignment, discrimination ratio) ---"
python3 "$EVAL_DIR/eval_role_adherence.py" | tee "$RESULTS_DIR/eval_role_adherence_output.txt"
echo ""

echo "--- Statistical Significance (t-tests, Wilcoxon, bootstrap, Holm-Bonferroni) ---"
python3 "$EVAL_DIR/eval_significance.py" | tee "$RESULTS_DIR/eval_significance_output.txt"
echo ""

echo "--- Embed-Only Baseline (naive vs embed-only vs BEAR dedup) ---"
python3 "$EVAL_DIR/eval_embed_only_baseline.py" | tee "$RESULTS_DIR/eval_embed_only_output.txt"
echo ""

echo "--- d_min Sensitivity Sweep (0.20 - 0.50) ---"
python3 "$EVAL_DIR/eval_dmin_sensitivity.py" | tee "$RESULTS_DIR/eval_dmin_output.txt"
echo ""

echo "--- Temporal Store Evolution (growth over turns) ---"
python3 "$EVAL_DIR/eval_temporal_evolution.py" | tee "$RESULTS_DIR/eval_temporal_output.txt"
echo ""

echo "--- Response Divergence (BEAR vs Naive inter-hat response distance) ---"
python3 "$EVAL_DIR/eval_response_divergence.py" | tee "$RESULTS_DIR/eval_response_divergence_output.txt"
echo ""

# =====================================================================
# Part B: LLM-dependent evals
# =====================================================================

if [[ "$ALL" == true ]]; then
    echo "===== Part B: LLM-Dependent Evals ====="
    echo ""

    echo "--- Role Divergence (BEAR vs Role vs Static prompt) ---"
    echo "  Expects: LM Studio with mistral-nemo-instruct-2407 at localhost:1234"
    python3 "$EVAL_DIR/eval_role_divergence.py" $MODEL_ARGS | tee "$RESULTS_DIR/eval_role_divergence_output.txt"
    echo ""
else
    echo "===== Skipping LLM-dependent evals (use --all to include) ====="
    echo "  eval_role_divergence.py  (needs LM Studio: mistral-nemo-instruct-2407)"
    echo ""
fi

echo "========================================"
echo "  Evals complete"
echo "  Results in: $RESULTS_DIR/"
echo "========================================"
