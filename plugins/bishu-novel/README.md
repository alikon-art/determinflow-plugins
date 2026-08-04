# Bishu Novel

`bishu-novel` 是随 DeterminFlow 开源的纯本地小说生产案例。它把长链路写作流程拆成
独立 Agent Node、确定性脚本和文件检查点，所有小说资料都保存在用户选择的本地
Workflow Workspace（工作流工作区）中。

## 发布内容

| 本地 Workflow ID | 用途 |
|---|---|
| `build` | 构建世界观的六个核心维度 |
| `character` | 生成角色骨架、信念、深层维度和声音 |
| `story-plan` | 生成故事规划与风格档案 |
| `outline` | 生成卷纲和近纲 |
| `mvp` | 生产章节正文，支持单写手或多写手组合 |
| `post-hoc` | 根据成稿更新世界、角色、伏笔和叙事债务 |
| `polish` | 自审、人文化处理和专业润色 |

包内还包括：

- 33 个生产 Agent/Prompt，以及 Workflow 需要的 Script Library；
- `writing-assistant` Skill，让 Main 同时作为用户的写作助手和写作工作流主管；
- `world/`、`meta/`、`outline/`、`story/`、`archive/` 与 `cache/` 组成的本地存档；
- 工作区内的文件完整性检查、JSON 索引和 Markdown 渲染。

## 运行要求

- DeterminFlow Core `v0.1.0` 或兼容版本
- Core `main` Agent 使用的默认模型和凭据需要完成配置
- `polish` 使用 AI Detect 节点时，需要配置可访问的 `AI_DETECT_GATEWAY_URL`

安装后不需要数据库、迁移、API、HMAC Key 或 UUID。运行每条 Workflow 时，为同一本书
填写相同的 `workspace_override`，例如 `data/books/my-novel`。书籍目录名由用户自行决定，
无需注册或生成 ID。

建议依次运行：`build` → `character` → `story-plan` → `outline` → `mvp` →
可选 `polish` → `post-hoc`。每条流程会直接复用同一工作区中的已有文件；进入下一章前
应完成当前章的 `post-hoc`，让后续章节读取已更新的连续性状态。

通过 Chat Main 使用时，安装后的 `bishu-novel-writing-assistant` Skill 默认启用并自动
注入 Main，会维护书籍上下文、选择下一条 Workflow、解释创作参数并监督落盘结果。用户仍可
在 Skill 页面关闭自动注入。同一 Main 会话创建不同 Task 时应使用相同的 `named_shared`
工作区名称；需要跨 Main 会话继续时，当前 Chat 工具不能仅凭同名 `workspace_ref` 重新连接
旧目录，应继续原会话，或通过 Web/API 使用固定的 `workspace_override`。

插件内的 Agent Definition（智能体定义）不固定模型，所有 Agent Node 默认继承 Core
`agents_config.json` 中 `main.model` 指向的模型。切换 Core 默认模型即可统一切换整套
工作流使用的模型，无需修改插件资源。

## 文档

- [Workflow 与资源](docs/workflows.md)
- [本地存档结构](docs/local-archive.md)
- [写作助手 Skill](resources/skill-bundles/writing-assistant/SKILL.md)

## License

Bishu Novel 使用 [GNU AGPL v3](LICENSE)（`AGPL-3.0-only`）许可证。
