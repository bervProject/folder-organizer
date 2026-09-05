"""Unit tests for FileDiscoverer (task 5.1 / 5.5).

Requirements covered: 2.1, 2.2, 2.3, 2.4, 2.5
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from folder_organizer.discoverer import DiscoveryError, FileDiscoverer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tree(root: Path, structure: dict) -> None:
    """Recursively create a directory tree from a nested dict.

    Keys that map to ``None`` become files; keys that map to another ``dict``
    become subdirectories.
    """
    for name, value in structure.items():
        child = root / name
        if value is None:
            child.touch()
        else:
            child.mkdir(exist_ok=True)
            _make_tree(child, value)


# ---------------------------------------------------------------------------
# Basic enumeration — Requirement 2.1
# ---------------------------------------------------------------------------

class TestBasicEnumeration:
    def test_flat_directory_discovers_all_files(self, tmp_path: Path) -> None:
        """All files in a flat directory are discovered."""
        _make_tree(tmp_path, {"a.txt": None, "b.py": None, "c.csv": None})
        result = FileDiscoverer().discover(tmp_path, [])
        assert set(result.discovered) == {
            tmp_path / "a.txt",
            tmp_path / "b.py",
            tmp_path / "c.csv",
        }

    def test_nested_directory_discovers_all_files(self, tmp_path: Path) -> None:
        """Files at arbitrary depth are all returned."""
        _make_tree(
            tmp_path,
            {
                "top.txt": None,
                "sub": {
                    "mid.md": None,
                    "deep": {"leaf.log": None},
                },
            },
        )
        result = FileDiscoverer().discover(tmp_path, [])
        names = {p.name for p in result.discovered}
        assert names == {"top.txt", "mid.md", "leaf.log"}

    def test_empty_directory_returns_empty_result(self, tmp_path: Path) -> None:
        result = FileDiscoverer().discover(tmp_path, [])
        assert result.discovered == []
        assert result.skipped_symlinks == 0
        assert result.excluded_count == 0

    def test_directories_not_included_in_discovered(self, tmp_path: Path) -> None:
        """Subdirectory entries must NOT appear in ``discovered``."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file.txt").touch()
        result = FileDiscoverer().discover(tmp_path, [])
        for p in result.discovered:
            assert p.is_file(), f"Non-file in discovered: {p}"


# ---------------------------------------------------------------------------
# Exclusion patterns — Requirement 2.2
# ---------------------------------------------------------------------------

class TestExclusionPatterns:
    def test_exclude_by_extension(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, {"keep.txt": None, "drop.log": None, "also.log": None})
        result = FileDiscoverer().discover(tmp_path, ["*.log"])
        assert {p.name for p in result.discovered} == {"keep.txt"}
        assert result.excluded_count == 2

    def test_exclude_by_filename(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, {"README.md": None, "notes.md": None})
        result = FileDiscoverer().discover(tmp_path, ["README.md"])
        assert {p.name for p in result.discovered} == {"notes.md"}
        assert result.excluded_count == 1

    def test_no_patterns_excludes_nothing(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, {"a.txt": None, "b.log": None})
        result = FileDiscoverer().discover(tmp_path, [])
        assert result.excluded_count == 0
        assert len(result.discovered) == 2

    def test_multiple_patterns_each_excluding_different_files(
        self, tmp_path: Path
    ) -> None:
        _make_tree(
            tmp_path,
            {"keep.py": None, "drop.log": None, "drop.tmp": None},
        )
        result = FileDiscoverer().discover(tmp_path, ["*.log", "*.tmp"])
        assert {p.name for p in result.discovered} == {"keep.py"}
        assert result.excluded_count == 2

    def test_exclude_pattern_matches_nested_file(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, {"sub": {"secret.key": None, "ok.txt": None}})
        result = FileDiscoverer().discover(tmp_path, ["*.key"])
        assert {p.name for p in result.discovered} == {"ok.txt"}
        assert result.excluded_count == 1

    def test_excluded_files_not_in_discovered(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, {"drop.log": None, "keep.txt": None})
        result = FileDiscoverer().discover(tmp_path, ["*.log"])
        for p in result.discovered:
            assert p.suffix != ".log"


# ---------------------------------------------------------------------------
# Symlink handling — Requirement 2.3
# ---------------------------------------------------------------------------

class TestSymlinkHandling:
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Symlink creation may require elevated privileges on Windows",
    )
    def test_in_scope_symlink_is_included(self, tmp_path: Path) -> None:
        """A symlink whose target is inside the source tree is included."""
        real = tmp_path / "real.txt"
        real.write_text("hello")
        link = tmp_path / "link.txt"
        link.symlink_to(real)
        result = FileDiscoverer().discover(tmp_path, [])
        # Both the real file and the in-scope symlink should be present.
        paths = set(result.discovered)
        assert real in paths
        assert link in paths
        assert result.skipped_symlinks == 0

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Symlink creation may require elevated privileges on Windows",
    )
    def test_out_of_scope_symlink_is_skipped_and_counted(
        self, tmp_path: Path
    ) -> None:
        """A symlink pointing outside the source tree is skipped."""
        outside = tmp_path.parent / "outside_target.txt"
        outside.write_text("secret")
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "normal.txt").touch()

        link = source_dir / "escape.txt"
        link.symlink_to(outside)

        result = FileDiscoverer().discover(source_dir, [])
        assert result.skipped_symlinks == 1
        discovered_names = {p.name for p in result.discovered}
        assert "escape.txt" not in discovered_names
        assert "normal.txt" in discovered_names


# ---------------------------------------------------------------------------
# Discovery counts — Requirement 2.4
# ---------------------------------------------------------------------------

class TestDiscoveryCounts:
    def test_counts_sum_correctly(self, tmp_path: Path) -> None:
        """discovered + excluded = total regular files encountered."""
        _make_tree(
            tmp_path,
            {
                "keep1.txt": None,
                "keep2.txt": None,
                "drop.log": None,
            },
        )
        result = FileDiscoverer().discover(tmp_path, ["*.log"])
        total_files = sum(1 for p in tmp_path.rglob("*") if p.is_file())
        assert len(result.discovered) + result.excluded_count == total_files

    def test_zero_counts_on_empty_dir(self, tmp_path: Path) -> None:
        result = FileDiscoverer().discover(tmp_path, [])
        assert result.skipped_symlinks == 0
        assert result.excluded_count == 0
        assert result.discovered == []


# ---------------------------------------------------------------------------
# Error handling — Requirement 2.5
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_nonexistent_source_dir_raises_discovery_error(
        self, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(DiscoveryError) as exc_info:
            FileDiscoverer().discover(missing, [])
        assert str(missing) in str(exc_info.value)

    def test_file_as_source_dir_raises_discovery_error(
        self, tmp_path: Path
    ) -> None:
        a_file = tmp_path / "file.txt"
        a_file.touch()
        with pytest.raises(DiscoveryError) as exc_info:
            FileDiscoverer().discover(a_file, [])
        assert str(a_file) in str(exc_info.value)

    def test_discovery_error_carries_path_and_reason(
        self, tmp_path: Path
    ) -> None:
        missing = tmp_path / "ghost"
        err = DiscoveryError(missing, "some reason")
        assert err.path == missing
        assert err.reason == "some reason"
        assert "ghost" in str(err)
        assert "some reason" in str(err)


# ---------------------------------------------------------------------------
# Task 5.5 — additional tests filling coverage gaps
# ---------------------------------------------------------------------------

class TestDiscoveryCountsWithSymlinks:
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Symlink creation may require elevated privileges on Windows",
    )
    def test_all_three_counts_reported_correctly(self, tmp_path: Path) -> None:
        """discovered + excluded_count + skipped_symlinks accounts for every path.

        Creates a directory containing:
        - 2 regular files that are kept
        - 1 regular file that is excluded
        - 1 symlink whose target is outside the source tree (skipped)

        Asserts each counter has the expected value and their collective sum
        equals the total number of file-like entries encountered.
        """
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        # Two regular files that should be discovered.
        (source_dir / "keep_a.txt").touch()
        (source_dir / "keep_b.txt").touch()

        # One regular file that will be excluded by pattern.
        (source_dir / "drop.log").touch()

        # One out-of-scope symlink.
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        (source_dir / "escape.txt").symlink_to(outside)

        result = FileDiscoverer().discover(source_dir, ["*.log"])

        assert len(result.discovered) == 2
        assert result.excluded_count == 1
        assert result.skipped_symlinks == 1

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Symlink creation may require elevated privileges on Windows",
    )
    def test_skipped_symlinks_not_in_discovered(self, tmp_path: Path) -> None:
        """Out-of-scope symlinks must not appear in ``discovered``."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "real.txt").touch()

        outside = tmp_path / "target.bin"
        outside.write_text("data")
        (source_dir / "link.bin").symlink_to(outside)

        result = FileDiscoverer().discover(source_dir, [])

        discovered_names = {p.name for p in result.discovered}
        assert "link.bin" not in discovered_names
        assert "real.txt" in discovered_names
        assert result.skipped_symlinks == 1


class TestUnreadableDirectory:
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="chmod permission model differs on Windows; test not applicable",
    )
    def test_unreadable_directory_raises_discovery_error(
        self, tmp_path: Path
    ) -> None:
        """A directory that exists but cannot be listed raises ``DiscoveryError``.

        Validates Requirement 2.5: when a directory cannot be read (permission
        denied), discovery halts with a ``DiscoveryError`` that carries the
        problematic path and a descriptive reason.
        """
        locked = tmp_path / "locked"
        locked.mkdir()
        (locked / "hidden.txt").touch()

        # Remove read and execute permission so os.listdir / rglob will fail.
        locked.chmod(0o000)

        try:
            with pytest.raises(DiscoveryError) as exc_info:
                FileDiscoverer().discover(locked, [])
            assert exc_info.value.path == locked
        finally:
            # Restore permissions so pytest can clean up tmp_path.
            locked.chmod(0o755)
