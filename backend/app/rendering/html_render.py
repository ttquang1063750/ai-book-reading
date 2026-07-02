"""Assemble translated blocks into HTML: a standalone file and an embeddable fragment."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import escape

from app.config import BOOKS_DIR
from app.db import get_connection
from app.models.book_structure import Block, BookStructure

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "jinja2"]),
)


def _wrap(block: Block, inner: str, cls: str = "") -> str:
    css = f' class="{cls}"' if cls else ""
    if block.type == "heading":
        tag = "h2" if (block.level or 1) == 1 else "h3"
        return f"<{tag}{css}>{inner}</{tag}>"
    return f"<p{css}>{inner}</p>"


def _original_html(block: Block) -> str:
    """Rich inline markup (bold/italic/line breaks) when available, else plain escaped text."""
    return block.html if block.html is not None else str(escape(block.text))


def _translated_html(block: Block) -> str:
    if block.translation_error:
        return _wrap(block, escape(block.text), cls="translation-error")
    if block.translated_text is None:
        # Not reached by the pipeline yet — show the original, visibly pending.
        return _wrap(block, escape(block.text), cls="pending")
    # LLM output is plain text; convert any preserved line breaks (verse) to <br>.
    text_html = str(escape(block.translated_text)).replace("\n", "<br>")
    return _wrap(block, text_html)


def _render_block(block: Block) -> str:
    # A stable anchor for each block, used by the reader's chapter navigation
    # (heading blocks in particular — see api/chapters.py) to scroll to a section.
    anchor = f' id="block-{block.id}"'

    if block.type == "page_break":
        return f'<hr class="page-break" data-page="{block.page}">'

    if block.type in ("image", "code"):
        # Not translated — render once, spanning both columns instead of duplicating.
        cls = "media" if block.type == "image" else "code-block"
        content = block.html if block.type == "image" else f"<pre><code>{block.html}</code></pre>"
        return f'<div class="block block-{cls}"{anchor}>{content}</div>'

    original = _wrap(block, _original_html(block))
    translated = _translated_html(block)
    return (
        f'<div class="block"{anchor}>'
        f'<div class="original" lang="und">{original}</div>'
        f'<div class="translated" lang="vi">{translated}</div>'
        f"</div>"
    )


def render_body(structure: BookStructure, title: str) -> str:
    """Inner-HTML fragment: served to the Angular reader and embedded in the standalone file.

    The wrapping <article> gets a mode class (mode-both | mode-original | mode-translated)
    set by the viewer; default is mode-both (side-by-side).
    """
    parts = ['<article class="book mode-both">', f'<h1 class="book-title">{escape(title)}</h1>']
    parts += [_render_block(b) for b in structure.blocks]
    parts.append("</article>")
    return "\n".join(parts)


def render_book(book_id: str) -> Path:
    """Render and persist data/books/{id}/output.html; returns the file path."""
    book_dir = BOOKS_DIR / book_id
    structure = BookStructure.load(book_dir / "structure.json")
    with get_connection() as conn:
        row = conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
    title = row["title"] if row else book_id

    body = render_body(structure, title)
    html = _env.get_template("book.html.jinja2").render(title=title, body=body)
    out_path = book_dir / "output.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
