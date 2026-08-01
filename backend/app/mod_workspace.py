import asyncio
import hashlib
import json
import os
import re
import secrets
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .schemas import (
    ModActionResult,
    ModBuildRecord,
    ModBuildStatus,
    ModEvidence,
    ModEvidenceKind,
    ModFileInfo,
    ModFileRead,
    ModPatch,
    ModPatchChange,
    ModPatchCreate,
    ModPatchOperation,
    ModPatchStatus,
    ModProject,
    ModProjectCreate,
    ModProjectInspection,
    ModProjectKind,
    ModProjectUpdate,
    ModTaskPlan,
    ModTaskPlanCreate,
    ModTestScenario,
    ModTestScenarioCreate,
    ModTestScenarioKind,
    ModTestStatus,
    _scenario_templates,
)
from .storage import Store, utcnow


class ModWorkspaceError(ValueError):
    pass


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_READ_BYTES = 512 * 1024
IGNORED_DIRECTORIES = {".git", ".gradle", "build", "node_modules", "__pycache__", ".idea"}
SENSITIVE_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SAFE_BUILD_EXECUTABLES = {
    "gradle",
    "gradlew",
    "gradlew.bat",
    "mvn",
    "mvnw",
    "mvnw.cmd",
    "npm",
    "npm.cmd",
    "pnpm",
    "pnpm.cmd",
    "yarn",
    "yarn.cmd",
    "python",
    "python.exe",
    "py",
    "dotnet",
    "cargo",
}
SHELL_TOKENS = {";", "&&", "||", "|", ">", ">>", "<"}
UNSAFE_BUILD_FLAGS = {"-c", "-command", "-encodedcommand", "/c", "/command"}


class DemoModTestAdapter:
    _signal_words = {
        ModTestScenarioKind.NEW_ITEM: ("item", "sword", "物品"),
        ModTestScenarioKind.NEW_BLOCK: ("block", "方块"),
        ModTestScenarioKind.NEW_RECIPE: ("recipe", "配方"),
        ModTestScenarioKind.ENTITY_BEHAVIOR: ("entity", "mob", "生物"),
        ModTestScenarioKind.PLAYER_INTERACTION: ("interaction", "event", "交互"),
        ModTestScenarioKind.HUD_GUI: ("hud", "gui", "screen", "界面"),
    }

    async def run(self, scenario: ModTestScenario, inspection: ModProjectInspection) -> tuple[bool, list[str], str]:
        await asyncio.sleep(0)
        words = self._signal_words[scenario.kind]
        matching = [item.path for item in inspection.files if any(word in item.path.lower() for word in words)]
        passed = bool(inspection.files) and (bool(matching) or scenario.project_id == "demo-mod")
        summary = (
            f"Demo 测试通过：{scenario.title}（未启动真实 Minecraft 客户端）。"
            if passed
            else f"Demo 测试未通过：没有找到与 {scenario.kind.value} 相关的文件信号。"
        )
        return passed, matching, summary


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _redact_output(value: str) -> str:
    value = re.sub(r"(?i)(api[_-]?key|token|password)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]", value)
    value = re.sub(r"\b(?:sk|key)-[A-Za-z0-9_-]{16,}\b", "[REDACTED]", value)
    return value[-12_000:]


def _language_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".java": "java",
        ".kt": "kotlin",
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".mcfunction": "mcfunction",
        ".mcmeta": "json",
        ".xml": "xml",
        ".properties": "properties",
    }.get(suffix, "text")


def _scenario_kind_from_request(request: str) -> ModTestScenarioKind | None:
    if any(word in request for word in ("物品", "item", "sword")):
        return ModTestScenarioKind.NEW_ITEM
    if any(word in request for word in ("方块", "block")):
        return ModTestScenarioKind.NEW_BLOCK
    if any(word in request for word in ("配方", "recipe", "合成")):
        return ModTestScenarioKind.NEW_RECIPE
    if any(word in request for word in ("实体", "生物", "entity", "mob")):
        return ModTestScenarioKind.ENTITY_BEHAVIOR
    if any(word in request for word in ("交互", "interaction")):
        return ModTestScenarioKind.PLAYER_INTERACTION
    if any(word in request for word in ("界面", "hud", "gui", "菜单")):
        return ModTestScenarioKind.HUD_GUI
    return None


class ModWorkspaceService:
    def __init__(self, store: Store, *, demo_root: Path | None = None) -> None:
        self.store = store
        self.demo_root = (demo_root or Path(__file__).resolve().parents[2] / "fixtures" / "mod-demo").resolve()
        self.test_adapter = DemoModTestAdapter()
        self.ensure_demo_project()

    def ensure_demo_project(self) -> ModProject:
        existing = self.store.get_mod_project("demo-mod")
        if existing:
            existing_root = Path(existing.root).expanduser()
            if (
                existing_root.name.lower() == "demo"
                and "mod-fixtures" in {part.lower() for part in existing_root.parts}
                and existing_root.resolve() != self.demo_root
            ):
                existing = existing.model_copy(update={"root": str(self.demo_root), "updated_at": utcnow()})
                self.store.save_mod_project(existing)
            return existing
        if not self.demo_root.is_dir():
            self.demo_root.mkdir(parents=True, exist_ok=True)
        project = ModProject(
            id="demo-mod",
            name="演示模组项目",
            root=str(self.demo_root),
            kind=ModProjectKind.FABRIC,
            minecraft_version="1.21.1",
            description="用于学习 ModCrafting 式分析、补丁和测试流程的安全 fixture。",
        )
        self.store.save_mod_project(project)
        return project

    def list_projects(self) -> list[ModProject]:
        return self.store.list_mod_projects()

    def get_project(self, project_id: str) -> ModProject:
        project = self.store.get_mod_project(project_id)
        if not project:
            raise ModWorkspaceError("mod_project_not_found")
        return project

    def create_project(self, payload: ModProjectCreate) -> ModProject:
        if self.store.get_mod_project(payload.id):
            raise ModWorkspaceError("mod_project_exists")
        root = self._validate_root(Path(payload.root))
        data = payload.model_dump()
        data["root"] = str(root)
        project = ModProject(
            **data,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.store.save_mod_project(project)
        return project

    def update_project(self, project_id: str, payload: ModProjectUpdate) -> ModProject:
        current = self.get_project(project_id)
        data = current.model_dump()
        data.update(payload.model_dump(exclude_unset=True))
        if "build_command" in data and data["build_command"] is None:
            data["build_command"] = []
        data["updated_at"] = utcnow()
        project = ModProject.model_validate(data)
        self._validate_root(Path(project.root))
        self.store.save_mod_project(project)
        return project

    def inspect_project(self, project_id: str) -> ModProjectInspection:
        project = self.get_project(project_id)
        root = self._validate_root(Path(project.root))
        files = self._scan_files(root)
        names = {item.path.lower() for item in files}
        detected = self._detect_features(root, names)
        warnings: list[str] = []
        if not files:
            warnings.append("project_has_no_readable_files")
        if not project.build_command:
            warnings.append("build_command_not_configured")
        if project.kind == ModProjectKind.UNKNOWN:
            warnings.append("project_loader_not_declared")
        return ModProjectInspection(
            summary=f"已分析项目 {project.name}，发现 {len(files)} 个可读文件。",
            project=project,
            files=files,
            detected_features=detected,
            warnings=warnings,
            next_actions=[
                "先读取与需求相关的源文件，再提出最小补丁。",
                "构建前确认 build_command 是服主显式配置的白名单命令。",
            ],
        )

    def plan_task(self, payload: ModTaskPlanCreate) -> ModTaskPlan:
        project = self.get_project(payload.project_id)
        lowered = payload.request.lower()
        scenario_kind = _scenario_kind_from_request(lowered)
        steps = [
            "分析项目元数据、loader 和文件清单",
            "读取与需求相关的源文件和资源文件",
            "提出最小补丁并校验 expected_sha256",
            "等待策略审批后应用补丁",
            "等待策略审批后执行显式构建命令",
            "生成测试场景并记录结构化证据",
        ]
        if any(word in lowered for word in ("只分析", "仅查看", "inspect only")):
            steps = steps[:2]
        plan = ModTaskPlan(
            id=f"mtp-{secrets.token_urlsafe(10)}",
            project_id=project.id,
            request=payload.request,
            objective=f"为 {project.name} 处理：{payload.request.strip()}",
            assumptions=[
                "项目根目录由用户显式配置，Agent 不会猜测或切换到其他目录。",
                "真实客户端测试、截图和 Bridge 不属于当前 Demo 验证范围。",
            ],
            steps=steps,
            scenario_kind=scenario_kind,
            status="completed",
            created_at=utcnow(),
            next_actions=[
                "先执行项目分析，再读取与需求直接相关的文件。",
                "任何文件写入和构建都必须经过工具策略与审批。",
            ],
        )
        self.store.save_mod_plan(plan)
        return plan

    def get_plan(self, plan_id: str) -> ModTaskPlan:
        plan = self.store.get_mod_plan(plan_id)
        if not plan:
            raise ModWorkspaceError("mod_plan_not_found")
        return plan

    def list_plans(self, project_id: str) -> list[ModTaskPlan]:
        self.get_project(project_id)
        return self.store.list_mod_plans(project_id)

    def list_files(self, project_id: str, prefix: str = "") -> list[ModFileInfo]:
        inspection = self.inspect_project(project_id)
        if not prefix:
            return inspection.files
        normalised = prefix.replace("\\", "/").strip("/")
        return [item for item in inspection.files if item.path.startswith(normalised)]

    def read_file(self, project_id: str, relative_path: str) -> ModFileRead:
        project = self.get_project(project_id)
        path = self._safe_path(project, relative_path, require_file=True)
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            raise ModWorkspaceError("mod_file_too_large_to_read")
        payload = path.read_bytes()
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ModWorkspaceError("mod_file_not_utf8_text") from exc
        return ModFileRead(
            project_id=project_id,
            path=self._relative(path, Path(project.root)),
            content=content,
            sha256=_sha256_bytes(payload),
            size_bytes=size,
            next_actions=["如果需要修改，请先提交带 expected_sha256 的补丁草稿。"],
        )

    def propose_patch(self, payload: ModPatchCreate) -> ModPatch:
        project = self.get_project(payload.project_id)
        seen: set[str] = set()
        changes: list[ModPatchChange] = []
        for change in payload.changes:
            if change.path in seen:
                raise ModWorkspaceError("duplicate_mod_patch_path")
            seen.add(change.path)
            target = self._safe_path(project, change.path, require_file=False, allow_missing=True)
            if target.exists() and target.is_dir():
                raise ModWorkspaceError("mod_patch_target_is_directory")
            exists = target.is_file()
            if change.operation == ModPatchOperation.CREATE and exists:
                raise ModWorkspaceError("mod_patch_create_target_exists")
            if change.operation in {ModPatchOperation.UPDATE, ModPatchOperation.DELETE} and not exists:
                raise ModWorkspaceError("mod_patch_target_not_found")
            expected = change.expected_sha256
            if exists and expected is None:
                expected = _sha256_bytes(target.read_bytes())
            changes.append(change.model_copy(update={"expected_sha256": expected}))
        patch = ModPatch(
            id=f"mp-{secrets.token_urlsafe(10)}",
            project_id=project.id,
            title=payload.title,
            rationale=payload.rationale,
            changes=changes,
            status=ModPatchStatus.PROPOSED,
            created_at=utcnow(),
        )
        self.store.save_mod_patch(patch)
        return patch

    def get_patch(self, patch_id: str) -> ModPatch:
        patch = self.store.get_mod_patch(patch_id)
        if not patch:
            raise ModWorkspaceError("mod_patch_not_found")
        return patch

    def list_patches(self, project_id: str) -> list[ModPatch]:
        self.get_project(project_id)
        return self.store.list_mod_patches(project_id)

    def apply_patch(self, patch_id: str) -> ModActionResult:
        patch = self.get_patch(patch_id)
        if patch.status != ModPatchStatus.PROPOSED:
            raise ModWorkspaceError("mod_patch_already_resolved")
        project = self.get_project(patch.project_id)
        targets: list[tuple[ModPatchChange, Path, bytes | None]] = []
        for change in patch.changes:
            target = self._safe_path(project, change.path, require_file=False, allow_missing=True)
            current = target.read_bytes() if target.is_file() else None
            if change.operation == ModPatchOperation.CREATE and current is not None:
                return self._fail_patch(patch, "mod_patch_create_target_exists")
            if change.operation in {ModPatchOperation.UPDATE, ModPatchOperation.DELETE} and current is None:
                return self._fail_patch(patch, "mod_patch_target_not_found")
            if change.expected_sha256 and current is not None and _sha256_bytes(current) != change.expected_sha256:
                return self._fail_patch(patch, "mod_patch_stale_expected_sha256")
            targets.append((change, target, current))

        originals: dict[Path, bytes | None] = {target: current for _, target, current in targets}
        try:
            for change, target, _ in targets:
                if change.operation == ModPatchOperation.DELETE:
                    target.unlink()
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=f".{target.name}.", suffix=".mineops.tmp", delete=False
                )
                temporary_path = Path(temporary.name)
                try:
                    temporary.write((change.content or "").encode("utf-8"))
                    temporary.flush()
                finally:
                    temporary.close()
                os.replace(temporary_path, target)
            applied = patch.model_copy(update={"status": ModPatchStatus.APPLIED, "applied_at": utcnow(), "error": None})
            self.store.save_mod_patch(applied)
        except Exception as exc:
            for target, original in originals.items():
                try:
                    if original is None:
                        if target.exists():
                            target.unlink()
                    else:
                        target.write_bytes(original)
                except OSError:
                    pass
            failed = patch.model_copy(update={"status": ModPatchStatus.FAILED, "error": str(exc)})
            self.store.save_mod_patch(failed)
            raise ModWorkspaceError(f"mod_patch_apply_failed:{exc}") from exc

        evidence = ModEvidence(
            id=f"me-{secrets.token_urlsafe(10)}",
            project_id=project.id,
            kind=ModEvidenceKind.FILE,
            title=f"补丁已应用：{patch.title}",
            excerpt=json.dumps(
                {"patch_id": patch.id, "files": [change.path for change in patch.changes]},
                ensure_ascii=False,
            ),
            metadata={"patch_id": patch.id, "operations": len(patch.changes)},
        )
        self.store.save_mod_evidence(evidence)
        return ModActionResult(
            status="completed",
            summary=f"补丁已安全应用到项目 {project.name}。",
            data={"patch": applied.model_dump(mode="json")},
            next_actions=["运行受控构建，再创建对应的游戏测试场景。"],
            artifacts=[evidence.id],
        )

    def create_scenario(self, payload: ModTestScenarioCreate) -> ModTestScenario:
        project = self.get_project(payload.project_id)
        templates = _scenario_templates()[payload.kind]
        scenario = ModTestScenario(
            id=f"mts-{secrets.token_urlsafe(10)}",
            project_id=project.id,
            kind=payload.kind,
            title=payload.title or self._scenario_title(payload.kind),
            steps=payload.steps or templates[0],
            assertions=payload.assertions or templates[1],
            status=ModTestStatus.DRAFT,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.store.save_mod_scenario(scenario)
        return scenario

    def get_scenario(self, scenario_id: str) -> ModTestScenario:
        scenario = self.store.get_mod_scenario(scenario_id)
        if not scenario:
            raise ModWorkspaceError("mod_scenario_not_found")
        return scenario

    def list_scenarios(self, project_id: str) -> list[ModTestScenario]:
        self.get_project(project_id)
        return self.store.list_mod_scenarios(project_id)

    def list_evidence(self, project_id: str) -> list[ModEvidence]:
        self.get_project(project_id)
        return self.store.list_mod_evidence(project_id)

    async def run_demo_test(self, scenario_id: str) -> ModActionResult:
        scenario = self.get_scenario(scenario_id)
        project = self.get_project(scenario.project_id)
        running = scenario.model_copy(update={"status": ModTestStatus.RUNNING, "updated_at": utcnow(), "error": None})
        self.store.save_mod_scenario(running)
        inspection = self.inspect_project(project.id)
        passed, matching, summary = await self.test_adapter.run(scenario, inspection)
        status = ModTestStatus.PASSED if passed else ModTestStatus.FAILED
        evidence = ModEvidence(
            id=f"me-{secrets.token_urlsafe(10)}",
            project_id=project.id,
            scenario_id=scenario.id,
            kind=ModEvidenceKind.TEST,
            title=scenario.title,
            excerpt=summary,
            metadata={"matched_files": matching, "fixture": True, "client_started": False},
        )
        self.store.save_mod_evidence(evidence)
        finished = running.model_copy(
            update={
                "status": status,
                "updated_at": utcnow(),
                "evidence_ids": [*running.evidence_ids, evidence.id],
                "error": None if passed else "scenario_signal_not_found",
            }
        )
        self.store.save_mod_scenario(finished)
        return ModActionResult(
            status="completed" if passed else "failed",
            summary=summary,
            data={"scenario": finished.model_dump(mode="json"), "matched_files": matching},
            next_actions=(
                ["如需真实验证，请配置未来的 Minecraft Bridge 适配器。"]
                if passed
                else ["读取相关源码和资源文件后提出补丁，再重新运行场景。"]
            ),
            artifacts=[evidence.id],
        )

    async def build_project(self, project_id: str, *, clean: bool = False) -> ModBuildRecord:
        project = self.get_project(project_id)
        root = self._validate_root(Path(project.root))
        build = ModBuildRecord(
            id=f"mb-{secrets.token_urlsafe(10)}",
            project_id=project.id,
            status=ModBuildStatus.RUNNING,
            command=list(project.build_command),
            started_at=utcnow(),
        )
        self.store.save_mod_build(build)
        is_demo = project.id == "demo-mod" or root == self.demo_root
        if is_demo and not project.build_command:
            await asyncio.sleep(0)
            finished = build.model_copy(
                update={
                    "status": ModBuildStatus.SUCCEEDED,
                    "finished_at": utcnow(),
                    "output": "Demo 构建完成：已检查项目结构和资源引用。",
                    "artifact_paths": [f"demo://mod-builds/{build.id}.jar"],
                    "exit_code": 0,
                }
            )
            self.store.save_mod_build(finished)
            self._save_build_evidence(project, finished)
            return finished
        if not project.build_command:
            finished = build.model_copy(
                update={
                    "status": ModBuildStatus.BLOCKED,
                    "finished_at": utcnow(),
                    "error": "build_command_not_configured",
                    "output": "未配置显式构建命令，MineOps 不会猜测或执行 shell。",
                }
            )
            self.store.save_mod_build(finished)
            return finished
        self._validate_build_command(project.build_command, root)
        if clean:
            await asyncio.sleep(0)
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *self._resolve_build_command(project.build_command, root),
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=os.environ.copy(),
            )
            output_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=project.build_timeout_seconds)
            output = _redact_output(output_bytes.decode("utf-8", errors="replace"))
            artifacts = self._find_artifacts(root)
            status = ModBuildStatus.SUCCEEDED if process.returncode == 0 else ModBuildStatus.FAILED
            finished = build.model_copy(
                update={
                    "status": status,
                    "finished_at": utcnow(),
                    "output": output,
                    "exit_code": process.returncode,
                    "artifact_paths": artifacts,
                    "error": None if status == ModBuildStatus.SUCCEEDED else "build_process_failed",
                }
            )
        except TimeoutError:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            finished = build.model_copy(
                update={
                    "status": ModBuildStatus.FAILED,
                    "finished_at": utcnow(),
                    "error": "build_timeout",
                    "output": "构建超过配置的超时时间，已停止进程。",
                }
            )
        except Exception as exc:
            finished = build.model_copy(
                update={
                    "status": ModBuildStatus.FAILED,
                    "finished_at": utcnow(),
                    "error": str(exc),
                }
            )
        self.store.save_mod_build(finished)
        self._save_build_evidence(project, finished)
        return finished

    def list_builds(self, project_id: str, limit: int = 50) -> list[ModBuildRecord]:
        self.get_project(project_id)
        return self.store.list_mod_builds(project_id, limit)

    def _save_build_evidence(self, project: ModProject, build: ModBuildRecord) -> ModEvidence:
        evidence = ModEvidence(
            id=f"me-{secrets.token_urlsafe(10)}",
            project_id=project.id,
            kind=ModEvidenceKind.BUILD,
            title=f"构建记录 {build.id}",
            excerpt=(build.output or build.error or "无构建输出")[-20_000:],
            metadata={"build_id": build.id, "status": build.status.value, "exit_code": build.exit_code},
        )
        self.store.save_mod_evidence(evidence)
        return evidence

    def _fail_patch(self, patch: ModPatch, error: str) -> ModActionResult:
        failed = patch.model_copy(update={"status": ModPatchStatus.FAILED, "error": error})
        self.store.save_mod_patch(failed)
        return ModActionResult(
            status="failed",
            summary=f"补丁未应用：{error}。",
            data={"patch": failed.model_dump(mode="json")},
            next_actions=["重新读取文件并生成新的补丁，避免覆盖其他人的修改。"],
        )

    def _validate_root(self, root: Path) -> Path:
        resolved = root.expanduser().resolve()
        if not resolved.is_dir():
            raise ModWorkspaceError("project_root_not_found")
        return resolved

    def _safe_path(
        self,
        project: ModProject,
        relative_path: str,
        *,
        require_file: bool,
        allow_missing: bool = False,
    ) -> Path:
        normalised = relative_path.replace("\\", "/").strip()
        parts = normalised.split("/")
        if not normalised or any(part in {"", ".", ".."} for part in parts) or Path(normalised).is_absolute():
            raise ModWorkspaceError("mod_path_must_be_relative")
        if self._is_sensitive_path(parts):
            raise ModWorkspaceError("mod_sensitive_path_forbidden")
        root = self._validate_root(Path(project.root))
        target = (root / Path(*parts)).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ModWorkspaceError("mod_path_outside_project") from exc
        if target.exists() and target.is_symlink():
            raise ModWorkspaceError("mod_symlink_target_forbidden")
        if require_file and not target.is_file():
            raise ModWorkspaceError("mod_file_not_found")
        if not allow_missing and not target.exists() and not require_file:
            raise ModWorkspaceError("mod_path_not_found")
        return target

    def _scan_files(self, root: Path) -> list[ModFileInfo]:
        result: list[ModFileInfo] = []
        total = 0
        for path in sorted(self._iter_files(root), key=lambda item: item.as_posix()):
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            total += size
            if total > MAX_TOTAL_BYTES:
                break
            payload = path.read_bytes()
            result.append(
                ModFileInfo(
                    path=self._relative(path, root),
                    size_bytes=size,
                    sha256=_sha256_bytes(payload),
                    language=_language_for(path),
                )
            )
        return result

    def _iter_files(self, root: Path) -> Iterable[Path]:
        for current, directories, files in os.walk(root, followlinks=False):
            directories[:] = [item for item in directories if item not in IGNORED_DIRECTORIES]
            current_path = Path(current)
            for name in files:
                path = current_path / name
                if path.is_symlink() or self._is_sensitive_path(path.relative_to(root).parts):
                    continue
                yield path

    def _relative(self, path: Path, root: Path) -> str:
        return path.resolve().relative_to(root.resolve()).as_posix()

    def _is_sensitive_path(self, parts: Iterable[str]) -> bool:
        for part in parts:
            lowered = part.lower()
            if lowered in SENSITIVE_NAMES or lowered.endswith(tuple(SENSITIVE_SUFFIXES)):
                return True
            if lowered == ".git" or lowered.startswith(".env"):
                return True
        return False

    def _detect_features(self, root: Path, names: set[str]) -> list[str]:
        features: list[str] = []
        if "fabric.mod.json" in names:
            features.append("fabric_metadata")
        if "meta-inf/mods.toml" in names or "mods.toml" in names:
            features.append("forge_metadata")
        if "meta-inf/neoforge.mods.toml" in names or "neoforge.mods.toml" in names:
            features.append("neoforge_metadata")
        if "manifest.json" in names and any("behavior_packs/" in name or "resource_packs/" in name for name in names):
            features.append("bedrock_addon_metadata")
        if "pack.mcmeta" in names:
            features.append("minecraft_resource_metadata")
        if (root / "gradlew").is_file() or (root / "gradlew.bat").is_file():
            features.append("gradle_build")
        return features

    def _scenario_title(self, kind: ModTestScenarioKind) -> str:
        return {
            ModTestScenarioKind.NEW_ITEM: "新物品验证",
            ModTestScenarioKind.NEW_BLOCK: "新方块验证",
            ModTestScenarioKind.NEW_RECIPE: "新配方验证",
            ModTestScenarioKind.ENTITY_BEHAVIOR: "实体行为验证",
            ModTestScenarioKind.PLAYER_INTERACTION: "玩家交互验证",
            ModTestScenarioKind.HUD_GUI: "HUD / GUI 验证",
        }[kind]

    def _validate_build_command(self, command: list[str], root: Path) -> None:
        if not command or len(command) > 32:
            raise ModWorkspaceError("build_command_not_configured")
        for token in command:
            if (
                any(operator in token for operator in SHELL_TOKENS)
                or token.lower() in UNSAFE_BUILD_FLAGS
                or "\x00" in token
            ):
                raise ModWorkspaceError("unsafe_build_command_token")
        executable = Path(command[0]).name.lower()
        is_bare_command = not Path(command[0]).is_absolute() and Path(command[0]).parent == Path(".")
        if executable in SAFE_BUILD_EXECUTABLES and is_bare_command:
            return
        candidate = Path(command[0]).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ModWorkspaceError("build_executable_outside_project") from exc
        if not candidate.is_file():
            raise ModWorkspaceError("build_executable_not_found")

    def _resolve_build_command(self, command: list[str], root: Path) -> list[str]:
        resolved = list(command)
        first = Path(resolved[0])
        if first.parent != Path(".") and not first.is_absolute():
            resolved[0] = str((root / first).resolve())
        return resolved

    def _find_artifacts(self, root: Path) -> list[str]:
        paths: list[str] = []
        for folder in (root / "build" / "libs", root / "dist", root / "out"):
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    paths.append(path.resolve().relative_to(root).as_posix())
        return paths[:100]
