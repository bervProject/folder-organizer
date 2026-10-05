# Feature: local-file-organizer, Property 5: Conflict resolution always produces a unique destination name

"""Property-based tests: FileMover conflict resolution always produces unique paths.

Validates: Requirements 7.2, 7.6 (Property 5)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from folder_organizer.file_mover import FileMover


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Base filenames with safe characters — avoid OS-reserved names and empty stems
_safe_stem_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=1,
    max_size=20,
)

_safe_extension_st = st.sampled_from([".pdf", ".txt", ".docx", ".png", ".csv", ""])

_filename_st = st.builds(
    lambda stem, ext: stem + ext,
    stem=_safe_stem_st,
    ext=_safe_extension_st,
)

# Number of files to place into the same directory (1–50 is plenty to exercise
# the suffix loop without making tests slow)
_file_count_st = st.integers(min_value=1, max_value=50)


# ---------------------------------------------------------------------------
# Property 5: Conflict resolution always produces a unique destination name
# Validates: Requirements 7.2, 7.6
# ---------------------------------------------------------------------------

@given(filename=_filename_st, n=_file_count_st)
@settings(max_examples=100, deadline=None)
def test_conflict_resolution_always_produces_unique_paths(
    filename: str,
    n: int,
) -> None:
    """For any destination directory and any sequence of *n* files all sharing
    the same base name, ``FileMover._resolve_conflict`` shall assign each file
    a unique filename (appending ``_1``, ``_2``, … as needed), and no two files
    shall end up with the same destination path.

    Property 5: Conflict resolution always produces a unique destination name
    Validates: Requirements 7.2, 7.6
    """
    mover = FileMover(dry_run=False)

    with tempfile.TemporaryDirectory() as tmp:
        dest_dir = Path(tmp)
        collected_paths: list[Path] = []

        for _ in range(n):
            dest_path = dest_dir / filename

            if dest_path.exists():
                # Conflict — resolve to a unique name
                resolved = mover._resolve_conflict(dest_dir, filename)
                assert resolved is not None, (
                    f"_resolve_conflict returned None for '{filename}' after "
                    f"{len(collected_paths)} files placed — suffix exhausted unexpectedly"
                )
                dest_path = resolved

            # Create a placeholder file so subsequent calls see the conflict
            dest_path.touch()
            collected_paths.append(dest_path)

        # All destination paths must be distinct
        assert len(collected_paths) == len(set(collected_paths)), (
            f"Duplicate destination paths detected among {len(collected_paths)} files "
            f"all named '{filename}': {[str(p) for p in collected_paths]}"
        )

        # Every created file must still exist (no silent overwrites)
        for path in collected_paths:
            assert path.exists(), f"Expected file '{path}' to exist but it does not"
