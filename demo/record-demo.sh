#!/usr/bin/env bash
# Records (or just runs) a 60-90s terminal demo of Lazybrief.
#
#   ./demo/record-demo.sh            # run the demo live in your terminal
#   asciinema rec -c ./demo/record-demo.sh lazybrief.cast   # record a cast
#
# The demo uses a throwaway data dir seeded from demo/sample-inbox.jsonl, so it
# never touches your real inbox. It runs the real model if Ollama is up;
# otherwise it falls back to --offline so the demo always completes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(dirname "$HERE")"
MODEL="${LAZYBRIEF_MODEL:-gemma3}"

DEMO_HOME="$(mktemp -d)"
trap 'rm -rf "$DEMO_HOME"' EXIT
mkdir -p "$DEMO_HOME/briefs"
cp "$HERE/sample-inbox.jsonl" "$DEMO_HOME/inbox.jsonl"
export LAZYBRIEF_HOME="$DEMO_HOME"

step() { printf '\n\033[1;36m$ %s\033[0m\n' "$*"; sleep 1; }
lazybrief() { python3 "$APP/lazybrief.py" "$@"; }
cd "$DEMO_HOME"
run()  { step "$*"; eval "$*"; sleep 2; }

clear
echo "Lazybrief — a do-it-later inbox that sorts itself overnight on a local Gemma"
sleep 2

# A day of lazy dumping (we pre-seeded 9 items; add two more live).
run "lazybrief add 'https://example.com/read-later'"
run "lazybrief add 'TODO book dentist'"

# Look at the mess.
run "lazybrief list"

# Overnight: the local model sorts it into a 5-line brief.
OFFLINE=""
if ! python3 "$APP/lazybrief.py" doctor --model "$MODEL" >/dev/null 2>&1; then
  echo
  echo "(no local model detected — using --offline so the demo still runs)"
  OFFLINE="--offline"
fi
run "lazybrief brief $OFFLINE"

# The full brief that got written.
run "cat briefs/$(ls -t briefs | head -1)"

echo
echo "Five lines. No cloud. No API key. You were lazy; the model wasn't."
