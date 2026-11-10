# Feature: local-file-organizer, Property 9: Dry run produces zero disk mutations

"""Property-based tests: running the pipeline with ``dry_run=True`` must leave
the file system completely unchanged — no files moved, no folders created, no
``organizer-metadata.json`` written.

Validates: Requirements 8.1, 8.3 (Property 9)
"""

from __future__ import annotations

import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from rich.console import Console

from folder_organizer.config import Config
from folder_organizer.models import CategorizationResult
from folder_organizer.organizer import Organizer
from folder_organizer.taxonomy import DEFAULT_TAXONOMY


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid ASCII filenames: letters/digits + a simple extension.
_safe_char_st = st.characters(whitelist_categories=("Lu", "Ll", "Nd"))

_filename_st = st.text(alphabet=_safe_char_st, min_size=1, max_size=20).map(
    lambda s: s + ".txt"
)

# Non-empty byte content (at most 512 bytes keeps tests fast)
_content_st = st.binary(min_size=1, max_size=512)

# A list of (filename, content) pairs — 1 to 8 files per run
_files_st = st.lists(
    st.tuples(_filename_st, _content_st),
    min_size=1,
    max_size=8,
)

# A valid taxonomy category for the mocked AI to return
_category_st = st.sampled_from(DEFAULT_TAXONOMY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snapshot(directory: Path) -> dict[str, bytes]:
    """Return a dict mapping relative-path-string → file bytes for every file
    under *directory* (recursively), excluding ``organizer.log`` (which the
    logger creates for all runs including dry runs — it is not a "mutation" per
    the property definition that calls out no files moved, no folders created,
    and no ``organizer-metadata.json`` written).
    """
    result: dict[str, bytes] = {}
    for path in directory.rglob("*"):
        if path.is_file() and path.name != "organizer.log":
            rel = str(path.relative_to(directory))
            result[rel] = path.read_bytes()
    return result


def _silent_console() -> Console:
    return Console(file=StringIO(), stderr=False)


def _make_ai_response(category: str) -> MagicMock:
    """Build a mock OpenAI response returning *category* with confidence 0.9."""
    payload = json.dumps({"category": category, "subcategory": None, "confidence": 0.9})
    mock_message = MagicMock()
    mock_message.content = payload
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


# ---------------------------------------------------------------------------
# Property 9 — Dry run produces zero disk mutations
# Validates: Requirements 8.1, 8.3
# ---------------------------------------------------------------------------

@given(
    files=_files_st,
    category=_category_st,
)
@settings(
    max_examples=100,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
    deadline=None,
)
def test_dry_run_produces_zero_disk_mutations(
    files: list[tuple[str, bytes]],
    category: str,
) -> None:
    """Running the full pipeline with dry_run=True must leave the directory
    tree byte-for-byte identical to the state before the run.

    Property 9: Dry run produces zero disk mutations
    Validates: Requirements 8.1, 8.3
    """
    with tempfile.TemporaryDirectory() as _tmp:
        run_dir = Path(_tmp)
        source_dir = run_dir / "source"
        target_dir = run_dir / "target"
        source_dir.mkdir(parents=True)
        target_dir.mkdir(parents=True)

        # --- Write generated files into source_dir --------------------------
        # Deduplicate filenames (Hypothesis may generate the same name twice).
        seen: set[str] = set()
        for filename, content in files:
            if filename in seen:
                continue
            seen.add(filename)
            (source_dir / filename).write_bytes(content)

        # --- Snapshot: state BEFORE the run ---------------------------------
        # We snapshot run_dir so that any writes inside either source_dir or
        # target_dir (including organizer-metadata.json / organizer.log) are
        # captured.
        before = _snapshot(run_dir)

        # --- Build config (dry_run=True) ------------------------------------
        config = Config(
            source_dir=source_dir,
            target_dir=target_dir,
            dry_run=True,
            ai_api_key="test-key",
            taxonomy=list(DEFAULT_TAXONOMY),
        )

        organizer = Organizer(config)
        # Silence Rich console output during property testing.
        organizer._console = _silent_console()

        # --- Mock the AI and signal handler; run the pipeline ---------------
        ai_response = _make_ai_response(category)

        with (
            patch(
                "folder_organizer.categorizer.AICategorizer._ai_categorize",
                return_value=CategorizationResult(
                    category=category,
                    subcategory=None,
                    confidence=0.9,
                    method="ai",
                    review_required=False,
                    fallback_used=False,
                ),
            ),
            patch("signal.signal"),  # prevent SIGINT handler side-effects
        ):
            organizer.run()

        # --- Snapshot: state AFTER the run ----------------------------------
        after = _snapshot(run_dir)

        # --- Assertions -----------------------------------------------------

        # 1. No files were added, removed, or changed.
        assert before == after, (
            f"File system was mutated during dry run.\n"
            f"  Before keys: {sorted(before.keys())}\n"
            f"  After keys:  {sorted(after.keys())}\n"
            f"  Added:   {sorted(set(after) - set(before))}\n"
            f"  Removed: {sorted(set(before) - set(after))}\n"
            f"  Changed: {sorted(k for k in before if k in after and before[k] != after[k])}\n"
        )

        # 2. organizer-metadata.json must NOT have been written (Requirement 8.3).
        metadata_path = target_dir / "organizer-metadata.json"
        assert not metadata_path.exists(), (
            "organizer-metadata.json was written during dry run (violates Requirement 8.3)"
        )

        # 3. No category folders were created inside target_dir (Requirement 8.1).
        # The logger creates organizer.log as a file (not a folder), so we only
        # check that no *directories* were created.
        for item in target_dir.iterdir():
            assert not item.is_dir(), (
                f"Unexpected directory '{item.name}' was created inside target_dir "
                f"during dry run (violates Requirement 8.1 — no folders should be "
                f"created in dry run mode)."
            )

        # 4. Original source files must still exist and be unchanged.
        for filename in seen:
            src = source_dir / filename
            assert src.exists(), (
                f"Source file '{filename}' was removed during dry run (Requirement 8.1)"
            )
            # Build the relative-path key the same way _snapshot does
            # (using os.path separators, as str(path.relative_to(...)) does on
            # the current platform).
            rel_key = str(src.relative_to(run_dir))
            assert rel_key in before, (
                f"Source file '{filename}' was not found in pre-run snapshot "
                f"(key={rel_key!r}, snapshot keys={sorted(before.keys())})"
            )
            assert before[rel_key] == src.read_bytes(), (
                f"Source file '{filename}' content was modified during dry run"
            )
