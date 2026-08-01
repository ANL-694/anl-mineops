import secrets
from datetime import timedelta
from typing import Any

from .schemas import ApprovalRecord, AuditEvent, PolicyMode, Risk, ToolPolicy
from .storage import Store, utcnow

DEFAULT_POLICIES = [
    ToolPolicy(tool_name="get_status", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="get_logs", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="get_players", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="diagnose_incident", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="start", risk=Risk.MUTATE, mode=PolicyMode.CONFIRM),
    ToolPolicy(tool_name="stop", risk=Risk.MUTATE, mode=PolicyMode.CONFIRM),
    ToolPolicy(tool_name="restart", risk=Risk.MUTATE, mode=PolicyMode.CONFIRM),
    ToolPolicy(tool_name="create_backup", risk=Risk.MUTATE, mode=PolicyMode.CONFIRM),
    ToolPolicy(tool_name="verify_backup", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="restore_backup", risk=Risk.DESTRUCTIVE, mode=PolicyMode.DISABLED),
    ToolPolicy(tool_name="inspect_mod_project", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="plan_mod_task", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="list_mod_files", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="read_mod_file", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="list_mod_evidence", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="list_mod_patches", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="list_mod_scenarios", risk=Risk.READ, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="propose_mod_patch", risk=Risk.MUTATE, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="apply_mod_patch", risk=Risk.MUTATE, mode=PolicyMode.CONFIRM),
    ToolPolicy(tool_name="build_mod_project", risk=Risk.MUTATE, mode=PolicyMode.CONFIRM),
    ToolPolicy(tool_name="create_mod_test_scenario", risk=Risk.MUTATE, mode=PolicyMode.AUTO),
    ToolPolicy(tool_name="run_demo_mod_test", risk=Risk.READ, mode=PolicyMode.AUTO),
]


class ApprovalRequired(Exception):
    def __init__(self, approval: ApprovalRecord) -> None:
        self.approval = approval
        super().__init__(f"approval_required:{approval.id}")


class PolicyEngine:
    def __init__(self, store: Store) -> None:
        self.store = store
        existing = {policy.tool_name for policy in self.store.list_policies()}
        for policy in DEFAULT_POLICIES:
            if policy.tool_name not in existing:
                self.store.save_policy(policy)

    def get(self, tool_name: str) -> ToolPolicy:
        policy = self.store.get_policy(tool_name)
        if policy:
            return policy
        return ToolPolicy(tool_name=tool_name, risk=Risk.MUTATE, mode=PolicyMode.CONFIRM)

    def check(self, tool_name: str, server_id: str, arguments: dict[str, Any], run_id: str) -> None:
        policy = self.get(tool_name)
        if policy.allowed_server_ids and server_id not in policy.allowed_server_ids:
            raise PermissionError("server_not_allowed")
        if policy.mode == PolicyMode.DISABLED:
            raise PermissionError("tool_disabled")
        if policy.mode != PolicyMode.CONFIRM:
            return
        approval = ApprovalRecord(
            id=secrets.token_urlsafe(12),
            run_id=run_id,
            tool_name=tool_name,
            server_id=server_id,
            arguments=arguments,
            status="pending",
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(minutes=10),
        )
        self.store.save_approval(approval)
        raise ApprovalRequired(approval)

    def approve(self, approval_id: str, approved: bool) -> ApprovalRecord:
        approval = self.store.get_approval(approval_id)
        if not approval:
            raise KeyError("approval_not_found")
        if approval.status != "pending":
            raise ValueError("approval_already_resolved")
        if approval.expires_at <= utcnow():
            approval = approval.model_copy(update={"status": "expired"})
        else:
            approval = approval.model_copy(
                update={"status": "approved" if approved else "rejected"}
            )
        self.store.save_approval(approval)
        return approval

    def audit(
        self,
        *,
        run_id: str | None,
        tool_name: str | None,
        action: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=secrets.token_urlsafe(12),
            run_id=run_id,
            actor="local-user",
            tool_name=tool_name,
            action=action,
            status=status,
            details=details or {},
            created_at=utcnow(),
        )
        self.store.save_audit(event)
        return event
