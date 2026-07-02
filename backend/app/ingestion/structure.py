"""Classify raw PDF blocks into headings/paragraphs/code/verse/images and build book structure."""

import base64
from collections import Counter
from pathlib import Path

from markupsafe import escape

from app.ingestion.pdf_extract import RawBlock, RawImage, RawLine, extract_raw_blocks
from app.models.book_structure import Block, BookStructure

HEADING_SIZE_RATIO = 1.15
CHAPTER_SIZE_RATIO = 1.4
HEADING_MAX_WORDS = 15
HEADER_FOOTER_MAX_WORDS = 8
HEADER_FOOTER_PAGE_RATIO = 0.5
Y_BAND = 20.0  # points; blocks whose y0 falls in the same band are "same position"

# A block reads as verse (poetry/address) rather than wrapped prose when its lines
# are short and don't look like word-wrapped paragraph text.
VERSE_MAX_AVG_LINE_CHARS = 45
VERSE_MIN_LINES = 2

_MIME_BY_EXT = {"png": "png", "jpeg": "jpeg", "jpg": "jpeg", "gif": "gif", "bmp": "bmp"}

Run = tuple[str, bool, bool]  # (text, bold, italic)


def _lines_to_runs_joined(lines: list[RawLine]) -> list[Run]:
    """Flatten lines into runs for flowing prose, repairing end-of-line hyphenation."""
    runs: list[Run] = []
    for line in lines:
        line_runs = [(s.text, s.bold, s.italic) for s in line.spans if s.text]
        if not line_runs:
            continue
        if runs and runs[-1][0].rstrip().endswith("-") and runs[-1][0].strip():
            text, bold, italic = runs[-1]
            runs[-1] = (text.rstrip()[:-1], bold, italic)
        elif runs:
            runs.append((" ", False, False))
        runs.extend(line_runs)
    return runs


def _lines_to_runs_preserved(lines: list[RawLine]) -> list[Run]:
    """Flatten lines into runs preserving each line break — for code/verse blocks."""
    runs: list[Run] = []
    for line in lines:
        line_runs = [(s.text, s.bold, s.italic) for s in line.spans if s.text]
        if not line_runs:
            continue
        if runs:
            runs.append(("\n", False, False))
        runs.extend(line_runs)
    return runs


def _runs_to_text(runs: list[Run]) -> str:
    return "".join(r[0] for r in runs).strip()


def _runs_to_html(runs: list[Run]) -> str:
    """Escape and wrap runs in <strong>/<em>, merging adjacent runs of the same style."""
    parts: list[str] = []
    open_tags: list[str] = []

    def close_all() -> None:
        while open_tags:
            parts.append(f"</{open_tags.pop()}>")

    current_style: tuple[bool, bool] | None = None
    for text, bold, italic in runs:
        if text == "\n":
            parts.append("<br>")
            continue
        style = (bold, italic)
        if style != current_style:
            close_all()
            if bold:
                parts.append("<strong>")
                open_tags.append("strong")
            if italic:
                parts.append("<em>")
                open_tags.append("em")
            current_style = style
        parts.append(str(escape(text)))
    close_all()
    return "".join(parts).strip()


def _modal_body_size(blocks: list[RawBlock]) -> float:
    """Most common span size weighted by text length — the body-text size."""
    counter: Counter[float] = Counter()
    for block in blocks:
        for line in block.lines:
            counter[round(line.max_size * 2) / 2] += len(line.text)
    if not counter:
        return 11.0
    return counter.most_common(1)[0][0]


def _repeating_header_footer_keys(blocks: list[RawBlock], page_count: int) -> set[tuple[str, int]]:
    """Find (normalized text, y-band) pairs that repeat on many pages — running headers/footers."""
    if page_count < 3:
        return set()
    seen: dict[tuple[str, int], set[int]] = {}
    for block in blocks:
        if block.word_count > HEADER_FOOTER_MAX_WORDS:
            continue
        key = (block.text_joined.lower(), int(block.y0 // Y_BAND))
        seen.setdefault(key, set()).add(block.page)
    return {
        key for key, pages in seen.items() if len(pages) / page_count > HEADER_FOOTER_PAGE_RATIO
    }


def _is_page_number(block: RawBlock) -> bool:
    text = block.text_joined
    return text.isdigit() or (len(text) <= 8 and text.replace(" ", "").isdigit())


def _is_verse(block: RawBlock) -> bool:
    lines = [l for l in block.lines if l.text.strip()]
    if len(lines) < VERSE_MIN_LINES:
        return False
    avg_len = sum(len(l.text.strip()) for l in lines) / len(lines)
    # Wrapped prose fills most lines to a similar, longer width; verse/addresses don't.
    return avg_len <= VERSE_MAX_AVG_LINE_CHARS


def build_structure(book_id: str, source_lang: str, pdf_path: Path) -> BookStructure:
    raw_blocks, raw_images, page_count = extract_raw_blocks(pdf_path)
    body_size = _modal_body_size(raw_blocks)
    skip_keys = _repeating_header_footer_keys(raw_blocks, page_count)

    # Merge text blocks and images into one reading-order stream per page (top to bottom).
    items: list[tuple[int, float, str, object]] = []
    for b in raw_blocks:
        items.append((b.page, b.y0, "text", b))
    for img in raw_images:
        items.append((img.page, img.y0, "image", img))
    items.sort(key=lambda t: (t[0], t[1]))

    blocks: list[Block] = []
    next_id = 0
    current_page = 0

    def append(
        block_type: str,
        page: int,
        text: str,
        level: int | None = None,
        html: str | None = None,
        translated_text: str | None = None,
    ) -> None:
        nonlocal next_id
        blocks.append(
            Block(
                id=next_id,
                page=page,
                type=block_type,
                level=level,
                text=text,
                html=html,
                translated_text=translated_text,
                order_key=next_id,
            )
        )
        next_id += 1

    def maybe_page_break(page: int) -> None:
        nonlocal current_page
        if page != current_page:
            if current_page != 0:
                append("page_break", page, "")
            current_page = page

    for page, _y0, kind, raw in items:
        if kind == "image":
            img: RawImage = raw  # type: ignore[assignment]
            mime = _MIME_BY_EXT.get(img.ext.lower(), "png")
            b64 = base64.b64encode(img.data).decode("ascii")
            html = f'<img src="data:image/{mime};base64,{b64}" alt="">'
            maybe_page_break(page)
            append("image", page, "", html=html, translated_text="")
            continue

        block: RawBlock = raw  # type: ignore[assignment]
        key = (block.text_joined.lower(), int(block.y0 // Y_BAND))
        if key in skip_keys or _is_page_number(block):
            continue
        if not block.text_joined:
            continue

        maybe_page_break(page)

        is_heading = (
            block.max_size >= body_size * HEADING_SIZE_RATIO
            and block.word_count <= HEADING_MAX_WORDS
        )
        if is_heading:
            level = 1 if block.max_size >= body_size * CHAPTER_SIZE_RATIO else 2
            runs = _lines_to_runs_joined(block.lines)
            append(
                "heading",
                page,
                _runs_to_text(runs),
                level=level,
                html=_runs_to_html(runs),
            )
        elif block.is_mono:
            # Code listing: not translated, kept verbatim, line breaks preserved.
            runs = _lines_to_runs_preserved(block.lines)
            text = _runs_to_text(runs)
            append("code", page, text, html=_runs_to_html(runs), translated_text=text)
        elif _is_verse(block):
            runs = _lines_to_runs_preserved(block.lines)
            append("verse", page, _runs_to_text(runs), html=_runs_to_html(runs))
        else:
            runs = _lines_to_runs_joined(block.lines)
            append("paragraph", page, _runs_to_text(runs), html=_runs_to_html(runs))

    return BookStructure(
        book_id=book_id, source_lang=source_lang, page_count=page_count, blocks=blocks
    )


def extract_book(book_id: str, source_lang: str, book_dir: Path) -> BookStructure:
    """Extract structure from a book's original.pdf and persist structure.json."""
    structure = build_structure(book_id, source_lang, book_dir / "original.pdf")
    structure.save(book_dir / "structure.json")
    return structure
