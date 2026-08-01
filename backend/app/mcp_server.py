from __future__ import annotations

from typing import Any

from .agent_runtime import RuntimeDeps
from .policy import ApprovalRequired
from .schemas import AgentAnswer, RunStatus
from .service import MineOpsService


def create_mcp_server(service: MineOpsService) -> Any:
    """Create an optional official MCP SDK server sharing MineOps policy and audit paths."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("install the mcp extra to enable the MCP server") from exc

    server = FastMCP("ANL MineOps")

    async def call(server_id: str, tool_name: str, **arguments: Any) -> dict[str, Any]:
        adapter = service.get_adapter(server_id)
        mod_prefixes = (
            "inspect_mod_",
            "plan_mod_",
            "list_mod_",
            "read_mod_",
            "propose_mod_",
            "apply_mod_",
            "build_mod_",
            "create_mod_",
            "run_demo_mod_",
        )
        mod_project_id = arguments.get("project_id") if tool_name.startswith(mod_prefixes) else None
        run = service.create_mcp_run(server_id, tool_name, mod_project_id)
        deps = RuntimeDeps(
            server_id=server_id,
            adapter=adapter,
            policy=service.policy,
            run_id=run.id,
            mod_workspace=service.mod_workspace,
            mod_project_id=mod_project_id,
            emit=lambda *_: _completed(),
        )
        try:
            outcome = await deps.call_tool(tool_name, **arguments)
            status = RunStatus.COMPLETED if outcome.ok else RunStatus.FAILED
            service.store.save_run(
                run.model_copy(
                    update={
                        "status": status,
                        "answer": AgentAnswer(
                            summary=f"MCP 工具已执行：{tool_name}。",
                            executed_tools=[tool_name],
                        ),
                    }
                )
            )
            return outcome.model_dump(mode="json")
        except ApprovalRequired as exc:
            return {
                "tool_name": tool_name,
                "ok": False,
                "status": "pending_approval",
                "approval_id": exc.approval.id,
                "run_id": run.id,
            }

    async def _completed() -> None:
        return None

    @server.tool()
    async def get_status(server_id: str = "demo") -> dict[str, Any]:
        return await call(server_id, "get_status")

    @server.tool()
    async def get_logs(server_id: str = "demo", limit: int = 100) -> dict[str, Any]:
        return await call(server_id, "get_logs", limit=limit)

    @server.tool()
    async def get_players(server_id: str = "demo") -> dict[str, Any]:
        return await call(server_id, "get_players")

    @server.tool()
    async def restart(server_id: str = "demo") -> dict[str, Any]:
        return await call(server_id, "restart")

    @server.tool()
    async def create_backup(server_id: str = "demo") -> dict[str, Any]:
        return await call(server_id, "create_backup")

    @server.tool()
    async def inspect_mod_project(project_id: str = "demo-mod") -> dict[str, Any]:
        return await call("demo", "inspect_mod_project", project_id=project_id)

    @server.tool()
    async def plan_mod_task(request: str, project_id: str = "demo-mod") -> dict[str, Any]:
        return await call("demo", "plan_mod_task", project_id=project_id, request=request)

    @server.tool()
    async def read_mod_file(path: str, project_id: str = "demo-mod") -> dict[str, Any]:
        return await call("demo", "read_mod_file", project_id=project_id, path=path)

    @server.tool()
    async def list_mod_evidence(project_id: str = "demo-mod") -> dict[str, Any]:
        return await call("demo", "list_mod_evidence", project_id=project_id)

    @server.tool()
    async def propose_mod_patch(
        title: str,
        rationale: str,
        changes: list[dict[str, Any]],
        project_id: str = "demo-mod",
    ) -> dict[str, Any]:
        return await call(
            "demo",
            "propose_mod_patch",
            project_id=project_id,
            title=title,
            rationale=rationale,
            changes=changes,
        )

    @server.tool()
    async def apply_mod_patch(patch_id: str) -> dict[str, Any]:
        patch = service.mod_workspace.get_patch(patch_id)
        return await call("demo", "apply_mod_patch", project_id=patch.project_id, patch_id=patch_id)

    @server.tool()
    async def build_mod_project(project_id: str = "demo-mod", clean: bool = False) -> dict[str, Any]:
        return await call("demo", "build_mod_project", project_id=project_id, clean=clean)

    @server.tool()
    async def create_mod_test_scenario(
        kind: str,
        project_id: str = "demo-mod",
        title: str | None = None,
    ) -> dict[str, Any]:
        return await call(
            "demo",
            "create_mod_test_scenario",
            project_id=project_id,
            kind=kind,
            title=title,
        )

    @server.tool()
    async def run_demo_mod_test(scenario_id: str) -> dict[str, Any]:
        scenario = service.mod_workspace.get_scenario(scenario_id)
        return await call("demo", "run_demo_mod_test", project_id=scenario.project_id, scenario_id=scenario_id)

    return server
