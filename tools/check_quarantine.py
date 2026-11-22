"""Check the quarantine of unused code (quarantine.json at the repository root).

For each entry: if ``usage`` (a regular expression for calls) matches anywhere in the repository,
the code is in use again and the entry should be dropped (reported, not an error). If it matches
nowhere and the entry is older than ``days``, the code is due for removal: the script lists it and
exits with 1, so CI reminds whoever looks. An entry may carry ``ignore``, a list of path globs that are
not searched for it (for example tests that only exercise the quarantined code). The files searched
are the tracked ones (``git ls-files``; a directory walk outside a git checkout). Standard library only.

    python tools/check_quarantine.py [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (".py", ".js", ".html", ".css", ".toml", ".yml", ".sh")
SKIP = {".git", "node_modules", ".venv", "__pycache__", "test-results"}


def _files() -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
        candidates = [ROOT / name for name in listed]
    except (OSError, subprocess.CalledProcessError):
        candidates = [p for p in ROOT.rglob("*") if not SKIP & set(p.relative_to(ROOT).parts)]
    return [p for p in candidates if p.suffix in SOURCES and p.is_file()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    config = json.loads((ROOT / "quarantine.json").read_text(encoding="utf-8"))
    files = _files()
    due = []
    for entry in config["entries"]:
        pattern = re.compile(entry["usage"])
        ignore = entry.get("ignore", [])
        used = []
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            if not any(fnmatch(name, glob) for glob in ignore) and pattern.search(
                path.read_text("utf-8", "ignore")
            ):
                used.append(name)
        defined_in = ROOT / entry["file"]
        if not defined_in.is_file() or entry["symbol"] not in defined_in.read_text(
            "utf-8", "ignore"
        ):
            print(
                f"stale entry, {entry['symbol']} is no longer in {entry['file']}: {entry['name']}"
            )
        age = (args.today - date.fromisoformat(entry["since"])).days
        if used:
            print(f"in use again, drop it from the quarantine: {entry['name']} ({', '.join(used)})")
        elif age >= config["days"]:
            due.append(entry)
            print(
                f"due for removal ({age} days unused): {entry['name']} — {entry['symbol']} in {entry['file']}"
            )
        else:
            print(f"in quarantine for {age} of {config['days']} days: {entry['name']}")
    return 1 if due else 0


if __name__ == "__main__":
    sys.exit(main())
