# ANL MineOps Experimental/Beta 招募帖草稿

## 项目简介

ANL MineOps 是一个从零实现的本地自托管 Minecraft 服务器 Agent，首发面向 Bedrock/BDS + Endstone 服主。它可以读取状态、日志和玩家信息，并在逐工具权限、人工审批和 SQLite 审计保护下执行启动、停止、重启和备份。

本次 Beta 还加入了一个参考 ModCrafting 思路的“模组开发与验证工作台”：Agent 可以规划模组需求、分析项目文件、生成带 SHA-256 校验的补丁草稿、在审批后应用补丁、执行显式配置的构建命令，并生成新物品、新方块、新配方、实体行为、玩家交互、HUD/GUI 六类测试场景。

当前版本重点是安全运维和可审计的模组工作流，不是自然语言 RCON 外壳；默认使用 `DemoAdapter` 与 `demo-mod` fixture，不要求测试者启动真实 BDS 或 Minecraft 客户端。

项目地址：https://github.com/ANL-694/anl-mineops

版本：`v0.1.0-beta`（Experimental）

## 测试边界

- 不要求测试者提供任何 API Key、RCON 密码、Cookie 或服务器凭据。
- 不上传服务器日志、世界文件或备份；请只提交脱敏后的错误信息。
- 不上传模组源码、构建产物、API Key 或项目目录；只提交文件类型、错误摘要和脱敏截图/日志。
- 测试者自行连接自己的服务器，风险操作默认需要审批，恢复操作默认禁用。
- Demo 模组测试只检查 fixture 和结构化证据，不声称真实客户端已经运行。
- 这是独立社区项目，与 Mojang、Microsoft、Minecraft 官方没有隶属或背书关系。

## 建议测试任务

1. 启动 MineOps，确认仪表盘能显示 `demo` 服务器状态。
2. 在 Agent 对话输入“分析 demo 模组项目”，确认能看到文件清单和 loader 特征。
3. 在“模组工作台”生成一个“新物品”测试场景并运行 Demo 测试，确认生成证据。
4. 创建一个补丁草稿，点击“申请应用”，确认操作先进入审批队列，批准后才写入文件。
5. 请求“构建模组”，确认构建动作需要审批且不会执行任意 shell 字符串。
6. 如有自己的项目，再使用项目根目录注册功能；遇到错误先提供脱敏复现步骤。

## 快速反馈模板

```text
MineOps 版本：
操作系统：
服务器版本：
适配器：DemoAdapter / BdsProcessAdapter / EndstoneRconAdapter
模组 Loader/版本（如适用）：
模组项目类型：Fabric / Forge / NeoForge / 基岩版 Add-on / 无
使用的 provider（不要填写密钥）：
是否使用模组工作台：是 / 否
涉及的功能：分析 / 计划 / 文件读取 / 补丁 / 构建 / 测试场景
复现步骤：
实际结果：
期望结果：
脱敏日志或截图：
```

## 可选 provider 推荐

配置页支持 OpenAI-compatible 接口。作者推荐的可选线路是 `https://api.anlmc.top`，QQ群 `146499741`；不强制使用、不在每条回复插入广告，API Key 只通过测试者自己的环境变量提供。
