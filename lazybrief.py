#!/usr/bin/env python3
"""
Lazybrief — a do-it-later inbox that sorts itself overnight on a local Gemma.

Be lazy during the day: dump links, notes, and todos into the inbox with a
single command (or pipe them in). Overnight, a local open-weight model (Gemma
via Ollama) reads the whole pile, dedupes it, clusters it by theme, assigns a
priority and a "do-it-later" schedule bucket to each cluster, and collapses
everything into a <=5-line morning brief. You wake up to five lines instead of
fifty tabs.

Nothing leaves your machine. No API keys, no cloud bill, no account. The model
is open-weight; the agent harness around it (Aeon) is open-source.

Standard library only — no pip install required.

Usage:
    lazybrief.py add "https://example.com/post"      # dump a link
    lazybrief.py add "ask the vet about the cat"      # dump a note
    echo "paste from clipboard" | lazybrief.py add    # dump via stdin
    lazybrief.py list                                  # show the pending pile
    lazybrief.py brief                                 # run the overnight sort
    lazybrief.py brief --offline                       # sort without a model
    lazybrief.py doctor                                # check your setup
    lazybrief.py stats                                 # inbox / archive counts

Environment:
    LAZYBRIEF_HOME    data directory (default: ./data next to this file)
    LAZYBRIEF_MODEL   Ollama model tag   (default: gemma3)
    OLLAMA_HOST       Ollama base URL    (default: http://localhost:11434)
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_MODEL = os.environ.get("LAZYBRIEF_MODEL", "gemma3")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MAX_BRIEF_LINES = 5
SCHEDULE_BUCKETS = ("today", "this-week", "someday", "drop")
PRIORITIES = ("high", "med", "low")


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def data_home() -> Path:
    env = os.environ.get("LAZYBRIEF_HOME")
    base = Path(env) if env else Path(__file__).resolve().parent / "data"
    (base / "briefs").mkdir(parents=True, exist_ok=True)
    return base


def inbox_path() -> Path:
    return data_home() / "inbox.jsonl"


def archive_path() -> Path:
    return data_home() / "archive.jsonl"


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, records: list) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# add / list / stats
# --------------------------------------------------------------------------- #
URL_RE = re.compile(r"https?://\S+")


def classify(text: str) -> str:
    stripped = text.strip()
    if URL_RE.match(stripped):
        return "link"
    low = stripped.lower()
    if low.startswith(("todo", "- [ ]", "[]", "remember to", "don't forget")):
        return "todo"
    return "note"


def cmd_add(args) -> int:
    text = " ".join(args.text).strip() if args.text else sys.stdin.read().strip()
    if not text:
        print("nothing to add (pass text or pipe it in)", file=sys.stderr)
        return 1
    record = {
        "id": uuid.uuid4().hex[:8],
        "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": classify(text),
        "text": text,
        "source": args.source,
    }
    append_jsonl(inbox_path(), record)
    print(f"added [{record['kind']}] {record['id']}: {text[:70]}")
    return 0


def cmd_list(args) -> int:
    items = read_jsonl(inbox_path())
    if not items:
        print("inbox is empty — nothing to do. Stay lazy.")
        return 0
    print(f"{len(items)} item(s) waiting to be sorted:\n")
    for i, it in enumerate(items, 1):
        print(f"{i:>3}. [{it['kind']:<4}] {it['text'][:90]}")
    return 0


def cmd_stats(args) -> int:
    inbox = read_jsonl(inbox_path())
    archive = read_jsonl(archive_path())
    briefs = sorted((data_home() / "briefs").glob("*.md"))
    print(f"pending in inbox : {len(inbox)}")
    print(f"archived items   : {len(archive)}")
    print(f"briefs generated : {len(briefs)}")
    if briefs:
        print(f"latest brief     : {briefs[-1].name}")
    return 0


# --------------------------------------------------------------------------- #
# Model call (Ollama / Gemma)
# --------------------------------------------------------------------------- #
# Small local models are much better at labelling items one at a time than at
# juggling item numbers inside clusters, so the model labels each item with a
# topic and the code does the grouping (see group_by_topic).
PROMPT_TEMPLATE = """You are a triage assistant for a lazy person's "do-it-later" \
inbox: a messy pile of links, notes, and todos they dumped during the day \
without organising. Go through EVERY item below, one by one, and label it. \
Do not skip any item.

For each item return:
- "n": the item's number exactly as shown
- "topic": a broad 1-2 word topic in plain words (for example "AI research", \
"admin", "home"). Items about the same subject MUST share the exact same \
topic, so related items and near-duplicates group together. Aim for 3-6 \
distinct topics across the whole inbox.
- "priority": "high" | "med" | "low"
- "schedule": "today" | "this-week" | "someday" | "drop" (use "drop" for \
anything stale, already done, or redundant)

Return ONLY valid JSON of this exact shape (no markdown, no commentary):
{{"items": [{{"n": 1, "topic": "...", "priority": "high", "schedule": "today"}}]}}

The inbox ({count} items):
{items}
"""


# Second pass: the brief is written from the already-grouped clusters, so it
# can only describe decisions the first pass actually made.
BRIEF_TEMPLATE = """Here is a person's do-it-later inbox, already sorted into \
clusters with a schedule for each. Write their morning brief: at most \
{max_lines} short plain-language lines, most urgent first, no preamble, each \
telling them the one thing to know or do. Only mention what is listed below; \
do not change any schedule. If a cluster is scheduled "drop", say in one line \
at the end that it was dropped.

Return ONLY valid JSON: {{"brief": ["line 1", "line 2"]}}

Clusters:
{clusters}
"""


def build_brief_prompt(clusters: list, items: list) -> str:
    blocks = []
    for c in clusters:
        texts = "; ".join(items[n - 1]["text"] for n in c["item_numbers"])
        blocks.append(f"- {c['title']} [{c['schedule']}, {c['priority']} priority]: {texts}")
    return BRIEF_TEMPLATE.format(max_lines=MAX_BRIEF_LINES, clusters="\n".join(blocks))


def build_prompt(items: list) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it['kind']}] {it['text']}")
    return PROMPT_TEMPLATE.format(
        max_lines=MAX_BRIEF_LINES,
        count=len(items),
        items="\n".join(lines),
    )


def call_ollama(prompt: str, model: str, timeout: int) -> dict:
    """Call a local Ollama model and return parsed JSON. Raises on failure."""
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    # Ollama returns the model's text in "response"; with format=json it is a
    # JSON string we parse again.
    return json.loads(body["response"])


# --------------------------------------------------------------------------- #
# Offline fallback (no model) — keeps the tool usable, clearly degraded
# --------------------------------------------------------------------------- #
def offline_sort(items: list) -> dict:
    """A dumb, deterministic grouper used when no model is available.

    This exists so the CLI and the demo never hard-fail without Ollama. It is
    NOT the product: the real clustering and prioritisation is the model's job.
    """
    groups = {"link": [], "todo": [], "note": []}
    for i, it in enumerate(items, 1):
        groups.setdefault(it["kind"], []).append(i)
    label = {
        "link": ("Links to read", "this-week", "low"),
        "todo": ("Todos", "today", "high"),
        "note": ("Notes", "this-week", "med"),
    }
    clusters = []
    for kind, nums in groups.items():
        if not nums:
            continue
        title, schedule, priority = label[kind]
        clusters.append(
            {
                "title": title,
                "summary": f"{len(nums)} {kind} item(s) (grouped by type — no model ran).",
                "priority": priority,
                "schedule": schedule,
                "item_numbers": nums,
            }
        )
    brief = [f"{c['title']}: {len(c['item_numbers'])} item(s)" for c in clusters]
    return {"clusters": clusters, "brief": brief[:MAX_BRIEF_LINES]}


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def group_by_topic(labels: list, items: list) -> list:
    """Turn per-item labels into clusters. Items the model skipped land in an
    "Unsorted" cluster so nothing silently disappears from the brief."""
    rank = {"high": 0, "med": 1, "low": 2}
    urgency = {"today": 0, "this-week": 1, "someday": 2, "drop": 3}
    groups, seen = {}, set()
    for lab in labels:
        n = lab.get("n") if isinstance(lab, dict) else None
        if not isinstance(n, int) or not 1 <= n <= len(items) or n in seen:
            continue
        seen.add(n)
        topic = str(lab.get("topic", "")).strip() or "Misc"
        pr = lab.get("priority") if lab.get("priority") in PRIORITIES else "med"
        sc = lab.get("schedule") if lab.get("schedule") in SCHEDULE_BUCKETS else "this-week"
        if sc == "drop":
            # Dropped items never hide inside a live topic.
            topic, pr = "Dropped", "low"
        g = groups.setdefault(topic.lower(), {"title": topic[:1].upper() + topic[1:], "nums": [], "pr": [], "sc": []})
        g["nums"].append(n)
        g["pr"].append(pr)
        g["sc"].append(sc)
    missing = [n for n in range(1, len(items) + 1) if n not in seen]
    if missing:
        groups["\0unsorted"] = {"title": "Unsorted", "nums": missing, "pr": ["med"], "sc": ["this-week"]}
    clusters = []
    for g in groups.values():
        clusters.append(
            {
                "title": g["title"],
                "summary": "",
                "priority": min(g["pr"], key=rank.get),
                # A cluster is only dropped if every item in it was dropped.
                "schedule": min(g["sc"], key=urgency.get),
                "item_numbers": g["nums"],
            }
        )
    return clusters


def normalize(result: dict, items: list) -> dict:
    """Defensive clean-up of whatever the model handed back."""
    if isinstance(result.get("items"), list):
        result = {"clusters": group_by_topic(result["items"], items), "brief": result.get("brief", [])}
    clusters = []
    for c in result.get("clusters", []):
        nums = [n for n in c.get("item_numbers", []) if isinstance(n, int) and 1 <= n <= len(items)]
        pr = c.get("priority", "med")
        sc = c.get("schedule", "this-week")
        clusters.append(
            {
                "title": str(c.get("title", "Untitled")).strip() or "Untitled",
                "summary": str(c.get("summary", "")).strip(),
                "priority": pr if pr in PRIORITIES else "med",
                "schedule": sc if sc in SCHEDULE_BUCKETS else "this-week",
                "item_numbers": nums,
            }
        )
    order = {"high": 0, "med": 1, "low": 2}
    urgency = {"today": 0, "this-week": 1, "someday": 2, "drop": 3}
    clusters.sort(key=lambda c: (urgency[c["schedule"]], order[c["priority"]]))
    brief = [str(b).strip() for b in result.get("brief", []) if str(b).strip()]
    return {"clusters": clusters, "brief": brief[:MAX_BRIEF_LINES]}


def render_markdown(result: dict, items: list, model_label: str) -> str:
    today = dt.date.today().isoformat()
    out = [f"# Morning brief — {today}", ""]
    out.append(f"_{len(items)} items sorted by {model_label}._")
    out.append("")
    out.append("## The 5-line brief")
    out.append("")
    if result["brief"]:
        for line in result["brief"]:
            out.append(f"- {line}")
    else:
        out.append("- (nothing worth surfacing)")
    out.append("")
    out.append("## Clusters")
    out.append("")
    badge = {"today": "🔴 today", "this-week": "🟡 this week", "someday": "🟢 someday", "drop": "⚪ drop"}
    for c in result["clusters"]:
        out.append(f"### {c['title']}  ·  {c['priority'].upper()}  ·  {badge.get(c['schedule'], c['schedule'])}")
        if c["summary"]:
            out.append(f"{c['summary']}")
        out.append("")
        for n in c["item_numbers"]:
            it = items[n - 1]
            out.append(f"- [{it['kind']}] {it['text']}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def one_paragraph(result: dict) -> str:
    """A compact brief suitable for a chat notification."""
    today = dt.date.today().isoformat()
    lines = result["brief"] or ["nothing worth surfacing"]
    body = "\n".join(f"• {l}" for l in lines)
    return f"*Lazybrief — {today}*\n{body}"


# --------------------------------------------------------------------------- #
# brief
# --------------------------------------------------------------------------- #
def cmd_brief(args) -> int:
    items = read_jsonl(inbox_path())
    if not items:
        print("inbox is empty — nothing to sort. Stay lazy.")
        if args.brief_file:
            Path(args.brief_file).write_text("Lazybrief: quiet night, nothing to sort.\n", encoding="utf-8")
        return 0

    model_label = f"{args.model} via Ollama"
    if args.offline:
        result = normalize(offline_sort(items), items)
        model_label = "the offline fallback (no model)"
        print("[offline] no model used — this is the degraded path, not the product.\n", file=sys.stderr)
    else:
        print(f"sorting {len(items)} items with {args.model} on this machine...", file=sys.stderr, flush=True)
        try:
            raw = call_ollama(build_prompt(items), args.model, args.timeout)
            clusters = normalize(raw, items)["clusters"]
            written = call_ollama(build_brief_prompt(clusters, items), args.model, args.timeout)
            result = normalize({"clusters": clusters, "brief": written.get("brief", [])}, items)
        except (urllib.error.URLError, OSError, KeyError, AttributeError, json.JSONDecodeError) as exc:
            print(
                f"could not reach a local model ({exc}).\n"
                f"Start Ollama and `ollama pull {args.model}`, or run with --offline.\n"
                f"Try: lazybrief.py doctor",
                file=sys.stderr,
            )
            return 2

    md = render_markdown(result, items, model_label)
    brief_file = data_home() / "briefs" / f"{dt.date.today().isoformat()}.md"
    brief_file.write_text(md, encoding="utf-8")

    # Emit the compact brief to stdout (what a notification would carry) and the
    # path to the full markdown.
    print(one_paragraph(result))
    if args.brief_file:
        Path(args.brief_file).write_text(one_paragraph(result) + "\n", encoding="utf-8")
    try:
        shown = brief_file.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        shown = brief_file
    print(f"\n(full brief: {shown})")

    if not args.keep:
        processed = read_jsonl(inbox_path())
        stamped = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        for it in processed:
            it["archived_at"] = stamped
            append_jsonl(archive_path(), it)
        write_jsonl(inbox_path(), [])
        print(f"(archived {len(processed)} items — inbox cleared)")
    return 0


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def cmd_doctor(args) -> int:
    ok = True
    print(f"python           : {sys.version.split()[0]}")
    print(f"data home        : {data_home()}")
    print(f"ollama host      : {OLLAMA_HOST}")
    print(f"model            : {args.model}")
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in tags.get("models", [])]
        print(f"ollama reachable : yes ({len(names)} model(s))")
        base = args.model.split(":")[0]
        if any(n == args.model or n.split(":")[0] == base for n in names):
            print(f"model present    : yes")
        else:
            ok = False
            print(f"model present    : NO — run `ollama pull {args.model}`")
            if names:
                print(f"  installed      : {', '.join(names)}")
    except (urllib.error.URLError, OSError) as exc:
        ok = False
        print(f"ollama reachable : NO ({exc})")
        print("  install        : https://ollama.com  then `ollama serve`")
    print()
    print("ready" if ok else "not ready — see above (or use `brief --offline` to test wiring)")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lazybrief",
        description="A do-it-later inbox that sorts itself overnight on a local Gemma.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="dump a link/note/todo into the inbox")
    a.add_argument("text", nargs="*", help="the thing to remember (or pipe via stdin)")
    a.add_argument("--source", default="cli", help="where it came from (default: cli)")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="show the pending pile")
    l.set_defaults(func=cmd_list)

    b = sub.add_parser("brief", help="sort the inbox and produce a morning brief")
    b.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    b.add_argument("--offline", action="store_true", help="skip the model (degraded, for testing)")
    b.add_argument("--keep", action="store_true", help="do not archive the inbox after briefing")
    b.add_argument("--timeout", type=int, default=180, help="model timeout seconds (default: 180)")
    b.add_argument("--brief-file", help="also write the compact brief to this file (for ./notify -f)")
    b.set_defaults(func=cmd_brief)

    s = sub.add_parser("stats", help="inbox / archive / brief counts")
    s.set_defaults(func=cmd_stats)

    d = sub.add_parser("doctor", help="check Ollama + model wiring")
    d.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    d.set_defaults(func=cmd_doctor)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
