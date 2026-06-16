# M59 LangGraph Workflow 编排接入方案

> 状态：M59-A 方案文档已落地；M59-B 依赖、配置和 runner skeleton 已落地；M59-C resume stream API 和 workflow SSE 事件已落地；M59-D `rag.note.write.interactive.v1` graph 已落地；M59-E 已补 pause/resume/retry/幂等单测；M59-F 已补交互式 live smoke matrix，并完成新旧矩阵验证；M59-G 已完成下一条 workflow 评估；M60-A 已新增 `interview.review.update.interactive.v1` id / state / runner skeleton / router flag；M60-B 已实现 read-only `retrieval_search` 和 `interview_review_scope` interrupt；M60-C 已实现 `retrieval_context_pack`、复盘草稿生成和 `interview_review_confirmation` interrupt；M60-D 已接 `note_create` 和 `career_application_merge`，并补写入幂等/恢复单测；M60-E 已把 Interview Review workflow 接入 ChatService dispatcher，并完成新增 live smoke 与旧矩阵回归；M61-A 已新增 WorkflowInstanceStore 状态投影，并接入 SQLite durable checkpoint backend；M61-B 已新增 `workflow_version` / `expected_version` 与 SQLite resume lease，挡住旧暂停卡片和跨进程同一 workflow 并发 resume；M61-C 已完成真实服务进程重启、跨进程并发 resume、最终写入 exactly-once 的 live smoke；M61-D 已统一两条 graph 的写入失败恢复协议，并让 Interview Review 的 `note_create` / `career_application_merge` 在自动尝试耗尽后进入可持久化的 retry/cancel interrupt。SQLite checkpointer 当前通过 `aiosqlite==0.20.0` 和 metadata serde compatibility shim 接入官方 `AsyncSqliteSaver`，避免用业务 snapshot 伪造 checkpoint 恢复。本文承接 M27/M39/M42/M58：当前已经有 `UnifiedWorkflowState`、`WorkflowContract` / `ActionContract`、`ToolGateway`、`ToolCallLedger` 和 Retrieval MCP backend。M59 不重写这些边界，而是把 LangGraph 接到“可恢复 workflow 编排、失败重试、人机交互暂停/恢复”这一层。

## 1. 背景

当前 runtime 已经能完成多数固定链路，但复杂度越来越集中在 `AgentRuntime`：

```text
用户意图
  -> RuntimeToolPlan / WorkflowContract
  -> 模型工具循环
  -> ToolGateway / ToolCallLedger / WorkflowRuntimeGuard
  -> 产品记录或 artifact
```

这套链路的问题不是不能跑，而是三类体验和工程问题会继续放大：

1. 失败恢复不够显式。
   - 某一步失败后，当前主要靠模型下一轮理解 tool result，再尝试继续。
   - 如果需要“失败节点重试，成功后接着往下走”，显式 graph state 比工具循环更稳。
2. 用户交互不是一等状态。
   - 例如“根据哪些内容生成笔记”，当前只能靠模型在聊天里问，后端没有持久化的暂停点。
   - 用户补充输入后，系统很难证明它是恢复同一个 workflow，而不是开了一个新回合。
3. 长链路和 fan-out/fan-in 不适合继续堆在 runtime 主循环里。
   - `AgentTaskRuntime` 目前只支持独立并发任务，`depends_on` 仍是 reserved。
   - 后续如果有 DAG、重试、恢复、并行聚合，继续手写会扩大维护成本。

LangGraph 的价值正好在这里：

- persistence / checkpoint：保存 graph state，支持中断后恢复。
- interrupt：在节点里暂停，等待用户输入，再用同一 thread 恢复。
- retry / timeout / error handler：节点级失败处理。
- conditional edge / fan-out / fan-in：把当前合同步骤变成可读的 graph。

参考官方文档：

- LangGraph overview: <https://docs.langchain.com/oss/python/langgraph/overview>
- Persistence: <https://docs.langchain.com/oss/python/langgraph/persistence>
- Interrupts: <https://docs.langchain.com/oss/python/langgraph/interrupts>
- Fault tolerance: <https://docs.langchain.com/oss/python/langgraph/fault-tolerance>

## 2. 核心判断

### 2.1 不全量替换 AgentRuntime

第一版不做：

- 不把普通聊天全部迁到 LangGraph。
- 不把现有模型工具循环删掉。
- 不把所有 workflow 一次性编译成 graph。
- 不绕开 `ToolGateway` 直接调用业务 tool。
- 不把 Retrieval MCP 回退成本地服务调用。

原因：

```text
LangGraph 负责编排、checkpoint、interrupt、retry。
ToolGateway 负责工具合法性、幂等、副作用账本和 guard 兜底。
Retrieval MCP 负责 RAG 能力边界。
AgentRuntime 继续负责默认通用聊天和未 graph 化的路径。
```

### 2.2 第一刀做 RAG -> Note 交互式 workflow

第一条链路选 `rag.note.write.v1` 的交互式版本。

原因：

- 它已经有 `ActionContract` 基础：`retrieval_search -> retrieval_context_pack -> note_create/note_append`。
- 它和用户体验诉求直接对应：生成笔记前询问依据哪些内容、允许用户补充。
- 它有 RAG、模型生成、用户确认、写 Note，能覆盖 LangGraph 的核心价值。
- 它不涉及 Career 主链路大范围状态迁移，风险可控。

第一版命名：

```text
rag.note.write.interactive.v1
```

## 3. 目标

M59 第一阶段目标：

- 新增 LangGraph workflow runner，作为 `ChatService` 和 `AgentRuntime` 之间的可选路由。
- 支持 graph thread / checkpoint / resume。
- 支持 structured interrupt，让前端能展示“选择来源 / 补充内容 / 确认草稿”。
- `rag.note.write.interactive.v1` 完成端到端：
  - RAG 检索；
  - 询问用户选择来源；
  - 接收用户补充；
  - 组装 context pack；
  - 生成 Note 草稿；
  - 用户确认或编辑；
  - 通过 `ToolGateway` 写 Note；
  - 返回最终结果。
- 节点失败支持有限重试和可恢复失败态。
- 默认普通聊天路径不变。

成功标准：

```text
1. 旧 live smoke 不回归。
2. 新 interactive rag_to_note smoke 可暂停、恢复、最终写入 Note。
3. interrupt 后恢复不会重复执行已成功的副作用工具。
4. 失败重试不会绕过 ToolGateway / ToolCallLedger。
5. 用户补充内容进入最终 Note 的 source / evidence 说明。
```

## 4. 非目标

M59 第一阶段不做：

- 不迁移 `career_full` 全链路。
- 不迁移 `AgentTaskRuntime` fan-out/fan-in。
- 不做 LangGraph Platform / hosted Agent Server。
- 不做 LangSmith 强依赖。
- 不新增数据库服务；checkpoint 第一版先用本地持久化方案。
- 不重做前端页面，只扩展现有 SSE 事件和最小交互 payload。
- 不改变 RAG MCP 已完成的默认 backend。

## 5. 总体架构

新增一层 workflow router：

```text
ChatService
  -> WorkflowRouter
       -> 命中 graph workflow:
            WorkflowGraphRunner
              -> LangGraph compiled graph
              -> Graph node
              -> ToolGateway.execute_async()
              -> ToolCallLedger / WorkflowRuntimeGuard / ToolExecutor
       -> 未命中:
            AgentRuntime.run / run_stream
```

`WorkflowRouter` 只做保守命中：

```text
用户明确要求：
  - 根据已有材料生成笔记
  - 根据检索 / 之前记录 / 求职材料保存笔记
  - 需要先选择来源再生成笔记

命中 rag.note.write.interactive.v1
```

其他请求继续走原 `AgentRuntime`。

## 6. Graph State

新增窄状态，不直接塞完整 `AgentRunInput`：

```text
WorkflowGraphState
  session_id: str
  run_id: str
  workflow_instance_id: str
  thread_id: str
  contract_id: str
  user_goal: str
  phase: str
  known_refs: dict
  retrieval_candidates: list
  selected_source_refs: list
  user_supplement: str | None
  context_pack_ref: dict | None
  draft_note: dict | None
  pending_question: dict | None
  retry_counters: dict
  last_error: dict | None
  outputs: dict
```

`thread_id` 不能只用 `session_id`。

建议：

```text
thread_id = "{session_id}:{workflow_instance_id}"
```

原因：

- 一个 session 里可能有多个未完成 workflow。
- LangGraph checkpoint 需要稳定 thread id 才能 resume。
- 后续可以在 session events 中按 `workflow_instance_id` 查询 pending workflow。

## 7. 第一条 Graph

`rag.note.write.interactive.v1`：

```text
START
  -> init_request
  -> retrieval_search
  -> maybe_ask_source_selection
  -> retrieval_context_pack
  -> draft_note
  -> maybe_ask_note_review
  -> write_note
  -> final_answer
  -> END
```

### 7.1 init_request

职责：

- 建立 `workflow_instance_id`。
- 写入 `workflow_started` event。
- 从当前 session / active artifacts / user message 中提取初始 goal。
- 生成初始 retrieval query。

不做：

- 不调用写工具。
- 不做用户 interrupt。

### 7.2 retrieval_search

职责：

- 构造 `ToolCall(name="retrieval_search", arguments=...)`。
- 通过 `ToolGateway.execute_async()` 执行。
- 保存候选来源到 `retrieval_candidates`。

失败策略：

- provider / transient / timeout：node retry。
- 参数校验失败：进入 `repair_retrieval_query` 或失败态。
- 无结果：interrupt 询问用户是否补充更多信息或改写目标。

### 7.3 maybe_ask_source_selection

触发条件：

- 候选来源超过 1 个；
- 候选来源置信度不够；
- 用户原话表达“按哪些内容生成 / 让我选择依据”；
- workflow 配置要求强制确认来源。

interrupt payload：

```json
{
  "type": "source_selection",
  "workflow_instance_id": "wf_xxx",
  "question": "选择用于生成笔记的来源",
  "candidates": [
    {
      "source_ref": {"source_type": "note", "source_id": "note_xxx"},
      "title": "xxx",
      "snippet": "xxx",
      "score": 0.82
    }
  ],
  "allow_extra_input": true,
  "allow_skip": false
}
```

用户 resume payload：

```json
{
  "selected_source_refs": [
    {"source_type": "note", "source_id": "note_xxx"}
  ],
  "user_supplement": "还要加上我今天补充的面试反馈..."
}
```

### 7.4 retrieval_context_pack

职责：

- 只使用用户确认后的 source refs。
- 把用户补充内容作为 manual source / supplemental context 进入状态。
- 通过 Retrieval MCP-backed tool 构建 context pack。

不做：

- 不写 Note。
- 不让模型自由决定额外来源，除非再次 interrupt。

### 7.5 draft_note

职责：

- 使用 context pack + supplement 生成结构化草稿：

```text
title
body_markdown
summary
tags
source_refs
evidence_refs
```

失败策略：

- LLM 调用失败：node retry。
- 草稿缺关键字段：本节点内修复一次；仍失败则进入 `note_review_interrupt`，让用户补充。

### 7.6 maybe_ask_note_review

触发条件：

- 配置要求写入前确认；
- 用户选择了“先预览”；
- source/evidence 不明确；
- draft confidence 低；
- 即将执行 `note_create`。

interrupt payload：

```json
{
  "type": "note_review",
  "workflow_instance_id": "wf_xxx",
  "draft": {
    "title": "xxx",
    "body_markdown": "xxx",
    "summary": "xxx",
    "tags": ["xxx"]
  },
  "source_refs": [],
  "actions": ["approve", "edit", "regenerate", "cancel"]
}
```

用户 resume payload：

```json
{
  "action": "approve",
  "edited_draft": null
}
```

关键约束：

```text
interrupt 前不能执行 note_create / note_append。
LangGraph resume 会重新跑当前 node，副作用必须放在确认后的独立 write_note node。
```

### 7.7 write_note

职责：

- 构造 `note_create` 或 `note_append` 的 ToolCall。
- 通过 `ToolGateway.execute_async()` 执行。
- 从 tool result 解析 `note_id`。
- 写入 `workflow_completed` event。

失败策略：

- 如果是参数格式问题：进入 `repair_note_payload`，最多一次。
- 如果是可幂等写失败：允许 retry，但必须复用同一业务 idempotency key。
- 如果是非幂等或不确定失败：停止并给用户可恢复错误，不继续盲写。

### 7.8 final_answer

职责：

- 返回用户可见结果。
- 不泄露 graph / runtime 内部状态。
- 包含 Note id、标题、使用的来源摘要。

## 8. 交互协议

现有 `/api/chat/stream` 可继续作为启动入口。

新增一种 resume 入口，二选一：

方案 A：

```text
POST /api/workflows/{workflow_instance_id}/resume/stream
```

优点：

- 语义清楚。
- 前端能明确知道这是恢复 pending workflow。
- 不污染普通 chat request。

方案 B：

```text
POST /api/chat/stream
{
  "session_id": "...",
  "message": "...",
  "resume_workflow": {
    "workflow_instance_id": "wf_xxx",
    "payload": {}
  }
}
```

优点：

- 接口数量少。
- 前端改动小。

建议第一版用方案 A，避免把普通聊天和 workflow resume 混在一个 DTO 里。

SSE 事件新增：

```text
workflow_started
workflow_node_started
workflow_node_succeeded
workflow_node_failed
workflow_waiting_for_input
workflow_resumed
workflow_completed
workflow_failed
```

`workflow_waiting_for_input` 必须结构化，不使用纯自然语言：

```json
{
  "workflow_instance_id": "wf_xxx",
  "thread_id": "sess_xxx:wf_xxx",
  "interrupt_type": "source_selection",
  "payload": {}
}
```

## 9. Checkpoint 与持久化

第一版 checkpoint 选择：

```text
测试：InMemorySaver
本地开发 / live smoke：InMemorySaver 或 SQLite
本地 durable：SQLite
多机器生产化后：再评估 PostgreSQL / LangGraph 官方持久化库
```

本项目当前主要存储是 JSONL，但 LangGraph 官方示例常见 SQLite checkpointer。
早期验证中，当前解析到的 `langgraph==1.2.4` / `langgraph-checkpoint==4.1.1` 与 `langgraph-checkpoint-sqlite==2.0.10` 直接组合不兼容：

```text
AsyncSqliteSaver + aiosqlite 0.22: missing is_alive()
SqliteSaver / AsyncSqliteSaver + checkpoint 4.1.1: JsonPlusSerializer has no dumps()
```

M61-A 调整为：

```text
LANGGRAPH_WORKFLOW_BACKEND=memory 仍可用于测试 / 单进程开发；
LANGGRAPH_WORKFLOW_BACKEND=sqlite 可用于本地 durable checkpoint；
锁定 aiosqlite==0.20.0，保留 Connection.is_alive() 兼容；
对 sqlite saver metadata serde 增加 dumps/loads shim，checkpoint 主体仍走 LangGraph typed serde；
WorkflowInstanceStore 只做状态投影 / pending 查询，不作为 checkpoint 恢复事实源。
```

M61-B 对多端 resume 增加两层闸门：

```text
workflow_waiting_for_input payload 携带 workflow_version；
resume API 接收 expected_version，旧卡片 / 旧客户端提交会被拒绝；
WorkflowRunnerDispatcher 在进入 runner 前使用 SQLite resume lease，挡住跨进程同一 workflow_instance_id 并发 resume；
lease 用 TTL 防止进程崩溃后永久占用，正常完成 / 失败都会 release。
```

M61-C 用真实 API 进程验证上述持久化和并发边界：

```text
进程 1：启动 workflow，执行到 scope interrupt 后退出；
进程 2 / 3：共享 SQLite checkpoint、instance projection 和 resume lease，
             使用同一 workflow_version 并发 resume，必须恰好一个成功；
进程 4：再次重启服务，从 durable checkpoint 恢复并确认最终写入；
最终 retrieval_search / retrieval_context_pack / note_create /
career_application_merge 都必须恰好执行一次。
```

建议：

1. 继续封装 checkpointer factory，不让业务代码直接依赖具体 saver。
2. 单测默认用 memory；跨 runner / 重启恢复测试用 sqlite。
3. live smoke 可先用 memory；需要验证热重载/进程切换时使用 sqlite。
4. 不做 JSONL checkpoint adapter；JSONL/JSON projection 只服务查询和审计。
5. 前端必须从最新 `workflow_waiting_for_input.workflow_version` 提交 `expected_version`，不要复用旧暂停卡片。

## 10. 失败恢复策略

失败分层：

### 10.1 可自动 retry

适合：

- LLM provider timeout。
- MCP read-only retrieval timeout。
- 临时网络错误。
- LangGraph node timeout。

策略：

```text
RetryPolicy(max_attempts=3, backoff)
TimeoutPolicy per async node
```

### 10.2 可 repair 后 retry

适合：

- tool 参数 schema 错误。
- Note draft 缺字段。
- source_refs alias 需要 canonicalize。

策略：

```text
repair node 最多 1-2 次。
repair 后仍失败，interrupt 给用户或 workflow_failed。
```

### 10.3 不能盲 retry

适合：

- 已经可能产生副作用但返回不确定。
- note_create 写入结果无法确认。
- career_application_merge 类项目写入。

策略：

```text
必须先查 ToolCallLedger / product store。
能确认成功则复用。
不能确认则进入人工确认或失败态。
```

## 11. 与现有模块关系

### 11.1 ToolGateway

Graph node 调工具必须走：

```text
ToolCall
  -> ToolGateway.execute_async()
  -> ToolCallLedger
  -> WorkflowRuntimeGuard
  -> ToolExecutionRunner
```

禁止：

```text
Graph node -> ToolRegistry.execute()
Graph node -> Service 直接写业务记录
```

### 11.2 ToolCallLedger

LangGraph checkpoint 记录 graph state。

ToolCallLedger 记录真实工具副作用。

两者都需要，不能互相替代：

```text
checkpoint:
  当前 workflow 跑到哪一步。

ledger:
  某个 tool call 是否已经执行、是否可复用、是否已产生业务结果。
```

### 11.3 ActionContract

`ActionContract` 不删除。

M59 第一版做一个 adapter：

```text
ActionContract
  -> Graph plan metadata
  -> nodes / required outputs / forbidden write tools
```

但不要一开始追求“所有 contract 自动编译成 graph”。

### 11.4 Retrieval MCP

RAG 仍走 M58 默认路径：

```text
Graph node
  -> ToolGateway
  -> retrieval_search / retrieval_context_pack tool
  -> internal MCP proxy
  -> Retrieval MCP server facade
  -> RetrievalService
```

不回退到旧本地 retrieval tool。

### 11.5 AgentTaskRuntime

M59 第一阶段不迁移。

后续可迁移点：

```text
AgentTaskRuntime independent tasks
  -> LangGraph fan-out/fan-in subgraph
  -> depends_on
  -> per-child retry / timeout
  -> checkpointed aggregation
```

## 12. 配置

新增配置建议：

```text
LANGGRAPH_WORKFLOW_ENABLED=false
LANGGRAPH_WORKFLOW_BACKEND=memory
LANGGRAPH_CHECKPOINT_PATH=data/langgraph/checkpoints.sqlite
LANGGRAPH_INTERACTIVE_NOTE_ENABLED=false
LANGGRAPH_INTERACTIVE_INTERVIEW_REVIEW_ENABLED=false
LANGGRAPH_NODE_TIMEOUT_SECONDS=90
LANGGRAPH_DRAFT_NODE_TIMEOUT_SECONDS=270
LANGGRAPH_NODE_RETRY_ATTEMPTS=3
```

默认先关闭，开发验证通过后再打开特定 workflow。

说明：

- `LANGGRAPH_NODE_TIMEOUT_SECONDS` 用于检索、写入等普通节点，保持短超时和快速失败。
- `LANGGRAPH_DRAFT_NODE_TIMEOUT_SECONDS` 只用于交互式草稿生成节点，例如 `draft_note` / `draft_review_update`。如果未显式配置，服务注入层会从 `CHAT_STREAM_RUN_TIMEOUT_SECONDS` 派生一个略低于外层 stream timeout 的值，避免 90 秒草稿节点超时触发多次无效重试。

## 13. 实施计划

### M59-A：方案文档

产物：

- 本文档。

验收：

- 明确第一版只做 `rag.note.write.interactive.v1`。
- 明确 LangGraph 不绕开 ToolGateway。
- 明确 interrupt / resume / checkpoint 策略。

### M59-B：依赖与 runner skeleton

改动：

- 添加 `langgraph>=1.2,<2` 依赖。
- 新增 `app/runtime/langgraph/` 包。
- 新增 `WorkflowGraphRunner`、`WorkflowRouter`、`WorkflowGraphState`。
- 单测覆盖 router fallback。

不做：

- 不接真实 Note 写入。

### M59-C：事件和 resume API

改动：

- 新增 workflow SSE event presenter。
- 新增 resume stream 入口。
- pending workflow 写 session event。
- 前端可先只通过已有事件面板观察，不做完整 UI。

验收：

- graph 可以 pause。
- 同一 `workflow_instance_id` 可以 resume。
- resume 使用相同 `thread_id`。

### M59-D：RAG -> Note interactive graph

改动：

- 实现 `rag.note.write.interactive.v1` nodes。
- retrieval / note 写入全部走 `ToolGateway.execute_async()`。
- interrupt source selection 和 note review。

验收：

- 单测覆盖 approve / edit / cancel。
- interrupt 后不会重复 retrieval write；写 Note 只发生在确认后。

### M59-E：失败恢复与幂等验证

改动：

- 节点 retry / timeout。
- repair node。
- ToolCallLedger 与 checkpoint 联合恢复测试。

验收：

```text
1. retrieval_search transient failure -> retry 后继续。
2. note draft malformed -> repair 后继续。
3. note_create 成功后 resume/retry -> 不重复创建 Note。
4. 非幂等不确定失败 -> workflow_failed 或 waiting_for_input。
```

### M59-F：Live smoke

新增场景：

```text
interactive_rag_to_note_source_select
interactive_rag_to_note_user_supplement
interactive_rag_to_note_review_edit
interactive_rag_to_note_retry_retrieval
```

同时跑旧矩阵：

```text
--all-p0 --all-p1
```

验收：

```text
旧矩阵不回归；
新 interactive 场景通过；
note_create / note_append <= 1 per workflow；
retrieval_search / retrieval_context_pack 符合预期；
workflow_waiting_for_input 和 workflow_completed 事件完整。
```

实际落地：

- `tools/smoke_live_matrix.py` 已加入 4 个 `interactive_rag_to_note_*` 场景。
- `tools/smoke_career_live_flow.py` 的 live stack 已补 `ChatService`，新 smoke 走真实 `/chat/stream` 等价路径和 `resume_workflow_stream`，不是直接调用私有 graph runner。
- LangGraph draft 阶段已记录 `llm_usage`，live smoke efficiency 不再把 graph LLM 调用误报为 0。

验证结果：

```text
.venv/bin/python -m pytest
=> 883 passed

.venv/bin/python -m mypy app tests
=> Success: no issues found in 331 source files

.venv/bin/python -m mypy --explicit-package-bases \
  tools/smoke_live_matrix.py \
  tools/smoke_career_live_flow.py \
  tests/test_smoke_live_matrix.py
=> Success: no issues found in 3 source files

.venv/bin/python tools/smoke_live_matrix.py \
  --scenario interactive_rag_to_note_source_select \
  --scenario interactive_rag_to_note_user_supplement \
  --scenario interactive_rag_to_note_review_edit \
  --scenario interactive_rag_to_note_retry_retrieval \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --data-dir data/live_smoke_matrix_m59_interactive_all_usage_r1 \
  --json-report data/live_smoke_matrix_m59_interactive_all_usage_r1/report.json \
  --quiet
=> 4/4 passed

.venv/bin/python tools/smoke_live_matrix.py \
  --all-p0 \
  --scenario career_custom_resume \
  --scenario rag_to_note \
  --scenario rag_to_learning_task \
  --scenario interview_review \
  --runs 1 \
  --concurrency 2 \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m59_old_matrix_r1 \
  --json-report data/live_smoke_matrix_m59_old_matrix_r1/report.json \
  --quiet
=> 11/11 passed
```

说明：

- 旧矩阵回归没有直接使用 `--all-p1`，因为 `--all-p1` 现在已经包含新增 interactive 场景；本次用 `--all-p0` 加旧 P1 显式列表验证原有路径不回归。
- `interactive_rag_to_note_retry_retrieval` live smoke 保持真实 MCP-backed retrieval 链路，没有人工注入检索失败；瞬时检索失败后的 retry 由 `tests/test_langgraph_rag_note_workflow.py` 单测覆盖。

### M59-G：评估下一条 workflow

候选：

1. `rag.learning_task.create.v1`
2. `interview.review.update.v1`
3. `AgentTaskRuntime` fan-out/fan-in
4. `career.resume_version.project_action.v1`

选择标准：

```text
优先迁移需要 checkpoint / interrupt / retry 的链路；
不迁移简单 direct note write；
不为普通聊天引入 graph 开销。
```

评估结论：

```text
下一条优先做 interview.review.update.interactive.v1。
它复用现有 ActionContract: interview.review.update.v1。
```

原因：

- 它同时涉及 RAG、Note 写入和 CareerApplication 更新，失败恢复和幂等风险高于 `rag.learning_task.create.v1`。
- 它适合做第二条 graph：先让用户确认要更新哪些面试结论、风险和下一步行动，再执行写入。
- 它不需要一次性迁移 Career 主链路，比 `career.resume_version.project_action.v1` 风险更可控。

现有边界：

- `app/runtime/workflow/contracts.py` 已有 `interview.review.update.v1`，required outputs 是 `retrieval_search`、`retrieval_context_pack`、`note`、`career_application_update`。
- `app/runtime/workflow/action_plan.py` 已明确顺序：召回后先写 `note_create` / `note_append`，再 `career_application_merge`。
- `app/runtime/workflow/action_payloads.py` 已有面试复盘后的 `career_application_merge` 确定性 payload builder。
- `tests/test_retrieval_action_flow.py` 已覆盖旧路径：工具顺序为 `retrieval_search`、`retrieval_context_pack`、`note_create`、`career_application_merge`，且不写 memory、不创建 LearningTask。

### M59-G.1 Graph 命名和路由

新增 graph workflow：

```text
interview.review.update.interactive.v1
```

它不是替代 `ActionContract`，而是把现有 contract 编排成可暂停、可恢复、可重试的 graph。

Router 命中条件要保守：

- 用户明确表达“刚面完 / 面试复盘 / 记录复盘 / 更新项目 / 更新阶段 / 下一步行动”。
- 用户要求保存复盘或更新求职项目。
- 当前请求不是单纯“根据复盘给建议”。建议类请求继续走现有 read-only RAG 或 learning workflow，不进入写项目 graph。

不命中：

- 只问“下一步怎么准备”。
- 只要求创建学习任务。
- 只要求保存普通笔记，不涉及求职项目更新。

### M59-G.2 Graph 节点

建议节点：

```text
START
  -> init_interview_review
  -> retrieval_search
  -> maybe_ask_review_scope
  -> retrieval_context_pack
  -> draft_review_update
  -> ask_review_confirmation
  -> write_review_note
  -> merge_career_application
  -> final_answer
  -> END
```

节点职责：

1. `init_interview_review`
   - 建立 `workflow_instance_id` 和 `thread_id`。
   - 写 `workflow_started`。
   - 提取用户复盘事实：面试轮次、被问问题、表现、薄弱点、用户禁止事项。
   - 不调用写工具。

2. `retrieval_search`
   - 通过 `ToolGateway` 调 `retrieval_search`。
   - 重点召回 `career_application`、`job_fit_report`、`resume_profile`、`jd_analysis`、历史 `note`。
   - transient failure 可自动 retry。

3. `maybe_ask_review_scope`
   - 如果召回到多个求职项目，或用户没明确要更新哪些字段，则 interrupt。
   - 让用户确认目标项目、是否保存 Note、是否更新阶段、风险、下一步行动、项目备注。
   - 只记录选择，不执行写入。

4. `retrieval_context_pack`
   - 只使用确认后的 application/source refs。
   - 通过 Retrieval MCP-backed tool 构建 context pack。
   - 不让模型自由追加未经确认的项目来源。

5. `draft_review_update`
   - 生成两个草稿：
     - 面试复盘 Note 草稿；
     - CareerApplication update preview。
   - update preview 只能包含 `stage`、`summary`、`next_actions`、`risks`、`notes`。
   - 不生成 LearningTask / WeaknessTracker。

6. `ask_review_confirmation`
   - 写入前 interrupt。
   - 用户可以 approve、edit、regenerate、cancel。
   - 这是执行副作用前最后一道确认。

7. `write_review_note`
   - 用户确认后才调用 `note_create` 或 `note_append`。
   - 第一版建议只做 `note_create`；`note_append` 仅在用户明确选择追加到已有 Note 时启用。
   - `note_id` 使用稳定值，例如 `note_{workflow_instance_id_suffix}`，复用现有 `ToolCallLedger` 幂等规则。

8. `merge_career_application`
   - `note_create` 成功后，再构造 `career_application_merge`。
   - `evidence_refs` 必须包含 `application_id` 和刚写入的 `note_id`。
   - payload 可以复用 `ActionPayloadBuilder.interview_review_application_merge_arguments`，但要允许把用户确认过的 summary / next_actions / risks / notes 覆盖进去。

9. `final_answer`
   - 返回 Note id、项目 id、更新字段摘要。
   - 不泄露 graph 内部状态。

### M59-G.3 Interrupt payload

`maybe_ask_review_scope` payload：

```json
{
  "type": "interview_review_scope",
  "workflow_instance_id": "wf_xxx",
  "question": "确认要更新的面试复盘范围",
  "application_candidates": [
    {
      "application_id": "application_xxx",
      "title": "星河智能 AI 应用开发岗位",
      "stage": "applied",
      "snippet": "..."
    }
  ],
  "default_update_fields": ["stage", "risks", "next_actions", "notes"],
  "allow_save_note": true,
  "allow_update_application": true,
  "allow_user_supplement": true
}
```

resume payload：

```json
{
  "selected_application_id": "application_xxx",
  "save_note": true,
  "update_application": true,
  "update_fields": ["stage", "risks", "next_actions", "notes"],
  "user_supplement": "补充：二面重点准备 RAG 评估和 Celery 延迟队列。"
}
```

`ask_review_confirmation` payload：

```json
{
  "type": "interview_review_confirmation",
  "workflow_instance_id": "wf_xxx",
  "note_draft": {
    "title": "星河智能一面复盘",
    "body_markdown": "...",
    "summary": "...",
    "tags": ["星河智能", "一面", "复盘"]
  },
  "application_update_preview": {
    "stage": "interviewing",
    "summary": "...",
    "next_actions": ["..."],
    "risks": ["..."],
    "notes": "..."
  },
  "actions": ["approve", "edit", "regenerate", "cancel"]
}
```

resume payload：

```json
{
  "action": "approve",
  "edited_note_draft": null,
  "edited_application_updates": null
}
```

### M59-G.4 副作用和幂等

强约束：

```text
interrupt 前不能调用 note_create / note_append / career_application_merge。
write_review_note 成功前不能调用 career_application_merge。
career_application_merge 必须引用刚保存的 note_id。
```

幂等策略：

- `retrieval_search` / `retrieval_context_pack`：read-only，可按节点 retry。
- `draft_review_update`：LLM 生成失败可 retry，malformed draft 先 repair 一次。
- `note_create`：graph 生成稳定 `note_id`，依赖 `ToolCallLedger` 的 `note_create:{session_id}:{note_id}` 幂等 key。
- `note_append`：第一版默认不走；启用时必须由用户选择已有 `note_id`，依赖 `note_append:{session_id}:{note_id}:{hash}`。
- `career_application_merge`：updates 必须稳定，依赖 `career_application_merge:{session_id}:{application_id}:updates:{hash}`。
- 如果 `note_create` 成功但 resume/retry 发生在 merge 前，恢复时复用 `note_id`，只继续 `career_application_merge`。
- 如果 `career_application_merge` 返回不确定失败，先查 ledger / product store；不能确认成功时进入 `workflow_failed` 或人工确认，不盲目重复写。

禁止工具：

```text
learning_task_create
memory_write
delegate_agents
career_resume_version_create
career_jd_analysis_save
career_job_fit_report_save
career_profile_merge
```

### M59-G.5 测试和 smoke

单测：

- router 命中 `interview.review.update.interactive.v1`，advice-only 不命中。
- start 后可进入 `interview_review_scope` interrupt。
- 多 application candidate 时必须等待用户选择。
- approve 后工具顺序固定为 `retrieval_search`、`retrieval_context_pack`、`note_create`、`career_application_merge`。
- edit 会改写 Note 和 application update preview。
- cancel 不产生 Note，也不 merge Application。
- `note_create` 成功后 resume/retry 不重复创建 Note，只继续 merge。
- transient retrieval failure retry 后继续。
- merge 不确定失败不盲目重复写。

live smoke 新增场景：

```text
interactive_interview_review_scope_select
interactive_interview_review_user_supplement
interactive_interview_review_review_edit
interactive_interview_review_resume_after_note_write
```

live gate：

```text
retrieval_search == 1
retrieval_context_pack == 1
note_create + note_append == 1
career_application_merge == 1
learning_task_create == 0
memory_write == 0
delegate_agents == 0
workflow_waiting_for_input >= 2
workflow_completed == 1
notes >= 1
career_applications unchanged in count, updated in content
```

### M59-G.6 实施边界

下一步如果进入实现，建议作为 M60：

```text
M60-A：新增 interview review graph types / runner skeleton / router tests。（已落地，不接真实执行）
M60-B：实现 read-only retrieval + scope interrupt。（已落地）
M60-C：实现 draft + confirmation interrupt。（已落地）
M60-D：接 note_create + career_application_merge，补幂等和 resume 测试。（已落地）
M60-E：补 live smoke matrix 和旧矩阵回归。（已落地）
```

M60 不做：

- 不迁移 `rag.learning_task.create.v1`。
- 不迁移 `career.resume_version.project_action.v1`。
- 不引入新的面试记录 store。
- 不让 graph 直接写业务 store。
- 不改普通聊天默认路径。

M60-A 实际状态：

- 已新增 `INTERVIEW_REVIEW_WORKFLOW_ID` 和 `InterviewReviewGraphState`。
- 已新增 `InterviewReviewWorkflowRunner` skeleton，只构造初始 state，不执行工具。
- 已新增 `LANGGRAPH_INTERACTIVE_INTERVIEW_REVIEW_ENABLED=false`。
- `WorkflowRouter` 可在独立开关开启时识别面试复盘更新请求，但 `ChatService` 在真实 runner 接入前会对非 RAG Note workflow id 回退原 `AgentRuntime`，避免误用 `RagNoteWorkflowRunner`。

M60-B 实际状态：

- `InterviewReviewWorkflowRunner` 当时先接 LangGraph memory checkpointer；M61-A 后可通过统一 `WorkflowCheckpointerHandle` 切到 SQLite durable checkpoint。
- `run_stream` 已执行 `workflow_started -> init_interview_review -> retrieval_search -> interview_review_scope interrupt`。
- `retrieval_search` 通过 `ToolGateway.execute_async()` 执行，pending runtime plan 使用 `interview_review_update` / `interview.review.update.v1`，并显式 discourages 写工具。
- `interview_review_scope` payload 已包含 `application_candidates`、`source_candidates`、默认更新字段和用户补充入口。
- scope resume 目前只确认范围并返回，不进入草稿生成、`note_create` 或 `career_application_merge`。
- `ChatService` 仍未把该 workflow 接到用户默认执行路径，真实接入等 M60-D/M60-E 验证后再打开。

M60-C 实际状态：

- scope resume 后已继续执行 `retrieval_context_pack`。
- `draft_review_update` 已用模型生成 `note_draft` 和 `application_update_preview`。
- 已记录 `llm_usage`，phase 为 `langgraph_interview_review_draft`。
- 已新增 `interview_review_confirmation` interrupt，用户可 `approve` / `edit` / `regenerate` / `cancel`。
- M60-C 当时只确认草稿并返回，不调用 `note_create`、`note_append` 或 `career_application_merge`；该写入链路已在 M60-D 接入。
- live smoke 留到 M60-E。

M60-D 实际状态：

- confirmation resume 后已按固定顺序执行 `note_create -> career_application_merge -> final_answer`。
- `note_create` 使用稳定 `note_id = note_{workflow_instance_id_suffix}`，并写入 `related_application_id`、`source_refs` 和 `evidence_refs`。
- `career_application_merge` 复用 `ActionPayloadBuilder.interview_review_application_merge_arguments`，再覆盖用户确认过的 `application_update_preview`。
- merge payload 的 `evidence_refs` 必须包含刚保存的 `note_id`。
- 写节点会先检查 state outputs：已有 `note_id` 时不重复创建 Note，已有 `application_id` 时不重复 merge。
- 已补单测：完整 approve/edit 写入链路；`career_application_merge` 首次 transient failure 后重试，且 `note_create` 只执行一次。
- M60-D 当时 `ChatService` 默认路径仍未启用该 workflow；M60-E 已通过 dispatcher 接入真实 runner。

M60-E 实际状态：

- 新增 `WorkflowRunnerDispatcher`，`ChatService` 按 workflow id 分发 `run_workflow_stream`，并按 `workflow_instance_id` 恢复同一 runner。
- 真实依赖装配和 `tools/smoke_career_live_flow.py` 已同时注册 `rag.note.write.interactive.v1` 与 `interview.review.update.interactive.v1` runner，仍受各自 feature flag 控制。
- live matrix 新增 3 个 Interview Review 交互场景：
  - `interactive_interview_review_scope_select`
  - `interactive_interview_review_user_supplement`
  - `interactive_interview_review_review_edit`
- live smoke 首轮发现 `note_create` 不接受 retrieval 的 `source_type=note` 作为 NoteSourceRef；已修为：历史 Note 只进入 `evidence_refs`，不进入 `source_refs`，`session_artifact` 映射为 `artifact`。
- `interactive_interview_review_resume_after_note_write` 没有做 live crash injection；恢复后不重复 `note_create` 的保障由单测覆盖。
- 新增 live smoke：`data/live_smoke_matrix_m60_interview_r1_fix1/report.json`，3/3 通过。
- 旧矩阵回归：`data/live_smoke_matrix_m60_old_matrix_r1/report.json`，11/11 通过。
- 最终本地验证：`pytest` 892 passed；`mypy app tests` 通过。

M61-C 实际状态：

- 新增 `tools/smoke_langgraph_restart_resume.py`，通过 4 个真实 Uvicorn 进程验证 SQLite durable checkpoint 和跨进程 resume lease。
- 首个进程在 `interview_review_scope` 暂停后退出；两个并发进程使用相同 `workflow_instance_id` / `expected_version` 恢复，结果恰好 1 个成功、1 个被 `already being resumed` 拒绝。
- 第四个进程重启后从 confirmation interrupt 继续，最终 `retrieval_search`、`retrieval_context_pack`、`note_create`、`career_application_merge` 均恰好执行 1 次。
- 新 smoke 报告：`data/live_smoke_m61_restart_resume_r2/report.json`；4 个服务进程日志位于同目录 `process_logs/`。
- 旧矩阵回归：`data/live_smoke_matrix_m61_old_matrix_r1/report.json`，11/11 通过，0 失败。
- 最终本地验证：`pytest` 902 tests 全通过；`mypy app tests` 342 个源文件通过；新 smoke 脚本 `py_compile` 通过。

M61-D 实际状态：

- 新增共享 `write_retry` helper，统一失败节点、错误摘要、重试轮次和 `retry/cancel` resume payload。
- `rag.note.write.interactive.v1` 复用共享协议，不再维护独立解析器。
- Interview Review 的 `note_create` 和 `career_application_merge` 会先按节点配置自动尝试；耗尽后进入 `workflow_write_retry` interrupt。
- 项目合并失败时取消，只取消项目更新；已经成功创建的 Note 保留，最终答复明确返回 `note_id`。
- SQLite runner 重建测试覆盖等待重试状态的恢复，且项目合并重试不会重复创建 Note。
- 新增真实进程故障注入 smoke：连续两次阻断 `career_application_merge`，在 retry interrupt 后杀掉 Uvicorn，再由新进程从 SQLite checkpoint 恢复。报告位于 `data/live_smoke_m61_write_retry/report.json`，结果为 `note_create=1`、`career_application_merge=3`、最终项目记录 1 条。
- 旧矩阵回归：`data/live_smoke_matrix_m61d_old_matrix_r1/report.json`，11/11 通过，`harmful_duplicate_runs=0/11`、`hidden_runs=0/11`。
- 最终本地验证：`pytest` 907 tests 全通过；`mypy` 345 个源文件通过；Flutter analyze、组件测试和 Web build 通过。

## 14. 测试计划

单测：

- graph state validation。
- workflow router 命中 / fallback。
- interrupt payload schema。
- resume payload validation。
- ToolGateway bridge 调用。
- retry policy。
- note write idempotency。

集成测试：

- start -> source_selection interrupt。
- resume source selection -> draft -> review interrupt。
- approve -> note_create -> final。
- edit -> note_update payload applied before write。
- cancel -> no note write。

live smoke：

- 新增 interactive 场景。
- 保留 M58 MCP 默认 backend 验证。
- 保留 full matrix 回归。

## 15. 风险与控制

风险 1：引入第二套状态机。

控制：

```text
Graph state 只管 workflow 推进；
ToolGateway / ToolCallLedger 继续管工具和副作用；
ActionContract 继续作为业务合同来源。
```

风险 2：interrupt 后重复副作用。

控制：

```text
interrupt node 前不放写工具；
write node 独立；
write node 必须通过 ToolGateway；
恢复测试必须覆盖重复 resume。
```

风险 3：普通聊天路径回归。

控制：

```text
feature flag 默认关闭；
WorkflowRouter 保守命中；
未命中直接走原 AgentRuntime；
full live smoke 必跑。
```

风险 4：checkpoint 存储和现有 JSONL 体系不一致。

控制：

```text
封装 WorkflowCheckpointerHandle；
第一版允许 SQLite durable checkpoint；
WorkflowInstanceStore 仅作为投影，不作为恢复事实源。
```

风险 5：前端改动过大。

控制：

```text
第一版事件 payload 先完整；
UI 可以先用简单卡片承接 source_selection / note_review；
不重做页面。
```

## 16. 审核点

开发前需要确认：

1. 第一条 workflow 是否确定为 `rag.note.write.interactive.v1`。
2. resume API 选方案 A 还是方案 B。
3. 第一版 checkpoint 是否接受 SQLite。
4. `note_review_interrupt` 是否默认开启，还是只在用户要求预览 / 低置信度时开启。
5. feature flag 默认关闭还是开发分支默认开启。

## 17. 结论

M59 的正确切入点不是“把项目改成 LangGraph”，而是：

```text
把需要暂停、恢复、重试、用户参与的 workflow 交给 LangGraph；
把工具执行和副作用继续留在 ToolGateway / ToolCallLedger；
把 RAG 继续留在 Retrieval MCP；
把普通聊天继续留在 AgentRuntime。
```

第一版只做 `rag.note.write.interactive.v1`，把用户选择来源、补充内容、确认草稿这条体验跑通。通过后，再考虑学习任务、面试复盘和 child-agent fan-out/fan-in。
