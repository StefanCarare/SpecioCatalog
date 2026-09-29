"""Render the small amount of Markdown a model tends to emit.

Chat answers arrive with **bold** around species names. Shown literally the
asterisks read as noise; deleted with a blind replace they can eat real text
("5 * 3" and an unclosed marker are both common). So the markup is parsed into
plain segments here - no Tk, no model - and the window decides how to draw
them.
"""
from __future__ import annotations

import re

__all__ = ["parse_markup"]

# ***text*** and **text**. A lone * is deliberately left alone: in prose from a
# small model it is far more often a stray character than real emphasis, and
# treating it as italics would mangle ordinary sentences.
_BOLD = re.compile(
    r"\*\*\*(?P<strong_italic>.+?)\*\*\*|\*\*(?P<bold>.+?)\*\*",
    re.DOTALL,
)


def parse_markup(text: str | None) -> list[tuple[str, bool]]:
    """Split text into (chunk, is_bold) segments with the markers removed.

    An unclosed "**" finds no pair, so it is returned verbatim rather than
    swallowing the rest of the answer.
    """
    if not text:
        return []
    segments: list[tuple[str, bool]] = []
    pos = 0
    for match in _BOLD.finditer(text):
        inner = match.group("strong_italic")
        if inner is None:
            inner = match.group("bold")
        if match.start() > pos:
            segments.append((text[pos:match.start()], False))
        segments.append((inner, True))
        pos = match.end()
    if pos < len(text):
        segments.append((text[pos:], False))
    return segments
