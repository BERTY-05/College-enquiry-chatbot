"""Optional online translation fallback.

The assistant answers natively in English, Tamil and Hindi without any
internet connection. For every *other* language (Telugu, Malayalam, Kannada,
...) it translates the question to English, finds the answer, and translates
the answer back. That needs the `deep-translator` package and internet.
If either is missing, `translate` simply returns None and the engine degrades
gracefully to English.
"""

from __future__ import annotations

import re
from typing import Optional

_LINE = re.compile(r"^(\s*(?:[-*]\s+|\d+\.\s+)?)(.*)$")


class Translator:
    """Thin wrapper around deep-translator's GoogleTranslator with a cache."""

    def __init__(self) -> None:
        self._cls = None
        self._cache: dict[tuple[str, str, str], str] = {}
        try:
            from deep_translator import GoogleTranslator  # type: ignore

            self._cls = GoogleTranslator
        except Exception:  # package not installed
            self._cls = None

    @property
    def available(self) -> bool:
        return self._cls is not None

    def translate(self, text: str, src: str, tgt: str) -> Optional[str]:
        """Translate plain text. Returns None on any failure."""
        if not text.strip():
            return text
        if self._cls is None:
            return None
        key = (text, src, tgt)
        if key in self._cache:
            return self._cache[key]
        try:
            out = self._cls(source=src, target=tgt).translate(text)
        except Exception:  # network error, unsupported language, rate limit
            return None
        if out:
            self._cache[key] = out
        return out or None

    def translate_markdown(self, text: str, src: str, tgt: str) -> Optional[str]:
        """Translate line by line, keeping bullets, numbering and **bold** headers."""
        lines_out = []
        for line in text.split("\n"):
            prefix, body = _LINE.match(line).groups()  # type: ignore[union-attr]
            if not body.strip():
                lines_out.append(line)
                continue
            bold = len(body) > 4 and body.startswith("**") and body.endswith("**")
            inner = body[2:-2] if bold else body
            translated = self.translate(inner, src, tgt)
            if translated is None:
                return None
            lines_out.append(f"{prefix}**{translated}**" if bold else f"{prefix}{translated}")
        return "\n".join(lines_out)
