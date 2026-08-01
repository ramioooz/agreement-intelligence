from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AgreementFamily = Literal[
    "client_agreement",
    "liquidity_provider_agreement",
    "non_agreement_material",
    "unknown_needs_review",
]


@dataclass(frozen=True)
class AgreementClassification:
    family: AgreementFamily
    confidence: float
    rationale: str
    evidence_terms: tuple[str, ...]
    version: str = "agreement-family-rules.v1"


def classify_document(text: str) -> AgreementClassification:
    normalized = text.lower()
    non_agreement_terms = tuple(
        term
        for term in (
            "curriculum vitae",
            "resume",
            "work experience",
            "professional experience",
            "education",
            "skills",
        )
        if term in normalized
    )
    has_specific_agreement_language = any(
        term in normalized
        for term in (
            "agreement",
            "client assets",
            "margin",
            "liquidity provider",
            "executable prices",
            "market maker",
        )
    )
    if len(non_agreement_terms) >= 2 and not has_specific_agreement_language:
        return AgreementClassification(
            "non_agreement_material",
            0.9,
            "Resume/CV-style material detected without agreement terms",
            non_agreement_terms,
        )
    client_hits = sum(term in normalized for term in ("client", "margin", "client assets"))
    provider_hits = sum(
        term in normalized for term in ("liquidity provider", "executable prices", "market maker")
    )
    if client_hits > provider_hits and client_hits:
        return AgreementClassification(
            "client_agreement", 0.8, "Client agreement terms detected", ("client",)
        )
    if provider_hits > client_hits and provider_hits:
        return AgreementClassification(
            "liquidity_provider_agreement",
            0.8,
            "Liquidity-provider terms detected",
            ("liquidity provider",),
        )
    return AgreementClassification(
        "unknown_needs_review", 0.0, "Insufficient agreement-family evidence", ()
    )
