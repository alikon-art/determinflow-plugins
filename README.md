# DeterminFlow Plugins

DeterminFlow 的官方 Workflow Plugin 仓库。Plugin 可以把 API、Workflow、Agent、Prompt、
Script Library（脚本库）和数据库迁移一起交付，并由 Core 锁定到具体版本运行。

## 官方案例

| Plugin | 能力 |
|---|---|
| [`bishu-novel`](plugins/bishu-novel) | 建书、卷纲、章节生产、后验与润色 |

## 安装

在 DeterminFlow 的 Plugin 页面填写：

- Git URL：本仓库的 GitHub Clone 地址
- Ref：Release Tag，例如 `v0.1.0`
- Subdirectory：`plugins/bishu-novel`

Core 会检查 Manifest 和资源，锁定精确 Commit，并在重启后应用依赖、迁移和启用状态。

Plugin 当前与 Core 同机运行，拥有主进程可用的系统权限。请只安装可信来源，并在生产环境
使用独立账户、最小化数据库权限和 Secret File（密钥文件）。

## License

本仓库使用 [GNU AGPL v3](LICENSE)（`AGPL-3.0-only`）许可证。
