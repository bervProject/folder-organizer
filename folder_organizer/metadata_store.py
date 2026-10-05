"""Metadata Store — load, upsert, merge, and atomic flush of organizer-metadata.json."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from folder_organizer.models import MetadataRecord

_METADATA_FILENAME = "organizer-metadata.json"
_SCHEMA_VERSION = "1"

logger = logging.getLogger(__name__)


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

        Existing records not encountered in the current run are preserved
        (keyed by path) to satisfy merge semantics (Requirement 5.6).
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

        On failure, logs the error and retains all in-memory records without
        aborting or re-raising (Requirement 5.4).
        """
        dest = target_dir / _METADATA_FILENAME

        payload = {
            "version": _SCHEMA_VERSION,
            "records": {
                path: record.to_dict()
                for path, record in self._records.items()
            },
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)

        fd: Optional[int] = None
        tmp_path: Optional[str] = None
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            # Write to a sibling temp file, then rename atomically
            fd, tmp_path = tempfile.mkstemp(
                dir=str(target_dir),
                prefix=".organizer-metadata-",
                suffix=".tmp",
            )
            os.write(fd, text.encode("utf-8"))
            os.close(fd)
            fd = None
            os.replace(tmp_path, str(dest))
            tmp_path = None
        except Exception as exc:
            logger.error(
                "Failed to write %s: %s — in-memory records are preserved for this run.",
                dest,
                exc,
            )
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            # Do NOT re-raise: Requirement 5.4 says retain in-memory records
            # without aborting file processing.

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

    def should_skip(self, sha256: str, category: str) -> bool:
        """Return whether a file should be skipped (i.e. reuse existing record).

        Returns ``True`` if a record with the same *sha256* **and** the same
        *category* already exists — the file can be skipped without
        re-processing (Requirement 5.5).

        Returns ``False`` if a record with the same *sha256* exists but with a
        **different** *category* — the file must be re-processed and the
        existing record overwritten (Requirement 5.7).

        Returns ``False`` if no record with *sha256* exists at all.
        """
        existing = self._by_hash.get(sha256)
        if existing is None:
            return False
        return existing.category == category

    def all_records(self) -> list[MetadataRecord]:
        """Return a snapshot of all records currently in the store."""
        return list(self._records.values())
