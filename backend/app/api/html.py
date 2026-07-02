import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.config import BOOKS_DIR
from app.db import get_connection
from app.models.book_structure import BookStructure
from app.rendering.html_render import render_body

router = APIRouter(prefix="/api/books", tags=["html"])


def _safe_filename(title: str) -> str:
    name = re.sub(r"[^\w\-\. ]", "", title).strip() or "book"
    return f"{name}.html"


@router.get("/{book_id}/html", response_class=HTMLResponse)
def book_html(book_id: str) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    structure_path = BOOKS_DIR / book_id / "structure.json"
    if not structure_path.exists():
        raise HTTPException(status_code=409, detail="Book has not been processed yet")
    structure = BookStructure.load(structure_path)
    return render_body(structure, row["title"])


@router.get("/{book_id}/download")
def download_book(book_id: str) -> FileResponse:
    with get_connection() as conn:
        row = conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    output_path = BOOKS_DIR / book_id / "output.html"
    if not output_path.exists():
        raise HTTPException(status_code=409, detail="Book has not finished translating yet")
    return FileResponse(
        output_path, media_type="text/html", filename=_safe_filename(row["title"])
    )
