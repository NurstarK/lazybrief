# Demo plan

Two ways to produce the demo. Either is enough for the DEV submission's "Demo"
section.

## Option A — automated terminal recording (fastest)

Prerequisites: [Ollama](https://ollama.com) running with `gemma3` pulled
(`ollama pull gemma3`). If it isn't, the script falls back to `--offline` so the
recording still completes — but for the submission you want the real model
running so the brief is genuinely model-written.

```bash
# plain run (watch it in your terminal)
./demo/record-demo.sh

# or record an asciinema cast you can embed in the DEV post
asciinema rec -c ./demo/record-demo.sh lazybrief.cast
asciinema upload lazybrief.cast
```

The script seeds a throwaway inbox from `sample-inbox.jsonl`, adds two items
live, lists the pile, runs the overnight sort, and prints the five-line brief
plus the full markdown. ~60 seconds.

## Option B — record a 60–90s screen video by hand

Script to follow on camera (each block is one on-screen beat):

1. **Setup (say it, don't film the download):** "Everything is local. One open
   binary, one open-weight model, no API key." Have Ollama already running with
   `gemma3`.

2. **Be lazy (15s).** Dump a few things the way you would during a real day:
   ```bash
   python3 lazybrief.py add "https://arxiv.org/abs/2610.01234 agent memory paper"
   python3 lazybrief.py add "TODO renew the domain before friday"
   echo "idea: warm the model so the overnight run starts faster" | python3 lazybrief.py add
   ```
   Narrate: "No folders, no tags, no decisions. Just dump."

3. **Show the mess (10s).**
   ```bash
   python3 lazybrief.py list
   ```
   Narrate: "By bedtime this is a pile. Normally you'd triage it yourself."

4. **The overnight run (20s).**
   ```bash
   python3 lazybrief.py brief
   ```
   Narrate: "Instead, a local Gemma reads the whole pile, dedupes it, clusters
   it, decides what's worth your time, and schedules the rest." Let the
   five-line brief land on screen.

5. **The payoff (15s).**
   ```bash
   cat data/briefs/$(date +%F).md
   ```
   Narrate: "Five lines in the morning. The laptop did the chores overnight, for
   free, offline. In production, Aeon runs this on a cron and sends the five
   lines to your phone."

Tip: run `python3 lazybrief.py doctor` once before recording to confirm the
model is present, so the live `brief` call is fast and clean.
