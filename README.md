# DeterminFlow Plugins

[`DeterminFlow`](https://github.com/alikon-art/DeterminFlow) 的官方 Workflow Plugin 仓库。
Plugin 可以把 Workflow、Agent、Prompt 和 Script Library（脚本库）一起交付，并由
Core 锁定到具体版本运行。

## 官方案例

| Plugin | 能力 |
|---|---|
| [`bishu-novel`](plugins/bishu-novel) | 无数据库、无 UUID 的本地小说生产流程 |

## 安装

在 DeterminFlow 的 Plugin 页面填写：

- Git URL：`https://github.com/alikon-art/DeterminFlow-Plugins.git`
- Ref：精确 Commit 或 Release Tag；纯本地版发布后使用 `v0.2.0` 或更高版本
- Subdirectory：`plugins/bishu-novel`

Core 会检查 Manifest 和资源，锁定精确 Commit，并在重启后启用 Plugin。

Plugin 当前与 Core 同机运行，拥有主进程可用的系统权限。请只安装可信来源，并为本地
小说工作区建立独立备份。

## License

本仓库使用 [GNU AGPL v3](LICENSE)（`AGPL-3.0-only`）许可证。
