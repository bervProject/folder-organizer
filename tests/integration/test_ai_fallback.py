"""Integration test — AI service failure with extension-based fallback categorization.

Verifies that when the OpenAI API is unavailable (simulated by raising an exception
from _ai_categorize), the pipeline falls back to extension-based categorization for
all files. Also verifies the "Uncategorized" path for unknown extensions.

Requirements: 4.6, 4.8
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from folder_organizer.config import Config
from folder_organizer.organizer import Organizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raise_service_unavailable(*args, **kwargs) -> None:
    """Simulates an OpenAI 503-style failure."""
    raise Exception("503 Service Unavailable")


# ---------------------------------------------------------------------------
# Scenario 1: Known extensions → extension-based fallback categories
# ---------------------------------------------------------------------------

class TestAIFailureKnownExtensions:
    """When AI is unavailable, files with known extensions get the correct fallback category."""

    def _build_source_dir(self, tmp_path: Path) -> tuple[Path, dict[str, str]]:
        """Create synthetic source files with known extensions and return expected categories."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        # .txt → Documents
        (source_dir / "readme.txt").write_text("Some text content.", encoding="utf-8")
        # .jpg → Images
        (source_dir / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
        # .py → Code
        (source_dir / "script.py").write_text("print('hello')", encoding="utf-8")

        filename_to_expected_category = {
            "readme.txt": "Documents",
            "photo.jpg":  "Images",
            "script.py":  "Code",
        }
        return source_dir, filename_to_expected_category

    def test_fallback_categories_correct(self, tmp_path: Path) -> None:
        """All files receive the extension-based category when AI fails."""
        source_dir, expected = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_raise_service_unavailable,
        ):
            organizer = Organizer(config)
            summary = organizer.run()

        # All files should have been moved
        assert summary.total_moved == len(expected)
        assert summary.total_errors == 0

        # Verify each file landed in the correct category folder
        for filename, category in expected.items():
            category_dir = target_dir / category
            found = list(category_dir.rglob(filename))
            assert len(found) == 1, (
                f"Expected {filename!r} under {category_dir}, found: {found}"
            )

    def test_fallback_used_true_in_metadata(self, tmp_path: Path) -> None:
        """organizer-metadata.json records have fallback_used=True for all files."""
        source_dir, expected = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_raise_service_unavailable,
        ):
            Organizer(config).run()

        metadata_path = target_dir / "organizer-metadata.json"
        assert metadata_path.exists(), "organizer-metadata.json was not created"

        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        records = data["records"]
        assert len(records) == len(expected), (
            f"Expected {len(expected)} records, got {len(records)}"
        )

        for key, record in records.items():
            assert record["fallback_used"] is True, (
                f"Record {key!r}: expected fallback_used=True, got {record['fallback_used']!r}"
            )
            assert record["confidence_score"] == 0.0, (
                f"Record {key!r}: expected confidence_score=0.0, got {record['confidence_score']!r}"
            )
            assert record["method"] == "fallback", (
                f"Record {key!r}: expected method='fallback', got {record['method']!r}"
            )

    def test_confidence_zero_for_all_fallback_records(self, tmp_path: Path) -> None:
        """confidence_score is exactly 0.0 in every record when fallback is used."""
        source_dir, expected = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_raise_service_unavailable,
        ):
            Organizer(config).run()

        data = json.loads(
            (target_dir / "organizer-metadata.json").read_text(encoding="utf-8")
        )
        for key, record in data["records"].items():
            assert record["confidence_score"] == 0.0, (
                f"Record {key!r}: confidence_score should be 0.0, got {record['confidence_score']!r}"
            )

    def test_correct_category_per_extension_in_metadata(self, tmp_path: Path) -> None:
        """Each record's category matches the expected extension-based mapping."""
        source_dir, expected = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_raise_service_unavailable,
        ):
            Organizer(config).run()

        data = json.loads(
            (target_dir / "organizer-metadata.json").read_text(encoding="utf-8")
        )

        # Build a filename → record mapping for easy lookup
        filename_to_record: dict[str, dict] = {}
        for record in data["records"].values():
            orig = Path(record["original_path"]).name
            filename_to_record[orig] = record

        for filename, expected_category in expected.items():
            assert filename in filename_to_record, (
                f"No metadata record found for {filename!r}"
            )
            actual_category = filename_to_record[filename]["category"]
            assert actual_category == expected_category, (
                f"{filename!r}: expected category {expected_category!r}, got {actual_category!r}"
            )


# ---------------------------------------------------------------------------
# Scenario 2: Unknown extension (.xyz) → Uncategorized (Requirement 4.8)
# ---------------------------------------------------------------------------

class TestAIFailureUnknownExtension:
    """When AI fails and extension is unrecognized, file is categorized as 'Uncategorized'."""

    def _build_source_dir_unknown_ext(self, tmp_path: Path) -> Path:
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "mystery.xyz").write_bytes(b"\x00\x01\x02\x03")
        return source_dir

    def test_unknown_extension_yields_uncategorized(self, tmp_path: Path) -> None:
        """A file with an unknown extension gets category='Uncategorized' when AI fails.

        Requirement 4.8: If AI unavailable AND extension unrecognized → Uncategorized.
        """
        source_dir = self._build_source_dir_unknown_ext(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_raise_service_unavailable,
        ):
            summary = Organizer(config).run()

        assert summary.total_discovered == 1

        data = json.loads(
            (target_dir / "organizer-metadata.json").read_text(encoding="utf-8")
        )
        records = data["records"]
        assert len(records) == 1

        record = next(iter(records.values()))
        assert record["category"] == "Uncategorized", (
            f"Expected category='Uncategorized', got {record['category']!r}"
        )
        assert record["fallback_used"] is True
        assert record["confidence_score"] == 0.0
        assert record["method"] == "fallback"

    def test_unknown_extension_marked_review_required(self, tmp_path: Path) -> None:
        """An unknown-extension file has review_required=True when AI fails (Requirement 4.8)."""
        source_dir = self._build_source_dir_unknown_ext(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_raise_service_unavailable,
        ):
            summary = Organizer(config).run()

        data = json.loads(
            (target_dir / "organizer-metadata.json").read_text(encoding="utf-8")
        )
        record = next(iter(data["records"].values()))
        assert record["review_required"] is True, (
            f"Expected review_required=True for unknown extension, got {record['review_required']!r}"
        )
        # summary should count the review
        assert summary.total_review == 1
