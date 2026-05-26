# M27 统一 Workflow State 与 Tool Gateway 实现方案

> 状态：第一阶段已实现并通过 `custom_resume 6x3` live smoke。本文承接 M24/M25/M26 的求职流程稳定性与长尾优化工作。当前不先接入 LangGraph，也不继续堆叠零散 guard；先实现一个可测试、可迁移到 LangGraph 的最小状态机与工具调用账本内核。

## 0. 实施记录

### 2026-05-25 第一阶段

已完成：

- 新增 `ToolCallLedger` / `JsonlToolCallLedger`，按 session 持久化工具调用账本。
- 新增 `ToolGateway`，把工具执行统一收口到 idempotency key、ledger、workflow guard、runner 之后再落真实工具。
- 新增工具策略与幂等键：只读工具按稳定输入复用，写工具按业务自然键约束。
- `AgentRuntime` 支持可选 gateway，并把硬工具轮次上限调整为软预算 + 无推进收束。
- live smoke 脚本接入 ledger，并输出效率摘要。

关键修复：

- r2 暴露出 blocked ledger 记录被复用的问题：`session_create_text_artifact` 被 guard recoverable block 后，后续相同调用一直复用 blocked 结果，导致 job_agent 长尾。已改为只复用 `succeeded/reused` 且有结果内容的记录。
- r3 暴露出收束条件过急的问题：`career_resume_version_create` 已可见时，模型仍调用隐藏的 `tool_search`，no-progress tracker 把同一阶段的 schema search 立即判为 stagnation，导致 fallback 且缺 `resume_versions`。已改为第一次 suppressed schema search 只做纠偏，不计入无推进终止；隐藏工具 block 不再重置提醒次数。

验证结果：

```text
r1: 6/6 passed，但 smoke 脚本当时未接入 ToolGateway，仅作为旧路径参考。
r2: 手动终止；根因是 blocked ledger 结果被错误复用。
r3: 5/6 passed；根因是 required tool 已可见时 schema_search 被过早收束。
r4: 6/6 passed；avg_llm_calls=26.0，max_llm_calls=31，avg_tokens=141990，max_tokens=170177，duplicate_runs=2/6，hidden_runs=6/6，stagnation_runs=0/6，hard_safety_runs=0/6。
```

剩余问题：

- `hidden_runs` 仍为 6/6，说明模型仍会尝试隐藏工具，只是 runtime 能正确纠偏并完成产物。
- run_006 曾因首次 `career_resume_version_create` 缺少 content 被 guard recoverable block，随后重试成功；这是下一阶段要减少的 LLM 浪费。
- run_002 仍有 `session_create_text_artifact` / profile get 级别的重复，已由 ledger/guard 保证正确性，但效率还没完全收敛。
- `.env` 未修改。

## 1. 背景

当前产品目标不变：

```text
围绕目标岗位 / 目标公司，持续管理用户能力差距、求职资产、学习计划和面试准备。
```

最近几轮 live smoke 的质量已经基本稳定，核心矛盾已经从“产品记录写不出来”转为：

```text
重复工具调用造成 token 和耗时偏高。
```

典型表现：

- main-agent 在 required tool 已可见时仍继续 `tool_search`。
- main-agent 偶发重复 `delegate_agents` 或重复项目动作。
- job_agent 偶发重复 `career_profile_get` / `career_resume_profile_get` / `session_read_artifact`。
- job_agent 在 report artifact 或 JobFitReport 已完成后，仍可能继续创建 artifact 或重复 save。
- guard / idempotency 能保护数据正确性，但经常是在模型已经发起错误工具调用后才拦截，仍然消耗一轮 LLM。

这说明继续加“某个工具重复时 block”的局部规则，会产生长尾效应：

```text
修一个重复点，模型可能转向另一个相邻重复点。
```

根因不是某一个工具缺 guard，而是当前系统缺一个统一的执行控制面：

```text
Workflow State 决定当前阶段和唯一下一步。
Tool Gateway 决定工具是否可执行、复用、跳过或拒绝。
Tool Call Ledger 记录工具调用账本、幂等键和执行结果。
```

## 2. 当前系统怎么做

当前已有几个基础能力。

### 2.1 子任务状态表已经存在

已有 `AgentTaskSpec` / `AgentTaskRecord` / `AgentTaskGroupRecord`：

```text
task_group_id
task_id
target_agent_id
status
instruction
artifact_refs
child_run_id
summary
answer
error
```

`AgentTaskRuntime` 目前通过 `delegate_agents(wait=true)` 创建 task group，并用 `asyncio.gather` 等待所有 child-agent 完成。

这意味着 main-agent 判断 sub-agent 完成的当前方式是：

```text
delegate_agents 返回时，子任务 group 已经 fan-in。
```

但当前不是完整 DAG 调度器：

- `depends_on` 已预留但当前拒绝使用。
- 没有跨进程 task queue。
- 没有 task lease / timeout / retry policy。
- `delegate_agents` 重复委派主要靠 guard 的签名复用，不是 task ledger 的幂等创建。

### 2.2 工具执行没有统一 Tool Call Ledger

当前工具执行链路大致是：

```text
AgentRuntime
  -> ToolRevealState 决定本轮可见工具
  -> WorkflowRuntimeGuard.inspect()
  -> ToolExecutionRunner.execute_safely()
  -> ToolExecutor.execute()
  -> 记录 tool_call / tool_result event
```

已有的防重复散落在多个位置：

- `WorkflowRuntimeGuard`：重复 get 复用、阶段完成 block、参数修正。
- `RuntimeToolPlan`：给模型提示下一步工具和 discouraged tools。
- `ToolRevealState`：隐藏未揭示或当前不该用的工具。
- `_ToolLoopProgressTracker`：发现重复/无推进后停止工具循环。
- Career tools：按业务自然键做部分幂等复用。

这些能力有用，但有三个问题：

```text
1. 不是统一入口。
2. 没有通用 tool_call 账本。
3. 多个控制层可能对“下一步是什么”给出不完全一致的答案。
```

### 2.3 guard 当前承担了太多职责

`WorkflowRuntimeGuard` 现在同时在做：

- 正确性兜底。
- 幂等复用。
- 参数修正。
- 阶段推进提示。
- 子任务输出边界。
- main-agent 阶段锁。

这导致最近的问题：

```text
guard 越加越多，但 token/耗时没有稳定下降。
```

因为 guard 多数是 post-hoc：

```text
模型先发起错误调用
  -> guard block/reuse
  -> tool result 回给模型
  -> 模型再理解修正
```

即使没有副作用，也已经消耗了 LLM 轮次和上下文 token。

## 3. 核心判断

### 3.1 暂不直接接入 LangGraph

LangGraph 的方向是对的：显式 state、node、edge、checkpoint、interrupt、fan-in/fan-out。

但当前最急的问题不是缺图框架，而是：

```text
工具调用缺统一账本；
workflow phase 缺唯一状态源；
工具可见性和 guard 不是同一个状态派生出来的。
```

如果现在直接接 LangGraph，风险是把现有分散逻辑搬进 graph node，复杂度增加，但重复工具调用仍然存在。

因此 M27 先手动实现一个 LangGraph-compatible 内核：

```text
UnifiedWorkflowState
ToolGateway
ToolCallLedger
IdempotencyPolicy
ToolVisibilityPolicy
```

后续如果需要复杂 DAG、跨进程恢复、人审 interrupt，再把这些状态和 gateway 迁入 LangGraph。

### 3.2 guard 应退回正确性兜底

M27 之后职责应调整为：

```text
Workflow State:
  判断 phase、completed、missing、next_required_tool、final_answer_ready。

Tool Gateway:
  判断 tool 是否可执行、是否重复、是否复用 ledger、是否需要跳过。

Tool Reveal:
  只根据 Workflow State 暴露工具 schema。

Workflow Guard:
  只做业务正确性兜底、参数修正、事实边界和副作用保护。
```

不要再让 guard 承担主规划。

### 3.3 降 token 的关键是前置控制

Tool Ledger 可以避免工具真正重复执行，但不能自动避免模型生成重复工具调用。

因此必须同时做：

```text
1. 工具执行前由 Tool Gateway 去重。
2. 模型调用前由 Workflow State 收窄可见工具。
3. required tool 已可见时，不再允许 schema_search_only 浪费轮次。
```

## 4. M27 目标

第一阶段目标：

- 建立统一 `ToolCallLedger` 数据模型和存储接口。
- 所有工具调用通过 `ToolGateway` 执行。
- 对 read-only 工具支持同 run 输入缓存复用。
- 对副作用工具支持业务幂等键复用。
- 把 `RuntimeToolPlan` / `ToolRevealState` / `WorkflowRuntimeGuard` 的下一步判断收敛到同一个 `UnifiedWorkflowState`。
- 保留现有产品质量门禁和 guard 事实边界。
- 不引入 LangGraph runtime。
- 不改变 `.env`。

第一阶段成功标准：

```text
custom_resume 6x3:
  6/6 passed
  hard_safety_runs = 0
  duplicate_runs 下降或不恶化
  hidden_runs 下降或不恶化
  stagnation_runs 下降或不恶化
  avg/max llm calls 和 tokens 不高于当前 r2 基线
```

## 5. 非目标

M27 第一阶段不做：

- 不接 LangGraph。
- 不做完整 DAG 引擎。
- 不做跨进程 task queue。
- 不做 Redis / DB 分布式锁。
- 不重写所有 career tools。
- 不把所有业务 guard 删除。
- 不降低 live smoke 质量门禁。
- 不修改用户 `.env`。

## 6. 总体架构

目标链路：

```text
AgentRuntime
  -> UnifiedWorkflowStateResolver
  -> ToolVisibilityPolicy
  -> model.generate(...)
  -> ToolGateway
       -> WorkflowGuard
       -> ToolCallLedger
       -> ToolExecutionRunner
       -> ToolCallLedger
  -> UnifiedWorkflowState transition
  -> final answer / next round
```

职责边界：

```text
AgentRuntime:
  负责模型循环、事件记录、最终答复恢复。

UnifiedWorkflowStateResolver:
  从事实源推导当前 workflow state。

ToolVisibilityPolicy:
  从 state 派生本轮可见工具。

ToolGateway:
  工具调用唯一入口；处理 ledger、幂等、复用、跳过、执行。

WorkflowGuard:
  保留业务正确性兜底，不再作为主 planner。

ToolCallLedger:
  持久记录工具调用、input_hash、idempotency_key、status、result。
```

## 7. UnifiedWorkflowState 设计

新增：

```text
app/runtime/workflow/state.py
```

建议结构：

```python
UnifiedWorkflowState
  phase: str | None
  status: Literal["idle", "pending", "ready", "completed", "blocked"]
  known_refs: dict[str, str]
  missing_outputs: list[str]
  next_required_tools: list[str]
  allowed_tools: list[str]
  discouraged_tools: list[str]
  completed_tools: list[str]
  final_answer_ready: bool
  next_action: str | None
  source: dict[str, str]
```

第一阶段支持这些 phase：

```text
resume_diagnosis
jd_fit
application_action
resume_version
```

状态来源：

```text
CurrentWorkflowState
CareerFlowState
WorkflowPhaseSnapshot
current run successful tool_result
agent_result_summary
CareerProductStore active records
SessionArtifact active artifacts
ToolCallLedger successful records
```

优先级：

```text
本 run 成功工具结果
  > ToolCallLedger 成功结果
  > agent_result_summary
  > CareerProductStore active records
  > current context bundle
```

第一阶段可以把现有 `RuntimeToolPlan` 的推导迁到 `UnifiedWorkflowStateResolver`，先保持行为等价，再减少重复逻辑。

## 8. ToolCallLedger 设计

新增 domain model：

```text
app/domain/tool_calls.py
```

字段：

```text
tool_call_record_id
session_id
run_id
agent_id
task_id
tool_name
tool_call_id
input_hash
idempotency_key
status
arguments
result_content
result_refs
error
created_at
updated_at
completed_at
```

status：

```text
planned
running
succeeded
failed
skipped
reused
blocked
```

新增 store protocol：

```text
app/domain/tool_call_protocols.py
```

```python
class ToolCallLedger(Protocol):
    def find_by_idempotency_key(...)
    def find_success_by_input_hash(...)
    def create_running(...)
    def mark_succeeded(...)
    def mark_failed(...)
    def mark_reused(...)
    def mark_blocked(...)
```

新增 JSONL 实现：

```text
app/infra/storage/jsonl_tool_call_ledger.py
```

第一阶段使用进程内 `RLock`，不做分布式锁。和现有 JSONL session/task store 风格保持一致。

## 9. input_hash 与 idempotency_key 策略

### 9.1 input_hash

用于 read-only / cacheable 工具：

```text
input_hash = sha256(tool_name + canonical_json(normalized_arguments))
```

规范化规则：

- dict 按 key 排序。
- list 保留顺序。
- 大段正文只保留 hash，不直接写入 fingerprint。
- 移除 `tool_call_id` 这类调用级随机字段。
- 空字符串 / None 统一规范化。

### 9.2 idempotency_key

用于副作用工具。不能只依赖原始参数，必须用业务自然键。

第一阶段建议策略：

```text
delegate_agents:
  session_id + run_id + semantic_task_signature

career_resume_profile_save:
  session_id + source_artifact_id

career_jd_analysis_save:
  session_id + source_artifact_id

session_create_text_artifact:
  session_id + run_id/task_id + output_kind
  output_kind in {resume_diagnosis, job_fit_report}

career_job_fit_report_save:
  session_id + jd_analysis_id + resume_profile_id
  fallback: report_artifact_id

career_application_create:
  session_id + jd_analysis_id + resume_profile_id + job_fit_report_id

career_resume_version_create:
  session_id + base_resume_profile_id + target_jd_analysis_id
  unless user explicitly asks to create a new version

career_application_merge:
  session_id + application_id + operation_kind + stable_update_hash
  for resume_version link:
    session_id + application_id + resume_version_id
```

这些策略应集中在：

```text
app/runtime/workflow/tool_idempotency.py
```

不要继续散落在各个 guard 分支里。

## 10. ToolGateway 设计

新增：

```text
app/runtime/agent/tool_gateway.py
```

职责：

```python
def execute(call, context, workflow_state) -> ToolExecutionResult:
    policy = resolve_tool_policy(call, context, workflow_state)

    if workflow_state.final_answer_ready:
        return blocked_terminal_result(...)

    if call violates state.allowed_tools:
        return blocked_by_state_result(...)

    idempotency_key = policy.idempotency_key(...)
    if idempotency_key:
        existing = ledger.find_by_idempotency_key(...)
        if existing.succeeded/reused:
            return reuse_existing_result(...)
        if existing.running:
            return already_running_result(...)

    input_hash = policy.input_hash(...)
    if policy.cacheable:
        existing = ledger.find_success_by_input_hash(...)
        if existing:
            return reuse_existing_result(...)

    record = ledger.create_running(...)
    guard_decision = workflow_guard.inspect(...)
    if guard_decision.result:
        ledger.mark_blocked_or_reused(...)
        return guard_decision.result

    result = runner.execute_safely(...)
    ledger.mark_succeeded_or_failed(...)
    return result
```

注意顺序：

```text
state terminal / allowed_tools 判断
  -> ledger 幂等查重
  -> guard 正确性兜底
  -> actual tool
```

原因：

- terminal / allowed_tools 是最便宜的，应最先拦截。
- ledger 能防止明显重复进入复杂 guard 和真实工具。
- guard 保留业务修正和事实边界。
- actual tool 放最后。

## 11. 工具分类策略

新增：

```text
app/runtime/workflow/tool_policy.py
```

分类：

```text
schema:
  tool_search

read_only:
  session_read_artifact
  session_list_artifacts
  session_search_artifact
  career_*_get
  career_*_list
  retrieval_search
  retrieval_context_pack

idempotent_write:
  career_resume_profile_save
  career_jd_analysis_save
  career_job_fit_report_save
  career_application_create
  career_application_merge
  career_resume_version_create
  session_create_text_artifact for generated_file workflow output

volatile_write:
  memory_write
```

第一阶段不强控所有工具。优先覆盖 career workflow 中的高频工具。

## 12. Tool Visibility 收敛

当前 `_visible_tool_definitions_for_runtime_plan` 基于 `pending_runtime_plan` 做过滤。

M27 调整为：

```text
visible_tools = ToolVisibilityPolicy.from_state(workflow_state, tool_reveal_state)
```

规则：

```text
final_answer_ready:
  隐藏 tool_search 和所有 workflow 工具，只保留 memory_write 等必要通用工具。

next_required_tools 非空且已揭示:
  只暴露 next_required_tools + 少量通用工具。
  tool_search 不再暴露。

next_required_tools 非空但未揭示:
  暴露 tool_search + 已有 always_visible。

无 workflow state:
  使用现有 reveal 行为。
```

重点修正：

```text
required tool 已可见时，模型再返回 schema_search_only，不再继续提醒 1-2 轮。
```

处理策略：

```text
直接生成 workflow_runtime_decision:
  reason=schema_search_suppressed_required_tool_visible
  policy=continue 或 finalize

并把 runtime notice 加入下一轮，或在 final_answer_ready 时直接 recover final answer。
```

如果实现上可以更进一步，直接把 `tool_search` 从 tools_payload 移除，模型就不能再调用。

## 13. 与现有 guard 的关系

保留：

- 候选人事实边界检查。
- ResumeVersion content 校验。
- 当前 session record ref 修正。
- child-agent pasted_text artifact 禁止。
- 空 artifact content 阻断。
- 已有 product record 的业务幂等复用。

迁移或弱化：

- main-agent 大面积阶段 block。
- child-agent 低层重复 get/list 的阶段推进提示。
- `delegate_agents` 签名复用。
- `career_application_merge -> final_answer_ready` 这类状态推进。

迁移目标：

```text
这些逻辑从 guard 分支迁到 ToolGateway / UnifiedWorkflowState。
```

短期兼容策略：

```text
先让 ToolGateway 在 guard 前做通用去重；
guard 保持现状；
确认 live smoke 不退化后，再逐步删除/弱化重复规划分支。
```

## 14. 实施步骤

### 14.1 文档确认

先确认本文方案和边界。

### 14.2 新增 ToolCallLedger

文件：

```text
app/domain/tool_calls.py
app/domain/tool_call_protocols.py
app/infra/storage/tool_call_serializers.py
app/infra/storage/jsonl_tool_call_ledger.py
tests/test_tool_call_ledger.py
```

测试：

- create running。
- mark succeeded。
- find by idempotency key。
- find by input hash。
- duplicate running 返回已有记录。
- JSONL reload 后仍可查询。

### 14.3 新增 tool policy / idempotency

文件：

```text
app/runtime/workflow/tool_policy.py
app/runtime/workflow/tool_idempotency.py
tests/test_tool_policy.py
```

测试：

- read-only 工具生成稳定 input_hash。
- career save/create/merge 生成业务 idempotency_key。
- 大段 content 不直接进入 fingerprint。
- 显式新建 ResumeVersion 的意图不会错误复用旧版本。

### 14.4 新增 ToolGateway

文件：

```text
app/runtime/agent/tool_gateway.py
tests/test_tool_gateway.py
```

接入点：

```text
AgentRuntime 原先:
  workflow_guard.inspect()
  tool_runner.execute_safely()

改为:
  tool_gateway.execute()
```

测试：

- final_answer_ready 时 workflow 工具被 terminal block。
- allowed_tools 不包含的工具被 state block。
- 同 idempotency_key 成功记录直接复用。
- read-only 同 input_hash 直接复用。
- guard repair 仍能生效。
- actual tool failure 写入 ledger failed。

### 14.5 新增 UnifiedWorkflowStateResolver

文件：

```text
app/runtime/workflow/state.py
app/runtime/workflow/state_resolver.py
tests/test_unified_workflow_state.py
```

第一阶段策略：

- 先包装现有 `RuntimeToolPlan` 结果。
- 保持 `phase / known_refs / missing_outputs / next_allowed_tools / final_answer_ready` 等价。
- 再逐步把 `pending_runtime_plan_from_successful_tool_result` 的状态推进迁入 state transition。

### 14.6 Tool visibility 从 state 派生

文件：

```text
app/runtime/workflow/tool_visibility.py
tests/test_tool_visibility.py
```

改造：

- `_visible_tool_definitions_for_runtime_plan` 改为兼容 wrapper。
- 新逻辑优先用 `UnifiedWorkflowState`。
- 保持旧测试通过。

### 14.7 收敛 schema_search_only 浪费轮次

改造 `AgentRuntime`：

```text
当 workflow_state.next_required_tools 已可见，且模型只返回 tool_search：
  不执行 tool_search。
  写入 workflow_runtime_decision。
  直接追加 state notice 或进入 final answer recovery。
```

测试：

- required tool 可见时，`tool_search` 不进入 tool_call/tool_result。
- required tool 未揭示时，`tool_search` 仍可正常揭示工具。
- final_answer_ready 时 `tool_search` 不再消耗 schema_search_rounds。

### 14.8 回归与 live smoke

单测：

```text
uv run pytest tests/test_tool_call_ledger.py tests/test_tool_policy.py tests/test_tool_gateway.py tests/test_unified_workflow_state.py tests/test_tool_visibility.py -q
```

相关回归：

```text
uv run pytest tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_tool_reveal.py tests/test_workflow_runtime_guard.py tests/test_career_tools.py tests/test_agent_task_runtime.py -q
```

类型检查：

```text
uv run mypy --explicit-package-bases app/runtime/agent/tool_gateway.py app/runtime/workflow/state.py app/runtime/workflow/tool_policy.py app/runtime/workflow/tool_idempotency.py
```

live smoke：

```text
uv run python tools/smoke_career_live_flow.py --runs 6 --concurrency 3 --max-tool-rounds 24 --project-action custom_resume --data-dir data/live_career_smoke_m27_tool_gateway_6x3_r1 --quiet
```

只跑一组 `custom_resume 6x3`。如果失败，先查根因，不继续打补丁。

## 15. 风险与回滚

### 15.1 风险：ledger 复用错误结果

控制：

- 副作用工具优先使用业务自然键，不只用参数 hash。
- result refs 必须来自真实 tool result。
- 对 ResumeVersion 保留“用户明确要求新版本”绕过复用。

### 15.2 风险：allowed_tools 过窄导致合法路径被阻断

控制：

- 第一阶段只在明确 workflow phase 下启用。
- 普通聊天和无 phase 场景走旧 reveal 行为。
- 所有 state block 都返回 `recoverable=True` 和明确 next_action。

### 15.3 风险：guard 与 gateway 双重判断冲突

控制：

- gateway 先只做通用 terminal/allowed/idempotency/cache。
- guard 保留业务兜底。
- 观察 smoke 后再逐步迁移 guard 内的规划分支。

### 15.4 回滚方式

保留开关：

```text
ENABLE_TOOL_GATEWAY_LEDGER=true/false
ENABLE_UNIFIED_WORKFLOW_STATE=true/false
```

默认在测试环境开启。若 live smoke 退化，可关闭开关回到 M26 行为。

## 16. 验收口径

必须保持：

```text
custom_resume 6/6 passed
hard_safety_runs = 0
产品记录完整
artifact 质量门禁通过
最终回答不泄露 runtime 内部状态
```

应改善：

```text
duplicate_runs
hidden_runs
stagnation_runs
avg_llm_calls
max_llm_calls
avg_tokens
max_tokens
```

不接受的结果：

```text
通过率下降；
为了减少工具而缺产物；
stagnation 增加；
重复工具从一个工具转移到另一个工具；
最终答复依赖 fallback 文案。
```

## 17. 后续 LangGraph 迁移点

M27 完成后，如果需要接 LangGraph，迁移边界会很清晰：

```text
UnifiedWorkflowState -> graph state
ToolGateway -> graph node/tool middleware
ToolCallLedger -> checkpoint/side-effect ledger
AgentTaskRuntime -> fan-out/fan-in node
WorkflowState transition -> conditional edges
```

因此 M27 不是反对 LangGraph，而是先补齐 LangGraph 也不会替我们自动完成的业务执行内核。

## 18. 结论

下一步不继续加局部 guard。

M27 的正确切入点是：

```text
统一 workflow state
统一 tool gateway
统一 tool call ledger
统一 idempotency policy
工具可见性从 state 派生
guard 退回正确性兜底
```

这样才能同时解决：

```text
main-agent 怎么知道流程是否完成；
sub-agent / task 是否已完成；
某个工具是否重复执行；
重复执行是否有副作用；
重复工具调用是否继续浪费 token；
后续是否可以平滑迁移 LangGraph。
```
