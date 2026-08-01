# ANL MineOps 架构说明

```text
React/Vite
    │  REST + SSE
FastAPI API
    │
MineOpsService ── SQLite runs / approvals / audits / providers / policies
    │
PydanticAI AgentRuntime ── typed tools ── PolicyEngine
    │                                      │
    ├────────────── ServerAdapter ──────────┘
    │                ├─ DemoAdapter
    │                ├─ BdsProcessAdapter
    │                └─ EndstoneRconAdapter
    │
    └────────────── ModWorkspaceService ── SQLite projects / patches / builds / scenarios / evidence
                    ├─ DemoModTestAdapter
                    └─ future Minecraft Bridge
```

## 关键边界

- Agent 只能请求已注册的 typed tool，不能直接运行 shell 或拼接任意 RCON 命令。
- `PolicyEngine` 在工具执行前检查风险、模式、服务器白名单和审批状态。
- 所有工具调用都返回结构化结果，并产生审计记录；模型没有执行的操作不能被渲染成“已完成”。
- provider 配置保存 API 地址、模型名和环境变量名，不保存密钥值。
- DemoAdapter 让 UI、Agent 和权限流程在没有真实 BDS 的情况下可重复测试。
- ServerConfig 将服主显式提供的适配器参数持久化到 SQLite；启动时由 server registry 自动注册，Agent 仍只能调用固定 typed tool。
- ModWorkspaceService 只在项目根内读取和写入文本文件；补丁应用前校验期望 SHA-256，构建命令必须由服主显式配置且经过安全白名单检查。
- 模组测试场景只生成步骤和断言；Demo 测试适配器产出结构化证据，真实客户端、截图和游戏内 Bridge 不属于首发发布门槛。

## 事件流

一次运行依次产生 `run_started`、`tool_requested`、`tool_completed` 或 `approval_required`，最后产生 `run_completed` / `run_failed`。前端通过 `/api/v1/runs/{id}/events` 使用 SSE 订阅。
