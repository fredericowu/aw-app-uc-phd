"""MCP server ``phd_knowledge_base``, exposed over Streamable HTTP (POST
/mcp) — same shape as ``aw-app-whiteboard``'s ``mcp/http_handler.py``
(JSON-RPC 2.0, the wire format aw-mcp-gateway's ``HttpUpstream`` speaks).

This is a Tier-1 (in-process) app, so the gateway (a sibling container)
cannot spawn a process inside it — the tool surface is served over HTTP
instead of stdio. See ``self_register.py`` for how the gateway discovers
this endpoint, and ``mcp/tools.py`` for the actual implementations: this
module only does JSON-RPC framing and error shaping, no business logic.
"""
from __future__ import annotations

import asyncio
import json

from .. import store as store_mod
from . import tools

TOOLS_SCHEMA = [
    {
        "name": "search_phd_theses",
        "description": (
            "Semantic search over the 18 UC DEI / CISUC PhD theses indexed from "
            "Estudo Geral. Returns ranked excerpts, each carrying `handle`, "
            "`title`, `authors`, `source_url` and the retrieval fields "
            "(`similarity`, `distance`, `snippet`, `full_text`), plus a top-level "
            "`relevance` block explaining these are nearest-passage matches, not "
            "a calibrated relevant/not-relevant verdict."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query."},
                "limit": {"type": "integer", "description": "Max results. Default 5."},
                "year": {"type": "string", "description": "Restrict to theses from this year."},
                "author": {"type": "string", "description": "Restrict to theses whose author name contains this (case-insensitive)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_phd_thesis",
        "description": (
            "Full record for one thesis by handle: title, authors, supervisors, "
            "research group(s), year, rights, both abstracts (PT/EN), the "
            "extracted body text, and `source_url` to the Estudo Geral item page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "Thesis handle, e.g. '10316/119520'."},
            },
            "required": ["handle"],
        },
    },
    {
        "name": "list_phd_theses",
        "description": (
            "Enumerate the thesis corpus (all 18) with no embedding cost — "
            "handle, title, authors, year, research group(s), source_url. "
            "Optionally filter by year or research group code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "year": {"type": "string", "description": "Restrict to this year."},
                "group": {"type": "string", "description": "Restrict to this research group code."},
                "limit": {"type": "integer", "description": "Max rows. Default 50."},
            },
        },
    },
]


def _ok(req_id, payload) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": text}], "isError": False}}


def _err(req_id, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": text}], "isError": True}}


async def handle_request(request: dict, *, store: store_mod.VectorStore) -> dict | None:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "phd_knowledge_base", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS_SCHEMA}}
    if method != "tools/call":
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    name = request.get("params", {}).get("name", "")
    args = request.get("params", {}).get("arguments", {}) or {}

    try:
        if name == "search_phd_theses":
            query = args.get("query")
            if not query:
                return _err(req_id, "query is required")
            # fastembed/ONNX embedding is synchronous CPU work — see
            # api/search.py's identical asyncio.to_thread for why this must
            # not run inline on the event loop.
            payload = await asyncio.to_thread(
                tools.search_phd_theses, store, query,
                limit=int(args.get("limit") or 5), year=args.get("year"), author=args.get("author"),
            )
        elif name == "get_phd_thesis":
            handle = args.get("handle")
            if not handle:
                return _err(req_id, "handle is required")
            payload = tools.get_phd_thesis(handle)
        elif name == "list_phd_theses":
            payload = tools.list_phd_theses(
                year=args.get("year"), group=args.get("group"), limit=int(args.get("limit") or 50),
            )
        else:
            return _err(req_id, f"Unknown tool: {name}")
    except tools.ToolError as exc:
        return _err(req_id, str(exc))

    return _ok(req_id, payload)
