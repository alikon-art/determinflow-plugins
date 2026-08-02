# Contributing

感谢你参与 DeterminFlow 官方 Plugin。

- Bug 或功能建议先开 Issue，写明 Plugin 版本、复现条件和期望行为。
- 新 Workflow 应有明确输入、输出、失败策略和不依赖真实凭据的测试。
- 不要提交真实小说数据、数据库导出、API Key、密码、HMAC Key 或本地绝对路径。
- 改动 Bishu 资源后必须运行 Core Workflow 校验器和插件测试。

```bash
export PYTHONPATH=/path/to/determinflow:/path/to/determinflow-plugins/plugins/bishu-novel
python -m pytest -q plugins/bishu-novel/tests
python /path/to/determinflow/src/core/defaults/skills/workflow-guide/scripts/validate_definition.py \
  plugins/bishu-novel/resources/workflows
```

提交信息使用 Conventional Commits，例如 `fix(bishu): reject stale chapter version`。
提交 Pull Request 即表示你的贡献按 AGPL-3.0-only 许可证发布。
