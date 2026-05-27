# M42：Agent 架构统一与解耦方案

> 状态：M42-A 架构文档已落地；M42-B `ActionPayloadBuilder` 初版已落地；M42-C `ToolCallController` skeleton 已落地；M42-D `action_plan.py` 已拆出；M42-E delegation guard 收缩已落地；M42-F Tool Gateway policy boundary 已落地；M42-G Tool Capability Registry 已落地。本文承接 M41：P0 `career_full` 已通过两批 `6x3` live smoke 停止线，下一阶段不继续为 harmless duplicate 或偶发长尾追加 guard，而是统一 runtime / workflow / state machine / skill / contract / gateway 的职责边界。

## 1. 背景

当前系统已经有一批有效能力：

```text
Tool Call Ledger / idempotency
WorkflowRuntimeGuard
RuntimeToolPlan
WorkflowContract / ActionContract
Deterministic Executor dry-run
DelegateTaskNormalizer
Finalization Packet
Live Smoke Matrix
```

这些能力本身方向没错，但如果继续零散新增，会出现一个新问题：

```text
runtime 里有 workflow；
workflow 里有 guard；
guard 里有 executor；
executor 旁边又有 skill；
action payload 还在 agent_runtime.py；
最终所有东西都能解释为“一个模块”，但工程结构越来越难读。
```

M42 要解决的不是某个 live smoke 失败，而是防止架构继续失焦。

## 2. 外部参考的共同点

调研对象：

```text
DeerFlow
Hermes Agent
OpenClaw
```

共同结论：

```text
1. 成熟 agent 系统不会让主 runtime 承担所有职责。
2. 长任务需要 durable state / task board / ledger，而不是靠模型记住流程。
3. tool / plugin / skill 要通过 capability 或 contract 注册，不直接暴露 runtime 内部 helper。
4. sub-agent 需要隔离上下文和结构化 handoff，不共享一大坨聊天历史。
5. skill 负责程序性知识，workflow/state 负责可靠推进和完成条件。
```

参考点：

```text
DeerFlow:
  - 把自身定位成 long-horizon agent harness，而不仅是 workflow graph。
  - 通过 staged execution、skills、sandbox、memory、subagent、context management 支撑长任务。

Hermes Agent:
  - 用 durable Kanban task board 做多 agent 协作。
  - 每个 task 是持久化记录，handoff 可追踪，worker 有独立上下文和技能。

OpenClaw:
  - Gateway-centric。
  - Gateway 管 state、routing、session、plugin/capability registry。
  - model 是 provider 依赖，不是系统核心。
  - 对外公开 capability contract，不鼓励暴露 runtime plumbing helper。
```

对本项目的启发：

```text
不要再争论“用 workflow 还是 skill”。

正确分工是：
  skill 让模型知道怎么做；
  workflow/contract/state 让系统保证做到哪一步；
  tool gateway 保证调用是合法、幂等、可审计的；
  runtime 只负责一轮模型交互和事件流。
```

## 3. 统一架构语言

后续只使用这几个一级概念，不再随意新增平行概念。

### 3.1 Agent Runtime

职责：

```text
1. 接收用户输入。
2. 组装 context。
3. 调用模型。
4. 处理 streaming。
5. 把模型 tool calls 交给 ToolCallController。
6. 把最终答复发回用户。
```

不负责：

```text
1. 业务 action payload 拼装。
2. workflow phase 推进。
3. task DAG / join / retry。
4. 工具幂等判断。
5. 场景级 guard。
6. 子 agent orchestration 参数修复。
```

目标：

```text
agent_runtime.py 应该变薄。
后续新增业务场景不能继续往 agent_runtime.py 加 if/else。
```

### 3.2 Orchestrator / Workflow Runtime

职责：

```text
1. 根据用户意图和当前状态选择 workflow/action contract。
2. 维护 phase、missing_outputs、known_refs、finalization barrier。
3. 判断 required task / required output 是否完成。
4. 处理 fan-out / fan-in / join。
5. 输出下一步可执行 plan。
```

不负责：

```text
1. 写具体工具 payload 的业务字段。
2. 直接执行工具。
3. 生成开放式内容。
```

边界：

```text
如果下一步唯一、参数可由状态构造，可以交给 executor / payload builder。
如果下一步不唯一，返回 incomplete / clarify，不让 runtime 猜。
```

### 3.3 Contract Registry

Contract 是系统的业务能力声明，不是 prompt。

职责：

```text
1. 声明 workflow/action 的 trigger phase。
2. 声明 required refs。
3. 声明 required outputs。
4. 声明允许/禁止的工具。
5. 声明完成条件。
6. 声明是否允许 deterministic executor。
```

Contract 不负责：

```text
1. 写长提示词。
2. 替模型生成报告正文。
3. 存储运行状态。
```

新增功能必须先回答：

```text
这是一个 skill、action contract，还是 workflow contract？
required refs 是什么？
required outputs 是什么？
哪些工具有副作用？
finalization barrier 是什么？
```

### 3.4 Action Payload Builder

职责：

```text
1. 根据 contract + known_refs + previous tool result 构造确定性工具参数。
2. 只处理参数可由状态推出的 action。
3. 输出 payload 或 missing refs。
```

适合：

```text
interview_review_update -> career_application_merge
rag_to_note -> note_create / note_append
rag_to_learning_task -> learning_task_create
resume_version_project_action -> career_application_merge
```

不适合：

```text
简历正文生成
岗位匹配报告正文生成
开放式建议生成
RAG query 改写
```

### 3.5 Tool Gateway

职责：

```text
1. schema validation。
2. tool visibility / permission。
3. idempotency key。
4. tool call ledger。
5. side-effect classification。
6. approval gate。
7. retry policy。
8. result canonicalization。
```

不负责：

```text
1. 判断业务 workflow 是否应该开始。
2. 生成业务内容。
3. 因为某个 smoke case 失败而猜下一步。
```

原则：

```text
所有工具调用必须经过 gateway。
副作用工具必须可审计、可幂等、可阻断。
```

### 3.6 Skill Layer

Skill 是程序性知识，不是可靠性边界。

职责：

```text
1. 教模型如何完成一类任务。
2. 提供领域步骤、注意事项、模板、引用资源。
3. 降低 prompt 重复和人工指导成本。
4. 让新 agent 获得专门能力。
```

不负责：

```text
1. 判断任务是否完成。
2. 保证 required tool 一定被调用。
3. 保证副作用幂等。
4. 替代 task ledger / state machine。
```

规则：

```text
Skill 可以建议流程；
Contract 决定流程是否完成；
Gateway 决定工具是否能执行。
```

### 3.7 Task / Artifact Ledger

职责：

```text
1. 持久化 task 状态。
2. 持久化 tool call 和 result。
3. 持久化 artifacts。
4. 记录 handoff。
5. 支撑 replay / resume / audit。
```

长期目标：

```text
main-agent 不靠上下文判断 sub-agent 是否完成；
orchestrator 通过 task ledger / artifact refs 判断。
```

## 4. 统一后的调用链

目标结构：

```text
User Input
  -> Agent Runtime
  -> Intent / Contract Selection
  -> Orchestrator builds RuntimePlan
  -> Model produces content or tool intent
  -> ToolCallController normalizes / validates
  -> Tool Gateway executes or rejects
  -> Ledger records result
  -> Orchestrator updates state
  -> Finalization barrier
  -> Final answer
```

其中：

```text
Runtime 不知道具体业务 payload。
Contract 不执行工具。
Skill 不保证完成。
Gateway 不选择业务流程。
Ledger 不做推理。
```

## 5. 当前模块映射

| 架构层 | 当前模块 | 状态 | 后续动作 |
|---|---|---|---|
| Agent Runtime | `app/runtime/agent_runtime.py` | 过重 | 只保留 turn loop / streaming / model call |
| Orchestrator | `workflow/tool_plan.py`, `workflow/executor.py` | 已有雏形但分散 | 拆出 action plan / workflow plan |
| Contract Registry | `workflow/contracts.py` | 方向正确 | 扩展 contract 字段，不塞主循环 |
| Delegate Boundary | `workflow/delegation.py` | M41-A 已落地 | 后续 contract-aware |
| Guard | `workflow/guard.py` | 过重 | 缩成事实边界 + 副作用保护 |
| Tool Gateway | `runtime/agent/tool_gateway.py`, `workflow/tool_idempotency.py` | 分散 | 合并 validation / idempotency / ledger 视角 |
| Skill Layer | `app/skills/*/SKILL.md` | 已存在 | 明确不承担可靠性 |
| Finalization | `runtime/agent/finalization_packet.py` | 可保留 | 作为最终答复上下文边界 |
| Live Smoke | `tools/smoke_live_matrix.py` | 已有 | 继续作为产品回归矩阵 |

## 6. 接入新功能的标准流程

后续新增任何 agent / workflow / action，必须按这个顺序：

```text
1. 定义用户意图和产品目标。
2. 判断是：
   - chat；
   - skill-only；
   - action contract；
   - workflow contract；
   - deterministic executor；
   - human approval workflow。
3. 写 contract：
   - required_refs；
   - required_outputs；
   - allowed_tools；
   - forbidden_write_tools；
   - finalization barrier。
4. 如需要确定性参数，写 ActionPayloadBuilder。
5. 如需要模型知道做法，写或更新 Skill。
6. 如有副作用工具，接入 Tool Gateway 幂等/权限/ledger。
7. 加 focused unit tests。
8. 加 live smoke matrix 场景。
```

禁止流程：

```text
直接在 agent_runtime.py 里加一个 if。
直接在 guard.py 里为一个场景塞业务 payload。
直接靠 skill 提示模型“记得调用某工具”。
只因为某个 live smoke 失败就新增 hidden/suppress 分支。
```

## 7. Skill 与 Workflow 的判断标准

使用 Skill：

```text
1. 任务步骤需要解释给模型。
2. 输出内容需要模型判断、取舍、写作。
3. 失败不会造成副作用错误。
4. 流程不是唯一固定工具链。
```

使用 Workflow / Contract：

```text
1. 必须产生某个产品记录。
2. 有明确 required outputs。
3. 有副作用工具。
4. 不完成某一步就不能 final。
5. 多 agent handoff 需要 join / barrier。
```

使用 Deterministic Executor：

```text
1. 下一步唯一。
2. 参数可由 known_refs / previous result 构造。
3. 不需要模型做业务判断。
4. contract dry-run 证明 refs/tools 都满足。
```

需要 Human Approval：

```text
1. 外部不可逆副作用。
2. 付款、删除、发送外部消息、提交正式申请。
3. 模型置信度不足但用户成本高。
```

## 8. 迁移路线

### M42-A：架构文档和命名冻结

```text
新增本文。
后续 PR / commit 必须使用本文术语。
不再新增平行概念名。
```

### M42-B：ActionPayloadBuilder

目标：

```text
从 agent_runtime.py 移出 interview_review_update 的 payload 构造。
不改变行为。
```

新增：

```text
app/runtime/workflow/action_payloads.py
```

覆盖：

```text
interview_review_update -> career_application_merge
```

验收：

```text
unit tests 通过；
focused live smoke 不退化；
agent_runtime.py 业务 payload helper 减少。
```

实现记录：

```text
新增：
  app/runtime/workflow/action_payloads.py
  tests/test_action_payloads.py

迁移：
  interview_review_update -> career_application_merge payload
  interview_review_update required_tool_call_hint

agent_runtime.py 现在只调用：
  build_action_payload_tool_call_from_plan(...)
  build_required_tool_call_hint_for_plan(...)

删除自 agent_runtime.py：
  _deterministic_action_payload_tool_call_from_plan
  _interview_review_application_merge_arguments
  _interview_review_application_merge_evidence_refs
  _required_tool_call_hint_for_plan
```

这一步是职责迁移，不改变行为：

```text
不新增 workflow 分支；
不新增 guard；
不改变 tool gateway；
不改变 runtime plan 语义；
不改 .env。
```

验证：

```text
python -m py_compile \
  app/runtime/workflow/action_payloads.py \
  app/runtime/agent_runtime.py \
  app/runtime/workflow/__init__.py

uv run pytest \
  tests/test_action_payloads.py \
  tests/test_runtime_tool_plan.py \
  tests/test_retrieval_action_flow.py \
  tests/test_workflow_executor.py \
  tests/test_agent_runtime.py::test_runtime_auto_executes_interview_review_application_merge_after_repeated_schema_search \
  -q

result:
  passed
```

### M42-C：ToolCallController skeleton

目标：

```text
把模型 tool_calls 到 gateway 前的决策统一封装。
```

首批只承接：

```text
strict required auto-call decision
hidden/suppress decision shell
```

要求：

```text
不新增业务规则；
只移动职责；
事件 payload 保持兼容。
```

实现记录：

```text
新增：
  app/runtime/agent/tool_call_controller.py
  tests/test_tool_call_controller.py

迁移：
  strict required auto-call decision
  hidden runtime support tool allowance
  hidden runtime tool suppression names
  hidden runtime tool suppression key
  strict auto-execute event payload

保留在 agent_runtime.py：
  turn loop
  streaming / sync event recording
  schema_search budget counters
  business tool round counters
  finalization fallback
```

说明：

```text
这一步没有迁移 delegate normalization。
当前 delegate normalization 已在 WorkflowRuntimeGuard + DelegateTaskNormalizer 边界内，
不应为了“概念完整”再移动一次，避免引入新耦合。
```

验证：

```text
python -m py_compile \
  app/runtime/agent/tool_call_controller.py \
  app/runtime/agent_runtime.py \
  app/runtime/agent/__init__.py \
  tests/test_tool_call_controller.py

uv run pytest \
  tests/test_tool_call_controller.py \
  tests/test_action_payloads.py \
  tests/test_runtime_tool_plan.py \
  tests/test_retrieval_action_flow.py \
  tests/test_workflow_executor.py \
  tests/test_workflow_runtime_guard.py \
  tests/test_agent_runtime.py::test_runtime_auto_executes_interview_review_application_merge_after_repeated_schema_search \
  -q

result:
  passed
```

### M42-D：拆分 workflow/tool_plan.py

目标：

```text
把 action contract plan 和 career phase plan 分开。
```

候选文件：

```text
workflow/action_plan.py
workflow/career_plan.py
workflow/runtime_plan.py
```

实现记录：

```text
新增：
  app/runtime/workflow/action_plan.py
  tests/test_action_plan.py

迁移：
  action_contract_for_phase
  action_contract_plan_payload
  pending_action_plan_after_tool_result
  action completed output / next action / final action helpers
  action write tools 列表

保留在 workflow/tool_plan.py：
  RuntimeToolPlan dataclass
  career phase plan
  retrieval read-only plan
  delegate/result refs parsing
  product refs extraction
  payload -> RuntimeToolPlan normalization
```

说明：

```text
action_plan.py 不 import tool_plan.py，避免循环依赖。
tool_plan.py 仍负责把 action payload 包装成 RuntimeToolPlan。
这一步只拆文件，不改变 action contract 语义。
```

验证：

```text
python -m py_compile \
  app/runtime/workflow/action_plan.py \
  app/runtime/workflow/tool_plan.py \
  app/runtime/workflow/__init__.py \
  tests/test_action_plan.py

uv run pytest \
  tests/test_action_plan.py \
  tests/test_runtime_tool_plan.py \
  tests/test_retrieval_action_flow.py \
  tests/test_workflow_runtime_guard.py \
  -q

result:
  passed
```

### M42-E：Guard 收缩

保留：

```text
schema validation
fact boundary
side-effect protection
delegate signature reuse
```

迁出：

```text
业务 payload 构造
workflow 推进
可由 contract 判断的 required output barrier
```

实现记录：

```text
迁出 guard.py：
  delegate_signature
  delegate_semantic_signature
  delegate_jd_fit_source_key
  is_jd_fit_delegate_task
  is_dependent_application_delegate_task
  mentions_application_record

迁入：
  app/runtime/workflow/delegation.py

保留在 guard.py：
  turn intent / fact boundary
  side-effect protection
  delegate normalization 调用点
  delegate 结果复用决策
```

说明：

```text
这一步只调整 delegation 边界归属，不合并 tool_idempotency.py 里的 delegate semantic hash。
两者用途不同：
  delegation.py 的签名用于 runtime guard 的结构/语义复用和 source 判断；
  tool_idempotency.py 的签名用于 tool call idempotency key。

不新增业务 guard；
不改变 delegate_agents 执行语义；
不改 .env。
```

验证：

```text
python -m py_compile \
  app/runtime/workflow/delegation.py \
  app/runtime/workflow/guard.py

uv run pytest \
  tests/test_delegate_task_normalizer.py \
  tests/test_workflow_runtime_guard.py \
  -q

uv run pytest \
  tests/test_delegate_task_normalizer.py \
  tests/test_action_plan.py \
  tests/test_action_payloads.py \
  tests/test_tool_call_controller.py \
  tests/test_runtime_tool_plan.py \
  tests/test_workflow_runtime_guard.py \
  -q

result:
  passed
```

### M42-F：Tool Gateway policy boundary

目标：

```text
把 ToolGateway 里的 policy / idempotency / runtime-state block 入口收成一个本地边界。
ToolGateway 负责执行顺序和 ledger 写入；
ToolGatewayPolicy 负责决定这次工具调用的执行属性和状态阻断结果。
```

实现记录：

```text
新增：
  app/runtime/agent/tool_gateway_policy.py
  tests/test_tool_gateway_policy.py

迁移出 tool_gateway.py：
  resolve_tool_gateway_policy
  gateway_state_block_result
  workflow_event_payload_from_result

ToolGateway 现在只依赖：
  tool_gateway_policy
  tool_runner
  workflow_guard
  ledger protocol
```

说明：

```text
这一步没有物理搬迁 workflow/tool_idempotency.py 和 workflow/tool_policy.py。
原因是它们已有测试和历史调用方，直接搬文件会扩大风险。
先通过 agent/tool_gateway_policy.py 做 facade，把依赖入口收口；
后续如果继续迁移，只需要移动 facade 内部实现，不影响 ToolGateway 执行主流程。

不新增业务 policy；
不改变幂等 key 规则；
不改变 ledger 复用语义；
不改 .env。
```

验证：

```text
python -m py_compile \
  app/runtime/agent/tool_gateway_policy.py \
  app/runtime/agent/tool_gateway.py \
  tests/test_tool_gateway_policy.py

uv run pytest \
  tests/test_tool_gateway_policy.py \
  tests/test_tool_gateway.py \
  tests/test_tool_policy.py \
  -q

result:
  passed
```

### M42-G：Tool Capability Registry

目标：

```text
把工具基础分类收成单一入口，避免新工具接入时同时改 tool_policy / action_plan / guard 等多个列表。
```

实现记录：

```text
新增：
  app/runtime/tool_capabilities.py
  tests/test_tool_capabilities.py

统一登记：
  schema tools
  read-only tools
  idempotent write tools
  volatile write tools
  action write tools
  read-only turn write-block tools

接入：
  workflow/tool_policy.py 从 registry 读取 ToolKind
  workflow/action_plan.py 从 registry 读取 ACTION_WRITE_TOOL_NAMES
  workflow/guard.py 从 registry 读取 READ_ONLY_TURN_WRITE_BLOCK_TOOL_NAMES
```

说明：

```text
这一步只统一分类来源，不改变任何工具分类结果。
没有把 stage-specific blocked_tools 迁入 registry，因为那些是 workflow 状态策略，不是工具固有能力。

registry 管“工具是什么”；
contract / guard / runtime plan 管“当前状态下能不能用”。
```

验证：

```text
python -m py_compile \
  app/runtime/tool_capabilities.py \
  app/runtime/workflow/tool_policy.py \
  app/runtime/workflow/action_plan.py \
  app/runtime/workflow/guard.py \
  tests/test_tool_capabilities.py

uv run pytest \
  tests/test_tool_capabilities.py \
  tests/test_tool_policy.py \
  tests/test_action_plan.py \
  tests/test_workflow_runtime_guard.py \
  -q

uv run pytest \
  tests/test_tool_capabilities.py \
  tests/test_tool_gateway_policy.py \
  tests/test_tool_gateway.py \
  tests/test_tool_policy.py \
  tests/test_action_plan.py \
  tests/test_action_payloads.py \
  tests/test_tool_call_controller.py \
  tests/test_runtime_tool_plan.py \
  tests/test_workflow_runtime_guard.py \
  -q

result:
  passed
```

### M42-H：Focused live regression

目标：

```text
停止继续拆结构，先验证 M42-B 到 M42-G 的边界迁移没有造成真实运行态退化。
```

执行：

```text
uv run python tools/smoke_live_matrix.py \
  --scenario career_full \
  --runs 1 \
  --concurrency 1 \
  --stream \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m42_structural_regression_career_full_c1_r1 \
  --json-report data/live_smoke_matrix_m42_structural_regression_career_full_c1_r1/report.json \
  --quiet
```

结果：

```text
passed=1/1
failed=0/1
elapsed=191.39s
llm_calls=13
tokens=63979
duplicate_tool_call_count=0
harmful_duplicate_tool_call_count=0
hidden_tool_result_count=0
failed_tool_result_count=0
quality_error_codes=[]
```

产品记录：

```text
resume_profiles=1
career_profiles=1
jd_analyses=1
job_fit_reports=1
resume_versions=1
career_applications=1
artifact_count=5
```

结论：

```text
M42 的结构收敛没有在 career_full P0 stream 路径上引入退化。
本轮只做 focused regression，不继续扩大到 6x3；
是否需要高并发回归应由后续产品变更风险决定，而不是每次结构小迁移都默认全量压测。
```

## 9. 成功标准

结构标准：

```text
1. 新功能不改 agent_runtime.py 主循环。
2. 新 action 通过 ActionContract + PayloadBuilder 接入。
3. 新 sub-agent 通过 capability / contract / skill 接入。
4. guard.py 行数不再持续增长。
5. runtime 只负责编排 turn，不负责业务细节。
```

质量标准：

```text
P0 live smoke 不退化。
P1 matrix 不因迁移下降。
harmful_duplicate = 0。
hidden 不新增。
副作用记录数量符合预期。
```

成本标准：

```text
不以少几秒或几千 token 为主要目标。
只要 avg_elapsed / avg_tokens 不明显劣化，就优先结构收敛。
```

## 10. 当前明确不做

```text
1. 不全量引入 LangGraph。
2. 不把所有 skill 改成 workflow。
3. 不把所有 workflow 改成 deterministic executor。
4. 不为了 harmless duplicate 加 guard。
5. 不为了单个 provider 长尾改架构。
6. 不继续把业务逻辑塞进 agent_runtime.py。
7. 不改 .env。
```

## 11. 最关键的决策

后续架构以这个边界为准：

```text
Agent Runtime:
  跑一轮模型。

Orchestrator:
  管状态和下一步。

Contract:
  声明业务能力和完成条件。

Skill:
  教模型怎么做。

Tool Gateway:
  管工具权限、幂等和审计。

Ledger:
  记录事实和结果。
```

如果一个改动不能明确落在这六层之一，就先不做。
