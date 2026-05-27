# M38：上下文与最终答复成本收敛方案

> 状态：M38-A 成本画像保留；application_id 规范化修复保留。M38-B/D 上下文压缩、delegate actionable snapshot、以及后续未提交的 M38-C/C.1 final completion fast path 已决定回退，原因是它们虽然能压 token / recovery，但把主流程继续推向多层 compact / guard / fast-path 分支，代码结构变重，不利于下一步 deterministic workflow executor。本文承接 M37。M37 已把重复工具调用和重复保存收敛到 `duplicate_runs=0/6`；后续优化不再继续追加 guard，而应把确定性 workflow 从模型决策中移出。

## 1. 当前基线

数据来源：

```text
data/live_career_smoke_m37_task_graph_idempotency_6x3_r1
runs=6
concurrency=3
passed=6/6
duplicate_runs=0/6
harmful_duplicate_runs=0/6
recovery_duplicate_runs=0/6
hidden_runs=0/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

成本基线：

```text
avg_elapsed=182.03s
max_elapsed=221.91s
avg_llm_calls=20.5
max_llm_calls=23
avg_tokens=122650
max_tokens=140370
```

按 session 根 `events.jsonl` 统计，不把 `agents/*/events.jsonl` 的镜像事件重复加总：

```text
avg_total_tokens=122650
avg_prompt_tokens=106390
avg_completion_tokens=16260
avg_llm_calls=20.5
```

按 agent 拆分：

```text
agent_main:
  avg_tokens=70373
  max_tokens=89510
  avg_calls=12.7
  max_calls=15

job_agent:
  avg_tokens=36441
  max_tokens=43922
  avg_calls=4.3
  max_calls=5

resume_agent:
  avg_tokens=15836
  max_tokens=20052
  avg_calls=3.5
  max_calls=4
```

按 phase 拆分：

```text
tool_loop:
  avg_tokens=97191
  max_tokens=120992

final_answer_recovery:
  avg_tokens=25459
  max_tokens=37976
```

这里的 `final_answer_recovery` 不全是异常恢复；它现在也承担“阶段完成后的最终表述生成/修复”。但从成本角度看，它已经占到平均总 token 的约 20.8%。

prompt 估算组成：

```text
system_prompt_estimate_tokens        avg=65437
messages_estimate_tokens             avg=38030
tools_estimate_tokens                avg=7546
workflow_rules_estimate_tokens       avg=5745
tool_pending_message_estimate_tokens avg=13395
tool_state_message_estimate_tokens   avg=1212
```

system prompt 主要 section：

```text
agent_identity                 avg=12550
assigned_task_context          avg=5804
workflow_rules                 avg=5745
tool_catalog                   avg=5017
current_runtime_tool_plan      avg=3700
assigned_agent_tasks           avg=2690
output_format_rules            avg=2433
memory_access_rules            avg=2283
soul_identity                  avg=2261
current_career_flow_state      avg=2089
active_artifacts               avg=1950
current_workflow_phase         avg=1921
skill_catalog                  avg=1450
child_agent_result_summaries   avg=952
```

结论：

```text
现在最大矛盾已经从“重复工具调用”切换成：
1. main-agent 上下文仍偏重；
2. final_answer_recovery 成本偏高；
3. child task context / tool pending messages 仍携带较多可结构化压缩的信息；
4. 已完成阶段的最终答复还过度依赖 LLM 生成。
```

## 2. 不继续做的方向

### 2.1 不继续补单点 guard

M37 已经验证：

```text
duplicate_runs=0/6
hidden_runs=0/6
stagnation_runs=0/6
```

继续围绕某个工具是否重复调用做拦截，收益低，且容易重新进入长尾补丁模式。

### 2.2 不直接压缩 AGENT.md / identity

历史上压缩 agent identity 后，child-agent 一次性完成率下降，导致轮次反增。

M38 不把第一步放在删身份文档，而是先把代码可控的上下文、child summary、最终答复路径做结构化收敛。

## 3. 优化目标

硬质量目标：

```text
passed=6/6
duplicate_runs=0/6
harmful_duplicate_runs=0/6
hidden_runs=0/6
stagnation_runs=0/6
hard_safety_runs=0/6
career_applications=1/run
resume_versions=1/run
```

成本目标：

```text
avg_llm_calls <= 18
max_llm_calls <= 21
avg_tokens <= 105000
max_tokens <= 125000
avg_final_answer_recovery_tokens <= 14000
```

如果 live 模型输出波动导致 token 未达标，但 `final_answer_recovery` 明显下降且质量稳定，可以进入下一小步；不能为了 token 降低牺牲产品记录完整性。

## 4. 方案切分

### M38-A：成本画像固化到 smoke 报告

状态：已实现，待随下一组 live smoke 使用。

先把本轮手工统计变成固定 smoke 输出，避免后续只看总 token。

新增指标：

```text
tokens_by_agent
llm_calls_by_agent
tokens_by_phase
final_answer_recovery_tokens
final_answer_recovery_calls
prompt_parts:
  system_prompt_estimate_tokens
  messages_estimate_tokens
  tools_estimate_tokens
  workflow_rules_estimate_tokens
  tool_pending_message_estimate_tokens
  tool_state_message_estimate_tokens
top_system_prompt_sections
```

验收：

```text
tools/smoke_career_live_flow.py 报告直接打印上述指标；
tests/test_career_live_smoke_report.py 覆盖格式和聚合逻辑；
统计口径只读 session 根 events.jsonl，不能重复加 agents/* 镜像事件。
```

实现记录：

```text
tools/smoke_career_live_flow.py
  - efficiency_summary 增加：
    - llm_calls_by_phase
    - llm_tokens_by_phase
    - total_prompt_tokens
    - total_completion_tokens
    - final_answer_recovery_tokens
    - final_answer_recovery_calls
    - final_answer_recovery_tokens_by_agent
    - llm_prompt_parts
    - llm_system_prompt_sections
  - print_report 每个 run 新增 cost_profile 行。
  - 聚合效率摘要新增：
    - avg_prompt_tokens
    - avg_completion_tokens
    - avg/max_final_answer_recovery_tokens
    - avg_final_answer_recovery_calls

tests/test_career_live_smoke_report.py
  - 覆盖 phase tokens、prompt parts、system prompt sections、
    final_answer_recovery 聚合与报告输出。
```

验证：

```text
uv run pytest -q tests/test_career_live_smoke_report.py
=> passed

uv run mypy --explicit-package-bases tools/smoke_career_live_flow.py tests/test_career_live_smoke_report.py
=> Success: no issues found in 2 source files
```

### M38-B：child result summary 压缩

状态：已实现，待随下一组 live smoke 验证收益。

问题：

```text
delegate_agents 返回的 child summary/answer 经常包含整段 Markdown 报告、表格和解释。
main-agent 实际只需要：
  product_refs
  output_artifact_refs
  score/recommendation
  top gaps/risks/next_actions
  是否已创建 JobFitReport/ResumeProfile/ResumeVersion
```

改法：

```text
在 AgentTaskResult.to_payload 或 tool_result_view 层增加 main-agent 可见 compact result。

保留 durable event 原文，供审计和 debug；
喂给 main-agent 的 tool observation 只放结构化摘要。
长正文通过 artifact_id 引用，不再回灌到 main 上下文。
```

实现记录：

```text
app/runtime/agent/tool_result_view.py
  - delegate_agents / agent_task_status 的 model-visible result 不再保留 answer_preview。
  - 每个 child result 保留：
    - task_id / target_agent_id / status / child_run_id
    - summary 短信号摘要
    - summary_omitted / answer_omitted 字符统计
    - extracted_ids
    - artifact_refs / output_artifact_refs / product_refs
    - followup_hints / next_steps / error

app/runtime/context/short_term.py
  - child_agent_result_summaries system prompt 不再直接回放完整 Markdown summary。
  - summary 只取前 4 行信号文本并限制长度。
  - next_steps / refs 做 item 级长度限制。
  - 从 summary 中补充 summary_refs，同时过滤 jd_analysis_id / artifact_id 这类字段名。

没有改 AgentTaskResult.to_payload：
  - tool ledger / task store 仍保留完整 summary 和 answer，便于审计与 debug。
  - 只收敛 model-visible 层。
```

验证：

```text
uv run pytest -q tests/test_tool_result_view.py tests/test_context_assembler.py tests/test_agent_invocation_service.py
=> passed

uv run mypy --explicit-package-bases app/runtime/agent/tool_result_view.py app/runtime/context/short_term.py tests/test_tool_result_view.py tests/test_context_assembler.py
=> Success: no issues found in 4 source files

uv run pytest -q
=> passed
```

风险：

```text
压得过短可能让 main-agent 最终答复缺少用户可读细节。
解决方式：保留 score/gaps/risks/next_actions 的短摘要，
需要正文时引用 artifact_id。
```

验收：

```text
child_agent_result_summaries tokens 下降；
messages_estimate_tokens 下降；
JD 匹配最终答复仍包含 job_fit_report_id/report_artifact_id/application_id。
```

### M38-C：final answer fast path

问题：

```text
当前 final_answer_recovery 平均 25459 tokens。
当 runtime_plan.final_answer_ready=true 且 completed_refs 完整时，
系统其实已经知道该回答什么。
```

改法：

```text
为已完成的 career workflow 阶段增加 deterministic final answer fast path：

resume_diagnosis:
  输出 ResumeProfile、诊断 artifact、CareerProfile 的 refs 和下一步。

jd_fit:
  输出 JDAnalysis、JobFitReport、report artifact、CareerApplication 的 refs，
  以及 recommendation/score/gaps 的短摘要。

resume_version:
  输出 ResumeVersion、artifact、CareerApplication merge 状态。

application_action:
  输出变更后的 application 状态、next_actions 或 notes refs。
```

触发条件：

```text
pending_runtime_plan.final_answer_ready == true
required refs 完整
最近一轮没有 tool failure
没有硬安全/事实冲突修复待处理
```

行为：

```text
优先使用 deterministic answer；
只有缺少用户可读摘要字段时，再调用 LLM 做轻量润色。
```

验收：

```text
final_answer_recovery_tokens 降低 40% 以上；
final answer 不包含内部 runtime 文本、伪工具调用或弱答复；
tests/test_agent_runtime.py 覆盖 completed workflow fast path。
```

### M38-D：tool pending message 压缩

状态：已实现，待随下一组 live smoke 验证收益。

问题：

```text
tool_pending_message_estimate_tokens avg=13395，max=23589。
写 artifact / resume version 时，工具调用参数里可能携带完整 Markdown content；
即使 tool result 已 compact，pending exchange 仍可能保留大段正文。
```

改法：

```text
ToolContextWindow 中对高体积参数做参数级压缩：
  content
  markdown
  body
  report
  resume_content

保留：
  content_hash
  content_chars
  first_heading
  artifact_id / record_id
  title
  output_kind

不要改 durable event 和 ledger，只改 model-visible message。
```

实现记录：

```text
app/runtime/agent/tool_context_window.py
  - _compact_arguments 从单一 content 扩展到 content / markdown / body / report / resume_content。
  - 大正文参数在 compact replay 中只保留：
    - <field>_omitted.chars
    - <field>_chars
    - <field>_hash
    - first_heading / <field>_first_heading
    - 失败修复时才保留 <field>_preview
  - 参数数量上限按原始字段计数，不因压缩元数据键数增加而提前丢字段。

tests/test_tool_context_window.py
  - 覆盖成功工具调用参数 replay 的 hash / chars / heading。
  - 覆盖失败长正文参数仍给 preview 便于修复。
  - 覆盖 markdown / body / report / resume_content 不再原文回放。
```

补充发现：

```text
content 参数在 M37 前已经有基础省略，所以 M38-D 是补齐通用大正文字段和审计元数据，不是当前最大收益点。
M37 pending 剩余高值里还有 provider reasoning_content 回放与 delegate child result 摘要。
reasoning_content 当前在 Mimo thinking 模式下属于协议兼容字段，不能在本步贸然删除；
delegate child result 属于 M38-B。
```

验证：

```text
uv run pytest -q tests/test_tool_context_window.py tests/test_career_live_smoke_report.py
=> passed

uv run mypy --explicit-package-bases app/runtime/agent/tool_context_window.py tests/test_tool_context_window.py
=> Success: no issues found in 2 source files

uv run pytest -q
=> passed
```

验收：

```text
tool_pending_message_estimate_tokens 明显下降；
session_create_text_artifact / career_resume_version_create 的后续工具仍能拿到必要 refs；
不影响 artifact 实际保存内容。
```

### M38-E：assigned task context 分层

问题：

```text
assigned_task_context avg=5804。
它对 child-agent 很重要，不能直接删除；
但其中 provided_artifacts/provided_records 可以按阶段分层。
```

改法：

```text
job_agent:
  默认只放 JD preview + ResumeProfile/CareerProfile compact snapshot；
  不放完整诊断报告正文。

resume_agent:
  放 resume artifact preview；
  不放无关 JD/application refs。

main-agent:
  不重复注入 child task context，只消费 compact child result。
```

验收：

```text
assigned_task_context tokens 下降；
job_agent first-pass 成功率不下降；
M37 的 duplicate/hidden/stagnation 不回归。
```

## 5. 建议实施顺序

推荐顺序：

```text
1. M38-A：先把成本画像固化到 smoke 报告。
2. M38-D：压缩 tool pending message，风险最低，收益直接。
3. M38-B：压缩 child result summary，降低 main-agent messages。
4. M38-C：final answer fast path，收益最大，但需要最严格质量门禁。
5. M38-E：task context 分层，最后做，因为它影响 child-agent 一次性完成率。
```

不建议一上来做 M38-C/E：

```text
final answer 和 child task context 都直接影响用户可见结果和任务成功率；
先做可观测和低风险压缩，再动完成态生成路径。
```

## 6. 验证计划

每个小步都跑：

```text
uv run pytest -q
uv run mypy --explicit-package-bases <changed files and related tests>
```

阶段验证：

```text
1 组 6x3 live smoke：
uv run python tools/smoke_career_live_flow.py \
  --runs 6 \
  --concurrency 3 \
  --data-dir data/live_career_smoke_m38_<step>_6x3_r1
```

验收输出必须包含：

```text
passed
avg/max elapsed
avg/max llm calls
avg/max tokens
tokens_by_agent
tokens_by_phase
final_answer_recovery_tokens
prompt_parts
duplicate/hidden/stagnation/hard_safety
```

## 7. 回滚边界

任一小步出现以下情况，应回滚或暂停：

```text
passed < 6/6
harmful_duplicate_runs > 0
hidden_runs > 0
stagnation_runs > 0
hard_safety_runs > 0
final answer 出现内部 runtime 文本或伪工具调用
CareerApplication / ResumeVersion 缺失
child-agent first-pass 明显变差
```

## 8. 本阶段原则

```text
M38 的核心不是继续“管住模型不要乱调工具”，
而是减少模型需要看的东西、减少完成态还要调用模型的次数。

代码负责保留完整结构化事实；
模型只在确实需要自然语言生成时介入。
```

## 9. M38-A/B/D Live Smoke 结果

数据目录：

```text
data/live_career_smoke_m38_abd_6x3_r1
runs=6
concurrency=3
passed=6/6
```

结果：

```text
avg_elapsed=246.88s
max_elapsed=435.29s
avg_llm_calls=22.2
max_llm_calls=25
avg_tokens=130456
max_tokens=159620
avg_prompt_tokens=112126
avg_completion_tokens=18330
avg_final_answer_recovery_tokens=27912
max_final_answer_recovery_tokens=40960
avg_final_answer_recovery_calls=4.5
duplicate_runs=2/6
harmful_duplicate_runs=0/6
recovery_duplicate_runs=2/6
hidden_runs=1/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

相对 M37：

```text
avg_elapsed: 182.03s -> 246.88s
avg_llm_calls: 20.5 -> 22.2
avg_tokens: 122650 -> 130456
avg_final_answer_recovery_tokens: 25459 -> 27912
```

有效下降的部分：

```text
tool_pending_message_estimate_tokens: 13395 -> 12682
child_agent_result_summaries: 952 -> 366
assigned_task_context: 5804 -> 5325
```

回归的部分：

```text
agent_main tokens: 70373 -> 79236
tool_loop tokens: 97191 -> 102544
final_answer_recovery tokens: 25459 -> 27912
messages_estimate_tokens: 38030 -> 39939
```

长尾样本：

```text
Run 1 elapsed=435.29s
  简历诊断阶段 292.02s
  JD 匹配阶段 104.09s
  JD 阶段有 session_create_text_artifact blocked -> succeeded 的恢复路径

Run 3 elapsed=256.98s
  duplicate_tools:
    job_agent:session_create_text_artifact:title=岗位匹配报告 - AI 应用开发工程师
  hidden_tools:
    agent_main:tool_search:tool_hidden_by_runtime_plan

Run 5 elapsed=329.34s
  duplicate_tools:
    agent_main:session_read_artifact:artifact_7a0847bc8304
```

根因判断：

```text
M38-B/D 的压缩本身确实减少了局部上下文；
但 delegate_agents 的 compact result 变短后，main-agent 在 resume_diagnosis 后更容易认为还缺少可执行事实，
转而调用 tool_search / session_read_artifact 读取 diagnosis artifact。

当前 delegate compact view 仍带 full_result_hint：
  如需更多细节，请基于保留的 id / artifact_id 继续读取。

这个提示对 retrieval/product read 合理，但对 career flow 的 child result 不够精确：
main-agent 需要的是可执行产品事实，而不是诊断 artifact 正文。

因此 M38-C final answer fast path 暂停，先修正 M38-B 的 compact payload：
  1. resume_agent child result 要显式提供 career_profile_merge 所需的最小事实快照；
  2. job_agent child result 要显式提供 application_create 所需的 jd_analysis/job_fit_report/report_artifact refs 和 score/recommendation；
  3. delegate compact full_result_hint 改成工具特定 next_input_hint，优先使用 product_refs / output_artifact_refs，不鼓励读诊断 artifact；
  4. 保留完整 answer 在 ledger/task store，不回灌给模型。
```

已做修正：

```text
app/runtime/agent/tool_result_view.py
  - delegate_agents / agent_task_status 不再返回泛化 full_result_hint。
  - 顶层返回 next_input_hint：
    优先使用 product_refs / output_artifact_refs / extracted_ids / actionable_snapshot；
    不要为了确认已完成 child work 而读取 child artifacts。
  - resume_agent actionable_snapshot：
    resume_profile_id
    diagnosis_artifact_id
    preferred_read_tool_if_facts_missing=career_resume_profile_get
    career_profile_input_facts（如果 child answer 中存在可抽取信号）
  - job_agent actionable_snapshot：
    jd_analysis_id
    job_fit_report_id
    report_artifact_id
    preferred_read_tool_if_score_missing=career_job_fit_report_get
    fit_summary（如果 child answer 中存在可抽取信号）

app/runtime/context/short_term.py
  - child_agent_result_summaries 增加 next_hint：
    resume_agent 缺 profile facts 时读 career_resume_profile_get，不读 diagnosis artifact；
    job_agent 缺 score 时读 career_job_fit_report_get，不读 report artifact。
```

验证：

```text
uv run pytest -q tests/test_tool_result_view.py tests/test_context_assembler.py tests/test_agent_invocation_service.py
=> passed

uv run mypy --explicit-package-bases app/runtime/agent/tool_result_view.py app/runtime/context/short_term.py tests/test_tool_result_view.py tests/test_context_assembler.py
=> Success: no issues found in 4 source files
```

## 10. Delegate Snapshot 修正后 Live Smoke

数据目录：

```text
data/live_career_smoke_m38_delegate_snapshot_6x3_r1
runs=6
concurrency=3
passed=5/6
```

结果：

```text
avg_elapsed=190.80s
max_elapsed=217.13s
avg_llm_calls=20.0
max_llm_calls=23
avg_tokens=116875
max_tokens=131791
avg_prompt_tokens=101364
avg_completion_tokens=15511
avg_final_answer_recovery_tokens=26957
max_final_answer_recovery_tokens=39515
avg_final_answer_recovery_calls=4.2
duplicate_runs=2/6
harmful_duplicate_runs=1/6
recovery_duplicate_runs=1/6
hidden_runs=0/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

正向信号：

```text
相对上一组 M38-A/B/D：
  avg_elapsed: 246.88s -> 190.80s
  avg_llm_calls: 22.2 -> 20.0
  avg_tokens: 130456 -> 116875
  hidden_runs: 1/6 -> 0/6

首阶段不再出现上一组的 session_read_artifact 长尾；
JD 阶段大部分 run 不再重复 session_create_text_artifact。
```

失败与根因：

```text
Run 1 failed:
  career_application_create 先后两次失败：
    application_id has invalid format: application_-__ai_9e63c0a0
    application_id has invalid format: application_-__ai_4861ef28
  第三次传 application_id=ca-zhangsan-001 后成功。

根因不是 delegate snapshot hint，而是 career_application_create 的默认 id 生成器：
  company=缺失-未明确说明
  position=AI 应用开发工程师
  slug 归一化保留了开头的 hyphen，生成 application_-__ai_...
  但 CareerApplication id schema 要求 application_ 后首字符必须是字母数字。
```

已做修复：

```text
app/tools/builtin_tools/career.py
  - 新增 _normalize_prefixed_id_stem。
  - _new_application_id 使用同一套 stem 归一化：
    strip leading/trailing "_" and "-"
    空 stem 回退 UUID 型 application id
    保证 stem 首字符为字母数字
  - _optional_prefixed_id 同步使用该归一化，避免模型传入 "-foo" 一类 id stem 后生成非法 prefixed id。

tests/test_career_tools.py
  - 新增 test_application_create_generates_valid_id_from_placeholder_company。
```

验证：

```text
uv run pytest -q tests/test_career_tools.py tests/test_tool_result_view.py tests/test_context_assembler.py tests/test_agent_invocation_service.py
=> passed

uv run mypy --explicit-package-bases app/tools/builtin_tools/career.py app/runtime/agent/tool_result_view.py app/runtime/context/short_term.py tests/test_career_tools.py tests/test_tool_result_view.py tests/test_context_assembler.py
=> Success: no issues found in 6 source files

uv run pytest -q
=> passed
```

下一步：

```text
需要再跑一组 6x3 live smoke 验证 ID 修复后的最终结果。
如果 passed 回到 6/6 且 avg_tokens 维持在本组量级，则 M38-B/D 修正可以保留；
再考虑进入 M38-C final answer fast path。
```

## 11. ID 修复后 Live Smoke

数据目录：

```text
data/live_career_smoke_m38_delegate_snapshot_idfix_6x3_r1
runs=6
concurrency=3
passed=6/6
```

结果：

```text
avg_elapsed=199.49s
max_elapsed=219.93s
avg_llm_calls=20.8
max_llm_calls=23
avg_tokens=119136
max_tokens=135418
avg_prompt_tokens=103482
avg_completion_tokens=15654
avg_final_answer_recovery_tokens=32199
max_final_answer_recovery_tokens=42553
avg_final_answer_recovery_calls=5.3
duplicate_runs=0/6
harmful_duplicate_runs=0/6
recovery_duplicate_runs=0/6
hidden_runs=0/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

相对 M37：

```text
avg_tokens: 122650 -> 119136
avg_llm_calls: 20.5 -> 20.8
avg_elapsed: 182.03s -> 199.49s
tool_loop tokens: 97191 -> 86938
final_answer_recovery tokens: 25459 -> 32199
tool_pending_message_estimate_tokens: 13395 -> 11270
child_agent_result_summaries: 952 -> 342
```

判断：

```text
M38-B/D + delegate actionable snapshot + application_id 修复可以保留：
  - passed 回到 6/6；
  - duplicate/harmful/recovery/hidden/stagnation/hard_safety 全部为 0；
  - tool_loop 和 main-agent tokens 明显下降；
  - child result summary 与 pending tool message 压缩有效。

但总耗时仍高于 M37，主要瓶颈已经转向 final_answer_recovery：
  - avg_final_answer_recovery_tokens 32199，高于 M37 的 25459；
  - avg_final_answer_recovery_calls 5.3；
  - final answer 阶段仍承担过多完成态表达/修复。
```

下一步：

```text
可以进入 M38-C，但要按“质量优先”做：
  1. 不直接删除 final answer LLM；
  2. 先做 deterministic completion payload；
  3. 只有 required refs 完整、最近无工具失败、无 rejected answer 时走 fast path；
  4. 缺少用户可读摘要时才用轻量 LLM 润色；
  5. 继续用 6x3 live smoke 验证 final_answer_recovery 是否下降，且最终回答质量不退化。
```

## 12. 回退决定：停止上下文压缩补丁路线

回退边界：

```text
保留：
  - M38-A 成本画像能力；
  - application_id 规范化修复；
  - M37 的 task graph / ledger / idempotency / workflow guard 基线。

回退：
  - M38-B child result summary 压缩；
  - M38-D tool pending message 参数级压缩；
  - delegate actionable_snapshot / next_input_hint；
  - 未提交的 M38-C / M38-C.1 final answer completion fast path。
```

原因：

```text
M38-B/D/C 的局部指标有改善，尤其 token 和 final answer recovery；
但整体路线开始偏向“发现一个模型偏差就加一层 compact / suppress / fast path”。

这类逻辑能挡错，也能压一部分 token，但不会减少确定性步骤里的模型参与。
结果是：
  - 代码层次变重；
  - 行为解释成本变高；
  - live smoke 仍会出现耗时长尾；
  - 后续 deterministic workflow executor 会被这些分支干扰。
```

回退后的下一步方向：

```text
不继续做“让模型少看一点，然后希望它少犯错”。
改为：
  - runtime 维护 workflow state；
  - 固定链路由 deterministic executor 执行；
  - 模型只负责无法确定的内容生成或质量判断。

优先候选：
  resume_version project-action

固定链路：
  career_application_get
  career_resume_version_create
  career_application_merge

当 application_id / resume_profile_id / jd_analysis_id / job_fit_report_id 已齐时，
runtime 不再让模型逐步选择这三个工具；
只在生成 resume_version content / change_summary / keyword_strategy / risk_notes 时调用模型，
并由工具 schema / product facts 做事实边界约束。
```
