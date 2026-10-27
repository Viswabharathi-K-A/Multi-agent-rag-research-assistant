"""Deterministic citation checks with no retrieval or model calls."""

from copy import deepcopy

import pytest

from app.agents.citations import validate_document_citations


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
