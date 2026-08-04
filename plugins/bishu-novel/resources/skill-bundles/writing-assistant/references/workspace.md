# 书籍工作区与存档

一本书的固定 Workflow Workspace（工作流工作区）就是它的本地身份。Plugin 不创建数据库、
UUID 或独立书籍登记表；移动、复制或备份整个目录即可迁移、复制或恢复一本书。

## 两种使用面

| 使用面 | 做法 |
|---|---|
| 同一 Chat Main 会话 | 每个 Task 都使用 `workspace_mode=named_shared`，并复用同一安全 `workspace_ref` |
| Web/API | 每个 Task 都传同一个 `workspace_override` |

`task_isolated` 会为每条 Task 创建不同目录，不适合同一本书跨七条 Workflow 复用资料。
不要把路径字符串作为普通 Workflow 变量填写；工作区由 Task 创建参数决定。

`named_shared` 的物理目录仍按 Main 会话隔离。同一 `workspace_ref` 只有在同一个 Main 会话
内才指向同一目录；新会话使用同名值会得到另一个目录。跨会话继续一本书时，应继续原 Main
会话，或使用 Web/API 的固定 `workspace_override`。当前 Chat 工具没有任意路径重连能力。

## 长期目录

```text
my-novel/
├── archive/
│   ├── hooks.json
│   └── debts.json
├── cache/
│   ├── character/
│   ├── story_plan/
│   ├── sync/
│   ├── writer/
│   └── ...
├── meta/
│   ├── world_foundation.md
│   ├── character_profiles.md
│   ├── character_voice.md
│   ├── story_plan.md
│   ├── style_profile.md
│   ├── hooks.md
│   └── debts.md
├── outline/
│   ├── volume_outline.md
│   └── near_term_outline.md
├── story/
│   └── 0001/
│       ├── chapter.md
│       ├── world_state.md
│       ├── world_events.md
│       ├── single_chapter_guide.md
│       ├── character_state_long.md
│       ├── character_minor.md
│       ├── diff_world_resolved.md
│       ├── diff_story_confirmed.md
│       └── diff_character.md
└── world/
    ├── core_laws.json
    ├── space_time.json
    ├── society.json
    ├── history_culture.json
    ├── existence.json
    └── information.json
```

## 数据分级

- `world/`、`meta/`、`outline/`、`story/`、`archive/` 是长期存档，也是判断生产阶段的主要
  证据。
- `cache/` 是可审计中间产物。它可帮助定位模型输出、转换和整合问题；空间紧张时也应先
  完整备份书籍，再由用户决定是否清理。
- `archive/hooks.json` 与 `archive/debts.json` 是结构化索引，`meta/hooks.md` 与
  `meta/debts.md` 是可读渲染，不要只修改其中一边制造不一致。
- DeterminFlow 自己保存 Task/Run 状态；Bishu 不把这些 ID 写进书籍存档。

## 覆盖与恢复

`build`、`character`、`story-plan`、`outline` 和同章 `mvp` 都可能覆盖固定输出；
`polish` 会直接覆盖该章 `chapter.md`。在用户要求“重写”“重建”或重复运行已完成阶段时：

1. 先确认目标确实是覆盖，而不是创建下一卷或下一章。
2. 说明会受影响的长期文件。
3. 没有版本控制或恢复副本时，建议复制整个工作区再运行。
4. 运行后验证文件非空；失败时保留当前目录和 `cache/`，不要用空文件补齐门禁。

所有 Script Library 文件参数都应是工作区内相对路径。绝对路径或含 `..` 的穿越路径会被
拒绝；不要通过放宽路径来处理工作区选择错误。
