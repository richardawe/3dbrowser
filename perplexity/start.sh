#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

source .venv/bin/activate
mkdir -p history

export SEARCH_API_URL="${SEARCH_API_URL:-http://localhost:8000}"
export SEARCH_API_KEY="${SEARCH_API_KEY:-my-secret-key-change-me}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

echo "Research Engine → http://localhost:8001"
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
