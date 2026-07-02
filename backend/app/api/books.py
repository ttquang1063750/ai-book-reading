import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.config import BOOKS_DIR, MAX_UPLOAD_BYTES
from app.db import get_connection
from app.models.schemas import BookOut
from app.pipeline.job_runner import has_running_job_for_book

router = APIRouter(prefix="/api/books", tags=["books"])


def _row_to_book(row) -> BookOut:
    return BookOut(**dict(row))


@router.post("", response_model=BookOut, status_code=201)
async def upload_book(
    file: UploadFile,
    target_lang: str = Form("Tiếng Việt"),
) -> BookOut:
    # source_lang is intentionally not accepted here — it's auto-detected from
    # the PDF's own text right after extraction, when the translation job runs.
    target_lang = target_lang.strip()
    if not target_lang or len(target_lang) > 50:
        raise HTTPException(status_code=422, detail="target_lang must be 1-50 characters")
    filename = file.filename or "book.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF files are accepted")

    book_id = uuid.uuid4().hex
    book_dir = BOOKS_DIR / book_id
    book_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = book_dir / "original.pdf"
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        book_dir.rmdir()
        raise HTTPException(
            status_code=413,
            detail=f"File too large — max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )
    if not content.startswith(b"%PDF"):
        book_dir.rmdir()
        raise HTTPException(status_code=422, detail="File does not look like a PDF")
    pdf_path.write_bytes(content)

    title = Path(filename).stem
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO books (id, title, original_filename, source_lang, target_lang, page_count, created_at, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (book_id, title, filename, "", target_lang, None, created_at, "uploaded"),
        )

    return BookOut(
        id=book_id,
        title=title,
        original_filename=filename,
        source_lang="",
        target_lang=target_lang,
        page_count=None,
        created_at=created_at,
        status="uploaded",
    )


@router.get("", response_model=list[BookOut])
def list_books() -> list[BookOut]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
    return [_row_to_book(r) for r in rows]


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: str) -> BookOut:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return _row_to_book(row)


@router.delete("/{book_id}", status_code=204)
def delete_book(book_id: str) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if has_running_job_for_book(book_id):
        raise HTTPException(status_code=409, detail="Cannot delete while a translation job is running")

    with get_connection() as conn:
        conn.execute("DELETE FROM jobs WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    shutil.rmtree(BOOKS_DIR / book_id, ignore_errors=True)
