"""File Mover — move with conflict resolution and mtime preservation."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from folder_organizer.models import MoveResult, PlacedFile

logger = logging.getLogger(__name__)


class FileMover:
    """Move files to their resolved destination directories.

    Handles:
    - Conflict resolution by appending ``_1`` … ``_9999`` before the extension
      (Requirement 7.2).
    - Preservation of the original last-modified timestamp after the move
      (Requirement 7.3).
    - Graceful error handling for ``PermissionError`` / ``OSError``
      (Requirement 7.4).
    - Dry-run mode that computes the destination path without performing I/O
      (Requirement 7.5 — dry-run short-circuit in the design).

    Parameters
    ----------
    dry_run:
        When ``True``, :meth:`move` computes the resolved destination path and
        returns a :class:`MoveResult` with ``success=False`` but performs no
        file-system mutations.
    """

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def move(self, placed: PlacedFile) -> MoveResult:
        """Move *placed.source_path* into *placed.destination_dir*.

        Steps
        -----
        1. Resolve destination filename (handle conflicts via
           :meth:`_resolve_conflict`).
        2. If ``dry_run`` is enabled, return the resolved path without moving.
        3. Capture the original ``mtime`` before the move.
        4. Perform ``shutil.move``.
        5. Restore the original ``mtime`` via ``os.utime``.

        Returns
        -------
        MoveResult
            ``success=True`` and ``destination_path`` set on success.
            ``success=False`` with a ``skip_reason`` on any failure.
        """
        source = placed.source_path
        dest_dir = placed.destination_dir
        filename = placed.destination_filename

        # ---- Resolve conflicts ------------------------------------------------
        dest_path = dest_dir / filename
        if dest_path.exists():
            resolved = self._resolve_conflict(dest_dir, filename)
            if resolved is None:
                msg = (
                    f"Conflict suffix exhausted (1–9999) for '{filename}' "
                    f"in '{dest_dir}'; skipping file."
                )
                logger.error("%s  source=%s", msg, source)
                return MoveResult(
                    source_path=source,
                    destination_path=None,
                    success=False,
                    skip_reason="conflict_exhausted",
                )
            dest_path = resolved

        # ---- Dry run short-circuit -------------------------------------------
        if self._dry_run:
            return MoveResult(
                source_path=source,
                destination_path=dest_path,
                success=False,
                skip_reason="dry_run",
            )

        # ---- Capture original mtime ------------------------------------------
        try:
            stat = source.stat()
            original_atime = stat.st_atime
            original_mtime = stat.st_mtime
        except OSError as exc:
            logger.error(
                "Cannot stat source file '%s': %s; skipping.", source, exc
            )
            return MoveResult(
                source_path=source,
                destination_path=None,
                success=False,
                skip_reason=str(exc),
            )

        # ---- Perform the move ------------------------------------------------
        try:
            shutil.move(str(source), str(dest_path))
        except PermissionError as exc:
            logger.error(
                "Permission denied moving '%s' → '%s': %s; skipping.",
                source,
                dest_path,
                exc,
            )
            return MoveResult(
                source_path=source,
                destination_path=None,
                success=False,
                skip_reason=str(exc),
            )
        except OSError as exc:
            logger.error(
                "I/O error moving '%s' → '%s': %s; skipping.",
                source,
                dest_path,
                exc,
            )
            return MoveResult(
                source_path=source,
                destination_path=None,
                success=False,
                skip_reason=str(exc),
            )

        # ---- Restore mtime ---------------------------------------------------
        try:
            os.utime(dest_path, (original_atime, original_mtime))
        except OSError as exc:
            # Non-fatal: the file was moved successfully, mtime restore is best-effort.
            logger.warning(
                "Could not restore mtime for '%s': %s", dest_path, exc
            )

        return MoveResult(
            source_path=source,
            destination_path=dest_path,
            success=True,
            skip_reason=None,
        )

    def _resolve_conflict(self, dest_dir: Path, filename: str) -> Optional[Path]:
        """Find a unique filename in *dest_dir* for a file named *filename*.

        Appends ``_1``, ``_2``, … ``_9999`` before the file extension until a
        path that does not exist is found.  Returns ``None`` when all 9,999
        suffixes are exhausted without finding a free name (Requirement 7.6).

        Parameters
        ----------
        dest_dir:
            Target directory in which to resolve the conflict.
        filename:
            Original filename (e.g. ``"report.pdf"``).

        Returns
        -------
        Path | None
            A :class:`~pathlib.Path` pointing to the first non-existent
            candidate, or ``None`` if all candidates are taken.
        """
        stem = Path(filename).stem
        suffix = Path(filename).suffix  # includes leading dot, e.g. ".pdf"

        for i in range(1, 10_000):  # 1 … 9999 inclusive
            candidate = dest_dir / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                return candidate

        return None
