# DB 同步脚本

## 功能

从 PostgreSQL 读取数据，渲染为 agent 可读的 Markdown 文件。

## 用法

```bash
python db_sync.py --book-id <UUID> --templates world,character,voice,style,story_plan
```

## 模板

| 模板 | 数据源 | 输出文件 |
|------|--------|---------|
| `world` | `world` 表 6 个 JSONB 维度 | `meta/world_foundation.md` |
| `character` | `character` 表 | `meta/character_profiles.md` |
| `voice` | `character.voice` JSONB | `meta/character_voice.md` |
| `style` | `book.style_profile` JSONB | `meta/style_profile.md` |
| `story_plan` | `book.story_plan` JSONB | `meta/story_plan.md` |

## 依赖

- `psycopg2`
- PostgreSQL 本地 127.0.0.1:5432
- 密码使用 `DB_PASSWORD`，未设置时可通过 `DB_PASSWORD_FILE` 传入
