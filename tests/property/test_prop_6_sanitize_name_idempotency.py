# Feature: local-file-organizer, Property 6: Folder name sanitization is idempotent

"""Property-based tests: sanitize_name is idempotent.

Applying sanitize_name twice produces the same result as applying it once.
This guarantees that already-sanitized names are left unchanged on repeated
calls, which is important for stable folder resolution across runs.

Validates: Requirements 6.3 (Property 6)
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from folder_organizer.folder_generator import FolderGenerator


# ---------------------------------------------------------------------------
# Property 6: Folder name sanitization is idempotent
# Validates: Requirements 6.3
# ---------------------------------------------------------------------------

@given(label=st.text())
@settings(max_examples=500)
def test_sanitize_name_is_idempotent(label: str) -> None:
    """For any Unicode string *label*, applying sanitize_name a second time
    must return the same result as applying it once.

    In other words: sanitize_name(sanitize_name(s)) == sanitize_name(s)

    Property 6: Folder name sanitization is idempotent
    Validates: Requirements 6.3
    """
    once = FolderGenerator.sanitize_name(label)
    twice = FolderGenerator.sanitize_name(once)
    assert once == twice, (
        f"sanitize_name is not idempotent for input {label!r}: "
        f"first pass → {once!r}, second pass → {twice!r}"
    )
