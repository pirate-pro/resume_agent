# M54 总览页产品化重构方案

日期：2026-06-01

目标：把「总览」页从“当前状态 + 若干卡片”重构成用户打开产品后最先看到的求职指挥台：告诉用户当前整体进度、最重要的项目、今天应该做什么、哪些资产和任务需要关注。本文只整理产品逻辑、页面结构、交互语义和 UI 细则，不直接改代码。

## 1. 当前实现的真实情况

当前页面入口：

```text
flutter_app/lib/features/dashboard/dashboard_page.dart
```

当前数据来源：

```text
careerWorkbenchProvider
├── selectedApplicationSummary
├── selectedApplicationDetail
├── applications
├── counts
├── suggestedActions
└── readiness
```

当前页面结构：

```text
DashboardPage
├── _StatusHeroCard
├── _MetricStrip
├── _RecentApplicationsSection
├── _TodayActionsSection
└── _DashboardRightRail
    ├── 当前判断
    ├── 推荐下一步
    └── 关联资产
```

当前动作入口：

```text
_sendDashboardAction(...)
_sendApplicationAction(...)
```

很多动作会直接发送 prompt。后续应改为：能跳业务页的跳业务页，能就地生成草案的就地生成草案，确实需要 Agent 时再进入 Agent。

## 2. 页面产品定位

总览页不是所有模块的缩略版，也不是统计看板。它应该是：

> 用户每天打开产品后看到的求职推进指挥台，帮助用户判断当前状态、选择最重要的岗位和完成今天最该做的动作。

用户进入总览最关心：

```text
1. 当前整体求职状态怎么样？
2. 哪个岗位最值得继续推进？
3. 今天最该做哪 1-3 件事？
4. 简历、JD 匹配、学习计划、笔记这些模块有没有缺口？
5. 如果我只有几分钟，点哪个按钮最有价值？
```

页面核心不是“所有模块都展示一点”，而是：

```text
当前最重要的判断是什么？
今天最应该推进什么？
哪些内容需要注意但不抢主线？
```

## 3. 信息层级

一级注意力：

```text
当前求职状态 Hero
今日推荐动作
```

二级注意力：

```text
最近推进的岗位
核心指标：已投递、匹配均值、待办任务、学习进度
```

三级注意力：

```text
右侧当前判断
关联资产
学习/笔记/简历提醒
```

四级注意力：

```text
历史项目、已完成动作、内部 ID、低优先级资产
```

## 4. 页面整体布局

桌面端两栏：

```text
DashboardPage
├── MainColumn
│   ├── StatusHero
│   ├── MetricStrip
│   ├── RecentApplications
│   └── TodayActionBoard
└── RightRail
    ├── CurrentJudgement
    ├── RecommendedNextSteps
    └── RelatedAssets
```

布局参数：

```css
.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(720px, 1fr) 340px;
  gap: 20px;
}
```

移动端顺序：

```text
Hero
今日行动
指标
最近岗位
当前判断
关联资产
```

原因：

```text
移动端最重要的是今天做什么，不是看完整数据。
```

## 5. StatusHero

Hero 是总览页核心。

结构：

```text
标题：当前求职状态
一句话判断
标签：目标岗位 / 意向城市 / 当前阶段
主 CTA
综合进度圆环
状态等级
```

主 CTA 规则：

```ts
if no applications:
  label = "开始建立求职项目"
  action = openProjectsCreateFlow
else if selected project has missing materials:
  label = "补齐关键材料"
  action = open selected project
else:
  label = "继续推进岗位"
  action = open selected project
```

Hero 文案要求：

```text
不要堆长报告。
不超过 2 行，告诉用户当前状态和最该做的事。
```

## 6. MetricStrip

指标只做概览，不抢主线。

建议四个指标：

```text
已投递岗位
匹配均值
待办任务
本周学习进度
```

点击行为：

```text
已投递岗位 → 求职项目页，筛选 applied/interviewing。
匹配均值 → JD 匹配页。
待办任务 → 学习计划页。
本周学习进度 → 学习计划页 / 复盘区。
```

样式：

```css
.dashboard-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.dashboard-metric-card {
  height: 82px;
  padding: 16px;
  border-radius: 16px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: 0 4px 16px rgba(15, 35, 25, 0.04);
}
```

## 7. 最近推进的岗位

作用：让用户知道当前有哪些项目，哪个最值得点进去。

展示 3 个即可，更多去求职项目页。

每张岗位卡：

```text
公司 / 岗位
匹配度
阶段
最近进展
主要风险
主按钮：继续推进 / 查看详情
```

不要把所有岗位摊满首页。

空态：

```text
还没有求职项目
可以从上传简历和粘贴 JD 开始，系统会生成第一个岗位工作台。

[创建求职项目] [分析 JD]
```

## 8. 今日行动

这是总览页最重要的“行动模块”。

来源：

```text
selectedApplicationDetail.suggestedActions
readiness.nextActions
learning pending tasks
application.nextActions
fallback actions
```

展示规则：

```text
最多展示 3 条。
按优先级和当前项目关联度排序。
每条必须说明为什么要做。
```

按钮文案：

```text
生成定制简历
准备面试题
创建学习任务
记录复盘
查看匹配差距
```

不要：

```text
去执行
AI 建议
Agent
处理
```

交互：

```text
能直接跳页面的跳页面。
能打开草案的打开草案。
必须对话的才进入 Agent。
```

## 9. 右侧当前判断

当前判断不是重复 Hero，而是解释 Hero 的依据。

展示：

```text
匹配度 / 准备度
主要优势
待提升领域
风险提示
更新时间
```

如果没有数据：

```text
完成简历解析和 JD 匹配后，这里会展示当前判断。
```

## 10. 右侧推荐下一步

右侧推荐下一步和今日行动的区别：

```text
今日行动：今天最该做，最多 3 条，强行动。
右侧推荐：辅助选择，可以是低优先级或后续动作。
```

右侧推荐不要重复所有今日行动。可以放：

```text
查看全部待办
查看学习计划
查看相关笔记
查看简历资料
```

## 11. 关联资产

总览页只展示资产类别和最近更新，不展示长列表。

结构：

```text
简历模板 / 简历版本
笔记文档
面试题库
学习资料
```

点击跳对应页面。

## 12. Agent 动作边界

总览页不应该成为“Agent prompt 面板”。

可以直接跳业务页的：

```text
继续推进岗位
查看 JD 匹配
查看简历资料
查看学习计划
查看笔记
```

需要草案的：

```text
生成学习任务草案
生成简历版本草案
整理复盘草案
```

确实需要 Agent 的：

```text
跨多个模块总结本周求职进展
自由问答
用户输入不明确，需要澄清
```

## 13. 数据动作映射

| UI 内容 | 数据来源 |
| --- | --- |
| 当前状态 | `selectedApplicationSummary.readiness` / `selectedApplicationDetail.readiness` |
| 最近岗位 | `provider.applications.take(3)` |
| 指标 | `workbench.counts` + provider lists |
| 今日行动 | `suggestedActions` + fallback actions |
| 关联资产 | `linkedAssets` / counts |

| UI 动作 | 目标行为 |
| --- | --- |
| 开始建立求职项目 | 打开求职项目创建 |
| 继续推进岗位 | 打开求职项目页并选中当前项目 |
| 生成定制简历 | 打开简历草案流程 |
| 准备面试题 | 打开面试题草案或 Agent |
| 创建学习任务 | 打开学习任务草案 |
| 查看匹配差距 | 打开 JD 匹配页 |

## 14. 组件拆分建议

```text
flutter_app/lib/features/dashboard/
├── dashboard_page.dart
├── widgets/
│   ├── dashboard_status_hero.dart
│   ├── dashboard_metric_strip.dart
│   ├── recent_application_cards.dart
│   ├── today_action_board.dart
│   ├── dashboard_right_rail.dart
│   ├── dashboard_current_judgement.dart
│   └── dashboard_related_assets.dart
└── models/
    └── dashboard_ui_models.dart
```

## 15. 空态

无项目：

```text
欢迎来到求职 Agent
先建立一个目标岗位，系统会围绕简历、JD、匹配、学习和笔记生成推进工作台。

[创建求职项目] [上传简历]
```

有简历无项目：

```text
已准备好基础简历
添加目标 JD 后，可以计算匹配度并生成定制简历。

[分析 JD] [创建项目]
```

有项目但缺下一步：

```text
当前没有明确推荐动作
刷新项目或完成一次 JD 匹配后，系统会重新生成下一步建议。

[刷新] [查看项目]
```

## 16. 响应式

```css
@media (max-width: 900px) {
  .dashboard-grid {
    display: block;
  }

  .dashboard-metric-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .recent-applications {
    display: block;
  }
}
```

移动端优先级：

```text
Hero
今日行动
核心指标
最近岗位
当前判断
资产入口
```

## 17. 验收标准

用户进入总览页后应该能明确知道：

```text
当前整体求职状态。
最重要的一个项目。
今天应该做的 1-3 件事。
每个按钮点击后会去哪个页面或生成什么草案。
没有数据时应该如何开始。
```

最关键的一句话：

> 总览页要从“信息汇总页”，升级成“每日求职推进指挥台”。
