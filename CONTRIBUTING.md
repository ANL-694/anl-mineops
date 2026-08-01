# 参与 ANL MineOps

感谢参与 ANL MineOps Beta。项目当前是 Experimental/Beta，欢迎反馈真实服主和模组开发工作流中的问题。

## 本地验证

需要 Python 3.11+、Node.js 20+ 和 `uv`：

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check backend
python scripts/validate_text.py
cd frontend
npm ci
npm run build
```

提交前请确认没有 API Key、RCON 密码、Cookie、服务器凭据、世界文件、备份或完整模组源码。模组工作台的 Demo fixture 位于 `fixtures/mod-demo`，不需要启动真实 Minecraft。

## 提交 Issue

请使用仓库 Issue 模板，并提供操作系统、MineOps 版本、Minecraft/Loader 版本、适配器或模组项目类型、最小复现步骤和脱敏错误摘要。不要把密钥或完整日志粘贴到公开 Issue。

## 变更边界

- 新工具必须使用 typed schema，并接入 `PolicyEngine`、审批和审计路径。
- 不新增任意 shell、任意 RCON 或绕过项目根目录的文件访问。
- 真实 Minecraft Bridge、截图和客户端观测应作为独立适配器提交，不改变 Demo 测试的可重复性。
- 用户可见文案默认使用中文，源文件保持 UTF-8。
