"""Evaluator package exporting the final pruning PathEvaluator and strategies."""

from collections.abc import Sequence
from pathlib import PurePosixPath

from zipdir.evaluator.pruning import PathEvaluator
from zipdir.evaluator.strategies import (
    DEFAULT_REMAP_STRATEGIES,
    DEFAULT_RULE_TRANSITIONS,
    ArchiveRootRemapStrategy,
    EvaluationState,
    ExcludeTransition,
    ExileRemapStrategy,
    LocalScopeRemapStrategy,
    ParentClimbRemapStrategy,
    PreserveHierarchyRemapStrategy,
    RedeleteTransition,
    RemapContext,
    RescueTransition,
    TemplateRenameRemapStrategy,
)
from zipdir.models import IgnoreRule, ScopedRule


def evaluate_path(
    rel_path: PurePosixPath,
    is_dir: bool,
    rules: Sequence[IgnoreRule | str | ScopedRule],
) -> tuple[bool, PurePosixPath | None, IgnoreRule | None]:
    """Evaluate path against rules, returning (is_excluded, arc_rel_path, matched_rule)."""
    res = PathEvaluator(rules).evaluate(rel_path, is_dir=is_dir)
    return res.is_excluded, res.arc_path, res.matched_rule


__all__ = [
    "ArchiveRootRemapStrategy",
    "DEFAULT_REMAP_STRATEGIES",
    "DEFAULT_RULE_TRANSITIONS",
    "EvaluationState",
    "ExcludeTransition",
    "ExileRemapStrategy",
    "LocalScopeRemapStrategy",
    "ParentClimbRemapStrategy",
    "PathEvaluator",
    "PreserveHierarchyRemapStrategy",
    "TemplateRenameRemapStrategy",
    "RedeleteTransition",
    "RemapContext",
    "RescueTransition",
    "evaluate_path",
]
