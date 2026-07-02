import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.config import BOOKS_DIR
from app.db import get_connection, get_job
from app.models.schemas import ChapterSummaryOut, JobOut
from app.pipeline.job_runner import has_running_job_for_book, start_summarize_job

router = APIRouter(prefix="/api/books", tags=["summaries"])


def _get_book_or_404(book_id: str):
    with get_connection() as conn:
        book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.post("/{book_id}/summarize", response_model=JobOut, status_code=202)
async def summarize_book(book_id: str, force: bool = Query(False)) -> JobOut:
    book = _get_book_or_404(book_id)
    if book["status"] != "done":
        raise HTTPException(status_code=409, detail="Book must finish translating before summarizing")
    if has_running_job_for_book(book_id):
        raise HTTPException(status_code=409, detail="A job is already running for this book")

    if force:
        summaries_path = BOOKS_DIR / book_id / "summaries.json"
        summaries_path.unlink(missing_ok=True)

    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO jobs (id, book_id, job_type, status, created_at, updated_at)"
            " VALUES (?, ?, 'summarize', 'queued', ?, ?)",
            (job_id, book_id, now, now),
        )
    start_summarize_job(job_id, book_id)
    return JobOut(**dict(get_job(job_id)))


@router.get("/{book_id}/summaries", response_model=list[ChapterSummaryOut])
def get_summaries(book_id: str) -> list[ChapterSummaryOut]:
    _get_book_or_404(book_id)
    summaries_path = BOOKS_DIR / book_id / "summaries.json"
    if not summaries_path.exists():
        return []
    data = json.loads(summaries_path.read_text(encoding="utf-8"))
    return [
        ChapterSummaryOut(heading_block_id=int(k), title=v["title"], summary=v["summary"])
        for k, v in data.items()
    ]
