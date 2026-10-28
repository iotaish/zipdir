"""Minimal concrete interpreter that parses 4-component syntax and compiles .zipignore rules."""

import importlib
import re
from collections.abc import Sequence
from pathlib import PurePosixPath

from zipdir.interfaces.glob import IGlobCompiler
from zipdir.interfaces.interpreter import IRuleInterpreter
from zipdir.models import IgnoreRule, ParsedRule, RuleKind, ScopedRule

RULE_COMPONENT_PATTERN = re.compile(r"^(?P<b1>!?)(?P<to>[^!]*)!(?P<pattern>.+)$")


class RuleInterpreter(IRuleInterpreter):
    """Minimal concrete interpreter that parses 4-component syntax and compiles .zipignore rules."""

    glob_compiler: IGlobCompiler

    def __init__(self, glob_compiler: IGlobCompiler | None = None) -> None:
        if glob_compiler is not None:
            self.glob_compiler = glob_compiler
        else:
            self.glob_compiler = importlib.import_module("zipdir.glob").GlobExpression()

    def parse_components(self, line: str) -> ParsedRule | None:
        """Parse raw line into 4-component AST node (ParsedRule)."""
        stripped = line.strip()
        match stripped:
            case "":
                return None
            case str() if stripped.startswith("#"):
                return None
            case str() if stripped.startswith((r"\#", r"\!")):
                return ParsedRule(RuleKind.EXCLUDE, "", stripped)
            case _:
                match RULE_COMPONENT_PATTERN.match(stripped):
                    case None:
                        return ParsedRule(RuleKind.EXCLUDE, "", stripped)
                    case re.Match() as m:
                        b1 = m.group("b1")
                        to = m.group("to").strip()
                        pattern = m.group("pattern").strip()
                        match (pattern, "?" in to):
                            case ("", _) | (_, True):
                                return None
                            case _:
                                kind = RuleKind.REDELETE if b1 else RuleKind.RESCUE
                                return ParsedRule(kind, to, pattern)

    def interpret(self, line: str, scope: PurePosixPath = PurePosixPath()) -> IgnoreRule | None:
        """Parse and compile a raw rule line into an IgnoreRule."""
        match self.parse_components(line):
            case None:
                return None
            case ParsedRule() as parsed:
                return self._build_rule(line, parsed, scope)

    def compile_all(
        self,
        rules: Sequence[str | ScopedRule | IgnoreRule],
        *,
        squeeze: bool = False,
    ) -> tuple[IgnoreRule, ...]:
        """Compile a sequence of raw or scoped rules into IgnoreRule objects."""
        compiled: list[IgnoreRule] = []
        for item in rules:
            match self._compile_single_item(item):
                case IgnoreRule() as rule:
                    compiled.append(rule)
                case None:
                    continue
        return tuple(compiled)

    def _compile_single_item(self, item: str | ScopedRule | IgnoreRule) -> IgnoreRule | None:
        match item:
            case IgnoreRule() as rule:
                return rule
            case ScopedRule(scope=scope, rule=rule_line):
                return self.interpret(rule_line, scope=scope)
            case str() as line:
                return self.interpret(line)
            case _:
                return None

    def _build_rule(self, raw: str, parsed: ParsedRule, scope: PurePosixPath) -> IgnoreRule:
        regex, is_dir_only, has_slash = self.glob_compiler.interpret(parsed.pattern)
        return IgnoreRule(
            raw=raw,
            kind=parsed.kind,
            target=parsed.target,
            pattern=parsed.pattern,
            regex=regex,
            is_dir_only=is_dir_only,
            has_slash=has_slash,
            scope=scope,
        )
