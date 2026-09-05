"""Unit tests for taxonomy.py — DEFAULT_TAXONOMY and build_taxonomy."""

import pytest

from folder_organizer.taxonomy import DEFAULT_TAXONOMY, build_taxonomy

EXPECTED_CATEGORIES = {
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
}


class TestDefaultTaxonomy:
    def test_has_13_categories(self):
        assert len(DEFAULT_TAXONOMY) == 13

    def test_contains_all_expected_categories(self):
        assert set(DEFAULT_TAXONOMY) == EXPECTED_CATEGORIES

    def test_is_a_list(self):
        assert isinstance(DEFAULT_TAXONOMY, list)

    def test_all_entries_are_non_empty_strings(self):
        for entry in DEFAULT_TAXONOMY:
            assert isinstance(entry, str) and entry


class TestBuildTaxonomy:
    def test_no_additions_returns_all_defaults(self):
        result = build_taxonomy([])
        assert result == frozenset(DEFAULT_TAXONOMY)

    def test_returns_frozenset(self):
        result = build_taxonomy([])
        assert isinstance(result, frozenset)

    def test_user_additions_are_included(self):
        result = build_taxonomy(["Medical", "Legal"])
        assert "Medical" in result
        assert "Legal" in result

    def test_default_categories_preserved_with_additions(self):
        result = build_taxonomy(["Medical"])
        assert EXPECTED_CATEGORIES.issubset(result)

    def test_total_count_with_novel_additions(self):
        result = build_taxonomy(["Medical", "Legal"])
        assert len(result) == 15

    def test_duplicate_additions_are_deduped(self):
        result = build_taxonomy(["Medical", "Medical"])
        assert len(result) == 14

    def test_addition_matching_existing_category_deduped(self):
        # "Documents" is already in DEFAULT_TAXONOMY — no extra entry
        result = build_taxonomy(["Documents"])
        assert len(result) == 13

    def test_taxonomy_is_case_sensitive(self):
        # lowercase "documents" is a different entry from "Documents"
        result = build_taxonomy(["documents"])
        assert "documents" in result
        assert "Documents" in result
        assert len(result) == 14

    def test_empty_string_addition_is_included(self):
        # build_taxonomy does not filter; callers validate inputs
        result = build_taxonomy([""])
        assert "" in result

    def test_large_number_of_additions(self):
        extras = [f"Category{i}" for i in range(100)]
        result = build_taxonomy(extras)
        assert len(result) == 13 + 100
        for extra in extras:
            assert extra in result
