import asyncio

import httpx
import pytest

from backend.app.main import create_app


@pytest.mark.asyncio
async def test_run_status_and_events(tmp_path):
    app = create_app(str(tmp_path / "api.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/v1/health")
        assert health.status_code == 200
        created = await client.post(
            "/api/v1/runs", json={"prompt": "服务器现在状态怎么样？", "server_id": "demo"}
        )
        assert created.status_code == 202
        run_id = created.json()["data"]["id"]
        for _ in range(20):
            run = await client.get(f"/api/v1/runs/{run_id}")
            if run.json()["data"]["status"] != "running":
                break
            await asyncio.sleep(0.01)
        assert run.json()["data"]["status"] == "completed"
        assert run.json()["data"]["answer"]["executed_tools"] == ["get_status"]
        events = await client.get(f"/api/v1/runs/{run_id}/events")
        assert events.status_code == 200


@pytest.mark.asyncio
async def test_mutating_tool_requires_approval(tmp_path):
    app = create_app(str(tmp_path / "approval.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/runs", json={"prompt": "请重启服务器", "server_id": "demo"}
        )
        run_id = created.json()["data"]["id"]
        for _ in range(20):
            run = await client.get(f"/api/v1/runs/{run_id}")
            if run.json()["data"]["status"] != "running":
                break
            await asyncio.sleep(0.01)
        assert run.json()["data"]["status"] == "pending_approval"
        approvals = (await client.get("/api/v1/approvals?pending_only=true")).json()["data"]
        assert approvals[0]["tool_name"] == "restart"
        resolved = await client.post(
            f"/api/v1/approvals/{approvals[0]['id']}/resolve", json={"approved": True}
        )
        assert resolved.status_code == 200
        completed = await client.get(f"/api/v1/runs/{run_id}")
        assert completed.json()["data"]["status"] == "completed"


@pytest.mark.asyncio
async def test_rejected_approval_closes_run(tmp_path):
    app = create_app(str(tmp_path / "rejected.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/runs", json={"prompt": "请重启服务器", "server_id": "demo"}
        )
        run_id = created.json()["data"]["id"]
        for _ in range(20):
            run = await client.get(f"/api/v1/runs/{run_id}")
            if run.json()["data"]["status"] != "running":
                break
            await asyncio.sleep(0.01)
        approvals = (await client.get("/api/v1/approvals?pending_only=true")).json()["data"]
        resolved = await client.post(
            f"/api/v1/approvals/{approvals[0]['id']}/resolve", json={"approved": False}
        )
        assert resolved.status_code == 200
        completed = await client.get(f"/api/v1/runs/{run_id}")
        assert completed.json()["data"]["status"] == "failed"


@pytest.mark.asyncio
async def test_unknown_server_uses_error_envelope(tmp_path):
    app = create_app(str(tmp_path / "error.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runs", json={"prompt": "查询状态", "server_id": "missing"}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "server_not_found"


@pytest.mark.asyncio
async def test_unknown_provider_uses_error_envelope(tmp_path):
    app = create_app(str(tmp_path / "unknown-provider-run.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runs",
            json={"prompt": "查询状态", "server_id": "demo", "provider_id": "missing"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "provider_not_found"


@pytest.mark.asyncio
async def test_server_config_registers_bds_adapter(tmp_path):
    app = create_app(str(tmp_path / "servers.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/servers/configs",
            json={
                "id": "bds-test",
                "name": "测试 BDS",
                "adapter": "bds-process",
                "root": str(tmp_path / "bds"),
                "command": ["bedrock_server.exe"],
            },
        )
        assert created.status_code == 201
        servers = (await client.get("/api/v1/servers")).json()["data"]
        assert any(item["id"] == "bds-test" and item["status"] == "offline" for item in servers)
    reloaded = create_app(str(tmp_path / "servers.db"))
    reloaded_transport = httpx.ASGITransport(app=reloaded)
    async with httpx.AsyncClient(transport=reloaded_transport, base_url="http://test") as client:
        configs = (await client.get("/api/v1/servers/configs")).json()["data"]
        assert any(item["id"] == "bds-test" for item in configs)


@pytest.mark.asyncio
async def test_provider_probe_endpoint_supports_custom_provider_without_network(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / "providers.db"))
    transport = httpx.ASGITransport(app=app)
    monkeypatch.delenv("CUSTOM_PROVIDER_KEY", raising=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/providers",
            json={
                "id": "custom-provider",
                "name": "自定义线路",
                "base_url": "https://example.com/v1",
                "model": "fixture-model",
                "api_key_env": "CUSTOM_PROVIDER_KEY",
            },
        )
        assert created.status_code == 201
        probe = await client.get("/api/v1/providers/custom-provider/probe")

    assert probe.status_code == 200
    assert probe.json()["data"]["api_key_configured"] is False
    assert probe.json()["data"]["live"] is False
    cached = app.state.service.get_provider_probe("custom-provider")
    assert cached is not None
    assert cached.live is False
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        updated = await client.patch(
            "/api/v1/providers/custom-provider",
            json={"model": "new-fixture-model"},
        )
        assert updated.status_code == 200
    assert app.state.service.get_provider_probe("custom-provider") is None


@pytest.mark.asyncio
async def test_provider_probe_endpoint_returns_not_found_for_unknown_provider(tmp_path):
    app = create_app(str(tmp_path / "missing-provider.db"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        probe = await client.get("/api/v1/providers/unknown/probe?live=true")

    assert probe.status_code == 404
    assert probe.json()["error"]["code"] == "provider_not_found"


@pytest.mark.asyncio
async def test_backup_records_are_listed_and_persisted(tmp_path):
    database = str(tmp_path / "backups.db")
    app = create_app(database)
    backup = await app.state.service.adapters["demo"].create_backup()
    app.state.service.store.save_backup(backup)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/v1/servers/demo/backups")
        assert listed.status_code == 200
        assert listed.json()["data"][0]["id"] == backup.id
    app.state.service.store.close()
    reloaded = create_app(database)
    assert reloaded.state.service.store.list_backups("demo")[0].id == backup.id


def test_server_config_rejects_path_escape():
    from pydantic import ValidationError

    from backend.app.schemas import ServerConfigCreate

    with pytest.raises(ValidationError, match="log_path_must_be_relative"):
        ServerConfigCreate(
            id="bds-test",
            name="测试 BDS",
            adapter="bds-process",
            root="C:/server",
            command=["bedrock_server.exe"],
            log_path="../outside.log",
        )
