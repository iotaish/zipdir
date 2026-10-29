"""Interface for packaging progress and console reporting."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from zipdir.models import PackagerConfig, PathExplanation, PresetModel


class IReporter:
    """Interface for console output reporting during packaging."""

    use_color: bool

    def print_presets(self, presets: Mapping[str, PresetModel]) -> None:
        raise NotImplementedError

    def print_dry_run(
        self,
        config: PackagerConfig,
        entries: Sequence[tuple[Path, str]],
        rescued_files: Sequence[tuple[str, str]],
        excluded_files: Sequence[str],
    ) -> None:
        raise NotImplementedError

    def print_summary(
        self,
        config: PackagerConfig,
        output: Path,
        entries: Sequence[tuple[Path, str]],
        rescued_files: Sequence[tuple[str, str]],
        excluded_files: Sequence[str],
    ) -> None:
        raise NotImplementedError

    def print_explanation(
        self,
        explanation: PathExplanation,
        preset_name: str = "",
    ) -> None:
        raise NotImplementedError
