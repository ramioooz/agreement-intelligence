from __future__ import annotations


def generate_summaries(blocks: list[tuple[str, str]]) -> dict[str, object]:
    claims = [
        {"text": text, "citation_anchor_ids": [anchor_id]}
        for anchor_id, text in blocks[:3]
    ]
    return {
        "business": {"version": "summary-rules.v1", "claims": claims},
        "legal": {"version": "summary-rules.v1", "claims": claims},
    }
