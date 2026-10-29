"""Interfaces for path evaluation against ignore rules and destination remapping."""

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from zipdir.models import (
    EvaluationResult,
    EvaluationState,
    IgnoreRule,
    PathExplanation,
    RemapContext,
    RuleKind,
)


class IRuleTransition:
    """Strategy interface for state transitions triggered by matched rules."""

    def apply(
        self,
        state: EvaluationState,
        rule: IgnoreRule,
        ancestor: PurePosixPath | None = None,
    ) -> None:
        raise NotImplementedError


class IRemapStrategy:
    """Strategy interface for destination target path remapping."""

    def matches(self, target: str) -> bool:
        raise NotImplementedError

    def remap(self, ctx: RemapContext) -> PurePosixPath:
        raise NotImplementedError


class IPathEvaluator:
    """Interface for evaluating filesystem paths against ignore rules."""

    rules: tuple[IgnoreRule, ...]
    transitions: Mapping[RuleKind, IRuleTransition]
    remap_strategies: Sequence[IRemapStrategy]

    def evaluate(self, rel_path: PurePosixPath, is_dir: bool = False) -> EvaluationResult:
        raise NotImplementedError

    def should_prune(self, rel_dir: PurePosixPath) -> bool:
        raise NotImplementedError

    def explain(self, rel_path: PurePosixPath, is_dir: bool = False) -> PathExplanation:
        raise NotImplementedError
