"""Unit tests for FileInspector.

Tests cover: SHA-256, text extraction, truncation, PDF / DOCX / XLSX / PPTX
extraction (mocked), binary UNAVAILABLE, read-error FAILED, and MIME fallback
when python-magic is unavailable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from folder_organizer.inspector import FileInspector
from folder_organizer.models import ExtractionStatus


# ---------------------------------------------------------------------------
# 1. SHA-256 always computed (even for binary / UNAVAILABLE files)
# ---------------------------------------------------------------------------

def test_sha256_always_computed(tmp_path: Path) -> None:
    """SHA-256 matches hashlib.sha256 even for binary files that get UNAVAILABLE."""
    content = b"\x00\x01\x02\x03\x89PNG"
    path = tmp_path / "data.bin"
    path.write_bytes(content)

    result = FileInspector().inspect(path)

    assert result.sha256 == hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# 2. Text extraction — content shorter than 4096 chars
# ---------------------------------------------------------------------------

def test_text_extraction(tmp_path: Path) -> None:
    """Short UTF-8 text file: status OK, extracted_text matches, char_count correct."""
    content = "Hello, World! This is a short text file."
    path = tmp_path / "readme.txt"
    path.write_text(content, encoding="utf-8")

    result = FileInspector().inspect(path)

    assert result.extraction_status == ExtractionStatus.OK
    assert result.extracted_text == content
    assert result.char_count == len(content)


# ---------------------------------------------------------------------------
# 3. Text extraction — content longer than 4096 chars (should be truncated)
# ---------------------------------------------------------------------------

def test_text_extraction_truncated(tmp_path: Path) -> None:
    """Text file with 5000 chars: extracted_text truncated to 4096, char_count == 4096."""
    content = "A" * 5000
    path = tmp_path / "long.txt"
    path.write_text(content, encoding="utf-8")

    result = FileInspector().inspect(path)

    assert result.extraction_status == ExtractionStatus.OK
    assert result.char_count == 4096
    assert len(result.extracted_text) == 4096


# ---------------------------------------------------------------------------
# 4. PDF extraction — only first 10 pages read
# ---------------------------------------------------------------------------

def test_pdf_extraction(tmp_path: Path) -> None:
    """PDF: only the first 10 of 15 pages are read; text is joined, status OK."""
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4 fake")  # so the file exists for stat()

    # Build 15 mock page objects
    pages = []
    for i in range(15):
        page = MagicMock()
        page.extract_text.return_value = "page text "
        pages.append(page)

    mock_reader_instance = MagicMock()
    mock_reader_instance.pages = pages

    with patch("folder_organizer.inspector.pypdf.PdfReader", return_value=mock_reader_instance):
        result = FileInspector().inspect(path)

    # Only 10 pages should have been read
    for i in range(10):
        pages[i].extract_text.assert_called_once()
    for i in range(10, 15):
        pages[i].extract_text.assert_not_called()

    expected_text = ("page text \n" * 10).rstrip("\n")[:4096]
    assert result.extraction_status == ExtractionStatus.OK
    assert result.extracted_text == expected_text


# ---------------------------------------------------------------------------
# 5. DOCX extraction
# ---------------------------------------------------------------------------

def test_docx_extraction(tmp_path: Path) -> None:
    """DOCX: paragraphs joined with space, status OK."""
    path = tmp_path / "report.docx"
    path.write_bytes(b"PK fake docx content")

    para1 = MagicMock()
    para1.text = "First paragraph."
    para2 = MagicMock()
    para2.text = "Second paragraph."

    mock_doc = MagicMock()
    mock_doc.paragraphs = [para1, para2]

    with patch("folder_organizer.inspector.docx.Document", return_value=mock_doc):
        result = FileInspector().inspect(path)

    assert result.extraction_status == ExtractionStatus.OK
    assert result.extracted_text == "First paragraph. Second paragraph."
    assert result.char_count == len("First paragraph. Second paragraph.")


# ---------------------------------------------------------------------------
# 6. XLSX extraction
# ---------------------------------------------------------------------------

def test_xlsx_extraction(tmp_path: Path) -> None:
    """XLSX: all non-None cell values across worksheets joined, status OK."""
    path = tmp_path / "data.xlsx"
    path.write_bytes(b"PK fake xlsx content")

    # Build a mock workbook with one worksheet and two rows
    cell_a1 = MagicMock()
    cell_a1.value = "alpha"
    cell_b1 = MagicMock()
    cell_b1.value = "beta"
    cell_a2 = MagicMock()
    cell_a2.value = None  # should be skipped
    cell_b2 = MagicMock()
    cell_b2.value = 42

    mock_ws = MagicMock()
    mock_ws.iter_rows.return_value = [
        [cell_a1, cell_b1],
        [cell_a2, cell_b2],
    ]

    mock_wb = MagicMock()
    mock_wb.worksheets = [mock_ws]

    with patch("folder_organizer.inspector.openpyxl.load_workbook", return_value=mock_wb):
        result = FileInspector().inspect(path)

    assert result.extraction_status == ExtractionStatus.OK
    assert result.extracted_text == "alpha beta 42"
    assert result.char_count == len("alpha beta 42")


# ---------------------------------------------------------------------------
# 7. PPTX extraction
# ---------------------------------------------------------------------------

def test_pptx_extraction(tmp_path: Path) -> None:
    """PPTX: all slide shape text-frame runs joined, status OK."""
    path = tmp_path / "slides.pptx"
    path.write_bytes(b"PK fake pptx content")

    run1 = MagicMock()
    run1.text = "Slide one"
    run2 = MagicMock()
    run2.text = "Slide two"

    para1 = MagicMock()
    para1.runs = [run1]
    para2 = MagicMock()
    para2.runs = [run2]

    tf1 = MagicMock()
    tf1.paragraphs = [para1]
    tf2 = MagicMock()
    tf2.paragraphs = [para2]

    shape1 = MagicMock()
    shape1.has_text_frame = True
    shape1.text_frame = tf1
    shape2 = MagicMock()
    shape2.has_text_frame = True
    shape2.text_frame = tf2

    slide1 = MagicMock()
    slide1.shapes = [shape1]
    slide2 = MagicMock()
    slide2.shapes = [shape2]

    mock_prs = MagicMock()
    mock_prs.slides = [slide1, slide2]

    with patch("folder_organizer.inspector.pptx", return_value=mock_prs):
        result = FileInspector().inspect(path)

    assert result.extraction_status == ExtractionStatus.OK
    assert result.extracted_text == "Slide one Slide two"
    assert result.char_count == len("Slide one Slide two")


# ---------------------------------------------------------------------------
# 8. Binary file → UNAVAILABLE
# ---------------------------------------------------------------------------

def test_binary_file_unavailable(tmp_path: Path) -> None:
    """PNG magic bytes with .png extension → UNAVAILABLE, no extracted text."""
    path = tmp_path / "photo.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    result = FileInspector().inspect(path)

    assert result.extraction_status == ExtractionStatus.UNAVAILABLE
    assert result.extracted_text is None
    assert result.char_count is None


# ---------------------------------------------------------------------------
# 9. Read error → FAILED (no exception propagated)
# ---------------------------------------------------------------------------

def test_read_error_sets_failed(tmp_path: Path) -> None:
    """An IOError during content read should set FAILED without raising."""
    path = tmp_path / "broken.txt"
    path.write_bytes(b"irrelevant")

    stat_mock = MagicMock()
    stat_mock.st_size = 0

    # Patch Path.read_bytes to raise — this simulates a disk error during the
    # initial binary read which feeds both sha256 and extraction.
    with patch.object(Path, "read_bytes", side_effect=IOError("disk error")), \
         patch.object(Path, "stat", return_value=stat_mock):
        result = FileInspector().inspect(path)

    assert result.extraction_status == ExtractionStatus.FAILED
    assert result.extracted_text is None
    assert result.char_count is None


# ---------------------------------------------------------------------------
# 10. MIME fallback when python-magic is None (simulates ImportError)
# ---------------------------------------------------------------------------

def test_mime_fallback_when_magic_unavailable(tmp_path: Path) -> None:
    """When magic module is None, MIME type is detected via mimetypes fallback."""
    path = tmp_path / "notes.txt"
    path.write_text("some notes", encoding="utf-8")

    with patch("folder_organizer.inspector.magic", None):
        result = FileInspector().inspect(path)

    assert result.mime_type.startswith("text/"), (
        f"Expected MIME starting with 'text/', got {result.mime_type!r}"
    )
    assert result.extraction_status == ExtractionStatus.OK
