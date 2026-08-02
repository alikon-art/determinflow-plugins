# API 入口

FastAPI OpenAPI 文档是完整契约。本页只列最常用的生产入口。

## 建书与生产

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/v1/novel/books` | 创建书籍 |
| `POST` | `/api/v1/novel/books/{book_id}/world/build` | 构建世界观 |
| `POST` | `/api/v1/novel/books/{book_id}/characters/build` | 构建角色 |
| `POST` | `/api/v1/novel/books/{book_id}/story-plan/build` | 构建故事规划 |
| `POST` | `/api/v1/novel/books/{book_id}/outline/build` | 构建卷纲与近纲 |
| `POST` | `/api/v1/novel/books/{book_id}/chapters/{number}/generate` | 生产章节 |
| `POST` | `/api/v1/novel/books/{book_id}/chapters/{number}/post-hoc` | 执行后验 |
| `POST` | `/api/v1/novel/books/{book_id}/chapters/{number}/polish` | 润色章节 |

## Job 与进度

生产入口返回 Job ID。客户端可以读取 Job 状态或订阅 SSE：

```text
GET /api/v1/novel/jobs/{job_id}
GET /api/v1/novel/jobs/{job_id}/stream
```

写请求支持 `Idempotency-Key`、`X-Actor-Ref` 和 `X-Request-Id`。相同幂等键只有在请求内容
一致时才会复用原 Job。
