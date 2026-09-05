"""File Discoverer — recursive enumeration, exclusion, symlink handling."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from folder_organizer.models import DiscoveryResult


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DiscoveryError(Exception):
    """Raised when the source directory cannot be read during enumeration."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Cannot read directory '{path}': {reason}")


# ---------------------------------------------------------------------------
# FileDiscoverer
# ---------------------------------------------------------------------------

class FileDiscoverer:
    """Recursively enumerates files in a source directory.

    Handles:
    - Symbolic link safety (skips out-of-scope symlinks)
    - Glob-pattern exclusions via ``fnmatch``
    - Accurate counts for the discovery report (Requirement 2.4)
    """

    def discover(
        self,
        source_dir: Path,
        exclude_patterns: list[str],
    ) -> DiscoveryResult:
        """Enumerate all files under *source_dir*.

        Parameters
        ----------
        source_dir:
            Root directory to scan.  Must exist and be a readable directory.
        exclude_patterns:
            Zero or more glob patterns tested against each file's path
            relative to *source_dir*.  Files (or directories) whose relative
            path matches any pattern are skipped and counted in
            ``excluded_count``.

        Returns
        -------
        DiscoveryResult
            ``discovered`` — list of absolute :class:`~pathlib.Path` objects
            for every regular, in-scope, non-excluded file found.
            ``skipped_symlinks`` — count of symbolic links whose resolved
            target was outside the canonical source directory tree.
            ``excluded_count`` — count of paths skipped due to an exclusion
            pattern match.

        Raises
        ------
        DiscoveryError
            When *source_dir* cannot be listed (e.g. permission denied or
            path does not exist as a directory).
        """
        # Validate source_dir up front; produce a clear error per Req 2.5.
        if not source_dir.exists():
            raise DiscoveryError(source_dir, "path does not exist")
        if not source_dir.is_dir():
            raise DiscoveryError(source_dir, "path is not a directory")

        # Canonical absolute form used for symlink containment checks.
        try:
            canonical_source = source_dir.resolve()
        except OSError as exc:
            raise DiscoveryError(source_dir, str(exc)) from exc

        discovered: list[Path] = []
        skipped_symlinks: int = 0
        excluded_count: int = 0

        try:
            all_paths = list(source_dir.rglob("*"))
        except PermissionError as exc:
            raise DiscoveryError(source_dir, f"permission denied: {exc}") from exc
        except OSError as exc:
            raise DiscoveryError(source_dir, str(exc)) from exc

        for path in all_paths:
            # Only consider leaf entries (files and symlinks pointing to files).
            # Directories are traversed implicitly by rglob; skip them here.
            if not path.is_file() and not path.is_symlink():
                continue

            # --- Symlink safety check (Requirement 2.3) --------------------
            if path.is_symlink():
                try:
                    resolved = path.resolve()
                except OSError:
                    # Cannot resolve — treat as out-of-scope.
                    skipped_symlinks += 1
                    continue

                # The resolved target must sit inside the canonical source tree.
                try:
                    resolved.relative_to(canonical_source)
                except ValueError:
                    # Target is outside the source directory.
                    skipped_symlinks += 1
                    continue

                # In-scope symlink that does not point to a regular file
                # (e.g. points to a directory) — skip without counting.
                if not resolved.is_file():
                    continue

            # --- Exclusion pattern check (Requirement 2.2) -----------------
            try:
                rel_str = str(path.relative_to(source_dir))
            except ValueError:
                # Defensive: should not happen, but skip gracefully.
                continue

            # Normalise to forward slashes so patterns work cross-platform.
            rel_posix = rel_str.replace(os.sep, "/")

            if any(
                fnmatch.fnmatch(rel_posix, pattern)
                or fnmatch.fnmatch(path.name, pattern)
                for pattern in exclude_patterns
            ):
                excluded_count += 1
                continue

            # Regular, in-scope, non-excluded file — add to results.
            discovered.append(path)

        return DiscoveryResult(
            discovered=discovered,
            skipped_symlinks=skipped_symlinks,
            excluded_count=excluded_count,
        )
