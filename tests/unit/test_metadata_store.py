"""Unit tests for MetadataStore.

Tests cover:
- load of existing organizer-metadata.json populates records correctly
- upsert overwrites existing record by path
- flush writes organizer-metadata.json atomically (temp file → rename)
- flush failure logs error but does not abort run
- skip re-processing when sha256 + category match (Requirement 5.5)
- overwrite when sha256 matches but category differs (Requirement 5.7)

Requirements: 5.3, 5.4, 5.5, 5.6, 5.7
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import MetadataRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    original_path: str,
    *,
    sha256: str = "abc123",
    category: str = "Documents",
    subcategory: str | None = "Reports",
    destination_path: str = "",
) -> MetadataRecord:
    """Build a minimal but valid MetadataRecord."""
    return MetadataRecord(
        original_path=original_path,
        destination_path=destination_path,
        sha256=sha256,
        size_bytes=1024,
        mime_type="application/pdf",
        text_snippet="Sample text",
        category=category,
        subcategory=subcategory,
        confidence_score=0.95,
        method="ai",
        review_required=False,
        fallback_used=False,
        extraction_status="ok",
        timestamp="2024-01-15T10:23:45Z",
    )


def _write_metadata_json(target_dir: Path, records: list[MetadataRecord]) -> None:
    """Write an organizer-metadata.json file with the given records."""
    payload = {
        "version": "1",
        "records": {r.original_path: r.to_dict() for r in records},
    }
    (target_dir / "organizer-metadata.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 1. load populates records correctly  (Req 5.3)
# ---------------------------------------------------------------------------

class TestMetadataStoreLoad:
    """Load behaviour: reading an existing organizer-metadata.json."""

    def test_load_populates_records_by_path(self, tmp_path: Path) -> None:
        """Records from organizer-metadata.json are accessible by original_path."""
        path_str = str(tmp_path / "file.pdf")
        record = _make_record(path_str, sha256="abc123")
        _write_metadata_json(tmp_path, [record])

        store = MetadataStore()
        store.load(tmp_path)

        result = store.get_by_path(Path(path_str))
        assert result is not None
        assert result.original_path == path_str
        assert result.sha256 == "abc123"
        assert result.category == "Documents"

    def test_load_populates_secondary_hash_index(self, tmp_path: Path) -> None:
        """Records loaded from file are also accessible by sha256."""
        path_str = str(tmp_path / "report.docx")
        record = _make_record(path_str, sha256="deadbeef")
        _write_metadata_json(tmp_path, [record])

        store = MetadataStore()
        store.load(tmp_path)

        result = store.get_by_hash("deadbeef")
        assert result is not None
        assert result.original_path == path_str

    def test_load_multiple_records(self, tmp_path: Path) -> None:
        """All records present in the JSON file are loaded into the store."""
        path_a = str(tmp_path / "a.pdf")
        path_b = str(tmp_path / "b.txt")
        path_c = str(tmp_path / "c.png")
        records = [
            _make_record(path_a, sha256="hash_a", category="Finance"),
            _make_record(path_b, sha256="hash_b", category="Documents"),
            _make_record(path_c, sha256="hash_c", category="Images"),
        ]
        _write_metadata_json(tmp_path, records)

        store = MetadataStore()
        store.load(tmp_path)

        assert store.get_by_path(Path(path_a)) is not None
        assert store.get_by_path(Path(path_b)) is not None
        assert store.get_by_path(Path(path_c)) is not None

    def test_load_nonexistent_file_is_silent(self, tmp_path: Path) -> None:
        """Loading when no organizer-metadata.json exists is a no-op (no exception)."""
        store = MetadataStore()
        store.load(tmp_path)  # should not raise

        assert store.all_records() == []

    def test_load_preserves_all_record_fields(self, tmp_path: Path) -> None:
        """Every field of MetadataRecord is round-tripped through load correctly."""
        path_str = str(tmp_path / "invoice.pdf")
        dest_str = str(tmp_path / "Finance" / "Invoices" / "invoice.pdf")
        original = MetadataRecord(
            original_path=path_str,
            destination_path=dest_str,
            sha256="cafebabe",
            size_bytes=2048,
            mime_type="application/pdf",
            text_snippet="Invoice #1234",
            category="Finance",
            subcategory="Invoices",
            confidence_score=0.95,
            method="ai",
            review_required=False,
            fallback_used=False,
            extraction_status="ok",
            timestamp="2024-01-15T10:23:45Z",
        )
        _write_metadata_json(tmp_path, [original])

        store = MetadataStore()
        store.load(tmp_path)

        loaded = store.get_by_path(Path(path_str))
        assert loaded == original

    def test_load_corrupted_json_starts_with_empty_store(self, tmp_path: Path) -> None:
        """A corrupted JSON file results in an empty store (no exception raised)."""
        (tmp_path / "organizer-metadata.json").write_text(
            "{ this is not valid json }", encoding="utf-8"
        )

        store = MetadataStore()
        store.load(tmp_path)  # should not raise

        assert store.all_records() == []

    def test_load_skips_malformed_individual_records(self, tmp_path: Path) -> None:
        """Malformed records within an otherwise valid file are skipped gracefully."""
        good_path = str(tmp_path / "good.pdf")
        bad_path = str(tmp_path / "bad.pdf")
        good_record = _make_record(good_path, sha256="aaa")
        payload = {
            "version": "1",
            "records": {
                good_path: good_record.to_dict(),
                bad_path: {"broken": "record", "no_required_fields": True},
            },
        }
        (tmp_path / "organizer-metadata.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        store = MetadataStore()
        store.load(tmp_path)

        assert store.get_by_path(Path(good_path)) is not None
        assert store.get_by_path(Path(bad_path)) is None


# ---------------------------------------------------------------------------
# 2. upsert inserts and overwrites  (Req 5.3, 5.4)
# ---------------------------------------------------------------------------

class TestMetadataStoreUpsert:
    """Upsert behaviour: insert new records and overwrite existing ones."""

    def test_upsert_inserts_new_record(self, tmp_path: Path) -> None:
        """A new record is reachable by path after upsert."""
        path_str = str(tmp_path / "new.pdf")
        store = MetadataStore()
        record = _make_record(path_str, sha256="new123")
        store.upsert(record)

        assert store.get_by_path(Path(path_str)) is record

    def test_upsert_makes_record_reachable_by_hash(self, tmp_path: Path) -> None:
        """After upsert, the record is also reachable by sha256."""
        path_str = str(tmp_path / "new.pdf")
        store = MetadataStore()
        record = _make_record(path_str, sha256="newhash")
        store.upsert(record)

        assert store.get_by_hash("newhash") is record

    def test_upsert_overwrites_existing_record_by_path(self, tmp_path: Path) -> None:
        """Upserting a record with the same path replaces the previous record."""
        path_str = str(tmp_path / "file.pdf")
        store = MetadataStore()
        original = _make_record(path_str, sha256="oldhash", category="Documents")
        store.upsert(original)

        updated = _make_record(path_str, sha256="newhash", category="Finance")
        store.upsert(updated)

        result = store.get_by_path(Path(path_str))
        assert result is updated
        assert result.category == "Finance"
        assert result.sha256 == "newhash"

    def test_upsert_updates_hash_index_on_overwrite(self, tmp_path: Path) -> None:
        """After overwriting a record, the sha256 index reflects the new hash."""
        path_str = str(tmp_path / "file.pdf")
        store = MetadataStore()
        store.upsert(_make_record(path_str, sha256="oldhash"))

        updated = _make_record(path_str, sha256="newhash")
        store.upsert(updated)

        # New hash resolves to the updated record
        assert store.get_by_hash("newhash") is updated

    def test_upsert_multiple_records_distinct_paths(self, tmp_path: Path) -> None:
        """Multiple distinct records coexist in the store after upsert."""
        path_a = str(tmp_path / "a.pdf")
        path_b = str(tmp_path / "b.txt")
        store = MetadataStore()
        r1 = _make_record(path_a, sha256="h1", category="Finance")
        r2 = _make_record(path_b, sha256="h2", category="Documents")
        store.upsert(r1)
        store.upsert(r2)

        assert store.get_by_path(Path(path_a)) is r1
        assert store.get_by_path(Path(path_b)) is r2


# ---------------------------------------------------------------------------
# 3. flush writes atomically  (Req 5.3)
# ---------------------------------------------------------------------------

class TestMetadataStoreFlush:
    """Flush behaviour: atomic write to organizer-metadata.json."""

    def test_flush_creates_metadata_json(self, tmp_path: Path) -> None:
        """After flush, organizer-metadata.json exists in target_dir."""
        store = MetadataStore()
        store.upsert(_make_record(str(tmp_path / "file.pdf")))
        store.flush(tmp_path)

        assert (tmp_path / "organizer-metadata.json").exists()

    def test_flush_writes_correct_version_field(self, tmp_path: Path) -> None:
        """The flushed JSON has version = '1'."""
        store = MetadataStore()
        store.flush(tmp_path)

        data = json.loads((tmp_path / "organizer-metadata.json").read_text(encoding="utf-8"))
        assert data["version"] == "1"

    def test_flush_persists_upserted_records(self, tmp_path: Path) -> None:
        """All upserted records are present in the flushed JSON file."""
        path_a = str(tmp_path / "a.pdf")
        path_b = str(tmp_path / "b.txt")
        store = MetadataStore()
        store.upsert(_make_record(path_a, sha256="h1", category="Finance"))
        store.upsert(_make_record(path_b, sha256="h2", category="Documents"))
        store.flush(tmp_path)

        data = json.loads((tmp_path / "organizer-metadata.json").read_text(encoding="utf-8"))
        assert path_a in data["records"]
        assert path_b in data["records"]
        assert data["records"][path_a]["category"] == "Finance"

    def test_flush_is_atomic_via_temp_file(self, tmp_path: Path) -> None:
        """Flush uses a sibling .tmp file and renames it — no lingering temp files."""
        store = MetadataStore()
        store.upsert(_make_record(str(tmp_path / "doc.pdf")))

        before = set(tmp_path.iterdir())
        store.flush(tmp_path)
        after = set(tmp_path.iterdir())

        # Only the final metadata file should remain — no .tmp files
        new_files = after - before
        assert len(new_files) == 1
        assert (tmp_path / "organizer-metadata.json") in new_files

    def test_flush_overwrites_existing_metadata_json(self, tmp_path: Path) -> None:
        """Flushing twice replaces the previous file with updated content."""
        path_a = str(tmp_path / "a.pdf")
        path_b = str(tmp_path / "b.pdf")
        store = MetadataStore()
        store.upsert(_make_record(path_a, sha256="h1", category="Finance"))
        store.flush(tmp_path)

        # Add another record and flush again
        store.upsert(_make_record(path_b, sha256="h2", category="Images"))
        store.flush(tmp_path)

        data = json.loads((tmp_path / "organizer-metadata.json").read_text(encoding="utf-8"))
        assert path_a in data["records"]
        assert path_b in data["records"]

    def test_flush_round_trip_preserves_all_fields(self, tmp_path: Path) -> None:
        """A record written by flush can be read back with all fields intact."""
        path_str = str(tmp_path / "invoice.pdf")
        dest_str = str(tmp_path / "Finance" / "Invoices" / "invoice.pdf")
        original = MetadataRecord(
            original_path=path_str,
            destination_path=dest_str,
            sha256="cafebabe",
            size_bytes=2048,
            mime_type="application/pdf",
            text_snippet="Invoice #1234",
            category="Finance",
            subcategory="Invoices",
            confidence_score=0.95,
            method="ai",
            review_required=False,
            fallback_used=False,
            extraction_status="ok",
            timestamp="2024-01-15T10:23:45Z",
        )
        store = MetadataStore()
        store.upsert(original)
        store.flush(tmp_path)

        fresh = MetadataStore()
        fresh.load(tmp_path)

        loaded = fresh.get_by_path(Path(path_str))
        assert loaded == original


# ---------------------------------------------------------------------------
# 4. flush failure logs error but does not abort  (Req 5.4)
# ---------------------------------------------------------------------------

class TestMetadataStoreFlushFailure:
    """Flush failure: error is logged; in-memory records are retained."""

    def test_flush_failure_does_not_raise(self, tmp_path: Path) -> None:
        """When os.replace fails, flush does not propagate the exception."""
        store = MetadataStore()
        store.upsert(_make_record(str(tmp_path / "file.pdf")))

        with patch("folder_organizer.metadata_store.os.replace", side_effect=OSError("disk full")):
            store.flush(tmp_path)  # must not raise

    def test_flush_failure_logs_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An error is logged when the flush write fails."""
        store = MetadataStore()
        store.upsert(_make_record(str(tmp_path / "file.pdf")))

        with patch("folder_organizer.metadata_store.os.replace", side_effect=OSError("disk full")):
            with caplog.at_level(logging.ERROR, logger="folder_organizer.metadata_store"):
                store.flush(tmp_path)

        assert len(caplog.records) >= 1
        assert any(
            "failed" in r.message.lower() or "disk full" in r.message.lower()
            for r in caplog.records
        )

    def test_flush_failure_preserves_in_memory_records(self, tmp_path: Path) -> None:
        """Records remain accessible in the store even after a failed flush."""
        path_str = str(tmp_path / "important.pdf")
        record = _make_record(path_str, sha256="keepme")
        store = MetadataStore()
        store.upsert(record)

        with patch("folder_organizer.metadata_store.os.replace", side_effect=OSError("nope")):
            store.flush(tmp_path)

        # In-memory records must still be intact
        result = store.get_by_path(Path(path_str))
        assert result is not None
        assert result.sha256 == "keepme"
        assert store.get_by_hash("keepme") is not None

    def test_flush_failure_cleans_up_temp_file(self, tmp_path: Path) -> None:
        """No leftover .tmp files remain after a failed flush."""
        store = MetadataStore()
        store.upsert(_make_record(str(tmp_path / "file.pdf")))

        with patch("folder_organizer.metadata_store.os.replace", side_effect=OSError("fail")):
            store.flush(tmp_path)

        tmp_files = list(tmp_path.glob(".organizer-metadata-*.tmp"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# 5. should_skip — sha256 + category match → skip  (Req 5.5)
# ---------------------------------------------------------------------------

class TestMetadataStoreShouldSkip:
    """should_skip: reuse decision based on sha256 + category match."""

    def test_skip_when_hash_and_category_match(self, tmp_path: Path) -> None:
        """should_skip returns True when both sha256 and category are identical."""
        store = MetadataStore()
        store.upsert(_make_record(str(tmp_path / "file.pdf"), sha256="abc", category="Finance"))

        assert store.should_skip("abc", "Finance") is True

    def test_no_skip_when_hash_matches_but_category_differs(self, tmp_path: Path) -> None:
        """should_skip returns False when sha256 matches but category has changed (Req 5.7)."""
        store = MetadataStore()
        store.upsert(_make_record(str(tmp_path / "file.pdf"), sha256="abc", category="Finance"))

        assert store.should_skip("abc", "Documents") is False

    def test_no_skip_when_hash_not_found(self) -> None:
        """should_skip returns False for an unknown sha256."""
        store = MetadataStore()

        assert store.should_skip("unknownhash", "Finance") is False

    def test_skip_after_load_from_disk(self, tmp_path: Path) -> None:
        """should_skip works correctly for records loaded from organizer-metadata.json."""
        path_str = str(tmp_path / "file.pdf")
        record = _make_record(path_str, sha256="diskhash", category="Images")
        _write_metadata_json(tmp_path, [record])

        store = MetadataStore()
        store.load(tmp_path)

        assert store.should_skip("diskhash", "Images") is True
        assert store.should_skip("diskhash", "Documents") is False

    def test_empty_store_never_skips(self) -> None:
        """An empty store never signals skip for any hash."""
        store = MetadataStore()
        assert store.should_skip("anyhash", "AnyCategory") is False


# ---------------------------------------------------------------------------
# 6. Overwrite when sha256 matches but category differs  (Req 5.7)
# ---------------------------------------------------------------------------

class TestMetadataStoreOverwrite:
    """Overwrite behaviour when sha256 matches but category has changed."""

    def test_upsert_replaces_record_with_new_category(self, tmp_path: Path) -> None:
        """When sha256 is the same but category differs, upsert stores the new record."""
        path_str = str(tmp_path / "file.pdf")
        store = MetadataStore()
        store.upsert(_make_record(path_str, sha256="shared", category="Finance"))
        store.upsert(_make_record(path_str, sha256="shared", category="Documents"))

        result = store.get_by_path(Path(path_str))
        assert result is not None
        assert result.category == "Documents"

    def test_hash_index_updated_after_overwrite(self, tmp_path: Path) -> None:
        """The sha256 index points to the new record after an overwrite."""
        path_str = str(tmp_path / "file.pdf")
        store = MetadataStore()
        store.upsert(_make_record(path_str, sha256="shared", category="Finance"))

        new_record = _make_record(path_str, sha256="shared", category="Documents")
        store.upsert(new_record)

        assert store.get_by_hash("shared") is new_record

    def test_should_skip_false_after_category_change(self, tmp_path: Path) -> None:
        """After a category change, should_skip returns False for the old category."""
        path_str = str(tmp_path / "file.pdf")
        store = MetadataStore()
        store.upsert(_make_record(path_str, sha256="shared", category="Finance"))

        # Simulate re-categorization with a different category
        assert store.should_skip("shared", "Documents") is False

    def test_should_skip_true_after_re_upsert_with_new_category(self, tmp_path: Path) -> None:
        """After upserting the new category, should_skip returns True for that new category."""
        path_str = str(tmp_path / "file.pdf")
        store = MetadataStore()
        store.upsert(_make_record(path_str, sha256="shared", category="Finance"))
        store.upsert(_make_record(path_str, sha256="shared", category="Documents"))

        # Now the new category is stored; should skip for "Documents"
        assert store.should_skip("shared", "Documents") is True
        # But not for the old one
        assert store.should_skip("shared", "Finance") is False

    def test_overwrite_persists_through_flush_and_reload(self, tmp_path: Path) -> None:
        """An overwritten record is correctly persisted and reloaded."""
        path_str = str(tmp_path / "file.pdf")
        store = MetadataStore()
        store.upsert(_make_record(path_str, sha256="shared", category="Finance"))
        store.upsert(_make_record(path_str, sha256="shared", category="Documents"))
        store.flush(tmp_path)

        fresh = MetadataStore()
        fresh.load(tmp_path)

        result = fresh.get_by_path(Path(path_str))
        assert result is not None
        assert result.category == "Documents"


# ---------------------------------------------------------------------------
# 7. Merge semantics — existing records not in current run are preserved  (Req 5.6)
# ---------------------------------------------------------------------------

class TestMetadataStoreMerge:
    """Merge: records from previous runs are retained after load."""

    def test_load_retains_records_not_in_current_run(self, tmp_path: Path) -> None:
        """Records loaded from disk persist even when not re-upserted in the current run."""
        old_path = str(tmp_path / "old_file.pdf")
        new_path = str(tmp_path / "new_file.txt")
        old_record = _make_record(old_path, sha256="oldhash", category="Finance")
        _write_metadata_json(tmp_path, [old_record])

        store = MetadataStore()
        store.load(tmp_path)

        # Only upsert a new, different record — don't touch old_file.pdf
        new_record = _make_record(new_path, sha256="newhash", category="Documents")
        store.upsert(new_record)
        store.flush(tmp_path)

        # Reload and verify the old record is still present
        fresh = MetadataStore()
        fresh.load(tmp_path)

        assert fresh.get_by_path(Path(old_path)) is not None
        assert fresh.get_by_path(Path(new_path)) is not None

    def test_all_records_includes_both_old_and_new(self, tmp_path: Path) -> None:
        """all_records() returns both loaded and newly upserted records."""
        alpha_path = str(tmp_path / "alpha.pdf")
        beta_path = str(tmp_path / "beta.pdf")
        old_record = _make_record(alpha_path, sha256="h_alpha")
        _write_metadata_json(tmp_path, [old_record])

        store = MetadataStore()
        store.load(tmp_path)

        new_record = _make_record(beta_path, sha256="h_beta")
        store.upsert(new_record)

        all_paths = {r.original_path for r in store.all_records()}
        assert alpha_path in all_paths
        assert beta_path in all_paths
