"""Integration test — AI returns an out-of-taxonomy category.

When the AI categorizer returns a category label that is not in the configured
taxonomy, the affected files must be routed to `_review/` with
`review_required=True` in their metadata records.  No category folder with the
invalid name should be created.

Requirements: 4.7
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from folder_organizer.config import Config
from folder_organizer.models import CategorizationResult, InspectedFile
from folder_organizer.organizer import Organizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_text_file(directory: Path, name: str, content: str = "sample") -> Path:
    """Create a plain-text file and return its path."""
    p = directory / name
    p.write_text(content, encoding="utf-8")
    return p


def _make_out_of_taxonomy_side_effect(category: str = "GarbageCategory"):
    """Return a side-effect that always produces an out-of-taxonomy result.

    The real `_ai_categorize` already sets `review_required=True` when the
    returned category is not in the taxonomy.  This mock simulates that
    final result directly, matching what the real method would produce.
    """

    def _side_effect(file: InspectedFile, *args, **kwargs) -> CategorizationResult:
        return CategorizationResult(
            category=category,
            subcategory=None,
            confidence=0.9,
            method="ai",
            review_required=True,
            fallback_used=False,
        )

    return _side_effect


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestOutOfTaxonomyRouting:
    """Files categorized with an out-of-taxonomy label must land in _review/."""

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def _build_source_dir(self, tmp_path: Path) -> tuple[Path, list[str]]:
        """Create a small source directory with two plain-text files."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        filenames = ["report.txt", "notes.md"]
        for name in filenames:
            _write_text_file(source_dir, name, f"Content of {name}")

        return source_dir, filenames

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_files_routed_to_review_dir(self, tmp_path: Path) -> None:
        """All files with an out-of-taxonomy category end up in target_dir/_review/."""
        source_dir, filenames = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_out_of_taxonomy_side_effect("GarbageCategory"),
        ):
            organizer = Organizer(config)
            summary = organizer.run()

        review_dir = target_dir / "_review"
        assert review_dir.is_dir(), (
            "_review/ directory was not created under target_dir"
        )

        for filename in filenames:
            assert (review_dir / filename).exists(), (
                f"{filename!r} was not routed to _review/"
            )

        assert summary.total_review == len(filenames), (
            f"Expected total_review={len(filenames)}, got {summary.total_review}"
        )

    def test_no_invalid_category_folder_created(self, tmp_path: Path) -> None:
        """No folder named after the invalid category is created under target_dir."""
        source_dir, _ = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        invalid_category = "GarbageCategory"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_out_of_taxonomy_side_effect(invalid_category),
        ):
            Organizer(config).run()

        invalid_dir = target_dir / invalid_category
        assert not invalid_dir.exists(), (
            f"Category folder {invalid_category!r} must not be created for "
            "out-of-taxonomy categories"
        )

    def test_metadata_records_have_review_required_true(self, tmp_path: Path) -> None:
        """organizer-metadata.json records for out-of-taxonomy files have review_required=True."""
        source_dir, filenames = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_out_of_taxonomy_side_effect("GarbageCategory"),
        ):
            Organizer(config).run()

        metadata_path = target_dir / "organizer-metadata.json"
        assert metadata_path.exists(), "organizer-metadata.json was not created"

        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        records = data["records"]

        assert len(records) == len(filenames), (
            f"Expected {len(filenames)} metadata records, got {len(records)}"
        )

        for key, record in records.items():
            assert record["review_required"] is True, (
                f"Record {key!r} has review_required={record['review_required']!r}; "
                "expected True for out-of-taxonomy category"
            )
            assert record["category"] == "GarbageCategory", (
                f"Record {key!r} has category={record['category']!r}; "
                "expected the original (invalid) category label to be preserved"
            )

    def test_files_not_in_source_dir_after_run(self, tmp_path: Path) -> None:
        """Files are moved out of source_dir even when destined for _review/."""
        source_dir, filenames = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_out_of_taxonomy_side_effect("GarbageCategory"),
        ):
            Organizer(config).run()

        for filename in filenames:
            assert not (source_dir / filename).exists(), (
                f"{filename!r} was not moved out of source_dir"
            )

    def test_run_summary_counts(self, tmp_path: Path) -> None:
        """RunSummary reflects that all files are review (not moved to category folders)."""
        source_dir, filenames = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_out_of_taxonomy_side_effect("GarbageCategory"),
        ):
            summary = Organizer(config).run()

        assert summary.total_discovered == len(filenames)
        assert summary.total_review == len(filenames)
        # Files land in _review/, so total_moved (non-review bucket) is 0
        assert summary.total_moved == 0
        assert summary.total_errors == 0
        assert summary.dry_run is False
