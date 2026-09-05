"""Default category taxonomy and taxonomy builder."""

from __future__ import annotations

DEFAULT_TAXONOMY: list[str] = [
    "Documents",
    "Images",
    "Videos",
    "Audio",
    "Code",
    "Archives",
    "Finance",
    "Data",
    "Presentations",
    "Spreadsheets",
    "Executables",
    "Fonts",
    "Uncategorized",
]


def build_taxonomy(user_additions: list[str]) -> frozenset[str]:
    """Merge the built-in taxonomy with user-provided category labels.

    Args:
        user_additions: Additional category strings supplied by the user via
            the configuration file.  May be empty.  Values are merged
            case-sensitively — "Finance" and "finance" are treated as two
            distinct entries.

    Returns:
        A frozenset containing every unique category label from both
        DEFAULT_TAXONOMY and *user_additions*.
    """
    return frozenset(DEFAULT_TAXONOMY) | frozenset(user_additions)
