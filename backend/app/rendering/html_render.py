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


RETRANSLATABLE_BLOCK_TYPES = ("heading", "paragraph", "verse")


def _translated_html(block: Block, interactive: bool) -> str:
    if block.translation_error:
        html = _wrap(block, escape(block.text), cls="translation-error")
    elif block.translated_text is None:
        # Not reached by the pipeline yet — show the original, visibly pending.
        # Nothing to retranslate yet, so no button even when interactive.
        return _wrap(block, escape(block.text), cls="pending")
    else:
        # LLM output is plain text; convert any preserved line breaks (verse) to <br>.
        text_html = str(escape(block.translated_text)).replace("\n", "<br>")
        html = _wrap(block, text_html)
    if interactive and block.type in RETRANSLATABLE_BLOCK_TYPES:
        # Inert without JS — only the Angular reader (interactive=True) wires up a
        # click handler for it. The standalone output.html never sets interactive,
        # so it never gets a button that would do nothing there.
        html += (
            f'<button type="button" class="retranslate-btn" data-block-id="{block.id}" '
            'title="Dịch lại đoạn này">↻</button>'
        )
    return html


def _render_block(block: Block, interactive: bool) -> str:
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
    translated = _translated_html(block, interactive)
    return (
        f'<div class="block"{anchor}>'
        f'<div class="original" lang="und">{original}</div>'
        f'<div class="translated" lang="vi">{translated}</div>'
        f"</div>"
    )


def render_body(structure: BookStructure, title: str, interactive: bool = False) -> str:
    """Inner-HTML fragment: served to the Angular reader and embedded in the standalone file.

    The wrapping <article> gets a mode class (mode-both | mode-original | mode-translated)
    set by the viewer; default is mode-both (side-by-side). `interactive` adds the
    per-block "Dịch lại" button — only for the Angular reader (see api/html.py),
    never for the standalone file, which has no backend to call.
    """
    parts = ['<article class="book mode-both">', f'<h1 class="book-title">{escape(title)}</h1>']
    parts += [_render_block(b, interactive) for b in structure.blocks]
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
