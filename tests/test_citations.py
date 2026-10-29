"""Accept retrieved sources and reject invented references."""

import pytest

from app.agents.citations import validate_document_citations, validate_web_citations


def test_only_supplied_citations_are_accepted():
    sources = [
        {"source_id": "raft.pdf:p1:c1", "source_kind": "document"},
        {"source_id": "web-1", "source_kind": "web", "url": "https://example.com/raft"},
    ]

    validate_document_citations("Evidence [raft.pdf:p1:c1]", sources)
    validate_web_citations("Evidence https://example.com/raft", sources)

    with pytest.raises(ValueError, match="exact supplied IDs"):
        validate_document_citations("Evidence [invented.pdf:p1:c1]", sources)
    with pytest.raises(ValueError, match="exact supplied URLs"):
        validate_web_citations("Evidence https://example.com/invented", sources)
