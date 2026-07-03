"""Tests for html_render.py's interactive "Dịch lại" button — must appear only
for the Angular reader (interactive=True), never in the standalone output.html
(interactive=False, the default), which has no backend to call."""

from app.models.book_structure import BookStructure
from app.rendering.html_render import render_body
from tests.conftest import make_block


def _structure(blocks) -> BookStructure:
    return BookStructure(book_id="b1", source_lang="en", page_count=1, blocks=blocks)


def test_interactive_adds_retranslate_button_for_translated_paragraph():
    blocks = [make_block(3, text="Src", translated_text="Đã dịch.")]
    html = render_body(_structure(blocks), "Title", interactive=True)
    assert 'class="retranslate-btn"' in html
    assert 'data-block-id="3"' in html


def test_non_interactive_never_adds_button():
    blocks = [make_block(3, text="Src", translated_text="Đã dịch.")]
    html = render_body(_structure(blocks), "Title", interactive=False)
    assert "retranslate-btn" not in html


def test_interactive_defaults_to_false():
    blocks = [make_block(3, text="Src", translated_text="Đã dịch.")]
    html = render_body(_structure(blocks), "Title")
    assert "retranslate-btn" not in html


def test_interactive_omits_button_for_pending_block():
    blocks = [make_block(0, text="Src", translated_text=None)]
    html = render_body(_structure(blocks), "Title", interactive=True)
    assert "retranslate-btn" not in html


def test_interactive_still_adds_button_for_translation_error_block():
    block = make_block(0, text="Src", translated_text=None)
    block.translation_error = True
    html = render_body(_structure([block]), "Title", interactive=True)
    assert 'class="retranslate-btn"' in html
    assert 'data-block-id="0"' in html


def test_interactive_omits_button_for_image_and_code_blocks():
    blocks = [
        make_block(0, type_="image", text="", translated_text=""),
        make_block(1, type_="code", text="print(1)", translated_text="print(1)"),
    ]
    html = render_body(_structure(blocks), "Title", interactive=True)
    assert "retranslate-btn" not in html
