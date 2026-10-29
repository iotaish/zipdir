"""Minimal concrete path evaluator (base stage for progressive inheritance)."""

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from zipdir.evaluator.strategies import (
    DEFAULT_REMAP_STRATEGIES,
    DEFAULT_RULE_TRANSITIONS,
    EvaluationState,
)
from zipdir.interfaces.evaluator import IPathEvaluator, IRemapStrategy, IRuleTransition
from zipdir.interfaces.interpreter import IRuleInterpreter
from zipdir.models import (
    EvaluationResult,
    ExplanationStep,
    IgnoreRule,
    PathExplanation,
    RuleKind,
    ScopedRule,
)


class PathEvaluator(IPathEvaluator):
    """Minimal concrete evaluator performing ancestor and target rule evaluation."""

    rules: tuple[IgnoreRule, ...]
    transitions: Mapping[RuleKind, IRuleTransition]
    remap_strategies: Sequence[IRemapStrategy]

    def __init__(
        self,
        rules: Sequence[IgnoreRule | str | ScopedRule] = (),
        interpreter: IRuleInterpreter | None = None,
        transitions: Mapping[RuleKind, IRuleTransition] | None = None,
        remap_strategies: Sequence[IRemapStrategy] | None = None,
    ) -> None:
        if rules and all(isinstance(r, IgnoreRule) for r in rules):
            self.rules = tuple(rules)  # type: ignore[arg-type]
        else:
            if interpreter is not None:
                compiler = interpreter
            else:
                import importlib

                compiler = importlib.import_module("zipdir.interpreter").RuleInterpreter()
            self.rules = compiler.compile_all(rules)
        self.transitions = transitions if transitions is not None else DEFAULT_RULE_TRANSITIONS
        self.remap_strategies = (
            remap_strategies if remap_strategies is not None else DEFAULT_REMAP_STRATEGIES
        )

    def evaluate(self, rel_path: PurePosixPath, is_dir: bool = False) -> EvaluationResult:
        """Evaluate path against rules, returning EvaluationResult(is_excluded, arc_path, matched_rule)."""
        state = self._evaluate_ancestors(rel_path.parts)
        self._evaluate_target(rel_path, is_dir, state)

        match (state.is_excluded, state.rescued_by):
            case (True, _):
                return EvaluationResult(True, None, state.excluded_by)
            case (False, None):
                return EvaluationResult(False, rel_path, None)
            case (False, IgnoreRule() as rescued_rule):
                arc_rel = self._resolve_rescued_path(
                    rel_path, rescued_rule, state.shallowest_excluded_ancestor
                )
                return EvaluationResult(False, arc_rel, rescued_rule)

    def should_prune(self, rel_dir: PurePosixPath) -> bool:
        """Minimal base pruning behavior (overridden in pruning.py)."""
        return False

    def explain(self, rel_path: PurePosixPath, is_dir: bool = False) -> PathExplanation:
        """Trace each step of rule evaluation, capturing transitions and final result."""
        steps: list[ExplanationStep] = []
        state = EvaluationState()
        parts = rel_path.parts

        for k in range(1, len(parts)):
            anc = PurePosixPath(*parts[:k])
            anc_str = anc.as_posix()
            for r in self.rules:
                match_str = self._scoped_target(anc, anc_str, r.scope)
                if match_str is not None and r.regex.search(match_str):
                    self.transitions[r.kind].apply(state, r, ancestor=anc)
                    steps.append(
                        ExplanationStep(
                            target=anc,
                            is_ancestor=True,
                            rule=r,
                            kind=r.kind,
                            is_excluded_after=state.is_excluded,
                            shallowest_excluded_ancestor=state.shallowest_excluded_ancestor,
                            action_description=f"Ancestor '{anc.as_posix()}' matched '{r.raw}' ({r.kind.name})",
                        )
                    )

        posix_str = rel_path.as_posix()
        for r in self.rules:
            if r.is_dir_only and not is_dir:
                continue
            target_str = self._scoped_target(rel_path, posix_str, r.scope)
            if target_str is not None and r.regex.search(target_str):
                self.transitions[r.kind].apply(state, r)
                steps.append(
                    ExplanationStep(
                        target=rel_path,
                        is_ancestor=False,
                        rule=r,
                        kind=r.kind,
                        is_excluded_after=state.is_excluded,
                        shallowest_excluded_ancestor=state.shallowest_excluded_ancestor,
                        action_description=f"Target '{rel_path.as_posix()}' matched '{r.raw}' ({r.kind.name})",
                    )
                )

        match (state.is_excluded, state.rescued_by):
            case (True, _):
                res = EvaluationResult(True, None, state.excluded_by)
            case (False, None):
                res = EvaluationResult(False, rel_path, None)
            case (False, IgnoreRule() as rescued_rule):
                arc_rel = self._resolve_rescued_path(
                    rel_path, rescued_rule, state.shallowest_excluded_ancestor
                )
                res = EvaluationResult(False, arc_rel, rescued_rule)

        return PathExplanation(
            rel_path=rel_path,
            is_dir=is_dir,
            steps=tuple(steps),
            result=res,
        )

    def _resolve_rescued_path(
        self,
        rel_path: PurePosixPath,
        rescued_by: IgnoreRule,
        shallowest_excluded_ancestor: PurePosixPath | None,
    ) -> PurePosixPath:
        """Base hook returning original relative path (extended in remapped.py)."""
        return rel_path

    def _evaluate_ancestors(self, parts: tuple[str, ...]) -> EvaluationState:
        state = EvaluationState()
        for k in range(1, len(parts)):
            anc = PurePosixPath(*parts[:k])
            anc_str = anc.as_posix()
            for r in self.rules:
                match_str = self._scoped_target(anc, anc_str, r.scope)
                if match_str is not None and r.regex.search(match_str):
                    self.transitions[r.kind].apply(state, r, ancestor=anc)
        return state

    def _evaluate_target(
        self, rel_path: PurePosixPath, is_dir: bool, state: EvaluationState
    ) -> None:
        posix_str = rel_path.as_posix()
        for r in self.rules:
            if r.is_dir_only and not is_dir:
                continue
            target_str = self._scoped_target(rel_path, posix_str, r.scope)
            if target_str is not None and r.regex.search(target_str):
                self.transitions[r.kind].apply(state, r)

    def _scoped_target(
        self, path: PurePosixPath, posix_str: str, scope: PurePosixPath
    ) -> str | None:
        match (scope, path.is_relative_to(scope) and path != scope):
            case (s, _) if s == PurePosixPath():
                return posix_str
            case (_, True):
                return path.relative_to(scope).as_posix()
            case _:
                return None
