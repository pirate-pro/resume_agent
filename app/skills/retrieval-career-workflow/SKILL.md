---
name: retrieval-career-workflow
description: 基于召回结果执行面试准备、投递前检查、面试复盘、保存准备内容或学习安排时使用。
---
# Retrieval Career Workflow

## 召回驱动求职动作规则

目标：用户基于历史求职项目继续推进时，先召回真实项目上下文，再按明确意图回答或写入对应产品记录。

- 用户说“帮我准备之前那个岗位面试 / 今天该学什么 / 投递前检查 / 保存这次准备内容”，且没有提供产品记录 id 时，先用 `retrieval_search` 定位相关 `CareerApplication`，再用 `retrieval_context_pack` 召回求职项目、匹配报告、笔记、学习任务、短板和资料题库上下文。
- 面试准备类请求默认只基于召回结果回答，不自动创建 Note、LearningTask、SessionArtifact 或 memory；只有用户明确要求保存、加入计划、生成报告或更新项目时，才调用对应写入工具。
- 学习安排类请求如果只是问“今天该学什么”，可以直接给出建议；如果用户明确要求“加入计划 / 创建任务 / 监督我完成”，才调用 learning 工具创建或更新可执行任务。除非用户明确要求同步求职项目状态，否则不要调用 `career_application_merge`，也不要把 `learning_plan_` 或 `learning_task_` 当成 CareerApplication 的 `evidence_refs`。
- 保存准备内容、答案草稿、复盘或面试题时，先召回依据，再调用 `note_create` 或 `note_append`；Note 的 `evidence_refs` 和 `source_refs` 必须使用 NoteService 当前支持的受控引用，例如 application、fit、resume_profile、jd、career_profile、resume_version、note 或 artifact。Learning / Knowledge 来源可以在正文中说明，或通过其关联的 application、fit、note、artifact 追溯，不要传不被 NoteService 支持的引用类型。
- 投递前检查应复用召回到的 `CareerApplication`、`ResumeProfile`、`JDAnalysis` 和 `JobFitReport`；不要重新委派 `resume_agent` 或 `job_agent`，不要重新解析简历或 JD。需要把检查结果沉淀到求职项目时，使用 `career_application_merge` 更新 `summary`、`next_actions`、`risks` 或 `notes`。
- 用户表达“已投递 / 约面试 / 刚面完 / 被问到 / 收到反馈 / 挂了 / 拿到 offer”等投递或面试进展时，先召回对应 `CareerApplication`；如果用户明确要求记录、复盘或更新项目，先用 `note_create` 或 `note_append` 保存面试复盘，再用 `career_application_merge` 更新 `stage`、`summary`、`next_actions`、`risks` 或 `notes`。
- 面试复盘 Note 必须设置 `related_application_id`，`source_refs` 至少包含对应 `career_application`；如果复盘依据来自匹配报告、简历画像、JD 分析或已有笔记，也要用 NoteService 支持的引用类型补充。复盘默认 `note_type` 用 `note`，只有用户明确说这是学习总结或短板整理时才用 `learning`。
- 面试复盘同步更新求职项目时，只使用 CareerApplication 允许的阶段值，例如 `applied`、`interviewing`、`offer`、`rejected` 或 `paused`；不要把面试详情塞进不存在的结构化字段，也不要创建新的面试 store 记录。
- 不要因为面试复盘暴露短板就自动创建 LearningTask 或 WeaknessTracker；只有用户明确要求“加入计划 / 创建任务 / 监督我补 / 跟踪这个短板”时，才调用 LearningService。
- 复盘驱动准备建议规则：用户问“下一步怎么准备 / 这些问题怎么补 / 下次面试重点是什么”时，先召回 `CareerApplication`、匹配报告、复盘 Note、现有学习任务和短板，再给出可执行建议；只问下一步准备建议时默认只回答，不自动写 Note、LearningTask、WeaknessTracker、CareerApplication 或 memory。
- 基于复盘给准备建议时，要把建议拆成优先级、准备主题、练习产出和验收标准；如果已有 LearningTask 或 WeaknessTracker，优先复用并提醒用户已有任务，不重复创建同类任务。
- 用户明确要求把建议加入计划、创建任务或监督完成时，才调用 LearningService；这类转任务动作应先召回复盘依据，`LearningTask.evidence_refs` 至少包含对应 `application_id`、复盘 `note_id` 和实际依据的 `fit_id`、`learning_plan_id`、`weakness_id`、`resource_id` 或 `question_id`。
- 把复盘建议转成 LearningTask 时，不要顺手调用 `career_application_merge` 更新求职项目；除非用户同时明确要求更新项目状态。
- 召回到多个候选求职项目且无法判断用户指的是哪一个时，先让用户确认；不要根据猜测写入 Note、Learning 或 Career。
- 召回后所有写入工具的 `evidence_refs` 必须来自本次召回或当前会话真实工具结果；不要把裸自然语言结论、workspace path 或未知 id 当证据。
