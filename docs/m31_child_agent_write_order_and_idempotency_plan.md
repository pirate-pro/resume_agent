# M31 Child Agent 写入顺序与幂等收敛方案

> 状态：已实现并通过一组 6x3 live smoke。本文承接 M30。M30 已把 main-agent hidden tool 消耗从 5/6 降到 1/6，剩余 duplicate 主要集中在 child agents 的写入阶段。

## 1. 当前基线

M30 live smoke：

```text
data/live_career_smoke_m30_strict_tool_surface_6x3_r1
passed=6/6
avg_llm_calls=23.0
max_llm_calls=25
avg_tokens=122919
max_tokens=130433
duplicate_runs=3/6
hidden_runs=1/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

重复样本分两类：

```text
1. job_agent: session_create_text_artifact
   多数是岗位匹配报告事实边界校验失败后的重写，不是成功后重复创建。

2. resume_agent: career_resume_profile_save
   先保存 ResumeProfile，后创建简历诊断 artifact，再尝试二次保存补 diagnosis_artifact_id。
```

第二类是更明确的根因问题：阶段顺序不确定，导致写入幂等保护虽然避免了重复落库，但也把后来的 `diagnosis_artifact_id` 更新挡掉了。

## 2. 根因

resume_agent 初始工具面同时暴露：

```text
session_read_artifact
session_create_text_artifact
career_resume_profile_save
career_resume_profile_get
```

模型读完简历后，没有确定性的 runtime plan 约束下一步必须先生成诊断 artifact，所以可能直接调用：

```text
career_resume_profile_save(source_artifact_id=...)
```

随后模型再创建诊断报告 artifact，并第二次调用：

```text
career_resume_profile_save(source_artifact_id=..., diagnosis_artifact_id=...)
```

当前 guard / tool 本身按 `source_artifact_id` 复用已有 ResumeProfile，于是第二次被当成 idempotent reuse。副作用是安全的，但：

```text
- 多消耗一轮 LLM 和一次工具调用
- smoke 计入 duplicate
- 已有 ResumeProfile 可能没有 diagnosis_artifact_id
```

这不是提高 max_tool_rounds 能解决的问题，也不是继续加重复调用上限的问题。

## 3. 目标

M31 目标：

```text
resume_agent 读完简历后，确定性进入：
session_create_text_artifact -> career_resume_profile_save

career_resume_profile_save 必须在有 diagnosis_artifact_id 后执行。
```

成功标准：

```text
custom_resume 6x3 passed=6/6
stagnation_runs=0/6
hard_safety_runs=0/6
hidden_runs 不恶化
resume_agent:career_resume_profile_save duplicate 消失或显著下降
ResumeProfile.diagnosis_artifact_id 稳定存在
```

## 4. 实现方案

### 4.1 session_read_artifact 为 child resume_agent 返回下一步计划

当 `resume_agent` 在子任务里读取简历 artifact 后，工具结果追加一个 runtime plan：

```text
phase=resume_diagnosis
next_allowed_tools=[session_create_text_artifact]
required_tools=[session_create_text_artifact]
missing_outputs=[diagnosis_artifact, resume_profile]
known_refs={resume_source_artifact_id, source_artifact_id}
next_action=先创建简历诊断报告 artifact，不要先保存 ResumeProfile。
```

这样 M30 strict mode 会在下一轮只暴露 `session_create_text_artifact`。

### 4.2 简历诊断 artifact 创建后，不直接 final

当前逻辑只要 previous plan 缺 `diagnosis_artifact`，创建 artifact 后可能直接进入 final plan。

M31 改为：

```text
如果 previous missing_outputs 还包含 resume_profile，或 known_refs 没有 resume_profile_id：
  下一步 required tool = career_resume_profile_save
  known_refs 带 diagnosis_artifact_id
否则：
  final_answer_ready
```

### 4.3 guard 兜底早保存

如果模型仍绕过 runtime plan，在没有诊断 artifact 时调用 `career_resume_profile_save`：

```text
block/recoverable
next_allowed_tools=[session_create_text_artifact]
reason=resume_profile_save_before_diagnosis_artifact
```

如果已有诊断 artifact，但模型保存时漏传 `diagnosis_artifact_id`：

```text
guard 自动补入 diagnosis_artifact_id 后继续执行
```

### 4.4 career tool 保留保守更新能力

如果已有 ResumeProfile 没有 `diagnosis_artifact_id`，而新调用携带了它，可以更新同一条记录，而不是无条件 idempotent reuse。

这是数据正确性的兜底，不作为主要调度手段。

## 5. 验证

目标测试：

```text
tests/test_runtime_tool_plan.py
tests/test_workflow_runtime_guard.py
tests/test_career_tools.py
tests/test_agent_runtime.py
```

回归：

```text
uv run pytest tests/test_tool_call_ledger.py tests/test_tool_policy.py tests/test_tool_gateway.py \
  tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_tool_reveal.py \
  tests/test_workflow_runtime_guard.py tests/test_career_tools.py tests/test_agent_task_runtime.py \
  tests/test_career_live_smoke_report.py tests/test_tool_result_view.py -q
```

live smoke：

```text
uv run python tools/smoke_career_live_flow.py \
  --runs 6 \
  --concurrency 3 \
  --max-tool-rounds 24 \
  --project-action custom_resume \
  --data-dir data/live_career_smoke_m31_child_write_order_6x3_r1 \
  --quiet
```

## 6. 实现结果

已完成：

```text
app/tools/builtin_tools/session_artifacts.py
  - child resume_agent 读取简历 artifact 后，返回 resume_diagnosis runtime plan
  - 下一步锁定 session_create_text_artifact，要求先创建诊断报告 artifact

app/runtime/workflow/tool_plan.py
  - 支持从普通成功工具结果中读取 runtime_plan_applied
  - 简历诊断 artifact 创建后，如果 ResumeProfile 未保存，则下一步锁定 career_resume_profile_save

app/runtime/workflow/guard.py
  - block child resume_agent 在没有诊断 artifact 时提前调用 career_resume_profile_save
  - 已有诊断 artifact 但保存画像漏传 diagnosis_artifact_id 时自动修正参数

app/tools/builtin_tools/career.py
  - 已有 ResumeProfile 缺 diagnosis_artifact_id 时，允许同一记录补写该字段
```

验证：

```text
uv run pytest tests/test_career_tools.py::test_resume_agent_read_resume_artifact_returns_diagnosis_artifact_plan \
  tests/test_career_tools.py::test_resume_profile_save_updates_existing_record_with_diagnosis_artifact \
  tests/test_workflow_runtime_guard.py::test_child_resume_agent_blocks_profile_save_before_diagnosis_artifact \
  tests/test_workflow_runtime_guard.py::test_child_resume_agent_repairs_profile_save_with_existing_diagnosis_artifact \
  tests/test_runtime_tool_plan.py::test_successful_resume_read_requires_diagnosis_artifact_before_profile_save \
  tests/test_runtime_tool_plan.py::test_successful_resume_diagnosis_artifact_requires_profile_save_when_profile_missing \
  tests/test_runtime_tool_plan.py::test_successful_resume_diagnosis_artifact_finishes_resume_stage -q
=> 7 passed

uv run pytest tests/test_career_tools.py tests/test_runtime_tool_plan.py tests/test_workflow_runtime_guard.py tests/test_agent_runtime.py -q
=> passed

uv run pytest tests/test_tool_call_ledger.py tests/test_tool_policy.py tests/test_tool_gateway.py \
  tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_tool_reveal.py \
  tests/test_workflow_runtime_guard.py tests/test_career_tools.py tests/test_agent_task_runtime.py \
  tests/test_career_live_smoke_report.py tests/test_tool_result_view.py -q
=> passed

uv run mypy --explicit-package-bases app/tools/builtin_tools/session_artifacts.py app/tools/builtin_tools/career.py \
  app/runtime/workflow/tool_plan.py app/runtime/workflow/guard.py \
  tests/test_career_tools.py tests/test_runtime_tool_plan.py tests/test_workflow_runtime_guard.py
=> Success: no issues found in 7 source files

git diff --check -- . ':!.env'
=> passed
```

live smoke：

```text
data/live_career_smoke_m31_child_write_order_6x3_r1
passed=6/6
avg_elapsed=184.12s
max_elapsed=208.16s
avg_llm_calls=23.2
max_llm_calls=26
avg_tokens=123285
max_tokens=135164
duplicate_runs=4/6
hidden_runs=3/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

相对 M30：

```text
avg_llm_calls: 23.0 -> 23.2
max_llm_calls: 25 -> 26
avg_tokens: 122919 -> 123285
max_tokens: 130433 -> 135164
duplicate_runs: 3/6 -> 4/6
hidden_runs: 1/6 -> 3/6
stagnation_runs: 0/6 -> 0/6
hard_safety_runs: 0/6 -> 0/6
```

M31 达成的局部目标：

```text
resume_agent:career_resume_profile_save duplicate 在本组 smoke 中消失。
6/6 ResumeProfile 都带 diagnosis_artifact_id。
```

未达成的整体效率目标：

```text
总 duplicate/hidden 没下降，反而变差。
新增/残留长尾来自：
- job_agent 因事实边界校验失败重写 session_create_text_artifact
- job_agent 在 required tool 已锁定后重复 session_read_artifact
- main-agent 在 resume_version/application merge 阶段重复 career_application_get 或 session_read_artifact
```

结论：

```text
M31 修复了 resume_agent 写入顺序和 ResumeProfile 数据完整性问题；
但它不是整体效率优化的成功闭环。下一步不应继续围绕 resume_profile_save 打补丁，
而应收敛“required tool 已锁定后模型仍调用旧工具”的同类问题，尤其是
career_application_get / session_read_artifact 的 hidden 重复，以及 job_agent 报告生成前的事实边界前置。
```
