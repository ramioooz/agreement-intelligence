from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Literal

from docx import Document
from pypdf import PdfReader

BlockKind = Literal["heading", "paragraph", "list_item", "table"]
EvidenceTrust = Literal["untrusted"]


@dataclass(frozen=True)
class CitationAnchor:
    anchor_id: str
    source_checksum: str
    page_number: int
    block_index: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class DocumentBlock:
    anchor_id: str
    kind: BlockKind
    text: str
    start_offset: int
    end_offset: int
    trust: EvidenceTrust = "untrusted"


@dataclass(frozen=True)
class DocumentPage:
    number: int
    blocks: tuple[DocumentBlock, ...]


@dataclass(frozen=True)
class DocumentDiagnostic:
    code: str
    message: str
    page_numbers: tuple[int, ...]


@dataclass(frozen=True)
class ParsedDocument:
    source_checksum: str
    pages: tuple[DocumentPage, ...]
    diagnostics: tuple[DocumentDiagnostic, ...]

    @property
    def citations(self) -> tuple[CitationAnchor, ...]:
        return tuple(
            CitationAnchor(
                anchor_id=block.anchor_id,
                source_checksum=self.source_checksum,
                page_number=page.number,
                block_index=index,
                start_offset=block.start_offset,
                end_offset=block.end_offset,
            )
            for page in self.pages
            for index, block in enumerate(page.blocks)
        )


def parse_document(*, content: bytes, content_type: str, source_checksum: str) -> ParsedDocument:
    if content_type == "application/pdf":
        pages = _parse_pdf(content, source_checksum)
        diagnostics = _pdf_diagnostics(pages)
    elif content_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        pages = (_parse_docx(content, source_checksum),)
        diagnostics = ()
    else:
        raise ValueError(f"Unsupported document content type: {content_type}")
    return ParsedDocument(
        source_checksum=source_checksum,
        pages=pages,
        diagnostics=diagnostics,
    )


def _parse_pdf(content: bytes, source_checksum: str) -> tuple[DocumentPage, ...]:
    reader = PdfReader(BytesIO(content))
    pages: list[DocumentPage] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        pages.append(_page_from_text(page_number, lines, source_checksum))
    return tuple(pages)


def _parse_docx(content: bytes, source_checksum: str) -> DocumentPage:
    document = Document(BytesIO(content))
    items: list[tuple[BlockKind, str]] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name.lower() if paragraph.style is not None else ""
        if style_name.startswith("heading"):
            kind: BlockKind = "heading"
        elif style_name.startswith("list"):
            kind = "list_item"
        else:
            kind = "paragraph"
        items.append((kind, text))
    for table in document.tables:
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        table_text = "\n".join(row for row in rows if row.strip())
        if table_text:
            items.append(("table", table_text))
    return _page_from_items(1, items, source_checksum)


def _page_from_text(page_number: int, lines: list[str], source_checksum: str) -> DocumentPage:
    return _page_from_items(
        page_number,
        [
            ("heading" if index == 0 and _looks_like_heading(line) else "paragraph", line)
            for index, line in enumerate(lines)
        ],
        source_checksum,
    )


def _page_from_items(
    page_number: int, items: list[tuple[BlockKind, str]], source_checksum: str
) -> DocumentPage:
    offset = 0
    blocks: list[DocumentBlock] = []
    for block_index, (kind, text) in enumerate(items):
        start_offset = offset
        end_offset = start_offset + len(text)
        blocks.append(
            DocumentBlock(
                anchor_id=_anchor_id(
                    source_checksum,
                    page_number,
                    block_index,
                    start_offset,
                    end_offset,
                ),
                kind=kind,
                text=text,
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
        offset = end_offset + 1
    return DocumentPage(number=page_number, blocks=tuple(blocks))


def _anchor_id(
    source_checksum: str,
    page_number: int,
    block_index: int,
    start_offset: int,
    end_offset: int,
) -> str:
    value = ":".join(
        (source_checksum, str(page_number), str(block_index), str(start_offset), str(end_offset))
    )
    return f"citation-{sha256(value.encode()).hexdigest()[:24]}"


def _looks_like_heading(text: str) -> bool:
    return len(text) <= 120 and not text.endswith((".", ";", ":"))


def _pdf_diagnostics(pages: tuple[DocumentPage, ...]) -> tuple[DocumentDiagnostic, ...]:
    low_text_pages = tuple(page.number for page in pages if not page.blocks)
    if not low_text_pages:
        return ()
    return (
        DocumentDiagnostic(
            code="ocr_required",
            message="This PDF has insufficient embedded text and requires OCR.",
            page_numbers=low_text_pages,
        ),
    )
