# 本地存档结构

笔枢不创建数据库，也不为书籍、章节或 Job 生成 UUID。用户为一本书选择一个固定的
Workflow Workspace（工作流工作区），全部 Workflow 直接在该目录中读写。

```text
my-novel/
├── archive/    # 伏笔、叙事债务等结构化长期索引
├── cache/      # Agent 输出与确定性脚本的中间文件
├── meta/       # 世界观、角色、故事规划、风格等可读资料
├── outline/    # 卷纲与近纲
├── story/      # 按章节号保存正文、状态和后验结果
└── world/      # 六个世界观维度的原始 JSON
```

## 使用方式

1. 为书籍确定一个易读目录名，例如 `data/books/echo-zone`。
2. 创建每条 Workflow Task 时，把该路径填写到 `workspace_override`。
3. 按 `build`、`character`、`story-plan`、`outline`、`mvp` 的顺序生产。
4. 章节完成后按需运行 `post-hoc` 和 `polish`，继续使用同一路径。

目录名就是本地书籍身份。移动、复制或备份整个目录即可迁移、复制或备份一本书。

## 数据边界

- `meta/`、`outline/`、`story/`、`world/` 和 `archive/` 是长期存档。
- `cache/` 保存可审计的中间产物；空间紧张时可以在完成整书备份后再清理。
- Script Library 只允许工作区内相对路径，拒绝绝对路径和 `..` 路径穿越。
- DeterminFlow 自己仍会管理 Workflow Task 状态；笔枢不读取或保存 Core 的 Task ID。
