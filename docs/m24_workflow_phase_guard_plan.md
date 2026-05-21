# M24 求职流程阶段守卫方案

## 1. 背景

M24 已经验证过三类降本方向：

```text
ToolContextWindow compact
tool_search / schema reveal
workflow_rules sparse
```

live smoke 的结论比较清楚：

- `ToolContextWindow compact` 稳定，能明显降低历史 tool message 回放成本。
- `tool_search` 能降低 schema token，但会增加模型探索轮次，并且偶发阶段越界、漏产物。
- `workflow_rules sparse` 能降低规则 token，但当前会削弱主链路约束，出现缺 `JobFitReport` 但继续往下走的问题。

因此默认链路先回到稳定优先：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=full
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=full
```

下一步优化不再优先压缩 prompt，而是补一个确定性的“求职流程阶段守卫”。它要解决的问题是：

- 简历阶段不该越界做 JD 写入。
- JD 匹配阶段必须产出 `JDAnalysis + JobFitReport + CareerApplication`。
- 定制简历阶段必须产出 `ResumeVersion` 并合并到 `CareerApplication`。
- 同一阶段同一输入不要重复读、重复写、重复委派。
- 模型最终回答前，runtime 能发现关键产物缺失并阻止“文字完成、产品没完成”。

## 2. 核心原则

### 2.1 质量优先，降本其次

`tool_search` 和 sparse rules 可以保留为实验开关，但不能作为默认主链路，直到它们能稳定通过 full smoke。

### 2.2 阶段状态来自事实源

阶段是否完成，只能来自事实源：

```text
CareerProductStore
SessionArtifact
AgentTask
agent_result_summary
successful tool_result
events
```

不能依赖模型说“我已经完成”。

### 2.3 守卫不替代 main-agent

main-agent 仍然负责：

- 判断用户意图。
- 决定是否进入求职流程。
- 决定是否委派 child-agent。
- 组织最终回答。

阶段守卫只做确定性约束：

- 哪些动作当前阶段不该做。
- 哪些动作已经完成，可以复用。
- 哪些关键产物缺失，不能最终答复。
- 哪些参数可以安全修复。

### 2.4 不做定点补丁

不能根据某次 smoke 的具体标题、具体 ID、具体报错写规则。

规则必须基于业务语义：

```text
同一 resume artifact -> 一个 ResumeProfile
同一 JD artifact -> 一个 JDAnalysis
同一 resume_profile + jd_analysis -> 一个 JobFitReport
同一 application + jd_analysis -> 默认一个最终 ResumeVersion
```

## 3. 阶段定义

第一版只覆盖求职主链路。

### 3.1 resume_diagnosis

触发条件：

- 用户要求诊断简历、生成简历画像、分析已上传简历。

输入：

```text
resume artifact
```

允许产物：

```text
ResumeProfile
diagnosis artifact
CareerProfile merge
```

禁止或限制：

```text
不应保存 JDAnalysis
不应保存 JobFitReport
不应创建 CareerApplication
不应创建 ResumeVersion
```

完成条件：

```text
存在当前 session 的 ResumeProfile
ResumeProfile.source_artifact_id 指向当前 resume artifact
存在 diagnosis_artifact_id 或等价诊断 artifact
CareerProfile 至少完成一次 merge，或明确无可合并内容
```

### 3.2 jd_fit

触发条件：

- 用户要求分析 JD。
- 用户要求简历和 JD 匹配。
- 用户上传或粘贴 JD，并要求生成匹配报告。

输入：

```text
JD artifact
ResumeProfile
CareerProfile
```

允许产物：

```text
JDAnalysis
JobFitReport
match report artifact
CareerApplication
```

完成条件：

```text
存在当前 session 的 JDAnalysis
存在当前 session 的 JobFitReport
JobFitReport.source_artifact_id 指向 JD artifact
JobFitReport.report_artifact_id 指向报告 artifact
存在 CareerApplication
CareerApplication 关联 resume_profile_id / jd_analysis_id / job_fit_report_id
```

### 3.3 resume_version

触发条件：

- 用户要求生成定制简历。
- 用户要求基于某 JD 改简历。
- 用户要求为某求职项目生成版本。

输入：

```text
ResumeProfile
JDAnalysis
JobFitReport
CareerApplication
```

允许产物：

```text
ResumeVersion
resume version artifact
CareerApplication merge
```

完成条件：

```text
存在当前 session 的 ResumeVersion
ResumeVersion.base_resume_profile_id 指向当前 ResumeProfile
ResumeVersion.target_jd_analysis_id 指向当前 JDAnalysis
CareerApplication.resume_version_ids 包含该 ResumeVersion
```

### 3.4 application_action

触发条件：

- 用户围绕某求职项目继续操作，例如再生成一版、投递前检查、面试准备。

输入：

```text
CareerApplication
```

允许产物按动作决定。第一版只约束“再生成定制简历”：

```text
允许创建新的 ResumeVersion
必须 merge 回 CareerApplication
```

## 4. 阶段识别

阶段识别不靠复杂分类模型，第一版用确定性信号组合。

优先级：

```text
显式用户意图
  > 当前 active artifact 类型
  > 当前已有产品记录缺口
  > 最近 successful tool_result
```

建议新增：

```text
app/runtime/workflow/phase.py
```

核心结构：

```python
WorkflowPhase:
  name: str
  confidence: str
  input_refs: list[str]
  required_outputs: list[str]
  allowed_tool_groups: list[str]
  blocked_tool_names: list[str]
```

第一版不需要完美识别普通对话。普通对话没有明确求职阶段时，不启用阶段强约束。

## 5. 阶段守卫策略

守卫位置：

```text
AgentRuntime
  -> resolve tool calls
  -> WorkflowRuntimeGuard.inspect(...)
  -> allow / reuse / repair / block
  -> execute real tool only when needed
```

### 5.1 allow

工具符合当前阶段，且没有重复执行风险。

### 5.2 reuse

当前动作已经完成，返回 synthetic success result。

适用：

- 同一 resume artifact 重复保存 `ResumeProfile`。
- 同一 JD artifact 重复保存 `JDAnalysis`。
- 同一 resume_profile + jd_analysis 重复保存 `JobFitReport`。
- 同一求职项目重复创建 `CareerApplication`。
- 同一 run 内重复委派相同 child task。

返回必须包含：

```json
{
  "workflow_runtime_result": true,
  "policy": "reuse",
  "record_type": "job_fit_report",
  "record_id": "fit_xxx",
  "message": "已复用当前阶段已有产物，不需要重复执行。"
}
```

### 5.3 repair

模型传入的 ID 不存在，但当前 session 只有一个明确候选时，修复参数后继续执行。

适用：

- `resume_profile_id`
- `jd_analysis_id`
- `job_fit_report_id`
- `application_id`
- `resume_version_id`

限制：

- 多个候选时不能修复。
- 修复必须写入 `workflow_runtime_decision`，便于审计。

### 5.4 block

当前工具明显越界或会破坏阶段完整性时阻止。

第一版只 block 高风险动作：

- `resume_diagnosis` 阶段保存 `JDAnalysis` / `JobFitReport` / `CareerApplication`。
- `jd_fit` 阶段在缺 `JobFitReport` 时直接进入 `ResumeVersion`。
- `resume_version` 阶段重复创建同 intent 的 ResumeVersion，且用户没有要求“再生成一版”。
- 空内容创建 artifact。

block result 必须是成功的可恢复引导，不能作为失败工具污染 smoke：

```json
{
  "workflow_runtime_result": true,
  "policy": "block",
  "recoverable": true,
  "reason": "jd_fit_missing_job_fit_report",
  "next_action": "先保存 JobFitReport，再生成 ResumeVersion。"
}
```

## 6. 最终答复门禁

只靠工具前拦截不够，还需要在模型准备最终答复时检查阶段完成度。

建议在 `AgentRuntime` 即将写入 `assistant_message` 前增加：

```text
WorkflowCompletionGate.inspect_final_answer(...)
```

第一版只覆盖求职主链路。

### 6.1 resume_diagnosis 门禁

如果用户要求简历诊断，但缺 `ResumeProfile`：

```text
不能最终答复
引导继续调用 delegate_agents 或 career_resume_profile_save
```

### 6.2 jd_fit 门禁

如果用户要求匹配报告，但缺以下任意记录：

```text
JDAnalysis
JobFitReport
CareerApplication
```

不能最终答复。返回给模型的引导应说明缺什么，以及下一步最小工具动作。

### 6.3 resume_version 门禁

如果用户要求生成定制简历，但缺：

```text
ResumeVersion
CareerApplication merge
```

不能最终答复。

### 6.4 门禁不是死循环

门禁最多触发一次恢复轮。

如果恢复后仍缺产物，最终答复应明确告诉用户：

```text
本轮没有完成，缺少哪个产品记录，建议下一步重试哪个动作。
```

## 7. 与现有组件关系

### 7.1 与 `CareerFlowState`

`CareerFlowState` 给模型看短状态摘要。

`WorkflowPhaseGuard` 做确定性执行约束。

```text
CareerFlowState = 状态说明
WorkflowPhaseGuard = 状态保护
```

### 7.2 与 `ToolContextWindow`

`ToolContextWindow` 继续负责压缩历史工具消息。

阶段守卫产生的 synthetic result 也进入 tool observation，但应保持短小。

### 7.3 与 `tool_search`

`tool_search` 继续保留，但不是默认主链路。

只有当后续能满足以下条件，才重新考虑默认启用：

```text
连续多次 full smoke 通过
不出现阶段越界
不出现缺产品记录
总 token 明显低于 full schema + compact
```

### 7.4 与 sparse workflow rules

sparse rules 暂时作为实验项，不默认启用。

阶段守卫稳定后，可以重新尝试 sparse，因为到那时产品完整性由 runtime 保证，不再完全依赖规则注入。

### 7.5 与 LangGraph

阶段守卫不是 LangGraph，但结构要能迁移：

```text
WorkflowPhase -> graph node / route
required_outputs -> node completion condition
reuse/repair/block -> conditional edge
WorkflowCompletionGate -> graph checkpoint
```

## 8. 开发顺序

### 第一步：只读阶段快照

新增：

```text
app/runtime/workflow/phase.py
app/runtime/workflow/career_phase.py
tests/test_workflow_phase_guard.py
```

只做状态识别和缺口分析，不拦截工具。

### 第二步：工具前阶段守卫

扩展现有：

```text
app/runtime/workflow/guard.py
```

加入：

- 当前阶段允许工具判断。
- 同阶段重复产物 reuse。
- 高风险越界 block。

### 第三步：最终答复门禁

在 `AgentRuntime` 最终答复前加入一次 completion gate。

第一版只做同步路径；流式路径后续跟进，避免一次改动过大。

### 第四步：live smoke 验证

稳定配置：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=full
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=full
```

验证：

```text
runs=1 concurrency=1 max_tool_rounds=10 project-action=custom_resume
```

### 第五步：再评估降本开关

只有阶段守卫稳定后，再分别评估：

- `WORKFLOW_RULE_SELECTION_MODE=sparse`
- `TOOL_SCHEMA_DISCLOSURE_MODE=search`

不能两个同时开，否则难以定位质量退化来源。

## 9. 测试计划

### 9.1 单元测试

- 简历阶段调用 JD 工具被 block。
- JD 阶段缺 `JobFitReport` 时不能进入 ResumeVersion。
- 已有 `ResumeProfile` 时重复保存返回 reuse。
- 已有 `JDAnalysis` 时重复保存返回 reuse。
- 已有 `JobFitReport` 时重复保存返回 reuse。
- 单一候选 ID 可 repair，多候选不 repair。
- completion gate 能识别缺 `JobFitReport`。
- 普通聊天不启用阶段强约束。

### 9.2 集成测试

- main-agent 重复调用 `delegate_agents`，复用已有 task group。
- child-agent 重复创建同类诊断报告，最终只有一个诊断 artifact 引用。
- JD 匹配阶段必须创建 `JDAnalysis + JobFitReport + CareerApplication`。
- 定制简历阶段必须创建 `ResumeVersion` 并 merge 回 `CareerApplication`。

### 9.3 live smoke 指标

第一版目标不是极限降本，而是质量稳定：

```text
质量门禁通过
缺失产品记录 = []
failed_tools = []
resume_profiles = 1
jd_analyses = 1
job_fit_reports = 1
career_applications = 1
resume_versions >= 1
```

成本观察指标：

```text
message_tool 维持在 compact 后量级
重复 session_create_text_artifact 明显下降
重复 career_*_get/list 明显下降
provider_prompt_tokens 不高于当前 full + compact 基线
```

## 10. 风险与回滚

### 10.1 误拦截

如果用户明确说：

```text
重新分析
再生成一版
换一个风格
重新匹配
```

不能 block。应允许新 intent 或要求模型澄清。

### 10.2 恢复轮过多

completion gate 最多触发一次恢复轮，避免无限循环。

### 10.3 synthetic result 误导

所有 synthetic result 必须标记：

```text
workflow_runtime_result=true
policy=reuse|repair|block
source=WorkflowPhaseGuard
```

### 10.4 回滚方式

阶段守卫应有开关：

```text
WORKFLOW_PHASE_GUARD_MODE=off|observe|enforce
```

默认开发期：

```text
observe
```

验证稳定后：

```text
enforce
```

## 11. 结论

下一步不应该继续默认启用 `tool_search` 或 sparse rules。

正确顺序是：

```text
先稳定阶段完成度
再减少重复工具调用
再压缩提示词和 schema
最后考虑 LangGraph / harness
```

这能避免“token 降了，但产品记录缺了”的情况。当前主线优化目标是把求职流程从“模型自觉完成”升级为“runtime 保证完成”。 
