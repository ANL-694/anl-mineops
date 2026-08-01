import asyncio

import httpx
import pytest
from pydantic_ai.models.test import TestModel

from backend.app.agent_runtime import AgentRuntime, RuntimeDeps
from backend.app.main import create_app
from backend.app.mod_workspace import ModWorkspaceError
from backend.app.policy import PolicyEngine
from backend.app.schemas import (
    ModPatchChange,
    ModPatchCreate,
    ModPatchOperation,
    ModProjectCreate,
    ModTestScenarioCreate,
    ModTestScenarioKind,
    ProviderProfile,
)
from backend.app.service import MineOpsService
from backend.app.storage import Store


@pytest.mark.asyncio
async def test_demo_project_inspection_build_and_scenario(tmp_path):
    service = MineOpsService(Store(str(tmp_path / "mod.db")))
    try:
        inspection = service.mod_workspace.inspect_project("demo-mod")
        assert inspection.status == "completed"
        assert "fabric_metadata" in inspection.detected_features
        assert any(item.path.endswith("DemoMod.java") for item in inspection.files)

        scenario = service.mod_workspace.create_scenario(
            ModTestScenarioCreate(project_id="demo-mod", kind=ModTestScenarioKind.NEW_ITEM)
        )
        result = await service.mod_workspace.run_demo_test(scenario.id)
        assert result.status == "completed"
        assert result.artifacts

        build = await service.mod_workspace.build_project("demo-mod")
        assert build.status.value == "succeeded"
        assert service.store.list_mod_builds("demo-mod")
    finally:
        service.store.close()


def test_patch_requires_relative_paths_and_applies_atomically(tmp_path):
    root = tmp_path / "mod"
    root.mkdir()
    source = root / "src.txt"
    source.write_text("before", encoding="utf-8")
    service = MineOpsService(Store(str(tmp_path / "patch.db")))
    try:
        project = service.mod_workspace.create_project(
            ModProjectCreate(id="fixture-mod", name="Fixture", root=str(root))
        )
        patch = service.mod_workspace.propose_patch(
            ModPatchCreate(
                project_id=project.id,
                title="更新文本",
                rationale="验证受保护补丁",
                changes=[
                    ModPatchChange(
                        path="src.txt",
                        operation=ModPatchOperation.UPDATE,
                        content="after",
                    ),
                    ModPatchChange(
                        path="new.txt",
                        operation=ModPatchOperation.CREATE,
                        content="new",
                    ),
                ],
            )
        )
        result = service.mod_workspace.apply_patch(patch.id)
        assert result.status == "completed"
        assert source.read_text(encoding="utf-8") == "after"
        assert (root / "new.txt").read_text(encoding="utf-8") == "new"
        with pytest.raises(ModWorkspaceError, match="mod_path_must_be_relative"):
            service.mod_workspace.read_file(project.id, "../src.txt")
    finally:
        service.store.close()


@pytest.mark.asyncio
async def test_mod_api_and_apply_approval(tmp_path):
    app = create_app(str(tmp_path / "mod-api.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        projects = (await client.get("/api/v1/mod-projects")).json()["data"]
        assert any(item["id"] == "demo-mod" for item in projects)
        inspection = await client.get("/api/v1/mod-projects/demo-mod")
        assert inspection.status_code == 200
        assert inspection.json()["data"]["files"]
        plan = await client.post(
            "/api/v1/mod-projects/demo-mod/plans",
            json={"project_id": "demo-mod", "request": "规划一个新物品需求"},
        )
        assert plan.status_code == 201
        assert plan.json()["data"]["scenario_kind"] == "new_item"
        scenario = await client.post(
            "/api/v1/mod-projects/demo-mod/scenarios",
            json={"project_id": "demo-mod", "kind": "new_item"},
        )
        assert scenario.status_code == 201
        scenario_id = scenario.json()["data"]["id"]
        run = await client.post(f"/api/v1/mod-projects/demo-mod/scenarios/{scenario_id}/run")
        assert run.status_code == 202
        assert run.json()["data"]["outcome"]["ok"] is True

        patch = await client.post(
            "/api/v1/mod-projects/demo-mod/patches",
            json={
                "project_id": "demo-mod",
                "title": "fixture patch",
                "rationale": "测试审批",
                "changes": [
                    {
                        "path": "README.md",
                        "operation": "update",
                        "content": "# changed\n",
                    }
                ],
            },
        )
        assert patch.status_code == 201
        patch_id = patch.json()["data"]["id"]
        requested = await client.post(f"/api/v1/mod-projects/demo-mod/patches/{patch_id}/apply")
        assert requested.json()["data"]["status"] == "pending_approval"
        approvals = (await client.get("/api/v1/approvals?pending_only=true")).json()["data"]
        approval = next(item for item in approvals if item["tool_name"] == "apply_mod_patch")
        resolved = await client.post(
            f"/api/v1/approvals/{approval['id']}/resolve", json={"approved": True}
        )
        assert resolved.status_code == 200
        assert app.state.service.store.get_mod_patch(patch_id).status.value == "applied"
    app.state.service.store.close()


@pytest.mark.asyncio
async def test_demo_agent_understands_modcrafting_flow(tmp_path):
    app = create_app(str(tmp_path / "mod-agent.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/runs",
            json={"prompt": "为新物品创建模组测试场景并验证", "server_id": "demo", "mod_project_id": "demo-mod"},
        )
        assert created.status_code == 202
        run_id = created.json()["data"]["id"]
        for _ in range(30):
            record = (await client.get(f"/api/v1/runs/{run_id}")).json()["data"]
            if record["status"] != "running":
                break
            await asyncio.sleep(0.01)
        assert record["status"] == "completed"
        assert record["answer"]["executed_tools"] == ["create_mod_test_scenario", "run_demo_mod_test"]
    app.state.service.store.close()


@pytest.mark.asyncio
async def test_agent_registers_modcrafting_typed_tools(monkeypatch, tmp_path):
    profile = ProviderProfile(
        id="mod-tools-model",
        name="模组工具测试模型",
        base_url="https://example.com/v1",
        model="fixture-model",
        api_key_env="MOD_TOOLS_KEY",
    )
    test_model = TestModel(call_tools=[], custom_output_args={"summary": "ok", "executed_tools": []})
    monkeypatch.setattr("backend.app.agent_runtime.build_model", lambda _: test_model)
    store = Store(str(tmp_path / "agent.db"))
    service = MineOpsService(store)

    async def emit(*_: object) -> None:
        return None

    deps = RuntimeDeps(
        server_id="demo",
        adapter=service.adapters["demo"],
        policy=PolicyEngine(store),
        run_id="mod-tools-run",
        emit=emit,
        mod_workspace=service.mod_workspace,
        mod_project_id="demo-mod",
    )
    await AgentRuntime(profile, tool_calling="supported").run("分析模组", deps)
    names = {tool.name for tool in test_model.last_model_request_parameters.function_tools}
    assert {"inspect_mod_project", "read_mod_file", "propose_mod_patch", "build_mod_project", "run_demo_mod_test"} <= names
    store.close()
