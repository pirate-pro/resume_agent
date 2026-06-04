# M55 Frontend Button Wiring And Backend Gap Audit

## 目标

最近几个产品页已经从“Agent 聊天入口”改成工作台形态，但仍存在一类产品风险：

```text
按钮看起来能点，点击后没有反馈；
按钮文案像真实功能，但背后只是 prompt 或占位；
同一个动作在不同页面跳转、弹窗、Agent 执行三种行为混用。
```

M55 的目标不是继续做视觉重构，而是收敛交互契约：

```text
每个可点击元素必须落到四类之一：
1. 确定性页面跳转
2. 当前页弹窗 / 抽屉 / 展开
3. 后端 API / Agent action，并显示运行状态
4. 明确的不可用说明或 SnackBar
```

不能再保留空回调、假按钮或无反馈禁用按钮。

## 已确认有后端通路的动作

这些动作可以继续作为真实功能入口：

| 页面 | 动作 | 当前通路 |
| --- | --- | --- |
| 学习计划 | AI 生成任务草案 | `POST /api/learning-admin/task-drafts/generate` |
| 学习计划 | 采纳学习任务草案 | `createLearningTask(...)` |
| 学习计划 | 记录学习进度 | `createLearningCheckin(...)` |
| 学习计划 | 拖动任务状态 | `updateLearningTaskState(...)` |
| 学习计划 | 删除任务 | `archiveLearningTask(...)` |
| 笔记 | 新建笔记 | `createNote(...)` |
| 笔记 | 追加记录 | `appendNote(...)` |
| 笔记 | 归档笔记 | `archiveNote(...)` |
| 笔记 | 行动项采纳为学习任务 | `createLearningTask(...)` |
| JD 匹配 | 保存项目证据 | 当前落为项目关联 Note |
| 简历资料 | 生成岗位定制版 | `POST /api/career/resume-version-drafts/generate` |
| 简历资料 | 保存岗位定制草案 | `POST /api/career/resume-version-drafts/{id}/accept` |

约束：

```text
AI 生成任务草案只生成 draft，不直接落库；
用户确认采纳后才创建 LearningTask；
笔记页草案类能力在结构化 API 完成前，不应伪装成已完整后端化。
```

## 当前仍是 Agent Action 的动作

这些动作不是空按钮，但结果仍主要依赖 `sendCareerPromptAction(...)` 和工作台刷新：

| 页面 | 动作 | 当前行为 |
| --- | --- | --- |
| 求职项目 | 生成定制简历 | 打开确认弹窗后发送 `custom_resume` action |
| 求职项目 | 投递前检查 | 发送对应 action，并通过 ActionBanner 反馈 |
| JD 匹配 | 重新分析匹配 | 发送 `jd_match_analysis` action |
| JD 匹配 | 生成定制简历 | 发送 `custom_resume` action |
| 简历资料 | 优化此版本 | 发送 resume optimize 类 action |

后续要升级的方向：

```text
Agent Action 返回结构化 draft；
前端在当前页面展示草案；
用户确认后再调用确定性保存 API；
不能自动覆盖旧版本。
```

## 已补齐的无反馈点

本轮修复范围：

| 位置 | 原问题 | 处理 |
| --- | --- | --- |
| 求职项目右侧关联资产：资料 | `onTap: null`，看起来可点但无响应 | 改为 SnackBar 说明资料暂汇总在当前项目和关联资产 |
| 求职项目时间线：查看全部记录 | 空回调 | 改为弹出完整时间线 Dialog |
| 求职项目右侧关联笔记：查看全部 | 空/弱反馈 | 改为进入笔记页 |
| JD 匹配证据依据：查看全部 | 无实际展开 | 改为证据列表 Dialog |
| JD 匹配证据来源：导出证据清单 | 无后端导出 | 改为复制证据清单文本，并提示成功 |
| JD 匹配相关笔记 | 只展示不可进入 | 改为进入笔记页 |
| 简历资料：查看基础简历 | 空回调 | 改为基础画像详情 Dialog |
| 学习计划：开始复盘 | 禁用但无原因 | 改为 SnackBar 提示复盘记录流程未接入 |
| 总览：学习任务资产入口 | 无响应 | 改为进入学习计划页 |
| 顶部通知 / 设置 | 空回调 | 改为当前状态说明 SnackBar |

## 仍需后端化或产品补齐的能力

这些不能在 UI 上表现成完整功能：

| 能力 | 当前建议 |
| --- | --- |
| 设置页 | 保持说明型 SnackBar，后续独立页面 |
| 项目资料页 | 先汇总在项目关联资产里，后续独立资料页 |
| 复盘记录流程 | 需要 Review record API / Note 草案确认流程 |
| 新建求职项目 | 需要确定性 create project dialog + API |
| 简历版本草案保存 | 需要 `ResumeVersionDraft -> accept -> ResumeVersion` |
| JD 证据库 | 当前用 Note 承接，后续应有 ProjectEvidence 数据对象 |
| 证据清单导出文件 | 当前复制文本，后续做 export API |
| 面试题草案保存 | 需要 InterviewPrepDraft / Note accept API |

## 前端实现规则

后续所有按钮按下面的判断写：

```text
有确定性页面：直接跳转；
有确定性弹窗：就地打开；
有后端 API：按钮 loading + 成功/失败提示；
只有 Agent action：必须显示当前页 ActionBanner；
没有实现：不要静默，显示原因；
没有产品意义：删除按钮。
```

代码上禁止：

```text
onTap: null 但样式像可点击
onPressed: () {}
disabled 按钮没有 tooltip / 说明
点击后强制跳到聊天页
Agent 结果只出现在聊天页，当前页面没有反馈
```

## 后续验收

每次重构一个页面后至少做三项检查：

```text
1. rg 扫描空回调和 null click handler；
2. Flutter analyze / 相关 widget test；
3. 手动截图检查：按钮点击后是否有页面变化、弹窗、loading、toast 或明确提示。
```

本阶段不要追求所有后端能力一次补完，但必须做到：

```text
用户点了任何看起来可点的东西，都知道发生了什么，以及为什么。
```
