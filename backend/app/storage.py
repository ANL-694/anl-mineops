import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .schemas import (
    ApprovalRecord,
    AuditEvent,
    BackupRecord,
    ModBuildRecord,
    ModEvidence,
    ModPatch,
    ModProject,
    ModTaskPlan,
    ModTestScenario,
    ProviderProbeResult,
    ProviderProfile,
    RunEvent,
    RunRecord,
    ServerConfig,
    ToolPolicy,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Store:
    def __init__(self, database: str) -> None:
        self.path = None if database == ":memory:" else Path(database)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database if self.path is None else self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, prompt TEXT NOT NULL, server_id TEXT NOT NULL,
                provider_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, answer_json TEXT
            );
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                type TEXT NOT NULL, message TEXT NOT NULL, data_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS providers (
                id TEXT PRIMARY KEY, profile_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_probes (
                provider_id TEXT PRIMARY KEY, probe_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS server_configs (
                id TEXT PRIMARY KEY, config_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS backups (
                id TEXT PRIMARY KEY, server_id TEXT NOT NULL, backup_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS policies (
                tool_name TEXT PRIMARY KEY, policy_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY, approval_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audits (
                id TEXT PRIMARY KEY, audit_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mod_projects (
                id TEXT PRIMARY KEY, project_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mod_patches (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, patch_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mod_builds (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, build_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mod_scenarios (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, scenario_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mod_evidence (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, evidence_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mod_plans (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, plan_json TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(runs)").fetchall()}
        if "mod_project_id" not in columns:
            self.connection.execute("ALTER TABLE runs ADD COLUMN mod_project_id TEXT")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def save_run(self, run: RunRecord) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO runs
            (id, prompt, server_id, provider_id, mod_project_id, status, created_at, updated_at, answer_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.id,
                run.prompt,
                run.server_id,
                run.provider_id,
                run.mod_project_id,
                run.status.value,
                run.created_at.isoformat(),
                run.updated_at.isoformat(),
                run.answer.model_dump_json() if run.answer else None,
            ),
        )
        self.connection.commit()

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self.connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        from .schemas import AgentAnswer, RunStatus

        return RunRecord(
            id=row["id"],
            prompt=row["prompt"],
            server_id=row["server_id"],
            provider_id=row["provider_id"],
            mod_project_id=row["mod_project_id"],
            status=RunStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            answer=AgentAnswer.model_validate_json(row["answer_json"])
            if row["answer_json"]
            else None,
        )

    def add_event(self, event: RunEvent) -> RunEvent:
        cursor = self.connection.execute(
            """INSERT INTO run_events (run_id, type, message, data_json, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (
                event.run_id,
                event.type,
                event.message,
                json.dumps(event.data, ensure_ascii=False),
                event.created_at.isoformat(),
            ),
        )
        self.connection.commit()
        return event.model_copy(update={"id": int(cursor.lastrowid)})

    def list_events(self, run_id: str) -> list[RunEvent]:
        rows = self.connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [
            RunEvent(
                id=row["id"],
                run_id=row["run_id"],
                type=row["type"],
                message=row["message"],
                data=json.loads(row["data_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def save_provider(self, profile: ProviderProfile) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO providers (id, profile_json) VALUES (?, ?)",
            (profile.id, profile.model_dump_json()),
        )
        self.connection.commit()

    def save_server_config(self, config: ServerConfig) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO server_configs (id, config_json) VALUES (?, ?)",
            (config.id, config.model_dump_json()),
        )
        self.connection.commit()

    def get_server_config(self, server_id: str) -> ServerConfig | None:
        row = self.connection.execute(
            "SELECT config_json FROM server_configs WHERE id = ?", (server_id,)
        ).fetchone()
        return ServerConfig.model_validate_json(row["config_json"]) if row else None

    def list_server_configs(self) -> list[ServerConfig]:
        rows = self.connection.execute(
            "SELECT config_json FROM server_configs ORDER BY id"
        ).fetchall()
        return [ServerConfig.model_validate_json(row["config_json"]) for row in rows]

    def save_backup(self, backup: BackupRecord) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO backups (id, server_id, backup_json) VALUES (?, ?, ?)",
            (backup.id, backup.server_id, backup.model_dump_json()),
        )
        self.connection.commit()

    def list_backups(self, server_id: str) -> list[BackupRecord]:
        rows = self.connection.execute(
            "SELECT backup_json FROM backups WHERE server_id = ?", (server_id,)
        ).fetchall()
        backups = [BackupRecord.model_validate_json(row["backup_json"]) for row in rows]
        return sorted(backups, key=lambda item: item.created_at, reverse=True)

    def get_provider(self, provider_id: str) -> ProviderProfile | None:
        row = self.connection.execute(
            "SELECT profile_json FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        return ProviderProfile.model_validate_json(row["profile_json"]) if row else None

    def list_providers(self) -> list[ProviderProfile]:
        rows = self.connection.execute("SELECT profile_json FROM providers ORDER BY id").fetchall()
        return [ProviderProfile.model_validate_json(row["profile_json"]) for row in rows]

    def save_provider_probe(self, probe: ProviderProbeResult) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO provider_probes (provider_id, probe_json) VALUES (?, ?)",
            (probe.provider_id, probe.model_dump_json()),
        )
        self.connection.commit()

    def get_provider_probe(self, provider_id: str) -> ProviderProbeResult | None:
        row = self.connection.execute(
            "SELECT probe_json FROM provider_probes WHERE provider_id = ?", (provider_id,)
        ).fetchone()
        return ProviderProbeResult.model_validate_json(row["probe_json"]) if row else None

    def delete_provider_probe(self, provider_id: str) -> None:
        self.connection.execute("DELETE FROM provider_probes WHERE provider_id = ?", (provider_id,))
        self.connection.commit()

    def save_policy(self, policy: ToolPolicy) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO policies (tool_name, policy_json) VALUES (?, ?)",
            (policy.tool_name, policy.model_dump_json()),
        )
        self.connection.commit()

    def get_policy(self, tool_name: str) -> ToolPolicy | None:
        row = self.connection.execute(
            "SELECT policy_json FROM policies WHERE tool_name = ?", (tool_name,)
        ).fetchone()
        return ToolPolicy.model_validate_json(row["policy_json"]) if row else None

    def list_policies(self) -> list[ToolPolicy]:
        rows = self.connection.execute(
            "SELECT policy_json FROM policies ORDER BY tool_name"
        ).fetchall()
        return [ToolPolicy.model_validate_json(row["policy_json"]) for row in rows]

    def save_approval(self, approval: ApprovalRecord) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO approvals (id, approval_json) VALUES (?, ?)",
            (approval.id, approval.model_dump_json()),
        )
        self.connection.commit()

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        row = self.connection.execute(
            "SELECT approval_json FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        return ApprovalRecord.model_validate_json(row["approval_json"]) if row else None

    def list_approvals(self, pending_only: bool = False) -> list[ApprovalRecord]:
        rows = self.connection.execute("SELECT approval_json FROM approvals").fetchall()
        approvals = [ApprovalRecord.model_validate_json(row["approval_json"]) for row in rows]
        if pending_only:
            approvals = [item for item in approvals if item.status == "pending"]
        return sorted(approvals, key=lambda item: item.created_at, reverse=True)

    def save_audit(self, event: AuditEvent) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO audits (id, audit_json) VALUES (?, ?)",
            (event.id, event.model_dump_json()),
        )
        self.connection.commit()

    def list_audits(self, limit: int = 100) -> list[AuditEvent]:
        rows = self.connection.execute("SELECT audit_json FROM audits").fetchall()
        events = [AuditEvent.model_validate_json(row["audit_json"]) for row in rows]
        return sorted(events, key=lambda item: item.created_at, reverse=True)[:limit]

    def save_mod_project(self, project: ModProject) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO mod_projects (id, project_json) VALUES (?, ?)",
            (project.id, project.model_dump_json()),
        )
        self.connection.commit()

    def get_mod_project(self, project_id: str) -> ModProject | None:
        row = self.connection.execute(
            "SELECT project_json FROM mod_projects WHERE id = ?", (project_id,)
        ).fetchone()
        return ModProject.model_validate_json(row["project_json"]) if row else None

    def list_mod_projects(self) -> list[ModProject]:
        rows = self.connection.execute(
            "SELECT project_json FROM mod_projects ORDER BY id"
        ).fetchall()
        return [ModProject.model_validate_json(row["project_json"]) for row in rows]

    def save_mod_patch(self, patch: ModPatch) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO mod_patches (id, project_id, patch_json) VALUES (?, ?, ?)",
            (patch.id, patch.project_id, patch.model_dump_json()),
        )
        self.connection.commit()

    def get_mod_patch(self, patch_id: str) -> ModPatch | None:
        row = self.connection.execute(
            "SELECT patch_json FROM mod_patches WHERE id = ?", (patch_id,)
        ).fetchone()
        return ModPatch.model_validate_json(row["patch_json"]) if row else None

    def list_mod_patches(self, project_id: str) -> list[ModPatch]:
        rows = self.connection.execute(
            "SELECT patch_json FROM mod_patches WHERE project_id = ?", (project_id,)
        ).fetchall()
        patches = [ModPatch.model_validate_json(row["patch_json"]) for row in rows]
        return sorted(patches, key=lambda item: item.created_at, reverse=True)

    def save_mod_build(self, build: ModBuildRecord) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO mod_builds (id, project_id, build_json) VALUES (?, ?, ?)",
            (build.id, build.project_id, build.model_dump_json()),
        )
        self.connection.commit()

    def get_mod_build(self, build_id: str) -> ModBuildRecord | None:
        row = self.connection.execute(
            "SELECT build_json FROM mod_builds WHERE id = ?", (build_id,)
        ).fetchone()
        return ModBuildRecord.model_validate_json(row["build_json"]) if row else None

    def list_mod_builds(self, project_id: str, limit: int = 50) -> list[ModBuildRecord]:
        rows = self.connection.execute(
            "SELECT build_json FROM mod_builds WHERE project_id = ?", (project_id,)
        ).fetchall()
        builds = [ModBuildRecord.model_validate_json(row["build_json"]) for row in rows]
        return sorted(builds, key=lambda item: item.started_at, reverse=True)[:limit]

    def save_mod_scenario(self, scenario: ModTestScenario) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO mod_scenarios (id, project_id, scenario_json) VALUES (?, ?, ?)",
            (scenario.id, scenario.project_id, scenario.model_dump_json()),
        )
        self.connection.commit()

    def get_mod_scenario(self, scenario_id: str) -> ModTestScenario | None:
        row = self.connection.execute(
            "SELECT scenario_json FROM mod_scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
        return ModTestScenario.model_validate_json(row["scenario_json"]) if row else None

    def list_mod_scenarios(self, project_id: str) -> list[ModTestScenario]:
        rows = self.connection.execute(
            "SELECT scenario_json FROM mod_scenarios WHERE project_id = ?", (project_id,)
        ).fetchall()
        scenarios = [ModTestScenario.model_validate_json(row["scenario_json"]) for row in rows]
        return sorted(scenarios, key=lambda item: item.created_at, reverse=True)

    def save_mod_evidence(self, evidence: ModEvidence) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO mod_evidence (id, project_id, evidence_json) VALUES (?, ?, ?)",
            (evidence.id, evidence.project_id, evidence.model_dump_json()),
        )
        self.connection.commit()

    def get_mod_evidence(self, evidence_id: str) -> ModEvidence | None:
        row = self.connection.execute(
            "SELECT evidence_json FROM mod_evidence WHERE id = ?", (evidence_id,)
        ).fetchone()
        return ModEvidence.model_validate_json(row["evidence_json"]) if row else None

    def list_mod_evidence(self, project_id: str, limit: int = 100) -> list[ModEvidence]:
        rows = self.connection.execute(
            "SELECT evidence_json FROM mod_evidence WHERE project_id = ?", (project_id,)
        ).fetchall()
        evidence = [ModEvidence.model_validate_json(row["evidence_json"]) for row in rows]
        return sorted(evidence, key=lambda item: item.created_at, reverse=True)[:limit]

    def save_mod_plan(self, plan: ModTaskPlan) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO mod_plans (id, project_id, plan_json) VALUES (?, ?, ?)",
            (plan.id, plan.project_id, plan.model_dump_json()),
        )
        self.connection.commit()

    def get_mod_plan(self, plan_id: str) -> ModTaskPlan | None:
        row = self.connection.execute(
            "SELECT plan_json FROM mod_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        return ModTaskPlan.model_validate_json(row["plan_json"]) if row else None

    def list_mod_plans(self, project_id: str, limit: int = 50) -> list[ModTaskPlan]:
        rows = self.connection.execute(
            "SELECT plan_json FROM mod_plans WHERE project_id = ?", (project_id,)
        ).fetchall()
        plans = [ModTaskPlan.model_validate_json(row["plan_json"]) for row in rows]
        return sorted(plans, key=lambda item: item.created_at, reverse=True)[:limit]
