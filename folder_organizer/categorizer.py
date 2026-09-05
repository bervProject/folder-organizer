"""AI Categorizer — OpenAI structured outputs and extension-based fallback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from openai import OpenAI

from folder_organizer.config import Config
from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import (
    CategorizationResult,
    InspectedFile,
    MetadataRecord,
)
from folder_organizer.taxonomy import build_taxonomy

# ---------------------------------------------------------------------------
# Extension → category fallback map
# ---------------------------------------------------------------------------

_EXT_TO_CATEGORY: dict[str, str] = {
    # Documents
    ".pdf": "Documents",
    ".doc": "Documents",
    ".docx": "Documents",
    ".odt": "Documents",
    ".rtf": "Documents",
    ".txt": "Documents",
    ".md": "Documents",
    # Images
    ".jpg": "Images",
    ".jpeg": "Images",
    ".png": "Images",
    ".gif": "Images",
    ".webp": "Images",
    ".bmp": "Images",
    ".tiff": "Images",
    ".tif": "Images",
    ".svg": "Images",
    ".ico": "Images",
    # Videos
    ".mp4": "Videos",
    ".mov": "Videos",
    ".avi": "Videos",
    ".mkv": "Videos",
    ".wmv": "Videos",
    ".flv": "Videos",
    ".webm": "Videos",
    # Audio
    ".mp3": "Audio",
    ".wav": "Audio",
    ".flac": "Audio",
    ".aac": "Audio",
    ".ogg": "Audio",
    ".m4a": "Audio",
    # Code
    ".py": "Code",
    ".js": "Code",
    ".ts": "Code",
    ".java": "Code",
    ".c": "Code",
    ".cpp": "Code",
    ".cc": "Code",
    ".h": "Code",
    ".hpp": "Code",
    ".go": "Code",
    ".rs": "Code",
    ".rb": "Code",
    ".php": "Code",
    ".swift": "Code",
    ".kt": "Code",
    ".cs": "Code",
    ".sh": "Code",
    ".bash": "Code",
    ".zsh": "Code",
    ".ps1": "Code",
    # Archives
    ".zip": "Archives",
    ".tar": "Archives",
    ".gz": "Archives",
    ".bz2": "Archives",
    ".xz": "Archives",
    ".rar": "Archives",
    ".7z": "Archives",
    ".tgz": "Archives",
    # Spreadsheets
    ".xlsx": "Spreadsheets",
    ".xls": "Spreadsheets",
    ".ods": "Spreadsheets",
    ".csv": "Spreadsheets",
    # Presentations
    ".pptx": "Presentations",
    ".ppt": "Presentations",
    ".odp": "Presentations",
    # Fonts
    ".ttf": "Fonts",
    ".otf": "Fonts",
    ".woff": "Fonts",
    ".woff2": "Fonts",
    ".eot": "Fonts",
    # Executables
    ".exe": "Executables",
    ".dll": "Executables",
    ".so": "Executables",
    ".dylib": "Executables",
    ".bin": "Executables",
    ".apk": "Executables",
    ".app": "Executables",
    # Data
    ".json": "Data",
    ".xml": "Data",
    ".yaml": "Data",
    ".yml": "Data",
    ".toml": "Data",
    ".ini": "Data",
    ".cfg": "Data",
    ".sql": "Data",
    ".db": "Data",
    ".sqlite": "Data",
}

# JSON schema for structured output
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "subcategory": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["category", "subcategory", "confidence"],
    "additionalProperties": False,
}


class AICategorizer:
    """Categorize files using the OpenAI API with extension-based fallback."""

    def __init__(self, config: Config, metadata_store: MetadataStore) -> None:
        self._config = config
        self._metadata_store = metadata_store
        self._taxonomy = build_taxonomy(config.taxonomy)
        # Build the OpenAI client.  The config.ai_endpoint is the full URL
        # (e.g. "https://api.openai.com/v1/chat/completions").  We pass only
        # the base portion up to /v1 as base_url so the SDK can append the
        # correct path.  If the endpoint already ends before a path component
        # we use it as-is.
        base_url = _derive_base_url(config.ai_endpoint)
        self._client = OpenAI(api_key=config.ai_api_key or "dummy", base_url=base_url)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def categorize(
        self,
        file: InspectedFile,
        existing_record: Optional[MetadataRecord] = None,
    ) -> CategorizationResult:
        """Categorize *file*, reusing cached results when possible.

        If the metadata store already has a record with the same SHA-256 hash
        and a non-empty category, that record is reused without calling the AI.
        Otherwise the AI is called; on any exception the fallback is used.
        """
        # ---- 1. Deduplication check ------------------------------------------
        cached = self._metadata_store.get_by_hash(file.sha256)
        if cached is not None and cached.category:
            return CategorizationResult(
                category=cached.category,
                subcategory=cached.subcategory,
                confidence=cached.confidence_score,
                method=cached.method,
                review_required=cached.review_required,
                fallback_used=cached.fallback_used,
            )

        # ---- 2. Try AI -----------------------------------------------------------
        try:
            result = self._ai_categorize(file)
        except Exception:
            return self._fallback_categorize(file)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ai_categorize(self, file: InspectedFile) -> CategorizationResult:
        """Call the OpenAI API and parse the structured response."""
        prompt = _build_prompt(file, list(self._taxonomy))

        response = self._client.chat.completions.create(
            model=self._config.ai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a file categorization assistant. "
                        "Respond only with a JSON object matching the provided schema."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "file_category",
                    "strict": True,
                    "schema": _RESPONSE_SCHEMA,
                },
            },
        )

        content = response.choices[0].message.content
        data = json.loads(content)

        category: str = data["category"]
        subcategory: Optional[str] = data.get("subcategory")
        # Normalise empty-string subcategory to None
        if subcategory == "":
            subcategory = None

        raw_confidence: float = float(data["confidence"])
        # Clamp confidence to [0.0, 1.0] regardless of what the model returns
        confidence = max(0.0, min(1.0, raw_confidence))

        review_required = False

        # Validate category against taxonomy
        if not self._is_valid_category(category):
            review_required = True

        # Apply minimum confidence threshold
        if confidence < self._config.min_confidence:
            review_required = True

        return CategorizationResult(
            category=category,
            subcategory=subcategory,
            confidence=confidence,
            method="ai",
            review_required=review_required,
            fallback_used=False,
        )

    def _fallback_categorize(self, file: InspectedFile) -> CategorizationResult:
        """Categorize by file extension when the AI is unavailable."""
        ext = file.path.suffix.lower()
        category = _EXT_TO_CATEGORY.get(ext)

        if category is None:
            return CategorizationResult(
                category="Uncategorized",
                subcategory=None,
                confidence=0.0,
                method="fallback",
                review_required=True,
                fallback_used=True,
            )

        return CategorizationResult(
            category=category,
            subcategory=None,
            confidence=0.0,
            method="fallback",
            review_required=False,
            fallback_used=True,
        )

    def _is_valid_category(self, category: str) -> bool:
        """Return True if *category* is in the configured taxonomy (case-sensitive)."""
        return category in self._taxonomy


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _derive_base_url(endpoint: str) -> str:
    """Derive the base URL to pass to the OpenAI SDK from the full endpoint URL.

    The design specifies ``ai_endpoint`` as the full chat completions URL
    (``https://api.openai.com/v1/chat/completions``).  The SDK ``base_url``
    parameter should be the root without the path suffix — we strip any
    trailing path components beyond ``/v1`` so the SDK can build the correct
    request URL itself.
    """
    # Normalise trailing slash
    endpoint = endpoint.rstrip("/")
    # If the URL contains "/v1" we use everything up to and including that
    v1_idx = endpoint.find("/v1")
    if v1_idx != -1:
        return endpoint[: v1_idx + 3]  # include "/v1"
    # Otherwise return as-is and let the SDK handle it
    return endpoint


def _build_prompt(file: InspectedFile, taxonomy: list[str]) -> str:
    """Compose the user-facing prompt sent to the AI model."""
    taxonomy_str = ", ".join(taxonomy)
    text_snippet = (file.extracted_text or "")[:512]

    return (
        f"Categorize the following file into one of these categories: {taxonomy_str}\n\n"
        f"Filename: {file.path.name}\n"
        f"Extension: {file.path.suffix}\n"
        f"Size: {file.size_bytes} bytes\n"
        f"MIME type: {file.mime_type}\n"
        f"Text snippet: {text_snippet!r}\n\n"
        "Respond with a JSON object with fields:\n"
        '- "category": one of the listed categories\n'
        '- "subcategory": a more specific label (or null)\n'
        '- "confidence": your confidence score between 0.0 and 1.0'
    )
