"""Interfaces for archive packaging and entry writing."""

import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path

from zipdir.interfaces.evaluator import IPathEvaluator
from zipdir.interfaces.ui import IReporter
from zipdir.models import IgnoreRule, PackagerConfig


class IArchiveEntryWriter:
    """Strategy interface for writing filesystem entries into a ZIP archive."""

    def matches(self, item: Path, source: Path) -> bool:
        raise NotImplementedError

    def write(self, archive: zipfile.ZipFile, item: Path, arcname: str) -> None:
        raise NotImplementedError


class IPackager:
    """Interface for packaging directories into ZIP archives."""

    config: PackagerConfig
    evaluator: IPathEvaluator
    reporter: IReporter
    entry_writers: Sequence[IArchiveEntryWriter]
    compiled_rules: list[IgnoreRule]
    rescued_files: list[tuple[str, str]]
    excluded_files: list[str]

    def collect_members(self) -> Iterator[tuple[Path, str]]:
        raise NotImplementedError

    def write_archive(self, path: Path, entries: Sequence[tuple[Path, str]]) -> None:
        raise NotImplementedError

    def package(self) -> Path:
        raise NotImplementedError
