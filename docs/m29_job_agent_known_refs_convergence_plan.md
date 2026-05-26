# M29 Job Agent Known Refs 收敛优化方案

> 状态：准备实施。本文承接 M27/M28，不继续堆工具轮次上限，也不继续按单个重复工具打补丁；优先修复 job_agent runtime plan 丢失已知引用，导致模型被系统提示诱导重复 get/list 的根因。

## 1. 背景

M28 `custom_resume 6x3` live smoke 已经 6/6 通过，但耗时和 token 仍主要集中在前两段：

```text
resume_diagnosis avg 139.73s
jd_fit          avg 174.51s
project_action  avg 69.85s
```

其中 `jd_fit` 是当前最大瓶颈。M28 后 job_agent 的典型长尾不再是“产物写不出来”，而是：

```text
产物已经接近完成，但模型又重复调用 career_resume_profile_get /
career_profile_get / session_read_artifact / session_create_text_artifact。
```

## 2. 根因

M28 新增了 `required_tool_call_hint`，方向是对的：当 runtime plan 已经收敛到唯一下一步工具时，直接告诉模型该调用什么工具、有哪些可复用参数。

但在 job_fit 子任务里，`WorkflowRuntimeGuard._child_job_fit_runtime_plan()` 生成计划时只保留了局部引用。例如 report artifact 已创建后，它只返回：

```json
{
  "required_tools": ["career_job_fit_report_save"],
  "known_refs": {
    "report_artifact_id": "artifact_xxx"
  }
}
```

而前面已经成功拿到或保存过的引用没有合并进来：

```text
resume_profile_id
career_profile_id
jd_analysis_id
source_artifact_id
```

于是 M28 的 hint 会正确地把这些字段标成 `missing_args`。模型看到缺参后，会继续调用低层 get/list 或重建 artifact，造成额外 LLM 轮次和 token 消耗。

这不是模型单独的问题，而是 runtime plan 的状态源不完整：

```text
工具结果里有引用
store 里有当前产品记录
assigned task 里有 artifact refs
但生成下一步计划时没有统一聚合
```

## 3. 目标

M29 只解决一个明确目标：

```text
当 job_agent 已进入 JDAnalysis / report artifact / JobFitReport 保存链路时，
runtime plan 必须携带足够的 known_refs，让模型直接调用下一步唯一工具。
```

期望效果：

- `career_job_fit_report_save` 的 hint 不再把已知 `resume_profile_id`、`career_profile_id`、`jd_analysis_id`、`source_artifact_id` 标成缺失。
- report artifact 已创建后，低层工具重复调用会被 block，同时返回完整 save skeleton。
- 不削弱候选人事实边界校验。
- 不放宽副作用工具保护。
- 不引入 LangGraph；保持 M27 的手动状态机内核。

## 4. 实现方案

### 4.1 Runtime 层维护 known refs 账本

`pending_runtime_plan` 不是完整状态账本。M28 的问题之一是：`career_resume_profile_get` 成功时还没有明确 pending plan，因此 resume id 没有被后续 plan 继承。

M29 在 `AgentRuntime` 内维护一个轻量 `runtime_known_refs`：

```text
每个成功工具结果 -> 提取产品 id / artifact id -> 合并到 runtime_known_refs
生成新的 pending_runtime_plan -> 自动把 runtime_known_refs 合并进去
隐藏工具或 workflow block -> 从 plan 中继续回填 refs
```

这样即使某个引用是在 plan 形成之前拿到的，后续 `career_jd_analysis_save` 和 `session_create_text_artifact` 推进计划时也不会丢。

### 4.2 新增 job_fit known refs 聚合

在 `WorkflowRuntimeGuard` 中新增 job_fit 专用聚合函数，从以下来源合并引用：

```text
1. 当前 run 成功的 session_read_artifact
2. assigned task 的 artifact_refs
3. 当前 run 成功的 career_resume_profile_get / career_profile_get
4. 当前 run 成功的 career_jd_analysis_save
5. 当前 session store 中唯一 active ResumeProfile / CareerProfile
6. report artifact 创建结果
7. 已保存 JobFitReport / JDAnalysis 记录
```

优先级：

```text
run 内最新成功工具结果 > 当前阶段显式 artifact > store 中唯一当前记录 > career_profile_default
```

其中 `career_profile_default` 是业务工具已经支持的默认值，只在准备调用 `career_job_fit_report_save` 时补齐。

### 4.3 改造 `_child_job_fit_runtime_plan`

三个分支都从统一 known refs 派生：

```text
需要重写 report artifact:
  next = session_create_text_artifact
  known_refs = 当前已知输入和 JDAnalysis 引用

需要保存 JDAnalysis:
  next = career_jd_analysis_save
  known_refs = report_artifact_id + 输入 artifact refs

需要保存 JobFitReport:
  next = career_job_fit_report_save
  known_refs = report_artifact_id + jd_analysis_id + resume_profile_id + career_profile_id + source_artifact_id
```

### 4.4 验证

先跑定向测试：

```text
tests/test_workflow_runtime_guard.py
tests/test_tool_reveal.py
tests/test_runtime_tool_plan.py
```

再跑 M27/M28 相关回归：

```text
tests/test_tool_call_ledger.py
tests/test_tool_policy.py
tests/test_tool_gateway.py
tests/test_agent_runtime.py
tests/test_agent_task_runtime.py
tests/test_career_tools.py
tests/test_career_live_smoke_report.py
tests/test_tool_result_view.py
```

最后只跑一组 live smoke，避免等待过久：

```text
custom_resume 6x3
```

通过标准不是只看 6/6，而是重点看：

```text
jd_fit 平均耗时是否下降
job_agent duplicate_runs 是否下降
hidden/blocked payload 是否不再提示已知参数 missing
```
