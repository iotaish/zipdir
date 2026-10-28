"""Interfaces for preset catalogs and cascading rule resolution."""

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from zipdir.interfaces.interpreter import IRuleSqueezer
from zipdir.models import PresetModel, ScopedRule


class IPresetCatalog:
    """Interface for discovering, loading, and cascading .zipignore presets."""

    preset_dirs: list[Path]
    interpreter: IRuleSqueezer

    def parse_file(self, file: Path) -> PresetModel:
        raise NotImplementedError

    def load_all(self) -> dict[str, PresetModel]:
        raise NotImplementedError

    def linearize_presets(
        self,
        name: str,
        raw_presets: Mapping[str, PresetModel],
    ) -> list[str]:
        raise NotImplementedError

    def discover_sub_zipignores(self, source: Path) -> list[tuple[PurePosixPath, Path]]:
        raise NotImplementedError

    def resolve_cascade(
        self,
        source: Path,
        presets: Mapping[str, PresetModel] | None = None,
        *,
        preset: str | None = None,
        cli_rules: Sequence[str] = (),
        no_default_rules: bool = False,
    ) -> tuple[str, list[str | ScopedRule]]:
        raise NotImplementedError
