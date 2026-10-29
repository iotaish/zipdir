"""Minimal concrete preset file parser and base cascade skeleton (base stage for progressive inheritance)."""

import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from zipdir.interfaces.interpreter import IRuleSqueezer
from zipdir.interfaces.presets import IPresetCatalog
from zipdir.models import PresetModel, ScopedRule

DEFAULT_PRESET_DIRS: list[Path] = [
    Path(__file__).resolve().parent.parent.parent / "presets",
    Path(__file__).resolve().parent.parent / "presets",
    Path.home() / ".config" / "zipdir" / "presets",
    Path.home() / ".dcfg" / "config" / "zipdir" / "presets",
]


def _as_preset_model(preset: PresetModel | Mapping[str, object]) -> PresetModel:
    match preset:
        case PresetModel():
            return preset
        case Mapping() as d:
            return PresetModel.model_validate(d)
        case _:
            raise TypeError(f"Invalid preset type: {type(preset)}")


def flatten_scoped_rule(scoped: ScopedRule) -> str:
    """Convert a ScopedRule into an equivalent root-level .zipignore rule string."""
    scope_str = scoped.scope.as_posix()
    if scope_str in ("", "."):
        return scoped.rule

    stripped = scoped.rule.strip()
    if stripped.startswith("#"):
        comment = stripped.lstrip("#").strip()
        return f"# [{scope_str}] {comment}"

    m = re.match(r"^(?P<b1>!?)(?P<to>[^!]*)!(?P<pattern>.+)$", stripped)
    if m:
        b1 = m.group("b1")
        to = m.group("to").strip()
        pat = m.group("pattern").strip()
        if to and not to.startswith(("/", "./", "../")):
            scoped_to = f"{scope_str}/{to}"
        else:
            scoped_to = to
        scoped_pat = pat.lstrip("/")
        new_pat = f"{scope_str}/{scoped_pat}"
        return f"{b1}{scoped_to}!{new_pat}"
    else:
        clean_rule = stripped.lstrip("/")
        if "/" in clean_rule:
            return f"{scope_str}/{clean_rule}"
        else:
            return f"{scope_str}/**/{clean_rule}"


class PresetCatalog(IPresetCatalog):
    """Minimal concrete preset catalog with TemplateMethod skeleton for rule cascading."""

    preset_dirs: list[Path]
    interpreter: IRuleSqueezer

    def __init__(
        self,
        preset_dirs: Sequence[Path] | None = None,
        interpreter: IRuleSqueezer | None = None,
    ) -> None:
        dirs = list(preset_dirs) if preset_dirs is not None else list(DEFAULT_PRESET_DIRS)
        if "ZIPDIR_PRESETS_DIR" in os.environ:
            dirs.insert(0, Path(os.environ["ZIPDIR_PRESETS_DIR"]))
        self.preset_dirs = dirs
        if interpreter is not None:
            self.interpreter = interpreter
        else:
            import importlib

            self.interpreter = importlib.import_module("zipdir.interpreter").RuleInterpreter()

    def parse_file(self, file: Path) -> PresetModel:
        """Parse a .zipignore preset file extracting description, inherit/extends, and rule lines."""
        description = ""
        extends: list[str] = []
        rules: list[str] = []

        for line in file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            match stripped:
                case "":
                    continue
                case s if s.startswith("#"):
                    description = self._parse_comment_directive(s, extends, description)
                    continue
                case s:
                    rules.append(s)

        return PresetModel(
            name=self._extract_preset_stem(file),
            description=description,
            rules=rules,
            extends=extends,
            source_path=file,
        )

    def load_all(self) -> dict[str, PresetModel]:
        """Minimal raw preset loading (extended with C3 linearization in linearized.py)."""
        return self._discover_raw_presets()

    def linearize_presets(
        self,
        name: str,
        raw_presets: Mapping[str, PresetModel],
    ) -> list[str]:
        """Minimal single-node linearization (extended with C3 MRO in linearized.py)."""
        if name not in raw_presets:
            raise ValueError(f"Preset '{name}' not found in configuration directories")
        return [name]

    def discover_sub_zipignores(self, source: Path) -> list[tuple[PurePosixPath, Path]]:
        """Minimal sub-zipignore hook (extended in cascade.py)."""
        return []

    def resolve_cascade(
        self,
        source: Path,
        presets: Mapping[str, PresetModel] | None = None,
        *,
        preset: str | None = None,
        cli_rules: Sequence[str] = (),
        no_default_rules: bool = False,
    ) -> tuple[str, list[str | ScopedRule]]:
        """Template skeleton building and squeezing the 4-tier rule cascade."""
        loaded = presets if presets is not None else self.load_all()
        local_model = self._load_root_zipignore(source)
        effective_name = self._determine_preset_name(preset, local_model)

        tier1: list[ScopedRule] = []
        if not no_default_rules:
            base_lines, effective_name = self._collect_tier1_rules(
                source, loaded, preset, local_model, effective_name
            )
            tier1 = [ScopedRule(rule=r) for r in base_lines]

        tier2 = self._collect_tier2_rules(source, loaded, preset, local_model)
        tier3 = self._collect_tier3_rules(source, loaded)
        tier4 = [ScopedRule(rule=r) for r in cli_rules]

        return effective_name, self._squeeze_cascade([*tier1, *tier2, *tier3, *tier4])

    def format_bundle(
        self,
        source_name: str,
        preset_name: str,
        rules: Sequence[str | ScopedRule],
    ) -> str:
        """Format resolved cascade rules into a self-contained, standalone .zipignore file string."""
        lines: list[str] = [
            f"# .zipignore: self-contained rule bundle for '{source_name}'",
            f"# base-preset: {preset_name}",
            "# resolved: 4-tier cascade (preset -> root -> subdir -> cli) & squeezed",
            "",
        ]
        for r in rules:
            match r:
                case ScopedRule() as s:
                    lines.append(flatten_scoped_rule(s))
                case str() as s:
                    lines.append(s)
        lines.append("")
        return "\n".join(lines)

    def _load_root_zipignore(self, source: Path) -> PresetModel | None:
        local_file = source / ".zipignore"
        return self.parse_file(local_file) if local_file.is_file() else None

    def _determine_preset_name(self, preset: str | None, local_model: PresetModel | None) -> str:
        match (preset, local_model):
            case (str() as p, _):
                return p
            case (None, PresetModel(extends=extends)) if extends:
                return ", ".join(extends)
            case _:
                return "clean"

    def _collect_tier1_rules(
        self,
        source: Path,
        loaded_presets: Mapping[str, PresetModel],
        preset: str | None,
        local_model: PresetModel | None,
        effective_name: str,
    ) -> tuple[list[str], str]:
        match (preset, preset in loaded_presets if preset else False):
            case (str() as p, True):
                return list(loaded_presets[p].rules), effective_name
            case (None, _) if "clean" in loaded_presets:
                return list(loaded_presets["clean"].rules), effective_name
            case (str() as p, False):
                available = ", ".join(loaded_presets.keys())
                raise ValueError(f"Unknown preset '{p}'. Available: {available}")
            case _:
                return [], effective_name

    def _collect_tier2_rules(
        self,
        source: Path,
        loaded_presets: Mapping[str, PresetModel],
        preset: str | None,
        local_model: PresetModel | None,
    ) -> list[ScopedRule]:
        return []

    def _collect_tier3_rules(
        self,
        source: Path,
        loaded_presets: Mapping[str, PresetModel],
    ) -> list[ScopedRule]:
        return []

    def _squeeze_cascade(self, combined: Sequence[ScopedRule]) -> list[str | ScopedRule]:
        squeezed = self.interpreter.squeeze(combined)
        result: list[str | ScopedRule] = []
        for r in squeezed:
            match r:
                case str() | ScopedRule():
                    result.append(r)
                case _:
                    result.append(ScopedRule(scope=r.scope, rule=r.rule))
        return result

    def _parse_comment_directive(self, stripped: str, extends: list[str], description: str) -> str:
        lower = stripped.lower()
        match lower:
            case s if any(k in s for k in ("inherit:", "extends:", "include:")):
                val = stripped.split(":", 1)[1]
                for p in val.split(","):
                    p_clean = p.strip()
                    if p_clean and p_clean not in extends:
                        extends.append(p_clean)
                return description
            case s if "description:" in s:
                return stripped.split(":", 1)[1].strip()
            case _:
                return description

    def _extract_preset_stem(self, file: Path) -> str:
        stem = file.name
        match stem:
            case s if s.endswith(".zipignore"):
                return s.removesuffix(".zipignore")
            case s if s.endswith((".yaml", ".yml")):
                return file.stem
            case s:
                return s

    def _discover_raw_presets(self) -> dict[str, PresetModel]:
        raw_presets: dict[str, PresetModel] = {}
        for directory in self.preset_dirs:
            if not directory.is_dir():
                continue
            found_files = (
                sorted(directory.glob("*.zipignore"))
                + sorted(directory.glob("*.yaml"))
                + sorted(directory.glob("*.yml"))
            )
            for file in found_files:
                stem = self._extract_preset_stem(file)
                if stem not in raw_presets:
                    try:
                        raw_presets[stem] = self.parse_file(file)
                    except Exception as e:
                        print(
                            f"zipdir: warning: failed to parse preset '{file}': {e}",
                            file=sys.stderr,
                        )
        return raw_presets
