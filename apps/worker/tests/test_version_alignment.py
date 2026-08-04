from agreement_intelligence_worker.version_alignment import (
    CanonicalElement,
    CanonicalVersion,
    align_versions,
)


def test_aligns_identical_clause_as_matched_without_review() -> None:
    baseline = _version(
        "baseline",
        _element(
            "liability-v1", 0, "Liability", "liability", "Liability is capped at AED 100,000."
        ),
    )
    target = _version(
        "target",
        _element(
            "liability-v2", 0, "Liability", "liability", "Liability is capped at AED 100,000."
        ),
    )

    alignment = align_versions(baseline, target)

    assert [
        (item.kind, item.baseline_element_ids, item.target_element_ids) for item in alignment
    ] == [
        ("matched", ("liability-v1",), ("liability-v2",)),
    ]
    assert alignment[0].review_required is False
    assert alignment[0].confidence == 1.0


def test_marks_reordered_identical_clause_as_moved() -> None:
    baseline = _version(
        "baseline",
        _element("scope-v1", 0, "Scope", "scope", "The services are described in Schedule 1."),
        _element(
            "term-v1",
            1,
            "Termination",
            "termination",
            "Either party may terminate on 30 days notice.",
        ),
    )
    target = _version(
        "target",
        _element(
            "term-v2",
            0,
            "Termination",
            "termination",
            "Either party may terminate on 30 days notice.",
        ),
        _element("scope-v2", 1, "Scope", "scope", "The services are described in Schedule 1."),
    )

    alignment = align_versions(baseline, target)

    assert {item.kind for item in alignment} == {"moved"}
    assert all(item.review_required is False for item in alignment)


def test_detects_one_clause_split_into_adjacent_elements() -> None:
    baseline = _version(
        "baseline",
        _element(
            "termination-v1",
            0,
            "Termination",
            "termination",
            "Either party may terminate this Agreement on 30 days written notice for convenience.",
        ),
    )
    target = _version(
        "target",
        _element(
            "termination-notice-v2",
            0,
            "Termination notice",
            "termination",
            "Either party may terminate this Agreement on 30 days written notice.",
        ),
        _element(
            "termination-convenience-v2",
            1,
            "Termination convenience",
            "termination",
            "Termination may be exercised for convenience.",
        ),
    )

    alignment = align_versions(baseline, target)

    assert [
        (item.kind, item.baseline_element_ids, item.target_element_ids) for item in alignment
    ] == [
        (
            "split",
            ("termination-v1",),
            ("termination-notice-v2", "termination-convenience-v2"),
        )
    ]


def test_detects_adjacent_baseline_elements_merged_into_one_clause() -> None:
    baseline = _version(
        "baseline",
        _element(
            "notice-v1",
            0,
            "Termination notice",
            "termination",
            "Either party may terminate this Agreement on 30 days written notice.",
        ),
        _element(
            "convenience-v1",
            1,
            "Termination convenience",
            "termination",
            "Termination may be exercised for convenience.",
        ),
    )
    target = _version(
        "target",
        _element(
            "termination-v2",
            0,
            "Termination",
            "termination",
            "Either party may terminate this Agreement on 30 days written notice for convenience.",
        ),
    )

    alignment = align_versions(baseline, target)

    assert [
        (item.kind, item.baseline_element_ids, item.target_element_ids) for item in alignment
    ] == [
        ("merged", ("notice-v1", "convenience-v1"), ("termination-v2",)),
    ]


def test_returns_added_and_removed_elements_when_no_candidate_exists() -> None:
    baseline = _version(
        "baseline",
        _element(
            "governing-law-v1",
            0,
            "Governing law",
            "governing_law",
            "This Agreement is governed by UAE law.",
        ),
    )
    target = _version(
        "target",
        _element(
            "indemnity-v2",
            0,
            "Indemnity",
            "indemnity",
            "Supplier indemnifies Customer against losses.",
        ),
    )

    alignment = align_versions(baseline, target)

    assert [
        (item.kind, item.baseline_element_ids, item.target_element_ids) for item in alignment
    ] == [
        ("removed", ("governing-law-v1",), ()),
        ("added", (), ("indemnity-v2",)),
    ]


def test_low_confidence_candidate_requires_review_instead_of_exact_match() -> None:
    baseline = _version(
        "baseline",
        _element(
            "liability-v1",
            0,
            "Liability",
            "liability",
            "Liability is capped at AED 100,000 for direct losses.",
        ),
    )
    target = _version(
        "target",
        _element(
            "liability-v2",
            0,
            "Liability",
            "liability",
            "Liability excludes indirect losses and is subject to a monetary cap.",
        ),
    )

    alignment = align_versions(baseline, target)

    assert len(alignment) == 1
    assert alignment[0].kind == "matched"
    assert alignment[0].review_required is True
    assert 0.45 <= alignment[0].confidence < 0.75


def _version(checksum: str, *elements: CanonicalElement) -> CanonicalVersion:
    return CanonicalVersion(source_checksum=checksum, elements=elements)


def _element(
    element_id: str,
    ordinal: int,
    heading: str,
    clause_type: str,
    text: str,
) -> CanonicalElement:
    return CanonicalElement(
        element_id=element_id,
        ordinal=ordinal,
        heading_path=(heading,),
        clause_type=clause_type,
        text=text,
        citation_anchor_ids=(f"citation-{element_id}",),
    )
