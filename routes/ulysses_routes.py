"""Admin-only Diogenes host-observation and fixed-action routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core.middleware import require_admin
from src.diogenes_docker_projects import (
    DockerProjectControl,
    DockerResourceControl,
    collect_docker_projects,
    read_docker_container_log,
    read_docker_documents,
    read_docker_log,
    save_docker_document,
)
from src.diogenes_skill_auditor import SkillAuditorControl, collect_skills
from src.sandwich_runtime import (
    collect_sandwich_status,
    observe_sandwich_installation,
)
from src.ulysses_chroma import collect_chroma_persistence
from src.ulysses_colibri import collect_colibri_providers
from src.ulysses_colibri_command import (
    ColibriCommandError,
    render_colibri_serve_command,
)
from src.ulysses_colibri_control import ColibriControl
from src.ulysses_catalog import default_runtime_registry
from src.ulysses_discovery import HostDiscoverySnapshot, collect_host_discovery
from src.ulysses_hermes import collect_hermes_adoption
from src.ulysses_hermes_control import HermesControl
from src.ulysses_hermes_stack import HermesStackControl
from src.ulysses_jobs import (
    RuntimeJobConfirmationError,
    RuntimeJobConflict,
    RuntimeJobError,
)
from src.ulysses_prism import collect_prism_providers
from src.ulysses_prism_command import (
    PrismCommandError,
    render_prism_serve_command,
)
from src.ulysses_prism_control import PrismControl
from src.ulysses_runtime_management import (
    ManagedRuntimeControl,
    collect_managed_runtimes,
    read_runtime_documents,
    read_runtime_log,
    save_runtime_document,
)
from src.ulysses_sandwich_control import SandwichControl
from src.ulysses_topology import build_topology_report
from src.tmux_ownership import list_owned_sessions, shutdown_owned_sessions


class HermesAdoptionApplyRequest(BaseModel):
    confirmation_phrase: str
    expected_source_root: str
    expected_gateway_unit: str


class HermesLifecyclePlanRequest(BaseModel):
    action: str


class HermesStackPlanRequest(BaseModel):
    action: str


class HermesMcpPlanRequest(BaseModel):
    action: str
    name: str
    command: str = ""
    args: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)


class RuntimeJobExecuteRequest(BaseModel):
    confirmation_token: str
    confirmation_phrase: str


class ColibriCommandRequest(BaseModel):
    runtime_id: str
    settings: dict[str, str | bool | int | float | None]


class ColibriLifecyclePlanRequest(BaseModel):
    runtime_id: str
    action: str


class PrismCommandRequest(BaseModel):
    model_id: str
    settings: dict[str, str | bool | int | float | None]


class PrismLifecyclePlanRequest(BaseModel):
    runtime_id: str
    action: str


class ManagedRuntimePlanRequest(BaseModel):
    runtime_id: str
    action: str


class DockerProjectPlanRequest(BaseModel):
    project_id: str
    action: str
    services: list[str] = Field(default_factory=list)


class DockerResourcePlanRequest(BaseModel):
    kind: str
    resource_id: str
    action: str


class SandwichLifecyclePlanRequest(BaseModel):
    action: str


class SkillAuditorPlanRequest(BaseModel):
    skill_id: str
    action: str


class RuntimeDocumentSaveRequest(BaseModel):
    expected_sha256: str | None = None
    content: str
    confirmation_phrase: str


class DockerDocumentSaveRequest(BaseModel):
    expected_sha256: str
    content: str
    confirmation_phrase: str


class TmuxShutdownRequest(BaseModel):
    confirmation_phrase: str
    include_agents: bool = False
    identities: list[str] | None = None


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
    prism_collector: Callable[[], dict] = collect_prism_providers,
    hermes_control_factory: Callable[[], HermesControl] = HermesControl,
    hermes_stack_control_factory: Callable[
        [], HermesStackControl
    ] = HermesStackControl,
    colibri_control_factory: Callable[[], ColibriControl] = ColibriControl,
    prism_control_factory: Callable[[], PrismControl] = PrismControl,
    runtime_control_factory: Callable[[], ManagedRuntimeControl] = ManagedRuntimeControl,
    docker_control_factory: Callable[
        [], DockerProjectControl
    ] = DockerProjectControl,
    docker_resource_control_factory: Callable[
        [], DockerResourceControl
    ] = DockerResourceControl,
    sandwich_control_factory: Callable[[], SandwichControl] = SandwichControl,
    skill_auditor_control_factory: Callable[
        [], SkillAuditorControl
    ] = SkillAuditorControl,
    sandwich_collector: Callable[[], dict] = collect_sandwich_status,
    managed_runtime_collector: Callable[[], dict] = collect_managed_runtimes,
    docker_project_collector: Callable[[], dict] = collect_docker_projects,
) -> APIRouter:
    router = APIRouter(prefix="/api/odysseus", tags=["odysseus"])

    @router.get("/topology")
    async def get_topology(request: Request) -> dict:
        require_admin(request)
        snapshot = await run_in_threadpool(collector)
        registry = default_runtime_registry()
        sandwich = observe_sandwich_installation()
        return build_topology_report(registry, snapshot, sandwich)

    @router.get("/sandwich")
    async def get_sandwich_status(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(sandwich_collector)

    @router.get("/chroma/persistence")
    async def get_chroma_persistence(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(chroma_collector)

    @router.get("/tmux/owned")
    async def get_owned_tmux_sessions(request: Request) -> dict:
        require_admin(request)
        sessions = await run_in_threadpool(list_owned_sessions)
        return {
            "schema_version": "diogenes.tmux-inventory.v1",
            "sessions": [session.as_dict() for session in sessions],
            "external_policy": (
                "Only explicitly tagged Diogenes sessions are listed. "
                "Legacy, adopted, and external tmux sessions are excluded."
            ),
        }

    @router.post("/tmux/shutdown")
    async def shutdown_tmux_sessions(
        request: Request,
        body: TmuxShutdownRequest,
    ) -> dict:
        require_admin(request)
        if body.confirmation_phrase != "STOP DIOGENES SESSIONS":
            raise HTTPException(400, "confirmation phrase mismatch")
        return await run_in_threadpool(
            shutdown_owned_sessions,
            include_agents=body.include_agents,
            identities=set(body.identities) if body.identities is not None else None,
        )

    @router.get("/hermes/adoption")
    async def get_hermes_adoption(request: Request) -> dict:
        require_admin(request)
        report = await run_in_threadpool(hermes_collector)
        return hermes_control_factory().decorate_report(report)

    @router.get("/hermes/stack")
    async def get_hermes_stack(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(
            hermes_stack_control_factory().observe
        )

    @router.get("/colibri/providers")
    async def get_colibri_providers(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(colibri_collector)

    @router.get("/prism/providers")
    async def get_prism_providers(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(prism_collector)

    @router.get("/runtimes")
    async def get_managed_runtimes(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(managed_runtime_collector)

    @router.get("/docker/projects")
    async def get_docker_projects(request: Request) -> dict:
        require_admin(request)
        return await run_in_threadpool(docker_project_collector)

    @router.get("/skills/audit")
    async def get_skill_audit(request: Request) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(collect_skills)
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/docker/projects/{project_id}/documents")
    async def get_docker_project_documents(
        request: Request,
        project_id: str,
        reveal: bool = False,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                read_docker_documents,
                project_id,
                reveal=reveal,
            )
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put(
        "/docker/projects/{project_id}/documents/{document_id}"
    )
    async def put_docker_project_document(
        request: Request,
        project_id: str,
        document_id: str,
        body: DockerDocumentSaveRequest,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                save_docker_document,
                project_id,
                document_id,
                expected_sha256=body.expected_sha256,
                content=body.content,
                confirmation_phrase=body.confirmation_phrase,
            )
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.get("/docker/projects/{project_id}/log")
    async def get_docker_project_log(
        request: Request,
        project_id: str,
        service: str | None = None,
        tail: int = 300,
        max_chars: int = 30000,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                read_docker_log,
                project_id,
                service=service,
                tail=tail,
                max_chars=max_chars,
            )
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/docker/containers/{container_id}/log")
    async def get_docker_container_log(
        request: Request,
        container_id: str,
        tail: int = 300,
        max_chars: int = 30000,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                read_docker_container_log,
                container_id,
                tail=tail,
                max_chars=max_chars,
            )
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/docker/jobs/plan")
    async def plan_docker_project(
        request: Request,
        body: DockerProjectPlanRequest,
    ) -> dict:
        require_admin(request)
        try:
            plan, token = await run_in_threadpool(
                docker_control_factory().create_plan,
                project_id=body.project_id,
                action=body.action,
                services=body.services,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/docker/resources/jobs/plan")
    async def plan_docker_resource(
        request: Request,
        body: DockerResourcePlanRequest,
    ) -> dict:
        require_admin(request)
        try:
            plan, token = await run_in_threadpool(
                docker_resource_control_factory().create_plan,
                kind=body.kind,
                resource_id=body.resource_id,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.get("/runtimes/{runtime_id}/documents")
    async def get_runtime_documents(
        request: Request,
        runtime_id: str,
        reveal: bool = False,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                read_runtime_documents,
                runtime_id,
                reveal=reveal,
            )
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/runtimes/{runtime_id}/documents/{document_id}")
    async def put_runtime_document(
        request: Request,
        runtime_id: str,
        document_id: str,
        body: RuntimeDocumentSaveRequest,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                save_runtime_document,
                runtime_id,
                document_id,
                expected_sha256=body.expected_sha256,
                content=body.content,
                confirmation_phrase=body.confirmation_phrase,
            )
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.get("/runtimes/{runtime_id}/log")
    async def get_managed_runtime_log(
        request: Request,
        runtime_id: str,
        max_chars: int = 20000,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                read_runtime_log,
                runtime_id,
                max_chars=max_chars,
            )
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/runtimes/jobs/plan")
    async def plan_managed_runtime(
        request: Request,
        body: ManagedRuntimePlanRequest,
    ) -> dict:
        require_admin(request)
        try:
            plan, token = await run_in_threadpool(
                runtime_control_factory().create_plan,
                runtime_id=body.runtime_id,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/skills/jobs/plan")
    async def plan_skill_auditor_action(
        request: Request,
        body: SkillAuditorPlanRequest,
    ) -> dict:
        require_admin(request)
        try:
            plan, token = await run_in_threadpool(
                skill_auditor_control_factory().create_plan,
                skill_id=body.skill_id,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/sandwich/jobs/plan")
    async def plan_sandwich_lifecycle(
        request: Request,
        body: SandwichLifecyclePlanRequest,
    ) -> dict:
        require_admin(request)
        status = await run_in_threadpool(sandwich_collector)
        try:
            plan, token = await run_in_threadpool(
                sandwich_control_factory().create_plan,
                status,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/colibri/command")
    async def render_colibri_command(
        request: Request,
        body: ColibriCommandRequest,
    ) -> dict:
        require_admin(request)
        try:
            command = await run_in_threadpool(
                render_colibri_serve_command,
                body.runtime_id,
                body.settings,
            )
        except ColibriCommandError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "schema_version": "ulysses.colibri-command.v1",
            "runtime_id": body.runtime_id,
            "command": command,
            # The structured controls regenerate this command, but the final
            # textarea follows vanilla Odysseus and remains operator-editable.
            # /api/model/serve parses and canonicalizes it before execution.
            "editable": True,
        }

    @router.post("/colibri/jobs/plan")
    async def plan_colibri_lifecycle(
        request: Request,
        body: ColibriLifecyclePlanRequest,
    ) -> dict:
        require_admin(request)
        report = await run_in_threadpool(colibri_collector)
        try:
            plan, token = await run_in_threadpool(
                colibri_control_factory().create_plan,
                report,
                provider_id=body.runtime_id,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/prism/command")
    async def render_prism_command(
        request: Request,
        body: PrismCommandRequest,
    ) -> dict:
        require_admin(request)
        try:
            command = await run_in_threadpool(
                render_prism_serve_command,
                body.model_id,
                body.settings,
            )
        except PrismCommandError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "schema_version": "ulysses.prism-command.v1",
            "runtime_id": "prism.llamacpp",
            "model_id": body.model_id,
            "command": command,
            # Match the native Cookbook contract: controls regenerate the
            # command, while /api/model/serve parses and canonicalizes manual
            # edits before the host job ever sees them.
            "editable": True,
        }

    @router.post("/prism/jobs/plan")
    async def plan_prism_lifecycle(
        request: Request,
        body: PrismLifecyclePlanRequest,
    ) -> dict:
        require_admin(request)
        report = await run_in_threadpool(prism_collector)
        try:
            plan, token = await run_in_threadpool(
                prism_control_factory().create_plan,
                report,
                provider_id=body.runtime_id,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

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

    @router.post("/hermes/stack/jobs/plan")
    async def plan_hermes_stack(
        request: Request,
        body: HermesStackPlanRequest,
    ) -> dict:
        require_admin(request)
        try:
            plan, token = await run_in_threadpool(
                hermes_stack_control_factory().create_plan,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/hermes/mcp/jobs/plan")
    async def plan_hermes_mcp(
        request: Request,
        body: HermesMcpPlanRequest,
    ) -> dict:
        require_admin(request)
        report = await run_in_threadpool(hermes_collector)
        try:
            plan, token = await run_in_threadpool(
                hermes_control_factory().create_mcp_plan,
                report,
                action=body.action,
                name=body.name,
                command=body.command,
                args=body.args,
                environment=body.environment,
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
