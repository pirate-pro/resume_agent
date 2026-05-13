# M14 求职工作台一级页面方案

## 背景

M13 已经把求职项目详情从前端本地拼装，升级为后端 `CareerWorkbench` 聚合视图。现在右侧「求职资产」栏可以展示简历画像、职业画像、JD 分析、匹配报告、简历版本、学习任务、短板、笔记和时间线。

问题也随之出现：内容越来越多后，右侧栏不适合继续承担主工作区职责。它宽度有限，列表、筛选、详情、预览和调试入口放在一起，会显得局促，也不利于用户长期管理求职项目、笔记和学习计划。

因此 M14 的方向不是继续扩展右侧栏，而是新增一个独立的「求职工作台」一级页面。

## 产品定位

```text
聊天界面：任务入口、过程反馈、追问和快速动作
右侧资产栏：轻量概览、最近资产、快速预览、打开工作台入口
求职工作台：长期管理、检索、对比、预览、推进求职资产
```

求职工作台不是调试面板，也不是简单的资产列表放大版。它应该让用户一眼知道：

- 当前有哪些求职项目。
- 哪些项目可以投递，哪些还缺材料。
- 每个项目关联了哪些简历、JD、报告、笔记和学习任务。
- 下一步应该做什么。
- 历史报告、定制简历、笔记和学习任务在哪里查看。

## M14 目标

- 新增一个一级工作台页面，给求职资产足够空间。
- 右侧「求职资产」栏降级为轻量入口，不再承载完整管理能力。
- 复用 M13 `CareerApplicationWorkbenchView` 作为项目详情事实源。
- 增加笔记、学习任务、资料资产的独立浏览区域。
- 建立清晰组件命名，后续调整 UI 时能准确定位。
- 保留聊天作为统一发起任务入口，工作台动作仍可回到聊天执行。

## 非目标

M14 第一阶段不做：

- 不引入新的后端 store。
- 不改变 `CareerProductStore`、`NoteStore`、`LearningStore` 的事实源边界。
- 不把 Note 自动写入 memory。
- 不做 RAG / MCP 接入。
- 不做日历、提醒、监督推送。
- 不做复杂看板拖拽。
- 不做跨项目智能排序模型。
- 不删除右侧资产栏，只调整它的职责。

## 总体布局

桌面端采用三栏工作台：

```text
┌──────────────────────────────────────────────────────────────┐
│ WorkbenchTopBar                                              │
├──────────────┬─────────────────────────────┬─────────────────┤
│ WorkbenchNav │ WorkbenchMainPane           │ WorkbenchSidePane│
│              │                             │                 │
│ 总览         │ 项目列表 / 资产列表 / 笔记   │ 当前详情 / 操作  │
│ 求职项目     │ 学习任务 / 时间线            │ 预览 / 推荐动作  │
│ 简历资料     │                             │                 │
│ JD 与匹配    │                             │                 │
│ 学习计划     │                             │                 │
│ 笔记         │                             │                 │
└──────────────┴─────────────────────────────┴─────────────────┘
```

移动端和窄屏采用两层结构：

```text
顶部：WorkbenchTopBar
一级：WorkbenchNav 横向 Tab
主体：WorkbenchMainPane
详情：底部弹层 / 全屏详情页
```

## 页面入口

### 1. 聊天顶部入口

`ChatHeader` 增加「工作台」按钮。

点击后从当前聊天界面切到 `CareerWorkbenchPage`。由于当前 Flutter 应用还没有路由系统，M14 第一阶段可以先在 `HomeScreen` 中增加主视图状态：

```text
HomeScreen
  _PrimaryViewMode.chat
  _PrimaryViewMode.careerWorkbench
```

后续如果引入路由，再迁移为 `/career-workbench`。

### 2. 右侧资产栏入口

`CareerAssetsPanel` 顶部增加「打开工作台」按钮。

右侧栏职责调整为：

- 展示最近资产。
- 展示当前项目摘要。
- 快速预览最近报告。
- 引导打开完整工作台。

### 3. 任务完成引导

当聊天生成 `CareerApplication`、`JobFitReport`、`ResumeVersion` 或 Note 后，结果卡片可以提供：

```text
查看工作台
查看项目详情
预览报告
```

M14 第一阶段先做「查看工作台」入口，不强行改所有聊天结果卡片。

## 组件结构

### 1. `CareerWorkbenchPage`

求职工作台根页面。

职责：

- 管理工作台当前 Tab。
- 管理当前选中的 `application_id`、`note_id`、`asset_id`。
- 触发 `CareerWorkbenchProvider` 加载数据。
- 连接聊天动作回调。

结构：

```text
CareerWorkbenchPage
  -> CareerWorkbenchTopBar
  -> CareerWorkbenchShell
```

### 2. `CareerWorkbenchTopBar`

页面顶部。

展示内容：

- 标题：求职工作台。
- 副标题：项目数、待办数、最近更新时间。
- 操作：
  - 返回聊天
  - 刷新
  - 新建会话 / 发起任务

视觉要求：

- 顶部不要做大 hero。
- 保持专业工具感，紧凑、清晰、可扫描。
- 显示当前数据刷新状态。

### 3. `CareerWorkbenchShell`

工作台布局外壳。

职责：

- 桌面端组织三栏。
- 窄屏切换为 Tab + 主体 + 弹层详情。
- 统一页面内边距、背景、分隔线和滚动行为。

结构：

```text
CareerWorkbenchShell
  -> CareerWorkbenchNav
  -> CareerWorkbenchMainPane
  -> CareerWorkbenchSidePane
```

### 4. `CareerWorkbenchNav`

左侧导航。

导航项：

```text
总览
求职项目
简历资料
JD 与匹配
学习计划
笔记
```

每项展示：

- 图标。
- 名称。
- 数量徽标。
- 当前选中状态。

不做会话标签，不根据聊天内容自动给会话贴标签。

### 5. `CareerWorkbenchMainPane`

中间主内容区。

职责：

- 根据当前 Tab 展示对应列表或总览。
- 承担主要浏览、筛选和选择行为。

可渲染视图：

```text
WorkbenchOverviewView
CareerProjectListView
ResumeAssetLibraryView
JobMatchLibraryView
LearningPlanBoardView
NoteLibraryView
```

### 6. `CareerWorkbenchSidePane`

右侧详情区。

职责：

- 展示当前选中对象详情。
- 展示建议动作。
- 展示可预览文件入口。
- 承载轻量编辑入口。

可渲染详情：

```text
CareerProjectDetailPane
AssetDetailPane
NoteDetailPane
LearningTaskDetailPane
EmptyDetailPane
```

### 7. `WorkbenchOverviewView`

总览页。

模块：

```text
ReadinessSummaryStrip
ActiveApplicationsSection
PendingActionsSection
RecentArtifactsSection
RecentNotesSection
LearningRiskSection
```

目标效果：

- 用户打开工作台后先看到“当前最该处理什么”。
- 不展示底层长 ID。
- 只显示 3-5 条最高价值信息，多余内容进入具体 Tab。

### 8. `CareerProjectListView`

求职项目列表。

展示字段：

- 公司和岗位。
- 阶段。
- 优先级。
- 匹配度。
- 缺失材料数量。
- 待办动作数量。
- 最近更新时间。

筛选：

```text
全部
准备中
可投递
已投递
面试中
已暂停
```

排序：

```text
最近更新
优先级
匹配度
风险数量
```

点击项目后，右侧显示 `CareerProjectDetailPane`。

### 9. `CareerProjectDetailPane`

求职项目详情。

直接复用 M13 工作台数据：

```text
GET /api/career/workbench/applications/{application_id}
```

模块：

```text
ProjectReadinessHeader
ProjectLinkedAssets
ProjectKeyStrengths
ProjectRisks
ProjectSuggestedActions
ProjectTimeline
ProjectNotesPreview
ProjectLearningPreview
```

M13 已经实现过类似弹层 UI。M14 不应复制一份完全独立逻辑，而应该抽出可复用组件：

```text
CareerApplicationWorkbenchViewWidget
```

这个组件可同时用于：

- M13 项目详情弹层。
- M14 项目详情侧栏。
- 后续独立项目详情页。

### 10. `ResumeAssetLibraryView`

简历资料页。

内容：

- 原始简历 artifact。
- 简历画像 `ResumeProfile`。
- 诊断报告 artifact。
- 简历版本 `ResumeVersion`。

分组规则沿用 `frontend_career_assets_grouping.md`：

- 默认展示当前版本。
- 历史版本折叠进时间线。
- 可预览状态明确显示。

### 11. `JobMatchLibraryView`

JD 与匹配页。

内容：

- JD 原文 artifact。
- JDAnalysis。
- JobFitReport。
- 岗位匹配报告 artifact。

目标：

- 用户能按公司、岗位、更新时间查找历史 JD 和匹配报告。
- 支持从匹配报告跳到关联项目。

### 12. `LearningPlanBoardView`

学习计划页。

内容：

- LearningPlan。
- LearningTask。
- WeaknessTracker。
- ReviewSchedule。

第一阶段用列表 + 分组，不做拖拽看板。

分组：

```text
待办
进行中
受阻
已完成
```

重点展示：

- 任务标题。
- 关联求职项目。
- 技能标签。
- 预计耗时。
- 截止时间。
- 短板来源。

### 13. `NoteLibraryView`

笔记页。

内容：

- 项目笔记。
- 面试复盘。
- 学习笔记。
- 普通笔记。

筛选：

```text
全部
项目笔记
面试复盘
学习笔记
普通笔记
```

展示字段：

- 标题。
- 摘要。
- 标签。
- 关联项目。
- 更新时间。

点击笔记后右侧显示 `NoteDetailPane`。

笔记正文第一阶段只读展示，后续再做编辑器。

### 14. `ArtifactPreviewDrawer`

文件预览抽屉或弹层。

职责：

- 预览 Markdown 报告。
- 预览简历版本。
- 预览 JD 原文。
- 下载 artifact。

复用当前 `ArtifactPreviewSheet` 和 Markdown 渲染能力。

M14 第一阶段可以继续用弹层，后续再变成右侧抽屉。

## Provider 与数据来源

### 1. `CareerWorkbenchProvider`

建议新增 provider，避免继续把全部状态塞进 `CareerAssetsProvider`。

职责：

- 加载工作台总览。
- 缓存项目详情。
- 管理当前选中对象。
- 管理筛选和排序。

数据：

```text
CareerWorkbenchListView
Map<String, CareerApplicationWorkbenchView>
selectedApplicationId
selectedNoteId
selectedLearningTaskId
activeTab
filters
```

### 2. API 数据源

M14 第一阶段优先复用已有接口：

```text
GET /api/career/workbench
GET /api/career/workbench/applications/{application_id}
GET /api/notes
GET /api/notes/{note_id}
GET /api/learning/plans
GET /api/learning/tasks
GET /api/learning/weaknesses
GET /api/learning/reviews
```

如果某些 learning 前端 API 还没封装，M14 第一阶段可以先只显示 `CareerApplicationWorkbenchView.learning` 中与项目关联的学习信息，不急着做全量学习计划页。

### 3. 与 `CareerAssetsProvider` 的关系

`CareerAssetsProvider` 继续服务右侧轻量栏。

`CareerWorkbenchProvider` 服务一级工作台。

两者可以复用 `ApiService` 和模型，但不要互相持有状态，避免刷新逻辑互相影响。

## 交互逻辑

### 1. 从聊天进入工作台

```text
用户点击顶部「工作台」
  -> HomeScreen 切换到 CareerWorkbenchPage
  -> CareerWorkbenchProvider.ensureLoaded()
  -> 默认打开总览
```

### 2. 从右侧资产栏进入项目

```text
用户在右侧资产栏点击「打开工作台」
  -> 切换到 CareerWorkbenchPage
  -> 如果当前卡片是 CareerApplication，选中对应 application_id
  -> 打开求职项目 Tab
```

### 3. 查看项目详情

```text
用户点击项目列表项
  -> selectedApplicationId = application_id
  -> 加载 getCareerApplicationWorkbench(application_id)
  -> 右侧显示 CareerProjectDetailPane
```

### 4. 执行推荐动作

工作台里的动作不直接绕过聊天执行。

```text
用户点击「生成定制简历 / 投递前检查 / 面试准备 / 创建学习任务」
  -> 生成受控 prompt
  -> 切回聊天或保持工作台并显示发送状态
  -> chatProvider.sendMessage(prompt)
  -> 聊天流式展示执行过程
  -> 结束后刷新工作台
```

第一阶段建议点击动作后切回聊天，让用户能看到执行过程。

### 5. 查看笔记

```text
用户打开「笔记」Tab
  -> 调用 GET /api/notes
  -> 列表显示笔记摘要
  -> 点击笔记
  -> 右侧 NoteDetailPane 展示正文
```

如果笔记关联了求职项目，详情里提供：

```text
查看关联项目
```

### 6. 查看 artifact

```text
用户点击预览报告 / 预览简历 / 预览 JD
  -> 使用 source_session_id + artifact_id
  -> 调用 session artifact content API
  -> 打开 ArtifactPreviewDrawer / ArtifactPreviewSheet
```

不允许前端或 agent 暴露本地路径。

## 视觉原则

- 工作台应该像专业生产力工具，不像调试后台。
- 卡片用于单个项目、单个笔记、单个任务，不把页面大区块做成层层嵌套卡片。
- 一级页面用清晰分区和轻量材质，不用大面积渐变装饰。
- 默认不展示长 ID；ID 放到详情里的调试区。
- 所有列表项必须能在窄屏下换行，不允许文字溢出。
- 重点信息优先：匹配度、风险、下一步行动、关联资料可预览状态。
- 操作用图标 + 短文案，避免大段说明文字。

## M14 分阶段范围

### M14-1：工作台壳与项目页

目标：先把主空间搭起来，解决右侧栏拥挤问题。

实现：

```text
flutter_app/lib/features/career_workbench/career_workbench_page.dart
flutter_app/lib/features/career_workbench/career_workbench_provider.dart
flutter_app/lib/features/career_workbench/widgets/workbench_shell.dart
flutter_app/lib/features/career_workbench/widgets/project_list.dart
flutter_app/lib/features/career_workbench/widgets/project_detail_pane.dart
```

功能：

- HomeScreen 支持聊天 / 工作台主视图切换。
- 聊天顶部增加「工作台」入口。
- 右侧资产栏增加「打开工作台」入口。
- 工作台展示总览和求职项目列表。
- 点击项目展示 M13 项目详情。
- 项目详情动作可发送 prompt 回聊天。

不做：

- 独立笔记库编辑。
- 全量学习任务管理。
- 复杂搜索。

### M14-2：笔记页

目标：让用户能独立查看所有 Note。

实现：

```text
NoteLibraryView
NoteListItem
NoteDetailPane
```

功能：

- 列出 `/api/notes`。
- 按项目关联、标签、更新时间筛选。
- 查看笔记正文。
- 从笔记跳转关联求职项目。

不做：

- 富文本编辑器。
- 自动写 memory。

### M14-3：学习计划页

目标：让用户能管理长期学习推进。

实现：

```text
LearningPlanBoardView
LearningTaskList
WeaknessTrackerList
ReviewScheduleList
```

功能：

- 展示学习计划、学习任务、短板和复盘安排。
- 按状态分组。
- 从短板跳转关联项目或匹配报告。

不做：

- 提醒系统。
- 日历同步。

### M14-4：资料与报告库

目标：让简历、JD、匹配报告和简历版本可查找。

实现：

```text
ResumeAssetLibraryView
JobMatchLibraryView
ArtifactPreviewDrawer
```

功能：

- 按类型浏览资料。
- 预览和下载 artifact。
- 查看历史版本。

不做：

- RAG 知识库统一检索。
- 外部资料库接入。

## 验收标准

M14-1 验收：

- 用户可以从聊天顶部进入求职工作台。
- 用户可以从右侧资产栏进入求职工作台。
- 工作台有独立页面空间，不再挤在右侧栏。
- 工作台能展示项目列表。
- 点击项目能展示当前判断、匹配点、风险、关联资产、学习推进、笔记和时间线。
- 项目详情中的预览按钮能打开 artifact 预览。
- 项目详情中的推荐动作能发送受控 prompt。
- 右侧资产栏仍可正常刷新和预览最近资产。
- `flutter analyze` 通过。
- 相关 widget 测试通过。

## 风险与取舍

### 1. 当前没有路由系统

M14-1 先用 `HomeScreen` 状态切换主视图，成本最低。后续如果页面继续增加，再引入路由。

### 2. 工作台和右侧栏状态可能重复

通过拆分 `CareerWorkbenchProvider` 和 `CareerAssetsProvider` 控制边界。两者都可以调用同一个 API，但不共享 mutable 状态。

### 3. 内容多后页面仍可能拥挤

M14 不把所有信息一次性铺开。总览只放高价值摘要，完整内容进入具体 Tab 和详情区。

### 4. 笔记和 memory 容易混淆

工作台只展示 Note，不展示 memory。Note 是用户可见资产，memory 是运行时上下文材料。M14 不做自动 Note -> memory。

## 推荐开发顺序

```text
1. 新增 CareerWorkbenchProvider
2. 新增 CareerWorkbenchPage / Shell / Nav / TopBar
3. HomeScreen 增加 chat/workbench 主视图切换
4. 抽出 M13 项目详情可复用组件
5. 实现 CareerProjectListView
6. 实现 CareerProjectDetailPane
7. 右侧资产栏增加“打开工作台”
8. 补 widget 测试
9. flutter analyze / flutter test
```

M14-1 完成后，再进入笔记页和学习计划页。
