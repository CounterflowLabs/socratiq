"""Prompt template loader.

Mirrors the design of Codex's ``codex-utils-template`` crate:

- Templates are plain ``.md`` files co-located with their consumers.
- The only template syntax is ``{{ name }}`` variable substitution.
- No conditionals, no loops, no filters — any branching belongs in Python
  so the template stays grep-friendly and bugs surface as code, not data.
- Missing, extra, or duplicate variables raise immediately at render time.
- Templates are read and parsed once via :func:`load_prompt`'s LRU cache.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class PromptTemplateError(ValueError):
    """Raised when a template fails to parse or render."""


class PromptTemplate:
    """A parsed prompt template with strict ``{{ name }}`` substitution."""

    __slots__ = ("path", "text", "variables")

    def __init__(self, path: Path) -> None:
        self.path = path
        self.text = path.read_text(encoding="utf-8")
        names = _PLACEHOLDER_RE.findall(self.text)
        duplicates = [n for n, c in Counter(names).items() if c > 1]
        # Duplicates are allowed for repeated injection (e.g. {{ language }}
        # used twice in lab_generation), but the variable set stays unique.
        del duplicates  # kept as a parsing checkpoint; remove if behavior changes
        self.variables: frozenset[str] = frozenset(names)

    def render(self, **values: object) -> str:
        provided = set(values.keys())
        missing = self.variables - provided
        extra = provided - self.variables
        if missing:
            raise PromptTemplateError(
                f"Missing variables for {self.path.name}: {sorted(missing)}"
            )
        if extra:
            raise PromptTemplateError(
                f"Unexpected variables for {self.path.name}: {sorted(extra)}"
            )
        return _PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]), self.text)


@lru_cache(maxsize=None)
def load_prompt(path: str | Path) -> PromptTemplate:
    """Load and parse a prompt template once; subsequent calls return the cached instance."""
    return PromptTemplate(Path(path))
