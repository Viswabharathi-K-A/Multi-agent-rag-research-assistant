"""Validate bracketed PDF chunk references against supplied document evidence."""

import re


def validate_document_citations(content: str, sources: list[dict]) -> None:
    """Raise ValueError for missing or invalid document references.

    Recognizes bracketed PDF chunk references containing `.pdf:p`. Each must
    exactly match one supplied document source_id. Document-backed output must
    include at least one such reference. Other brackets and web URLs are ignored.
    This checks reference identity, not whether evidence supports each claim.
    """
    allowed_ids = {
        source["source_id"] for source in sources
        if source.get("source_kind") == "document"
    }
    found = False
    for reference in re.findall(r"\[([^\]]+)\]", content):
        if reference in allowed_ids:
            found = True
        elif ".pdf:p" in reference.lower():
            raise ValueError("Document citations must use exact supplied IDs in separate brackets")
    if allowed_ids and not found:
        raise ValueError("Document-backed output omitted exact source citations")
