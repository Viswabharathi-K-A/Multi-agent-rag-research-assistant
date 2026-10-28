"""Search the web using Tavily Remote MCP."""

import asyncio
import json
import logging
import re
from urllib.parse import urlencode, urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.config import Settings, get_settings


class RetrievalError(Exception):
    """A safe error message for a failed Tavily search."""


def redact_log(record: logging.LogRecord) -> bool:
    """Suppress SDK log records that could expose the Tavily URL or key."""
    text = record.getMessage() + (record.exc_text or "")
    if record.exc_info:
        text += logging.Formatter().formatException(record.exc_info)
    text = text.lower()
    return "mcp.tavily.com" not in text and "tavilyapikey" not in text


# The assignment uses URL authentication, so SDK request logs need protection.
for logger_name in ("httpx2", "mcp.client.streamable_http"):
    logging.getLogger(logger_name).addFilter(redact_log)


def normalize_domains(allowed_domains: list[str] | None) -> list[str]:
    """Accept hostnames only; never silently discard an invalid restriction."""
    domains = []
    for domain in allowed_domains or []:
        domain = domain.strip().lower().rstrip(".")
        if not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in domain.split(".")):
            raise RetrievalError("Allowed domains must be hostnames without URLs or paths")
        if domain not in domains:
            domains.append(domain)
    return domains


def url_matches_domains(url: str, domains: list[str]) -> bool:
    """Match an exact hostname or its subdomains, never lookalike suffixes."""
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return not domains or any(host == domain or host.endswith("." + domain) for domain in domains)


def extract_sources(response, limit: int, allowed_domains: list[str] | None = None) -> list[dict]:
    """Preserve usable evidence with exact URLs as stable, cross-search IDs."""
    if response.is_error:
        raise RetrievalError("Tavily search failed")

    data = response.structured_content
    if data is None:
        for block in response.content:
            if block.type != "text":
                continue
            try:
                candidate = json.loads(block.text)
            except ValueError:
                continue
            if isinstance(candidate, dict) and "results" in candidate:
                data = candidate
                break

    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise RetrievalError("Invalid Tavily search results")

    domains = normalize_domains(allowed_domains)
    sources = []
    seen_urls = set()
    for item in data["results"]:
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        title = item.get("title", "")
        content = item.get("content", item.get("snippet", ""))
        if not all(isinstance(value, str) for value in (url, title, content)):
            continue
        try:
            parsed_url = urlsplit(url)
            valid_url = parsed_url.scheme in ("http", "https") and bool(parsed_url.hostname)
        except ValueError:
            valid_url = False
        if not valid_url or url in seen_urls or not content.strip():
            continue
        if not url_matches_domains(url, domains):
            continue

        seen_urls.add(url)
        sources.append({
            "source_id": url,
            "title": title[:500],
            "url": url,
            "content": content[:6000],
            "metadata": {
                key: item[key]
                for key in ("score", "published_date", "author")
                if key in item
            },
        })
        if len(sources) >= limit:
            break

    if data["results"] and not sources and domains:
        raise RetrievalError("Tavily returned no usable sources from the allowed domains")
    if data["results"] and not sources:
        raise RetrievalError("Tavily returned no usable sources")
    return sources


async def search_web(
    query: str, settings: Settings | None = None,
    *, allowed_domains: list[str] | None = None,
) -> tuple[str, list[dict]]:
    """Connect, discover Tavily search, invoke it, and return its evidence."""
    settings = settings or get_settings()
    if not settings.tavily_api_key or not settings.tavily_api_key.strip():
        raise RetrievalError("Tavily API key is missing")
    if not query.strip():
        raise RetrievalError("Search query cannot be empty")
    domains = normalize_domains(allowed_domains)

    url = "https://mcp.tavily.com/mcp/?" + urlencode({
        "tavilyApiKey": settings.tavily_api_key,
    })
    try:
        async with asyncio.timeout(settings.tavily_timeout_seconds):
            async with streamable_http_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    search_tool = None
                    for tool in tools.tools:
                        if tool.name not in ("tavily_search", "tavily-search"):
                            continue
                        properties = tool.input_schema.get("properties", {})
                        if properties.get("query", {}).get("type") == "string":
                            search_tool = tool
                            break
                    if search_tool is None:
                        raise RetrievalError("Tavily search tool not found in returned tools")

                    properties = search_tool.input_schema.get("properties", {})
                    arguments = {"query": query}
                    if "search_depth" in properties:
                        arguments["search_depth"] = "basic"
                    if "max_results" in properties:
                        arguments["max_results"] = settings.tavily_max_results
                    domain_schema = properties.get("include_domains", {})
                    if domains and domain_schema.get("type") == "array" and domain_schema.get("items", {}).get("type") == "string":
                        arguments["include_domains"] = domains
                    for name in search_tool.input_schema.get("required", []):
                        if name not in arguments:
                            raise RetrievalError("Tavily search requires an unsupported argument")

                    response = await session.call_tool(search_tool.name, arguments=arguments)
                    sources = extract_sources(response, settings.tavily_max_results, domains)
                    return search_tool.name, sources
    except RetrievalError:
        raise
    except TimeoutError:
        raise RetrievalError("Tavily search timed out") from None
    except Exception:
        raise RetrievalError("Tavily MCP request failed") from None
