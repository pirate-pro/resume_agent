# M24 子 Agent 阶段执行层方案

> 状态：开发方案。目标是解决高并发 live smoke 暴露的“子 Agent 阶段恢复失控”问题，不继续通过提示词或单个 smoke 样本打补丁。

## 1. 背景

M24 已经完成了三类降本和稳定性改造：

- `tool_search -> schema reveal`：减少一次性暴露全部工具 schema。
- `ToolContextWindow`：压缩历史 tool message。
- `WorkflowRuntimeGuard`：对主链路关键产物做阶段守卫和幂等复用。

但高并发 smoke 仍然暴露出长尾问题：

```text
部分 run 会在 job_agent 内部重复读取资料、重复生成报告 artifact、重复保存产品记录。
guard 能拦截错误动作，但拦截结果没有稳定变成下一轮的执行计划。
child-agent 工具轮数耗尽后，AgentTaskRuntime 仍可能把任务标记为 completed。
main-agent 看到子任务 completed，但产品记录不完整，于是再次 delegate，形成跨 run 重复。
```

最新问题的 token 结构也说明根因不只是 schema：

```text
失败长尾 run:
  max schema count: 11
  job_agent tokens 明显高于 main-agent
  session_read_artifact / product get / delegate_agents 出现重复
```

结论：当前缺的是“子 Agent 阶段执行层”。guard 不能只是被动返回 block/reuse，还要把下一步允许工具、已知引用和缺失产物稳定传给下一轮；子任务 runtime 也不能只看自然语言输出判断完成。

## 2. 目标

第一版只覆盖求职主链路中最容易失控的 `job_agent -> JD 匹配` 阶段。

目标：

- 子 Agent 每个阶段都有确定性的完成条件。
- recoverable block/reuse 必须携带 `next_allowed_tools` 和 `blocked_tools`。
- AgentRuntime 能把子 Agent guard 结果转成 pending runtime plan。
- 子 Agent 在 pending plan 存在时，只暴露完成当前阶段必需的工具。
- AgentTaskRuntime 不再把工具轮数耗尽或缺少必需产物的子任务标记为 completed。
- main-agent 根据结构化子任务状态决策，而不是靠自然语言摘要重复委派。

## 3. 非目标

本阶段不做：

- 不引入 LangGraph 依赖。
- 不做通用 DAG 编排器。
- 不把普通对话纳入 workflow。
- 不限制 child-agent 的专业判断，只限制已进入阶段后的错误恢复路径。
- 不针对某次 smoke 的固定标题、固定 id、固定文本写规则。
- 不把质量校验全部提前到 runtime；报告内容质量仍由工具校验和后续质量门禁负责。

## 4. JD 匹配阶段模型

`job_agent` 的 JD 匹配任务按事实源拆成五个阶段：

```text
read_inputs
  事实：已读取 JD artifact / 简历画像 / 职业画像
  下一步：保存 JDAnalysis 或生成匹配报告 artifact

save_jd_analysis
  事实：career_jd_analysis_save 成功，或同一 JD artifact 下已有 active JDAnalysis
  下一步：生成唯一岗位匹配报告 artifact

create_fit_report_artifact
  事实：当前 child run 已有合法 job_fit_report artifact
  下一步：career_job_fit_report_save

save_job_fit_report
  事实：career_job_fit_report_save 成功，或同一 resume_profile_id + jd_analysis_id 下已有 active JobFitReport
  下一步：最终总结

final_answer
  事实：JDAnalysis + JobFitReport + report_artifact_id 都存在
  下一步：停止工具调用，返回结构化结果
```

阶段完成态只能来自事实源：

```text
SessionArtifact
CareerProductStore
current run tool_result
agent_result_summary
AgentTaskRecord
```

不能来自模型说“我已经完成”。

## 5. Runtime 行为

### 5.1 子阶段状态构建

新增只读子阶段状态：

```text
ChildStageExecutionState
  agent_id
  run_id
  task_id
  stage_name
  completed_refs
  missing_outputs
  next_allowed_tools
  blocked_tools
  final_answer_ready
```

第一版可以直接从 `WorkflowRuntimeGuard` 内部构建，不单独落库。

### 5.2 Guard 结果必须可执行

所有可恢复的子阶段 block/reuse 结果必须包含：

```json
{
  "workflow_runtime_result": true,
  "policy": "block",
  "recoverable": true,
  "next_allowed_tools": ["career_job_fit_report_save"],
  "required_tools": ["career_job_fit_report_save"],
  "blocked_tools": ["session_read_artifact", "career_resume_profile_get"],
  "missing_outputs": ["job_fit_report"],
  "completed_refs": {
    "report_artifact_id": "artifact_xxx",
    "jd_analysis_id": "jd_xxx"
  }
}
```

如果没有 `next_allowed_tools`，AgentRuntime 就无法窄化下一轮工具面，模型会继续尝试低层读取和搜索。

### 5.3 AgentRuntime 应用 pending plan

AgentRuntime 已有 `pending_runtime_plan_from_workflow_result`，但只有 guard 结果携带 `next_allowed_tools` 时才生效。

本阶段要保证：

- 子 Agent 的 guard block/reuse 也能进入 pending runtime plan。
- pending plan 下隐藏 `tool_search` 和 `blocked_tools`。
- 必需工具已可见时，不继续暴露低层读取工具。
- 如果模型提前最终答复，runtime 用 `runtime_plan_notice` 要求先完成必需工具。

### 5.4 子任务完成判定

AgentTaskRuntime 不能只要 child runtime 正常返回就标记 completed。

第一版增加保守判定：

```text
如果 answer 包含 Tool call limit reached:
  status = failed

如果目标 agent 是 job_agent，且 instruction 明确要求 JD 匹配报告:
  必须存在 job_fit_report 产品引用或当前 child run 成功调用 career_job_fit_report_save
  否则 status = failed
```

失败结果要返回给 main-agent，而不是伪装成 completed。main-agent 后续可以选择重试或向用户说明失败。

## 6. 实施顺序

### 第一步：文档和测试基线

完成本文档，明确这不是 prompt 补丁。

### 第二步：子阶段 next_allowed_tools 补齐

统一为 `job_agent` 的 recoverable block/reuse 结果补齐：

- `session_create_text_artifact` 内容为空。
- 错误创建 JD 分析 artifact。
- 报告 artifact 已存在但还没保存 JobFitReport。
- 报告 artifact 内容被事实校验拦截后需要重写。
- 报告记录已保存后禁止低层读取。

### 第三步：Runtime plan 覆盖子 Agent

确认 `pending_runtime_plan_from_workflow_result` 能吃到子阶段结果，并在 child-agent full schema 模式下仍能隐藏被阻断工具。

### 第四步：AgentTaskRuntime 完成判定

新增子任务结果校验：

- 工具轮数耗尽 => failed。
- JD 匹配任务缺少 `job_fit_report` 或 `report_artifact` => failed。
- 失败摘要中保留缺失产物，方便 main-agent 判断是否重试。

### 第五步：高并发 live smoke

用默认降本配置跑：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
```

## 7. 验收指标

第一版目标：

```text
高并发 live smoke 通过率 >= 5/6
job_agent 不再出现 Tool call limit reached
同一 JD 匹配阶段 delegate_agents <= 1，除非子任务明确 failed
同一 child run 内 session_read_artifact 不再超过必要输入读取
career_jd_analysis_save <= 1
career_job_fit_report_save <= 1
artifact_count <= 5
普通成功 run 总 token 回到 20 万以内
长尾失败 run 不再膨胀到 30 万以上
```

第二版再追求：

```text
6/6 高并发稳定通过
普通成功 run 总 token 低于 16 万
main-agent 不再承担子阶段恢复编排
```

## 8. 风险

### 8.1 过度限制子 Agent

如果 `next_allowed_tools` 太窄，可能让模型无法修复真实质量问题。

控制方式：

- 只在阶段事实明确后收窄。
- 内容质量冲突时允许重新创建 report artifact，但阻止继续低层读取。
- 多候选引用不自动 repair，交给工具校验失败。

### 8.2 任务失败率短期上升

把工具轮数耗尽从 completed 改成 failed 后，短期 smoke 可能暴露更多失败。

这是正确方向：失败应该显性化，否则 main-agent 会基于假 completed 继续错误编排。

### 8.3 与 LangGraph 的关系

这一步不是 LangGraph，但状态结构要可迁移：

```text
ChildStageExecutionState -> graph node state
next_allowed_tools -> conditional edge
AgentTaskRuntime completion validation -> node success criteria
```

先把阶段事实和完成判定做稳，再接 LangGraph 才有意义。

## 9. 结论

当前问题不是“再补一条 prompt”能解决的。

正确方向是把子 Agent 的阶段恢复从自然语言层提升到 runtime 执行层：

```text
guard 发现错误动作
  -> 返回可执行 next_allowed_tools
  -> AgentRuntime 收窄下一轮工具面
  -> 子任务 runtime 校验必需产物
  -> main-agent 只处理结构化完成/失败状态
```

这能同时解决质量、耗时和 token 膨胀问题，也给后续 LangGraph / workflow harness 留出清晰迁移路径。
