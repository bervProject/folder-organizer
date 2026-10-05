# Feature: local-file-organizer, Property 11: File last-modified timestamp is preserved after move

"""Property-based tests: FileMover preserves the original mtime after a move.

Validates: Requirements 7.3
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from folder_organizer.file_mover import FileMover
from folder_organizer.models import PlacedFile


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Safe filenames — avoid OS-reserved names and empty stems
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

# mtime values: arbitrary positive floats representing Unix timestamps
# Range: 1970-01-02 to ~2100, with up to 1-second precision to stay within
# OS rounding on most platforms (FAT32 rounds to 2 s, NTFS to 100 ns, etc.).
# We round to whole seconds to avoid sub-second precision issues across OSes.
_mtime_st = st.floats(
    min_value=86_400.0,          # 1970-01-02 00:00:00 UTC — avoid epoch edge
    max_value=4_102_444_800.0,   # 2100-01-01 00:00:00 UTC
    allow_nan=False,
    allow_infinity=False,
).map(lambda t: round(t))  # whole seconds — cross-platform safe


# ---------------------------------------------------------------------------
# Property 11: File last-modified timestamp is preserved after move
# Validates: Requirements 7.3
# ---------------------------------------------------------------------------

@given(filename=_filename_st, mtime=_mtime_st)
@settings(max_examples=100, deadline=None)
def test_mtime_preserved_after_move(filename: str, mtime: float) -> None:
    """For any source file with any last-modified timestamp, after ``FileMover``
    moves the file the destination shall have the same ``st_mtime`` as the
    original (within 1-second tolerance to accommodate FAT32 2-second rounding).

    Property 11: File last-modified timestamp is preserved after move
    Validates: Requirements 7.3
    """
    mover = FileMover(dry_run=False)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_dir = tmp_path / "source"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()

        source_file = source_dir / filename
        source_file.write_bytes(b"content")

        # Set the desired mtime (and keep atime equal to mtime for simplicity)
        os.utime(source_file, (mtime, mtime))

        placed = PlacedFile(
            source_path=source_file,
            destination_dir=dest_dir,
            destination_filename=filename,
            review_required=False,
            unplaced=False,
        )

        result = mover.move(placed)

        assert result.success, (
            f"Expected move to succeed but got skip_reason={result.skip_reason!r}"
        )
        assert result.destination_path is not None

        dest_mtime = os.stat(result.destination_path).st_mtime

        # Allow up to 1-second tolerance for FAT32 / filesystem rounding
        assert abs(dest_mtime - mtime) <= 1.0, (
            f"mtime not preserved: original={mtime}, destination={dest_mtime}, "
            f"delta={abs(dest_mtime - mtime)}"
        )
