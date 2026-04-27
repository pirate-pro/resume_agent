---
name: memory
description: Guidance for long-term memory write and retrieval decisions. Use when user preferences or persistent facts are involved.
---
# Memory Skill

- 当用户表达长期偏好、稳定事实、跨会话仍会复用的经验时，考虑写入 memory。
- 当用户明确要求“忘记/删除/不再按此执行”时，优先走 `memory_forget`。
- 当用户明确要求“把 A 改成 B/更新为 B”时，优先走 `memory_update`（先删后写）。
- 回答前可先检索 memory，避免丢失历史偏好。
- 当前任务目标、下一步、working notes、一次性会话约束，优先使用 `state_set`，不要误写成 memory。
- 不要把一次性的短期上下文误写成长期偏好。
- 不要把原始文件内容、代码块、JSON 工具输出直接写入 memory；应先压缩成稳定、可复用的经验结论。
- 写入 memory 时保持内容简洁、可复用、可验证。
- 默认先短期记录；满足“重复出现、用户确认、显式规则”后再晋升长期更稳妥。
