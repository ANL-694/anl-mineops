import asyncio
import hashlib
import os
import re
import secrets
import shutil
import struct
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .schemas import BackupRecord, LogEntry, ServerSummary


def utcnow() -> datetime:
    return datetime.now(UTC)


class ServerAdapter(Protocol):
    server_id: str

    async def get_status(self) -> ServerSummary: ...

    async def get_logs(self, limit: int = 100) -> list[LogEntry]: ...

    async def get_players(self) -> list[str]: ...

    async def start(self) -> ServerSummary: ...

    async def stop(self) -> ServerSummary: ...

    async def restart(self) -> ServerSummary: ...

    async def create_backup(self) -> BackupRecord: ...

    async def verify_backup(self, backup_id: str) -> BackupRecord: ...

    async def restore_backup(self, backup_id: str) -> ServerSummary: ...


class DemoAdapter:
    def __init__(self, server_id: str = "demo") -> None:
        self.server_id = server_id
        self.running = True
        self.players = ["Alex", "Steve"]
        self.logs = [
            LogEntry(
                timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                level="info",
                message="Endstone server started successfully",
                source="demo",
            ),
            LogEntry(
                timestamp=datetime(2026, 8, 1, 12, 4, tzinfo=UTC),
                level="warning",
                message="simulation backlog reached 12 ticks",
                source="demo",
            ),
            LogEntry(
                timestamp=datetime(2026, 8, 1, 12, 5, tzinfo=UTC),
                level="error",
                message="example diagnostic: chunk save queue is delayed",
                source="demo",
            ),
        ]
        self.backups: dict[str, BackupRecord] = {}

    def _summary(self) -> ServerSummary:
        return ServerSummary(
            id=self.server_id,
            name="演示 Endstone 服务器",
            adapter="demo",
            status="online" if self.running else "offline",
            online_players=len(self.players) if self.running else 0,
            max_players=20,
            last_backup_at=max((item.created_at for item in self.backups.values()), default=None),
            capabilities=[
                "status",
                "logs",
                "players",
                "start",
                "stop",
                "restart",
                "backup",
                "verify_backup",
                "restore_backup",
            ],
        )

    async def get_status(self) -> ServerSummary:
        return self._summary()

    async def get_logs(self, limit: int = 100) -> list[LogEntry]:
        return self.logs[-max(1, min(limit, 500)) :]

    async def get_players(self) -> list[str]:
        return list(self.players) if self.running else []

    async def start(self) -> ServerSummary:
        self.running = True
        return self._summary()

    async def stop(self) -> ServerSummary:
        self.running = False
        return self._summary()

    async def restart(self) -> ServerSummary:
        self.running = False
        await asyncio.sleep(0)
        self.running = True
        return self._summary()

    async def create_backup(self) -> BackupRecord:
        payload = f"demo-world:{self.server_id}:{utcnow().isoformat()}".encode()
        backup_id = secrets.token_urlsafe(10)
        record = BackupRecord(
            id=backup_id,
            server_id=self.server_id,
            created_at=utcnow(),
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            verified=True,
            path=f"demo://backups/{backup_id}",
        )
        self.backups[backup_id] = record
        return record

    async def verify_backup(self, backup_id: str) -> BackupRecord:
        if backup_id not in self.backups:
            raise ValueError("backup_not_found")
        record = self.backups[backup_id].model_copy(update={"verified": True})
        self.backups[backup_id] = record
        return record

    async def restore_backup(self, backup_id: str) -> ServerSummary:
        if backup_id not in self.backups:
            raise ValueError("backup_not_found")
        self.running = True
        return self._summary()


class BdsProcessAdapter:
    """Local BDS process adapter skeleton with safe, typed lifecycle operations."""

    def __init__(
        self,
        server_id: str,
        name: str,
        root: Path,
        command: list[str],
        log_path: str = "logs/latest.log",
        world_path: str = "worlds",
        backup_root: Path | None = None,
    ) -> None:
        self.server_id = server_id
        self.name = name
        self.root = root.resolve()
        self.command = list(command)
        self.log_path = log_path
        self.world_root = self.root / world_path
        self.backup_root = (backup_root or self.root / "backups").resolve()
        self.process: asyncio.subprocess.Process | None = None
        self.backups: dict[str, BackupRecord] = {}

    async def get_status(self) -> ServerSummary:
        running = self.process is not None and self.process.returncode is None
        return ServerSummary(
            id=self.server_id,
            name=self.name,
            adapter="bds-process",
            status="online" if running else "offline",
            capabilities=[
                "status",
                "logs",
                "start",
                "stop",
                "restart",
                "backup",
                "verify_backup",
                "restore_backup",
            ],
        )

    async def get_logs(self, limit: int = 100) -> list[LogEntry]:
        log_path = self.root / self.log_path
        if not log_path.is_file():
            return []
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        return [
            LogEntry(timestamp=utcnow(), level=_level_from_line(line), message=line)
            for line in lines
        ]

    async def get_players(self) -> list[str]:
        return []

    async def start(self) -> ServerSummary:
        if self.process is None or self.process.returncode is not None:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=self.root,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        return await self.get_status()

    async def stop(self) -> ServerSummary:
        if self.process and self.process.returncode is None:
            if self.process.stdin:
                self.process.stdin.write(b"stop\n")
                await self.process.stdin.drain()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=20)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        return await self.get_status()

    async def restart(self) -> ServerSummary:
        await self.stop()
        return await self.start()

    async def create_backup(self) -> BackupRecord:
        if not self.world_root.is_dir():
            raise ValueError("world_path_not_found")
        self.backup_root.mkdir(parents=True, exist_ok=True)
        files = [path for path in self.world_root.rglob("*") if path.is_file()]
        total_size = sum(path.stat().st_size for path in files)
        if shutil.disk_usage(self.backup_root).free < max(total_size * 2, 1024 * 1024):
            raise ValueError("insufficient_backup_space")

        was_running = self.process is not None and self.process.returncode is None
        if was_running:
            await self.stop()
        backup_id = secrets.token_urlsafe(10)
        final_path = self.backup_root / f"{backup_id}.zip"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.backup_root, prefix=f".{backup_id}.", suffix=".tmp", delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
            with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    archive.write(path, Path(self.world_root.name) / path.relative_to(self.world_root))
            os.replace(temporary_path, final_path)
            temporary_path = None
            record = await self.verify_backup(backup_id)
            self.backups[backup_id] = record
            return record
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()
            if was_running:
                await self.start()

    async def verify_backup(self, backup_id: str) -> BackupRecord:
        backup_path = self.backup_root / f"{backup_id}.zip"
        if not backup_path.is_file():
            raise ValueError("backup_not_found")
        digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
        record = BackupRecord(
            id=backup_id,
            server_id=self.server_id,
            created_at=datetime.fromtimestamp(backup_path.stat().st_mtime, UTC),
            size_bytes=backup_path.stat().st_size,
            sha256=digest,
            verified=True,
            path=str(backup_path),
        )
        self.backups[backup_id] = record
        return record

    async def restore_backup(self, backup_id: str) -> ServerSummary:
        backup_path = self.backup_root / f"{backup_id}.zip"
        if not backup_path.is_file():
            raise ValueError("backup_not_found")
        was_running = self.process is not None and self.process.returncode is None
        if was_running:
            await self.stop()
        temporary_root: Path | None = None
        try:
            temporary_root = Path(tempfile.mkdtemp(prefix=f"restore-{backup_id}-", dir=self.root))
            with zipfile.ZipFile(backup_path) as archive:
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise ValueError("backup_path_traversal")
                archive.extractall(temporary_root)
            extracted_world = temporary_root / self.world_root.name
            if not extracted_world.is_dir():
                raise ValueError("backup_world_missing")
            if self.world_root.exists():
                shutil.rmtree(self.world_root)
            shutil.move(str(extracted_world), str(self.world_root))
            return await self.get_status()
        finally:
            if temporary_root and temporary_root.exists():
                shutil.rmtree(temporary_root, ignore_errors=True)
            if was_running:
                await self.start()


class EndstoneRconAdapter(BdsProcessAdapter):
    """Process adapter extension point for an Endstone RCON bridge."""

    def __init__(
        self,
        server_id: str,
        name: str,
        root: Path,
        command: list[str],
        log_path: str,
        world_path: str,
        backup_root: Path | None,
        rcon_host: str,
        rcon_port: int,
        rcon_password_env: str,
    ) -> None:
        super().__init__(server_id, name, root, command, log_path, world_path, backup_root)
        self.rcon_host = rcon_host
        self.rcon_port = rcon_port
        self.rcon_password_env = rcon_password_env

    async def get_players(self) -> list[str]:
        password = os.getenv(self.rcon_password_env)
        if not password:
            raise ValueError(f"missing_rcon_password_env:{self.rcon_password_env}")
        output = await _rcon_command(
            self.rcon_host,
            self.rcon_port,
            password,
            "list",
        )
        match = re.search(r"online:\s*(.*)$", output, flags=re.IGNORECASE)
        if not match or not match.group(1).strip():
            return []
        return [name.strip() for name in match.group(1).split(",") if name.strip()]


async def _rcon_command(host: str, port: int, password: str, command: str) -> str:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5)
    try:
        await _write_rcon_packet(writer, 1, 3, password)
        auth_id, _, _ = await _read_rcon_packet(reader)
        if auth_id == -1:
            raise ValueError("rcon_auth_failed")
        await _write_rcon_packet(writer, 2, 2, command)
        _, _, body = await _read_rcon_packet(reader)
        return body
    finally:
        writer.close()
        await writer.wait_closed()


async def _write_rcon_packet(
    writer: asyncio.StreamWriter, request_id: int, packet_type: int, body: str
) -> None:
    payload = struct.pack("<ii", request_id, packet_type) + body.encode("utf-8") + b"\x00\x00"
    writer.write(struct.pack("<i", len(payload)) + payload)
    await writer.drain()


async def _read_rcon_packet(
    reader: asyncio.StreamReader,
) -> tuple[int, int, str]:
    size_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=5)
    size = struct.unpack("<i", size_bytes)[0]
    if size < 10 or size > 4 * 1024 * 1024:
        raise ValueError("invalid_rcon_packet_size")
    payload = await asyncio.wait_for(reader.readexactly(size), timeout=5)
    request_id, packet_type = struct.unpack("<ii", payload[:8])
    return request_id, packet_type, payload[8:-2].decode("utf-8", errors="replace")


def _level_from_line(line: str) -> str:
    lowered = line.lower()
    if "error" in lowered or "fatal" in lowered or "crash" in lowered:
        return "error"
    if "warn" in lowered:
        return "warning"
    if "debug" in lowered:
        return "debug"
    return "info"
