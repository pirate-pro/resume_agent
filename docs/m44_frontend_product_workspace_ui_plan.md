# M44：求职工作台产品化前端改版方案

> 状态：开发中。分支：`m44-frontend-product-workspace-ui`。目标是按 UI 设计稿把当前 Flutter 前端从“聊天 + 调试/资产面板”调整为“求职产品工作台”。`.env` 不属于本阶段改动范围。

当前落地进度：

```text
M44-A/B：产品级 App Shell、左侧产品导航、顶部搜索和总览页已落地。
M44-C：求职项目页已从旧 CareerWorkbenchPage 中拆出为独立产品页。
M44-D：JD 匹配页已从旧 CareerWorkbenchPage 中拆出为独立产品页。
待继续：简历资料页、学习计划和笔记页继续逐页替换旧工作台 UI。
```

## 1. 背景与目标

当前后端和 Agent 主链路已经有较稳定的产品能力：

```text
CareerApplicationWorkbench 聚合视图
ResumeProfile / JDAnalysis / JobFitReport / ResumeVersion
Note / LearningTask / Review / SuggestedAction
Agent 事件流和多 agent 执行进度
```

但当前 Flutter 前端的信息架构仍偏工程态：

```text
1. HomeScreen 主体仍以 ChatScreen 为中心。
2. CareerWorkbenchPage 已有数据，但视觉层次不像产品首页。
3. SessionSidebar 是会话侧栏，不是产品导航。
4. CareerAssetsPanel 是资产抽屉，不是完整资料库页面。
5. 用户必须通过聊天理解系统能力，页面本身没有明确的下一步引导。
```

M44 的目标：

```text
1. 建立产品级 App Shell：左侧产品导航 + 顶部搜索/新建 + 主页面。
2. 按设计稿落地 4 个核心页面：
   - 总览
   - 求职项目
   - JD 匹配
   - 简历资料
3. 保持所有写入动作仍回到 Agent/Chat 执行，不让前端直接绕过事实源。
4. 保持响应式，不做死位置，不依赖固定屏幕尺寸。
5. 第一版优先提升体感，不在本阶段重做后端 API。
```

## 2. 不做事项

```text
不改 Agent runtime。
不改工具链。
不新增后端事实源。
不把页面做成纯静态 mock。
不为了对齐设计稿写死像素坐标。
不要求一次性实现所有细节动画。
不隐藏聊天入口；聊天仍是执行动作和自由问答入口。
```

## 3. 现有前端结构

当前主要文件：

```text
flutter_app/lib/features/home/home_screen.dart
  当前 App 壳：SessionSidebar + ChatScreen + CareerAssetsPanel / DebugPanel / CareerWorkbenchPage

flutter_app/lib/shared/widgets/session_sidebar.dart
  当前左侧会话侧栏。

flutter_app/lib/features/chat/chat_screen.dart
  聊天主页面，包含顶部 dock、消息区、输入区。

flutter_app/lib/features/career_workbench/career_workbench_page.dart
  当前求职工作台，包含 overview/projects/resumes/jobs/learning/notes 多个私有 widget。

flutter_app/lib/features/career_workbench/career_workbench_provider.dart
  工作台状态与 API 聚合。

flutter_app/lib/features/career/career_assets_panel.dart
  求职资产侧边面板。

flutter_app/lib/shared/theme/app_theme.dart
  当前颜色、字体、装饰。
```

当前问题不是数据不够，而是组件边界不清晰。`career_workbench_page.dart` 已经超过 5000 行，M44 不应继续往一个文件里堆 UI，需要拆出产品组件层。

## 4. 新信息架构

设计稿对应的主导航：

```text
总览
求职项目
简历资料
JD 匹配
学习计划
笔记
```

页面关系：

```text
ProductShell
  ├── ProductSidebar
  ├── WorkspaceTopBar
  └── WorkspacePageHost
      ├── DashboardPage
      ├── CareerProjectsPage
      ├── ResumeLibraryPage
      ├── JDMatchPage
      ├── LearningPlanPage
      └── NotesPage
```

聊天入口处理：

```text
1. 左侧「新建会话」仍创建聊天会话。
2. 左侧「Agent 助手」进入 ChatScreen。
3. 所有推荐动作按钮调用现有 onSendPrompt，回到 Chat 执行。
4. ChatScreen 不再作为唯一首页，而是 ProductShell 中的一个 workspace mode。
```

## 5. 文件与组件拆分计划

### 5.1 Shell 层

新增：

```text
flutter_app/lib/features/workspace/workspace_shell.dart
flutter_app/lib/features/workspace/workspace_nav.dart
flutter_app/lib/features/workspace/workspace_top_bar.dart
flutter_app/lib/features/workspace/workspace_models.dart
```

职责：

```text
workspace_shell.dart
  ProductWorkspaceShell
  - 接收 activePage、onPageChanged、onNewSession、onOpenChat。
  - 按断点决定三种布局：desktop / tablet / mobile。
  - 只负责页面框架，不直接读业务 API。

workspace_nav.dart
  ProductSidebar
  ProductNavItem
  WorkspaceQuickEntryGrid
  AssistantStatusCard
  MobileWorkspaceDrawer
  - 替代当前 SessionSidebar 的产品导航场景。
  - SessionSidebar 保留给聊天会话抽屉，不删除。

workspace_top_bar.dart
  WorkspaceTopBar
  GlobalSearchBox
  TopActionButton
  NotificationIconButton
  UserAvatarButton
  - 顶部搜索/命令入口。
  - 第一版搜索可以只做 UI 和回车转聊天 prompt，不做全局搜索索引。

workspace_models.dart
  WorkspacePage enum
  WorkspaceNavBadge
  WorkspaceQuickAction
```

修改：

```text
flutter_app/lib/features/home/home_screen.dart
```

调整方式：

```text
1. 新增 _WorkspaceViewMode：
   overview / projects / resumes / jdMatch / learning / notes / chat

2. HomeScreen 保留：
   - chatProvider
   - careerWorkbenchProvider
   - careerAssetsProvider
   - _sendWorkbenchPrompt

3. HomeScreen 不再用 SessionSidebar 作为常驻左栏。
   desktop 常驻 ProductSidebar；
   mobile 使用 Drawer 或 bottom sheet 打开 ProductSidebar。

4. ChatScreen 作为 workspace host 中的一个页面。
```

### 5.2 Theme / Design Token 层

新增：

```text
flutter_app/lib/shared/theme/product_tokens.dart
```

内容：

```dart
class ProductColors {
  static const canvas = Color(0xFFF7FAF9);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceSoft = Color(0xFFF2F8F6);
  static const surfaceMint = Color(0xFFEAF8F3);
  static const border = Color(0xFFDDE8E4);
  static const borderStrong = Color(0xFFC9D8D3);

  static const primary = Color(0xFF0F9B78);
  static const primaryHover = Color(0xFF0B7E62);
  static const primarySoft = Color(0xFFE5F6F1);

  static const info = Color(0xFF2563EB);
  static const infoSoft = Color(0xFFEFF6FF);
  static const warning = Color(0xFFF59E0B);
  static const warningSoft = Color(0xFFFFF7E6);
  static const danger = Color(0xFFEF4444);
  static const dangerSoft = Color(0xFFFFF1F2);
  static const purple = Color(0xFF8B5CF6);
  static const purpleSoft = Color(0xFFF5F3FF);

  static const text = Color(0xFF14211B);
  static const textSecondary = Color(0xFF55645F);
  static const textMuted = Color(0xFF8A9892);
}
```

设计原则：

```text
绿色只用于主状态和主操作；
蓝色用于资料/文档/证据；
橙色用于风险和待补齐；
紫色用于面试/Agent/学习；
红色只用于阻断风险和失败；
页面底色保持白灰，不做大面积绿色背景，避免一色到底。
```

新增通用装饰：

```text
ProductSurface.card()
  radius 16
  border ProductColors.border
  shadow blur 18 alpha 0.08

ProductSurface.softCard()
  radius 16
  border ProductColors.border
  fill ProductColors.surfaceSoft

ProductSurface.hero()
  radius 18
  gradient: #EAF8F3 -> #F8FCFA -> #EEF7FF
  border primary alpha 0.18
```

不要使用：

```text
固定 absolute Positioned 页面布局。
根据 viewport width 缩放字体。
负 letter spacing。
大面积纯渐变背景。
卡片套卡片。
```

### 5.3 通用组件层

新增：

```text
flutter_app/lib/shared/widgets/product_card.dart
flutter_app/lib/shared/widgets/product_metric_card.dart
flutter_app/lib/shared/widgets/product_score_ring.dart
flutter_app/lib/shared/widgets/product_tag.dart
flutter_app/lib/shared/widgets/product_section.dart
flutter_app/lib/shared/widgets/product_action_tile.dart
flutter_app/lib/shared/widgets/product_empty_state.dart
```

组件说明：

```text
ProductCard
  - 统一 padding / radius / border / shadow。
  - 支持 header / body / footer slot。

ProductMetricCard
  - 左侧 icon tile，右侧 value + label + trend。
  - 用于总览四个指标和简历资料统计。

ProductScoreRing
  - 复用当前 _ScoreRing 逻辑，但支持 size / label / status。
  - desktop 默认 88；card 内 64；mobile hero 76。

ProductTag
  - pill tag，支持 tone: primary/info/warning/danger/purple/neutral。

ProductSection
  - section header + trailing action + child。
  - 用于风险、推荐动作、关联资产、证据依据。

ProductActionTile
  - icon + title + subtitle + optional badge + trailing button/arrow。
  - 用于推荐动作、下一步、关联资产。
```

第一版可以先在新文件中实现，旧 `_TinyTag`、`_SmallTextButton`、`_ScoreRing` 暂时不删，后续逐步替换。

## 6. 布局断点

所有页面使用 `LayoutBuilder`，不能依赖固定屏幕。

```text
desktop: width >= 1280
  ProductSidebar: 260
  main content: Expanded
  right rail: 320-360
  gap: 20
  page horizontal padding: 28

tablet: 900 <= width < 1280
  ProductSidebar: 84 collapsed rail 或可展开 220
  right rail 下移为主内容右侧 second column 或 section stack
  main grid: 2 columns
  page horizontal padding: 20

compact: 720 <= width < 900
  no persistent sidebar
  top bar shows menu button
  main content single column
  metric cards 2 columns
  page horizontal padding: 16

mobile: width < 720
  no persistent sidebar
  top bar compact
  bottom safe area respected
  single column
  horizontal chips for tabs
  card padding 14
  hero action buttons wrap
```

可滚动策略：

```text
1. 页面整体用 CustomScrollView 或 ListView。
2. 不在页面内部堆多个 Expanded + ListView，避免高度约束混乱。
3. desktop 三栏中只有主内容和右 rail 各自可滚动。
4. mobile 所有右 rail 内容作为普通 section 顺序下沉。
```

## 7. 页面一：总览 Dashboard

设计稿对应第三张图。

新增文件：

```text
flutter_app/lib/features/dashboard/dashboard_page.dart
flutter_app/lib/features/dashboard/widgets/status_hero_card.dart
flutter_app/lib/features/dashboard/widgets/dashboard_metric_strip.dart
flutter_app/lib/features/dashboard/widgets/recent_application_card.dart
flutter_app/lib/features/dashboard/widgets/today_action_card.dart
flutter_app/lib/features/dashboard/widgets/dashboard_right_rail.dart
```

### 7.1 DashboardPage 布局

desktop：

```text
DashboardPage
  Row
    Expanded main column
      StatusHeroCard
      DashboardMetricStrip
      RecentApplicationsSection
      TodayRecommendedActionsSection
    SizedBox(width: 20)
    SizedBox(width: 340)
      DashboardRightRail
```

mobile：

```text
ListView
  StatusHeroCard
  DashboardMetricStrip as Wrap 2 columns / 1 column
  DashboardRightRail.currentJudgment as section
  RecentApplicationsSection
  TodayRecommendedActionsSection
  DashboardRightRail.linkedAssets as section
```

### 7.2 StatusHeroCard

位置：

```text
Dashboard main column 第一块。
```

元素：

```text
左侧：
  title: 当前求职状态
  subtitle: readiness.summary 或默认整体建议
  chips:
    目标岗位: 从 active application title / target role 取
    意向城市: 从 careerProfile 或空态展示“待补充”
    当前阶段: active application stage
  primary button:
    继续推进岗位 -> 打开 active project / 触发 recommended action

右侧：
  ProductScoreRing
    value: active readiness.score
    label: 综合进度
  status pill:
    良好 / 需补齐 / 高风险
```

色块：

```text
background: ProductSurface.hero()
score ring: primary
status pill good: primarySoft + primary
status pill warning: warningSoft + warning
```

数据来源：

```text
careerWorkbenchProvider.workbench.activeApplicationId
careerWorkbenchProvider.selectedApplicationSummary.readiness
```

### 7.3 DashboardMetricStrip

位置：

```text
StatusHeroCard 下方。
```

四个 ProductMetricCard：

```text
已投递岗位
  value: counts.activeApplications 或 applications.length
  icon: Icons.near_me_outlined
  tone: info

匹配度均值
  value: applications readiness score average
  icon: Icons.track_changes_rounded
  tone: primary

待办任务
  value: counts.learningTasks + suggestedActions count
  icon: Icons.format_list_bulleted_rounded
  tone: warning

本周学习进度
  value: learning completed / total 推断；没有数据时显示 "-"
  icon: Icons.menu_book_outlined
  tone: purple
```

响应：

```text
desktop: 4 columns
tablet: 2 columns
mobile: 1-2 columns，根据 minWidth 156 自动 wrap
```

### 7.4 RecentApplicationsSection

位置：

```text
Dashboard main column 中部。
```

元素：

```text
section header:
  title 最近推进中的岗位
  trailing 查看全部

RecentApplicationCard x3
  company logo/avatar:
    没有真实 logo 时用首字或品牌色块，不使用外链图片。
  title
  company / location
  status tags: stage / recommendation
  latest progress
  key points: top 2 strengths or risks
  ProductScoreRing small
  primary action:
    继续跟进 / 准备面试 / 优化简历，按 stage + suggestedActions 推断
  secondary action:
    查看详情
```

desktop：

```text
横向 3 卡；每卡 minWidth 260，使用 Wrap。
```

mobile：

```text
单列卡片。
```

### 7.5 DashboardRightRail

位置：

```text
desktop 右侧 rail。
mobile 下沉为普通 section。
```

包含：

```text
CurrentJudgmentCard
  title 当前判断
  summary readiness.summary
  strengths top 2
  risks top 2

NextStepCard
  title 推荐下一步
  action rows top 3
  button 查看全部待办

RelatedAssetSummaryCard
  counts:
    简历模板 / 笔记文档 / 面试题库 / 学习资料
  recent assets top 3
```

## 8. 页面二：求职项目 Projects

设计稿对应第一张图。

改造文件：

```text
flutter_app/lib/features/career_workbench/career_workbench_page.dart
```

新增拆分：

```text
flutter_app/lib/features/career_workbench/pages/career_projects_page.dart
flutter_app/lib/features/career_workbench/widgets/project_overview_header.dart
flutter_app/lib/features/career_workbench/widgets/job_fact_strip.dart
flutter_app/lib/features/career_workbench/widgets/project_stage_timeline.dart
flutter_app/lib/features/career_workbench/widgets/agent_execution_board.dart
flutter_app/lib/features/career_workbench/widgets/project_right_rail.dart
flutter_app/lib/features/career_workbench/widgets/risk_gap_panel.dart
flutter_app/lib/features/career_workbench/widgets/recommended_action_panel.dart
flutter_app/lib/features/career_workbench/widgets/linked_asset_panel.dart
```

### 8.1 CareerProjectsPage 布局

desktop：

```text
CareerProjectsPage
  Column
    ProjectOverviewHeader
    JobFactStrip
    Row
      SizedBox(width: 260) ProjectStageTimeline
      Expanded AgentExecutionBoard
      SizedBox(width: 320) ProjectRightRail
    Row
      Expanded RiskGapPanel
      Expanded RecommendedActionPanel
      SizedBox(width: 320) LinkedAssetPanel
```

tablet：

```text
ProjectOverviewHeader
JobFactStrip
AgentExecutionBoard
Row
  ProjectStageTimeline
  ProjectRightRail
RiskGapPanel
RecommendedActionPanel
LinkedAssetPanel
```

mobile：

```text
Project selector chips
ProjectOverviewHeader
JobFactStrip horizontal scroll
ProjectRightRail.currentJudgment
ProjectStageTimeline
AgentExecutionBoard horizontal cards
RiskGapPanel
RecommendedActionPanel
LinkedAssetPanel
```

### 8.2 ProjectOverviewHeader

位置：

```text
Projects 页面顶部第一块。
```

元素：

```text
company/avatar tile:
  64 desktop / 52 mobile
  如果 application.company 存在，取首字；否则用 work icon。

title group:
  company name
  official link badge 可先隐藏，除非后端有 source url。
  job title: application.displayTitle
  meta row:
    location / education / experience / employment type
    从 JDAnalysis 和 application 字段取，取不到就不显示该项。

score:
  ProductScoreRing 86
  label 匹配度
  status pill 良好/谨慎/风险

status block:
  当前状态: _stageLabel(application.stage)
  最近更新: application.updatedAt

AI summary:
  readiness.summary
  button 查看完整分析报告
```

色块：

```text
background: hero gradient #EAF8F3 -> #F7FCFA
border: primary alpha 0.18
score: primary / warning / danger by score
```

### 8.3 JobFactStrip

位置：

```text
ProjectOverviewHeader 下方。
```

元素：

```text
投递时间
岗位来源
招聘类型
岗位热度
竞争人数
期望薪资
```

第一版数据来源：

```text
application.appliedAt / updatedAt
application.source / jdAnalysis.source
jdAnalysis.extractedFields
找不到数据时显示“待补充”，不要硬编码华为/深圳/35K。
```

视觉：

```text
一行 6 个 FactItem。
desktop: 6 columns。
tablet: 3 columns。
mobile: horizontal ListView，单项 minWidth 148。
```

### 8.4 ProjectStageTimeline

位置：

```text
desktop 左中列；mobile 在 header 后。
```

阶段：

```text
简历投递
简历筛选
技术面试
综合面试
HR 面试
Offer
```

状态推断：

```text
completed: timeline 中已有该阶段 / application.stage 超过该阶段
active: application.stage 当前阶段
pending: 未开始
```

元素：

```text
圆点/序号
阶段名
时间
状态 chip：进行中/未开始/已完成
button 查看全部流程
```

### 8.5 AgentExecutionBoard

位置：

```text
desktop 中间主内容。
```

元素：

```text
section header:
  多 Agent 执行进度
  trailing 查看全部 Agent 执行记录

AgentStepCard x5:
  简历解析 Agent
  JD 分析 Agent
  匹配评估 Agent
  简历改写 Agent
  面试准备 Agent

每卡包含：
  icon tile
  agent name
  status: 已完成/进行中/待执行
  input summary
  output summary
  button 查看详情 / 继续执行
```

数据来源：

```text
优先：events agent_task_* / run_progress_panel 现有解析逻辑。
第一版可从 detail 已完成资产推断：
  resumeProfile -> 简历解析已完成
  jdAnalysis -> JD 分析已完成
  jobFitReport -> 匹配评估已完成
  resumeVersions not empty -> 简历改写已完成
  notes/reviews/interview actions -> 面试准备进行中/待执行
```

注意：

```text
这只是前端进度可视化，不创建新的任务状态事实源。
```

### 8.6 ProjectRightRail

包含：

```text
CurrentProjectJudgmentCard
  score + recommendation
  readiness.summary
  updatedAt

ProgressChecklistCard
  6 stage checklist
  completion count

LinkedAssetsCompactCard
  tabs: 简历 / 项目 / 笔记 / 资料
  top 3 assets
```

desktop 常驻右侧；mobile 下沉。

## 9. 页面三：JD 匹配

设计稿对应第二张图。

新增：

```text
flutter_app/lib/features/jd_match/jd_match_page.dart
flutter_app/lib/features/jd_match/widgets/jd_match_header.dart
flutter_app/lib/features/jd_match/widgets/match_score_overview.dart
flutter_app/lib/features/jd_match/widgets/match_dimension_grid.dart
flutter_app/lib/features/jd_match/widgets/gap_analysis_panel.dart
flutter_app/lib/features/jd_match/widgets/evidence_panel.dart
flutter_app/lib/features/jd_match/widgets/interview_question_strip.dart
flutter_app/lib/features/jd_match/widgets/jd_match_right_rail.dart
```

### 9.1 JDMatchPage 布局

desktop：

```text
JDMatchPage
  Row
    Expanded
      JDMatchHeader
      TabBar: 匹配分析 / 差距分析 / 证据依据 / 面试准备
      MatchScoreOverview
      MatchDimensionGrid
      Row
        GapAnalysisPanel
        EvidencePanel
      InterviewQuestionStrip
    SizedBox(width: 320)
      JDMatchRightRail
```

mobile：

```text
JDMatchHeader
MatchScoreOverview
Tabs horizontal
MatchDimensionGrid wrap
JDMatchRightRail.currentJudgment
GapAnalysisPanel
EvidencePanel
InterviewQuestionStrip horizontal scroll
JDMatchRightRail.related
```

### 9.2 JDMatchHeader

元素：

```text
company/avatar
job title
meta row: city / degree / scope / years
summary line
ProductScoreRing
trend: 较上次 +N，第一版没有历史时隐藏
updatedAt
```

数据来源：

```text
selected detail.application
selected detail.jdAnalysis
selected detail.jobFitReport
selected detail.readiness
```

### 9.3 MatchDimensionGrid

维度卡：

```text
技术栈匹配
项目经历匹配
Agent/LLM 经验
工程化能力
面试准备度
风险项
```

每个卡片：

```text
icon
title
score/数量
trend
supporting text top 1-2
```

分数来源：

```text
优先从 jobFitReport.structured fields 取。
没有结构化分数时，用 readiness.strengths / risks / weaknesses 做派生：
  技术栈匹配：skills overlap 粗略 count，只展示“较强/待补齐”，不伪造具体百分比。
```

原则：

```text
有真实数值就显示百分比；
没有真实数值就显示等级，不编造 85%、72%。
```

### 9.4 GapAnalysisPanel

元素：

```text
gap row:
  risk icon
  title
  priority chip: 高优先级/中优先级/低优先级
  left: JD 要求/问题
  right: 建议补充
```

数据来源：

```text
readiness.risks
learning.weaknesses
jobFitReport.gaps
```

### 9.5 EvidencePanel

元素：

```text
tabs: 匹配证据 / 缺失证据
evidence rows:
  check icon
  evidence title
  source chip: 项目经历 / 简历画像 / 报告
  one-line explanation
button 查看全部证据
```

数据来源：

```text
jobFitReport.evidence_refs
resumeProfile.projectExperience
linkedAssets
```

### 9.6 InterviewQuestionStrip

元素：

```text
filter chips: 全部 / 高频问答 / 技术深挖 / 项目追问 / 系统设计
question card:
  category tag
  question
  focus points
  difficulty
  button 查看参考答案
```

第一版：

```text
如果没有题库 API，使用 suggestedActions + risks 派生 3-5 个准备问题；
明确标记为“建议准备方向”，不要伪装成真实题库。
```

## 10. 页面四：简历资料

设计稿对应第四张图。

新增：

```text
flutter_app/lib/features/resume_library/resume_library_page.dart
flutter_app/lib/features/resume_library/widgets/resume_stats_strip.dart
flutter_app/lib/features/resume_library/widgets/resume_version_list.dart
flutter_app/lib/features/resume_library/widgets/resume_preview_panel.dart
flutter_app/lib/features/resume_library/widgets/resume_ai_insight_panel.dart
flutter_app/lib/features/resume_library/widgets/resume_right_rail.dart
flutter_app/lib/features/resume_library/widgets/resume_version_history.dart
```

### 10.1 ResumeLibraryPage 布局

desktop：

```text
ResumeLibraryPage
  ResumeStatsStrip
  Row
    SizedBox(width: 300) ResumeVersionList
    Expanded ResumePreviewPanel
    SizedBox(width: 320) ResumeAIInsightPanel
    SizedBox(width: 300) ResumeRightRail
  ResumeVersionHistory
```

这个四列在 1440 以下太挤，所以实际规则：

```text
width >= 1600:
  version list 300 + preview expanded + insight 320 + right rail 300

1280 <= width < 1600:
  version list 300 + preview expanded + insight 320
  right rail 下移

900 <= width < 1280:
  version list 280 + preview expanded
  insight/right rail 下移为 sections

mobile:
  tabs: 版本 / 预览 / AI 洞察 / 关联
```

### 10.2 ResumeStatsStrip

四个指标：

```text
简历版本
已优化次数
针对岗位版本
最近更新
```

数据来源：

```text
provider.resumeVersions.length
resumeVersion version labels
resumeVersions target_jd_analysis_id count
latest updatedAt
```

### 10.3 ResumeVersionList

元素：

```text
header:
  title 版本列表
  button 生成新版本
  filter icon

version item:
  title
  version label
  purpose / target job
  updatedAt
  score ring or match score if linked report available
  current using chip
```

交互：

```text
click item -> select resume version
生成新版本 -> onSendPrompt 回聊天执行
```

### 10.4 ResumePreviewPanel

元素：

```text
header:
  selected version title
  version chip
  current using chip
  updatedAt

preview body:
  candidate name
  target role
  contact row
  summary
  work experience
  project experience
  skills

footer actions:
  预览简历
  优化此版本
  对比版本
  生成新版本
```

数据原则：

```text
优先使用 ResumeVersion content / artifact 预览；
没有 ResumeVersion 时展示 ResumeProfile 结构化摘要；
不要把长 markdown 直接塞满页面，预览区域限制 max width 并可滚动。
```

### 10.5 ResumeAIInsightPanel

元素：

```text
AI 洞察 / 匹配分析 tabs
score card
strength list
weakness list
recommended rewrite block
reusable experience tags
```

数据来源：

```text
selected detail.readiness
resumeProfile.diagnosis
jobFitReport
learning.weaknesses
```

### 10.6 ResumeRightRail

包含：

```text
CurrentJudgmentCard
RecommendedResumeActionsCard
RelatedJobsCard
RelatedAssetsCard
```

## 11. 左侧产品导航

设计稿左侧结构：

```text
Brand
  logo bolt icon
  求职 Agent
  你的智能求职伙伴

Primary CTA
  + 新建会话

Nav
  总览 count optional
  求职项目 count applications
  简历资料 count resumeLibraryCount
  JD 匹配 count jobMatchLibraryCount
  学习计划 count learningTasks
  笔记 count notes

WorkspaceQuickEntryGrid
  生成简历
  JD 分析
  面试准备
  Agent 助手

AssistantStatusCard
  AI 助理
  在线
```

桌面尺寸：

```text
width: 260
padding: 16
card radius: 16
nav item height: 44
gap: 8
```

折叠侧栏：

```text
width: 76
只显示 icon 和 tooltip；
保留 active state；
隐藏 count 文本但可以显示小 badge。
```

mobile：

```text
ProductSidebar 进入 Drawer/bottom sheet。
顶部只显示菜单 icon + page title + 新建按钮。
```

## 12. 顶部栏

WorkspaceTopBar 结构：

```text
left:
  mobile menu button
  breadcrumb / page title

center:
  GlobalSearchBox
    placeholder: 搜索项目、岗位、笔记，或输入命令（如：分析 JD 匹配度）
    keyboard badge: ⌘ K

right:
  + 新建 split button
  notification icon with badge
  settings icon
  AI avatar
```

响应：

```text
desktop: search maxWidth 620, 居中。
tablet: search Expanded。
mobile: 第一行 title/actions；第二行 search full width。
```

第一版搜索行为：

```text
输入后 Enter：
  如果以“分析/生成/准备/创建”等动词开头，转 ChatScreen 并发送 prompt。
  否则本地过滤当前页面列表。

不做全局索引，不做后端搜索。
```

## 13. 数据与动作边界

页面只读展示：

```text
DashboardPage
CareerProjectsPage
JDMatchPage
ResumeLibraryPage
```

动作按钮：

```text
生成简历
优化简历
JD 分析
面试准备
创建学习任务
保存笔记
推进项目
```

全部调用现有：

```dart
WorkbenchPromptSender onSendPrompt(
  String prompt, {
  CareerWorkbenchActionRequest? action,
})
```

不能直接调用：

```text
learning_task_create
career_resume_version_create
career_application_merge
career_job_fit_report_save
```

例外：

```text
Note 页面当前已有 createNote / updateNote 前端直接 API 能力；
M44 保持现状，不扩大直接写范围。
```

## 14. 分阶段实施

### M44-A：组件拆分与 ProductShell

产出：

```text
1. ProductWorkspaceShell
2. ProductSidebar
3. WorkspaceTopBar
4. Product tokens 和通用卡片组件
5. HomeScreen 接入 workspace page enum
```

验收：

```text
desktop 1440x900：左侧产品导航可见。
mobile 390x844：无横向 overflow，侧栏通过菜单打开。
ChatScreen 仍可打开和发送消息。
flutter analyze 通过。
```

### M44-B：总览页

产出：

```text
DashboardPage
StatusHeroCard
MetricStrip
RecentApplicationsSection
DashboardRightRail
TodayRecommendedActionsSection
```

验收：

```text
用户进入默认页面看到当前求职状态。
无项目时有专业空状态和新建/聊天入口。
有项目时显示 score、推荐动作、最近岗位。
```

### M44-C：求职项目页

产出：

```text
CareerProjectsPage
ProjectOverviewHeader
JobFactStrip
AgentExecutionBoard
ProjectStageTimeline
ProjectRightRail
RiskGapPanel
RecommendedActionPanel
LinkedAssetPanel
```

验收：

```text
第一张设计稿的主信息结构落地。
Agent 进度来自真实 detail/events 或资产推断。
推荐动作仍回聊天执行。
```

### M44-D：JD 匹配页

产出：

```text
JDMatchPage
Match header / score overview / dimension grid
gap analysis / evidence / interview questions / right rail
```

验收：

```text
第二张设计稿的信息结构落地。
不编造不存在的分数。
没有结构化维度时显示等级和说明。
```

### M44-E：简历资料页

产出：

```text
ResumeLibraryPage
Stats strip
Version list
Preview panel
AI insight panel
Version history
Right rail
```

验收：

```text
第四张设计稿的信息结构落地。
可查看简历版本、预览 artifact、触发优化 prompt。
```

### M44-F：收口与截图验收

产出：

```text
widget tests
responsive screenshot checks
视觉问题清单
```

命令：

```bash
cd flutter_app
/home/ubunt/resume_agent/flutter/bin/flutter analyze
/home/ubunt/resume_agent/flutter/bin/flutter test
```

截图尺寸：

```text
desktop: 1440x900
wide desktop: 1728x1000
tablet: 1024x768
mobile: 390x844
```

## 15. 测试计划

新增/更新测试：

```text
flutter_app/test/product_workspace_shell_test.dart
  - desktop 显示 ProductSidebar 和 WorkspaceTopBar。
  - mobile 不显示常驻 sidebar，显示 menu button。
  - 点击 nav 切换页面。

flutter_app/test/dashboard_page_test.dart
  - 展示当前求职状态、指标、最近项目、推荐动作。
  - 空状态不崩溃。

flutter_app/test/career_projects_page_test.dart
  - 展示项目 header、岗位总览、Agent 执行进度、风险、关联资产。
  - 推荐动作调用 onSendPrompt。

flutter_app/test/jd_match_page_test.dart
  - 展示匹配分、维度卡、差距分析、证据依据。
  - 缺少结构化分数字段时不显示伪造百分比。

flutter_app/test/resume_library_page_test.dart
  - 展示版本列表、预览区、AI 洞察、关联岗位。
  - 点击预览调用 artifact preview。

flutter_app/test/responsive_overflow_test.dart
  - 390x844、768x1024、1440x900 pump 关键页面。
  - 捕获 Flutter overflow error。
```

保留现有测试：

```text
home_screen_test.dart
career_workbench_page_test.dart
career_assets_panel_test.dart
run_progress_panel_test.dart
```

如果 M44 拆文件导致旧测试入口变化，保留 `CareerWorkbenchPage` 作为兼容 wrapper，避免测试和外部引用一次性大改。

## 16. 验收标准

产品体感：

```text
打开前端默认进入总览页，而不是空聊天。
用户 5 秒内能知道：当前状态、最重要岗位、下一步动作。
求职项目页能看出完整闭环：岗位 -> 匹配 -> 简历 -> 面试 -> 资产。
JD 匹配页能解释为什么是这个分数。
简历资料页能管理版本和触发优化。
```

工程质量：

```text
不改后端 API 也能完成第一版。
不写死 demo 公司名和固定数字。
移动端没有横向滚动和 RenderFlex overflow。
flutter analyze 通过。
flutter test 通过。
```

回归：

```text
聊天仍可发送。
上传资料仍可用。
求职工作台动作仍回聊天执行。
资产预览仍可用。
Note 编辑仍可用。
```

## 17. 风险与处理

### 风险 1：当前后端字段不足以填满设计稿

处理：

```text
字段不存在就隐藏或显示“待补充”，不硬编码。
可用 readiness / linkedAssets / timeline / suggestedActions 组合出第一版。
后续再补后端字段。
```

### 风险 2：一次性拆太大导致回归

处理：

```text
先加新 ProductShell 和 Dashboard，不删除旧 CareerWorkbenchPage。
每个页面独立接入。
保持 wrapper 兼容。
```

### 风险 3：移动端信息太密

处理：

```text
移动端按任务顺序展示：
状态 -> 下一步 -> 最近岗位 -> 风险 -> 资产。
隐藏非关键指标，使用横向 chips 和折叠 section。
```

### 风险 4：UI 太像静态看板，动作断层

处理：

```text
所有核心卡片都必须有下一步动作：
继续推进 / 生成简历 / 准备面试 / 查看报告 / 新建笔记。
动作必须进入 onSendPrompt 或现有 Note 编辑流程。
```

## 18. 推荐开始顺序

先做：

```text
M44-A ProductShell
M44-B Dashboard
```

原因：

```text
这两步最直接提升“像产品”的第一印象；
不需要改复杂业务页面；
可以尽早验证响应式和整体视觉语言。
```

再做：

```text
M44-C Projects
```

原因：

```text
Projects 是求职闭环主路径，最能承接 Agent 已完成的后端能力。
```

最后做：

```text
M44-D JD Match
M44-E Resume Library
```

原因：

```text
这两页细节多，依赖更多字段和资产预览，适合在 shell 和项目页稳定后推进。
```

## 19. UI 逐块规格附录

本附录按用户提供的 4 张 UI 图拆块，供实现时逐块对照。块编号只用于开发沟通，不要求在代码里保留。

通用约束：

```text
1. 结构和信息层级对齐设计图，不复制固定坐标。
2. 所有块使用 LayoutBuilder / Wrap / Sliver / Flexible 自适应。
3. 所有真实数值来自 API / provider；缺数据时隐藏、显示待补充或显示空状态。
4. 卡片最大圆角 16，按钮和 tag 可用 999 pill。
5. 页面主间距 desktop 20-24，tablet 16-20，mobile 12-16。
6. 字体不随 viewport 缩放；只按组件层级选择固定字号。
7. 移动端顺序优先：判断、下一步、当前项目、风险、资产。
```

### 19.1 全局 Shell 规格

#### S-01 Brand 区

```text
组件：ProductSidebarBrand
位置：左侧导航顶部。
desktop 尺寸：sidebar width 260；brand row height 52。
mobile：在 drawer 顶部，padding 16。

元素：
- logo：40x40，圆角 16，绿色渐变，bolt icon。
- 主标题：求职 Agent，15-16px，fontWeight 800。
- 副标题：你的智能求职伙伴，11-12px，textMuted。

色块：
- logo gradient: #0F9B78 -> #059669。
- sidebar background: #FFFFFF。
- sidebar border-right: #DDE8E4。

交互：
- 点击 brand 回到总览页。
```

#### S-02 新建会话 CTA

```text
组件：ProductPrimaryCreateButton
位置：Brand 下方。
desktop：height 44，width fill。
mobile：drawer 中 width fill；顶部栏另有 compact 新建按钮。

元素：
- left icon: add。
- label: 新建会话。
- right icon: auto_awesome 或 sparkles。

色块：
- background: #0F9B78。
- hover/pressed: #0B7E62。
- text/icon: white。

行为：
- 调用 chatProvider.createNewSession。
- 切换 workspace page 到 chat。
```

#### S-03 主导航

```text
组件：ProductNavList / ProductNavItem
位置：左侧导航中部。

导航项：
- 总览：Icons.home_outlined。
- 求职项目：Icons.business_center_outlined，badge applications。
- 简历资料：Icons.badge_outlined，badge resumeLibraryCount。
- JD 匹配：Icons.analytics_outlined，badge jobMatchLibraryCount。
- 学习计划：Icons.school_outlined，badge learningTasks。
- 笔记：Icons.sticky_note_2_outlined，badge notes。

desktop item：
- height 44。
- padding horizontal 12。
- icon 18。
- label 13。
- badge minWidth 22，height 22。

selected：
- background: #E5F6F1。
- icon/text: #0F9B78。
- border: primary alpha 0.12。

mobile：
- drawer item height 48。
- label 不省略。
- badge 右对齐。
```

#### S-04 工作台快捷入口

```text
组件：WorkspaceQuickEntryGrid
位置：左侧导航下部。
desktop：2x2 grid，每项 minHeight 42。
mobile：drawer 中 2x2。

入口：
- 生成简历：description icon。
- JD 分析：link/search icon。
- 面试准备：chat/message icon。
- Agent 助手：auto_awesome icon。

行为：
- 生成简历/JD 分析/面试准备：切到 chat 并填充或发送对应 prompt。
- Agent 助手：切到 chat。

色块：
- card background: #FFFFFF。
- border: #DDE8E4。
- icon: primary / info / purple / primary。
```

#### S-05 AI 助理状态卡

```text
组件：AssistantStatusCard
位置：左侧导航底部。
desktop：height 64。
mobile：drawer 底部。

元素：
- avatar：36x36，primary circle，group/assistant icon。
- title：AI 助理。
- status：绿色 dot + 在线。
- expand/collapse chevron。

行为：
- 点击切到 chat。
- 后续可展开显示最近 agent 任务，M44 第一版只保留入口。
```

#### S-06 顶部栏

```text
组件：WorkspaceTopBar
位置：主内容顶部，sticky 不强制，desktop 保持页面顶部可见。
desktop height：64。
mobile：两行，第一行 title/actions，第二行 search。

元素：
- mobile menu button。
- breadcrumb 或 page title。
- GlobalSearchBox。
- 新建 split button。
- notification icon + badge。
- settings icon。
- AI avatar。

GlobalSearchBox：
- maxWidth desktop 620。
- height 44。
- icon search。
- placeholder：搜索项目、岗位、笔记，或输入命令（如：分析 JD 匹配度）。
- trailing badge：⌘ K。

行为：
- Enter 命令类文本：切到 chat 并 sendMessage。
- 普通文本：第一版只做当前页面本地过滤。
```

### 19.2 总览页，图 3

#### D-01 当前求职状态 Hero

```text
组件：StatusHeroCard
位置：DashboardPage 主列第一块。
desktop：height 220-260，自适应内容；右侧 score ring。
mobile：单列，score ring 放在标题下或右上角，不使用横向硬排。

元素：
- title：当前求职状态。
- sparkle icon：primary。
- summary：readiness.summary 或聚合提示。
- chips：
  - 目标岗位：active application title / target role。
  - 意向城市：careerProfile target city，缺失显示待补充。
  - 当前阶段：stage label。
- primary button：继续推进岗位，带 arrow icon。
- ProductScoreRing：score，label 综合进度。
- status pill：良好 / 谨慎 / 高风险。

色块：
- background gradient: #EAF8F3 -> #F8FCFA -> #EEF7FF。
- border: #0F9B78 alpha 0.18。
- button: #0F9B78。

数据：
- provider.selectedApplicationSummary。
- provider.selectedApplicationDetail?.readiness。

空状态：
- title：开始建立你的求职工作台。
- button：上传简历 / 新建会话。
```

#### D-02 指标卡条

```text
组件：DashboardMetricStrip
位置：Hero 下方。
desktop：4 columns。
tablet：2 columns。
mobile：1 或 2 columns，按 min item width 156 wrap。

卡片：
1. 已投递岗位
   value: applications.length 或 activeApplications。
   trend: 较上周，第一版无历史则隐藏。
   icon: near_me_outlined，tone info。

2. 匹配度均值
   value: readiness score average。
   suffix: %。
   icon: track_changes，tone primary。

3. 待办任务
   value: learningTasks + suggestedActions count。
   warning text: 其中紧急 N 个。
   icon: checklist，tone warning。

4. 本周学习进度
   value: completed / total 或 readiness learning proxy。
   progress bar。
   icon: menu_book，tone purple。

卡片结构：
- icon tile 52x52。
- value 24px。
- label 12px。
- trend 11px。
```

#### D-03 最近推进中的岗位

```text
组件：RecentApplicationsSection / RecentApplicationCard
位置：Dashboard 主列中部。
desktop：section header + 3 card wrap。
mobile：单列。

section header：
- title：最近推进中的岗位。
- trailing：查看全部。

卡片元素：
- company avatar：48x48，首字/品牌 icon。
- title：岗位名。
- company/location。
- score ring：右上或右侧。
- tags：stage / recommendation / match level。
- latest progress：timeline 最新项或 application updatedAt。
- main advantage：strengths top 1。
- needs improvement：risks top 1。
- primary action：继续跟进 / 准备面试 / 优化简历。
- secondary action：查看详情。

行为：
- 卡片点击：切到求职项目页并 select application。
- primary action：onSendPrompt。
```

#### D-04 今日推荐动作

```text
组件：TodayRecommendedActionsSection
位置：Dashboard 主列底部。
desktop：横向 3 card 或 List。
mobile：单列 action tile。

动作来源：
- selected detail.suggestedActions。
- learning.tasks 中 due today / high priority。
- risks 派生动作。

每项元素：
- icon tile。
- title。
- subtitle。
- CTA：去生成 / 去准备 / 去创建。

行为：
- onSendPrompt + CareerWorkbenchActionRequest。
```

#### D-05 右侧当前判断

```text
组件：DashboardCurrentJudgmentCard
位置：desktop right rail 第一块；mobile 在 Hero 后下沉。

元素：
- title 当前判断。
- updatedAt。
- summary。
- 优势领域：strengths top 2，primary/info tone。
- 待提升领域：risks/weaknesses top 2，warning tone。
- 风险提示：high risk top 1，danger/warning tone。

空状态：
- 暂无项目判断，上传简历和 JD 后生成。
```

#### D-06 推荐下一步

```text
组件：DashboardNextStepCard
位置：right rail 第二块。

元素：
- 1/2/3 index badge。
- action title。
- priority chip：内推优先/提升匹配度/降低风险。
- trailing chevron。
- footer button：查看全部待办。

行为：
- 点击 action 执行 onSendPrompt。
- footer 切到学习计划或项目详情。
```

#### D-07 关联资产摘要

```text
组件：DashboardAssetSummaryCard
位置：right rail 第三块。

元素：
- asset count grid：
  - 简历模板/简历版本。
  - 笔记文档。
  - 面试题库/面试准备。
  - 学习资料/学习任务。
- 最近更新列表 top 3：
  icon + title + type chip + date。

行为：
- 点击 asset 切到对应页面或打开 preview。
```

### 19.3 求职项目页，图 1

#### P-01 页面标题与操作栏

```text
组件：ProjectsPageHeader
位置：WorkspaceTopBar 下方，项目页内容顶部。

元素：
- breadcrumb：求职项目 > 岗位工作台。
- title：求职项目。
- actions：分享 / 导出报告 / 更多操作。

mobile：
- breadcrumb 隐藏，只显示 title。
- actions 收敛到 overflow menu。
```

#### P-02 项目总览 Hero

```text
组件：ProjectOverviewHeader
位置：ProjectsPage 第一块。
desktop：横向 4 区：company/title、score、status、AI summary。
mobile：纵向：title -> score/status -> summary。

元素：
- company logo/avatar 64x64。
- company name。
- official/source badge，有 URL 才显示。
- job title。
- meta：city / degree / years / employment。
- score ring 78 匹配度。
- status block：当前状态、最近更新。
- AI 总结：readiness.summary。
- button：查看完整分析报告。

色块：
- background：#EAF8F3 低饱和渐变。
- border：primary alpha 0.18。
- section divider：#DDE8E4。

数据：
- CareerApplicationWorkbenchView.application。
- jdAnalysis。
- readiness。
```

#### P-03 岗位总览事实条

```text
组件：JobFactStrip
位置：ProjectOverviewHeader 下方。
desktop：6 equal columns。
mobile：horizontal scroll，item minWidth 148。

FactItem：
- 投递时间。
- 岗位来源。
- 招聘类型。
- 岗位热度。
- 竞争人数。
- 期望薪资。

每项元素：
- icon tile 34x34。
- label 11。
- value 13 bold。

缺数据：
- 显示 待补充，不显示假的薪资和人数。
```

#### P-04 面试流程时间线

```text
组件：ProjectStageTimeline
位置：desktop 左中列；mobile 在事实条后。

阶段：
- 简历投递。
- 简历筛选。
- 技术面试。
- 综合面试。
- HR 面试。
- Offer。

元素：
- vertical line。
- circle state marker。
- stage label。
- time。
- status chip。
- footer button：查看全部流程。

状态色：
- completed: primary。
- active: primarySoft + primary border。
- pending: neutral。
- blocked: warning/danger。
```

#### P-05 多 Agent 执行进度

```text
组件：AgentExecutionBoard
位置：desktop 中间主区域。
desktop：横向 StepCard + connector line。
mobile：horizontal scroll cards。

AgentStepCard：
- icon tile。
- agent name：
  - 简历解析 Agent。
  - JD 分析 Agent。
  - 匹配评估 Agent。
  - 简历改写 Agent。
  - 面试准备 Agent。
- status：已完成/进行中/待执行。
- input summary。
- output summary。
- CTA：查看详情 / 继续执行。

数据：
- 优先从 events agent_task_*。
- 第一版可以按产品记录推断完成态。

约束：
- 不展示内部 tool 名。
- 不展示 raw runtime hidden/block。
- 只显示业务阶段。
```

#### P-06 项目右侧判定与进度

```text
组件：ProjectRightRail
位置：desktop 右侧 rail；mobile 下沉。

包含：
1. CurrentProjectJudgmentCard
   - score。
   - recommendation。
   - AI 评价。
   - updatedAt。

2. ProjectProgressChecklistCard
   - completion 3/6。
   - stage checklist。
   - active row highlighted。
   - button 查看全部流程。

3. ProjectLinkedAssetsCompactCard
   - tabs：简历 / 项目 / 笔记 / 资料。
   - top 3 assets。
   - button 查看全部资产。
```

#### P-07 风险与差距

```text
组件：RiskGapPanel
位置：项目页下方左侧。

元素：
- title 风险与差距。
- risk rows top 3。
- 每行：
  - icon tone danger/warning/info。
  - title。
  - description。
  - severity chip：高风险/中风险/低风险。
- footer：查看差距详情与改进建议。

数据：
- readiness.risks。
- learning.weaknesses。
- jobFitReport gaps。
```

#### P-08 推荐动作

```text
组件：RecommendedActionPanel
位置：项目页下方中间。

元素：
- title 推荐动作。
- action rows top 3。
- 每行：
  - icon。
  - title。
  - subtitle。
  - CTA button。
- footer：查看全部推荐动作。

行为：
- action CTA -> onSendPrompt。
```

#### P-09 关联资产

```text
组件：ProjectLinkedAssetPanel
位置：desktop 下方右侧或 right rail；mobile 最后。

元素：
- title 关联资产。
- tabs/chips：简历 / 项目 / 笔记 / 资料。
- asset rows：
  - icon。
  - title。
  - type chip。
  - updatedAt。
- button 查看全部资产。

行为：
- 可预览 artifact 的资产点击打开 preview sheet。
- note 点击打开 note editor。
```

### 19.4 JD 匹配页，图 2

#### J-01 JD 匹配页头

```text
组件：JDMatchHeader
位置：JDMatchPage 第一块。

元素：
- company logo/avatar。
- company name + verified/source marker。
- job title。
- meta：city / district / employment / years。
- one-line jd summary。
- score ring。
- trend：较上次 +N，缺历史隐藏。
- updatedAt。

mobile：
- score ring 放标题下方右对齐或独立行。
- meta chips 横向滚动。
```

#### J-02 分析 Tab 与对比控制

```text
组件：JDMatchControlBar
位置：header 下方。

元素：
- tabs：匹配分析 / 差距分析 / 证据依据 / 面试准备。
- compare dropdown：对比简历。
- refresh button：重新分析。

行为：
- tabs 本地切换。
- compare dropdown 第一版可只显示当前简历。
- 重新分析 -> onSendPrompt。
```

#### J-03 匹配总览

```text
组件：MatchScoreOverview
位置：Tab 下方第一块。

元素：
- large score ring：78%。
- label：匹配度。
- trend。
- optional summary。

色块：
- score >= 80 primary。
- 60-79 warning。
- <60 danger。
```

#### J-04 维度卡网格

```text
组件：MatchDimensionGrid
位置：匹配总览右侧或下方。
desktop：6 cards horizontal。
tablet：3x2。
mobile：2 columns or single column by width。

维度：
- 技术栈匹配。
- 项目经历匹配。
- Agent/LLM 经验。
- 工程化能力。
- 面试准备度。
- 风险项。

每卡元素：
- icon。
- title。
- value：百分比/等级/数量。
- trend：有历史才显示。
- supporting text。

严禁：
- 没有真实结构化分数时硬写 85%、72%。
```

#### J-05 差距分析

```text
组件：GapAnalysisPanel
位置：主区域中部左侧。

元素：
- title 差距分析。
- subtitle 与岗位要求对比。
- gap rows：
  - title。
  - priority chip。
  - left requirement。
  - right suggestion。
  - chevron。
- footer：查看全部 N 项差距。

数据：
- readiness.risks。
- learning.weaknesses。
- jobFitReport gaps。
```

#### J-06 证据依据

```text
组件：EvidencePanel
位置：主区域中部右侧。

元素：
- title 证据依据。
- subtitle 来自你的简历。
- mini tabs：匹配证据 / 缺失证据。
- evidence rows：
  - check icon。
  - evidence title。
  - source chip：项目经历/简历画像/匹配报告。
  - explanation。
- footer：查看全部证据。

数据：
- jobFitReport.evidence_refs。
- resumeProfile.projectExperience。
- linkedAssets。
```

#### J-07 推荐面试题

```text
组件：InterviewQuestionStrip
位置：页面底部主区域。

元素：
- filter chips：全部 / 高频问答 / 技术深挖 / 项目追问 / 系统设计。
- question card：
  - category tag。
  - question。
  - focus points。
  - difficulty。
  - button 查看参考答案。

数据：
- 第一版从 risks + suggestedActions 派生。
- 文案标注“建议准备方向”，不伪装成题库真实数据。
```

#### J-08 右侧当前判断

```text
组件：JDMatchJudgmentRailCard
位置：desktop right rail 第一块。

元素：
- title 当前判断。
- status pill 良好/谨慎/风险。
- summary。
- 优势 box。
- 风险 box。
```

#### J-09 推荐下一步

```text
组件：JDMatchNextStepCard
位置：right rail 第二块。

元素：
- action index 1/2/3。
- title。
- impact chip。
- footer 查看全部行动项。

行为：
- 点击 action -> onSendPrompt。
```

#### J-10 相关简历与笔记

```text
组件：JDMatchRelatedRail
位置：right rail 下方。

块：
- 相关简历：当前对比版本 + 选择其他简历对比。
- 相关笔记：top 3 note rows + 新建笔记。

行为：
- 简历点击切到简历资料页并选中版本。
- 笔记点击打开 Note。
```

### 19.5 简历资料页，图 4

#### R-01 简历资料页头与指标

```text
组件：ResumeStatsStrip
位置：ResumeLibraryPage 顶部。

四个指标：
- 简历版本。
- 已优化次数。
- 针对岗位版本。
- 最近更新。

desktop：4 columns。
mobile：2 columns / 1 column。

数据：
- resumeVersions.length。
- version history count。
- target_jd_analysis_id count。
- latest updatedAt。
```

#### R-02 版本列表

```text
组件：ResumeVersionList
位置：desktop 左侧。
desktop width：300。
mobile：作为 tab page 或第一 section。

元素：
- title 版本列表。
- button 生成新版本。
- filter icon。
- version item：
  - title。
  - version label。
  - purpose/target job。
  - updatedAt。
  - score ring/match score if available。
  - current using chip。
- recycle bin card。

行为：
- 点击 item -> select version。
- 生成新版本 -> onSendPrompt。
```

#### R-03 简历预览面板

```text
组件：ResumePreviewPanel
位置：desktop 中央主区域。

元素：
- header：
  - selected version title。
  - version chip。
  - current using chip。
  - updatedAt。
- preview body：
  - candidate name。
  - target role。
  - contact row。
  - personal summary。
  - work experience。
  - project experience。
  - skills。
- footer actions：
  - 预览简历。
  - 优化此版本。
  - 对比版本。
  - 生成新版本。

视觉：
- preview body 是白底文档感，但不要再套一层大卡中卡。
- 内容区域 maxWidth 720，居中或 left aligned。

数据：
- selected ResumeVersion artifact content。
- fallback ResumeProfile structured fields。
```

#### R-04 AI 洞察面板

```text
组件：ResumeAIInsightPanel
位置：desktop 预览右侧；tablet/mobile 下沉。

tabs：
- AI 洞察。
- 匹配分析。

元素：
- score card。
- 亮点 list。
- 缺失项 list。
- 推荐改写 block。
- 可复用经历 tags。

行为：
- 推荐改写 block 的应用按钮第一版可以填充 prompt，不直接改写记录。
```

#### R-05 当前判断右栏

```text
组件：ResumeCurrentJudgmentCard
位置：right rail 第一块。

元素：
- title 当前判断。
- updatedAt。
- status：匹配度较高/需补齐。
- summary。
- skill tags。

数据：
- selected application readiness。
- selected resume version linked report。
```

#### R-06 推荐动作右栏

```text
组件：ResumeRecommendedActionsCard
位置：right rail 第二块。

动作：
- 优化项目描述，突出业务价值。
- 补充开源项目与技术博客链接。
- 生成针对该岗位的求职信。

每项：
- icon。
- title。
- estimated time。
- click -> onSendPrompt。
```

#### R-07 关联岗位

```text
组件：ResumeRelatedJobsCard
位置：right rail 第三块。

元素：
- job rows top 3。
- title。
- match score chip。
- chevron。

行为：
- 点击切到对应求职项目或 JD 匹配页。
```

#### R-08 关联资产

```text
组件：ResumeRelatedAssetsCard
位置：right rail 第四块。

元素：
- asset rows：
  - icon。
  - title。
  - updatedAt。
- button 查看全部。
```

#### R-09 版本历史

```text
组件：ResumeVersionHistory
位置：desktop 页面底部横向时间线；mobile 折叠 section。

元素：
- version card：
  - version label。
  - change type：优化/针对岗位/当前。
  - date。
  - chevron。
- compare button。

行为：
- 点击 version 选中。
- 对比版本第一版可打开占位 dialog，后续实现 diff。
```

## 20. 实现检查清单

每实现一个页面，都按下面清单自查：

```text
1. 1440x900 无 overflow。
2. 390x844 无横向 overflow。
3. 主 CTA 可点击并进入聊天或目标页面。
4. 缺数据时没有假数字、假公司、假薪资。
5. 所有卡片标题不超过 2 行，超出省略。
6. 所有长列表都有滚动边界。
7. right rail 在 mobile 正确下沉。
8. flutter analyze 通过。
9. 对应 widget test 至少覆盖有数据和空状态。
```
