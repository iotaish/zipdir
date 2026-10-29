"""Comprehensive tests for zipdir ignore rule syntax, path evaluation, and packaging engine."""

import zipfile
from pathlib import Path, PurePosixPath

import pytest

from zipdir import (
    GlobExpression,
    IgnoreRule,
    PackagerConfig,
    ParsedRule,
    PresetModel,
    RuleInterpreter,
    RuleKind,
    ScopedRule,
    ZipPackager,
    compile_rule,
    discover_sub_zipignores,
    evaluate_path,
    load_raw_zipignore_preset,
    squeeze_rules,
)
from zipdir.cli import resolve_output_path


# ==============================================================================
# 1. Rule Compiler Tests (Syntax Variations)
# ==============================================================================
class TestRuleCompiler:
    """Tests parsing and compilation of all .zipignore rule syntax variations."""

    def test_comments_and_blank_lines(self) -> None:
        """Comments and empty lines should return None."""
        assert compile_rule("") is None
        assert compile_rule("   ") is None
        assert compile_rule("# This is a comment") is None
        assert compile_rule("   # Indented comment") is None

    def test_standard_exclude_rules(self) -> None:
        """Standard gitignore-style exclusions."""
        r_file = compile_rule("debug.log")
        assert r_file is not None
        assert r_file.kind == RuleKind.EXCLUDE
        assert r_file.pattern == "debug.log"
        assert not r_file.is_dir_only

        r_dir = compile_rule("out/")
        assert r_dir is not None
        assert r_dir.kind == RuleKind.EXCLUDE
        assert r_dir.pattern == "out/"
        assert r_dir.is_dir_only

        r_glob = compile_rule("*.tmp")
        assert r_glob is not None
        assert r_glob.kind == RuleKind.EXCLUDE
        assert r_glob.pattern == "*.tmp"

    def test_rescue_exile_route_default(self) -> None:
        """Default rescue syntax '!{pattern}' has empty target '' (亡命ルート)."""
        r = compile_rule("!out/*.pdf")
        assert r is not None
        assert r.kind == RuleKind.RESCUE
        assert r.target == ""
        assert r.pattern == "out/*.pdf"

    def test_question_prefix_is_abolished(self) -> None:
        """Legacy '?' prefix syntax in destination targets is rejected."""
        for syntax in ["?/!out/*.pdf", "?!out/*.pdf", "?/dist!out/*.pdf", "!?/dist!out/*.pdf"]:
            assert compile_rule(syntax) is None, f"Expected {syntax} to be rejected"

    def test_rescue_preserve_hierarchy(self) -> None:
        """階層死守 (Preserve original directory hierarchy) syntax: './!{}' and '.!{}'."""
        for syntax in ["./!out/*.pdf", ".!out/*.pdf"]:
            r = compile_rule(syntax)
            assert r is not None, f"Failed to compile {syntax}"
            assert r.kind == RuleKind.RESCUE
            assert r.target in (".", "./")
            assert r.pattern == "out/*.pdf"

    def test_rescue_custom_destination(self) -> None:
        """Custom remapping targets: '{to}!{pattern}'."""
        # Directory targets require trailing slash
        r1 = compile_rule("dist/!out/*.pdf")
        assert r1 is not None
        assert r1.kind == RuleKind.RESCUE
        assert r1.target == "dist/"
        assert r1.pattern == "out/*.pdf"

        r2 = compile_rule("dist/bundle/!out/*.pdf")
        assert r2 is not None
        assert r2.kind == RuleKind.RESCUE
        assert r2.target == "dist/bundle/"
        assert r2.pattern == "out/*.pdf"

        # Rename targets without trailing slash
        r_rename1 = compile_rule("final.pdf!out/*.pdf")
        assert r_rename1 is not None
        assert r_rename1.target == "final.pdf"

        r_rename2 = compile_rule("app!out/bin")
        assert r_rename2 is not None
        assert r_rename2.target == "app"

    def test_rescue_archive_root(self) -> None:
        """Archive root placement '/!{pattern}'."""
        r = compile_rule("/!out/*.pdf")
        assert r is not None
        assert r.kind == RuleKind.RESCUE
        assert r.target == "/"
        assert r.pattern == "out/*.pdf"

    def test_rescue_relative_lift(self) -> None:
        """Relative lifting: '../!{pattern}'."""
        r = compile_rule("../!sub/doc.txt")
        assert r is not None
        assert r.kind == RuleKind.RESCUE
        assert r.target in ("..", "../")
        assert r.pattern == "sub/doc.txt"

    def test_redelete_syntax(self) -> None:
        """Re-delete syntax '!{to}!{pattern}' and '!!{pattern}' using 3-tier prefix targets."""
        # Exile cancellation with !! (omitted target == '')
        r = compile_rule("!!out/draft.pdf")
        assert r is not None
        assert r.kind == RuleKind.REDELETE
        assert r.target == ""
        assert r.pattern == "out/draft.pdf"

        # Targeted cancellations with !{to}!
        r_dist = compile_rule("!dist/!out/*.pdf")
        assert r_dist is not None
        assert r_dist.kind == RuleKind.REDELETE
        assert r_dist.target == "dist/"
        assert r_dist.pattern == "out/*.pdf"

        r_preserve = compile_rule("!./!out/draft.pdf")
        assert r_preserve is not None
        assert r_preserve.kind == RuleKind.REDELETE
        assert r_preserve.target == "./"
        assert r_preserve.pattern == "out/draft.pdf"

        r_root = compile_rule("!/dist/!out/*.pdf")
        assert r_root is not None
        assert r_root.kind == RuleKind.REDELETE
        assert r_root.target == "/dist/"
        assert r_root.pattern == "out/*.pdf"

        r_rename = compile_rule("!final.pdf!out/*.pdf")
        assert r_rename is not None
        assert r_rename.kind == RuleKind.REDELETE
        assert r_rename.target == "final.pdf"
        assert r_rename.pattern == "out/*.pdf"

    def test_escaped_exclamation(self) -> None:
        """Escaped exclamation mark should be treated as literal character."""
        r = compile_rule(r"\!important.txt")
        assert r is not None
        assert r.kind == RuleKind.EXCLUDE
        assert r.pattern == r"\!important.txt"


# ==============================================================================
# 2. Path Evaluation & Remapping Tests (Semantic Verification)
# ==============================================================================
class TestPathEvaluation:
    """Tests evaluate_path logic across all rule types and remapping targets."""

    def test_unexcluded_file(self) -> None:
        """Files that do not match any ignore rules are kept as-is."""
        rules: list[IgnoreRule] = []
        is_exc, arc, matched = evaluate_path(PurePosixPath("src/main.py"), False, rules)
        assert not is_exc
        assert arc == PurePosixPath("src/main.py")
        assert matched is None

    def test_normal_directory_exclusion(self) -> None:
        """Directory exclusion excludes all descendants."""
        rules = [compile_rule("out/") or pytest.fail("rule failed")]
        is_exc, arc, matched = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert is_exc
        assert arc is None
        assert matched is not None and matched.kind == RuleKind.EXCLUDE

    def test_exile_route_lifts_from_excluded_dir(self) -> None:
        """'!' lifts file from excluded folder to exile destination."""
        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("!out/*.pdf") or pytest.fail("rule failed"),
        ]
        is_exc, arc, matched = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert not is_exc
        assert arc == PurePosixPath("report.pdf")
        assert matched is not None and matched.kind == RuleKind.RESCUE

    def test_exile_route_nested_excluded_dir(self) -> None:
        """Nested excluded folder 'a/b/out/' lifts file to 'a/b/' via '!a/b/out/*.pdf'."""
        rules = [
            compile_rule("a/b/out/") or pytest.fail("rule failed"),
            compile_rule("!a/b/out/*.pdf") or pytest.fail("rule failed"),
        ]
        is_exc, arc, matched = evaluate_path(PurePosixPath("a/b/out/report.pdf"), False, rules)
        assert not is_exc
        assert arc == PurePosixPath("a/b/report.pdf")
        assert matched is not None and matched.kind == RuleKind.RESCUE

    def test_preserve_hierarchy_in_excluded_dir(self) -> None:
        """'./!{}' keeps original hierarchy even when the parent folder is excluded."""
        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("./!out/*.pdf") or pytest.fail("rule failed"),
        ]
        is_exc, arc, matched = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert not is_exc
        assert arc == PurePosixPath("out/report.pdf")
        assert matched is not None and matched.kind == RuleKind.RESCUE

    def test_custom_destination_remapping(self) -> None:
        """'dist/!out/*.pdf' remaps to 'dist/report.pdf' at exile destination."""
        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("dist/!out/*.pdf") or pytest.fail("rule failed"),
        ]
        is_exc, arc, matched = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert not is_exc
        assert arc == PurePosixPath("dist/report.pdf")
        assert matched is not None and matched.kind == RuleKind.RESCUE

    def test_redelete_cancels_specific_destination(self) -> None:
        """'!dist/!out/*.pdf' cancels a prior 'dist/!out/*.pdf' rescue."""
        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("dist/!out/*.pdf") or pytest.fail("rule failed"),
            compile_rule("!dist/!out/*.pdf") or pytest.fail("rule failed"),
        ]
        is_exc, arc, matched = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert is_exc
        assert arc is None
        assert matched is not None and matched.kind == RuleKind.REDELETE
        assert matched.target == "dist/"

    def test_archive_root_remapping(self) -> None:
        """'/!out/*.pdf' places directly at archive root."""
        rules = [
            compile_rule("a/b/out/") or pytest.fail("rule failed"),
            compile_rule("/!a/b/out/*.pdf") or pytest.fail("rule failed"),
        ]
        is_exc, arc, matched = evaluate_path(PurePosixPath("a/b/out/report.pdf"), False, rules)
        assert not is_exc
        assert arc == PurePosixPath("report.pdf")
        assert matched is not None and matched.kind == RuleKind.RESCUE

    def test_lift_unexcluded_file(self) -> None:
        """'../!{}' and '!{}' can lift files even if their folder was never excluded."""
        rules = [compile_rule("../!sub/notes.md") or pytest.fail("rule failed")]
        is_exc, arc, matched = evaluate_path(PurePosixPath("sub/notes.md"), False, rules)
        assert not is_exc
        assert arc == PurePosixPath("notes.md")

    def test_redelete_negates_rescue(self) -> None:
        """'!!pattern' re-excludes a file previously rescued via '!pattern'."""
        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("!out/*.pdf") or pytest.fail("rule failed"),
            compile_rule("!!out/draft.pdf") or pytest.fail("rule failed"),
        ]
        # report.pdf is rescued
        exc1, arc1, _ = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert not exc1
        assert arc1 == PurePosixPath("report.pdf")

        # draft.pdf is re-deleted (excluded)
        exc2, arc2, matched2 = evaluate_path(PurePosixPath("out/draft.pdf"), False, rules)
        assert exc2
        assert arc2 is None
        assert matched2 is not None and matched2.kind == RuleKind.REDELETE

        # other files in out/ remain excluded
        exc3, arc3, _ = evaluate_path(PurePosixPath("out/other.txt"), False, rules)
        assert exc3
        assert arc3 is None

    def test_rescue_rename_without_trailing_slash(self) -> None:
        """When {to} lacks a trailing slash, it renames the file instead of appending inside a folder."""
        # 1. Exile destination rename: final.pdf!out/report.pdf -> final.pdf
        rules1 = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("final.pdf!out/report.pdf") or pytest.fail("rule failed"),
        ]
        exc1, arc1, m1 = evaluate_path(PurePosixPath("out/report.pdf"), False, rules1)
        assert not exc1
        assert arc1 == PurePosixPath("final.pdf")
        assert m1 is not None and m1.target == "final.pdf"

        # 2. Subdirectory destination rename: dist/final.pdf!out/report.pdf -> dist/final.pdf
        rules2 = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("dist/final.pdf!out/report.pdf") or pytest.fail("rule failed"),
        ]
        exc2, arc2, m2 = evaluate_path(PurePosixPath("out/report.pdf"), False, rules2)
        assert not exc2
        assert arc2 == PurePosixPath("dist/final.pdf")

        # 3. Archive root rename: /final.pdf!out/report.pdf -> final.pdf
        rules3 = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("/final.pdf!out/report.pdf") or pytest.fail("rule failed"),
        ]
        exc3, arc3, m3 = evaluate_path(PurePosixPath("out/report.pdf"), False, rules3)
        assert not exc3
        assert arc3 == PurePosixPath("final.pdf")

        # 4. Redelete targeting renamed file cancels rescue
        rules4 = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("final.pdf!out/report.pdf") or pytest.fail("rule failed"),
            compile_rule("!final.pdf!out/report.pdf") or pytest.fail("rule failed"),
        ]
        exc4, arc4, m4 = evaluate_path(PurePosixPath("out/report.pdf"), False, rules4)
        assert exc4
        assert arc4 is None
        assert m4 is not None and m4.kind == RuleKind.REDELETE

        # 5. Different extension rename: summary.txt!out/data.log -> summary.txt
        rules5 = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("summary.txt!out/data.log") or pytest.fail("rule failed"),
        ]
        exc5, arc5, m5 = evaluate_path(PurePosixPath("out/data.log"), False, rules5)
        assert not exc5
        assert arc5 == PurePosixPath("summary.txt")
        assert m5 is not None and m5.target == "summary.txt"

        # 6. Extensionless binary rename: app!build/bin -> app
        rules6 = [
            compile_rule("build/") or pytest.fail("rule failed"),
            compile_rule("app!build/bin") or pytest.fail("rule failed"),
        ]
        exc6, arc6, m6 = evaluate_path(PurePosixPath("build/bin"), False, rules6)
        assert not exc6
        assert arc6 == PurePosixPath("app")
        assert m6 is not None and m6.target == "app"

        # 7. Non-slash directory name 'dist' renames file to 'dist'
        rules7 = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("dist!out/report.pdf") or pytest.fail("rule failed"),
        ]
        exc6, arc6, m6 = evaluate_path(PurePosixPath("out/report.pdf"), False, rules7)
        assert not exc6
        assert arc6 == PurePosixPath("dist")
        assert m6 is not None and m6.target == "dist"

        # 8. Redelete targeting 'dist' cancels 'dist!out/report.pdf'
        rules8 = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("dist!out/report.pdf") or pytest.fail("rule failed"),
            compile_rule("!dist!out/report.pdf") or pytest.fail("rule failed"),
        ]
        exc7, arc7, m7 = evaluate_path(PurePosixPath("out/report.pdf"), False, rules8)
        assert exc7
        assert arc7 is None
        assert m7 is not None and m7.kind == RuleKind.REDELETE

    def test_dynamic_template_rename_with_wildcards(self) -> None:
        """When target contains '*' or '$1', wildcards are dynamically expanded without phagocytosis."""
        # 1. Asterisk template expansion: submitted_*.pdf!out/*.pdf
        rules1 = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("submitted_*.pdf!out/*.pdf") or pytest.fail("rule failed"),
        ]
        exc1, arc1, m1 = evaluate_path(PurePosixPath("out/alice.pdf"), False, rules1)
        assert not exc1
        assert arc1 == PurePosixPath("submitted_alice.pdf")
        assert m1 is not None and m1.target == "submitted_*.pdf"

        exc2, arc2, _ = evaluate_path(PurePosixPath("out/bob.pdf"), False, rules1)
        assert not exc2
        assert arc2 == PurePosixPath("submitted_bob.pdf")

        # 2. Numbered capture group $1: v1_$1.bin!dist/*.bin
        rules2 = [
            compile_rule("dist/") or pytest.fail("rule failed"),
            compile_rule("v1_$1.bin!dist/*.bin") or pytest.fail("rule failed"),
        ]
        exc3, arc3, _ = evaluate_path(PurePosixPath("dist/server.bin"), False, rules2)
        assert not exc3
        assert arc3 == PurePosixPath("v1_server.bin")

        # 3. Multiple capture groups $1, $2: archive_$1_$2.csv!data/*_*.csv
        rules3 = [
            compile_rule("data/") or pytest.fail("rule failed"),
            compile_rule("archive_$1_$2.csv!data/*_*.csv") or pytest.fail("rule failed"),
        ]
        exc4, arc4, _ = evaluate_path(PurePosixPath("data/2026_sales.csv"), False, rules3)
        assert not exc4
        assert arc4 == PurePosixPath("archive_2026_sales.csv")

        # 4. Dynamic template with archive root coordinate: /release/pkg_*.tar.gz!dist/*.tar.gz
        rules4 = [
            compile_rule("dist/") or pytest.fail("rule failed"),
            compile_rule("/release/pkg_*.tar.gz!dist/*.tar.gz") or pytest.fail("rule failed"),
        ]
        exc5, arc5, _ = evaluate_path(PurePosixPath("dist/app.tar.gz"), False, rules4)
        assert not exc5
        assert arc5 == PurePosixPath("release/pkg_app.tar.gz")

        # 5. Dynamic template with local scope coordinate: ./backup_*.log!logs/*.log
        rules5 = [
            compile_rule("logs/") or pytest.fail("rule failed"),
            compile_rule("./backup_*.log!logs/*.log") or pytest.fail("rule failed"),
        ]
        exc6, arc6, _ = evaluate_path(PurePosixPath("logs/error.log"), False, rules5)
        assert not exc6
        assert arc6 == PurePosixPath("logs/backup_error.log")


# ==============================================================================
# 3. End-to-End Packaging & Integration Tests
# ==============================================================================
class TestPackagerIntegration:
    """Tests complete ZIP archive creation and verify namelist."""

    def test_dynamic_template_rename_packaging_prevents_phagocytosis(self, tmp_path: Path) -> None:
        """Verifies that dynamic template renaming packages multiple matching files without collision."""
        import zipfile

        source = tmp_path / "project"
        source.mkdir()
        out_dir = source / "out"
        out_dir.mkdir()
        (out_dir / "alice.pdf").write_text("alice content", encoding="utf-8")
        (out_dir / "bob.pdf").write_text("bob content", encoding="utf-8")
        (source / "main.py").write_text("print('hello')", encoding="utf-8")

        zip_out = tmp_path / "archive.zip"
        config = PackagerConfig(
            source=source,
            output=zip_out,
            name="bundle",
            preset_name="none",
            rules=("out/", "submitted_*.pdf!out/*.pdf"),
        )
        packager = ZipPackager(config)
        packager.package()

        assert zip_out.exists()
        with zipfile.ZipFile(zip_out, "r") as zf:
            names = set(zf.namelist())
            assert "bundle/main.py" in names
            assert "bundle/submitted_alice.pdf" in names
            assert "bundle/submitted_bob.pdf" in names
            assert zf.read("bundle/submitted_alice.pdf").decode("utf-8") == "alice content"
            assert zf.read("bundle/submitted_bob.pdf").decode("utf-8") == "bob content"

    def test_full_packaging_with_all_syntax(self, tmp_path: Path) -> None:
        """Verifies full archive creation exercising exclude, exile, keep, remap, re-delete, and lift."""
        source = tmp_path / "project"
        source.mkdir()

        # Setup directory structure
        (source / "out").mkdir()
        (source / "out" / "final.pdf").write_text("final report")
        (source / "out" / "exiled.pdf").write_text("exiled report")
        (source / "out" / "preserved.pdf").write_text("preserved report")
        (source / "out" / "custom.pdf").write_text("custom destination")
        (source / "out" / "draft.pdf").write_text("draft to re-delete")
        (source / "out" / "build.log").write_text("log file")

        (source / "docs").mkdir()
        (source / "docs" / "readme.md").write_text("readme to lift")
        (source / "docs" / "guide.md").write_text("regular guide")

        (source / "src").mkdir()
        (source / "src" / "app.py").write_text("code")

        output_zip = tmp_path / "result.zip"
        config = PackagerConfig(
            source=source,
            output=output_zip,
            name="project",
            preset_name="custom",
            rules=[
                "out/",
                "!out/final.pdf",  # omitted prefix -> floats to exile destination (root)
                "!out/exiled.pdf",  # omitted prefix -> floats to exile destination (root)
                "./!out/preserved.pdf",  # ./! -> preserved inside out/
                "dist/!out/custom.pdf",  # dist/! -> moved to dist/ at exile destination
                "!!out/draft.pdf",  # !! -> re-deleted (excluded)
                "!docs/readme.md",  # ! -> lifted out of docs to root
            ],
            compression=6,
            flat=True,
            force=True,
        )

        packager = ZipPackager(config)
        packager.package()

        assert output_zip.exists()
        with zipfile.ZipFile(output_zip, "r") as zf:
            members = set(zf.namelist())

            # Verified inclusions and exact paths
            assert "final.pdf" in members  # exiled to root
            assert "exiled.pdf" in members  # exiled to root
            assert "out/preserved.pdf" in members  # preserved hierarchy
            assert "dist/custom.pdf" in members  # custom destination
            assert "readme.md" in members  # lifted from docs/
            assert "docs/guide.md" in members  # regular unexcluded
            assert "src/app.py" in members  # regular unexcluded

            # Verified exclusions
            assert "draft.pdf" not in members
            assert "out/draft.pdf" not in members
            assert "out/final.pdf" not in members
            assert "out/exiled.pdf" not in members
            assert "out/build.log" not in members

    def test_preset_inheritance_and_local_squeeze(self, tmp_path: Path) -> None:
        """Tests # inherit: and rule squeeze priority."""
        content = """# inherit: clean, report
# description: Test preset inheritance
*.extra
!!out/unwanted.pdf
"""
        preset_file = tmp_path / "custom.zipignore"
        preset_file.write_text(content, encoding="utf-8")

        model: PresetModel = load_raw_zipignore_preset(preset_file)
        assert model.name == "custom"
        assert model.extends == ["clean", "report"]
        assert "*.extra" in model.rules
        assert "!!out/unwanted.pdf" in model.rules


# ==============================================================================
# 4. 4-Component Pattern Matching & Shorthand Normalization Tests
# ==============================================================================
class TestInterpreterComponents:
    """Direct unit tests for the 4-component pattern matching and 3-tier prefix normalization."""

    def test_parse_components_redelete(self) -> None:
        interpreter = RuleInterpreter()
        # Empty {to} -> !!pattern (cancels exile rescue)
        res_empty = interpreter.parse_components("!!out/draft.pdf")
        assert res_empty == ParsedRule(RuleKind.REDELETE, "", "out/draft.pdf")

        # Specific {to} -> !{to}!pattern
        res_target = interpreter.parse_components("!dist/!out/*.pdf")
        assert res_target == ParsedRule(RuleKind.REDELETE, "dist/", "out/*.pdf")

        res_preserve = interpreter.parse_components("!./!out/draft.pdf")
        assert res_preserve == ParsedRule(RuleKind.REDELETE, "./", "out/draft.pdf")

        res_root = interpreter.parse_components("!/dist/!out/*.pdf")
        assert res_root == ParsedRule(RuleKind.REDELETE, "/dist/", "out/*.pdf")

        # '?' in target is disallowed
        assert interpreter.parse_components("!?/dist!out/*.pdf") is None
        assert interpreter.parse_components("!?/!out/draft.pdf") is None

    def test_parse_components_rescue_and_prefix_normalization(self) -> None:
        interpreter = RuleInterpreter()
        # Omitted {to} -> !pattern (亡命ルート, target='')
        res_shorthand = interpreter.parse_components("!out/*.pdf")
        assert res_shorthand == ParsedRule(RuleKind.RESCUE, "", "out/*.pdf")

        # Explicit destinations
        res_keep = interpreter.parse_components("./!out/*.pdf")
        assert res_keep == ParsedRule(RuleKind.RESCUE, "./", "out/*.pdf")

        res_custom = interpreter.parse_components("dist/!out/*.pdf")
        assert res_custom == ParsedRule(RuleKind.RESCUE, "dist/", "out/*.pdf")

    def test_parse_components_exclude(self) -> None:
        interpreter = RuleInterpreter()
        res = interpreter.parse_components("*.log")
        assert res == ParsedRule(RuleKind.EXCLUDE, "", "*.log")

        res_escaped = interpreter.parse_components(r"\!important.txt")
        assert res_escaped == ParsedRule(RuleKind.EXCLUDE, "", r"\!important.txt")

    def test_glob_expression_unit(self) -> None:
        glob_expr = GlobExpression()
        regex, is_dir_only, has_slash = glob_expr.interpret("out/*.pdf")
        assert is_dir_only is False
        assert has_slash is True
        assert regex.search("out/test.pdf")
        assert not regex.search("other/test.pdf")


# ==============================================================================
# 5. Phagocytosis (貪食) Tests: Path Overlap & Precedence Resolution
# ==============================================================================
class TestPhagocytosis:
    """Verifies that overlapping paths and rule kinds correctly engulf / override each other."""

    def test_hierarchical_rescue_eats_ancestor_exclusion(self) -> None:
        """A descendant directory rescue (!a/b/) eats parent exclusion (a/) for subtree."""
        rules = [
            compile_rule("a/") or pytest.fail("rule failed"),
            compile_rule("!a/b/") or pytest.fail("rule failed"),
        ]
        # a/other.txt is excluded by a/
        exc1, arc1, _ = evaluate_path(PurePosixPath("a/other.txt"), False, rules)
        assert exc1

        # a/b/c/file.txt is rescued because !a/b/ eats a/
        exc2, arc2, r2 = evaluate_path(PurePosixPath("a/b/c/file.txt"), False, rules)
        assert not exc2
        assert arc2 == PurePosixPath("b/c/file.txt")
        assert r2 is not None and r2.kind == RuleKind.RESCUE

    def test_hierarchical_redelete_eats_ancestor_rescue(self) -> None:
        """A sub-descendant redelete (!!a/b/c/) eats prior rescue (!a/b/)."""
        rules = [
            compile_rule("a/") or pytest.fail("rule failed"),
            compile_rule("!a/b/") or pytest.fail("rule failed"),
            compile_rule("!!a/b/c/") or pytest.fail("rule failed"),
        ]
        # a/b/keep.txt is rescued by !a/b/
        exc1, arc1, _ = evaluate_path(PurePosixPath("a/b/keep.txt"), False, rules)
        assert not exc1

        # a/b/c/file.txt is re-deleted by !!a/b/c/
        exc2, arc2, r2 = evaluate_path(PurePosixPath("a/b/c/file.txt"), False, rules)
        assert exc2
        assert r2 is not None and r2.kind == RuleKind.REDELETE

    def test_file_rescue_eats_hierarchical_redelete(self) -> None:
        """File-level rescue (./!a/b/c/file.txt) eats directory re-delete (!!a/b/c/)."""
        rules = [
            compile_rule("a/") or pytest.fail("rule failed"),
            compile_rule("!a/b/") or pytest.fail("rule failed"),
            compile_rule("!!a/b/c/") or pytest.fail("rule failed"),
            compile_rule("./!a/b/c/file.txt") or pytest.fail("rule failed"),
        ]
        exc, arc, r = evaluate_path(PurePosixPath("a/b/c/file.txt"), False, rules)
        assert not exc
        assert arc == PurePosixPath("a/b/c/file.txt")
        assert r is not None and r.kind == RuleKind.RESCUE

    def test_file_exclude_eats_file_rescue(self) -> None:
        """A later EXCLUDE rule eats an earlier RESCUE rule on the same file."""
        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("!out/*.pdf") or pytest.fail("rule failed"),
            compile_rule("draft.pdf") or pytest.fail("rule failed"),
        ]
        # report.pdf remains rescued
        exc1, arc1, _ = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert not exc1

        # draft.pdf is eaten by EXCLUDE
        exc2, arc2, r2 = evaluate_path(PurePosixPath("out/draft.pdf"), False, rules)
        assert exc2
        assert r2 is not None and r2.kind == RuleKind.EXCLUDE

    def test_rescue_destination_phagocytosis(self) -> None:
        """A later RESCUE updates destination, devouring the earlier RESCUE destination."""
        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("dist/!out/*.pdf") or pytest.fail("rule failed"),
            compile_rule("final/!out/*.pdf") or pytest.fail("rule failed"),
        ]
        exc, arc, r = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert not exc
        assert arc == PurePosixPath("final/report.pdf")
        assert r is not None and r.target == "final/"

    def test_targeted_redelete_only_eats_matching_target(self) -> None:
        """!build/!out/*.pdf and !!out/*.pdf do NOT eat dist/!out/*.pdf, but !dist/!out/*.pdf DOES."""
        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("dist/!out/*.pdf") or pytest.fail("rule failed"),
            compile_rule("!build/!out/*.pdf") or pytest.fail("rule failed"),
            compile_rule("!!out/*.pdf") or pytest.fail("rule failed"),
        ]
        exc1, arc1, _ = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert not exc1
        assert arc1 == PurePosixPath("dist/report.pdf")

        rules.append(compile_rule("!dist/!out/*.pdf") or pytest.fail("rule failed"))
        exc2, arc2, r2 = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert exc2
        assert r2 is not None and r2.kind == RuleKind.REDELETE
        assert r2.target == "dist/"

    def test_squeeze_rules_eats_identical_patterns(self) -> None:
        """squeeze_rules compresses rules where later rules eat earlier rules of the same pattern."""
        raw_rules = [
            "*.log",
            "out/",
            "!out/*.pdf",
            "dist/!out/*.pdf",
            "!*.log",
            "!!out/draft.pdf",
        ]
        squeezed = squeeze_rules(raw_rules)
        assert squeezed == ["!*.log", "out/", "dist/!out/*.pdf", "!!out/draft.pdf"]


# ==============================================================================
# 6. Scoped Rules & Hierarchical 4-Tier Evaluation Tests
# ==============================================================================
class TestScopedRules:
    """Verifies subdirectory .zipignore scoping, 4-tier resolution (Preset -> Root -> Subdir -> CLI),
    3-tier destination remapping, and non-greedy pruning.
    """

    def test_discover_sub_zipignores(self, tmp_path: Path) -> None:
        """discover_sub_zipignores should find .zipignore files in subdirectories sorted by depth, ignoring VCS."""
        root = tmp_path / "proj"
        root.mkdir()
        (root / ".zipignore").write_text("*.log\n")

        sub1 = root / "sub1"
        sub1.mkdir()
        (sub1 / ".zipignore").write_text("!special.log\n")

        sub2 = root / "sub1" / "nested"
        sub2.mkdir()
        (sub2 / ".zipignore").write_text("*.tmp\n")

        vcs = root / ".git"
        vcs.mkdir()
        (vcs / ".zipignore").write_text("secret\n")

        found = discover_sub_zipignores(root)
        rel_paths = [str(item[0]) for item in found]
        assert rel_paths == ["sub1", "sub1/nested"]

    def test_scoped_compile_and_squeeze(self) -> None:
        """Rules within different scopes should not eat each other, but same-scope duplicates squeeze."""
        raw = [
            ScopedRule(scope=PurePosixPath(), rule="*.log"),
            ScopedRule(scope=PurePosixPath("sub"), rule="!*.log"),
            ScopedRule(scope=PurePosixPath("sub"), rule="*.log"),
            ScopedRule(scope=PurePosixPath(), rule="!*.log"),
        ]
        squeezed = squeeze_rules(raw)
        assert len(squeezed) == 2
        assert squeezed[0] == ScopedRule(scope=PurePosixPath(), rule="!*.log")
        assert squeezed[1] == ScopedRule(scope=PurePosixPath("sub"), rule="*.log")

    def test_scoped_rule_affects_only_subtree(self) -> None:
        """Subdirectory .zipignore only matches files within its subtree."""
        rule = compile_rule("*.tmp", scope=PurePosixPath("pkg/sub"))
        assert rule is not None

        # Inside subtree -> excluded
        exc1, _, _ = evaluate_path(PurePosixPath("pkg/sub/data.tmp"), False, [rule])
        assert exc1

        exc2, _, _ = evaluate_path(PurePosixPath("pkg/sub/deep/data.tmp"), False, [rule])
        assert exc2

        # Outside subtree -> untouched
        exc3, arc3, _ = evaluate_path(PurePosixPath("pkg/data.tmp"), False, [rule])
        assert not exc3
        assert arc3 == PurePosixPath("pkg/data.tmp")

        exc4, arc4, _ = evaluate_path(PurePosixPath("other/data.tmp"), False, [rule])
        assert not exc4
        assert arc4 == PurePosixPath("other/data.tmp")

    def test_scoped_rule_rescues_from_parent_exclusion(self) -> None:
        """Subdirectory .zipignore can rescue files excluded by a root rule."""
        root_rule = compile_rule("*.log", scope=PurePosixPath())
        sub_rule = compile_rule("!important.log", scope=PurePosixPath("logs"))
        assert root_rule is not None and sub_rule is not None

        rules = [root_rule, sub_rule]

        # Root file matches root rule -> excluded
        exc1, _, _ = evaluate_path(PurePosixPath("app.log"), False, rules)
        assert exc1

        # logs/other.log matches root rule -> excluded
        exc2, _, _ = evaluate_path(PurePosixPath("logs/other.log"), False, rules)
        assert exc2

        # logs/important.log is rescued by scoped rule
        exc3, arc3, matched = evaluate_path(PurePosixPath("logs/important.log"), False, rules)
        assert not exc3
        assert matched is not None and matched.kind == RuleKind.RESCUE

    def test_scoped_rescue_omitted_prefix_exiles_and_dot_slash_preserves_scope(self) -> None:
        """Inside a subdirectory .zipignore, omitted prefix (dist/!*.pdf) exiles to shallowest excluded parent,
        while './dist/!*.txt' places inside that subdirectory's own hierarchy (out/dist/).
        """
        root_rule = compile_rule("a/out/", scope=PurePosixPath())
        sub_exile_rule = compile_rule("dist/!*.pdf", scope=PurePosixPath("a/out"))
        sub_local_rule = compile_rule("./dist/!*.txt", scope=PurePosixPath("a/out"))
        assert root_rule is not None and sub_exile_rule is not None and sub_local_rule is not None

        rules = [root_rule, sub_exile_rule, sub_local_rule]

        # Omitted prefix 'dist/!*.pdf' -> exiled to a/dist/report.pdf (shallowest excluded parent is 'a')
        exc1, arc1, matched1 = evaluate_path(PurePosixPath("a/out/report.pdf"), False, rules)
        assert not exc1
        assert arc1 == PurePosixPath("a/dist/report.pdf")
        assert matched1 is not None and matched1.target == "dist/"

        # './dist/!*.txt' -> kept inside scope at a/out/dist/note.txt
        exc2, arc2, matched2 = evaluate_path(PurePosixPath("a/out/note.txt"), False, rules)
        assert not exc2
        assert arc2 == PurePosixPath("a/out/dist/note.txt")
        assert matched2 is not None and matched2.target == "./dist/"

    def test_scoped_rescue_absolute_destination(self) -> None:
        """Rescue remapping /dist/!*.pdf inside a subdirectory is resolved relative to archive root."""
        root_rule = compile_rule("a/out/", scope=PurePosixPath())
        sub_rule = compile_rule("/dist/!*.pdf", scope=PurePosixPath("a/out"))
        assert root_rule is not None and sub_rule is not None

        rules = [root_rule, sub_rule]

        # Rescued file moves to dist/ (root-relative)
        exc, arc, matched = evaluate_path(PurePosixPath("a/out/report.pdf"), False, rules)
        assert not exc
        assert arc == PurePosixPath("dist/report.pdf")
        assert matched is not None and matched.target == "/dist/"

    def test_scoped_rescue_preserves_hierarchy(self) -> None:
        """Preserve hierarchy ./! inside a subdirectory preserves path from archive root."""
        root_rule = compile_rule("out/", scope=PurePosixPath())
        sub_rule = compile_rule("./!*.pdf", scope=PurePosixPath("out"))
        assert root_rule is not None and sub_rule is not None

        rules = [root_rule, sub_rule]
        exc, arc, _ = evaluate_path(PurePosixPath("out/report.pdf"), False, rules)
        assert not exc
        assert arc == PurePosixPath("out/report.pdf")

    def test_nested_sub_overrides_enclosing_sub(self) -> None:
        """Deeper subdirectory rule overrides shallower enclosing subdirectory rule."""
        shallow_rule = compile_rule("*.tmp", scope=PurePosixPath("a"))
        deep_rule = compile_rule("!keep.tmp", scope=PurePosixPath("a/b"))
        assert shallow_rule is not None and deep_rule is not None

        rules = [shallow_rule, deep_rule]

        # a/test.tmp is excluded by shallow rule
        exc1, _, _ = evaluate_path(PurePosixPath("a/test.tmp"), False, rules)
        assert exc1

        # a/b/test.tmp is excluded by shallow rule
        exc2, _, _ = evaluate_path(PurePosixPath("a/b/test.tmp"), False, rules)
        assert exc2

        # a/b/keep.tmp is rescued by deep rule
        exc3, _, matched = evaluate_path(PurePosixPath("a/b/keep.tmp"), False, rules)
        assert not exc3
        assert matched is not None and matched.kind == RuleKind.RESCUE

    def test_cli_overrides_scoped_rule(self) -> None:
        """CLI arguments (Tier 4) override subdirectory rules (Tier 3)."""
        root_rule = compile_rule("*.log", scope=PurePosixPath())
        sub_rule = compile_rule("!important.log", scope=PurePosixPath("logs"))
        cli_override = compile_rule("logs/important.log", scope=PurePosixPath())
        assert root_rule is not None and sub_rule is not None and cli_override is not None

        rules = [root_rule, sub_rule, cli_override]
        exc, _, matched = evaluate_path(PurePosixPath("logs/important.log"), False, rules)
        assert exc
        assert matched is not None and matched.kind == RuleKind.EXCLUDE

    def test_4_tier_full_packaging_integration(self, tmp_path: Path) -> None:
        """Comprehensive packaging test verifying 4-tier loading and that .zipignore is not archived."""
        source = tmp_path / "project"
        source.mkdir()

        # Preset (Tier 1): will exclude *.zipignore
        # Root .zipignore (Tier 2): excludes temp/
        (source / ".zipignore").write_text("temp/\n*.bak\n")

        # Subdirectory temp/.zipignore (Tier 3): rescues !keep.txt, local ./dist!export.csv, and root /archive!summary.csv
        (source / "temp").mkdir()
        (source / "temp" / ".zipignore").write_text(
            "!keep.txt\n./dist/!export.csv\n/archive/!summary.csv\n"
        )
        (source / "temp" / "keep.txt").write_text("keep me")
        (source / "temp" / "export.csv").write_text("csv data")
        (source / "temp" / "summary.csv").write_text("summary data")
        (source / "temp" / "drop.txt").write_text("do not keep")

        # Subdirectory src/
        (source / "src").mkdir()
        (source / "src" / ".zipignore").write_text("private.py\n")
        (source / "src" / "app.py").write_text("app code")
        (source / "src" / "private.py").write_text("secret")

        # Root file
        (source / "readme.md").write_text("hello")

        # Tier 4: CLI argument excludes readme.md
        tier1 = [ScopedRule(rule="*.zipignore")]
        tier2 = [ScopedRule(rule="temp/"), ScopedRule(rule="*.bak")]
        tier3 = [
            ScopedRule(scope=PurePosixPath("temp"), rule="!keep.txt"),
            ScopedRule(scope=PurePosixPath("temp"), rule="./dist/!export.csv"),
            ScopedRule(scope=PurePosixPath("temp"), rule="/archive/!summary.csv"),
            ScopedRule(scope=PurePosixPath("src"), rule="private.py"),
        ]
        tier4 = [ScopedRule(rule="readme.md")]

        all_rules = squeeze_rules(tier1 + tier2 + tier3 + tier4)

        output_zip = tmp_path / "bundle.zip"
        config = PackagerConfig(
            source=source,
            output=output_zip,
            name="project",
            preset_name="test",
            rules=all_rules,
            flat=True,
            force=True,
        )

        packager = ZipPackager(config)
        packager.package()

        assert output_zip.exists()
        with zipfile.ZipFile(output_zip, "r") as zf:
            members = set(zf.namelist())

            # Verified inclusions
            assert "keep.txt" in members
            assert "temp/dist/export.csv" in members
            assert "archive/summary.csv" in members
            assert "src/app.py" in members

            # Verified exclusions
            assert ".zipignore" not in members
            assert "temp/.zipignore" not in members
            assert "src/.zipignore" not in members
            assert "temp/drop.txt" not in members
            assert "src/private.py" not in members
            assert "readme.md" not in members


# ==============================================================================
# 7. Output Path Resolution & Collision Fallback Tests
# ==============================================================================
class TestOutputPathResolution:
    """Verifies OutputResolver 3-tier path prefix rules, bare -o, and timestamp collision fallback."""

    def test_default_output_path_is_current_directory(self, tmp_path: Path) -> None:
        """When output_target is None and timestamp is False, output defaults to cwd/<name>.zip."""
        source = tmp_path / "some" / "nested" / "my_project"
        cwd = tmp_path / "work"
        cwd.mkdir(parents=True)
        res = resolve_output_path(source, "my_project", None, timestamp=False, cwd=cwd)
        assert res == cwd.resolve() / "my_project.zip"

    def test_output_path_with_timestamp(self, tmp_path: Path) -> None:
        """When timestamp is True, output should have _<YYYYMMDD_HHMMSS>.zip in cwd."""
        source = Path("/tmp/my_project")
        res = resolve_output_path(source, "my_project", None, timestamp=True, cwd=tmp_path)
        assert res.parent == tmp_path.resolve()
        assert res.name.startswith("my_project_")
        assert res.name.endswith(".zip")
        assert len(res.name) > len("my_project_.zip")

    def test_three_tier_prefix_resolution(self, tmp_path: Path) -> None:
        """Verifies / (absolute), ./ (cwd-relative), and bare ___ / empty (source.parent-relative)."""
        parent_dir = tmp_path / "parent"
        source = parent_dir / "src_proj"
        cwd = tmp_path / "current_work"
        source.mkdir(parents=True)
        cwd.mkdir(parents=True)

        # 1. Cwd-relative: ./___
        res_cwd = resolve_output_path(source, "src_proj", "./local_out.zip", cwd=cwd)
        assert res_cwd == cwd.resolve() / "local_out.zip"

        res_cwd_stem = resolve_output_path(source, "src_proj", "./local_stem", cwd=cwd)
        assert res_cwd_stem == cwd.resolve() / "local_stem.zip"

        # 2. Source-parent-relative: ___ and empty "" (bare -o)
        res_parent_bare = resolve_output_path(source, "src_proj", "sibling.zip", cwd=cwd)
        assert res_parent_bare == parent_dir.resolve() / "sibling.zip"

        res_parent_root = resolve_output_path(source, "src_proj", "", cwd=cwd)
        assert res_parent_root == parent_dir.resolve() / "src_proj.zip"

        # 3. Absolute: /___
        abs_target = tmp_path / "abs_out.zip"
        res_abs = resolve_output_path(source, "src_proj", str(abs_target), cwd=cwd)
        assert res_abs == abs_target.resolve()

    def test_output_dir_without_and_with_timestamp(self, tmp_path: Path) -> None:
        """When output is an existing directory, places <name>.zip or <name>_<ts>.zip inside it."""
        source = Path("/tmp/my_project")
        res1 = resolve_output_path(source, "my_project", tmp_path, timestamp=False)
        assert res1 == tmp_path.resolve() / "my_project.zip"

        res2 = resolve_output_path(source, "my_project", tmp_path, timestamp=True)
        assert res2.parent == tmp_path.resolve()
        assert res2.name.startswith("my_project_")
        assert res2.name.endswith(".zip")

    def test_collision_fallback_to_timestamp_when_unspecified_or_directory(
        self, tmp_path: Path
    ) -> None:
        """When <stem>.zip already exists and .zip was not explicitly specified, falls back to -t."""
        source = tmp_path / "my_project"
        source.mkdir()
        (source / "main.py").write_text("print(1)")

        existing_zip = tmp_path / "my_project.zip"
        existing_zip.write_text("old archive")

        # 1. Default (unspecified) in cwd=tmp_path falls back to my_project_<ts>.zip
        resolved = resolve_output_path(
            source, "my_project", None, timestamp=False, force=False, cwd=tmp_path
        )
        assert resolved.parent == tmp_path.resolve()
        assert resolved.name.startswith("my_project_")
        assert resolved.name.endswith(".zip")
        assert resolved != existing_zip.resolve()

        # 2. Directory target (-o tmp_path) also falls back to my_project_<ts>.zip
        resolved_dir = resolve_output_path(
            source, "my_project", str(tmp_path), timestamp=False, force=False, cwd=tmp_path
        )
        assert resolved_dir.name.startswith("my_project_")
        assert resolved_dir != existing_zip.resolve()

        # 3. With force=True, does NOT fall back (overwrites my_project.zip)
        resolved_force = resolve_output_path(
            source, "my_project", None, timestamp=False, force=True, cwd=tmp_path
        )
        assert resolved_force == existing_zip.resolve()

    def test_package_current_directory_excludes_self_and_collided_zip(self, tmp_path: Path) -> None:
        """Packaging source when output is inside source succeeds and skips self archives."""
        source = tmp_path / "proj"
        source.mkdir()
        (source / "app.py").write_text("code")

        # First run: creates proj/proj.zip inside source itself
        out1 = resolve_output_path(source, "proj", None, cwd=source)
        assert out1 == source.resolve() / "proj.zip"
        cfg1 = PackagerConfig(
            source=source, output=out1, name="proj", preset_name="clean", flat=True
        )
        ZipPackager(cfg1).package()
        assert out1.exists()
        with zipfile.ZipFile(out1, "r") as zf:
            assert set(zf.namelist()) == {"app.py"}

        # Second run without -f: collides with proj/proj.zip, falls back to proj/proj_<ts>.zip,
        # and does not include proj.zip inside the new archive!
        out2 = resolve_output_path(source, "proj", None, cwd=source)
        assert out2 != out1
        assert out2.name.startswith("proj_")
        cfg2 = PackagerConfig(
            source=source, output=out2, name="proj", preset_name="clean", flat=True
        )
        ZipPackager(cfg2).package()
        assert out2.exists()
        with zipfile.ZipFile(out2, "r") as zf:
            assert set(zf.namelist()) == {"app.py"}

        # Third run: another archive is created while proj.zip AND proj_<ts>.zip both exist,
        # verifying full dynamic idempotency: neither prior archive (standard or custom timestamp)
        # is engulfed into the new ZIP!
        out3 = source / "proj_custom_arbitrary_timestamp.zip"
        cfg3 = PackagerConfig(
            source=source, output=out3, name="proj", preset_name="clean", flat=True
        )
        ZipPackager(cfg3).package()
        assert out3.exists()
        with zipfile.ZipFile(out3, "r") as zf:
            assert set(zf.namelist()) == {"app.py"}

    def test_bare_o_cli_normalization(self, tmp_path: Path) -> None:
        """Verifies that bare `-o` at end of args or before another flag normalizes to `""`."""
        from typer.testing import CliRunner

        from zipdir.cli import app
        from zipdir.output import OutputResolver

        resolver = OutputResolver()
        assert resolver.normalize_cli_args(["-o"]) == ["-o", ""]
        assert resolver.normalize_cli_args(["report", "-o"]) == ["report", "-o", ""]
        assert resolver.normalize_cli_args(["-o", "-t"]) == ["-o", "", "-t"]
        assert resolver.normalize_cli_args(["-o", "./sub"]) == ["-o", "./sub"]

        source = tmp_path / "sub_proj"
        source.mkdir()
        (source / "hello.txt").write_text("world")

        runner = CliRunner()
        result = runner.invoke(app, [str(source), "-o"])
        assert result.exit_code == 0
        expected_zip = tmp_path / "sub_proj.zip"
        assert expected_zip.exists()

    def test_explicit_output_filename_ignores_timestamp_and_does_not_fallback(
        self, tmp_path: Path
    ) -> None:
        """Explicit .zip output file target preserves filename and raises FileExistsError on collision."""
        source = tmp_path / "my_project"
        source.mkdir()
        (source / "file.txt").write_text("hello")
        explicit_target = tmp_path / "custom_archive.zip"
        explicit_target.write_text("existing")
        expected = explicit_target.parent.resolve() / explicit_target.name
        res1 = resolve_output_path(source, "my_project", explicit_target, timestamp=False)
        assert res1 == expected
        res2 = resolve_output_path(source, "my_project", explicit_target, timestamp=True)
        config = PackagerConfig(
            source=source,
            output=res1,
            name="my_project",
            preset_name="clean",
            force=False,
        )
        with pytest.raises(FileExistsError):
            ZipPackager(config).package()
        assert res2 == expected


# ==============================================================================
# 8. 3-Tier Prefix Coordinates, Scoped Inheritance & Phagocytosis Tests
# ==============================================================================
class TestAnalogicalCoordinateAndCascade:
    """Verifies 3-tier remap coordinates (omitted, ./{to}, ../../{to}), target-aware squeezing,
    recursive LEGB scoped inheritance (# inherit: / # include:), and archive member phagocytosis.
    """

    def test_three_tier_remap_coordinates(self) -> None:
        """Verifies omitted (exile), ./{to}!, and multi-level ../../{to}! coordinate remapping."""
        # 1. Omitted prefix (exile destination relative): dist/!a/b/out/*.pdf -> a/b/dist/report.pdf
        rules_exile = [
            compile_rule("a/b/out/") or pytest.fail("rule failed"),
            compile_rule("dist/!a/b/out/*.pdf") or pytest.fail("rule failed"),
        ]
        exc1, arc1, _ = evaluate_path(PurePosixPath("a/b/out/report.pdf"), False, rules_exile)
        assert not exc1
        assert arc1 == PurePosixPath("a/b/dist/report.pdf")

        # 2. Hierarchy-preserving coordinate with subpath: ./published/!a/b/out/*.pdf -> a/b/out/published/report.pdf
        rules_preserve = [
            compile_rule("a/b/out/") or pytest.fail("rule failed"),
            compile_rule("./published/!a/b/out/*.pdf") or pytest.fail("rule failed"),
        ]
        exc2, arc2, _ = evaluate_path(PurePosixPath("a/b/out/report.pdf"), False, rules_preserve)
        assert not exc2
        assert arc2 == PurePosixPath("a/b/out/published/report.pdf")

        # 3. Multi-level parent climbing coordinate: ../../bundle/!a/b/c/out/*.pdf -> a/bundle/report.pdf
        rules_climb = [
            compile_rule("a/b/c/out/") or pytest.fail("rule failed"),
            compile_rule("../../bundle/!a/b/c/out/*.pdf") or pytest.fail("rule failed"),
        ]
        exc3, arc3, _ = evaluate_path(PurePosixPath("a/b/c/out/report.pdf"), False, rules_climb)
        assert not exc3
        assert arc3 == PurePosixPath("a/bundle/report.pdf")

    def test_target_aware_compile_time_squeezer_isomorphism(self) -> None:
        """Targeted REDELETE (!build/!out/*.pdf or !!out/*.pdf) does not eat mismatched RESCUE (dist/!out/*.pdf) during squeeze."""
        raw_non_matching = [
            "out/",
            "dist/!out/*.pdf",
            "!build/!out/*.pdf",
            "!!out/*.pdf",
        ]
        squeezed_non_matching = squeeze_rules(raw_non_matching)
        assert "dist/!out/*.pdf" in squeezed_non_matching
        compiled = RuleInterpreter().compile_all(raw_non_matching, squeeze=True)
        exc1, arc1, _ = evaluate_path(PurePosixPath("out/report.pdf"), False, compiled)
        assert not exc1
        assert arc1 == PurePosixPath("dist/report.pdf")

        # Matching targeted REDELETE (!dist/!out/*.pdf) eats dist/!out/*.pdf
        raw_matching = [
            "out/",
            "dist/!out/*.pdf",
            "!dist/!out/*.pdf",
        ]
        squeezed_matching = squeeze_rules(raw_matching)
        assert squeezed_matching == ["out/", "!dist/!out/*.pdf"]
        compiled_match = RuleInterpreter().compile_all(raw_matching, squeeze=True)
        exc2, arc2, _ = evaluate_path(PurePosixPath("out/report.pdf"), False, compiled_match)
        assert exc2
        assert arc2 is None

    def test_scoped_subdir_inheritance_and_relative_ignore_include(self, tmp_path: Path) -> None:
        """Subdirectory .zipignore supports # inherit: <preset> and # include: <relative_file> within its scope."""
        from zipdir.presets import PresetCatalog

        source = tmp_path / "workspace"
        source.mkdir()
        (source / ".gitignore").write_text("*.secret\n", encoding="utf-8")
        (source / ".zipignore").write_text("# include: .gitignore\n", encoding="utf-8")
        (source / "root.secret").write_text("hidden")
        (source / "readme.md").write_text("visible")

        # Subdirectory module inheriting 'report' preset and a local .gitignore
        mod = source / "module_a"
        mod.mkdir()
        (mod / ".gitignore").write_text("*.local_tmp\n", encoding="utf-8")
        (mod / ".zipignore").write_text(
            "# inherit: report, .gitignore\n",
            encoding="utf-8",
        )
        (mod / "out").mkdir()
        (mod / "out" / "paper.pdf").write_text("pdf content")
        (mod / "out" / "paper.aux").write_text("aux content")
        (mod / "scratch.local_tmp").write_text("temp")
        (mod / "code.py").write_text("print(1)")

        catalog = PresetCatalog()
        preset_name, cascade_rules = catalog.resolve_cascade(source)
        output_zip = tmp_path / "workspace.zip"
        config = PackagerConfig(
            source=source,
            output=output_zip,
            name="workspace",
            preset_name=preset_name,
            rules=cascade_rules,
            flat=True,
            force=True,
        )
        ZipPackager(config).package()

        with zipfile.ZipFile(output_zip, "r") as zf:
            members = set(zf.namelist())
            assert "readme.md" in members
            assert "root.secret" not in members
            assert "module_a/code.py" in members
            assert "module_a/paper.pdf" in members
            assert "module_a/out/paper.aux" not in members
            assert "module_a/scratch.local_tmp" not in members

    def test_archive_member_phagocytosis_on_arcname_collision(self, tmp_path: Path) -> None:
        """When multiple files map to the same archive path, later/rescued member replaces earlier one without duplicate ZIP entries."""
        source = tmp_path / "proj"
        source.mkdir()
        (source / "report.pdf").write_text("old root version")
        (source / "out").mkdir()
        (source / "out" / "report.pdf").write_text("new built version")

        output_zip = tmp_path / "out.zip"
        config = PackagerConfig(
            source=source,
            output=output_zip,
            name="proj",
            preset_name="report",
            rules=["out/", "!out/*.pdf"],
            flat=True,
            force=True,
        )
        ZipPackager(config).package()

        with zipfile.ZipFile(output_zip, "r") as zf:
            names = zf.namelist()
            assert names.count("report.pdf") == 1
            assert zf.read("report.pdf").decode("utf-8") == "new built version"

    def test_c3_linearization_diamond_inheritance(self, tmp_path: Path) -> None:
        """Verifies C3 superclass linearization on diamond preset inheritance (A -> {B, C} -> D).

        In a diamond hierarchy where A excludes '*.log', B rescues '!*.log', and C (also extending A)
        excludes '*.tmp', naive depth-first resolution of '# inherit: B, C' would re-apply A's '*.log'
        after B and clobber '!*.log'. C3 linearization resolves the order as [A, B, C, D], preserving B's rescue.
        """
        from zipdir.presets import PresetCatalog

        preset_dir = tmp_path / "presets"
        preset_dir.mkdir()
        (preset_dir / "base_a.zipignore").write_text(
            "# description: Base A\n*.log\n",
            encoding="utf-8",
        )
        (preset_dir / "left_b.zipignore").write_text(
            "# inherit: base_a\n!*.log\n",
            encoding="utf-8",
        )
        (preset_dir / "right_c.zipignore").write_text(
            "# inherit: base_a\n*.tmp\n",
            encoding="utf-8",
        )
        (preset_dir / "diamond_d.zipignore").write_text(
            "# inherit: left_b, right_c\n*.bak\n",
            encoding="utf-8",
        )

        catalog = PresetCatalog(preset_dirs=[preset_dir])
        raw = catalog._discover_raw_presets()
        assert catalog.linearize_presets("diamond_d", raw) == [
            "base_a",
            "left_b",
            "right_c",
            "diamond_d",
        ]

        loaded = catalog.load_all()
        assert loaded["diamond_d"].rules == ["!*.log", "*.tmp", "*.bak"]

    def test_c3_linearization_inconsistent_hierarchy_warns_and_falls_back(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verifies that C3 linearization emits a warning and provisionally resolves contradictory parent orders."""
        from zipdir.presets import PresetCatalog

        catalog = PresetCatalog(preset_dirs=[])
        raw = {
            "a": PresetModel(name="a", rules=["*.a"]),
            "b": PresetModel(name="b", rules=["*.b"]),
            "x": PresetModel(name="x", extends=["a", "b"], rules=[]),
            "y": PresetModel(name="y", extends=["b", "a"], rules=[]),
            "z": PresetModel(name="z", extends=["x", "y"], rules=[]),
        }
        order = catalog.linearize_presets("z", raw)
        captured = capsys.readouterr()
        assert "warning: C3 linearization conflict" in captured.err
        assert order[-1] == "z"
        assert set(order) == {"a", "b", "x", "y", "z"}


# ==============================================================================
# 11. Standalone Rule Bundle Tests (--dump-rules / --freeze-rules)
# ==============================================================================
class TestRuleBundle:
    """Verifies standalone rule bundle dumping (--dump-rules) and freezing (--freeze-rules)."""

    def test_flatten_scoped_rule_variations(self) -> None:
        """Verifies converting ScopedRule into root-level .zipignore representation."""
        from zipdir.models import ScopedRule
        from zipdir.presets import flatten_scoped_rule

        # Root-level scoped rules remain untouched
        assert flatten_scoped_rule(ScopedRule(scope=PurePosixPath("."), rule="*.pyc")) == "*.pyc"
        assert flatten_scoped_rule(ScopedRule(scope=PurePosixPath(""), rule="out/")) == "out/"

        # Subdirectory excludes
        assert (
            flatten_scoped_rule(ScopedRule(scope=PurePosixPath("client"), rule="dist/"))
            == "client/dist/"
        )
        assert (
            flatten_scoped_rule(ScopedRule(scope=PurePosixPath("client"), rule="*.map"))
            == "client/**/*.map"
        )

        # Subdirectory rescues
        assert (
            flatten_scoped_rule(ScopedRule(scope=PurePosixPath("client"), rule="!out/*.pdf"))
            == "!client/out/*.pdf"
        )
        assert (
            flatten_scoped_rule(ScopedRule(scope=PurePosixPath("client"), rule="bundle/!out/*.pdf"))
            == "client/bundle/!client/out/*.pdf"
        )
        assert (
            flatten_scoped_rule(ScopedRule(scope=PurePosixPath("client"), rule="/dist/!out/*.pdf"))
            == "/dist/!client/out/*.pdf"
        )
        assert (
            flatten_scoped_rule(
                ScopedRule(scope=PurePosixPath("client"), rule="final.pdf!out/report.pdf")
            )
            == "client/final.pdf!client/out/report.pdf"
        )
        assert (
            flatten_scoped_rule(ScopedRule(scope=PurePosixPath("client"), rule="!!out/*.pdf"))
            == "!!client/out/*.pdf"
        )

    def test_format_bundle_header_and_rules(self) -> None:
        """Verifies bundle text headers and sequential rule listing."""
        from zipdir.models import ScopedRule
        from zipdir.presets import PresetCatalog

        catalog = PresetCatalog()
        rules = [
            ScopedRule(scope=PurePosixPath("."), rule="*.pyc"),
            ScopedRule(scope=PurePosixPath("sub"), rule="build/"),
            "custom_rule.log",
        ]
        text = catalog.format_bundle("testapp", "clean", rules)
        assert "# .zipignore: self-contained rule bundle for 'testapp'" in text
        assert "# base-preset: clean" in text
        assert "*.pyc" in text
        assert "sub/build/" in text
        assert "custom_rule.log" in text

    def test_cli_dump_rules_prints_to_stdout_and_exits(self, tmp_path: Path) -> None:
        """Verifies --dump-rules prints self-contained .zipignore without creating ZIP archive."""
        from typer.testing import CliRunner

        from zipdir.cli import app

        source = tmp_path / "app"
        source.mkdir()
        (source / "data.txt").write_text("content")

        runner = CliRunner()
        result = runner.invoke(
            app, [str(source), "--dump-rules", "-p", "clean", "-r", "!extra/*.pdf"]
        )
        assert result.exit_code == 0
        assert "# .zipignore: self-contained rule bundle for 'app'" in result.stdout
        assert "# base-preset: clean" in result.stdout
        assert "!extra/*.pdf" in result.stdout

        # Verify no zip file created
        zip_candidates = list(tmp_path.glob("*.zip"))
        assert len(zip_candidates) == 0

    def test_cli_freeze_rules_writes_to_source_zipignore(self, tmp_path: Path) -> None:
        """Verifies --freeze-rules creates <source>/.zipignore with complete resolved rules."""
        from typer.testing import CliRunner

        from zipdir.cli import app

        source = tmp_path / "frozen_proj"
        source.mkdir()
        (source / "main.py").write_text("print('hello')")

        runner = CliRunner()
        result = runner.invoke(
            app, [str(source), "--freeze-rules", "-p", "clean", "-r", "frozen_test/"]
        )
        assert result.exit_code == 0
        assert "Frozen" in result.stdout

        target_file = source / ".zipignore"
        assert target_file.is_file()
        content = target_file.read_text(encoding="utf-8")
        assert "# .zipignore: self-contained rule bundle for 'frozen_proj'" in content
        assert "frozen_test/" in content


# ==============================================================================
# 12. Rule Evaluation Diagnostic Tests (--explain)
# ==============================================================================
class TestRuleExplanation:
    """Verifies diagnostic tracing and explainability of rule evaluation."""

    def test_explain_ancestor_and_target_transitions(self) -> None:
        """Verifies step-by-step recording of ancestor exclusion and target rescue."""
        from zipdir import PathEvaluator, RuleKind, compile_rule

        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("submitted_*.pdf!out/*.pdf") or pytest.fail("rule failed"),
        ]
        evaluator = PathEvaluator(rules)
        exp = evaluator.explain(PurePosixPath("out/alice.pdf"))

        assert exp.rel_path == PurePosixPath("out/alice.pdf")
        assert not exp.is_dir
        assert len(exp.steps) == 2

        # Step 1: ancestor out excluded
        assert exp.steps[0].is_ancestor
        assert exp.steps[0].target == PurePosixPath("out")
        assert exp.steps[0].kind == RuleKind.EXCLUDE
        assert exp.steps[0].is_excluded_after
        assert exp.steps[0].shallowest_excluded_ancestor == PurePosixPath("out")

        # Step 2: target out/alice.pdf rescued
        assert not exp.steps[1].is_ancestor
        assert exp.steps[1].target == PurePosixPath("out/alice.pdf")
        assert exp.steps[1].kind == RuleKind.RESCUE
        assert not exp.steps[1].is_excluded_after

        # Final result
        assert not exp.result.is_excluded
        assert exp.result.arc_path == PurePosixPath("submitted_alice.pdf")

    def test_explain_excluded_without_rescue(self) -> None:
        """Verifies trace for purely excluded file."""
        from zipdir import PathEvaluator, compile_rule

        rules = [compile_rule("*.o") or pytest.fail("rule failed")]
        evaluator = PathEvaluator(rules)
        exp = evaluator.explain(PurePosixPath("build/main.o"))

        assert exp.result.is_excluded
        assert exp.result.arc_path is None
        assert len(exp.steps) == 1
        assert exp.steps[0].kind.name == "EXCLUDE"

    def test_explain_no_matching_rules(self) -> None:
        """Verifies trace when no rules match path."""
        from zipdir import PathEvaluator, compile_rule

        rules = [compile_rule("*.tmp") or pytest.fail("rule failed")]
        evaluator = PathEvaluator(rules)
        exp = evaluator.explain(PurePosixPath("main.py"))

        assert len(exp.steps) == 0
        assert not exp.result.is_excluded
        assert exp.result.arc_path == PurePosixPath("main.py")

    def test_cli_explain_option_prints_diagnostic_and_exits(self, tmp_path: Path) -> None:
        """Verifies --explain prints diagnostic trace and skips ZIP creation."""
        from typer.testing import CliRunner

        from zipdir.cli import app

        source = tmp_path / "diag_proj"
        source.mkdir()
        out_dir = source / "out"
        out_dir.mkdir()
        (out_dir / "alice.pdf").write_text("dummy")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                str(source),
                "--explain",
                "out/alice.pdf",
                "-r",
                "out/",
                "-r",
                "submitted_*.pdf!out/*.pdf",
            ],
        )

        assert result.exit_code == 0
        assert "Rule Evaluation Diagnostic" in result.stdout
        assert "out/alice.pdf" in result.stdout
        assert "Transition Trace:" in result.stdout
        assert "Final Decision:" in result.stdout
        assert "INCLUDED" in result.stdout

        # Verify no zip file created
        zip_candidates = list(tmp_path.glob("*.zip"))
        assert len(zip_candidates) == 0


# ==============================================================================
# 13. Archive Constraint Guard Tests (--max-size, --check-empty, --strict-rescue)
# ==============================================================================
class TestArchiveConstraints:
    """Verifies pre-flight and post-flight submission constraints and guards."""

    def test_parse_size_units_and_errors(self) -> None:
        """Verifies parsing human-readable size strings into byte values."""
        from zipdir.models import parse_size

        assert parse_size("1024") == 1024
        assert parse_size("1024B") == 1024
        assert parse_size("500KB") == 500 * 1024
        assert parse_size("500k") == 500 * 1024
        assert parse_size("10MB") == 10 * 1024 * 1024
        assert parse_size("10M") == 10 * 1024 * 1024
        assert parse_size("1.5GB") == int(1.5 * 1024 * 1024 * 1024)
        assert parse_size("1G") == 1024 * 1024 * 1024

        with pytest.raises(ValueError, match="Invalid size string"):
            parse_size("invalid")
        with pytest.raises(ValueError, match="Unknown size unit"):
            parse_size("10XB")

    def test_check_empty_raises_when_no_files_collected(self, tmp_path: Path) -> None:
        """Verifies --check-empty raises ValueError when archive contains 0 regular files."""
        source = tmp_path / "empty_proj"
        source.mkdir()
        (source / "ignore.log").write_text("test")

        out_zip = tmp_path / "out.zip"
        config = PackagerConfig(
            source=source,
            output=out_zip,
            name="empty_test",
            preset_name="none",
            rules=("*.log",),
            check_empty=True,
        )
        packager = ZipPackager(config)
        with pytest.raises(ValueError, match="Archive constraint violation \\(--check-empty\\)"):
            packager.package()

        assert not out_zip.exists()

    def test_strict_rescue_raises_when_rescue_rule_matches_zero_files(self, tmp_path: Path) -> None:
        """Verifies --strict-rescue raises ValueError when configured rescue rules rescue 0 files."""
        source = tmp_path / "strict_proj"
        source.mkdir()
        (source / "main.py").write_text("print('hello')")

        out_zip = tmp_path / "out.zip"
        config = PackagerConfig(
            source=source,
            output=out_zip,
            name="strict_test",
            preset_name="none",
            rules=("out/", "!out/*.pdf"),
            strict_rescue=True,
        )
        packager = ZipPackager(config)
        with pytest.raises(ValueError, match="Archive constraint violation \\(--strict-rescue\\)"):
            packager.package()

        assert not out_zip.exists()

    def test_strict_rescue_succeeds_when_files_rescued(self, tmp_path: Path) -> None:
        """Verifies --strict-rescue succeeds when at least one file is rescued."""
        source = tmp_path / "strict_ok_proj"
        source.mkdir()
        out_dir = source / "out"
        out_dir.mkdir()
        (out_dir / "report.pdf").write_text("pdf content")

        out_zip = tmp_path / "out.zip"
        config = PackagerConfig(
            source=source,
            output=out_zip,
            name="strict_ok",
            preset_name="none",
            rules=("out/", "!out/*.pdf"),
            strict_rescue=True,
        )
        packager = ZipPackager(config)
        result = packager.package()
        assert result.exists()

    def test_max_size_raises_and_unlinks_when_exceeded(self, tmp_path: Path) -> None:
        """Verifies --max-size unlinks output and raises ValueError when size threshold is exceeded."""
        source = tmp_path / "big_proj"
        source.mkdir()
        (source / "large.bin").write_bytes(b"A" * 5000)

        out_zip = tmp_path / "out.zip"
        config = PackagerConfig(
            source=source,
            output=out_zip,
            name="big_test",
            preset_name="none",
            compression=0,
            max_size=1000,
        )
        packager = ZipPackager(config)
        with pytest.raises(ValueError, match="Archive constraint violation \\(--max-size\\)"):
            packager.package()

        assert not out_zip.exists()

    def test_cli_constraints_options(self, tmp_path: Path) -> None:
        """Verifies CLI flags for --check-empty, --strict-rescue, and --max-size via CliRunner."""
        from typer.testing import CliRunner

        from zipdir.cli import app

        source = tmp_path / "cli_proj"
        source.mkdir()
        (source / "file.txt").write_text("content")

        runner = CliRunner()

        # 1. --check-empty failure
        res_empty = runner.invoke(app, [str(source), "--check-empty", "-r", "*.txt"])
        assert res_empty.exit_code == 1
        assert "Archive constraint violation (--check-empty)" in res_empty.stderr

        # 2. --strict-rescue failure
        res_strict = runner.invoke(app, [str(source), "--strict-rescue", "-r", "!missing/*.pdf"])
        assert res_strict.exit_code == 1
        assert "Archive constraint violation (--strict-rescue)" in res_strict.stderr

        # 3. --max-size failure
        res_size = runner.invoke(app, [str(source), "--max-size", "10B", "-f"])
        assert res_size.exit_code == 1
        assert "Archive constraint violation (--max-size)" in res_size.stderr


# ==============================================================================
# 14. Brace Expansion Tests ({a,b,c})
# ==============================================================================
class TestBraceExpansion:
    """Verifies comma-separated brace expansion patterns in .zipignore rules."""

    def test_brace_expansion_multiple_extensions(self) -> None:
        """Verifies *.{jpg,png,webp} matches all specified extensions and excludes others."""
        from zipdir import compile_rule, evaluate_path

        rule = compile_rule("*.{jpg,png,webp}") or pytest.fail("rule failed")
        rules = [rule]

        # Matched extensions
        exc_jpg, _, _ = evaluate_path(PurePosixPath("photo.jpg"), False, rules)
        assert exc_jpg

        exc_png, _, _ = evaluate_path(PurePosixPath("image.png"), False, rules)
        assert exc_png

        exc_webp, _, _ = evaluate_path(PurePosixPath("banner.webp"), False, rules)
        assert exc_webp

        # Unmatched extension
        exc_gif, arc_gif, _ = evaluate_path(PurePosixPath("animation.gif"), False, rules)
        assert not exc_gif
        assert arc_gif == PurePosixPath("animation.gif")

    def test_brace_expansion_directory_paths(self) -> None:
        """Verifies path segments with braces: src/{client,server}/**/*.py."""
        from zipdir import compile_rule, evaluate_path

        rule = compile_rule("src/{client,server}/**/*.py") or pytest.fail("rule failed")
        rules = [rule]

        exc_client, _, _ = evaluate_path(
            PurePosixPath("src/client/components/app.py"), False, rules
        )
        assert exc_client

        exc_server, _, _ = evaluate_path(PurePosixPath("src/server/api.py"), False, rules)
        assert exc_server

        exc_common, arc_common, _ = evaluate_path(PurePosixPath("src/common/util.py"), False, rules)
        assert not exc_common
        assert arc_common == PurePosixPath("src/common/util.py")

    def test_brace_expansion_multiple_braces_in_rule(self) -> None:
        """Verifies multiple brace expansions in single pattern: {src,test}/**/*.{js,ts}."""
        from zipdir import compile_rule, evaluate_path

        rule = compile_rule("{src,test}/**/*.{js,ts}") or pytest.fail("rule failed")
        rules = [rule]

        assert evaluate_path(PurePosixPath("src/app.js"), False, rules)[0]
        assert evaluate_path(PurePosixPath("src/sub/app.ts"), False, rules)[0]
        assert evaluate_path(PurePosixPath("test/unit.js"), False, rules)[0]
        assert evaluate_path(PurePosixPath("test/e2e/test.ts"), False, rules)[0]

        # Other extensions / directories
        assert not evaluate_path(PurePosixPath("src/app.css"), False, rules)[0]
        assert not evaluate_path(PurePosixPath("docs/readme.js"), False, rules)[0]

    def test_brace_expansion_empty_alternative(self) -> None:
        """Verifies empty alternative in braces: file.{txt,} matches file.txt and file.."""
        from zipdir import compile_rule, evaluate_path

        rule = compile_rule("file.{txt,}") or pytest.fail("rule failed")
        rules = [rule]

        assert evaluate_path(PurePosixPath("file.txt"), False, rules)[0]
        assert evaluate_path(PurePosixPath("file."), False, rules)[0]
        assert not evaluate_path(PurePosixPath("file.doc"), False, rules)[0]

    def test_single_brace_without_comma_treated_as_literal(self) -> None:
        """Verifies {single} without comma is treated as literal text, matching shell semantics."""
        from zipdir import compile_rule, evaluate_path

        rule = compile_rule("file.{single}") or pytest.fail("rule failed")
        rules = [rule]

        assert evaluate_path(PurePosixPath("file.{single}"), False, rules)[0]
        assert not evaluate_path(PurePosixPath("file.single"), False, rules)[0]

    def test_escaped_brace_treated_as_literal(self) -> None:
        r"""Verifies \{a,b\} matches literal {a,b}."""
        from zipdir import compile_rule, evaluate_path

        rule = compile_rule(r"file.\{jpg,png\}") or pytest.fail("rule failed")
        rules = [rule]

        assert evaluate_path(PurePosixPath("file.{jpg,png}"), False, rules)[0]
        assert not evaluate_path(PurePosixPath("file.jpg"), False, rules)[0]

    def test_brace_expansion_with_rescue_and_remap(self) -> None:
        """Verifies rescue rules with braces: !out/*.{jpg,png} rescues both types."""
        from zipdir import compile_rule, evaluate_path

        rules = [
            compile_rule("out/") or pytest.fail("rule failed"),
            compile_rule("!out/*.{jpg,png}") or pytest.fail("rule failed"),
        ]

        exc1, arc1, m1 = evaluate_path(PurePosixPath("out/photo.jpg"), False, rules)
        assert not exc1
        assert arc1 == PurePosixPath("photo.jpg")

        exc2, arc2, m2 = evaluate_path(PurePosixPath("out/logo.png"), False, rules)
        assert not exc2
        assert arc2 == PurePosixPath("logo.png")

        # Unrescued
        exc3, _, _ = evaluate_path(PurePosixPath("out/data.csv"), False, rules)
        assert exc3
