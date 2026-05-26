# M30 Main Agent 确定性工具面收敛方案

> 状态：已实现并通过一组 6x3 live smoke。本文承接 M27/M28/M29。M29 已解决 job_agent 低层重复读取导致的 stagnation；M30 不继续补 job_agent 低层 guard，而是收敛 main-agent 在确定性 workflow 阶段仍调用 `tool_search` / `memory_write` 带来的 LLM 轮次和 token 浪费。

## 1. 当前基线

最终 M29 live smoke：

```text
data/live_career_smoke_m29_job_agent_refs_6x3_r3
runs=6 concurrency=3 project_action=custom_resume
passed=6/6
avg_llm_calls=24.7
max_llm_calls=26
avg_tokens=137773
max_tokens=155538
duplicate_runs=1/6
hidden_runs=5/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

M29 的有效成果：

- job_agent 低层 `session_read_artifact` / `career_resume_profile_get` / `career_profile_get` 重复导致的 stagnation 已消失。
- `career_job_fit_report_save` 前的 `known_refs` 不再丢失。
- ToolGateway 已改为 `state block -> guard -> ledger reuse -> execute`，避免 ledger 复用旧结果压过 workflow guard。

剩余主要浪费：

```text
main-agent 在 runtime plan 已明确下一步工具时，仍偶发调用 tool_search；
部分项目动作阶段还会出现 memory_write；
系统能 block/hidden，但已经消耗了一轮 LLM。
```

## 2. 为什么不能继续按单个工具打补丁

当前 `_visible_tool_definitions_for_runtime_plan()` 已经做了一层控制：

```text
pending_runtime_plan 存在
required tool 已可见
=> 隐藏 discouraged tools 和 tool_search
```

但 live smoke 仍有 `hidden_runs=5/6`。这说明残留问题不是简单的“schema 还暴露着”，而是：

```text
模型在前几轮曾看过 tool_search / memory_write；
后续即使本轮 schema 不再包含这些工具，模型仍可能从上下文惯性里调用旧工具名；
runtime 再返回 hidden/block 结果；
模型下一轮才修正。
```

所以 M30 不能只加：

```text
如果 tool_search 被调用，就 block。
```

因为这已经在发生了。真正要减少 LLM 轮次，需要把确定性阶段的模型输入本身变短、变硬、变少歧义。

## 3. 目标

M30 的目标是：

```text
当 workflow 已收敛到唯一下一步工具时，main-agent 的下一轮模型输入只围绕该工具展开，
不再携带容易诱导 tool_search / memory_write 的旧工具上下文。
```

目标指标：

```text
hidden_runs 从 5/6 降到 <= 2/6
stagnation_runs 保持 0/6
hard_safety_runs 保持 0/6
passed 保持 6/6
max_llm_calls 不高于 26
```

不把 avg_tokens 作为唯一硬指标，因为 live 模型输出长度波动较大；但如果 hidden runs 降低，平均 token 应该跟随下降。

## 4. 实现方向

### 4.1 确定性阶段进入 strict tool mode

新增一个判定：

```python
strict_runtime_tool_mode =
    pending_runtime_plan 有唯一 required tool
    and required tool schema 已可见
    and pending_runtime_plan.final_answer_ready != True
```

strict mode 下：

```text
visible tools = required/completion tools
不再保留 tool_search
不再保留 memory_write
不再保留其它 always_visible 工具
```

当前代码已经隐藏了 `tool_search`，但还会先从 `tool_reveal_state.visible_definitions()` 继承历史可见工具，再过滤 discouraged。M30 要改成白名单式：

```text
非 strict: 当前逻辑
strict: 只返回 completion_tools 对应 definition
```

### 4.2 strict mode 下压缩工具上下文窗口

只隐藏 schema 不够，因为模型仍可能受上一轮 tool_search/tool result 影响。

strict mode 下，`ToolContextWindow` 应追加更强的 runtime notice，并避免继续把旧的 schema 搜索结果作为主要上下文信号：

```text
当前 workflow 已锁定唯一下一步工具：X。
本轮没有工具搜索阶段。
不要调用 tool_search / memory_write / get/list。
直接调用 X。
```

对 project action，notice 还要带参数骨架：

```text
career_application_get -> application_id
career_resume_version_create -> base_resume_profile_id / target_jd_analysis_id / evidence_refs / content
career_application_merge -> application_id / updates.resume_version_ids
```

这些内容已经有 `required_tool_call_hint`，M30 要确保 strict mode 的 prompt 一定包含 hint。

### 4.3 hidden tool result 不再推进为“新计划”

现在 hidden tool result 会被转成 workflow result，再 merge 回 `pending_runtime_plan`。这保证正确性，但也会把 hidden 工具调用变成一条新的工具观察，增加上下文。

M30 中，对于 strict mode 下的 hidden `tool_search` / `memory_write`：

```text
只记录事件；
模型可见内容使用更短的 deterministic correction；
不重复展开完整 known_refs；
不把它当作有效进展；
不生成冗长 block payload。
```

保留完整事件日志，减少喂给模型的 token。

### 4.4 项目动作三步状态机收紧

`custom_resume` 的 project-action 固定链路是：

```text
career_application_get
career_resume_version_create
career_application_merge
```

当前 M29 以后仍能看到 project action 中的 `tool_search` hidden。M30 要让这三步在 runtime plan 中更明确：

```text
application_read missing:
  only career_application_get

resume_version missing:
  only career_resume_version_create

application_resume_version_link missing:
  only career_application_merge
```

只要 required refs 已齐，就不再进入 schema search。

### 4.5 memory_write 前置降噪

guard 当前能阻止把 workflow 临时状态写入 memory，但这仍然是 post-hoc。

M30 strict mode 下：

```text
required output 未完成时，不暴露 memory_write。
final_answer_ready 后，也不暴露 memory_write。
```

这样避免 main-agent 在项目动作完成前把“当前已经完成了什么”写入 memory。

## 5. 需要修改的代码

预计修改范围：

```text
app/runtime/agent_runtime.py
  - 新增 strict runtime tool mode 判定
  - 改造 _visible_tool_definitions_for_runtime_plan 为白名单模式
  - strict mode 下插入更短、更硬的 runtime notice

app/runtime/workflow/tool_plan.py
  - 确保 runtime_plan_notice 对唯一 required tool 输出 required_tool_call_hint
  - project-action plan 的 next_action / discouraged_tools 更明确

app/runtime/agent/tool_reveal.py
  - hidden_tool_result 支持 strict correction 的短 payload

app/runtime/agent/tool_result_view.py
  - 对 strict hidden result 做更短的 model-facing compact
```

预计测试：

```text
tests/test_agent_runtime.py
tests/test_runtime_tool_plan.py
tests/test_tool_reveal.py
tests/test_tool_result_view.py
```

## 6. 验证方案

先跑定向测试：

```text
uv run pytest tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_tool_reveal.py tests/test_tool_result_view.py -q
```

再跑 M27-M29 回归子集：

```text
uv run pytest \
  tests/test_tool_call_ledger.py \
  tests/test_tool_policy.py \
  tests/test_tool_gateway.py \
  tests/test_agent_runtime.py \
  tests/test_runtime_tool_plan.py \
  tests/test_tool_reveal.py \
  tests/test_workflow_runtime_guard.py \
  tests/test_career_tools.py \
  tests/test_agent_task_runtime.py \
  tests/test_career_live_smoke_report.py \
  tests/test_tool_result_view.py \
  -q
```

类型检查：

```text
uv run mypy --explicit-package-bases \
  app/runtime/agent_runtime.py \
  app/runtime/workflow/tool_plan.py \
  app/runtime/agent/tool_reveal.py \
  app/runtime/agent/tool_result_view.py \
  tests/test_agent_runtime.py \
  tests/test_runtime_tool_plan.py \
  tests/test_tool_reveal.py \
  tests/test_tool_result_view.py
```

最终只跑一组 live smoke：

```text
uv run python tools/smoke_career_live_flow.py \
  --runs 6 \
  --concurrency 3 \
  --max-tool-rounds 24 \
  --project-action custom_resume \
  --data-dir data/live_career_smoke_m30_strict_tool_surface_6x3_r1 \
  --quiet
```

## 7. 风险与边界

### 风险 1：过早 strict 导致模型缺 schema

边界：

```text
只有 required tool 已可见才进入 strict mode。
如果 required tool 不可见，仍保留 tool_search。
```

### 风险 2：content 生成类工具需要模型自由生成

例如：

```text
session_create_text_artifact
career_resume_version_create
```

strict mode 不能自动执行这些工具；仍需要模型生成正文。M30 只收窄工具面，不替模型生成内容。

### 风险 3：过短 hidden correction 影响可恢复性

边界：

```text
事件日志保留完整 payload；
模型可见内容压短；
只有 strict hidden tool 使用短 payload。
```

### 风险 4：memory_write 合法偏好记忆被误隐藏

边界：

```text
workflow required output 未完成时隐藏 memory_write；
普通对话或无 pending runtime plan 时不改变 memory_write 行为。
```

## 8. 成功标准

M30 成功标准：

```text
custom_resume 6x3 passed=6/6
stagnation_runs=0/6
hard_safety_runs=0/6
hidden_runs <= 2/6
max_llm_calls <= 26
project-action 不再稳定出现 tool_search hidden
```

如果 hidden_runs 没明显下降，说明下一步不应继续调 schema 可见性，而要考虑更强的 deterministic action runner：在某些无正文生成的 required tool 上直接执行工具或生成结构化 tool call。

## 9. 实现结果

已完成代码改动：

```text
app/runtime/agent_runtime.py
  - 增加 strict runtime tool mode
  - 单 required tool 且 schema 已可见时，只向模型暴露该 required tool
  - strict notice 只追加到当前模型调用 messages，不长期污染 ToolContextWindow

app/runtime/agent/tool_reveal.py
  - hidden_tool_result 支持 strict_runtime_plan
  - strict hidden payload 带 required_tool、required_tool_call_hint、correction

app/runtime/agent/tool_result_view.py
  - strict hidden tool result 的模型视图压缩到 deterministic correction
  - 不再把完整 known_refs 回灌给模型

tests/test_agent_runtime.py
tests/test_tool_result_view.py
  - 覆盖 strict mode 下 tool_search / memory_write 被收窄
  - 覆盖 strict hidden result 的 compact model view
```

验证结果：

```text
uv run pytest tests/test_agent_runtime.py::test_runtime_does_not_execute_extra_tool_search_when_required_tool_is_visible \
  tests/test_agent_runtime.py::test_runtime_breaks_repeated_schema_search_after_resume_version_pending_merge \
  tests/test_agent_runtime.py::test_gateway_runtime_allows_one_schema_search_correction_before_stagnation \
  tests/test_tool_reveal.py \
  tests/test_tool_result_view.py -q
=> 22 passed

uv run pytest tests/test_tool_call_ledger.py tests/test_tool_policy.py tests/test_tool_gateway.py \
  tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_tool_reveal.py \
  tests/test_workflow_runtime_guard.py tests/test_career_tools.py tests/test_agent_task_runtime.py \
  tests/test_career_live_smoke_report.py tests/test_tool_result_view.py -q
=> passed

uv run mypy --explicit-package-bases app/runtime/agent_runtime.py app/runtime/agent/tool_reveal.py \
  app/runtime/agent/tool_result_view.py app/runtime/workflow/tool_plan.py \
  tests/test_agent_runtime.py tests/test_tool_reveal.py tests/test_tool_result_view.py
=> Success: no issues found in 7 source files

git diff --check -- . ':!.env'
=> passed
```

live smoke：

```text
data/live_career_smoke_m30_strict_tool_surface_6x3_r1
runs=6 concurrency=3 project_action=custom_resume
passed=6/6
avg_elapsed=170.72s
max_elapsed=181.98s
avg_llm_calls=23.0
max_llm_calls=25
avg_tokens=122919
max_tokens=130433
duplicate_runs=3/6
hidden_runs=1/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

相对 M29：

```text
avg_llm_calls: 24.7 -> 23.0
max_llm_calls: 26 -> 25
avg_tokens: 137773 -> 122919
max_tokens: 155538 -> 130433
hidden_runs: 5/6 -> 1/6
stagnation_runs: 0/6 -> 0/6
hard_safety_runs: 0/6 -> 0/6
duplicate_runs: 1/6 -> 3/6
```

结论：

```text
M30 对 main-agent hidden tool 消耗有效，核心目标达成。
剩余长尾不再主要是 tool_search / memory_write 暴露问题，而是写入类工具的幂等粒度：
- job_agent 偶发重复 session_create_text_artifact 创建同一岗位匹配报告
- resume_agent 偶发重复 career_resume_profile_save 保存同一 resume_profile_id
```

下一步不应继续补 main-agent schema guard，而应进入写入工具幂等/内容指纹方向。

## 10. M34/M35 复盘：ResumeVersion required action

M34 反证：

```text
data/live_career_smoke_m34_final_fallback_hidden_suppress_6x3_r1
runs=6 concurrency=3 project_action=custom_resume
passed=3/6
failed=3/6
harmful_duplicate_runs=0/6
hidden_runs=1/6
stagnation_runs=1/6
```

失败根因不是 hidden tool 本身，而是 `resume_version` 阶段仍把“必须创建 ResumeVersion”交给模型自由决定：

```text
CareerApplication 已读取
runtime plan 已要求 career_resume_version_create
模型仍可能：
  - 调 tool_search / read 类隐藏工具
  - 直接提前答复
  - 首次 career_resume_version_create 写入占位或未证实指标后失败
```

因此继续压 hidden tool 只是在外围打补丁，不能保证 required action 一定完成。

M35 修正：

```text
app/tools/builtin_tools/career.py
  - career_resume_version_create 增加显式 use_safe_fallback
  - 无 content/artifact 时可由工具生成保守事实版本
  - 普通调用仍优先要求完整 content 或 generated_file artifact

app/runtime/workflow/guard.py
  - use_safe_fallback=true 时不再以 missing content 阻断
  - 仍保留 JD / ResumeProfile / JobFitReport / CareerApplication 前置检查

app/runtime/agent_runtime.py
  - career_resume_version_create 加入 strict auto execute required tools
  - 隐藏非支持性工具可被 required tool 替换
  - 支持性 session_create_text_artifact 仍优先允许，避免打断“先生成 artifact、再保存 ResumeVersion”的正常路径
  - 无工具提前答复先提醒一次；第二次仍不执行时才自动落到 deterministic required action
```

验证：

```text
uv run pytest -q
=> passed

uv run mypy --explicit-package-bases app/runtime/agent_runtime.py app/tools/builtin_tools/career.py \
  app/runtime/workflow/guard.py tools/smoke_career_live_flow.py \
  tests/test_agent_runtime.py tests/test_career_tools.py tests/test_workflow_runtime_guard.py
=> Success: no issues found in 7 source files
```

live smoke：

```text
data/live_career_smoke_m35_resume_version_required_action_6x3_r1
runs=6 concurrency=3 project_action=custom_resume
passed=6/6
avg_elapsed=176.12s
max_elapsed=233.33s
avg_llm_calls=21.0
max_llm_calls=25
avg_tokens=125393
max_tokens=165937
duplicate_runs=2/6
harmful_duplicate_runs=0/6
recovery_duplicate_runs=2/6
hidden_runs=0/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

结论：

```text
缺 ResumeVersion / hidden tool stagnation 的主问题已收住。
继续优化工具 guard 的边际收益已经低。
下一步应转向最终答复质量：
  - answer 中仍偶发泄露 <tool_call> 文本
  - 个别阶段答复过弱但产品记录完整
  - recovery duplicate 仍主要来自模型首稿被工具事实边界拒绝后的正常恢复
```

## 11. M36 复盘：最终答复质量与 completed refs 收束

M35 后继续 live smoke 发现两个问题：

```text
1. 模型在 final_answer_recovery 中仍可能输出 XML 风格伪工具调用：
   <tool_call><function=...><parameter=...>

2. 阶段已经完成时，workflow guard 返回 terminal block + completed_refs，
   但 runtime 没有把它转成 final_answer_ready plan。
   结果是补答连续失败后只能退到通用 fallback：
   “当前没有生成可用的最终答复……”
```

第一版 M36 修正：

```text
app/prompts/agent_runtime.py
  - final answer recovery 明确禁止伪工具调用文本。

app/runtime/agent_runtime.py
  - final answer guard 统一拒绝：
    - 内部 runtime 文案
    - <tool_invocation .../>
    - <tool_call>/<function=...>/<parameter=...> 伪工具调用
    - workflow 已完成后仍说“我将/需要/首先/然后调用或创建”的弱答复
  - 被拒绝后触发一次 recovery；recovery 仍不可用时走 deterministic fallback。

app/runtime/workflow/tool_plan.py
  - terminal workflow result 且 missing_outputs=[] 时，
    转成 final_answer_ready=true plan，并保留 completed_refs -> known_refs。
  - 这样 deterministic fallback 能基于真实产品记录输出完成摘要。

tools/smoke_career_live_flow.py
  - live smoke 增加最终答复质量门禁：
    - turn.answer 中的伪工具调用/不可交付弱答复
    - assistant_message / agent_result_summary 中的伪工具调用/不可交付弱答复
```

验证时第一组通过但暴露新根因：

```text
data/live_career_smoke_m36_final_answer_quality_6x3_r2
passed=6/6
hidden_runs=1/6
stagnation_runs=1/6
hard_safety_runs=0/6
```

残留根因不是最终答复，而是 runtime tool surface 不一致：

```text
runtime_next_allowed_tools = [career_resume_profile_get, career_profile_merge]
required_tools            = [career_profile_merge]

实际只暴露 required tool，导致模型想先 career_resume_profile_get 时被判 hidden。
随后 schema_search / hidden suppression 循环，最后以 workflow_incomplete_answer 收束。
```

最终修正：

```text
app/runtime/agent_runtime.py
  - 当 required tool 已可见时，收窄后的可见工具集改为：
    runtime_plan_completion_tools ∪ runtime_plan_next_allowed_tools
  - required tool 仍决定阶段完成条件；
    next_allowed tool 只作为合法前置步骤保留在工具面里。
```

最终验证：

```text
uv run pytest -q
=> passed

uv run mypy --explicit-package-bases app/runtime/agent_runtime.py app/runtime/workflow/tool_plan.py \
  tools/smoke_career_live_flow.py tests/test_agent_runtime.py \
  tests/test_runtime_tool_plan.py tests/test_career_live_smoke_report.py
=> Success: no issues found in 6 source files

data/live_career_smoke_m36_final_answer_quality_6x3_r3
runs=6 concurrency=3 project_action=custom_resume
passed=6/6
avg_elapsed=194.62s
max_elapsed=222.38s
avg_llm_calls=22.7
max_llm_calls=27
avg_tokens=135979
max_tokens=172881
duplicate_runs=2/6
harmful_duplicate_runs=0/6
recovery_duplicate_runs=2/6
hidden_runs=0/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

结论：

```text
M36 收住了三类问题：
1. 最终答复伪工具调用泄露
2. 已完成阶段退到“没有可用答复”的通用 fallback
3. required_tools 与 next_allowed_tools 不一致导致的 hidden/stagnation

剩余 duplicate_runs=2/6 都是 recovery_duplicate，不是 harmful duplicate。
下一步如果继续优化，方向不是 main-agent guard，
而是 job_agent 写入类工具的 recovery duplicate 压缩：
- session_create_text_artifact 同标题同阶段多次重写
- career_jd_analysis_save / career_job_fit_report_save 首稿被业务事实边界纠正后重写
```
