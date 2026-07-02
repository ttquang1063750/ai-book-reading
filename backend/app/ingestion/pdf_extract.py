"""Raw text extraction from PDF via PyMuPDF, keeping font metadata per block."""

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# PyMuPDF span "flags" bitfield (see page.get_text("dict") docs).
_FLAG_ITALIC = 1 << 1
_FLAG_MONOSPACE = 1 << 3
_FLAG_BOLD = 1 << 4


@dataclass
class RawSpan:
    text: str
    size: float
    bold: bool
    italic: bool
    mono: bool


@dataclass
class RawLine:
    spans: list[RawSpan] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def max_size(self) -> float:
        return max((s.size for s in self.spans), default=0.0)

    @property
    def is_mono(self) -> bool:
        return bool(self.spans) and all(s.mono for s in self.spans)


class EncryptedPdfError(Exception):
    """Raised when the uploaded PDF is password-protected and can't be read."""


@dataclass
class RawImage:
    page: int  # 1-based
    y0: float
    data: bytes
    ext: str


@dataclass
class RawBlock:
    page: int  # 1-based
    y0: float
    y1: float
    lines: list[RawLine] = field(default_factory=list)

    @property
    def max_size(self) -> float:
        return max((l.max_size for l in self.lines), default=0.0)

    @property
    def is_mono(self) -> bool:
        return bool(self.lines) and all(l.is_mono for l in self.lines)

    @property
    def text_joined(self) -> str:
        """Join lines into flowing prose, repairing end-of-line hyphenation."""
        parts: list[str] = []
        for line in self.lines:
            text = line.text.strip()
            if not text:
                continue
            if parts and parts[-1].endswith("-"):
                parts[-1] = parts[-1][:-1] + text
            elif parts:
                parts[-1] = parts[-1] + " " + text
            else:
                parts.append(text)
        return " ".join(parts).strip()

    @property
    def text_lines_preserved(self) -> str:
        """Join lines keeping line breaks verbatim — for code/verse blocks."""
        return "\n".join(line.text.strip() for line in self.lines if line.text.strip())

    @property
    def word_count(self) -> int:
        return len(self.text_joined.split())


def extract_raw_blocks(pdf_path: Path) -> tuple[list[RawBlock], list[RawImage], int]:
    """Return ordered raw text blocks, raw images, and the page count."""
    blocks: list[RawBlock] = []
    images: list[RawImage] = []
    with pymupdf.open(pdf_path) as doc:
        if doc.is_encrypted:
            raise EncryptedPdfError(
                "Sách bị khoá mật khẩu, vui lòng gỡ khoá trước khi tải lên."
            )
        page_count = doc.page_count
        for page_index, page in enumerate(doc):
            page_dict = page.get_text("dict")
            for b in page_dict["blocks"]:
                if b.get("type") == 1:  # image block
                    img_bytes = b.get("image")
                    if img_bytes:
                        images.append(
                            RawImage(
                                page=page_index + 1,
                                y0=b["bbox"][1],
                                data=img_bytes,
                                ext=b.get("ext", "png"),
                            )
                        )
                    continue
                if b.get("type") != 0:
                    continue
                raw = RawBlock(page=page_index + 1, y0=b["bbox"][1], y1=b["bbox"][3])
                for line in b.get("lines", []):
                    spans = [
                        RawSpan(
                            text=s["text"],
                            size=s["size"],
                            bold=bool(s["flags"] & _FLAG_BOLD),
                            italic=bool(s["flags"] & _FLAG_ITALIC),
                            mono=bool(s["flags"] & _FLAG_MONOSPACE),
                        )
                        for s in line.get("spans", [])
                    ]
                    if not any(s.text.strip() for s in spans):
                        continue
                    raw.lines.append(RawLine(spans=spans))
                if raw.lines:
                    blocks.append(raw)
    return blocks, images, page_count
