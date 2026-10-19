#!/usr/bin/env bash
# Start the platform locally on macOS / Linux.
#   ./start.sh          start (creates demo data on first run)
#   ./start.sh reset    recreate the demo data from scratch
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  "$PY" -m venv .venv
fi
source .venv/bin/activate

echo "Installing requirements..."
python -m pip install --disable-pip-version-check -q -r backend/requirements.txt

cd backend
if [ "${1:-}" = "reset" ]; then
  python -m app.seed --reset
else
  python -m app.seed
fi

echo
echo "Open in your browser:  http://localhost:8000"
echo "Demo password for all accounts:  Demo@12345"
echo "Press Ctrl+C to stop."
echo
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
