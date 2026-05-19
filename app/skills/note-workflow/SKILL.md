---
name: note-workflow
description: 用户明确要求保存、整理、追加或沉淀笔记时使用，处理 Note 与 memory、artifact、career 记录的边界。
---
# Note Workflow

目标：把用户明确想保留的内容沉淀为可编辑笔记，同时避免把笔记、memory 和文件事实源混在一起。

- NoteService 用于用户可见、可编辑、可归档的笔记资产；它不是 memory，也不是 artifact。
- 用户明确说“存到笔记 / 保存为笔记 / 整理成笔记 / 记录这次复盘 / 把面试题记下来”时，才调用 `note_create` 或 `note_append`。
- 用户只是要求简历诊断、JD 分析、匹配报告、定制简历、投递前检查或面试准备时，不要自动创建 Note；这些主流程仍然先产出 career 产品记录和 session artifact。
- 用户说“记住我以后都想投 AI 应用后端 / 以后都按这个偏好”这类长期偏好或稳定事实时，按现有 memory 规则判断；不要因为有 NoteService 就改写 memory 边界。
- 如果用户表达“记一下”但无法判断是“写笔记”还是“长期记住”，先追问，不要同时写 note 和 memory。
- `note_create` / `note_append` 不会也不应该触发 memory 写入；不要在创建 note 后再自动调用 `memory_write`。
- 从报告、诊断、投递前检查、面试准备材料整理成笔记时，`source_artifact_id` 指当前 session 的来源 artifact；`source_refs` 和 `evidence_refs` 要包含实际来源的 artifact id、application_id、fit_id、jd_analysis_id、resume_profile_id 等受控 id。
- Note 正文是用户整理后的可编辑内容；原始报告、简历、JD、定制简历仍以 `SessionArtifact` 为文件事实源。不要把 note 当成报告 artifact 的替代品。
- 创建或更新 Note 时按用途设置 `note_type`：`note` 表示自由记录/总结/杂项，`learning` 表示学习笔记/短板复盘，`resource` 表示面经/文章/链接/资产摘录；无法判断时用 `note`。
- 不要向 note 工具传任何路径、workspace 文件路径、`source_session_id`、`created_at`、`updated_at` 或 `status`；note 工具会使用当前会话和 store 时间戳。
- `resume_agent` 和 `job_agent` 默认不写 Note；需要沉淀笔记时，由 main-agent 在汇总后根据用户明确保存意图调用 note 工具。
