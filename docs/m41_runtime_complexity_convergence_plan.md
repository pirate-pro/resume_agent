# M41：Runtime 复杂度收敛与长尾效应控制方案

> 状态：M41-A `DelegateTaskNormalizer` 已落地；M41-B 已用两批 `career_full 6x3` live smoke 验证 P0 停止线，并完成 runtime 分支审计。本文承接 M37/M39 的结论：重复工具调用、副作用幂等和核心 career P0 已阶段性收住；当前主要风险变成“为偶发 smoke failure 不断加 guard，导致代码更重、上下文更复杂、长尾更多”。

## 1. 当前判断

最近的优化已经出现长尾效应迹象：

```text
1. 单点问题被修掉后，新问题转移到另一个边界。
2. agent_runtime.py 继续膨胀，主循环同时承担：
   - 模型调用；
   - 工具可见性控制；
   - hidden/suppress；
   - schema_search 预算；
   - required tool 自动替换；
   - workflow executor；
   - final answer recovery；
   - finalization packet；
   - runtime plan merge。
3. guard / runtime plan / executor / tool gateway 职责有重叠。
4. 模型仍在生成底层 orchestration 参数，例如 delegate_agents.tasks。
```

这会导致一个结构性问题：

```text
越修越像补丁；
越补越依赖上下文提示；
上下文越复杂，模型越容易偏；
偏了以后又需要新的 guard。
```

所以 M41 的目标不是继续追某个 smoke failure，而是先把复杂度压回正确边界。

## 2. 核心原则

```text
模型负责：
  - 判断用户意图；
  - 生成开放式内容；
  - 产出业务草稿；
  - 做需要取舍的文本表达。

代码负责：
  - workflow 状态机；
  - 工具权限；
  - 工具参数结构；
  - task/delegate orchestration；
  - 幂等、锁、ledger；
  - 完成条件和 finalization barrier。
```

具体落地原则：

```text
1. 不让模型生成底层 orchestration 参数。
   例如 delegate_agents.tasks 不能由模型自由拼完整结构。

2. 不在主循环里继续加场景级 if。
   新规则必须落到 contract、normalizer、gateway 或 validator。

3. guard 只做兜底。
   guard 不能承担主流程推进。

4. executor 只处理封闭世界。
   唯一正确、状态可构造、工具链固定，才进入 executor。

5. smoke failure 先分类。
   是架构边界问题、模型质量问题、provider 长尾、数据问题，还是测试门禁过严，不能混在一起修。
```

## 3. 保留 / 回退 / 泛化

### 3.1 保留

这些是架构级资产，应保留：

```text
1. Tool Call Ledger / idempotency。
   解决重复调用的副作用和成本问题，是根能力。

2. Live Smoke Matrix。
   覆盖 chat_only / note / memory / rag / child agent / career full / P1 action。
   它是产品回归，不是单场景调试脚本。

3. WorkflowContract / ActionContract registry。
   新 agent 或新 workflow 应该通过 contract 注册能力，而不是改主循环。

4. Deterministic Executor。
   只保留用于封闭工具链：
     resume_diagnosis child
     resume_version project action
   后续新增 executor 必须先写 contract 和 dry-run。

5. Finalization Barrier。
   “只做 retrieval 不允许 final”，“缺 required write output 不允许 final”属于正确边界。

6. Retrieval / Note / Product ref canonicalization。
   这是输入规范化，不是补丁。
```

### 3.2 需要回退或合并

这些逻辑有补丁化倾向，不能继续扩张：

```text
1. hidden/suppress 针对具体工具的分支。
   例如某个阶段隐藏 tool_search / delegate_agents 后再给模型提示。
   这类逻辑应逐步被 contract finalization barrier 或 tool normalizer 替代。

2. schema_search 重复后替换成 required tool 的主循环逻辑。
   这是“模型没推进，runtime 替它猜下一步”的模式。
   如果下一步唯一，应该由 executor / action contract 直接执行；
   如果不唯一，应该要求澄清或返回 workflow incomplete，而不是继续猜。

3. 针对 interview_review_update 的硬编码 payload 构造。
   这类应迁移到 ActionContract 的 payload builder，而不是放在 agent_runtime.py helper。

4. child job_agent / resume_agent 的大量低层 guard。
   能被 child executor 或 child task contract 覆盖的，应逐步删除；
   剩余只保留事实边界和副作用保护。

5. final answer recovery 的过度使用。
   如果 deterministic final packet 已足够，应直接生成结构化最终答复；
   recovery 只用于自然语言润色或异常兜底。
```

### 3.3 必须泛化

这类不能按当前失败点补：

```text
1. delegate_agents 参数。
   当前失败是 tasks[0] 缺 target_agent_id。
   不能写“缺 target_agent_id 就过滤”。
   应建立 DelegateTaskNormalizer：
     - 按当前 phase / contract 归一化；
     - 只保留合法 target_agent_id；
     - 补齐 artifact_refs；
     - 合并重复 task；
     - repair 后二次 schema validation；
     - validation 不过则不执行工具。

2. action payload 构造。
   interview_review_update / rag_note_write / rag_learning_task_create 不能散落在 runtime helper。
   应迁移到 ActionContractPayloadBuilder。

3. required tool 推进。
   不再由 hidden/suppress 触发“再提醒模型一次”。
   改成：
     - contract 可执行：代码执行；
     - contract 不可执行：返回缺失 refs / missing outputs；
     - 多 contract：不自动执行。

4. tool result 进入模型上下文。
   保留必要事实，不塞重复正文。
   但不为了省 token 删掉质量必需证据。
```

## 4. 下一步实施方案

### Phase A：复杂度审计，不改行为

输出一张 runtime 分支表：

```text
branch / helper
所在文件
触发条件
解决的问题
是否仍被 live smoke 需要
归类：keep / remove / generalize
迁移目标
```

重点审计：

```text
agent_runtime.py:
  _strict_required_tool_auto_call_from_plan
  _deterministic_action_payload_tool_call_from_plan
  _hidden_runtime_tool_names_to_suppress
  _hidden_runtime_support_tool_allowed
  schema_search_suppressed_required_tool_visible
  strict_schema_search_replaced_with_required_tool
  final answer recovery / finalization packet

workflow/guard.py:
  main stage gate
  child job_fit low-level guard
  child resume_diagnosis output reuse
  delegate_agents repair

workflow/tool_plan.py:
  pending plan merge
  successful tool result -> next plan
  action contract runtime plan
```

### Phase B：建立通用 DelegateTaskNormalizer

新增边界层：

```text
app/runtime/workflow/delegation.py
```

职责：

```text
normalize_delegate_agents_arguments(
  raw_arguments,
  phase,
  known_refs,
  action_contract,
  available_agents,
) -> NormalizedDelegateDecision
```

输出：

```text
status:
  normalized
  rejected
  no_change

arguments:
  修复后的 delegate_agents 参数

errors:
  缺 target_agent_id / artifact_refs / instruction 等结构错误

repair_actions:
  结构化记录，给 smoke 和事件日志使用
```

硬规则：

```text
1. JD fit 阶段只允许 job_agent child task。
2. resume diagnosis 阶段只允许 resume_agent child task。
3. application create / merge 不允许伪装成 child task。
4. 缺 target_agent_id 的 task 不执行。
5. repair 后必须通过 delegate_agents schema validation。
```

这不是补丁，因为它不关心“某一次缺哪个字段”，而是把 orchestration 参数从模型输出变成代码规范化。

### Phase C：迁移 action payload builder

把主循环里的确定性 action payload 移出：

```text
app/runtime/workflow/action_payloads.py
```

首批迁移：

```text
interview_review_update -> career_application_merge payload
rag_note_write -> note_create/note_append payload skeleton
rag_learning_task_create -> learning_task_create payload skeleton
```

agent_runtime 只调用：

```text
payload = action_payload_builder.build(contract, state)
```

不再知道每个 action 的字段细节。

### Phase D：收缩 agent_runtime 主循环

目标结构：

```text
AgentRuntime loop:
  1. 组装上下文
  2. 调模型
  3. 把 tool_calls 交给 ToolCallController
  4. 执行 controller 返回的 executable calls
  5. 更新 state
  6. finalization
```

新边界：

```text
ToolCallController:
  - schema validation
  - delegate normalization
  - action payload builder
  - hidden/not-visible handling
  - replacement/rejection decision

WorkflowExecutorRouter:
  - dry-run contract
  - executable contract dispatch
  - sync/stream executor 统一入口
```

### Phase E：逐步删除补丁分支

只在 live smoke 通过后删除：

```text
1. schema_search repeated -> required tool auto replacement。
2. interview_review_update hard-coded auto payload。
3. child resume_diagnosis output reuse guard 中已被 executor 覆盖的部分。
4. career_custom_resume 相关 hidden correction 文案。
```

删除顺序要小步，不一次性大改。

## 5. 验收方式

每个 phase 都必须跑：

```text
unit:
  tests/test_workflow_executor.py
  tests/test_runtime_tool_plan.py
  tests/test_workflow_runtime_guard.py
  tests/test_retrieval_action_flow.py
  tests/test_smoke_live_matrix.py

focused live:
  rag_read_only
  career_full
  rag_to_note
  rag_to_learning_task
  interview_review

full matrix:
  P0 + P1
```

产品停止线：

```text
1. P0/P1 结构成功率不下降。
2. harmful_duplicate = 0。
3. hidden 不新增。
4. failed tool result 不新增。
5. avg_tokens / avg_elapsed 没有明显劣化。
6. agent_runtime.py 新增行数不能继续快速膨胀。
```

复杂度停止线：

```text
一次改动如果只是为了某个 smoke run 的单个参数变体过关，停止。
必须能回答：
  - 这个规则适用于哪些 workflow？
  - 新 agent 加入后是否仍成立？
  - 是否从主循环移出了一类职责？
  - 是否减少了模型自由拼底层参数的空间？
```

## 6. 当前不处理的事

```text
不继续追求几秒或几千 token 的优化；
不新增某个工具名的 hidden/suppress 特判；
不把所有流程都 executor 化；
不做 LangGraph 全量迁移；
不因为 career_full run_001 的 malformed delegate_agents 直接写过滤补丁；
不改 .env。
```

## 7. 建议立即执行的下一步

```text
1. 做 Phase A 审计表。
2. 只选择一个泛化边界实现：DelegateTaskNormalizer。
3. 写单测覆盖：
   - malformed task + valid task；
   - missing target_agent_id；
   - missing artifact_refs；
   - duplicated job_agent tasks；
   - unknown target_agent_id；
   - JD fit 阶段 application create 不进入 child task。
4. 接入 delegate_agents 工具入口或 gateway，不接入主循环 if。
5. 跑 focused live：career_full 2x2。
```

如果 Phase B 成功，说明方向正确：不是又加一层 guard，而是把“模型拼 orchestration 参数”的自由度收回到代码层。

## 8. M41-A：DelegateTaskNormalizer 初版

落地内容：

```text
app/runtime/workflow/delegation.py
tests/test_delegate_task_normalizer.py
```

接入点：

```text
WorkflowRuntimeGuard._inspect_delegate_agents

顺序：
  1. 先保留已有 instruction / artifact_refs / jd_fit task repair；
  2. repair 后统一 normalize delegate_agents.tasks；
  3. normalization 通过后再做 signature / semantic signature 复用；
  4. normalization 失败时返回 recoverable block，不把 malformed 参数交给工具执行。
```

Normalizer 目前只管结构边界：

```text
1. task 必须是 object；
2. target_agent_id 必须非空，且属于可用 child agents；
3. instruction 必须非空；
4. 明确 jd_fit phase 时只保留 job_agent task；
5. 明确 resume_diagnosis phase 时只保留 resume_agent task；
6. JD fit 下 application create/merge 不能伪装成 child task；
7. 有合法 task 时，丢弃 malformed sibling；
8. 没有合法 task 时，不执行 delegate_agents；
9. 明确 workflow phase 且能读取当前 session artifacts 时，artifact_refs 必须是真实 session artifact id；
10. 从 instruction 中补齐真实 artifact refs，但不在普通 delegate 场景里改变原有 semantic reuse。
```

这次不是在主循环里写新 if，也没有改 `delegate_agents` 工具执行逻辑；它把参数结构收敛到 guard/gateway 边界。

单测：

```text
python -m py_compile app/runtime/workflow/delegation.py app/runtime/workflow/guard.py app/runtime/workflow/__init__.py

uv run pytest tests/test_delegate_task_normalizer.py tests/test_workflow_runtime_guard.py \
  tests/test_agent_task_runtime.py tests/test_runtime_tool_plan.py tests/test_smoke_live_matrix.py -q

result:
passed
```

实现中踩到的一个边界：

```text
第一版 normalizer 只做 malformed task 过滤，没有校验 artifact_refs 是否是真实 session artifact。

M41-A c2_r2 live 结果：
  career_full 2x2
  passed=0/2
  harmful_duplicate_runs=2/2
  hidden_runs=1/2

根因：
  模型把 artifact_id / artifact_refs 这类占位词塞进 delegate_agents.tasks[].artifact_refs；
  normalizer 没去掉它们；
  guard 的 exact signature 认为每次 delegate 参数不同；
  于是没有复用上一次 delegate 结果，形成有害重复委派。

修正：
  normalizer 在明确 workflow phase 且能拿到当前 session artifact 集合时，
  只保留真实 session artifact id；
  无明确 phase 时不做这个收窄，避免影响普通 delegate 和 semantic reuse。
```

修正后 focused live：

```text
uv run python tools/smoke_live_matrix.py \
  --scenario career_full \
  --runs 1 --concurrency 1 --stream \
  --data-dir data/live_smoke_matrix_m41_a_delegate_normalizer_c1_r1 \
  --json-report data/live_smoke_matrix_m41_a_delegate_normalizer_c1_r1/report.json

result:
passed=1/1
elapsed=196.44s
llm_calls=18
tokens=107387
harmful_duplicate=0
hidden=0
failed_tool_results=0
```

剩余问题，不在本轮继续修：

```text
1. JD 阶段仍出现 session_create_text_artifact 重写尝试：
   duplicate=2，但 harmful_duplicate=0；
   这来自 job_agent 生成的匹配报告 artifact 被事实边界拦截后重写。

2. JD 阶段仍出现 memory_write：
   smoke 当前未判失败；
   后续应放入 ActionContract / product-store 边界统一处理，
   不在本轮给 memory_write 加新场景 guard。

3. 单轮仍偏重：
   career_full c1_r1 elapsed=196.44s, tokens=107387。
   这不是 delegate normalizer 能解决的问题。
```

## 9. M41-B：高并发停止线与 runtime 分支审计

### 9.1 Live smoke 停止线

按用户要求跑了两批 `career_full 6x3`，不继续追加第三批。原因是两批合计已经达到 M39/M41 停止线；继续跑主要消耗时间和 token，不能提供足够新的工程信号。

Batch 1：

```text
data/live_smoke_matrix_m41_b_delegate_normalizer_career_full_6x3_r1
passed=6/6
failed=0/6
avg_elapsed=177.04s
max_elapsed=199.11s
avg_llm_calls=14.8
max_llm_calls=16
avg_tokens=78337
max_tokens=83141
duplicate_runs=2/6
harmful_duplicate_runs=0/6
recovery_duplicate_runs=2/6
hidden_runs=0/6
```

Batch 2：

```text
data/live_smoke_matrix_m41_b_delegate_normalizer_career_full_6x3_r2
passed=6/6
failed=0/6
avg_elapsed=170.78s
max_elapsed=186.57s
avg_llm_calls=15.3
max_llm_calls=17
avg_tokens=77253
max_tokens=83578
duplicate_runs=2/6
harmful_duplicate_runs=0/6
recovery_duplicate_runs=2/6
hidden_runs=0/6
```

合并结果：

```text
passed=12/12
avg_elapsed=173.91s
max_elapsed=199.11s
avg_llm_calls=15.1
max_llm_calls=17
avg_tokens=77795
max_tokens=83578
duplicate_runs=4/12
harmful_duplicate_runs=0/12
hidden_runs=0/12
```

判断：

```text
1. P0 career_full 已满足停止线。
2. harmful duplicate 和 hidden 都没有回归。
3. 剩余 duplicate 是 recovery duplicate 或被幂等吸收后的 harmless duplicate。
4. 不继续为了 duplicate_runs=0/12 加 guard。
5. 下一步只做结构性收敛，不做单点行为补丁。
```

### 9.2 当前代码复杂度快照

```text
app/runtime/agent_runtime.py                 4879 lines
app/runtime/workflow/guard.py                4187 lines
app/runtime/workflow/tool_plan.py            2092 lines
app/runtime/workflow/executor.py              232 lines
app/runtime/workflow/contracts.py             467 lines
app/runtime/workflow/delegation.py            421 lines
app/runtime/agent/finalization_packet.py      544 lines
```

结构判断：

```text
agent_runtime.py 和 workflow/guard.py 仍然过重。
M41 后续不能再把新业务分支塞进这两个文件。
新逻辑只能落到：
  - WorkflowContract / ActionContract；
  - DelegateTaskNormalizer；
  - payload builder；
  - ToolCallController；
  - finalization packet。
```

### 9.3 Runtime 分支审计表

| 分支 / helper | 当前位置 | 当前作用 | 归类 | 后续方向 |
|---|---|---|---|---|
| `DelegateTaskNormalizer` | `workflow/delegation.py` + `workflow/guard.py` | 规范化模型生成的 `delegate_agents.tasks`，过滤 malformed / 越界 child task | keep | 保留为 orchestration 参数边界；后续只扩展成 contract-aware，不回到主循环 if |
| `delegate_agents` signature / semantic reuse | `workflow/guard.py` | 复用已成功的委派结果，避免重复 child task | keep | 保留；必要时把 signature 计算迁到 delegation module，减少 guard 体积 |
| `_strict_required_tool_auto_call_from_plan` | `agent_runtime.py` | 模型反复 schema_search 或没推进时，按 runtime plan 自动替换 required tool | generalize | 迁到 ToolCallController；只允许 contract 唯一步骤自动执行；不能继续加工具名分支 |
| `_deterministic_action_payload_tool_call_from_plan` | `agent_runtime.py` | interview review 阶段自动构造 `career_application_merge` payload | generalize | 迁到 ActionContractPayloadBuilder；当前硬编码阶段不可继续扩张 |
| `_interview_review_application_merge_arguments` | `agent_runtime.py` | 为面试复盘构造项目更新 payload | generalize | 迁到 action payload builder；字段规则属于 action contract，不属于主循环 |
| `_hidden_runtime_tool_names_to_suppress` | `agent_runtime.py` | 工具不可见时 suppress，追加 runtime notice | retire gradually | 保留兜底；新场景不得再加 hidden/suppress 特判；能被 contract barrier 覆盖后逐步删 |
| `_hidden_runtime_support_tool_allowed` | `agent_runtime.py` | resume_version 阶段允许隐藏的 artifact 创建支持工具 | generalize | 迁到 contract step capability；不要按 title 猜业务阶段 |
| `schema_search_suppressed_required_tool_visible` | `agent_runtime.py` | 模型只搜 schema，不调用 required tool 时提醒继续 | retire gradually | 如果 contract 唯一，走 controller/executor；如果不唯一，返回 incomplete，不再多轮提醒 |
| `strict_schema_search_replaced_with_required_tool` | `agent_runtime.py` | 多轮 schema_search 后强制替换 required tool | generalize | 只能由 contract dry-run 证明唯一可执行后触发 |
| final answer recovery | `agent_runtime.py` + `agent/finalization_packet.py` | 无正文、内部文案或伪工具输出时补答 | keep but cap | 保留作为兜底；正常 workflow 应优先使用 finalization packet，不把 recovery 当主路径 |
| finalization packet | `agent/finalization_packet.py` | 用结构化 packet 生成补答上下文，避免塞全量工具历史 | keep | 继续保留；后续可做 deterministic final answer，但不能牺牲质量证据 |
| WorkflowExecutor dry-run | `workflow/executor.py` | 判断 contract 是否唯一、refs/tools 是否满足 | keep | 继续作为封闭 workflow 的入口；不要扩到开放式内容生成 |
| ActionContract registry | `workflow/contracts.py` | P1/P0 action 的 required outputs 和工具链声明 | keep | 新 agent / 新 action 必须通过 contract 注册，不改主循环 |
| Action runtime plan builder | `workflow/tool_plan.py` | 根据 action contract 推进 missing outputs / final barrier | generalize | 保留方向，但文件已偏大；后续拆 `action_plan.py` |
| child low-level guard | `workflow/guard.py` | 子 agent 低层事实边界、重复读取/写入保护 | retire gradually | 只保留事实边界和副作用保护；能由 executor/contract 覆盖的删除 |

### 9.4 下一步只做两类事

允许做：

```text
1. 迁移职责：
   从 agent_runtime.py / guard.py 移出已有逻辑，不改变行为。

2. 把已验证有效的边界泛化：
   例如 ActionContractPayloadBuilder、ToolCallController、contract-aware delegation。
```

暂不做：

```text
1. 不继续追 harmless duplicate 到 0。
2. 不为了某个 run 多一次只读工具调用加 guard。
3. 不把所有 workflow executor 化。
4. 不压缩必要质量上下文。
5. 不改 .env。
```

### 9.5 建议执行顺序

```text
M41-C:
  新增 ActionContractPayloadBuilder。
  只迁移 interview_review_application_merge payload。
  行为必须保持不变。

M41-D:
  新增 ToolCallController skeleton。
  第一版只承接 delegate normalization / strict required auto-call 的决策封装。
  AgentRuntime 调用 controller，不新增业务规则。

M41-E:
  从 agent_runtime.py 删除已迁移 helper。
  跑 P0/P1 focused smoke。

M42:
  再考虑成本收敛：
    - final answer deterministic path；
    - tool result context 去重；
    - child instruction contract id 化。
```

停止条件：

```text
如果某一步不能减少 agent_runtime.py / guard.py 的职责，或者只是为某个 live smoke 变体加判断，直接停止。
```
