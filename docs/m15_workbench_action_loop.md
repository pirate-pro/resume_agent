# M15 工作台动作闭环方案

## 背景

M14 已经把求职工作台从右侧栏中独立出来，用户可以查看求职项目、简历资料、JD 与匹配、学习计划和笔记。当前剩下的主要体验断点是：用户在工作台点击推荐动作后，会回到聊天执行，但工作台本身没有明确告诉用户：

- 这个动作是否已经触发。
- 执行完成后产生了什么变化。
- 新产物应该在哪里查看。
- 下一步应该继续做什么。

M15 的目标不是新增新的产品事实源，而是把“工作台发起动作 -> 聊天执行 -> 产物回到工作台”的体验闭环补齐。

## 产品目标

```text
用户在工作台点击动作后：
  -> 立即看到动作已进入执行
  -> 回到聊天观看执行过程
  -> 执行完成后工作台和资产栏自动刷新
  -> 再打开工作台时能看到本次动作结果和定位入口
```

核心体验标准：

- 不让用户觉得系统卡住。
- 不让用户猜新报告、新简历、新笔记在哪里。
- 不把调试 ID 当成主体验。
- 不让工作台绕过聊天直接执行任务。

## 非目标

M15 第一阶段不做：

- 不新增后端 store。
- 不新增 workflow 引擎。
- 不引入 LangGraph。
- 不改变 `CareerProductStore`、`NoteStore`、`LearningStore`、`SessionArtifact` 的边界。
- 不做服务端持久任务状态。
- 不扩大 smoke 压力测试批次。

## 状态模型

M15 第一阶段只在前端维护临时动作状态：

```text
CareerWorkbenchActionRequest
  application_id
  action_type
  label
  origin

CareerWorkbenchActionRun
  request
  state: running | completed | failed
  started_at
  finished_at
  result_hints
  error
```

状态含义：

- `running`：动作已经从工作台发起，正在聊天链路中执行。
- `completed`：聊天执行结束，工作台和右侧资产栏已经刷新。
- `failed`：聊天执行链路失败，或 ChatProvider 返回错误。

这不是事实源，只是当前前端会话中的体验状态。刷新页面后丢失可以接受。

## 结果定位

动作开始前，工作台记录一个轻量快照：

```text
application_count
note_count
learning_task_count
resume_version_count
当前项目 linked_asset_ids
当前项目 notes 数量
当前项目 learning tasks 数量
```

动作完成并刷新后，对比快照生成用户可读提示：

```text
新增 1 个关联资料
新增 1 个学习任务
新增 1 条笔记
项目状态已刷新
```

如果没有检测到明显新增资产，也显示保守提示：

```text
已刷新项目状态和关联资料，可打开项目查看最新结果。
```

## 交互设计

### 1. 推荐动作

项目详情里的推荐动作仍然放在「推荐下一步」区域。

点击后：

```text
构造受控 prompt
构造 CareerWorkbenchActionRequest
HomeScreen 切回聊天
CareerWorkbenchProvider.beginAction()
ChatProvider.sendMessage()
CareerWorkbenchProvider.refresh()
CareerAssetsProvider.refresh()
CareerWorkbenchProvider.completeAction()
```

如果 ChatProvider 出错：

```text
CareerWorkbenchProvider.failAction(error)
```

### 2. 工作台动作横幅

工作台顶部增加轻量横幅。

运行中：

```text
正在执行：生成定制简历
已回到聊天处理，完成后会同步刷新工作台。
```

完成后：

```text
已完成：生成定制简历
新增 1 个关联资料 / 项目状态已刷新
按钮：查看项目、关闭
```

失败时：

```text
执行失败：生成定制简历
错误摘要
按钮：返回聊天、关闭
```

### 3. 学习动作

学习计划页里的「生成计划」「同步进展」也接入同一动作状态模型。它们仍然回到聊天执行，不直接写 LearningStore。

## 组件调整

```text
CareerWorkbenchProvider
  -> beginAction()
  -> completeAction()
  -> failAction()
  -> clearAction()
  -> focusActiveActionTarget()

CareerWorkbenchPage
  -> _WorkbenchActionBanner

HomeScreen
  -> _sendWorkbenchPrompt(prompt, action)

_DetailActionSection
  -> 发送 CareerWorkbenchActionRequest

_LearningActionStrip
  -> 发送 CareerWorkbenchActionRequest
```

## 验收标准

- 工作台推荐动作点击后仍回到聊天执行。
- 动作发起后 provider 中有 running 状态。
- 聊天完成后工作台和右侧资产栏刷新。
- 再打开工作台可以看到动作完成横幅。
- 横幅能定位回对应求职项目。
- ChatProvider 返回错误时，工作台动作状态显示失败。
- `flutter analyze` 通过。
- `flutter test test/home_screen_test.dart` 通过。
- `flutter test test/career_workbench_page_test.dart` 通过。

## 后续方向

M15 第一阶段完成后，再考虑：

- 服务端任务状态持久化。
- 按 run_id 展示更细粒度 agent 进度。
- 执行完成后自动高亮新增资产。
- 把下一步建议和项目阶段流转做得更主动。
