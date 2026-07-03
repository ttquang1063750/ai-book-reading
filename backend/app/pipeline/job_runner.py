"""Background translation job: extraction → chunked hybrid translation → HTML."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import BOOKS_DIR
from app.db import get_connection, update_book, update_job
from app.ingestion.structure import extract_book
from app.models.book_structure import Block, BookStructure
from app.pipeline import rag
from app.pipeline.chunking import Chunk, build_chunks
from app.pipeline.summarize import split_into_chapters, summarize_chapter
from app.pipeline.translate import detect_source_language, polish_chunk, rough_translate_chunk, tail_sentences
from app.rendering.html_render import render_book

logger = logging.getLogger(__name__)

# job_id -> asyncio.Task, for status introspection and future cancellation
RUNNING_JOBS: dict[str, asyncio.Task] = {}

# book_id -> lock, serializing "check no job is running, then create one" so two
# near-simultaneous requests for the same book can't both pass the check.
_BOOK_LOCKS: dict[str, asyncio.Lock] = {}


def get_book_lock(book_id: str) -> asyncio.Lock:
    lock = _BOOK_LOCKS.get(book_id)
    if lock is None:
        lock = _BOOK_LOCKS[book_id] = asyncio.Lock()
    return lock


def _load_glossary(path: Path) -> dict[str, str]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_glossary(path: Path, glossary: dict[str, str]) -> None:
    path.write_text(json.dumps(glossary, ensure_ascii=False, indent=1), encoding="utf-8")


async def _get_or_detect_source_lang(book_id: str, structure: BookStructure, structure_path: Path) -> str:
    """Detect once and cache — a retry or re-translate reuses the value already
    stored on the book/structure instead of asking the model again."""
    if structure.source_lang:
        return structure.source_lang

    sample = "\n".join(
        b.text for b in structure.blocks if b.type in ("heading", "paragraph", "verse") and b.text.strip()
    )
    detected = await detect_source_language(sample[:1000])
    structure.source_lang = detected
    structure.save(structure_path)
    update_book(book_id, source_lang=detected)
    return detected


def _rough_done(chunk: Chunk) -> bool:
    return all(b.rough_text is not None for b in chunk.text_blocks)


def _polish_done(chunk: Chunk) -> bool:
    return all(b.translated_text is not None for b in chunk.text_blocks)


async def _run_rough_phase(
    job_id: str, chunks: list[Chunk], source_lang: str, target_lang: str, glossary: dict[str, str],
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
                chunk, source_lang, target_lang, glossary, prev_tail
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
    job_id: str, chunks: list[Chunk], source_lang: str, target_lang: str, glossary: dict[str, str],
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
            parts, prev_tail = await polish_chunk(chunk, source_lang, target_lang, glossary, prev_tail)
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


async def run_translation_job(job_id: str, book_id: str, target_lang: str) -> None:
    book_dir = BOOKS_DIR / book_id
    structure_path = book_dir / "structure.json"
    glossary_path = book_dir / "glossary.json"

    try:
        update_job(job_id, status="running", current_stage="extracting")
        update_book(book_id, status="translating")

        if structure_path.exists():
            structure = BookStructure.load(structure_path)
        else:
            # Source language isn't known yet — detected right after extraction,
            # from the text that extraction itself just produced.
            structure = await asyncio.to_thread(extract_book, book_id, "", book_dir)
            update_book(book_id, page_count=structure.page_count)

        source_lang = await _get_or_detect_source_lang(book_id, structure, structure_path)

        chunks = build_chunks(structure.blocks)
        glossary = _load_glossary(glossary_path)

        # Two whole-book passes so each model is loaded once instead of alternating
        # every chunk — much lighter on machines that can't keep both models warm.
        rough_failed = await _run_rough_phase(
            job_id, chunks, source_lang, target_lang, glossary, structure, structure_path, glossary_path
        )
        polish_failed = await _run_polish_phase(
            job_id, chunks, source_lang, target_lang, glossary, structure, structure_path
        )
        failed = rough_failed + polish_failed

        update_job(job_id, current_stage="assembling_html")
        await asyncio.to_thread(render_book, book_id)

        if failed:
            update_job(job_id, status="done", current_stage="done",
                       error_message=f"{failed} chunk(s) failed; use retry-failed")
            update_book(book_id, status="error")
        else:
            update_job(job_id, status="done", current_stage="done")
            update_book(book_id, status="done")
            _auto_start_index(book_id)
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


def _load_summaries(path: Path) -> dict[str, dict]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_summaries(path: Path, summaries: dict[str, dict]) -> None:
    path.write_text(json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8")


async def run_summarize_job(job_id: str, book_id: str, target_lang: str) -> None:
    book_dir = BOOKS_DIR / book_id
    structure_path = book_dir / "structure.json"
    summaries_path = book_dir / "summaries.json"

    try:
        update_job(job_id, status="running", current_stage="summarizing")

        if not structure_path.exists():
            raise RuntimeError("Book has not been translated yet")
        structure = BookStructure.load(structure_path)
        with get_connection() as conn:
            row = conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
        title = row["title"] if row else book_id

        chapters = split_into_chapters(structure.blocks, title)
        summaries = _load_summaries(summaries_path)
        completed = sum(1 for c in chapters if str(c.heading_block_id) in summaries)
        failed = 0
        update_job(job_id, total_chunks=len(chapters), completed_chunks=completed)

        for chapter in chapters:
            key = str(chapter.heading_block_id)
            if key in summaries:
                continue
            try:
                summary = await summarize_chapter(chapter, target_lang)
                summaries[key] = {"title": chapter.title, "summary": summary}
                completed += 1
            except Exception as exc:
                logger.exception("Summary for chapter '%s' failed: %s", chapter.title, exc)
                failed += 1
            _save_summaries(summaries_path, summaries)
            update_job(job_id, completed_chunks=completed, failed_chunks=failed)

        if failed:
            update_job(job_id, status="done", current_stage="done",
                       error_message=f"{failed} chapter(s) failed to summarize")
        else:
            update_job(job_id, status="done", current_stage="done")
    except asyncio.CancelledError:
        update_job(job_id, status="cancelled")
        raise
    except Exception as exc:
        logger.exception("Summarize job %s failed: %s", job_id, exc)
        update_job(job_id, status="error", error_message=str(exc)[:500])
    finally:
        RUNNING_JOBS.pop(job_id, None)


async def run_index_job(job_id: str, book_id: str) -> None:
    """Build the embedding index for chat, in batches so progress is polled
    the same way as translate/summarize instead of one un-interruptible call."""
    book_dir = BOOKS_DIR / book_id
    structure_path = book_dir / "structure.json"

    try:
        update_job(job_id, status="running", current_stage="indexing")

        if not structure_path.exists():
            raise RuntimeError("Book has not been translated yet")
        structure = BookStructure.load(structure_path)
        entries = rag.chunk_texts_for_retrieval(structure)
        total = len(entries)
        update_job(job_id, total_chunks=total, completed_chunks=0)

        if total == 0:
            rag.save_index(book_id, [], [])
            update_job(job_id, status="done", current_stage="done")
            return

        vectors: list[list[float]] = []
        completed = 0
        for i in range(0, total, rag.EMBED_BATCH_SIZE):
            batch = entries[i : i + rag.EMBED_BATCH_SIZE]
            vectors.extend(await rag.embed_texts([e["text"] for e in batch]))
            completed += len(batch)
            update_job(job_id, completed_chunks=completed)

        rag.save_index(book_id, entries, vectors)
        update_job(job_id, status="done", current_stage="done")
    except asyncio.CancelledError:
        update_job(job_id, status="cancelled")
        raise
    except Exception as exc:
        logger.exception("Index job %s failed: %s", job_id, exc)
        update_job(job_id, status="error", error_message=str(exc)[:500])
    finally:
        RUNNING_JOBS.pop(job_id, None)


RETRANSLATABLE_BLOCK_TYPES = ("heading", "paragraph", "verse")


async def retranslate_block(book_id: str, block_id: int) -> Block:
    """Re-translate a single block in isolation — no chunk-mates, no continuity
    context — for the reader's per-block "Dịch lại" button, fixing one paragraph
    that came out wrong without re-running the whole book. Fast enough (one rough
    + up to a few polish calls) to run synchronously rather than as a tracked job."""
    book_dir = BOOKS_DIR / book_id
    structure_path = book_dir / "structure.json"
    if not structure_path.exists():
        raise FileNotFoundError("Book has not been translated yet")
    structure = BookStructure.load(structure_path)
    block = next((b for b in structure.blocks if b.id == block_id), None)
    if block is None:
        raise KeyError(f"Block {block_id} not found")
    if block.type not in RETRANSLATABLE_BLOCK_TYPES:
        raise ValueError(f"Block type '{block.type}' cannot be retranslated")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT source_lang, target_lang FROM books WHERE id = ?", (book_id,)
        ).fetchone()
    source_lang, target_lang = row["source_lang"], row["target_lang"]
    glossary_path = book_dir / "glossary.json"
    glossary = _load_glossary(glossary_path)

    chunk = Chunk(index=0, blocks=[block])
    try:
        rough_parts, glossary_updates, _tail = await rough_translate_chunk(
            chunk, source_lang, target_lang, glossary, ""
        )
        block.rough_text = rough_parts[0]
        if glossary_updates:
            glossary.update(glossary_updates)
            _save_glossary(glossary_path, glossary)

        polished_parts, _tail2 = await polish_chunk(chunk, source_lang, target_lang, glossary, "")
        block.translated_text = polished_parts[0]
        block.translation_error = False
    except Exception:
        block.translation_error = True
        raise
    finally:
        structure.save(structure_path)

    await asyncio.to_thread(render_book, book_id)
    return block


def start_job(job_id: str, book_id: str, target_lang: str) -> None:
    task = asyncio.create_task(run_translation_job(job_id, book_id, target_lang))
    RUNNING_JOBS[job_id] = task


def start_summarize_job(job_id: str, book_id: str, target_lang: str) -> None:
    task = asyncio.create_task(run_summarize_job(job_id, book_id, target_lang))
    RUNNING_JOBS[job_id] = task


def start_index_job(job_id: str, book_id: str) -> None:
    task = asyncio.create_task(run_index_job(job_id, book_id))
    RUNNING_JOBS[job_id] = task


def _auto_start_index(book_id: str) -> None:
    """Chain an index job right after a translation completes successfully,
    the same way HTML assembly is chained — chat should just work without a
    separate manual step. Fire-and-forget: any failure here shouldn't affect
    the translation job that just succeeded, only get logged."""
    try:
        job_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO jobs (id, book_id, job_type, status, created_at, updated_at)"
                " VALUES (?, ?, 'index', 'queued', ?, ?)",
                (job_id, book_id, now, now),
            )
        start_index_job(job_id, book_id)
    except Exception:
        logger.exception("Auto-index after translation failed to start for book %s", book_id)


def cancel_job(job_id: str) -> bool:
    """Cancel a running job's asyncio.Task. Returns False if it wasn't running
    (already finished, or the process restarted since it was started)."""
    task = RUNNING_JOBS.get(job_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def has_running_job_for_book(book_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE book_id = ? AND status IN ('queued', 'running')",
            (book_id,),
        ).fetchone()
    return row["n"] > 0
