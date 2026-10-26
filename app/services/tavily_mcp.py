"""Search the web using Tavily Remote MCP."""

import asyncio
import json
import logging
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


def extract_sources(response, limit: int) -> list[dict]:
    """Read structured or JSON-text results and preserve usable evidence."""
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

        seen_urls.add(url)
        sources.append({
            "source_id": f"web-{len(sources) + 1}",
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

    if data["results"] and not sources:
        raise RetrievalError("Tavily returned no usable sources")
    return sources


async def search_web(
    query: str, settings: Settings | None = None,
) -> tuple[str, list[dict]]:
    """Connect, discover Tavily search, invoke it, and return its evidence."""
    settings = settings or get_settings()
    if not settings.tavily_api_key or not settings.tavily_api_key.strip():
        raise RetrievalError("Tavily API key is missing")
    if not query.strip():
        raise RetrievalError("Search query cannot be empty")

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
                    for name in search_tool.input_schema.get("required", []):
                        if name not in arguments:
                            raise RetrievalError("Tavily search requires an unsupported argument")

                    response = await session.call_tool(search_tool.name, arguments=arguments)
                    sources = extract_sources(response, settings.tavily_max_results)
                    return search_tool.name, sources
    except RetrievalError:
        raise
    except TimeoutError:
        raise RetrievalError("Tavily search timed out") from None
    except Exception:
        raise RetrievalError("Tavily MCP request failed") from None
