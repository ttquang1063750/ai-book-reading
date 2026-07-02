"""Per-chunk translation: rough pass, glossary extraction, literary polish."""

import json
import logging
import re

from app.config import POLISH_MODEL, ROUGH_MODEL
from app.pipeline import ollama_client
from app.pipeline.chunking import Chunk

logger = logging.getLogger(__name__)

LANG_NAMES = {"en": "English", "fr": "French"}

PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def split_paragraphs(text: str, expected: int) -> list[str] | None:
    parts = [p.strip() for p in PARAGRAPH_SPLIT.split(text.strip()) if p.strip()]
    return parts if len(parts) == expected else None


async def rough_translate(chunk: Chunk, source_lang: str, prev_tail: str) -> str:
    lang = LANG_NAMES.get(source_lang, source_lang)
    n = len(chunk.text_blocks)
    system = (
        f"You are a professional literary translator. Translate the {lang} text into Vietnamese. "
        f"The input has {n} paragraphs separated by blank lines; output exactly {n} paragraphs "
        "separated by blank lines. Output only the translation, no commentary."
    )
    user = ""
    if prev_tail:
        user += f"Previously translated context (for continuity, do NOT re-translate):\n{prev_tail}\n\n"
    user += f"Text to translate:\n\n{chunk.source_text}"
    return await ollama_client.chat(
        ROUGH_MODEL,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
    )


# Capitalized word preceded by a lowercase word — i.e. mid-sentence, so likely a proper noun
MID_SENTENCE_CAPITALIZED = re.compile(r"[a-zà-þ,;]\s+([A-ZÀ-Þ][a-zà-þA-ZÀ-Þ'-]+)")


def new_capitalized_terms(source_text: str, glossary: dict[str, str]) -> set[str]:
    terms = set(MID_SENTENCE_CAPITALIZED.findall(source_text))
    return {t for t in terms if t not in glossary}


async def extract_glossary_terms(
    source_text: str, translated_text: str, glossary: dict[str, str]
) -> dict[str, str]:
    """Ask the rough model how proper nouns were rendered; first-seen-wins merge."""
    candidates = new_capitalized_terms(source_text, glossary)
    if not candidates:
        return {}
    prompt = (
        "Below is an original passage and its Vietnamese translation. For each proper noun "
        "(person, place, organization) in this list, give how it was rendered in the translation. "
        'Answer as strict JSON: {"terms": [{"source": "...", "translated": "..."}]}\n\n'
        f"Proper noun candidates: {sorted(candidates)}\n\n"
        f"Original:\n{source_text}\n\nTranslation:\n{translated_text}"
    )
    try:
        raw = await ollama_client.chat(
            ROUGH_MODEL, [{"role": "user", "content": prompt}], json_format=True, temperature=0.0
        )
        data = json.loads(raw)
        updates = {}
        for item in data.get("terms", []):
            src, dst = item.get("source"), item.get("translated")
            if src and dst and src not in glossary:
                updates[src] = dst
        return updates
    except (json.JSONDecodeError, AttributeError, TypeError, ollama_client.OllamaError) as exc:
        logger.warning("Glossary extraction failed, skipping: %s", exc)
        return {}


async def polish(
    chunk: Chunk, source_lang: str, rough_text: str, glossary: dict[str, str], prev_tail: str
) -> str:
    lang = LANG_NAMES.get(source_lang, source_lang)
    n = len(chunk.text_blocks)
    system = (
        "Bạn là một biên tập viên văn học tiếng Việt. Nhiệm vụ: viết lại bản dịch nháp thành văn xuôi "
        "tiếng Việt tự nhiên, trôi chảy, giữ đúng nghĩa so với nguyên bản. "
        f"Bản dịch có {n} đoạn văn phân cách bằng dòng trống; giữ nguyên đúng {n} đoạn. "
        "Chỉ xuất ra bản dịch đã chỉnh sửa, không thêm bình luận."
    )
    user = ""
    if glossary:
        pairs = "; ".join(f"{k} → {v}" for k, v in glossary.items())
        user += f"Dùng nhất quán các tên riêng/thuật ngữ sau: {pairs}\n\n"
    if prev_tail:
        user += f"Đoạn cuối của phần đã dịch trước đó (để nối mạch, KHÔNG dịch lại):\n{prev_tail}\n\n"
    user += (
        f"Nguyên bản ({lang}):\n{chunk.source_text}\n\n"
        f"Bản dịch nháp:\n{rough_text}\n\n"
        "Hãy viết lại bản dịch cho tự nhiên hơn."
    )
    return await ollama_client.chat(
        POLISH_MODEL,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.7,
    )


def tail_sentences(text: str, max_chars: int = 300) -> str:
    """Last ~1-2 sentences of a translated chunk, used as continuity context."""
    text = text.strip()
    return text[-max_chars:] if len(text) > max_chars else text


def _split_or_fallback(text: str, expected: int, fallback: str, label: str, chunk_index: int) -> list[str]:
    parts = split_paragraphs(text, expected)
    if parts is not None:
        return parts
    logger.warning("Chunk %d: %s output paragraph count mismatch, using fallback split", chunk_index, label)
    parts = split_paragraphs(fallback, expected)
    if parts is not None:
        return parts
    logger.warning("Chunk %d: fallback split also mismatched, merging into first block", chunk_index)
    return [text.strip()] + [""] * (expected - 1)


async def rough_translate_chunk(
    chunk: Chunk, source_lang: str, glossary: dict[str, str], prev_tail: str
) -> tuple[list[str], dict[str, str], str]:
    """Rough pass + glossary extraction for one chunk (rough model only).

    Returns (per-block rough translations, glossary updates, new rough-tail for the next chunk).
    """
    text_blocks = chunk.text_blocks
    rough = await rough_translate(chunk, source_lang, prev_tail)
    glossary_updates = await extract_glossary_terms(chunk.source_text, rough, glossary)

    parts = _split_or_fallback(rough, len(text_blocks), rough, "rough", chunk.index)
    return parts, glossary_updates, tail_sentences(rough)


async def polish_chunk(
    chunk: Chunk, source_lang: str, glossary: dict[str, str], prev_tail: str
) -> tuple[list[str], str]:
    """Polish pass for one chunk, reading each block's already-saved rough_text
    (polish model only). Returns (per-block polished translations, new polish-tail).
    """
    text_blocks = chunk.text_blocks
    rough_joined = "\n\n".join(b.rough_text or "" for b in text_blocks)
    polished = await polish(chunk, source_lang, rough_joined, glossary, prev_tail)

    parts = _split_or_fallback(polished, len(text_blocks), rough_joined, "polish", chunk.index)
    return parts, tail_sentences(polished)
