import pytest
from pydantic_ai.models.test import TestModel

from backend.app.adapters import DemoAdapter
from backend.app.agent_runtime import AgentRuntime, RuntimeDeps
from backend.app.policy import PolicyEngine
from backend.app.schemas import ProviderProfile
from backend.app.storage import Store


@pytest.mark.asyncio
async def test_pydantic_ai_runtime_uses_test_model_without_network(monkeypatch, tmp_path):
    profile = ProviderProfile(
        id="test-model",
        name="测试模型",
        base_url="https://example.com/v1",
        model="fixture-model",
        api_key_env="TEST_MODEL_KEY",
    )
    test_model = TestModel(
        call_tools=[],
        custom_output_args={
            "summary": "fixture answer",
            "executed_tools": [],
        },
    )
    monkeypatch.setattr("backend.app.agent_runtime.build_model", lambda _: test_model)
    store = Store(str(tmp_path / "agent.db"))
    emitted: list[str] = []

    async def emit(event_type: str, message: str, data: dict):
        emitted.append(event_type)

    deps = RuntimeDeps(
        server_id="demo",
        adapter=DemoAdapter(),
        policy=PolicyEngine(store),
        run_id="test-run",
        emit=emit,
    )
    answer = await AgentRuntime(profile).run("给我一个 fixture 回复", deps)
    assert answer.summary == "fixture answer"
    assert "agent_step" in emitted
    store.close()


@pytest.mark.asyncio
async def test_provider_without_tool_capability_registers_read_tools_only(monkeypatch, tmp_path):
    profile = ProviderProfile(
        id="read-only-model",
        name="只读模型",
        base_url="https://example.com/v1",
        model="fixture-model",
        api_key_env="READ_ONLY_MODEL_KEY",
    )
    test_model = TestModel(
        call_tools=[],
        custom_output_args={"summary": "只读回复", "executed_tools": []},
    )
    monkeypatch.setattr("backend.app.agent_runtime.build_model", lambda _: test_model)
    store = Store(str(tmp_path / "read-only.db"))

    async def emit(event_type: str, message: str, data: dict):
        return None

    deps = RuntimeDeps(
        server_id="demo",
        adapter=DemoAdapter(),
        policy=PolicyEngine(store),
        run_id="read-only-run",
        emit=emit,
    )
    answer = await AgentRuntime(profile, tool_calling="unsupported").run("请重启服务器", deps)

    registered_tools = {tool.name for tool in test_model.last_model_request_parameters.function_tools}
    assert {"server_status", "recent_logs", "server_players", "diagnose_incident"} <= registered_tools
    assert not {"restart_server", "start_server", "stop_server", "create_server_backup"} & registered_tools
    assert answer.summary == "只读回复"
    store.close()


@pytest.mark.asyncio
async def test_provider_with_tool_capability_registers_mutating_tools(monkeypatch, tmp_path):
    profile = ProviderProfile(
        id="tool-model",
        name="工具模型",
        base_url="https://example.com/v1",
        model="fixture-model",
        api_key_env="TOOL_MODEL_KEY",
    )
    test_model = TestModel(
        call_tools=[],
        custom_output_args={"summary": "工具回复", "executed_tools": []},
    )
    monkeypatch.setattr("backend.app.agent_runtime.build_model", lambda _: test_model)
    store = Store(str(tmp_path / "tool-model.db"))

    async def emit(event_type: str, message: str, data: dict):
        return None

    deps = RuntimeDeps(
        server_id="demo",
        adapter=DemoAdapter(),
        policy=PolicyEngine(store),
        run_id="tool-run",
        emit=emit,
    )
    await AgentRuntime(profile, tool_calling="supported").run("请重启服务器", deps)

    registered_tools = {tool.name for tool in test_model.last_model_request_parameters.function_tools}
    assert {"restart_server", "start_server", "stop_server", "create_server_backup"} <= registered_tools
    store.close()


def test_provider_probe_does_not_require_network_for_environment_mode(monkeypatch):
    from backend.app.providers import probe_environment

    monkeypatch.delenv("MISSING_PROVIDER_KEY", raising=False)
    profile = ProviderProfile(
        id="probe-test",
        name="探测测试",
        base_url="https://example.com/v1",
        model="fixture-model",
        api_key_env="MISSING_PROVIDER_KEY",
    )
    result = probe_environment(profile)
    assert result.api_key_configured is False
    assert result.live is False
    assert result.capabilities["tool_calling"] == "not_probed"


@pytest.mark.asyncio
async def test_live_provider_probe_reads_model_catalog_without_exposing_key(monkeypatch):
    from backend.app import providers

    class FakeResponse:
        status_code = 200
        is_success = True

        def json(self):
            return {
                "data": [
                    {
                        "id": "fixture-model",
                        "capabilities": {"tool_calling": True, "streaming": "supported"},
                    }
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            assert url == "https://example.com/v1/models"
            assert headers == {"Authorization": "Bearer fixture-secret"}
            return FakeResponse()

    monkeypatch.setenv("FIXTURE_PROVIDER_KEY", "fixture-secret")
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    profile = ProviderProfile(
        id="probe-live",
        name="在线探测",
        base_url="https://example.com/v1",
        model="fixture-model",
        api_key_env="FIXTURE_PROVIDER_KEY",
    )

    result = await providers.probe_provider(profile, live=True)

    assert result.reachable is True
    assert result.http_status == 200
    assert result.model_available is True
    assert result.capabilities == {"tool_calling": "supported", "streaming": "supported"}
    assert "fixture-secret" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_live_provider_probe_reports_missing_key_without_network(monkeypatch):
    from backend.app import providers

    class UnexpectedClient:
        def __init__(self, **kwargs):
            raise AssertionError("missing-key probe must not make a network request")

    monkeypatch.delenv("MISSING_LIVE_PROVIDER_KEY", raising=False)
    monkeypatch.setattr(providers.httpx, "AsyncClient", UnexpectedClient)
    profile = ProviderProfile(
        id="probe-missing",
        name="缺少密钥",
        base_url="https://example.com/v1",
        model="fixture-model",
        api_key_env="MISSING_LIVE_PROVIDER_KEY",
    )

    result = await providers.probe_provider(profile, live=True)

    assert result.live is True
    assert result.reachable is None
    assert result.error == "missing_api_key_env:MISSING_LIVE_PROVIDER_KEY"
    assert "MISSING_LIVE_PROVIDER_KEY" in result.error
