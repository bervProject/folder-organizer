"""Unit tests for AICategorizer.

Tests cover:
- Successful AI call returns correct CategorizationResult
- Out-of-taxonomy AI response triggers review_required = True
- AI unavailable → _fallback_categorize used, fallback_used = True, confidence = 0.0
- AI unavailable + unknown extension → "Uncategorized", review_required = True
- confidence < min_confidence → review_required = True
- Duplicate sha256 skips AI call (reuses cached record)

Requirements: 4.1, 4.3, 4.5, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from folder_organizer.categorizer import AICategorizer
from folder_organizer.config import Config
from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import ExtractionStatus, InspectedFile, MetadataRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(min_confidence: float = 0.0) -> Config:
    """Return a minimal Config suitable for unit tests (no real AI calls)."""
    return Config(
        source_dir=Path("/tmp/src"),
        target_dir=Path("/tmp/target"),
        min_confidence=min_confidence,
        ai_endpoint="https://api.openai.com/v1/chat/completions",
        ai_model="gpt-4o-mini",
        ai_api_key="test-key",
        taxonomy=[],  # use DEFAULT_TAXONOMY from taxonomy.py
    )


def _make_inspected_file(
    name: str = "report.pdf",
    sha256: str = "abc123",
    mime_type: str = "application/pdf",
    extracted_text: str | None = "Invoice Q1",
    size_bytes: int = 2048,
) -> InspectedFile:
    """Return a minimal InspectedFile for testing."""
    return InspectedFile(
        path=Path(f"/tmp/src/{name}"),
        sha256=sha256,
        size_bytes=size_bytes,
        mime_type=mime_type,
        extracted_text=extracted_text,
        char_count=len(extracted_text) if extracted_text else None,
        extraction_status=ExtractionStatus.OK if extracted_text else ExtractionStatus.UNAVAILABLE,
    )


def _make_openai_response(category: str, subcategory: str | None, confidence: float) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    content = json.dumps(
        {"category": category, "subcategory": subcategory, "confidence": confidence}
    )
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# 1. Successful AI call returns correct CategorizationResult
# ---------------------------------------------------------------------------

def test_successful_ai_call_returns_correct_result() -> None:
    """AI call succeeds → result has correct category, subcategory, confidence, method."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="invoice.pdf", sha256="deadbeef01")
    mock_response = _make_openai_response("Finance", "Invoices", 0.92)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.category == "Finance"
    assert result.subcategory == "Invoices"
    assert result.confidence == pytest.approx(0.92)
    assert result.method == "ai"
    assert result.fallback_used is False
    assert result.review_required is False


def test_successful_ai_call_null_subcategory() -> None:
    """AI response with null subcategory → subcategory is None."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="photo.jpg", sha256="cafebabe01")
    mock_response = _make_openai_response("Images", None, 0.85)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.category == "Images"
    assert result.subcategory is None


def test_successful_ai_call_empty_string_subcategory_normalized_to_none() -> None:
    """AI response with empty-string subcategory is normalized to None."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="data.csv", sha256="c0ffee0001")
    mock_response = _make_openai_response("Data", "", 0.8)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.subcategory is None


# ---------------------------------------------------------------------------
# 2. Out-of-taxonomy AI response → review_required = True  (Req 4.7)
# ---------------------------------------------------------------------------

def test_out_of_taxonomy_response_sets_review_required() -> None:
    """AI returns a category not in the taxonomy → review_required True, no auto-move."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="weird.xyz", sha256="badf00d001")
    # "GalacticMiscellany" is definitely not in DEFAULT_TAXONOMY
    mock_response = _make_openai_response("GalacticMiscellany", None, 0.75)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.review_required is True
    assert result.category == "GalacticMiscellany"  # category is still stored as-is
    assert result.method == "ai"
    assert result.fallback_used is False


# ---------------------------------------------------------------------------
# 3. AI unavailable → fallback used, fallback_used=True, confidence=0.0  (Req 4.6)
# ---------------------------------------------------------------------------

def test_ai_unavailable_uses_fallback_for_known_extension() -> None:
    """When AI raises an exception, fallback by extension is used."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="photo.jpg", sha256="1a2b3c4d01")

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        side_effect=Exception("connection refused"),
    ):
        result = categorizer.categorize(file)

    assert result.fallback_used is True
    assert result.confidence == pytest.approx(0.0)
    assert result.method == "fallback"
    assert result.category == "Images"
    assert result.review_required is False


def test_ai_unavailable_uses_fallback_for_pdf_extension() -> None:
    """PDF extension → fallback category is 'Documents'."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="manual.pdf", sha256="fe01fe0201")

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        side_effect=RuntimeError("timeout"),
    ):
        result = categorizer.categorize(file)

    assert result.fallback_used is True
    assert result.confidence == pytest.approx(0.0)
    assert result.category == "Documents"


# ---------------------------------------------------------------------------
# 4. AI unavailable + unknown extension → "Uncategorized", review_required=True  (Req 4.8)
# ---------------------------------------------------------------------------

def test_ai_unavailable_unknown_extension_gives_uncategorized() -> None:
    """When AI fails and extension is unknown → Uncategorized with review_required."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    # .xyz is not in the extension map
    file = _make_inspected_file(name="mystery.xyz", sha256="dead000001")

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        side_effect=Exception("service down"),
    ):
        result = categorizer.categorize(file)

    assert result.category == "Uncategorized"
    assert result.review_required is True
    assert result.fallback_used is True
    assert result.confidence == pytest.approx(0.0)
    assert result.method == "fallback"


def test_ai_unavailable_no_extension_gives_uncategorized() -> None:
    """When AI fails and there is no extension at all → Uncategorized."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="MAKEFILE", sha256="cafe000001")
    # Override the path suffix situation by giving a file with no extension
    file.path = Path("/tmp/src/MAKEFILE")

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        side_effect=Exception("service down"),
    ):
        result = categorizer.categorize(file)

    assert result.category == "Uncategorized"
    assert result.review_required is True
    assert result.fallback_used is True


# ---------------------------------------------------------------------------
# 5. confidence < min_confidence → review_required = True  (Req 4.3)
# ---------------------------------------------------------------------------

def test_low_confidence_below_threshold_sets_review_required() -> None:
    """When AI confidence < min_confidence, review_required must be True."""
    config = _make_config(min_confidence=0.7)
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="doc.txt", sha256="1111111101")
    # Confidence 0.5 is below threshold 0.7
    mock_response = _make_openai_response("Documents", None, 0.5)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.review_required is True
    assert result.confidence == pytest.approx(0.5)
    assert result.method == "ai"


def test_confidence_at_threshold_does_not_set_review_required() -> None:
    """Confidence exactly equal to min_confidence is not flagged for review."""
    config = _make_config(min_confidence=0.7)
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="doc.txt", sha256="2222222201")
    mock_response = _make_openai_response("Documents", None, 0.7)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.review_required is False


def test_confidence_above_threshold_does_not_set_review_required() -> None:
    """Confidence above min_confidence → review_required is False."""
    config = _make_config(min_confidence=0.5)
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="image.png", sha256="3333333301")
    mock_response = _make_openai_response("Images", None, 0.9)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.review_required is False


# ---------------------------------------------------------------------------
# 6. Duplicate sha256 skips AI call — reuses existing record  (Req 4.5)
# ---------------------------------------------------------------------------

def test_duplicate_sha256_skips_ai_call() -> None:
    """Second file with same sha256 reuses cached categorization; AI is not called."""
    config = _make_config()
    store = MetadataStore()

    # Seed the store with an existing record for sha256 "dupe1234"
    existing = MetadataRecord(
        original_path="/tmp/src/original.pdf",
        destination_path="/tmp/target/Documents/original.pdf",
        sha256="dupe1234",
        size_bytes=1024,
        mime_type="application/pdf",
        text_snippet="existing snippet",
        category="Documents",
        subcategory="Reports",
        confidence_score=0.88,
        method="ai",
        review_required=False,
        fallback_used=False,
        extraction_status="ok",
        timestamp="2024-01-15T10:00:00Z",
    )
    store.upsert(existing)

    categorizer = AICategorizer(config, store)
    file = _make_inspected_file(name="duplicate.pdf", sha256="dupe1234")

    ai_mock = MagicMock()
    with patch.object(categorizer._client.chat.completions, "create", ai_mock):
        result = categorizer.categorize(file)

    # AI should never have been called
    ai_mock.assert_not_called()

    # Result should match the cached record
    assert result.category == "Documents"
    assert result.subcategory == "Reports"
    assert result.confidence == pytest.approx(0.88)
    assert result.method == "ai"
    assert result.review_required is False
    assert result.fallback_used is False


def test_duplicate_sha256_result_matches_original_exactly() -> None:
    """Reused result for duplicate file has all fields matching the cached record."""
    config = _make_config()
    store = MetadataStore()

    existing = MetadataRecord(
        original_path="/tmp/src/first.docx",
        destination_path="",
        sha256="hashXYZ99",
        size_bytes=512,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        text_snippet="meeting notes",
        category="Documents",
        subcategory=None,
        confidence_score=0.65,
        method="fallback",
        review_required=True,
        fallback_used=True,
        extraction_status="ok",
        timestamp="2024-02-01T08:30:00Z",
    )
    store.upsert(existing)

    categorizer = AICategorizer(config, store)
    file = _make_inspected_file(name="second.docx", sha256="hashXYZ99")

    with patch.object(categorizer._client.chat.completions, "create") as ai_mock:
        result = categorizer.categorize(file)

    ai_mock.assert_not_called()
    assert result.category == existing.category
    assert result.subcategory == existing.subcategory
    assert result.confidence == pytest.approx(existing.confidence_score)
    assert result.method == existing.method
    assert result.review_required == existing.review_required
    assert result.fallback_used == existing.fallback_used


# ---------------------------------------------------------------------------
# 7. Confidence clamping — model returns out-of-range values
# ---------------------------------------------------------------------------

def test_ai_confidence_clamped_above_1() -> None:
    """AI returns confidence > 1.0 → clamped to 1.0."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="video.mp4", sha256="clamp001")
    mock_response = _make_openai_response("Videos", None, 1.5)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.confidence == pytest.approx(1.0)


def test_ai_confidence_clamped_below_0() -> None:
    """AI returns negative confidence → clamped to 0.0."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="audio.mp3", sha256="clamp002")
    mock_response = _make_openai_response("Audio", None, -0.5)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert result.confidence == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 8. category is always non-empty string (Req 4.1)
# ---------------------------------------------------------------------------

def test_fallback_for_known_extension_produces_non_empty_category() -> None:
    """Fallback path with known extension → category is a non-empty string."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="script.py", sha256="nonempty01")

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        side_effect=Exception("down"),
    ):
        result = categorizer.categorize(file)

    assert isinstance(result.category, str)
    assert len(result.category) > 0
    assert result.category == "Code"


def test_fallback_for_unknown_extension_category_is_uncategorized_not_empty() -> None:
    """Fallback with unknown extension → 'Uncategorized' (not empty string)."""
    config = _make_config()
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    file = _make_inspected_file(name="data.foobar", sha256="nonempty02")

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        side_effect=Exception("down"),
    ):
        result = categorizer.categorize(file)

    assert result.category == "Uncategorized"
    assert len(result.category) > 0
