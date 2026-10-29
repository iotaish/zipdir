"""Command Line Interface and Composition Root wiring for zipdir."""

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import typer
from typer._click.core import Context as ClickContext
from typer.core import TyperCommand

from zipdir.models import PackagerConfig, PresetModel
from zipdir.output import OutputResolver, resolve_output_path
from zipdir.packager import ZipPackager
from zipdir.presets import PresetCatalog
from zipdir.ui import ConsoleReporter, color_yellow


class ZipdirCommand(TyperCommand):
    """Custom Typer command that normalizes bare `-o` / `--output` flags to `""` (source.parent)."""

    def parse_args(self, ctx: ClickContext, args: list[str]) -> list[str]:
        resolver = OutputResolver()
        normalized = resolver.normalize_cli_args(args)
        return super().parse_args(ctx, normalized)


app = typer.Typer(
    name="zipdir",
    help="Package a directory into a clean ZIP archive with .zipignore rules and smart path remapping.",
    add_completion=False,
    no_args_is_help=False,
)


def print_presets(
    presets: Mapping[str, PresetModel],
    reporter: ConsoleReporter | None = None,
) -> None:
    """Display available presets and their configurations."""
    active_reporter = reporter if reporter is not None else ConsoleReporter()
    active_reporter.print_presets(presets)


@app.command(
    cls=ZipdirCommand,
    epilog="""\
Output path resolution (-o / positional output):
  - (omitted)            # Current directory: ./<name>.zip
  - '-o' (no value)      # Source parent directory: <source.parent>/<name>.zip
  - '-o ./___'           # Current directory relative: ./___
  - '-o ___'             # Source parent relative: <source.parent>/___
  - '-o /___', '-o ~/___'# Absolute path
  * When output is omitted or specifies a directory/stem without '.zip', existing files
    automatically fall back to <stem>_<YYYYMMDD_HHMMSS>.zip (unless -f is set).
  * When an explicit '.zip' filename is given, no fallback occurs (raises error unless -f).

Rule syntax (.zipignore):
  - 'out/'               # Exclude out/ directory
  - '!out/*.pdf'         # Rescue out/*.pdf and lift to exile destination (shallowest excluded parent)
  - '{to}/!out/*.pdf'    # Rescue and move to directory {to}/ relative to exile destination (e.g. 'dist/!out/*.pdf')
  - '{name}!out/file'    # Rescue and rename file to {name} at exile destination (e.g. 'final.pdf!out/report.pdf')
  - '{pattern}!out/*.ext'# Rescue and dynamically rename via '*' or '$1' (e.g. 'submitted_*.pdf!out/*.pdf')
  - './!out/*.pdf'       # Rescue out/*.pdf keeping original directory hierarchy (階層死守)
  - './{to}/!out/*.pdf'  # Rescue and move to {to}/ relative to original hierarchy / local scope
  - '/{to}/!out/*.pdf'   # Rescue and move to {to}/ relative to archive root
  - '!!out/*.pdf'        # Re-delete item rescued via '!out/*.pdf'
  - '!{to}!out/*.pdf'    # Re-delete item rescued targeting {to} (e.g. '!dist/!out/*.pdf', '!./!out/*.pdf')
""",
)
def package(
    directory: Annotated[
        str | None,
        typer.Argument(help="Target directory to package (default: current directory '.')"),
    ] = None,
    output_path: Annotated[
        str | None,
        typer.Argument(help="Optional ZIP output path (positional alternative to -o)"),
    ] = None,
    preset: Annotated[
        str | None,
        typer.Option(
            "-p",
            "--preset",
            help="Packaging preset name or .zipignore path (defaults to 'clean' or local .zipignore inherit)",
        ),
    ] = None,
    list_presets: Annotated[
        bool,
        typer.Option("--list-presets", help="List all available presets and exit"),
    ] = False,
    rule: Annotated[
        list[str] | None,
        typer.Option(
            "-r",
            "--rule",
            "-x",
            "--exclude",
            help="Additional .zipignore rules (exclude, rescue !, re-delete !!, rename target!source); repeatable",
        ),
    ] = None,
    no_default_rules: Annotated[
        bool,
        typer.Option(
            "--no-default-rules",
            "--no-default-excludes",
            help="Ignore preset rules",
        ),
    ] = False,
    output: Annotated[
        str | None,
        typer.Option(
            "-o",
            "--output",
            help="Output path: ./___ (cwd), ___ or bare -o (source.parent), /___ or ~/___ (abs)",
        ),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Archive root directory name and default filename prefix"),
    ] = None,
    timestamp: Annotated[
        bool,
        typer.Option(
            "-t",
            "--timestamp",
            help="Append timestamp to output filename (e.g. <name>_<timestamp>.zip; default: False)",
        ),
    ] = False,
    flat: Annotated[
        bool,
        typer.Option("--flat", help="Omit enclosing top-level directory in ZIP"),
    ] = False,
    compression: Annotated[
        int,
        typer.Option(
            "--compression",
            min=0,
            max=9,
            help="ZIP compression level (0=store, 1..9=deflate; default: 6)",
        ),
    ] = 6,
    force: Annotated[
        bool,
        typer.Option("-f", "--force", help="Overwrite output file if it already exists"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Print details of rescued and excluded items"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show resulting members without creating ZIP"),
    ] = False,
    dump_rules: Annotated[
        bool,
        typer.Option(
            "--dump-rules",
            help="Dump resolved, linearized, and squeezed rules as standalone .zipignore to stdout and exit",
        ),
    ] = False,
    freeze_rules: Annotated[
        bool,
        typer.Option(
            "--freeze-rules",
            help="Freeze resolved rules directly into <source>/.zipignore and exit",
        ),
    ] = False,
) -> None:
    catalog = PresetCatalog()
    reporter = ConsoleReporter()
    presets = catalog.load_all()

    if list_presets:
        reporter.print_presets(presets)
        return

    target_dir_str, target_out_arg = _resolve_cli_targets(directory, output_path, output)
    source = _validate_source_dir(target_dir_str)
    archive_name = _validate_archive_name(name, source)

    try:
        effective_preset_name, combined_rules = catalog.resolve_cascade(
            source,
            presets,
            preset=preset,
            cli_rules=rule or (),
            no_default_rules=no_default_rules,
        )
    except ValueError as e:
        print(f"{color_yellow('Error:')} {e}", file=sys.stderr)
        raise typer.Exit(code=1)

    if dump_rules or freeze_rules:
        bundle_text = catalog.format_bundle(
            source_name=source.name,
            preset_name=effective_preset_name,
            rules=combined_rules,
        )
        if dump_rules:
            sys.stdout.write(bundle_text)
            return
        if freeze_rules:
            target_file = source / ".zipignore"
            target_file.write_text(bundle_text, encoding="utf-8")
            print(f"Frozen {len(combined_rules)} rules into {target_file}")
            return

    resolved_output = resolve_output_path(
        source,
        archive_name,
        target_out_arg,
        timestamp=timestamp,
        force=force,
    )

    config = PackagerConfig(
        source=source,
        output=resolved_output,
        name=archive_name,
        preset_name=effective_preset_name,
        rules=combined_rules,
        compression=compression,
        flat=flat,
        dry_run=dry_run,
        force=force,
        verbose=verbose,
    )

    packager = ZipPackager(config, reporter=reporter)
    try:
        packager.package()
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        print(f"{color_yellow('Error:')} {e}", file=sys.stderr)
        raise typer.Exit(code=1)


def _resolve_cli_targets(
    directory: str | None, output_path: str | None, output: str | None
) -> tuple[str, str | None]:
    match (directory, output_path, output):
        case (None, _, _):
            return ".", output
        case (str() as d, None, _) if d.endswith(".zip"):
            return ".", output if output is not None else d
        case (str() as d, _, _):
            return d, output if output is not None else output_path


def _validate_source_dir(target_dir_str: str) -> Path:
    source = Path(target_dir_str).expanduser().resolve()
    match source.is_dir():
        case False:
            print(f"{color_yellow('Error:')} Not a directory: {source}", file=sys.stderr)
            raise typer.Exit(code=1)
        case True:
            return source


def _validate_archive_name(name: str | None, source: Path) -> str:
    archive_name = name if name is not None else source.name
    match (
        not archive_name
        or archive_name in (".", "..")
        or "/" in archive_name
        or "\\" in archive_name
    ):
        case True:
            print(
                f"{color_yellow('Error:')} --name must be a nonempty single directory name",
                file=sys.stderr,
            )
            raise typer.Exit(code=1)
        case False:
            return archive_name
