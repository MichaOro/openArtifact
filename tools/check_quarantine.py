"""Check the quarantine of unused code (quarantine.json at the repository root).

For each entry: if ``usage`` (a regular expression for calls) matches anywhere in the repository,
the code is in use again and the entry should be dropped (reported, not an error). If it matches
nowhere and the entry is older than ``days``, the code is due for removal: the script lists it and
exits with 1, so CI reminds whoever looks. Standard library only.

    python tools/check_quarantine.py [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (".py", ".js", ".html", ".css")
SKIP = {".git", "node_modules", ".venv", "__pycache__", "test-results"}


def _files() -> list[Path]:
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file() and p.suffix in SOURCES and not SKIP & set(p.relative_to(ROOT).parts)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    config = json.loads((ROOT / "quarantine.json").read_text(encoding="utf-8"))
    files = _files()
    due = []
    for entry in config["entries"]:
        pattern = re.compile(entry["usage"])
        used = [str(p.relative_to(ROOT)) for p in files if pattern.search(p.read_text("utf-8", "ignore"))]
        age = (args.today - date.fromisoformat(entry["since"])).days
        if used:
            print(f"in use again, drop it from the quarantine: {entry['name']} ({', '.join(used)})")
        elif age >= config["days"]:
            due.append(entry)
            print(f"due for removal ({age} days unused): {entry['name']} — {entry['symbol']} in {entry['file']}")
        else:
            print(f"in quarantine for {age} of {config['days']} days: {entry['name']}")
    return 1 if due else 0


if __name__ == "__main__":
    sys.exit(main())
