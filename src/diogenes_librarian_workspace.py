"""Same-host adapter for Librarian's versioned browser API.

Diogenes owns authentication and presentation. Librarian continues to own the
OKF bundle, delegated agent, traces, graph, and proposal lifecycle. This
adapter deliberately exposes named operations instead of a generic URL proxy.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values
import httpx


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
_PATH_RE = re.compile(r"^/[^\r\n\0]{1,1000}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,240}$")
_QUERY_RE = re.compile(r"^[^\r\n\0]{1,1000}$")
_GUIDED_MODES = {"add", "update", "maintain", "import"}


class LibrarianWorkspaceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _services_root() -> Path:
    configured = os.environ.get("ULYSSES_MICROSERVICES_ROOT", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / "Hermes"
    if not path.is_absolute():
        raise LibrarianWorkspaceError(
            "ULYSSES_MICROSERVICES_ROOT must be absolute",
            status_code=500,
        )
    return path.resolve()


def _librarian_api_url() -> str:
    configured = os.environ.get(
        "DIOGENES_LIBRARIAN_URL",
        "http://127.0.0.1:3800",
    ).strip()
    parsed = urlsplit(configured)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _LOOPBACK_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise LibrarianWorkspaceError(
            "DIOGENES_LIBRARIAN_URL must be an HTTP loopback URL",
            status_code=500,
        )
    try:
        port = parsed.port or 3800
    except ValueError as exc:
        raise LibrarianWorkspaceError(
            "DIOGENES_LIBRARIAN_URL has an invalid port",
            status_code=500,
        ) from exc
    if not 1 <= port <= 65535:
        raise LibrarianWorkspaceError(
            "DIOGENES_LIBRARIAN_URL has an invalid port",
            status_code=500,
        )
    path = parsed.path.rstrip("/")
    if path not in {"", "/api"}:
        raise LibrarianWorkspaceError(
            "DIOGENES_LIBRARIAN_URL may only use the /api path",
            status_code=500,
        )
    return f"http://{parsed.hostname}:{port}/api"


def _librarian_token() -> str:
    configured = os.environ.get("DIOGENES_LIBRARIAN_TOKEN")
    if configured is not None:
        return configured.strip()
    env_path = _services_root() / "librarian" / ".env"
    if not env_path.is_file():
        return ""
    try:
        value = dotenv_values(env_path, encoding="utf-8-sig").get("AUTH_TOKEN")
    except (OSError, ValueError) as exc:
        raise LibrarianWorkspaceError(
            "Librarian's .env could not be read",
            status_code=500,
        ) from exc
    return str(value or "").strip()


class LibrarianWorkspaceClient:
    """Typed subset of Librarian's local HTTP contract."""

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or _librarian_api_url()).rstrip("/")
        self.token = _librarian_token() if token is None else token.strip()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        long_running: bool = False,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        timeout: httpx.Timeout | None = (
            None if long_running else httpx.Timeout(30.0, connect=2.0)
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    json=payload,
                    headers=headers,
                )
        except httpx.ConnectError as exc:
            raise LibrarianWorkspaceError(
                "Librarian is not running on the configured loopback port",
                status_code=503,
            ) from exc
        except httpx.TimeoutException as exc:
            raise LibrarianWorkspaceError(
                "Librarian did not answer the local request in time",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise LibrarianWorkspaceError(
                f"Librarian request failed: {exc}",
                status_code=502,
            ) from exc

        try:
            body = response.json()
        except ValueError:
            body = None
        if response.is_error:
            message = ""
            if isinstance(body, dict):
                message = str(body.get("error") or body.get("detail") or "")
            if not message:
                message = response.text.strip()[:500]
            raise LibrarianWorkspaceError(
                message or f"Librarian returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        if body is None:
            raise LibrarianWorkspaceError("Librarian returned invalid JSON")
        return body

    async def overview(self) -> dict[str, Any]:
        tree, validation, config, log, concept_types = await asyncio.gather(
            self._request("GET", "/tree"),
            self._request("GET", "/validate"),
            self._request("GET", "/config"),
            self._request("GET", "/log"),
            self._request("GET", "/types"),
        )
        return {
            "schema_version": "diogenes.librarian-workspace.v1",
            "tree": tree,
            "validation": validation,
            "config": config,
            "log": log,
            "types": concept_types,
            "contract": {
                "owner": "librarian",
                "transport": "same-host HTTP",
                "browser_token_exposed": False,
            },
        }

    async def concept(self, path: str) -> Any:
        if not _PATH_RE.fullmatch(path):
            raise LibrarianWorkspaceError("invalid concept path", status_code=400)
        return await self._request("GET", "/concept", params={"path": path})

    async def search(
        self,
        query: str,
        *,
        concept_type: str = "",
        tag: str = "",
    ) -> Any:
        query = query.strip()
        if not _QUERY_RE.fullmatch(query):
            raise LibrarianWorkspaceError(
                "search must contain 1 to 1000 single-line characters",
                status_code=400,
            )
        params: dict[str, str] = {"q": query}
        if concept_type.strip():
            params["type"] = concept_type.strip()[:120]
        if tag.strip():
            params["tag"] = tag.strip()[:120]
        return await self._request("GET", "/search", params=params)

    async def graph(self) -> Any:
        return await self._request("GET", "/graph")

    async def traces(self) -> Any:
        return await self._request("GET", "/traces")

    async def trace(self, trace_id: str) -> Any:
        if not _ID_RE.fullmatch(trace_id):
            raise LibrarianWorkspaceError("invalid trace ID", status_code=400)
        return await self._request("GET", "/trace", params={"id": trace_id})

    async def dreams(self) -> dict[str, Any]:
        proposals, status = await asyncio.gather(
            self._request("GET", "/dreams"),
            self._request("GET", "/dreams/status"),
        )
        return {"proposals": proposals, "status": status}

    async def dream(self, proposal_id: str) -> Any:
        if not _ID_RE.fullmatch(proposal_id):
            raise LibrarianWorkspaceError("invalid proposal ID", status_code=400)
        return await self._request("GET", f"/dreams/{proposal_id}")

    async def export_bundle(self) -> Any:
        return await self._request("GET", "/bundle/export")

    async def chat(self, messages: list[dict[str, Any]], *, model: str = "") -> Any:
        if not messages or len(messages) > 200:
            raise LibrarianWorkspaceError(
                "chat requires between 1 and 200 turns",
                status_code=400,
            )
        clean: list[dict[str, str]] = []
        for message in messages:
            role = str(message.get("role") or "")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                raise LibrarianWorkspaceError("invalid Librarian chat turn", status_code=400)
            if not content or len(content) > 250_000:
                raise LibrarianWorkspaceError("invalid Librarian chat content", status_code=400)
            clean.append({"role": role, "content": content})
        payload: dict[str, Any] = {"messages": clean}
        if model.strip():
            payload["model"] = model.strip()[:300]
        return await self._request(
            "POST",
            "/chat",
            payload=payload,
            long_running=True,
        )

    async def propose_dream(self) -> Any:
        return await self._request(
            "POST",
            "/dreams/propose",
            long_running=True,
        )

    async def guided_proposal(
        self,
        mode: str,
        *,
        content: str = "",
        suggested_path: str = "",
        instruction: str = "",
        focus: str = "",
        bundle: dict[str, Any] | None = None,
        strategy: str = "merge",
    ) -> Any:
        if mode not in _GUIDED_MODES:
            raise LibrarianWorkspaceError("invalid guided operation", status_code=400)
        payload: dict[str, Any] = {"mode": mode}
        if mode == "add":
            payload["content"] = _guided_text(content, "knowledge", required=True)
            if suggested_path:
                if not _PATH_RE.fullmatch(suggested_path):
                    raise LibrarianWorkspaceError("invalid suggested path", status_code=400)
                payload["suggestedPath"] = suggested_path
        elif mode == "update":
            payload["instruction"] = _guided_text(
                instruction,
                "update instruction",
                required=True,
            )
        elif mode == "maintain":
            payload["focus"] = _guided_text(focus, "maintenance focus")
        else:
            if not isinstance(bundle, dict):
                raise LibrarianWorkspaceError(
                    "import requires a Librarian JSON bundle",
                    status_code=400,
                )
            if strategy not in {"merge", "replace"}:
                raise LibrarianWorkspaceError("invalid import strategy", status_code=400)
            payload.update(bundle=bundle, strategy=strategy)
        return await self._request(
            "POST",
            "/dreams/guided",
            payload=payload,
            long_running=True,
        )

    async def dream_action(self, proposal_id: str, action: str) -> Any:
        if not _ID_RE.fullmatch(proposal_id):
            raise LibrarianWorkspaceError("invalid proposal ID", status_code=400)
        if action not in {"approve", "reject", "rollback"}:
            raise LibrarianWorkspaceError("invalid proposal action", status_code=400)
        return await self._request(
            "POST",
            f"/dreams/{proposal_id}/{action}",
            long_running=True,
        )


def _guided_text(value: str, label: str, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 250_000 or "\0" in value:
        raise LibrarianWorkspaceError(f"invalid {label}", status_code=400)
    cleaned = value.strip()
    if required and not cleaned:
        raise LibrarianWorkspaceError(f"{label} is required", status_code=400)
    return cleaned
