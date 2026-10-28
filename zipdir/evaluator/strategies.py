"""Concrete rule transition and 3-tier coordinate remapping strategies."""

from pathlib import PurePosixPath

from zipdir.interfaces.evaluator import (
    IRemapStrategy,
    IRuleTransition,
)
from zipdir.models import (
    EvaluationState,
    IgnoreRule,
    RemapContext,
    RuleKind,
    normalize_posix_path,
    redelete_matches_rescue,
)


class ExcludeTransition(IRuleTransition):
    """Transition for EXCLUDE rules: marks state excluded and records shallowest ancestor."""

    def apply(
        self,
        state: EvaluationState,
        rule: IgnoreRule,
        ancestor: PurePosixPath | None = None,
    ) -> None:
        state.is_excluded = True
        state.excluded_by = rule
        state.rescued_by = None
        match (ancestor, state.shallowest_excluded_ancestor):
            case (PurePosixPath(), None):
                state.shallowest_excluded_ancestor = ancestor
            case _:
                pass


class RescueTransition(IRuleTransition):
    """Transition for RESCUE rules: marks state included and records active rescue rule."""

    def apply(
        self,
        state: EvaluationState,
        rule: IgnoreRule,
        ancestor: PurePosixPath | None = None,
    ) -> None:
        state.is_excluded = False
        state.rescued_by = rule
        state.excluded_by = None


class RedeleteTransition(IRuleTransition):
    """Transition for REDELETE rules: cancels prior rescue when destination target matches."""

    def apply(
        self,
        state: EvaluationState,
        rule: IgnoreRule,
        ancestor: PurePosixPath | None = None,
    ) -> None:
        match state.rescued_by:
            case None:
                state.is_excluded = True
                state.excluded_by = rule
            case IgnoreRule() as rescued:
                if redelete_matches_rescue(rule.target, rescued.target):
                    state.is_excluded = True
                    state.excluded_by = rule
                    state.rescued_by = None


DEFAULT_RULE_TRANSITIONS: dict[RuleKind, IRuleTransition] = {
    RuleKind.EXCLUDE: ExcludeTransition(),
    RuleKind.RESCUE: RescueTransition(),
    RuleKind.REDELETE: RedeleteTransition(),
}


def is_rename_target(target: str) -> bool:
    """Check if target represents a file rename rather than a directory placement."""
    stripped = target.strip()
    return bool(
        stripped and not stripped.endswith("/") and stripped not in (".", "..", "./", "../", "/")
    )


def _combine_dest(
    dest_dir: PurePosixPath, sub_path: PurePosixPath, *, is_rename: bool = False
) -> PurePosixPath:
    clean_dir = PurePosixPath() if dest_dir == PurePosixPath(".") else dest_dir
    match clean_dir:
        case PurePosixPath() if clean_dir != PurePosixPath():
            if is_rename:
                return clean_dir
            return clean_dir / sub_path
        case _:
            return sub_path


class PreserveHierarchyRemapStrategy(IRemapStrategy):
    """Strategy for '.' or './': preserves original relative path from archive root."""

    def matches(self, target: str) -> bool:
        match target:
            case "." | "./":
                return True
            case _:
                return False

    def remap(self, ctx: RemapContext) -> PurePosixPath:
        return ctx.rel_path


class ArchiveRootRemapStrategy(IRemapStrategy):
    """Strategy for '/...': places rescued item relative to the archive root."""

    def matches(self, target: str) -> bool:
        match target:
            case s if s.startswith("/"):
                return True
            case _:
                return False

    def remap(self, ctx: RemapContext) -> PurePosixPath:
        target = ctx.rescued_by.target
        is_rename = is_rename_target(target)
        dest_dir = normalize_posix_path(PurePosixPath(target.lstrip("/")))
        return _combine_dest(dest_dir, ctx.sub_path, is_rename=is_rename)


class LocalScopeRemapStrategy(IRemapStrategy):
    """Strategy for './{to}': places rescued item relative to local scope or ancestor."""

    def matches(self, target: str) -> bool:
        match target:
            case s if s.startswith("./") and s not in (".", "./"):
                return True
            case _:
                return False

    def remap(self, ctx: RemapContext) -> PurePosixPath:
        target = ctx.rescued_by.target
        is_rename = is_rename_target(target)
        rel_sub = target.removeprefix("./").strip("/")
        scope = ctx.rescued_by.scope
        match (scope, ctx.shallowest_excluded_ancestor):
            case (s, _) if s != PurePosixPath():
                preserved_base = s
            case (_, PurePosixPath() as anc):
                preserved_base = anc
            case _:
                preserved_base = ctx.rel_path.parent

        raw_dest = preserved_base / rel_sub if rel_sub else preserved_base
        return _combine_dest(normalize_posix_path(raw_dest), ctx.sub_path, is_rename=is_rename)


class ParentClimbRemapStrategy(IRemapStrategy):
    """Strategy for '..' or '../...': climbs N parent levels from anchor_parent."""

    def matches(self, target: str) -> bool:
        match target:
            case ".." | "../":
                return True
            case s if s.startswith("../"):
                return True
            case _:
                return False

    def remap(self, ctx: RemapContext) -> PurePosixPath:
        target = ctx.rescued_by.target
        is_rename = is_rename_target(target)
        current = PurePosixPath() if ctx.anchor_parent == PurePosixPath(".") else ctx.anchor_parent
        parts = [p for p in target.split("/") if p and p != "."]
        idx = 0
        while idx < len(parts) and parts[idx] == "..":
            current = (
                PurePosixPath()
                if current in (PurePosixPath(), PurePosixPath("."))
                else current.parent
            )
            idx += 1
        remainder = PurePosixPath(*parts[idx:]) if idx < len(parts) else PurePosixPath()
        combined = current / remainder if remainder != PurePosixPath() else current
        return _combine_dest(normalize_posix_path(combined), ctx.sub_path, is_rename=is_rename)


class ExileRemapStrategy(IRemapStrategy):
    """Fallback Strategy (omitted prefix '!' or '{to}!'): exiles to excluded parent."""

    def matches(self, target: str) -> bool:
        return True

    def remap(self, ctx: RemapContext) -> PurePosixPath:
        target = ctx.rescued_by.target
        is_rename = is_rename_target(target)
        has_ancestor = ctx.shallowest_excluded_ancestor is not None
        clean_target = target.rstrip("/")
        match (has_ancestor, clean_target, ctx.rel_path.parent):
            case (False, "", parent) if parent == PurePosixPath("."):
                return ctx.rel_path
            case (True, _, _):
                exile_base = ctx.anchor_parent
            case (False, _, parent) if parent == PurePosixPath("."):
                exile_base = PurePosixPath()
            case _:
                exile_base = ctx.anchor_parent.parent

        raw_dest = exile_base / clean_target if clean_target else exile_base
        return _combine_dest(normalize_posix_path(raw_dest), ctx.sub_path, is_rename=is_rename)


DEFAULT_REMAP_STRATEGIES: tuple[IRemapStrategy, ...] = (
    PreserveHierarchyRemapStrategy(),
    ArchiveRootRemapStrategy(),
    LocalScopeRemapStrategy(),
    ParentClimbRemapStrategy(),
    ExileRemapStrategy(),
)
