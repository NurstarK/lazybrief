---
name: Lazybrief
description: Overnight do-it-later inbox — a local Gemma sorts the day's dumped links/notes/todos into a 5-line morning brief
var: ""
tags: [productivity, local-model]
---
> **${var}** — Optional path to the Lazybrief app (default: `apps/lazybrief`).

This skill runs the Lazybrief CLI over a locally accumulated inbox and sends the
resulting five-line brief through Aeon's `./notify` fan-out. It pairs the
open-source [Aeon](https://github.com/aeonfun/aeon) harness (scheduling,
notify, memory) with an open-weight model (Gemma via Ollama) running on your own
machine — no API key, no cloud bill.

Intended to run on an overnight cron so you wake up to the brief. See
`aeon.yml` wiring at the bottom.

Read `memory/MEMORY.md` for context.

## Steps

1. Resolve the app directory (default `apps/lazybrief`, or `${var}` if set).

2. Check the model is reachable:
   ```bash
   python3 apps/lazybrief/lazybrief.py doctor
   ```
   If it reports "not ready", the local model is down. Do **not** silently send
   an empty brief — log the condition and exit (the operator needs to start
   Ollama). You may optionally run with `--offline` for a type-grouped fallback
   if the operator has opted into degraded mode.

3. Generate the brief over whatever has accumulated in the inbox, capturing the
   output (run `brief` exactly **once** — it archives the inbox as it goes):
   ```bash
   OUT="$(python3 apps/lazybrief/lazybrief.py brief)"
   echo "$OUT"
   ```
   This writes `apps/lazybrief/data/briefs/YYYY-MM-DD.md`, prints a compact
   notification-ready brief to stdout, and archives the processed items.

4. If the inbox was empty, the CLI prints "inbox is empty" — send a one-line
   "quiet night, nothing to sort" notice rather than padding, and stop.

5. Otherwise send the compact brief (the block that starts with `*Lazybrief —`,
   i.e. everything before the `(full brief: ...)` line) via Aeon's notifier:
   ```bash
   ./notify "$(printf '%s' "$OUT" | sed -n '/^\*Lazybrief/,/^(full brief/p' | sed '/^(full brief/d')"
   ```

6. Append a one-line entry to `memory/logs/YYYY-MM-DD.md` noting how many items
   were sorted.

## How items get into the inbox

Anything that appends a JSON line to `apps/lazybrief/data/inbox.jsonl` works.
Simplest is the CLI during the day:
```bash
python3 apps/lazybrief/lazybrief.py add "https://... or a note or a TODO"
echo "pasted text" | python3 apps/lazybrief/lazybrief.py add
```
Other Aeon skills can feed it too (e.g. a capture skill that dumps unread items
each evening) — just append records of the shape `{id, ts, kind, text, source}`.

## Sandbox note

This skill is **local-first by design** — the model runs on `localhost:11434`,
which the GitHub Actions sandbox cannot reach, and there is no public API to
fall back to. Run this skill on a self-hosted runner or locally via `./aeon`,
not on hosted GitHub Actions. `./notify` still fans out normally once the brief
string is built. No secrets or environment variables are required.

## Environment Variables

None required. Optional:
- `LAZYBRIEF_MODEL` — Ollama model tag (default `gemma3`).
- `OLLAMA_HOST` — Ollama base URL (default `http://localhost:11434`).
- `LAZYBRIEF_HOME` — data directory (default `apps/lazybrief/data`).

## Scheduling (aeon.yml)

Add under `skills:` to run overnight on a self-hosted runner:
```yaml
  - name: lazybrief
    schedule: "0 6 * * *"   # 06:00 — brief is ready when you wake
    enabled: true
    prompt: "Read and execute apps/lazybrief/skill/SKILL.md"
```
