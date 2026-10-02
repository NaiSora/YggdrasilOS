"""Logique métier, indépendante de l'interface : facile à tester."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(frozen=True)
class Stats:
    lines: int
    words: int
    characters: int
    most_common: list[tuple[str, int]]


def word_stats(text: str, top: int = 5) -> Stats:
    words = [w.lower() for w in WORD_RE.findall(text)]
    return Stats(
        lines=len(text.splitlines()),
        words=len(words),
        characters=len(text),
        most_common=Counter(words).most_common(top),
    )
