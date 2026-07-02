"""Tests for the heading/code/verse/image classification heuristics in structure.py."""

import pymupdf
import pytest

from app.ingestion.structure import build_structure


@pytest.fixture
def tmp_pdf(tmp_path):
    def _save(doc: pymupdf.Document) -> str:
        path = tmp_path / "test.pdf"
        doc.save(str(path))
        return str(path)

    return _save


def test_chapter_heading_is_level_1(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Chapter One", fontsize=22, fontname="hebo")
    page.insert_text((72, 150), "A normal paragraph of body text follows the heading here.", fontsize=11)
    structure = build_structure("b1", "en", tmp_pdf(doc))

    headings = [b for b in structure.blocks if b.type == "heading"]
    assert len(headings) == 1
    assert headings[0].level == 1
    assert headings[0].text == "Chapter One"


def test_section_heading_is_level_2(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Chapter One", fontsize=22, fontname="hebo")
    page.insert_text((72, 150), "A Section Title", fontsize=13, fontname="hebo")
    page.insert_text((72, 190), "A normal paragraph of body text follows here for padding.", fontsize=11)
    structure = build_structure("b1", "en", tmp_pdf(doc))

    headings = {b.text: b.level for b in structure.blocks if b.type == "heading"}
    assert headings["Chapter One"] == 1
    assert headings["A Section Title"] == 2


def test_monospace_block_becomes_code_and_is_pre_translated(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "function add(a, b) {", fontsize=10, fontname="cour")
    page.insert_text((72, 114), "  return a + b;", fontsize=10, fontname="cour")
    page.insert_text((72, 128), "}", fontsize=10, fontname="cour")
    structure = build_structure("b1", "en", tmp_pdf(doc))

    code_blocks = [b for b in structure.blocks if b.type == "code"]
    assert len(code_blocks) == 1
    block = code_blocks[0]
    assert "\n" in block.text
    assert block.text.splitlines() == ["function add(a, b) {", "  return a + b;", "}"]
    # Code is never sent to the LLM — translated_text is pre-filled verbatim.
    assert block.translated_text == block.text


def test_short_lines_become_verse(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Roses are red,", fontsize=11)
    page.insert_text((72, 116), "Violets are blue,", fontsize=11)
    page.insert_text((72, 132), "Sugar is sweet,", fontsize=11)
    structure = build_structure("b1", "en", tmp_pdf(doc))

    verse_blocks = [b for b in structure.blocks if b.type == "verse"]
    assert len(verse_blocks) == 1
    assert "\n" in verse_blocks[0].text
    assert verse_blocks[0].translated_text is None  # verse IS translated, unlike code


def test_long_wrapped_paragraph_is_not_misclassified_as_verse(tmp_pdf):
    """The trickiest boundary: word-wrapped prose must stay type='paragraph'."""
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        "This is the first line of a long paragraph that has been wrapped",
        "across several lines of roughly similar and fairly long width, just",
        "like ordinary body text found throughout the rest of this book here.",
    ]
    y = 100
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 15
    structure = build_structure("b1", "en", tmp_pdf(doc))

    types = {b.type for b in structure.blocks}
    assert "verse" not in types
    paragraphs = [b for b in structure.blocks if b.type == "paragraph"]
    assert len(paragraphs) == 1


def test_repeating_header_filtered_across_pages(tmp_pdf):
    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 40), "RUNNING HEADER", fontsize=9)
        page.insert_text((72, 100), f"Unique body content for page {i} goes here.", fontsize=11)
    structure = build_structure("b1", "en", tmp_pdf(doc))

    all_text = " ".join(b.text for b in structure.blocks)
    assert "RUNNING HEADER" not in all_text
    assert "Unique body content for page 0" in all_text
    assert "Unique body content for page 3" in all_text


def test_content_appearing_once_is_kept_even_with_many_pages(tmp_pdf):
    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 100), f"Distinct paragraph text unique to page {i}.", fontsize=11)
    structure = build_structure("b1", "en", tmp_pdf(doc))

    paragraphs = [b.text for b in structure.blocks if b.type == "paragraph"]
    assert len(paragraphs) == 4


def test_page_number_only_block_filtered(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Real paragraph content that should be kept in the output.", fontsize=11)
    page.insert_text((300, 800), "42", fontsize=9)
    structure = build_structure("b1", "en", tmp_pdf(doc))

    all_text = [b.text for b in structure.blocks]
    assert "42" not in all_text
    assert any("Real paragraph content" in t for t in all_text)


def test_image_block_included_with_data_uri_html(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Text before the image.", fontsize=11)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20))
    pix.set_rect(pix.irect, (10, 20, 30))
    page.insert_image(pymupdf.Rect(72, 150, 92, 170), pixmap=pix)
    page.insert_text((72, 200), "Text after the image.", fontsize=11)
    structure = build_structure("b1", "en", tmp_pdf(doc))

    images = [b for b in structure.blocks if b.type == "image"]
    assert len(images) == 1
    assert images[0].html.startswith('<img src="data:image/')
    assert images[0].translated_text == ""

    # Reading order preserved: text-before, image, text-after.
    ordered_types = [b.type for b in structure.blocks if b.type != "page_break"]
    assert ordered_types == ["paragraph", "image", "paragraph"]


def test_page_break_inserted_between_pages(tmp_pdf):
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((72, 100), f"Content on page {i}.", fontsize=11)
    structure = build_structure("b1", "en", tmp_pdf(doc))

    assert any(b.type == "page_break" for b in structure.blocks)


def test_bold_paragraph_gets_html_with_strong_tag(tmp_pdf):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "This whole sentence is bold for the test.", fontsize=11, fontname="hebo")
    structure = build_structure("b1", "en", tmp_pdf(doc))

    paragraphs = [b for b in structure.blocks if b.type == "paragraph"]
    assert len(paragraphs) == 1
    assert "<strong>" in paragraphs[0].html
