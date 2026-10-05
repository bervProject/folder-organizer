"""Unit tests for OrganizerLogger.

Tests cover:
- Progress indicator increments correctly (Requirement 9.1)
- Log entry written with all required fields for INFO, WARN, ERROR levels (Requirements 9.2, 9.5)
- ISO 8601 timestamp format in log entries (Requirement 9.5)
- log_error writes ERROR entry with all required fields (Requirements 9.2, 9.5)

Requirements: 9.1, 9.2, 9.5
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from folder_organizer.logger import OrganizerLogger


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

ISO_8601_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def _make_console() -> Console:
    """Return a Rich Console that writes to a StringIO (no terminal output)."""
    return Console(file=io.StringIO(), highlight=False)


@pytest.fixture
def mock_store() -> MagicMock:
    return MagicMock()


def _read_log_lines(target_dir: Path) -> list[dict]:
    """Read organizer.log and parse each line as JSON."""
    log_file = target_dir / "organizer.log"
    lines = log_file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# 1. Progress indicator increments correctly  (Req 9.1)
# ---------------------------------------------------------------------------

class TestProgressAdvance:
    """Rich progress bar advances correctly when advance() is called."""

    def test_initial_completed_is_zero(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """The progress task starts at 0 completed steps."""
        with OrganizerLogger(tmp_path, 10, mock_store, console=_make_console()) as logger:
            assert logger._progress.tasks[0].completed == 0

    def test_advance_increments_by_one(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """advance() with no argument increments completed by 1."""
        with OrganizerLogger(tmp_path, 10, mock_store, console=_make_console()) as logger:
            logger.advance()
            assert logger._progress.tasks[0].completed == 1

    def test_advance_increments_by_given_count(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """advance(n) increments completed by n."""
        with OrganizerLogger(tmp_path, 10, mock_store, console=_make_console()) as logger:
            logger.advance(3)
            assert logger._progress.tasks[0].completed == 3

    def test_advance_accumulates_across_calls(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """Multiple advance() calls accumulate correctly."""
        with OrganizerLogger(tmp_path, 10, mock_store, console=_make_console()) as logger:
            logger.advance()
            logger.advance(3)
            logger.advance(2)
            assert logger._progress.tasks[0].completed == 6

    def test_total_files_sets_progress_bar_total(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """The progress task total equals total_files passed to the constructor."""
        with OrganizerLogger(tmp_path, 42, mock_store, console=_make_console()) as logger:
            assert logger._progress.tasks[0].total == 42


# ---------------------------------------------------------------------------
# 2. Log entry fields for INFO level  (Req 9.2, 9.5)
# ---------------------------------------------------------------------------

class TestLogActionInfoLevel:
    """log_action with level='INFO' writes a complete log entry."""

    def test_info_entry_has_all_required_fields(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """An INFO log entry contains timestamp, level, path, action, destination."""
        src = str(tmp_path / "report.pdf")
        dst = str(tmp_path / "Finance" / "report.pdf")

        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(src, "moved", dst, level="INFO")

        entries = _read_log_lines(tmp_path)
        assert len(entries) == 1
        entry = entries[0]

        assert "timestamp" in entry
        assert "level" in entry
        assert "path" in entry
        assert "action" in entry
        assert "destination" in entry

    def test_info_entry_values_are_correct(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """Field values in an INFO entry match the arguments passed to log_action."""
        src = str(tmp_path / "report.pdf")
        dst = str(tmp_path / "Finance" / "report.pdf")

        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(src, "moved", dst, level="INFO")

        entry = _read_log_lines(tmp_path)[0]
        assert entry["level"] == "INFO"
        assert entry["path"] == src
        assert entry["action"] == "moved"
        assert entry["destination"] == dst

    def test_info_entry_no_error_field(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """An INFO log entry does not contain an 'error' field."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(str(tmp_path / "f.pdf"), "moved", level="INFO")

        entry = _read_log_lines(tmp_path)[0]
        assert "error" not in entry


# ---------------------------------------------------------------------------
# 3. Log entry fields for WARN level  (Req 9.2, 9.5)
# ---------------------------------------------------------------------------

class TestLogActionWarnLevel:
    """log_action with level='WARN' writes a WARNING-level log entry."""

    def test_warn_entry_has_correct_level(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """A WARN log entry records level as 'WARNING'."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(str(tmp_path / "f.pdf"), "review_required", level="WARN")

        entry = _read_log_lines(tmp_path)[0]
        assert entry["level"] == "WARNING"

    def test_warn_entry_has_all_required_fields(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """A WARN entry contains timestamp, level, path, action, destination."""
        src = str(tmp_path / "doc.pdf")

        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(src, "review_required", level="WARN")

        entry = _read_log_lines(tmp_path)[0]
        assert "timestamp" in entry
        assert "level" in entry
        assert "path" in entry
        assert "action" in entry
        assert "destination" in entry

    def test_warn_entry_path_and_action_values(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """Path and action values are set correctly in WARN entries."""
        src = str(tmp_path / "doc.pdf")

        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(src, "review_required", level="WARN")

        entry = _read_log_lines(tmp_path)[0]
        assert entry["path"] == src
        assert entry["action"] == "review_required"


# ---------------------------------------------------------------------------
# 4. Log entry fields for ERROR level  (Req 9.2, 9.5)
# ---------------------------------------------------------------------------

class TestLogActionErrorLevel:
    """log_action with level='ERROR' writes an ERROR-level log entry."""

    def test_error_entry_has_correct_level(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """An ERROR log entry records level as 'ERROR'."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(str(tmp_path / "f.pdf"), "failed", level="ERROR")

        entry = _read_log_lines(tmp_path)[0]
        assert entry["level"] == "ERROR"

    def test_error_entry_has_all_required_fields(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """An ERROR entry from log_action contains timestamp, level, path, action, destination."""
        src = str(tmp_path / "broken.pdf")

        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(src, "failed", level="ERROR")

        entry = _read_log_lines(tmp_path)[0]
        assert "timestamp" in entry
        assert "level" in entry
        assert "path" in entry
        assert "action" in entry
        assert "destination" in entry


# ---------------------------------------------------------------------------
# 5. log_error writes structured ERROR entry  (Req 9.2, 9.5)
# ---------------------------------------------------------------------------

class TestLogError:
    """log_error writes a structured ERROR entry with path and error fields."""

    def test_log_error_level_is_error(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """log_error always records level as 'ERROR'."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_error(str(tmp_path / "file.pdf"), "Permission denied")

        entry = _read_log_lines(tmp_path)[0]
        assert entry["level"] == "ERROR"

    def test_log_error_has_path_field(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """log_error writes the file path into the 'path' field."""
        src = str(tmp_path / "file.pdf")

        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_error(src, "Permission denied")

        entry = _read_log_lines(tmp_path)[0]
        assert entry["path"] == src

    def test_log_error_has_error_field(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """log_error writes the reason into the 'error' field."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_error(str(tmp_path / "file.pdf"), "Permission denied")

        entry = _read_log_lines(tmp_path)[0]
        assert "error" in entry
        assert entry["error"] == "Permission denied"

    def test_log_error_has_all_required_fields(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """log_error entry contains timestamp, level, path, action, and error fields."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_error(str(tmp_path / "file.pdf"), "disk full")

        entry = _read_log_lines(tmp_path)[0]
        assert "timestamp" in entry
        assert "level" in entry
        assert "path" in entry
        assert "action" in entry
        assert "error" in entry

    def test_log_error_action_field_is_error(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """log_error sets action to 'error' in the log entry."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_error(str(tmp_path / "file.pdf"), "some failure")

        entry = _read_log_lines(tmp_path)[0]
        assert entry["action"] == "error"


# ---------------------------------------------------------------------------
# 6. ISO 8601 timestamp format  (Req 9.5)
# ---------------------------------------------------------------------------

class TestTimestampFormat:
    """Timestamp field in log entries conforms to ISO 8601 with milliseconds."""

    def test_timestamp_matches_iso_8601_pattern(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """Timestamp format is YYYY-MM-DDTHH:MM:SS.mmmZ."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(str(tmp_path / "f.pdf"), "moved")

        entry = _read_log_lines(tmp_path)[0]
        ts = entry["timestamp"]
        assert ISO_8601_PATTERN.match(ts), (
            f"Timestamp {ts!r} does not match YYYY-MM-DDTHH:MM:SS.mmmZ"
        )

    def test_timestamp_ends_with_z_for_utc(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """Timestamp ends with 'Z' indicating UTC."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(str(tmp_path / "f.pdf"), "moved")

        entry = _read_log_lines(tmp_path)[0]
        assert entry["timestamp"].endswith("Z")

    def test_timestamp_is_parseable(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """The timestamp string can be parsed with the expected strptime format."""
        from datetime import datetime

        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_error(str(tmp_path / "f.pdf"), "some error")

        entry = _read_log_lines(tmp_path)[0]
        ts = entry["timestamp"]
        # Should not raise
        parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
        assert parsed.year >= 2024

    def test_log_error_timestamp_also_conforms(self, tmp_path: Path, mock_store: MagicMock) -> None:
        """Timestamp in log_error entries also matches the ISO 8601 pattern."""
        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_error(str(tmp_path / "f.pdf"), "read error")

        entry = _read_log_lines(tmp_path)[0]
        assert ISO_8601_PATTERN.match(entry["timestamp"])

    def test_multiple_entries_all_have_valid_timestamps(
        self, tmp_path: Path, mock_store: MagicMock
    ) -> None:
        """All entries written in a single run have valid ISO 8601 timestamps."""
        paths = [str(tmp_path / f"file{i}.pdf") for i in range(3)]

        with OrganizerLogger(tmp_path, 5, mock_store, console=_make_console()) as logger:
            logger.log_action(paths[0], "moved", level="INFO")
            logger.log_action(paths[1], "skipped", level="WARN")
            logger.log_error(paths[2], "permission denied")

        for entry in _read_log_lines(tmp_path):
            assert ISO_8601_PATTERN.match(entry["timestamp"]), (
                f"Bad timestamp {entry['timestamp']!r} in entry {entry}"
            )
