# Security Policy

请使用 GitHub 仓库的 **Security → Report a vulnerability** 私密报告功能，不要在公开
Issue 中提交漏洞细节或真实凭据。

Bishu Novel 是资源型 Plugin，不访问数据库，也不注册业务 API。它的本地存档脚本只接受
当前 Workflow Workspace（工作流工作区）内的相对路径，并拒绝绝对路径和 `..` 路径穿越。

模型和可选 AI Detect Gateway 的凭据仍由 DeterminFlow Core 或对应服务管理，不要写入
Plugin 仓库或小说工作区。发现凭据进入 Git 历史后，应立即吊销并更换。
