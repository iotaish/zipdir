"""Atomic and dry-run packager via progressive inheritance over phagocytic.ZipPackager."""

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from zipdir.models import RuleKind, format_size
from zipdir.packager.phagocytic import ZipPackager as PhagocyticZipPackager


class ZipPackager(PhagocyticZipPackager):
    """Extends PhagocyticZipPackager with pre-flight checks, dry-run preview, and atomic hardlink write."""

    def package(self) -> Path:
        """Evaluate paths, handle dry-run, or atomically write ZIP archive."""
        output = self.config.output
        match self.config.dry_run:
            case False:
                self._validate_output_target(output)
            case True:
                pass

        entries = list(self.collect_members())
        self._validate_pre_flight_constraints(entries)

        match self.config.dry_run:
            case True:
                self.reporter.print_dry_run(
                    self.config, entries, self.rescued_files, self.excluded_files
                )
                return output
            case False:
                self._write_atomic_archive(output, entries)
                self._validate_post_flight_constraints(output)
                self.reporter.print_summary(
                    self.config, output, entries, self.rescued_files, self.excluded_files
                )
                return output

    def _validate_output_target(self, output: Path) -> None:
        match not self.config.force and (output.exists() or output.is_symlink()):
            case True:
                raise FileExistsError(
                    f"Output already exists (use -f/--force to overwrite): {output}"
                )
            case False:
                match not output.parent.is_dir():
                    case True:
                        raise FileNotFoundError(
                            f"Output parent directory does not exist: {output.parent}"
                        )
                    case False:
                        pass

    def _write_atomic_archive(self, output: Path, entries: list[tuple[Path, str]]) -> None:
        fd, temp_file_str = tempfile.mkstemp(prefix=".zipdir_", suffix=".zip", dir=output.parent)
        os.close(fd)
        temp_path = Path(temp_file_str)
        try:
            self.write_archive(temp_path, entries)
            if self.config.force and (output.exists() or output.is_symlink()):
                output.unlink()
            output.hardlink_to(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _validate_pre_flight_constraints(self, entries: Sequence[tuple[Path, str]]) -> None:
        file_count = sum(1 for _, arcname in entries if not arcname.endswith("/"))
        if self.config.check_empty and file_count == 0:
            raise ValueError("Archive constraint violation (--check-empty): 0 files collected")

        has_rescue_rules = any(r.kind == RuleKind.RESCUE for r in self.compiled_rules)
        if self.config.strict_rescue and has_rescue_rules and not self.rescued_files:
            raise ValueError(
                "Archive constraint violation (--strict-rescue): specified rescue rules did not match any files"
            )

    def _validate_post_flight_constraints(self, output: Path) -> None:
        if self.config.max_size is not None:
            actual_size = output.stat().st_size
            if actual_size > self.config.max_size:
                output.unlink(missing_ok=True)
                raise ValueError(
                    f"Archive constraint violation (--max-size): size {format_size(actual_size)} exceeds limit of {format_size(self.config.max_size)}"
                )
