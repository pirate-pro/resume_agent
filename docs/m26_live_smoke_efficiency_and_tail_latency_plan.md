# M26 live smoke 效率与长尾优化方案

> 状态：第一阶段已实现并完成一组 `custom_resume 6x3` live smoke。本文承接 M24 的 JD 匹配长尾收敛和 M25 的最终回答 / 工具预算边界优化，目标是在产品质量已经稳定通过后，降低常规 live smoke 的等待时间、模型轮次和重复工具调用。

## 1. 背景

当前产品目标不变：

```text
围绕目标岗位 / 目标公司，持续管理用户能力差距、求职资产、学习计划和面试准备。
```

M24 已经把 `job_agent` 的岗位匹配保存回退压住，M25 已经把工具轮次上限从用户可见失败原因改成软预算和停滞收束边界。最近高并发 live smoke 结果显示，主链路质量已经稳定：

```text
none:          6/6 passed
checklist:     6/6 passed
interview:     6/6 passed
custom_resume: 6/6 passed
```

但成本和反馈周期仍偏高。常规开发不再跑四组 6x3，而是默认只跑一组代表性验证：

```text
uv run python tools/smoke_career_live_flow.py --runs 6 --concurrency 3 --max-tool-rounds 24 --project-action custom_resume --quiet
```

`custom_resume` 作为默认代表性场景，因为它覆盖：

- 简历画像生成
- JD 匹配分析
- CareerApplication 创建
- 定制简历 ResumeVersion 生成
- 项目动作回写
- artifact / 产品记录质量门禁

## 2. 当前信号

基于最近 `custom_resume 6x3` 事件样本，主要长尾信号不再是“记录写不出来”，而是：

```text
1. agent_main LLM 调用和 token 偏高
   个别 run 达到 15-18 次主 agent LLM 调用，主 agent token 超过 100k。

2. job_agent 偶发重复生成 / 保存
   个别 run 仍出现 session_create_text_artifact=3、
   career_jd_analysis_save=2、career_job_fit_report_save=2。

3. 工具隐藏和停滞事件仍偶发
   M25 已能收束，但这些事件说明模型仍在尝试已完成或当前不可执行的动作。

4. smoke 报告缺少效率维度
   现在能看到总耗时、工具计数、质量失败；
   但不能一眼看到每个 agent 的 LLM 调用、token、重复工具、隐藏工具和停滞恢复。
```

这意味着 M26 不应该先加新 guard 或继续提高工具预算，而应该先把效率问题可观测化，再针对高频重复路径做确定性收敛。

## 3. 优化目标

第一阶段目标：

- 常规 live smoke 只要求一组代表性 `custom_resume 6x3`。
- smoke 报告直接暴露效率指标，能定位长尾来自哪个 agent / 工具 / 阶段。
- 减少 `agent_main` 在产品记录已齐全后的重复 `tool_search`、重复读取和重复 delegate。
- 减少 `job_agent` 在合法 JobFitReport / report artifact 已生成后的重复保存或生成。
- 不放松事实守卫、产品记录校验、最终回答质量门禁。

非目标：

- 不为了提速降低质量门禁。
- 不恢复 full schema 或 full context。
- 不把所有隐藏工具都当成功。
- 不把外部模型偶发慢响应误判成业务问题。
- 不重写 multi-agent 架构。

## 4. 方案设计

### 4.1 先补 live smoke 效率摘要

在 `tools/smoke_career_live_flow.py` 中新增只读效率统计：

```text
per run:
  llm_calls_by_agent
  llm_tokens_by_agent
  tool_calls_by_agent
  duplicate_tool_calls
  hidden_tool_results
  failed_tool_results
  stagnation_decisions
  hard_safety_decisions

aggregate:
  avg / max elapsed
  avg / max llm calls
  avg / max tokens
  runs with duplicates
  runs with hidden tools
  runs with stagnation
```

第一版只打印和记录，不作为失败门禁。原因是当前还需要收集稳定基线，避免用单次模型延迟给系统加错约束。

### 4.2 定义重复工具的稳定口径

重复不应只按工具名统计。合理口径是：

```text
agent_id + tool_name + stable_arguments_fingerprint
```

`stable_arguments_fingerprint` 只保留短字段：

- `artifact_id`
- `application_id`
- `resume_profile_id`
- `career_profile_id`
- `jd_analysis_id`
- `job_fit_report_id`
- `resume_version_id`
- `record_id`
- `target_agent_id`
- `query`
- `intent`
- `title`

大段正文、简历内容、报告正文、定制简历正文不进入 fingerprint，避免把内容噪声写进 smoke 报告。

### 4.3 先观测，再设门禁

第一阶段只输出 warning：

```text
duplicate_tool_calls > 0
hidden_tool_results > 0
stagnation_decisions > 0
agent_main_llm_calls > 14
job_agent_llm_calls > 8
total_tokens > 220k
elapsed > 260s
```

第二阶段在数据稳定后，再把明确的产品退化升级为失败，例如：

```text
JobFitReport 已成功保存后再次成功保存同一报告
合法 custom resume ResumeVersion 已生成后再次生成同类版本
final_answer_ready 后继续执行业务写工具
```

### 4.4 主 agent 阶段收敛

M25 后主 agent 有能力基于 durable state 生成最终回答，但仍可能继续搜索或读取已经由 child agent 返回的记录。

优化方向：

```text
delegate_agents 成功返回 completed_refs
  -> RuntimeToolPlan 立即合并这些 refs
  -> current_workflow_phase 不回退
  -> 已满足的 required_tools 从下一轮上下文中移除
  -> 只暴露当前阶段唯一下一步
```

重点减少：

- child 成功后重复 `tool_search`
- 已有 `resume_profile_id` 后重复 `career_resume_profile_get`
- 已有 `job_fit_report_id` 后重复 `career_job_fit_report_get/list`
- 已创建 `application_id` 后重复 delegate JD 匹配

### 4.5 JD fit 尾部继续收窄

M24 已经处理了大多数保存回退，但最新样本仍说明需要继续强化：

```text
合法 report artifact 已存在
  -> 下一步只能 career_job_fit_report_save

JobFitReport 已保存
  -> job_agent final_answer_ready
  -> 阻止再次 session_create_text_artifact / career_jd_analysis_save / career_job_fit_report_save
```

如果这些重复发生，先判断根因：

- pending plan 是否丢失 phase
- hidden result 是否污染了成功工具事实
- agent result refs 是否没有带到 main run
- idempotent reuse 是否被模型理解成还可继续修复

不做针对某个 run id、标题或文本的补丁。

### 4.6 custom_resume 项目动作收敛

默认代表性 smoke 使用 `custom_resume`，因此项目动作阶段需要更直接：

```text
career_application_get
  -> career_resume_version_create
  -> career_application_merge
  -> final answer
```

需要避免：

- 没有必要的 `tool_search`
- 重复读取底层记录
- 把上传的原始简历 artifact 当成输出 ResumeVersion
- ResumeVersion 已创建后没有合并回 application

M25 已经修复了错误 artifact fallback 和 invalid optional refs，M26 重点是减少不必要轮次。

## 5. 开发顺序

### 第一步：补 smoke 效率统计

新增 `EfficiencySummary` 或等价结构，来源只读事件日志。

回归覆盖：

```text
tests/test_career_live_smoke_report.py
```

验证点：

- 统计 llm usage by agent。
- 统计 hidden tool result。
- 统计 stagnation / hard safety decision。
- 统计同一 agent + tool + stable args 的重复工具调用。
- 报告输出不影响既有质量门禁。

### 第二步：用现有 live 数据回填基线

对最近一组 `custom_resume 6x3` 重新生成摘要，记录：

```text
agent_main llm_calls / tokens
job_agent llm_calls / tokens
duplicate tools
hidden tools
stagnation events
elapsed max run
```

此步不改业务逻辑，只确定真正的优化优先级。

### 第三步：修首个确定性重复路径

按基线选择第一条路径。优先级：

```text
1. JobFitReport 已完成后的 job_agent 重复生成 / 保存。
2. child completed_refs 已齐全后的 main agent 重复 tool_search / get。
3. custom_resume 已生成 ResumeVersion 后的重复读取或未及时 merge。
```

修复前必须先写确定性测试复现根因。

### 第四步：常规验收

定向回归：

```text
uv run pytest tests/test_career_live_smoke_report.py tests/test_runtime_tool_plan.py tests/test_agent_runtime.py tests/test_workflow_runtime_guard.py -q
```

mypy 按触达文件补充。

live smoke：

```text
uv run python tools/smoke_career_live_flow.py --runs 6 --concurrency 3 --max-tool-rounds 24 --project-action custom_resume --data-dir data/live_career_smoke_m26_efficiency_custom_resume_6x3_r1 --quiet
```

只有当本轮改动触及 `checklist` / `interview` / `none` 的专属逻辑，或准备 release gate 时，才追加其它 action 矩阵。

## 6. 第一阶段验收标准

质量必须保持：

- `custom_resume 6/6` 通过。
- product store checker 通过。
- 最终回答不泄露 runtime 内部错误。
- 不出现未支持候选人事实写入定制简历。
- ResumeVersion 创建后合并回 CareerApplication。

效率先作为观测目标：

- smoke 报告展示每个 run 的效率摘要。
- 能看出最慢 run 的主要成本来自哪个 agent。
- 能列出重复工具和隐藏工具。
- 能区分模型响应慢和 workflow 重复。

如果第一轮优化后数据稳定，再把以下目标作为下一阶段硬指标候选：

```text
custom_resume 6x3 max elapsed < 260s
agent_main max llm_calls <= 14
job_agent max llm_calls <= 8
job_agent career_jd_analysis_save <= 1
job_agent career_job_fit_report_save <= 1
hard safety decisions = 0
```

## 7. 风险和缓解

### 7.1 把正常修复误判为重复

风险：

```text
第一次 artifact 被事实守卫拒绝，第二次创建是必要修复。
```

缓解：

```text
重复统计区分 success / failure / hidden。
第一阶段只 warning，不失败。
```

### 7.2 只优化 smoke 样本

风险：

```text
针对 custom_resume 优化后，checklist / interview 退化。
```

缓解：

```text
只做 workflow 状态和 durable refs 的确定性收敛。
触及共享 project-action 逻辑时追加对应 action 小批量 smoke。
```

### 7.3 指标噪声太大

风险：

```text
真实模型延迟波动导致 elapsed 不稳定。
```

缓解：

```text
耗时只作为参考，核心优化看 llm_calls、tool_calls、duplicates、hidden、stagnation。
```

## 8. 结论

M26 的第一步不是继续加 guard，而是让 live smoke 从“质量通过 / 失败”升级到“质量 + 效率可解释”。

开发优先级：

```text
1. 补 smoke efficiency summary。
2. 用最近 custom_resume 6x3 回填基线。
3. 选择一条确定性重复路径写测试并修复。
4. 只跑一组代表性 custom_resume 6x3 做常规高并发 live smoke。
```

## 9. 第一阶段实现结果

已完成：

```text
1. FlowReport 增加 efficiency 摘要。
2. smoke 从事件日志统计：
   - llm_calls_by_agent
   - llm_tokens_by_agent
   - duplicate_tool_calls
   - hidden_tool_results
   - failed_tool_results
   - workflow_decisions
3. print_report 增加全局效率摘要和每个 run 的效率摘要。
4. duplicate fingerprint 只保留稳定短字段，避免把大段正文写入报告。
```

定向回归：

```text
uv run pytest tests/test_career_live_smoke_report.py -q
结果：28 passed

uv run mypy --explicit-package-bases tools/smoke_career_live_flow.py tests/test_career_live_smoke_report.py
结果：Success
```

一组代表性高并发 live smoke：

```text
uv run python tools/smoke_career_live_flow.py \
  --runs 6 \
  --concurrency 3 \
  --max-tool-rounds 24 \
  --project-action custom_resume \
  --data-dir data/live_career_smoke_m26_efficiency_custom_resume_6x3_r1 \
  --quiet

结果：
  6/6 passed
  avg elapsed: 276.88s
  max elapsed: 329.82s
  avg_llm_calls: 26.8
  max_llm_calls: 33
  avg_tokens: 149,768
  max_tokens: 182,348
  duplicate_runs: 4/6
  hidden_runs: 4/6
  stagnation_runs: 0/6
  hard_safety_runs: 0/6
```

当前最明确的下一步优化目标：

```text
1. custom_resume 阶段的 career_resume_version_create 重复调用：
   run_001 / run_005 / run_006 均出现同标题重复创建尝试，
   其中部分由 ResumeVersion 保护性拒绝恢复触发。

2. job_agent 的岗位匹配报告 artifact 重复创建：
   run_004 出现 session_create_text_artifact 同标题 4 次，
   对应本轮最大耗时 329.82s。

3. agent_main / job_agent 的隐藏工具：
   hidden_runs=4/6，说明 completed refs / runtime plan 仍有可收窄空间。
```

下一轮开发应先从第 2 项入手。原因是它直接对应最大耗时 run，且 M24 已经有 JD fit 终态和 artifact 事实边界的测试基础，适合先找到 plan 回退或 artifact 完成态未稳定传递的根因。

## 10. 第二阶段具体修复方案

本阶段聚焦 `run_004` 暴露的 JD fit 长尾：

```text
session_create_text_artifact 第 1 次：候选人事实冲突，被 guard 拦截。
session_create_text_artifact 第 2 次：仍然候选人事实冲突，被 guard 拦截。
session_create_text_artifact 第 3 次：合法 report artifact 创建成功。
session_create_text_artifact 第 4 次：已不该再创建，被 runtime plan 隐藏。
career_job_fit_report_save：最终保存成功。
```

根因拆成两类：

```text
1. conflict 反馈太原则化。
   guard 只告诉模型“不要把未支持 JD 要求写成候选人已有能力”，
   但没有指出具体是哪一句、哪个术语、应该移动到哪个栏目。

2. 合法 artifact 成功后的下一步提示出现得太晚。
   第 3 次 artifact 成功结果只返回 artifact_id/title/kind，
   “下一步只调用 career_job_fit_report_save”是在第 4 次错误调用被隐藏后才出现。
```

具体修复：

```text
1. job_fit_report_artifact_candidate_facts_conflict 返回 invalid_claims：
   - term
   - claim
   - section
   - reason
   - rewrite_to

2. 同一 payload 返回 repair_actions：
   - remove_or_rewrite_unsupported_candidate_claim
   - move_term_to_gap_risk_or_interview_focus

3. session_create_text_artifact 在 job_agent 成功创建岗位匹配报告 artifact 后，
   成功结果直接附带 jd_fit follow-up：
   - next_action
   - next_allowed_tools=[career_job_fit_report_save]
   - required_tools=[career_job_fit_report_save]
   - required_tool_call_hint.available_args.report_artifact_id
   - blocked_tools=[session_create_text_artifact]

4. 不改变产品校验和事实守卫。
   合法报告仍必须通过候选人事实边界，未支持技术只能写入差距/风险/面试追问。
```

验收：

```text
1. 确定性测试覆盖 invalid_claims / repair_actions。
2. 确定性测试覆盖 report artifact 成功结果里的 required_tool_call_hint。
3. 定向回归通过。
4. 常规只跑一组 custom_resume 6x3。
```

## 11. 第二阶段实现结果

已完成：

```text
1. job_fit_report_artifact_candidate_facts_conflict 增加 invalid_claims：
   - term
   - claim
   - section
   - reason
   - rewrite_to

2. conflict payload 增加 repair_actions：
   - move_unsupported_term_to_gap_or_risk

3. job_agent 成功创建岗位匹配报告 artifact 后，
   session_create_text_artifact 成功结果直接带：
   - output_kind=job_fit_report
   - next_allowed_tools=[career_job_fit_report_save]
   - required_tool_call_hint.available_args.report_artifact_id
   - blocked_tools=[session_create_text_artifact]

4. workflow guard 拦截求职 session 工作状态类 memory_write：
   当前 session 的 product ids / workflow 进度不写入长期 memory，
   由 product store 和 workflow state 承担。
```

定向回归：

```text
uv run pytest tests/test_workflow_runtime_guard.py tests/test_runtime_tool_plan.py \
  tests/test_tool_reveal.py tests/test_career_tools.py tests/test_career_live_smoke_report.py \
  tests/test_tool_registry.py -q
结果：通过

uv run mypy --explicit-package-bases app/runtime/workflow/guard.py \
  app/tools/builtin_tools/session_artifacts.py tools/smoke_career_live_flow.py \
  tests/test_workflow_runtime_guard.py tests/test_career_tools.py \
  tests/test_career_live_smoke_report.py tests/test_tool_registry.py
结果：Success
```

第一轮 live smoke 暴露了一个新根因：

```text
data/live_career_smoke_m26_jobfit_artifact_guidance_6x3_r1
  5/6 passed
  失败原因：agent_main 调用 memory_write 写入 session working state：
    resume_profile_id / career_profile 已更新 / 岗位匹配可复用 ResumeProfile
  底层 memory 工具正确拒绝：This looks like session working state; use state_set instead of memory_write.
```

该问题不是通过 smoke 忽略失败解决，而是在 workflow guard 前置拦截：

```text
career_session_state_should_not_use_memory_write
```

第二轮 live smoke：

```text
uv run python tools/smoke_career_live_flow.py \
  --runs 6 \
  --concurrency 3 \
  --max-tool-rounds 24 \
  --project-action custom_resume \
  --data-dir data/live_career_smoke_m26_jobfit_artifact_guidance_6x3_r2 \
  --quiet

结果：
  6/6 passed
  avg elapsed: 204.78s
  max elapsed: 223.57s
  avg_llm_calls: 27.2
  max_llm_calls: 31
  avg_tokens: 149,146
  max_tokens: 168,431
  duplicate_runs: 4/6
  hidden_runs: 5/6
  stagnation_runs: 2/6
  hard_safety_runs: 0/6
```

对比第一阶段基线：

```text
max elapsed: 329.82s -> 223.57s
max_llm_calls: 33 -> 31
max_tokens: 182,348 -> 168,431
job_agent 同标题岗位匹配报告 artifact 重复：4 次长尾 -> 本轮最多 2 次
```

结论：

```text
本阶段修复有效，但还没有完全消除重复轮次。
剩余主要问题转为：
1. main agent 重复 delegate_agents。
2. job_agent 重复 career_profile_get / career_resume_profile_get / session_read_artifact。
3. 个别 run 仍触发 tool_loop_stagnation，但 hard safety 为 0，产品质量通过。
```

## 12. 第三阶段优化方案：前置阶段锁

当前剩余重复没有被前两阶段完全兜住，根因是已有保护仍偏后置：

```text
1. delegate_agents 复用依赖调用参数签名。
   当同一 job-fit 子任务换了 artifact_refs 形态、把 artifact id 写进 instruction，
   或产品 id 只出现在任务正文里时，exact signature 不一定能稳定命中。

2. job_agent 读完 JD / ResumeProfile / CareerProfile 后，
   还没有显式的 input snapshot complete 状态。
   因此模型在保存 JDAnalysis / JobFitReport 前，仍可能回到低层读取工具。

3. tool_loop_stagnation 是最后的止损边界。
   它能防止无限重复，但不能减少已经发生的 LLM 轮次。
```

第三阶段改为前置收敛：

```text
1. delegate_agents 增加语义签名：
   target_agent_id + phase + artifact ids + product ids + required outputs

   语义签名忽略：
   - instruction 的自然语言措辞
   - max_tool_rounds
   - wait

   对 job_fit 子任务，即使第二次委派把 artifact id 写进 instruction，
   也能识别为同一个 JD 匹配阶段。

2. job_agent 增加 input snapshot lock：
   当同一 child run 已经成功读取：
   - 当前任务要求的 artifact_refs
   - ResumeProfile
   - 当前 session 已有的 CareerProfile

   后续再调用 session_read_artifact / career_resume_profile_get /
   career_profile_get / get/list 类低层工具时，直接返回 recoverable block，
   并把下一步导向 career_jd_analysis_save 或 session_create_text_artifact。

3. 保持必要修复通道：
   - artifact 事实冲突后仍允许重新创建唯一匹配报告 artifact。
   - JobFitReport 未保存时不把失败或不完整 child 结果伪装成完成。
   - 已有 product record 的 idempotent reuse 仍保留。
```

验收：

```text
1. 确定性测试覆盖语义相同但参数形态不同的 delegate_agents 复用。
2. 确定性测试覆盖 job_agent 输入齐全后重复低层读取被阻断。
3. 定向回归通过。
4. 只跑一组 custom_resume 6x3 live smoke。
```

## 13. 第三阶段实现结果

最终保留的修复：

```text
1. delegate_agents 增加语义签名复用：
   - target_agent_id
   - phase
   - artifact ids
   - product ids
   - required outputs

   这样同一 job-fit 子任务即使把 artifact id 从 artifact_refs 挪到 instruction，
   也能被识别为同一语义任务。

2. job_agent 增加 input snapshot lock：
   当 JD artifact、ResumeProfile、当前 session 已有 CareerProfile 都已读过后，
   再调用 session_read_artifact / career_resume_profile_get / career_profile_get /
   get/list 类低层工具，会被 recoverable block，并导向 career_jd_analysis_save
   或 session_create_text_artifact。

3. job-fit 输入快照只把 JD artifact 当作必读 artifact：
   如果 main agent 同时把 resume artifact / 诊断 artifact 放进 artifact_refs，
   job_agent 不再被要求重复读取这些候选人资料；候选人事实以
   ResumeProfile / CareerProfile 为准。
```

明确撤回的尝试：

```text
1. 放宽 JDAnalysis 保存后的 runtime tool plan，
   让 career_resume_profile_get / career_profile_get 和 session_create_text_artifact
   同时可用。

   结果：r2 中 job_agent 更容易反复 get / 重复 save JDAnalysis，
   avg/max elapsed 和 stagnation 均变差，因此撤回。

2. 在输入快照未齐时前置阻断 career_jd_analysis_save。

   结果：r5 中模型多次重复 career_jd_analysis_save，而不是稳定转向
   career_profile_get，导致 soft budget / stagnation，撤回。
```

最终定向回归：

```text
uv run pytest tests/test_workflow_runtime_guard.py tests/test_runtime_tool_plan.py \
  tests/test_tool_reveal.py tests/test_career_tools.py tests/test_career_live_smoke_report.py \
  tests/test_tool_registry.py tests/test_agent_runtime.py -q
结果：通过

uv run mypy --explicit-package-bases app/runtime/workflow/guard.py app/runtime/workflow/tool_plan.py \
  tests/test_workflow_runtime_guard.py tests/test_runtime_tool_plan.py tests/test_agent_runtime.py
结果：Success
```

最终 live smoke：

```text
uv run python tools/smoke_career_live_flow.py \
  --runs 6 \
  --concurrency 3 \
  --max-tool-rounds 24 \
  --project-action custom_resume \
  --data-dir data/live_career_smoke_m26_input_locks_6x3_r6 \
  --quiet

结果：
  6/6 passed
  avg elapsed: 183.84s
  max elapsed: 231.89s
  avg_llm_calls: 25.3
  max_llm_calls: 30
  avg_tokens: 140,490
  max_tokens: 182,081
  duplicate_runs: 2/6
  hidden_runs: 1/6
  stagnation_runs: 0/6
  hard_safety_runs: 0/6
```

对比第二阶段通过结果：

```text
avg elapsed: 204.78s -> 183.84s
max elapsed: 223.57s -> 231.89s
avg_llm_calls: 27.2 -> 25.3
max_llm_calls: 31 -> 30
avg_tokens: 149,146 -> 140,490
duplicate_runs: 4/6 -> 2/6
hidden_runs: 5/6 -> 1/6
stagnation_runs: 2/6 -> 0/6
hard_safety_runs: 0/6 -> 0/6
```

结论：

```text
第三阶段有效，但不应继续用更强 guard 压 job_agent 的自然顺序。
当前最有价值的下一步不是继续加阻断规则，而是优化 main agent 在项目动作阶段
偶发 tool_search / career_application_get 重复，以及 job_agent 首轮任务指令的顺序表达。
```

## 14. 第四阶段优化方案：项目动作定制简历阶段锁

第三阶段后剩余的主要浪费点集中在 main agent 的 `custom_resume` 项目动作：

```text
career_application_get 成功前后，runtime plan 已经给出 next_allowed_tools，
但 guard 没有把它提升为阶段事实。

因此模型偶发会：
- 在已明确 application_id 且要求先读项目时继续 tool_search。
- career_application_get 成功后重复 career_application_get。
- CareerApplication 已读后尝试重新读取关联产品记录，或过早 merge。
```

本阶段不扩大到所有项目动作。投递前检查和面试准备可能需要创建 Markdown 报告、
更新 notes/risks/next_actions，不能简单压成 `create -> merge`。本阶段只处理
用户消息中明确包含：

```text
请先调用 career_application_get 读取项目
```

且当前意图是定制简历 / ResumeVersion 的场景。

实现边界：

```text
1. application_get 前：
   只允许 career_application_get。
   阻止 tool_search、delegate_agents、session 读取、产品 get/list/save、
   career_resume_version_create、career_application_merge。

2. application_get 后：
   只允许 career_resume_version_create。
   阻止重复 career_application_get、tool_search、低层读取、过早 merge。

3. career_resume_version_create 后：
   只允许 career_application_merge。
   阻止重复生成、重复读取、tool_search。

4. career_application_merge 后：
   进入 final answer ready，阻止继续搜索、读取或重复更新。
```

同时把 `pending_runtime_plan_after_application_get` 的定制简历分支收窄：

```text
CareerApplication 已读且 ResumeVersion 未创建时，
career_application_merge 也进入 discouraged_tools。
```

验收：

```text
1. 确定性测试覆盖 application_get 前 tool_search 被导向 application_get。
2. 确定性测试覆盖 application_get 后重复 get / tool_search 被导向 resume_version_create。
3. 确定性测试覆盖 resume_version_create 后重复 create 被导向 application_merge。
4. 定向回归通过。
5. 只跑一组 custom_resume 6x3 live smoke。
```

第一轮 live smoke 结果：

```text
data/live_career_smoke_m26_project_resume_gate_6x3_r1

结果：
  6/6 passed
  avg elapsed: 238.75s
  max elapsed: 352.42s
  avg_llm_calls: 25.7
  max_llm_calls: 28
  avg_tokens: 145,333
  max_tokens: 161,063
  duplicate_runs: 3/6
  hidden_runs: 2/6
  stagnation_runs: 0/6
  hard_safety_runs: 0/6
```

结论：r1 质量通过，但耗时变差，不能作为最终结果。

根因不是项目动作 guard 没有生效。run_003 中第二次
`career_application_merge` 已被新 guard 以
`main_project_resume_version_complete_final_answer` 阻断；真正问题在 runtime plan：

```text
career_resume_version_create 成功
  -> pending plan 正确要求 career_application_merge

career_application_merge 成功
  -> pending plan 被清空
  -> 下一轮可见工具面重新变宽
  -> 模型又尝试重复 career_application_merge
  -> guard 阻断后触发 final_answer_recovery
```

修正：

```text
pending_runtime_plan_from_successful_tool_result 增加 career_application_merge 分支。

当 previous_pending_plan.phase == resume_version
且 career_application_merge 是 required/completion tool 时：
  -> 返回 final_answer_ready=True
  -> missing_outputs=[]
  -> next_allowed_tools=[]
  -> discouraged_tools 包含 tool_search / career_application_get /
     career_application_merge / career_resume_version_create
```

第二轮 live smoke 结果：

```text
data/live_career_smoke_m26_project_resume_gate_6x3_r2

结果：
  6/6 passed
  avg elapsed: 229.42s
  max elapsed: 359.91s
  avg_llm_calls: 27.5
  max_llm_calls: 35
  avg_tokens: 150,718
  max_tokens: 206,260
  duplicate_runs: 2/6
  hidden_runs: 5/6
  stagnation_runs: 1/6
  hard_safety_runs: 0/6
```

r2 结论：

```text
1. 项目动作链路的正确性稳定：
   6/6 均完成 career_application_get -> career_resume_version_create -> career_application_merge。

2. r1 中的重复 career_application_merge 根因已修正：
   merge 成功后 runtime plan 进入 final_answer_ready；
   run_006 可见工具面只剩 memory_write，没有再次暴露 application/resume 写工具。

3. 但整体效率没有改善到可接受基线：
   r2 的长尾主要来自 run_002 的 job_agent 重复 get/save 和 stagnation，
   以及部分项目动作中模型在 required tool 已可见时仍尝试 tool_search / 未揭示工具。

4. 因此第四阶段当前只能算“修正了一个真实状态推进缺口”，
   不能算整体效率优化完成。
```

下一步建议：

```text
不要继续单纯加 main guard。

优先处理两个更底层问题：
1. required tool 已可见时，模型仍发起 schema_search_only 的运行时处理；
   现在只是提醒并继续，可能浪费 1-2 轮。

2. job_agent 在 JD fit 中偶发重复 career_profile_get /
   career_resume_profile_get / session_create_text_artifact，
   需要继续从 input snapshot 与 report artifact 状态推进查根因。
```
