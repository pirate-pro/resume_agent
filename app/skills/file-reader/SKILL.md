---
name: file-reader
description: Read uploaded session files using list/search/read workflow with citations. Use when questions depend on file content.
---
# File Reader Skill

目标：在不扩大上下文负担的前提下，基于会话文件给出可追溯答案。

流程：

1. 先调用 `session_list_files()` 确认可用文件、active 状态、`file_id` 与元数据（大小、parsed_token_estimate、parsed_char_count）。
2. 用户未指定文件时，优先使用 active 文件；用户指定文件名时先映射到 `file_id`。
3. 调用 `session_plan_file_access(file_id, user_goal?)` 获取推荐策略。
4. 按策略执行：
   - `direct_read`：直接 `session_read_file(...)`；
   - `search_then_read`：先 `session_search_file(...)`，再 `session_read_file(...)`；
   - `focused_search_then_chunked_read`：先检索，再按 offset 分块精读。
5. 回答时标注来源（至少给出 `file_id` 和文件名），不要把检索命中当作未验证事实。

约束：

- 不要在没有工具结果时编造文件内容。
- 文件过大时分段读取，避免一次性请求过多文本。
- 工具返回解析失败时，直接反馈失败原因并给出下一步建议。
