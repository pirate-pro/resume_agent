# M63 工具路由收敛方案

> 状态：第一层已实现并完成 targeted tests + P1 focused live smoke。本文定义工具选择、工具可见性、ToolGateway、RAG MCP 与 LangGraph 的边界。

## 0. 本轮落地结果

已完成第一层收敛：

- `RuntimeToolPlan.next_allowed_tools` 非空时，本轮模型只暴露这些工具 schema，不再默认暴露 `tool_search` / `memory_write`。
- 本轮用户消息里的受控产品 id 会进入 `WorkflowPhaseSnapshot`；例如 `application_id=application_xxx` 会让项目级 `resume_version` 首步直接走 `career_application_get`。
- `build_runtime_tool_plan` 信任 phase snapshot 里已完成输出的 refs，避免已有上下文只停留在提示文本里。
- `tool_search` 被 runtime plan 接管时输出 `tool_route_decision_source=runtime_plan`，并保留 catalog 命中字段用于排查。
- `learning_task_create.output_artifact_id` 对不存在的可选输出 artifact 做忽略容错，避免可恢复伪 id 造成一次失败工具结果和重复写调用。

验证结果：

- `career_custom_resume` focused live smoke：通过，121.42s，工具链为 `career_application_get -> career_resume_version_create -> career_application_merge`，`tool_search=0`，hidden=0。
- RAG focused live smoke：
  - `rag_to_note`：通过，工具链为 `retrieval_search -> retrieval_context_pack -> note_create`。
  - `interview_review`：通过，工具链为 `retrieval_search -> retrieval_context_pack -> note_create -> career_application_merge`。
  - `rag_to_learning_task`：第一次暴露出 `learning_task_create.output_artifact_id` 伪 id 容错问题；修复后重跑通过，工具链为 `retrieval_search -> retrieval_context_pack -> learning_task_create`，重复=0，hidden=0。

## 1. 背景

当前分支里，工具链路已经不是单一的 `tool_search -> reveal schema`。

历史上分了几次演进：

- M23：引入 `tool_search` / search disclosure，目标是降低一次性暴露全部工具 schema 的 token 成本。
- M27：引入 `ToolGateway` / `ToolCallLedger`，目标是把工具执行收口到幂等、ledger、guard、runner 之后再落真实工具。
- M30：收敛 main-agent 在确定性 workflow 阶段仍调用 `tool_search` / `memory_write` 的浪费。
- M42：拆出 `ToolCallController`、`ActionPlan`、`ToolGatewayPolicy`，把 runtime / workflow / gateway 的职责做结构解耦。
- M58：RAG 工具可切到 MCP proxy，但工具名仍是 `retrieval_search` / `retrieval_context_pack`。
- M59-M62：LangGraph workflow 通过 `ToolGateway.execute_async()` 直接执行节点工具，不通过 `tool_search` 做工具发现。

这些方向都对，但现在留下了一个边界问题：工具“选择权”分散在多个层里。

## 2. 当前真实链路

### 2.1 Main Agent 普通 runtime

```text
ContextAssembler
  -> RuntimeToolPlan
  -> ToolRevealState
  -> model.generate(tools=visible_tools)
  -> AgentRuntime pre-gateway repair/suppression
  -> ToolGateway
  -> WorkflowGuard
  -> ToolCallLedger
  -> ToolExecutionRunner
```

其中：

- `RuntimeToolPlan` 决定当前阶段、已知 ids、缺失产物、下一步工具；
- `ToolRevealState` 决定本轮模型能看到哪些 schema；
- `tool_search` 只应该在 runtime plan 无法确定下一步时使用；
- `ToolGateway` 是工具执行入口，不应该承担模型调用前的工具选择职责。

### 2.2 ToolSearch 目录查询

`tool_search` 仍使用本地 catalog：

```text
query / groups
  -> ToolCatalog matched_groups
  -> reveal_packs
  -> revealed_tool_names
```

catalog 里仍有关键词分组：

- `retrieval`
- `artifact`
- `career_read`
- `career_diagnosis`
- `career_jd_fit`
- `career_resume_version`
- `career_application`
- `note`
- `learning`
- `delegation`

但当 `RuntimeToolPlan` 存在且适用时，`tool_search` 会覆盖 reveal 结果，返回 `runtime_next_allowed_tools`。

### 2.3 RAG MCP

RAG MCP 只影响 `retrieval_search` / `retrieval_context_pack` 的执行后端。

```text
retrieval_search
  -> RetrievalMcpSearchTool
  -> app.mcp.retrieval_server
  -> RetrievalService
```

它不参与 `tool_search` 的工具发现决策。

### 2.4 LangGraph workflow

LangGraph 节点直接执行固定工具：

```text
node retrieval_search
  -> ToolGateway.execute_async(retrieval_search)
node retrieval_context_pack
  -> ToolGateway.execute_async(retrieval_context_pack)
node write_note
  -> ToolGateway.execute_async(note_create)
```

LangGraph 的 LLM draft 阶段 `tool_schema_count=0`，不通过 `tool_search` 选择工具。

## 3. 现有问题

### 3.1 ToolGateway 不能减少模型发起多余 tool_search 的成本

ToolGateway 发生在模型已经输出 tool_call 之后。

它能做到：

- block；
- reuse；
- guard repair；
- ledger 幂等；
- 防止真实重复副作用。

它不能做到：

- 阻止模型在调用前多想一轮；
- 阻止模型先发出一次 `tool_search`；
- 降低已经发生的 LLM round 成本。

所以 M27 的 ToolGateway 不是现在工具搜索浪费的根因，也不是完整解法。

### 3.2 M30 收敛只覆盖了部分场景

当前 `_visible_tool_definitions_for_runtime_plan()` 的关键行为是：

```text
required/completion tool 已可见
  -> 隐藏 tool_search / memory_write / discouraged tools
```

但如果当前 runtime plan 的下一步只是前置读取工具，例如：

```text
career_application_list
career_application_get
retrieval_search
```

则 `tool_search` 仍可能可见。

最近 `career_custom_resume` live smoke 证据：

```text
round 0 visible = memory_write, tool_search, career_application_list
round 1 visible = career_application_list
round 2 visible = memory_write, tool_search, career_application_list
round 3 visible = career_application_get
round 4 visible = career_resume_version_create
round 5 visible = career_application_merge
```

结果虽然通过，但多了 2 次 `tool_search` 和多轮 LLM 等待。

### 3.3 tool_search payload 同时包含两套语义

当前 payload 可能同时出现：

```text
matched_groups / reveal_packs / routing_guidance
runtime_plan_applied
runtime_next_allowed_tools
runtime_discouraged_tools
runtime_upcoming_required_tools
```

这会造成两类混乱：

- 模型可能被旧 catalog guidance 误导，继续搜或走 delegation；
- 人看日志时也不容易判断本轮到底是谁决定了下一步工具。

### 3.4 prompt 仍暴露 capability groups

search disclosure 模式下，prompt 仍会展示：

```text
Available capability groups through tool_search
Use tool_search when a needed capability is not visible
```

当 runtime plan 已经有 `next_allowed_tools` 时，这段提示不应该再成为主导信息。

## 4. 目标

M63 的目标是把工具路由收敛为清晰的优先级：

```text
LangGraph fixed node
  > RuntimeToolPlan
  > ActionContract / deterministic executor
  > tool_search catalog
  > full schema fallback
```

具体目标：

1. 确定性 workflow 阶段不再通过 `tool_search` 找下一步工具。
2. `RuntimeToolPlan.next_allowed_tools` 非空时，本轮工具面只暴露这些工具和必要支持工具。
3. `tool_search` 只用于 runtime plan 为空、用户意图确实需要探索未知能力的场景。
4. `ToolGateway` 继续只负责执行合法性、幂等、ledger、guard，不上移为工具选择器。
5. LangGraph 和 RAG MCP 现有路径不回退。
6. smoke/report 能直接看出每轮工具路由由谁决定。

## 5. 非目标

本阶段不做：

- 不重写 ToolGateway。
- 不删除 ToolCatalog。
- 不改变 RAG MCP server/proxy 协议。
- 不迁移更多业务流程到 LangGraph。
- 不放宽 career / note / learning 工具的业务校验。
- 不为了单个 smoke 样本继续堆 prompt 特判。

## 6. 方案设计

### 6.1 引入工具路由决策语义

新增一个轻量路由语义，不一定需要新大类，至少在 payload 和 telemetry 中统一字段：

```text
tool_route_decision_source:
  langgraph_node
  runtime_plan
  action_contract
  tool_search_catalog
  full_schema
```

在 `llm_usage` / smoke report 中记录：

- `tool_route_decision_source`
- `initial_visible_tool_names`
- `runtime_plan_phase`
- `runtime_next_allowed_tools`
- `tool_search_count`
- `runtime_plan_applied_tool_search_count`

### 6.2 RuntimeToolPlan 优先控制可见工具

调整可见工具策略：

```text
if pending_runtime_plan.final_answer_ready:
    visible_tools = []
elif pending_runtime_plan.next_allowed_tools:
    visible_tools = next_allowed_tools + allowed_support_tools
else:
    visible_tools = ToolRevealState.visible_definitions()
```

关键变化：

- 不再等 required/completion tool 可见才隐藏 `tool_search`；
- 只要 runtime plan 已经明确当前下一步，就不暴露 `tool_search`；
- `memory_write` 同样从确定性 workflow 阶段隐藏；
- `allowed_support_tools` 只保留已明确允许的支持工具，例如特定阶段允许的 `session_create_text_artifact`。

### 6.3 ToolSearch runtime plan 覆盖时降级 catalog 信息

当 `ToolSearchTool` 应用 runtime plan 时：

```text
decision_source = runtime_plan
revealed_tool_names = runtime_next_allowed_tools
catalog_matched_groups = 原 matched_groups
catalog_reveal_packs = 原 reveal_packs
routing_guidance = null
next_step = 直接调用 runtime_next_allowed_tools
```

保留 catalog 信息只用于 debug，不再作为模型行动建议。

### 6.4 Prompt 中区分“工具探索”和“确定性下一步”

如果 `RuntimeToolPlan.next_allowed_tools` 非空：

- tool catalog section 不再强调 `Available capability groups through tool_search`；
- 明确写：

```text
Current runtime plan has selected the next visible tool set.
Do not call tool_search for this step.
```

如果 runtime plan 为空：

- 仍展示 capability groups；
- 允许 `tool_search` 作为探索工具。

### 6.5 修正 career_custom_resume 的第一步

当前 seeded 项目动作已把 `application_id` 写入用户消息：

```text
当前求职项目 application_id 是 ...
```

因此 runtime plan 不应先暴露 `career_application_list`。

目标链路：

```text
career_application_get
  -> career_resume_version_create
  -> career_application_merge
```

仅当 `application_id` 缺失时，才允许：

```text
career_application_list
  -> career_application_get
```

### 6.6 保留 LangGraph 直连工具节点

LangGraph workflow 保持：

```text
node -> ToolGateway.execute_async(tool)
```

不引入 `tool_search`。

验收时只确认：

- `tool_schema_count=0`；
- 节点工具仍走 `ToolGateway`；
- 写入失败恢复和幂等不回退。

## 7. 分步实施

### M63-A：文档与观测字段

- 落本文档。
- 增加 route decision 的报告字段。
- smoke report 打印：
  - 首轮 visible tools；
  - tool_search 次数；
  - runtime_plan_applied 次数；
  - LangGraph direct node 次数。

不改变行为。

### M63-B：ToolSearch payload 收敛

- runtime plan 生效时，清理模型可见的旧 catalog guidance；
- 增加 `decision_source=runtime_plan`；
- catalog 匹配信息改为 debug 字段。

### M63-C：RuntimeToolPlan 控制可见工具

- 只要 `next_allowed_tools` 非空，就隐藏 `tool_search`；
- 保留支持工具白名单；
- 补单测覆盖：
  - next_allowed 为 `career_application_list` 时不暴露 `tool_search`；
  - next_allowed 为 `career_application_get` 时不暴露 `tool_search`；
  - runtime plan 为空时仍可见 `tool_search`。

### M63-D：custom_resume 首步收敛

- 有 `application_id` 时首轮直接 `career_application_get`；
- 不再先 list；
- 验证 `career_custom_resume` 工具链路无 `tool_search`。

### M63-E：live smoke 回归

最小 live smoke：

```text
tools/smoke_live_matrix.py \
  --scenario career_custom_resume \
  --scenario rag_to_note \
  --scenario rag_to_learning_task \
  --scenario interview_review \
  --runs 1 \
  --concurrency 2 \
  --stream
```

必要时再补：

```text
--scenario career_full
--scenario interactive_rag_to_note_source_select
--scenario interactive_interview_review_scope_select
```

## 8. 验收标准

### 8.1 结构验收

- `ToolGateway` 仍是唯一工具执行入口。
- `retrieval_search` 默认仍走 MCP proxy。
- LangGraph 节点不调用 `tool_search`。
- search disclosure 在 runtime plan 为空时仍可用。

### 8.2 行为验收

`career_custom_resume`：

```text
tool_search_count = 0
tools = career_application_get, career_resume_version_create, career_application_merge
```

RAG 非交互动作：

```text
rag_to_note:
  retrieval_search -> retrieval_context_pack -> note_create

rag_to_learning_task:
  retrieval_search -> retrieval_context_pack -> learning_task_create

interview_review:
  retrieval_search -> retrieval_context_pack -> note_create -> career_application_merge
```

LangGraph 交互动作：

```text
tool_schema_count = 0
workflow_node_started / workflow_node_succeeded 正常
写入节点 exactly-once 不回退
```

### 8.3 性能验收

目标不是承诺固定秒数，因为 live LLM 会受 provider 波动影响。

但必须达到：

- `career_custom_resume` LLM round 数下降；
- `career_custom_resume` 不再出现 `tool_search`；
- P1 seeded 4 场景仍 4/4 passed；
- harmful duplicate 0；
- hidden run 0。

## 9. 风险与控制

### 风险 1：隐藏 tool_search 后，错误 runtime plan 会卡住模型

控制：

- 只在 `next_allowed_tools` 非空时隐藏；
- runtime plan 为空仍保留 `tool_search`；
- hidden tool / gateway block 仍返回 recoverable correction；
- smoke 覆盖 unknown/general 场景，确认普通探索不受影响。

### 风险 2：支持工具被误隐藏

例如某些阶段需要 `session_create_text_artifact` 辅助生成 artifact。

控制：

- 保留 `allowed_support_tools`；
- 复用现有 `hidden_runtime_support_tool_allowed` 规则；
- 用单测锁住 resume_version / note_write 的支持工具行为。

### 风险 3：LangGraph 和 main-agent runtime 的规则混淆

控制：

- route decision source 明确标注 `langgraph_node`；
- LangGraph draft LLM 不暴露工具 schema；
- LangGraph 写节点只通过 ToolGateway 执行真实工具。

## 10. 判断

这次问题不是 ToolGateway 改坏了。

ToolGateway 当时解决的是：

- 工具执行顺序；
- 幂等；
- ledger 复用；
- guard 兜底；
- 副作用安全。

现在遗留的是模型调用前的工具面控制没有完全收敛：

- M30 只覆盖了 required/completion tool 已可见后的阶段；
- `career_application_list/get` 这类前置读取阶段仍可能暴露 `tool_search`；
- `tool_search` payload 仍混合 catalog guidance 和 runtime plan guidance。

M63 应该把“工具选择权”前移并统一到 RuntimeToolPlan / LangGraph node，而不是继续依赖 ToolGateway 在执行阶段兜底。
