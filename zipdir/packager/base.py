"""Minimal concrete ZIP packager with TemplateMethod skeleton (base stage for progressive inheritance)."""

import importlib
import os
import stat
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath

from zipdir.interfaces.evaluator import IPathEvaluator
from zipdir.interfaces.packager import IArchiveEntryWriter, IPackager
from zipdir.interfaces.ui import IReporter
from zipdir.models import IgnoreRule, PackagerConfig, RuleKind
from zipdir.packager.writers import DEFAULT_ENTRY_WRITERS


def _is_packable_stat(path: Path) -> bool:
    try:
        mode = os.lstat(path).st_mode
        return bool(stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode))
    except OSError:
        return False


class ZipPackager(IPackager):
    """Minimal concrete packager defining the TemplateMethod skeleton for member collection."""

    config: PackagerConfig
    evaluator: IPathEvaluator
    reporter: IReporter
    entry_writers: Sequence[IArchiveEntryWriter]
    compiled_rules: list[IgnoreRule]
    rescued_files: list[tuple[str, str]]
    excluded_files: list[str]

    def __init__(
        self,
        config: PackagerConfig,
        evaluator: IPathEvaluator | None = None,
        reporter: IReporter | None = None,
        entry_writers: Sequence[IArchiveEntryWriter] | None = None,
    ) -> None:
        self.config = config
        self.evaluator = (
            evaluator
            if evaluator is not None
            else importlib.import_module("zipdir.evaluator").PathEvaluator(config.rules)
        )
        self.reporter = (
            reporter
            if reporter is not None
            else importlib.import_module("zipdir.ui").ConsoleReporter()
        )
        self.entry_writers = entry_writers if entry_writers is not None else DEFAULT_ENTRY_WRITERS
        self.compiled_rules = list(self.evaluator.rules)
        self.rescued_files = []
        self.excluded_files = []

    def collect_members(self) -> Iterator[tuple[Path, str]]:
        """Template skeleton traversing source directory and yielding (path, arcname) pairs."""
        prefix = self._archive_prefix()
        staged = self._init_staged_entries(prefix)
        for dirpath, dirnames, filenames in self.config.source.walk(follow_symlinks=False):
            rel_dir = dirpath.relative_to(self.config.source)
            self._filter_dirnames(dirpath, rel_dir, dirnames)
            for file_path, file_posix in self._iter_candidate_files(dirpath, rel_dir, filenames):
                match self._evaluate_file(file_posix, prefix):
                    case (full_arcname, arc_path, is_rescued):
                        self._stage_member(
                            staged, file_path, full_arcname, file_posix, arc_path, is_rescued
                        )
                    case None:
                        continue
        self._finalize_collection(staged)
        yield from staged

    def write_archive(self, path: Path, entries: Sequence[tuple[Path, str]]) -> None:
        """Write member files into the target ZIP archive via IArchiveEntryWriter strategies."""
        method = zipfile.ZIP_STORED if self.config.compression == 0 else zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(
            path, "w", compression=method, compresslevel=self.config.compression
        ) as archive:
            for item, arcname in entries:
                for writer in self.entry_writers:
                    if writer.matches(item, self.config.source):
                        writer.write(archive, item, arcname)
                        break

    def package(self) -> Path:
        """Minimal direct archive packaging (extended with atomic temp/hardlink in atomic.py)."""
        output = self.config.output
        entries = list(self.collect_members())
        self.write_archive(output, entries)
        return output

    def _archive_prefix(self) -> PurePosixPath:
        match self.config.flat:
            case True:
                return PurePosixPath()
            case False:
                return PurePosixPath(self.config.name)

    def _init_staged_entries(self, prefix: PurePosixPath) -> list[tuple[Path, str]]:
        match self.config.flat:
            case True:
                return []
            case False:
                return [(self.config.source, f"{prefix.as_posix()}/")]

    def _filter_dirnames(self, dirpath: Path, rel_dir: Path, dirnames: list[str]) -> None:
        dirnames[:] = sorted(d for d in dirnames if _is_packable_stat(dirpath / d))

    def _iter_candidate_files(
        self, dirpath: Path, rel_dir: Path, filenames: list[str]
    ) -> Iterator[tuple[Path, PurePosixPath]]:
        for fname in sorted(filenames):
            file_path = dirpath / fname
            if self._is_self_archive(file_path) or not _is_packable_stat(file_path):
                continue
            file_rel = rel_dir / fname if rel_dir != Path(".") else Path(fname)
            yield file_path, PurePosixPath(file_rel.as_posix())

    def _evaluate_file(
        self, file_posix: PurePosixPath, prefix: PurePosixPath
    ) -> tuple[str, PurePosixPath, bool] | None:
        result = self.evaluator.evaluate(file_posix, is_dir=False)
        match (result.is_excluded, result.arc_path):
            case (True, _) | (_, None):
                return None
            case (False, PurePosixPath() as arc):
                full_arcname = (prefix / arc).as_posix()
                is_rescued = (
                    result.matched_rule is not None and result.matched_rule.kind == RuleKind.RESCUE
                )
                return full_arcname, arc, is_rescued

    def _stage_member(
        self,
        staged: list[tuple[Path, str]],
        file_path: Path,
        full_arcname: str,
        file_posix: PurePosixPath,
        arc_path: PurePosixPath,
        is_rescued: bool,
    ) -> None:
        staged.append((file_path, full_arcname))

    def _finalize_collection(self, staged: Sequence[tuple[Path, str]]) -> None:
        pass

    def _is_self_archive(self, file_path: Path) -> bool:
        match file_path.name:
            case s if s.startswith(".zipdir_") and s.endswith(".zip"):
                return True
            case _:
                pass
        resolved = file_path.resolve()
        output_resolved = self.config.output.resolve()
        match resolved == output_resolved:
            case True:
                return True
            case False:
                match resolved.parent == output_resolved.parent:
                    case True:
                        fname = resolved.name
                        target_stems = {self.config.name, output_resolved.stem}
                        if "_" in output_resolved.stem:
                            target_stems.add(output_resolved.stem.rsplit("_", 1)[0])

                        for stem in target_stems:
                            match fname == f"{stem}.zip" or (
                                fname.startswith(f"{stem}_") and fname.endswith(".zip")
                            ):
                                case True:
                                    return True
                                case False:
                                    pass
                    case False:
                        pass
                return False
