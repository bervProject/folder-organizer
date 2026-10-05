# Feature: local-file-organizer, Property 16: Every processed file is assigned a non-empty category

"""Property-based tests: every processed file is assigned a non-empty category.

Validates: Requirements 4.1 (Property 16)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from folder_organizer.categorizer import AICategorizer
from folder_organizer.config import Config
from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import ExtractionStatus, InspectedFile
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

# Extensions that map to a known category (fallback path) — sampled from _EXT_TO_CATEGORY
_known_extension_st = st.sampled_from([
    ".pdf", ".doc", ".docx", ".txt", ".md",
    ".jpg", ".jpeg", ".png", ".gif",
    ".mp4", ".mov", ".avi",
    ".mp3", ".wav", ".flac",
    ".py", ".js", ".ts",
    ".zip", ".tar", ".gz",
    ".xlsx", ".xls", ".csv",
    ".pptx", ".ppt",
    ".ttf", ".otf",
    ".exe", ".dll",
    ".json", ".xml", ".yaml",
])

# Extensions NOT in the fallback map (uncategorized path)
_unknown_extension_st = st.sampled_from([
    ".xyz", ".foobar", ".unknown", ".blah", ".qwerty123",
])

def _build_inspected_file(ext: str) -> st.SearchStrategy[InspectedFile]:
    """Build an InspectedFile strategy using the given file extension."""
    return st.builds(
        InspectedFile,
        path=st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            min_size=1,
            max_size=20,
        ).map(lambda s: Path(s + ext)),
        sha256=_sha256_st,
        size_bytes=st.integers(min_value=0, max_value=10_000_000),
        mime_type=st.sampled_from([
            "text/plain", "application/pdf", "image/png",
            "application/octet-stream", "application/zip",
        ]),
        extracted_text=st.one_of(st.none(), st.text(max_size=512)),
        char_count=st.one_of(st.none(), st.integers(min_value=0, max_value=4096)),
        extraction_status=_extraction_status_st,
    )


_valid_category_st = st.sampled_from(DEFAULT_TAXONOMY)

_subcategory_st = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != ""),
)


def _make_config() -> Config:
    return Config(
        source_dir=Path("."),
        min_confidence=0.0,
        ai_api_key="test-key",
    )


def _make_ai_response(category: str, subcategory: Optional[str], confidence: float) -> MagicMock:
    """Build a minimal mock that looks like an OpenAI chat completion response."""
    content = json.dumps({
        "category": category,
        "subcategory": subcategory,
        "confidence": confidence,
    })
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_non_empty_category(result, path: str = "") -> None:
    """Assert that result.category is a non-empty string and subcategory is
    a non-empty string or None."""
    assert isinstance(result.category, str), (
        f"{path}category must be a string, got {type(result.category)!r}"
    )
    assert result.category != "", (
        f"{path}category must be non-empty, got empty string"
    )
    assert result.subcategory is None or (
        isinstance(result.subcategory, str) and result.subcategory != ""
    ), (
        f"{path}subcategory must be a non-empty string or None, "
        f"got {result.subcategory!r}"
    )


# ---------------------------------------------------------------------------
# Property 16: Every processed file is assigned a non-empty category — AI path
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

@given(
    file=_build_inspected_file(".txt"),
    category=_valid_category_st,
    subcategory=_subcategory_st,
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_non_empty_category_ai_path(
    file: InspectedFile,
    category: str,
    subcategory: Optional[str],
    confidence: float,
) -> None:
    """When the AI returns a valid response, the category must be a non-empty string
    and subcategory must be a non-empty string or None.

    Property 16: Every processed file is assigned a non-empty category (AI path)
    Validates: Requirements 4.1
    """
    store = MetadataStore()
    config = _make_config()
    categorizer = AICategorizer(config, store)

    mock_response = _make_ai_response(category, subcategory, confidence)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    _assert_non_empty_category(result, "[AI path] ")


# ---------------------------------------------------------------------------
# Property 16: Every processed file is assigned a non-empty category — fallback path
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

@given(
    ext=_known_extension_st,
    sha256=_sha256_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_non_empty_category_fallback_path(ext: str, sha256: str) -> None:
    """When the AI is unavailable and the extension is recognised, the fallback
    path shall assign a non-empty category.

    Property 16: Every processed file is assigned a non-empty category (fallback path)
    Validates: Requirements 4.1
    """
    store = MetadataStore()
    config = _make_config()
    categorizer = AICategorizer(config, store)

    file = InspectedFile(
        path=Path("testfile" + ext),
        sha256=sha256,
        size_bytes=1024,
        mime_type="application/octet-stream",
        extracted_text=None,
        char_count=None,
        extraction_status=ExtractionStatus.UNAVAILABLE,
    )

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        side_effect=Exception("AI unavailable"),
    ):
        result = categorizer.categorize(file)

    _assert_non_empty_category(result, "[fallback path] ")
    # Confirm it actually went through the fallback
    assert result.fallback_used is True, (
        "[fallback path] fallback_used should be True when AI is unavailable"
    )


# ---------------------------------------------------------------------------
# Property 16: Every processed file is assigned a non-empty category — uncategorized path
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

@given(
    ext=_unknown_extension_st,
    sha256=_sha256_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_non_empty_category_uncategorized_path(ext: str, sha256: str) -> None:
    """When the AI is unavailable AND the extension is unrecognised, the file
    shall still be assigned the non-empty category 'Uncategorized'.

    Property 16: Every processed file is assigned a non-empty category (uncategorized path)
    Validates: Requirements 4.1
    """
    store = MetadataStore()
    config = _make_config()
    categorizer = AICategorizer(config, store)

    file = InspectedFile(
        path=Path("testfile" + ext),
        sha256=sha256,
        size_bytes=512,
        mime_type="application/octet-stream",
        extracted_text=None,
        char_count=None,
        extraction_status=ExtractionStatus.UNAVAILABLE,
    )

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        side_effect=Exception("AI unavailable"),
    ):
        result = categorizer.categorize(file)

    _assert_non_empty_category(result, "[uncategorized path] ")
    # Confirm it is the Uncategorized sentinel value
    assert result.category == "Uncategorized", (
        f"[uncategorized path] expected 'Uncategorized', got {result.category!r}"
    )
    assert result.fallback_used is True, (
        "[uncategorized path] fallback_used should be True"
    )
    assert result.review_required is True, (
        "[uncategorized path] review_required should be True for unrecognised extensions"
    )
