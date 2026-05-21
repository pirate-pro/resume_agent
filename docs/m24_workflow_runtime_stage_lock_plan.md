# M24 Workflow Runtime 阶段锁设计

> 状态说明：本文是早期阶段锁方案。经过 M24 多轮 live smoke 后，默认策略已调整为质量优先：
> `TOOL_SCHEMA_DISCLOSURE_MODE=full`、`TOOL_CONTEXT_WINDOW_MODE=compact`、`WORKFLOW_RULE_SELECTION_MODE=full`。
> 后续开发依据以 [M24 求职流程阶段守卫方案](m24_workflow_phase_guard_plan.md) 为准；`tool_search` 和 sparse workflow rules 暂作为实验开关，不作为默认主链路。

## 1. 背景

M23/M24 已经完成三类成本优化：

- `tool_search -> schema reveal`：减少一次性暴露全部工具 schema。
- `ToolContextWindow`：压缩同一 run 内历史 tool message。
- `workflow_rules sparse`：减少每轮固定规则注入。

这些优化有效，但最新 live smoke 暴露出更深的问题：

```text
模型仍可能重复委派 child-agent
模型仍可能重复保存同一份 JDAnalysis
模型仍可能重复创建同类报告 artifact
模型仍可能使用不存在的产品 id
模型可能在阶段已完成后继续低层 get/list/read
```

这些问题不能继续靠提示词或单点工具兜底修复。继续补提示会让系统变成：

```text
AGENT.md 一条规则
SKILL.md 一条规则
tool_search 一条规则
tool_context_window 一条规则
具体工具再补一条校验
```

这就是补丁化，后续很难维护，也很难解释为什么某个调用被允许或被拦截。

## 2. 核心原则

### 2.1 不再用提示词承担状态一致性

提示词只负责让模型理解目标和边界，不负责保证：

- 某阶段只执行一次。
- 某产品记录只保存一次。
- 某个 artifact 不重复创建。
- 某个产品 id 一定存在。

这些必须由 runtime / store / tool contract 提供确定性保障。

### 2.2 阶段完成态必须来自事实源

阶段是否完成，只能来自事实源：

```text
AgentTask
SessionArtifact
CareerProductStore
tool_result
agent_result_summary
events
```

不能来自模型自述的“我已经完成”。

### 2.3 拦截要按阶段语义做，不按失败样本做

不能写成：

```text
如果标题是“岗位匹配分析报告”就怎样
如果 query 里有 risk notes 就怎样
如果 live smoke run_003 失败就怎样
```

而应该写成：

```text
同一 run / 同一 application / 同一输入 artifact 下：
JDAnalysis 阶段完成后，不再重复保存 JDAnalysis
JobFitReport 阶段完成后，不再重复创建同类 report artifact
ResumeVersion 阶段完成后，不再重复创建 ResumeVersion
CareerApplication 已合并最终版本后，进入可答复态
```

## 3. 目标

新增轻量 `WorkflowRuntime` 阶段锁，先覆盖求职主链路，不做通用 DAG 引擎。

目标：

- 降低重复工具调用。
- 降低 tool pending message 和 tool schema 反复携带。
- 提升 live smoke 稳定性。
- 避免模型写入不存在的产品引用。
- 为后续 LangGraph / harness 迁移留下状态结构。

## 4. 非目标

本阶段不做：

- 不引入 LangGraph 依赖。
- 不做完整可视化流程编排器。
- 不把普通聊天强制纳入 workflow。
- 不替代 main-agent 的高层意图判断。
- 不取消 child-agent 自主执行。
- 不用 prompt 作为主要控制手段。

## 5. 阶段模型

第一版只定义求职链路的阶段：

```text
resume_diagnosis
  输入：resume artifact
  输出：ResumeProfile + diagnosis artifact + CareerProfile merge

jd_fit
  输入：JD artifact + ResumeProfile/CareerProfile
  输出：JDAnalysis + JobFitReport + report artifact + CareerApplication

resume_version
  输入：ResumeProfile + JDAnalysis + JobFitReport + CareerApplication
  输出：ResumeVersion + resume artifact + CareerApplication merge
```

阶段不是固定 DAG。main-agent 仍然决定是否进入某阶段，runtime 只在阶段已进入后提供确定性状态和拦截。

## 6. 状态结构

新增运行态结构，不直接替代 `CareerFlowState`，而是在其基础上提供更强的阶段锁。

```python
WorkflowRuntimeState
  session_id: str
  run_id: str
  workflow_type: "career"
  active_stage: str | None
  stages: list[WorkflowStageState]
  locks: list[WorkflowLock]
  final_answer_ready: bool
  next_allowed_actions: list[str]
  blocked_actions: list[str]
```

```python
WorkflowStageState
  stage_name: str
  status: "not_started" | "in_progress" | "completed" | "failed"
  input_refs: list[str]
  output_refs: list[str]
  completed_at: str | None
  completion_source: str
```

```python
WorkflowLock
  lock_key: str
  scope: "run" | "session" | "application"
  action: str
  idempotency_key: str
  existing_refs: list[str]
  policy: "reuse" | "block" | "repair" | "allow_new_if_user_requested"
```

## 7. 幂等键

幂等键必须来自业务语义，不来自自然语言标题。

### 7.1 ResumeProfile

```text
resume_profile
  key = session_id + source_resume_artifact_id
```

同一 session 同一简历 artifact，只保留一个 active ResumeProfile。

### 7.2 JDAnalysis

```text
jd_analysis
  key = session_id + source_jd_artifact_id
```

同一 JD artifact 已有 active JDAnalysis 后，重复保存应复用已有记录。

### 7.3 JobFitReport

```text
job_fit_report
  key = session_id + resume_profile_id + jd_analysis_id
```

同一简历画像和同一 JDAnalysis，只保留一个 active JobFitReport。报告 artifact 可更新，但产品记录不重复创建。

### 7.4 ResumeVersion

```text
resume_version
  key = session_id + resume_profile_id + jd_analysis_id + application_id + version_intent
```

默认 `version_intent=final_for_current_jd`。除非用户明确要求“再生成一版 / 另一个风格 / 第二版”，否则重复调用复用已有 ResumeVersion。

### 7.5 CareerApplication

```text
career_application
  key = session_id + jd_analysis_id + resume_profile_id
```

同一候选人画像和同一 JD，只对应一个求职项目。

## 8. Runtime 拦截策略

拦截发生在工具执行前，而不是模型调用后靠质量门禁发现。

```text
AgentRuntime
  -> resolve tool calls
  -> WorkflowRuntimeGuard.inspect(tool_call, context)
  -> allow / reuse / repair / block
  -> execute real tool only when needed
```

### 8.1 allow

工具调用符合当前阶段，且没有完成锁。

### 8.2 reuse

当前动作已经完成，runtime 返回一个成功的 synthetic tool result，内容指向已有记录。

示例：

```json
{
  "record_type": "jd_analysis",
  "record_id": "jd_analysis_001",
  "idempotent_reused": true,
  "workflow_lock": "jd_analysis:artifact_jd_live_001"
}
```

### 8.3 repair

模型传入不存在的 id，但当前 session 只有一个明确候选，runtime 修正参数后再执行。

适用：

- `target_jd_analysis_id`
- `resume_profile_id`
- `job_fit_report_id`
- `application_id`

修正必须写入 tool result，便于审计。

### 8.4 block

模型重复执行高风险动作，且无法安全复用或修正。

示例：

```json
{
  "blocked": true,
  "reason": "resume_version 已完成，除非用户明确要求新版本，否则不要再次创建。",
  "existing_resume_version_id": "resume_version_xxx",
  "next_action": "final_answer"
}
```

## 9. 与现有组件的关系

### 9.1 与 CareerFlowState

`CareerFlowState` 继续负责给模型看的短状态摘要。

`WorkflowRuntimeGuard` 负责执行前确定性拦截。

```text
CareerFlowState = 告诉模型现在是什么状态
WorkflowRuntimeGuard = 防止模型破坏状态
```

### 9.2 与 tool_search

`tool_search` 只负责发现工具和 schema reveal。

它不负责判断某阶段是否已完成，也不负责阻止重复调用。

### 9.3 与 ToolContextWindow

`ToolContextWindow` 只负责压缩上下文。

它可以展示 workflow lock 结果，但不承担业务状态机职责。

### 9.4 与工具层校验

工具层仍保留基础校验：

- id 格式。
- artifact 是否属于当前 session。
- store-owned 字段禁止传入。
- evidence_refs 格式。

但跨记录完成态和阶段幂等由 runtime guard 统一处理。

### 9.5 与 LangGraph

这一步不是接入 LangGraph，但状态结构要可迁移：

```text
WorkflowRuntimeState -> graph state
WorkflowStageState -> node state
WorkflowLock -> checkpoint / barrier
allow/reuse/repair/block -> conditional edge
```

## 10. 实施顺序

### 第一步：文档和验收指标

完成本文档，明确不再继续补丁化。

### 第二步：只读状态提取

新增：

```text
app/runtime/workflow/
  state.py
  career_state.py
```

只从现有事实源提取状态，不拦截工具。

### 第三步：Guard 干跑模式

新增：

```text
WorkflowRuntimeGuard.inspect(...)
```

先只记录：

- 哪些工具本可复用。
- 哪些工具本可修正。
- 哪些工具本应阻止。

不改变执行结果。

### 第四步：低风险复用

先启用 `reuse`：

- 重复 JDAnalysis 保存。
- 重复 ResumeProfile 保存。
- 重复 CareerApplication 创建。

### 第五步：参数修正

启用 `repair`：

- 单一当前 JDAnalysis。
- 单一当前 ResumeProfile。
- 单一当前 JobFitReport。
- 单一当前 CareerApplication。

### 第六步：完成态阻止

启用 `block`：

- ResumeVersion 已创建并已 merge 后，不允许重复创建。
- JobFitReport 已保存后，不允许重复保存同一匹配报告。
- 已完成阶段不允许重复 `delegate_agents`，除非用户明确要求重新分析。

### 第七步：live smoke 验证

分两类验证，不能混在一起看：

质量基线验证使用稳定配置：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=full
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=full
```

成本验收验证使用低成本配置：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
```

`search + sparse` 只有在阶段锁已经能阻止越界、缺产物和重复创建后才作为产品目标配置。否则虽然 token 会低，但质量风险会重新出现。

## 11. 测试计划

### 单元测试

- 已有 JDAnalysis 时重复保存返回 `idempotent_reused`。
- 已有 JobFitReport 时重复保存返回已有记录。
- 已有 ResumeVersion 且用户未要求新版时，重复创建被 block。
- 传入不存在的 `target_jd_analysis_id`，当前 session 唯一 JDAnalysis 时 repair。
- 多个候选记录时不 repair，返回明确错误或继续原工具校验。
- 普通聊天不创建 WorkflowRuntimeState。

### 集成测试

- 构造 main-agent 连续重复调用同一工具，runtime 不重复写文件或产品记录。
- 构造 child-agent 重复创建报告 artifact，runtime 复用或更新同一业务产物。
- 构造错误 id 进入 `career_resume_version_create`，最终 ResumeVersion 指向真实 JDAnalysis。

### live smoke 指标

目标：

```text
质量门禁通过
artifact_count <= 5
career_jd_analysis_save <= 1
career_job_fit_report_save <= 1
career_resume_version_create <= 1
同一阶段 delegate_agents <= 1
低成本配置下 provider_prompt_tokens 接近或低于 180k
tool_pending_message 不再随重复调用膨胀
```

## 12. 风险控制

### 12.1 误拦截用户明确要求

如果用户明确说：

```text
重新分析
再生成一版
换一种风格
覆盖之前版本
```

runtime 不应直接 block，而应允许新版本或要求模型确认覆盖语义。

### 12.2 repair 修错

只在“当前 session 唯一候选”时 repair。

如果有多个候选，必须返回可解释错误，让模型调用 list/get 确认。

### 12.3 synthetic result 误导模型

synthetic result 必须明确标记：

```text
workflow_runtime_result=true
policy=reuse|repair|block
source=WorkflowRuntimeGuard
```

这样调试面板和 live smoke 可以区分真实工具执行和 runtime 复用。

## 13. 验收结论

这一步的价值不是再少几千 token，而是把主链路从“靠模型自律”升级为“runtime 有边界”。

后续如果继续复杂化，再接 LangGraph 才是顺滑的：

```text
先有确定性状态
再有阶段锁
再有节点化 workflow
最后迁移到 LangGraph / harness
```

不能反过来先接框架，再把当前补丁散落进去。

## 14. r16/r17 验证结论

r16 暴露了一个重要问题：`job_fit_report_artifact_candidate_facts_conflict` 能阻止错误报告 artifact 落地，但如果只返回“重新生成报告”，模型会继续读取简历/JD、反复 get/list，再多次重写报告，导致 `job_agent` token 和耗时明显膨胀。

因此阶段锁不能只做“拦截”，还必须给出阶段内重试边界：

- 第一次发现匹配报告正文把 JD 要求误写成候选人已有能力时，阻止创建 artifact。
- 返回 `supported_candidate_facts` 和 `unsupported_candidate_facts`，让模型知道可以写什么、不能写什么。
- 在同一 run 中，如果还没有合法的匹配报告 artifact，后续低层 `read/get/list` 统一被拦截，只允许重新生成合法报告。
- 合法报告 artifact 创建后，后续低层读取/重写继续被拦截，下一步只能保存 `JobFitReport`。

r17 验证结果：

```text
data_dir: data/live_career_smoke_m24_phase_guard_lowcost_r17/run_001
session_id: sess_live_career_001_16a56e5f
结果: 通过
总耗时: 157.54s
total_tokens: 162,437
prompt_tokens: 150,939
completion_tokens: 11,498
artifact_count: 5
career_jd_analysis_save: 1
career_job_fit_report_save: 1
career_resume_version_create: 1
质量门禁: 通过
```

对比 r16：

```text
r16 total_tokens: 275,645
r17 total_tokens: 162,437

r16 job_agent: 123,213 tokens / 20 tool calls
r17 job_agent: 46,280 tokens / 8 tool calls
```

结论：阶段锁的方向成立，但 guard 的输出不能只表达“禁止”，必须表达“当前阶段只剩哪一个可执行动作”。这比继续增加提示词更稳定，也更接近后续 LangGraph / harness 的节点状态思想。

## 15. r18-r21 优化实验结论

在 r17 通过后，尝试过三类进一步降 token 方案：

```text
1. focused tool reveal
   把 tool_search 后的 schema 从“累计揭示”改成“只保留最近一次搜索结果”。

2. 更激进的 product tool compact
   进一步压缩 career get/save/merge 返回给模型的 tool message。

3. 定制简历阶段工具包收窄
   减少 career_resume_version / career_application 相关 schema 暴露。
```

验证结果不理想：

```text
r18: 失败，耗时 297.43s
原因：focused reveal 触发多次 tool_search，JD 阶段和定制简历阶段重复重试。

r19: 失败，耗时 234.07s
原因：delegate_agents.artifact_refs 混入 resume_profile/career_profile 产品 id，工具拒绝。

r20: 通过，耗时 244.90s
问题：总 token 和 main-agent 调用轮次显著高于 r17。

r21: 失败，耗时 283.95s
原因：子任务/中间步骤触发工具调用轮次上限。
```

最终处理：

- 撤回 `focused tool reveal`，继续使用 `cumulative_search`。
- 撤回更激进的 product compact 限制，保留原有 compact 视图。
- 撤回定制简历阶段工具包收窄，避免模型因为缺少 schema 反复搜索。
- 保留 `delegate_agents.artifact_refs` 修正：如果模型把 `resume_profile_*`、`career_profile_*` 等产品 id 放进 `artifact_refs`，runtime 会把它们移出 `artifact_refs`，并保留在 instruction 中；文件名/路径类非法引用仍然让工具拒绝。

结论：当前阶段继续压缩 schema 或 tool result 的收益不稳定，容易损伤模型执行判断。下一步更应该做“完成态早停 / 阶段动作许可”：

```text
阶段事实源已经显示完成时：
- 不再允许重复 delegate_agents。
- 不再允许重复 get/list/read 只是为了确认状态。
- 不再允许重复 create/merge 已完成产物。
- runtime 直接返回 next_action=final_answer。
```

这条路线比继续压缩上下文更接近核心矛盾：不是模型不知道工具少一点，而是模型缺少确定性的“已经完成，可以答复”边界。

## 16. 完成态早停开发方案

### 16.1 背景

r18-r21 说明继续压缩 schema 或 tool result 不稳定。真正的问题是：事实源已经完成阶段后，main-agent 仍可能继续做低层确认动作，例如：

```text
重复 delegate_agents
重复 get/list/read
重复 create/merge 已完成产物
重复 tool_search 寻找已经可见或已经不需要的工具
```

这些动作会增加 token、耗时和失败概率，但对最终产品记录没有新增价值。

### 16.2 目标

在 `WorkflowRuntimeGuard` 中增加 main-agent 完成态早停：

```text
JD 匹配阶段完成:
  已存在同一 session 下 active JDAnalysis + JobFitReport + CareerApplication
  后续重复 delegate/read/get/save/create/status -> block
  next_action=final_answer

定制简历阶段完成:
  已存在同一 session 下 active ResumeVersion
  且 CareerApplication.resume_version_ids 已包含该版本
  后续重复 read/get/create/merge -> block
  next_action=final_answer

简历诊断阶段完成:
  已存在 active ResumeProfile + CareerProfile
  后续重复 delegate/read/profile_get -> block
  next_action=final_answer
```

### 16.3 非目标

本阶段不做：

- 不改 tool schema reveal 策略。
- 不继续压缩 product tool result。
- 不引入 LangGraph。
- 不把普通聊天纳入 workflow。
- 不阻止用户明确要求“重新分析 / 再生成一版 / 覆盖”的动作。

### 16.4 拦截原则

只在 main-agent 生效，child-agent 仍按已有子任务阶段锁执行。

只在事实源完成时拦截，不基于模型自述：

```text
CareerProductStore
SessionArtifact
AgentTask result events
tool_result
```

拦截返回 synthetic tool result：

```json
{
  "workflow_runtime_result": true,
  "policy": "block",
  "reason": "career_stage_complete_final_answer",
  "next_action": "本阶段产品记录已完成，直接给用户最终答复。",
  "completed_refs": [...]
}
```

### 16.5 验收指标

使用同一 live smoke 配置：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
```

目标：

```text
质量门禁通过
artifact_count = 5
career_jd_analysis_save <= 1
career_job_fit_report_save <= 1
career_resume_version_create <= 1
career_application_merge <= 1
delegate_agents 在已完成阶段不重复
total_tokens 接近或低于 r17 的 162,437
```

### 16.6 r22-r27 验证结论

本轮实际开发后连续跑了 r22-r27。结论是：

```text
r22: 失败
  结果记录齐全，质量门禁通过，但第一次 career_resume_version_create 因虚构邮箱和未证实技术栈被真实工具拒绝。

r23: 失败
  ResumeVersion 真实工具失败已消失，但简历诊断阶段触发工具轮次上限。
  原因：半完成态把 career_resume_profile_get 也拦掉，main-agent 拿不到 ResumeProfile 正文后反复读取 artifact。

r24: 失败
  简历诊断阶段恢复，但 job_agent 的岗位匹配报告被事实护栏误伤，多次无法创建 report artifact。
  原因：把“是否具备向量检索 / 需确认 / 可能影响面试”等风险问题误判为候选人已有事实声明。

r25/r26: 失败
  JD 阶段恢复，但 ResumeVersion 预执行事实护栏导致 main-agent 反复重试，最后没有创建 ResumeVersion。
  结论：ResumeVersion 预检 block 不能保留。success=true 的 synthetic block 容易让模型误判“已创建”，即使文案强调未创建也不稳定。

r27: 通过
  elapsed=191.62s
  total_tokens=192,531
  prompt_tokens=177,455
  completion_tokens=15,076
  LLM calls=34
  artifact_count=5
  质量门禁通过
```

r27 与 r17 对比：

```text
r17 total_tokens=162,437, LLM calls=29, schema_sum=280, schema_max=13
r27 total_tokens=192,531, LLM calls=34, schema_sum=328, schema_max=15

agent_main:
  r17=96,689
  r27=125,661

job_agent:
  r17=46,280
  r27=40,007

resume_agent:
  r17=19,468
  r27=26,863
```

本轮保留：

- main-agent 阶段完成态早停。
- 简历诊断半完成态允许 `career_resume_profile_get`，但仍阻止重复委派和重复读取原文。
- job_fit_report artifact 护栏的风险/问题语句识别修正：`是否 / 确认 / 可能 / 影响 / 薄弱` 等不再被误判为候选人已有事实。
- block synthetic result 增加 `tool_executed=false`、`result_created=false`，避免调试和模型上下文把 block 当真实执行。
- ResumeVersion schema / workflow rule 增加“正文只放可投递简历，不放匹配说明、风险表、差距表”的产品边界。

本轮撤回：

- `ResumeVersion` 预执行 candidate facts block。

原因：它把真实工具失败变成了 runtime block，但没有降低总轮次，反而让模型陷入重试和查询空记录。ResumeVersion 的事实校验应继续由工具执行；后续如果要进一步降低失败率，应该改“生成前上下文和模板”，而不是在 guard 里对大段 Markdown 做事实修剪。

当前判断：

```text
这轮完成了质量回归，但没有完成 token 降低目标。
token 增长主要来自 main-agent 调用次数和工具 schema 累计暴露增长，而不是 memory。
下一步不应继续加 guard block；应回到 context/tool 编排层，减少低价值 session_read_artifact、重复 tool_search 和最终阶段 get/list 确认。
```

## 17. r38-r44 工具目录压缩与 runtime plan 保留

### 17.1 有效优化：search 模式工具目录压缩

r38 的 token 拆分显示，`TOOL_SCHEMA_DISCLOSURE_MODE=search` 虽然隐藏了完整工具 schema，但 system prompt 里仍然每轮注入当前 agent 的完整工具名称和描述。

本轮将 search 模式的 `tool_catalog` 从“完整工具清单”改为：

```text
当前可见工具 schema
能力分组摘要
tool_search 使用规则
```

full 模式保持原样，作为调试和回退路径。

验证结果：

```text
r38:
  total_tokens=190,498
  prompt_tokens=174,558
  LLM calls=34
  tool_catalog section=23,346

compact_catalog_r1:
  total_tokens=155,454
  prompt_tokens=141,883
  LLM calls=28
  tool_catalog section=9,125
  artifact_count=5
  质量门禁通过
```

结论：这条优化有效，且没有降低主链路质量。

### 17.2 撤回优化：压缩 AGENT.md

尝试压缩 main/resume/job 三个 `AGENT.md` 后，静态 `agent_identity` token 有下降，但 child-agent 调用轮次显著上升，尤其是 `job_agent`：

```text
compact_catalog_r1:
  total_tokens=155,454
  job_agent calls=6

compact_agent_docs_r4:
  total_tokens=195,228
  job_agent calls=12
```

结论：当前阶段不压缩 AGENT.md。AGENT.md 里的约束虽然看起来重复，但对 child-agent 一次性完成产品记录仍有稳定作用。后续如果要减少这部分成本，应该先把 child-agent 的任务模板和工具结果契约做得更确定，而不是直接删身份文档。

### 17.3 有效修复：tool_search 不得清空 pending runtime plan

r41 暴露了一个 runtime 问题：

```text
context runtime plan 已要求 career_resume_version_create
模型中途调用 tool_search 搜索 artifact 读取能力
该 tool_search 结果没有 runtime_plan_applied
AgentRuntime 仍把 pending_runtime_plan 覆盖为 None
模型随后可以提前最终答复，导致缺 ResumeVersion
```

修复策略：

```text
tool_search 返回 runtime plan 时才合并 pending plan
tool_search 没有 runtime plan 时，只更新 revealed tools，不清空已有 required_tools
如果 incoming plan 比 current plan 更弱，保留更严格的 required_tools
```

新增回归：

```text
test_runtime_tool_search_without_runtime_plan_keeps_pending_required_tool
```

### 17.4 有效修复：CareerApplication stage 自然语言归一化

连续 live smoke 中模型传入：

```text
stage=resume_tailoring
stage=tailoring
stage=定制简历完成
```

这些表达语义上都表示“定制简历已完成，可进入投递准备”，但不属于产品枚举。

修复策略：

```text
精确别名：resume_tailoring / tailoring / custom_resume 等 -> ready_to_apply
自然语言归一化：包含“简历/定制/生成/完成/可投递”等表达 -> ready_to_apply
未知 stage 仍然拒绝，不静默写入脏数据
```

新增回归：

```text
test_career_application_merge_accepts_resume_stage_aliases
```

### 17.5 最新验证

```text
stage_normalize_r1:
  结果: 通过
  elapsed=225.24s
  total_tokens=193,618
  prompt_tokens=174,792
  completion_tokens=18,826
  LLM calls=33
  artifact_count=6
  质量门禁通过
```

这说明产品质量已恢复，但 token 又回升。主要原因不是工具目录压缩失效，而是本轮 live smoke 中 `job_agent` 重复保存/读取：

```text
job_agent calls=13
career_jd_analysis_save=2
session_create_text_artifact=4
career_profile_get=2
career_resume_profile_get=2
```

下一步不继续压缩 AGENT.md，应该处理 child-agent 阶段内幂等与输出 artifact 复用：

```text
JDAnalysis 已保存后，job_agent 不应重复 save
JobFitReport report artifact 已创建后，不应重复 create_text_artifact
child-agent 读过 resume_profile/career_profile 后，不应反复 get
```

### 17.6 有效修复：JDAnalysis 与匹配报告 artifact 边界

`stage_normalize_r1` 的主要浪费来自 `job_agent` 在 JD 匹配阶段先多次生成 `JD分析报告.md`，之后才生成真正的岗位匹配报告。这里的根因不是单个工具调用错误，而是产品边界不够硬：

```text
JDAnalysis = 产品结构化记录
JobFitReport.report_artifact_id = 用户可预览的匹配报告 artifact
```

修复策略：

```text
delegate_agents 修正 job_agent 子任务：
  如果任务包含 JobFitReport / 匹配报告语义，追加输出边界：
  不要为 JDAnalysis 单独创建用户可见 artifact；
  只生成一个用户可预览的岗位匹配报告 artifact。

WorkflowRuntimeGuard 执行前拦截：
  job_agent 当前任务需要 JobFitReport 时，
  如果 session_create_text_artifact 的产物被识别为 JD 分析报告，
  直接返回 synthetic block，要求继续生成岗位匹配报告 artifact。

保留例外：
  如果子任务只是“只分析 JD / 保存 JDAnalysis”，不拦截 JD 分析 artifact。
```

新增回归：

```text
test_child_job_agent_blocks_separate_jd_analysis_artifact_when_fit_report_required
test_child_job_agent_allows_jd_analysis_artifact_when_fit_report_not_required
test_delegate_agents_jd_fit_task_gets_single_report_artifact_boundary_without_profiles
```

验证结果：

```text
child_job_artifact_guard_r1:
  结果: 通过
  elapsed=219.44s
  total_tokens=174,103
  prompt_tokens=156,184
  completion_tokens=17,919
  LLM calls=30
  artifact_count=5
  career_jd_analysis_save=1
  career_job_fit_report_save=1
  质量门禁通过
```

注意：token 统计只应读取 session 根 `events.jsonl`，不要同时把 `agents/*/events.jsonl` 加总。后者是同一批事件的 agent 视图副本，同时相加会把 174k 误算成 348k。

当前剩余问题：

```text
session_create_text_artifact 仍出现 5 次，其中 job_agent 有一次无效报告拦截和一次复用拦截
按根 events 统计：agent_main calls=16，resume_agent calls=4，job_agent calls=10
下一步应该优化 child-agent 的工具调用顺序和报告质量门禁，减少无效报告重写，而不是继续压缩 AGENT.md
```

### 17.7 有效修复：报告生成合同与 content 参数压缩

`child_job_artifact_guard_r1` 中 `job_agent` 还有两类浪费：

```text
先生成候选人事实冲突的匹配报告，被 WorkflowRuntimeGuard 拦截
随后模型把历史 tool_call 中的 content_chars 当成参数传回，触发 empty_content
```

修复策略：

```text
delegate_agents 修正 job_agent 子任务时，追加报告生成合同：
  已匹配项只能来自 supported_candidate_facts
  JD 未覆盖要求只能写入 gaps / 风险 / 建议 / 待确认
  session_create_text_artifact 必须传完整 Markdown content
  不要传 content_chars / content_omitted / 占位正文
  artifact 创建成功后立即保存 JobFitReport，不要重写报告

ToolContextWindow 压缩历史 tool_call 参数时：
  不再把 content 改写成 content_chars
  改成 content_omitted: {chars: N}
```

这样做的原因是 `content_chars` 看起来像工具 schema 参数，模型容易照抄。`content_omitted` 明确表达“这是历史内容省略说明”，不会被误认为可调用字段。

新增回归：

```text
test_child_job_agent_blocks_match_report_artifact_without_content_field
test_compact_window_summarizes_failed_long_content_arguments_for_repair
```

验证结果：

```text
job_contract_r1:
  结果: 通过
  elapsed=240.13s
  total_tokens=182,877
  prompt_tokens=165,412
  completion_tokens=17,465
  LLM calls=32
  artifact_count=5
  job_agent calls=6
  career_jd_analysis_save=1
  career_job_fit_report_save=1
  质量门禁通过
```

结论：

```text
job_agent 从上一轮 10 calls 降到 6 calls，目标达成
总 token 未下降，原因转移到 agent_main 在阶段中间反复 tool_search / 尝试错误动作
```

### 17.8 撤回优化：部分完成态直接拦截 tool_search

尝试把 `tool_search` 加入以下部分完成态 block：

```text
resume_profile_ready_career_profile_missing -> 只允许 career_profile_merge
fit_ready_application_missing -> 只允许 career_application_create
version_ready_application_merge_missing -> 只允许 career_application_merge
```

验证结果：

```text
main_stage_tool_search_guard_r1:
  结果: 失败
  失败原因: tool_search 被拦截后，模型知道下一步应该调用 career_application_create，
            但没有拿到 career_application_create schema，最终只输出文字说明，没有真正创建 CareerApplication
```

结论：

```text
不能简单拦截 tool_search
后续要处理的是“阶段守卫结果如何触发 schema reveal”
也就是 block/reuse/repair 结果需要能携带 runtime tool plan，
让下一轮直接暴露 next_allowed_tools 的 schema
```

本次撤回该优化，只保留：

```text
job_agent 报告生成合同
content_omitted 参数压缩
JDAnalysis / JobFitReport artifact 边界
```

### 17.9 再次复盘：保留 schema reveal 能力，撤回 tool_search 部分态拦截

在 `main_stage_tool_search_guard_r1` 之后补了一次 runtime schema reveal：

```text
WorkflowRuntimeGuard 的 block / reuse / repair 结果只要携带 next_allowed_tools，
AgentRuntime 就会把这些工具 schema 加入下一轮可见工具。

这个逻辑对普通工具和 tool_search 自身都生效。
```

验证结论：

```text
guard_schema_reveal_r1:
  schema reveal 已经生效
  career_profile_merge / career_application_create / career_application_merge 都能按 next_allowed_tools 暴露
  但模型在 schema 已经可见后仍反复调用 tool_search
  resume_diagnosis 和 resume_version 阶段都触发了 schema search limit
```

因此问题不是“schema 没暴露”，而是“把 tool_search 放进部分完成态 block 会诱发搜索重试”。这条策略不稳定，已撤回：

```text
fit_ready_application_missing 不再拦截 tool_search
version_ready_application_merge_missing 不再拦截 tool_search
resume_profile_ready_career_profile_missing 不再拦截 tool_search
```

保留的有效能力：

```text
WorkflowRuntimeGuard 结果仍可以触发 runtime schema reveal
tool_search 本身仍作为搜索即披露入口
最终完成态仍可以拦截 tool_search，避免阶段已经终止后继续搜索
```

这次失败还暴露了另一个确定性问题：main-agent 委派 `job_agent` 时，指令里可能残留伪造或陈旧产品 id，例如：

```text
career_profile_facts
resume_profile_stale
```

修复策略：

```text
只在 JD 匹配阶段
只针对 job_agent 委派任务
只在当前 session 存在唯一 active ResumeProfile 和唯一 active CareerProfile 时
把 instruction 中的 resume_profile_* / career_profile_* 引用替换为真实当前记录 id
不替换 resume_profile_id / career_profile_id 这些字段名
```

新增回归：

```text
test_delegate_agents_jd_fit_replaces_stale_profile_ids_in_instruction
```

最新本地验证：

```text
uv run pytest tests/test_workflow_runtime_guard.py tests/test_tool_context_window.py tests/test_tool_result_view.py tests/test_agent_runtime.py tests/test_career_tools.py::test_career_application_merge_accepts_resume_stage_aliases tests/test_context_assembler.py -q
uv run mypy app/runtime/workflow/guard.py app/runtime/agent_runtime.py tests/test_workflow_runtime_guard.py tests/test_agent_runtime.py
```

### 17.10 验证结果：delegate ref repair 后 live smoke 通过

验证命令：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
uv run python tools/smoke_career_live_flow.py --runs 1 --concurrency 1 --max-tool-rounds 10 --project-action custom_resume --data-dir data/live_career_smoke_m24_delegate_ref_repair_r1 --quiet
```

结果：

```text
delegate_ref_repair_r1:
  结果: 通过
  elapsed=204.40s
  质量门禁: 通过
  artifact_count=5
  career_applications=1
  career_profiles=1
  jd_analyses=1
  job_fit_reports=1
  resume_profiles=1
  resume_versions=1
```

按 session 根 `events.jsonl` 统计 token，不把 agent 子目录副本重复相加：

```text
LLM calls: 26
total_tokens: 148,213
prompt_tokens: 131,961
completion_tokens: 16,252

system_prompt_estimate_tokens: 65,816
tools_estimate_tokens: 26,584
messages_estimate_tokens: 39,604
workflow_rules_estimate_tokens: 6,798
tool_pending_message_estimate_tokens: 19,632
tool_state_message_estimate_tokens: 4,892
```

按 agent：

```text
agent_main:   82,992 tokens / 14 calls
resume_agent: 31,394 tokens / 7 calls
job_agent:    33,827 tokens / 5 calls
```

结论：

```text
fake product id 问题未复现：没有 career_profile_facts / stale profile id / Profile not found
schema search limit 未复现
总 token 低于上一轮 174k / 182k，通过链路更稳
```

残留 warning：

```text
第一次 career_resume_version_create 尝试把 vector_search 写进定制简历，
被 ResumeVersion 事实边界拒绝，随后模型恢复并生成成功版本。
```

这说明当前事实边界是有效的，但 resume_version 阶段仍有一次可优化的无效写入。后续优化不应再从 `tool_search` 硬拦截切入，而应处理：

```text
ResumeVersion 写作上下文中“可写入候选人事实”的表达
career_resume_version_create 失败后的恢复成本
agent_main 在定制简历阶段的 tool pending message 增长
```

### 17.11 高并发 live smoke 暴露的问题

验证命令：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
uv run python tools/smoke_career_live_flow.py --runs 6 --concurrency 3 --max-tool-rounds 10 --project-action custom_resume --data-dir data/live_career_smoke_m24_high_concurrency_r1 --quiet
```

结果：

```text
runs=6
concurrency=3
success=2
failed=4
avg_elapsed=230.34s
max_elapsed=294.56s
```

按 session 根 `events.jsonl` 统计，不把 agent 子目录重复相加：

```text
run_001: 245,846 tokens / 44 calls / failed
run_002: 159,120 tokens / 29 calls / passed
run_003: 213,921 tokens / 35 calls / failed
run_004: 204,292 tokens / 33 calls / failed
run_005: 191,076 tokens / 30 calls / passed
run_006: 187,148 tokens / 33 calls / failed
total: 1,201,403 tokens
```

这轮没有暴露明显的数据竞争：

```text
通过和失败 run 中，核心产品记录没有跨 session 串写
大多数失败 run 中 JDAnalysis / JobFitReport / CareerApplication 仍然保持 1 条
artifact 没有并发写入损坏
```

主要失败根因：

```text
1. ResumeVersion 失败恢复不稳
   run_001 中第一次因 unsupported candidate tech facts 被拒绝后，
   第二次把历史压缩字段 content_omitted / content_preview 当成输入，
   触发 career_resume_version_create requires either content or artifact_id。
   第三次恢复成功，但 smoke 仍把失败工具计入失败。

2. ResumeVersion 创建后未稳定合并 CareerApplication
   run_003 已成功创建 ResumeVersion，
   但最后一轮才通过 tool_search 暴露 career_application_merge，
   随后达到工具轮次上限，导致项目动作未回写 CareerApplication。

3. Pending runtime plan 被模型忽略后仍允许最终答复
   run_004 中 JDAnalysis 和 JobFitReport 已完成，
   runtime plan 明确要求 career_application_create。
   模型连续两次提前最终答复，当前逻辑提醒两次后放行，
   最终缺少 CareerApplication。

4. 项目动作阶段出现 schema search 空转
   run_006 的项目动作一开始缺少 ResumeVersion，
   runtime next_allowed_tools 包含 career_resume_version_create，
   但模型连续搜索 career_application_merge / update application，
   最终触发 schema search limit，ResumeVersion 未创建。

5. CareerProfile merge 仍有无效字段
   run_006 曾传入 preferred_industries_note，
   工具拒绝后模型修正成功，但 smoke 仍记录失败工具。
```

结论：

```text
高并发不是主要问题，主要问题是单条链路在压力下更容易走到恢复分支。
下一步不应该做新功能，也不应该继续压 prompt。
优先修 WorkflowRuntime 对“必需下一步工具”的执行约束和 ResumeVersion 失败恢复。
```

建议修复顺序：

```text
1. Runtime plan hard pending：
   如果 required_tools 已可见，模型仍最终答复，不再两次提醒后放行。
   应继续要求调用 required_tools，或返回明确 workflow incomplete。

2. ResumeVersion 成功后直接推进 application merge：
   career_resume_version_create 成功后，如果当前 session 有唯一 CareerApplication，
   pending runtime plan 应立即要求 career_application_merge，
   避免再靠 tool_search 找 merge 工具。

3. ResumeVersion retry 输入清理：
   career_resume_version_create 前置 guard 拦截 content_omitted / content_preview 但缺少 content 的调用，
   返回可恢复 synthetic block，要求用完整 content 或 artifact_id，不让工具报硬失败。

4. CareerProfile merge 字段净化：
   对 updates 中不允许字段做工具层明确失败前的可解释过滤或 repair，
   但必须保留审计，不静默吞字段。
```

### 17.12 高并发修复迭代记录

本轮按“先压测、再定点归因、再修确定性边界”的方式推进，期间跑了多批 high concurrency smoke。

#### r2：第一批修复后的高并发结果

命令：

```text
uv run python tools/smoke_career_live_flow.py --runs 6 --concurrency 3 --max-tool-rounds 10 --project-action custom_resume --data-dir data/live_career_smoke_m24_high_concurrency_r2 --quiet
```

结果：

```text
success=5
failed=1
avg_elapsed=207.47s
max_elapsed=283.36s
root total_tokens=1,151,686
```

注意 token 口径：`events.jsonl` 在 session 根目录和 agent 子目录各有一份，不能重复相加。重复相加会得到约 `2,303,372`，这是统计口径错误。

按 root 口径拆分：

```text
agent_main:   716,893
job_agent:    319,159
resume_agent: 115,634

system_prompt_estimate_tokens: 502,716
messages_estimate_tokens:      356,370
tools_estimate_tokens:         203,741
tool_pending_message_tokens:   164,490
workflow_rules_tokens:          52,873
```

r2 只剩一个失败：`ResumeVersion` 已创建，但模型连续 `tool_search`，没有执行已可见的 `career_application_merge`，最后被 runtime 拦在 workflow incomplete。

#### r3：错误修法

曾尝试在 pending runtime plan 下“只暴露必需工具”，结果：

```text
success=0
failed=6
```

失败原因很清楚：创建 ResumeVersion 前，模型仍需要读取 `career_application_get / career_resume_profile_get / career_job_fit_report_get` 等上下文工具。只暴露 `career_resume_version_create` 会让模型无法取正文事实，开始调用隐藏工具并空转。

结论：不能把工具面收得过窄。正确策略是：

```text
保留已揭示的业务工具
只在 required tool 已可见时隐藏 tool_search
```

#### r4：工具面修正后的小批次

命令：

```text
uv run python tools/smoke_career_live_flow.py --runs 3 --concurrency 3 --max-tool-rounds 10 --project-action custom_resume --data-dir data/live_career_smoke_m24_high_concurrency_r4 --quiet
```

结果：

```text
success=1
failed=2
avg_elapsed=236.87s
max_elapsed=269.11s
```

这轮 schema search 空转不再是主因，失败集中到 CareerApplication 数据边界：

```text
run_001: career_application_merge 传入非法 stage: resume_version_created / resume_customized
run_002: CareerApplication 中出现“待补”类占位表达，质量门禁失败
```

已修复：

```text
career_application_merge 支持 resume_version_created / resume_customized 等阶段别名，归一到 ready_to_apply
career_application_create / merge 对 summary、notes、next_actions、risks 做占位表达清洗
```

#### r5：数据边界修复后的小批次

命令：

```text
uv run python tools/smoke_career_live_flow.py --runs 3 --concurrency 3 --max-tool-rounds 10 --project-action custom_resume --data-dir data/live_career_smoke_m24_high_concurrency_r5 --quiet
```

结果：

```text
success=2
failed=1
avg_elapsed=238.99s
max_elapsed=303.12s
```

r4 的两个问题未复现。剩余失败集中在 ResumeVersion 失败恢复：

```text
第一次 career_resume_version_create 写入了源简历不存在的联系方式和技术词，被事实边界拒绝
第二次调用只传 content_omitted / content_preview，没有完整 content
runtime 正确阻止了压缩内容进入工具，但模型误以为 synthetic block 等于创建成功
随后连续提前最终答复，最终缺少 ResumeVersion 和 application merge
```

已补修复：

```text
1. Workflow guard：
   如果同一 run 已有 ResumeVersion validation failed，
   后续 compacted content retry 不再直接 block，
   而是移除 content_omitted/content_preview，让工具进入 fallback 分支。

2. career_resume_version_create：
   如果同一 run 已有 ResumeVersion validation failed，
   且本次没有 content / artifact_id，
   工具会生成保守 fallback 简历 artifact 和 ResumeVersion，
   不再让模型依赖压缩预览恢复。
```

本地验证：

```text
uv run pytest tests/test_workflow_runtime_guard.py tests/test_agent_runtime.py tests/test_tool_context_window.py tests/test_tool_result_view.py tests/test_career_tools.py tests/test_context_assembler.py -q
通过

uv run mypy app/runtime/agent_runtime.py app/runtime/workflow/guard.py app/tools/builtin_tools/career.py tests/test_agent_runtime.py tests/test_workflow_runtime_guard.py tests/test_career_tools.py
通过
```

#### 当前判断

质量方向已经比 r1 收敛，但性能仍不达标：

```text
高并发 3 run 平均仍在 230s 左右
失败主要来自恢复分支，不是并发写坏数据
main-agent 仍承担过多等待、重试和状态判断
```

后续不建议继续靠 prompt 细则修补。下一步应该进入“工作流执行层”：

```text
resume_diagnosis / jd_fit / resume_version 三个阶段由 runtime 判断完成态
模型负责产出内容和必要决策
runtime 负责 required action 的推进、失败恢复和最终闭环确认
```
