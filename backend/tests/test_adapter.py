import asyncio
import struct
import zipfile

import pytest

from backend.app.adapters import BdsProcessAdapter, DemoAdapter, EndstoneRconAdapter


@pytest.mark.asyncio
async def test_demo_adapter_status_and_backup():
    adapter = DemoAdapter()
    status = await adapter.get_status()
    assert status.status == "online"
    backup = await adapter.create_backup()
    assert backup.verified is True
    verified = await adapter.verify_backup(backup.id)
    assert verified.sha256 == backup.sha256


@pytest.mark.asyncio
async def test_bds_file_backup_verify_and_restore(tmp_path):
    root = tmp_path / "bds"
    world = root / "worlds"
    world.mkdir(parents=True)
    (world / "level.dat").write_bytes(b"before")
    adapter = BdsProcessAdapter("bds-test", "测试 BDS", root, ["bedrock_server.exe"])

    backup = await adapter.create_backup()
    assert backup.verified is True
    (world / "level.dat").write_bytes(b"changed")
    await adapter.restore_backup(backup.id)
    assert (world / "level.dat").read_bytes() == b"before"


@pytest.mark.asyncio
async def test_bds_backup_rejects_missing_world(tmp_path):
    adapter = BdsProcessAdapter("bds-test", "测试 BDS", tmp_path / "bds", ["bedrock_server.exe"])
    with pytest.raises(ValueError, match="world_path_not_found"):
        await adapter.create_backup()


@pytest.mark.asyncio
async def test_bds_restore_rejects_zip_path_traversal(tmp_path):
    root = tmp_path / "bds"
    (root / "worlds").mkdir(parents=True)
    adapter = BdsProcessAdapter("bds-test", "测试 BDS", root, ["bedrock_server.exe"])
    adapter.backup_root.mkdir(parents=True)
    malicious = adapter.backup_root / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("worlds/../../outside.txt", "unsafe")
    with pytest.raises(ValueError, match="backup_path_traversal"):
        await adapter.restore_backup("malicious")


@pytest.mark.asyncio
async def test_endstone_rcon_player_query_uses_fixed_list_command(monkeypatch, tmp_path):
    observed_commands: list[str] = []

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        async def read_packet() -> tuple[int, int, str]:
            size = struct.unpack("<i", await reader.readexactly(4))[0]
            payload = await reader.readexactly(size)
            request_id, packet_type = struct.unpack("<ii", payload[:8])
            return request_id, packet_type, payload[8:-2].decode()

        async def write_packet(request_id: int, packet_type: int, body: str):
            payload = struct.pack("<ii", request_id, packet_type) + body.encode() + b"\x00\x00"
            writer.write(struct.pack("<i", len(payload)) + payload)
            await writer.drain()

        request_id, _, _ = await read_packet()
        await write_packet(request_id, 2, "")
        request_id, _, command = await read_packet()
        observed_commands.append(command)
        await write_packet(request_id, 0, "There are 2 of a max of 20 players online: Alex, Steve")
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setenv("TEST_RCON_PASSWORD", "fixture-password")
    adapter = EndstoneRconAdapter(
        "endstone-test",
        "测试 Endstone",
        tmp_path,
        ["bedrock_server.exe"],
        "logs/latest.log",
        "worlds",
        None,
        "127.0.0.1",
        port,
        "TEST_RCON_PASSWORD",
    )
    try:
        assert await adapter.get_players() == ["Alex", "Steve"]
        assert observed_commands == ["list"]
    finally:
        server.close()
        await server.wait_closed()
