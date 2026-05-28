# M45：Agent 对话工作区产品化方案

> 状态：待确认。分支：`m44-frontend-product-workspace-ui`。本阶段只做前端体验和信息架构优化，不改 Agent runtime、不改后端协议、不引入用户管理系统。`.env` 不属于本阶段改动范围。

## 1. 背景

M44 已经把核心业务模块拆成产品页：

```text
总览 / 求职项目 / 简历资料 / JD 匹配 / 学习计划 / 笔记
```

但当前 ChatScreen 仍然偏旧工作台形态：

```text
1. 会话历史通过弹层恢复了入口，但没有成为聊天页的常驻信息结构。
2. 对话气泡、执行过程、任务上下文之间的视觉关系不够清楚。
3. 多 Agent 执行卡片已经有能力，但还没有融入一个清晰的 Chat Workspace。
4. 用户在业务页点击动作后进入聊天页，当前上下文和相关资产没有足够稳定地展示在右侧。
5. 未来做用户管理后，用户头像、昵称、身份状态需要有明确接入点。
```

用户给出的 UI 参考图可以总结成一个方向：

```text
左侧：产品导航 + 最近会话
中间：对话时间线 + 用户/Agent 气泡 + 执行卡片 + 输入框
右侧：当前任务上下文 + 推荐操作 + 关联资产
```

M45 的目标不是重新做一个独立聊天 App，而是把当前 Agent 执行页做成产品级工作区。

## 2. 产品目标

```text
1. 用户可以直接在左侧看到最近会话，并切换会话历史。
2. 用户可以在中间清楚看到：
   - 自己问了什么
   - Agent 如何执行
   - 多 Agent 进行到哪一步
   - 最终产出了什么
3. 用户可以在右侧看到当前对话/任务绑定的上下文：
   - 当前求职项目
   - 目标岗位
   - 相关文件
   - 推荐下一步
   - 关联资产
4. 页面在桌面、平板、手机都可用，不写死位置。
5. 先复用现有 provider、SessionSidebar、ChatBubble、StreamingBubble、RunProgressPanel、InputBar，不重做后端。
```

## 3. 不做事项

```text
不做用户注册、登录、权限系统。
不做真实用户头像上传。
不重写 Agent stream protocol。
不重做工具执行卡片底层解析。
不把右侧上下文写成静态 mock。
不删除 M44 业务页。
不把所有功能塞回 ChatScreen 一个文件。
```

用户头像处理：

```text
第一版：
  - 用户头像使用默认头像或首字母占位。
  - Agent 头像使用求职 Agent 品牌图标。

后续用户管理上线后：
  - ChatUserAvatar 从 user profile 读取 avatarUrl / displayName。
  - 未登录或无头像时 fallback 到默认头像。
```

## 4. 现有代码基础

当前相关文件：

```text
flutter_app/lib/features/chat/chat_screen.dart
  当前聊天页主体，负责 Header、消息层、输入层。

flutter_app/lib/shared/widgets/chat_bubble.dart
  当前用户/Agent 消息、Markdown、产物、学习任务动作、进度事件展示。

flutter_app/lib/shared/widgets/input_bar.dart
  当前输入框、文件上传、技能选择、活跃 artifact。

flutter_app/lib/shared/widgets/session_sidebar.dart
  当前会话历史列表，支持切换、删除、重命名、置顶。

flutter_app/lib/shared/widgets/run_progress_panel.dart
  多 Agent 执行动态和任务图展示。

flutter_app/lib/features/home/home_screen.dart
  ProductWorkspaceShell 的页面切换和动作 prompt 入口。

flutter_app/lib/features/workspace/*
  M44 产品壳、导航、顶部搜索。

flutter_app/lib/features/career_workbench/career_workbench_provider.dart
  当前求职项目聚合数据源，可给右侧上下文使用。
```

当前应该保留的能力：

```text
ChatProvider.sessions
ChatProvider.switchSession
ChatProvider.createNewSession
ChatProvider.deleteSession
ChatProvider.renameSession
ChatProvider.setSessionPinned
ChatProvider.messages
ChatProvider.streamEvents
ChatProvider.sessionArtifacts
CareerWorkbenchProvider.selectedApplicationSummary
CareerWorkbenchProvider.selectedApplicationDetail
```

## 5. 新页面信息架构

M45 新结构：

```text
AgentChatWorkspace
  ├── AgentChatSidebar
  │   ├── BrandHeader
  │   ├── NewSessionButton
  │   ├── PrimaryNav
  │   ├── QuickActionGrid
  │   ├── RecentSessionList
  │   └── AssistantStatus
  │
  ├── AgentChatMain
  │   ├── ChatTaskTopBar
  │   ├── ChatWelcomeHeader
  │   ├── ChatTimeline
  │   │   ├── DateSeparator
  │   │   ├── UserMessageBubble
  │   │   ├── AgentMessageBubble
  │   │   ├── RunProgressMessageCard
  │   │   └── ResultSummaryCard
  │   └── ChatComposerDock
  │
  └── AgentContextRail
      ├── CurrentTaskContextCard
      ├── RecommendedActionsCard
      ├── RelatedAssetsCard
      └── SessionFactsCard
```

页面关系：

```text
ProductWorkspaceShell
  └── WorkspacePage.chat
      └── AgentChatWorkspace
```

M45 不再让 ChatScreen 自己管理全部布局。ChatScreen 可以逐步降级为 `AgentChatMain` 的内部消息流组件，或保留旧实现作为 fallback。

## 6. 桌面布局

断点：

```text
desktop: >= 1180px
tablet: 760px - 1179px
mobile: < 760px
```

桌面三栏：

```text
AgentChatSidebar: 280px
AgentChatMain: flex 1，max content width 920px，但时间线居中
AgentContextRail: 340px
```

整体：

```text
background: ProductColors.canvas (#F7FAF9)
panel background: ProductColors.surface (#FFFFFF)
border: ProductColors.border (#DDE8E4)
primary: ProductColors.primary (#0F9B78)
soft mint: ProductColors.primarySoft / surfaceMint
radius:
  sidebar/main rail panel: 0 或 18，按壳层
  cards: 14-18
  bubbles: 12-16
  input dock: 18-22
```

不要用固定绝对坐标；三栏通过 `Row + SizedBox + Expanded`，主内容内部用 `ConstrainedBox` 控制最大宽度。

## 7. 左侧 AgentChatSidebar

### 7.1 位置与职责

文件建议：

```text
flutter_app/lib/features/chat_workspace/agent_chat_sidebar.dart
```

职责：

```text
1. 聊天页内的会话历史和快捷入口。
2. 不是替代全局业务导航，而是在 Chat Workspace 内呈现“最近会话”。
3. 复用 ChatProvider.sessions，不新增状态源。
```

### 7.2 内容结构

顶部品牌：

```text
左侧圆形品牌图标：
  40x40
  primary 渐变或纯 primary
  icon: Icons.auto_awesome_rounded / 品牌图标

文字：
  求职 Agent
  你的智能求职伙伴

状态：
  在线小圆点，可放在标题右侧或副标题前
```

新建会话按钮：

```text
height: 44
background: ProductColors.primary
foreground: white
left icon: Icons.add_rounded
label: 新建会话
right badge: ⌘K 或快捷键占位
onTap: ChatProvider.createNewSession + 保持 chat page
```

主导航：

```text
工作台
会话历史
求职项目
简历资料
JD 匹配
学习计划
笔记
数据分析（可先隐藏或作为未来入口）
```

说明：

```text
1. 左侧聊天页可以展示业务入口，但不能再出现“双重导航”。
2. 如果外层 ProductSidebar 已经常驻，桌面 ChatWorkspace 可以选择复用外层导航，只新增 RecentSessionList。
3. 为减少重复，第一版建议在 WorkspacePage.chat 下隐藏外层 ProductSidebar，使用 AgentChatSidebar。
```

快捷入口：

```text
生成简历
JD 分析
面试准备
Agent 助手
```

最近会话：

```text
section title: 最近会话
right action: 更多 >
每条 item:
  icon: small chat/document dot
  title: session.title
  time: 今天 HH:mm / 昨天 / MM-DD
  active background: ProductColors.primarySoft
  active text: ProductColors.primary
  hover: surfaceSoft
  context menu:
    重命名
    置顶/取消置顶
    删除
```

底部状态：

```text
AI 助理
在线/离线
可折叠箭头
```

## 8. 中间 AgentChatMain

文件建议：

```text
flutter_app/lib/features/chat_workspace/agent_chat_workspace.dart
flutter_app/lib/features/chat_workspace/agent_chat_main.dart
flutter_app/lib/features/chat_workspace/chat_timeline.dart
flutter_app/lib/features/chat_workspace/chat_message_bubble.dart
flutter_app/lib/features/chat_workspace/chat_result_cards.dart
```

### 8.1 顶部栏 ChatTaskTopBar

对应参考图：

```text
左侧：
  当前会话标题，例如：学习任务进度查询 / 产品经理求职全流程任务
  下拉箭头，用于未来切换会话或重命名
  可选状态 chip：
    对话中
    多 Agent 协作
    自动保存于 10:24:30

右侧：
  置顶
  分享
  历史记录
  更多
  或：切换工作台 / 分享 / 通知 / AI 头像
```

数据来源：

```text
session title: ChatProvider active session title
状态:
  chat.isStreaming -> 对话中 / 执行中
  streamEvents contains task/delegate -> 多 Agent 协作
  last message updatedAt -> 自动保存时间
```

### 8.2 空会话欢迎区

当前无消息时显示：

```text
居中：
  👋 你好，我是你的求职 Agent 助手
  我可以帮你规划学习路径、分析岗位、优化简历、模拟面试，陪你一起拿下心仪 Offer！

下方可放快捷 prompt：
  分析 JD 匹配度
  生成定制简历
  查看学习进度
  创建面试准备计划
```

实现要求：

```text
1. 不做营销式 Hero。
2. 文案短，主要服务首次使用。
3. 发送快捷 prompt 后进入同一会话。
```

### 8.3 ChatTimeline

时间线元素：

```text
DateSeparator:
  今天 · 5月23日
  background: surfaceSoft
  text: ProductColors.textMuted

UserMessageBubble:
  align: right
  maxWidth: min(70%, 560)
  background: ProductColors.primarySoft 或淡绿色
  border: primary alpha 0.16
  avatar: 32x32，当前先默认头像，未来 user profile
  meta: 时间、发送状态

AgentMessageBubble:
  align: left
  maxWidth: min(78%, 720)
  background: white
  border: ProductColors.border
  avatar: 36x36 brand icon
  header: Agent 助手 + time
  body: Markdown / cards
  footer actions: copy / like / dislike
```

消息渲染：

```text
1. 继续复用 ChatBubble 的 Markdown / artifact / career report 渲染。
2. 先做外层视觉 wrapper，不重写所有 Markdown 解析。
3. 对复杂消息：ChatBubble 内部报告卡保留，外层统一气泡边距和头像。
```

### 8.4 多 Agent 执行卡片

参考图包含两种状态：

```text
执行中：
  title: 多 Agent 执行中...
  stepper:
    需求分析 已完成
    岗位匹配 已完成
    简历优化 执行中
    结果整合 待开始
  live logs:
    岗位分析 Agent 完成了 JD 核心要求提取
    简历优化 Agent 正在生成匹配的简历要点

执行完成：
  title: 多 Agent 执行完成
  progress: 100%
  stepper all done
  result summary
  next actions
```

实现策略：

```text
1. 复用 RunProgressPanel 的数据解析。
2. 新增 compact variant：
   RunProgressPanel(variant: chatTimelineCard)
3. 第一版不改 stream event schema。
4. 如果没有结构化 stepper，fallback 到现有执行动态列表。
```

### 8.5 结果摘要卡片

用于 Agent answer 中的结构化成果。

学习任务进度场景：

```text
卡片标题：结果摘要
metrics:
  进行中任务 3 个
  已完成任务 8 个
  总任务数 12 个
  整体进度 66%
footer:
  你正在稳步推进学习计划，继续保持！
```

求职项目分析场景：

```text
卡片标题：多 Agent 协同执行结果
summary bullets:
  提取岗位核心要求 6 项
  匹配出优势 8 项
  生成简历要点 12 条
next actions:
  查看详细报告
  优化简历（生成版）
  模拟面试问题推荐
```

实现策略：

```text
1. 优先从现有 ChatBubble 中识别 career/action/result markdown。
2. 不做弱规则大改。
3. 新增少量通用 ResultSummaryCard，用于未来 structured response。
```

### 8.6 输入区 ChatComposerDock

参考图：

```text
底部居中或贴主栏底部。
desktop maxWidth: 860
height:
  collapsed: 58
  expanded with tools/files: auto
```

元素：

```text
左侧：
  + / 附件
  上传附件
  快捷命令
  引用内容

输入：
  placeholder: 输入你的问题，或使用 / 快捷命令
  Enter 发送，Shift + Enter 换行

右侧：
  麦克风 icon，占位
  发送按钮 primary
```

实现策略：

```text
1. 复用 InputBar 现有文件上传、技能、artifact 激活能力。
2. M45 第一阶段只做视觉包裹和布局，不拆 InputBar 内部所有功能。
3. 后续再把 InputBar 拆成 ComposerToolbar / ComposerTextField / ComposerAttachmentTray。
```

## 9. 右侧 AgentContextRail

文件建议：

```text
flutter_app/lib/features/chat_workspace/agent_context_rail.dart
```

职责：

```text
1. 展示当前对话的业务上下文。
2. 不是调试面板，不展示内部 token 或工具轮次。
3. 所有内容来自现有 provider，不制造新事实源。
```

### 9.1 CurrentTaskContextCard

内容：

```text
标题：当前任务上下文
右上：管理

字段：
  任务名称
  任务目标
  涉及岗位
  创建时间
  相关文件
```

数据映射：

```text
如果当前有 CareerWorkbenchActionRequest:
  task name = action.label
  task goal = action.actionType 映射文案
  related application = action.applicationId

如果 selectedApplicationDetail 存在:
  company / position / stage / readiness
  jdAnalysisId / jobFitReportId / resumeVersionIds

如果 sessionArtifacts 存在:
  展示最近 2-4 个 PDF/MD/TXT 文件
```

空态：

```text
当前没有绑定任务
可以从左侧项目、简历或 JD 页面发起 Agent 动作
```

### 9.2 RecommendedActionsCard

内容：

```text
推荐操作
  生成定制简历
  对比岗位匹配度
  面试问题推荐
  学习提升建议
```

数据来源：

```text
CareerApplicationView.nextActions
CareerReadinessView.nextActions
CareerWorkbenchProvider.selectedApplicationDetail.suggestedActions
fallback static quick prompts
```

点击行为：

```text
1. 使用现有 sendCareerPromptAction。
2. 进入当前会话，不新开会话。
3. action origin = chat_context_rail。
```

### 9.3 RelatedAssetsCard

内容：

```text
关联资产
  项目经验库
  技能库
  证书库
  笔记
  简历版本
  JD 分析
```

第一版：

```text
使用现有 sessionArtifacts + selectedApplicationDetail linkedAssets。
点击：打开 artifact preview 或跳转对应产品页。
```

### 9.4 SessionFactsCard

可选，第一版低优先：

```text
当前会话事实：
  活跃文件数
  当前技能
  最近产物
  最近工具执行状态
```

注意：

```text
只展示用户能理解的事实，不展示 runtime 内部细节。
```

## 10. 响应式方案

### 10.1 Desktop >= 1180

```text
三栏常驻：
  左侧 AgentChatSidebar
  中间 AgentChatMain
  右侧 AgentContextRail
```

### 10.2 Tablet 760-1179

```text
左侧：
  只保留窄栏或菜单按钮，RecentSessionList 进入 drawer。

中间：
  主对话占满剩余宽度。

右侧：
  ContextRail 折叠为右上按钮「上下文」。
  点击后用 side sheet / bottom sheet 展示。
```

### 10.3 Mobile < 760

```text
顶部：
  menu
  session title
  context button

正文：
  单列消息流
  气泡 maxWidth 约 86%

底部：
  composer dock full width
  工具按钮折叠为 + 菜单

左侧会话历史：
  bottom sheet / full-height drawer

右侧上下文：
  bottom sheet
```

移动端必须检查：

```text
1. 输入框不被键盘遮挡。
2. 气泡文字不溢出。
3. 执行卡片 stepper 可以横向滚动或纵向堆叠。
4. 右侧上下文不在窄屏常驻。
```

## 11. 文件拆分计划

新增：

```text
flutter_app/lib/features/chat_workspace/agent_chat_workspace.dart
flutter_app/lib/features/chat_workspace/agent_chat_sidebar.dart
flutter_app/lib/features/chat_workspace/agent_chat_main.dart
flutter_app/lib/features/chat_workspace/agent_context_rail.dart
flutter_app/lib/features/chat_workspace/chat_workspace_models.dart
flutter_app/lib/features/chat_workspace/widgets/chat_task_top_bar.dart
flutter_app/lib/features/chat_workspace/widgets/chat_timeline.dart
flutter_app/lib/features/chat_workspace/widgets/chat_message_shell.dart
flutter_app/lib/features/chat_workspace/widgets/chat_composer_dock.dart
flutter_app/lib/features/chat_workspace/widgets/context_cards.dart
```

保留并复用：

```text
flutter_app/lib/shared/widgets/chat_bubble.dart
flutter_app/lib/shared/widgets/input_bar.dart
flutter_app/lib/shared/widgets/session_sidebar.dart
flutter_app/lib/shared/widgets/run_progress_panel.dart
```

修改：

```text
flutter_app/lib/features/home/home_screen.dart
  WorkspacePage.chat 从 ChatScreen 改为 AgentChatWorkspace。

flutter_app/lib/features/chat/chat_screen.dart
  第一阶段保留，不删除。
  可作为 AgentChatMain 的内部 fallback 或逐步拆出。

flutter_app/lib/shared/widgets/run_progress_panel.dart
  可选新增 compact card variant。
```

## 12. 数据与状态流

### 12.1 会话历史

```text
source: ChatProvider.sessions
actions:
  createNewSession
  switchSession
  deleteSession
  renameSession
  setSessionPinned
```

### 12.2 当前消息

```text
source:
  ChatProvider.messages
  ChatProvider.streamBuffer
  ChatProvider.isStreaming
  ChatProvider.streamEvents
```

### 12.3 当前任务上下文

第一版优先级：

```text
1. ChatProvider.sessionArtifacts
2. CareerWorkbenchProvider.selectedApplicationSummary/detail
3. CareerWorkbenchProvider.currentAction / last action state
4. fallback quick actions
```

如果 provider 当前没有显式 current action，需要补轻量状态：

```text
CareerWorkbenchProvider:
  activeActionRequest?
  lastCompletedAction?
  lastFailedAction?
```

注意：

```text
这属于 UI 状态，不改后端事实源。
```

## 13. 分阶段实现

### M45-A：ChatWorkspace 外壳

目标：

```text
1. 新增 AgentChatWorkspace。
2. 桌面三栏布局落地。
3. 左侧展示最近会话。
4. 中间复用当前 ChatScreen 的消息列表和输入框。
5. 右侧先展示基础上下文空态和 session artifacts。
```

验收：

```text
desktop 1440px：
  左侧会话、主聊天、右侧上下文同时可见。

mobile 390px：
  左侧/右侧通过按钮打开，不遮挡输入。
```

### M45-B：对话气泡产品化

目标：

```text
1. 新增 ChatMessageShell，统一头像、发送方、时间、气泡边距。
2. 用户气泡右对齐，Agent 气泡左对齐。
3. ChatBubble 作为 Agent body 内容复用。
4. StreamingBubble 包进同一视觉容器。
```

验收：

```text
1. 普通聊天、Markdown、职业报告、artifact 预览都正常。
2. 旧测试不回归。
3. 用户头像先使用默认占位，后续可替换。
```

### M45-C：多 Agent 执行卡片紧凑版

目标：

```text
1. RunProgressPanel 支持 chat compact variant。
2. 执行中和执行完成状态视觉接近参考图。
3. 结果摘要和下一步动作卡片在气泡内展示。
```

验收：

```text
1. live stream 时能看到执行阶段变化。
2. 完成后有 summary + action buttons。
3. 没有结构化事件时 fallback 到当前动态列表。
```

### M45-D：右侧任务上下文

目标：

```text
1. 当前任务上下文卡片。
2. 推荐操作卡片。
3. 关联资产卡片。
4. 点击操作继续走 Agent prompt。
```

验收：

```text
1. 从求职项目页点击动作进入 ChatWorkspace 后，右侧展示该项目。
2. 从学习计划记录进度进入 ChatWorkspace 后，右侧展示学习任务上下文。
3. 普通聊天时显示空态和最近资产。
```

### M45-E：响应式与视觉走查

目标：

```text
1. 1440 / 1180 / 900 / 390 宽度截图检查。
2. 长标题、长中文、长英文 ID 不溢出。
3. 输入框、bottom sheet、context rail 在移动端可用。
```

## 14. 测试计划

新增/更新测试：

```text
flutter_app/test/agent_chat_workspace_test.dart
  - desktop 展示三栏
  - mobile 展示菜单/上下文按钮
  - 最近会话可切换
  - 新建会话调用 ChatProvider.createNewSession

flutter_app/test/chat_message_shell_test.dart
  - 用户消息右对齐
  - Agent 消息左对齐
  - 空头像 fallback
  - 长文本不溢出

flutter_app/test/agent_context_rail_test.dart
  - 有 selectedApplication 时展示公司/岗位/相关文件
  - 无项目时展示空态
  - 推荐动作发送 prompt
```

保留：

```text
flutter analyze
flutter test
```

手动/截图验收：

```text
1. desktop 1440x1000
2. laptop 1280x900
3. tablet 900x1100
4. mobile 390x844
```

## 15. Live Smoke 范围

M45 是前端呈现层，第一阶段不需要大批量 live smoke。完成 M45-C/D 后跑小矩阵：

```text
1. 仅聊天
2. 求职项目 -> 生成定制简历
3. JD 匹配 -> 生成建议
4. 学习计划 -> 记录进度
5. RAG -> 写 Note
```

验证重点：

```text
1. UI 能展示执行中/完成。
2. 右侧上下文不串项目。
3. 会话切换后消息和上下文同步。
4. 前端没有因为布局导致功能不可用。
```

不把几秒钟性能差异作为 M45 的核心门槛。M45 核心是产品感和信息可理解性。

## 16. 风险与边界

风险：

```text
1. ChatBubble 当前文件很大，如果继续往里加视觉逻辑会失控。
2. RunProgressPanel 数据解析复杂，不能在 M45 同时重写协议和 UI。
3. 右侧上下文如果强行推断，会出现项目串线。
4. 外层 ProductSidebar 和 ChatWorkspaceSidebar 可能重复导航。
```

控制方式：

```text
1. 新增 chat_workspace 目录，隔离新布局。
2. 复用旧组件，外层包壳，不直接重写所有渲染。
3. 右侧上下文只展示 provider 明确给出的状态；不猜。
4. 桌面 ChatWorkspace 下可以隐藏外层 ProductSidebar，避免双导航。
5. 每阶段完成后截图走查，不用长尾式打补丁。
```

## 17. 完成标准

M45 可收口标准：

```text
1. Chat 页面视觉接近参考图：
   - 左侧最近会话
   - 中间气泡时间线
   - 多 Agent 执行卡片
   - 右侧上下文

2. 核心功能不回归：
   - 新建会话
   - 切换会话
   - 发送消息
   - 文件上传/引用
   - Agent streaming
   - artifact 展示

3. 响应式可用：
   - desktop 三栏
   - tablet 抽屉/侧栏
   - mobile bottom sheet

4. 用户管理未上线也不阻塞：
   - 用户头像有 fallback
   - 后续 user profile 可直接接入 ChatUserAvatar
```

## 18. 建议下一步

确认后先做 M45-A：

```text
1. 新增 chat_workspace 目录和 AgentChatWorkspace。
2. 把 WorkspacePage.chat 切到 AgentChatWorkspace。
3. 左侧接入 ChatProvider.sessions。
4. 中间先复用当前 ChatScreen/消息层。
5. 右侧先做 ContextRail 空态 + session artifacts。
6. 跑 flutter analyze / flutter test。
7. 启动前端截图走查 desktop + mobile。
```

M45-A 完成后，再决定是否继续 M45-B 气泡产品化。不要一次性重写整个聊天页。
