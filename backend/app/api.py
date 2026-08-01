import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from .config import Settings, get_settings
from .mod_workspace import ModWorkspaceError
from .providers import probe_provider as run_provider_probe
from .schemas import (
    ApiResponse,
    ApprovalResolve,
    ModBuildRequest,
    ModPatchCreate,
    ModProjectCreate,
    ModProjectUpdate,
    ModTaskPlanCreate,
    ModTestScenarioCreate,
    ProviderCreate,
    ProviderUpdate,
    RunCreate,
    ServerConfigCreate,
    ServerConfigUpdate,
    ToolPolicyUpdate,
)
from .service import MineOpsService

router = APIRouter(prefix="/api/v1")


def _exception_code(exc: KeyError) -> str:
    return str(exc.args[0]) if exc.args else str(exc)


def get_service(request: Request) -> MineOpsService:
    return request.app.state.service


def response(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return ApiResponse(data=data, meta=meta or {}).model_dump(mode="json")


def _mod_http_error(exc: ModWorkspaceError) -> HTTPException:
    code = str(exc)
    status_code = 404 if code.endswith("_not_found") else 422
    if code in {"mod_project_exists", "mod_patch_already_resolved"}:
        status_code = 409
    return HTTPException(status_code=status_code, detail=code)


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return response({"status": "ok", "app": settings.app_name, "version": settings.app_version})


@router.get("/servers")
async def list_servers(service: MineOpsService = Depends(get_service)) -> dict[str, Any]:
    return response([item.model_dump(mode="json") for item in await service.list_servers()])


@router.get("/mod-projects")
async def list_mod_projects(service: MineOpsService = Depends(get_service)) -> dict[str, Any]:
    return response([item.model_dump(mode="json") for item in service.mod_workspace.list_projects()])


@router.post("/mod-projects", status_code=status.HTTP_201_CREATED)
async def create_mod_project(
    payload: ModProjectCreate, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        project = service.mod_workspace.create_project(payload)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    service.policy.audit(
        run_id=None,
        tool_name="create_mod_project",
        action="mod_project_create",
        status="completed",
        details={"project_id": project.id},
    )
    return response(project.model_dump(mode="json"))


@router.get("/mod-projects/{project_id}")
async def inspect_mod_project(
    project_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        inspection = service.mod_workspace.inspect_project(project_id)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response(inspection.model_dump(mode="json"))


@router.patch("/mod-projects/{project_id}")
async def update_mod_project(
    project_id: str,
    payload: ModProjectUpdate,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    try:
        project = service.mod_workspace.update_project(project_id, payload)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response(project.model_dump(mode="json"))


@router.get("/mod-projects/{project_id}/files")
async def list_mod_files(
    project_id: str,
    prefix: str = Query(default="", max_length=1000),
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    try:
        files = service.mod_workspace.list_files(project_id, prefix)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response([item.model_dump(mode="json") for item in files])


@router.get("/mod-projects/{project_id}/plans")
async def list_mod_plans(
    project_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        plans = service.mod_workspace.list_plans(project_id)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response([item.model_dump(mode="json") for item in plans])


@router.post("/mod-projects/{project_id}/plans", status_code=status.HTTP_201_CREATED)
async def plan_mod_task(
    project_id: str,
    payload: ModTaskPlanCreate,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    if payload.project_id != project_id:
        raise HTTPException(status_code=422, detail="project_id_mismatch")
    try:
        plan = service.mod_workspace.plan_task(payload)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    service.policy.audit(
        run_id=None,
        tool_name="plan_mod_task",
        action="mod_plan_create",
        status="completed",
        details={"project_id": project_id, "plan_id": plan.id},
    )
    return response(plan.model_dump(mode="json"))


@router.get("/mod-projects/{project_id}/files/{relative_path:path}")
async def read_mod_file(
    project_id: str, relative_path: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        file = service.mod_workspace.read_file(project_id, relative_path)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response(file.model_dump(mode="json"))


@router.get("/mod-projects/{project_id}/patches")
async def list_mod_patches(
    project_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        patches = service.mod_workspace.list_patches(project_id)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response([item.model_dump(mode="json") for item in patches])


@router.post("/mod-projects/{project_id}/patches", status_code=status.HTTP_201_CREATED)
async def propose_mod_patch(
    project_id: str,
    payload: ModPatchCreate,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    if payload.project_id != project_id:
        raise HTTPException(status_code=422, detail="project_id_mismatch")
    try:
        patch = service.mod_workspace.propose_patch(payload)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    service.policy.audit(
        run_id=None,
        tool_name="propose_mod_patch",
        action="mod_patch_propose",
        status="completed",
        details={"project_id": project_id, "patch_id": patch.id, "files": [item.path for item in patch.changes]},
    )
    return response(patch.model_dump(mode="json"))


@router.post("/mod-projects/{project_id}/patches/{patch_id}/apply", status_code=status.HTTP_202_ACCEPTED)
async def apply_mod_patch(
    project_id: str, patch_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        patch = service.mod_workspace.get_patch(patch_id)
        if patch.project_id != project_id:
            raise ModWorkspaceError("mod_patch_not_found")
        result = await service.execute_mod_tool(project_id, "apply_mod_patch", {"patch_id": patch_id})
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    code = status.HTTP_202_ACCEPTED if result.get("status") == "pending_approval" else status.HTTP_200_OK
    return response(result, meta={"http_status": code})


@router.get("/mod-projects/{project_id}/builds")
async def list_mod_builds(
    project_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        builds = service.mod_workspace.list_builds(project_id)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response([item.model_dump(mode="json") for item in builds])


@router.post("/mod-projects/{project_id}/builds", status_code=status.HTTP_202_ACCEPTED)
async def build_mod_project(
    project_id: str,
    payload: ModBuildRequest,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    if payload.project_id != project_id:
        raise HTTPException(status_code=422, detail="project_id_mismatch")
    try:
        result = await service.execute_mod_tool(
            project_id, "build_mod_project", {"clean": payload.clean}
        )
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    code = status.HTTP_202_ACCEPTED if result.get("status") == "pending_approval" else status.HTTP_200_OK
    return response(result, meta={"http_status": code})


@router.get("/mod-projects/{project_id}/scenarios")
async def list_mod_scenarios(
    project_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        scenarios = service.mod_workspace.list_scenarios(project_id)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response([item.model_dump(mode="json") for item in scenarios])


@router.post("/mod-projects/{project_id}/scenarios", status_code=status.HTTP_201_CREATED)
async def create_mod_scenario(
    project_id: str,
    payload: ModTestScenarioCreate,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    if payload.project_id != project_id:
        raise HTTPException(status_code=422, detail="project_id_mismatch")
    try:
        scenario = service.mod_workspace.create_scenario(payload)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    service.policy.audit(
        run_id=None,
        tool_name="create_mod_test_scenario",
        action="mod_scenario_create",
        status="completed",
        details={"project_id": project_id, "scenario_id": scenario.id, "kind": scenario.kind.value},
    )
    return response(scenario.model_dump(mode="json"))


@router.post("/mod-projects/{project_id}/scenarios/{scenario_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_mod_scenario(
    project_id: str, scenario_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        scenario = service.mod_workspace.get_scenario(scenario_id)
        if scenario.project_id != project_id:
            raise ModWorkspaceError("mod_scenario_not_found")
        result = await service.execute_mod_tool(project_id, "run_demo_mod_test", {"scenario_id": scenario_id})
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response(result)


@router.get("/mod-projects/{project_id}/evidence")
async def list_mod_evidence(
    project_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        evidence = service.mod_workspace.list_evidence(project_id)
    except ModWorkspaceError as exc:
        raise _mod_http_error(exc) from exc
    return response([item.model_dump(mode="json") for item in evidence])


@router.get("/servers/configs")
async def list_server_configs(service: MineOpsService = Depends(get_service)) -> dict[str, Any]:
    return response([item.model_dump(mode="json") for item in service.list_server_configs()])


@router.get("/servers/{server_id}/backups")
async def list_backups(
    server_id: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    if not service.get_server_config(server_id):
        raise HTTPException(status_code=404, detail="server_not_found")
    return response([item.model_dump(mode="json") for item in service.list_backups(server_id)])


@router.post("/servers/configs", status_code=status.HTTP_201_CREATED)
async def create_server_config(
    payload: ServerConfigCreate, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    if service.get_server_config(payload.id):
        raise HTTPException(status_code=409, detail="server_config_exists")
    try:
        config = service.save_server_config(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response(config.model_dump(mode="json"))


@router.patch("/servers/configs/{server_id}")
async def update_server_config(
    server_id: str,
    payload: ServerConfigUpdate,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    current = service.get_server_config(server_id)
    if not current:
        raise HTTPException(status_code=404, detail="server_config_not_found")
    try:
        updated_data = current.model_dump()
        updated_data.update(payload.model_dump(exclude_unset=True))
        updated = ServerConfigCreate.model_validate(updated_data)
        config = service.save_server_config(updated)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response(config.model_dump(mode="json"))


@router.post("/servers/{server_id}/actions/{action}", status_code=status.HTTP_202_ACCEPTED)
async def server_action(
    server_id: str, action: str, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    prompts = {
        "start": "启动服务器",
        "stop": "停止服务器",
        "restart": "重启服务器",
        "backup": "创建备份",
    }
    if action not in prompts:
        raise HTTPException(status_code=422, detail="unsupported_action")
    try:
        run = await service.start_run(RunCreate(prompt=prompts[action], server_id=server_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_exception_code(exc)) from exc
    return response(run.model_dump(mode="json"))


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: RunCreate, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    try:
        run = await service.start_run(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_exception_code(exc)) from exc
    return response(run.model_dump(mode="json"))


@router.get("/runs/{run_id}")
async def get_run(run_id: str, service: MineOpsService = Depends(get_service)) -> dict[str, Any]:
    run = service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    return response(run.model_dump(mode="json"))


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str, service: MineOpsService = Depends(get_service)
) -> StreamingResponse:
    if not service.get_run(run_id):
        raise HTTPException(status_code=404, detail="run_not_found")

    async def stream():
        async for event in service.events(run_id):
            payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            yield f"id: {event.id}\nevent: {event.type}\ndata: {payload}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/providers")
async def list_providers(service: MineOpsService = Depends(get_service)) -> dict[str, Any]:
    return response([item.model_dump(mode="json") for item in service.list_providers()])


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreate, service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    if service.store.get_provider(payload.id):
        raise HTTPException(status_code=409, detail="provider_exists")
    return response(service.save_provider(payload).model_dump(mode="json"))


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    current = service.store.get_provider(provider_id)
    if not current:
        raise HTTPException(status_code=404, detail="provider_not_found")
    updated = current.model_copy(update=payload.model_dump(exclude_unset=True))
    return response(service.save_provider(updated).model_dump(mode="json"))


@router.get("/providers/{provider_id}/probe")
async def probe_provider(
    provider_id: str, live: bool = Query(default=False), service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    profile = service.store.get_provider(provider_id)
    if not profile:
        raise HTTPException(status_code=404, detail="provider_not_found")
    result = await run_provider_probe(profile, live=live)
    service.store.save_provider_probe(result)
    return response(result.model_dump(mode="json"))


@router.get("/tool-policies")
async def list_policies(service: MineOpsService = Depends(get_service)) -> dict[str, Any]:
    return response([item.model_dump(mode="json") for item in service.list_policies()])


@router.patch("/tool-policies/{tool_name}")
async def update_policy(
    tool_name: str,
    payload: ToolPolicyUpdate,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    current = service.policy.get(tool_name)
    updated = current.model_copy(update=payload.model_dump(exclude_unset=True))
    return response(service.update_policy(updated).model_dump(mode="json"))


@router.get("/approvals")
async def list_approvals(
    pending_only: bool = Query(default=False), service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    return response([item.model_dump(mode="json") for item in service.list_approvals(pending_only)])


@router.post("/approvals/{approval_id}/resolve")
async def resolve_approval(
    approval_id: str,
    payload: ApprovalResolve,
    service: MineOpsService = Depends(get_service),
) -> dict[str, Any]:
    try:
        approval = await service.resolve_approval(approval_id, payload.approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_exception_code(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return response(approval.model_dump(mode="json"))


@router.get("/audit-events")
async def audit_events(
    limit: int = Query(default=100, ge=1, le=500), service: MineOpsService = Depends(get_service)
) -> dict[str, Any]:
    return response([item.model_dump(mode="json") for item in service.list_audits(limit)])
