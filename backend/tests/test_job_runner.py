"""Tests for the two-phase job orchestration in job_runner.py: resume logic,
rough-before-polish ordering, and excluding rough-failed chunks from polish.

Ollama itself is never involved — job_runner.rough_translate_chunk/polish_chunk
are monkeypatched with fakes, and DB writes (update_job/update_book) are stubbed
out so these tests don't touch app.db at all.
"""

import pytest

from app.models.book_structure import BookStructure
from app.pipeline import job_runner
from app.pipeline.chunking import build_chunks
from tests.conftest import make_block


@pytest.fixture(autouse=True)
def stub_db_writes(monkeypatch):
    """job_runner.update_job/update_book hit real SQLite; no-op them for these tests."""
    monkeypatch.setattr(job_runner, "update_job", lambda *a, **kw: None)
    monkeypatch.setattr(job_runner, "update_book", lambda *a, **kw: None)


@pytest.fixture
def call_log():
    return []


@pytest.fixture
def fake_rough(monkeypatch, call_log):
    async def _fake(chunk, source_lang, target_lang, glossary, prev_tail):
        call_log.append(("rough", chunk.index))
        parts = [f"rough:{b.text}" for b in chunk.text_blocks]
        return parts, {}, "rough-tail"

    monkeypatch.setattr(job_runner, "rough_translate_chunk", _fake)
    return _fake


@pytest.fixture
def fake_polish(monkeypatch, call_log):
    async def _fake(chunk, source_lang, target_lang, glossary, prev_tail):
        call_log.append(("polish", chunk.index))
        parts = [f"polish:{b.rough_text}" for b in chunk.text_blocks]
        return parts, "polish-tail"

    monkeypatch.setattr(job_runner, "polish_chunk", _fake)
    return _fake


def _structure_with_blocks(n: int) -> BookStructure:
    blocks = [make_block(i, text=f"Source paragraph {i}.") for i in range(n)]
    return BookStructure(book_id="b1", source_lang="en", page_count=1, blocks=blocks)


async def test_rough_phase_skips_already_done_chunks(tmp_path, fake_rough, call_log):
    structure = _structure_with_blocks(3)
    structure.blocks[0].rough_text = "already done"  # chunk 0 pre-completed

    chunks = build_chunks(structure.blocks, token_budget=1)  # 1 block per chunk
    failed = await job_runner._run_rough_phase(
        "job1", chunks, "en", "Tiếng Việt", {}, structure, tmp_path / "structure.json", tmp_path / "glossary.json"
    )

    assert failed == 0
    assert call_log == [("rough", 1), ("rough", 2)]  # chunk 0 skipped


async def test_polish_phase_skips_already_done_chunks(tmp_path, fake_polish, call_log):
    structure = _structure_with_blocks(3)
    for b in structure.blocks:
        b.rough_text = f"rough:{b.text}"
    structure.blocks[0].translated_text = "already polished"  # chunk 0 pre-completed

    chunks = build_chunks(structure.blocks, token_budget=1)
    failed = await job_runner._run_polish_phase(
        "job1", chunks, "en", "Tiếng Việt", {}, structure, tmp_path / "structure.json"
    )

    assert failed == 0
    assert call_log == [("polish", 1), ("polish", 2)]


async def test_rough_phase_fully_precedes_polish_phase(tmp_path, fake_rough, fake_polish, call_log):
    structure = _structure_with_blocks(3)
    chunks = build_chunks(structure.blocks, token_budget=1)

    await job_runner._run_rough_phase(
        "job1", chunks, "en", "Tiếng Việt", {}, structure, tmp_path / "structure.json", tmp_path / "glossary.json"
    )
    await job_runner._run_polish_phase(
        "job1", chunks, "en", "Tiếng Việt", {}, structure, tmp_path / "structure.json"
    )

    rough_calls = [i for kind, i in call_log if kind == "rough"]
    polish_calls = [i for kind, i in call_log if kind == "polish"]
    assert len(rough_calls) == 3
    assert len(polish_calls) == 3
    # Every rough call happened before every polish call.
    last_rough_index = max(idx for idx, (kind, _) in enumerate(call_log) if kind == "rough")
    first_polish_index = min(idx for idx, (kind, _) in enumerate(call_log) if kind == "polish")
    assert last_rough_index < first_polish_index


async def test_rough_failure_excludes_chunk_from_polish_phase(tmp_path, monkeypatch, call_log, fake_polish):
    structure = _structure_with_blocks(2)
    chunks = build_chunks(structure.blocks, token_budget=1)

    async def _flaky_rough(chunk, source_lang, target_lang, glossary, prev_tail):
        if chunk.index == 0:
            raise RuntimeError("simulated Ollama failure")
        call_log.append(("rough", chunk.index))
        return [f"rough:{b.text}" for b in chunk.text_blocks], {}, "tail"

    monkeypatch.setattr(job_runner, "rough_translate_chunk", _flaky_rough)

    rough_failed = await job_runner._run_rough_phase(
        "job1", chunks, "en", "Tiếng Việt", {}, structure, tmp_path / "structure.json", tmp_path / "glossary.json"
    )
    assert rough_failed == 1
    assert structure.blocks[0].translation_error is True

    polish_failed = await job_runner._run_polish_phase(
        "job1", chunks, "en", "Tiếng Việt", {}, structure, tmp_path / "structure.json"
    )
    assert polish_failed == 0
    # Chunk 0 (rough-failed) must never reach the polish model.
    assert ("polish", 0) not in call_log
    assert call_log == [("rough", 1), ("polish", 1)]


class _FakeConn:
    """Records executed SQL instead of touching real sqlite."""

    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_auto_start_index_inserts_index_job_and_starts_it(monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(job_runner, "get_connection", lambda: fake_conn)
    started = []
    monkeypatch.setattr(job_runner, "start_index_job", lambda job_id, book_id: started.append((job_id, book_id)))

    job_runner._auto_start_index("book1")

    assert len(fake_conn.executed) == 1
    sql, params = fake_conn.executed[0]
    assert "INSERT INTO jobs" in sql
    assert "'index'" in sql
    book_id, job_id = params[1], params[0]
    assert book_id == "book1"
    assert started == [(job_id, "book1")]


def test_auto_start_index_swallows_errors(monkeypatch):
    def _boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(job_runner, "get_connection", _boom)

    job_runner._auto_start_index("book1")  # must not raise


async def test_get_or_detect_source_lang_detects_and_persists_when_unknown(tmp_path, monkeypatch):
    structure = _structure_with_blocks(2)
    structure.source_lang = ""  # not yet detected
    structure_path = tmp_path / "structure.json"

    detect_calls = []

    async def _fake_detect(sample):
        detect_calls.append(sample)
        return "Tiếng Anh"

    monkeypatch.setattr(job_runner, "detect_source_language", _fake_detect)
    updated_books = []
    monkeypatch.setattr(job_runner, "update_book", lambda book_id, **kw: updated_books.append((book_id, kw)))

    result = await job_runner._get_or_detect_source_lang("book1", structure, structure_path)

    assert result == "Tiếng Anh"
    assert structure.source_lang == "Tiếng Anh"
    assert BookStructure.load(structure_path).source_lang == "Tiếng Anh"
    assert updated_books == [("book1", {"source_lang": "Tiếng Anh"})]
    assert len(detect_calls) == 1


async def test_get_or_detect_source_lang_reuses_already_known_value(tmp_path, monkeypatch):
    structure = _structure_with_blocks(2)
    structure.source_lang = "Tiếng Pháp"  # already detected in a previous run
    structure_path = tmp_path / "structure.json"

    async def _fail_if_called(sample):
        raise AssertionError("should not re-detect when already known")

    monkeypatch.setattr(job_runner, "detect_source_language", _fail_if_called)
    monkeypatch.setattr(job_runner, "update_book", lambda *a, **kw: pytest.fail("should not update_book"))

    result = await job_runner._get_or_detect_source_lang("book1", structure, structure_path)

    assert result == "Tiếng Pháp"
