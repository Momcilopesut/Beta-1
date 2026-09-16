#!/usr/bin/env bash
# Serves the repo root over HTTP so site/*.html's relative ../data/... fetches
# resolve correctly. Open http://localhost:8000/site/index.html afterward.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8000}"
echo "Serving $(pwd) at http://localhost:${PORT}/site/index.html"
python3 -m http.server "$PORT"
