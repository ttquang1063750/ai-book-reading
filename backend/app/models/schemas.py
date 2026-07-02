from typing import Literal

from pydantic import BaseModel


class BookOut(BaseModel):
    id: str
    title: str
    original_filename: str
    source_lang: Literal["en", "fr"]
    page_count: int | None = None
    created_at: str
    status: Literal["uploaded", "extracted", "translating", "done", "error"]


class JobOut(BaseModel):
    id: str
    book_id: str
    status: Literal["queued", "running", "done", "error", "cancelled"]
    current_stage: str | None = None
    total_chunks: int | None = None
    completed_chunks: int = 0
    failed_chunks: int = 0
    error_message: str | None = None
    created_at: str
    updated_at: str
