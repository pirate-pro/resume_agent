# 求职 Agent M10 LearningService 学习计划层方案

日期：2026-05-12

## 1. M10 一句话目标

建立 `LearningService`，把求职项目、匹配报告、个人笔记和外部知识库中的能力差距转成可追踪、可调整、可复盘的学习计划。

M10 不做 RAG，不做 MCP，不做前端提醒系统，不接日历，不自动写 memory，不做开放式聊天写入。只给 `agent_main` 开放受控 Learning 工具，先把学习计划和进度的事实源做稳。

```text
CareerApplication / JobFitReport / Note / Knowledge
  -> LearningService
  -> LearningPlan / LearningTask / ProgressCheckin / WeaknessTracker / ReviewSchedule
  -> 后续 Agent 监督 / 前端日程 / RAG 召回可复用
```

## 2. 为什么现在做 LearningService

M7 已经有求职项目，能把一个目标岗位串起来。

M8 已经有 NoteService，能保存用户自己的复盘、学习理解和面试问题。

M9 已经有 KnowledgeService 底座，能承载外部资料、题库、公司画像和能力要求。M9 现在不通过聊天 Agent 写入，但后续可以作为外部知识来源。

当前还缺的是“持续执行层”：

- 用户知道自己有短板，但不知道今天该做什么。
- 匹配报告给出风险，但没有持续跟踪风险是否被补齐。
- 面试复盘暴露问题，但没有变成下一轮准备任务。
- 学生或转行用户需要长期计划，而不是一次性建议。

LearningService 的价值是把“建议”变成“计划、任务、进度、复盘和调整”。

## 3. 核心边界

### 3.1 LearningService 不是 CareerService

`CareerService` 负责求职项目和求职资产。

`LearningService` 负责学习计划、任务、进度和短板跟踪。

规则：

- `CareerApplication` 提供目标岗位、优先级、风险和下一步动作。
- `JobFitReport` 提供能力差距和面试准备重点。
- `LearningPlan` 可以关联求职项目，但不替代求职项目状态。
- 投递状态、面试状态仍由 CareerService 维护。

### 3.2 LearningService 不是 NoteService

`NoteService` 保存用户自己的笔记、复盘和学习理解。

`LearningService` 保存计划和执行状态。

规则：

- 用户写学习笔记、面试复盘、回答草稿，进入 NoteService。
- 用户的笔记可以作为 LearningTask 的证据或产出引用。
- LearningTask 不复制 Note 正文，只保存 note id 或 evidence ref。
- LearningService 不把计划内容自动写成笔记。

### 3.3 LearningService 不是 KnowledgeService

`KnowledgeService` 保存外部资料、题库、公司画像和能力要求。

`LearningService` 消费这些资料，但不替代资料库。

规则：

- 外部题目、资料、公司要求仍属于 KnowledgeService。
- 学习任务可以引用 `resource_id`、`question_id`、`skill_req_id`。
- M10 不做 Knowledge 检索，也不做题库导入。
- M10 不要求 Knowledge 记录真实存在，只做 id 格式校验，避免跨 store 耦合。

### 3.4 LearningService 不是 MemoryService

Learning 记录是用户可见、可管理的产品资产。

Memory 是运行时上下文材料。

规则：

- 创建学习计划、完成任务、提交打卡不等于 `memory_write`。
- LearningService 不主动写 memory。
- 用户明确表达长期偏好、稳定目标、长期事实时，仍按现有 memory 规则处理。
- 后续可以通过 RAG 或受控摘要把学习状态注入上下文，M10 不做。

### 3.5 LearningService 不是提醒系统

M10 只保存计划和时间字段，不做推送、日历同步、后台提醒 worker。

规则：

- 可以有 `due_date`、`planned_start_date`、`review_at`。
- 不接 Google Calendar。
- 不做通知推送。
- 不做自动定时提醒。
- 后续如果做提醒，基于 LearningService 的数据再单独实现。

## 4. M10 范围

### 4.1 做

- `app/learning/` 领域层。
- LearningPlan / LearningTask / ProgressCheckin / WeaknessTracker / ReviewSchedule 模型。
- 文件型 JSON store。
- ID 前缀、status、来源字段、时间戳校验。
- `evidence_refs` 字符串格式校验，不做跨 store 存在性校验。
- 原子写入。
- get / list / archive。
- create / update。
- task 状态流转。
- checkin 追加。
- weakness 更新。
- 损坏 JSON 稳定失败。
- API 和工具的契约设计。

### 4.2 不做

- RAG。
- MCP。
- 前端计划页。
- 日历同步。
- 通知推送。
- 自动提醒 worker。
- 聊天 Agent 写工具。
- 自动写 memory。
- 自动生成完整学习计划。
- 跨 store 强存在性校验。
- 外部资料抓取。
- 面试模拟评分。

## 5. 产品对象

### 5.1 LearningPlan

一个围绕目标岗位、目标能力或一段时间周期的学习计划。

建议字段：

```text
learning_plan_id
status
source_session_id
source_artifact_id
evidence_refs
created_at
updated_at

title
description
plan_type
target_application_id
target_role
target_company
start_date
end_date
priority
goals
focus_skill_tags
task_ids
weakness_ids
review_schedule_ids
progress_summary
```

字段说明：

- `learning_plan_id`：`learning_plan_` 前缀。
- `status`：`active | archived`。
- `plan_type`：`career_gap | interview_prep | skill_build | review | custom`。
- `target_application_id`：关联求职项目，可为空。
- `target_role` / `target_company`：目标方向。
- `start_date` / `end_date`：计划时间范围，M10 用日期字符串或 date。
- `priority`：`high | medium | low`。
- `goals`：用户可见目标列表。
- `focus_skill_tags`：重点能力标签。
- `task_ids`：关联任务 id，不做存在性校验。
- `weakness_ids`：关联短板 id，不做存在性校验。
- `review_schedule_ids`：关联复习计划 id，不做存在性校验。
- `progress_summary`：当前进度摘要。

### 5.2 LearningTask

具体学习任务，是用户每天或每周执行的最小产品对象。

建议字段：

```text
learning_task_id
status
source_session_id
source_artifact_id
evidence_refs
created_at
updated_at

learning_plan_id
title
description
task_type
priority
state
skill_tags
estimated_minutes
planned_start_date
due_date
completed_at
resource_refs
question_refs
note_refs
output_artifact_id
success_criteria
progress_notes
```

字段说明：

- `learning_task_id`：`learning_task_` 前缀。
- `task_type`：`read_resource | practice_question | write_answer | revise_resume | mock_interview | review_note | custom`。
- `state`：`todo | doing | blocked | done | skipped`。
- `learning_plan_id`：所属计划，可为空。
- `skill_tags`：任务对应能力。
- `estimated_minutes`：预计耗时，整数分钟。
- `planned_start_date` / `due_date`：计划时间。
- `completed_at`：完成时间，由 store 或服务更新。
- `resource_refs`：关联 `resource_`、`skill_req_` 等资料引用。
- `question_refs`：关联 `question_`。
- `note_refs`：关联 `note_`，用于任务产出或复盘。
- `output_artifact_id`：如果任务产出文件，指向 artifact。
- `success_criteria`：完成标准。
- `progress_notes`：轻量执行备注，不替代 Note 正文。

### 5.3 ProgressCheckin

一次学习打卡或进度记录。

建议字段：

```text
checkin_id
status
source_session_id
source_artifact_id
evidence_refs
created_at
updated_at

learning_plan_id
learning_task_id
checkin_date
minutes_spent
progress_state
summary
blockers
confidence
next_action
note_refs
```

字段说明：

- `checkin_id`：`checkin_` 前缀。
- `progress_state`：`not_started | in_progress | completed | blocked | skipped`。
- `minutes_spent`：本次投入时间。
- `summary`：打卡摘要。
- `blockers`：遇到的问题。
- `confidence`：`low | medium | high`。
- `next_action`：下一步。
- `note_refs`：关联笔记，不复制正文。

### 5.4 WeaknessTracker

持续跟踪的能力短板。

建议字段：

```text
weakness_id
status
source_session_id
source_artifact_id
evidence_refs
created_at
updated_at

title
description
weakness_type
severity
state
skill_tags
target_application_ids
source_report_ids
related_task_ids
related_note_ids
last_observed_at
resolved_at
resolution_summary
```

字段说明：

- `weakness_id`：`weakness_` 前缀。
- `weakness_type`：`skill_gap | project_gap | interview_gap | resume_gap | habit | confidence | other`。
- `severity`：`low | medium | high`。
- `state`：`open | improving | resolved | ignored`。
- `source_report_ids`：可以引用 `fit_`、`jd_`、`artifact_` 等。
- `related_task_ids`：关联学习任务。
- `last_observed_at`：最近一次暴露时间。
- `resolved_at`：解决时间。
- `resolution_summary`：如何解决的摘要。

### 5.5 ReviewSchedule

复习和回看安排。

建议字段：

```text
review_schedule_id
status
source_session_id
source_artifact_id
evidence_refs
created_at
updated_at

learning_plan_id
learning_task_id
weakness_id
title
review_type
review_at
interval_days
state
resource_refs
question_refs
note_refs
last_reviewed_at
next_review_at
summary
```

字段说明：

- `review_schedule_id`：`review_` 前缀。
- `review_type`：`spaced_repetition | interview_rehearsal | resume_review | project_drill | custom`。
- `review_at`：当前计划复习时间。
- `interval_days`：复习间隔。
- `state`：`scheduled | done | skipped | cancelled`。
- `resource_refs` / `question_refs` / `note_refs`：引用资料、题目和笔记。
- `last_reviewed_at` / `next_review_at`：后续提醒系统可使用，M10 不自动调度。

## 6. 来源与证据规则

### 6.1 计划来源

Learning 记录可以来自：

- `CareerApplication`：目标岗位项目。
- `JobFitReport`：匹配报告中的短板、风险和面试准备重点。
- `ResumeProfile` / `CareerProfile`：当前画像中的技能和经历。
- `Note`：用户自己的面试复盘、学习记录和回答草稿。
- `Knowledge`：外部能力要求、资料和题目。
- `SessionArtifact`：生成的计划报告或用户上传资料。

M10 不做跨 store 强存在性校验，只保存格式正确的 id 引用。

### 6.2 evidence_refs

允许前缀建议：

```text
artifact_
application_
resume_profile_
career_profile_
jd_
fit_
resume_version_
note_
resource_
experience_
question_
company_
skill_req_
learning_plan_
learning_task_
checkin_
weakness_
review_
sess_
```

规则：

- 只校验格式，不校验引用对象是否真实存在。
- 不允许空字符串。
- 不允许任意文件路径。
- API 和工具只接受受控 id，不接受 workspace path。

### 6.3 时间戳与日期

时间戳由 store 统一维护。

规则：

- 新建时由 store 设置 `created_at` 和 `updated_at`。
- 更新、归档、状态流转时只更新 `updated_at`。
- 使用 Asia/Shanghai 时区。
- `completed_at`、`last_observed_at`、`resolved_at`、`review_at` 等业务时间必须校验格式。

## 7. 状态规则

### 7.1 LearningTask.state

允许状态：

```text
todo
doing
blocked
done
skipped
```

建议流转：

```text
todo -> doing -> done
todo -> blocked
doing -> blocked
blocked -> doing
todo / doing / blocked -> skipped
```

M10 store 可以先只校验枚举，不强制状态机。后续工具层再根据业务需要限制流转。

### 7.2 WeaknessTracker.state

允许状态：

```text
open
improving
resolved
ignored
```

M10 不自动判定 resolved。用户确认、任务完成或后续 agent 评估可以触发更新。

### 7.3 ReviewSchedule.state

允许状态：

```text
scheduled
done
skipped
cancelled
```

M10 不自动创建下一次复习，只保存 `next_review_at` 字段。

## 8. 存储设计

建议目录：

```text
data/learning/
  plans/
    learning_plan_xxx.json
  tasks/
    learning_task_xxx.json
  checkins/
    checkin_xxx.json
  weaknesses/
    weakness_xxx.json
  reviews/
    review_xxx.json
```

存储规则：

- 每条记录一个 JSON 文件。
- 原子写入。
- 严格反序列化，坏 schema 直接失败。
- 损坏 JSON 抛稳定的 storage error。
- list 默认只返回 `active`，可选包含 `archived`。
- 不写 Markdown 快照。
- 不创建向量索引。

## 9. API 契约草案

M10 第一批先不实现 API，但契约按以下方向设计。

公共读取接口：

```text
GET /api/learning/plans
GET /api/learning/plans/{learning_plan_id}
GET /api/learning/tasks
GET /api/learning/tasks/{learning_task_id}
GET /api/learning/checkins
GET /api/learning/weaknesses
GET /api/learning/reviews
```

后台 / Agent 受控写接口后续再定：

```text
POST  /api/learning-admin/plans
PATCH /api/learning-admin/plans/{learning_plan_id}
POST  /api/learning-admin/plans/{learning_plan_id}/archive

POST  /api/learning-admin/tasks
PATCH /api/learning-admin/tasks/{learning_task_id}
POST  /api/learning-admin/tasks/{learning_task_id}/archive
POST  /api/learning-admin/tasks/{learning_task_id}/complete

POST  /api/learning-admin/checkins
POST  /api/learning-admin/weaknesses
PATCH /api/learning-admin/weaknesses/{weakness_id}
POST  /api/learning-admin/reviews
PATCH /api/learning-admin/reviews/{review_schedule_id}
```

M10-1 不做 API，先做 store。

## 10. 工具与 Agent 契约

M10-1 不做工具。

后续如果接工具，建议先只给 `agent_main` 开放受控写入工具：

```text
learning_plan_create
learning_plan_get
learning_task_create
learning_task_update_state
learning_checkin_create
learning_weakness_update
```

Agent 边界：

- 用户要求制定学习计划时，main agent 可以创建 LearningPlan 和 LearningTask。
- 用户记录学习理解、面试复盘时，写 NoteService，不直接塞进 LearningTask。
- 用户完成任务或打卡时，写 ProgressCheckin，并可更新 LearningTask.state。
- 不把 Learning 记录自动写 memory。
- 不让 child-agent 默认写 LearningService。

M10-1 暂不实现这些工具，避免在模型没稳定前放开写入口。

## 11. 开发批次

### M10-1：领域模型和 store

文件：

```text
app/learning/models.py
app/learning/store.py
tests/test_learning_store.py
```

状态：已完成。

验收：

- 五类记录模型。
- ID 前缀校验。
- status 校验。
- state / type / priority 枚举校验。
- 来源字段校验。
- evidence_refs 格式校验。
- store 统一维护 Asia/Shanghai 时间戳。
- 原子写入 JSON。
- get / list / archive。
- create / update。
- task 状态更新。
- checkin 追加。
- weakness 更新。
- 损坏 JSON 稳定失败。
- 反序列化严格失败，不做宽松类型转换。

已完成内容：

- `LearningPlan / LearningTask / ProgressCheckin / WeaknessTracker / ReviewSchedule` 五类模型。
- `LearningStore` 文件型 JSON store。
- store 统一维护 Asia/Shanghai 时间戳，支持可注入 clock。
- 五类记录的 get / list / update / archive。
- `LearningTask` 状态更新，完成时由 store 设置 `completed_at`。
- `ProgressCheckin` 追加入口。
- 严格反序列化，坏 schema 和损坏 JSON 统一抛 `StorageError`。
- `tests/test_learning_store.py` 覆盖模型校验、时间戳、归档、过滤、损坏 JSON 和跨 store 不校验存在性。

### M10-2：API

文件：

```text
app/schemas/learning.py
app/api/learning.py
tests/test_learning_api.py
```

状态：已完成。

验收：

- 公共 `/api/learning` 只读。
- 后台 `/api/learning-admin` 承担创建、更新、归档和状态流转。
- API 不暴露路径。
- API 不做跨 store 强存在性校验。

已完成内容：

- `LearningPlan / LearningTask / ProgressCheckin / WeaknessTracker / ReviewSchedule` 五类记录的 HTTP view、create request 和 update request。
- 公共 `/api/learning` 只读列表和详情接口。
- 后台 `/api/learning-admin` 创建、更新、归档接口。
- `LearningTask` 状态更新接口和完成接口。
- app 主路由和依赖注入接入 `LearningStore`。
- `tests/test_learning_api.py` 覆盖创建、读取、过滤、归档、状态流转、公共接口只读和路径不泄漏。

### M10-3：工具和 agent 契约

文件：

```text
app/tools/builtin_tools/learning.py
app/config/agent_capabilities.json
app/agents/default/AGENT.md
tests/test_learning_tools.py
tests/test_learning_agent_flow.py
```

状态：已完成。

验收：

- main agent 可以按用户明确要求创建学习计划。
- main agent 可以记录打卡和更新任务状态。
- child-agent 默认无 Learning 写权限。
- 个人学习笔记仍走 NoteService。
- 创建 Learning 不写 memory。

已完成内容：

- `learning_plan_create / learning_plan_get / learning_plan_list`。
- `learning_task_create / learning_task_get / learning_task_list / learning_task_update_state`。
- `learning_checkin_create`。
- `learning_weakness_create / learning_weakness_update`。
- 只给 `agent_main` 开放 Learning 写工具；`resume_agent` 和 `job_agent` 默认无 Learning 写权限。
- AGENT 契约明确 Learning、Note、Knowledge、Memory 的边界。
- 工具层拒绝路径、workspace path、`source_session_id`、`created_at`、`updated_at`、`status`。
- `source_artifact_id` 只能引用当前会话 artifact。
- 确定性 runtime 测试覆盖显式学习计划请求写 Learning、不写 memory。

### M10-4：低成本真实链路验证

状态：已完成。

验收：

- 基于一个 CareerApplication + JobFitReport 创建学习计划。
- 创建 3 到 5 个 LearningTask。
- 用户完成一个任务后创建 ProgressCheckin。
- 一个 WeaknessTracker 能从 open 更新到 improving。
- smoke 批次保持低，避免 token 消耗失控。

已完成内容：

- 新增 `tests/test_learning_career_chain.py`。
- 使用确定性 runtime 串起 `CareerApplication`、`JobFitReport`、`LearningPlan`、`LearningTask`、`ProgressCheckin` 和 `WeaknessTracker`。
- 从一个求职项目和匹配报告创建 1 个学习计划、4 个学习任务。
- 模拟用户完成一个 RAG 任务后写入进度打卡，并把任务状态更新为 `done`。
- 将 `WeaknessTracker` 从 `open` 更新为 `improving`。
- 验证 Learning 链路不写 memory，不生成 Markdown 快照，不依赖真实模型 smoke。

## 12. 风险与控制

### 12.1 计划过度复杂

风险：一开始就做排期算法、提醒、复习曲线，会拖慢主线。

控制：

- M10-1 只做事实源。
- M10-2 只做 API。
- M10-3 再接工具。
- 复习算法、提醒系统和日历同步后置。

### 12.2 和 Note 混淆

风险：任务备注、学习笔记、复盘混在 LearningTask 里，最后 NoteService 失去意义。

控制：

- LearningTask 只放短备注和状态。
- 长内容、回答草稿、复盘正文进入 NoteService。
- LearningTask 用 note id 引用笔记。

### 12.3 和 Memory 混淆

风险：学习状态被当成长记忆写入，导致 memory 变成隐藏的学习数据库。

控制：

- LearningService 不主动写 memory。
- 后续上下文使用优先走 RAG 或受控摘要。
- 用户明确要求“记住长期偏好”时才走 memory。

### 12.4 和 Knowledge 混淆

风险：学习计划里直接复制资料和题目，造成双事实源。

控制：

- 外部资料和题目仍在 KnowledgeService。
- LearningTask 只保存引用。
- 用户个人答案和复盘仍在 NoteService。

## 13. 当前建议

M10-1、M10-2、M10-3、M10-4 和 M10 收口已完成。LearningService 已具备后端事实源、API、main-agent 受控工具、低成本主链路验证和基础测试收口。

M10 收口已完成：

```text
修正 agent_task_progress 事件测试预期
确认子 agent 运行进度会投影到 orchestration events
保留前端进度面板依赖的 progress 事件
不回退运行逻辑
```

下一步建议进入 M11 前先落 RAG / MCP 召回边界文档：

```text
明确召回来源：Career、Note、Knowledge、Learning、SessionArtifact
明确 RAG 是召回能力，不是产品资产事实源
明确不自动写 memory，不复制资料正文
```

暂时不要碰：

```text
前端
复习调度
RAG
MCP
memory 自动写入
日历同步
通知提醒
排期算法
跨 store 存在性校验
```
