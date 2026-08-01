# 模组工作台

模组工作台借鉴 ModCrafting 的“计划 → 工具执行 → 证据”闭环，但首发只做可审计的本地 MVP，不启动真实 Minecraft 客户端。

## 快速演示

启动后，系统会注册 `demo-mod` 项目。可以在 Agent 对话中输入：

- `规划一个新物品模组需求`
- `分析 demo 模组项目`
- `为新物品创建模组测试场景并验证`
- `构建模组`

前两类请求是只读操作；构建和文件写入会进入审批队列。最后一类测试使用 `DemoModTestAdapter`，输出匹配文件、断言和证据 ID，不会连接游戏客户端。

## 项目配置

通过 `POST /api/v1/mod-projects` 注册项目：

```json
{
  "id": "my-fabric-mod",
  "name": "我的 Fabric 模组",
  "root": "D:/MinecraftProjects/my-fabric-mod",
  "kind": "fabric",
  "minecraft_version": "1.21.1",
  "build_command": ["gradlew.bat", "build"]
}
```

`root` 必须是存在的目录。构建命令只能是显式配置的参数数组；MineOps 不执行 shell 字符串，并拒绝 shell 操作符、`-c`/`/c`、绝对路径逃逸和不存在的项目内可执行文件。

## 补丁与测试

1. `GET /api/v1/mod-projects/{id}` 分析 loader、文件哈希和风险提示。
2. `GET /api/v1/mod-projects/{id}/files/{path}` 读取 UTF-8 文本文件。
3. `POST /api/v1/mod-projects/{id}/patches` 保存补丁草稿。更新补丁会记录 `expected_sha256`，文件被别人改过时不会覆盖。
4. `POST /api/v1/mod-projects/{id}/patches/{patch_id}/apply` 请求应用；默认需要一次性审批。
5. `POST /api/v1/mod-projects/{id}/builds` 请求受控构建；默认需要审批。
6. `POST /api/v1/mod-projects/{id}/scenarios` 从六类模板创建场景，`.../run` 运行 Demo 测试并产生证据。

所有动作继续使用 MineOps 的 `PolicyEngine`、SQLite 审批和审计表。工作区拒绝路径穿越、敏感文件、符号链接目标和二进制文件读取。未来接入真实 Gradle/Minecraft Bridge 时，应新增适配器，不应绕过这些边界。
