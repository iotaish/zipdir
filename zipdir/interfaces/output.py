"""Interfaces for output path resolution."""

from collections.abc import Callable, Sequence
from pathlib import Path

from zipdir.models import ResolvedOutput


class IOutputTargetStrategy:
    """Strategy interface for output destination target classification."""

    def matches(self, raw: str) -> bool:
        raise NotImplementedError

    def classify(self, source: Path, cwd: Path, raw: str) -> tuple[Path, bool]:
        raise NotImplementedError


class IOutputResolver:
    """Interface for resolving output paths and detecting fallback collisions."""

    cwd: Path
    timestamp_fn: Callable[[], str]
    target_strategies: Sequence[IOutputTargetStrategy]

    def normalize_cli_args(self, args: Sequence[str]) -> list[str]:
        raise NotImplementedError

    def resolve_with_metadata(
        self,
        source: Path,
        name: str,
        output_target: str | Path | None = None,
        *,
        timestamp: bool = False,
        force: bool = False,
    ) -> ResolvedOutput:
        raise NotImplementedError

    def resolve(
        self,
        source: Path,
        name: str,
        output_target: str | Path | None = None,
        *,
        timestamp: bool = False,
        force: bool = False,
    ) -> Path:
        raise NotImplementedError
