"""Admin-only Diogenes host-observation and fixed-action routes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core.middleware import INTERNAL_TOOL_HEADER, require_admin
from routes.auth_routes import SESSION_COOKIE
from src.diogenes_host_services import HostServiceError, HostServicesManager
from src.diogenes_librarian_workspace import (
    LibrarianWorkspaceClient,
    LibrarianWorkspaceError,
)
from src.diogenes_persephone_workspace import (
    PersephoneWorkspaceControl,
    PersephoneWorkspaceError,
)
from src.diogenes_roboomp_workspace import (
    RoboOMPWorkspaceControl,
    RoboOMPWorkspaceError,
)
from src.diogenes_docker_projects import (
    DockerProjectControl,
    DockerResourceControl,
    collect_docker_projects,
    read_docker_container_log,
    read_docker_documents,
    read_docker_log,
    save_docker_document,
)
from src.diogenes_skill_auditor import (
    SkillAuditorControl,
    collect_retrieval_catalog,
    collect_retrieval_runtime,
    collect_skills,
    inspect_retrieval_skill,
    search_retrieval_skills,
)
from src.diogenes_user_scripts import UserScriptControl
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
from src.owner_identity import INTERNAL_TOOL_USER, auth_disabled


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


class UserScriptWriteRequest(BaseModel):
    name: str
    content: str
    cwd: str = ""


class UserScriptPlanRequest(BaseModel):
    script_id: str


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
    skill_id: str = ""
    action: str
    query: str = ""
    harness: str = ""


class LibrarianChatRequest(BaseModel):
    messages: list[dict[str, object]]
    model: str = ""


class PersephoneLifecyclePlanRequest(BaseModel):
    action: str


class PersephoneMutationPlanRequest(BaseModel):
    mutation: dict[str, object]


class RoboOMPLifecyclePlanRequest(BaseModel):
    action: str


class RoboOMPMutationPlanRequest(BaseModel):
    mutation: dict[str, object]


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


class HostServiceActionRequest(BaseModel):
    action: str


class HostShellCreateRequest(BaseModel):
    title: str = ""
    cwd: str = ""
    cols: int = Field(default=100, ge=20, le=400)
    rows: int = Field(default=30, ge=8, le=200)


def _job_http_error(exc: RuntimeJobError) -> HTTPException:
    if isinstance(exc, RuntimeJobConflict):
        return HTTPException(409, str(exc))
    if isinstance(exc, RuntimeJobConfirmationError):
        return HTTPException(400, str(exc))
    return HTTPException(400, str(exc))


def _librarian_http_error(exc: LibrarianWorkspaceError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


def _require_operator_admin(request: Request) -> None:
    """Require a human admin; internal agent and bearer-token bypasses stay out."""
    user = getattr(request.state, "current_user", None)
    if (
        user == INTERNAL_TOOL_USER
        or getattr(request.state, "api_token", False)
        or request.headers.get(INTERNAL_TOOL_HEADER)
    ):
        raise HTTPException(403, "Operator admin only")
    require_admin(request)
    if auth_disabled():
        return
    auth_manager = getattr(request.app.state, "auth_manager", None)
    if (
        not user
        or auth_manager is None
        or not auth_manager.is_admin(user)
    ):
        raise HTTPException(403, "Operator admin only")


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
    user_script_control_factory: Callable[[], UserScriptControl] = UserScriptControl,
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
    librarian_client_factory: Callable[
        [], LibrarianWorkspaceClient
    ] = LibrarianWorkspaceClient,
    persephone_control_factory: Callable[
        [], PersephoneWorkspaceControl
    ] = PersephoneWorkspaceControl,
    roboomp_control_factory: Callable[
        [], RoboOMPWorkspaceControl
    ] = RoboOMPWorkspaceControl,
    sandwich_collector: Callable[[], dict] = collect_sandwich_status,
    managed_runtime_collector: Callable[[], dict] = collect_managed_runtimes,
    docker_project_collector: Callable[[], dict] = collect_docker_projects,
    host_services_manager_factory: Callable[
        [], HostServicesManager
    ] = HostServicesManager,
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

    @router.get("/user-scripts")
    async def get_user_scripts(request: Request) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(user_script_control_factory().collect)
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/user-scripts")
    async def create_user_script(
        request: Request,
        body: UserScriptWriteRequest,
    ) -> dict:
        require_admin(request)
        try:
            value = await run_in_threadpool(
                user_script_control_factory().create,
                name=body.name,
                content=body.content,
                cwd=body.cwd,
            )
            return {"script": value}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.put("/user-scripts/{script_id}")
    async def update_user_script(
        request: Request,
        script_id: str,
        body: UserScriptWriteRequest,
    ) -> dict:
        require_admin(request)
        try:
            value = await run_in_threadpool(
                user_script_control_factory().update,
                script_id,
                name=body.name,
                content=body.content,
                cwd=body.cwd,
            )
            return {"script": value}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.delete("/user-scripts/{script_id}")
    async def delete_user_script(request: Request, script_id: str) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                user_script_control_factory().delete,
                script_id,
            )
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/user-scripts/jobs/plan")
    async def plan_user_script(
        request: Request,
        body: UserScriptPlanRequest,
    ) -> dict:
        require_admin(request)
        try:
            plan, token = await run_in_threadpool(
                user_script_control_factory().create_plan,
                script_id=body.script_id,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

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

    @router.get("/skills/catalog")
    async def get_retrieval_catalog(
        request: Request,
        refresh: bool = False,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                collect_retrieval_catalog,
                refresh=refresh,
            )
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/skills/inspect")
    async def get_retrieval_skill(
        request: Request,
        skill_id: str,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(inspect_retrieval_skill, skill_id)
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/skills/search")
    async def search_retrieval_catalog(
        request: Request,
        query: str,
        limit: int = 24,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                search_retrieval_skills,
                query,
                limit=limit,
            )
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/skills/runtime")
    async def get_retrieval_runtime(request: Request) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(collect_retrieval_runtime)
        except RuntimeJobError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/library/overview")
    async def get_librarian_overview(request: Request) -> dict:
        require_admin(request)
        try:
            return await librarian_client_factory().overview()
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.get("/library/concept")
    async def get_librarian_concept(request: Request, path: str) -> dict:
        require_admin(request)
        try:
            return await librarian_client_factory().concept(path)
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.get("/library/search")
    async def search_librarian(
        request: Request,
        query: str,
        concept_type: str = "",
        tag: str = "",
    ) -> list:
        require_admin(request)
        try:
            return await librarian_client_factory().search(
                query,
                concept_type=concept_type,
                tag=tag,
            )
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.get("/library/graph")
    async def get_librarian_graph(request: Request) -> dict:
        require_admin(request)
        try:
            return await librarian_client_factory().graph()
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.get("/library/traces")
    async def get_librarian_traces(request: Request) -> list:
        require_admin(request)
        try:
            return await librarian_client_factory().traces()
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.get("/library/trace")
    async def get_librarian_trace(request: Request, trace_id: str) -> dict:
        require_admin(request)
        try:
            return await librarian_client_factory().trace(trace_id)
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.get("/library/dreams")
    async def get_librarian_dreams(request: Request) -> dict:
        require_admin(request)
        try:
            return await librarian_client_factory().dreams()
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.get("/library/dreams/{proposal_id}")
    async def get_librarian_dream(request: Request, proposal_id: str) -> dict:
        require_admin(request)
        try:
            return await librarian_client_factory().dream(proposal_id)
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.post("/library/chat")
    async def chat_with_librarian(
        request: Request,
        body: LibrarianChatRequest,
    ) -> dict:
        _require_operator_admin(request)
        try:
            return await librarian_client_factory().chat(
                body.messages,
                model=body.model,
            )
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.post("/library/dreams/propose")
    async def propose_librarian_dream(request: Request) -> dict:
        _require_operator_admin(request)
        try:
            return await librarian_client_factory().propose_dream()
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.post("/library/dreams/{proposal_id}/{action}")
    async def act_on_librarian_dream(
        request: Request,
        proposal_id: str,
        action: str,
    ) -> dict:
        _require_operator_admin(request)
        try:
            return await librarian_client_factory().dream_action(
                proposal_id,
                action,
            )
        except LibrarianWorkspaceError as exc:
            raise _librarian_http_error(exc) from exc

    @router.get("/persephone/workspace")
    async def get_persephone_workspace(
        request: Request,
        limit: int = 50,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                persephone_control_factory().observe,
                limit=limit,
            )
        except PersephoneWorkspaceError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get("/persephone/queue/{kind}/{record_id}")
    async def get_persephone_queue_record(
        request: Request,
        kind: str,
        record_id: int,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                persephone_control_factory().queue_record,
                kind=kind,
                record_id=record_id,
            )
        except PersephoneWorkspaceError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/persephone/lifecycle/jobs/plan")
    async def plan_persephone_lifecycle(
        request: Request,
        body: PersephoneLifecyclePlanRequest,
    ) -> dict:
        _require_operator_admin(request)
        try:
            plan, token = await run_in_threadpool(
                persephone_control_factory().create_lifecycle_plan,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/persephone/mutations/jobs/plan")
    async def plan_persephone_mutation(
        request: Request,
        body: PersephoneMutationPlanRequest,
    ) -> dict:
        _require_operator_admin(request)
        try:
            plan, token = await run_in_threadpool(
                persephone_control_factory().create_mutation_plan,
                body.mutation,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.get("/roboomp/workspace")
    async def get_roboomp_workspace(
        request: Request,
        limit: int = 50,
        state: str = "open",
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                roboomp_control_factory().observe,
                limit=limit,
                state=state,
            )
        except RoboOMPWorkspaceError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get("/roboomp/issues/inspect")
    async def inspect_roboomp_issue(
        request: Request,
        issue: str,
        limit: int = 50,
    ) -> dict:
        require_admin(request)
        try:
            return await run_in_threadpool(
                roboomp_control_factory().inspect,
                issue=issue,
                limit=limit,
            )
        except RoboOMPWorkspaceError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/roboomp/lifecycle/jobs/plan")
    async def plan_roboomp_lifecycle(
        request: Request,
        body: RoboOMPLifecyclePlanRequest,
    ) -> dict:
        _require_operator_admin(request)
        try:
            plan, token = await run_in_threadpool(
                roboomp_control_factory().create_lifecycle_plan,
                action=body.action,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

    @router.post("/roboomp/mutations/jobs/plan")
    async def plan_roboomp_mutation(
        request: Request,
        body: RoboOMPMutationPlanRequest,
    ) -> dict:
        _require_operator_admin(request)
        try:
            plan, token = await run_in_threadpool(
                roboomp_control_factory().create_mutation_plan,
                body.mutation,
            )
            return {"job": plan, "confirmation_token": token}
        except RuntimeJobError as exc:
            raise _job_http_error(exc) from exc

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
                query=body.query,
                harness=body.harness,
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

    @router.get("/host-services")
    async def get_host_services(request: Request) -> dict:
        _require_operator_admin(request)
        return await run_in_threadpool(host_services_manager_factory().observe)

    @router.post("/host-services/{service_id}")
    async def control_host_service(
        request: Request,
        service_id: str,
        body: HostServiceActionRequest,
    ) -> dict:
        _require_operator_admin(request)
        try:
            return await run_in_threadpool(
                host_services_manager_factory().act,
                service_id,
                body.action,
            )
        except HostServiceError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/host-services/{service_id}/log")
    async def get_host_service_log(
        request: Request,
        service_id: str,
        max_chars: int = 40000,
    ) -> dict:
        _require_operator_admin(request)
        try:
            return await run_in_threadpool(
                host_services_manager_factory().read_log,
                service_id,
                max_chars=max_chars,
            )
        except HostServiceError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/host-shell/sessions")
    async def get_host_shells(request: Request) -> dict:
        _require_operator_admin(request)
        return await run_in_threadpool(host_services_manager_factory().list_shells)

    @router.post("/host-shell/sessions")
    async def create_host_shell(
        request: Request,
        body: HostShellCreateRequest,
    ) -> dict:
        _require_operator_admin(request)
        try:
            return await run_in_threadpool(
                host_services_manager_factory().create_shell,
                title=body.title,
                cwd=body.cwd,
                cols=body.cols,
                rows=body.rows,
            )
        except HostServiceError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/host-shell/sessions/{shell_id}")
    async def delete_host_shell(request: Request, shell_id: str) -> dict:
        _require_operator_admin(request)
        try:
            return await run_in_threadpool(
                host_services_manager_factory().delete_shell,
                shell_id,
            )
        except HostServiceError as exc:
            raise HTTPException(400, str(exc)) from exc

    async def _authorize_host_shell(websocket: WebSocket) -> bool:
        # Cookies alone must not authorize a cross-site WebSocket connection.
        origin = websocket.headers.get("origin", "")
        if origin:
            origin_host = urlsplit(origin).netloc.lower()
            request_host = websocket.headers.get("host", "").lower()
            forwarded_host = websocket.headers.get("x-forwarded-host", "").split(",")[0].strip().lower()
            allowed_hosts = {value for value in (request_host, forwarded_host) if value}
            if not origin_host or origin_host not in allowed_hosts:
                await websocket.close(code=4403, reason="Origin rejected")
                return False
        if auth_disabled():
            return True
        app = websocket.scope.get("app")
        manager = getattr(getattr(app, "state", None), "auth_manager", None)
        token = websocket.cookies.get(SESSION_COOKIE)
        if manager is not None and manager.validate_token(token):
            username = manager.get_username_for_token(token)
            if username and manager.is_admin(username):
                return True
        await websocket.close(code=4403, reason="Admin only")
        return False

    @router.websocket("/host-shell/sessions/{shell_id}/ws")
    async def attach_host_shell(websocket: WebSocket, shell_id: str) -> None:
        if not await _authorize_host_shell(websocket):
            return
        try:
            cols = max(20, min(int(websocket.query_params.get("cols", "100")), 400))
            rows = max(8, min(int(websocket.query_params.get("rows", "30")), 200))
            attachment = await run_in_threadpool(
                host_services_manager_factory().attach_shell,
                shell_id,
                cols=cols,
                rows=rows,
            )
        except (HostServiceError, TypeError, ValueError):
            await websocket.close(code=4404, reason="Operator shell unavailable")
            return

        await websocket.accept()
        loop = asyncio.get_running_loop()
        output: asyncio.Queue[bytes | None] = asyncio.Queue()

        def terminal_ready() -> None:
            try:
                chunk = attachment.read()
            except BlockingIOError:
                return
            except OSError:
                chunk = b""
            output.put_nowait(chunk or None)

        async def send_terminal() -> None:
            while True:
                chunk = await output.get()
                if chunk is None:
                    return
                await websocket.send_bytes(chunk)

        async def receive_terminal() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                raw = message.get("text")
                if not raw or len(raw) > 131072:
                    continue
                try:
                    event = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if event.get("type") == "input" and isinstance(event.get("data"), str):
                    attachment.write(event["data"].encode("utf-8")[:65536])
                elif event.get("type") == "resize":
                    try:
                        attachment.resize(int(event.get("cols", 100)), int(event.get("rows", 30)))
                    except (TypeError, ValueError):
                        continue

        loop.add_reader(attachment.fileno(), terminal_ready)
        tasks = {
            asyncio.create_task(send_terminal()),
            asyncio.create_task(receive_terminal()),
        }
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done | pending:
                with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                    await task
        finally:
            loop.remove_reader(attachment.fileno())
            attachment.close()
            with suppress(RuntimeError):
                await websocket.close()

    return router
