"""Minimal concrete glob compiler (base stage for progressive inheritance)."""

import re
from collections.abc import Callable, Mapping

from zipdir.interfaces.glob import IGlobCompiler

GLOB_TOKEN_REGEX = re.compile(
    r"""
    (?P<globstar_slash>\*\*/)|
    (?P<globstar>\*\*)|
    (?P<star>\*)|
    (?P<question>\?)|
    (?P<bracket>\[(!|\^)?.*?\])|
    (?P<brace>\{[^{}]*,[^{}]*\})|
    (?P<escape>\\.)|
    (?P<meta>[.+()^${}|])|
    (?P<literal>[^\\*?\[.+()^${}|/]+)|
    (?P<slash>/)
    """,
    re.VERBOSE,
)

BASE_TOKEN_TRANSLATORS: dict[str, Callable[[str], str]] = {
    "star": lambda _: "[^/]*",
    "question": lambda _: "[^/]",
    "escape": lambda token: re.escape(token[1:]),
    "meta": lambda token: "\\" + token,
    "literal": lambda token: token,
    "slash": lambda token: token,
}


class GlobExpression(IGlobCompiler):
    """Minimal concrete glob compiler handling single-segment wildcards and literals."""

    token_pattern: re.Pattern[str]
    translators: Mapping[str, Callable[[str], str]]

    def __init__(
        self,
        token_pattern: re.Pattern[str] = GLOB_TOKEN_REGEX,
        translators: Mapping[str, Callable[[str], str]] | None = None,
    ) -> None:
        self.token_pattern = token_pattern
        self.translators = translators if translators is not None else BASE_TOKEN_TRANSLATORS

    def interpret(self, pattern: str) -> tuple[re.Pattern[str], bool, bool]:
        """Compile a glob pattern into (compiled_regex, is_dir_only, has_slash)."""
        is_dir_only, clean_pat, anchored, has_slash = self._analyze_structure(pattern)
        regex_body = self.token_pattern.sub(self._translate_token, clean_pat)
        full_regex = self._anchor_regex(regex_body, anchored=anchored, has_slash=has_slash)
        return re.compile(full_regex), is_dir_only, has_slash

    def _analyze_structure(self, pattern: str) -> tuple[bool, str, bool, bool]:
        is_dir_only = pattern.endswith("/")
        clean_pat = pattern[:-1] if is_dir_only else pattern
        anchored = clean_pat.startswith("/")
        if anchored:
            clean_pat = clean_pat[1:]
        has_slash = "/" in clean_pat
        return is_dir_only, clean_pat, anchored, has_slash

    def _anchor_regex(self, regex_body: str, *, anchored: bool, has_slash: bool) -> str:
        return f"^{regex_body}$" if (has_slash or anchored) else f"(?:^|/){regex_body}$"

    def _translate_token(self, match: re.Match[str]) -> str:
        group_name = match.lastgroup
        token = match.group(0)
        if group_name is not None and (translator := self.translators.get(group_name)) is not None:
            return translator(token)
        return token
