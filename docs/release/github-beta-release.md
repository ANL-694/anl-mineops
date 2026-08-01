# ANL MineOps v0.1.0-beta

## 发布定位

这是一个 `Experimental/Beta` 的本地自托管版本，面向 Minecraft Bedrock/BDS + Endstone 服主和希望测试 Agent 模组工作流的开发者。它不要求真实服务器或 Minecraft 客户端作为安装和 CI 门槛。

## 本版本包含

- 服务器状态、日志、玩家、生命周期操作、备份、校验、审批和审计。
- 自定义 OpenAI-compatible provider、环境变量密钥引用和工具能力探测。
- 模组开发与验证工作台：结构化计划、项目分析、文件读取、SHA-256 补丁草稿、审批后应用、受控构建。
- 六类 Demo 测试场景：新物品、新方块、新配方、实体行为、玩家交互、HUD/GUI。
- `DemoModTestAdapter` 和 `fixtures/mod-demo`，不启动真实 Minecraft 客户端。
- FastAPI `/api/v1/mod-projects` API、SSE 事件、MCP typed tools 和 React 工作台。

## 快速验证

```powershell
uv sync --extra dev
Copy-Item .env.example .env
uv run pytest
uv run ruff check backend
cd frontend
npm install
npm run build
```

启动后选择默认 `demo` 服务器，在对话中尝试：

- `规划一个新物品模组需求`
- `分析 demo 模组项目`
- `为新物品创建模组测试场景并验证`
- `构建模组`

构建和补丁应用默认需要审批。测试过程不会要求输入 API Key、RCON 密码，也不会上传本地日志、世界文件或模组源码。

## 已知限制

- Demo 测试适配器不会启动 Minecraft、读取游戏内截图或观察真实客户端状态。
- 真实 Gradle/Minecraft Bridge、Forge/NeoForge 深度适配和基岩版 Add-on 游戏内验证属于后续版本。
- 当前面向单个服主或小团队，不提供 SaaS、多租户、云端托管和集中式源码存储。
- GitHub 仓库和 Issue 模板已发布；仓库地址为 <https://github.com/ANL-694/anl-mineops>，欢迎通过 Issue 提交测试反馈。

GitHub 仓库已提供 `Bug 报告` 和 `功能建议` Issue 模板；提交者不应上传密钥、服务器凭据、世界文件、备份或完整模组源码。

贡献规范见 `CONTRIBUTING.md`，安全问题见 `SECURITY.md`。发布页面：<https://github.com/ANL-694/anl-mineops/releases>。

## 反馈

请提供操作系统、MineOps 版本、服务器适配器、Minecraft/Loader 版本、模组项目类型、复现步骤和脱敏错误摘要。不要提交 API Key、RCON 密码、Cookie、世界文件、备份或完整模组源码。

本项目与 Mojang、Microsoft、Minecraft 官方没有隶属或背书关系。
