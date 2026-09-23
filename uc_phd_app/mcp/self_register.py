"""Write this app's own ``mcp.json`` so aw-mcp-gateway's app-scan
(``scan_app_mcp_servers()``, reading ``<installed-app-dir>/mcp.json``)
discovers the ``/mcp`` endpoint (``http_handler.py``) without any manual
wiring — ported from ``aw-app-whiteboard``'s ``whiteboard_app/mcp/
self_register.py`` (S4 Architect decision: whiteboard, not ``aw-app-kb``, is
the Tier-1 precedent).

Tier-1 vs Tier-2 difference: a Tier-2 app is its OWN container, so it needs
``AW_APP_SELF_HOST`` (injected by ``ContainerSupervisor.start()``) to tell
sibling containers its own network alias. A Tier-1 app IS the aw-workspace
process — ``socket.gethostname()`` from inside it returns the exact same
value ``ContainerSupervisor`` injects into sibling containers as
``AW_WORKSPACE_HOST`` (see ``src/apps/containers.py``), so no extra env var
is needed here.

Tier-1 routes are also IdentityGuard-gated by default (unlike Tier-2, which
is reverse-proxied 1:1 with no such gate) — the registered entry's
``headers`` field carries ``X-Api-Key`` so aw-mcp-gateway's ``HttpUpstream``
authenticates the same way any other app/MCP would (see
``docs/app-workspace-api-auth.md`` in ``aw-app-template``).
"""

from __future__ import annotations

import json
import logging
import os
import socket

log = logging.getLogger("aw_apps.uc_phd")

MCP_SERVER_NAME = "phd_knowledge_base"


def _mcp_json_path(package_dir: str) -> str:
    return os.path.join(package_dir, "mcp.json")


def register_self(package_dir: str, port: int) -> None:
    """Best-effort; a bare dev run with no package_dir on a scanned root
    simply no-ops (nothing to write into, nothing breaks)."""
    if not os.path.isdir(package_dir):
        return

    host = socket.gethostname()
    api_key = os.environ.get("AW_WORKSPACE_API_KEY")
    entry: dict = {
        "type": "http",
        "url": f"http://{host}:{port}/api/apps/aw-app-uc-phd/mcp",
        "enabled": True,
    }
    if api_key:
        entry["headers"] = {"X-Api-Key": api_key}

    path = _mcp_json_path(package_dir)
    data: dict = {"mcpServers": {}}
    try:
        with open(path) as f:
            existing = json.load(f)
        if isinstance(existing, dict) and isinstance(existing.get("mcpServers"), dict):
            data = existing
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if data["mcpServers"].get(MCP_SERVER_NAME) == entry:
        return
    data["mcpServers"][MCP_SERVER_NAME] = entry
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        log.info("registered self as %r in %s (%s)", MCP_SERVER_NAME, path, entry["url"])
    except OSError as e:
        log.warning("could not write %s: %s", path, e)
