# 部署与迁移

Bishu Novel 作为 DeterminFlow 同进程 Plugin 运行，不单独维护 Core 镜像或进程编排。

## 新环境

1. 创建独立 PostgreSQL 数据库和最小权限用户。
2. 在 Plugin Settings 中填写 `settings.schema.json` 定义的配置；密码优先使用
   `DB_PASSWORD_FILE`。
3. 从 Git Release 安装 `plugins/bishu-novel`，启用后重启 DeterminFlow。
4. Core 会依次执行 Manifest 中的 `migrate`、`verify`，全部通过后才启动 API。
5. 检查 `/api/extensions` 中插件状态为 `running`，再访问
   `/api/v1/novel/books?limit=1&offset=0`。

## 接管既有数据库

只有已经存在表结构、但还没有 Migration Checksum Ledger（迁移校验账本）的数据库才需要
执行 `adopt`：

```bash
python -m ai_company_plugin_bishu_novel.backend.migrations_cli \
  adopt \
  --release-revision <plugin-commit>
```

`adopt` 不会由 Core 自动执行。执行前应先备份数据库，并确认现有 Schema 与目标迁移一致。

## Engine HMAC

生产环境建议启用 `ENGINE_SIGN_ENABLED`，完成观察期后再把 `ENGINE_SIGN_MODE` 切换为
`enforce`。每个 Key 至少 32 bytes，通过 `ENGINE_SIGN_KEYS_FILE` 注入；不要把 Key 写入
Plugin Settings 的导出文件、命令行或日志。
