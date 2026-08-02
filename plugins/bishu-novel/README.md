# Bishu Novel

`bishu-novel` 是随 DeterminFlow 开源的官方小说生产案例。它把一套真实运行的长链路写作
流程拆成独立 Agent Node、确定性脚本和数据库检查点，并通过 API 对外提供服务。

## 发布内容 ✍️

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

- `/api/novel` 与 `/api/v1/novel` 接口、SSE 进度事件和幂等 Job；
- PostgreSQL Schema、前向迁移和版本校验；
- 33 个生产 Agent/Prompt，以及 Workflow 需要的 Script Library；
- Engine HMAC 验证、Secret File 和数据库配置支持。

Python 包路径暂时保留 `ai_company_plugin_bishu_novel`，这是首版兼容标识，不影响以
DeterminFlow Plugin 的方式安装和运行。

## 运行要求

- DeterminFlow Core `v0.1.0` 或兼容版本
- Python 3.11+
- PostgreSQL 14+
- Workflow 中引用的模型需要在 Core 中完成配置
- `polish` 使用 AI Detect 节点时，需要配置可访问的 `AI_DETECT_GATEWAY_URL`

复制 `.env.example` 中需要的配置。密码与 HMAC Key 必须通过环境变量、Plugin Settings
或 `*_FILE` 提供，不要写进仓库。

```bash
python -m pip install -r requirements.txt
```

正常安装时，依赖和数据库迁移由 DeterminFlow 根据 `extension.toml` 在冷启动阶段处理。

## 文档

- [Workflow 与资源](docs/workflows.md)
- [API 入口](docs/api.md)
- [部署与迁移](docs/deploy.md)

## License

Bishu Novel 使用 [GNU AGPL v3](LICENSE)（`AGPL-3.0-only`）许可证。
