# ANL MineOps

面向 Minecraft 服主的本地自托管 AI 运维助手。当前版本是 `Experimental/Beta`，首发聚焦 Bedrock/BDS + Endstone 的状态、日志、诊断、备份和受策略控制的生命周期操作。

## 模组开发与验证工作台（Experimental）

参考 [newstarbar/ModCrafting](https://github.com/newstarbar/ModCrafting) 的 Plan → Execute → Evidence 思路，MineOps 现在提供一个受控的模组工作台。它可以分析已配置的 Fabric/Forge/NeoForge/基岩版项目、读取文本文件、生成带期望哈希的补丁草稿、在审批后应用补丁、执行服主显式配置的白名单构建命令，并从六类模板生成测试场景：新物品、新方块、新配方、实体行为、玩家交互和 HUD/GUI。

首发测试适配器是 `DemoModTestAdapter`：它只检查 fixture、文件信号和结构化断言，不启动真实 Minecraft 客户端，也不伪造截图或游戏日志。真实 Gradle/Minecraft Bridge 属于后续适配能力。工作区会拒绝绝对路径、路径穿越、敏感文件、符号链接逃逸和任意 shell；`apply_mod_patch`、`build_mod_project` 默认需要审批，所有工具调用仍写入审计记录。

对应 API 统一位于 `/api/v1/mod-projects`，包括项目分析、文件读取、补丁队列、构建记录、测试场景和证据查询。Agent 对话可以使用“分析 demo 模组项目”“为新物品创建模组测试场景并验证”等请求；需要写入或构建时会在审批队列暂停。

## 快速开始

需要 Python 3.11+、Node.js 20+ 和 `uv`。

```powershell
uv sync --extra dev
Copy-Item .env.example .env
uv run uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8787
```

另开终端启动前端：

```powershell
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。未配置模型时，演示服务器仍可完成状态、日志诊断、玩家查询和审批流程；不会启动真实 BDS。

### Beta 公测建议流程

先使用默认的 `demo` 服务器和 `demo-mod` fixture 验证完整流程，再决定是否连接自己的 BDS 或模组项目。模组工作台的详细步骤见 `docs/mod-workbench.md`，GitHub 发布说明见 `docs/release/github-beta-release.md`，MineBBS 招募帖见 `docs/release/minebbs-beta-post.md`。公测不要求真实 Minecraft 客户端、API Key、RCON 密码或上传任何本地文件。

可选启用 MCP 工具服务：

```powershell
uv sync --extra mcp
uv run --extra mcp python -m backend.app.mcp_main
```

`backend.app.mcp_server:create_mcp_server` 使用官方 Python MCP SDK 暴露同一套 typed 工具；MCP 调用仍经过 MineOps 的权限、审批和审计路径，不能绕过策略。

## 添加真实服务器配置

前端“模型与权限”区域的“添加服务器”表单会把 BDS 目录、启动命令参数、日志/世界相对路径和适配器类型保存到 SQLite，并在服务重启时自动注册。启动命令是服主显式配置的适配器参数，Agent 不能修改或拼接任意 shell 命令；密码只填写环境变量名，不填写密码值。`BdsProcessAdapter` 已支持基于世界目录的 ZIP 备份、SHA-256 校验和受策略保护的恢复；Endstone RCON 目前支持固定 `list` 玩家查询，完整 save-safe 协议和更多 RCON 能力仍属于后续适配工作。

## 自定义模型接口

provider 配置只保存 `base_url`、模型名和 API Key 环境变量名，不保存 API Key 本身。第一版使用 OpenAI-compatible Chat/Responses 协议，因此可以接入自定义网关和 `anlapi`。

保存后可以先使用“检查配置”执行离线环境检查，再使用“在线探测”请求 provider 的 `/models` 目录；在线探测只返回可达性、HTTP 状态、目标模型是否存在以及 provider 自己声明的能力，不记录密钥或响应正文。对应接口是 `GET /api/v1/providers/{provider_id}/probe?live=false|true`。

对话区可以选择已启用的 provider。只有在线探测明确声明支持工具调用时，Agent 才会注册重启、备份、恢复、模组补丁和构建等写工具；未探测或不支持时自动进入只读模式。演示模式不调用任何模型。

`anlapi` 是可选推荐线路：<https://api.anlmc.top>，QQ群 `146499741`。项目不会强制路由、在每条回复中插入广告或上传本地日志。

## 安全边界

- 默认只绑定本机 `127.0.0.1`。
- 读操作默认自动执行；启动、停止、重启和备份默认需要审批；恢复默认禁用。
- 不提供默认开放的任意 shell/RCON 命令工具。
- 服务器日志只作为不可信输入，不能改变系统策略。
- 不要把 API Key、RCON 密码、服务器凭据或生产日志提交到 Git。

## 公测范围

项目采用 MIT 许可证，欢迎服主先使用 `DemoAdapter` 和 `demo-mod` 体验，再通过自己的 BDS/Endstone 适配器或模组项目进行测试。请在 Issue 中提供版本、适配器、loader、模组项目类型、脱敏日志、复现步骤和期望结果。

GitHub 仓库：[ANL-694/anl-mineops](https://github.com/ANL-694/anl-mineops)。MineBBS 招募帖草稿见 `docs/release/minebbs-beta-post.md`，测试者应自行连接自己的服务器。

本项目与 Mojang、Microsoft、Minecraft 官方没有隶属或背书关系。
