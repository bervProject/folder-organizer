"""Metadata Store — load, upsert, merge, and atomic flush of organizer-metadata.json."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from folder_organizer.models import MetadataRecord

_METADATA_FILENAME = "organizer-metadata.json"
_SCHEMA_VERSION = "1"


class MetadataStore:
    """In-memory store for :class:`MetadataRecord` objects backed by
    ``organizer-metadata.json`` on disk.

    The store is keyed by ``original_path`` (string) with a secondary index
    keyed by ``sha256`` for fast duplicate-detection lookups.

    Usage::

        store = MetadataStore()
        store.load(target_dir)          # load existing records (if any)
        store.upsert(record)            # add / replace a record
        store.flush(target_dir)         # write back atomically
    """

    def __init__(self) -> None:
        # Primary index: original_path → MetadataRecord
        self._records: dict[str, MetadataRecord] = {}
        # Secondary index: sha256 → MetadataRecord (most-recently upserted wins)
        self._by_hash: dict[str, MetadataRecord] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, target_dir: Path) -> None:
        """Populate the in-memory store from *target_dir*/organizer-metadata.json.

        Silently does nothing if the file does not exist.  Unknown top-level
        keys and unknown record keys are ignored for forward compatibility.
        """
        path = target_dir / _METADATA_FILENAME
        if not path.exists():
            return

        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, json.JSONDecodeError):
            # Corrupted or unreadable file — start with empty store
            return

        records_raw = data.get("records", {})
        for _key, record_dict in records_raw.items():
            try:
                record = MetadataRecord.from_dict(record_dict)
                self._records[record.original_path] = record
                self._by_hash[record.sha256] = record
            except (TypeError, KeyError):
                # Skip malformed records
                continue

    def flush(self, target_dir: Path) -> None:
        """Write all in-memory records to *target_dir*/organizer-metadata.json.

        The write is atomic: records are written to a temp file in the same
        directory, then renamed over the destination file.

        Raises :class:`OSError` if the write fails (callers should handle this
        and report the error without aborting).
        """
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / _METADATA_FILENAME

        payload = {
            "version": _SCHEMA_VERSION,
            "records": {
                path: record.to_dict()
                for path, record in self._records.items()
            },
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)

        # Write to a sibling temp file, then rename atomically
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target_dir),
            prefix=".organizer-metadata-",
            suffix=".tmp",
        )
        try:
            os.write(fd, text.encode("utf-8"))
            os.close(fd)
            os.replace(tmp_path, str(dest))
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_by_path(self, path: Path) -> Optional[MetadataRecord]:
        """Return the record for *path* or ``None`` if not present."""
        return self._records.get(str(path))

    def get_by_hash(self, sha256: str) -> Optional[MetadataRecord]:
        """Return the most-recently upserted record with hash *sha256*, or ``None``."""
        return self._by_hash.get(sha256)

    def upsert(self, record: MetadataRecord) -> None:
        """Insert or replace the record keyed by ``original_path``."""
        self._records[record.original_path] = record
        self._by_hash[record.sha256] = record

    def all_records(self) -> list[MetadataRecord]:
        """Return a snapshot of all records currently in the store."""
        return list(self._records.values())
