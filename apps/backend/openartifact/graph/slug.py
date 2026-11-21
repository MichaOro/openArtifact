"""URL names ("slugs") of pipelines and action definitions."""

from __future__ import annotations

import re
import unicodedata

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def slugify(name: str, fallback: str) -> str:
    """Lower-case ASCII words joined by hyphens; ``fallback`` when nothing is left."""
    text = unicodedata.normalize("NFKD", name.lower().translate(_UMLAUTS))
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:80].strip("-") or fallback
