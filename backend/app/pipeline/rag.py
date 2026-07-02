"""Embedding-based retrieval over a book's translated text — powers the chat feature.

No vector DB: a book has at most a few thousand chunks, so brute-force cosine
similarity over a NumPy matrix is microseconds — an ANN index would be
over-engineering here.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.config import BOOKS_DIR, POLISH_MODEL
from app.models.book_structure import BookStructure
from app.pipeline import ollama_client
from app.pipeline.chunking import build_chunks

EMBED_MODEL = "bge-m3"
# Reuse the polish model — it's already the "good writer" model and is loaded
# on demand like every other Ollama call here, no extra RAM footprint decision.
CHAT_MODEL = POLISH_MODEL
# Smaller than the 1800-token translation budget — that size is tuned for
# rough/polish prompt context, not retrieval granularity. Coarser chunks here
# would dilute relevance (more irrelevant text riding along with the answer).
RETRIEVAL_CHUNK_TOKEN_BUDGET = 500
EMBED_BATCH_SIZE = 20
CHAT_NUM_CTX = 8192
# Lower than Ollama's model default (~0.7-0.8) — qwen2.5 occasionally
# code-switches into Chinese mid-answer at default temperature, especially
# on off-topic questions with no retrieved context to anchor generation.
CHAT_TEMPERATURE = 0.2
CHAT_HISTORY_TURNS = 6  # most recent user+assistant messages sent as context

EMBEDDINGS_FILENAME = "embeddings.npy"
INDEX_FILENAME = "chunks_index.json"
CHAT_HISTORY_FILENAME = "chat_history.json"

def _chat_system_prompt(target_lang: str) -> str:
    return (
        "You are an assistant answering questions about a book's content, based only on the "
        f"excerpts provided below (already translated into {target_lang}). "
        "You may ONLY answer based on these excerpts — you must NEVER use outside knowledge, "
        "even if you know the real answer. If the information is not in the excerpts, just say "
        "so and stop there — do not add anything else. "
        f"Answer entirely in {target_lang}, concise and natural."
    )


@dataclass
class RetrievedChunk:
    text: str
    page: int
    similarity: float


def _index_paths(book_id: str) -> tuple[Path, Path]:
    book_dir = BOOKS_DIR / book_id
    return book_dir / EMBEDDINGS_FILENAME, book_dir / INDEX_FILENAME


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed texts, several per Ollama call rather than one-at-a-time."""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        vectors.extend(await ollama_client.embed(EMBED_MODEL, batch))
    return vectors


def chunk_texts_for_retrieval(structure: BookStructure) -> list[dict]:
    """Build small (~500-token) chunks from *translated* text for embedding.
    Each entry keeps a page number for citation. Chunks with no translation
    yet (or code/image passthrough blocks) are skipped."""
    chunks = build_chunks(structure.blocks, token_budget=RETRIEVAL_CHUNK_TOKEN_BUDGET)
    entries = []
    for chunk in chunks:
        text_blocks = [b for b in chunk.text_blocks if b.translated_text]
        if not text_blocks:
            continue
        text = "\n\n".join(b.translated_text for b in text_blocks)
        if not text.strip():
            continue
        entries.append({"text": text, "page": text_blocks[0].page})
    return entries


def save_index(book_id: str, entries: list[dict], vectors: list[list[float]]) -> None:
    """Persist an already-embedded index. Split out from build_index() so
    job_runner can call this once after embedding in progress-reporting
    batches, instead of one big un-interruptible embed_texts() call."""
    emb_path, idx_path = _index_paths(book_id)
    matrix = np.array(vectors, dtype="float32") if vectors else np.zeros((0, 0), dtype="float32")
    # Write the index first — a crash mid-write should never leave the .npy
    # referencing rows the index doesn't describe (index is the source of
    # truth for row count; a stale-but-consistent pair beats a mismatched one).
    idx_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(emb_path, matrix)


async def build_index(book_id: str) -> int:
    """(Re)build the embedding index for a book from its current translated
    text in one shot. Returns the number of indexed chunks (0 if nothing to
    index). Convenience wrapper with no progress reporting — job_runner's
    run_index_job does the same steps in batches for a real progress bar."""
    book_dir = BOOKS_DIR / book_id
    structure = BookStructure.load(book_dir / "structure.json")
    entries = chunk_texts_for_retrieval(structure)
    if not entries:
        save_index(book_id, [], [])
        return 0
    vectors = await embed_texts([e["text"] for e in entries])
    save_index(book_id, entries, vectors)
    return len(entries)


def index_status(book_id: str) -> tuple[bool, int]:
    """(indexed, chunk_count) — cheap check, doesn't load the embedding matrix."""
    emb_path, idx_path = _index_paths(book_id)
    if not idx_path.exists() or not emb_path.exists():
        return False, 0
    entries = json.loads(idx_path.read_text(encoding="utf-8"))
    return True, len(entries)


def _load_index(book_id: str) -> tuple[np.ndarray, list[dict]]:
    emb_path, idx_path = _index_paths(book_id)
    entries = json.loads(idx_path.read_text(encoding="utf-8"))
    matrix = np.load(emb_path)
    return matrix, entries


async def retrieve(
    book_id: str, query: str, top_k: int = 5, min_similarity: float = 0.3
) -> list[RetrievedChunk]:
    """Embed the query, return the top-K most similar indexed chunks — chunks
    below min_similarity are dropped rather than handed to the LLM as noise
    (cosine similarity always returns *something*, even for off-topic questions)."""
    matrix, entries = _load_index(book_id)
    if matrix.shape[0] == 0:
        return []

    query_vec = (await embed_texts([query]))[0]
    query_arr = np.array(query_vec, dtype="float32")

    matrix_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8)
    query_norm = query_arr / (np.linalg.norm(query_arr) + 1e-8)
    similarities = matrix_norm @ query_norm

    top_indices = np.argsort(-similarities)[:top_k]
    results = []
    for i in top_indices:
        sim = float(similarities[i])
        if sim < min_similarity:
            continue
        entry = entries[int(i)]
        results.append(RetrievedChunk(text=entry["text"], page=entry["page"], similarity=sim))
    return results


def _history_path(book_id: str) -> Path:
    return BOOKS_DIR / book_id / CHAT_HISTORY_FILENAME


def load_chat_history(book_id: str) -> list[dict]:
    path = _history_path(book_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_chat_history(book_id: str, history: list[dict]) -> None:
    _history_path(book_id).write_text(
        json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def clear_chat_history(book_id: str) -> None:
    path = _history_path(book_id)
    if path.exists():
        path.unlink()


def _build_chat_messages(
    history: list[dict], question: str, retrieved: list[RetrievedChunk], target_lang: str
) -> list[dict]:
    system_prompt = _chat_system_prompt(target_lang)
    if retrieved:
        context = "\n\n---\n\n".join(
            f"[Page {c.page}]\n{c.text}" for c in retrieved
        )
        system_content = f"{system_prompt}\n\n### Excerpts from the book:\n\n{context}"
    else:
        system_content = (
            f"{system_prompt}\n\n"
            "No excerpt relevant to this question was found in the book. The ONLY thing you "
            f"may do is state, in {target_lang}, that this question has no relevant information "
            "in the book, and stop there — do not add anything else."
        )
    messages = [{"role": "system", "content": system_content}]
    recent = history[-2 * CHAT_HISTORY_TURNS :]
    for turn in recent:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})
    return messages


async def stream_answer_question(book_id: str, question: str, target_lang: str) -> AsyncIterator[str]:
    """Same as answer_question(), but yields the answer token-by-token and
    only persists history once the stream completes (a client disconnecting
    mid-stream should not save a half answer)."""
    history = load_chat_history(book_id)
    retrieved = await retrieve(book_id, question)
    messages = _build_chat_messages(history, question, retrieved, target_lang)

    chunks: list[str] = []
    async for token in ollama_client.chat_stream(
        CHAT_MODEL, messages, num_ctx=CHAT_NUM_CTX, temperature=CHAT_TEMPERATURE
    ):
        chunks.append(token)
        yield token

    answer = "".join(chunks)
    now = datetime.now(timezone.utc).isoformat()
    history.append({"role": "user", "content": question, "timestamp": now})
    history.append({"role": "assistant", "content": answer, "timestamp": now})
    save_chat_history(book_id, history)
