"""Gitignore-extended glob compiler via progressive inheritance over base.GlobExpression."""

import re
from collections.abc import Callable, Mapping

from zipdir.glob.base import (
    BASE_TOKEN_TRANSLATORS,
    GLOB_TOKEN_REGEX,
)
from zipdir.glob.base import (
    GlobExpression as BaseGlobExpression,
)


def _translate_brace(token: str) -> str:
    inner = token[1:-1]
    parts = inner.split(",")
    translated: list[str] = []
    for p in parts:
        esc = re.escape(p).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        translated.append(esc)
    return f"(?:{'|'.join(translated)})"


def _translate_bracket(token: str) -> str:
    inner = token[1:-1]
    return f"[^{inner[1:]}]" if inner.startswith("!") else token


DEFAULT_TOKEN_TRANSLATORS: dict[str, Callable[[str], str]] = {
    **BASE_TOKEN_TRANSLATORS,
    "globstar_slash": lambda _: "(?:.*/)?",
    "globstar": lambda _: ".*",
    "bracket": _translate_bracket,
    "brace": _translate_brace,
}


class GlobExpression(BaseGlobExpression):
    """Extends base GlobExpression with recursive globstar (** / **/) and character class ([!...])."""

    def __init__(
        self,
        token_pattern: re.Pattern[str] = GLOB_TOKEN_REGEX,
        translators: Mapping[str, Callable[[str], str]] | None = None,
    ) -> None:
        super().__init__(
            token_pattern=token_pattern,
            translators=translators if translators is not None else DEFAULT_TOKEN_TRANSLATORS,
        )
