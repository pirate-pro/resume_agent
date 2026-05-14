# M20 学习任务入口产品化方案

## 背景

M19 已经验证了复盘建议链路：

```text
只问准备建议 -> 只召回并回答
明确加入学习任务 -> 创建 LearningTask
```

下一步不能只做“系统推荐加入任务”。真实用户会有两类行为：

- 用户自己想到一个学习目标，主动添加任务。
- 系统根据复盘、匹配报告、短板或准备建议推荐任务，用户确认后加入。

这两类都应该进入 LearningService，但它们的来源、证据要求和 UI 引导不同。

## 产品目标

M20 第一批目标：

- 在工作台和对话结果中提供清晰的学习任务入口。
- 支持用户主动创建任务。
- 支持系统推荐后用户确认创建任务。
- 支持用户从任务继续打卡或更新状态。
- 不新增事实源，不引入日历提醒，不自动写 memory。

## 两类创建入口

### 1. 用户主动添加

用户自己发起：

```text
我要学 RAG 评估，帮我建一个任务。
这周监督我把 Celery 延迟队列补一下。
我想每天刷一道系统设计题。
```

处理规则：

- 可以直接创建 LearningTask。
- 不强制必须有关联求职项目、复盘 Note 或匹配报告。
- 如果上下文里能召回到相关 CareerApplication、Note、JobFitReport、Knowledge 或已有 LearningPlan，可以自动带 evidence_refs。
- 如果召回不到关联资产，不拒绝创建；使用当前 session 作为来源，并把任务标记为用户主动添加语义。
- 不自动创建 WeaknessTracker。
- 不自动写 Note 或 memory。

### 2. 系统推荐添加

系统先给出建议，用户再确认：

```text
把这个建议加入学习任务。
就按你说的 P0 创建任务。
把 RAG 评估和 Celery 这两项加入监督。
```

处理规则：

- 必须先召回建议来源。
- 创建 LearningTask 时应带 evidence_refs。
- evidence_refs 优先包含：
  - `application_id`
  - `note_id`
  - `fit_id`
  - `learning_plan_id`
  - `weakness_id`
  - `resource_id`
  - `question_id`
  - `artifact_id`
- 如果推荐来自刚刚的对话建议，但还没有持久化 artifact，可以引用当前 session 和已召回产品记录，不强制创建新的 Note。
- 不顺手更新 CareerApplication。
- 不保存新 Note。
- 不创建 WeaknessTracker，除非用户明确要求跟踪短板。
- 不写 memory。

## 来源语义

M20 第一批不新增 `LearningTask.origin` 字段，先用轻量约定表达来源：

```text
用户主动添加 -> progress_notes 里保留“来源：用户主动添加”
系统推荐添加 -> progress_notes 里保留“来源：系统推荐”
复盘转入     -> progress_notes 里保留“来源：面试复盘建议”
匹配短板转入 -> progress_notes 里保留“来源：岗位匹配短板”
```

同时通过 evidence_refs 保证可追溯性。

后续如果 UI 需要筛选或统计来源，再考虑给 LearningTask 增加受控字段：

```text
origin: manual | recommended | review_advice | fit_gap
```

第一批不做迁移。

## UI 结构

### 1. 工作台学习任务区

组件：

```text
LearningTaskPanel
  -> LearningTaskToolbar
  -> LearningTaskQuickCreate
  -> LearningTaskSuggestionStrip
  -> LearningTaskBoard
  -> LearningTaskCard
  -> LearningTaskDetailSheet
  -> LearningCheckinComposer
```

组件职责：

- `LearningTaskPanel`：承载当前项目或全局学习任务概览。
- `LearningTaskToolbar`：提供“新建任务”“只看当前项目”“待办 / 进行中 / 已完成”筛选。
- `LearningTaskQuickCreate`：用户主动添加任务，支持标题、目标、预计时间、优先级。
- `LearningTaskSuggestionStrip`：展示系统可推荐任务，例如“来自复盘”“来自匹配短板”。
- `LearningTaskBoard`：按状态分组展示任务。
- `LearningTaskCard`：显示任务标题、来源标签、优先级、预计时间、关联资产和下一步动作。
- `LearningTaskDetailSheet`：查看任务详情、成功标准、证据来源、关联笔记/报告。
- `LearningCheckinComposer`：记录今天完成了什么、卡点、信心和下一步。

### 2. 对话结果区

当 Assistant 输出准备建议时，建议底部出现克制的动作栏：

```text
[加入学习任务] [查看相关任务] [稍后再说]
```

交互规则：

- 用户点击“加入学习任务”后，不直接无提示创建一堆任务。
- 如果建议里有多个主题，先展示轻量确认面板，让用户选择 1 到 3 个任务。
- 默认只选最高优先级任务。
- 创建成功后显示任务卡片，并提供“查看任务”“今天打卡”。

### 3. 输入区快捷入口

当用户在工作台或对话中已有求职上下文时，输入区可以提供轻量建议：

```text
新建学习任务
把建议加入任务
记录今日进度
```

这些入口只生成意图，不绕过聊天执行。最终仍由 Agent 调用 learning 工具，保证审计和进度可见。

## Agent 契约

### 用户主动添加任务

当用户明确要求创建学习任务，且不是来自某条具体系统建议时：

1. 可先用 retrieval 召回相关上下文，但不要因为召回为空而拒绝创建。
2. 调用 `learning_task_create`。
3. `evidence_refs` 至少包含当前 session ref；如果召回到相关记录，再加入真实产品记录 id。
4. `progress_notes` 写明“来源：用户主动添加”。
5. 不自动调用 `career_application_merge`、`note_create`、`learning_weakness_create` 或 `memory_write`。

### 系统推荐转任务

当用户明确把系统建议加入任务时：

1. 必须先召回建议来源，或者复用本轮已经召回的上下文。
2. 调用 `learning_task_create`。
3. `evidence_refs` 应包含推荐依据。
4. `progress_notes` 写明推荐来源，例如“来源：面试复盘建议”或“来源：岗位匹配短板”。
5. 不顺手更新 CareerApplication。
6. 不自动保存 Note。
7. 不自动创建 WeaknessTracker。
8. 不写 memory。

### 打卡与状态更新

当用户说“完成了 / 学了一半 / 卡住了 / 今天学了 40 分钟”：

1. 先定位相关 LearningTask。
2. 调用 `learning_checkin_create` 记录进度。
3. 如果用户明确表达状态变化，再调用 `learning_task_update_state`。
4. 不自动写 Note 或 memory。

## 后端范围

M20 第一批后端不新增模型字段。

可复用现有能力：

- `learning_task_create`
- `learning_task_list`
- `learning_task_get`
- `learning_task_update_state`
- `learning_checkin_create`
- `retrieval_search`
- `retrieval_context_pack`

第一批不做：

- `LearningTask.origin` 字段。
- 日历提醒。
- push/邮件通知。
- 任务重复检测算法。
- 自动拆解大型学习计划。
- 学习任务自动写入 memory。

## 前端范围

第一批建议先做：

```text
1. 工作台学习任务区增加“新建任务”入口。
2. 对话建议结果底部增加“加入学习任务”动作。
3. 任务卡片显示来源标签：用户添加 / 系统推荐 / 复盘转入 / 匹配短板。
4. 任务详情支持“记录今日进度”。
```

如果后端暂时没有 origin 字段，来源标签第一批从 `progress_notes` 和 evidence_refs 推断。

## 验收标准

- 用户可以主动创建一个无项目关联的学习任务。
- 用户可以基于复盘建议创建 LearningTask。
- 系统推荐转任务必须带 evidence_refs。
- 用户主动添加任务即使没有 evidence_refs 也能创建，但需要保留 session ref 或来源说明。
- 创建任务不会自动写 Note。
- 创建任务不会自动更新 CareerApplication。
- 创建任务不会自动创建 WeaknessTracker。
- 创建任务不会写 memory。
- 用户可以对任务打卡，并按需更新任务状态。
- 工作台能区分任务来源，至少通过标签展示。

## 推荐实施顺序

```text
1. 更新 Agent 契约。
2. 增加确定性 runtime 测试：主动添加任务。
3. 增加确定性 runtime 测试：系统推荐转任务。
4. 增加确定性 runtime 测试：打卡与状态更新。
5. 前端设计学习任务入口和任务详情交互。
6. 前端接入工作台动作入口。
7. 低批次 smoke 验证主动添加和推荐转任务。
```

## 后续方向

- 如果来源标签成为高频筛选条件，再为 LearningTask 增加 `origin` 字段。
- 如果用户开始长期使用学习监督，再考虑日历和提醒系统。
- 如果用户希望系统自动拆计划，再引入任务拆解规则。
- 如果学习过程需要长期建模，再单独设计 memory / RAG 的边界，不在 M20 第一批处理。
