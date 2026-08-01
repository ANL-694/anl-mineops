import pytest

from backend.app.policy import ApprovalRequired, PolicyEngine
from backend.app.schemas import PolicyMode, Risk, ToolPolicy
from backend.app.storage import Store


def test_confirm_policy_creates_approval(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    engine = PolicyEngine(store)
    try:
        engine.store.save_policy(
            ToolPolicy(tool_name="restart", risk=Risk.MUTATE, mode=PolicyMode.CONFIRM)
        )
        with pytest.raises(ApprovalRequired):
            engine.check("restart", "demo", {}, "run-1")
        approvals = store.list_approvals(pending_only=True)
        assert len(approvals) == 1
        assert approvals[0].tool_name == "restart"
    finally:
        store.close()


def test_memory_store_does_not_create_database_file(tmp_path):
    store = Store(":memory:")
    try:
        assert not (tmp_path / ":memory:").exists()
    finally:
        store.close()


@pytest.mark.asyncio
async def test_mcp_run_can_resume_after_approval(tmp_path):
    from backend.app.service import MineOpsService

    service = MineOpsService(Store(str(tmp_path / "mcp.db")))
    run = service.create_mcp_run("demo", "restart")
    with pytest.raises(ApprovalRequired):
        service.policy.check("restart", "demo", {}, run.id)
    approval = service.store.list_approvals(pending_only=True)[0]
    await service.resolve_approval(approval.id, True)
    assert service.get_run(run.id).status.value == "completed"
    service.store.close()
