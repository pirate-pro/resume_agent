---
name: tools
description: Tool usage policy and invocation checklist. Use whenever tool calls may improve correctness.
---
# Tools Skill

可用工具：

1. `state_set(key, value)`：写入或更新当前 agent 的私有 session state，适合当前目标、下一步、临时决策、working notes。
2. `state_publish(keys)`：把当前 agent 的私有 state 显式发布到 session shared state，供协作 agent 读取。
3. `state_list(scope="all")`：查看当前 session state；`scope` 可选 `agent/shared/all`。
4. `memory_write(content, tags=[])`：写入记忆候选（默认短期；可通过 tags 指定长期/共享倾向）。
5. `memory_search(query, limit=5)`：按当前 agent 作用域检索相关记忆（包含同 agent 的跨会话 short 记忆）。
6. `memory_forget(query, limit=5, hard_delete=false, reason?)`：先检索后遗忘，删除/作废符合查询的记忆。
7. `memory_update(query, new_content, new_tags=[], limit=3, hard_delete_old=false)`：替换记忆（先定位旧记忆，再删旧写新）。
8. `workspace_write_file(path, content)`：写入当前 session 的 workspace 文件。
9. `workspace_read_file(path)`：读取文件，查找顺序为“workspace 优先，若未命中则逐级向上到文件系统根目录”。
10. `session_list_files()`：列出当前会话上传文件及 active 状态。
11. `session_plan_file_access(file_id, user_goal?)`：基于文件元数据给出推荐访问策略（直读/先检索后精读等）。
12. `session_read_file(file_id, offset=0, max_chars=3000)`：读取文件文本内容，若未解析会懒解析。
13. `session_search_file(file_id, query, top_k=3, window_chars=160)`：在文件中检索关键词并返回片段。

规则：

- 调用工具前检查参数是否完整。
- 工具失败时如实报告失败原因，不要伪造成功。
- 使用 `state_*` 时：
  - 当前任务目标、下一步、局部结论、会话内临时约束，优先写 `state_set`，不要直接塞进 memory。
  - 只有在确实需要协作 agent 读取时，才调用 `state_publish`。
  - `state_list` 用于回看当前 session 的 working state，不替代 memory 检索。
- 使用 `memory_write` 时：
  - 如果内容看起来像当前 session working state，工具会拒绝写入，并要求改用 `state_set`。
  - 如果内容看起来像原始文件内容、代码块、JSON 工具输出，工具会拒绝写入；先提炼成稳定经验再写。
  - 临时信息可不带长期标签（默认走短期层）。
  - 长期偏好/约束建议带 `preference/constraint/long_term/policy` 等标签。
  - 仅在确实需要跨 Agent 共享时带 `shared/global/cross_agent`。
- 使用 `memory_forget` 时：
  - 先用足够具体的 query，避免误删。
  - 若命中多条，不要自行猜测，应先向用户澄清。
- 使用 `memory_update` 时：
  - 只有在目标唯一明确时才执行“先删后写”。
  - 当返回 `ambiguous_match` 时，先让用户确认目标后再重试。
- 文件工具必须使用相对路径，不允许路径逃逸。
- workspace 目录定义：`data/sessions/<session_id>/workspace`（由后端运行目录决定绝对路径）。
- 文件读取优先用会话文件工具（`session_*`），而不是盲猜文件内容。
- 对大文件优先采用“先检索再精读”的策略，避免一次性注入过长上下文。
