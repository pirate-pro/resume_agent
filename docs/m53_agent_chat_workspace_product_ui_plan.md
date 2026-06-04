# M53 求职 Agent 界面产品化重构方案

日期：2026-06-01

目标：把「求职 Agent」界面从“所有业务动作的默认落点”重构成一个清晰的对话执行工作区：普通聊天像聊天，多 Agent 执行像任务进度，业务页动作尽量就地生成草案，只有需要对话协作时才进入 Agent。本文是对 M45 的产品化补充，强调当前实现、按钮语义、流式展示、会话历史和多 Agent 卡片边界。

## 1. 当前实现的真实情况

当前页面入口：

```text
flutter_app/lib/features/chat_workspace/agent_chat_workspace.dart
flutter_app/lib/features/chat/chat_screen.dart
flutter_app/lib/shared/widgets/chat_bubble.dart
flutter_app/lib/shared/widgets/run_progress_panel.dart
```

当前结构：

```text
AgentChatWorkspace
├── _AgentChatSidebar
│   ├── 品牌
│   ├── 新建会话
│   ├── 产品导航
│   ├── 快捷入口
│   └── 最近会话
├── ChatScreen
└── _ContextRail
    ├── 当前项目上下文
    ├── 推荐操作
    └── 会话资产
```

当前能力：

```text
ChatProvider.sessions
ChatProvider.switchSession
ChatProvider.createNewSession
ChatProvider.deleteSession
ChatProvider.renameSession
ChatProvider.setSessionPinned
ChatProvider.messages
ChatProvider.streamReasoningBuffer
ChatProvider.sessionArtifacts
CareerWorkbenchProvider.selectedApplicationDetail
```

当前主要问题：

```text
1. 普通聊天有时也显示多 Agent 执行卡，显得过重。
2. 业务页按钮容易直接跳 Agent，打断当前页面上下文。
3. 工具调用和 reasoning 展示边界还需要更清楚。
4. 会话历史、当前任务上下文、最终回答之间层级还可以继续收敛。
5. 多 Agent 执行卡应该只在真的触发复杂协作时出现。
```

## 2. 页面产品定位

求职 Agent 界面不是所有功能的入口，也不是后台日志页。它应该是：

> 当用户需要自由问答、跨模块协作、长任务执行或查看会话历史时使用的对话工作区。

用户进入 Agent 页后最关心：

```text
1. 我现在在哪个会话？
2. 我问了什么，Agent 回答了什么？
3. 如果 Agent 调用了工具，做到了哪一步？
4. 当前对话绑定哪个求职项目或资产？
5. 我能继续追问、上传材料、还是回到业务页面处理？
```

关键原则：

```text
普通聊天应该像聊天。
工具调用可以像思考/执行过程一样轻量展示。
多 Agent 协作才展示多 Agent 进度卡。
业务页里的确定性动作尽量就地完成，不默认跳 Agent。
```

## 3. 信息架构

桌面三栏：

```text
AgentChatWorkspace
├── AgentChatSidebar 280px
├── AgentChatMain minmax(720px, 1fr)
└── AgentContextRail 360px
```

中间主区：

```text
AgentChatMain
├── ChatTaskTopBar
├── ChatTimeline
│   ├── WelcomeBlock
│   ├── DateSeparator
│   ├── UserBubble
│   ├── AssistantBubble
│   ├── LightweightToolTrace
│   ├── MultiAgentProgressCard
│   └── FinalResultCard
└── ChatComposerDock
```

右侧栏：

```text
AgentContextRail
├── CurrentTaskContextCard
├── RecommendedActionsCard
├── RelatedAssetsCard
└── SessionFactsCard
```

## 4. 左侧栏

左侧栏必须同时支持导航和会话历史，但层级要明确：

```text
品牌区
新建会话
主导航
快捷入口
最近会话
AI 状态
```

最近会话行为：

```text
默认展示最近 6 条。
“更多”展开全部。
支持切换、重命名、置顶、删除。
当前会话高亮。
```

注意：

```text
点击更多必须有反馈。
不需要额外提醒“长按拖拽”等操作。
会话删除要有确认或可撤销 toast。
```

## 5. 中间聊天主区

### 5.1 普通聊天

普通聊天消息结构：

```text
UserBubble：靠右，浅绿，小气泡。
AssistantBubble：靠左，白底卡片，头像 + 名字 + 时间。
```

不展示：

```text
多 Agent 协作完成
执行阶段大卡
求职报告卡
```

除非这一轮确实有业务动作或多 Agent 执行。

### 5.2 工具调用展示

如果普通聊天调用了少量工具，展示为轻量执行过程：

```text
模型思考
工具调用：读取当前项目 / 查询笔记 / 检索资料
工具结果摘要
最终回答
```

样式：

```text
折叠式小卡
低权重边框
不占据大面积
默认可折叠
```

不要用完整多 Agent 卡。

### 5.3 多 Agent 执行卡

只有满足以下条件才展示：

```text
触发 delegate_agents
出现多个明确子任务
有业务 workflow/action context
需要展示 fan-out / fan-in 进度
```

结构：

```text
MultiAgentProgressCard
├── 标题：多 Agent 协作执行
├── 状态：进行中 / 已完成 / 失败
├── 横向步骤：接收请求 / 执行工具 / 生成产物 / 汇总结果
├── 子 Agent 列表
└── 结果摘要
```

### 5.4 报告型结果

简历报告、JD 匹配、学习任务草案等不应该一开始就以大报告卡出现。

规则：

```text
生成过程中：轻量进度。
生成完成后：结构化结果卡。
需要保存的内容：弹出草案确认或回到对应业务页展示。
```

## 6. Reasoning 与流式输出

当前模型思考内容来自：

```text
reasoning_content / streamReasoningBuffer
```

展示原则：

```text
reasoning 可以实时展示，但默认折叠或弱化。
最终回答应流式输出。
工具调用期间可以展示“正在读取/检索/分析”，但不要把内部草稿当最终答案。
```

普通 tool-enabled 轮次：

```text
允许展示轻量过程。
不要因为可能调用工具就完全不流式。
如果模型后续调用工具，已展示文本必须能自然过渡，不出现闪烁 reset。
```

推荐状态机：

```text
thinking
tool_running
tool_result_summary
answer_streaming
completed
failed
```

## 7. 输入区 ChatComposer

输入区结构：

```text
左侧：加号 / 上传
中间：多行输入
右侧：语音 / 发送
上方：快捷 chip
```

快捷 chip：

```text
上传简历
分析 JD
创建学习任务
准备面试
```

注意：

```text
快捷 chip 是发起对话，不直接写业务数据。
业务页里的“记录进度、保存笔记、创建任务”优先在业务页就地完成。
```

## 8. 右侧上下文栏

右侧栏不是消息列表，也不是全部资产库。它只解释当前对话上下文。

固定模块：

```text
当前任务上下文
推荐操作
关联资产
会话事实
```

当前任务上下文：

```text
如果有 selectedApplication：展示项目、阶段、匹配度、当前风险。
如果是学习任务动作：展示 taskId、状态、进度。
如果是笔记动作：展示 note title、类型、关联项目。
如果没有上下文：解释“从业务页发起动作后这里会显示上下文”。
```

推荐操作：

```text
继续推进岗位
查看 JD 匹配
查看简历版本
查看学习任务
整理成笔记
```

这些按钮优先跳回业务页，不一定发 Agent。

## 9. 从业务页进入 Agent 的边界

不应该跳 Agent 的动作：

```text
学习任务记录进度
新建笔记
编辑笔记
查看详情
展开已完成任务
查看关联资产
导出简历
切换项目阶段
```

可以进入 Agent 的动作：

```text
自由问答
跨多个页面的复杂任务
生成一份长报告
需要用户持续追问的分析
不确定目标，需要对话澄清
```

更推荐就地生成草案的动作：

```text
生成学习任务草案
生成简历版本草案
整理复盘草案
提取行动项
生成面试题草案
```

## 10. 按钮文案规范

禁止泛化文案：

```text
Agent
执行
处理
AI 建议
去生成
```

推荐文案：

```text
生成定制简历
分析岗位差距
生成面试题
提取行动项
整理复盘草案
创建学习任务
查看关联项目
```

## 11. 数据动作映射

| UI 内容 | 数据来源 |
| --- | --- |
| 会话历史 | `ChatProvider.sessions` |
| 当前消息 | `ChatProvider.messages` |
| 流式正文 | `streamBuffer` |
| 流式 reasoning | `streamReasoningBuffer` |
| 工具事件 | `streamEvents` |
| 会话资产 | `sessionArtifacts` |
| 当前项目上下文 | `CareerWorkbenchProvider.selectedApplicationDetail` |

| UI 动作 | 数据动作 |
| --- | --- |
| 新建会话 | `createNewSession()` |
| 切换会话 | `switchSession(sessionId)` |
| 删除会话 | `deleteSession(sessionId)` |
| 重命名 | `renameSession(sessionId, title)` |
| 置顶 | `setSessionPinned(sessionId, pinned)` |
| 发送消息 | `sendMessage()` |
| 上传文件 | InputBar upload flow |

## 12. 组件拆分建议

```text
flutter_app/lib/features/chat_workspace/
├── agent_chat_workspace.dart
├── widgets/
│   ├── agent_chat_sidebar.dart
│   ├── recent_session_list.dart
│   ├── agent_chat_main.dart
│   ├── chat_message_shell.dart
│   ├── tool_trace_card.dart
│   ├── multi_agent_progress_card.dart
│   ├── chat_composer_dock.dart
│   ├── agent_context_rail.dart
│   └── current_task_context_card.dart
└── models/
    └── chat_workspace_ui_models.dart
```

## 13. 响应式

桌面：

```text
左 280 / 中 flex / 右 360
```

平板：

```text
隐藏右栏，右下浮动上下文按钮。
左侧会话栏可抽屉打开。
```

手机：

```text
只显示聊天主区。
顶部有会话按钮和上下文按钮。
Composer 固定底部。
消息气泡最大宽度 86vw。
```

## 14. 验收标准

用户应该能明确感受到：

```text
普通聊天就是轻量对话。
工具调用是轻量过程，不是大报告。
多 Agent 协作才出现多 Agent 进度卡。
会话历史随时可见或可打开。
业务上下文在右侧稳定展示。
业务页的确定性操作不会莫名跳到 Agent。
```

最关键的一句话：

> 求职 Agent 页要从“所有动作的落点”，升级成“对话协作和长任务执行工作区”。
