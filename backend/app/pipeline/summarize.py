"""Per-chapter summaries of the translated (Vietnamese) text, via the polish model."""

import logging
from dataclasses import dataclass, field

from app.config import POLISH_MODEL
from app.models.book_structure import Block
from app.pipeline import ollama_client
from app.pipeline.chunking import estimate_tokens

logger = logging.getLogger(__name__)

# Leaves ample room in the polish model's context for prompt overhead + output.
SUMMARY_GROUP_TOKEN_BUDGET = 6000
DEFAULT_CHAPTER_TITLE = "Mở đầu"


@dataclass
class Chapter:
    heading_block_id: int
    title: str
    blocks: list[Block] = field(default_factory=list)

    @property
    def translated_text(self) -> str:
        parts = [b.translated_text for b in self.blocks if b.translated_text]
        return "\n\n".join(parts)


def split_into_chapters(blocks: list[Block], book_title: str) -> list[Chapter]:
    """Group blocks by level-1 heading. Content before the first heading (if any)
    becomes its own leading chapter; if there are no level-1 headings at all, the
    whole book becomes a single chapter."""
    chapters: list[Chapter] = []
    current: Chapter | None = None

    for block in blocks:
        if block.type == "heading" and block.level == 1:
            current = Chapter(heading_block_id=block.id, title=block.translated_text or block.text)
            chapters.append(current)
            continue
        if block.type in ("page_break",):
            continue
        if current is None:
            current = Chapter(heading_block_id=-1, title=DEFAULT_CHAPTER_TITLE)
            chapters.append(current)
        current.blocks.append(block)

    if not chapters:
        chapters = [Chapter(heading_block_id=-1, title=book_title, blocks=list(blocks))]

    return [c for c in chapters if c.translated_text.strip()]


def _group_by_budget(text: str, budget: int = SUMMARY_GROUP_TOKEN_BUDGET) -> list[str]:
    """Split already-translated chapter text into paragraph groups under a token budget."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    groups: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for p in paragraphs:
        p_tokens = estimate_tokens(p)
        if current and current_tokens + p_tokens > budget:
            groups.append("\n\n".join(current))
            current, current_tokens = [], 0
        current.append(p)
        current_tokens += p_tokens
    if current:
        groups.append("\n\n".join(current))
    return groups or [text]


async def _summarize_text(text: str, title: str) -> str:
    system = (
        "Bạn là một biên tập viên sách. Viết một đoạn tóm tắt ngắn gọn (khoảng 4-8 câu) bằng "
        "tiếng Việt cho nội dung được cung cấp, nêu bật các nhân vật/sự kiện/ý chính, không thêm "
        "bình luận, không lặp lại tiêu đề."
    )
    user = f"Chương: {title}\n\nNội dung:\n{text}"
    return await ollama_client.chat(
        POLISH_MODEL,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.5,
    )


async def summarize_chapter(chapter: Chapter) -> str:
    """Map-reduce summary: summarize directly if short enough, else summarize each
    group and combine those partial summaries into one final summary."""
    text = chapter.translated_text
    if estimate_tokens(text) <= SUMMARY_GROUP_TOKEN_BUDGET:
        return (await _summarize_text(text, chapter.title)).strip()

    groups = _group_by_budget(text)
    logger.info("Chapter '%s' too long (%d groups) — using map-reduce summary", chapter.title, len(groups))
    partials = [await _summarize_text(g, chapter.title) for g in groups]
    combined = "\n\n".join(f"- {p.strip()}" for p in partials)
    return (await _summarize_text(combined, chapter.title)).strip()
