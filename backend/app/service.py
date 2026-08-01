import asyncio
import secrets
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from .adapters import DemoAdapter, ServerAdapter
from .agent_runtime import AgentRuntime, RuntimeDeps
from .mod_workspace import ModWorkspaceService
from .policy import ApprovalRequired, PolicyEngine
from .schemas import (
    AdapterKind,
    AgentAnswer,
    ApprovalRecord,
    AuditEvent,
    BackupRecord,
    PolicyMode,
    ProviderProbeResult,
    ProviderProfile,
    RunCreate,
    RunEvent,
    RunRecord,
    RunStatus,
    ServerConfig,
    ServerSummary,
    ToolPolicy,
)
from .server_registry import build_adapter
from .storage import Store, utcnow


async def _noop_emit(*_: Any) -> None:
    return None


class RunBus:
    def __init__(self) -> None:
        self.queues: dict[str, asyncio.Queue[RunEvent]] = defaultdict(asyncio.Queue)

    async def publish(self, event: RunEvent) -> None:
        await self.queues[event.run_id].put(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[RunEvent]:
        while True:
            event = await self.queues[run_id].get()
            yield event
            if event.type in {"run_completed", "run_failed", "approval_required"}:
                return


class MineOpsService:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.policy = PolicyEngine(store)
        self.mod_workspace = ModWorkspaceService(store)
        self.bus = RunBus()
        self.adapters: dict[str, ServerAdapter] = {"demo": DemoAdapter()}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        if not self.store.get_server_config("demo"):
            self.store.save_server_config(
                ServerConfig(id="demo", name="演示服务器", adapter=AdapterKind.DEMO)
            )
        self.adapter_errors: dict[str, str] = {}
        for config in self.store.list_server_configs():
            if config.id == "demo" or not config.enabled:
                continue
            try:
                self.adapters[config.id] = build_adapter(config)
            except Exception as exc:
                self.adapter_errors[config.id] = str(exc)

    def add_adapter(self, adapter: ServerAdapter) -> None:
        self.adapters[adapter.server_id] = adapter

    def list_server_configs(self) -> list[ServerConfig]:
        return self.store.list_server_configs()

    def save_server_config(self, config: ServerConfig) -> ServerConfig:
        adapter = build_adapter(config)
        self.store.save_server_config(config)
        self.adapter_errors.pop(config.id, None)
        if config.enabled:
            self.adapters[config.id] = adapter
        else:
            self.adapters.pop(config.id, None)
        return config

    def get_server_config(self, server_id: str) -> ServerConfig | None:
        return self.store.get_server_config(server_id)

    def list_backups(self, server_id: str) -> list[BackupRecord]:
        return self.store.list_backups(server_id)

    def create_mcp_run(self, server_id: str, tool_name: str, mod_project_id: str | None = None) -> RunRecord:
        self.get_adapter(server_id)
        if mod_project_id:
            self.mod_workspace.get_project(mod_project_id)
        now = utcnow()
        run = RunRecord(
            id=f"mcp-{secrets.token_urlsafe(12)}",
            prompt=f"MCP 调用：{tool_name}",
            server_id=server_id,
            mod_project_id=mod_project_id,
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
        self.store.save_run(run)
        return run

    async def execute_mod_tool(
        self, project_id: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.mod_workspace.get_project(project_id)
        run = self.create_mcp_run("demo", tool_name, project_id)
        deps = RuntimeDeps(
            server_id="demo",
            adapter=self.get_adapter("demo"),
            policy=self.policy,
            run_id=run.id,
            mod_workspace=self.mod_workspace,
            mod_project_id=project_id,
            emit=lambda *_: _noop_emit(),
        )
        try:
            call_arguments = dict(arguments or {})
            call_arguments.setdefault("project_id", project_id)
            outcome = await deps.call_tool(tool_name, **call_arguments)
        except ApprovalRequired as exc:
            self.store.save_run(
                run.model_copy(update={"status": RunStatus.PENDING_APPROVAL, "updated_at": utcnow()})
            )
            return {
                "status": "pending_approval",
                "run_id": run.id,
                "approval_id": exc.approval.id,
                "tool_name": tool_name,
            }
        except Exception as exc:
            self.store.save_run(
                run.model_copy(update={"status": RunStatus.FAILED, "updated_at": utcnow()})
            )
            self.policy.audit(
                run_id=run.id,
                tool_name=tool_name,
                action="mod_tool_call",
                status="failed",
                details={"error": str(exc), "project_id": project_id},
            )
            raise
        status = RunStatus.COMPLETED if outcome.ok else RunStatus.FAILED
        answer = AgentAnswer(
            summary=f"模组工具已执行：{tool_name}。",
            executed_tools=[tool_name],
        )
        self.store.save_run(
            run.model_copy(update={"status": status, "answer": answer, "updated_at": utcnow()})
        )
        return {
            "status": outcome.status,
            "run_id": run.id,
            "outcome": outcome.model_dump(mode="json"),
        }

    def get_adapter(self, server_id: str) -> ServerAdapter:
        try:
            return self.adapters[server_id]
        except KeyError as exc:
            raise KeyError("server_not_found") from exc

    async def list_servers(self) -> list[ServerSummary]:
        return [await adapter.get_status() for adapter in self.adapters.values()]

    def list_providers(self) -> list[ProviderProfile]:
        return self.store.list_providers()

    def save_provider(self, profile: ProviderProfile) -> ProviderProfile:
        self.store.save_provider(profile)
        self.store.delete_provider_probe(profile.id)
        return profile

    def get_provider(self, provider_id: str | None) -> ProviderProfile | None:
        return self.store.get_provider(provider_id) if provider_id else None

    def get_provider_probe(self, provider_id: str | None) -> ProviderProbeResult | None:
        return self.store.get_provider_probe(provider_id) if provider_id else None

    async def start_run(self, request: RunCreate) -> RunRecord:
        self.get_adapter(request.server_id)
        if request.provider_id and not self.get_provider(request.provider_id):
            raise KeyError("provider_not_found")
        if request.mod_project_id:
            self.mod_workspace.get_project(request.mod_project_id)
        now = utcnow()
        run = RunRecord(
            id=secrets.token_urlsafe(12),
            prompt=request.prompt,
            server_id=request.server_id,
            provider_id=request.provider_id,
            mod_project_id=request.mod_project_id,
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
        self.store.save_run(run)
        task = asyncio.create_task(self._execute_run(run))
        self.tasks[run.id] = task
        return run

    async def _emit(self, run_id: str, event_type: str, message: str, data: dict[str, Any]) -> None:
        event = self.store.add_event(
            RunEvent(
                id=0,
                run_id=run_id,
                type=event_type,
                message=message,
                data=data,
                created_at=utcnow(),
            )
        )
        await self.bus.publish(event)

    async def _execute_run(self, run: RunRecord) -> None:
        await self._emit(run.id, "run_started", "Agent 开始处理请求", {"prompt": run.prompt})
        try:
            profile = self.get_provider(run.provider_id)
            probe = self.get_provider_probe(run.provider_id)
            tool_calling = probe.capabilities.get("tool_calling") if probe and probe.live else None
            runtime = AgentRuntime(profile, tool_calling=tool_calling)
            deps = RuntimeDeps(
                server_id=run.server_id,
                adapter=self.get_adapter(run.server_id),
                policy=self.policy,
                run_id=run.id,
                mod_workspace=self.mod_workspace,
                mod_project_id=run.mod_project_id,
                emit=lambda event_type, message, data: self._emit(
                    run.id, event_type, message, data
                ),
            )
            answer = await runtime.run(run.prompt, deps)
            updated = run.model_copy(
                update={
                    "status": answer.status,
                    "answer": answer,
                    "updated_at": utcnow(),
                }
            )
            self.store.save_run(updated)
            await self._emit(
                run.id,
                "approval_required"
                if answer.status == RunStatus.PENDING_APPROVAL
                else "run_completed",
                "等待审批" if answer.status == RunStatus.PENDING_APPROVAL else "Agent 已完成",
                {"answer": answer.model_dump(mode="json")},
            )
        except ApprovalRequired as exc:
            updated = run.model_copy(
                update={"status": RunStatus.PENDING_APPROVAL, "updated_at": utcnow()}
            )
            self.store.save_run(updated)
            await self._emit(
                run.id,
                "approval_required",
                "操作需要审批",
                {"approval_id": exc.approval.id, "tool_name": exc.approval.tool_name},
            )
        except Exception as exc:
            updated = run.model_copy(update={"status": RunStatus.FAILED, "updated_at": utcnow()})
            self.store.save_run(updated)
            self.policy.audit(
                run_id=run.id,
                tool_name=None,
                action="agent_run",
                status="failed",
                details={"error": str(exc)},
            )
            await self._emit(run.id, "run_failed", "Agent 执行失败", {"error": str(exc)})

    async def events(self, run_id: str) -> AsyncIterator[RunEvent]:
        for event in self.store.list_events(run_id):
            yield event
        run = self.store.get_run(run_id)
        if run and run.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.PENDING_APPROVAL,
        }:
            return
        async for event in self.bus.subscribe(run_id):
            yield event

    def get_run(self, run_id: str) -> RunRecord | None:
        return self.store.get_run(run_id)

    def list_policies(self) -> list[ToolPolicy]:
        return self.store.list_policies()

    def update_policy(self, policy: ToolPolicy) -> ToolPolicy:
        self.store.save_policy(policy)
        return policy

    def list_approvals(self, pending_only: bool = False) -> list[ApprovalRecord]:
        return self.store.list_approvals(pending_only=pending_only)

    async def resolve_approval(self, approval_id: str, approved: bool) -> ApprovalRecord:
        approval = self.policy.approve(approval_id, approved)
        self.policy.audit(
            run_id=approval.run_id,
            tool_name=approval.tool_name,
            action="approval",
            status=approval.status,
            details={"approval_id": approval.id},
        )
        if approval.status == "approved":
            run = self.get_run(approval.run_id)
            if run:
                await self._execute_approved_tool(run, approval)
        elif approval.status in {"rejected", "expired"}:
            run = self.get_run(approval.run_id)
            if run:
                answer = AgentAnswer(
                    summary=(
                        "审批已拒绝，未执行操作。"
                        if approval.status == "rejected"
                        else "审批已过期，未执行操作。"
                    ),
                    status=RunStatus.FAILED,
                )
                self.store.save_run(
                    run.model_copy(
                        update={
                            "status": RunStatus.FAILED,
                            "answer": answer,
                            "updated_at": utcnow(),
                        }
                    )
                )
                await self._emit(
                    run.id,
                    "run_failed",
                    answer.summary,
                    {"approval_id": approval.id, "status": approval.status},
                )
        return approval

    async def _execute_approved_tool(self, run: RunRecord, approval: ApprovalRecord) -> None:
        deps = RuntimeDeps(
            server_id=run.server_id,
            adapter=self.get_adapter(run.server_id),
            policy=self.policy,
            run_id=run.id,
            mod_workspace=self.mod_workspace,
            mod_project_id=run.mod_project_id,
            emit=lambda event_type, message, data: self._emit(run.id, event_type, message, data),
        )
        original = self.store.get_policy(approval.tool_name)
        if original:
            self.store.save_policy(original.model_copy(update={"mode": PolicyMode.AUTO}))
        try:
            outcome = await deps.call_tool(approval.tool_name, **approval.arguments)
            answer = AgentAnswer(
                summary=(
                    f"已按审批执行：{approval.tool_name}。"
                    if outcome.ok
                    else f"审批操作未成功：{approval.tool_name}。"
                ),
                executed_tools=[approval.tool_name],
                evidence=[{"source": approval.tool_name, "excerpt": str(outcome.data)}],
                status=RunStatus.COMPLETED if outcome.ok else RunStatus.FAILED,
            )
            updated = run.model_copy(
                update={
                    "status": answer.status,
                    "answer": answer,
                    "updated_at": utcnow(),
                }
            )
            self.store.save_run(updated)
            await self._emit(
                run.id,
                "run_completed" if outcome.ok else "run_failed",
                "审批操作已完成" if outcome.ok else "审批操作失败",
                {"answer": answer.model_dump(mode="json")},
            )
        except Exception as exc:
            updated = run.model_copy(update={"status": RunStatus.FAILED, "updated_at": utcnow()})
            self.store.save_run(updated)
            await self._emit(run.id, "run_failed", "审批操作失败", {"error": str(exc)})
        finally:
            if original:
                self.store.save_policy(original)

    def list_audits(self, limit: int = 100) -> list[AuditEvent]:
        return self.store.list_audits(limit)
