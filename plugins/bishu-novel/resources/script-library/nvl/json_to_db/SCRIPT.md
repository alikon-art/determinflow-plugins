---
name: json-to-db
description: 通用 JSON 文件 → PostgreSQL 数据库写入脚本，支持 upsert-world 等操作模式
author: system
version: 1.0.0
---

## 用法

### upsert-world
批量写入/更新 6 个世界观维度到 world 表。

```bash
DB_PASSWORD_FILE=/run/secrets/db_password python3 json_to_db.py \
  --book-id <UUID> \
  --action upsert-world \
  world/core_laws.json \
  world/space_time.json \
  world/society.json \
  world/history_culture.json \
  world/existence.json \
  world/information.json
```

- 自动从文件名提取维度名（`core_laws.json` → `core_laws` 列）
- 已存在 world 行则 UPDATE 对应列，不存在则 INSERT 新行
- 需要 book 在 book 表中已存在
- 环境变量：DB_HOST(127.0.0.1) / DB_PORT(5432) / DB_NAME(novel_platform) / DB_USER(postgres) / DB_PASSWORD 或 DB_PASSWORD_FILE（二选一，DB_PASSWORD 优先）
