#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON=""
for candidate in "$ROOT/.venv/bin/python" "$ROOT/venv/bin/python" "$ROOT/../../work/venv/bin/python"; do
  if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
done
if [ -z "$PYTHON" ]; then PYTHON="$(command -v python3)"; fi
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
export LLM_PROVIDER=ollama
export OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4:e4b}"
"$PYTHON" -c 'import langgraph, httpx, pydantic' || { echo 'Install the backend dependencies in your Python environment first.'; exit 1; }
CASE_IDS="$("$PYTHON" -c 'import json; from pathlib import Path; print(",".join(json.loads(Path("backend/app/evaluation/benchmark18.json").read_text())["case_ids"]))')"
if [ "${1:-}" = "--dry-run" ]; then
  "$PYTHON" -m app.evaluation.benchmark --case all --case-ids "$CASE_IDS" --repeats 1 --output work/evaluation-18-preview --dry-run
  exit 0
fi
mkdir -p "$ROOT/work"
RUN_DIR="$(mktemp -d "$ROOT/work/evaluation-18-$(date +%Y%m%d-%H%M%S)-XXXXXX")"
printf '18 distinct questions, one answer per system per question. Model: %s\nResults: %s\n' "$OLLAMA_MODEL" "$RUN_DIR"
# Keep the Mac awake while this Terminal session runs. Ctrl+C stops the run.
/usr/bin/caffeinate -i -w $$ &
"$PYTHON" -u -m app.evaluation.benchmark --case all --case-ids "$CASE_IDS" --repeats 1 --max-requests 648 --output "$RUN_DIR/agent"
"$PYTHON" -u -m app.evaluation.baseline_compare --agent-directory "$RUN_DIR/agent" --output "$RUN_DIR/comparison" --judge-provider ollama --judge-model "$OLLAMA_MODEL" --max-requests 468
printf '\nFinished. Comparison report: %s/comparison/comparison.md\n' "$RUN_DIR"
