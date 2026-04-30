# ContextAssembler Multi-Agent Context Design

日期：2026-04-29

## 1. 文档目标

本文档用于重新定义 `ContextAssembler` 在 multi-agent 方向下的上下文注入边界。

核心调整：

1. 不再把 `shared_session` 作为默认上下文层。
2. main-agent 负责总体编排和全局进度理解。
3. 每个 agent 的 session / state / events 默认隔离。
4. main-agent 可以通过权限读取其他 agent 的摘要或原始上下文。
5. other-agent 默认只接收自己的任务、自己的进度、自己的事件和必要的长期记忆。

这份设计的重点不是立刻实现完整 multi-agent，而是先把 `ContextAssembler` 的目标结构定清楚，避免后续继续把 state、events、memory、history 混在一起。

---

## 2. 核心结论

目标结构应该是：

```text
main-agent
  负责用户入口、任务拆解、调用其他 agent、汇总结果、维护总体进度。

other-agent
  负责执行被分配的局部任务，维护自己的执行进度和局部事件。
```

上下文隔离口径：

```text
main-agent 可以看到全局编排视角。
other-agent 默认只能看到自己的局部视角。
other-agent 不默认读取 main-agent 的 session state。
other-agent 不默认读取其他 agent 的 state/events/memory。
```

因此，之前的 `shared_session_state` 不应作为常驻上下文层继续扩大。它容易让所有 agent 共享同一份短期工作台，后续 multi-agent 一复杂，会导致职责污染。

---

## 3. 当前实现现状

当前代码已经具备部分基础：

1. `RunContext` 已包含：
   - `session_id`
   - `run_id`
   - `agent_id`
   - `entry_agent_id`
   - `parent_run_id`

2. `EventRecord` 已包含：
   - `agent_id`
   - `run_id`
   - `parent_run_id`

3. `StateManager` 当前有两类 state：
   - `agent_session`
   - `shared_session`

4. `memory` 当前有：
   - `shared`
   - `agents/<agent_id>`

当前主要问题：

1. `ContextAssembler` 还没有区分 main-agent 和 other-agent 注入策略。
2. recent events 当前从整个 session 取最近事件，不按 agent role 过滤。
3. `shared_session_state` 当前会被注入，但目标设计里不再作为默认层。
4. mid-term Markdown 结构存在，但还没有明确的注入策略。
5. long-term memory 当前按 lane 注入，但还没显式区分 shared / agent overlay / facts / history。

---

## 4. 新的上下文模型

### 4.1 Root Session

`root_session` 是用户入口会话，主要由 main-agent 维护。

它保存：

```text
用户输入
main-agent 回复
main-agent 的总体计划
main-agent 调用其他 agent 的记录
其他 agent 返回给 main-agent 的结果摘要
main-agent 自己调用工具的关键结果
```

它不应该保存：

```text
其他 agent 的完整内部推理过程
其他 agent 的全部工具原始输出
其他 agent 的私有 working state
```

### 4.2 Agent Session

每个被调用的 agent 应该有自己的隔离 session。

它保存：

```text
收到的 task/handoff
该 agent 自己的 state
该 agent 自己的 user/assistant/tool events
该 agent 产出的局部结果
该 agent 的局部错误和修正记录
```

它不默认保存：

```text
root session 的完整历史
main-agent 的内部编排状态
其他 sibling agent 的上下文
```

### 4.3 Task / Handoff

`task` 不应和 `state` 混为一谈。

建议定义：

```text
task
  上级 agent 分配给当前 agent 的输入契约。
  相对稳定，是“你要做什么”。

state
  当前 agent 在执行任务过程中的可变工作台。
  是“我现在做到哪里了”。

event
  实际发生过的用户消息、agent 消息、工具调用、工具结果。
  是“发生过什么”。
```

第一版如果暂时没有独立 task 模型，可以先把 handoff 信息放在 child agent session 的首个 event 或 agent state 中。但目标上建议独立出来。

---

## 5. 注入层级

目标 prompt section 顺序：

```text
1. Static Identity
2. Runtime Rules
3. Skill Catalog
4. Tool Catalog
5. Runtime Metadata
6. Short-Term Context
7. Long-Term Context
8. Mid-Term Context
9. Artifacts
10. Recent Messages / Events
```

说明：

1. `AGENT.md`、`SOUL.md` 属于 Static Identity，全量注入。
2. skill / tool 使用渐进式披露，prompt 里只注入 `name + description`。
3. tool schema 仍通过模型 tool definitions 提供，不应塞进 system prompt。
4. short-term 是当前执行需要的工作台，不是 memory。
5. long-term 是稳定画像、事实、背景、约束。
6. mid-term 是近期自然语言摘要和 rolling context，后续可 chunk / keyword / vector 召回。

---

## 6. Main-Agent 注入策略

main-agent 的目标是编排，不是执行所有细节。

main-agent 应注入：

```text
AGENT.md / SOUL.md
runtime rules
skill catalog
tool catalog
current root session metadata
main-agent private state
root session orchestration events
child agent task dispatch records
child agent result summaries
shared long-term memory
main-agent long-term overlay
high-confidence always facts
retrieved relevant facts
retrieved relevant mid-term summaries
active artifacts metadata
recent user/assistant messages
```

main-agent 不应默认注入：

```text
child agent 的完整 private state
child agent 的完整 raw events
child agent 的完整 tool output
所有 sibling agent 的 memory overlay
```

main-agent 可通过 capability 读取：

```text
child agent session summary
child agent state
child agent events
child agent artifacts
child agent private memory
```

但这些读取应是显式行为，而不是每次 prompt 默认注入。

### 6.1 Main-Agent Recent Events

main-agent 的 recent events 应该是“编排视角事件”，例如：

```text
用户提出目标
main-agent 拆分任务
main-agent 调用 researcher_agent
researcher_agent 返回摘要
main-agent 调用 coder_agent
coder_agent 返回 patch summary
main-agent 调用工具并得到关键结果
main-agent 合成最终回答
```

它不应该是所有 agent events 的简单拼接。

---

## 7. Other-Agent 注入策略

other-agent 的目标是执行局部任务。

other-agent 应注入：

```text
自己的 AGENT.md / SOUL.md
runtime rules
允许使用的 skill catalog
允许使用的 tool catalog
task / handoff instruction
自己的 agent state
自己的 recent events
与任务相关的 artifacts
shared long-term memory 中允许读取的 always facts
自己的 long-term overlay
retrieved relevant facts
retrieved relevant mid-term summaries
```

other-agent 不应默认注入：

```text
root session 全量历史
main-agent private state
其他 agent state
其他 agent events
其他 agent private memory
所有 shared orchestration state
```

这能保持 agent 的局部性，避免它看到过多全局上下文后越权决策。

---

## 8. State 设计调整

目标上不再需要 `shared_session_state` 作为默认上下文。

建议收敛为：

```text
agent_session_state
  每个 agent 自己的当前任务工作台。

main_orchestration_state
  main-agent 自己维护的总体进度。
  本质上仍是 main-agent 的 agent_session_state，只是语义上用于编排。
```

也就是说：

```text
shared_session_state
  不再作为长期目标设计中的核心层。
```

当前兼容策略：

1. 短期可以保留 `StateManager.list_shared_state(...)`，但 `ContextAssembler` 不再默认给所有 agent 注入。
2. main-agent 可以暂时读取 legacy shared state，作为迁移期兼容。
3. other-agent 默认不读取 shared state。
4. 后续逐步把 shared state 用法迁移到 main-agent state 或 handoff/task。

---

## 9. Events 设计调整

当前 events 是 session 级 JSONL，每条 event 带 `agent_id/run_id/parent_run_id`。

第一阶段不必立刻改物理存储，可以先按 agent 过滤注入。

目标逻辑：

```text
main-agent
  读取 root session orchestration events。
  可读取 child result summary events。
  不默认读取 child raw events。

other-agent
  读取当前 agent session events。
  可读取本 task 相关 handoff event。
  不读取 root session 全量 events。
```

未来物理结构可以演进为：

```text
data/sessions/<root_session_id>/
  metadata.json
  events.jsonl                 # main-agent orchestration log
  state.json                   # main-agent orchestration state
  agent_sessions/
    <agent_session_id>/
      metadata.json
      task.json
      state.json
      events.jsonl
      result.md
```

当前阶段也可以继续使用：

```text
data/sessions/<session_id>/events.jsonl
```

但必须在读取时按 `agent_id/run_id/parent_run_id/event_type` 做逻辑过滤。

---

## 10. Memory 设计口径

### 10.1 Short-Term

short-term 不属于 `memory`。

来源：

```text
agent state
agent events
task/handoff
recent messages
tool result references
```

生命周期：

```text
频繁变化
只服务当前任务或当前 agent session
可以被 flush 到 mid-term
不直接成为 long-term memory
```

### 10.2 Mid-Term

mid-term 适合 Markdown。

建议结构：

```text
mid_term/
  rolling.md
  daily/
    2026-04-29.md
```

用途：

```text
近期阶段摘要
任务推进脉络
跨几天仍有用的上下文
尚未沉淀为长期事实的观察
```

第一版不要直接上向量。

建议顺序：

1. 固定 Markdown section。
2. 做简单 keyword / substring 召回。
3. 等结构稳定后再 chunk。
4. 再考虑 embedding / vector index。

### 10.3 Long-Term

long-term 结合 DeerFlow 结构。

建议包括：

```text
user
  workContext
  personalContext
  topOfMind

history
  recentMonths
  earlierContext
  longTermBackground

facts
  fact_1
  fact_2
```

注意：

```text
history 不是 events。
history 是长期背景摘要。
events 是原始发生记录。
```

long-term 注入分两类：

```text
always inject
  称呼
  语言
  禁忌
  强约束
  高置信稳定偏好
  长期身份背景

retrieved inject
  历史项目背景
  旧决策
  低频事实
  agent 专属经验
```

facts 排序建议：

```text
injectPolicy
confidence
updatedAt
category priority
scope priority
```

---

## 11. Capability 设计

不建议只用粗粒度 bool。

需要面向上下文读取定义能力：

```json
{
  "agentId": "agent_main",
  "contextCapabilities": [
    {"action": "read", "resource": "own_state", "allowed": true},
    {"action": "read", "resource": "own_events", "allowed": true},
    {"action": "read", "resource": "child_result_summary", "allowed": true},
    {"action": "read", "resource": "child_state", "allowed": true},
    {"action": "read", "resource": "child_raw_events", "allowed": false},
    {"action": "read", "resource": "sibling_private_memory", "allowed": false}
  ]
}
```

main-agent 可以更强，但也不应默认无边界全读。

other-agent 默认能力：

```text
read own state
read own events
read assigned task
read allowed shared long-term facts
read own memory overlay
```

---

## 12. ContextAssembler 目标结构

建议把当前 `ContextAssembler.assemble(...)` 拆成内部 plan：

```text
ContextAssemblyPlan
  role
  static_identity_policy
  skill_policy
  tool_policy
  short_term_policy
  long_term_policy
  mid_term_policy
  artifact_policy
  recent_event_policy
```

角色判断第一版可以使用：

```text
context.agent_id == context.entry_agent_id
```

但长期不建议硬编码 `agent_main`。

更稳的方式：

```text
AgentCapability.role = orchestrator | worker | specialist
```

第一版实现可以先：

```text
main-agent = context.agent_id == context.entry_agent_id
other-agent = context.agent_id != context.entry_agent_id
```

---

## 13. 建议实现阶段

### Phase A：只重构 ContextAssembler 结构，不改行为

目标：

1. 引入内部 section builder。
2. 把 system prompt section 明确命名。
3. 输出 context assembly summary。
4. 保持现有测试尽量不变。

交付：

```text
Static Identity section
Runtime Rules section
Skill Catalog section
Tool Catalog section
Short-Term section
Long-Term section
Artifacts section
```

实现状态（2026-04-29）：

```text
已完成第一批结构性改造：
- 新增 ContextAssemblyRole
- 新增 ContextSection
- 新增 ContextAssemblyPlan
- ContextAssembler.determine_role(...) 显式判断 main-agent / other-agent
- system prompt 改为先生成 section plan，再统一 render
- 当前 prompt 内容和注入行为保持不变
```

### Phase B：按 main-agent / other-agent 区分 short-term

目标：

1. main-agent 注入 orchestration state/events。
2. other-agent 只注入自己的 state/events/task。
3. `shared_session_state` 不再默认注入给 other-agent。

交付：

```text
main-agent prompt 不丢失总体进度。
other-agent prompt 不看到全局 session state。
```

实现状态（2026-04-29）：

```text
已完成第一批 short-term 分流：
- main-agent 继续读取 legacy shared_session_state
- other-agent 默认不读取 shared_session_state
- other-agent 仍读取自己的 agent_session_state
- recent events 过滤暂未改动，留到 Phase C
```

### Phase C：重构 recent events 过滤

目标：

1. main-agent recent events 只保留编排相关事件。
2. other-agent recent events 只保留自身相关事件。
3. child result 通过 summary event 回到 main-agent。

交付：

```text
event 注入从“最近 N 条”变成“按角色相关的最近 N 条”。
```

实现状态（2026-04-29）：

```text
已完成第一批 recent events 分流：
- main-agent 继续读取 root session 最近事件，保持当前编排行为
- other-agent 只读取当前 agent_id / 当前 run / 当前 run 子事件相关 events
- 当前只改上下文 messages 的事件来源过滤
- child result summary event 类型和 orchestrator summary 仍待后续设计
```

### Phase C.5：Skill / Tool 渐进式披露

目标：

1. `AGENT.md` / `SOUL.md` 继续全量注入。
2. skill 不再把完整 `SKILL.md` body 塞进 system prompt。
3. prompt 中只展示 skill `name + description`。
4. prompt 中只展示 tool `name + description`。
5. tool schema 继续通过 model tool definitions 提供，不进入 system prompt。

交付：

```text
Skills:
- base: ...
- memory: ...

Tools:
- memory_search: ...
- state_set: ...
```

实现状态（2026-04-29）：

```text
已完成第一批渐进式披露：
- skill catalog 使用 SKILL.md frontmatter description
- tool catalog 使用 ToolDefinition.description
- system prompt 不再包含完整 skill body
- system prompt 不包含 tool parameters_schema
- tool_definitions 返回值保持不变
```

### Phase D：接入 mid-term Markdown

目标：

1. 定义 rolling/daily Markdown section。
2. 做简单文本检索。
3. 分 main/agent scope 注入。

交付：

```text
mid-term 有独立 section，不再混在 Long-term memory 下。
```

实现状态（2026-04-29）：

```text
已完成第一批 mid-term 独立注入：
- 复用现有 memory rolling/daily Markdown 读取能力
- 不新增向量、不新增 SQLite、不新增 chunk index
- ContextAssembler 按 tags 将 mid_term 记录从 memory lanes 中拆出
- prompt 中新增独立 Mid-term context section
- mid-term 不再渲染到 Long-term memory - Other relevant memory
```

### Phase E：细化 long-term 注入

目标：

1. shared long-term 和 agent overlay 分开。
2. facts 按 confidence / injectPolicy 排序。
3. DeerFlow history 作为 long-term background 注入。

交付：

```text
Long-term section 能区分 profile/history/facts/agent overlay。
```

实现状态（2026-04-29）：

```text
已完成第一批 long-term 分层注入：
- MemoryItem 保留 scope / memory_layer / source_kind / metadata
- MemoryManager 从 memory MemoryRecord 转换时不再丢失 memory_layer 与 scope
- ContextAssembler 将 long-term summary、facts、mid-term 拆成不同 section
- long_term.json / long_term_overlay.json 的内容进入 Long-term summaries
- facts.jsonl 的内容进入 Long-term facts，并按 Shared / Agent overlay 分 section
- mid-term Markdown 继续保持独立 Mid-term context section
```

### Phase F0：Multi-agent Scaffold，不做调度

目标：

1. 先把多 agent 协作协议占位做好。
2. 不实现 main-agent 调用 other-agent。
3. 不引入独立 `AgentSession`。
4. 不引入 task queue / scheduler / worker runtime。

交付：

```text
ContextAssembler 能识别未来 multi-agent 协作事件，但 runtime 暂不生成这些事件。
```

实现状态（2026-04-29）：

```text
已完成第一批 scaffold：
- 新增 agent_task_assigned / agent_result_summary 事件常量
- 新增 AgentTaskAssignedPayload / AgentResultSummaryPayload
- ContextAssembler 新增 ShortTermContextPlan
- shared_session_state 的 prompt 语义收敛为 Main orchestration state
- other-agent 可从事件中读取发给自己的 Assigned agent tasks
- main-agent 可从事件中读取 Child agent result summaries
- 仅搭协议和注入入口，不做 agent 调度执行
```

### Phase G0：Prompt 输出验收与减法

目标：

1. 不继续扩展新架构。
2. 用真实 session 检查最终 system prompt。
3. 只做文案和展示层减法。

实现状态（2026-04-29）：

```text
已完成第一批 prompt 减法：
- 用 sess_0a73f1415002 组装实际 prompt 做人工验收
- system prompt 从约 5368 字符降到约 3193 字符
- 输出规则从 14 条压缩为 7 条
- tool catalog 只展示工具描述第一句，不再像工具手册一样展开
- state_publish/state_list 的展示文案收敛到 main orchestration state
- 不改底层 state 存储结构，不新增 multi-agent 调度逻辑
```

---

## 14. 测试策略

新增测试建议：

1. main-agent 会注入 main state，不默认注入 child raw events。
2. other-agent 不注入 main orchestration state。
3. other-agent 只看到自己的 recent events。
4. child result summary 可以被 main-agent 看到。
5. `AGENT.md` / `SOUL.md` 始终全量注入。
6. skill/tool catalog 只在 prompt 展示 name + description。
7. mid-term 有独立 section。
8. long-term shared / agent overlay 分 section。
9. 关闭 cross-agent capability 时，不能读取其他 agent private context。
10. 打开 main-agent read capability 时，可显式读取 child summary。
11. other-agent 可以看到 target 指向自己的 `agent_task_assigned`。
12. main-agent 可以看到 target 指向自己的 `agent_result_summary`。

---

## 15. 当前待决问题

1. 是否引入独立 `AgentSession` 模型。
2. `task/handoff` 第一批已选择 event payload，后续是否独立文件待定。
3. main-agent 读取 child context 时，默认读 summary 还是允许读 raw events。
4. child agent 的 result summary 由 child 自己产出，还是 runtime 自动压缩。
5. long-term 的 DeerFlow `history` 是写在 shared long_term，还是单独 JSON section。
6. main-agent 真正派发 other-agent 的 runtime 调度链路何时启动。

---

## 16. 最终方向

最终目标不是让每个 agent 看到更多上下文，而是让每个 agent 只看到自己完成任务所需的上下文。

关键原则：

```text
main-agent 拥有编排视角。
other-agent 拥有局部执行视角。
session/state/events 默认按 agent 隔离。
main-agent 可以通过权限读取其他 agent 的摘要。
raw events 和 private state 不默认跨 agent 注入。
shared long-term memory 是稳定共享知识，不是 shared short-term workspace。
```

这套设计能避免 `shared_session` 变成新的“什么都往里塞”的容器，也能为后续真正的 multi-agent 协作留下清晰边界。
