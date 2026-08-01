from agreement_intelligence_worker.clause_extraction import extract_clauses


def test_extracts_termination_clause_with_its_source_anchor() -> None:
    clauses = extract_clauses(
        [("citation-1", "Either party may terminate this Agreement on 30 days notice.")]
    )

    assert clauses == [
        {
            "category": "termination",
            "source_text": "Either party may terminate this Agreement on 30 days notice.",
            "citation_anchor_ids": ["citation-1"],
            "confidence": 0.9,
            "extraction_version": "clause-rules.v1",
        }
    ]
