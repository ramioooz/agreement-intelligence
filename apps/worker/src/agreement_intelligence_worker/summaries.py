from __future__ import annotations

from typing import TypedDict


class SummaryClaim(TypedDict):
    text: str
    citation_anchor_ids: list[str]


class Summary(TypedDict):
    version: str
    claims: list[SummaryClaim]


def generate_summaries(blocks: list[tuple[str, str]]) -> dict[str, Summary]:
    claims: list[SummaryClaim] = [
        {"text": text, "citation_anchor_ids": [anchor_id]} for anchor_id, text in blocks[:3]
    ]
    return {
        "business": {"version": "summary-rules.v1", "claims": claims},
        "legal": {"version": "summary-rules.v1", "claims": claims},
    }
