# Tools Skill

可用工具：

1. `memory_write(content, tags=[])`：写入长期记忆。
2. `memory_search(query, limit=5)`：检索相关记忆。
3. `workspace_write_file(path, content)`：写入当前 session 的 workspace 文件。
4. `workspace_read_file(path)`：读取当前 session 的 workspace 文件。

规则：

- 调用工具前检查参数是否完整。
- 工具失败时如实报告失败原因，不要伪造成功。
- 文件工具必须使用相对路径，不允许路径逃逸。
