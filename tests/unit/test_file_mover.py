"""Unit tests for FileMover.

Tests cover:
- File moved to correct destination
- Conflict suffix appended correctly (report_1.pdf, report_2.pdf, ...)
- Suffix exhaustion at 9,999 logs error and skips file
- PermissionError logs error, skips file, continues
- OSError logs error, skips file, continues
- Dry run returns resolved path without I/O

Requirements: 7.1, 7.2, 7.4, 7.6
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from folder_organizer.file_mover import FileMover
from folder_organizer.models import PlacedFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_placed(source: Path, dest_dir: Path, filename: str | None = None) -> PlacedFile:
    """Build a PlacedFile pointing source → dest_dir."""
    return PlacedFile(
        source_path=source,
        destination_dir=dest_dir,
        destination_filename=filename or source.name,
        review_required=False,
        unplaced=False,
    )


# ---------------------------------------------------------------------------
# 1. File moved to correct destination  (Req 7.1)
# ---------------------------------------------------------------------------

class TestFileMoverBasicMove:
    """Basic successful move behaviour."""

    def test_file_moved_to_destination_dir(self, tmp_path: Path) -> None:
        """A plain move: source file lands in the destination directory."""
        src = tmp_path / "source"
        src_file = src / "report.pdf"
        src.mkdir()
        src_file.write_bytes(b"content")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        placed = _make_placed(src_file, dest_dir, "report.pdf")
        result = FileMover(dry_run=False).move(placed)

        assert result.success is True
        assert result.destination_path == dest_dir / "report.pdf"
        assert (dest_dir / "report.pdf").exists()
        assert not src_file.exists()

    def test_move_result_source_path_recorded(self, tmp_path: Path) -> None:
        """MoveResult.source_path always reflects the original source path."""
        src_file = tmp_path / "notes.txt"
        src_file.write_text("hello")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        placed = _make_placed(src_file, dest_dir)
        result = FileMover().move(placed)

        assert result.source_path == src_file

    def test_move_with_different_filename(self, tmp_path: Path) -> None:
        """destination_filename controls the final name, not the source name."""
        src_file = tmp_path / "original.txt"
        src_file.write_bytes(b"data")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        placed = _make_placed(src_file, dest_dir, "renamed.txt")
        result = FileMover().move(placed)

        assert result.success is True
        assert (dest_dir / "renamed.txt").exists()

    def test_skip_reason_is_none_on_success(self, tmp_path: Path) -> None:
        """skip_reason is None when the move succeeds."""
        src_file = tmp_path / "a.pdf"
        src_file.write_bytes(b"pdf")
        dest_dir = tmp_path / "d"
        dest_dir.mkdir()

        result = FileMover().move(_make_placed(src_file, dest_dir))
        assert result.skip_reason is None


# ---------------------------------------------------------------------------
# 2. Conflict suffix appended correctly  (Req 7.2)
# ---------------------------------------------------------------------------

class TestConflictResolution:
    """Conflict suffix behaviour — _1, _2, … appended before extension."""

    def test_first_conflict_gets_suffix_1(self, tmp_path: Path) -> None:
        """When destination already exists, the moved file gets suffix _1."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"new")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        # Pre-create the conflict
        (dest_dir / "report.pdf").write_bytes(b"existing")

        result = FileMover().move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert result.success is True
        assert result.destination_path == dest_dir / "report_1.pdf"
        assert (dest_dir / "report_1.pdf").exists()
        assert (dest_dir / "report.pdf").exists()  # original untouched

    def test_second_conflict_gets_suffix_2(self, tmp_path: Path) -> None:
        """When both dest and dest_1 exist, the moved file gets suffix _2."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"newest")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        (dest_dir / "report.pdf").write_bytes(b"first")
        (dest_dir / "report_1.pdf").write_bytes(b"second")

        result = FileMover().move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert result.success is True
        assert result.destination_path == dest_dir / "report_2.pdf"

    def test_conflict_resolution_no_extension(self, tmp_path: Path) -> None:
        """Conflict suffix still works for files without an extension."""
        src_file = tmp_path / "MAKEFILE"
        src_file.write_bytes(b"build")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        (dest_dir / "MAKEFILE").write_bytes(b"original")

        result = FileMover().move(_make_placed(src_file, dest_dir, "MAKEFILE"))

        assert result.success is True
        assert result.destination_path == dest_dir / "MAKEFILE_1"

    def test_sequential_moves_produce_ascending_suffixes(self, tmp_path: Path) -> None:
        """Moving multiple files with the same name produces _1, _2, _3 in order."""
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        # First file — no conflict
        f0 = tmp_path / "doc0.txt"
        f0.write_bytes(b"0")
        r0 = FileMover().move(_make_placed(f0, dest_dir, "doc.txt"))
        assert r0.destination_path == dest_dir / "doc.txt"

        # Second file — conflict with doc.txt → doc_1.txt
        f1 = tmp_path / "doc1.txt"
        f1.write_bytes(b"1")
        r1 = FileMover().move(_make_placed(f1, dest_dir, "doc.txt"))
        assert r1.destination_path == dest_dir / "doc_1.txt"

        # Third file — conflict with doc.txt and doc_1.txt → doc_2.txt
        f2 = tmp_path / "doc2.txt"
        f2.write_bytes(b"2")
        r2 = FileMover().move(_make_placed(f2, dest_dir, "doc.txt"))
        assert r2.destination_path == dest_dir / "doc_2.txt"


# ---------------------------------------------------------------------------
# 3. Suffix exhaustion at 9,999 logs error and skips file  (Req 7.6)
# ---------------------------------------------------------------------------

class TestConflictExhaustion:
    """_resolve_conflict returns None → error logged, file skipped."""

    def test_suffix_exhaustion_returns_failure(self, tmp_path: Path) -> None:
        """When _resolve_conflict returns None, move returns success=False."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"data")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        (dest_dir / "report.pdf").write_bytes(b"existing")

        mover = FileMover()
        with patch.object(mover, "_resolve_conflict", return_value=None):
            result = mover.move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert result.success is False
        assert result.skip_reason == "conflict_exhausted"
        assert result.destination_path is None

    def test_suffix_exhaustion_logs_error(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """When conflict suffixes are exhausted, an error is logged."""
        import logging

        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"data")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        (dest_dir / "report.pdf").write_bytes(b"conflict")

        mover = FileMover()
        with patch.object(mover, "_resolve_conflict", return_value=None):
            with caplog.at_level(logging.ERROR, logger="folder_organizer.file_mover"):
                mover.move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert any("conflict" in msg.lower() or "exhausted" in msg.lower() for msg in caplog.messages)

    def test_suffix_exhaustion_source_file_not_moved(self, tmp_path: Path) -> None:
        """When suffixes are exhausted, the source file is left untouched."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"data")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        (dest_dir / "report.pdf").write_bytes(b"conflict")

        mover = FileMover()
        with patch.object(mover, "_resolve_conflict", return_value=None):
            mover.move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert src_file.exists(), "Source should be untouched when move is skipped"


# ---------------------------------------------------------------------------
# 4. PermissionError / OSError logs error, skips file, continues  (Req 7.4)
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Error handling: PermissionError and OSError are caught gracefully."""

    def test_permission_error_returns_failure(self, tmp_path: Path) -> None:
        """PermissionError during shutil.move → success=False, no exception raised."""
        src_file = tmp_path / "secret.pdf"
        src_file.write_bytes(b"data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        placed = _make_placed(src_file, dest_dir)
        with patch("folder_organizer.file_mover.shutil.move", side_effect=PermissionError("denied")):
            result = FileMover().move(placed)

        assert result.success is False
        assert result.destination_path is None
        assert "denied" in result.skip_reason

    def test_permission_error_logs_error(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """PermissionError is captured in the error log."""
        import logging

        src_file = tmp_path / "secret.pdf"
        src_file.write_bytes(b"data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        placed = _make_placed(src_file, dest_dir)
        with patch("folder_organizer.file_mover.shutil.move", side_effect=PermissionError("access denied")):
            with caplog.at_level(logging.ERROR, logger="folder_organizer.file_mover"):
                FileMover().move(placed)

        assert any("permission" in msg.lower() or "denied" in msg.lower() for msg in caplog.messages)

    def test_oserror_returns_failure(self, tmp_path: Path) -> None:
        """Generic OSError during shutil.move → success=False, no exception raised."""
        src_file = tmp_path / "file.txt"
        src_file.write_bytes(b"data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        placed = _make_placed(src_file, dest_dir)
        with patch("folder_organizer.file_mover.shutil.move", side_effect=OSError("disk full")):
            result = FileMover().move(placed)

        assert result.success is False
        assert result.destination_path is None
        assert "disk full" in result.skip_reason

    def test_oserror_logs_error(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Generic OSError is captured in the error log."""
        import logging

        src_file = tmp_path / "file.txt"
        src_file.write_bytes(b"data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        placed = _make_placed(src_file, dest_dir)
        with patch("folder_organizer.file_mover.shutil.move", side_effect=OSError("disk full")):
            with caplog.at_level(logging.ERROR, logger="folder_organizer.file_mover"):
                FileMover().move(placed)

        assert any("i/o" in msg.lower() or "disk full" in msg.lower() for msg in caplog.messages)

    def test_error_does_not_raise_exception(self, tmp_path: Path) -> None:
        """Errors during move never propagate as exceptions — always returns MoveResult."""
        src_file = tmp_path / "file.txt"
        src_file.write_bytes(b"data")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        placed = _make_placed(src_file, dest_dir)
        # Should not raise
        with patch("folder_organizer.file_mover.shutil.move", side_effect=PermissionError("nope")):
            result = FileMover().move(placed)

        assert isinstance(result.skip_reason, str)


# ---------------------------------------------------------------------------
# 5. Dry run returns resolved path without I/O  (Req 7.5)
# ---------------------------------------------------------------------------

class TestDryRun:
    """Dry-run mode computes destination but performs no file-system mutations."""

    def test_dry_run_returns_resolved_path(self, tmp_path: Path) -> None:
        """Dry run resolves and returns the destination path."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"content")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        result = FileMover(dry_run=True).move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert result.destination_path == dest_dir / "report.pdf"

    def test_dry_run_success_is_false(self, tmp_path: Path) -> None:
        """Dry run result has success=False (no actual move performed)."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"content")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        result = FileMover(dry_run=True).move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert result.success is False

    def test_dry_run_skip_reason_is_dry_run(self, tmp_path: Path) -> None:
        """Dry run sets skip_reason to 'dry_run'."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"content")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        result = FileMover(dry_run=True).move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert result.skip_reason == "dry_run"

    def test_dry_run_does_not_move_source_file(self, tmp_path: Path) -> None:
        """Source file remains in its original location after a dry run."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"content")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        FileMover(dry_run=True).move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert src_file.exists(), "Source file must not be moved in dry-run mode"
        assert not (dest_dir / "report.pdf").exists()

    def test_dry_run_does_not_create_destination_file(self, tmp_path: Path) -> None:
        """No files are created in dest_dir during a dry run."""
        src_file = tmp_path / "invoice.docx"
        src_file.write_bytes(b"docx")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        FileMover(dry_run=True).move(_make_placed(src_file, dest_dir))

        assert list(dest_dir.iterdir()) == []

    def test_dry_run_resolves_conflict_path_without_creating_files(self, tmp_path: Path) -> None:
        """When dest already exists, dry run returns the conflict-resolved path but creates nothing."""
        src_file = tmp_path / "report.pdf"
        src_file.write_bytes(b"new")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        (dest_dir / "report.pdf").write_bytes(b"existing")  # pre-existing conflict

        result = FileMover(dry_run=True).move(_make_placed(src_file, dest_dir, "report.pdf"))

        assert result.destination_path == dest_dir / "report_1.pdf"
        assert not (dest_dir / "report_1.pdf").exists()  # nothing created
        assert src_file.exists()  # source untouched

    def test_dry_run_does_not_call_shutil_move(self, tmp_path: Path) -> None:
        """shutil.move is never called during a dry run."""
        src_file = tmp_path / "data.csv"
        src_file.write_bytes(b"csv")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        with patch("folder_organizer.file_mover.shutil.move") as mock_move:
            FileMover(dry_run=True).move(_make_placed(src_file, dest_dir))

        mock_move.assert_not_called()

    def test_dry_run_does_not_call_os_utime(self, tmp_path: Path) -> None:
        """os.utime is never called during a dry run."""
        src_file = tmp_path / "data.csv"
        src_file.write_bytes(b"csv")
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        with patch("folder_organizer.file_mover.os.utime") as mock_utime:
            FileMover(dry_run=True).move(_make_placed(src_file, dest_dir))

        mock_utime.assert_not_called()
