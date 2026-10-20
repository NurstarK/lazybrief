#!/usr/bin/env python3
"""Self-test for lazybrief. Runs fully offline — no model, no network.

    python3 tests/test_lazybrief.py

Exercises the full round-trip: add -> list -> brief (offline) -> archive, plus
the model-output normaliser and the classifier. Uses a throwaway temp data dir
so it never touches your real inbox.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "lazybrief.py"
FAILED = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        FAILED.append(name)


def run(home, *args, stdin=None):
    env = dict(os.environ, LAZYBRIEF_HOME=str(home))
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, input=stdin, env=env,
    )


def test_roundtrip(home):
    print("round-trip (add/list/brief/archive):")
    r = run(home, "add", "https://example.com/a-long-read")
    check("add link exits 0", r.returncode == 0)
    check("add link detected as [link]", "[link]" in r.stdout)

    r = run(home, "add", "remember to call the vet")
    check("add todo detected as [todo]", "[todo]" in r.stdout)

    r = run(home, "add", stdin="pasted idea about caching\n")
    check("add via stdin exits 0", r.returncode == 0)

    r = run(home, "list")
    check("list shows 3 items", "3 item(s)" in r.stdout)

    r = run(home, "brief", "--offline")
    check("offline brief exits 0", r.returncode == 0)
    check("brief has header", "Lazybrief" in r.stdout)
    check("inbox cleared after brief", "archived 3 items" in r.stdout)

    brief_files = list((home / "briefs").glob("*.md"))
    check("brief markdown written", len(brief_files) == 1)
    if brief_files:
        text = brief_files[0].read_text()
        check("markdown has 5-line brief section", "The 5-line brief" in text)
        check("markdown has clusters section", "## Clusters" in text)

    r = run(home, "list")
    check("list empty after archive", "empty" in r.stdout)

    r = run(home, "stats")
    check("stats reports 3 archived", "archived items   : 3" in r.stdout)


def test_group_by_topic():
    print("per-item labels -> clusters:")
    sys.path.insert(0, str(ROOT))
    import lazybrief as lb

    items = [{"kind": "note", "text": str(i)} for i in range(5)]
    raw = {
        "items": [
            {"n": 1, "topic": "Research", "priority": "low", "schedule": "someday"},
            {"n": 2, "topic": "research", "priority": "high", "schedule": "this-week"},
            {"n": 3, "topic": "Old", "priority": "drop", "schedule": "drop"},
            {"n": 3, "topic": "dup ref", "priority": "high", "schedule": "today"},
            {"n": 99, "topic": "bogus", "priority": "high", "schedule": "today"},
        ],
        "brief": ["a"],
    }
    out = lb.normalize(raw, items)
    titles = [c["title"] for c in out["clusters"]]
    research = next(c for c in out["clusters"] if c["title"] == "Research")
    check("same topic merged case-insensitively", research["item_numbers"] == [1, 2])
    check("cluster takes highest priority", research["priority"] == "high")
    check("cluster takes most urgent schedule", research["schedule"] == "this-week")
    check("skipped items land in Unsorted", "Unsorted" in titles and
          next(c for c in out["clusters"] if c["title"] == "Unsorted")["item_numbers"] == [4, 5])
    check("dropped clusters sorted last", out["clusters"][-1]["schedule"] == "drop")
    check("dropped items get their own cluster", out["clusters"][-1]["title"] == "Dropped")
    check("every item appears exactly once",
          sorted(n for c in out["clusters"] for n in c["item_numbers"]) == [1, 2, 3, 4, 5])


def test_normalizer():
    print("normaliser (defends against bad model output):")
    sys.path.insert(0, str(ROOT))
    import lazybrief as lb

    items = [{"kind": "note", "text": "x"}, {"kind": "link", "text": "y"}]
    raw = {
        "clusters": [
            {"title": "A", "priority": "bogus", "schedule": "nope", "item_numbers": [1, 99]},
            {"title": "B", "priority": "high", "schedule": "today", "item_numbers": [2]},
        ],
        "brief": ["l1", "l2", "l3", "l4", "l5", "l6"],
    }
    out = lb.normalize(raw, items)
    check("brief truncated to 5 lines", len(out["brief"]) == 5)
    check("bad priority coerced to med", out["clusters"][1]["priority"] == "med")
    check("bad schedule coerced", out["clusters"][1]["schedule"] == "this-week")
    check("out-of-range item dropped", out["clusters"][1]["item_numbers"] == [1])
    check("most urgent sorted first", out["clusters"][0]["schedule"] == "today")

    check("classify url -> link", lb.classify("https://x.com") == "link")
    check("classify todo", lb.classify("TODO water plants") == "todo")
    check("classify note", lb.classify("random thought") == "note")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_roundtrip(Path(tmp))
    test_normalizer()
    test_group_by_topic()
    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
