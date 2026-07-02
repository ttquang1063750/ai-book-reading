"""Background translation job: extraction → chunked hybrid translation → HTML."""

import asyncio
import json
import logging
from pathlib import Path

from app.config import BOOKS_DIR
from app.db import get_connection, update_book, update_job
from app.ingestion.structure import extract_book
from app.models.book_structure import BookStructure
from app.pipeline.chunking import Chunk, build_chunks
from app.pipeline.translate import polish_chunk, rough_translate_chunk, tail_sentences

logger = logging.getLogger(__name__)

# job_id -> asyncio.Task, for status introspection and future cancellation
RUNNING_JOBS: dict[str, asyncio.Task] = {}


def _load_glossary(path: Path) -> dict[str, str]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_glossary(path: Path, glossary: dict[str, str]) -> None:
    path.write_text(json.dumps(glossary, ensure_ascii=False, indent=1), encoding="utf-8")


def _rough_done(chunk: Chunk) -> bool:
    return all(b.rough_text is not None for b in chunk.text_blocks)


def _polish_done(chunk: Chunk) -> bool:
    return all(b.translated_text is not None for b in chunk.text_blocks)


async def _run_rough_phase(
    job_id: str, chunks: list[Chunk], source_lang: str, glossary: dict[str, str],
    structure: BookStructure, structure_path: Path, glossary_path: Path,
) -> int:
    """Whole-book rough pass — loads only the rough model. Returns failed-chunk count."""
    completed = sum(1 for c in chunks if _rough_done(c))
    failed = 0
    update_job(job_id, current_stage="rough_translating", total_chunks=len(chunks), completed_chunks=completed)

    prev_tail = ""
    for chunk in chunks:
        if _rough_done(chunk):
            if chunk.text_blocks:
                prev_tail = tail_sentences(chunk.text_blocks[-1].rough_text or "")
            continue
        try:
            parts, glossary_updates, prev_tail = await rough_translate_chunk(
                chunk, source_lang, glossary, prev_tail
            )
            for block, rough in zip(chunk.text_blocks, parts):
                block.rough_text = rough
            if glossary_updates:
                glossary.update(glossary_updates)
                _save_glossary(glossary_path, glossary)
            completed += 1
        except Exception as exc:
            logger.exception("Rough pass, chunk %d failed: %s", chunk.index, exc)
            for block in chunk.text_blocks:
                block.translation_error = True
            failed += 1
        structure.save(structure_path)
        update_job(job_id, completed_chunks=completed, failed_chunks=failed)
    return failed


async def _run_polish_phase(
    job_id: str, chunks: list[Chunk], source_lang: str, glossary: dict[str, str],
    structure: BookStructure, structure_path: Path,
) -> int:
    """Whole-book polish pass — loads only the polish model. Returns failed-chunk count."""
    # Only polish chunks whose rough pass actually succeeded.
    polishable = [c for c in chunks if _rough_done(c)]
    completed = sum(1 for c in polishable if _polish_done(c))
    failed = 0
    update_job(job_id, current_stage="polishing", total_chunks=len(polishable), completed_chunks=completed)

    prev_tail = ""
    for chunk in polishable:
        if _polish_done(chunk):
            if chunk.text_blocks:
                prev_tail = tail_sentences(chunk.text_blocks[-1].translated_text or "")
            continue
        try:
            parts, prev_tail = await polish_chunk(chunk, source_lang, glossary, prev_tail)
            for block, translated in zip(chunk.text_blocks, parts):
                block.translated_text = translated
                block.translation_error = False
            completed += 1
        except Exception as exc:
            logger.exception("Polish pass, chunk %d failed: %s", chunk.index, exc)
            for block in chunk.text_blocks:
                block.translation_error = True
            failed += 1
        structure.save(structure_path)
        update_job(job_id, completed_chunks=completed, failed_chunks=failed)
    return failed


async def run_translation_job(job_id: str, book_id: str, source_lang: str) -> None:
    book_dir = BOOKS_DIR / book_id
    structure_path = book_dir / "structure.json"
    glossary_path = book_dir / "glossary.json"

    try:
        update_job(job_id, status="running", current_stage="extracting")
        update_book(book_id, status="translating")

        if structure_path.exists():
            structure = BookStructure.load(structure_path)
        else:
            structure = await asyncio.to_thread(extract_book, book_id, source_lang, book_dir)
            update_book(book_id, page_count=structure.page_count)

        chunks = build_chunks(structure.blocks)
        glossary = _load_glossary(glossary_path)

        # Two whole-book passes so each model is loaded once instead of alternating
        # every chunk — much lighter on machines that can't keep both models warm.
        rough_failed = await _run_rough_phase(
            job_id, chunks, source_lang, glossary, structure, structure_path, glossary_path
        )
        polish_failed = await _run_polish_phase(
            job_id, chunks, source_lang, glossary, structure, structure_path
        )
        failed = rough_failed + polish_failed

        update_job(job_id, current_stage="assembling_html")
        try:
            from app.rendering.html_render import render_book

            await asyncio.to_thread(render_book, book_id)
        except ImportError:
            logger.warning("html_render not implemented yet, skipping HTML assembly")

        if failed:
            update_job(job_id, status="done", current_stage="done",
                       error_message=f"{failed} chunk(s) failed; use retry-failed")
            update_book(book_id, status="error")
        else:
            update_job(job_id, status="done", current_stage="done")
            update_book(book_id, status="done")
    except asyncio.CancelledError:
        update_job(job_id, status="cancelled")
        update_book(book_id, status="error")
        raise
    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        update_job(job_id, status="error", error_message=str(exc)[:500])
        update_book(book_id, status="error")
    finally:
        RUNNING_JOBS.pop(job_id, None)


def start_job(job_id: str, book_id: str, source_lang: str) -> None:
    task = asyncio.create_task(run_translation_job(job_id, book_id, source_lang))
    RUNNING_JOBS[job_id] = task


def has_running_job_for_book(book_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE book_id = ? AND status IN ('queued', 'running')",
            (book_id,),
        ).fetchone()
    return row["n"] > 0
