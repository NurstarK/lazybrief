---
name: lazybrief
description: Overnight do-it-later inbox. A local Gemma (via Ollama) sorts the links, notes and todos dumped during the day into a five-line morning brief, sent through ./notify.
metadata:
  title: Lazybrief
  category: productivity
  var: ""
  tags:
    - productivity
    - local-model
  mode: write
  capabilities:
    - sends_notifications
---
> **${var}** — Optional path to the Lazybrief checkout. Default: `apps/lazybrief`.

Sort the Lazybrief inbox with a local open-weight model and send the five-line
brief through `./notify`. Lazybrief does the model work; this skill only runs it
and delivers the result.

**Run each command below as its own Bash call.** No `&&`, `;` or pipes: the
sandbox denies chained commands.

## Steps

1. Set `APP` to `${var}` if it is non-empty, otherwise `apps/lazybrief`. If
   `APP/lazybrief.py` does not exist, notify
   `lazybrief: no checkout at APP (see the Lazybrief README)` and stop.

2. Check the model is reachable:
   ```bash
   python3 APP/lazybrief.py doctor
   ```
   If the last line is not `ready`, the local model is down. Notify
   `lazybrief: local model not ready, skipped tonight's brief (start Ollama)`
   with `--severity warn` and stop. Never send an empty or invented brief, and
   never fall back to `--offline` unless the operator asked for it in `${var}`.

3. Generate the brief. Run this exactly **once**, because it archives the inbox:
   ```bash
   python3 APP/lazybrief.py brief --brief-file APP/data/notify.md
   ```
   It writes the full brief to `APP/data/briefs/YYYY-MM-DD.md` and the compact
   five-line version to `APP/data/notify.md` (git-ignored, like the rest of
   `APP/data/`). On an empty inbox the file holds
   a one-line "quiet night" notice instead.

4. Send it:
   ```bash
   ./notify --title "Lazybrief" -f APP/data/notify.md
   ```

5. Append one line to `memory/logs/${today}.md`: how many items were sorted (from
   the `(archived N items ...)` line of step 3's output), or that the inbox was
   empty.

## Where it runs

The model lives on `localhost:11434`. A hosted GitHub Actions runner cannot
reach it, so run this skill wherever Ollama is: your own machine, or a
self-hosted runner on it.

On a self-hosted runner, `actions/checkout` wipes the Aeon workspace before
every run — anything cloned into `apps/` is deleted, inbox included. Keep the
Lazybrief checkout (and its `data/` inbox) **outside** the Aeon repo and point
`${var}` at it with an absolute path.

## Install

Install the skill from the pack:
```bash
bin/install-skill-pack NurstarK/lazybrief
```

Clone the app **outside** your Aeon checkout, pinned to a release tag:
```bash
git clone --branch v0.1.0 --depth 1 https://github.com/NurstarK/lazybrief /opt/lazybrief
```

Then enable it in `aeon.yml`, pointing `var` at the checkout (schedules are UTC):
```yaml
  lazybrief: { enabled: true, schedule: "0 5 * * *", var: "/opt/lazybrief" } # overnight do-it-later inbox -> 5-line brief (local Ollama)
```

For a purely local run (`scripts/dry-run.sh run lazybrief`), `var: ""` with a
checkout at `apps/lazybrief` also works — just know a self-hosted runner will
wipe it.

## Environment

No secrets. Optional: `LAZYBRIEF_MODEL` (default `gemma3`), `OLLAMA_HOST`
(default `http://localhost:11434`), `LAZYBRIEF_HOME` (default `APP/data`).
