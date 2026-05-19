---
name: learning-workflow
description: 用户要求制定学习计划、创建或推荐学习任务、记录打卡进度、跟踪能力短板时使用。
---
# Learning Workflow

目标：把岗位差距、面试复盘和用户主动学习目标转成可追踪任务，同时避免自动写入 memory 或笔记。

- LearningService 用于用户可见、可追踪的学习计划、任务、打卡和能力短板；它不是 memory、不是 Note，也不是 Knowledge。
- 用户明确要求“制定学习计划 / 面试准备计划 / 本周学习安排 / 监督我完成任务 / 记录学习进度”时，才调用 learning 工具。
- 学习任务有两类入口：用户主动添加和系统推荐添加。用户主动添加不强制依赖求职项目、复盘 Note 或匹配报告；系统推荐添加必须带实际依据的 `evidence_refs`。
- 用户主动添加学习任务时，可以先召回相关上下文；如果召回为空，也可以创建任务。用户主动添加默认创建一条独立 `LearningTask`，不要套用系统推荐任务的去重规则；只有用户明确要求合并、去重或继续已有任务时，才复用已有任务。`evidence_refs` 至少包含当前原始会话 id，例如 `sess_...`，不要写成 `session:sess_...` 或其他 typed ref；`progress_notes` 写明“来源：用户主动添加”。新建任务阶段只创建待办任务，不要顺手调用 `learning_checkin_create` 或 `learning_task_update_state`。
- 系统推荐添加学习任务时，必须先召回或复用本轮已经召回的上下文，`progress_notes` 写明来源，例如“来源：面试复盘建议”或“来源：岗位匹配短板”。
- 简历诊断、JD 分析、匹配报告和投递前检查默认仍进入 CareerService 与 artifact；不要因为报告里有建议就自动创建 LearningPlan。
- 外部资料、面经、题库和公司要求仍属于 KnowledgeService；LearningTask 只保存 `resource_`、`question_`、`skill_req_` 等受控引用，不复制资料正文。
- 用户写学习笔记、面试复盘、答案草稿或长篇理解时，进入 NoteService；LearningTask 只保存短备注、状态和 `note_` 引用。
- 创建学习计划时，优先先读取当前 `CareerApplication`、`JobFitReport`、`CareerProfile`、Note 或已知 Knowledge id，再用 `learning_plan_create` 创建计划，并用 `learning_task_create` 创建 3 到 5 个可执行任务。
- 学习计划的 `evidence_refs` 至少包含实际依据的 `application_id`、`fit_id`、`resume_profile_id`、`career_profile_id`、`jd_analysis_id`、`note_id`、`resource_id` 或 `artifact_id`；不要传 workspace path。
- 用户汇报“完成了 / 做到一半 / 卡住了 / 今天学了多久 / 信心如何”时，先定位相关 LearningTask，再调用 `learning_checkin_create` 记录打卡；如果对应任务状态变化，再调用 `learning_task_update_state`。
- 打卡和任务状态更新不自动写 Note 或 memory；只有用户明确要求整理成长笔记时，才另行调用 NoteService。
- 用户明确说某个短板改善、解决、暂时忽略或暴露出新问题时，调用 `learning_weakness_create` 或 `learning_weakness_update`；不要把短板状态写入 memory。
- Learning 工具不会也不应该触发 memory 写入；只有用户表达长期偏好、稳定目标或长期事实时，才按 memory 规则判断。
- 不要向 learning 工具传任何路径、workspace 文件路径、`source_session_id`、`created_at`、`updated_at` 或 `status`；learning 工具会使用当前会话和 store 时间戳。
- `resume_agent` 和 `job_agent` 默认不写 LearningService；学习计划、打卡和短板跟踪由 main-agent 在汇总后根据用户明确意图写入。
