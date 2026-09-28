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
if [ "${1:-}" != "--dry-run" ] && [ -x /usr/bin/caffeinate ]; then
  /usr/bin/caffeinate -i -w $$ &
fi
"$PYTHON" -u -m app.evaluation.run45 "$@"
