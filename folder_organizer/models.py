"""Shared data models — all pipeline DTOs and MetadataRecord."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExtractionStatus(str, Enum):
    """Status of text extraction from a file."""

    OK = "ok"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Pipeline stage DTOs
# ---------------------------------------------------------------------------

@dataclass
class DiscoveredFile:
    """A file path found during the discovery stage."""

    path: Path


@dataclass
class DiscoveryResult:
    """Output of the FileDiscoverer stage."""

    discovered: list[Path]
    skipped_symlinks: int
    excluded_count: int


@dataclass
class InspectedFile:
    """A file enriched with MIME type, hash, size, and optional extracted text."""

    path: Path
    sha256: str
    size_bytes: int
    mime_type: str
    extracted_text: Optional[str]
    char_count: Optional[int]
    extraction_status: ExtractionStatus


@dataclass
class CategorizedFile:
    """An inspected file that has been assigned a category and confidence score."""

    path: Path
    sha256: str
    size_bytes: int
    mime_type: str
    extracted_text: Optional[str]
    char_count: Optional[int]
    extraction_status: str
    category: str
    subcategory: Optional[str]
    confidence: float
    method: str  # "ai" | "fallback"
    review_required: bool
    fallback_used: bool


@dataclass
class CategorizationResult:
    """The result of categorizing a single file."""

    category: str
    subcategory: Optional[str]
    confidence: float
    method: Literal["ai", "fallback"]
    review_required: bool
    fallback_used: bool


@dataclass
class PlacedFile:
    """A categorized file whose destination directory has been resolved."""

    source_path: Path
    destination_dir: Path
    destination_filename: str  # original filename; conflict suffix added by FileMover
    review_required: bool
    unplaced: bool


@dataclass
class MoveResult:
    """The outcome of a single file-move operation."""

    source_path: Path
    destination_path: Optional[Path]
    success: bool
    skip_reason: Optional[str] = None


@dataclass
class FolderCreationError:
    """Recorded when a destination folder could not be created."""

    path: Path
    reason: str


@dataclass
class RunSummary:
    """Aggregate counts reported at the end of an organizer run."""

    total_discovered: int
    total_processed: int
    total_moved: int
    total_skipped: int
    total_review: int
    total_unplaced: int
    total_errors: int
    dry_run: bool


# ---------------------------------------------------------------------------
# Persistent record
# ---------------------------------------------------------------------------

@dataclass
class MetadataRecord:
    """Per-file record persisted to organizer-metadata.json.

    All fields are plain Python scalars so that ``dataclasses.asdict`` produces
    a JSON-serializable dict without any custom encoder.
    """

    original_path: str          # absolute path at time of processing
    destination_path: str       # absolute path after move ("" if not moved yet)
    sha256: str                 # hex-encoded SHA-256 of full binary content
    size_bytes: int
    mime_type: str
    text_snippet: str           # up to 512 chars of extracted text
    category: str
    subcategory: Optional[str]
    confidence_score: float     # [0.0, 1.0]
    method: str                 # "ai" | "fallback"
    review_required: bool
    fallback_used: bool
    extraction_status: str      # "ok" | "unavailable" | "failed"
    timestamp: str              # ISO 8601, e.g. "2024-01-15T10:23:45Z"

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MetadataRecord":
        """Reconstruct a ``MetadataRecord`` from a plain dictionary.

        Unknown keys are silently ignored so that future schema additions
        are backwards-compatible when reading older records.
        """
        known_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def to_json(self) -> str:
        """Serialize this record to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "MetadataRecord":
        """Deserialize a ``MetadataRecord`` from a JSON string."""
        return cls.from_dict(json.loads(text))
