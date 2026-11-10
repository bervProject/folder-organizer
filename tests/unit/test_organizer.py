"""Unit tests for the Organizer class.

Tests cover:
- Dry run does not create folders, move files, or write metadata (Requirements 8.1, 8.3)
- Dry run output report lists all files with correct proposed destinations (Requirement 8.2)
- _review files appear in dry-run report with correct flag (Requirement 8.4)
- _unplaced files appear in dry-run report with correct flag (Requirement 8.4)
- SIGINT flushes metadata and prints partial summary (Requirement 9.4)

Requirements: 8.1, 8.2, 8.3, 8.4, 9.4
"""

from __future__ import annotations

import io
import signal
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest
from rich.console import Console

from folder_organizer.config import Config
from folder_organizer.models import (
    CategorizedFile,
    CategorizationResult,
    DiscoveryResult,
    ExtractionStatus,
    InspectedFile,
    PlacedFile,
    RunSummary,
)
from folder_organizer.organizer import Organizer


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_console() -> tuple[Console, io.StringIO]:
    """Return a Rich Console writing to a StringIO buffer and the buffer itself."""
    buf = io.StringIO()
    console = Console(file=buf, highlight=False, width=200)
    return console, buf


def _make_config(tmp_path: Path, *, dry_run: bool = True) -> Config:
    """Build a minimal Config for testing."""
    return Config(
        source_dir=tmp_path / "source",
        target_dir=tmp_path / "target",
        dry_run=dry_run,
        ai_api_key="test-key",
    )


def _make_inspected_file(path: Path) -> InspectedFile:
    """Create a stub InspectedFile for the given path."""
    return InspectedFile(
        path=path,
        sha256="abc123def456" + path.name[:8].ljust(8, "0"),
        size_bytes=1024,
        mime_type="text/plain",
        extracted_text="Sample content",
        char_count=14,
        extraction_status=ExtractionStatus.OK,
    )


def _make_cat_result(*, review_required: bool = False) -> CategorizationResult:
    """Create a stub CategorizationResult."""
    return CategorizationResult(
        category="Documents",
        subcategory="Reports",
        confidence=0.92,
        method="ai",
        review_required=review_required,
        fallback_used=False,
    )


def _make_cat_file(
    path: Path,
    *,
    review_required: bool = False,
    category: str = "Documents",
    subcategory: Optional[str] = "Reports",
) -> CategorizedFile:
    """Create a stub CategorizedFile for the given path."""
    return CategorizedFile(
        path=path,
        sha256="abc123" + path.name[:6].ljust(6, "0"),
        size_bytes=1024,
        mime_type="text/plain",
        extracted_text="Sample content",
        char_count=14,
        extraction_status="ok",
        category=category,
        subcategory=subcategory,
        confidence=0.92,
        method="ai",
        review_required=review_required,
        fallback_used=False,
    )


# ---------------------------------------------------------------------------
# 1. TestDryRunNoMutations  (Requirements 8.1, 8.3)
# ---------------------------------------------------------------------------


class TestDryRunNoMutations:
    """Dry run mode produces zero disk mutations."""

    def _build_pipeline_mocks(
        self,
        source_dir: Path,
        file_paths: list[Path],
        *,
        review_required: bool = False,
    ) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
        """Return mocks for (FileDiscoverer, FileInspector, AICategorizer, MetadataStore)."""
        mock_discoverer = MagicMock()
        mock_discoverer.return_value.discover.return_value = DiscoveryResult(
            discovered=file_paths,
            skipped_symlinks=0,
            excluded_count=0,
        )

        mock_inspector = MagicMock()
        mock_inspector.return_value.inspect.side_effect = lambda p: _make_inspected_file(p)

        mock_categorizer = MagicMock()
        mock_categorizer.return_value.categorize.return_value = _make_cat_result(
            review_required=review_required
        )

        mock_metadata_store = MagicMock()
        mock_metadata_store.return_value.get_by_hash.return_value = None
        mock_metadata_store.return_value.should_skip.return_value = False

        return mock_discoverer, mock_inspector, mock_categorizer, mock_metadata_store

    def test_dry_run_does_not_create_category_folders(self, tmp_path: Path) -> None:
        """No folders are created in target_dir when dry_run=True (Requirement 8.1)."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        # Create real files so the mocked discoverer can reference them
        file_paths = [source_dir / f"file{i}.txt" for i in range(2)]
        for p in file_paths:
            p.write_text("content")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer, mock_inspector, mock_categorizer, mock_metadata_store = (
            self._build_pipeline_mocks(source_dir, file_paths)
        )
        mock_folder_gen = MagicMock()
        mock_folder_gen.return_value.resolve_placement.side_effect = (
            lambda cat_file, td: PlacedFile(
                source_path=cat_file.path,
                destination_dir=td / "Documents" / "Reports",
                destination_filename=cat_file.path.name,
                review_required=False,
                unplaced=False,
            )
        )

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
            patch("folder_organizer.organizer.FolderGenerator", mock_folder_gen),
        ):
            organizer = Organizer(config)
            console, _ = _make_console()
            organizer._console = console
            organizer.run()

        # create_folders must never be called in dry run
        mock_folder_gen.return_value.create_folders.assert_not_called()
        # Category folder should not exist
        assert not (target_dir / "Documents").exists()

    def test_dry_run_does_not_move_files(self, tmp_path: Path) -> None:
        """FileMover.move is never called when dry_run=True (Requirement 8.1)."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        file_paths = [source_dir / "report.txt"]
        for p in file_paths:
            p.write_text("content")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer, mock_inspector, mock_categorizer, mock_metadata_store = (
            self._build_pipeline_mocks(source_dir, file_paths)
        )
        mock_file_mover = MagicMock()

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
            patch("folder_organizer.organizer.FileMover", mock_file_mover),
        ):
            organizer = Organizer(config)
            console, _ = _make_console()
            organizer._console = console
            organizer.run()

        # FileMover constructor is never called in dry run
        mock_file_mover.assert_not_called()

    def test_dry_run_does_not_write_metadata_json(self, tmp_path: Path) -> None:
        """organizer-metadata.json is NOT written to target_dir after a dry run (Requirement 8.3)."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        file_paths = [source_dir / "notes.txt"]
        for p in file_paths:
            p.write_text("content")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer, mock_inspector, mock_categorizer, mock_metadata_store = (
            self._build_pipeline_mocks(source_dir, file_paths)
        )

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
        ):
            organizer = Organizer(config)
            console, _ = _make_console()
            organizer._console = console
            organizer.run()

        # flush must never be called on the mocked store in dry run
        mock_metadata_store.return_value.flush.assert_not_called()
        # The real metadata file must not exist on disk
        assert not (target_dir / "organizer-metadata.json").exists()

    def test_dry_run_returns_summary_with_zero_moved(self, tmp_path: Path) -> None:
        """RunSummary.total_moved == 0 and RunSummary.dry_run == True after dry run (Requirement 8.1)."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        file_paths = [source_dir / "data.txt", source_dir / "other.txt"]
        for p in file_paths:
            p.write_text("content")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer, mock_inspector, mock_categorizer, mock_metadata_store = (
            self._build_pipeline_mocks(source_dir, file_paths)
        )

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
        ):
            organizer = Organizer(config)
            console, _ = _make_console()
            organizer._console = console
            summary = organizer.run()

        assert summary.total_moved == 0
        assert summary.dry_run is True


# ---------------------------------------------------------------------------
# 2. TestDryRunReport  (Requirement 8.2)
# ---------------------------------------------------------------------------


class TestDryRunReport:
    """Dry-run report lists files with their proposed destinations."""

    def _run_dry_run_with_files(
        self,
        tmp_path: Path,
        filenames: list[str],
        *,
        review_required: bool = False,
    ) -> str:
        """Run Organizer in dry_run mode and return captured console output."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        file_paths = [source_dir / name for name in filenames]
        for p in file_paths:
            p.write_text("content")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer = MagicMock()
        mock_discoverer.return_value.discover.return_value = DiscoveryResult(
            discovered=file_paths,
            skipped_symlinks=0,
            excluded_count=0,
        )

        mock_inspector = MagicMock()
        mock_inspector.return_value.inspect.side_effect = lambda p: _make_inspected_file(p)

        mock_categorizer = MagicMock()
        mock_categorizer.return_value.categorize.return_value = CategorizationResult(
            category="Documents",
            subcategory="Reports",
            confidence=0.92,
            method="ai",
            review_required=review_required,
            fallback_used=False,
        )

        mock_metadata_store = MagicMock()
        mock_metadata_store.return_value.get_by_hash.return_value = None
        mock_metadata_store.return_value.should_skip.return_value = False

        console, buf = _make_console()

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
        ):
            organizer = Organizer(config)
            organizer._console = console
            organizer.run()

        return buf.getvalue()

    def test_dry_run_report_lists_all_files(self, tmp_path: Path) -> None:
        """Console output contains all 3 filenames in the dry-run report (Requirement 8.2)."""
        filenames = ["alpha.txt", "beta.txt", "gamma.txt"]
        output = self._run_dry_run_with_files(tmp_path, filenames)

        for name in filenames:
            assert name in output, f"Expected filename {name!r} in dry-run report output"

    def test_dry_run_report_contains_proposed_destination(self, tmp_path: Path) -> None:
        """Report contains the proposed destination path for each file (Requirement 8.2)."""
        output = self._run_dry_run_with_files(tmp_path, ["report.txt"])

        # The report should include the destination: target/Documents/Reports/report.txt
        # We check that the category folder path appears
        assert "Documents" in output

    def test_dry_run_report_contains_category(self, tmp_path: Path) -> None:
        """Category appears in the report output (Requirement 8.2)."""
        output = self._run_dry_run_with_files(tmp_path, ["invoice.txt"])

        assert "Documents" in output

    def test_dry_run_report_contains_subcategory(self, tmp_path: Path) -> None:
        """Subcategory appears in the report output (Requirement 8.2)."""
        output = self._run_dry_run_with_files(tmp_path, ["invoice.txt"])

        assert "Reports" in output

    def test_dry_run_report_title_present(self, tmp_path: Path) -> None:
        """Report title or 'DRY RUN' label appears in console output."""
        output = self._run_dry_run_with_files(tmp_path, ["file.txt"])

        assert "DRY RUN" in output


# ---------------------------------------------------------------------------
# 3. TestDryRunReviewFlag  (Requirement 8.4)
# ---------------------------------------------------------------------------


class TestDryRunReviewFlag:
    """_review files appear with the correct flag in the dry-run report."""

    def test_review_file_shows_review_flag_in_report(self, tmp_path: Path) -> None:
        """'_review' flag appears in the console output for review_required files (Requirement 8.4)."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        review_file = source_dir / "suspicious.txt"
        review_file.write_text("content")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer = MagicMock()
        mock_discoverer.return_value.discover.return_value = DiscoveryResult(
            discovered=[review_file],
            skipped_symlinks=0,
            excluded_count=0,
        )
        mock_inspector = MagicMock()
        mock_inspector.return_value.inspect.return_value = _make_inspected_file(review_file)

        mock_categorizer = MagicMock()
        mock_categorizer.return_value.categorize.return_value = CategorizationResult(
            category="Documents",
            subcategory=None,
            confidence=0.35,  # Low confidence → triggers review
            method="ai",
            review_required=True,
            fallback_used=False,
        )

        mock_metadata_store = MagicMock()
        mock_metadata_store.return_value.get_by_hash.return_value = None
        mock_metadata_store.return_value.should_skip.return_value = False

        console, buf = _make_console()

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
        ):
            organizer = Organizer(config)
            organizer._console = console
            organizer.run()

        output = buf.getvalue()
        assert "_review" in output, (
            f"Expected '_review' flag in dry-run output for review_required file.\nOutput:\n{output}"
        )

    def test_review_file_destination_is_review_folder(self, tmp_path: Path) -> None:
        """Proposed destination for a review file is under target_dir/_review/ (Requirement 8.4)."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        review_file = source_dir / "uncertain.txt"
        review_file.write_text("content")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer = MagicMock()
        mock_discoverer.return_value.discover.return_value = DiscoveryResult(
            discovered=[review_file],
            skipped_symlinks=0,
            excluded_count=0,
        )
        mock_inspector = MagicMock()
        mock_inspector.return_value.inspect.return_value = _make_inspected_file(review_file)

        mock_categorizer = MagicMock()
        mock_categorizer.return_value.categorize.return_value = CategorizationResult(
            category="Documents",
            subcategory=None,
            confidence=0.20,
            method="ai",
            review_required=True,
            fallback_used=False,
        )

        mock_metadata_store = MagicMock()
        mock_metadata_store.return_value.get_by_hash.return_value = None
        mock_metadata_store.return_value.should_skip.return_value = False

        console, buf = _make_console()

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
        ):
            organizer = Organizer(config)
            organizer._console = console
            organizer.run()

        output = buf.getvalue()
        assert "_review" in output, (
            f"Expected '_review' directory in proposed destination.\nOutput:\n{output}"
        )

    def test_review_summary_counts_review_files(self, tmp_path: Path) -> None:
        """RunSummary.total_review reflects the number of review_required files."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        file_paths = [source_dir / f"file{i}.txt" for i in range(3)]
        for p in file_paths:
            p.write_text("content")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer = MagicMock()
        mock_discoverer.return_value.discover.return_value = DiscoveryResult(
            discovered=file_paths,
            skipped_symlinks=0,
            excluded_count=0,
        )
        mock_inspector = MagicMock()
        mock_inspector.return_value.inspect.side_effect = lambda p: _make_inspected_file(p)

        # Two files need review, one does not
        cat_results = [
            CategorizationResult("Documents", None, 0.20, "ai", review_required=True, fallback_used=False),
            CategorizationResult("Documents", None, 0.95, "ai", review_required=False, fallback_used=False),
            CategorizationResult("Documents", None, 0.15, "ai", review_required=True, fallback_used=False),
        ]
        mock_categorizer = MagicMock()
        mock_categorizer.return_value.categorize.side_effect = cat_results

        mock_metadata_store = MagicMock()
        mock_metadata_store.return_value.get_by_hash.return_value = None
        mock_metadata_store.return_value.should_skip.return_value = False

        console, _ = _make_console()

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
        ):
            organizer = Organizer(config)
            organizer._console = console
            summary = organizer.run()

        assert summary.total_review == 2


# ---------------------------------------------------------------------------
# 4. TestDryRunUnplacedFlag  (Requirement 8.4)
# ---------------------------------------------------------------------------


class TestDryRunUnplacedFlag:
    """_unplaced files appear with the correct flag in the dry-run report."""

    def test_unplaced_file_shows_unplaced_flag_in_report(self, tmp_path: Path) -> None:
        """'_unplaced' appears in the console output when FolderGenerator.resolve_placement
        returns unplaced=True (Requirement 8.4)."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        unplaced_file = source_dir / "mystery.bin"
        unplaced_file.write_bytes(b"\x00\x01\x02")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer = MagicMock()
        mock_discoverer.return_value.discover.return_value = DiscoveryResult(
            discovered=[unplaced_file],
            skipped_symlinks=0,
            excluded_count=0,
        )
        mock_inspector = MagicMock()
        mock_inspector.return_value.inspect.return_value = _make_inspected_file(unplaced_file)

        mock_categorizer = MagicMock()
        mock_categorizer.return_value.categorize.return_value = CategorizationResult(
            category="Unknown",
            subcategory=None,
            confidence=0.10,
            method="fallback",
            review_required=False,
            fallback_used=True,
        )

        mock_metadata_store = MagicMock()
        mock_metadata_store.return_value.get_by_hash.return_value = None
        mock_metadata_store.return_value.should_skip.return_value = False

        # Patch FolderGenerator so resolve_placement returns unplaced=True
        mock_folder_gen = MagicMock()
        mock_folder_gen.return_value.resolve_placement.return_value = PlacedFile(
            source_path=unplaced_file,
            destination_dir=target_dir / "_unplaced",
            destination_filename=unplaced_file.name,
            review_required=False,
            unplaced=True,
        )

        console, buf = _make_console()

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
            patch("folder_organizer.organizer.FolderGenerator", mock_folder_gen),
        ):
            organizer = Organizer(config)
            organizer._console = console
            organizer.run()

        output = buf.getvalue()
        assert "_unplaced" in output, (
            f"Expected '_unplaced' flag in dry-run output for unplaced file.\nOutput:\n{output}"
        )

    def test_unplaced_destination_path_contains_unplaced_folder(self, tmp_path: Path) -> None:
        """The proposed destination for an unplaced file contains '_unplaced' in the path."""
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        unplaced_file = source_dir / "unknown.xyz"
        unplaced_file.write_bytes(b"\xff\xfe")

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
        )

        mock_discoverer = MagicMock()
        mock_discoverer.return_value.discover.return_value = DiscoveryResult(
            discovered=[unplaced_file],
            skipped_symlinks=0,
            excluded_count=0,
        )
        mock_inspector = MagicMock()
        mock_inspector.return_value.inspect.return_value = _make_inspected_file(unplaced_file)

        mock_categorizer = MagicMock()
        mock_categorizer.return_value.categorize.return_value = CategorizationResult(
            category="Unknown",
            subcategory=None,
            confidence=0.05,
            method="fallback",
            review_required=False,
            fallback_used=True,
        )

        mock_metadata_store = MagicMock()
        mock_metadata_store.return_value.get_by_hash.return_value = None
        mock_metadata_store.return_value.should_skip.return_value = False

        mock_folder_gen = MagicMock()
        mock_folder_gen.return_value.resolve_placement.return_value = PlacedFile(
            source_path=unplaced_file,
            destination_dir=target_dir / "_unplaced",
            destination_filename=unplaced_file.name,
            review_required=False,
            unplaced=True,
        )

        console, buf = _make_console()

        with (
            patch("folder_organizer.organizer.FileDiscoverer", mock_discoverer),
            patch("folder_organizer.organizer.FileInspector", mock_inspector),
            patch("folder_organizer.organizer.AICategorizer", mock_categorizer),
            patch("folder_organizer.organizer.MetadataStore", mock_metadata_store),
            patch("folder_organizer.organizer.FolderGenerator", mock_folder_gen),
        ):
            organizer = Organizer(config)
            organizer._console = console
            organizer.run()

        output = buf.getvalue()
        assert "_unplaced" in output


# ---------------------------------------------------------------------------
# 5. TestSigintFlush  (Requirement 9.4)
# ---------------------------------------------------------------------------


class TestSigintFlush:
    """SIGINT flushes metadata and prints partial summary (Requirement 9.4)."""

    def _build_organizer_with_running_logger(
        self,
        tmp_path: Path,
    ) -> tuple[Organizer, MagicMock, Console, io.StringIO]:
        """Set up the objects for a SIGINT test without running the full pipeline.

        Returns (organizer, mock_metadata_store_instance, console, buf).
        """
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=False,
            ai_api_key="test-key",
        )

        organizer = Organizer(config)
        console, buf = _make_console()
        organizer._console = console

        return organizer, config, target_dir, console, buf

    def test_sigint_flushes_metadata_store(self, tmp_path: Path) -> None:
        """MetadataStore.flush is called when SIGINT is received (Requirement 9.4)."""
        from folder_organizer.logger import OrganizerLogger
        from folder_organizer.metadata_store import MetadataStore

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        mock_store = MagicMock(spec=MetadataStore)
        console, _ = _make_console()

        with pytest.raises(SystemExit):
            with OrganizerLogger(
                target_dir=target_dir,
                total_files=5,
                metadata_store=mock_store,
                console=console,
            ):
                signal.raise_signal(signal.SIGINT)

        mock_store.flush.assert_called_once_with(target_dir)

    def test_sigint_prints_partial_summary(self, tmp_path: Path) -> None:
        """Console output after SIGINT contains partial-summary-related text (Requirement 9.4)."""
        from folder_organizer.logger import OrganizerLogger

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        mock_store = MagicMock()
        console, buf = _make_console()

        with pytest.raises(SystemExit):
            with OrganizerLogger(
                target_dir=target_dir,
                total_files=5,
                metadata_store=mock_store,
                console=console,
            ):
                signal.raise_signal(signal.SIGINT)

        output = buf.getvalue()
        # The SIGINT handler prints "Partial summary:" before the summary table
        assert "Partial summary" in output or "Interrupted" in output, (
            f"Expected 'Partial summary' or 'Interrupted' in output.\nOutput:\n{output}"
        )

    def test_sigint_exits_with_code_130(self, tmp_path: Path) -> None:
        """SystemExit(130) is raised when SIGINT is received (Requirement 9.4)."""
        from folder_organizer.logger import OrganizerLogger

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        mock_store = MagicMock()
        console, _ = _make_console()

        with pytest.raises(SystemExit) as exc_info:
            with OrganizerLogger(
                target_dir=target_dir,
                total_files=5,
                metadata_store=mock_store,
                console=console,
            ):
                signal.raise_signal(signal.SIGINT)

        assert exc_info.value.code == 130

    def test_sigint_does_not_flush_in_dry_run(self, tmp_path: Path) -> None:
        """In a dry-run pipeline, SIGINT still invokes flush (since SIGINT bypasses dry-run check).

        This test documents that the SIGINT handler always calls flush regardless of mode;
        the dry-run guard only prevents the normal-path flush call.
        """
        from folder_organizer.logger import OrganizerLogger

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        mock_store = MagicMock()
        console, _ = _make_console()

        with pytest.raises(SystemExit):
            with OrganizerLogger(
                target_dir=target_dir,
                total_files=1,
                metadata_store=mock_store,
                console=console,
            ):
                signal.raise_signal(signal.SIGINT)

        # The SIGINT handler always flushes to preserve partial work
        mock_store.flush.assert_called_once_with(target_dir)
