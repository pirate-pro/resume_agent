# M20 学习任务前端入口设计

## 目标

M20 第二批要把学习任务从“Agent 可以创建”推进到“用户自然会用”：

- 用户可以自己创建学习任务。
- 用户可以把系统推荐的建议加入学习任务。
- 用户可以对学习任务记录今日进度。
- 所有执行仍回到聊天链路，由 Agent 调用工具，前端不直接写 store。
- 前端需要看起来像一个专业工作台，而不是把所有记录堆在侧边栏里。

## 当前问题

现有工作台已经有学习计划、学习任务、短板跟踪和复盘区域，但入口还偏弱：

- `LearningActionStrip` 只有“生成计划 / 同步进展”，没有明确区分“自己添加”和“推荐添加”。
- `LearningTaskBoard` 能展示任务，但缺少创建入口、来源提示和打卡入口。
- `LearningTaskCard` 点击后只看详情，不承接“今天做了什么 / 是否完成 / 卡在哪里”。
- 空状态文案只提示回到聊天生成计划，缺少直接可执行动作。
- 对话结果里的“加入学习任务”还没有形成统一的确认和落地视图。

## 设计原则

- 任务是用户自己的长期行动，不只来自系统推荐。
- 推荐任务必须让用户确认，不默认批量创建。
- 工作台负责组织和入口，执行过程仍由聊天展示。
- 来源只做轻量提示，不引入复杂筛选或过多标签。
- 调试 ID 不作为主视觉信息，只在详情或复制动作里出现。

## 总体布局

学习任务入口保留在工作台“学习计划”页内，不新增一级页面。

```text
学习计划页
  -> LearningOverviewHeader
  -> LearningProjectSelector
  -> LearningMetricStrip
  -> LearningTaskEntryPanel
       -> LearningTaskPrimaryActions
       -> LearningTaskSuggestionStrip
  -> LearningPlanSection
  -> LearningTaskPanel
       -> LearningTaskToolbar
       -> LearningTaskBoard
       -> LearningTaskCard
  -> LearningWeaknessSection
  -> LearningReviewSection
```

第一批前端开发只调整学习任务相关区域，不重做整页布局。

## 组件设计

### 1. `LearningTaskEntryPanel`

位置：`LearningMetricStrip` 下方，替代现有 `LearningActionStrip`。

任务：

- 承载学习任务的主要入口。
- 明确给出两个创建方向：自己添加、基于当前项目推荐。
- 提供“记录今日进度”的快捷入口。

视觉：

- 轻量横向面板，不做大卡片。
- 左侧是说明文案，右侧是 2 到 3 个动作按钮。
- 文案控制在一行到两行。

建议结构：

```text
今天要推进什么？
基于当前岗位、复盘和短板管理学习任务。

[新建任务] [从项目推荐] [记录进度]
```

### 2. `LearningTaskPrimaryActions`

动作：

- `新建任务`：用户主动添加任务。
- `从项目推荐`：让 Agent 基于当前项目、匹配报告、复盘和短板生成建议。
- `记录进度`：对已有任务打卡或更新状态。

交互：

- 点击后先回到聊天区域，并发送结构化意图。
- 前端不直接调用 `learning_task_create`。
- 如果正在运行任务，按钮进入禁用状态并提示“当前任务正在执行”。

### 3. `LearningTaskCreateSheet`

用途：用户主动添加任务前的轻量确认面板。

字段：

- 任务标题，必填。
- 任务说明，可选。
- 优先级，默认常规。
- 预计耗时，可选。
- 关联项目，可选，默认当前项目。

提交行为：

- 生成一条聊天意图，让 Agent 创建 LearningTask。
- 如果没有当前项目，也允许创建。
- 期望 Agent 写入 `progress_notes: 来源：用户主动添加`。

首版可以先不做复杂表单校验，只保证标题非空。

### 4. `LearningTaskSuggestionStrip`

用途：展示系统推荐入口，不展示一堆未确认任务。

来源：

- 当前项目存在匹配报告。
- 当前项目存在未解决短板。
- 当前项目存在面试复盘。
- 最近一次 Assistant 回复给出了准备建议。

展示：

```text
可生成学习建议
[基于匹配短板] [基于面试复盘] [基于当前项目]
```

交互：

- 点击后发送聊天意图。
- Agent 先召回上下文，再创建或返回建议。
- 如果建议包含多个任务，Assistant 回复中展示确认动作，不由前端静默创建。

### 5. `LearningTaskPanel`

用途：替代单纯的 `LearningTaskBoard` 容器。

结构：

```text
学习任务
待推进 2 · 进行中 1 · 已完成 4

[全部] [待推进] [进行中] [已完成]

任务看板
```

任务：

- 展示任务总数和状态分布。
- 提供轻量状态筛选。
- 保留原有三列看板，但窄屏下继续纵向排列。

### 6. `LearningTaskCard`

需要强化，但不要变重。

主信息：

- 标题。
- 来源标签：用户添加 / 推荐加入 / 复盘建议 / 匹配短板。
- 状态：待推进 / 进行中 / 受阻 / 已完成。
- 优先级和预计耗时。

次信息：

- 下一步或成功标准，最多两条。
- 技能标签最多三个。

底部动作：

- `详情`
- `记录进度`

点击卡片主体打开详情；点击进度按钮进入打卡面板。

### 7. `LearningTaskDetailSheet`

用途：查看任务和继续行动。

内容：

- 标题、状态、优先级、来源。
- 任务说明。
- 成功标准。
- 技能标签。
- 关联项目、笔记、报告或资料。
- 进展记录。

底部动作：

- `记录今日进度`
- `标记进行中`
- `标记完成`

状态变化仍通过聊天意图执行，不直接写 store。

### 8. `LearningCheckinComposer`

用途：记录今日进度。

字段：

- 今天完成了什么。
- 当前卡点。
- 下一步。
- 是否需要更新状态。

提交行为：

- 生成聊天意图。
- Agent 先定位 LearningTask，再调用 `learning_checkin_create`。
- 只有用户明确选择状态变化时，才调用 `learning_task_update_state`。

## 对话结果动作

当 Assistant 给出学习建议、复盘建议或岗位准备建议时，消息底部出现克制动作栏：

```text
[加入学习任务] [查看相关任务] [记录今日进度]
```

规则：

- “加入学习任务”打开确认面板。
- 多条建议默认只勾选最高优先级的一条。
- 用户确认后，再回到聊天执行。
- 不把 Assistant 文本里的每个 bullet 都自动转任务。

## 来源标签推断

M20 第一批不新增 `LearningTask.origin` 字段，前端用现有字段推断：

```text
progress_notes 包含“来源：用户主动添加” -> 用户添加
progress_notes 包含“来源：系统推荐”     -> 推荐加入
progress_notes 包含“来源：面试复盘建议” -> 复盘建议
progress_notes 包含“来源：岗位匹配短板” -> 匹配短板
evidence_refs 包含 fit_                 -> 匹配短板
evidence_refs 包含 note_                -> 复盘建议
无法判断                                -> 学习任务
```

标签用于解释来源，不作为强筛选条件。

## 视觉方向

整体保持当前工作台的浅色、克制、玻璃感风格，但学习任务区要更像行动面板：

- 入口按钮使用清晰图标：加号、星光、打卡。
- 任务卡片减少大面积同色背景，更多使用细边框、浅色标签和留白。
- 状态列之间保持稳定间距，窄屏改为纵向堆叠。
- 来源标签不要抢主标题权重。
- 详情弹层里用分组阅读，不展示大段未整理 Markdown。

## 执行链路

### 用户主动添加

```text
点击“新建任务”
  -> LearningTaskCreateSheet
  -> 用户填写标题和目标
  -> 前端发送聊天意图
  -> Agent 调用 learning_task_create
  -> 聊天展示执行过程
  -> 工作台刷新任务列表
```

### 系统推荐添加

```text
点击“从项目推荐”
  -> 前端发送聊天意图
  -> Agent 召回项目、报告、复盘、短板
  -> Assistant 返回建议或确认项
  -> 用户点击“加入学习任务”
  -> Agent 调用 learning_task_create
  -> 工作台刷新任务列表
```

### 记录进度

```text
点击“记录进度”
  -> 选择任务或默认当前任务
  -> LearningCheckinComposer
  -> 前端发送聊天意图
  -> Agent 调用 learning_checkin_create
  -> 如用户明确选择状态变化，再更新 LearningTask 状态
  -> 工作台刷新任务列表
```

## 开发拆分

第一步：

- 将 `LearningActionStrip` 升级为 `LearningTaskEntryPanel`。
- 增加“新建任务 / 从项目推荐 / 记录进度”三个入口。
- 保持执行回到聊天，不新增 API。

第二步：

- 优化 `LearningTaskBoard` 为 `LearningTaskPanel`。
- 增加状态筛选和来源标签。
- 优化空状态。

第三步：

- 增加 `LearningTaskCreateSheet` 和 `LearningCheckinComposer`。
- 详情弹层增加“记录今日进度”和状态动作。

第四步：

- 对话结果动作栏接入“加入学习任务”。
- 支持从 Assistant 建议确认创建任务。

## 验收标准

- 没有求职项目时，用户也能从工作台或聊天创建学习任务。
- 有求职项目时，用户能基于当前项目生成推荐任务。
- 学习任务卡片能看出任务来源、状态、优先级和下一步。
- 用户可以从任务卡片或详情记录今日进度。
- 所有写入仍经过 Agent 工具，不由前端直接写 store。
- 创建任务不自动写 Note、CareerApplication、WeaknessTracker 或 memory。
- 前端空状态不再只提示“回到聊天”，而是给出可执行入口。
