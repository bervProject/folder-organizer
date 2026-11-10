"""Integration test — full pipeline with mixed file types.

Runs Organizer.run() end-to-end over a synthetic directory containing a text
file, a PDF stub, an image, and a binary file.  The OpenAI API call is mocked
via unittest.mock.patch so no real network traffic is generated.

Requirements: 1.x, 2.x, 3.x, 4.x, 5.x, 6.x, 7.x, 9.x
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from folder_organizer.config import Config
from folder_organizer.models import CategorizationResult, InspectedFile, ExtractionStatus
from folder_organizer.organizer import Organizer


# ---------------------------------------------------------------------------
# Minimal valid file stubs
# ---------------------------------------------------------------------------

# Smallest valid PNG (1×1 transparent pixel)
_MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"                           # PNG signature
    b"\x00\x00\x00\rIHDR"                           # IHDR chunk length + type
    b"\x00\x00\x00\x01\x00\x00\x00\x01"            # 1×1 dimensions
    b"\x08\x02\x00\x00\x00\x90wS\xde"              # bit depth, colour type, crc
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00" # IDAT chunk
    b"\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"              # IEND chunk
)

# Minimal PDF stub — just the header bytes; pypdf may fail extraction but the
# inspector will still produce a valid InspectedFile with FAILED extraction.
_MINIMAL_PDF_HEADER = b"%PDF-1.4\n%%EOF\n"

# Random binary bytes that do not match any known text encoding
_BINARY_DATA = bytes(range(256))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ai_categorize_side_effect(path_to_category: dict[str, str]):
    """Return a side_effect callable that maps filenames to CategorizationResult."""

    def _side_effect(file: InspectedFile, existing_record=None) -> CategorizationResult:
        filename = file.path.name
        category = path_to_category.get(filename, "Documents")
        return CategorizationResult(
            category=category,
            subcategory=None,
            confidence=0.95,
            method="ai",
            review_required=False,
            fallback_used=False,
        )

    return _side_effect


# ---------------------------------------------------------------------------
# Main integration test
# ---------------------------------------------------------------------------

class TestFullPipelineMixedFiles:
    """Full pipeline integration test over a synthetic directory."""

    def _build_source_dir(self, tmp_path: Path) -> tuple[Path, dict[str, str]]:
        """Create synthetic source files and return (source_dir, filename→category)."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        # 1. Plain text file  → Documents
        txt_file = source_dir / "readme.txt"
        txt_file.write_text("This is a sample text document.", encoding="utf-8")

        # 2. Minimal PDF stub → Documents
        pdf_file = source_dir / "report.pdf"
        pdf_file.write_bytes(_MINIMAL_PDF_HEADER)

        # 3. Minimal PNG image → Images
        png_file = source_dir / "photo.png"
        png_file.write_bytes(_MINIMAL_PNG)

        # 4. Binary/executable file → Executables
        bin_file = source_dir / "tool.bin"
        bin_file.write_bytes(_BINARY_DATA)

        filename_to_category = {
            "readme.txt": "Documents",
            "report.pdf": "Documents",
            "photo.png":  "Images",
            "tool.bin":   "Executables",
        }
        return source_dir, filename_to_category

    def test_all_files_moved_to_category_folders(self, tmp_path: Path) -> None:
        """Every source file ends up in organized/<Category>/ after Organizer.run()."""
        source_dir, filename_to_category = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_categorize_side_effect(filename_to_category),
        ):
            organizer = Organizer(config)
            summary = organizer.run()

        # Every file must have been moved out of source_dir
        for filename in filename_to_category:
            assert not (source_dir / filename).exists(), (
                f"{filename} was not moved out of source_dir"
            )

        # Each file must be under the correct category folder in target_dir
        for filename, category in filename_to_category.items():
            category_dir = target_dir / category
            # Walk the category dir to find the file (handles optional subcategory level)
            found = list(category_dir.rglob(filename))
            assert len(found) == 1, (
                f"Expected exactly one copy of {filename!r} under {category_dir}, "
                f"found {found}"
            )

        # RunSummary counts
        assert summary.total_discovered == 4
        assert summary.total_moved == 4
        assert summary.total_errors == 0
        assert summary.dry_run is False

    def test_metadata_json_written_with_all_records(self, tmp_path: Path) -> None:
        """organizer-metadata.json is created under target_dir and contains one record per file."""
        source_dir, filename_to_category = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_categorize_side_effect(filename_to_category),
        ):
            Organizer(config).run()

        metadata_path = target_dir / "organizer-metadata.json"
        assert metadata_path.exists(), "organizer-metadata.json was not created"

        # Must parse as valid JSON
        raw = metadata_path.read_text(encoding="utf-8")
        data = json.loads(raw)

        # Top-level structure
        assert "version" in data, "Missing 'version' key in metadata JSON"
        assert "records" in data, "Missing 'records' key in metadata JSON"

        records = data["records"]
        assert len(records) == 4, (
            f"Expected 4 records in metadata, got {len(records)}"
        )

        # Each record must carry the required fields defined in MetadataRecord
        required_fields = {
            "original_path", "destination_path", "sha256", "size_bytes",
            "mime_type", "text_snippet", "category", "subcategory",
            "confidence_score", "method", "review_required", "fallback_used",
            "extraction_status", "timestamp",
        }
        for key, record in records.items():
            missing = required_fields - set(record.keys())
            assert not missing, (
                f"Record for {key!r} is missing fields: {missing}"
            )
            assert record["sha256"], f"sha256 must not be empty for {key!r}"
            assert record["category"] in {"Documents", "Images", "Executables"}, (
                f"Unexpected category {record['category']!r} for {key!r}"
            )

    def test_organizer_log_written_with_valid_json_lines(self, tmp_path: Path) -> None:
        """organizer.log is created under target_dir; every line is valid JSON with
        the required fields (timestamp, level, path, action)."""
        source_dir, filename_to_category = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_categorize_side_effect(filename_to_category),
        ):
            Organizer(config).run()

        log_path = target_dir / "organizer.log"
        assert log_path.exists(), "organizer.log was not created"

        lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) > 0, "organizer.log must contain at least one entry"

        valid_levels = {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"}

        for i, line in enumerate(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                pytest.fail(f"Line {i + 1} of organizer.log is not valid JSON: {exc}\n  {line!r}")

            # Required fields per Requirement 9.5
            for field in ("timestamp", "level", "path", "action"):
                assert field in entry, (
                    f"Line {i + 1} missing required field {field!r}: {entry}"
                )

            assert entry["level"] in valid_levels, (
                f"Line {i + 1} has unexpected level {entry['level']!r}"
            )
            # Timestamp should not be empty
            assert entry["timestamp"], f"Line {i + 1} has empty timestamp"

    def test_run_summary_total_moved_equals_file_count(self, tmp_path: Path) -> None:
        """RunSummary.total_moved equals the number of source files when all moves succeed."""
        source_dir, filename_to_category = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_categorize_side_effect(filename_to_category),
        ):
            summary = Organizer(config).run()

        assert summary.total_moved == len(filename_to_category), (
            f"total_moved={summary.total_moved}, expected {len(filename_to_category)}"
        )
        assert summary.total_errors == 0

    def test_category_folders_created_in_target_dir(self, tmp_path: Path) -> None:
        """Category subdirectories (Documents, Images, Executables) are created under target_dir."""
        source_dir, filename_to_category = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_categorize_side_effect(filename_to_category),
        ):
            Organizer(config).run()

        for category in {"Documents", "Images", "Executables"}:
            assert (target_dir / category).is_dir(), (
                f"Expected category folder {category!r} to exist under target_dir"
            )

    def test_no_review_files_when_all_confidence_high(self, tmp_path: Path) -> None:
        """When AI returns confidence=0.95 for all files, none end up in _review/."""
        source_dir, filename_to_category = self._build_source_dir(tmp_path)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            min_confidence=0.5,
            ai_api_key="test-key",
        )

        with patch(
            "folder_organizer.categorizer.AICategorizer._ai_categorize",
            side_effect=_make_ai_categorize_side_effect(filename_to_category),
        ):
            summary = Organizer(config).run()

        review_dir = target_dir / "_review"
        if review_dir.exists():
            review_files = list(review_dir.iterdir())
            assert len(review_files) == 0, (
                f"Expected no files in _review/, found: {review_files}"
            )

        assert summary.total_review == 0
