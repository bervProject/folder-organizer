# Feature: local-file-organizer, Property 1: Metadata round-trip fidelity

"""Property-based tests for MetadataRecord serialization round-trips.

Validates: Requirements 5.2, 5.3
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from folder_organizer.models import MetadataRecord


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Constrain method and extraction_status to their documented valid values so
# the round-trip tests exercise realistic records.  Using st.text() for those
# fields would still pass (the serialization is field-agnostic), but a more
# focused strategy surfaces problems with enum-like string constraints faster.
_method_st = st.sampled_from(["ai", "fallback"])
_extraction_status_st = st.sampled_from(["ok", "unavailable", "failed"])

metadata_record_strategy = st.builds(
    MetadataRecord,
    original_path=st.text(),
    destination_path=st.text(),
    sha256=st.text(),
    size_bytes=st.integers(),
    mime_type=st.text(),
    text_snippet=st.text(),
    category=st.text(),
    subcategory=st.one_of(st.none(), st.text()),
    confidence_score=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    method=_method_st,
    review_required=st.booleans(),
    fallback_used=st.booleans(),
    extraction_status=_extraction_status_st,
    timestamp=st.text(),
)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@given(metadata_record_strategy)
@settings(max_examples=100)
def test_metadata_dict_roundtrip(record: MetadataRecord) -> None:
    """Serializing to dict and back produces a record equal to the original.

    Validates: Requirements 5.2, 5.3
    """
    assert MetadataRecord.from_dict(record.to_dict()) == record


@given(metadata_record_strategy)
@settings(max_examples=100)
def test_metadata_json_roundtrip(record: MetadataRecord) -> None:
    """Serializing to JSON and back produces a record equal to the original.

    Validates: Requirements 5.2, 5.3
    """
    assert MetadataRecord.from_json(record.to_json()) == record
