import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.config import BOOKS_DIR
from app.db import get_connection, get_job, get_latest_job_for_book
from app.models.book_structure import BookStructure
from app.models.schemas import JobOut
from app.pipeline.job_runner import cancel_job, get_book_lock, has_running_job_for_book, start_job

router = APIRouter(prefix="/api", tags=["jobs"])


def _row_to_job(row) -> JobOut:
    return JobOut(**dict(row))


async def _create_and_start_job(book_id: str, target_lang: str) -> JobOut:
    async with get_book_lock(book_id):
        if has_running_job_for_book(book_id):
            raise HTTPException(
                status_code=409, detail="A translation job is already running for this book"
            )
        job_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO jobs (id, book_id, job_type, status, created_at, updated_at)"
                " VALUES (?, ?, 'translate', ?, ?, ?)",
                (job_id, book_id, "queued", now, now),
            )
        start_job(job_id, book_id, target_lang)
    return _row_to_job(get_job(job_id))


def _get_book_or_404(book_id: str):
    with get_connection() as conn:
        book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.post("/books/{book_id}/translate", response_model=JobOut, status_code=202)
async def translate_book(book_id: str) -> JobOut:
    book = _get_book_or_404(book_id)
    return await _create_and_start_job(book_id, book["target_lang"])


@router.get("/jobs/{job_id}", response_model=JobOut)
def job_status(job_id: str) -> JobOut:
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _row_to_job(row)


@router.get("/books/{book_id}/job", response_model=JobOut)
def latest_job_for_book(book_id: str) -> JobOut:
    _get_book_or_404(book_id)
    row = get_latest_job_for_book(book_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No job for this book")
    return _row_to_job(row)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut, status_code=202)
async def cancel_job_endpoint(job_id: str) -> JobOut:
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] not in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Job is not running")
    if not cancel_job(job_id):
        raise HTTPException(status_code=409, detail="Job is not tracked as running (server may have restarted)")
    return _row_to_job(get_job(job_id))


@router.post("/jobs/{job_id}/retry-failed", response_model=JobOut, status_code=202)
async def retry_failed(job_id: str) -> JobOut:
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    book_id = row["book_id"]
    book = _get_book_or_404(book_id)

    # Clear error flags so failed chunks are re-attempted (completed chunks are skipped).
    structure_path = BOOKS_DIR / book_id / "structure.json"
    if structure_path.exists():
        structure = BookStructure.load(structure_path)
        for block in structure.blocks:
            if block.translation_error:
                block.rough_text = None
                block.translated_text = None
                block.translation_error = False
        structure.save(structure_path)

    return await _create_and_start_job(book_id, book["target_lang"])
