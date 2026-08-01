from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class Risk(StrEnum):
    READ = "read"
    MUTATE = "mutate"
    DESTRUCTIVE = "destructive"


class PolicyMode(StrEnum):
    AUTO = "auto"
    CONFIRM = "confirm"
    DISABLED = "disabled"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PENDING_APPROVAL = "pending_approval"
    FAILED = "failed"


class ProviderProtocol(StrEnum):
    OPENAI_COMPATIBLE_CHAT = "openai-compatible-chat"
    OPENAI_COMPATIBLE_RESPONSES = "openai-compatible-responses"


class AdapterKind(StrEnum):
    DEMO = "demo"
    BDS_PROCESS = "bds-process"
    ENDSTONE_RCON = "endstone-rcon"


class ServerConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=100)
    adapter: AdapterKind
    enabled: bool = True
    root: str | None = Field(default=None, max_length=1000)
    command: list[str] = Field(default_factory=list)
    log_path: str = Field(default="logs/latest.log", min_length=1, max_length=1000)
    world_path: str = Field(default="worlds", min_length=1, max_length=1000)
    rcon_host: str | None = Field(default=None, max_length=255)
    rcon_port: int = Field(default=19132, ge=1, le=65535)
    rcon_password_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    backup_root: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_adapter_fields(self) -> "ServerConfig":
        log_path = Path(self.log_path)
        for field_name, relative_path in (("log_path", log_path), ("world_path", Path(self.world_path))):
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError(f"{field_name}_must_be_relative")
        if self.adapter != AdapterKind.DEMO and (not self.root or not self.command):
            raise ValueError("root_and_command_required_for_process_adapter")
        if self.adapter == AdapterKind.ENDSTONE_RCON and (
            not self.rcon_host or not self.rcon_password_env
        ):
            raise ValueError("rcon_connection_required_for_endstone_adapter")
        return self


class ServerConfigCreate(ServerConfig):
    pass


class ServerConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    adapter: AdapterKind | None = None
    enabled: bool | None = None
    root: str | None = Field(default=None, max_length=1000)
    command: list[str] | None = None
    log_path: str | None = Field(default=None, min_length=1, max_length=1000)
    world_path: str | None = Field(default=None, min_length=1, max_length=1000)
    rcon_host: str | None = Field(default=None, max_length=255)
    rcon_port: int | None = Field(default=None, ge=1, le=65535)
    rcon_password_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    backup_root: str | None = Field(default=None, max_length=1000)


class ProviderProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=100)
    protocol: ProviderProtocol = ProviderProtocol.OPENAI_COMPATIBLE_CHAT
    base_url: HttpUrl
    model: str = Field(min_length=1, max_length=200)
    api_key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    enabled: bool = True
    notes: str | None = Field(default=None, max_length=500)


class ProviderCreate(ProviderProfile):
    pass


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    protocol: ProviderProtocol | None = None
    base_url: HttpUrl | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=500)


class ProviderProbeResult(BaseModel):
    provider_id: str
    base_url: str
    model: str
    protocol: ProviderProtocol
    api_key_configured: bool
    checked_at: datetime
    live: bool = False
    reachable: bool | None = None
    http_status: int | None = None
    model_available: bool | None = None
    capabilities: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class ServerSummary(BaseModel):
    id: str
    name: str
    adapter: str
    status: str
    online_players: int = 0
    max_players: int = 0
    last_backup_at: datetime | None = None
    capabilities: list[str] = Field(default_factory=list)


class LogEntry(BaseModel):
    timestamp: datetime
    level: Literal["debug", "info", "warning", "error"]
    message: str
    source: str = "server"


class BackupRecord(BaseModel):
    id: str
    server_id: str
    created_at: datetime
    size_bytes: int
    sha256: str
    verified: bool = False
    path: str | None = None


class ToolPolicy(BaseModel):
    tool_name: str
    risk: Risk
    mode: PolicyMode
    timeout_seconds: int = Field(default=30, ge=1, le=900)
    allowed_server_ids: list[str] = Field(default_factory=list)


class ToolPolicyUpdate(BaseModel):
    mode: PolicyMode
    timeout_seconds: int | None = Field(default=None, ge=1, le=900)
    allowed_server_ids: list[str] | None = None


class RunCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    server_id: str = "demo"
    provider_id: str | None = None
    mod_project_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")


class RunRecord(BaseModel):
    id: str
    prompt: str
    server_id: str
    provider_id: str | None = None
    mod_project_id: str | None = None
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    answer: "AgentAnswer | None" = None


class Evidence(BaseModel):
    source: str
    excerpt: str
    timestamp: datetime | None = None


class ToolOutcome(BaseModel):
    tool_name: str
    ok: bool
    status: str
    summary: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    error: str | None = None
    audit_id: str | None = None


class AgentAnswer(BaseModel):
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    executed_tools: list[str] = Field(default_factory=list)
    status: RunStatus = RunStatus.COMPLETED


class RunEvent(BaseModel):
    id: int
    run_id: str
    type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ApprovalRecord(BaseModel):
    id: str
    run_id: str
    tool_name: str
    server_id: str
    arguments: dict[str, Any]
    status: Literal["pending", "approved", "rejected", "expired"]
    expires_at: datetime
    created_at: datetime


class ApprovalResolve(BaseModel):
    approved: bool


class AuditEvent(BaseModel):
    id: str
    run_id: str | None = None
    actor: str
    tool_name: str | None = None
    action: str
    status: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ApiError(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class ApiResponse(BaseModel):
    data: Any
    meta: dict[str, Any] = Field(default_factory=dict)
    error: ApiError | None = None


def _mod_now() -> datetime:
    return datetime.now(UTC)


def _normalise_mod_path(value: str) -> str:
    normalised = value.replace("\\", "/").strip()
    path = PurePosixPath(normalised)
    if not normalised or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("mod_path_must_be_relative")
    if "\x00" in normalised:
        raise ValueError("mod_path_contains_null")
    return "/".join(path.parts)


class ModProjectKind(StrEnum):
    UNKNOWN = "unknown"
    FABRIC = "fabric"
    FORGE = "forge"
    NEOFORGE = "neoforge"
    BEDROCK_ADDON = "bedrock-addon"
    GENERIC = "generic"


class ModPatchOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ModPatchStatus(StrEnum):
    PROPOSED = "proposed"
    APPLIED = "applied"
    FAILED = "failed"


class ModBuildStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class ModTestScenarioKind(StrEnum):
    NEW_ITEM = "new_item"
    NEW_BLOCK = "new_block"
    NEW_RECIPE = "new_recipe"
    ENTITY_BEHAVIOR = "entity_behavior"
    PLAYER_INTERACTION = "player_interaction"
    HUD_GUI = "hud_gui"


class ModTestStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class ModEvidenceKind(StrEnum):
    FILE = "file"
    BUILD = "build"
    TEST = "test"
    LOG = "log"
    SCREENSHOT = "screenshot"


class ModProject(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    root: str = Field(min_length=1, max_length=2000)
    kind: ModProjectKind = ModProjectKind.UNKNOWN
    minecraft_version: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    build_command: list[str] = Field(default_factory=list, max_length=32)
    build_timeout_seconds: int = Field(default=900, ge=10, le=3600)
    created_at: datetime = Field(default_factory=_mod_now)
    updated_at: datetime = Field(default_factory=_mod_now)

    @field_validator("build_command")
    @classmethod
    def validate_build_command(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 300 for item in value):
            raise ValueError("invalid_mod_build_command")
        return value


class ModProjectCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    root: str = Field(min_length=1, max_length=2000)
    kind: ModProjectKind = ModProjectKind.UNKNOWN
    minecraft_version: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    build_command: list[str] = Field(default_factory=list, max_length=32)
    build_timeout_seconds: int = Field(default=900, ge=10, le=3600)

    @field_validator("build_command")
    @classmethod
    def validate_build_command(cls, value: list[str]) -> list[str]:
        return ModProject.validate_build_command(value)


class ModProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: ModProjectKind | None = None
    minecraft_version: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None
    build_command: list[str] | None = Field(default=None, max_length=32)
    build_timeout_seconds: int | None = Field(default=None, ge=10, le=3600)

    @field_validator("build_command")
    @classmethod
    def validate_build_command(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return ModProject.validate_build_command(value)


class ModFileInfo(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: str = "text"

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _normalise_mod_path(value)


class ModProjectInspection(BaseModel):
    status: Literal["completed", "failed"] = "completed"
    summary: str
    project: ModProject
    files: list[ModFileInfo] = Field(default_factory=list)
    detected_features: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


class ModFileRead(BaseModel):
    status: Literal["completed"] = "completed"
    project_id: str
    path: str
    content: str
    sha256: str
    size_bytes: int
    truncated: bool = False
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


class ModPatchChange(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    operation: ModPatchOperation
    content: str | None = Field(default=None, max_length=1_000_000)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    summary: str | None = Field(default=None, max_length=500)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _normalise_mod_path(value)

    @model_validator(mode="after")
    def validate_content(self) -> "ModPatchChange":
        if self.operation in {ModPatchOperation.CREATE, ModPatchOperation.UPDATE} and self.content is None:
            raise ValueError("mod_patch_content_required")
        if self.operation == ModPatchOperation.DELETE and self.content is not None:
            raise ValueError("mod_patch_delete_content_forbidden")
        if self.content is not None and "\x00" in self.content:
            raise ValueError("mod_patch_binary_content_forbidden")
        return self


class ModPatchCreate(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    title: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=1000)
    changes: list[ModPatchChange] = Field(min_length=1, max_length=50)


class ModPatch(BaseModel):
    id: str
    project_id: str
    title: str
    rationale: str
    changes: list[ModPatchChange]
    status: ModPatchStatus = ModPatchStatus.PROPOSED
    created_at: datetime = Field(default_factory=_mod_now)
    applied_at: datetime | None = None
    error: str | None = None


class ModBuildRequest(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    clean: bool = False


class ModBuildRecord(BaseModel):
    id: str
    project_id: str
    status: ModBuildStatus
    command: list[str] = Field(default_factory=list)
    output: str = ""
    exit_code: int | None = None
    started_at: datetime = Field(default_factory=_mod_now)
    finished_at: datetime | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    error: str | None = None


def _scenario_templates() -> dict[ModTestScenarioKind, tuple[list[str], list[str]]]:
    return {
        ModTestScenarioKind.NEW_ITEM: (
            ["加载客户端并进入测试世界", "获取新物品并放入快捷栏", "丢弃并重新拾取物品"],
            ["物品成功注册", "名称、图标和堆叠规则符合预期", "日志无崩溃或资源缺失"],
        ),
        ModTestScenarioKind.NEW_BLOCK: (
            ["加载客户端并进入测试世界", "放置新方块", "破坏并观察掉落物"],
            ["方块可放置且碰撞体正常", "破坏后掉落配置正确", "日志无崩溃或资源缺失"],
        ),
        ModTestScenarioKind.NEW_RECIPE: (
            ["打开工作台或配方界面", "放入配方所需材料", "执行合成并取出产物"],
            ["配方可被发现", "材料与产物数量正确", "重复合成不会报错"],
        ),
        ModTestScenarioKind.ENTITY_BEHAVIOR: (
            ["生成目标实体", "触发目标行为", "观察实体状态和日志"],
            ["实体成功生成", "行为在触发条件下发生", "没有异常崩溃或无限循环"],
        ),
        ModTestScenarioKind.PLAYER_INTERACTION: (
            ["以普通玩家身份进入测试世界", "与目标方块、物品或实体交互", "重复交互并重连"],
            ["权限边界符合预期", "交互反馈稳定", "重连后状态没有异常丢失"],
        ),
        ModTestScenarioKind.HUD_GUI: (
            ["进入测试世界并打开目标界面", "点击主要控件并切换页面", "关闭后重新打开界面"],
            ["界面在目标分辨率可见", "控件点击和文本渲染正常", "关闭、重开不会导致客户端错误"],
        ),
    }


class ModTestScenarioCreate(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    kind: ModTestScenarioKind
    title: str | None = Field(default=None, max_length=160)
    steps: list[str] = Field(default_factory=list, max_length=30)
    assertions: list[str] = Field(default_factory=list, max_length=30)


class ModTestScenario(BaseModel):
    id: str
    project_id: str
    kind: ModTestScenarioKind
    title: str
    steps: list[str]
    assertions: list[str]
    status: ModTestStatus = ModTestStatus.DRAFT
    created_at: datetime = Field(default_factory=_mod_now)
    updated_at: datetime = Field(default_factory=_mod_now)
    evidence_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class ModEvidence(BaseModel):
    id: str
    project_id: str
    scenario_id: str | None = None
    kind: ModEvidenceKind
    title: str
    excerpt: str = Field(max_length=20_000)
    artifact_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_mod_now)


class ModActionResult(BaseModel):
    status: Literal["completed", "failed", "blocked", "pending_approval"]
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    run_id: str | None = None


class ModTaskPlanCreate(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    request: str = Field(min_length=1, max_length=4000)


class ModTaskPlan(BaseModel):
    id: str
    project_id: str
    request: str
    objective: str
    assumptions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    scenario_kind: ModTestScenarioKind | None = None
    status: Literal["draft", "completed"] = "completed"
    created_at: datetime = Field(default_factory=_mod_now)
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
