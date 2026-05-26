# M32 Strict Context 与确定性 Required Tool 执行方案

> 状态：已实施。M31 修复了 resume_agent 写入顺序和 `diagnosis_artifact_id` 数据完整性，但 6x3 live smoke 的整体效率没有变好。M32 不继续给单个重复工具加限制，而是处理同一类根因：required tool 已锁定后，模型仍从历史上下文里调用旧工具。

## 1. M31 后基线

```text
data/live_career_smoke_m31_child_write_order_6x3_r1
passed=6/6
avg_llm_calls=23.2
max_llm_calls=26
avg_tokens=123285
max_tokens=135164
duplicate_runs=4/6
hidden_runs=3/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

已解决：

```text
resume_agent:career_resume_profile_save duplicate 消失
6/6 ResumeProfile 都有 diagnosis_artifact_id
```

剩余/新增长尾：

```text
job_agent:session_create_text_artifact 重写
job_agent:session_read_artifact hidden
agent_main:career_application_get hidden
agent_main:session_read_artifact hidden
```

## 2. 根因

M30 已经把当前轮 visible tools 收窄到唯一 required tool，但 `ToolContextWindow` 的 compact state 仍会回放历史工具摘要：

```text
successful_tools
recent_observations
workflow_completion_guidance
latest_refs
```

这些摘要里还包含上一个阶段的 `career_application_get` / `session_read_artifact` / `session_create_text_artifact`。模型看不到 schema，但仍会从上下文惯性里调用旧工具名，runtime 再返回 hidden/block。结果正确，但多消耗一轮 LLM。

所以 M32 的核心不是继续 block，而是：

```text
strict mode 下，模型上下文只保留 required tool 所需状态。
当 required tool 参数完整且无需模型生成正文时，模型若仍调用隐藏工具，orchestrator 直接执行 required tool。
```

## 3. 修改方向

### 3.1 Strict 状态摘要过滤历史工具

`ToolContextWindow.render_messages()` 增加 strict runtime plan 参数。

strict mode 下：

```text
state_message 只保留：
- required tool
- known_refs
- missing_outputs
- recent observations 中不在 discouraged_tools 的工具

过滤：
- tool_search
- session_read_artifact
- session_list_artifacts
- session_search_artifact
- career_application_get 等当前 runtime_plan.discouraged_tools
```

pending exchange 保留，因为它通常是刚完成的上一 required tool；但 state summary 不再反复提示旧工具。

实现：

```text
app/runtime/agent/tool_context_window.py
```

`render_messages()` / `usage_payload()` 接收 `runtime_plan` 与 `strict_mode`，strict mode 下 compact state 只保留当前 required tool 的支撑观察，并显式携带 `known_refs`、`missing_outputs`、`discouraged_tools`。

### 3.2 Strict hidden violation 自动执行确定性 required tool

当满足：

```text
strict_runtime_tool_mode=True
模型调用了当前不可见/隐藏工具
pending_runtime_plan 只有一个 required tool
required_tool_call_hint.missing_args=[]
required tool 不需要模型生成长正文
```

则 runtime 不返回 hidden result，而是把本次调用改写成 required tool：

```text
career_application_merge
career_job_fit_report_save
```

不自动执行：

```text
session_create_text_artifact   需要模型生成报告正文
career_resume_version_create   需要模型生成定制简历正文/策略
career_profile_merge           需要模型判断更新内容
```

这样可以减少：

```text
agent_main 在 merge 阶段重复 career_application_get
job_agent 在 save 阶段重复 session_read_artifact
```

实现：

```text
app/runtime/agent_runtime.py
app/runtime/workflow/tool_hints.py
```

补充点：

```text
- career_job_fit_report_save 缺 career_profile_id 时，hint 默认使用 career_profile_default。
- 自动替换执行时同时记录实际执行的 tool_call，避免审计/验收只看到原始隐藏工具。
- required tool 完成且 runtime_plan.final_answer_ready=True 后，runtime 直接进入 final answer recovery，不再开放普通工具轮次。
```

### 3.3 job_agent 报告事实边界前置

已有 guard 会在 `session_create_text_artifact` 后检查非法候选人事实，但失败时已经花掉完整报告生成 token。

M32 先不做复杂模板生成，只把 `report_artifact_contract` 纳入 strict notice：

```text
supported_candidate_facts
rewrite_rules
artifact_rules
```

让模型第一次生成报告前就看到事实边界。

实现：

```text
app/runtime/workflow/tool_plan.py
app/runtime/agent/tool_reveal.py
app/runtime/agent_runtime.py
```

`pending_runtime_plan_from_workflow_result()` 保留 `report_artifact_contract`，hidden result 和 strict notice 都会透传该合同。

## 4. Live 结果

### 4.1 M32 r1

```text
data/live_career_smoke_m32_strict_context_required_tool_6x3_r1
passed=6/6
avg_elapsed=233.04s
max_elapsed=417.46s
avg_llm_calls=23.7
max_llm_calls=31
avg_tokens=126999
max_tokens=171119
duplicate_runs=3/6
hidden_runs=5/6
stagnation_runs=1/6
hard_safety_runs=0/6
```

结论：失败。r1 证明原始 M32 还没有兜住根因。

关键原因：

```text
- career_job_fit_report_save 实际可默认 career_profile_default，但 hint 把 career_profile_id 当成 missing_arg，导致 strict auto-execute 不触发。
- final_answer_ready 后仍进入普通工具轮次，模型偶发继续调用工具，造成 terminal hidden。
```

### 4.2 M32 r2

```text
data/live_career_smoke_m32_strict_context_required_tool_6x3_r2
passed=5/6
avg_elapsed=164.74s
max_elapsed=182.12s
avg_llm_calls=22.3
max_llm_calls=24
avg_tokens=116345
max_tokens=124794
duplicate_runs=1/6
hidden_runs=2/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

结论：效率改善明显，但验收未完全通过。

失败原因：

```text
Run 4 实际通过 auto-execute 执行了 career_application_merge，
但事件日志只记录了原始模型 tool_call=tool_search；
smoke 的项目回写检查按 tool_call 名称判断，因此报告“项目动作未回写 CareerApplication”。
```

r2 后补丁：

```text
strict auto-execute required tool 时，额外记录实际执行的 tool_call：
name=<required_tool>, auto_executed=true, replaced_tool_name=<model_tool_name>
```

### 4.3 M32 r3

```text
data/live_career_smoke_m32_strict_context_required_tool_6x3_r3
passed=6/6
avg_elapsed=190.48s
max_elapsed=206.65s
avg_llm_calls=23.0
max_llm_calls=25
avg_tokens=124065
max_tokens=134584
duplicate_runs=3/6
hidden_runs=2/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

结论：r3 确认 auto-execute 的审计事件补丁有效，r2 的“项目动作未回写 CareerApplication”误判消失。

但 M32 只算部分达标：

```text
- 通过率恢复到 6/6。
- stagnation 保持 0/6。
- hard_safety 保持 0/6。
- hidden_runs 从 M31 的 3/6 降到 2/6。
- duplicate_runs 从 M31 的 4/6 降到 3/6。
- avg_llm_calls 从 M31 的 23.2 降到 23.0。
- avg_tokens 与 avg_elapsed 没有稳定下降，r3 avg_tokens=124065，略高于 M31 的 123285。
```

剩余问题已经不是 `career_application_merge` 审计或 `career_job_fit_report_save` 缺默认参数，而是低层读取和子 agent 局部重复：

```text
job_agent:career_resume_profile_get
job_agent:session_read_artifact
resume_agent:session_read_artifact
agent_main:tool_search
```

## 5. 成功标准

```text
passed=6/6
stagnation_runs=0/6
hard_safety_runs=0/6
hidden_runs <= 1/6
duplicate_runs <= 2/6
ResumeProfile.diagnosis_artifact_id 继续 6/6 存在
```

## 6. 验证

```text
uv run pytest tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_workflow_runtime_guard.py tests/test_tool_result_view.py -q

uv run pytest tests/test_tool_call_ledger.py tests/test_tool_policy.py tests/test_tool_gateway.py \
  tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_tool_reveal.py \
  tests/test_workflow_runtime_guard.py tests/test_career_tools.py tests/test_agent_task_runtime.py \
  tests/test_career_live_smoke_report.py tests/test_tool_result_view.py -q

uv run mypy --explicit-package-bases \
  app/runtime/agent_runtime.py \
  app/runtime/agent/tool_context_window.py \
  app/runtime/workflow/tool_plan.py \
  tests/test_agent_runtime.py

uv run python tools/smoke_career_live_flow.py \
  --runs 6 \
  --concurrency 3 \
  --max-tool-rounds 24 \
  --project-action custom_resume \
  --data-dir data/live_career_smoke_m32_strict_context_required_tool_6x3_r1 \
  --quiet
```

已执行：

```text
uv run pytest tests/test_tool_call_ledger.py tests/test_tool_policy.py tests/test_tool_gateway.py \
  tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_tool_reveal.py \
  tests/test_workflow_runtime_guard.py tests/test_career_tools.py tests/test_agent_task_runtime.py \
  tests/test_career_live_smoke_report.py tests/test_tool_result_view.py tests/test_tool_context_window.py -q

uv run mypy --explicit-package-bases \
  app/runtime/agent_runtime.py app/runtime/workflow/tool_hints.py \
  app/runtime/agent/tool_context_window.py app/runtime/workflow/tool_plan.py \
  app/runtime/agent/tool_reveal.py tests/test_agent_runtime.py \
  tests/test_tool_context_window.py tests/test_runtime_tool_plan.py tests/test_tool_reveal.py

git diff --check -- . ':!.env'
```
