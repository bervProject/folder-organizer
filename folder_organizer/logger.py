"""Logger and progress reporter — Rich progress bar, JSON-Lines log, SIGINT handler."""

from __future__ import annotations

import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from folder_organizer.models import RunSummary

if TYPE_CHECKING:
    from folder_organizer.metadata_store import MetadataStore

_LOG_FILENAME = "organizer.log"

_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _resolve_level(level: str) -> int:
    """Convert a string level name to a :mod:`logging` integer level.

    Accepts ``"INFO"``, ``"WARN"``, ``"WARNING"``, and ``"ERROR"``
    (case-insensitive).  Defaults to ``logging.INFO`` for unknown values.
    """
    return _LEVEL_MAP.get(level.upper(), logging.INFO)


# ---------------------------------------------------------------------------
# JSON-Lines formatter
# ---------------------------------------------------------------------------

class _JsonLinesFormatter(logging.Formatter):
    """Format log records as single-line JSON objects (JSON-Lines).

    Each record is emitted as one JSON object per line with the fields
    required by Requirement 9.5::

        {"timestamp": "...", "level": "INFO", "path": "...", "action": "...", "destination": "..."}
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.") + f"{record.msecs:03.0f}Z",
            "level": record.levelname,
            "path": getattr(record, "file_path", ""),
            "action": getattr(record, "action", record.getMessage()),
        }
        destination = getattr(record, "destination", None)
        if destination is not None:
            entry["destination"] = destination
        error = getattr(record, "error", None)
        if error is not None:
            entry["error"] = error
        return json.dumps(entry, ensure_ascii=False)


# ---------------------------------------------------------------------------
# OrganizerLogger
# ---------------------------------------------------------------------------

class OrganizerLogger:
    """Wraps Rich :class:`~rich.progress.Progress` and a JSON-Lines file handler.

    Responsibilities
    ----------------
    - Display a live progress indicator (files processed / total) via Rich
      (Requirement 9.1).
    - Write structured JSON-Lines log entries to ``target_dir/organizer.log``
      for every file action and error (Requirements 9.2, 9.5).
    - Install a ``SIGINT`` signal handler that flushes the
      :class:`~folder_organizer.metadata_store.MetadataStore` and prints a
      partial :class:`~folder_organizer.models.RunSummary` before exiting with
      code 130 (Requirement 9.4).

    Parameters
    ----------
    target_dir:
        The directory where ``organizer.log`` is written.
    total_files:
        The total number of files to process, used to initialise the progress
        bar denominator.
    metadata_store:
        Reference to the running :class:`~folder_organizer.metadata_store.MetadataStore`
        instance, used by the SIGINT handler.
    console:
        Optional :class:`~rich.console.Console` to use for Rich output.
        Primarily useful in tests.
    """

    def __init__(
        self,
        target_dir: Path,
        total_files: int,
        metadata_store: "MetadataStore",
        *,
        console: Optional[Console] = None,
    ) -> None:
        self._target_dir = target_dir
        self._total_files = total_files
        self._metadata_store = metadata_store
        self._console = console or Console(stderr=True)

        # Partial summary state — incremented by callers
        self._processed: int = 0
        self._moved: int = 0
        self._skipped: int = 0
        self._review: int = 0
        self._unplaced: int = 0
        self._errors: int = 0

        # ---- File logger -------------------------------------------------------
        target_dir.mkdir(parents=True, exist_ok=True)
        log_path = target_dir / _LOG_FILENAME

        self._file_logger = logging.getLogger(
            f"folder_organizer.run.{id(self)}"
        )
        self._file_logger.setLevel(logging.DEBUG)
        self._file_logger.propagate = False

        handler = logging.FileHandler(str(log_path), encoding="utf-8")
        handler.setFormatter(_JsonLinesFormatter())
        self._file_logger.addHandler(handler)
        self._handler = handler

        # ---- Rich progress bar -------------------------------------------------
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self._console,
            transient=False,
        )
        self._task_id: TaskID = self._progress.add_task(
            "Organizing files…", total=total_files
        )

        # ---- SIGINT handler ----------------------------------------------------
        self._original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "OrganizerLogger":
        self._progress.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._progress.stop()
        self._restore_sigint()
        self._handler.close()

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def advance(self, count: int = 1) -> None:
        """Advance the progress bar by *count* steps."""
        self._progress.advance(self._task_id, count)

    # ------------------------------------------------------------------
    # Structured logging
    # ------------------------------------------------------------------

    def log_action(
        self,
        path: str | Path,
        action: str,
        destination: str | Path = "",
        level: str = "INFO",
    ) -> None:
        """Write a structured INFO/WARN/ERROR log entry for a file action.

        Parameters
        ----------
        path:
            The source file path (Requirement 9.5: ``path`` field).
        action:
            A short description of the action taken, e.g. ``"moved"``,
            ``"skipped"``, ``"review"`` (Requirement 9.5: ``action`` field).
        destination:
            The destination path after the action (may be empty string when not
            applicable).
        level:
            One of ``"INFO"``, ``"WARN"``/``"WARNING"``, or ``"ERROR"``.
        """
        extra = {
            "file_path": str(path),
            "action": action,
            "destination": str(destination) if destination else "",
        }
        log_level = _resolve_level(level)
        self._file_logger.log(log_level, action, extra=extra)

    def log_error(
        self,
        path: str | Path,
        reason: str,
    ) -> None:
        """Write a structured ERROR log entry for a file-level error.

        Parameters
        ----------
        path:
            The file path that encountered the error.
        reason:
            Human-readable description of the error.
        """
        extra = {
            "file_path": str(path),
            "action": "error",
            "error": reason,
        }
        self._file_logger.log(logging.ERROR, reason, extra=extra)

    # ------------------------------------------------------------------
    # Summary counters (convenience setters for the Organizer stage)
    # ------------------------------------------------------------------

    def record_moved(self) -> None:
        """Increment the moved-files counter."""
        self._moved += 1
        self._processed += 1

    def record_skipped(self) -> None:
        """Increment the skipped-files counter."""
        self._skipped += 1
        self._processed += 1

    def record_review(self) -> None:
        """Increment the review-flagged counter."""
        self._review += 1
        self._processed += 1

    def record_unplaced(self) -> None:
        """Increment the unplaced-files counter."""
        self._unplaced += 1
        self._processed += 1

    def record_error(self) -> None:
        """Increment the error counter (does NOT advance processed count)."""
        self._errors += 1

    def build_partial_summary(self, *, dry_run: bool = False) -> RunSummary:
        """Build a :class:`~folder_organizer.models.RunSummary` from current counters."""
        return RunSummary(
            total_discovered=self._total_files,
            total_processed=self._processed,
            total_moved=self._moved,
            total_skipped=self._skipped,
            total_review=self._review,
            total_unplaced=self._unplaced,
            total_errors=self._errors,
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------
    # Final summary display
    # ------------------------------------------------------------------

    def print_summary(self, summary: RunSummary) -> None:
        """Print the run summary table to the console via Rich."""
        self._console.print()  # blank line before table
        table = Table(title="Organizer Run Summary", show_header=True)
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")

        if summary.dry_run:
            table.add_row("[yellow]DRY RUN — no files were moved[/yellow]", "")

        table.add_row("Files discovered", str(summary.total_discovered))
        table.add_row("Files processed", str(summary.total_processed))
        table.add_row("Files moved", str(summary.total_moved))
        table.add_row("Files skipped", str(summary.total_skipped))
        table.add_row("Files flagged for review", str(summary.total_review))
        table.add_row("Files unplaced", str(summary.total_unplaced))
        table.add_row("Errors", str(summary.total_errors))

        self._console.print(table)

    # ------------------------------------------------------------------
    # SIGINT handler
    # ------------------------------------------------------------------

    def _handle_sigint(self, signum: int, frame: object) -> None:  # noqa: ARG002
        """Flush metadata, print a partial summary, and exit with code 130."""
        # Stop the progress bar so the terminal is clean
        try:
            self._progress.stop()
        except Exception:  # noqa: BLE001
            pass

        self._console.print(
            "\n[bold yellow]Interrupted — flushing metadata store…[/bold yellow]"
        )

        try:
            self._metadata_store.flush(self._target_dir)
        except Exception as exc:  # noqa: BLE001
            self._console.print(f"[red]Failed to flush metadata: {exc}[/red]")

        self._console.print("[bold yellow]Partial summary:[/bold yellow]")
        partial = self.build_partial_summary()
        self.print_summary(partial)

        self._restore_sigint()
        sys.exit(130)

    def _restore_sigint(self) -> None:
        """Restore the original SIGINT handler."""
        try:
            signal.signal(signal.SIGINT, self._original_sigint)
        except Exception:  # noqa: BLE001
            pass
