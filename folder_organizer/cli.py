"""CLI layer — Typer app and argument definitions.

Defines the ``organize`` command with all flags. Config file values are loaded
first; CLI flags are merged on top so CLI always wins (Requirement 10.2).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from folder_organizer.config import (
    Config,
    ConfigLoader,
    ConfigMissingFieldError,
    ConfigParseError,
    ConfigValidationError,
)
from folder_organizer.organizer import Organizer

app = typer.Typer(
    name="folder-organizer",
    help="AI-powered local file organizer — recursively categorizes files using an AI model.",
    add_completion=False,
)

_console = Console(stderr=True)


@app.command()
def organize(
    source_dir: Path = typer.Argument(
        ...,
        help="Directory whose files will be organized. Must exist and be a directory.",
        show_default=False,
    ),
    target_dir: Optional[Path] = typer.Option(
        None,
        "--target-dir",
        "-t",
        help=(
            "Root directory under which category folders are created. "
            "Defaults to SOURCE_DIR when not specified."
        ),
    ),
    config_file: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to a YAML or JSON configuration file. CLI flags override file values.",
    ),
    exclude: List[str] = typer.Option(
        [],
        "--exclude",
        "-e",
        help=(
            "Glob pattern for files to exclude. Can be repeated: "
            "-e '*.tmp' -e '__pycache__/**'."
        ),
    ),
    min_confidence: Optional[float] = typer.Option(
        None,
        "--min-confidence",
        help=(
            "Minimum confidence score [0.0–1.0]. Files categorized below this "
            "threshold are placed in _review instead of being auto-moved. Default: 0.0."
        ),
    ),
    dry_run: Optional[bool] = typer.Option(
        None,
        "--dry-run/--no-dry-run",
        help=(
            "When enabled, simulate all actions without creating folders, moving files, "
            "or writing the metadata store. Default: False."
        ),
    ),
    ai_endpoint: Optional[str] = typer.Option(
        None,
        "--ai-endpoint",
        help=(
            "URL of the OpenAI-compatible chat completions endpoint. "
            "Default: https://api.openai.com/v1/chat/completions."
        ),
    ),
    ai_model: Optional[str] = typer.Option(
        None,
        "--ai-model",
        help="Model identifier passed to the AI API. Default: gpt-4o-mini.",
    ),
) -> None:
    """Organize SOURCE_DIR by moving files into AI-assigned category folders.

    When --config is provided, values are read from the file first.
    Any CLI flags you supply override the corresponding config file values.
    """

    # ------------------------------------------------------------------
    # 1. Load config file (if given), otherwise start from a minimal Config
    # ------------------------------------------------------------------
    config: Config

    if config_file is not None:
        if not config_file.exists():
            _console.print(
                f"[bold red]Error:[/bold red] Config file not found: {config_file}"
            )
            raise typer.Exit(code=1)

        try:
            config = ConfigLoader.load(config_file)
        except ConfigParseError as exc:
            _console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc
        except ConfigMissingFieldError as exc:
            _console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc
        except ConfigValidationError as exc:
            _console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc
        except FileNotFoundError as exc:
            _console.print(
                f"[bold red]Error:[/bold red] Config file not found: {config_file}"
            )
            raise typer.Exit(code=1) from exc
    else:
        # No config file — build a minimal Config from the CLI source_dir.
        # source_dir will be validated below; we supply it here so Config
        # construction doesn't fail on missing required field.
        try:
            config = Config(source_dir=source_dir)
        except ConfigValidationError as exc:
            _console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    # ------------------------------------------------------------------
    # 2. Merge CLI overrides on top of the file-loaded (or default) config.
    #    Config.merge_cli_overrides ignores None values, so only flags the
    #    user actually provided will overwrite file values.
    # ------------------------------------------------------------------
    try:
        config = config.merge_cli_overrides(
            source_dir=source_dir,
            target_dir=target_dir,
            exclude_patterns=exclude,
            min_confidence=min_confidence,
            dry_run=dry_run,
            ai_endpoint=ai_endpoint,
            ai_model=ai_model,
        )
    except ConfigValidationError as exc:
        _console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    # ------------------------------------------------------------------
    # 3. Validate source_dir (Requirements 1.1, 1.2)
    # ------------------------------------------------------------------
    resolved_source = config.source_dir

    if not resolved_source.exists():
        _console.print(
            f"[bold red]Error:[/bold red] Source directory does not exist: {resolved_source}"
        )
        raise typer.Exit(code=1)

    if not resolved_source.is_dir():
        _console.print(
            f"[bold red]Error:[/bold red] Source path is not a directory: {resolved_source}"
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # 4. Validate / create target_dir (Requirements 1.3, 1.4, 1.5)
    #    When absent, Config already defaults to None (Organizer resolves it
    #    to source_dir at runtime), so we only need to act when a path was
    #    explicitly provided.
    # ------------------------------------------------------------------
    if config.target_dir is not None:
        td = config.target_dir
        if not td.exists():
            try:
                td.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError) as exc:
                _console.print(
                    f"[bold red]Error:[/bold red] Cannot create target directory "
                    f"{td}: {exc}"
                )
                raise typer.Exit(code=1) from exc

    # ------------------------------------------------------------------
    # 5. Delegate to the pipeline orchestrator (Requirements 10.4)
    # ------------------------------------------------------------------
    Organizer(config).run()
