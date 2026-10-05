"""Folder Generator — placement resolution and name sanitization."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

from folder_organizer.models import CategorizedFile, FolderCreationError, PlacedFile

logger = logging.getLogger(__name__)

# Characters allowed in folder names; anything else is replaced with '_'.
_ALLOWED_CHARS = re.compile(r"[^A-Za-z0-9_\-. ]")


class FolderGenerator:
    """Resolve file placements and create the required folder structure."""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def resolve_placement(
        self, file: CategorizedFile, target_dir: Path
    ) -> PlacedFile:
        """Resolve the destination directory for *file* relative to *target_dir*.

        Routing rules (Requirement 6.1 – 6.5):
        - ``review_required=True`` → ``target_dir/_review/``
        - Otherwise → ``target_dir/<category>/[<subcategory>/]``
          with both labels sanitized via :meth:`sanitize_name`.

        The returned :class:`PlacedFile` always has ``unplaced=False``; the
        ``unplaced`` flag is only set to ``True`` by :meth:`create_folders`
        when a ``PermissionError`` prevents folder creation.
        """
        if file.review_required:
            destination_dir = target_dir / "_review"
        else:
            sanitized_category = self.sanitize_name(file.category)
            if file.subcategory:
                sanitized_subcategory = self.sanitize_name(file.subcategory)
                destination_dir = target_dir / sanitized_category / sanitized_subcategory
            else:
                destination_dir = target_dir / sanitized_category

        return PlacedFile(
            source_path=file.path,
            destination_dir=destination_dir,
            destination_filename=file.path.name,
            review_required=file.review_required,
            unplaced=False,
        )

    def create_folders(
        self, placements: List[PlacedFile]
    ) -> List[FolderCreationError]:
        """Create all destination directories referenced by *placements*.

        For each unique destination directory:
        - On success (or if the directory already exists): no action (Requirement 6.4).
        - On ``PermissionError``: log the error, record a
          :class:`FolderCreationError`, and re-route affected
          :class:`PlacedFile` objects to ``target_dir/_unplaced``
          (Requirement 6.5).

        The ``_unplaced`` directory itself is created without error handling —
        if the target root is unwritable the run will have failed earlier.

        Returns a (possibly empty) list of :class:`FolderCreationError`
        instances for every directory that could not be created.
        """
        errors: List[FolderCreationError] = []
        failed_dirs: set[Path] = set()

        # Collect unique destination directories.
        unique_dirs: dict[Path, list[PlacedFile]] = {}
        for placed in placements:
            unique_dirs.setdefault(placed.destination_dir, []).append(placed)

        for dest_dir, affected in unique_dirs.items():
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError as exc:
                reason = str(exc)
                logger.error(
                    "Cannot create folder %s: %s — routing %d file(s) to _unplaced",
                    dest_dir,
                    reason,
                    len(affected),
                )
                errors.append(FolderCreationError(path=dest_dir, reason=reason))
                failed_dirs.add(dest_dir)

        if failed_dirs:
            # Determine the common target root by walking up from any failed dir.
            # We use the first failed destination to infer the target_dir: since
            # our paths are always ``target_dir / ...`` we can resolve it safely.
            sample_failed = next(iter(failed_dirs))
            # The target root is two or three levels up depending on whether there
            # is a subcategory.  Rather than guessing the depth we walk the list
            # of placements to find which ones are affected and update them in place.
            # We need to find the matching target_dir; since PlacedFile objects do
            # not store target_dir directly we derive it from the non-_review,
            # non-_unplaced prefix of the destination_dir.
            unplaced_dir = _derive_unplaced_dir(sample_failed, placements)
            unplaced_dir.mkdir(parents=True, exist_ok=True)

            for placed in placements:
                if placed.destination_dir in failed_dirs:
                    placed.destination_dir = unplaced_dir
                    placed.unplaced = True

        return errors

    @staticmethod
    def sanitize_name(label: str) -> str:
        """Replace any character not in ``[A-Za-z0-9_\\-. ]`` with ``_``.

        The substitution is applied in a single pass so the result is
        guaranteed to be idempotent: ``sanitize_name(sanitize_name(s)) ==
        sanitize_name(s)`` for all strings *s* (Property 6).
        """
        return _ALLOWED_CHARS.sub("_", label)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _derive_unplaced_dir(failed_path: Path, placements: List[PlacedFile]) -> Path:
    """Derive the ``_unplaced`` directory given a failed destination path.

    We need to reconstruct ``target_dir / "_unplaced"``.  Because all
    placements share the same *target_dir* we find the common ancestor of all
    destination directories.

    In practice destination dirs have this shape:
    - ``target_dir/_review``             (review files, depth 1)
    - ``target_dir/<cat>``               (no subcategory, depth 1)
    - ``target_dir/<cat>/<subcat>``      (with subcategory, depth 2)

    The common ancestor of all destination dirs is always *target_dir*.
    """
    all_dest_dirs = [p.destination_dir for p in placements]

    if all_dest_dirs:
        # Start from the parent of the first dir (one level above the
        # first component that was added to target_dir).
        candidate = all_dest_dirs[0].parent
        for dest in all_dest_dirs[1:]:
            # Walk up candidate until it is an ancestor-or-equal of dest.
            while True:
                try:
                    dest.relative_to(candidate)
                    break
                except ValueError:
                    candidate = candidate.parent
        target_dir = candidate
    else:
        # Fallback: two levels up from the failed path.
        target_dir = failed_path.parent.parent

    return target_dir / "_unplaced"
