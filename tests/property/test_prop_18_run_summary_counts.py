# Feature: local-file-organizer, Property 18: Run summary counts match actual operation counts

"""Property-based tests: RunSummary counts must equal actual operation counts.

The ``OrganizerLogger`` maintains per-bucket counters (moved, skipped, review,
unplaced, errors) and exposes them through ``build_partial_summary()``.  This
property verifies that every counter method increments exactly one counter by
one, and that ``build_partial_summary`` faithfully reflects those counters.

Validates: Requirements 9.3 (Property 18)
"""

from __future__ import annotations

import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from rich.console import Console

from folder_organizer.logger import OrganizerLogger
from folder_organizer.models import RunSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent_console() -> Console:
    """Return a Rich Console that discards all output (safe for property tests)."""
    return Console(file=StringIO(), stderr=False)


def _mock_metadata_store() -> MagicMock:
    store = MagicMock()
    store.flush.return_value = None
    return store


def _make_logger(target_dir: Path, total: int) -> OrganizerLogger:
    """Instantiate OrganizerLogger without starting the Rich progress bar.

    ``signal.signal`` is patched so the SIGINT handler installation does not
    interfere with the test runner.  The file handler is created normally so
    that the logger is fully functional, but we never call ``__enter__`` /
    ``__exit__`` — the counter methods do not depend on the progress bar.
    """
    store = _mock_metadata_store()
    console = _silent_console()
    with patch("signal.signal"):
        logger = OrganizerLogger(
            target_dir=target_dir,
            total_files=max(total, 1),
            metadata_store=store,
            console=console,
        )
    return logger


def _close_logger(logger: OrganizerLogger) -> None:
    """Close and detach the file handler to release the log file on Windows."""
    for handler in logger._file_logger.handlers[:]:
        handler.close()
        logger._file_logger.removeHandler(handler)
    # Restore SIGINT to whatever it was before the logger was constructed.
    logger._restore_sigint()


# ---------------------------------------------------------------------------
# Property 18 — counter methods accumulate correctly
# Validates: Requirements 9.3
# ---------------------------------------------------------------------------

@given(
    n_moved=st.integers(min_value=0, max_value=50),
    n_skipped=st.integers(min_value=0, max_value=50),
    n_review=st.integers(min_value=0, max_value=50),
    n_unplaced=st.integers(min_value=0, max_value=50),
    n_errors=st.integers(min_value=0, max_value=50),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_run_summary_counts_match_actual_operations(
    n_moved: int,
    n_skipped: int,
    n_review: int,
    n_unplaced: int,
    n_errors: int,
) -> None:
    """RunSummary fields must equal the number of times the corresponding
    record_* method was called on OrganizerLogger.

    Key invariants:
    - total_moved    == n_moved
    - total_skipped  == n_skipped
    - total_review   == n_review
    - total_unplaced == n_unplaced
    - total_errors   == n_errors
    - total_processed == n_moved + n_skipped + n_review + n_unplaced
      (record_error does NOT advance the processed counter)
    - dry_run == False

    Property 18: Run summary counts match actual operation counts
    Validates: Requirements 9.3
    """
    expected_processed = n_moved + n_skipped + n_review + n_unplaced
    total_files = expected_processed + n_errors + 1  # +1 so total_files >= 1

    with tempfile.TemporaryDirectory() as _tmp:
        target_dir = Path(_tmp)
        logger = _make_logger(target_dir, total_files)
        try:
            for _ in range(n_moved):
                logger.record_moved()
            for _ in range(n_skipped):
                logger.record_skipped()
            for _ in range(n_review):
                logger.record_review()
            for _ in range(n_unplaced):
                logger.record_unplaced()
            for _ in range(n_errors):
                logger.record_error()

            summary: RunSummary = logger.build_partial_summary(dry_run=False)

            assert summary.total_moved == n_moved, (
                f"total_moved: expected {n_moved}, got {summary.total_moved}"
            )
            assert summary.total_skipped == n_skipped, (
                f"total_skipped: expected {n_skipped}, got {summary.total_skipped}"
            )
            assert summary.total_review == n_review, (
                f"total_review: expected {n_review}, got {summary.total_review}"
            )
            assert summary.total_unplaced == n_unplaced, (
                f"total_unplaced: expected {n_unplaced}, got {summary.total_unplaced}"
            )
            assert summary.total_errors == n_errors, (
                f"total_errors: expected {n_errors}, got {summary.total_errors}"
            )
            assert summary.total_processed == expected_processed, (
                f"total_processed: expected {expected_processed} "
                f"(moved={n_moved} + skipped={n_skipped} + review={n_review} + "
                f"unplaced={n_unplaced}), got {summary.total_processed}"
            )
            assert summary.dry_run is False, (
                f"dry_run: expected False, got {summary.dry_run!r}"
            )
        finally:
            _close_logger(logger)


# ---------------------------------------------------------------------------
# Property 18 — dry_run flag is forwarded faithfully
# Validates: Requirements 9.3
# ---------------------------------------------------------------------------

@given(
    n_moved=st.integers(min_value=0, max_value=20),
    dry_run=st.booleans(),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_run_summary_dry_run_flag_forwarded(
    n_moved: int,
    dry_run: bool,
) -> None:
    """build_partial_summary must forward the dry_run argument unchanged.

    Property 18: Run summary counts match actual operation counts
    Validates: Requirements 9.3
    """
    with tempfile.TemporaryDirectory() as _tmp:
        target_dir = Path(_tmp)
        logger = _make_logger(target_dir, n_moved + 1)
        try:
            for _ in range(n_moved):
                logger.record_moved()

            summary: RunSummary = logger.build_partial_summary(dry_run=dry_run)

            assert summary.dry_run is dry_run, (
                f"dry_run: expected {dry_run!r}, got {summary.dry_run!r}"
            )
            assert summary.total_moved == n_moved, (
                f"total_moved: expected {n_moved}, got {summary.total_moved}"
            )
        finally:
            _close_logger(logger)


# ---------------------------------------------------------------------------
# Property 18 — record_error does NOT increment total_processed
# Validates: Requirements 9.3
# ---------------------------------------------------------------------------

@given(
    n_errors=st.integers(min_value=1, max_value=50),
    n_moved=st.integers(min_value=0, max_value=20),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_record_error_does_not_advance_processed(
    n_errors: int,
    n_moved: int,
) -> None:
    """Calling record_error() must NOT increment total_processed.

    Only the successful-outcome methods (record_moved, record_skipped,
    record_review, record_unplaced) contribute to total_processed.

    Property 18: Run summary counts match actual operation counts
    Validates: Requirements 9.3
    """
    with tempfile.TemporaryDirectory() as _tmp:
        target_dir = Path(_tmp)
        logger = _make_logger(target_dir, n_moved + n_errors + 1)
        try:
            for _ in range(n_moved):
                logger.record_moved()
            for _ in range(n_errors):
                logger.record_error()

            summary: RunSummary = logger.build_partial_summary(dry_run=False)

            assert summary.total_processed == n_moved, (
                f"total_processed should equal n_moved={n_moved} "
                f"(errors must not count), got {summary.total_processed}"
            )
            assert summary.total_errors == n_errors, (
                f"total_errors: expected {n_errors}, got {summary.total_errors}"
            )
        finally:
            _close_logger(logger)
