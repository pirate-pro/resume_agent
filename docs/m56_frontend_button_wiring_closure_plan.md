# M56 Frontend Button Wiring Closure Plan

## 目标

M55 已经把“无反馈按钮”收敛成显式反馈，但其中一部分能力其实已经有后端通路。M56 的目标是把这类入口从 SnackBar 占位升级为真实闭环。

本轮先处理学习计划页的复盘按钮：

```text
点击开始复盘
-> 当前页确认弹窗
-> PATCH /api/learning-admin/reviews/{review_schedule_id}
-> state=done, last_reviewed_at=now
-> 刷新当前求职项目 workbench
```

## 为什么先做复盘

M55 里把学习计划“开始复盘”临时处理成：

```text
复盘记录流程未接入
```

但后端已经存在 `ReviewScheduleUpdateRequest` 和 review schedule PATCH API。继续保留占位会造成两个问题：

```text
1. 用户看到按钮能点，但无法完成复盘；
2. 后续产品判断会误以为这是后端缺口，而不是前端未接线。
```

## 本轮实现

### 1. ApiService

新增：

```text
updateLearningReviewSchedule(...)
```

请求：

```text
PATCH /api/learning-admin/reviews/{review_schedule_id}
```

字段：

```text
state
last_reviewed_at
next_review_at
summary
```

### 2. CareerWorkbenchProvider

新增：

```text
completeLearningReview(...)
```

职责：

```text
1. 调用 review PATCH；
2. 把 review 标记为 done；
3. 写入 last_reviewed_at；
4. 强制刷新当前 selected application detail。
```

### 3. LearningPlanPage

原来：

```text
开始复盘 -> SnackBar 占位
```

改为：

```text
开始复盘 -> 完成复盘 Dialog -> 标记完成 -> 刷新页面
```

弹窗显示：

```text
复盘标题
复盘类型
到期状态
可选复盘总结
```

用户确认后才写入后端。

## 验收标准

```text
1. 点击“开始复盘”必须打开确认弹窗；
2. 点击“标记完成”必须调用结构化 review 更新接口；
3. 完成后刷新学习计划，已完成复盘不再出现在待复盘列表；
4. 失败时显示明确错误；
5. Widget test 覆盖这条点击路径。
```

## 后续同类处理

继续按这个原则清理按钮：

```text
已有后端 API：接真实 API；
只有 Agent Action：当前页显示运行状态；
没有实现：明确提示原因；
没有产品意义：删除入口。
```

