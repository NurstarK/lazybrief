#!/usr/bin/env bash
# One-command setup for Lazybrief.
#   ./setup.sh            # check wiring, pull the model if Ollama is present
#   ./setup.sh --no-pull  # just check, never download
#
# No secrets, no accounts, no cloud. Everything runs locally.
set -euo pipefail

MODEL="${LAZYBRIEF_MODEL:-gemma3}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PULL=1
[ "${1:-}" = "--no-pull" ] && PULL=0

echo "Lazybrief setup"
echo "  model: $MODEL"
echo

# 1. Python 3 (standard library only — nothing to install).
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.8+ and re-run." >&2
  exit 1
fi
echo "python3: $(python3 --version)"

# 2. Ollama + the open-weight model.
if command -v ollama >/dev/null 2>&1; then
  echo "ollama : found"
  if [ "$PULL" = "1" ]; then
    echo "pulling $MODEL (this is the only download; it stays on your machine)..."
    ollama pull "$MODEL"
  fi
else
  cat <<EOF
ollama : NOT found.
  Install it from https://ollama.com (one binary), then run:
      ollama pull $MODEL
  Until then you can still test the wiring with:
      python3 lazybrief.py brief --offline
EOF
fi

echo
echo "Done. Try:"
echo "  python3 $HERE/lazybrief.py add \"https://example.com/something-to-read\""
echo "  python3 $HERE/lazybrief.py brief"
echo "  python3 $HERE/lazybrief.py doctor"
