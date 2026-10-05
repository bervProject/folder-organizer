# Feature: local-file-organizer, Property 17: Structured log entries contain all required fields

"""Property-based tests: every log entry written to organizer.log contains all required fields.

Validates: Requirements 9.2, 9.5 (Property 17)
"""

from __future__ import annotations

import json
import re
import tempfile
from io import StringIO
from pathlib import Path
from typing import NamedTuple
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from rich.console import Console

from folder_organizer.logger import OrganizerLogger


# ---------------------------------------------------------------------------
# ISO 8601 pattern: YYYY-MM-DDTHH:MM:SS.mmmZ
# ---------------------------------------------------------------------------

_ISO8601_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$")
_VALID_LEVELS = {"INFO", "WARN", "WARNING", "ERROR"}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

class _LogCall(NamedTuple):
    path: str
    action: str
    level: str


_level_st = st.sampled_from(["INFO", "WARN", "WARNING", "ERROR"])

# Paths and actions must be non-empty (logger contracts require non-empty path/action)
_nonempty_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Pc")),
    min_size=1,
    max_size=40,
)

_log_call_st = st.builds(
    _LogCall,
    path=_nonempty_text_st,
    action=_nonempty_text_st,
    level=_level_st,
)

_log_calls_st = st.lists(_log_call_st, min_size=1, max_size=20)


# ---------------------------------------------------------------------------
# Helper: build a silent Rich Console so the progress bar doesn't pollute output
# ---------------------------------------------------------------------------

def _silent_console() -> Console:
    return Console(file=StringIO(), stderr=False)


# ---------------------------------------------------------------------------
# Helper: build a minimal MetadataStore mock
# ---------------------------------------------------------------------------

def _mock_metadata_store() -> MagicMock:
    store = MagicMock()
    store.flush.return_value = None
    return store


# ---------------------------------------------------------------------------
# Helper: parse organizer.log and return a list of dicts
# ---------------------------------------------------------------------------

def _parse_log(log_path: Path) -> list[dict]:
    entries = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def _run_logger(target_dir: Path, calls_fn) -> None:
    """Create, use, and fully tear down an OrganizerLogger with proper handler cleanup."""
    store = _mock_metadata_store()
    console = _silent_console()
    logger = OrganizerLogger(
        target_dir=target_dir,
        total_files=0,
        metadata_store=store,
        console=console,
    )
    try:
        logger.__enter__()
        calls_fn(logger)
    finally:
        logger.__exit__(None, None, None)
        # Explicitly remove the file handler from the named logger so that
        # Hypothesis shrinking steps don't reuse a closed handler pointing to a
        # deleted temporary directory.
        logger._file_logger.removeHandler(logger._handler)


# ---------------------------------------------------------------------------
# Property 17: Structured log entries contain all required fields — log_action path
# Validates: Requirements 9.2, 9.5
# ---------------------------------------------------------------------------

@given(calls=_log_calls_st)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_log_action_entries_contain_required_fields(
    calls: list[_LogCall],
) -> None:
    """Every entry written via log_action shall have a valid ISO 8601 timestamp,
    a level in {INFO, WARN, WARNING, ERROR}, a non-empty path, and a non-empty action.

    Property 17: Structured log entries contain all required fields
    Validates: Requirements 9.2, 9.5
    """
    with tempfile.TemporaryDirectory() as _tmp:
        target_dir = Path(_tmp)

        def _do_log(logger: OrganizerLogger) -> None:
            for call in calls:
                logger.log_action(path=call.path, action=call.action, level=call.level)

        _run_logger(target_dir, _do_log)

        log_path = target_dir / "organizer.log"
        assert log_path.exists(), "organizer.log must be created by OrganizerLogger"

        entries = _parse_log(log_path)
        assert len(entries) == len(calls), (
            f"Expected {len(calls)} log entries, got {len(entries)}"
        )
        for i, entry in enumerate(entries):
            _assert_entry_complete(entry, index=i)


# ---------------------------------------------------------------------------
# Property 17: Structured log entries contain all required fields — log_error path
# Validates: Requirements 9.2, 9.5
# ---------------------------------------------------------------------------

@given(
    paths=st.lists(_nonempty_text_st, min_size=1, max_size=20),
    reasons=st.lists(_nonempty_text_st, min_size=1, max_size=20),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_log_error_entries_contain_required_fields(
    paths: list[str],
    reasons: list[str],
) -> None:
    """Every entry written via log_error shall have a valid ISO 8601 timestamp,
    level == 'ERROR', a non-empty path, and a non-empty action.

    Property 17: Structured log entries contain all required fields (error path)
    Validates: Requirements 9.2, 9.5
    """
    # Pair up paths and reasons, taking the shorter length
    pairs = list(zip(paths, reasons))
    if not pairs:
        return

    with tempfile.TemporaryDirectory() as _tmp:
        target_dir = Path(_tmp)

        def _do_log(logger: OrganizerLogger) -> None:
            for path, reason in pairs:
                logger.log_error(path=path, reason=reason)

        _run_logger(target_dir, _do_log)

        log_path = target_dir / "organizer.log"
        assert log_path.exists(), "organizer.log must be created by OrganizerLogger"

        entries = _parse_log(log_path)
        assert len(entries) == len(pairs), (
            f"Expected {len(pairs)} log entries, got {len(entries)}"
        )
        for i, entry in enumerate(entries):
            _assert_entry_complete(entry, index=i)
            assert entry["level"] == "ERROR", (
                f"Entry {i}: log_error must write level='ERROR', got {entry['level']!r}"
            )


# ---------------------------------------------------------------------------
# Property 17: Mixed log_action and log_error calls all produce complete entries
# Validates: Requirements 9.2, 9.5
# ---------------------------------------------------------------------------

@given(
    action_calls=_log_calls_st,
    error_paths=st.lists(_nonempty_text_st, min_size=1, max_size=10),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_mixed_log_entries_all_contain_required_fields(
    action_calls: list[_LogCall],
    error_paths: list[str],
) -> None:
    """A mix of log_action and log_error calls must all produce complete JSON-Lines
    entries satisfying all structural requirements.

    Property 17: Structured log entries contain all required fields (mixed path)
    Validates: Requirements 9.2, 9.5
    """
    total = len(action_calls) + len(error_paths)

    with tempfile.TemporaryDirectory() as _tmp:
        target_dir = Path(_tmp)

        def _do_log(logger: OrganizerLogger) -> None:
            for call in action_calls:
                logger.log_action(path=call.path, action=call.action, level=call.level)
            for path in error_paths:
                logger.log_error(path=path, reason="test error reason")

        _run_logger(target_dir, _do_log)

        log_path = target_dir / "organizer.log"
        assert log_path.exists(), "organizer.log must be created by OrganizerLogger"

        entries = _parse_log(log_path)
        assert len(entries) == total, (
            f"Expected {total} entries, got {len(entries)}"
        )
        for i, entry in enumerate(entries):
            _assert_entry_complete(entry, index=i)


# ---------------------------------------------------------------------------
# Shared assertion helper
# ---------------------------------------------------------------------------

def _assert_entry_complete(entry: dict, *, index: int) -> None:
    """Assert that a single parsed log entry satisfies all structural requirements."""
    prefix = f"Entry {index}"

    # timestamp: must be present and match ISO 8601 pattern
    assert "timestamp" in entry, f"{prefix}: missing 'timestamp' field"
    ts = entry["timestamp"]
    assert isinstance(ts, str) and ts, f"{prefix}: 'timestamp' must be a non-empty string"
    assert _ISO8601_PATTERN.match(ts), (
        f"{prefix}: 'timestamp' {ts!r} does not match ISO 8601 pattern "
        r"YYYY-MM-DDTHH:MM:SS.mmmZ"
    )

    # level: must be in the allowed set
    assert "level" in entry, f"{prefix}: missing 'level' field"
    level = entry["level"]
    assert level in _VALID_LEVELS, (
        f"{prefix}: 'level' must be one of {_VALID_LEVELS}, got {level!r}"
    )

    # path: must be a non-empty string
    assert "path" in entry, f"{prefix}: missing 'path' field"
    path = entry["path"]
    assert isinstance(path, str) and path, (
        f"{prefix}: 'path' must be a non-empty string, got {path!r}"
    )

    # action: must be a non-empty string
    assert "action" in entry, f"{prefix}: missing 'action' field"
    action = entry["action"]
    assert isinstance(action, str) and action, (
        f"{prefix}: 'action' must be a non-empty string, got {action!r}"
    )
