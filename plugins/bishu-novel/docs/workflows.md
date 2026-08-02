# Bishu Novel Workflows

本插件交付 7 条生产 Workflow。它们使用包内本地 ID，加载时由 DeterminFlow Core 的
Resource Resolver（资源解析器）映射为最终 ID；插件代码不拼接资源前缀。

| Workflow | 主要阶段 | 主要落盘内容 |
|---|---|---|
| `build` | 六维世界观并行生成、校验、合并 | 世界观 JSON 与 Markdown |
| `character` | 角色骨架、信念、深层维度、声音 | 角色 JSON 与角色档案 |
| `story-plan` | 故事宏观规划、风格提取 | 故事规划与风格档案 |
| `outline` | 卷纲、近纲 | 大纲版本与 Markdown |
| `mvp` | 世界状态、导演、角色状态、写手、整合 | 章节正文与中间状态 |
| `post-hoc` | 章节观察、裁决、状态回写 | 世界/角色差异、伏笔与债务 |
| `polish` | 自审、AI 检测、两阶段润色 | 新的章节正文版本 |

## 资源边界

- `resources/agents.json` 与 `resources/prompts.json` 只包含以上 Workflow 实际引用的资源。
- `resources/script-library/` 只包含生产流程使用的确定性脚本。
- `resources/migrations/` 只管理 Bishu Novel 自己的 PostgreSQL Schema。
- Workflow Node 类型由 Core 提供，Plugin 只组合现有 Node。

## 运行前置

`db_sync` 与 `json_to_db` 会连接 PostgreSQL。运行前需要配置 `DB_HOST`、`DB_PORT`、
`DB_NAME`、`DB_USER`，并通过 `DB_PASSWORD` 或 `DB_PASSWORD_FILE` 提供密码。

模型 ID 由 Agent 模板声明，实际 Provider 和凭据由 Core 管理。每个 Agent Node 都使用
自己的会话、模型配置和工具权限，脚本节点负责确定性转换与落库。
