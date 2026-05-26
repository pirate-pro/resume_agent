# M25 最终回答质量与工具预算边界优化方案

> 状态：开发前方案。本文承接 M24 高并发 live smoke 结果，目标是把工具轮次限制从“用户可见失败原因”降级为极端安全阀，并用“是否有真实推进”作为 agent 收束边界。

## 1. 背景

当前求职 Agent 主链路已经具备较稳定的产品数据能力：

```text
none:          6/6 passed
checklist:     6/6 passed
interview:     6/6 passed
custom_resume: 6/6 passed
```

这说明 M24 的核心问题已经从“产品记录是否能写对”转为“最终交付是否像产品级 Agent”。最近 live smoke 中仍出现过这种最终回答：

```text
Tool schema search limit reached before generating final answer.
```

质量门禁能因为产品记录完整而放行，但从用户体验看，这种回答是不合格的。它把 runtime 的内部保护机制直接泄露给用户，也没有交付用户要的面试准备、申请清单或定制简历结果。

## 2. 判断

现在的工具轮次限制偏低，而且语义不对。

合理的边界不应该是：

```text
调用了 N 轮工具 -> 直接终止 -> 返回工具上限错误
```

而应该是：

```text
工具调用没有带来新信息 / 新产物 / 阶段推进
  -> 判断为无推进
  -> 阻止继续重复调用
  -> 基于当前 durable state 生成可用最终回答
```

因此 M25 不建议完全移除所有边界。需要保留一个很高的硬安全阀，防止模型死循环、成本失控或外部工具异常。但正常业务链路不应该被低轮次数字截断，更不能把 `Tool call limit` / `Tool schema search limit` 作为最终用户回答。

## 3. 根因

### 3.1 数字上限承担了错误职责

`AgentRuntime` 目前在工具循环里直接判断：

```text
schema_search_rounds >= _MAX_SCHEMA_SEARCH_ROUNDS
business_tool_rounds >= run_input.max_tool_rounds
```

触发后直接生成：

```text
Tool schema search limit reached before generating final answer.
Tool call limit reached before generating final answer.
```

这两个字符串适合作为日志或事件，不适合作为用户答案。

### 3.2 runtime 不知道“有没有推进”

同样是一次工具调用，语义差异很大：

```text
career_resume_version_create 成功创建 ResumeVersion -> 有推进
career_application_get 首次读到项目 -> 有推进
重复 tool_search 且未揭示新工具 -> 无推进
同一工具同一参数反复失败 -> 无推进
产品记录已经齐全后继续搜索工具 -> 无推进
```

当前 runtime 主要按轮次数量判断，没有把这些差异建模。

### 3.3 终态恢复路径不够产品化

M24 已经有 `final_answer_ready` 和 terminal workflow result 的概念，但数字上限触发时没有优先进入最终回答恢复，而是直接返回内部错误文本。

这会导致一个不合理结果：

```text
产品数据已经完成
项目动作也已经回写
但最终 answer_preview 是 runtime 上限错误
```

## 4. 优化目标

第一阶段目标：

- 正常求职主链路不再因为 10 轮工具上限终止。
- 工具上限 / schema search 上限不再出现在最终用户回答中。
- runtime 能识别“有推进”和“无推进”。
- 当模型重复调用同一工具且没有推进时，自动收束到最终回答。
- 最终回答必须基于当前产品记录、artifact 和已完成阶段生成。
- live smoke 把内部错误文本泄露视为质量失败。

非目标：

- 不取消所有安全边界。
- 不通过放宽产品记录校验或事实守卫来减少轮次。
- 不把所有工具失败都包装成成功。
- 不重写 agent 架构。
- 不把普通聊天强行纳入求职 workflow。

## 5. 方案设计

### 5.1 将工具轮次拆成软预算和硬安全阀

引入两个概念：

```text
soft_budget:
  用于观察、提示和优化，不直接作为用户可见失败条件。

hard_safety_limit:
  极端保护阀，只防止死循环或成本失控。
```

建议第一版配置：

```text
product live smoke:
  --max-tool-rounds 24

AgentTask / API:
  默认值仍可保持 10，但上限提高到 40 或 60。
  对求职 workflow 任务按阶段覆盖为 20-24。

runtime hard safety:
  max_model_rounds 不再简单等于 max_tool_rounds + schema_search_extra。
  由 hard_safety_limit 独立控制。
```

`max_tool_rounds` 的定位从“业务终止条件”调整为“期望预算”。超过软预算时记录事件并触发更严格的无推进检测，但不直接返回错误。

### 5.2 新增 ToolLoopProgressTracker

在 `AgentRuntime` 的 sync 和 stream 循环中维护一个轻量状态对象：

```text
ToolLoopProgressTracker
  seen_tool_fingerprints
  consecutive_no_progress_rounds
  repeated_tool_count
  revealed_tool_names
  completed_runtime_refs
  successful_product_records
  successful_artifacts
  consumed_required_tools
  last_error_signature
```

工具调用后生成 `ToolProgressEvent`：

```text
tool_name
arguments_fingerprint
success
progress_kind
progress_refs
error_signature
runtime_plan_before
runtime_plan_after
```

`arguments_fingerprint` 只保留稳定业务字段，不记录大段正文，避免日志和比较受内容噪声影响。

### 5.3 有推进信号

以下情况判定为有推进：

```text
1. 新建或更新产品记录
   career_profile_merge
   career_resume_profile_save
   career_jd_analysis_save
   career_job_fit_report_save
   career_resume_version_create
   career_application_create / merge

2. 新建 artifact
   session_create_text_artifact 返回新的 artifact_id。

3. 首次读到当前阶段必需对象
   career_application_get
   career_resume_profile_get
   career_profile_get
   session_read_artifact

4. runtime plan 单调推进
   missing_outputs 减少
   required_tools 减少
   next_allowed_tools 进入后序阶段
   final_answer_ready 从 false 变 true

5. 工具 schema 有效揭示
   tool_search 揭示了之前不可见、且当前 runtime plan 需要的工具。

6. recoverable guard 给出新的修复方向
   例如 schema error 后 next_allowed_tools 或 required fields 发生变化。
```

### 5.4 无推进信号

以下情况判定为无推进：

```text
1. 同一个工具 + 等价参数重复出现，且没有新记录 / artifact / plan 推进。
2. 连续 tool_search 但没有揭示新工具，或只搜索已可见工具。
3. required outputs 已满足，模型仍继续搜索或读取低层对象。
4. 同一个 schema error / invalid ref / not found 重复出现。
5. hidden_tool_result 反复出现，模型没有改用 next_allowed_tools。
6. 产品 store 幂等复用后，模型继续重复 save 同一记录。
7. workflow terminal result 已出现后，模型仍继续要求工具。
```

### 5.5 StagnationDetector 收束策略

建议第一版阈值：

```text
same_tool_same_args_no_progress >= 2
consecutive_no_progress_rounds >= 3
same_error_signature >= 2
schema_search_without_new_reveal >= 2
terminal_result_then_tool_call >= 1
soft_budget_exceeded + no_progress >= 1
```

触发后不再执行相同无推进工具，而是进入收束：

```text
1. 记录 workflow_runtime_decision:
   policy=finalize
   reason=tool_loop_stagnation
   stop_reason=stagnation

2. 向模型注入 runtime notice:
   当前不能继续调用工具。
   请基于已经完成的记录和 artifact 生成最终回答。
   如果缺少关键数据，只说明已完成、缺失、下一步需要用户提供什么。

3. 调用 final answer recovery。

4. 如果 recovery 仍返回空文本或内部错误文本，使用 deterministic fallback。
```

deterministic fallback 只使用 durable state，不编造业务内容：

```text
已完成：
  - 已创建 / 更新的产品记录
  - 已创建的 artifact

仍缺少：
  - runtime plan 中未完成的 required outputs

下一步：
  - 用户需要补充的信息，或系统下一步应执行的动作
```

### 5.6 禁止内部错误文本成为最终回答

新增最终回答过滤：

```text
Tool call limit reached
Tool schema search limit reached
max_tool_rounds
schema search limit
workflow_runtime_result
hidden_tool_by_runtime_plan
```

如果模型最终回答包含这类 runtime 内部文本：

```text
1. 不直接返回给用户。
2. 记录 assistant_answer_rejected 事件。
3. 进入 final answer recovery。
4. recovery 失败时返回 deterministic fallback。
```

这不是掩盖错误。内部错误仍保留在日志和事件里，live smoke 仍可检测；只是不能把它当作用户交付。

### 5.7 sync / stream 保持同构

`run` 和 `run_stream` 当前各自维护工具循环。M25 要避免只修 sync 漏掉 stream。

第一版可以先抽出纯函数：

```text
evaluate_tool_loop_budget(...)
update_tool_loop_progress(...)
should_finalize_due_to_stagnation(...)
sanitize_final_answer(...)
```

sync / stream 共用这些函数，后续再考虑把工具循环进一步抽象。

## 6. 开发顺序

### 第一步：补确定性测试

先新增测试覆盖当前不合理行为：

```text
1. schema search 到达上限时，不返回 Tool schema search limit 作为最终回答。
2. business tool 到达软预算时，不返回 Tool call limit 作为最终回答。
3. 同一 tool_search 无新揭示重复两次后，进入 final answer recovery。
4. 同一工具同一参数重复失败后，进入 final answer recovery。
5. workflow terminal result 后继续工具调用，立即收束。
6. stream 路径与 sync 路径行为一致。
```

### 第二步：实现最终回答净化

先改最小闭环：

```text
AgentRuntime 任何路径准备返回 answer 前：
  sanitize_final_answer(answer)
  如果命中内部错误文本 -> final answer recovery / fallback
```

这一步能立刻解决用户可见错误泄露。

### 第三步：引入 progress tracker

实现轻量 `ToolLoopProgressTracker`，先只处理高信号场景：

```text
tool_search 无新揭示
same tool + same args
same error signature
terminal workflow result
runtime plan final_answer_ready
```

产品记录 / artifact 的精细进展判断可以逐步补充。

### 第四步：调整预算语义

修改 runtime：

```text
超过 max_tool_rounds:
  记录 soft_budget_exceeded
  如果本轮仍有推进，可以继续到 hard_safety_limit
  如果无推进，finalize

达到 hard_safety_limit:
  记录 hard_safety_limit_reached
  finalize / fallback
```

修改 CLI 和 schema：

```text
tools/smoke_career_live_flow.py:
  --max-tool-rounds 允许到 24 或 40

app/domain/models.py
app/domain/agent_tasks.py
app/schemas/chat.py
app/services/agent_invocation_service.py
app/tools/builtin_tools/agents.py
  上限从 20 提高到 40 或 60
```

具体数值开发时按测试结果定，默认先保守用 40。

### 第五步：升级 live smoke 质量门禁

新增质量断言：

```text
最终回答不能包含内部 runtime 文本。
项目动作最终回答必须包含用户可读交付。
interview 必须包含面试准备重点或行动项。
checklist 必须包含申请前检查项或风险。
custom_resume 必须包含 ResumeVersion 或定制简历 artifact。
```

原来的 `tool_limit_detected` 保留，但语义改为：

```text
检测到 hard safety 或 stagnation 事件 -> warning / error 取决于是否有可用最终回答。
检测到内部错误文本进入 assistant_message -> error。
```

## 7. 验收标准

确定性回归：

```text
uv run pytest tests/test_agent_runtime.py tests/test_agent_task_runtime.py tests/test_career_live_smoke_report.py -q
uv run mypy app/runtime/agent_runtime.py app/domain/models.py app/domain/agent_tasks.py app/schemas/chat.py app/tools/builtin_tools/agents.py
```

live smoke：

```text
uv run python tools/smoke_career_live_flow.py --runs 6 --concurrency 3 --max-tool-rounds 24 --project-action custom_resume --quiet
```

常规开发验收只跑一组代表性 6x3，避免每次修改都等待四组高并发 live smoke。默认选择 `custom_resume`，因为它覆盖主链路、项目动作、定制简历、artifact 和 ResumeVersion 写入。只有在改动明确触及某个项目动作的专属逻辑，或准备 release gate 时，才追加 `none` / `checklist` / `interview` 的扩展矩阵。

质量验收：

- 代表性 6/6 live smoke 通过；release gate 或高风险共享改动可扩展到多 action 矩阵。
- 最终回答不包含 `Tool call limit` / `Tool schema search limit`。
- 产品记录数量和质量门禁不退化。
- 有 stagnation 事件时，最终回答仍能说明已完成内容和下一步。
- 不出现同一工具同一参数长时间重复调用。

体验验收：

- 用户看到的是业务结果、阶段性结果或明确缺失项。
- 用户不会看到 runtime 内部预算、schema search 或 hidden tool 文案。
- 项目动作 answer_preview 能表达真实交付，而不是只有“已更新记录”。

## 8. 风险和缓解

### 8.1 过早收束

风险：

```text
模型只是正常重试一次，runtime 误判为无推进。
```

缓解：

```text
第一版阈值不低于 2-3 次。
只在无新记录、无新 artifact、无 plan 推进时触发。
terminal workflow result 后才允许 1 次收束。
```

### 8.2 成本上升

风险：

```text
提高工具轮次后，异常 run 消耗更多 token。
```

缓解：

```text
soft_budget_exceeded 后启用更严格的无推进检测。
hard_safety_limit 保留。
live smoke 记录 p95 tool/model calls。
```

### 8.3 fallback 内容过弱

风险：

```text
deterministic fallback 只能列记录，业务价值不如模型总结。
```

缓解：

```text
fallback 只作为最后兜底。
优先使用 final answer recovery，让模型基于已有上下文总结。
fallback 必须诚实，不编造未读取内容。
```

### 8.4 sync / stream 行为不一致

风险：

```text
只修普通 run，流式接口仍泄露内部错误。
```

缓解：

```text
预算判断、无推进检测、最终回答净化都抽成共享函数。
测试同时覆盖 sync 和 stream。
```

## 9. 开发结论

M25 的核心不是简单把 `max_tool_rounds` 调大，也不是完全取消限制，而是把边界语义改正确：

```text
低工具轮次上限 -> 软预算
极端死循环保护 -> 硬安全阀
真实终止条件 -> 无推进 / 已终态 / 可恢复最终回答
```

开发优先级：

```text
1. 先禁止内部上限错误成为最终回答。
2. 再实现无推进检测和收束。
3. 然后提高 smoke 和 API 的工具预算上限。
4. 最后用一组代表性 6x3 高并发 live smoke 验证最终回答质量；必要时再扩展多 action 矩阵。
```
