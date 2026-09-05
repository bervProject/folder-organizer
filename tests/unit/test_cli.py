"""Unit tests for cli.py — organize command validation logic.

Tests cover source/target directory validation and error handling at the CLI layer.

Requirements: 1.1, 1.2, 1.4, 1.5, 10.5
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from folder_organizer.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoke(*args: str) -> "typer.testing.Result":  # type: ignore[name-defined]
    """Invoke the CLI app with the given arguments using the test runner."""
    return runner.invoke(app, [str(a) for a in args])


# ---------------------------------------------------------------------------
# Requirement 1.1 / 1.2 — source_dir validation
# ---------------------------------------------------------------------------

class TestSourceDirValidation:
    def test_nonexistent_source_dir_exits_with_code_1(self, tmp_path: Path) -> None:
        """Non-existent source_dir causes exit code 1.

        Validates: Requirements 1.1, 1.2
        """
        missing = tmp_path / "does_not_exist"
        result = _invoke(missing)
        assert result.exit_code == 1

    def test_nonexistent_source_dir_shows_descriptive_error(
        self, tmp_path: Path
    ) -> None:
        """Non-existent source_dir prints a descriptive error message.

        Validates: Requirements 1.2
        """
        missing = tmp_path / "does_not_exist"
        result = _invoke(missing)
        # stderr or output should mention the path or describe the problem
        output = result.output
        assert "does not exist" in output.lower() or str(missing) in output

    def test_source_dir_pointing_to_file_exits_with_code_1(
        self, tmp_path: Path
    ) -> None:
        """source_dir pointing to a file (not a directory) causes exit code 1.

        Validates: Requirements 1.2
        """
        file_path = tmp_path / "some_file.txt"
        file_path.write_text("content")
        result = _invoke(file_path)
        assert result.exit_code == 1

    def test_source_dir_pointing_to_file_shows_descriptive_error(
        self, tmp_path: Path
    ) -> None:
        """source_dir pointing to a file prints a descriptive error message.

        Validates: Requirements 1.2
        """
        file_path = tmp_path / "some_file.txt"
        file_path.write_text("content")
        result = _invoke(file_path)
        output = result.output
        assert "not a directory" in output.lower() or str(file_path) in output

    def test_no_files_modified_when_source_dir_nonexistent(
        self, tmp_path: Path
    ) -> None:
        """No pipeline is executed when source_dir is missing.

        Validates: Requirements 1.2
        """
        missing = tmp_path / "does_not_exist"
        with patch("folder_organizer.cli.Organizer") as mock_organizer:
            result = _invoke(missing)
        assert result.exit_code == 1
        mock_organizer.assert_not_called()

    def test_no_files_modified_when_source_dir_is_file(
        self, tmp_path: Path
    ) -> None:
        """Organizer pipeline is not invoked when source_dir points to a file.

        Validates: Requirements 1.2
        """
        file_path = tmp_path / "some_file.txt"
        file_path.write_text("content")
        with patch("folder_organizer.cli.Organizer") as mock_organizer:
            result = _invoke(file_path)
        assert result.exit_code == 1
        mock_organizer.assert_not_called()

    def test_valid_source_dir_invokes_organizer(self, tmp_path: Path) -> None:
        """A valid source_dir delegates to Organizer.run().

        Validates: Requirements 1.1
        """
        source = tmp_path / "source"
        source.mkdir()
        with patch("folder_organizer.cli.Organizer") as mock_organizer:
            mock_organizer.return_value.run.return_value = None
            result = _invoke(source)
        assert result.exit_code == 0
        mock_organizer.return_value.run.assert_called_once()


# ---------------------------------------------------------------------------
# Requirement 10.5 — missing source_dir
# ---------------------------------------------------------------------------

class TestMissingSourceDir:
    def test_missing_source_dir_argument_exits_with_nonzero_code(self) -> None:
        """Invoking the CLI with no arguments exits with a non-zero code.

        Validates: Requirements 10.5
        """
        result = runner.invoke(app, [])
        assert result.exit_code != 0

    def test_missing_source_dir_shows_usage_or_error(self) -> None:
        """Invoking the CLI with no arguments produces an error or usage message.

        Validates: Requirements 10.5
        """
        result = runner.invoke(app, [])
        output = result.output
        # Typer/Click will print a missing argument error or usage hint
        assert len(output) > 0


# ---------------------------------------------------------------------------
# Requirement 1.4 / 1.5 — target_dir creation
# ---------------------------------------------------------------------------

class TestTargetDirCreation:
    def test_nonexistent_target_dir_is_created(self, tmp_path: Path) -> None:
        """A non-existent target_dir is created before the pipeline runs.

        Validates: Requirements 1.4
        """
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "nested" / "target"

        with patch("folder_organizer.cli.Organizer") as mock_organizer:
            mock_organizer.return_value.run.return_value = None
            result = _invoke(source, "--target-dir", target)

        assert result.exit_code == 0
        assert target.exists()
        assert target.is_dir()

    def test_nonexistent_target_dir_nested_path_is_created(
        self, tmp_path: Path
    ) -> None:
        """All intermediate directories for target_dir are created.

        Validates: Requirements 1.4
        """
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "a" / "b" / "c" / "target"

        with patch("folder_organizer.cli.Organizer") as mock_organizer:
            mock_organizer.return_value.run.return_value = None
            result = _invoke(source, "--target-dir", target)

        assert result.exit_code == 0
        assert target.exists()

    def test_existing_target_dir_is_reused_without_error(
        self, tmp_path: Path
    ) -> None:
        """An already-existing target_dir is accepted silently.

        Validates: Requirements 1.4
        """
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        with patch("folder_organizer.cli.Organizer") as mock_organizer:
            mock_organizer.return_value.run.return_value = None
            result = _invoke(source, "--target-dir", target)

        assert result.exit_code == 0

    def test_target_dir_creation_failure_exits_with_code_1(
        self, tmp_path: Path
    ) -> None:
        """If target_dir cannot be created, exit code is 1 with no pipeline run.

        Validates: Requirements 1.5
        """
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        with patch("folder_organizer.cli.Organizer") as mock_organizer:
            # Patch Path.mkdir to raise PermissionError
            with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
                result = _invoke(source, "--target-dir", target)

        assert result.exit_code == 1
        mock_organizer.assert_not_called()

    def test_target_dir_creation_failure_shows_descriptive_error(
        self, tmp_path: Path
    ) -> None:
        """A target_dir creation failure prints a descriptive error.

        Validates: Requirements 1.5
        """
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        with patch("folder_organizer.cli.Organizer"):
            with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
                result = _invoke(source, "--target-dir", target)

        output = result.output
        assert "error" in output.lower() or "cannot" in output.lower()


# ---------------------------------------------------------------------------
# Config file error handling (Requirement 10.3)
# ---------------------------------------------------------------------------

class TestConfigFileErrors:
    def test_nonexistent_config_file_exits_with_code_1(
        self, tmp_path: Path
    ) -> None:
        """A config file path that does not exist causes exit code 1."""
        source = tmp_path / "source"
        source.mkdir()
        missing_cfg = tmp_path / "missing.yaml"

        result = _invoke(source, "--config", missing_cfg)
        assert result.exit_code == 1

    def test_nonexistent_config_file_shows_error_message(
        self, tmp_path: Path
    ) -> None:
        """A missing config file prints an informative error."""
        source = tmp_path / "source"
        source.mkdir()
        missing_cfg = tmp_path / "missing.yaml"

        result = _invoke(source, "--config", missing_cfg)
        output = result.output
        assert "not found" in output.lower() or str(missing_cfg) in output

    def test_malformed_config_file_exits_with_code_1(
        self, tmp_path: Path
    ) -> None:
        """A config file with invalid YAML syntax causes exit code 1."""
        source = tmp_path / "source"
        source.mkdir()
        bad_cfg = tmp_path / "bad.yaml"
        bad_cfg.write_text("source_dir: /src\n  bad_indent: [\n")

        result = _invoke(source, "--config", bad_cfg)
        assert result.exit_code == 1
