# Feature: local-file-organizer, Property 15: SHA-256 hash is computed correctly
# Feature: local-file-organizer, Property 8: Extraction character count is within bounds

"""Property-based tests for FileInspector.

Validates: Requirements 3.5 (Property 15), Requirements 3.1 and 3.7 (Property 8)
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from folder_organizer.inspector import FileInspector
from folder_organizer.models import ExtractionStatus


# ---------------------------------------------------------------------------
# Property 15: SHA-256 hash is computed correctly
# Validates: Requirements 3.5
# ---------------------------------------------------------------------------

@given(content=st.binary())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_sha256_hash_correctness(content: bytes) -> None:
    """For any file with binary content b, inspector.inspect(path).sha256 shall
    equal hashlib.sha256(b).hexdigest().

    Property 15: SHA-256 hash is computed correctly
    Validates: Requirements 3.5
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        path = Path(tmp_dir) / "file.bin"
        path.write_bytes(content)

        result = FileInspector().inspect(path)

        assert result.sha256 == hashlib.sha256(content).hexdigest(), (
            f"SHA-256 mismatch for content of length {len(content)}.\n"
            f"  Expected : {hashlib.sha256(content).hexdigest()}\n"
            f"  Got      : {result.sha256}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 8: Extraction character count is within bounds
# Validates: Requirements 3.1, 3.7
# ---------------------------------------------------------------------------

@given(content=st.text(min_size=0, max_size=8192))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_extraction_char_count_bounds(content: str) -> None:
    """For any text-based file whose content is successfully extracted, the
    char_count shall be between 0 and 4096 inclusive, and shall equal
    len(extracted_text).

    Property 8: Extraction character count is within bounds
    Validates: Requirements 3.1, 3.7
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        path = Path(tmp_dir) / "file.txt"
        path.write_bytes(content.encode("utf-8"))

        result = FileInspector().inspect(path)

        assert result.extraction_status == ExtractionStatus.OK, (
            f"Expected extraction_status OK for a .txt file, "
            f"got {result.extraction_status!r}"
        )
        assert result.char_count is not None, (
            "char_count should not be None when extraction_status is OK"
        )
        assert 0 <= result.char_count <= 4096, (
            f"char_count {result.char_count} is outside [0, 4096]"
        )
        assert result.char_count == len(result.extracted_text), (
            f"char_count {result.char_count} != len(extracted_text) "
            f"{len(result.extracted_text)}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
