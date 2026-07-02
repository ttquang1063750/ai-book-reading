import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.db import get_connection, get_job
from app.models.schemas import ChatMessageOut, IndexStatusOut, JobOut
from app.pipeline import rag
from app.pipeline.job_runner import get_book_lock, has_running_job_for_book, start_index_job

router = APIRouter(prefix="/api/books", tags=["chat"])


class ChatMessageIn(BaseModel):
    message: str


def _get_book_or_404(book_id: str):
    with get_connection() as conn:
        book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.post("/{book_id}/index", response_model=JobOut, status_code=202)
async def index_book(book_id: str) -> JobOut:
    book = _get_book_or_404(book_id)
    if book["status"] != "done":
        raise HTTPException(status_code=409, detail="Book must finish translating before indexing")

    async with get_book_lock(book_id):
        if has_running_job_for_book(book_id):
            raise HTTPException(status_code=409, detail="A job is already running for this book")

        job_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO jobs (id, book_id, job_type, status, created_at, updated_at)"
                " VALUES (?, ?, 'index', 'queued', ?, ?)",
                (job_id, book_id, now, now),
            )
        start_index_job(job_id, book_id)
    return JobOut(**dict(get_job(job_id)))


@router.get("/{book_id}/index-status", response_model=IndexStatusOut)
def get_index_status(book_id: str) -> IndexStatusOut:
    _get_book_or_404(book_id)
    indexed, chunk_count = rag.index_status(book_id)
    return IndexStatusOut(indexed=indexed, chunk_count=chunk_count)


@router.get("/{book_id}/chat/history", response_model=list[ChatMessageOut])
def get_chat_history(book_id: str) -> list[ChatMessageOut]:
    _get_book_or_404(book_id)
    return [ChatMessageOut(**m) for m in rag.load_chat_history(book_id)]


@router.delete("/{book_id}/chat/history", status_code=204)
def delete_chat_history(book_id: str) -> None:
    _get_book_or_404(book_id)
    rag.clear_chat_history(book_id)


@router.post("/{book_id}/chat/messages")
async def post_chat_message(book_id: str, body: ChatMessageIn) -> StreamingResponse:
    """Streams the assistant's answer as plain incremental text chunks (not
    SSE framing) — the frontend reads it via fetch() + ReadableStream, so no
    "data: ..." wrapping is needed. History is saved server-side once the
    stream completes; checks below run eagerly, before any bytes are sent,
    so they still surface as normal HTTP error responses."""
    book = _get_book_or_404(book_id)
    indexed, chunk_count = rag.index_status(book_id)
    if not indexed or chunk_count == 0:
        raise HTTPException(status_code=409, detail="Book has not been indexed yet")
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="Message must not be empty")

    return StreamingResponse(
        rag.stream_answer_question(book_id, body.message, book["target_lang"]), media_type="text/plain"
    )
