"""Tests for the RAG retrieval module: chunk selection, index build, and
cosine-similarity ranking — all with Ollama's embed() mocked."""

from pathlib import Path

import pytest

from app.models.book_structure import BookStructure
from app.pipeline import rag
from tests.conftest import make_block


def _structure(blocks) -> BookStructure:
    return BookStructure(book_id="b1", source_lang="en", page_count=1, blocks=blocks)


def test_chunk_texts_for_retrieval_skips_untranslated_and_passthrough_blocks():
    blocks = [
        make_block(0, text="Translated one.", translated_text="Đã dịch một."),
        make_block(1, text="Not translated yet.", translated_text=None),
        make_block(2, type_="code", text="print(1)", translated_text="print(1)"),
        make_block(3, text="Translated two.", translated_text="Đã dịch hai."),
    ]
    entries = rag.chunk_texts_for_retrieval(_structure(blocks))

    texts = [e["text"] for e in entries]
    assert any("Đã dịch một." in t for t in texts)
    assert any("Đã dịch hai." in t for t in texts)
    assert not any("print(1)" in t for t in texts)
    joined = " ".join(texts)
    assert "Not translated yet" not in joined


def test_chunk_texts_for_retrieval_keeps_page_number():
    blocks = [make_block(0, text="Src", translated_text="Dịch", page=7)]
    entries = rag.chunk_texts_for_retrieval(_structure(blocks))
    assert entries[0]["page"] == 7


async def test_build_index_writes_matching_index_and_matrix(tmp_path, monkeypatch, fake_embed):
    book_dir = tmp_path / "book1"
    book_dir.mkdir()
    monkeypatch.setattr(rag, "BOOKS_DIR", tmp_path)
    blocks = [
        # Both tiny — well under the 500-token retrieval budget, so build_chunks
        # correctly merges them into a single chunk (1 embedding), not 2.
        make_block(0, text="A", translated_text="Đoạn một."),
        make_block(1, text="B", translated_text="Đoạn hai."),
    ]
    _structure(blocks).save(book_dir / "structure.json")

    count = await rag.build_index("book1")

    assert count == 1
    assert (book_dir / rag.INDEX_FILENAME).exists()
    assert (book_dir / rag.EMBEDDINGS_FILENAME).exists()
    indexed, chunk_count = rag.index_status("book1")
    assert indexed is True
    assert chunk_count == 1


async def test_build_index_handles_book_with_nothing_translated(tmp_path, monkeypatch, fake_embed):
    book_dir = tmp_path / "book2"
    book_dir.mkdir()
    monkeypatch.setattr(rag, "BOOKS_DIR", tmp_path)
    blocks = [make_block(0, type_="image", text="", translated_text="")]
    _structure(blocks).save(book_dir / "structure.json")

    count = await rag.build_index("book2")

    assert count == 0
    indexed, chunk_count = rag.index_status("book2")
    assert indexed is True  # index exists, just empty — distinct from "never indexed"
    assert chunk_count == 0


def test_index_status_when_never_indexed(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "BOOKS_DIR", tmp_path)
    (tmp_path / "book3").mkdir()
    indexed, chunk_count = rag.index_status("book3")
    assert indexed is False
    assert chunk_count == 0


async def test_retrieve_ranks_by_similarity_and_filters_low_scores(tmp_path, monkeypatch, fake_embed):
    book_dir = tmp_path / "book4"
    book_dir.mkdir()
    monkeypatch.setattr(rag, "BOOKS_DIR", tmp_path)
    # Pad well past the 500-token retrieval budget so each topic lands in its
    # own chunk instead of being merged with the other by build_chunks.
    # Chunk sizing is based on Block.text (original language), not
    # translated_text — pad both fields, matching how a real block would have
    # proportional lengths in both languages.
    cat_text = "Nói về con mèo. " + "Con mèo rất dễ thương. " * 150
    chair_text = "Nói về cái ghế. " + "Cái ghế làm bằng gỗ. " * 150
    blocks = [
        make_block(0, text=cat_text, translated_text=cat_text),
        make_block(1, text=chair_text, translated_text=chair_text),
    ]
    _structure(blocks).save(book_dir / "structure.json")

    fake_embed.set_vector(cat_text, [1.0, 0.0, 0.0])
    fake_embed.set_vector(chair_text, [0.0, 1.0, 0.0])
    count = await rag.build_index("book4")
    assert count == 2  # confirms the padding actually forced two separate chunks

    fake_embed.set_vector("con mèo là gì?", [1.0, 0.0, 0.0])
    results = await rag.retrieve("book4", "con mèo là gì?", top_k=5, min_similarity=0.3)

    assert len(results) == 1
    assert "con mèo" in results[0].text
    assert results[0].similarity == pytest.approx(1.0, abs=1e-4)


async def test_retrieve_on_empty_index_returns_nothing(tmp_path, monkeypatch, fake_embed):
    book_dir = tmp_path / "book5"
    book_dir.mkdir()
    monkeypatch.setattr(rag, "BOOKS_DIR", tmp_path)
    blocks = [make_block(0, type_="image", text="", translated_text="")]
    _structure(blocks).save(book_dir / "structure.json")
    await rag.build_index("book5")

    results = await rag.retrieve("book5", "bất kỳ câu hỏi nào")
    assert results == []


async def test_stream_answer_question_grounds_prompt_and_saves_history(
    tmp_path, monkeypatch, fake_embed, fake_ollama
):
    book_dir = tmp_path / "book6"
    book_dir.mkdir()
    monkeypatch.setattr(rag, "BOOKS_DIR", tmp_path)
    blocks = [make_block(0, text="Src", translated_text="Elena tìm thấy phòng thí nghiệm.", page=3)]
    _structure(blocks).save(book_dir / "structure.json")
    await rag.build_index("book6")

    fake_ollama.queue("Elena đã tìm thấy phòng thí nghiệm.")
    tokens = [t async for t in rag.stream_answer_question("book6", "Elena tìm thấy gì?", "Tiếng Việt")]

    assert "".join(tokens) == "Elena đã tìm thấy phòng thí nghiệm."
    assert len(tokens) > 1  # actually streamed in pieces, not one giant chunk

    call = fake_ollama.calls[0]
    assert call["model"] == rag.CHAT_MODEL
    assert call["num_ctx"] == rag.CHAT_NUM_CTX
    system_msg = call["messages"][0]
    assert system_msg["role"] == "system"
    assert "Elena tìm thấy phòng thí nghiệm." in system_msg["content"]
    assert call["messages"][-1] == {"role": "user", "content": "Elena tìm thấy gì?"}

    history = rag.load_chat_history("book6")
    assert [h["role"] for h in history] == ["user", "assistant"]
    assert history[1]["content"] == "Elena đã tìm thấy phòng thí nghiệm."


async def test_stream_answer_question_tells_model_when_nothing_relevant_found(
    tmp_path, monkeypatch, fake_embed, fake_ollama
):
    book_dir = tmp_path / "book7"
    book_dir.mkdir()
    monkeypatch.setattr(rag, "BOOKS_DIR", tmp_path)
    blocks = [make_block(0, text="Src", translated_text="Nội dung không liên quan.")]
    _structure(blocks).save(book_dir / "structure.json")
    await rag.build_index("book7")

    # Force the query vector to be orthogonal to the indexed chunk so it's
    # filtered out by the default min_similarity threshold.
    fake_embed.set_vector("Nội dung không liên quan.", [1.0, 0.0, 0.0])
    fake_embed.set_vector("câu hỏi lạc đề", [0.0, 1.0, 0.0])

    fake_ollama.queue("Không tìm thấy trong sách.")
    tokens = [t async for t in rag.stream_answer_question("book7", "câu hỏi lạc đề", "Tiếng Việt")]

    assert "".join(tokens) == "Không tìm thấy trong sách."
    system_msg = fake_ollama.calls[0]["messages"][0]
    assert "No excerpt relevant to this question was found" in system_msg["content"]
    assert "Tiếng Việt" in system_msg["content"]
