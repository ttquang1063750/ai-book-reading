"""Tests for raw PDF extraction: font-flag decoding, hyphenation repair, image bytes."""

import pymupdf
import pytest

from app.ingestion.pdf_extract import EncryptedPdfError, extract_raw_blocks


@pytest.fixture
def tmp_pdf(tmp_path):
    """Save a freshly-built pymupdf.Document to a temp file and return its path."""

    def _save(doc: pymupdf.Document) -> str:
        path = tmp_path / "test.pdf"
        doc.save(str(path))
        return str(path)

    return _save


def test_bold_flag_decoded(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Bold sentence for testing.", fontsize=11, fontname="hebo")
    blocks, _images, _pages = extract_raw_blocks(tmp_pdf(doc))

    spans = [s for b in blocks for l in b.lines for s in l.spans]
    assert spans, "expected at least one span"
    assert all(s.bold for s in spans)
    assert not any(s.italic for s in spans)
    assert not any(s.mono for s in spans)


def test_italic_flag_decoded(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Italic sentence for testing.", fontsize=11, fontname="heit")
    blocks, _images, _pages = extract_raw_blocks(tmp_pdf(doc))

    spans = [s for b in blocks for l in b.lines for s in l.spans]
    assert spans
    assert all(s.italic for s in spans)
    assert not any(s.bold for s in spans)


def test_monospace_flag_decoded(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "print('hello')", fontsize=11, fontname="cour")
    blocks, _images, _pages = extract_raw_blocks(tmp_pdf(doc))

    spans = [s for b in blocks for l in b.lines for s in l.spans]
    assert spans
    assert all(s.mono for s in spans)


def test_plain_text_has_no_flags(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Plain unstyled sentence.", fontsize=11, fontname="helv")
    blocks, _images, _pages = extract_raw_blocks(tmp_pdf(doc))

    spans = [s for b in blocks for l in b.lines for s in l.spans]
    assert spans
    assert not any(s.bold or s.italic or s.mono for s in spans)


def test_hyphenation_repaired_across_lines(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "The old house had win-", fontsize=11)
    page.insert_text((72, 115), "dows that rattled at night.", fontsize=11)
    blocks, _images, _pages = extract_raw_blocks(tmp_pdf(doc))

    assert len(blocks) == 1
    assert "windows" in blocks[0].text_joined
    assert "win-" not in blocks[0].text_joined


def test_text_lines_preserved_keeps_line_breaks(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "line one", fontsize=11)
    page.insert_text((72, 115), "line two", fontsize=11)
    blocks, _images, _pages = extract_raw_blocks(tmp_pdf(doc))

    assert len(blocks) == 1
    assert blocks[0].text_lines_preserved == "line one\nline two"


def test_image_block_extracted_with_bytes_and_ext(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20))
    pix.set_rect(pix.irect, (10, 20, 30))
    page.insert_image(pymupdf.Rect(72, 100, 92, 120), pixmap=pix)
    _blocks, images, _pages = extract_raw_blocks(tmp_pdf(doc))

    assert len(images) == 1
    assert len(images[0].data) > 0
    assert images[0].ext
    assert images[0].page == 1


def test_page_count_matches_document(tmp_pdf):
    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {i}", fontsize=11)
    _blocks, _images, page_count = extract_raw_blocks(tmp_pdf(doc))

    assert page_count == 4


def test_encrypted_pdf_raises_clear_error(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Secret protected content.", fontsize=11)
    path = tmp_path / "encrypted.pdf"
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")

    with pytest.raises(EncryptedPdfError):
        extract_raw_blocks(str(path))


def test_empty_lines_are_skipped(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "   ", fontsize=11)  # whitespace-only
    page.insert_text((72, 115), "Real content here.", fontsize=11)
    blocks, _images, _pages = extract_raw_blocks(tmp_pdf(doc))

    all_text = " ".join(b.text_joined for b in blocks)
    assert "Real content here." in all_text


def test_epub_extraction_keeps_heading_font_size_larger_than_body(tmp_epub):
    path = tmp_epub("<h1>Chapter One</h1><p>A normal paragraph of body text follows here.</p>")
    blocks, _images, _pages = extract_raw_blocks(path)

    by_text = {b.text_joined: b.max_size for b in blocks}
    assert by_text["Chapter One"] > by_text["A normal paragraph of body text follows here."]
