"""Repair unambiguous citation formatting and validate document references."""

import re


def normalize_document_citations(content: str, sources: list[dict]) -> str:
    """Split comma-separated groups only when every full ID is supplied.

    Preserve other text, including invalid references, for strict validation.
    Never expand ranges, infer abbreviated IDs, or modify source evidence.
    """
    allowed_ids = {
        source["source_id"] for source in sources
        if source.get("source_kind") == "document"
    }

    def normalize_match(match: re.Match) -> str:
        reference = match.group(1)
        if reference in allowed_ids or "," not in reference:
            return match.group(0)
        source_ids = [part.strip() for part in reference.split(",")]
        if all(source_id in allowed_ids for source_id in source_ids):
            return " ".join(f"[{source_id}]" for source_id in source_ids)
        return match.group(0)

    return re.sub(r"\[([^\]]+)\]", normalize_match, content)


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


def validate_web_citations(content: str, sources: list[dict], *, code: bool = False) -> None:
    """Check prose URLs against web evidence, without judging claim support.

    Code examples may contain arbitrary endpoint URLs, so Code can exclude
    fenced code and inline code from this check. Source URL fragments must also
    match exactly; a plausible documentation URL is not retrieved evidence.
    """
    if code:
        content = re.sub(r"```[\s\S]*?```|`[^`\n]*`", "", content)
    allowed_urls = {source["url"] for source in sources if source.get("source_kind") == "web"}
    found = False
    for match in re.finditer(r"https?://[^\s<>\[\]\"`]+", content, flags=re.IGNORECASE):
        url = match.group(0)
        if url not in allowed_urls:
            url = url.rstrip(".,;:!?)")
        if url not in allowed_urls:
            raise ValueError("Web citations must use exact supplied URLs")
        found = True
    if allowed_urls and not found:
        raise ValueError("Web-backed output omitted exact source citations")
