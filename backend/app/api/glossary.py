import json

from fastapi import APIRouter, HTTPException

from app.config import BOOKS_DIR
from app.db import get_connection
from app.models.schemas import GlossaryOut

router = APIRouter(prefix="/api/books", tags=["glossary"])


@router.get("/{book_id}/glossary", response_model=GlossaryOut)
def get_glossary(book_id: str) -> GlossaryOut:
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    glossary_path = BOOKS_DIR / book_id / "glossary.json"
    if not glossary_path.exists():
        return GlossaryOut(terms={})
    terms = json.loads(glossary_path.read_text(encoding="utf-8"))
    return GlossaryOut(terms=terms)
