# M57 Frontend Active Placeholder Audit

## 目标

本轮只处理当前产品主路由仍能触达的“可点击但反馈不清楚”入口，不继续重构旧 workbench。

用户侧标准：

- 看起来可点击的控件必须有真实动作或明确反馈。
- 反馈必须说明当前缺少什么，而不是统一说“入口不可用”。
- 当前主产品页优先，旧页面只记录边界，避免把逻辑继续堆回旧结构。

## 主路由边界

当前 `HomeScreen` 主路由：

- `DashboardPage`
- `ChatScreen`
- `CareerProjectsPage`
- `JDMatchPage`
- `ResumeLibraryPage`
- `LearningPlanPage`
- `NotesLibraryPage`

仍在 active path 的辅助组件：

- `CareerAssetsPanel`：聊天页右侧/浮层求职资产入口。
- `ChatBubble`：聊天消息渲染与学习任务确认入口。

旧路径：

- `CareerWorkbenchPage` 目前只在测试中直接引用，不是 `HomeScreen` 主产品路由。

## 本轮处理项

### ChatBubble 学习任务入口

场景：

Assistant 消息中出现学习建议时，页面显示“加入学习任务”。

正常路径：

点击后弹确认 sheet，确认后通过 `chatProvider.sendMessage()` 交给 Agent 创建或复用学习任务。

异常路径：

如果组件没有 `ProviderScope`，以前反馈为“当前入口暂不可用”。

本轮改为：

```text
当前聊天上下文未就绪，暂时不能创建学习任务
```

### CareerAssetsPanel 推荐动作

场景：

聊天侧边资产面板中的求职项目推荐动作，例如生成定制简历、投递前检查、面试准备。

正常路径：

`CareerAssetsPanel` 在 `HomeScreen` 中会传入 `chatProvider.sendMessage`，动作会发回聊天执行，并在执行完成后刷新资产。

异常路径：

如果组件被单独挂载，没有传 `onApplicationPromptAction`，以前反馈为“当前入口暂不可用”。

本轮改为：

```text
当前资产面板未接入聊天执行通道，暂时不能发起该动作
```

### CareerWorkbenchPage 旧路径

场景：

旧 workbench 的推荐动作和学习动作仍有测试覆盖，但不属于当前主产品路由。

本轮只把兜底文案改清楚：

```text
当前工作台未接入聊天执行通道，暂时不能发起推荐动作
当前工作台未接入聊天执行通道，暂时不能发起学习动作
```

不在旧页面继续补新交互。

## 保留项说明

### JDMatchPage source_session_id guard

以下提示不是未实现按钮，而是数据缺口保护：

```text
缺少 source_session_id，暂时不能保存项目证据
缺少 source_session_id，暂时不能保存为笔记
```

原因：

保存 Note/证据需要可追溯来源；缺少 `source_session_id` 时，前端不能伪造来源。

### Workspace 设置入口

```text
设置页尚未接入，后续会独立补齐。
```

这是显式未接入反馈，不属于静默按钮。

### 防重复点击空回调

`_saving ? () {} : ...` 和 loading 中的 `setState(() {})` 是防重复点击或本地重绘，不是用户可见的死按钮。本轮不改。

## 后续验收建议

每次重构一个页面后，至少跑一次：

```bash
rg -n "当前入口暂不可用|尚未接入|没有接入|暂时不能|onTap: null|onPressed: null|\\(\\) \\{\\}" flutter_app/lib/features flutter_app/lib/shared
```

判定规则：

- active path 中的按钮：必须真实执行、导航、打开弹窗，或给出具体原因。
- 数据缺口：可以保留 guard，但文案必须说明缺哪个关键数据。
- 旧路径：只做边界记录，不继续新增产品逻辑。
