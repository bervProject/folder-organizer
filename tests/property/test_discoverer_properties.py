# Feature: local-file-organizer, Property 12: Recursive enumeration discovers all files

"""Property-based tests for FileDiscoverer recursive enumeration.

Validates: Requirements 2.1
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from folder_organizer.discoverer import FileDiscoverer


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A path component is a non-empty string with only safe filename characters
# (letters, digits, underscores, hyphens).  This avoids OS-level restrictions
# on filenames (e.g. NUL bytes, trailing dots on Windows) while still covering
# a realistic variety of names.
_safe_component = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=12,
)

# A relative file path has between 1 and 4 depth components plus a filename.
# Example: "docs/reports/2024/summary.txt"
def _rel_path_strategy() -> st.SearchStrategy[str]:
    return st.lists(_safe_component, min_size=1, max_size=4).map(
        lambda parts: "/".join(parts)
    )


# A directory tree is represented as a list of relative path strings.
# We deduplicate and then remove any path that is a prefix of another path
# (e.g. drop "a" when "a/b" is also present, because "a" cannot be both a
# file and a directory at the same time).
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})


def _has_reserved_component(rel: str) -> bool:
    """Return True if any path component (case-insensitive) is a Windows reserved name."""
    return any(part.upper() in _WINDOWS_RESERVED for part in rel.replace("\\", "/").split("/"))


def _sanitize_tree(paths: list[str]) -> list[str]:
    """Deduplicate, remove file/directory conflicts, and drop Windows reserved names."""
    seen = list(dict.fromkeys(paths))  # deduplicate, preserve order
    # Drop paths that contain Windows reserved device names (e.g. NUL, CON).
    seen = [p for p in seen if not _has_reserved_component(p)]
    result: list[str] = []
    for candidate in seen:
        # Keep only paths that are not an ancestor of any other path in the set.
        candidate_prefix = candidate + "/"
        if any(other.startswith(candidate_prefix) for other in seen if other != candidate):
            continue  # candidate would need to be a directory — skip it as a file
        result.append(candidate)
    return result


_tree_strategy = st.lists(
    _rel_path_strategy(),
    min_size=0,
    max_size=20,
).map(_sanitize_tree)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_tree(root: Path, rel_paths: list[str]) -> set[Path]:
    """Create files at every relative path under *root*.

    Returns the set of absolute :class:`~pathlib.Path` objects for each
    created file.
    """
    created: set[Path] = set()
    for rel in rel_paths:
        full = root / Path(rel)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(b"x")
        created.add(full.resolve())
    return created


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@given(rel_paths=_tree_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_discovers_all_files(rel_paths: list[str]) -> None:
    """FileDiscoverer returns exactly the set of regular files in the tree.

    For any directory tree of arbitrary depth and structure, the discoverer
    shall return a list that includes every regular file contained within the
    tree (no exclusions, no symlinks).

    Property 12: Recursive enumeration discovers all files
    Validates: Requirements 2.1
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        root = Path(tmp_dir)
        expected = _create_tree(root, rel_paths)

        result = FileDiscoverer().discover(root, exclude_patterns=[])

        discovered = {p.resolve() for p in result.discovered}

        assert discovered == expected, (
            f"Discoverer missed or added files.\n"
            f"  Expected : {sorted(str(p) for p in expected)}\n"
            f"  Discovered: {sorted(str(p) for p in discovered)}\n"
            f"  Missing  : {sorted(str(p) for p in expected - discovered)}\n"
            f"  Extra    : {sorted(str(p) for p in discovered - expected)}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Feature: local-file-organizer, Property 13: Exclusion filter removes all matching files

"""Property-based tests for FileDiscoverer exclusion filter.

Validates: Requirements 2.2
"""


# ---------------------------------------------------------------------------
# Strategies for exclusion tests
# ---------------------------------------------------------------------------

# A glob pattern that is likely to match some files — built from a safe
# component optionally surrounded by wildcards.
_glob_prefix = st.sampled_from(["", "*", "*/"])
_glob_suffix = st.sampled_from(["", "*", ".*", ".txt", ".py", ".log"])


def _pattern_strategy() -> st.SearchStrategy[str]:
    """Generate a glob pattern: optionally wildcarded prefix + component + suffix."""
    return st.builds(
        lambda prefix, component, suffix: prefix + component + suffix,
        _glob_prefix,
        _safe_component,
        _glob_suffix,
    )


_patterns_strategy = st.lists(_pattern_strategy(), min_size=0, max_size=5)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@given(rel_paths=_tree_strategy, patterns=_patterns_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_exclusion_filter_removes_all_matching_files(
    rel_paths: list[str],
    patterns: list[str],
) -> None:
    """No file whose relative path matches an exclusion pattern appears in discovered.

    For any set of files and any set of glob patterns, the FileDiscoverer
    shall return a list containing no file whose relative POSIX path or
    filename matches any of the provided patterns.

    Property 13: Exclusion filter removes all matching files
    Validates: Requirements 2.2
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        root = Path(tmp_dir)
        _create_tree(root, rel_paths)

        result = FileDiscoverer().discover(root, exclude_patterns=patterns)

        for discovered_path in result.discovered:
            rel_posix = str(discovered_path.relative_to(root)).replace(os.sep, "/")
            filename = discovered_path.name

            for pattern in patterns:
                assert not fnmatch.fnmatch(rel_posix, pattern) and not fnmatch.fnmatch(filename, pattern), (
                    f"File '{rel_posix}' matched exclusion pattern '{pattern}' "
                    f"but was still returned in discovered list."
                )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 14: Discovery count report is accurate
# Feature: local-file-organizer, Property 14: Discovery count report is accurate
# Validates: Requirements 2.4
# ---------------------------------------------------------------------------

@given(
    rel_paths=_tree_strategy,
    patterns=st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll", "Lu", "Nd"),
                whitelist_characters="_-.*?",
            ),
            min_size=1,
            max_size=15,
        ),
        min_size=0,
        max_size=3,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_discovery_count_report_is_accurate(rel_paths: list[str], patterns: list[str]) -> None:
    """Reported counts exactly partition all regular files in the tree.

    For any source directory, the counts reported by the FileDiscoverer
    (discovered, excluded, skipped_symlinks) shall equal the true count of
    regular files in the tree, and their sum shall account for every path
    encountered during enumeration.

    Because we create no symlinks in this property, skipped_symlinks should
    always be zero, so the simplified form also holds:
        len(result.discovered) + result.excluded_count == total_files

    Property 14: Discovery count report is accurate
    Validates: Requirements 2.4
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        root = Path(tmp_dir)
        _create_tree(root, rel_paths)

        result = FileDiscoverer().discover(root, exclude_patterns=patterns)

        # Ground-truth: count every regular file under the root.
        total_files = sum(1 for p in root.rglob("*") if p.is_file())

        # No symlinks were created, so skipped_symlinks must be 0.
        assert result.skipped_symlinks == 0, (
            f"Expected no skipped symlinks (none were created), "
            f"got {result.skipped_symlinks}"
        )

        # Full accounting: every file is either discovered, excluded, or
        # skipped as a symlink.
        assert len(result.discovered) + result.excluded_count + result.skipped_symlinks == total_files, (
            f"Counts do not sum to total.\n"
            f"  total_files       : {total_files}\n"
            f"  discovered        : {len(result.discovered)}\n"
            f"  excluded_count    : {result.excluded_count}\n"
            f"  skipped_symlinks  : {result.skipped_symlinks}\n"
            f"  sum               : {len(result.discovered) + result.excluded_count + result.skipped_symlinks}"
        )

        # Simplified form (no symlinks in this property).
        assert len(result.discovered) + result.excluded_count == total_files, (
            f"Simplified count check failed.\n"
            f"  total_files    : {total_files}\n"
            f"  discovered     : {len(result.discovered)}\n"
            f"  excluded_count : {result.excluded_count}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
