from __future__ import annotations

from typing import TypedDict


class ExtractedClause(TypedDict):
    category: str
    source_text: str
    citation_anchor_ids: list[str]
    confidence: float
    extraction_version: str


def extract_clauses(blocks: list[tuple[str, str]]) -> list[ExtractedClause]:
    categories = {
        "termination": ("terminate", "termination"),
        "confidentiality": ("confidential",),
        "governing_law": ("governing law",),
        "liability": ("liability", "liable"),
        "dispute_resolution": ("dispute", "arbitration"),
    }
    clauses: list[ExtractedClause] = []
    for anchor_id, text in blocks:
        lowered = text.lower()
        for category, signals in categories.items():
            if any(signal in lowered for signal in signals):
                clauses.append(
                    {
                        "category": category,
                        "source_text": text,
                        "citation_anchor_ids": [anchor_id],
                        "confidence": 0.9,
                        "extraction_version": "clause-rules.v1",
                    }
                )
                break
    return clauses
