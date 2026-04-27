---
name: memory-editor
description: Deterministic workflow for memory add/update/delete operations. Use when user asks to remember, revise, or forget stored memories.
---
# Memory Editor Skill

目标：把记忆编辑操作变成稳定流程，避免“误删、误改、口头承诺未落库”。

触发规则：

1. `新增`：用户明确要求“记住/记录/以后按这个来”。
2. `删除`：用户明确要求“忘掉/删除/不再使用这条记忆”。
3. `更新`：用户明确要求“改成/更新为/不是 A 是 B/从现在开始用 B”。

执行顺序：

1. 先判定意图（新增/删除/更新），并先区分“这是长期 memory，还是当前 session working state”。
2. 删除或更新前，先调用 `memory_search` 定位目标。
3. 若命中 0 条：反馈未找到，不要假装已更新。
4. 若命中 >1 条：先澄清目标，不要盲改。
5. 目标唯一时执行：
   - 新增长期 memory：`memory_write`
   - 删除：`memory_forget`
   - 更新：`memory_update`（内部是先删旧、再写新）
6. 操作后再调用 `memory_search` 做一次校验（可选但推荐）。

补充规则：

1. 当前任务目标、下一步、会话内临时决策、working notes，不要写进 memory，优先用 `state_set`。
2. 只有“跨会话仍有复用价值”的用户经验、稳定偏好、长期事实，才走 `memory_write`。

回复约束：

1. 只有工具成功，才能说“已记录/已删除/已更新”。
2. 工具失败或未执行时，必须明确说明失败原因与下一步。
3. 涉及长期规则时，明确写出新记忆内容，便于用户确认。
