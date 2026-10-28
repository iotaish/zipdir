"""Unit tests verifying interfaces/ package separation, progressive inheritance (OCP), TemplateMethod decomposition, match usage, and Strategy/Bridge patterns."""

import ast
import inspect
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

import pytest
from pydantic import ValidationError

import zipdir.evaluator.base
import zipdir.evaluator.pruning
import zipdir.evaluator.remapped
import zipdir.evaluator.strategies
import zipdir.glob.base
import zipdir.glob.gitignore
import zipdir.interfaces.evaluator
import zipdir.interfaces.glob
import zipdir.interfaces.interpreter
import zipdir.interfaces.output
import zipdir.interfaces.packager
import zipdir.interfaces.presets
import zipdir.interfaces.ui
import zipdir.interpreter.base
import zipdir.interpreter.squeezed
import zipdir.interpreter.strategies
import zipdir.models
import zipdir.output.base
import zipdir.output.fallback
import zipdir.output.strategies
import zipdir.packager.atomic
import zipdir.packager.base
import zipdir.packager.phagocytic
import zipdir.packager.pruned
import zipdir.packager.writers
import zipdir.presets.base
import zipdir.presets.cascade
import zipdir.presets.linearized
import zipdir.presets.local
import zipdir.ui.base
import zipdir.ui.verbose
from zipdir import (
    ArchiveRootRemapStrategy,
    ConsoleReporter,
    EvaluationResult,
    ExileRemapStrategy,
    GlobExpression,
    IGlobCompiler,
    IgnoreRule,
    IOutputResolver,
    IPackager,
    IPathEvaluator,
    IPresetCatalog,
    IRemapStrategy,
    IReporter,
    IRuleInterpreter,
    LocalScopeRemapStrategy,
    OutputResolver,
    OverwriteSqueezeStrategy,
    PackagerConfig,
    ParentClimbRemapStrategy,
    ParsedRule,
    PathEvaluator,
    PreserveHierarchyRemapStrategy,
    PresetCatalog,
    PresetModel,
    RemapContext,
    ResolvedOutput,
    RuleInterpreter,
    RuleKind,
    TargetedRedeleteSqueezeStrategy,
    ZipPackager,
    compile_rule,
)


class TestInterfacesDirectoryAndProgressiveInheritance:
    """Verifies dedicated interfaces/ directory separation and progressive inheritance (Sections 3.2, 3.4, 3.5, 4.6, 8.1)."""

    def test_interfaces_package_files_are_separated_and_import_no_concretes(self) -> None:
        """All interfaces reside under zipdir/interfaces/*.py and import only interfaces or models."""
        interface_modules = [
            zipdir.interfaces.glob,
            zipdir.interfaces.interpreter,
            zipdir.interfaces.evaluator,
            zipdir.interfaces.output,
            zipdir.interfaces.presets,
            zipdir.interfaces.ui,
            zipdir.interfaces.packager,
        ]
        for mod in interface_modules:
            source = inspect.getsource(mod)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and node.module.startswith("zipdir.")
                ):
                    assert node.module == "zipdir.models" or node.module.startswith(
                        "zipdir.interfaces."
                    ), (
                        f"{mod.__name__} must only import from zipdir.interfaces.* or zipdir.models, got {node.module}"
                    )

    def test_concrete_directories_contain_no_interface_definitions(self) -> None:
        """Concrete feature directories must not define I* interface classes."""
        concrete_modules = [
            zipdir.models,
            zipdir.glob.base,
            zipdir.glob.gitignore,
            zipdir.interpreter.base,
            zipdir.interpreter.squeezed,
            zipdir.interpreter.strategies,
            zipdir.evaluator.base,
            zipdir.evaluator.remapped,
            zipdir.evaluator.pruning,
            zipdir.evaluator.strategies,
            zipdir.output.base,
            zipdir.output.fallback,
            zipdir.output.strategies,
            zipdir.presets.base,
            zipdir.presets.linearized,
            zipdir.presets.local,
            zipdir.presets.cascade,
            zipdir.ui.base,
            zipdir.ui.verbose,
            zipdir.packager.base,
            zipdir.packager.pruned,
            zipdir.packager.phagocytic,
            zipdir.packager.atomic,
            zipdir.packager.writers,
        ]
        for mod in concrete_modules:
            source = inspect.getsource(mod)
            tree = ast.parse(source)
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    assert not (
                        node.name.startswith("I") and len(node.name) > 1 and node.name[1].isupper()
                    ), (
                        f"Interface {node.name} must reside in zipdir/interfaces/, not {mod.__name__}"
                    )

    def test_cross_package_imports_target_only_interfaces_or_models(self) -> None:
        """Concrete files in package A must never import concrete files from package B (DIP)."""
        package_concrete_groups = {
            "glob": [zipdir.glob.base, zipdir.glob.gitignore],
            "interpreter": [
                zipdir.interpreter.base,
                zipdir.interpreter.squeezed,
                zipdir.interpreter.strategies,
            ],
            "evaluator": [
                zipdir.evaluator.base,
                zipdir.evaluator.remapped,
                zipdir.evaluator.pruning,
                zipdir.evaluator.strategies,
            ],
            "output": [
                zipdir.output.base,
                zipdir.output.fallback,
                zipdir.output.strategies,
            ],
            "presets": [
                zipdir.presets.base,
                zipdir.presets.linearized,
                zipdir.presets.local,
                zipdir.presets.cascade,
            ],
            "ui": [zipdir.ui.base, zipdir.ui.verbose],
            "packager": [
                zipdir.packager.base,
                zipdir.packager.pruned,
                zipdir.packager.phagocytic,
                zipdir.packager.atomic,
                zipdir.packager.writers,
            ],
        }
        for pkg_name, mods in package_concrete_groups.items():
            own_prefix = f"zipdir.{pkg_name}."
            for mod in mods:
                source = inspect.getsource(mod)
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.ImportFrom)
                        and node.module
                        and node.module.startswith("zipdir.")
                    ):
                        if node.module.startswith(own_prefix):
                            continue
                        assert node.module == "zipdir.models" or node.module.startswith(
                            "zipdir.interfaces"
                        ), f"{mod.__name__} directly imports external concrete module {node.module}"

    def test_progressive_inheritance_chains_and_ocp_decomposition(self) -> None:
        """Verifies progressive inheritance chains and TemplateMethod decomposition across all packages."""
        # 1. glob: gitignore.GlobExpression -> base.GlobExpression -> IGlobCompiler
        assert GlobExpression is zipdir.glob.gitignore.GlobExpression
        assert issubclass(zipdir.glob.gitignore.GlobExpression, zipdir.glob.base.GlobExpression)
        assert issubclass(zipdir.glob.base.GlobExpression, IGlobCompiler)

        # 2. interpreter: squeezed.RuleInterpreter -> base.RuleInterpreter -> IRuleInterpreter
        assert RuleInterpreter is zipdir.interpreter.squeezed.RuleInterpreter
        assert issubclass(
            zipdir.interpreter.squeezed.RuleInterpreter,
            zipdir.interpreter.base.RuleInterpreter,
        )
        assert issubclass(zipdir.interpreter.base.RuleInterpreter, IRuleInterpreter)

        # 3. evaluator: pruning -> remapped -> base -> IPathEvaluator
        assert PathEvaluator is zipdir.evaluator.pruning.PathEvaluator
        assert issubclass(
            zipdir.evaluator.pruning.PathEvaluator,
            zipdir.evaluator.remapped.PathEvaluator,
        )
        assert issubclass(
            zipdir.evaluator.remapped.PathEvaluator,
            zipdir.evaluator.base.PathEvaluator,
        )
        assert issubclass(zipdir.evaluator.base.PathEvaluator, IPathEvaluator)

        # 4. output: fallback -> base -> IOutputResolver
        assert OutputResolver is zipdir.output.fallback.OutputResolver
        assert issubclass(
            zipdir.output.fallback.OutputResolver,
            zipdir.output.base.OutputResolver,
        )
        assert issubclass(zipdir.output.base.OutputResolver, IOutputResolver)

        # 5. presets: cascade -> local -> linearized -> base -> IPresetCatalog
        assert PresetCatalog is zipdir.presets.cascade.PresetCatalog
        assert issubclass(
            zipdir.presets.cascade.PresetCatalog,
            zipdir.presets.local.PresetCatalog,
        )
        assert issubclass(
            zipdir.presets.local.PresetCatalog,
            zipdir.presets.linearized.PresetCatalog,
        )
        assert issubclass(
            zipdir.presets.linearized.PresetCatalog,
            zipdir.presets.base.PresetCatalog,
        )
        assert issubclass(zipdir.presets.base.PresetCatalog, IPresetCatalog)

        # 6. ui: verbose -> base -> IReporter
        assert ConsoleReporter is zipdir.ui.verbose.ConsoleReporter
        assert issubclass(zipdir.ui.verbose.ConsoleReporter, zipdir.ui.base.ConsoleReporter)
        assert issubclass(zipdir.ui.base.ConsoleReporter, IReporter)

        # 7. packager: atomic -> phagocytic -> pruned -> base -> IPackager
        assert ZipPackager is zipdir.packager.atomic.ZipPackager
        assert issubclass(
            zipdir.packager.atomic.ZipPackager,
            zipdir.packager.phagocytic.ZipPackager,
        )
        assert issubclass(
            zipdir.packager.phagocytic.ZipPackager,
            zipdir.packager.pruned.ZipPackager,
        )
        assert issubclass(
            zipdir.packager.pruned.ZipPackager,
            zipdir.packager.base.ZipPackager,
        )
        assert issubclass(zipdir.packager.base.ZipPackager, IPackager)


class TestStructuralPatternMatchingUsage:
    """Verifies active utilization of Python 3.10+ match statements across the codebase."""

    def test_match_statements_present_in_core_modules(self) -> None:
        """Verify that core modules use match/case statements for state transitions and AST parsing."""
        modules_with_match = [
            zipdir.models,
            zipdir.interpreter.base,
            zipdir.interpreter.squeezed,
            zipdir.evaluator.base,
            zipdir.evaluator.strategies,
            zipdir.output.base,
            zipdir.presets.base,
            zipdir.presets.local,
            zipdir.packager.base,
        ]
        for mod in modules_with_match:
            source = inspect.getsource(mod)
            tree = ast.parse(source)
            match_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Match)]
            assert len(match_nodes) >= 1, f"Expected match statements in {mod.__name__}, found none"


class TestDataModelInvariants:
    """Verifies domain data model runtime class invariants."""

    def test_parsed_rule_invariants(self) -> None:
        with pytest.raises(ValueError, match="pattern must be non-empty"):
            ParsedRule(RuleKind.EXCLUDE, "", "")
        with pytest.raises(ValueError, match=r"'\?' is prohibited"):
            ParsedRule(RuleKind.RESCUE, "?/dist", "*.pdf")

    def test_ignore_rule_invariants(self) -> None:
        base = compile_rule("*.pdf")
        assert base is not None
        with pytest.raises(ValueError, match="scope must be a relative path"):
            IgnoreRule(
                raw="*.pdf",
                kind=RuleKind.EXCLUDE,
                target="",
                pattern="*.pdf",
                regex=base.regex,
                is_dir_only=False,
                has_slash=False,
                scope=PurePosixPath("/abs/scope"),
            )

    def test_evaluation_result_invariants(self) -> None:
        with pytest.raises(ValueError, match="excluded path cannot have an arc_path"):
            EvaluationResult(True, PurePosixPath("a.txt"), None)
        with pytest.raises(ValueError, match="included path must have an arc_path"):
            EvaluationResult(False, None, None)

    def test_resolved_output_invariants(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="explicit .zip path cannot fall back"):
            ResolvedOutput(
                path=tmp_path / "out.zip",
                explicit_zip=True,
                stem="out",
                fell_back=True,
            )

    def test_packager_config_invariants(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            PackagerConfig(
                source=tmp_path,
                output=tmp_path / "out.zip",
                name="",
                preset_name="clean",
            )
        with pytest.raises(ValidationError):
            PackagerConfig(
                source=tmp_path,
                output=tmp_path / "out.zip",
                name="proj",
                preset_name="clean",
                compression=10,
            )


class TestBridgeAndStrategyPatterns:
    """Verifies Strategy implementations and Bridge DI."""

    def test_bridge_custom_reporter_injection(self, tmp_path: Path) -> None:
        class RecordingReporter(IReporter):
            def __init__(self) -> None:
                self.use_color = False
                self.dry_run_called = False
                self.recorded_entries: list[str] = []

            def print_presets(self, presets: Mapping[str, PresetModel]) -> None:
                pass

            def print_dry_run(
                self,
                config: PackagerConfig,
                entries: Sequence[tuple[Path, str]],
                rescued_files: Sequence[tuple[str, str]],
                excluded_files: Sequence[str],
            ) -> None:
                self.dry_run_called = True
                self.recorded_entries = [arc for _, arc in entries]

            def print_summary(
                self,
                config: PackagerConfig,
                output: Path,
                entries: Sequence[tuple[Path, str]],
                rescued_files: Sequence[tuple[str, str]],
                excluded_files: Sequence[str],
            ) -> None:
                pass

        src = tmp_path / "app"
        src.mkdir()
        (src / "hello.txt").write_text("hi")
        cfg = PackagerConfig(
            source=src,
            output=tmp_path / "app.zip",
            name="app",
            preset_name="clean",
            flat=True,
            dry_run=True,
        )
        reporter = RecordingReporter()
        packager = ZipPackager(cfg, reporter=reporter)
        packager.package()

        assert reporter.dry_run_called
        assert reporter.recorded_entries == ["hello.txt"]

    def test_remap_strategies_unit(self) -> None:
        rule = compile_rule("/dist/!out/a.pdf")
        assert rule is not None
        ctx = RemapContext(
            rel_path=PurePosixPath("out/a.pdf"),
            rescued_by=rule,
            shallowest_excluded_ancestor=PurePosixPath("out"),
            sub_path=PurePosixPath("a.pdf"),
            anchor_parent=PurePosixPath("."),
        )
        strat = ArchiveRootRemapStrategy()
        assert strat.matches("/dist/")
        assert strat.remap(ctx) == PurePosixPath("dist/a.pdf")

        for s_cls in (
            PreserveHierarchyRemapStrategy,
            ArchiveRootRemapStrategy,
            LocalScopeRemapStrategy,
            ParentClimbRemapStrategy,
            ExileRemapStrategy,
        ):
            assert issubclass(s_cls, IRemapStrategy)

    def test_custom_remap_strategy_injection(self) -> None:
        class PrefixOverrideStrategy(IRemapStrategy):
            def matches(self, target: str) -> bool:
                return target == "custom_hook"

            def remap(self, ctx: RemapContext) -> PurePosixPath:
                return PurePosixPath("hooked") / ctx.sub_path

        evaluator = PathEvaluator(
            ["out/", "custom_hook!out/file.txt"],
            remap_strategies=(PrefixOverrideStrategy(),),
        )
        res = evaluator.evaluate(PurePosixPath("out/file.txt"))
        assert not res.is_excluded
        assert res.arc_path == PurePosixPath("hooked/file.txt")

    def test_squeeze_strategies_compile_all_consistency(self) -> None:
        interpreter = RuleInterpreter()
        raw_rules = ["out/", "!out/*.pdf", "dist/!out/*.pdf", "!build/!out/*.pdf"]
        compiled = interpreter.compile_all(raw_rules, squeeze=True)
        assert [r.raw for r in compiled] == ["out/", "dist/!out/*.pdf", "!build/!out/*.pdf"]
        assert isinstance(
            interpreter.squeeze_strategies[RuleKind.EXCLUDE], OverwriteSqueezeStrategy
        )
        assert isinstance(
            interpreter.squeeze_strategies[RuleKind.REDELETE], TargetedRedeleteSqueezeStrategy
        )
