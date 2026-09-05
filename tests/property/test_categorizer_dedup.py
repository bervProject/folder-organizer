# Feature: local-file-organizer, Property 4: Duplicate files reuse existing categorization

"""Property-based tests: duplicate files (same sha256) reuse cached categorization.

Validates: Requirements 4.5, 5.5 (Property 4)
"""

from __future__ import annotations

import json
import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch, call

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from folder_organizer.categorizer import AICategorizer
from folder_organizer.config import Config
from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import ExtractionStatus, InspectedFile, MetadataRecord
from folder_organizer.taxonomy import DEFAULT_TAXONOMY


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_extraction_status_st = st.sampled_from(list(ExtractionStatus))

_sha256_st = st.text(
    alphabet="0123456789abcdef",
    min_size=64,
    max_size=64,
)

_filename_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=1,
    max_size=20,
).map(lambda s: s + ".txt")

_inspected_file_st = st.builds(
    InspectedFile,
    path=_filename_st.map(Path),
    sha256=_sha256_st,
    size_bytes=st.integers(min_value=0, max_value=10_000_000),
    mime_type=st.sampled_from(["text/plain", "application/pdf", "image/png"]),
    extracted_text=st.one_of(st.none(), st.text(max_size=512)),
    char_count=st.one_of(st.none(), st.integers(min_value=0, max_value=4096)),
    extraction_status=_extraction_status_st,
)

_valid_category_st = st.sampled_from(DEFAULT_TAXONOMY)


def _make_config() -> Config:
    return Config(
        source_dir=Path("."),
        min_confidence=0.0,
        ai_api_key="test-key",
    )


def _make_ai_response(category: str, subcategory: Optional[str], confidence: float) -> MagicMock:
    content = json.dumps({"category": category, "subcategory": subcategory, "confidence": confidence})
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _result_to_record(file: InspectedFile, category: str, subcategory: Optional[str], confidence: float) -> MetadataRecord:
    """Build a MetadataRecord that looks like a persisted result for *file*."""
    return MetadataRecord(
        original_path=str(file.path),
        destination_path="",
        sha256=file.sha256,
        size_bytes=file.size_bytes,
        mime_type=file.mime_type,
        text_snippet=(file.extracted_text or "")[:512],
        category=category,
        subcategory=subcategory,
        confidence_score=max(0.0, min(1.0, confidence)),
        method="ai",
        review_required=False,
        fallback_used=False,
        extraction_status=file.extraction_status.value,
        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
    )


# ---------------------------------------------------------------------------
# Property 4: Duplicate files reuse existing categorization
# Validates: Requirements 4.5, 5.5
# ---------------------------------------------------------------------------

@given(
    file1=_inspected_file_st,
    file2=_inspected_file_st,
    category=_valid_category_st,
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_duplicate_sha256_reuses_existing_record(
    file1: InspectedFile,
    file2: InspectedFile,
    category: str,
    confidence: float,
) -> None:
    """When a file with the same SHA-256 has already been processed, the second
    categorization shall reuse the existing record without calling the AI again.

    Property 4: Duplicate files reuse existing categorization
    Validates: Requirements 4.5, 5.5
    """
    # Force both files to share the same sha256
    shared_hash = file1.sha256
    # Rebuild file2 with the same hash using object replacement
    file2_dup = InspectedFile(
        path=file2.path,
        sha256=shared_hash,
        size_bytes=file2.size_bytes,
        mime_type=file2.mime_type,
        extracted_text=file2.extracted_text,
        char_count=file2.char_count,
        extraction_status=file2.extraction_status,
    )

    store = MetadataStore()
    config = _make_config()
    categorizer = AICategorizer(config, store)

    # Seed the store with the first file's record
    record = _result_to_record(file1, category, None, confidence)
    store.upsert(record)

    # Now categorize the second file — the AI must NOT be called
    mock_create = MagicMock(side_effect=AssertionError("AI should not be called for duplicate"))

    with patch.object(categorizer._client.chat.completions, "create", mock_create):
        result = categorizer.categorize(file2_dup)

    # Verify AI was not invoked
    mock_create.assert_not_called()

    # Verify the result matches what was stored for the first file
    assert result.category == category, (
        f"Expected cached category {category!r}, got {result.category!r}"
    )
    assert result.confidence == max(0.0, min(1.0, confidence)), (
        f"Expected cached confidence {confidence}, got {result.confidence}"
    )
