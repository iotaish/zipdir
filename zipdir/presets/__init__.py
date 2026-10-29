"""Presets package exporting the final cascade PresetCatalog and helper functions."""

from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from zipdir.models import PresetModel
from zipdir.presets.base import DEFAULT_PRESET_DIRS, flatten_scoped_rule
from zipdir.presets.cascade import PresetCatalog


def load_raw_zipignore_preset(file: Path) -> PresetModel:
    """Parse a .zipignore preset file extracting description, inherit/extends, and rule lines."""
    return PresetCatalog().parse_file(file)


def load_presets(preset_dirs: Sequence[Path] | None = None) -> dict[str, PresetModel]:
    """Discover and load presets from configuration directories."""
    return PresetCatalog(preset_dirs=preset_dirs).load_all()


def discover_sub_zipignores(source: Path) -> list[tuple[PurePosixPath, Path]]:
    """Discover all .zipignore files in subdirectories under source, sorted by depth."""
    return PresetCatalog().discover_sub_zipignores(source)


__all__ = [
    "DEFAULT_PRESET_DIRS",
    "flatten_scoped_rule",
    "PresetCatalog",
    "discover_sub_zipignores",
    "load_presets",
    "load_raw_zipignore_preset",
]
