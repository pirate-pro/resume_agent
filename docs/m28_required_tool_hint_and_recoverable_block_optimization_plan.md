# M28 Required Tool Hint 与 Recoverable Block 优化方案

> 状态：第一阶段已完成并通过 `custom_resume 6x3` live smoke。本文承接 M27 第一阶段；目标不是再加一层 guard，而是降低 required tool 阶段的无效 LLM 轮次。

## 0. 实施记录

### 2026-05-25

已完成：

- 新增 `app/runtime/workflow/tool_hints.py`，统一生成 required tool 参数提示。
- `hidden_tool_result` 改为对 `career_job_fit_report_save`、`career_resume_version_create`、`career_application_merge` 使用同一套 hint。
- `runtime_plan_notice` 在单一 required tool 阶段附加 `required_tool_call_hint`，让模型下一轮能直接填参。
- `resume_version_missing_content_or_artifact` / `resume_version_compacted_content_not_usable` block 结果返回 `retry_tool_call_skeleton` 和 `blocked_retry_tools`。

验证结果：

```text
custom_resume 6x3 r1: 6/6 passed
avg_llm_calls=24.3
max_llm_calls=26
avg_tokens=132466
max_tokens=146860
duplicate_runs=2/6
hidden_runs=6/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

对比 M27 r4：

```text
avg_llm_calls: 26.0 -> 24.3
max_llm_calls: 31 -> 26
avg_tokens: 141990 -> 132466
max_tokens: 170177 -> 146860
hidden_runs: 6/6 -> 6/6
```

结论：

- required tool hint 对 LLM 调用数和 token 有正向收益。
- `hidden_runs` 仍未消失，说明模型仍会尝试隐藏工具；但总 hidden 次数下降，且没有触发 stagnation。
- 总耗时没有下降，本组平均耗时更高，主要来自 live LLM 延迟与前两阶段 job_agent 分析链路，下一步不应继续只围绕 project-action hint 优化。

## 1. 背景

M27 已经完成：

- 工具执行统一进入 ToolGateway。
- ToolCallLedger 持久化工具调用账本。
- blocked 结果不再错误复用。
- 工具轮次从硬失败改为软预算 + 无推进收束。

`custom_resume 6x3 r4` 已经恢复到 `6/6 passed`，且：

```text
stagnation_runs=0/6
hard_safety_runs=0/6
```

但效率问题还没完全收敛：

```text
hidden_runs=6/6
duplicate_runs=2/6
```

典型残留：

- `career_resume_version_create` 已可见后，模型仍调用 `tool_search`。
- `career_resume_version_create` 首次缺 `content` / `artifact_id`，被 recoverable block 后再重试。
- `career_application_merge` 阶段偶发重复 `career_application_get` 或 `tool_search`。

## 2. 根因

M27 解决的是执行边界，但模型纠偏信息仍不够“可执行”：

```text
当前提示告诉模型“不要做什么”，但没有稳定告诉模型“下一次工具调用怎么填”。
```

具体表现：

- `hidden_tool_result.required_tool_call_hint` 目前只覆盖 `career_job_fit_report_save`。
- `runtime_plan_notice` 展示已知引用，但没有按 required tool 给出参数骨架。
- `resume_version_missing_content_or_artifact` 只说明缺完整 Markdown 或 generated_file artifact，没有给出下一次调用的最小参数模板。

## 3. 优化目标

必须保持：

```text
custom_resume 6/6 passed
stagnation_runs=0
hard_safety_runs=0
产品记录完整
```

应改善：

```text
hidden_runs
duplicate_runs
avg_llm_calls
max_llm_calls
project-action 阶段耗时
```

## 4. 实施范围

### 4.1 扩展 required_tool_call_hint

为以下 required tool 增加参数提示：

- `career_resume_version_create`
- `career_application_merge`

`career_resume_version_create` hint 应包含：

```text
available_args:
  base_resume_profile_id
  target_jd_analysis_id
  title
  evidence_refs

missing_args:
  content_or_artifact_id

instruction:
  直接生成完整 Markdown content，或使用已有 generated_file artifact_id；
  不要 tool_search/get/list；
  不要把匹配报告、风险表或面试准备写进 content。
```

`career_application_merge` hint 应包含：

```text
available_args:
  application_id
  updates.resume_version_ids
  evidence_refs

missing_args:
  resume_version_id 或 application_id

instruction:
  只把当前 resume_version_id merge 回 CareerApplication；
  不要重新创建 ResumeVersion；
  不要重新读取项目。
```

### 4.2 runtime_plan_notice 加入工具参数骨架

当 `required_tools` 只有一个时，notice 附加对应 hint。

目标是模型下一轮能直接形成工具参数，而不是再次搜索 schema。

### 4.3 recoverable block 提供下一次调用模板

对 `resume_version_missing_content_or_artifact` / `resume_version_compacted_content_not_usable` 增加：

```text
required_tool_call_hint
retry_tool_call_skeleton
blocked_retry_tools
```

其中 skeleton 只包含可确定的 id 和结构，不生成正文内容。

### 4.4 不做的事

- 不引入 LangGraph。
- 不迁移完整 DAG。
- 不把 guard 继续扩成规划器。
- 不为了降低 hidden count 牺牲产品记录。

## 5. 验证

单元测试：

```text
tests/test_tool_reveal.py
tests/test_runtime_tool_plan.py
tests/test_workflow_runtime_guard.py
tests/test_agent_runtime.py
tests/test_tool_gateway.py
```

集成验证：

```text
uv run python tools/smoke_career_live_flow.py --runs 6 --concurrency 3 --max-tool-rounds 24 --project-action custom_resume --data-dir data/live_career_smoke_m28_required_hint_6x3_r1 --quiet
```

验收口径：

```text
6/6 passed
stagnation_runs=0/6
hard_safety_runs=0/6
hidden_runs 不高于 M27 r4
avg/max llm calls 不高于 M27 r4
```
