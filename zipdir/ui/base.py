"""Minimal concrete console reporter and terminal styling helpers (base stage for progressive inheritance)."""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from zipdir.interfaces.ui import IReporter
from zipdir.models import PackagerConfig, PathExplanation, PresetModel
from zipdir.models import format_size as format_size
from zipdir.models import parse_size as parse_size

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(text: str, code: str, *, enabled: bool = USE_COLOR) -> str:
    match enabled:
        case True:
            return f"\033[{code}m{text}\033[0m"
        case False:
            return text


def color_success(text: str) -> str:
    return _c(text, "1;32")


def color_dim(text: str) -> str:
    return _c(text, "2")


def color_bold(text: str) -> str:
    return _c(text, "1")


def color_cyan(text: str) -> str:
    return _c(text, "36")


def color_yellow(text: str) -> str:
    return _c(text, "33")


class ConsoleReporter(IReporter):
    """Minimal concrete reporter rendering preset listings, dry-run previews, and base summaries."""

    use_color: bool

    def __init__(self, use_color: bool | None = None) -> None:
        self.use_color = USE_COLOR if use_color is None else use_color

    def print_presets(self, presets: Mapping[str, PresetModel]) -> None:
        """Display available presets and their configurations."""
        print(self._bold("\nAvailable zipdir presets:\n"))
        for name, p in presets.items():
            src_info = f"({p.source_path})" if p.source_path else "(built-in)"
            extends_info = f" [extends {', '.join(p.extends)}]" if p.extends else ""
            print(
                f"  {self._cyan(name):<12} {self._bold(p.description)}{self._dim(extends_info)} {self._dim(src_info)}"
            )
            if p.rules:
                rules_str = ", ".join(p.rules)
                print(f"    {self._dim('• Rules:')} {rules_str}")
            print()

    def print_dry_run(
        self,
        config: PackagerConfig,
        entries: Sequence[tuple[Path, str]],
        rescued_files: Sequence[tuple[str, str]],
        excluded_files: Sequence[str],
    ) -> None:
        """Render dry-run preview of archive structure."""
        print(
            f"\n{self._yellow('[DRY RUN]')} Resulting archive structure for {self._bold(config.output.name)}:"
        )
        print(f"  • Source:   {config.source}")
        print(f"  • Preset:   {config.preset_name}")
        print(f"  • Rules:    {len(config.rules)} rules\n")
        if rescued_files:
            print(self._cyan("Rescued / Remapped files (!):"))
            for src, dst in rescued_files:
                print(f"  ↑ {src} -> {dst}")
        if excluded_files:
            print(self._yellow("Excluded paths:"))
            for ex in excluded_files:
                print(f"  ✕ {ex}")
        print(self._bold("Archive members:"))
        for _, arcname in entries:
            print(f"  + {arcname}")

    def print_summary(
        self,
        config: PackagerConfig,
        output: Path,
        entries: Sequence[tuple[Path, str]],
        rescued_files: Sequence[tuple[str, str]],
        excluded_files: Sequence[str],
    ) -> None:
        """Render completion summary after archive creation."""
        file_count = sum(1 for _, arcname in entries if not arcname.endswith("/"))
        dir_count = sum(1 for _, arcname in entries if arcname.endswith("/"))
        size_str = format_size(output.stat().st_size)

        print(
            f"{self._success('✔')} Created archive: {self._bold(output.name)} {self._dim(f'({size_str})')}"
        )
        print(f"  {self._dim('Path:')}     {self._cyan(str(output))}")
        print(f"  {self._dim('Preset:')}   {config.preset_name} ({len(config.rules)} rules)")
        print(f"  {self._dim('Members:')}  {file_count} files, {dir_count} directories")

    def print_explanation(
        self,
        explanation: PathExplanation,
        preset_name: str = "",
    ) -> None:
        """Render step-by-step rule evaluation diagnosis and state transition trace."""
        print(
            f"\n{self._bold('Rule Evaluation Diagnostic')} for '{self._cyan(explanation.rel_path.as_posix())}':"
        )
        if preset_name:
            print(f"  {self._dim('Effective Preset:')} {preset_name}")
        print()

        if not explanation.steps:
            print(f"  {self._dim('(No rules matched this path)')}\n")
        else:
            print(self._bold("Transition Trace:"))
            for idx, step in enumerate(explanation.steps, 1):
                target_kind = "Ancestor" if step.is_ancestor else "Target"
                kind_badge = (
                    self._yellow(step.kind.name)
                    if step.kind.name == "EXCLUDE"
                    else self._cyan(step.kind.name)
                )
                print(
                    f"  [{idx}] {target_kind} '{step.target.as_posix()}' matched rule '{step.rule.raw}' ({kind_badge})"
                )
                state_str = "EXCLUDED" if step.is_excluded_after else "INCLUDED / RESCUED"
                anc_info = (
                    f" (shallowest: '{step.shallowest_excluded_ancestor}')"
                    if step.shallowest_excluded_ancestor
                    else ""
                )
                print(f"      -> State: {state_str}{self._dim(anc_info)}")
            print()

        status_str = (
            self._yellow("EXCLUDED")
            if explanation.result.is_excluded
            else self._success("INCLUDED")
        )
        arc_str = (
            explanation.result.arc_path.as_posix()
            if explanation.result.arc_path is not None
            else "(none)"
        )
        rule_str = (
            explanation.result.matched_rule.raw
            if explanation.result.matched_rule is not None
            else "(none)"
        )

        print(self._bold("Final Decision:"))
        print(f"  • Status:       {status_str}")
        print(f"  • Archive Path: {self._cyan(arc_str)}")
        print(f"  • Matched Rule: {rule_str}")

    def _success(self, text: str) -> str:
        return _c(text, "1;32", enabled=self.use_color)

    def _dim(self, text: str) -> str:
        return _c(text, "2", enabled=self.use_color)

    def _bold(self, text: str) -> str:
        return _c(text, "1", enabled=self.use_color)

    def _cyan(self, text: str) -> str:
        return _c(text, "36", enabled=self.use_color)

    def _yellow(self, text: str) -> str:
        return _c(text, "33", enabled=self.use_color)
