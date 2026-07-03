"""Shared test fixtures/helpers: a fake Ollama chat client and a Block factory."""

import zipfile

import pytest

from app.models.book_structure import Block
from app.pipeline import ollama_client


def make_block(id_: int, type_: str = "paragraph", text: str = "", page: int = 1, rough_text=None, translated_text=None):
    return Block(
        id=id_, page=page, type=type_, text=text, rough_text=rough_text,
        translated_text=translated_text, order_key=id_,
    )


class FakeOllama:
    """Records every call() and returns a queued/callable response instead of hitting Ollama."""

    def __init__(self):
        self.calls: list[dict] = []
        self._responses: list = []

    def queue(self, response) -> None:
        """Queue a response: a string, or a callable(model, messages, **kw) -> str."""
        self._responses.append(response)

    async def chat(self, model, messages, *, json_format=False, temperature=None, num_ctx=None):
        self.calls.append(
            {
                "model": model, "messages": messages, "json_format": json_format,
                "temperature": temperature, "num_ctx": num_ctx,
            }
        )
        if not self._responses:
            raise AssertionError("FakeOllama.chat called with no queued response")
        response = self._responses.pop(0)
        if callable(response):
            return response(model, messages, json_format=json_format, temperature=temperature)
        return response

    async def chat_stream(self, model, messages, *, temperature=None, num_ctx=None):
        self.calls.append(
            {"model": model, "messages": messages, "temperature": temperature, "num_ctx": num_ctx}
        )
        if not self._responses:
            raise AssertionError("FakeOllama.chat_stream called with no queued response")
        response = self._responses.pop(0)
        text = response(model, messages, num_ctx=num_ctx) if callable(response) else response
        # Yield word-by-word so tests can observe incremental delivery.
        words = text.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "


@pytest.fixture
def fake_ollama(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(ollama_client, "chat", fake.chat)
    monkeypatch.setattr(ollama_client, "chat_stream", fake.chat_stream)
    return fake


class FakeEmbed:
    """Fake Ollama embed(): deterministic per-text vectors, overridable so
    retrieval-ranking tests can control which chunk should score highest."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self._vector_for: dict[str, list[float]] = {}

    def set_vector(self, text: str, vector: list[float]) -> None:
        self._vector_for[text] = vector

    async def embed(self, model, texts):
        self.calls.append(list(texts))
        return [self._vector_for.get(t, self._default_vector(t)) for t in texts]

    @staticmethod
    def _default_vector(text: str) -> list[float]:
        # Stable within a test run (hash() is per-process-stable), not meant
        # to be semantically meaningful.
        return [float(hash(text) % 1000), float(len(text)), 0.0]


@pytest.fixture
def fake_embed(monkeypatch):
    fake = FakeEmbed()
    monkeypatch.setattr(ollama_client, "embed", fake.embed)
    return fake


_EPUB_CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

_EPUB_CONTENT_OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:identifier id="BookId">urn:uuid:test</dc:identifier>
  </metadata>
  <manifest>
    <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>"""


@pytest.fixture
def tmp_epub(tmp_path):
    """Build a minimal single-chapter EPUB with the given XHTML body, return its path.

    PyMuPDF opens EPUB natively (it renders reflowable content into fixed pages,
    same font-size-per-span metadata as a PDF), so ingestion code needs no
    EPUB-specific branch — this fixture only exists to prove that end to end.
    """

    def _save(body_html: str) -> str:
        path = tmp_path / "test.epub"
        chapter = (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<html xmlns='http://www.w3.org/1999/xhtml'><body>" + body_html + "</body></html>"
        )
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
            z.writestr("META-INF/container.xml", _EPUB_CONTAINER_XML)
            z.writestr("OEBPS/content.opf", _EPUB_CONTENT_OPF)
            z.writestr("OEBPS/chap1.xhtml", chapter)
        return str(path)

    return _save
