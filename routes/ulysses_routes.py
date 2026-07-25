"""Admin-only, read-only Ulysses control-plane routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from core.middleware import require_admin
from src.sandwich_runtime import observe_sandwich_installation
from src.ulysses_chroma import collect_chroma_persistence
from src.ulysses_colibri import collect_colibri_providers
from src.ulysses_catalog import default_runtime_registry
from src.ulysses_discovery import HostDiscoverySnapshot, collect_host_discovery
from src.ulysses_hermes import collect_hermes_adoption
from src.ulysses_hermes_control import HermesControl
from src.ulysses_jobs import (
    RuntimeJobConfirmationError,
    RuntimeJobConflict,
    RuntimeJobError,
)
from src.ulysses_readiness import collect_switchover_readiness
from src.ulysses_topology import build_topology_report


class HermesAdoptionApplyRequest(BaseModel):
    confirmation_phrase: str
    expected_source_root: str
    expected_gateway_unit: str


class HermesLifecyclePlanRequest(BaseModel):
    action: str


class RuntimeJobExecuteRequest(BaseModel):
    confirmation_token: str
    confirmation_phrase: str


def _job_http_error(exc: RuntimeJobError) -> HTTPException:
    if isinstance(exc, RuntimeJobConflict):
        return HTTPException(409, str(exc))
    if isinstance(exc, RuntimeJobConfirmationError):
        return HTTPException(400, str(exc))
    return HTTPException(400, str(exc))


def setup_ulysses_routes(
    *,
    collector: Callable[[], HostDiscoverySnapshot] = collect_host_discovery,
    chroma_collector: Callable[[], dict] = collect_chroma_persistence,
    hermes_collector: Callable[[], dict] = collect_hermes_adoption,
    colibri_collector: Callable[[], dict] = collect_colibri_providers,
    hermes_control_factory: Callable[[], HermesControl] = HermesControl,
    readiness_collector: Callable[
        [dict, dict, dict], dict
    ] = collect_switchover_readiness,
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

    @router.get("/hermes/adoption")
    async def get_hermes_adoption(request: Request) -> dict:
        require_admin(request)
        report = await run_in_threadpool(hermes_collector)
        return hermes_control_factory().decorate_report(report)

    @router.get("/colibri/providers")
    async def get_colibri_providers(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(colibri_collector)

    @router.post("/hermes/adoption/apply")
    async def apply_hermes_adoption(
        request: Request,
        body: HermesAdoptionApplyRequest,
    ) -> dict:
        require_admin(request)
        report = await run_in_threadpool(hermes_collector)
        try:
            return await run_in_threadpool(
                hermes_control_factory().apply_adoption,
                report,
                confirmation_phrase=body.confirmation_phrase,
                expected_source_root=body.expected_source_root,
                expected_gateway_unit=body.expected_gateway_unit,
            )
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/hermes/jobs/plan")
    async def plan_hermes_lifecycle(
        request: Request,
        body: HermesLifecyclePlanRequest,
    ) -> dict:
        require_admin(request)
        report = await run_in_threadpool(hermes_collector)
        try:
            plan, token = await run_in_threadpool(
                hermes_control_factory().create_lifecycle_plan,
                report,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.get("/jobs")
    async def list_runtime_jobs(request: Request, limit: int = 50) -> dict:
        require_admin(request)
        jobs = await run_in_threadpool(
            hermes_control_factory().jobs.list,
            limit=limit,
        )
        return {"schema_version": "ulysses.runtime-jobs.v1", "jobs": jobs}

    @router.get("/readiness")
    async def get_switchover_readiness(request: Request) -> dict:
        require_admin(request)

        def collect() -> dict:
            snapshot = collector()
            registry = default_runtime_registry()
            sandwich = observe_sandwich_installation()
            topology = build_topology_report(registry, snapshot, sandwich)
            chroma = chroma_collector()
            hermes = hermes_control_factory().decorate_report(
                hermes_collector()
            )
            return readiness_collector(topology, chroma, hermes)

        return await run_in_threadpool(collect)

    @router.get("/jobs/{job_id}")
    async def get_runtime_job(request: Request, job_id: str) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                hermes_control_factory().jobs.get,
                job_id,
            )
        except RuntimeJobError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/jobs/{job_id}/log")
    async def get_runtime_job_log(
        request: Request,
        job_id: str,
        max_chars: int = 16000,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                hermes_control_factory().jobs.read_log,
                job_id,
                max_chars=max_chars,
            )
        except RuntimeJobError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/jobs/{job_id}/execute")
    async def execute_runtime_job(
        request: Request,
        job_id: str,
        body: RuntimeJobExecuteRequest,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                hermes_control_factory().jobs.execute,
                job_id,
                confirmation_token=body.confirmation_token,
                confirmation_phrase=body.confirmation_phrase,
            )
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    return router
