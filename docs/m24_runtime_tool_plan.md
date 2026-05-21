# M24-2 RuntimeToolPlan 工具动作编排方案

> 状态：开发方案。目标是在不牺牲质量的前提下减少 main-agent 的低价值工具轮次。

## 1. 背景

r27 live smoke 已经证明求职主链路可以跑通：

```text
ResumeProfile / CareerProfile / JDAnalysis / JobFitReport / CareerApplication / ResumeVersion 全部齐
artifact_count=5
质量门禁通过
```

但 token 没有下降：

```text
r17 total_tokens=162,437
r27 total_tokens=192,531
```

主要增长来自 main-agent：

```text
r17 agent_main=96,689
r27 agent_main=125,661
```

工具调用上也能看到低价值动作：

```text
重复 tool_search
重复 session_read_artifact
阶段内为了确认状态反复 get/list
```

这些不是 memory 问题，也不是单纯 schema 太大的问题，而是 main-agent 每轮缺少明确的下一步动作面。

## 2. 目标

新增只读 `RuntimeToolPlan`：

```text
RuntimeToolPlan
  phase
  known_refs
  missing_outputs
  next_allowed_tools
  discouraged_tools
  schema_groups
  final_answer_ready
  next_action
```

它只从现有事实源和上下文状态推导，不写任何数据。

目标：

- 让模型知道“下一步最多调用哪些工具”。
- 减少重复 `tool_search`。
- 减少已经有产品记录后的 `session_read_artifact`。
- 减少为了确认已知 id 的 get/list。
- 不改 tool schema reveal 的基本模式。
- 不做大段 Markdown 事实预检。

## 3. 非目标

本阶段不做：

- 不接 LangGraph。
- 不做通用 DAG 引擎。
- 不改变 child-agent 自主工具调用能力。
- 不把普通聊天强行纳入 workflow。
- 不再尝试 ResumeVersion 预执行事实 block。
- 不用更激进的 product compact。

## 4. 编排原则

### 4.1 计划只约束 main-agent

child-agent 仍然根据自己的 AGENT / skill / tool schema 自主完成专业任务。

### 4.2 计划来自事实源

输入包括：

```text
CurrentWorkflowState
CareerFlowState
WorkflowPhaseSnapshot
active_artifacts
current run tool results
```

不使用模型自述作为完成态事实。

### 4.3 下一步动作要窄

例如定制简历阶段：

```text
缺 ResumeVersion:
  next_allowed_tools = [career_resume_version_create]

ResumeVersion 已创建但未合并:
  next_allowed_tools = [career_application_merge]

全部完成:
  next_allowed_tools = []
  final_answer_ready = true
```

### 4.4 不是硬阻断所有偏离

第一版主要通过上下文提示和 tool_search 结果约束减少无效动作。

只有已经由 `WorkflowRuntimeGuard` 覆盖的完成态，才继续执行确定性 block。

## 5. 阶段策略

### 5.1 简历诊断

```text
缺 ResumeProfile:
  next_allowed_tools = [delegate_agents]
  schema_groups = [delegation, career_diagnosis]

有 ResumeProfile，缺 CareerProfile:
  next_allowed_tools = [career_resume_profile_get, career_profile_merge]
  discouraged_tools = [delegate_agents, session_read_artifact, session_list_artifacts]

ResumeProfile + CareerProfile 已完成:
  final_answer_ready = true
```

### 5.2 JD 匹配

```text
缺 JDAnalysis 或 JobFitReport:
  next_allowed_tools = [delegate_agents]
  schema_groups = [delegation, career_jd_fit]

有 JDAnalysis + JobFitReport，缺 CareerApplication:
  next_allowed_tools = [career_application_create]
  discouraged_tools = [delegate_agents, session_read_artifact, career_jd_analysis_get, career_job_fit_report_get]

三者已完成:
  final_answer_ready = true
```

### 5.3 定制简历

```text
缺关键引用:
  next_allowed_tools = [career_application_get]

关键引用齐，缺 ResumeVersion:
  next_allowed_tools = [career_resume_version_create]
  discouraged_tools = [session_read_artifact, career_resume_version_list, retrieval_search]

ResumeVersion 已创建，缺 Application merge:
  next_allowed_tools = [career_application_merge]

全部完成:
  final_answer_ready = true
```

## 6. 与 tool_search 的关系

`tool_search` 仍然保留，但结果要参考 `RuntimeToolPlan`：

- 如果 `next_allowed_tools` 已经明确，tool_search 返回 `runtime_plan_guidance`。
- 如果搜索结果包含大量不在计划内的工具，结果中标记为 `discouraged_by_runtime_plan`。
- 如果当前计划已经给出可直接调用的工具，提示模型不要继续搜索。

第一版已验证：只靠提示模型“不要继续搜索”不够稳定，模型仍可能先 `tool_search` 再执行。

因此第二版增加一个更直接但仍然可控的策略：

```text
search 模式下：
  RuntimeToolPlan.next_allowed_tools 非空
    -> 这些工具在本轮直接进入 initial_visible_tool_names
    -> 模型可以直接调用下一步工具
    -> 不需要先 tool_search

  RuntimeToolPlan.final_answer_ready=true
    -> 不额外 reveal 工具
    -> 仍只保留常驻工具，由 WorkflowRuntimeGuard 拦截多余调用

  普通对话 / 阶段不明确 / next_allowed_tools 为空
    -> 保持原 tool_search 渐进披露
```

这不是恢复旧的“意图裁剪工具 schema”，因为可见工具不是由关键词猜测出来的，而是由确定性流程状态推导：

```text
CurrentWorkflowState + CareerFlowState + WorkflowPhaseSnapshot
  -> RuntimeToolPlan.next_allowed_tools
  -> initial_visible_tool_names
```

它解决的是“阶段已经明确时还要多一轮 tool_search”的成本问题；未知能力发现仍由 `tool_search` 负责。

## 7. 实施顺序

```text
1. 新增 app/runtime/workflow/tool_plan.py
2. ShortTermContextPlan 增加 runtime_tool_plan
3. section_builder 注入 current_runtime_tool_plan
4. tool_search 返回 runtime_plan_guidance
5. ContextBundle 增加 initial_visible_tool_names
6. AgentRuntime 在 search 模式下把 initial_visible_tool_names 合并进首轮可见 schema
7. 单元测试
8. live smoke 验证
```

## 8. 验收指标

与 r27 对比：

```text
质量门禁通过
artifact_count=5
产品记录齐全
tool_search <= 4
session_read_artifact <= 5
agent_main LLM calls <= 18
total_tokens <= 175k
```

如果质量下降或产品记录缺失，撤回 tool_search 约束，仅保留只读 plan section。

## 9. r28/r29 验证结论

r28 验证了 `initial_visible_tool_names` 的稳态收益：

```text
配置: TOOL_SCHEMA_DISCLOSURE_MODE=search
     TOOL_CONTEXT_WINDOW_MODE=compact
     WORKFLOW_RULE_SELECTION_MODE=sparse

结果: 通过
质量门禁: 通过
artifact_count: 5
产品记录: ResumeProfile / CareerProfile / JDAnalysis / JobFitReport / CareerApplication / ResumeVersion 全部齐
total_tokens: 190,204
agent_main total: 120,167
agent_main schema_sum: 103
```

与 r27 相比：

```text
r27 total_tokens: 192,531
r28 total_tokens: 190,204

r27 agent_main: 125,661
r28 agent_main: 120,167

r27 agent_main schema_sum: 209
r28 agent_main schema_sum: 103
```

结论：初始 reveal 能明显降低 schema 累积，但总 token 下降不大，因为模型仍会主动 `tool_search`，并且 child-agent 的 get/read 轮次仍然存在。

r29 尝试在 `next_allowed_tools` 非空时临时隐藏 `tool_search`，已撤回：

```text
简历诊断阶段出现重复 delegate_agents / session_read_artifact / state_set / memory_write
说明强行拿掉 tool_search 会损伤模型决策，不适合作为默认策略。
```

当前保留策略：

```text
next_allowed_tools 进入 initial_visible_tool_names
tool_search 保持常驻
继续依靠 runtime plan / guard 引导，不强行隐藏工具
```
