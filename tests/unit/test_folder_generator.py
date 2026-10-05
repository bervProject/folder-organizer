"""Unit tests for FolderGenerator.

Tests cover:
- sanitize_name replaces disallowed characters with '_'
- sanitize_name keeps allowed characters unchanged
- sanitize_name is idempotent (applying twice = applying once)
- resolve_placement routes review_required files to _review/
- resolve_placement builds correct path for category-only
- resolve_placement builds correct path for category + subcategory
- create_folders creates directories that did not exist
- create_folders reuses existing directories without error
- create_folders routes to _unplaced on PermissionError

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from folder_organizer.folder_generator import FolderGenerator
from folder_organizer.models import CategorizedFile, FolderCreationError, PlacedFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_categorized_file(
    name: str = "report.pdf",
    category: str = "Documents",
    subcategory: str | None = None,
    review_required: bool = False,
) -> CategorizedFile:
    return CategorizedFile(
        path=Path(f"/src/{name}"),
        sha256="abc123",
        size_bytes=1024,
        mime_type="application/pdf",
        extracted_text=None,
        char_count=None,
        extraction_status="ok",
        category=category,
        subcategory=subcategory,
        confidence=0.9,
        method="ai",
        review_required=review_required,
        fallback_used=False,
    )


# ---------------------------------------------------------------------------
# 1. sanitize_name
# ---------------------------------------------------------------------------

class TestSanitizeName:
    def test_allowed_chars_unchanged(self) -> None:
        """Letters, digits, underscores, hyphens, dots, and spaces are kept."""
        label = "Finance_Reports-2024 v1.0"
        assert FolderGenerator.sanitize_name(label) == label

    def test_disallowed_chars_replaced_with_underscore(self) -> None:
        """Slashes, colons, asterisks, etc. are replaced with '_'."""
        result = FolderGenerator.sanitize_name("My/Dir:Name*")
        assert result == "My_Dir_Name_"

    def test_unicode_chars_replaced(self) -> None:
        """Non-ASCII characters are replaced with '_'."""
        result = FolderGenerator.sanitize_name("Ré sum é")
        assert result == "R_ sum _"

    def test_empty_string_unchanged(self) -> None:
        """Empty string input → empty string output."""
        assert FolderGenerator.sanitize_name("") == ""

    def test_already_clean_string_unchanged(self) -> None:
        """A string with only allowed chars survives unchanged."""
        label = "Images"
        assert FolderGenerator.sanitize_name(label) == label

    def test_idempotent_on_clean_string(self) -> None:
        """Applying twice on a clean string produces the same result."""
        label = "Finance"
        assert FolderGenerator.sanitize_name(FolderGenerator.sanitize_name(label)) == FolderGenerator.sanitize_name(label)

    def test_idempotent_on_dirty_string(self) -> None:
        """Applying twice on a dirty string equals applying once (Property 6)."""
        label = "A/B:C*D"
        once = FolderGenerator.sanitize_name(label)
        twice = FolderGenerator.sanitize_name(once)
        assert once == twice

    def test_tab_and_newline_replaced(self) -> None:
        """Tab and newline are replaced."""
        result = FolderGenerator.sanitize_name("line1\nline2\ttab")
        assert result == "line1_line2_tab"

    def test_question_mark_replaced(self) -> None:
        result = FolderGenerator.sanitize_name("what?")
        assert result == "what_"

    def test_pipe_replaced(self) -> None:
        result = FolderGenerator.sanitize_name("a|b")
        assert result == "a_b"


# ---------------------------------------------------------------------------
# 2. resolve_placement
# ---------------------------------------------------------------------------

class TestResolvePlacement:
    def test_review_required_routes_to_review_dir(self, tmp_path: Path) -> None:
        """Files with review_required=True land in _review/."""
        fg = FolderGenerator()
        file = _make_categorized_file(review_required=True, category="Documents")
        placed = fg.resolve_placement(file, tmp_path)
        assert placed.destination_dir == tmp_path / "_review"
        assert placed.review_required is True
        assert placed.unplaced is False

    def test_normal_file_routes_to_category_dir(self, tmp_path: Path) -> None:
        """Files without subcategory land in target/category/."""
        fg = FolderGenerator()
        file = _make_categorized_file(category="Images", subcategory=None)
        placed = fg.resolve_placement(file, tmp_path)
        assert placed.destination_dir == tmp_path / "Images"
        assert placed.unplaced is False

    def test_file_with_subcategory_routes_to_nested_dir(self, tmp_path: Path) -> None:
        """Files with subcategory land in target/category/subcategory/."""
        fg = FolderGenerator()
        file = _make_categorized_file(category="Finance", subcategory="Invoices")
        placed = fg.resolve_placement(file, tmp_path)
        assert placed.destination_dir == tmp_path / "Finance" / "Invoices"

    def test_category_label_is_sanitized(self, tmp_path: Path) -> None:
        """Category with disallowed chars is sanitized in the destination path."""
        fg = FolderGenerator()
        file = _make_categorized_file(category="My/Docs", subcategory=None)
        placed = fg.resolve_placement(file, tmp_path)
        assert placed.destination_dir == tmp_path / "My_Docs"

    def test_subcategory_label_is_sanitized(self, tmp_path: Path) -> None:
        """Subcategory with disallowed chars is sanitized."""
        fg = FolderGenerator()
        file = _make_categorized_file(category="Finance", subcategory="Q1:2024")
        placed = fg.resolve_placement(file, tmp_path)
        assert placed.destination_dir == tmp_path / "Finance" / "Q1_2024"

    def test_destination_filename_is_original_filename(self, tmp_path: Path) -> None:
        """destination_filename should be the original file's name."""
        fg = FolderGenerator()
        file = _make_categorized_file(name="my_invoice.pdf", category="Finance")
        placed = fg.resolve_placement(file, tmp_path)
        assert placed.destination_filename == "my_invoice.pdf"

    def test_source_path_preserved(self, tmp_path: Path) -> None:
        """source_path in PlacedFile equals the file's original path."""
        fg = FolderGenerator()
        file = _make_categorized_file(name="photo.jpg", category="Images")
        placed = fg.resolve_placement(file, tmp_path)
        assert placed.source_path == file.path

    def test_review_required_does_not_use_category_in_path(self, tmp_path: Path) -> None:
        """Even if a category is set, review_required files go to _review/."""
        fg = FolderGenerator()
        file = _make_categorized_file(
            category="Finance", subcategory="Invoices", review_required=True
        )
        placed = fg.resolve_placement(file, tmp_path)
        assert placed.destination_dir == tmp_path / "_review"


# ---------------------------------------------------------------------------
# 3. create_folders
# ---------------------------------------------------------------------------

class TestCreateFolders:
    def test_creates_nonexistent_directory(self, tmp_path: Path) -> None:
        """create_folders creates a directory that does not yet exist."""
        fg = FolderGenerator()
        dest = tmp_path / "Documents"
        placed = PlacedFile(
            source_path=Path("/src/file.pdf"),
            destination_dir=dest,
            destination_filename="file.pdf",
            review_required=False,
            unplaced=False,
        )
        errors = fg.create_folders([placed])
        assert dest.exists()
        assert dest.is_dir()
        assert errors == []

    def test_creates_nested_directory(self, tmp_path: Path) -> None:
        """create_folders creates nested directories with parents=True."""
        fg = FolderGenerator()
        dest = tmp_path / "Finance" / "Invoices"
        placed = PlacedFile(
            source_path=Path("/src/invoice.pdf"),
            destination_dir=dest,
            destination_filename="invoice.pdf",
            review_required=False,
            unplaced=False,
        )
        errors = fg.create_folders([placed])
        assert dest.exists()
        assert errors == []

    def test_reuses_existing_directory_without_error(self, tmp_path: Path) -> None:
        """create_folders is a no-op (and no error) when directory already exists."""
        fg = FolderGenerator()
        dest = tmp_path / "Images"
        dest.mkdir()  # pre-create

        placed = PlacedFile(
            source_path=Path("/src/photo.jpg"),
            destination_dir=dest,
            destination_filename="photo.jpg",
            review_required=False,
            unplaced=False,
        )
        errors = fg.create_folders([placed])
        assert errors == []
        assert dest.exists()

    def test_permission_error_returns_folder_creation_error(self, tmp_path: Path) -> None:
        """PermissionError when creating a folder → FolderCreationError returned."""
        fg = FolderGenerator()
        dest = tmp_path / "Finance"
        placed = PlacedFile(
            source_path=Path("/src/invoice.pdf"),
            destination_dir=dest,
            destination_filename="invoice.pdf",
            review_required=False,
            unplaced=False,
        )

        # Only raise PermissionError for the specific failing dest; allow _unplaced creation.
        original_mkdir = Path.mkdir

        def selective_mkdir(self: Path, *args, **kwargs):  # type: ignore[override]
            if self == dest:
                raise PermissionError("access denied")
            return original_mkdir(self, *args, **kwargs)

        with patch.object(Path, "mkdir", selective_mkdir):
            errors = fg.create_folders([placed])

        # Should have one error and one unplaced file
        assert len(errors) == 1
        assert isinstance(errors[0], FolderCreationError)
        assert errors[0].path == dest
        assert "access denied" in errors[0].reason

    def test_permission_error_sets_unplaced_flag(self, tmp_path: Path) -> None:
        """On PermissionError, the affected PlacedFile.unplaced is set to True."""
        fg = FolderGenerator()
        dest = tmp_path / "Finance"
        placed = PlacedFile(
            source_path=Path("/src/invoice.pdf"),
            destination_dir=dest,
            destination_filename="invoice.pdf",
            review_required=False,
            unplaced=False,
        )

        original_mkdir = Path.mkdir

        def selective_mkdir(self: Path, *args, **kwargs):  # type: ignore[override]
            if self == dest:
                raise PermissionError("nope")
            return original_mkdir(self, *args, **kwargs)

        with patch.object(Path, "mkdir", selective_mkdir):
            fg.create_folders([placed])

        assert placed.unplaced is True

    def test_empty_placements_list_returns_empty_errors(self, tmp_path: Path) -> None:
        """create_folders on empty list → no errors, no directories created."""
        fg = FolderGenerator()
        errors = fg.create_folders([])
        assert errors == []

    def test_multiple_files_same_dir_created_once(self, tmp_path: Path) -> None:
        """Multiple files sharing a destination directory: directory created once."""
        fg = FolderGenerator()
        dest = tmp_path / "Documents"
        placements = [
            PlacedFile(
                source_path=Path(f"/src/file{i}.pdf"),
                destination_dir=dest,
                destination_filename=f"file{i}.pdf",
                review_required=False,
                unplaced=False,
            )
            for i in range(3)
        ]
        errors = fg.create_folders(placements)
        assert dest.exists()
        assert errors == []

    def test_no_permission_error_no_unplaced(self, tmp_path: Path) -> None:
        """Successful folder creation leaves unplaced=False unchanged."""
        fg = FolderGenerator()
        dest = tmp_path / "Code"
        placed = PlacedFile(
            source_path=Path("/src/main.py"),
            destination_dir=dest,
            destination_filename="main.py",
            review_required=False,
            unplaced=False,
        )
        fg.create_folders([placed])
        assert placed.unplaced is False
