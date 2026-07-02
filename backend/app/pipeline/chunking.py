"""Group ordered blocks into translation chunks that respect paragraph boundaries."""

from dataclasses import dataclass, field

from app.config import CHARS_PER_TOKEN_ESTIMATE, CHUNK_TOKEN_BUDGET
from app.models.book_structure import Block


PASSTHROUGH_TYPES = {"page_break", "image", "code"}


@dataclass
class Chunk:
    index: int
    blocks: list[Block] = field(default_factory=list)

    @property
    def text_blocks(self) -> list[Block]:
        """Blocks that need translation — excludes page breaks, images, and code
        listings (kept verbatim; translating source code would corrupt syntax)."""
        return [b for b in self.blocks if b.type not in PASSTHROUGH_TYPES]

    @property
    def source_text(self) -> str:
        return "\n\n".join(b.text for b in self.text_blocks)


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN_ESTIMATE + 1


def build_chunks(blocks: list[Block], token_budget: int = CHUNK_TOKEN_BUDGET) -> list[Chunk]:
    """Accumulate whole blocks into chunks up to the token budget.

    Never splits a block. A single oversized block becomes its own over-budget
    chunk rather than looping forever. page_break blocks carry no text and are
    attached to whichever chunk is open (they never start one).
    """
    chunks: list[Chunk] = []
    current: list[Block] = []
    current_tokens = 0

    def close() -> None:
        nonlocal current, current_tokens
        if any(b.type not in PASSTHROUGH_TYPES for b in current):
            chunks.append(Chunk(index=len(chunks), blocks=current))
        elif current and chunks:
            chunks[-1].blocks.extend(current)
        current = []
        current_tokens = 0

    for block in blocks:
        block_tokens = 0 if block.type in PASSTHROUGH_TYPES else estimate_tokens(block.text)
        if current_tokens and current_tokens + block_tokens > token_budget:
            close()
        current.append(block)
        current_tokens += block_tokens
    close()

    return chunks
