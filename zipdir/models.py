"""Concrete domain data models and value helpers for zipdir using Pydantic."""

import re
from collections.abc import Iterator
from enum import Enum
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field


class RuleKind(Enum):
    """Classification of rule types in .zipignore, directly indexed by count of '!' marks."""

    EXCLUDE = 0
    RESCUE = 1
    REDELETE = 2


CANONICAL_TARGETS: dict[str, str] = {
    "": "",
    ".": "./",
    "./": "./",
    "..": "../",
    "../": "../",
    "/": "/",
}


def normalize_target(target: str) -> str:
    """Normalize a rescue/redelete destination target into canonical form."""
    stripped = target.strip()
    match stripped:
        case s if s in CANONICAL_TARGETS:
            return CANONICAL_TARGETS[s]
        case s if s.endswith("/"):
            return s.rstrip("/") + "/"
        case s:
            return s


def redelete_matches_rescue(redelete_target: str, rescued_target: str | None) -> bool:
    """Check whether a REDELETE target cancels a given RESCUE target."""
    match rescued_target:
        case None:
            return True
        case str() as target:
            return normalize_target(redelete_target) == normalize_target(target)


def normalize_posix_path(path: PurePosixPath) -> PurePosixPath:
    """Resolve '.' and '..' segments within a relative PurePosixPath."""
    stack: list[str] = []
    for part in path.parts:
        match part:
            case "" | ".":
                continue
            case "..":
                if stack:
                    stack.pop()
            case _:
                stack.append(part)
    return PurePosixPath(*stack) if stack else PurePosixPath()


class ParsedRule(BaseModel):
    """AST representation for an interpreted .zipignore rule."""

    model_config = ConfigDict(frozen=True)

    kind: RuleKind
    target: str = ""
    pattern: str

    def __init__(
        self,
        kind: RuleKind | None = None,
        target: str = "",
        pattern: str = "",
        **data: object,
    ) -> None:
        if kind is not None:
            data.setdefault("kind", kind)
        if target is not None:
            data.setdefault("target", target)
        if pattern is not None:
            data.setdefault("pattern", pattern)
        super().__init__(**data)

    def model_post_init(self, __context: object) -> None:
        if not self.pattern:
            raise ValueError("ParsedRule invariant violated: pattern must be non-empty")
        if "?" in self.target:
            raise ValueError("ParsedRule invariant violated: '?' is prohibited in target")


class IgnoreRule(BaseModel):
    """Compiled .zipignore rule with optional rescue / remapping target."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    raw: str
    kind: RuleKind
    target: str = ""
    pattern: str
    regex: re.Pattern[str]
    is_dir_only: bool
    has_slash: bool
    scope: PurePosixPath = Field(default_factory=PurePosixPath)

    def __init__(
        self,
        raw: str | None = None,
        kind: RuleKind | None = None,
        target: str = "",
        pattern: str = "",
        regex: re.Pattern[str] | None = None,
        is_dir_only: bool = False,
        has_slash: bool = False,
        scope: PurePosixPath | None = None,
        **data: object,
    ) -> None:
        if raw is not None:
            data.setdefault("raw", raw)
        if kind is not None:
            data.setdefault("kind", kind)
        if target:
            data.setdefault("target", target)
        if pattern:
            data.setdefault("pattern", pattern)
        if regex is not None:
            data.setdefault("regex", regex)
        data.setdefault("is_dir_only", is_dir_only)
        data.setdefault("has_slash", has_slash)
        if scope is not None:
            data.setdefault("scope", scope)
        super().__init__(**data)

    def model_post_init(self, __context: object) -> None:
        if not self.pattern:
            raise ValueError("IgnoreRule invariant violated: pattern must be non-empty")
        if "?" in self.target:
            raise ValueError("IgnoreRule invariant violated: '?' is prohibited in target")
        if self.scope.is_absolute():
            raise ValueError("IgnoreRule invariant violated: scope must be a relative path")


class EvaluationResult(BaseModel):
    """Outcome of evaluating a path against a compiled rule set."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    is_excluded: bool
    arc_path: PurePosixPath | None = None
    matched_rule: IgnoreRule | None = None

    def __init__(
        self,
        is_excluded: bool | None = None,
        arc_path: PurePosixPath | None = None,
        matched_rule: IgnoreRule | None = None,
        **data: object,
    ) -> None:
        if is_excluded is not None:
            data.setdefault("is_excluded", is_excluded)
        data.setdefault("arc_path", arc_path)
        data.setdefault("matched_rule", matched_rule)
        super().__init__(**data)

    def model_post_init(self, __context: object) -> None:
        match (self.is_excluded, self.arc_path):
            case (True, PurePosixPath()):
                raise ValueError(
                    "EvaluationResult invariant violated: excluded path cannot have an arc_path"
                )
            case (False, None):
                raise ValueError(
                    "EvaluationResult invariant violated: included path must have an arc_path"
                )
            case _:
                pass

    def __iter__(self) -> Iterator[bool | PurePosixPath | IgnoreRule | None]:
        yield self.is_excluded
        yield self.arc_path
        yield self.matched_rule


class ResolvedOutput(BaseModel):
    """Resolved archive output path and collision metadata."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    path: Path
    explicit_zip: bool
    stem: str
    fell_back: bool = False

    def __init__(
        self,
        path: Path | None = None,
        explicit_zip: bool | None = None,
        stem: str = "",
        fell_back: bool = False,
        **data: object,
    ) -> None:
        if path is not None:
            data.setdefault("path", path)
        if explicit_zip is not None:
            data.setdefault("explicit_zip", explicit_zip)
        if stem:
            data.setdefault("stem", stem)
        data.setdefault("fell_back", fell_back)
        super().__init__(**data)

    def model_post_init(self, __context: object) -> None:
        match (self.explicit_zip, self.fell_back):
            case (True, True):
                raise ValueError(
                    "ResolvedOutput invariant violated: explicit .zip path cannot fall back"
                )
            case _:
                pass


class ScopedRule(BaseModel):
    """Rule line paired with its directory scope (relative to packaging source)."""

    scope: PurePosixPath = Field(default_factory=PurePosixPath)
    rule: str


class PresetModel(BaseModel):
    """Pydantic schema for preset definitions."""

    name: str = ""
    description: str = ""
    rules: list[str] = Field(default_factory=list)
    extends: list[str] = Field(default_factory=list)
    source_path: Path | None = None


class PackagerConfig(BaseModel):
    """Configuration options for directory packaging."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: Path
    output: Path
    name: str = Field(min_length=1)
    preset_name: str
    rules: list[str | ScopedRule | IgnoreRule] = Field(default_factory=list)
    compression: int = Field(default=6, ge=0, le=9)
    flat: bool = False
    dry_run: bool = False
    force: bool = False
    verbose: bool = False
