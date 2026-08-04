# Workflow 顺序与用户输入

本文件记录 `bishu-novel` 0.3.0 的静态摘要。运行时先用 `list_workflows` 和
`get_workflow` 核对实际定义；安装 Prefix 可能变化，有效 ID 不一定以
`bishu-novel-` 开头。

## 总体顺序

| 阶段 | 本地 Workflow ID | 前置 | 主要用户输入 | 主要长期产物 |
|---|---|---|---|---|
| 世界观 | `build` | 新工作区 | `premise`、`genre`、`language` | `world/*.json`、`meta/world_foundation.md` |
| 角色 | `character` | 世界观基础 | 同一 `premise`、`genre`、`language` | `meta/character_profiles.md`、`meta/character_voice.md` |
| 故事规划 | `story-plan` | 世界观与角色档案 | 同一 `premise`、`genre`、`language` | `meta/story_plan.md`、`meta/style_profile.md` |
| 大纲 | `outline` | 世界观、角色、故事规划 | `volume_number`、`estimated_length`、`words_per_chapter`、`latest_chapter` | `outline/volume_outline.md`、`outline/near_term_outline.md` |
| 章节生产 | `mvp` | 全部建书资料与大纲 | 章节号、上一章号、创作意图、目标字数、写手类型、语言 | `story/<章节>/chapter.md` 及本章状态 |
| 润色 | `polish` | 已有章节正文 | 章节号、语言、执行方案 | 覆盖该章 `chapter.md`，保留自审缓存 |
| 后验 | `post-hoc` | 最终章节正文与本章生产状态 | 章节号、语言 | 本章差异文件及更新后的伏笔、债务索引 |

## 新书前置

### `build`

把用户的创意整理为稳定的故事前提和题材，不要只填一句书名。运行会生成六个世界观维度：
核心规律、时空、社会、历史文化、存在和信息，并合并成可读的世界观基础。

重跑会覆盖对应世界观文件。已有章节的书若要重建世界观，应先解释连续性风险并备份工作区。

### `character`

沿用 `build` 的故事前提和题材。默认文件路径已指向世界观产物，通常不需要用户填写。
流程会依次生成角色骨架、信念、逐角色深层维度和声音锚。

### `story-plan`

沿用同一故事前提和题材，读取世界观与角色档案，生成宏观故事规划和风格档案。不要在这里
用新的 premise 偷换用户已经确认的核心故事。

### `outline`

- `volume_number`：目标卷号。公开本地版应显式提供；不要依赖旧说明中的数据库自动查询。
- `estimated_length`：短、中、长。
- `words_per_chapter`：例如 `2000-2500`，决定单章情节密度。
- `latest_chapter`：当前实际完成的最后一章，四位数字；新书为 `0000`。

同一目标卷再次运行属于重写。开始前说明现有卷纲和近纲可能被覆盖。

## 单章生产

### `mvp`

最少核对这些创作参数：

| 参数 | 说明 |
|---|---|
| `chapter_number` | 当前章，四位数字，例如 `0012` |
| `prev_chapter` | 上一章，例如 `0011`；首章为 `0000` |
| `human_intent` | 用户对本章事件、情绪、人物选择或结尾的要求，可空 |
| `world_intent` | 世界级外力，仅在用户明确需要时填写，可空 |
| `target_word_count` | 建议范围，例如 `3000-4000` |
| `writer_type` | `single` 或当前兼容值 `muti` |
| `language` | `中文` 或 `English` |

其余 file 变量和中间变量使用 Workflow 默认值。`mvp` 会读取建书资料、大纲、上一章状态和
上一章后验，生成本章世界状态、单章指导、角色状态、分镜、裁剪上下文和正文。若同章
`chapter.md` 已存在，本次运行会覆盖它。

### `polish`

完整润色包含外部 AI 检测、自审、人文化处理和专业润色，并覆盖原 `chapter.md`。当前定义
还提供“仅检查”执行方案；使用方案前以实际 definition 为准。两种路径都依赖
`AI_DETECT_GATEWAY_URL` 可访问。

润色原则上只改表达，不改情节事实。若最终正文的事件、角色状态、伏笔或信息边界发生变化，
后续必须重新做 `post-hoc`。

### `post-hoc`

读取最终章节正文与本章生产状态，观察偏差并裁决世界、故事、角色差异，同时合并伏笔和
叙事债务索引。完成后才能让下一章可靠读取上一章的连续性结果。

## 推进判断

| 已验证状态 | 下一步 |
|---|---|
| 工作区为空 | `build` |
| 有世界观，无角色档案或声音锚 | `character` |
| 有角色，无故事规划或风格档案 | `story-plan` |
| 有故事规划，无卷纲或近纲 | `outline` |
| 建书资料和大纲完整 | 对目标章运行 `mvp` |
| 章节正文完成，用户需要文字打磨 | 可选 `polish` |
| 最终正文完成，但本章差异文件缺失 | `post-hoc` |
| 本章后验完成 | 下一章 `mvp`；需要新卷时先 `outline` |

文件存在但为空不算完成。Task completed 但关键长期文件缺失也不算完成。
