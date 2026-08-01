import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .adapters import ServerAdapter
from .mod_workspace import ModWorkspaceService
from .policy import ApprovalRequired, PolicyEngine
from .providers import ProviderError, build_model
from .schemas import (
    AgentAnswer,
    BackupRecord,
    Evidence,
    ModPatchChange,
    ModPatchCreate,
    ModTaskPlanCreate,
    ModTestScenarioCreate,
    ModTestScenarioKind,
    ProviderProfile,
    RunStatus,
    ToolOutcome,
)


@dataclass
class RuntimeDeps:
    server_id: str
    adapter: ServerAdapter
    policy: PolicyEngine
    run_id: str
    emit: Callable[[str, str, dict[str, Any]], Awaitable[None]]
    mod_workspace: ModWorkspaceService | None = None
    mod_project_id: str | None = None

    async def call_tool(self, tool_name: str, **arguments: Any) -> ToolOutcome:
        await self.emit("tool_requested", tool_name, {"arguments": arguments})
        try:
            self.policy.check(tool_name, self.server_id, arguments, self.run_id)
            result = await _dispatch(
                self.adapter,
                tool_name,
                arguments,
                mod_workspace=self.mod_workspace,
                mod_project_id=self.mod_project_id,
            )
            if tool_name in {"create_backup", "verify_backup"}:
                self.policy.store.save_backup(BackupRecord.model_validate(result))
        except ApprovalRequired as exc:
            await self.emit(
                "approval_required",
                f"等待批准：{tool_name}",
                {"approval_id": exc.approval.id, "tool_name": tool_name},
            )
            raise
        except Exception as exc:
            self.policy.audit(
                run_id=self.run_id,
                tool_name=tool_name,
                action="tool_call",
                status="failed",
                details={"error": str(exc)},
            )
            await self.emit("tool_failed", f"工具失败：{tool_name}", {"error": str(exc)})
            return ToolOutcome(tool_name=tool_name, ok=False, status="failed", error=str(exc))
        audit = self.policy.audit(
            run_id=self.run_id,
            tool_name=tool_name,
            action="tool_call",
            status="failed" if isinstance(result, dict) and result.get("status") in {"failed", "blocked"} else "completed",
            details={"arguments": _audit_argument_summary(arguments)},
        )
        result_failed = isinstance(result, dict) and result.get("status") in {"failed", "blocked"}
        outcome = ToolOutcome(
            tool_name=tool_name,
            ok=not result_failed,
            status=str(result.get("status")) if result_failed else "completed",
            summary=result.get("summary") if isinstance(result, dict) else None,
            data=result,
            next_actions=result.get("next_actions", []) if isinstance(result, dict) else [],
            artifacts=result.get("artifacts", []) if isinstance(result, dict) else [],
            audit_id=audit.id,
        )
        await self.emit("tool_completed", f"工具完成：{tool_name}", outcome.model_dump())
        return outcome


async def _dispatch(
    adapter: ServerAdapter,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    mod_workspace: ModWorkspaceService | None = None,
    mod_project_id: str | None = None,
) -> dict[str, Any]:
    if tool_name == "get_status":
        return (await adapter.get_status()).model_dump(mode="json")
    if tool_name == "get_logs":
        logs = await adapter.get_logs(arguments.get("limit", 100))
        return {"logs": [item.model_dump(mode="json") for item in logs]}
    if tool_name == "get_players":
        return {"players": await adapter.get_players()}
    if tool_name in {"start", "stop", "restart"}:
        return (await getattr(adapter, tool_name)()).model_dump(mode="json")
    if tool_name == "create_backup":
        return (await adapter.create_backup()).model_dump(mode="json")
    if tool_name == "verify_backup":
        return (await adapter.verify_backup(arguments["backup_id"])).model_dump(mode="json")
    if tool_name == "restore_backup":
        return (await adapter.restore_backup(arguments["backup_id"])).model_dump(mode="json")
    if tool_name == "diagnose_incident":
        logs = await adapter.get_logs(100)
        errors = [item for item in logs if item.level == "error"]
        return {
            "error_count": len(errors),
            "recent_errors": [item.model_dump(mode="json") for item in errors[-10:]],
        }
    if tool_name.startswith("mod_") or tool_name in {
        "inspect_mod_project",
        "plan_mod_task",
        "list_mod_files",
        "read_mod_file",
        "propose_mod_patch",
        "apply_mod_patch",
        "build_mod_project",
        "create_mod_test_scenario",
        "run_demo_mod_test",
        "list_mod_evidence",
        "list_mod_patches",
        "list_mod_scenarios",
    }:
        if mod_workspace is None:
            raise ValueError("mod_workspace_not_configured")
        project_id = arguments.get("project_id") or mod_project_id or "demo-mod"
        if tool_name == "inspect_mod_project":
            return mod_workspace.inspect_project(project_id).model_dump(mode="json")
        if tool_name == "plan_mod_task":
            payload = ModTaskPlanCreate(project_id=project_id, request=arguments["request"])
            return mod_workspace.plan_task(payload).model_dump(mode="json")
        if tool_name == "list_mod_files":
            files = mod_workspace.list_files(project_id, arguments.get("prefix", ""))
            return {"files": [item.model_dump(mode="json") for item in files]}
        if tool_name == "read_mod_file":
            return mod_workspace.read_file(project_id, arguments["path"]).model_dump(mode="json")
        if tool_name == "propose_mod_patch":
            payload = ModPatchCreate(
                project_id=project_id,
                title=arguments["title"],
                rationale=arguments["rationale"],
                changes=arguments["changes"],
            )
            return mod_workspace.propose_patch(payload).model_dump(mode="json")
        if tool_name == "apply_mod_patch":
            return mod_workspace.apply_patch(arguments["patch_id"]).model_dump(mode="json")
        if tool_name == "build_mod_project":
            build = await mod_workspace.build_project(project_id, clean=bool(arguments.get("clean", False)))
            return build.model_dump(mode="json")
        if tool_name == "create_mod_test_scenario":
            payload = ModTestScenarioCreate(
                project_id=project_id,
                kind=arguments["kind"],
                title=arguments.get("title"),
                steps=arguments.get("steps", []),
                assertions=arguments.get("assertions", []),
            )
            return mod_workspace.create_scenario(payload).model_dump(mode="json")
        if tool_name == "run_demo_mod_test":
            return (await mod_workspace.run_demo_test(arguments["scenario_id"])).model_dump(mode="json")
        if tool_name == "list_mod_evidence":
            return {"evidence": [item.model_dump(mode="json") for item in mod_workspace.list_evidence(project_id)]}
        if tool_name == "list_mod_patches":
            return {"patches": [item.model_dump(mode="json") for item in mod_workspace.list_patches(project_id)]}
        if tool_name == "list_mod_scenarios":
            return {"scenarios": [item.model_dump(mode="json") for item in mod_workspace.list_scenarios(project_id)]}
    raise ValueError(f"unknown_tool:{tool_name}")


def _audit_argument_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in arguments.items():
        if key == "content" and isinstance(value, str):
            summary[key] = {
                "length": len(value),
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }
        elif key == "changes" and isinstance(value, list):
            summary[key] = [
                {
                    "path": item.get("path"),
                    "operation": item.get("operation"),
                    "content_length": len(item.get("content", ""))
                    if isinstance(item, dict)
                    else None,
                }
                for item in value
            ]
        else:
            summary[key] = value
    return summary


class AgentRuntime:
    def __init__(self, profile: ProviderProfile | None, *, tool_calling: str | None = None) -> None:
        self.profile = profile
        self.tool_calling = tool_calling

    @property
    def read_only(self) -> bool:
        return self.profile is not None and self.tool_calling != "supported"

    async def run(self, prompt: str, deps: RuntimeDeps) -> AgentAnswer:
        await deps.emit(
            "provider_mode",
            "演示模式" if self.profile is None else ("模型工具模式" if not self.read_only else "模型只读模式"),
            {
                "mode": "demo" if self.profile is None else ("tools" if not self.read_only else "read_only"),
                "tool_calling": self.tool_calling or "not_probed",
            },
        )
        if self.profile:
            try:
                return await self._run_pydantic_ai(prompt, deps)
            except ApprovalRequired:
                return AgentAnswer(
                    summary="操作需要在审批面板中确认后继续。",
                    status=RunStatus.PENDING_APPROVAL,
                )
            except ProviderError as exc:
                await deps.emit("provider_unavailable", str(exc), {})
            except Exception as exc:
                await deps.emit(
                    "provider_failed", "模型调用失败，已切换到演示诊断模式。", {"error": str(exc)}
                )
        return await self._run_demo(prompt, deps, read_only=self.profile is not None)

    async def _run_pydantic_ai(self, prompt: str, deps: RuntimeDeps) -> AgentAnswer:
        model = build_model(self.profile) if self.profile else None
        if model is None:
            raise ProviderError("provider_not_configured")
        from pydantic_ai import Agent, RunContext

        agent = Agent(
            model,
            deps_type=RuntimeDeps,
            output_type=AgentAnswer,
            instructions=(
                "你是 Minecraft 服务器运维助手。只能通过已注册的 typed tools 获取事实或执行动作。"
                "不要声称没有执行的操作已经完成；所有结论引用工具返回的证据。"
                "处理模组需求时遵循：分析项目 → 读取相关文件 → 提出最小补丁 →"
                "（审批后）应用 →（审批后）构建 → 创建并运行测试场景。"
                "mc_test 场景工具只生成结构化步骤，Demo 测试不会启动真实 Minecraft；不得伪造截图、客户端日志或构建产物。"
            ),
        )

        @agent.tool
        async def server_status(ctx: RunContext[RuntimeDeps]) -> ToolOutcome:
            return await ctx.deps.call_tool("get_status")

        @agent.tool
        async def recent_logs(ctx: RunContext[RuntimeDeps], limit: int = 100) -> ToolOutcome:
            return await ctx.deps.call_tool("get_logs", limit=limit)

        @agent.tool
        async def server_players(ctx: RunContext[RuntimeDeps]) -> ToolOutcome:
            return await ctx.deps.call_tool("get_players")

        @agent.tool
        async def diagnose_incident(ctx: RunContext[RuntimeDeps]) -> ToolOutcome:
            return await ctx.deps.call_tool("diagnose_incident")

        @agent.tool
        async def inspect_mod_project(
            ctx: RunContext[RuntimeDeps], project_id: str = "demo-mod"
        ) -> ToolOutcome:
            return await ctx.deps.call_tool("inspect_mod_project", project_id=project_id)

        @agent.tool
        async def plan_mod_task(
            ctx: RunContext[RuntimeDeps], request: str, project_id: str = "demo-mod"
        ) -> ToolOutcome:
            return await ctx.deps.call_tool("plan_mod_task", project_id=project_id, request=request)

        @agent.tool
        async def list_mod_files(
            ctx: RunContext[RuntimeDeps], project_id: str = "demo-mod", prefix: str = ""
        ) -> ToolOutcome:
            return await ctx.deps.call_tool("list_mod_files", project_id=project_id, prefix=prefix)

        @agent.tool
        async def read_mod_file(
            ctx: RunContext[RuntimeDeps], path: str, project_id: str = "demo-mod"
        ) -> ToolOutcome:
            return await ctx.deps.call_tool("read_mod_file", project_id=project_id, path=path)

        @agent.tool
        async def list_mod_evidence(
            ctx: RunContext[RuntimeDeps], project_id: str = "demo-mod"
        ) -> ToolOutcome:
            return await ctx.deps.call_tool("list_mod_evidence", project_id=project_id)

        @agent.tool
        async def list_mod_patches(
            ctx: RunContext[RuntimeDeps], project_id: str = "demo-mod"
        ) -> ToolOutcome:
            return await ctx.deps.call_tool("list_mod_patches", project_id=project_id)

        @agent.tool
        async def list_mod_scenarios(
            ctx: RunContext[RuntimeDeps], project_id: str = "demo-mod"
        ) -> ToolOutcome:
            return await ctx.deps.call_tool("list_mod_scenarios", project_id=project_id)

        if not self.read_only:
            @agent.tool
            async def restart_server(ctx: RunContext[RuntimeDeps]) -> ToolOutcome:
                return await ctx.deps.call_tool("restart")

            @agent.tool
            async def start_server(ctx: RunContext[RuntimeDeps]) -> ToolOutcome:
                return await ctx.deps.call_tool("start")

            @agent.tool
            async def stop_server(ctx: RunContext[RuntimeDeps]) -> ToolOutcome:
                return await ctx.deps.call_tool("stop")

            @agent.tool
            async def create_server_backup(ctx: RunContext[RuntimeDeps]) -> ToolOutcome:
                return await ctx.deps.call_tool("create_backup")

            @agent.tool
            async def verify_server_backup(
                ctx: RunContext[RuntimeDeps], backup_id: str
            ) -> ToolOutcome:
                return await ctx.deps.call_tool("verify_backup", backup_id=backup_id)

            @agent.tool
            async def restore_server_backup(
                ctx: RunContext[RuntimeDeps], backup_id: str
            ) -> ToolOutcome:
                return await ctx.deps.call_tool("restore_backup", backup_id=backup_id)

            @agent.tool
            async def propose_mod_patch(
                ctx: RunContext[RuntimeDeps],
                title: str,
                rationale: str,
                changes: list[ModPatchChange],
                project_id: str = "demo-mod",
            ) -> ToolOutcome:
                return await ctx.deps.call_tool(
                    "propose_mod_patch",
                    project_id=project_id,
                    title=title,
                    rationale=rationale,
                    changes=[item.model_dump(mode="json") for item in changes],
                )

            @agent.tool
            async def apply_mod_patch(
                ctx: RunContext[RuntimeDeps], patch_id: str
            ) -> ToolOutcome:
                return await ctx.deps.call_tool("apply_mod_patch", patch_id=patch_id)

            @agent.tool
            async def build_mod_project(
                ctx: RunContext[RuntimeDeps], project_id: str = "demo-mod", clean: bool = False
            ) -> ToolOutcome:
                return await ctx.deps.call_tool(
                    "build_mod_project", project_id=project_id, clean=clean
                )

            @agent.tool
            async def create_mod_test_scenario(
                ctx: RunContext[RuntimeDeps],
                kind: ModTestScenarioKind,
                project_id: str = "demo-mod",
                title: str | None = None,
                steps: list[str] | None = None,
                assertions: list[str] | None = None,
            ) -> ToolOutcome:
                return await ctx.deps.call_tool(
                    "create_mod_test_scenario",
                    project_id=project_id,
                    kind=kind.value,
                    title=title,
                    steps=steps or [],
                    assertions=assertions or [],
                )

            @agent.tool
            async def run_demo_mod_test(
                ctx: RunContext[RuntimeDeps], scenario_id: str
            ) -> ToolOutcome:
                return await ctx.deps.call_tool("run_demo_mod_test", scenario_id=scenario_id)

        async with agent.iter(prompt, deps=deps) as run:
            async for node in run:
                await deps.emit(
                    "agent_step",
                    f"Agent 节点：{type(node).__name__}",
                    {"node": type(node).__name__},
                )
            return run.result.output

    async def _run_demo(
        self, prompt: str, deps: RuntimeDeps, *, read_only: bool = False
    ) -> AgentAnswer:
        lowered = prompt.lower()
        if any(word in lowered for word in ("模组", "mod", "fabric", "forge", "neoforge", "addon")):
            project_id = deps.mod_project_id or "demo-mod"
            if any(word in lowered for word in ("分析", "项目", "inspect", "结构")) and not any(
                word in lowered for word in ("规划", "计划", "plan")
            ):
                outcome = await deps.call_tool("inspect_mod_project", project_id=project_id)
                data = outcome.data
                return AgentAnswer(
                    summary=data.get("summary", "已完成模组项目分析。"),
                    evidence=[Evidence(source="inspect_mod_project", excerpt=str(data))],
                    recommendations=data.get("next_actions", []),
                    executed_tools=["inspect_mod_project"],
                )
            if any(word in lowered for word in ("规划", "计划", "plan")):
                outcome = await deps.call_tool(
                    "plan_mod_task", project_id=project_id, request=prompt
                )
                data = outcome.data
                return AgentAnswer(
                    summary=f"已生成模组开发计划：{data.get('objective', '未命名需求')}。",
                    evidence=[Evidence(source="plan_mod_task", excerpt=str(data))],
                    recommendations=data.get("next_actions", []),
                    executed_tools=["plan_mod_task"],
                )
            if any(word in lowered for word in ("构建", "build", "编译")):
                if read_only:
                    return AgentAnswer(
                        summary="当前 provider 只读能力未确认，未执行模组构建。",
                        status=RunStatus.FAILED,
                        recommendations=["完成 provider 在线工具能力探测后再请求构建。"],
                    )
                outcome = await deps.call_tool("build_mod_project", project_id=project_id)
                data = outcome.data
                return AgentAnswer(
                    summary=(
                        f"模组构建状态：{data.get('status', outcome.status)}。"
                        if data
                        else "模组构建已提交。"
                    ),
                    evidence=[Evidence(source="build_mod_project", excerpt=str(data))],
                    recommendations=["构建成功后创建对应的测试场景。"],
                    executed_tools=["build_mod_project"],
                )
            if any(word in lowered for word in ("测试", "场景", "验证", "test")):
                kind = _scenario_kind_from_prompt(lowered)
                created = await deps.call_tool(
                    "create_mod_test_scenario", project_id=project_id, kind=kind.value
                )
                scenario_id = created.data.get("id")
                if not scenario_id:
                    return AgentAnswer(
                        summary="测试场景草稿创建失败。",
                        status=RunStatus.FAILED,
                        evidence=[Evidence(source="create_mod_test_scenario", excerpt=str(created.data))],
                    )
                result = await deps.call_tool("run_demo_mod_test", scenario_id=scenario_id)
                return AgentAnswer(
                    summary=result.data.get("summary", result.status),
                    evidence=[Evidence(source="run_demo_mod_test", excerpt=str(result.data))],
                    recommendations=result.data.get("next_actions", []),
                    executed_tools=["create_mod_test_scenario", "run_demo_mod_test"],
                    status=RunStatus.COMPLETED if result.ok else RunStatus.FAILED,
                )
            if any(word in lowered for word in ("读取", "查看文件", "文件", "read")):
                path = "src/main/java/com/anl/mineops/demo/DemoMod.java"
                outcome = await deps.call_tool("read_mod_file", project_id=project_id, path=path)
                return AgentAnswer(
                    summary=f"已读取模组文件：{path}。",
                    evidence=[Evidence(source="read_mod_file", excerpt=outcome.data.get("content", "")[:4000])],
                    recommendations=["如果要修改，请先说明目标行为，再生成最小补丁。"],
                    executed_tools=["read_mod_file"],
                )
            return AgentAnswer(
                summary="我可以按 ModCrafting 式流程分析模组项目、读取文件、生成补丁草稿、构建并运行六类 Demo 测试场景。",
                recommendations=[
                    "试试：分析 demo 模组项目。",
                    "试试：为新物品创建测试场景并验证。",
                    "试试：构建模组（构建动作需要审批）。",
                ],
            )
        if any(word in lowered for word in ("状态", "status", "在线")):
            outcome = await deps.call_tool("get_status")
            return AgentAnswer(
                summary=_status_summary(outcome.data),
                evidence=[Evidence(source="server_status", excerpt=str(outcome.data))],
                executed_tools=["get_status"],
            )
        if any(word in lowered for word in ("日志", "崩溃", "crash", "error", "诊断")):
            outcome = await deps.call_tool("diagnose_incident")
            data = outcome.data
            return AgentAnswer(
                summary=f"已检查最近日志，发现 {data.get('error_count', 0)} 条错误级记录。",
                evidence=[Evidence(source="diagnose_incident", excerpt=str(data))],
                recommendations=["先查看最近错误日志，再决定是否重启；不要跳过备份。"],
                executed_tools=["diagnose_incident"],
            )
        if any(word in lowered for word in ("玩家", "player", "在线人数")):
            outcome = await deps.call_tool("get_players")
            return AgentAnswer(
                summary=f"当前在线玩家：{', '.join(outcome.data.get('players', [])) or '无'}。",
                evidence=[Evidence(source="get_players", excerpt=str(outcome.data))],
                executed_tools=["get_players"],
            )
        if any(word in lowered for word in ("重启", "restart")):
            if read_only:
                return AgentAnswer(
                    summary="模型不可用，已降级为只读模式，未执行重启。",
                    status=RunStatus.FAILED,
                    recommendations=["配置可用的 provider 后再重试。"],
                )
            await deps.call_tool("restart")
            return AgentAnswer(summary="重启已完成。", executed_tools=["restart"])
        if any(word in lowered for word in ("启动", "start")):
            if read_only:
                return AgentAnswer(
                    summary="模型不可用，已降级为只读模式，未执行启动。",
                    status=RunStatus.FAILED,
                    recommendations=["配置可用的 provider 后再重试。"],
                )
            await deps.call_tool("start")
            return AgentAnswer(summary="启动已完成。", executed_tools=["start"])
        if any(word in lowered for word in ("停止", "停服", "stop")):
            if read_only:
                return AgentAnswer(
                    summary="模型不可用，已降级为只读模式，未执行停止。",
                    status=RunStatus.FAILED,
                    recommendations=["配置可用的 provider 后再重试。"],
                )
            await deps.call_tool("stop")
            return AgentAnswer(summary="停止已完成。", executed_tools=["stop"])
        if any(word in lowered for word in ("备份", "backup")):
            if read_only:
                return AgentAnswer(
                    summary="模型不可用，已降级为只读模式，未执行备份。",
                    status=RunStatus.FAILED,
                    recommendations=["配置可用的 provider 后再重试。"],
                )
            outcome = await deps.call_tool("create_backup")
            return AgentAnswer(
                summary=f"备份已完成：{outcome.data.get('id', 'unknown')}。",
                evidence=[Evidence(source="create_backup", excerpt=str(outcome.data))],
                executed_tools=["create_backup"],
            )
        return AgentAnswer(
            summary="我现在可以帮你查询状态、日志、玩家和诊断问题，也可以按工具策略执行重启或备份。",
            recommendations=["试试：服务器现在状态怎么样？", "试试：检查最近崩溃日志。"],
        )


def _scenario_kind_from_prompt(prompt: str) -> ModTestScenarioKind:
    if any(word in prompt for word in ("方块", "block")):
        return ModTestScenarioKind.NEW_BLOCK
    if any(word in prompt for word in ("配方", "recipe", "合成")):
        return ModTestScenarioKind.NEW_RECIPE
    if any(word in prompt for word in ("实体", "生物", "entity", "mob")):
        return ModTestScenarioKind.ENTITY_BEHAVIOR
    if any(word in prompt for word in ("交互", "interaction")):
        return ModTestScenarioKind.PLAYER_INTERACTION
    if any(word in prompt for word in ("界面", "hud", "gui", "菜单")):
        return ModTestScenarioKind.HUD_GUI
    return ModTestScenarioKind.NEW_ITEM


def _status_summary(data: dict[str, Any]) -> str:
    return f"服务器状态：{data.get('status', 'unknown')}，在线玩家 {data.get('online_players', 0)}/{data.get('max_players', 0)}。"
