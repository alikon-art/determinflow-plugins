# Security Policy

请使用 GitHub 仓库的 **Security → Report a vulnerability** 私密报告功能，不要在公开
Issue 中提交漏洞细节、签名样本或真实凭据。

Bishu Novel 会访问 PostgreSQL，并作为可信代码与 DeterminFlow Core 同机运行。生产环境
应使用独立数据库账户、最小权限、受限网络和 Secret File；启用 Engine HMAC 时，每个
Key 至少使用 32 bytes 的随机值。

仓库中的 `.env.example` 只能包含空值或本地占位值。发现凭据进入 Git 历史后，应立即
吊销并更换，删除文件本身不能让旧凭据失效。
