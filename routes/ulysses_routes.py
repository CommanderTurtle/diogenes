"""Admin-only, read-only Ulysses control-plane routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from core.middleware import require_admin
from src.sandwich_runtime import observe_sandwich_installation
from src.ulysses_chroma import collect_chroma_persistence
from src.ulysses_catalog import default_runtime_registry
from src.ulysses_discovery import HostDiscoverySnapshot, collect_host_discovery
from src.ulysses_topology import build_topology_report


def setup_ulysses_routes(
    *,
    collector: Callable[[], HostDiscoverySnapshot] = collect_host_discovery,
    chroma_collector: Callable[[], dict] = collect_chroma_persistence,
) -> APIRouter:
    router = APIRouter(prefix="/api/ulysses", tags=["ulysses"])

    @router.get("/topology")
    async def get_topology(request: Request) -> dict:
        require_admin(request)
        snapshot = await run_in_threadpool(collector)
        registry = default_runtime_registry()
        sandwich = observe_sandwich_installation()
        return build_topology_report(registry, snapshot, sandwich)

    @router.get("/chroma/persistence")
    async def get_chroma_persistence(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(chroma_collector)

    return router
