from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import BOOKS_DIR
from app.db import get_connection
from app.models.book_structure import BookStructure
from app.pipeline.summarize import split_into_chapters

router = APIRouter(prefix="/api/books", tags=["chapters"])


class ChapterOut(BaseModel):
    heading_block_id: int
    title: str


@router.get("/{book_id}/chapters", response_model=list[ChapterOut])
def get_chapters(book_id: str) -> list[ChapterOut]:
    """Lightweight chapter list for reader navigation — just titles + anchors,
    no summarization (unlike GET /summaries, this needs no LLM call and no job)."""
    with get_connection() as conn:
        row = conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")

    structure_path = BOOKS_DIR / book_id / "structure.json"
    if not structure_path.exists():
        return []
    structure = BookStructure.load(structure_path)
    chapters = split_into_chapters(structure.blocks, row["title"])
    return [
        ChapterOut(heading_block_id=c.heading_block_id, title=c.title)
        for c in chapters
        if c.heading_block_id != -1  # skip the synthetic "front matter" bucket
    ]
