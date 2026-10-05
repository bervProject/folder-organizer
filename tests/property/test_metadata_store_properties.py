# Feature: local-file-organizer, Property 7: Metadata merge preserves existing records

"""Property-based tests for MetadataStore merge behavior.

Validates: Requirements 5.6
"""

import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import MetadataRecord


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_method_st = st.sampled_from(["ai", "fallback"])
_extraction_status_st = st.sampled_from(["ok", "unavailable", "failed"])


def _metadata_record_strategy(path_prefix: str = ""):
    """Strategy that builds a MetadataRecord with a unique-ish original_path."""
    return st.builds(
        MetadataRecord,
        original_path=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1,
        ).map(lambda s: f"{path_prefix}/{s}"),
        destination_path=st.text(),
        sha256=st.text(
            alphabet="0123456789abcdef", min_size=64, max_size=64
        ),
        size_bytes=st.integers(min_value=0),
        mime_type=st.text(min_size=1),
        text_snippet=st.text(),
        category=st.text(min_size=1),
        subcategory=st.one_of(st.none(), st.text(min_size=1)),
        confidence_score=st.floats(
            min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
        method=_method_st,
        review_required=st.booleans(),
        fallback_used=st.booleans(),
        extraction_status=_extraction_status_st,
        timestamp=st.just("2024-01-15T10:23:45Z"),
    )


# Two disjoint sets: "existing" records get paths under /run1/,
# "new" records get paths under /run2/, guaranteeing no path overlap.
_existing_records_st = st.lists(
    _metadata_record_strategy("/run1"),
    min_size=1,
    max_size=10,
)

_new_records_st = st.lists(
    _metadata_record_strategy("/run2"),
    min_size=0,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(existing=_existing_records_st, new=_new_records_st)
@settings(max_examples=100)
def test_metadata_merge_preserves_existing_records(
    existing: list[MetadataRecord],
    new: list[MetadataRecord],
) -> None:
    """Merging a new set of records into an existing store preserves all prior records.

    Validates: Requirements 5.6 — WHEN a subsequent run starts and an existing
    ``organizer-metadata.json`` is present in the Target_Directory, THE Organizer
    SHALL merge new and updated MetadataRecords into the existing store, keyed by
    original file path, without removing records for files not encountered in the
    current run.
    """
    # Use a fresh temp directory for each generated example so state never
    # leaks between Hypothesis iterations.
    with tempfile.TemporaryDirectory() as _tmpdir:
        tmp_path = Path(_tmpdir)

        # Deduplicate by original_path (last value wins, matching JSON dict
        # semantics) so the on-disk payload and assertion set are consistent.
        existing_by_path: dict[str, MetadataRecord] = {}
        for r in existing:
            existing_by_path[r.original_path] = r
        existing_deduped = list(existing_by_path.values())

        # --- Step 1: persist the "existing" (run-1) records to disk ---
        existing_payload = {
            "version": "1",
            "records": {r.original_path: r.to_dict() for r in existing_deduped},
        }
        metadata_file = tmp_path / "organizer-metadata.json"
        metadata_file.write_text(
            json.dumps(existing_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # --- Step 2: load the store (simulates a new run finding the existing file) ---
        store = MetadataStore()
        store.load(tmp_path)

        # --- Step 3: upsert the "new" (run-2) records (disjoint paths from /run2/) ---
        for record in new:
            store.upsert(record)

        # --- Step 4: assert every run-1 record is still present in the store ---
        for record in existing_deduped:
            stored = store.get_by_path(record.original_path)
            assert stored is not None, (
                f"Record for path {record.original_path!r} was removed from the store "
                f"after merging {len(new)} new records — merge must not delete existing entries."
            )
            assert stored == record, (
                f"Record for path {record.original_path!r} was modified during merge. "
                f"Expected {record!r}, got {stored!r}."
            )
