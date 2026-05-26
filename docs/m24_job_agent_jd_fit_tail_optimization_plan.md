# M24 job_agent JD 匹配长尾优化方案

> 状态：开发前方案。本文基于 `live_career_smoke_m24_final_ready_terminal_concurrency_r2` 的复盘结果，目标是在不放松事实守卫和质量门禁的前提下，减少 `job_agent` 在 JD 匹配阶段的重复工具轮次。

## 1. 背景

当前产品目标仍然是长期求职成长 Agent：

```text
围绕目标岗位 / 目标公司，持续管理用户能力差距、求职资产、学习计划和面试准备。
```

M24 当前主线不是新增产品功能，而是让默认降本配置下的求职主链路稳定收敛：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
```

上一轮高并发 live smoke 已经达到质量收口：

```text
r2: 6/6 passed
avg elapsed: 206.37s
max elapsed: 279.30s

每个 run 均生成：
  artifacts=5
  career_applications=1
  career_profiles=1
  jd_analyses=1
  job_fit_reports=1
  resume_profiles=1
  resume_versions=1
```

但性能长尾仍然明显。Run 5 中 `job_agent` 消耗偏高：

```text
job_agent calls=16
job_agent tokens=99,195
career_jd_analysis_save=2
career_job_fit_report_save=3
```

这说明当前问题已经不是“产品记录写不出来”，而是“阶段完成后仍有多余模型轮次和重复工具尝试”。

## 2. 现象复盘

Run 5 的关键路径如下：

```text
1. job_agent 正常读取 JD、简历画像、职业画像。
2. career_jd_analysis_save 成功。
3. 第一次 session_create_text_artifact 被事实守卫拦截：
   报告把 JD 中的“向量检索”写成了候选人能力。
4. 第二次 session_create_text_artifact 成功，生成岗位匹配报告 artifact。
5. runtime 正确提示下一步应调用 career_job_fit_report_save。
6. career_job_fit_report_save 成功，JobFitReport 产品记录已经存在。
7. 后续仍继续出现 session_create_text_artifact、career_jd_analysis_save、career_job_fit_report_save。
8. 重复保存最终通过幂等复用收敛，但额外消耗了模型轮次和 token。
```

这里有两个正向信号：

- 事实守卫没有放过错误内容，候选人事实边界有效。
- store 幂等复用没有造成重复产品记录，最终质量通过。

同时也暴露出一个核心短板：

```text
guard / idempotency 能保护数据正确性，但还没有足够强地把 child-agent 推入终态。
```

## 3. 根因判断

### 3.1 完成态没有变成强终态

`career_job_fit_report_save` 成功后，JD 匹配阶段已经具备完整产物：

```text
JDAnalysis
JobFitReport
report artifact
```

但之后的 recoverable block / reuse 结果仍然像“还能继续修复”一样返回，模型会继续尝试创建 artifact 或重复保存产品记录。

### 3.2 pending runtime plan 可能阶段回退

长尾 run 中出现过这种状态：

```text
JobFitReport 已保存
但后续 runtime plan 又提示 missing_outputs 包含 jd_analysis / job_fit_report
next_allowed_tools 回到 career_jd_analysis_save
```

这不是事实源缺失，而是由隐藏工具结果、synthetic reuse/block 和 pending plan 合并顺序共同导致的计划回退。

### 3.3 幂等复用保护了数据，但没有消除模型轮次

`career_jd_analysis_save` 和 `career_job_fit_report_save` 的幂等逻辑是必要的，但它只在工具调用发生后生效。

优化目标不是删除幂等，而是在阶段已完成时，让重复调用更早变成终态信号，减少下一轮模型继续试探。

### 3.4 错误报告 artifact 的修复路径还不够短

第一次匹配报告 artifact 被拦截是正确行为。问题在于修复成功后，runtime 没有把“下一步只剩保存 JobFitReport”这个状态稳定保持到阶段结束。

## 4. 优化目标

第一阶段目标：

- `job_agent` 在 JD 匹配阶段完成后快速停止工具调用。
- 已成功保存 `JobFitReport` 后，不再回退到保存 `JDAnalysis` 或重新生成报告 artifact。
- 保留候选人事实守卫，不允许把 JD 要求写成候选人已有能力。
- 保留 store 幂等复用，作为数据正确性的最后防线。
- 不通过扩大 prompt、恢复 full schema、放宽校验来掩盖问题。

非目标：

- 不新增产品功能。
- 不引入 LangGraph。
- 不重写 multi-agent 架构。
- 不把普通聊天纳入强 workflow。
- 不为了降低 token 放松 artifact 事实校验。

## 5. 方案设计

### 5.1 JobFitReport 成功后的 child 终态计划

当当前 child run 已经有成功的 `career_job_fit_report_save`，且能确认以下引用齐全：

```text
jd_analysis_id
job_fit_report_id
report_artifact_id
```

`WorkflowRuntimeGuard` 对后续 JD 匹配阶段工具调用统一返回终态结果：

```json
{
  "workflow_runtime_result": true,
  "policy": "block",
  "recoverable": true,
  "terminal": true,
  "final_answer_ready": true,
  "next_allowed_tools": [],
  "required_tools": [],
  "missing_outputs": [],
  "completed_refs": {
    "jd_analysis_id": "...",
    "job_fit_report_id": "...",
    "report_artifact_id": "..."
  }
}
```

覆盖的重复动作包括：

- `session_create_text_artifact`
- `career_jd_analysis_save`
- `career_job_fit_report_save`
- 阶段内低层 `get/list/read`

目的不是让工具静默成功，而是明确告诉 runtime 和模型：

```text
当前 child-agent 应该停止工具调用，进入最终答复。
```

### 5.2 pending runtime plan 单调化

`RuntimeToolPlan` 在 JD 匹配 child 阶段需要满足单调性：

```text
read_inputs
  -> save_jd_analysis
  -> create_fit_report_artifact
  -> save_job_fit_report
  -> final_answer
```

只要事实源证明后序阶段已完成，就不能接受回退计划。例如：

```text
已成功保存 JobFitReport
  -> 不接受 missing_outputs=[jd_analysis]
  -> 不接受 next_allowed_tools=[career_jd_analysis_save]
  -> 归一化为 final_answer_ready=true
```

事实源优先级：

```text
current run successful tool_result
CareerProductStore idempotent existing record
valid SessionArtifact created in current child run
```

自然语言摘要和模型自述不能覆盖这些事实。

### 5.3 修复 artifact 后立即收窄下一步

当 `session_create_text_artifact` 因 `job_fit_report_artifact_candidate_facts_conflict` 被拦截时，下一步仍然只允许重新创建报告 artifact。

当第二次 artifact 通过后，plan 必须立即切到：

```text
next_allowed_tools=[career_job_fit_report_save]
missing_outputs=[job_fit_report]
```

如果之后出现第三次创建报告 artifact，应被判定为阶段重复，而不是继续开放生成。

### 5.4 保持事实守卫，不做内容放宽

Run 5 第一次报告被拦截的原因是模型把 JD 要求“向量检索”写成了候选人能力。这类错误必须继续拦截。

可以优化的是反馈形态：

```text
把 JD 要求写为“差距 / 待补足”，不要写入“候选人已有能力”。
```

但这属于次级优化。第一版先做 runtime 终态和 plan 单调化，不先改 prompt。

## 6. 开发顺序

### 第一步：补确定性测试

新增或扩展 runtime guard / tool plan 测试，复现以下场景：

```text
child run 已成功 career_job_fit_report_save
后续再次调用 session_create_text_artifact
后续再次调用 career_jd_analysis_save
后续再次调用 career_job_fit_report_save
```

期望：

```text
terminal=true
final_answer_ready=true
next_allowed_tools=[]
missing_outputs=[]
completed_refs 包含 jd_analysis_id / job_fit_report_id / report_artifact_id
```

### 第二步：实现 child JD 匹配终态 guard

在 `WorkflowRuntimeGuard` 中新增 JD 匹配终态推导逻辑。它只从当前 run 的成功工具结果和已知产品引用推导，不依赖模型文本。

建议先做成小函数：

```text
_child_job_fit_terminal_plan(...)
```

再由重复工具拦截路径复用，避免分散在多个 if 分支里。

### 第三步：让 pending runtime plan 不回退

在 `pending_runtime_plan_from_workflow_result` 或 plan 合并处增加归一化：

```text
如果当前事实已经完成 job_fit_report
  incoming plan 不能重新引入 jd_analysis / job_fit_report 缺失
  incoming next_allowed_tools 不能退回到 career_jd_analysis_save
```

这一步要保持保守：

- 只有成功工具结果或已有产品记录能触发单调化。
- 失败结果不能触发终态。
- 用户明确要求重新生成时，不走本次优化路径。

### 第四步：验证 AgentRuntime 终态恢复

增加 runtime 层测试：

```text
当 child-agent 连续收到 terminal workflow result
AgentRuntime 应进入 final answer recovery
不继续 schema search / 工具试探
```

### 第五步：live smoke 验证

先跑小批次，再跑高并发：

```text
3 runs / concurrency 3
6 runs / concurrency 3
```

默认配置保持：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
```

## 7. 验收标准

质量标准：

- live smoke `6/6 passed`。
- `check_career_product_store.py` 全部通过。
- 不出现以下错误关键词：

```text
optional string argument must be a string
Tool schema search limit
Tool call limit
requires either content or artifact_id
```

性能标准：

- `job_agent` 单 run tool/model calls 目标 `p95 <= 8`，最大不超过 `10`。
- 高并发 `max elapsed` 目标降到 `220s` 以内。
- 高并发 `avg elapsed` 目标降到 `190s` 以内。
- 不再出现同一 child run 内 `career_jd_analysis_save=2`、`career_job_fit_report_save=3` 这类长尾形态。

边界标准：

- 不放松 `ResumeVersion` 候选人事实守卫。
- 不放松 `JobFitReport` 中 JD 要求和候选人能力的边界。
- 不把失败的 `career_job_fit_report_save` 误判为终态。
- 不影响主 agent 在产品记录缺失时的正常重试能力。

## 8. 风险和缓解

### 8.1 过早终态

风险：

```text
JobFitReport 产品记录存在，但 report_artifact_id 没有正确传给最终答复。
```

缓解：

```text
终态计划必须携带 completed_refs。
测试中断言 jd_analysis_id / job_fit_report_id / report_artifact_id 三者齐全。
```

### 8.2 误伤合法重试

风险：

```text
某次 save 失败后，runtime 误以为阶段完成。
```

缓解：

```text
只有 successful tool_result 或 store 中已存在的 active record 能触发终态。
失败 tool_result 只能触发 repair plan，不能触发 final_answer_ready。
```

### 8.3 指标口径混淆

风险：

```text
tool_call_counts 可能把 synthetic block/reuse 也算入工具调用，导致看起来仍有重复。
```

缓解：

```text
验收时同时看 model calls、successful real tool execution、workflow_runtime_result。
最终目标是减少模型轮次；synthetic guard 次数作为辅助指标。
```

## 9. 开发结论

下一步开发优先级：

```text
1. 先补确定性测试，锁定 JobFitReport 成功后的终态行为。
2. 再实现 WorkflowRuntimeGuard 的 child JD 匹配终态计划。
3. 然后补 RuntimeToolPlan 单调化，防止 pending plan 回退。
4. 最后用默认降本配置跑 3x3 和 6x3 live smoke。
```

这条路线优先处理 runtime 状态收敛，而不是继续扩大 prompt 或调整模型输出风格。原因是 Run 5 已经证明产品事实和质量门禁有效，剩下的主要损耗来自阶段完成后的多余试探。

## 10. 实施结果

本轮已完成第一阶段开发：

- `WorkflowRuntimeGuard` 增加 `job_agent` JD 匹配终态拦截：当前 child run 成功保存 `JobFitReport` 后，重复 `tool_search`、低层读取、报告 artifact 重写、`career_jd_analysis_save` 和 `career_job_fit_report_save` 都返回 `terminal=true` / `final_answer_ready=true`。
- `RuntimeToolPlan` 增加 `career_job_fit_report_save` 成功后的 final plan，并防止已完成 JD 匹配计划回退到 `jd_analysis` / `job_fit_report` 缺失态。
- `AgentRuntime` 对 pending runtime plan 下的重复 `tool_search` 增加防卡死处理：前两次提醒，之后返回隐藏工具的结构化结果，避免只追加自然语言 notice 导致模型反复搜索。
- `tool_result_view` 保留隐藏 `tool_search` 的 runtime payload，避免 compact 视图吞掉 `tool_hidden_by_runtime_plan` 和下一步工具信息。
- `career_job_fit_report_save` 的 `evidence_refs` 兼容模型常见的带标签引用，例如 `JD artifact: artifact_xxx` 会归一化为 `artifact_xxx`。
- 同步保留上一轮修复：`career_application_merge` 的 `summary` / `notes` 支持字符串或字符串列表。

验证结果：

```text
确定性回归：
  tests/test_career_tools.py
  tests/test_runtime_tool_plan.py
  tests/test_agent_runtime.py
  tests/test_tool_reveal.py
  tests/test_tool_context_window.py
  tests/test_workflow_runtime_guard.py
  tests/test_agent_task_runtime.py
  全部通过

mypy:
  app/runtime/agent_runtime.py
  app/runtime/agent/tool_result_view.py
  app/runtime/workflow/guard.py
  app/runtime/workflow/tool_plan.py
  app/tools/builtin_tools/career.py
  以及相关测试文件
  全部通过
```

live smoke：

```text
3x3: data/live_career_smoke_m24_job_fit_terminal_3x3_r1
  3/3 passed

6x3 final: data/live_career_smoke_m24_job_fit_terminal_6x3_r3
  6/6 passed
  avg elapsed: 199.22s
  max elapsed: 226.17s
  product store checker: 6/6 passed
  关键错误扫描: no matches
```

最终 `job_agent` 分布：

```text
run_001: calls=6 tokens=31,237
run_002: calls=7 tokens=39,263
run_003: calls=8 tokens=47,283
run_004: calls=7 tokens=40,166
run_005: calls=7 tokens=40,839
run_006: calls=6 tokens=34,424
```

结论：

- 原始长尾中的 `job_agent calls=16 / tokens=99,195 / career_job_fit_report_save=3` 已收敛。
- 6x3 final 中 `career_jd_analysis_save` 和 `career_job_fit_report_save` 均未出现重复保存长尾。
- 最大耗时仍略高于 220s 目标，主要由真实模型耗时和个别阶段 artifact 重写造成；这是后续主 agent / 内容生成层面的优化点，不再是 JobFitReport 保存后阶段回退问题。

## 11. 追加优化：保存成功后的 final plan 兜底

3x3 复测中进一步发现两个尾部问题：

```text
1. career_job_fit_report_save 已成功时，如果 previous_pending_plan 丢失，RuntimeToolPlan 可能没有进入 final_answer_ready。
2. 隐藏的 career_job_fit_report_save 回包曾被 guard 误计为真实保存成功，导致 child job_agent 过早终态。
```

本轮追加修复：

```text
1. career_job_fit_report_save 返回 record_type=job_fit_report 且带 record_id / job_fit_report_id 时，
   即使 previous_pending_plan=None，也直接生成 jd_fit final plan。

2. hidden_tool_result 增加 tool_executed=false / result_created=false。

3. WorkflowRuntimeGuard 统计“当前 run 是否成功调用某工具”时跳过 tool_schema_not_revealed，
   防止隐藏工具回包被当成真实产品写入。

4. RuntimeToolPlan 将“匹配分析报告”类标题识别为岗位匹配报告 artifact，
   避免合法报告标题没有命中 “匹配报告” 而回退到 JDAnalysis 保存计划。
```

同时 3x3 暴露了主链路的一个数据边界：

```text
CareerApplication 在 JD 阶段被模型提前写入不存在的 resume_version_id，
导致后续定制简历阶段误以为 ResumeVersion 已存在。
```

同步修复：

```text
1. career_application_create 只保留当前 session 真实存在的 active ResumeVersion id。
2. career_application_create 从 evidence_refs 中移除不存在的 resume_version_* 引用。
3. career_application_merge 在定制简历阶段只允许合并真实 active ResumeVersion id，
   并从 evidence_refs 中移除非当前 session 的 resume_version_* 引用。
```

追加回归覆盖：

```text
tests/test_runtime_tool_plan.py
  - JobFitReport 保存成功但 previous_pending_plan=None 时进入 final plan
  - “匹配分析报告”标题进入 career_job_fit_report_save 计划

tests/test_agent_runtime.py
  - 保存成功但没有 pending plan 时，下一轮隐藏已完成阶段工具

tests/test_tool_reveal.py
  - 隐藏工具回包标记 tool_executed=false / result_created=false

tests/test_workflow_runtime_guard.py
  - hidden career_job_fit_report_save 不触发 child job_agent 终态
  - career_application_merge 移除非当前 ResumeVersion id

tests/test_career_tools.py
  - career_application_create 丢弃不存在的 resume_version_id
```

最终验证：

```text
定向回归：
uv run pytest tests/test_runtime_tool_plan.py tests/test_workflow_runtime_guard.py \
  tests/test_tool_reveal.py tests/test_agent_runtime.py tests/test_career_tools.py -q
结果：通过

完整职业链路回归：
uv run pytest tests/test_career_tools.py tests/test_runtime_tool_plan.py tests/test_agent_runtime.py \
  tests/test_tool_reveal.py tests/test_tool_context_window.py tests/test_workflow_runtime_guard.py \
  tests/test_agent_task_runtime.py tests/test_tool_result_view.py -q
结果：通过

mypy:
app/runtime/agent/tool_reveal.py
app/runtime/workflow/guard.py
app/runtime/workflow/tool_plan.py
app/tools/builtin_tools/career.py
以及相关测试文件
结果：通过
```

live smoke：

```text
3x3 final: data/live_career_smoke_m24_jobfit_final_plan_fallback_3x3_r3
  3/3 passed
  avg elapsed: 220.48s
  max elapsed: 248.34s

6x3 final: data/live_career_smoke_m24_jobfit_final_plan_fallback_6x3_r1
  6/6 passed
  avg elapsed: 177.45s
  max elapsed: 203.57s
  product store checker: 6/6 passed
  关键错误扫描: no matches
```

6x3 final 的 `job_agent` 分布：

```text
run_001: llm_calls=6, tokens=35,606, career_jd_analysis_save=1, career_job_fit_report_save=1, hidden=0
run_002: llm_calls=7, tokens=42,778, career_jd_analysis_save=1, career_job_fit_report_save=1, hidden=session_create_text_artifact:1
run_003: llm_calls=5, tokens=29,400, career_jd_analysis_save=1, career_job_fit_report_save=1, hidden=0
run_004: llm_calls=5, tokens=25,520, career_jd_analysis_save=1, career_job_fit_report_save=1, hidden=0
run_005: llm_calls=8, tokens=48,308, career_jd_analysis_save=1, career_job_fit_report_save=1, hidden=0
run_006: llm_calls=7, tokens=37,915, career_jd_analysis_save=1, career_job_fit_report_save=1, hidden=career_profile_get:1
```

结论：

```text
JobFitReport 保存后的阶段回退已压住。
隐藏工具不再被误判为真实成功工具。
CareerApplication 不再接收不存在的 ResumeVersion id。
当前 6x3 最大耗时降至 203.57s，低于 220s 目标。
```
