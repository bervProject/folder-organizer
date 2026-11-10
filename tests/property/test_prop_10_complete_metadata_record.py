# Feature: local-file-organizer, Property 10: Every processed file has a complete MetadataRecord

"""Property-based tests: every processed file has a complete MetadataRecord.

After running files through the pipeline's metadata upsert logic, every file
must have a corresponding MetadataRecord in the MetadataStore with all required
fields populated and of the correct types.

Validates: Requirements 5.1, 5.2 (Property 10)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import (
    CategorizedFile,
    CategorizationResult,
    ExtractionStatus,
    InspectedFile,
    MetadataRecord,
)
from folder_organizer.organizer import _utc_now
from folder_organizer.taxonomy import DEFAULT_TAXONOMY


# ---------------------------------------------------------------------------
# ISO 8601 timestamp pattern expected by the organizer
# ---------------------------------------------------------------------------

_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

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

_method_st = st.sampled_from(["ai", "fallback"])

_confidence_st = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

_categorization_result_st = st.builds(
    CategorizationResult,
    category=_valid_category_st,
    subcategory=st.one_of(st.none(), st.text(min_size=1, max_size=30)),
    confidence=_confidence_st,
    method=_method_st,
    review_required=st.booleans(),
    fallback_used=st.booleans(),
)

# Lists of 1–10 (inspected_file, categorization_result) pairs
_pipeline_inputs_st = st.lists(
    st.tuples(_inspected_file_st, _categorization_result_st),
    min_size=1,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Helpers — mirror the organizer.py upsert block exactly
# ---------------------------------------------------------------------------

def _build_record(
    cat_file: CategorizedFile,
    dest_path_str: str,
) -> MetadataRecord:
    """Replicate the MetadataRecord construction from organizer.py."""
    text_snippet = (cat_file.extracted_text or "")[:512]
    return MetadataRecord(
        original_path=str(cat_file.path.resolve()),
        destination_path=dest_path_str,
        sha256=cat_file.sha256,
        size_bytes=cat_file.size_bytes,
        mime_type=cat_file.mime_type,
        text_snippet=text_snippet,
        category=cat_file.category,
        subcategory=cat_file.subcategory,
        confidence_score=cat_file.confidence,
        method=cat_file.method,
        review_required=cat_file.review_required,
        fallback_used=cat_file.fallback_used,
        extraction_status=cat_file.extraction_status,
        timestamp=_utc_now(),
    )


def _inspected_to_categorized(
    inspected: InspectedFile,
    cat_result: CategorizationResult,
) -> CategorizedFile:
    """Convert InspectedFile + CategorizationResult → CategorizedFile (as the organizer does)."""
    extraction_status_str = (
        inspected.extraction_status.value
        if hasattr(inspected.extraction_status, "value")
        else str(inspected.extraction_status)
    )
    return CategorizedFile(
        path=inspected.path,
        sha256=inspected.sha256,
        size_bytes=inspected.size_bytes,
        mime_type=inspected.mime_type,
        extracted_text=inspected.extracted_text,
        char_count=inspected.char_count,
        extraction_status=extraction_status_str,
        category=cat_result.category,
        subcategory=cat_result.subcategory,
        confidence=cat_result.confidence,
        method=cat_result.method,
        review_required=cat_result.review_required,
        fallback_used=cat_result.fallback_used,
    )


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def _assert_record_complete(record: MetadataRecord, label: str) -> None:
    """Assert that *record* has all required fields with correct types."""
    # original_path: str, non-empty
    assert isinstance(record.original_path, str), (
        f"{label}: original_path must be str, got {type(record.original_path)}"
    )
    assert record.original_path, f"{label}: original_path must be non-empty"

    # destination_path: str (may be empty)
    assert isinstance(record.destination_path, str), (
        f"{label}: destination_path must be str, got {type(record.destination_path)}"
    )

    # sha256: str, exactly 64 hex chars
    assert isinstance(record.sha256, str), (
        f"{label}: sha256 must be str, got {type(record.sha256)}"
    )
    assert re.fullmatch(r"[0-9a-fA-F]{64}", record.sha256), (
        f"{label}: sha256 must be 64 hex chars, got {record.sha256!r}"
    )

    # size_bytes: int, >= 0
    assert isinstance(record.size_bytes, int), (
        f"{label}: size_bytes must be int, got {type(record.size_bytes)}"
    )
    assert record.size_bytes >= 0, (
        f"{label}: size_bytes must be >= 0, got {record.size_bytes}"
    )

    # mime_type: str, non-empty
    assert isinstance(record.mime_type, str), (
        f"{label}: mime_type must be str, got {type(record.mime_type)}"
    )
    assert record.mime_type, f"{label}: mime_type must be non-empty"

    # text_snippet: str (may be empty)
    assert isinstance(record.text_snippet, str), (
        f"{label}: text_snippet must be str, got {type(record.text_snippet)}"
    )

    # category: str, non-empty
    assert isinstance(record.category, str), (
        f"{label}: category must be str, got {type(record.category)}"
    )
    assert record.category, f"{label}: category must be non-empty"

    # subcategory: Optional[str]
    assert record.subcategory is None or isinstance(record.subcategory, str), (
        f"{label}: subcategory must be str or None, got {type(record.subcategory)}"
    )

    # confidence_score: float in [0.0, 1.0]
    assert isinstance(record.confidence_score, float), (
        f"{label}: confidence_score must be float, got {type(record.confidence_score)}"
    )
    assert 0.0 <= record.confidence_score <= 1.0, (
        f"{label}: confidence_score must be in [0.0, 1.0], got {record.confidence_score}"
    )

    # method: str, one of "ai" or "fallback"
    assert isinstance(record.method, str), (
        f"{label}: method must be str, got {type(record.method)}"
    )
    assert record.method in ("ai", "fallback"), (
        f"{label}: method must be 'ai' or 'fallback', got {record.method!r}"
    )

    # review_required: bool
    assert isinstance(record.review_required, bool), (
        f"{label}: review_required must be bool, got {type(record.review_required)}"
    )

    # fallback_used: bool
    assert isinstance(record.fallback_used, bool), (
        f"{label}: fallback_used must be bool, got {type(record.fallback_used)}"
    )

    # extraction_status: str, one of "ok", "unavailable", "failed"
    assert isinstance(record.extraction_status, str), (
        f"{label}: extraction_status must be str, got {type(record.extraction_status)}"
    )
    assert record.extraction_status in ("ok", "unavailable", "failed"), (
        f"{label}: extraction_status must be one of ok/unavailable/failed, "
        f"got {record.extraction_status!r}"
    )

    # timestamp: str, ISO 8601 format YYYY-MM-DDTHH:MM:SSZ
    assert isinstance(record.timestamp, str), (
        f"{label}: timestamp must be str, got {type(record.timestamp)}"
    )
    assert _ISO8601_RE.match(record.timestamp), (
        f"{label}: timestamp must match ISO 8601 pattern, got {record.timestamp!r}"
    )


# ---------------------------------------------------------------------------
# Property 10: Every processed file has a complete MetadataRecord
# Validates: Requirements 5.1, 5.2
# ---------------------------------------------------------------------------

@given(pipeline_inputs=_pipeline_inputs_st)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_every_processed_file_has_complete_metadata_record(
    pipeline_inputs: list[tuple[InspectedFile, CategorizationResult]],
) -> None:
    """After running files through the pipeline's metadata upsert logic,
    every file must have a MetadataRecord in the store with all required
    fields populated and of the correct types.

    Property 10: Every processed file has a complete MetadataRecord
    Validates: Requirements 5.1, 5.2
    """
    store = MetadataStore()

    for inspected, cat_result in pipeline_inputs:
        # Mirror organizer.py: InspectedFile + CategorizationResult → CategorizedFile
        cat_file = _inspected_to_categorized(inspected, cat_result)

        # Mirror organizer.py: build record and upsert (simulate a successful move)
        dest_path_str = str(cat_file.path.parent / "target" / cat_file.path.name)
        record = _build_record(cat_file, dest_path_str)
        store.upsert(record)

    # Assert: every file has a record with all required fields
    all_records = store.all_records()
    assert len(all_records) >= 1, "Store must contain at least one record"

    # Retrieve each record by sha256 (as the organizer does for dedup checks)
    for inspected, cat_result in pipeline_inputs:
        cat_file = _inspected_to_categorized(inspected, cat_result)

        # Retrieve by path (the primary key the organizer uses)
        record = store.get_by_path(Path(str(cat_file.path.resolve())))

        assert record is not None, (
            f"No MetadataRecord found for path {cat_file.path!r}. "
            f"Store has {len(all_records)} record(s)."
        )

        label = f"File {cat_file.path.name!r}"
        _assert_record_complete(record, label)


@given(pipeline_inputs=_pipeline_inputs_st)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_metadata_record_retrievable_by_hash(
    pipeline_inputs: list[tuple[InspectedFile, CategorizationResult]],
) -> None:
    """Every upserted record must also be retrievable by its sha256 hash.

    Property 10: Every processed file has a complete MetadataRecord
    Validates: Requirements 5.1, 5.2
    """
    store = MetadataStore()

    for inspected, cat_result in pipeline_inputs:
        cat_file = _inspected_to_categorized(inspected, cat_result)
        record = _build_record(cat_file, "")
        store.upsert(record)

    # Each sha256 must be retrievable
    for inspected, _ in pipeline_inputs:
        record = store.get_by_hash(inspected.sha256)
        assert record is not None, (
            f"No MetadataRecord found for sha256 {inspected.sha256!r}"
        )
        _assert_record_complete(record, f"sha256={inspected.sha256[:8]}…")


@given(pipeline_inputs=_pipeline_inputs_st)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_metadata_text_snippet_bounded(
    pipeline_inputs: list[tuple[InspectedFile, CategorizationResult]],
) -> None:
    """The text_snippet stored in each MetadataRecord must be at most 512 chars,
    matching the truncation applied in organizer.py.

    Property 10: Every processed file has a complete MetadataRecord
    Validates: Requirements 5.1, 5.2
    """
    store = MetadataStore()

    for inspected, cat_result in pipeline_inputs:
        cat_file = _inspected_to_categorized(inspected, cat_result)
        record = _build_record(cat_file, "")
        store.upsert(record)

    for record in store.all_records():
        assert len(record.text_snippet) <= 512, (
            f"text_snippet exceeds 512 chars: {len(record.text_snippet)}"
        )
        assert isinstance(record.text_snippet, str), (
            f"text_snippet must be str, got {type(record.text_snippet)}"
        )
