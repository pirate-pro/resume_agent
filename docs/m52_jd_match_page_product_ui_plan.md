# M52 JD 匹配页产品化重构方案

日期：2026-06-01

目标：把「JD 匹配」页从“匹配报告展示 + 若干 Agent 动作”重构成一个解释岗位要求、匹配分数、证据、差距和面试准备方向的分析工作台。本文只整理产品逻辑、页面结构、交互语义和 UI 细则，不直接改代码。

## 1. 当前实现的真实情况

当前页面入口：

```text
flutter_app/lib/features/jd_match/jd_match_page.dart
```

当前数据来源：

```text
careerWorkbenchProvider
├── selectedApplicationSummary
├── selectedApplicationDetail
├── jdAnalyses
├── jobFitReports
├── resumeVersions
├── loadAssetLibrary()
└── activeAction
```

当前页面结构：

```text
JDMatchPage
├── _JDMatchHeader
├── _JDActionBanner
├── _JDHeroCard
├── _JDTabBar
├── _JDMainContent
│   ├── match
│   ├── gaps
│   ├── evidence
│   └── interview
├── _JDLibrarySection
└── _JDRail
    ├── _JDNextStepCard
    └── _JDRelatedAssetsCard
```

当前动作入口：

```text
重新分析 JD 匹配
优化 JD 匹配差距
生成面试准备
推荐下一步
```

这些动作可继续使用 `sendCareerPromptAction`，但 UI 必须区分：

```text
只读分析
生成草案
创建任务
跳转查看
```

## 2. 页面产品定位

JD 匹配页不是一个分数页，也不是 JD 文本查看器。它应该是：

> 解释目标岗位为什么这样匹配、哪些要求已满足、哪些证据不足、下一步如何优化简历和准备面试的岗位分析工作台。

用户进入页面后最关心：

```text
1. 这个岗位要求什么？
2. 我的简历和岗位匹配多少？
3. 分数为什么是这个结果？
4. 哪些差距会影响投递或面试？
5. 下一步应该优化简历、补学习任务，还是准备面试？
```

页面核心不是“78 分”，而是：

```text
为什么是 78 分？
哪些证据支撑这个分数？
哪些差距最该优先处理？
```

## 3. 对象语义

| 对象 | 产品含义 | 页面职责 |
| --- | --- | --- |
| `JDAnalysis` | 岗位要求结构化结果 | 展示硬性要求、加分项、关键词、面试关注点 |
| `JobFitReport` | 简历与 JD 的匹配报告 | 展示分数、优势、差距、证据、推荐动作 |
| `ResumeProfile` | 候选人事实基础 | 解释匹配证据来自哪里 |
| `ResumeVersion` | 面向该 JD 的定制简历 | 关联右侧资产和下一步动作 |
| `CareerReadiness` | 当前项目综合准备度 | 辅助判断是否可以投递 |
| `CareerApplication` | 当前求职项目 | 绑定公司、岗位和阶段 |

关键原则：

```text
JDAnalysis 只说明岗位要求。
JobFitReport 才说明候选人与岗位的匹配关系。
没有 JobFitReport 时，不能展示完整匹配分数。
没有 ResumeProfile 时，不能假装已经完成候选人能力匹配。
```

## 4. 页面整体布局

桌面端两栏：

```text
JDMatchPage
├── MainColumn
│   ├── JDHeader
│   ├── JDHero
│   ├── MatchTabs
│   ├── MatchOverview / GapAnalysis / Evidence / InterviewPrep
│   └── JDLibrary
└── RightRail
    ├── CurrentJudgement
    ├── RecommendedNextSteps
    ├── RelatedResumes
    └── RelatedNotes
```

布局参数：

```css
.jd-page-grid {
  display: grid;
  grid-template-columns: minmax(720px, 1fr) 340px;
  gap: 20px;
}
```

移动端顺序：

```text
Header
Hero
当前判断
推荐下一步
Tabs
当前 Tab 内容
关联简历 / 项目 / 笔记
JD 库
```

## 5. Header

Header 保留确定性动作：

```text
左侧：JD 匹配 + 智能分析
右侧：当前求职项目 / 刷新 / 重新分析
```

按钮语义：

```text
当前求职项目：回到求职项目页或打开项目选择。
刷新：刷新 workbench + asset library。
重新分析：基于当前 ResumeProfile、CareerProfile、JDAnalysis 重新生成 JobFitReport。
```

不要把“重新分析”做成无反馈 prompt。点击后应出现：

```text
正在重新分析匹配
完成后会刷新：匹配分数、差距、证据、面试准备建议。
```

## 6. JD Hero

Hero 展示岗位和匹配总判断。

结构：

```text
公司 Logo
公司 / 岗位
地点 / 年限 / 更新时间
匹配度圆环
较上次变化
整体判断
```

核心字段：

```text
JD 标题：application.company + application.position 或 jd.displayTitle
匹配度：jobFitReport.overallScore
推荐等级：jobFitReport.recommendation / readiness.level
更新时间：report.meta.updatedAt / jd.meta.updatedAt
```

如果缺 report：

```text
已解析 JD，尚未生成匹配报告
```

主 CTA：

```text
生成匹配报告
```

## 7. Tab 结构

当前已有四个 Tab，保留但调整语义：

```text
匹配分析
差距分析
证据依据
面试准备
```

### 匹配分析

回答：

```text
整体匹配多少？
每个维度多少？
主要优势是什么？
主要风险是什么？
```

组件：

```text
ScoreSummaryCard
ScoreBreakdownGrid
StrengthsCard
RisksCard
```

### 证据依据

证据依据页不能只展示“已命中 / 未命中”两列。它的核心任务是让用户把缺失证据补进去，并明确这些证据会沉淀到哪里。

桌面端结构：

```text
EvidenceTab
├── 左侧：证据覆盖区
│   ├── 已命中证据
│   ├── 未命中要求
│   └── 来源引用
├── 中间/右侧：补充项目证据面板（按需打开）
│   ├── 证据标题
│   ├── 关联项目
│   ├── 补充描述
│   ├── 关键技术点
│   ├── 量化成果
│   └── 附件/引用：当前 JD / 匹配报告
└── 右侧栏：当前判断 / 推荐下一步 / 相关资料 / 相关笔记
```

交互规则：

```text
1. 点击未命中要求中的「补充证据」或差距动作中的「补充项目证据」，在当前 JD 页内打开证据面板。
2. 不跳转 Agent 会话，不直接 sendCareerPromptAction。
3. 保存时如果后端没有专用 ProjectEvidence API，则先保存为 Note：
   note_type = note
   origin = jd_match
   tags = ["项目证据", "JD匹配", ...关键技术点]
   related_application_id = 当前 application_id
   evidence_refs = [application_id, jd_analysis_id, job_fit_report_id]
4. 保存成功后刷新 notes / application detail，并在右侧相关笔记中可见。
5. 成功提示要说明：已保存为项目证据笔记；建议重新分析匹配让新证据参与评分。
```

证据依据 Tab 激活时，右侧「推荐下一步」不能继续展示通用的简历/学习/面试动作，必须切换成补证据动作：

```text
补充 LangGraph 实践经验
完善 RAG 评估与量化数据
补充高并发 SSE 优化数据
查看全部建议
```

这些动作点击后应在当前页打开「补充项目证据」面板，并预填证据标题、关联项目、补充描述和关键技术点；不要跳转到 Agent 会话。

面板字段：

```text
证据标题：必填，默认带入未命中要求标题。
关联项目：必填，默认当前求职项目。
补充描述：必填，说明项目背景、个人贡献和实现细节。
关键技术点：可选，逗号或空格分隔。
量化成果：可选，记录延迟、吞吐、成本、稳定性、准确率等结果。
附件/引用：第一阶段展示当前 JD 与匹配报告引用，不做文件上传。
```

按钮：

```text
取消
保存为项目证据
```

样式要求：

```text
面板宽度：桌面端约 430px。
面板圆角：16px。
面板背景：#FFFFFF。
保存按钮：主绿色 #0F9F6E。
取消按钮：白底描边。
必填项错误：使用红色辅助文案，不要只禁用按钮。
```

### 差距分析

回答：

```text
最影响岗位匹配的 3-5 个差距是什么？
每个差距应该优化简历、学习补齐，还是面试准备？
```

每条差距：

```text
标题
影响程度
关联 JD 要求
当前证据缺口
建议动作：优化简历 / 转学习任务 / 准备面试
```

### 证据依据

回答：

```text
哪些简历事实支撑了匹配分数？
哪些 JD 要求没有找到证据？
```

结构：

```text
匹配证据
未命中要求
来源引用
```

### 面试准备

回答：

```text
如果进入面试，会被追问什么？
应该怎么组织回答？
```

卡片：

```text
问题
考察点
回答要点
参考证据
动作：保存为笔记 / 生成模拟问答
```

## 8. 右侧推荐下一步

推荐动作不要泛化。

| 条件 | 动作 |
| --- | --- |
| `report.resumeOptimizationDirection` 不空 | 根据差距优化简历 |
| `report.interviewPreparationFocus` 不空 | 生成面试准备清单 |
| `report.gaps` 中有学习类差距 | 转成学习任务 |
| 有目标 JD 但无定制简历 | 生成岗位定制简历 |
| 有证据不足 | 补充项目证据 |

按钮文案：

```text
优化简历差距
创建学习任务
生成面试题
补充项目证据
生成定制简历
```

禁止：

```text
AI 建议
Agent
去执行
处理
```

## 9. JD Library

JD 库是辅助入口，不应压过当前分析。

显示：

```text
JDAnalysis 列表
JobFitReport 列表
关联项目数量
更新时间
```

点击行为：

```text
点击 JDAnalysis：切换当前 JD，如果有关联项目则切换项目。
点击 JobFitReport：切换到对应项目和报告。
```

如果只是孤立 JD，没有项目：

```text
可显示“未绑定项目”，按钮：创建求职项目。
```

## 10. Agent / 草案边界

JD 匹配页允许 Agent 做三类事情：

```text
1. 重新生成 JobFitReport。
2. 根据差距生成简历优化草案。
3. 根据面试关注点生成问题草案。
```

但结果必须就地展示：

```text
重新分析结果刷新当前报告。
简历优化进入 ResumeVersionDraftDialog。
面试题进入 InterviewQuestionDraftDialog。
学习任务进入 LearningTaskDraftDialog。
```

不要点击后直接跳聊天页。

## 11. 数据动作映射

| UI 内容 | 数据来源 |
| --- | --- |
| JD 要求 | `JDAnalysisView` |
| 匹配分数 | `JobFitReportView.overallScore` |
| 维度分 | `scoreBreakdown` |
| 匹配证据 | `matchedEvidence` |
| 差距 | `gaps` |
| 简历优化方向 | `resumeOptimizationDirection` |
| 面试准备重点 | `interviewPreparationFocus` |
| 关联简历 | `ResumeVersionView.targetJdAnalysisId` |
| 关联项目 | `CareerApplicationView.jdAnalysisId` |

| UI 动作 | 当前/目标动作 |
| --- | --- |
| 刷新 | `provider.refresh()` + `loadAssetLibrary()` |
| 重新分析 | 当前 `sendCareerPromptAction(jd_match_analysis)`；长期专用 API |
| 优化简历 | 打开简历草案生成，不直接跳 Agent |
| 创建学习任务 | 打开学习任务草案 |
| 生成面试题 | 打开面试题草案 |
| 保存为笔记 | 创建 note |

## 12. 空状态

没有 JD：

```text
还没有 JD 分析
粘贴岗位描述或关联求职项目后，系统会解析岗位要求并生成匹配报告。

[粘贴 JD] [选择求职项目]
```

有 JD、无简历画像：

```text
已解析 JD，但缺少基础简历画像
上传简历后才能计算匹配度和候选人证据。

[上传简历]
```

有 JD 和简历、无报告：

```text
可以开始匹配分析
系统会结合岗位要求、简历画像和职业画像生成匹配分数、证据和差距。

[生成匹配报告]
```

## 13. 组件拆分建议

```text
flutter_app/lib/features/jd_match/
├── jd_match_page.dart
├── widgets/
│   ├── jd_match_header.dart
│   ├── jd_match_hero.dart
│   ├── jd_match_tabs.dart
│   ├── match_overview.dart
│   ├── gap_analysis_panel.dart
│   ├── evidence_panel.dart
│   ├── interview_prep_panel.dart
│   ├── jd_right_rail.dart
│   ├── jd_next_actions.dart
│   ├── jd_library_section.dart
│   └── jd_draft_dialogs.dart
└── models/
    └── jd_match_ui_models.dart
```

## 14. 响应式

```css
@media (max-width: 900px) {
  .jd-page-grid {
    display: block;
  }

  .score-breakdown-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .jd-right-rail {
    width: auto;
    margin: 14px 0;
  }
}
```

## 15. 验收标准

用户应该能明确知道：

```text
当前匹配分数从哪里来。
每个差距对应哪个 JD 要求。
每个证据来自简历还是项目记录。
下一步动作会生成什么草案或更新什么记录。
没有报告时页面不会假装已有匹配结果。
```

最关键的一句话：

> JD 匹配页要从“分数展示”，升级成“岗位差距解释与行动转化页”。

## 16. 本轮落地前检查清单

> 日期：2026-06-01  
> 状态：实现前补充，用于约束本轮 JD 匹配页二次修正。后续修改要先对照这份清单，避免只改视觉而留下不可用入口。

### 16.1 参考目标

本轮以用户提供的四张 JD 匹配参考图为准，合理还原这些产品点：

```text
1. 页面首屏必须像“岗位差距解释与行动转化工作台”，不是普通分数看板。
2. Hero 要清楚展示岗位、匹配分、当前判断、主行动。
3. Tab 内容要能解释：匹配分析、差距分析、证据依据、面试准备。
4. 右侧栏要固定承接：当前判断、推荐下一步、相关资料、相关笔记。
5. 所有可点击动作都要有明确产品语义，不能出现泛化“执行”“AI 建议”“处理”。
```

### 16.2 功能完整性底线

这轮允许继续复用现有 `sendCareerPromptAction`，但不能出现“看起来能点，实际没有反馈”的入口。所有入口至少要满足一种结果：

```text
1. 就地切换当前 Tab。
2. 触发现有 action banner 并说明会刷新哪些区域。
3. 跳转到明确页面，例如简历资料、学习计划、求职项目。
4. 打开明确弹窗或抽屉；如果后端还没有专用 API，要在文案上说明是草案/当前 action pipeline。
```

不允许：

```text
1. 按钮点击后无反馈。
2. 泛化按钮文案：执行、处理、AI 建议。
3. 没有 JobFitReport 时假装已有完整匹配结果。
4. 证据、差距、面试准备混在一个卡片里导致用户不知道下一步。
5. 视觉上出现明显溢出、跨行按钮、卡片挤压或右侧栏信息密度失衡。
```

### 16.3 当前必须覆盖的交互

| 区域 | 动作 | 本轮最低行为 |
| --- | --- | --- |
| Header | 全局搜索/会话/新建 | 使用外层工作台统一头部，JD 页内部不再额外渲染一排页面级操作按钮 |
| Hero | 重新分析 | 触发 `jd_match_analysis`，显示 action banner |
| Hero | 优化匹配 | 有报告时进入差距优化路径；无报告时引导生成匹配报告 |
| Tab | 匹配分析 | 展示总分、维度分、优势、风险 |
| Tab | 差距分析 | 展示差距优先级，并提供优化简历、创建学习任务、补充证据、准备面试 |
| Tab | 证据依据 | 区分已命中证据、未命中要求、来源引用 |
| Tab | 面试准备 | 展示问题方向、准备指标，生成面试题有反馈 |
| 右侧推荐 | 优化简历差距 | 触发简历优化 action |
| 右侧推荐 | 创建学习任务 | 跳学习计划或触发学习任务草案入口 |
| 右侧推荐 | 生成面试题 | 切到面试准备并触发面试题 action |
| 相关资料 | 资料项 | 至少可见类型与更新时间，不混淆 JD 与匹配报告 |
| 相关笔记 | 笔记项 | 有笔记时展示，无笔记时解释如何生成 |

### 16.4 截图验收

每次结束前至少检查：

```text
1. 桌面宽屏：约 1920x1080。
2. 窄屏：约 390x844 或接近移动端。
3. 默认匹配分析 Tab。
4. 差距分析 Tab。
5. 证据依据 Tab。
6. 面试准备 Tab。
```

截图观察点：

```text
1. Hero 是否第一眼能看懂岗位、分数和当前判断。
2. 主行动按钮是否清楚且不跨行。
3. 右侧栏是否紧凑但不拥挤。
4. Tab 内容是否有足够信息密度，不是空白大卡。
5. 差距分析是否能解释“为什么要行动”。
6. 证据依据是否区分已命中和未命中。
7. 面试准备是否不是单纯问题列表，而是准备工作台。
8. 移动端内容顺序是否合理：Hero -> 判断/下一步 -> Tabs -> 内容。
```

### 16.5 已知边界

本轮不强行新增后端专用草案 API。当前结构化草案能力仍分阶段推进：

```text
1. 重新分析匹配：继续走 `sendCareerPromptAction(jd_match_analysis)`。
2. 简历差距优化：短期走 `resume_optimize` action；长期接 ResumeVersionDraft API。
3. 学习任务：已有学习任务 draft API，但 JD 页第一步可先跳学习计划或发起 task action。
4. 面试题：短期走 `interview_prep` action；长期接 InterviewQuestionDraft API。
5. 补充项目证据：短期用 action/banner 或弹窗占位；长期接 Evidence API。
```

如果某个入口还没有专用 API，UI 必须通过文案告诉用户“生成草案 / 当前页会刷新”，不能表现成已经有完整确定性落库能力。

## 17. 本轮截图复查后的修正项

桌面截图对照参考图后，本轮必须修掉以下问题再结束：

```text
1. 页面外层 workspace 已经提供“JD 匹配 / 分析岗位要求、匹配度和差距”，JD 页内部不应再渲染一套重复标题。
2. 面试准备卡片里的“保存为笔记 / 模拟问答 / 展开要点”不能只是视觉按钮，必须分别落到确定动作：
   - 保存为笔记：直接创建面试准备笔记，失败时给出错误提示。
   - 模拟问答：触发现有 interview_prep action，并通过页面 action banner 反馈。
   - 展开要点：打开就地详情弹窗，展示考察点和回答组织。
3. 面试准备详情弹窗里继续保留“保存为笔记”和“模拟问答”，避免用户只能在卡片上操作。
4. 如果保存笔记缺少 source_session_id，要显示明确失败原因，不能静默无反应。
5. 修正后重新构建 web，并分别截图默认 Tab、差距 Tab、证据 Tab、面试 Tab 和移动端。
6. 后端返回的评分维度 key 不能原样暴露到 UI；`technical_stack`、`technical stack`、`skills` 等都要映射成中文产品文案，例如“技术栈匹配”。
7. 移动端不能把“相关资料 / 相关笔记”插在 Tab 内容前面；移动端顺序必须是 Hero -> 当前判断/推荐下一步 -> Tab/当前内容 -> 相关资料/笔记。
```

这部分属于功能完整性修正，不新增新的后端草案 API，也不扩大 JD 页范围。

## 18. 证据依据打开态对齐补充

针对参考图中的「证据依据 + 补充项目证据」打开态，本轮按以下规则验收：

```text
1. 点击未命中要求中的「补充证据」后，在主区和右侧上下文之间插入页面级补证据表单，不跳转聊天页。
2. 主区继续展示已命中证据、未命中要求和来源引用，用户不会丢失当前分析上下文。
3. 证据行不能只是单行清单，需要展示证据说明、来源或版本标签，让用户知道证据来自哪里。
4. 补证据表单必须包含：证据标题、关联项目、补充描述、关键技术点、量化成果、附件/引用。
5. 量化成果区域保留「添加成果」动作，用于提醒用户补充可验证指标，而不是只留一个普通输入框。
```

视觉对齐要求：

```text
主区：已命中证据用浅绿/浅蓝证据卡，未命中要求用浅橙警示卡。
右侧补证据面板：宽度约 430px，作为页面级侧栏插入主区和右侧上下文之间。
表单底部：取消为次按钮，保存为项目证据为主绿色按钮。
证据列表：筛选行显示全部/已命中/未命中数量，首屏每列只展示 4 条摘要，完整列表通过「查看全部已命中证据 / 查看全部未命中要求」承接，保证来源引用表在首屏可见。
未命中区：优先使用 `JobFitReport.gaps` 解释真实差距；只有报告缺口为空时，才从 JD required/preferred skills 中推导未覆盖项。
Hero 操作：目标打开态使用「重新分析 / 优化匹配」两枚按钮，不在 Hero 上混入「生成定制简历」。
```
