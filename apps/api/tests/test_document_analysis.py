from __future__ import annotations

from agreement_intelligence_api.analysis.service import load_analysis
from agreement_intelligence_api.documents.storage import StoredDocument


class Storage:
    def read(self, key: str) -> None:
        return None


def test_analysis_returns_none_when_no_completed_artifact_exists() -> None:
    assert load_analysis(Storage(), None) is None


def test_analysis_loads_the_immutable_manifest() -> None:
    class ManifestStorage:
        def read(self, key: str) -> StoredDocument:
            assert key == "analysis/document-analysis.v1.json"
            return StoredDocument(
                content=b'{"schema_version":"document-analysis.v1","diagnostics":[{"code":"ocr_required"}]}',
                content_type="application/json",
            )

    assert load_analysis(ManifestStorage(), "analysis/document-analysis.v1.json") == {
        "schema_version": "document-analysis.v1",
        "diagnostics": [{"code": "ocr_required"}],
    }
