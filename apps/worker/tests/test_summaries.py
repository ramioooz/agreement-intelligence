from agreement_intelligence_worker.summaries import generate_summaries


def test_summaries_are_grounded_in_cited_source_text() -> None:
    summaries = generate_summaries(
        [("citation-1", "Either party may terminate this Agreement on 30 days notice.")]
    )

    assert summaries["business"]["claims"][0]["citation_anchor_ids"] == ["citation-1"]
    assert summaries["legal"]["claims"][0]["citation_anchor_ids"] == ["citation-1"]
