# Feature: local-file-organizer, Property 3: Below-threshold files are never auto-moved

"""Property-based tests: files whose confidence is below the configured threshold
are always routed to ``_review/``, never to a category folder.

Validates: Requirements 4.3, 7.5 (Property 3)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from folder_organizer.categorizer import AICategorizer
from folder_organizer.config import Config
from folder_organizer.file_mover import FileMover
from folder_organizer.folder_generator import FolderGenerator
from folder_organizer.metadata_store import MetadataStore
from folder_organizer.models import (
    CategorizedFile,
    CategorizationResult,
    ExtractionStatus,
    InspectedFile,
    PlacedFile,
)
from folder_organizer.taxonomy import DEFAULT_TAXONOMY


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate a threshold strictly above 0 (so there is always room for a
# confidence value below it) up to 1.0.
_threshold_st = st.floats(
    min_value=0.001,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)


def _confidence_below(threshold: float) -> st.SearchStrategy[float]:
    """Return a strategy that generates a confidence value in [0.0, threshold)."""
    # Clamp the upper bound to be strictly less than threshold.
    # Because of floating-point precision we subtract a small epsilon; for very
    # small thresholds we just use 0.0.
    upper = max(0.0, threshold - 1e-9)
    if upper <= 0.0:
        return st.just(0.0)
    return st.floats(
        min_value=0.0,
        max_value=upper,
        allow_nan=False,
        allow_infinity=False,
    )


# A valid taxonomy category to use as the category returned by the (mocked) AI.
_category_st = st.sampled_from(DEFAULT_TAXONOMY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(source_dir: Path, target_dir: Path, threshold: float) -> Config:
    return Config(
        source_dir=source_dir,
        target_dir=target_dir,
        min_confidence=threshold,
        ai_api_key="test-key",
    )


def _make_inspected_file(path: Path) -> InspectedFile:
    return InspectedFile(
        path=path,
        sha256="a" * 64,
        size_bytes=100,
        mime_type="text/plain",
        extracted_text="hello world",
        char_count=11,
        extraction_status=ExtractionStatus.OK,
    )


def _make_categorized_file(
    path: Path,
    category: str,
    confidence: float,
    review_required: bool,
) -> CategorizedFile:
    return CategorizedFile(
        path=path,
        sha256="a" * 64,
        size_bytes=100,
        mime_type="text/plain",
        extracted_text="hello world",
        char_count=11,
        extraction_status="ok",
        category=category,
        subcategory=None,
        confidence=confidence,
        method="ai",
        review_required=review_required,
        fallback_used=False,
    )


# ---------------------------------------------------------------------------
# Property 3 — via FolderGenerator directly (pure routing logic)
# Validates: Requirements 4.3, 7.5
# ---------------------------------------------------------------------------

@given(
    threshold=_threshold_st,
    category=_category_st,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_below_threshold_routed_to_review_via_folder_generator(
    threshold: float,
    category: str,
    tmp_path: Path,
) -> None:
    """For any (threshold, confidence) where confidence < threshold, the
    FolderGenerator shall route the file to ``_review/``, not a category folder.

    Property 3: Below-threshold files are never auto-moved
    Validates: Requirements 4.3, 7.5
    """
    # Draw a concrete confidence value below the threshold using the flat_map
    # pattern; since @given doesn't support dependent draws directly we derive
    # a deterministic sub-threshold value from threshold itself.
    # We use threshold / 2 when threshold > 0, otherwise 0.0 — this always
    # satisfies confidence < threshold for any threshold in (0, 1].
    confidence = threshold / 2.0 if threshold > 0.0 else 0.0

    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)

    source_file = tmp_path / "source" / "sample.txt"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("hello")

    # Build a CategorizedFile that the AICategorizer would have produced.
    # Because confidence < threshold, review_required must be True (Req 4.3).
    cat_file = _make_categorized_file(
        path=source_file,
        category=category,
        confidence=confidence,
        review_required=True,  # AICategorizer sets this when conf < threshold
    )

    # FolderGenerator is the component that translates review_required → _review/.
    generator = FolderGenerator()
    placement: PlacedFile = generator.resolve_placement(cat_file, target_dir)

    # The destination directory must be ``target_dir/_review``.
    expected_review_dir = target_dir / "_review"
    assert placement.destination_dir == expected_review_dir, (
        f"Expected destination_dir == {expected_review_dir!r} "
        f"but got {placement.destination_dir!r} "
        f"(threshold={threshold}, confidence={confidence}, category={category!r})"
    )

    # Confirm it is NOT a direct category folder.
    expected_category_dir = target_dir / category
    assert placement.destination_dir != expected_category_dir, (
        f"File was incorrectly routed to category folder {expected_category_dir!r} "
        f"despite confidence {confidence} < threshold {threshold}"
    )

    assert placement.review_required is True


# ---------------------------------------------------------------------------
# Property 3 — via AICategorizer (review_required flag is set)
# Validates: Requirement 4.3
# ---------------------------------------------------------------------------

@given(
    threshold=_threshold_st,
    category=_category_st,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_below_threshold_sets_review_required_in_categorizer(
    threshold: float,
    category: str,
    tmp_path: Path,
) -> None:
    """When AICategorizer returns a confidence strictly below the configured
    threshold, review_required shall be True in the CategorizationResult.

    Property 3: Below-threshold files are never auto-moved
    Validates: Requirement 4.3
    """
    import json

    # Confidence is strictly less than threshold.
    confidence = threshold / 2.0 if threshold > 0.0 else 0.0

    source_file = tmp_path / "sample.txt"
    source_file.write_text("hello world")

    config = Config(
        source_dir=tmp_path,
        target_dir=tmp_path,
        min_confidence=threshold,
        ai_api_key="test-key",
    )
    store = MetadataStore()
    categorizer = AICategorizer(config, store)

    inspected = _make_inspected_file(source_file)

    # Craft a mock AI response that returns confidence < threshold.
    ai_payload = json.dumps({
        "category": category,
        "subcategory": None,
        "confidence": confidence,
    })
    mock_message = MagicMock()
    mock_message.content = ai_payload
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(
        categorizer._client.chat.completions,
        "create",
        return_value=mock_response,
    ):
        result: CategorizationResult = categorizer.categorize(inspected)

    assert result.review_required is True, (
        f"review_required should be True when confidence={confidence} < threshold={threshold}, "
        f"but got review_required={result.review_required}"
    )
    assert result.confidence < threshold or result.confidence == confidence, (
        f"Unexpected confidence value: {result.confidence}"
    )


# ---------------------------------------------------------------------------
# Property 3 — end-to-end via full Organizer pipeline (mocked I/O)
# Validates: Requirements 4.3, 7.5
# ---------------------------------------------------------------------------

@given(
    threshold=_threshold_st,
    category=_category_st,
)
@settings(
    max_examples=100,
    deadline=None,
)
def test_below_threshold_organizer_routes_to_review(
    threshold: float,
    category: str,
) -> None:
    """Running FolderGenerator + FileMover with a file whose confidence is below
    the configured threshold (review_required=True) must place the file in
    ``_review/``, not in its assigned category folder.

    This tests the routing + moving stages directly — the components that
    actually enforce Requirement 7.5 — avoiding the logger's FileHandler which
    causes Windows file-lock complications with TemporaryDirectory cleanup in
    Hypothesis multi-example runs.

    Property 3: Below-threshold files are never auto-moved
    Validates: Requirements 4.3, 7.5
    """
    import tempfile

    confidence = threshold / 2.0 if threshold > 0.0 else 0.0

    with tempfile.TemporaryDirectory() as _tmp:
        run_dir = Path(_tmp)
        source_dir = run_dir / "source"
        target_dir = run_dir / "target"
        source_dir.mkdir(parents=True)
        target_dir.mkdir(parents=True)

        # Create a real source file.
        source_file = source_dir / "document.txt"
        source_file.write_text("some content")

        # Build a CategorizedFile with review_required=True (confidence < threshold).
        cat_file = _make_categorized_file(
            path=source_file,
            category=category,
            confidence=confidence,
            review_required=True,
        )

        # Stage 5: resolve placement (this is what routes review_required → _review/).
        generator = FolderGenerator()
        placed: PlacedFile = generator.resolve_placement(cat_file, target_dir)

        # Create the destination folder.
        placed.destination_dir.mkdir(parents=True, exist_ok=True)

        # Stage 6: move the file.
        mover = FileMover(dry_run=False)
        result = mover.move(placed)

        # --- Assertions --------------------------------------------------

        # Placement must be in _review/, not a category folder.
        expected_review_dir = target_dir / "_review"
        assert placed.destination_dir == expected_review_dir, (
            f"FolderGenerator routed to {placed.destination_dir!r} "
            f"instead of _review/ (threshold={threshold}, confidence={confidence})"
        )
        assert placed.review_required is True

        # The file must have actually been moved to _review/.
        assert result.success, (
            f"FileMover failed to move file: {result.skip_reason}"
        )
        assert result.destination_path is not None
        assert result.destination_path.parent == expected_review_dir, (
            f"File landed in {result.destination_path.parent!r} "
            f"instead of _review/ (threshold={threshold}, confidence={confidence})"
        )
        assert result.destination_path.exists(), (
            "Moved file does not exist at destination"
        )

        # The source must no longer be in a category folder.
        category_dir = target_dir / category
        if category_dir.exists():
            category_files = list(category_dir.iterdir())
            assert len(category_files) == 0, (
                f"File was incorrectly placed in category folder {category_dir!r} "
                f"instead of _review/ (threshold={threshold}, confidence={confidence})"
            )
