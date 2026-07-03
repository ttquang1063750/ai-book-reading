"""Tests for translate.py: pure paragraph-split logic, glossary regex, and the
rough/polish pipeline functions with Ollama mocked out (fast, no live model needed)."""

from app.config import POLISH_MODEL, ROUGH_MODEL
from app.pipeline import ollama_client
from app.pipeline.chunking import Chunk
from app.pipeline.translate import (
    DEFAULT_SOURCE_LANG_LABEL,
    _has_wrong_language,
    _split_or_fallback,
    detect_source_language,
    new_capitalized_terms,
    polish_chunk,
    rough_translate_chunk,
    split_paragraphs,
    strip_markdown_artifacts,
)
from tests.conftest import make_block


def test_split_paragraphs_matching_count():
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    assert split_paragraphs(text, 3) == ["First paragraph.", "Second paragraph.", "Third paragraph."]


def test_split_paragraphs_mismatched_count_returns_none():
    text = "Only one paragraph here."
    assert split_paragraphs(text, 3) is None


def test_strip_markdown_artifacts_removes_bold_and_headings():
    text = "**CHƯƠNG 1 Giới thiệu**\n\n# Một tiêu đề khác\n\nVăn bản bình thường **có nhấn mạnh** ở giữa."
    result = strip_markdown_artifacts(text)
    assert "**" not in result
    assert "#" not in result
    assert "CHƯƠNG 1 Giới thiệu" in result
    assert "Một tiêu đề khác" in result
    assert "Văn bản bình thường có nhấn mạnh ở giữa." in result


def test_strip_markdown_artifacts_leaves_plain_text_untouched():
    text = "Không có định dạng gì ở đây cả."
    assert strip_markdown_artifacts(text) == text


async def test_detect_source_language_identifies_english(fake_ollama):
    result = await detect_source_language("The quick brown fox jumps over the lazy dog near the fence.")
    assert result == "Tiếng Anh"
    assert fake_ollama.calls == []  # langdetect-based now — no model call at all


async def test_detect_source_language_identifies_japanese(fake_ollama):
    result = await detect_source_language("古い灯台は崖の端に立っており、何十年もの潮風でその白いペンキが剥がれていた。")
    assert result == "Tiếng Nhật"


async def test_detect_source_language_identifies_short_heading_line(fake_ollama):
    # Regression test: an LLM-based detector (translategemma) got this kind of
    # short, heading-like sample wrong more often than not — see the docstring
    # on detect_source_language for the live-testing numbers that motivated
    # switching to langdetect.
    result = await detect_source_language("The Lighthouse\nA Quiet Morning")
    assert result == "Tiếng Anh"


async def test_detect_source_language_empty_sample_returns_placeholder(fake_ollama):
    result = await detect_source_language("   ")
    assert result == DEFAULT_SOURCE_LANG_LABEL
    assert fake_ollama.calls == []  # short-circuits, never calls Ollama for nothing


async def test_detect_source_language_too_short_returns_placeholder(fake_ollama):
    # Below LANGDETECT_MIN_CHARS — not enough signal to guess reliably, so this
    # falls back instead of risking a confident-but-wrong single-word guess.
    result = await detect_source_language("Hello")
    assert result == DEFAULT_SOURCE_LANG_LABEL


async def test_detect_source_language_undetectable_text_returns_placeholder(fake_ollama):
    # No linguistic features at all (langdetect raises LangDetectException) —
    # falls back instead of propagating.
    result = await detect_source_language("1234567890 !@#$%^&*() 1234567890 !@#$%^&*()")
    assert result == DEFAULT_SOURCE_LANG_LABEL


def test_new_capitalized_terms_catches_mid_sentence_proper_nouns():
    text = "Winston Smith slipped through the doors of Victory Mansions near the Ministry."
    terms = new_capitalized_terms(text, {})
    assert "Smith" in terms
    assert "Victory" in terms
    assert "Mansions" in terms
    assert "Ministry" in terms


def test_new_capitalized_terms_excludes_sentence_starters():
    text = "The wind was cold. He walked home. It was late."
    terms = new_capitalized_terms(text, {})
    assert terms == set()


def test_new_capitalized_terms_excludes_already_known_glossary_terms():
    text = "Winston Smith walked past Julia quietly."
    terms = new_capitalized_terms(text, {"Smith": "Smith"})
    assert "Smith" not in terms
    assert "Julia" in terms


def test_split_or_fallback_uses_primary_when_it_matches():
    primary = "A.\n\nB."
    result = _split_or_fallback(primary, 2, "fallback text", "test", 0)
    assert result == ["A.", "B."]


def test_split_or_fallback_uses_fallback_when_primary_mismatched():
    primary = "Only one blob, no double newline."
    fallback = "X.\n\nY."
    result = _split_or_fallback(primary, 2, fallback, "test", 0)
    assert result == ["X.", "Y."]


def test_split_or_fallback_merges_into_first_block_when_both_fail():
    primary = "Still one blob."
    fallback = "Also one blob."
    result = _split_or_fallback(primary, 3, fallback, "test", 0)
    assert result[0] == "Still one blob."
    assert result[1:] == ["", ""]


async def test_rough_translate_chunk_calls_rough_model_and_splits_per_block(fake_ollama):
    blocks = [make_block(0, text="First sentence."), make_block(1, text="Second sentence.")]
    chunk = Chunk(index=0, blocks=blocks)
    fake_ollama.queue("Câu một.\n\nCâu hai.")  # rough_translate response
    # No mid-sentence capitalized candidates in the source, so extract_glossary_terms
    # short-circuits and never calls Ollama a second time.

    parts, glossary_updates, tail = await rough_translate_chunk(chunk, "en", "Tiếng Việt", {}, "")

    assert parts == ["Câu một.", "Câu hai."]
    assert glossary_updates == {}
    assert len(fake_ollama.calls) == 1
    assert fake_ollama.calls[0]["model"] == ROUGH_MODEL


async def test_rough_translate_chunk_extracts_glossary_when_proper_nouns_present(fake_ollama):
    blocks = [make_block(0, text="Winston Smith walked home quietly.")]
    chunk = Chunk(index=0, blocks=blocks)
    fake_ollama.queue("Winston Smith đi bộ về nhà lặng lẽ.")  # rough_translate
    fake_ollama.queue('{"terms": [{"source": "Smith", "translated": "Smith"}]}')  # glossary extraction

    parts, glossary_updates, _tail = await rough_translate_chunk(chunk, "en", "Tiếng Việt", {}, "")

    assert parts == ["Winston Smith đi bộ về nhà lặng lẽ."]
    assert glossary_updates == {"Smith": "Smith"}
    assert len(fake_ollama.calls) == 2
    assert fake_ollama.calls[1]["json_format"] is True


async def test_polish_chunk_uses_rough_text_field_not_original_text(fake_ollama):
    blocks = [make_block(0, text="Original English.", rough_text="Bản dịch nháp.")]
    chunk = Chunk(index=0, blocks=blocks)
    fake_ollama.queue("Bản dịch hoàn chỉnh.")

    parts, _tail = await polish_chunk(chunk, "en", "Tiếng Việt", {}, "")

    assert parts == ["Bản dịch hoàn chỉnh."]
    assert fake_ollama.calls[0]["model"] == POLISH_MODEL
    # The prompt must reference the rough draft, not the original source text.
    user_message = fake_ollama.calls[0]["messages"][-1]["content"]
    assert "Bản dịch nháp." in user_message


async def test_polish_retries_on_cjk_leak_then_succeeds(fake_ollama):
    blocks = [make_block(0, text="Original English.", rough_text="Bản dịch nháp.")]
    chunk = Chunk(index=0, blocks=blocks)
    fake_ollama.queue("Ngọn hải đăng指引船只穿过雾气。")  # leaked CJK — must be rejected
    fake_ollama.queue("Bản dịch hoàn chỉnh, sạch sẽ.")  # clean retry

    parts, _tail = await polish_chunk(chunk, "en", "Tiếng Việt", {}, "")

    assert parts == ["Bản dịch hoàn chỉnh, sạch sẽ."]
    assert len(fake_ollama.calls) == 2


async def test_polish_falls_back_to_rough_text_after_repeated_cjk_leaks(fake_ollama):
    blocks = [make_block(0, text="Original English.", rough_text="Bản dịch nháp sạch.")]
    chunk = Chunk(index=0, blocks=blocks)
    for _ in range(3):  # POLISH_MAX_ATTEMPTS
        fake_ollama.queue("我将提供越南语翻译：Ngọn hải đăng指引船只。")

    parts, _tail = await polish_chunk(chunk, "en", "Tiếng Việt", {}, "")

    assert parts == ["Bản dịch nháp sạch."]  # fell back to the (clean) rough draft
    assert len(fake_ollama.calls) == 3


async def test_polish_does_not_flag_cjk_when_target_language_is_chinese(fake_ollama):
    blocks = [make_block(0, text="Original English.", rough_text="Rough draft.")]
    chunk = Chunk(index=0, blocks=blocks)
    fake_ollama.queue("这是一个自然的中文翻译。")  # CJK is *expected* here, not a leak

    parts, _tail = await polish_chunk(chunk, "en", "Tiếng Trung", {}, "")

    assert parts == ["这是一个自然的中文翻译。"]
    assert len(fake_ollama.calls) == 1


def test_has_wrong_language_detects_french_leak_into_vietnamese_target():
    french_text = "Ceci est une phrase entièrement normale écrite en français."
    assert _has_wrong_language(french_text, "Tiếng Việt") is True


def test_has_wrong_language_accepts_correct_vietnamese():
    vietnamese_text = "Đây là một câu hoàn toàn bình thường được viết bằng tiếng Việt."
    assert _has_wrong_language(vietnamese_text, "Tiếng Việt") is False


def test_has_wrong_language_skips_langdetect_for_short_text():
    # Below LANGDETECT_MIN_CHARS — too short to trust, even though "Bonjour" is French.
    assert _has_wrong_language("Bonjour", "Tiếng Việt") is False


def test_has_wrong_language_skips_check_for_unmapped_custom_target():
    french_text = "Ceci est une phrase entièrement normale écrite en français."
    assert _has_wrong_language(french_text, "Klingon") is False


async def test_polish_retries_when_french_leaks_into_vietnamese_target(fake_ollama):
    blocks = [make_block(0, text="Original English.", rough_text="Bản dịch nháp sạch sẽ và dài đủ.")]
    chunk = Chunk(index=0, blocks=blocks)
    fake_ollama.queue("Ceci est une phrase entièrement normale écrite en français, pas en vietnamien.")
    fake_ollama.queue("Đây là bản dịch tiếng Việt hoàn chỉnh và đúng ngôn ngữ đích được yêu cầu.")

    parts, _tail = await polish_chunk(chunk, "en", "Tiếng Việt", {}, "")

    assert parts == ["Đây là bản dịch tiếng Việt hoàn chỉnh và đúng ngôn ngữ đích được yêu cầu."]
    assert len(fake_ollama.calls) == 2
