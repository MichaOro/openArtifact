"""Check relative links and anchors in the tracked Markdown files.

For every ``[text](target)`` and reference definition: a relative file target must exist, and a
``#anchor`` (in the same or the linked Markdown file) must match a heading, using GitHub's slug
rules. External links (http, https, mailto) are not fetched. Code blocks and inline code are
ignored. Standard library only; exits with 1 when something is broken.

    python tools/check_links.py [paths ...]      (default: every tracked *.md)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "node_modules", ".venv", "__pycache__"}
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"!?\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*[\"'])?\s*\)")
REFDEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
HTML_ID = re.compile(r"""<a\s[^>]*(?:name|id)=["']([^"']+)["']""")


def markdown_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
        return [ROOT / n for n in out if (ROOT / n).is_file()]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*.md") if not SKIP & set(p.relative_to(ROOT).parts)]


def slug(heading: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links keep their text
    text = INLINE_CODE.sub(lambda m: m.group(0).strip("`"), text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def prose_lines(path: Path):
    in_fence = False
    for number, line in enumerate(path.read_text("utf-8", "ignore").splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield number, line


_anchors: dict[Path, set[str]] = {}


def anchors(path: Path) -> set[str]:
    if path not in _anchors:
        found: set[str] = set()
        counts: dict[str, int] = {}
        for _, line in prose_lines(path):
            match = HEADING.match(line)
            if match:
                base = slug(match.group(1))
                n = counts.get(base, 0)
                counts[base] = n + 1
                found.add(base if n == 0 else f"{base}-{n}")
            found.update(HTML_ID.findall(line))
        _anchors[path] = found
    return _anchors[path]


def check(path: Path) -> list[str]:
    problems = []
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    for number, line in prose_lines(path):
        clean = INLINE_CODE.sub("", line)
        targets = LINK.findall(clean)
        ref = REFDEF.match(clean)
        if ref:
            targets.append(ref.group(1))
        for target in targets:
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("//"):
                continue
            file_part, _, fragment = target.partition("#")
            file_part = unquote(file_part)
            dest = path if not file_part else (path.parent / file_part).resolve()
            if file_part and not dest.exists():
                problems.append(f"{rel}:{number}: missing file {target}")
                continue
            if fragment and dest.suffix == ".md" and dest.is_file():
                if unquote(fragment).lower() not in anchors(dest):
                    problems.append(f"{rel}:{number}: missing anchor {target}")
    return problems


def main() -> int:
    files = [Path(a).resolve() for a in sys.argv[1:]] or markdown_files()
    problems = [p for f in files for p in check(f)]
    for problem in problems:
        print(problem)
    print(f"{len(files)} Markdown files checked, {len(problems)} broken links")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
