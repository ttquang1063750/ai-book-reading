"""Per-chunk translation: rough pass, glossary extraction, literary polish."""

import json
import logging
import re

from langdetect import DetectorFactory, LangDetectException, detect

from app.config import POLISH_MODEL, ROUGH_MODEL
from app.pipeline import ollama_client
from app.pipeline.chunking import Chunk

DetectorFactory.seed = 0  # langdetect is otherwise non-deterministic on ambiguous text

logger = logging.getLogger(__name__)

PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")

# Both models occasionally wrap output in Markdown formatting (most often **bold**
# around headings) even when told not to — the reader renders translated text as
# plain HTML, not Markdown, so leftover ** would show up literally on the page.
# Stripped defensively rather than relying solely on the prompt instruction.
MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*")
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)


def strip_markdown_artifacts(text: str) -> str:
    text = MARKDOWN_BOLD.sub(r"\1", text)
    text = MARKDOWN_HEADING.sub("", text)
    return text


def split_paragraphs(text: str, expected: int) -> list[str] | None:
    parts = [p.strip() for p in PARAGRAPH_SPLIT.split(text.strip()) if p.strip()]
    return parts if len(parts) == expected else None


# qwen2.5 (the polish model) has a reproducible failure mode on literary/narrative
# prose — independent of source/target language — where it "thinks out loud" in
# Chinese before giving the actual answer (e.g. "请注意，这里的...应改为纯越南文：" mid-output),
# or occasionally drifts into a wrong Latin-script language entirely (e.g. French
# instead of Vietnamese). Confirmed via live testing: 0/3 on technical content,
# 3/3 on narrative sentences, across multiple unrelated source/target language
# pairs — a model quirk, not something a better prompt reliably prevents.
# Detected and retried defensively instead, same fallback-chain idiom as
# _split_or_fallback below.
CJK_CHAR = re.compile(r"[一-鿿㐀-䶿]")
_CJK_TARGET_KEYWORDS = ("trung", "nhật", "hàn", "chinese", "japanese", "korean", "中文", "日本語", "한국어")
POLISH_MAX_ATTEMPTS = 3

# ISO 639-1 codes langdetect returns, for the curated target-language presets offered
# in the upload UI (frontend/library-page.ts's TARGET_LANG_PRESETS) — used to catch
# leaks between languages that share the Latin script (CJK regex above can't tell
# French from Vietnamese, both are just "Latin letters" to a character check).
# Free-text/"Khác…" target languages outside this list fall back to the CJK-only
# check — there's no reliable way to map arbitrary text to an ISO code.
_TARGET_LANG_ISO = {
    "tiếng việt": "vi", "tiếng anh": "en", "tiếng pháp": "fr", "tiếng nhật": "ja",
    "tiếng hàn": "ko", "tiếng trung": "zh-cn", "tiếng đức": "de",
    "tiếng tây ban nha": "es", "tiếng ý": "it", "tiếng nga": "ru", "tiếng thái": "th",
}
# Below this, langdetect's confidence is too low to trust (e.g. a lone short heading).
LANGDETECT_MIN_CHARS = 20


def _target_expects_cjk(target_lang: str) -> bool:
    lower = target_lang.lower()
    return any(keyword in lower for keyword in _CJK_TARGET_KEYWORDS)


def _has_unexpected_cjk_leak(text: str, target_lang: str) -> bool:
    return not _target_expects_cjk(target_lang) and bool(CJK_CHAR.search(text))


def _has_wrong_language(text: str, target_lang: str) -> bool:
    """Broader check than the CJK regex: also catches wrong-but-same-script leaks
    (e.g. French output when the target is Vietnamese) via offline language
    detection, for the target languages we can map to an ISO code."""
    if _has_unexpected_cjk_leak(text, target_lang):
        return True
    expected_iso = _TARGET_LANG_ISO.get(target_lang.strip().lower())
    if expected_iso is None or len(text.strip()) < LANGDETECT_MIN_CHARS:
        return False
    try:
        return detect(text) != expected_iso
    except LangDetectException:
        return False  # too ambiguous to call — don't block a retry loop on it


DEFAULT_SOURCE_LANG_LABEL = "Không xác định"


async def detect_source_language(sample_text: str) -> str:
    """Identify the source language from a short text sample, using the rough
    model (already loaded for the rough pass right after this runs — no extra
    model swap). Returns a Vietnamese language name, matching how target
    languages are phrased in the UI (e.g. "Tiếng Anh", "Tiếng Nhật")."""
    sample_text = sample_text.strip()
    if not sample_text:
        return DEFAULT_SOURCE_LANG_LABEL
    prompt = (
        "What language is the following text written in? Respond with ONLY the language "
        'name in Vietnamese (e.g. "Tiếng Anh", "Tiếng Nhật", "Tiếng Đức"), nothing else — '
        "no punctuation, no explanation.\n\n"
        f"Text:\n{sample_text[:1000]}"
    )
    try:
        response = await ollama_client.chat(
            ROUGH_MODEL, [{"role": "user", "content": prompt}], temperature=0.0
        )
        first_line = response.strip().splitlines()[0].strip()
        detected = first_line.strip('"').strip("'").strip()
        return detected or DEFAULT_SOURCE_LANG_LABEL
    except (ollama_client.OllamaError, IndexError) as exc:
        logger.warning("Source language detection failed, using placeholder: %s", exc)
        return DEFAULT_SOURCE_LANG_LABEL


async def rough_translate(chunk: Chunk, source_lang: str, target_lang: str, prev_tail: str) -> str:
    n = len(chunk.text_blocks)
    system = (
        f"You are a professional literary translator. Translate the {source_lang} text into "
        f"{target_lang}. The input has {n} paragraphs separated by blank lines; output exactly "
        f"{n} paragraphs separated by blank lines. Output only the translation, no commentary. "
        f"The output must be entirely in {target_lang} — never switch to {source_lang} or any "
        "other language, not even for a single sentence or word (proper nouns, code, and "
        "acronyms are the only exception and should be kept as-is). "
        "Output plain text only — do not use Markdown formatting (no **bold**, no # headings, "
        "no bullet lists) even for chapter titles or headings."
    )
    user = ""
    if prev_tail:
        user += f"Previously translated context (for continuity, do NOT re-translate):\n{prev_tail}\n\n"
    user += f"Text to translate:\n\n{chunk.source_text}"
    raw = await ollama_client.chat(
        ROUGH_MODEL,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
    )
    return strip_markdown_artifacts(raw)


# Capitalized word preceded by a lowercase word — i.e. mid-sentence, so likely a proper noun.
# The anchor is a lookbehind (zero-width) rather than a consumed char, so back-to-back
# capitalized words ("Victory Mansions") each get captured instead of only the first.
# Relies on upper/lowercase distinction, so it only fires for Latin-cased source languages —
# for scripts without case (CJK, Arabic, Thai, ...) this simply finds zero candidates, so
# glossary consistency silently doesn't kick in rather than erroring.
MID_SENTENCE_CAPITALIZED = re.compile(r"(?<=[a-zà-þ,;])\s+([A-ZÀ-Þ][a-zà-þA-ZÀ-Þ'-]+)")


def new_capitalized_terms(source_text: str, glossary: dict[str, str]) -> set[str]:
    terms = set(MID_SENTENCE_CAPITALIZED.findall(source_text))
    return {t for t in terms if t not in glossary}


async def extract_glossary_terms(
    source_text: str, translated_text: str, glossary: dict[str, str], target_lang: str
) -> dict[str, str]:
    """Ask the rough model how proper nouns were rendered; first-seen-wins merge."""
    candidates = new_capitalized_terms(source_text, glossary)
    if not candidates:
        return {}
    prompt = (
        f"Below is an original passage and its {target_lang} translation. For each proper noun "
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
    chunk: Chunk, source_lang: str, target_lang: str, rough_text: str,
    glossary: dict[str, str], prev_tail: str
) -> str:
    n = len(chunk.text_blocks)
    system = (
        f"You are a literary editor writing in {target_lang}. Task: rewrite the draft translation "
        f"into natural, flowing {target_lang} prose, keeping the exact meaning of the original. "
        f"The translation has {n} paragraphs separated by blank lines; keep exactly {n} paragraphs. "
        "Respond with ONLY the revised translation — no commentary, no explanation of your "
        "reasoning or approach, no restating the task, nothing before or after the translation "
        "itself. "
        f"The output must be entirely in {target_lang} — never switch to {source_lang} or any "
        "other language, not even for a single sentence or word. Proper nouns, code, and "
        "acronyms are the only exception and should be kept as-is. "
        "Output plain text only — do NOT use Markdown formatting (no **bold**, no # headings, "
        "no bullet lists), even for chapter titles."
    )
    user = ""
    if glossary:
        pairs = "; ".join(f"{k} → {v}" for k, v in glossary.items())
        user += f"Use these proper nouns/terms consistently: {pairs}\n\n"
    if prev_tail:
        user += f"End of the previously translated text (for continuity, do NOT re-translate):\n{prev_tail}\n\n"
    user += (
        f"Original ({source_lang}):\n{chunk.source_text}\n\n"
        f"Draft translation:\n{rough_text}\n\n"
        f"Rewrite the draft translation to sound more natural. Output only the rewritten "
        f"{target_lang} text, nothing else."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    cleaned = rough_text
    for attempt in range(POLISH_MAX_ATTEMPTS):
        raw = await ollama_client.chat(POLISH_MODEL, messages, temperature=0.3)
        cleaned = strip_markdown_artifacts(raw)
        if not _has_wrong_language(cleaned, target_lang):
            return cleaned
        logger.warning(
            "Chunk %d: polish attempt %d produced text in the wrong language, retrying",
            chunk.index, attempt + 1,
        )
    logger.warning("Chunk %d: polish kept producing the wrong language after %d attempts, "
                    "falling back to rough draft", chunk.index, POLISH_MAX_ATTEMPTS)
    return rough_text


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
    chunk: Chunk, source_lang: str, target_lang: str, glossary: dict[str, str], prev_tail: str
) -> tuple[list[str], dict[str, str], str]:
    """Rough pass + glossary extraction for one chunk (rough model only).

    Returns (per-block rough translations, glossary updates, new rough-tail for the next chunk).
    """
    text_blocks = chunk.text_blocks
    rough = await rough_translate(chunk, source_lang, target_lang, prev_tail)
    glossary_updates = await extract_glossary_terms(chunk.source_text, rough, glossary, target_lang)

    parts = _split_or_fallback(rough, len(text_blocks), rough, "rough", chunk.index)
    return parts, glossary_updates, tail_sentences(rough)


async def polish_chunk(
    chunk: Chunk, source_lang: str, target_lang: str, glossary: dict[str, str], prev_tail: str
) -> tuple[list[str], str]:
    """Polish pass for one chunk, reading each block's already-saved rough_text
    (polish model only). Returns (per-block polished translations, new polish-tail).
    """
    text_blocks = chunk.text_blocks
    rough_joined = "\n\n".join(b.rough_text or "" for b in text_blocks)
    polished = await polish(chunk, source_lang, target_lang, rough_joined, glossary, prev_tail)

    parts = _split_or_fallback(polished, len(text_blocks), rough_joined, "polish", chunk.index)
    return parts, tail_sentences(polished)
