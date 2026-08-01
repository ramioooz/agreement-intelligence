from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4

from agreement_intelligence_worker.document_processor import DocumentUnderstandingProcessor
from agreement_intelligence_worker.processing import ProcessingJob
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


@dataclass
class InMemoryObjectStorage:
    objects: dict[str, bytes]

    def read(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def put_immutable(self, key: str, content: bytes, *, content_type: str) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = content
        return True


def test_processor_writes_a_versioned_cited_document_analysis_manifest() -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    source_key = "tenants/example/workspaces/example/documents/source/original.pdf"
    storage = InMemoryObjectStorage(objects={source_key: _pdf_with_text("Client Agreement")})
    processor = DocumentUnderstandingProcessor(storage)
    job = ProcessingJob(
        id=uuid4(),
        agreement_id=agreement_id,
        state="processing",
        attempt_count=1,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_storage_key=source_key,
        source_checksum="a" * 64,
        source_content_type="application/pdf",
    )

    artifact = processor.process(job)
    manifest = json.loads(storage.objects[artifact.key])

    assert artifact.key == (
        f"tenants/{organization_id}/workspaces/{workspace_id}/agreements/{agreement_id}/"
        f"analysis/{'a' * 64}/document-analysis.v1.json"
    )
    assert manifest["schema_version"] == "document-analysis.v1"
    assert manifest["source"]["checksum"] == "a" * 64
    assert manifest["document"]["pages"][0]["blocks"][0]["text"] == "Client Agreement"
    assert manifest["citations"][0]["anchor_id"].startswith("citation-")
    assert manifest["diagnostics"] == []


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
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()
