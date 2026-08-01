from __future__ import annotations

from io import BytesIO

from agreement_intelligence_worker.document_understanding import parse_document
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def test_parse_digital_pdf_preserves_page_text_and_stable_citation_anchors() -> None:
    first = parse_document(
        content=_pdf_with_text("Master Agreement\nTermination right"),
        content_type="application/pdf",
        source_checksum="a" * 64,
    )
    second = parse_document(
        content=_pdf_with_text("Master Agreement\nTermination right"),
        content_type="application/pdf",
        source_checksum="a" * 64,
    )

    assert first.diagnostics == ()
    assert first.pages[0].number == 1
    assert [block.text for block in first.pages[0].blocks] == [
        "Master Agreement",
        "Termination right",
    ]
    assert first.pages[0].blocks[0].anchor_id == second.pages[0].blocks[0].anchor_id
    assert first.pages[0].blocks[0].anchor_id.startswith("citation-")


def test_parse_docx_preserves_headings_paragraphs_and_tables() -> None:
    document = Document()
    document.add_heading("Liquidity Provider Agreement", level=1)
    document.add_paragraph("The provider shall make executable prices.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Provider"
    table.rows[0].cells[1].text = "Liquidity Co"
    stream = BytesIO()
    document.save(stream)

    parsed = parse_document(
        content=stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        source_checksum="b" * 64,
    )

    assert [(block.kind, block.text) for block in parsed.pages[0].blocks] == [
        ("heading", "Liquidity Provider Agreement"),
        ("paragraph", "The provider shall make executable prices."),
        ("table", "Provider | Liquidity Co"),
    ]


def test_parse_low_text_pdf_reports_ocr_required_without_running_ocr() -> None:
    parsed = parse_document(
        content=_pdf_with_text(""),
        content_type="application/pdf",
        source_checksum="c" * 64,
    )

    assert parsed.diagnostics[0].code == "ocr_required"
    assert parsed.diagnostics[0].page_numbers == (1,)


def _pdf_with_text(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    page[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    lines = text.split("\n") if text else []
    operators = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            operators.append("0 -18 Td")
        operators.append(f"({line}) Tj")
    operators.append("ET")
    content.set_data("\n".join(operators).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()
