from typing import Literal

from pydantic import BaseModel


class BookOut(BaseModel):
    id: str
    title: str
    original_filename: str
    source_lang: str
    target_lang: str
    page_count: int | None = None
    created_at: str
    status: Literal["uploaded", "extracted", "translating", "done", "error"]


class ChapterSummaryOut(BaseModel):
    heading_block_id: int
    title: str
    summary: str | None = None


class IndexStatusOut(BaseModel):
    indexed: bool
    chunk_count: int


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str


class JobOut(BaseModel):
    id: str
    book_id: str
    job_type: Literal["translate", "summarize", "index"] = "translate"
    status: Literal["queued", "running", "done", "error", "cancelled"]
    current_stage: str | None = None
    total_chunks: int | None = None
    completed_chunks: int = 0
    failed_chunks: int = 0
    error_message: str | None = None
    created_at: str
    updated_at: str
