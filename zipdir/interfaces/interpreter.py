"""Interfaces for .zipignore rule interpretation and squeezing."""

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from zipdir.interfaces.glob import IGlobCompiler
from zipdir.models import IgnoreRule, ParsedRule, RuleKind, ScopedRule


class SqueezeBuffer[T](BaseModel):
    """Mutable buffer state for compile-time rule squeezing."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[T] = Field(default_factory=list)
    parsed_meta: list[ParsedRule] = Field(default_factory=list)
    seen: dict[tuple[PurePosixPath, str], list[int]] = Field(default_factory=dict)

    def shift_indices(self, removed_idx: int) -> None:
        for indices in self.seen.values():
            for i, idx in enumerate(indices):
                if idx > removed_idx:
                    indices[i] = idx - 1


class ISqueezeStrategy:
    """Strategy interface for resolving rule collisions on identical (scope, pattern)."""

    def apply[T](
        self,
        buffer: SqueezeBuffer[T],
        key: tuple[PurePosixPath, str],
        indices: list[int],
        parsed: ParsedRule,
        entry: T,
    ) -> None:
        raise NotImplementedError


class IRuleInterpreter:
    """Interface for parsing and compiling .zipignore rules."""

    glob_compiler: IGlobCompiler

    def parse_components(self, line: str) -> ParsedRule | None:
        raise NotImplementedError

    def interpret(self, line: str, scope: PurePosixPath = PurePosixPath()) -> IgnoreRule | None:
        raise NotImplementedError

    def compile_all(
        self,
        rules: Sequence[str | ScopedRule | IgnoreRule],
        *,
        squeeze: bool = False,
    ) -> tuple[IgnoreRule, ...]:
        raise NotImplementedError


class IRuleSqueezer(IRuleInterpreter):
    """Extended interface supporting target-aware compile-time rule squeezing."""

    squeeze_strategies: Mapping[RuleKind, ISqueezeStrategy]

    def squeeze(self, rules: Sequence[str | ScopedRule]) -> list[str | ScopedRule]:
        raise NotImplementedError
