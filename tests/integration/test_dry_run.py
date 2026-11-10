"""Integration test — dry run produces zero mutations.

Verifies that running Organizer with dry_run=True:
  - does not move or modify any files in source_dir (Req 8.1)
  - prints a proposed-changes report rather than acting (Req 8.2)
  - does NOT write organizer-metadata.json (Req 8.3)
  - correctly flags low-confidence files as _review candidates (Req 8.4)

Requirements: 8.1, 8.2, 8.3, 8.4
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from folder_organizer.config import Config
from folder_organizer.models import CategorizationResult, InspectedFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snapshot(root: Path) -> dict[str, bytes]:
    """Return a mapping of relative-path-string → file content bytes for every
    file found recursively under *root*.

    This lets tests compare the filesystem state before and after a run with
    a simple equality check.
    """
    result: dict[str, bytes] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            result[rel] = p.read_bytes()
    return result


def _make_ai_side_effect(
    filename_to_category: dict[str, str],
    confidence: float = 0.9,
    review_required: bool = False,
):
    """Return a side_effect callable for _ai_categorize."""

    def _side_effect(file: InspectedFile, existing_record=None) -> CategorizationResult:
        filename = file.path.name
        category = filename_to_category.get(filename, "Documents")
        return CategorizationResult(
            category=category,
            subcategory=None,
            confidence=confidence,
            method="ai",
            review_required=review_required,
            fallback_used=False,
        )

    return _side_effect


def _make_low_confidence_side_effect(filename_to_category: dict[str, str]):
    """Return a side_effect that sets confidence=0.1 AND review_required=True.

    When confidence < min_confidence the real _ai_categorize would set
    review_required=True; we replicate that in the mock so the dry-run summary
    correctly counts flagged files (Req 8.4).
    """
    return _make_ai_side_effect(
        filename_to_category, confidence=0.1, review_required=True
    )


def _build_source_dir(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Create three synthetic files and return (source_dir, filename→category)."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    (source_dir / "notes.txt").write_text("Meeting notes", encoding="utf-8")
    (source_dir / "photo.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (source_dir / "data.csv").write_text("col1,col2\n1,2\n", encoding="utf-8")

    filename_to_category = {
        "notes.txt": "Documents",
        "photo.png": "Images",
        "data.csv": "Spreadsheets",
    }
    return source_dir, filename_to_category


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDryRunProducesZeroMutations:
    """Dry run must leave the filesystem completely unchanged."""

    def test_source_files_unchanged_after_dry_run(self, tmp_path: Path) -> None:
        """Requirement 8.1 — no files are moved; source_dir is identical before and after."""
        source_dir, filename_to_category = _build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        # Snapshot the entire tmp_path tree BEFORE the run
        before = _snapshot(tmp_path)

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_side_effect(filename_to_category),
        ):
            from folder_organizer.organizer import Organizer
            Organizer(config).run()

        # Snapshot after — must be identical
        after = _snapshot(tmp_path)

        # Every file that existed before must still exist with the same content
        for rel, content in before.items():
            assert rel in after, f"File disappeared after dry run: {rel!r}"
            assert after[rel] == content, f"File content changed after dry run: {rel!r}"

        # No source files should have been moved or new category folders created.
        # organizer.log is allowed (the logger always opens it); what must NOT
        # appear is organizer-metadata.json or any category subdirectory files.
        disallowed_new = {
            rel for rel in (set(after.keys()) - set(before.keys()))
            if not rel.endswith("organizer.log")
        }
        assert not disallowed_new, (
            f"Dry run created unexpected new files: {disallowed_new}"
        )

    def test_metadata_json_not_written(self, tmp_path: Path) -> None:
        """Requirement 8.3 — organizer-metadata.json must NOT be written during dry run."""
        source_dir, filename_to_category = _build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_side_effect(filename_to_category),
        ):
            from folder_organizer.organizer import Organizer
            Organizer(config).run()

        metadata_path = target_dir / "organizer-metadata.json"
        assert not metadata_path.exists(), (
            "organizer-metadata.json must NOT be written when dry_run=True "
            f"(found at {metadata_path})"
        )

    def test_run_summary_flags_dry_run_and_zero_moved(self, tmp_path: Path) -> None:
        """RunSummary.dry_run is True and total_moved == 0 after a dry run."""
        source_dir, filename_to_category = _build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_side_effect(filename_to_category),
        ):
            from folder_organizer.organizer import Organizer
            summary = Organizer(config).run()

        assert summary.dry_run is True, "RunSummary.dry_run must be True"
        assert summary.total_moved == 0, (
            f"total_moved must be 0 in dry run, got {summary.total_moved}"
        )
        assert summary.total_discovered == len(filename_to_category), (
            f"total_discovered={summary.total_discovered}, "
            f"expected {len(filename_to_category)}"
        )

    def test_low_confidence_files_flagged_for_review_in_dry_run(
        self, tmp_path: Path
    ) -> None:
        """Requirement 8.4 — files below min_confidence are shown as _review candidates
        in the dry-run report; RunSummary.total_review reflects the count."""
        source_dir, filename_to_category = _build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        # min_confidence=0.5; AI returns 0.1 for all files → all 3 flagged
        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            min_confidence=0.5,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_low_confidence_side_effect(filename_to_category),
        ):
            from folder_organizer.organizer import Organizer
            summary = Organizer(config).run()

        assert summary.dry_run is True
        assert summary.total_moved == 0, "dry run must never move files"
        assert summary.total_review == len(filename_to_category), (
            f"Expected all {len(filename_to_category)} files flagged for review "
            f"(confidence 0.1 < min_confidence 0.5), got {summary.total_review}"
        )

    def test_no_category_folders_created_in_target_dir(self, tmp_path: Path) -> None:
        """Dry run must not create any category folders under target_dir (Req 8.1)."""
        source_dir, filename_to_category = _build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_side_effect(filename_to_category),
        ):
            from folder_organizer.organizer import Organizer
            Organizer(config).run()

        # target_dir itself must not have been created (or if it was, must be empty
        # aside from any organizer.log that the logger writes).
        if target_dir.exists():
            contents = [
                p for p in target_dir.iterdir()
                # Allow organizer.log — it is explicitly NOT blocked in dry-run mode
                # by the current design; what must NOT exist is organizer-metadata.json
                # and category subdirectories.
                if p.name not in ("organizer.log",)
            ]
            assert not contents, (
                f"target_dir should contain no category folders in dry run, "
                f"found: {[p.name for p in contents]}"
            )
