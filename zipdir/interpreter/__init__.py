"""Interpreter package exporting the final squeezed RuleInterpreter and strategies."""

from collections.abc import Sequence
from pathlib import PurePosixPath

from zipdir.interpreter.base import RULE_COMPONENT_PATTERN
from zipdir.interpreter.squeezed import RuleInterpreter
from zipdir.interpreter.strategies import (
    DEFAULT_SQUEEZE_STRATEGIES,
    OverwriteSqueezeStrategy,
    SqueezeBuffer,
    TargetedRedeleteSqueezeStrategy,
)
from zipdir.models import IgnoreRule, ScopedRule


def compile_rule(line: str, scope: PurePosixPath = PurePosixPath()) -> IgnoreRule | None:
    """Compile a single .zipignore rule line into an IgnoreRule."""
    return RuleInterpreter().interpret(line, scope=scope)


def squeeze_rules(rules: Sequence[str | ScopedRule]) -> list[str | ScopedRule]:
    """Squeeze rule lines by pattern and scope."""
    return RuleInterpreter().squeeze(rules)


__all__ = [
    "DEFAULT_SQUEEZE_STRATEGIES",
    "OverwriteSqueezeStrategy",
    "RULE_COMPONENT_PATTERN",
    "RuleInterpreter",
    "SqueezeBuffer",
    "TargetedRedeleteSqueezeStrategy",
    "compile_rule",
    "squeeze_rules",
]
