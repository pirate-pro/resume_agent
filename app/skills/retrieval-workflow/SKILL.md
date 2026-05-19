---
name: retrieval-workflow
description: 用户引用历史、已有资料、保存过的记录、当前画像或计划时使用，只读召回产品上下文。
---
# Retrieval Workflow

目标：用只读召回替代全量上下文注入，让 agent 在需要历史资料时先取相关片段，再决定是否写入产品记录。

- RetrievalService 用于只读召回 Career、Note、Knowledge、Learning 和当前 SessionArtifact 中的产品上下文；它不是 memory，也不是新的产品事实源。
- 用户提到“之前 / 上次 / 最近 / 保存过的 / 投过的 / 我的计划”，或没有提供 ID 但提到公司、岗位、技能、项目、学习目标时，优先调用 `retrieval_context_pack` 获取可追溯上下文，再回答或决定是否创建新记录。
- 只需要轻量找候选记录时，可以调用 `retrieval_search`；需要基于历史资料生成准备建议、复盘总结、学习安排或求职项目判断时，优先调用 `retrieval_context_pack`。
- 用户刚上传文件并明确要求分析当前文件时，优先使用当前 session artifact 和对应专业工具；不要为了当前上传文件先做全局召回。
- Retrieval 工具只读，不会也不应该触发 memory 写入、Note 写入、Learning 写入或 Career 写入；只有用户明确要求保存、更新或记住时，才按对应服务规则另行处理。
- Retrieval 结果中的 `source_type`、`source_id`、`artifact_id` 和 `match_reason` 用于追溯和调试；面向用户回答时不要把裸 ID 当成主要体验，但可以用“来自匹配报告 / 笔记 / 学习任务 / 资料”等自然描述说明依据。
- 不要向 retrieval 工具传任何路径、workspace 文件路径、`session_id`、`source_session_id`、`created_at`、`updated_at` 或 `status`；工具会使用当前 RunContext 的 session。
- `resume_agent` 和 `job_agent` 默认不调用全局 RetrievalService；需要历史资料时，由 main-agent 先召回并把明确的 artifact id 或产品记录 id 传给 child-agent。
