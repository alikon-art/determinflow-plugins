# Local Archive

笔枢的纯本地存档工具。它只读写当前 Workflow Workspace（工作流工作区）中的相对路径：

- `prepare`：检查前置文件，并为章节生产构建本地上下文；
- `checkpoint`：校验阶段产物，合并伏笔与叙事债务索引；
- `render`：把 JSON 存档渲染为 Markdown；
- `post-hoc`：归档章节后验结果。

脚本不连接数据库，不创建 UUID，也不访问工作区外路径。
