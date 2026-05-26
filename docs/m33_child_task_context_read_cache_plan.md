# M33 Child TaskContext 与 Read-through Cache 方案

> 状态：已实施并完成两轮 6x3 live smoke；质量通过，但效率目标未达成。M32 让 strict required tool 的执行路径更稳定，但 r3 仍有 `duplicate_runs=3/6`、`hidden_runs=2/6`，并且 `avg_tokens=124065` 没有稳定低于 M31。M33 不继续给单个重复工具加 guard，而是调整职责边界：代码在委派前准备确定性输入，child agent 只负责分析、生成和保存。

## 0. 实施记录

本轮已落地的核心改动：

```text
- RunContext 增加 task_id，child run、任务分配事件和结果摘要都能回到同一 task。
- AgentTaskRuntime 在委派前通过 TaskContextBuilder 生成确定性 task_context。
- AgentInvocationRequest / AgentTaskAssignedPayload 携带 task_context。
- ContextAssembler 增加 assigned_task_context section，把 provided_records / provided_artifacts 注入 child prompt。
- ToolCallLedger 的 read-only 复用范围扩展到 same task_id，返回 reason=read_ledger_reuse。
- Tool result compaction 保留 record_id / hits 等状态机关键字段，避免压缩后打断后续编排。
- 内部 runtime notice / final-answer recovery prompt 改为 assistant role，避免覆盖最新 user intent。
- JD 匹配阶段要求先沉淀 JD source artifact，再委派 job_agent。
- ResumeVersion 主路径保持 career_resume_version_create；已有 generated_file 简历版本 artifact 可作为隐藏支持性工具结果被运行时吸收，但不作为 next_allowed_tools 暴露。
- ResumeVersion artifact 内容校验与 content 直传路径对齐，非法事实触发安全 fallback。
- TaskContext 进一步升级为 child 初始 runtime plan：resume_agent 首轮只暴露 session_create_text_artifact，job_agent 首轮只暴露 career_jd_analysis_save。
- TaskContextBuilder 过滤 schema 字段名，避免把 resume_profile_id / jd_analysis_id 这类字段名误当成真实记录 id。
```

验证：

```text
uv run pytest -q
uv run mypy app/services/task_context_builder.py app/services/agent_invocation_service.py app/services/agent_task_runtime.py app/runtime/agent/tool_gateway.py app/runtime/agent/tool_context_window.py app/runtime/agent/tool_result_view.py app/runtime/agent_runtime.py app/runtime/context/short_term.py app/runtime/context/section_builder.py app/domain/models.py app/runtime/agent_events.py app/infra/storage/jsonl_tool_call_ledger.py app/domain/tool_call_protocols.py app/runtime/workflow/tool_plan.py app/runtime/workflow/career_phase.py app/tools/builtin_tools/career.py
```

live smoke：

```text
data/live_career_smoke_m33_task_context_read_cache_6x3_r1
passed=6/6
avg_elapsed=195.66s
max_elapsed=268.69s
avg_llm_calls=23.2
avg_tokens=140499
duplicate_runs=3/6
hidden_runs=5/6
stagnation_runs=0/6
hard_safety_runs=0/6

结论：TaskContext 已进入 child prompt，但没有收窄 child 初始工具面，首轮仍能看到 read/get 工具；效率未达成。

data/live_career_smoke_m33_task_context_read_cache_6x3_r2
passed=6/6
avg_elapsed=182.26s
max_elapsed=221.68s
avg_llm_calls=21.2
avg_tokens=130535
duplicate_runs=5/6
hidden_runs=6/6
stagnation_runs=0/6
hard_safety_runs=0/6

结论：child 初始工具面收窄后，耗时和 llm_calls 有改善，但 hidden/duplicate 未达标。
```

## 1. 当前问题

M32 r3：

```text
data/live_career_smoke_m32_strict_context_required_tool_6x3_r3
passed=6/6
avg_elapsed=190.48s
max_elapsed=206.65s
avg_llm_calls=23.0
avg_tokens=124065
duplicate_runs=3/6
hidden_runs=2/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

剩余重复集中在只读工具和 schema 搜索：

```text
job_agent:career_resume_profile_get
job_agent:session_read_artifact
resume_agent:session_read_artifact
agent_main:tool_search
```

这些不是副作用问题，而是上下文准备问题。child agent 收到的是自然语言 instruction 和少量 refs，它无法确信：

```text
- artifact 正文是否已读过
- resume_profile / career_profile / jd_analysis 是否已验证
- 哪些 refs 可以直接用于保存
- 哪些 read/get 只是重复确认
```

所以模型用 read/get/search 给自己补确定性。M32 的 strict mode 能挡住或替换一部分，但只是纠偏，不是让重复意图消失。

## 2. 原则

M33 不做：

```text
- 不给 job_agent:career_resume_profile_get 单独加“最多一次” guard。
- 不给 session_read_artifact 单独写更多隐藏工具提示。
- 不靠 prompt 让模型“记住已经读过”。
- 不把所有工具轮次上限继续调小。
```

M33 要做：

```text
- main/orchestrator 负责准备 child task 的确定性输入。
- child agent 默认消费 TaskContext，不再临场拼上下文。
- 只读工具统一由 ledger/cache 复用，作为兜底。
- 模型仍可请求缺失输入，但缺失必须由 TaskContext 明确标记。
```

一句话：

```text
Agent 负责产物推理；代码负责输入完整性。
```

## 3. 目标结构

### 3.1 TaskContextSnapshot

新增一个 child-task 输入快照概念，不一定第一版就持久化成独立表，但必须随 child run 进入上下文：

```json
{
  "task_context": true,
  "task_id": "task_xxx",
  "task_group_id": "task_group_xxx",
  "phase": "jd_fit",
  "target_agent_id": "job_agent",
  "provided_inputs_complete": true,
  "known_refs": {
    "resume_profile_id": "resume_profile_xxx",
    "career_profile_id": "career_profile_default",
    "jd_source_artifact_id": "artifact_jd_xxx"
  },
  "provided_artifacts": [
    {
      "artifact_id": "artifact_jd_xxx",
      "title": "目标岗位 JD.txt",
      "media_type": "text/plain",
      "content_hash": "sha256:...",
      "text_preview": "公司招聘 AI 应用开发工程师...",
      "returned_chars": 1200,
      "truncated": false
    }
  ],
  "provided_records": {
    "resume_profile": {
      "record_id": "resume_profile_xxx",
      "content_hash": "sha256:...",
      "snapshot": {}
    },
    "career_profile": {
      "record_id": "career_profile_default",
      "content_hash": "sha256:...",
      "snapshot": {}
    }
  },
  "required_outputs": [
    "jd_analysis",
    "job_fit_report",
    "career_application"
  ],
  "allowed_initial_tools": [
    "career_jd_analysis_save",
    "session_create_text_artifact",
    "career_job_fit_report_save"
  ],
  "do_not_read_again": [
    "session_read_artifact:artifact_jd_xxx",
    "career_resume_profile_get:resume_profile_xxx",
    "career_profile_get:career_profile_default"
  ],
  "missing_inputs": []
}
```

关键字段不是提示词装饰，而是 runtime 计算结果：

```text
provided_inputs_complete=true 代表 child agent 不需要 read/get 才能开始产物写入。
missing_inputs 非空时，才允许对应 read/get。
do_not_read_again 不是软提示，gateway 可据此复用 read ledger。
```

### 3.2 Job Agent 的确定性输入

job_agent 做 JD 匹配时，委派前应准备：

```text
- JD artifact 正文或足够完整的 compact text
- ResumeProfile snapshot
- CareerProfile snapshot，缺省为 career_profile_default
- 已知 diagnosis_artifact_id / resume_source_artifact_id
- report_artifact_contract
- 预期输出：JDAnalysis、JobFitReport、CareerApplication
```

job_agent 第一轮可直接：

```text
career_jd_analysis_save
session_create_text_artifact
career_job_fit_report_save
```

不需要先：

```text
session_read_artifact
career_resume_profile_get
career_profile_get
```

### 3.3 Resume Agent 的确定性输入

resume_agent 做简历诊断时，委派前应准备：

```text
- resume artifact 正文或 compact text
- source_artifact_id / resume_source_artifact_id
- expected diagnosis artifact output_kind
- 预期输出：diagnosis_artifact、ResumeProfile
```

如果 artifact 内容已进入 TaskContext，resume_agent 第一轮可直接：

```text
session_create_text_artifact
career_resume_profile_save
```

不需要重复：

```text
session_read_artifact
```

## 4. 接入点

### 4.1 AgentTaskSpec 扩展

现状：

```python
AgentTaskSpec(
    target_agent_id,
    instruction,
    constraints,
    artifact_refs,
    skill_names,
    max_tool_rounds,
)
```

M33 增加：

```python
task_context: dict[str, Any] = field(default_factory=dict)
```

或者先不改外部 tool schema，只在 `AgentTaskRuntime` 创建 child run 前由代码生成：

```text
AgentTaskRecord.task_context
AgentInvocationRequest.task_context
ContextAssembler.assigned_agent_tasks section
```

优先方案：先内部生成，不暴露给模型参数。这样 main agent 不需要自己构造 JSON，避免把可靠性重新交给模型。

### 4.2 AgentTaskRuntime 组装 TaskContext

接入点：

```text
app/services/agent_task_runtime.py
```

在 `_run_one()` 调用 `AgentInvocationRequest` 前：

```python
task_context = task_context_builder.build(
    source_context=request.source_context,
    spec=spec,
    record=record,
)
```

然后传入 child run。

### 4.3 AgentInvocationService 注入 child 上下文

接入点：

```text
app/services/agent_invocation_service.py
app/runtime/context/section_builder.py
```

child run 的 context section 新增：

```text
assigned_task_context
```

该 section 必须短、结构化、不可散文化：

```text
- provided_inputs_complete=true
- known_refs=...
- provided_artifacts=...
- provided_records=...
- do_not_read_again=...
- missing_inputs=[]
- required_outputs=...
```

### 4.4 ToolGateway Read-through Cache

现有：

```text
ToolGateway 已按 read_only tool 的 input_hash 复用当前 run/agent 的成功结果。
```

M33 要扩展为：

```text
- 同一 task_context 内的 read-only 工具复用。
- 允许 child run 复用 parent run 或 sibling child run 已读取过的 artifact/product snapshot。
- 返回 policy=reuse, reason=read_ledger_reuse 或 task_context_read_reuse。
```

注意：这是兜底，不是主路径。主路径仍然是 TaskContext 让模型不再产生重复 read/get。

## 5. Read Cache 规则

### 5.1 Cache Key

```text
tool_name + canonical_json(arguments) + session_id + content_version
```

其中：

```text
session_read_artifact:
  content_version = artifact_id + artifact.updated_at/hash + offset/max_chars

career_*_get:
  content_version = record_id + record.updated_at/hash

tool_search:
  content_version = available_tool_catalog_version + query + runtime_plan signature
```

第一版可以先用现有 `canonical_tool_input_hash()`，但文档和事件里标出当前版本没有 record hash，避免假装强一致。

### 5.2 Reuse Scope

按风险从小到大：

```text
1. same run + same agent
2. same task_id
3. same session + same content_version
```

M33 第一版建议做到 1 + 2，谨慎引入 3。

### 5.3 返回格式

复用结果仍返回原工具结果，但附加：

```json
{
  "workflow_runtime_result": true,
  "policy": "reuse",
  "reason": "read_ledger_reuse",
  "read_cache_reused": true,
  "source_tool_call_record_id": "tool_call_xxx"
}
```

## 6. 阶段计划

### Phase 1：文档与观测

```text
- 增加 M33 文档。
- 给 live smoke 报告增加 read_duplicate 分类：
  read_duplicate_tools
  read_reuse_count
  task_context_missing_inputs
```

目标：先确认重复读来自哪些 task/phase，而不是继续凭感觉改。

### Phase 2：TaskContextBuilder

新增：

```text
app/services/task_context_builder.py
tests/test_task_context_builder.py
```

能力：

```text
- 根据 target_agent_id + artifact_refs + current workflow refs 生成 TaskContextSnapshot。
- job_agent 自动填 JD artifact text、ResumeProfile、CareerProfile、report_artifact_contract。
- resume_agent 自动填 resume artifact text 和 source refs。
- 输出 provided_inputs_complete / missing_inputs。
```

### Phase 3：Child Context 注入

接入：

```text
AgentTaskRuntime -> AgentInvocationRequest -> ContextAssembler/SectionBuilder
```

测试：

```text
- job_agent child prompt 中出现 assigned_task_context。
- resume_agent child prompt 中出现 assigned_task_context。
- provided_inputs_complete=true 时，section 明确列出 do_not_read_again。
```

### Phase 4：Read-through Cache 扩展

接入：

```text
ToolGateway
ToolCallLedger
tool_policy
```

测试：

```text
- same task 的 session_read_artifact 第二次返回 read_ledger_reuse。
- same task 的 career_resume_profile_get 第二次返回 read_ledger_reuse。
- write tool 不跨结果复用，仍走幂等键。
```

### Phase 5：Live Smoke

先跑一组高并发全量 live smoke，避免 4 组/2 组等待时间过长；如果结果仍有明显长尾，再基于事件根因决定是否追加第二组：

```text
data/live_career_smoke_m33_task_context_read_cache_6x3_r1
```

## 7. 验收标准

硬标准：

```text
passed=6/6
stagnation_runs=0/6
hard_safety_runs=0/6
ResumeProfile.diagnosis_artifact_id=6/6
```

效率标准：

```text
hidden_runs <= 1/6
duplicate_runs <= 1/6
avg_llm_calls < 22
avg_tokens < 115000
```

结构性标准：

```text
job_agent 不应为了已提供的 resume_profile_id 重复 career_resume_profile_get。
job_agent 不应为了已提供的 JD artifact text 重复 session_read_artifact。
resume_agent 不应为了已提供的 resume artifact text 重复 session_read_artifact。
agent_main 不应在 required tool 已可见时重复 tool_search。
```

## 8. 风险与边界

### 8.1 TaskContext 过大

风险：把 artifact 正文和 record snapshot 都塞进 child prompt，可能增加 prompt token。

处理：

```text
- artifact text 按任务类型 compact。
- JD 通常较短，可直接放全文。
- 简历较长时保留结构化摘要 + 必要片段。
- snapshot 做字段白名单，不塞完整历史。
```

### 8.2 复用过期读结果

风险：read cache 返回旧 record。

处理：

```text
- 第一版 reuse scope 限 same run / same task。
- 跨 run/session 复用必须等 content_version/hash 完整后再做。
```

### 8.3 模型仍调用 read/get

这是预期内的残余行为。处理方式不是 hidden，而是：

```text
- 如果 TaskContext 已提供该输入，gateway 返回 read_ledger_reuse。
- 如果 TaskContext missing_inputs 包含该输入，允许真实读取。
- 如果既不缺也不可复用，才返回 runtime block，并记录为 task_context_violation。
```

## 9. 判断标准

如果 M33 只让 live smoke 偶然变好，但事件里仍然看到 child agent 先 read/get 再写入，说明失败。

真正成功的事件形态应该是：

```text
delegate_agents
  -> child receives assigned_task_context
  -> child first business write/save tools
  -> optional read_ledger_reuse only as fallback
  -> final summary
```

而不是：

```text
delegate_agents
  -> child session_read_artifact
  -> child career_resume_profile_get
  -> child career_profile_get
  -> child 再开始写入
```

## 10. R2 后的真实剩余问题

M33 已经证明一个判断：只给 child prompt 注入 TaskContext 不够，必须让 runtime plan 收窄工具面。R2 之后 child 首轮读工具明显减少，但整体效率仍未达标，剩余问题已经换类：

```text
1. main agent 在 required/final plan 下仍尝试隐藏工具：
   - agent_main:tool_search
   - agent_main:delegate_agents
   - agent_main:career_application_get

2. 写工具重复不再主要是“读上下文”，而是校验/恢复链路触发：
   - career_resume_version_create 因禁用词或事实边界失败后重试
   - career_jd_analysis_save / career_job_fit_report_save 因报告事实边界重写后重试
   - session_create_text_artifact 因岗位匹配报告被重写而重复创建

3. 个别 child 在 runtime plan 后续阶段仍尝试隐藏 read/get：
   - job_agent:career_resume_profile_get
   - job_agent:session_read_artifact
```

这说明下一步不应继续加“某工具最多一次”补丁，而要把剩余问题分到两个状态机里：

```text
- Product write recovery state：
  写入失败时明确进入 REPAIR_REQUIRED，只允许同一个 required write 或 required artifact rewrite；
  重试成功后用 ledger/idempotency 标记上一轮失败是 recovery，不计作普通 duplicate。

- Final/required action state：
  required/final plan 下，隐藏工具请求不再回灌成普通 tool result 让模型再想一轮；
  能 auto-execute required tool 的直接执行，final_ready 时直接进入 deterministic finalizer。
```

下一步优化目标应从“child 少读”切换到：

```text
- required/final plan 下消除 hidden tool round-trip。
- 把 write validation recovery 从模型自由重试改成代码状态机。
- live smoke 统计区分 harmful duplicate、recovery retry、idempotent reuse。
```

## 11. R3 前收口实现

已补充两处代码层状态机收口：

```text
1. required tool 已可见时，模型如果继续调用 tool_search：
   - runtime 只记录 schema_search_suppressed_required_tool_visible；
   - 不再生成 tool_hidden_by_runtime_plan 的 tool result；
   - 直接把 runtime_plan_notice 回灌给模型，要求调用 required tool。

2. final_answer_ready=true 时：
   - 本轮可见工具面直接清空；
   - 不再把非 discouraged 工具留给模型继续调用。
```

同时 smoke 统计新增：

```text
- harmful_duplicate_tool_calls / harmful_duplicate_tool_call_count
- recovery_duplicate_tool_calls / recovery_duplicate_tool_call_count
- aggregate 中新增 harmful_duplicate_runs / recovery_duplicate_runs
```

这样后续判断不再只看 raw duplicate，而是区分：

```text
- harmful duplicate：无状态推进的重复工具调用。
- recovery duplicate：写入校验失败后的受控恢复重试。
```

验证：

```text
uv run pytest -q
uv run mypy --explicit-package-bases app/runtime/agent_runtime.py tools/smoke_career_live_flow.py tests/test_agent_runtime.py tests/test_career_live_smoke_report.py
```

## 12. R3 复盘与状态驱动修正

R3 live smoke 业务全部通过，但效率没有真正收口：

```text
data/live_career_smoke_m33_task_context_read_cache_6x3_r3
- passed=6/6
- avg_elapsed=334.48s
- max_elapsed=776.57s
- avg_llm_calls=29.2
- avg_tokens=180679
- duplicate_runs=4/6
- harmful_duplicate_runs=4/6
- hidden_runs=4/6
```

最坏的 run_001 暴露出真正根因：

```text
resume_agent 在同一个子任务里跑到 35 个模型轮次。
前 29 轮 runtime 只暴露 session_create_text_artifact。
模型反复创建/复用诊断 artifact，或直接最终答复后被 runtime 判定 premature。
career_resume_profile_save 直到很晚才真正进入可见工具面。
```

这不是单个工具 guard 没写够，而是 workflow 推进仍依赖 artifact title/content 猜测：

```text
- title=resume_diagnosis_artifact_resume_live_001.md 不含中文“简历诊断报告”，
  runtime 没识别为 diagnosis_artifact 已完成。
- artifact 正文里提到“岗位匹配报告”，idempotency 曾误归类为 job_fit_report。
- 结果是 pending_runtime_plan 没从 session_create_text_artifact 推进到 career_resume_profile_save。
```

修正原则：

```text
不要再把产物类型交给标题猜测。
优先使用 pending_runtime_plan.phase + missing_outputs + required_tool 判定当前 text artifact 属于哪个 workflow output。
title/content classifier 只做无 runtime plan 时的兜底。
```

已实现：

```text
1. session_create_text_artifact 的 idempotency key 优先读取 runtime plan：
   - resume_diagnosis + diagnosis_artifact -> resume_diagnosis
   - jd_fit + jd_source_artifact -> jd_source
   - jd_fit + job_fit_report_artifact/job_fit_report -> job_fit_report
   - resume_version + resume_version -> resume_version_artifact

2. pending_runtime_plan_from_successful_tool_result 在 required text artifact 步骤中，
   直接按 runtime plan 推进状态，不再要求 title 必须命中特定中文模式。

3. premature final answer 增加无推进边界：
   同一 pending plan 下模型连续直接答复超过阈值，runtime 进入
   premature_final_answer_stagnation，返回 deterministic incomplete answer，
   不再烧到 hard model round limit。

4. smoke 统计口径进一步拆分：
   - raw duplicate：模型是否重复提出相同工具意图。
   - recovery duplicate：guard/ledger/strict replacement 防住或恢复的重复。
   - harmful duplicate：同一工具实际重复执行且没有被防住。
```

验证：

```text
uv run pytest -q
uv run mypy --explicit-package-bases app/runtime/agent_runtime.py app/runtime/agent/tool_gateway.py app/runtime/workflow/tool_idempotency.py app/runtime/workflow/tool_plan.py tools/smoke_career_live_flow.py
```

R4 live smoke：

```text
data/live_career_smoke_m33_state_driven_text_artifact_6x3_r1
- passed=6/6
- avg_elapsed=179.84s
- max_elapsed=208.96s
- avg_llm_calls=20.3
- avg_tokens=124388
- duplicate_runs(raw)=2/6
- harmful_duplicate_runs=0/6
- recovery_duplicate_runs=2/6
- hidden_runs=2/6
```

对比 R3：

```text
- avg_elapsed: 334.48s -> 179.84s
- max_elapsed: 776.57s -> 208.96s
- avg_llm_calls: 29.2 -> 20.3
- avg_tokens: 180679 -> 124388
- harmful_duplicate_runs: 4/6 -> 0/6
```

剩余问题已经不是副作用重复执行，而是模型仍会偶发提出被 runtime 阻止的隐藏工具：

```text
- main agent 在 required plan 下尝试 career_resume_profile_get/session_read_artifact/delegate_agents。
- job_agent 在 TaskContext 已提供输入时仍尝试 session_read_artifact。
- resume_version 阶段模型偶发重复提出已完成的 create，但 strict runtime 会替换为 required merge。
```

下一步不应回到“给某个工具加一次性补丁”，而应继续收敛 deterministic action surface：

```text
1. main agent 在 child result 已包含 CareerProfile/ResumeProfile refs 时，直接 final 或 required merge，
   避免再次通过读工具确认。
2. child agent 若 TaskContext 已完整提供输入，首轮只暴露 required write tool；
   对 hidden read 不再作为普通 observation 回灌长文本。
3. final_answer_recovery 的质量需要单独收口，避免“关键产物已完成但模型没有生成可用总结”成为用户可见结果。
```
