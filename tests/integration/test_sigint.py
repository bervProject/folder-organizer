"""Integration test — SIGINT mid-run produces a partial metadata flush.

Verifies that when SIGINT is received while the organizer is processing files,
the OrganizerLogger._handle_sigint handler flushes whatever MetadataStore
records have been upserted so far and exits with code 130.

Requirements: 9.4

Implementation strategy
-----------------------
``os.kill(os.getpid(), signal.SIGINT)`` on Windows generates CTRL_C_EVENT
which does NOT invoke Python's custom signal handler (the handler installed by
``OrganizerLogger``).

``signal.raise_signal(signal.SIGINT)`` (Python ≥ 3.8) *does* invoke Python's
signal handler synchronously from C, raising the ``SystemExit(130)`` that the
organizer's handler fires.  We catch that exception with ``pytest.raises`` and
inspect the resulting partial metadata file.
"""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from folder_organizer.config import Config
from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import CategorizationResult
from folder_organizer.organizer import Organizer


# ---------------------------------------------------------------------------
# Helper: build a source directory with N simple text files
# ---------------------------------------------------------------------------

def _build_source_dir(tmp_path: Path, file_count: int = 6) -> Path:
    """Create *file_count* plain-text files in a fresh source directory."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for i in range(file_count):
        (source_dir / f"file_{i:02d}.txt").write_text(
            f"Sample text content for file {i}.", encoding="utf-8"
        )
    return source_dir


# ---------------------------------------------------------------------------
# Helper: build a simple AI stub
# ---------------------------------------------------------------------------

def _make_ai_stub(category: str = "Documents", confidence: float = 0.95):
    """Return a side_effect callable that always returns a fixed result."""

    def _side_effect(file, existing_record=None) -> CategorizationResult:
        return CategorizationResult(
            category=category,
            subcategory=None,
            confidence=confidence,
            method="ai",
            review_required=False,
            fallback_used=False,
        )

    return _side_effect


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSigintPartialFlush:
    """SIGINT mid-run causes a partial metadata flush and exit with code 130.

    Each test injects SIGINT by patching ``MetadataStore.upsert`` to call
    ``signal.raise_signal(signal.SIGINT)`` after N records have been stored.
    By the time upsert fires, the FileMover has already moved that file and the
    MetadataStore has the record in memory, so the SIGINT handler's flush call
    writes those records to disk.
    """

    def test_sigint_produces_partial_metadata_flush(self, tmp_path: Path) -> None:
        """organizer-metadata.json exists after SIGINT and contains at least
        the records for the files processed before the interrupt."""
        source_dir = _build_source_dir(tmp_path, file_count=6)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        upsert_count = 0
        original_upsert = MetadataStore.upsert

        def patched_upsert(self_store: MetadataStore, record) -> None:
            nonlocal upsert_count
            original_upsert(self_store, record)
            upsert_count += 1
            if upsert_count == 2:
                # signal.raise_signal invokes the Python-level handler
                # synchronously, so the OrganizerLogger._handle_sigint fires
                # and raises SystemExit(130) right here.
                signal.raise_signal(signal.SIGINT)

        with pytest.raises(SystemExit) as exc_info:
            with patch(
                "folder_organizer.categorizer.AICategorizer._ai_categorize",
                side_effect=_make_ai_stub(),
            ), patch.object(MetadataStore, "upsert", patched_upsert):
                Organizer(config).run()

        # Handler must exit with code 130 (Requirement 9.4)
        assert exc_info.value.code == 130, (
            f"Expected exit code 130, got {exc_info.value.code}"
        )

        # organizer-metadata.json must have been written by the SIGINT handler
        metadata_path = target_dir / "organizer-metadata.json"
        assert metadata_path.exists(), (
            "organizer-metadata.json was not created by the SIGINT flush"
        )

        raw = metadata_path.read_text(encoding="utf-8")
        data = json.loads(raw)

        assert "version" in data, "Missing 'version' key in metadata JSON"
        assert "records" in data, "Missing 'records' key in metadata JSON"

        records = data["records"]
        # At least 2 records were upserted before SIGINT
        assert len(records) >= 2, (
            f"Expected at least 2 records in partial metadata, got {len(records)}"
        )

        # Every record must carry all required MetadataRecord fields
        required_fields = {
            "original_path", "destination_path", "sha256", "size_bytes",
            "mime_type", "text_snippet", "category", "subcategory",
            "confidence_score", "method", "review_required", "fallback_used",
            "extraction_status", "timestamp",
        }
        for key, record in records.items():
            missing = required_fields - set(record.keys())
            assert not missing, (
                f"Record {key!r} is missing required fields: {missing}"
            )

    def test_sigint_exit_code_is_130(self, tmp_path: Path) -> None:
        """SIGINT always produces exit code 130 (Requirement 9.4)."""
        source_dir = _build_source_dir(tmp_path, file_count=4)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        upsert_count = 0
        original_upsert = MetadataStore.upsert

        def patched_upsert(self_store: MetadataStore, record) -> None:
            nonlocal upsert_count
            original_upsert(self_store, record)
            upsert_count += 1
            if upsert_count == 1:
                signal.raise_signal(signal.SIGINT)

        with pytest.raises(SystemExit) as exc_info:
            with patch(
                "folder_organizer.categorizer.AICategorizer._ai_categorize",
                side_effect=_make_ai_stub(),
            ), patch.object(MetadataStore, "upsert", patched_upsert):
                Organizer(config).run()

        assert exc_info.value.code == 130, (
            f"Expected exit code 130, got {exc_info.value.code}"
        )

    def test_sigint_metadata_records_have_correct_values(
        self, tmp_path: Path
    ) -> None:
        """Records flushed on SIGINT carry correct category, sha256 and
        confidence values, and the count matches exactly N upserts."""
        source_dir = _build_source_dir(tmp_path, file_count=5)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        upsert_count = 0
        original_upsert = MetadataStore.upsert

        def patched_upsert(self_store: MetadataStore, record) -> None:
            nonlocal upsert_count
            original_upsert(self_store, record)
            upsert_count += 1
            if upsert_count == 3:
                signal.raise_signal(signal.SIGINT)

        with pytest.raises(SystemExit):
            with patch(
                "folder_organizer.categorizer.AICategorizer._ai_categorize",
                side_effect=_make_ai_stub(confidence=0.88),
            ), patch.object(MetadataStore, "upsert", patched_upsert):
                Organizer(config).run()

        metadata_path = target_dir / "organizer-metadata.json"
        assert metadata_path.exists(), (
            "organizer-metadata.json was not created by the SIGINT flush"
        )

        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        records = data["records"]

        # Exactly 3 records were upserted before the SIGINT
        assert len(records) == 3, (
            f"Expected exactly 3 records flushed, got {len(records)}"
        )

        for key, record in records.items():
            assert record["category"] == "Documents", (
                f"Expected category 'Documents', got {record['category']!r}"
            )
            assert record["sha256"], (
                f"sha256 must not be empty for record {key!r}"
            )
            assert abs(record["confidence_score"] - 0.88) < 1e-6, (
                f"Unexpected confidence_score for record {key!r}: "
                f"{record['confidence_score']}"
            )

    def test_sigint_during_categorize_flushes_empty_store(
        self, tmp_path: Path
    ) -> None:
        """When SIGINT fires before any file is moved (no upserts yet), the
        SIGINT handler still runs, exits with 130, and the metadata file either
        does not exist or contains zero records.

        This validates the handler fires correctly even on an empty store.
        """
        source_dir = _build_source_dir(tmp_path, file_count=4)
        target_dir = tmp_path / "organized"

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        # Send SIGINT on the first _ai_categorize call — before any file has
        # been moved and before any MetadataStore.upsert has been called.
        call_count = 0

        def ai_side_effect(file, existing_record=None) -> CategorizationResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                signal.raise_signal(signal.SIGINT)
            return CategorizationResult(
                category="Documents",
                subcategory=None,
                confidence=0.95,
                method="ai",
                review_required=False,
                fallback_used=False,
            )

        with pytest.raises(SystemExit) as exc_info:
            with patch(
                "folder_organizer.categorizer.AICategorizer._ai_categorize",
                side_effect=ai_side_effect,
            ):
                Organizer(config).run()

        # Must still exit 130
        assert exc_info.value.code == 130, (
            f"Expected exit code 130, got {exc_info.value.code}"
        )

        # If the file exists it must be valid JSON with an empty records dict
        metadata_path = target_dir / "organizer-metadata.json"
        if metadata_path.exists():
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            assert len(data.get("records", {})) == 0, (
                "Expected zero records when SIGINT fires before any upsert, "
                f"got {len(data.get('records', {}))}"
            )
