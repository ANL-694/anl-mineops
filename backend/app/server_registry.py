from pathlib import Path

from .adapters import BdsProcessAdapter, DemoAdapter, EndstoneRconAdapter, ServerAdapter
from .schemas import AdapterKind, ServerConfig


def build_adapter(config: ServerConfig) -> ServerAdapter:
    if config.adapter == AdapterKind.DEMO:
        return DemoAdapter(config.id)

    root = Path(config.root or "").expanduser().resolve()
    if config.adapter == AdapterKind.BDS_PROCESS:
        return BdsProcessAdapter(
            server_id=config.id,
            name=config.name,
            root=root,
            command=config.command,
            log_path=config.log_path,
            world_path=config.world_path,
            backup_root=Path(config.backup_root).expanduser() if config.backup_root else None,
        )
    if config.adapter == AdapterKind.ENDSTONE_RCON:
        return EndstoneRconAdapter(
            server_id=config.id,
            name=config.name,
            root=root,
            command=config.command,
            log_path=config.log_path,
            world_path=config.world_path,
            backup_root=Path(config.backup_root).expanduser() if config.backup_root else None,
            rcon_host=config.rcon_host or "",
            rcon_port=config.rcon_port,
            rcon_password_env=config.rcon_password_env or "",
        )
    raise ValueError(f"unsupported_adapter:{config.adapter}")
