# M51 求职项目页产品化重构方案

日期：2026-06-01

目标：把「求职项目」页从“岗位数据 + Agent 动作入口”重构成一个围绕单个目标岗位推进投递、简历、JD 匹配、面试准备和风险处理的项目工作台。本文只整理产品逻辑、页面结构、交互语义和 UI 细则，不直接改代码。

## 1. 当前实现的真实情况

当前页面入口：

```text
flutter_app/lib/features/projects/career_projects_page.dart
```

当前数据来源：

```text
careerWorkbenchProvider
├── getCareerWorkbench()
├── selectedApplicationSummary
├── selectedApplicationDetail
├── applications
├── activeAction
└── suggestedActions
```

当前页面主要结构：

```text
CareerProjectsPage
├── _ProjectHeader
├── _ProjectActionBanner
├── _ProjectHeroCard
├── _PositionOverviewCard
├── _ExecutionBoard
├── _RiskActionGrid
└── _ProjectRightRail
    ├── _ProjectJudgmentCard
    ├── _ProjectProgressCard
    └── _ProjectLinkedAssetsCard
```

当前动作入口主要通过：

```text
sendCareerPromptAction(...)
```

也就是说，很多动作本质是给 Agent 发送 prompt，再由 Agent 决定执行过程。这个机制可以保留，但页面必须把“用户点击了什么、当前页会出现什么反馈、成功后哪个模块会变化”讲清楚，不能让所有按钮都像“去执行”。

## 2. 页面产品定位

求职项目页不是岗位列表，也不是 Agent 操作台。它应该是：

> 围绕一个目标岗位，展示当前投递状态、材料完整度、执行进度、风险差距和下一步动作的岗位推进工作台。

用户进入页面后最关心：

```text
1. 这个岗位现在推进到哪一步？
2. 我是否已经完成 JD 匹配、简历定制、投递前检查、面试准备？
3. 当前最大的风险是什么？
4. 今天我应该继续做哪一件事？
5. 相关简历、JD、匹配报告、笔记和学习任务在哪里？
```

页面核心不是“有多少项目”，而是：

```text
当前项目能不能继续推进？
缺什么材料？
下一步怎么做？
做完后状态如何更新？
```

## 3. 核心对象语义

| 对象 | 产品含义 | 页面职责 |
| --- | --- | --- |
| `CareerApplication` | 一个目标岗位项目 | 页面的主对象 |
| `JDAnalysis` | 岗位要求解析 | 解释岗位来源和要求 |
| `JobFitReport` | 简历与岗位匹配判断 | 决定风险、匹配度和优化方向 |
| `ResumeProfile` | 基础简历画像 | 判断候选人事实来源 |
| `ResumeVersion` | 可投递简历版本 | 项目推进中的关键产物 |
| `CareerReadiness` | 当前综合判断 | Hero、右侧判断和风险入口 |
| `CareerSuggestedAction` | 建议动作 | 页面动作候选，但文案必须产品化 |
| `CareerLinkedAsset` | 项目相关资产 | 右侧关联资产和底部材料入口 |

关键边界：

```text
求职项目页负责“推进项目状态”。
JD 匹配页负责“解释匹配为什么是这个结果”。
简历资料页负责“管理可投递简历版本”。
学习计划页负责“把能力短板变成学习任务”。
Agent 只负责生成草案、执行复杂动作或补全内容，不负责替代页面状态机。
```

## 4. 页面整体布局

桌面端推荐两栏：

```text
CareerProjectsPage
├── MainColumn
│   ├── ProjectHeader
│   ├── ProjectHero
│   ├── ProjectFactStrip
│   ├── ProjectWorkflow
│   ├── RiskAndNextActionGrid
│   └── Timeline / NotesPreview
└── RightRail
    ├── CurrentJudgementCard
    ├── ProjectProgressCard
    ├── LinkedAssetsCard
    └── RelatedNotesCard
```

布局参数：

```css
.project-page-grid {
  display: grid;
  grid-template-columns: minmax(720px, 1fr) 340px;
  gap: 20px;
}

.project-main {
  min-width: 0;
}

.project-right-rail {
  width: 340px;
}
```

移动端顺序：

```text
Header
Hero
当前判断
项目进度
岗位事实
执行流程
风险与下一步
关联资产
笔记 / 时间线
```

## 5. 视觉 Token

沿用 M47-M50 产品 Token。

```css
:root {
  --bg-page: #F6FAF8;
  --bg-card: #FFFFFF;
  --primary: #0F9F6E;
  --primary-hover: #0B8A5F;
  --primary-light: #E8F7F0;
  --border: #E2ECE7;
  --border-strong: #CFE3DA;
  --text-main: #1F2933;
  --text-secondary: #667085;
  --text-tertiary: #98A2B3;
  --blue: #3B82F6;
  --blue-light: #EEF5FF;
  --orange: #F59E0B;
  --orange-light: #FFF7E8;
  --danger: #EF4444;
  --danger-light: #FFF1F1;
  --shadow-soft: 0 4px 16px rgba(15, 35, 25, 0.04);
}
```

## 6. Header

Header 职责：选择项目、筛选项目、刷新，不做复杂 Agent 入口。

推荐结构：

```text
左侧：
  求职项目
  围绕目标岗位推进简历、匹配、投递和面试

右侧：
  项目筛选
  项目选择器
  刷新
  新建项目
```

按钮语义：

```text
刷新：重新拉取工作台和当前项目详情。
新建项目：打开新建项目流程，不直接发一段 prompt。
项目选择器：切换 selectedApplicationId。
项目筛选：筛选 draft / ready / applied / interviewing / paused。
```

样式：

```css
.project-header {
  min-height: 72px;
  padding: 16px;
  border-radius: 18px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: var(--shadow-soft);
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.project-title {
  font-size: 22px;
  font-weight: 800;
  color: #1F2933;
}

.project-subtitle {
  margin-top: 5px;
  font-size: 13px;
  color: #667085;
}
```

## 7. Project Hero

Hero 是项目页的一级注意力。它应该回答：

```text
这个岗位是谁？
当前匹配/准备度是多少？
当前阶段是什么？
下一步最该做什么？
```

结构：

```text
ProjectHero
├── 公司 Logo / 占位图标
├── 公司 + 岗位
├── 地点 / 阶段 / 优先级 / 更新时间
├── 综合评分环
├── 当前状态判断
└── 主 CTA
```

主 CTA 规则：

```ts
if missing JDAnalysis:
  primary = "分析 JD 匹配"
else if missing ResumeVersion:
  primary = "生成定制简历"
else if stage is draft or ready_to_apply:
  primary = "投递前检查"
else if stage is interviewing:
  primary = "准备面试"
else:
  primary = "查看下一步"
```

注意：

```text
主 CTA 必须是确定动作，不写“Agent 执行”。
点击后在当前页显示 ActionBanner 或草案弹窗，不要让用户无感跳转。
```

## 8. 岗位事实条

作用：让用户快速知道岗位的基础事实。

字段：

```text
投递时间 / 来源渠道 / 招聘类型 / 岗位热度 / 竞争人数 / 薪资范围
```

数据缺失时：

```text
显示“待补充”，不要用 mock 数字。
```

样式：

```css
.project-fact-strip {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0;
  padding: 14px 16px;
  border-radius: 16px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
}

.project-fact-label {
  font-size: 12px;
  color: #98A2B3;
}

.project-fact-value {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 700;
  color: #1F2933;
}
```

## 9. 执行流程 ProjectWorkflow

这是项目页最重要的二级模块。它不是“Agent 执行进度卡”，而是项目生命周期。

推荐阶段：

```text
1. 简历投递
2. 简历筛选
3. 技术面试
4. 综合面试
5. HR 面试
6. Offer
```

每个节点字段：

```text
阶段名
状态：已完成 / 进行中 / 未开始 / 阻塞
完成时间或预计时间
关联产物：简历版本、匹配报告、面试准备、复盘笔记
动作：查看详情 / 推进阶段 / 记录复盘
```

状态流转：

```text
用户可以手动修改项目阶段。
Agent 可以给建议，但不自动修改阶段，除非用户确认。
阶段变化后刷新 CareerApplication.stage 和 timeline。
```

## 10. 风险与下一步

左侧风险，右侧推荐动作。

风险来源：

```text
readiness.risks
application.risks
job_fit_report.gaps
resume_version.risk_notes
interview reviews
```

推荐动作来源：

```text
detail.suggestedActions
fallback actions
```

但按钮文案必须明确：

| 动作类型 | 按钮文案 |
| --- | --- |
| `custom_resume` | 生成定制简历 |
| `resume_optimize` | 优化当前简历 |
| `jd_match_analysis` | 重新分析匹配 |
| `interview_prep` | 准备面试题 |
| `learning_task` | 转成学习任务 |
| `note_review` | 记录复盘 |

不要显示：

```text
去执行
Agent
更多操作
处理
```

## 11. 右侧栏

右侧栏固定四块。

```text
ProjectRightRail
├── 当前判断
├── 求职进度
├── 关联资产
└── 关联笔记
```

### 当前判断

展示：

```text
准备度评分
判断等级
优势领域
待提升领域
最后更新时间
```

如果没有 readiness：

```text
完成简历解析和 JD 匹配后，这里会生成当前项目判断。
```

### 求职进度

展示生命周期节点，右侧小卡不展示长报告。

### 关联资产

只放关键资产：

```text
基础简历画像
JD 分析
匹配报告
当前简历版本
面试准备笔记
学习任务
```

### 关联笔记

显示最近 3 条，按钮：

```text
查看全部
新建复盘
```

## 12. ActionBanner

当前已有 `provider.activeAction`。它应该只显示“正在做什么”和“完成后哪里会变化”。

文案：

```text
正在生成定制简历
完成后会刷新：简历版本、关联资产和项目下一步。
```

不要写：

```text
Agent 正在处理
```

状态：

```text
running：显示 spinner。
completed：显示完成摘要 + 查看产物。
failed：显示错误 + 重试。
```

## 13. 新建项目流程

不要简单跳聊天页。

推荐流程：

```text
点击新建项目
↓
打开 CreateProjectDialog
↓
填写：公司、岗位、地点、JD 文本/链接、优先级、来源
↓
保存 CareerApplication 草案
↓
可选：立即分析 JD 匹配
```

第一阶段如果后端还没有确定性创建项目 API，可以用 Agent，但 UI 必须显示：

```text
正在创建项目草案
创建失败 / 创建成功
```

不能只发 prompt 然后跳聊天。

## 14. 数据动作映射

| UI 动作 | 当前/目标动作 |
| --- | --- |
| 刷新 | `provider.refresh()` |
| 切换项目 | `provider.selectApplication(applicationId)` |
| 筛选项目 | `provider.setProjectFilter(filter)` |
| 打开详情 | `provider.loadApplicationDetail(applicationId)` |
| 生成定制简历 | 当前 `sendCareerPromptAction(custom_resume)`；长期结构化草案 |
| 投递前检查 | `sendCareerPromptAction(preflight_check)` |
| 准备面试 | `sendCareerPromptAction(interview_prep)` |
| 转学习任务 | 打开学习任务草案，不直接跳 Agent |
| 修改阶段 | 目标：确定性 update application stage |

## 15. 组件拆分建议

```text
flutter_app/lib/features/projects/
├── career_projects_page.dart
├── widgets/
│   ├── project_header.dart
│   ├── project_selector.dart
│   ├── project_hero.dart
│   ├── project_fact_strip.dart
│   ├── project_workflow.dart
│   ├── project_risk_panel.dart
│   ├── project_next_actions.dart
│   ├── project_right_rail.dart
│   ├── project_linked_assets.dart
│   └── create_project_dialog.dart
└── models/
    └── project_ui_models.dart
```

## 16. 空状态

无项目：

```text
还没有求职项目
上传简历和目标 JD 后，系统会生成第一个岗位工作台。

[新建项目] [上传 JD]
```

有项目但缺 JD：

```text
当前项目还没有 JD 分析
补充岗位描述后才能计算匹配度和生成定制简历。

[补充 JD] [查看项目资料]
```

有 JD 但缺匹配报告：

```text
JD 已解析，尚未完成匹配分析
匹配分析会结合基础简历和职业画像，生成差距、风险和面试准备方向。

[分析匹配]
```

## 17. 响应式

```css
@media (max-width: 900px) {
  .project-page-grid {
    display: block;
  }

  .project-right-rail {
    width: auto;
    margin: 14px 0;
  }

  .project-fact-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}
```

移动端优先顺序：

```text
当前岗位与主 CTA
当前判断
求职进度
风险与下一步
岗位事实
关联资产
历史记录
```

## 18. 验收标准

改完后用户应该能明确知道：

```text
这个页面只服务当前求职项目。
当前阶段是什么。
下一步最该做什么。
JD、匹配报告、简历版本、学习任务分别是否齐全。
每个 Agent 动作点击后会在当前页产生什么结果。
```

最关键的一句话：

> 求职项目页要从“岗位信息展示”，升级成“岗位推进控制台”。
