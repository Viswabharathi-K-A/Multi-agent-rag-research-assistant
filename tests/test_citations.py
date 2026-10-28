"""Deterministic citation checks with no retrieval or model calls."""

from copy import deepcopy

import pytest

from app.agents.citations import normalize_document_citations, validate_document_citations, validate_web_citations


@pytest.fixture
def sources():
    return [
        {"source_id": "raft.pdf:p5:c4", "source_kind": "document"},
        {"source_id": "raft.pdf:p5:c5", "source_kind": "document"},
        {"source_id": "Practical Byzantine Fault Tolerance.pdf:p3:c6", "source_kind": "document"},
        {"source_id": "web-1", "source_kind": "web", "url": "https://example.com/ref"},
    ]


@pytest.mark.parametrize("content", [
    "Claim [raft.pdf:p5:c4]",
    "Claim [raft.pdf:p5:c4] [raft.pdf:p5:c5]",
    "Claim [raft.pdf:p5:c4]. Another [raft.pdf:p5:c4].",
    "[Note] Claim [Practical Byzantine Fault Tolerance.pdf:p3:c6]",
    "Claim [raft.pdf:p5:c4]\nWeb evidence https://example.com/ref",
])
def test_valid_references_preserve_sources(sources, content):
    original = deepcopy(sources)
    assert validate_document_citations(content, sources) is None
    assert sources == original


@pytest.mark.parametrize("reference", [
    "raft.pdf:p99:c99",
    "raft.pdf:p5:c4-c5",
    "raft.pdf:p5:c4–c5",
    "raft.pdf:p5:c4—c5",
    "raft.pdf:p5:c4, raft.pdf:p5:c5",
    "raft.pdf:p5:c4 raft.pdf:p5:c5",
    "raft.pdf:p5:c4\nraft.pdf:p5:c5",
    " raft.pdf:p5:c4 ",
    "RAFT.pdf:p5:c4",
    "raft.pdf:pX:c4",
    "[raft.pdf:p5:c4",
])
def test_invalid_reference_is_rejected_even_alongside_valid_one(sources, reference):
    with pytest.raises(ValueError, match="exact supplied IDs"):
        validate_document_citations(f"Valid [raft.pdf:p5:c4]. Invalid [{reference}]", sources)


@pytest.mark.parametrize("content", ["", "No citations", "[Note]", "https://example.com/ref", "raft.pdf:p5:c4"])
def test_document_evidence_requires_a_bracketed_reference(sources, content):
    with pytest.raises(ValueError, match="omitted exact source citations"):
        validate_document_citations(content, sources)


@pytest.mark.parametrize("sources,content", [
    ([], "Self-contained code explanation [index]"),
    ([{"source_kind": "web", "source_id": "web-1", "url": "https://example.com/ref"}],
     "Web evidence https://example.com/ref"),
])
def test_no_document_evidence_does_not_require_document_citations(sources, content):
    assert validate_document_citations(content, sources) is None


def test_fabricated_document_reference_is_rejected_without_document_evidence():
    with pytest.raises(ValueError, match="exact supplied IDs"):
        validate_document_citations("Invented [raft.pdf:p5:c4]", [])


def test_matching_id_on_web_source_is_not_document_evidence():
    with pytest.raises(ValueError, match="exact supplied IDs"):
        validate_document_citations("Claim [raft.pdf:p5:c4]", [
            {"source_kind": "web", "source_id": "raft.pdf:p5:c4"},
        ])


@pytest.mark.parametrize("content,expected", [
    ("Claim [raft.pdf:p5:c4, raft.pdf:p5:c5].",
     "Claim [raft.pdf:p5:c4] [raft.pdf:p5:c5]."),
    ("Claim [raft.pdf:p5:c4,\n raft.pdf:p5:c5].",
     "Claim [raft.pdf:p5:c4] [raft.pdf:p5:c5]."),
    ("Claim [raft.pdf:p5:c4, Practical Byzantine Fault Tolerance.pdf:p3:c6].",
     "Claim [raft.pdf:p5:c4] [Practical Byzantine Fault Tolerance.pdf:p3:c6]."),
    ("[Note] Claim [raft.pdf:p5:c4, raft.pdf:p5:c5]\nhttps://example.com/ref",
     "[Note] Claim [raft.pdf:p5:c4] [raft.pdf:p5:c5]\nhttps://example.com/ref"),
])
def test_normalization_splits_only_supplied_full_ids(sources, content, expected):
    original = deepcopy(sources)

    normalized = normalize_document_citations(content, sources)

    assert normalized == expected
    assert validate_document_citations(normalized, sources) is None
    assert normalize_document_citations(normalized, sources) == normalized
    assert sources == original


@pytest.mark.parametrize("reference", [
    "raft.pdf:p5:c4, raft.pdf:p99:c99",
    "raft.pdf:p5:c4-c5",
    "raft.pdf:p5:c4, c5",
    "raft.pdf:p5:c4,",
    "raft.pdf:p5:c4, web-1",
    "raft.pdf:p5:c4, RAFT.pdf:p5:c5",
])
def test_normalization_leaves_invalid_groups_for_validation(sources, reference):
    content = f"Valid [raft.pdf:p5:c4]. Invalid [{reference}]"

    normalized = normalize_document_citations(content, sources)

    assert normalized == content
    with pytest.raises(ValueError, match="exact supplied IDs"):
        validate_document_citations(normalized, sources)


def test_normalization_does_not_supply_missing_citations(sources):
    content = "Finding without references"
    normalized = normalize_document_citations(content, sources)

    assert normalized == content
    with pytest.raises(ValueError, match="omitted exact source citations"):
        validate_document_citations(normalized, sources)


def test_normalization_preserves_exact_id_containing_comma():
    sources = [{"source_id": "Paper, revised.pdf:p2:c1", "source_kind": "document"}]
    content = "Claim [Paper, revised.pdf:p2:c1]"

    assert normalize_document_citations(content, sources) == content
    assert validate_document_citations(content, sources) is None


@pytest.mark.parametrize("sources", [
    [],
    [{"source_id": "raft.pdf:p5:c4", "source_kind": "web"},
     {"source_id": "raft.pdf:p5:c5", "source_kind": "web"}],
])
def test_normalization_does_not_accept_groups_without_document_evidence(sources):
    content = "Claim [raft.pdf:p5:c4, raft.pdf:p5:c5]"

    assert normalize_document_citations(content, sources) == content
    with pytest.raises(ValueError, match="exact supplied IDs"):
        validate_document_citations(content, sources)


@pytest.mark.parametrize("content", [
    "Finding [https://example.com/ref]",
    "Finding https://example.com/ref.",
    "Finding [Reference](https://example.com/ref)",
])
def test_web_citations_accept_only_supplied_urls(sources, content):
    assert validate_web_citations(content, sources) is None


@pytest.mark.parametrize("content", [
    "Finding [https://example.com/not-retrieved]",
    "Finding https://example.com/ref#invented-section",
    "Valid https://example.com/ref and invalid https://example.com/other",
    "Finding [https://example.com/ref?invented=1]",
])
def test_web_citations_reject_unsupplied_urls_even_with_valid_reference(sources, content):
    with pytest.raises(ValueError, match="exact supplied URLs"):
        validate_web_citations(content, sources)


def test_web_evidence_requires_inline_url_before_appendix(sources):
    with pytest.raises(ValueError, match="omitted exact source citations"):
        validate_web_citations("Finding [web-1]", sources)


def test_code_example_urls_are_not_treated_as_evidence():
    text = 'Example:\n```python\nendpoint = "https://example.com/api"\n```\nUse `https://example.com/other` as a placeholder.'
    assert validate_web_citations(text, [], code=True) is None
    with pytest.raises(ValueError, match="exact supplied URLs"):
        validate_web_citations(text, [])
    with pytest.raises(ValueError, match="exact supplied URLs"):
        validate_web_citations(text + " Cite https://example.com/unretrieved", [], code=True)


def test_url_in_code_does_not_satisfy_prose_citation_requirement(sources):
    with pytest.raises(ValueError, match="omitted exact source citations"):
        validate_web_citations('```python\nurl = "https://example.com/ref"\n```', sources, code=True)
