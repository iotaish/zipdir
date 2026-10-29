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

POSIX_CHARACTER_CLASSES: dict[str, str] = {
    "alnum": "a-zA-Z0-9",
    "alpha": "a-zA-Z",
    "blank": " \t",
    "cntrl": r"\x00-\x1f\x7f",
    "digit": "0-9",
    "graph": r"\x21-\x7e",
    "lower": "a-z",
    "print": r"\x20-\x7e",
    "punct": r"\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e",
    "space": r"\s",
    "upper": "A-Z",
    "xdigit": "0-9a-fA-F",
    "word": r"a-zA-Z0-9_",
}

POSIX_CLASS_PATTERN = re.compile(r"\[:(?P<cls>[a-zA-Z_]+):\]")

BRACE_PART_TOKEN_REGEX = re.compile(
    r"""
    (?P<star>\*)|
    (?P<question>\?)|
    (?P<bracket>\[(?:\\.|\[:[a-zA-Z_]+:\]|[^\]])*\])|
    (?P<escape>\\.)|
    (?P<meta>[.+()^${}|])|
    (?P<literal>[^\\*?\[.+()^${}|/]+)|
    (?P<slash>/)
    """,
    re.VERBOSE,
)


def _expand_posix_classes(content: str) -> str:
    def _replace_posix(match: re.Match[str]) -> str:
        cls_name = match.group("cls").lower()
        return POSIX_CHARACTER_CLASSES.get(cls_name, match.group(0))

    return POSIX_CLASS_PATTERN.sub(_replace_posix, content)


def _translate_bracket(token: str) -> str:
    inner = token[1:-1]
    if inner.startswith(("!", "^")) and len(inner) > 1:
        negation = "^"
        content = inner[1:]
    else:
        negation = ""
        content = inner
    expanded = _expand_posix_classes(content)
    return f"[{negation}{expanded}]"


def _translate_brace_part_token(match: re.Match[str]) -> str:
    group_name = match.lastgroup
    token = match.group(0)
    match group_name:
        case "star":
            return "[^/]*"
        case "question":
            return "[^/]"
        case "bracket":
            return _translate_bracket(token)
        case "escape":
            return re.escape(token[1:])
        case "meta":
            return "\\" + token
        case "literal" | "slash":
            return token
        case _:
            return token


def _split_brace_parts(inner: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    bracket_depth = 0
    for char in inner:
        if char == "[":
            bracket_depth += 1
            current.append(char)
        elif char == "]" and bracket_depth > 0:
            bracket_depth -= 1
            current.append(char)
        elif char == "," and bracket_depth == 0:
            parts.append("".join(current))
            current.clear()
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _translate_brace(token: str) -> str:
    inner = token[1:-1]
    parts = _split_brace_parts(inner)
    translated = [BRACE_PART_TOKEN_REGEX.sub(_translate_brace_part_token, p) for p in parts]
    return f"(?:{'|'.join(translated)})"


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
