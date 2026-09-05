# Feature: local-file-organizer, Property 2: Confidence score is always in range

"""Property-based tests: confidence score is always in [0.0, 1.0].

Validates: Requirements 4.2, 4.6 (Property 2)
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

_inspected_file_st = st.builds(
    InspectedFile,
    path=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
        min_size=1,
        max_size=20,
    ).map(lambda s: Path(s + ".txt")),
    sha256=st.text(
        alphabet="0123456789abcdef",
        min_size=64,
        max_size=64,
    ),
    size_bytes=st.integers(min_value=0, max_value=10_000_000),
    mime_type=st.sampled_from(["text/plain", "application/pdf", "image/png", "application/octet-stream"]),
    extracted_text=st.one_of(st.none(), st.text(max_size=512)),
    char_count=st.one_of(st.none(), st.integers(min_value=0, max_value=4096)),
    extraction_status=_extraction_status_st,
)

# Arbitrary float confidence values including out-of-range values
_raw_confidence_st = st.floats(
    min_value=-10.0,
    max_value=10.0,
    allow_nan=False,
    allow_infinity=False,
)

_valid_category_st = st.sampled_from(DEFAULT_TAXONOMY)


def _make_config(min_confidence: float = 0.0) -> Config:
    return Config(
        source_dir=Path("."),
        min_confidence=min_confidence,
        ai_api_key="test-key",
    )


def _make_ai_response(category: str, subcategory: Optional[str], confidence: float) -> MagicMock:
    """Build a minimal mock that looks like an OpenAI chat completion response."""
    content = json.dumps({"category": category, "subcategory": subcategory, "confidence": confidence})
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# Property 2: Confidence score always in [0.0, 1.0] — AI path
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------

@given(
    file=_inspected_file_st,
    category=_valid_category_st,
    raw_confidence=_raw_confidence_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_confidence_always_in_range_ai_path(
    file: InspectedFile,
    category: str,
    raw_confidence: float,
) -> None:
    """For any AI response with an arbitrary confidence value (including out-of-range),
    the resulting CategorizationResult.confidence shall be in [0.0, 1.0].

    Property 2: Confidence score is always in range
    Validates: Requirements 4.2
    """
    store = MetadataStore()
    config = _make_config()
    categorizer = AICategorizer(config, store)

    mock_response = _make_ai_response(category, None, raw_confidence)

    with patch.object(categorizer._client.chat.completions, "create", return_value=mock_response):
        result = categorizer.categorize(file)

    assert 0.0 <= result.confidence <= 1.0, (
        f"confidence {result.confidence} is out of [0.0, 1.0] "
        f"for raw AI value {raw_confidence}"
    )


# ---------------------------------------------------------------------------
# Property 2: Confidence score always in [0.0, 1.0] — fallback path
# Validates: Requirements 4.6
# ---------------------------------------------------------------------------

@given(file=_inspected_file_st)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_confidence_always_in_range_fallback_path(file: InspectedFile) -> None:
    """When the AI raises an exception, the fallback path shall still produce
    a confidence in [0.0, 1.0].

    Property 2: Confidence score is always in range (fallback)
    Validates: Requirements 4.6
    """
    store = MetadataStore()
    config = _make_config()
    categorizer = AICategorizer(config, store)

    with patch.object(
        categorizer._client.chat.completions, "create", side_effect=Exception("AI unavailable")
    ):
        result = categorizer.categorize(file)

    assert 0.0 <= result.confidence <= 1.0, (
        f"fallback confidence {result.confidence} is out of [0.0, 1.0]"
    )
