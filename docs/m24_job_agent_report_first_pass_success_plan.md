# M24 job_agent 报告一次生成成功率优化方案

> 状态：已实现并完成 6x3 live smoke 验证。本文衔接 [M24 job_agent JD 匹配长尾优化方案](m24_job_agent_jd_fit_tail_optimization_plan.md)，目标是在不放松候选人事实守卫的前提下，提升岗位匹配报告 artifact 的一次生成成功率，进一步压低 JD 匹配阶段长尾。

## 1. 背景

上一轮已经解决 `JobFitReport` 保存后阶段回退问题：

```text
6x3 final: data/live_career_smoke_m24_job_fit_terminal_6x3_r3
  6/6 passed
  avg elapsed: 199.22s
  max elapsed: 226.17s

job_agent calls:
  6 / 7 / 8 / 7 / 7 / 6
```

原始长尾中的重复保存形态已经收敛：

```text
career_jd_analysis_save 不再重复长尾
career_job_fit_report_save 不再重复长尾
JobFitReport 保存后不再回退到 JDAnalysis 阶段
```

剩余长尾集中在报告 artifact 创建阶段。典型样本：

```text
run_001:
  session_create_text_artifact=2
  第一次被 job_fit_report_artifact_candidate_facts_conflict 拦截
  unsupported: vector_search 被写成候选人能力

run_003:
  JD 匹配阶段耗时 121.12s
  job_agent calls=8
  session_create_text_artifact=3
  第一次被 candidate facts conflict 拦截
  第二次 artifact 创建成功
  第三次被 runtime plan hidden block
```

结论：

```text
当前主要问题不再是产品记录保存后重复执行，
而是模型第一次生成匹配报告时仍可能把 JD 要求写成候选人已有能力，
或者在合法报告 artifact 已生成后又尝试再创建一次。
```

## 2. 产品目标和边界

产品目标不变：

```text
围绕目标岗位 / 目标公司，持续管理用户能力差距、求职资产、学习计划和面试准备。
```

岗位匹配报告在产品链路中的职责：

- 把 JD 要求拆成可解释的能力维度。
- 把候选人已有证据和 JD 要求做匹配。
- 把未被简历 / ResumeProfile 支持的要求写入差距、风险、建议或待确认。
- 为定制简历和面试准备提供事实边界。

本阶段必须继续坚持：

```text
JD 要求不能直接变成候选人已有能力。
候选人事实只能来自 ResumeProfile、简历 artifact、CareerProfile 中稳定事实。
未支持的 JD 技能只能写入 gaps / risks / interview focus / resume optimization direction。
```

## 3. 问题形态

### 3.1 JD 技能被误写为候选人能力

例子：

```text
vector_search:
  AI 应用开发、Python、FastAPI、RAG、Agent、向量检索
```

问题在于模型把 JD 中“向量检索”与候选人已有的 RAG / Agent 能力混在同一条优势描述里，导致事实守卫判断它在声明候选人具备向量检索能力。

正确写法应该是：

```text
优势：
  Python、FastAPI、RAG、Agent 工具调用、多 Agent 委派

差距 / 风险：
  向量检索 / 向量数据库经验未在简历画像中体现，需要补充或面试确认。
```

### 3.2 等价技能边界不清

run_003 中出现：

```text
mysql:
  PostgreSQL 使用经验覆盖 JD 要求的“关系型数据库（PostgreSQL / MySQL）”
```

这类情况比 `vector_search` 更微妙。PostgreSQL 可以证明候选人有关系型数据库经验，但不能直接证明候选人有 MySQL 经验。

正确写法应该是：

```text
优势：
  有 PostgreSQL 使用经验，可覆盖“关系型数据库”这一大类要求的一部分。

差距 / 待确认：
  MySQL 具体使用经验未在简历中体现，如 JD 强调 MySQL 细节，需要补充或面试确认。
```

### 3.3 合法 artifact 之后仍尝试再创建报告

run_003 中第二次 `session_create_text_artifact` 已成功，但后续又出现第三次创建尝试，被 runtime plan 以 `tool_hidden_by_runtime_plan` 拦截。

这说明现有 guard 能阻止数据错误，但模型仍可能没有稳定理解：

```text
合法 report artifact 已存在后，下一步只剩 career_job_fit_report_save。
```

## 4. 优化目标

第一阶段目标：

- 提高岗位匹配报告 artifact 的一次生成成功率。
- 减少 `job_fit_report_artifact_candidate_facts_conflict`。
- 合法 report artifact 生成后，减少再次调用 `session_create_text_artifact`。
- 不放松候选人事实守卫。
- 不把 JD 要求自动记入候选人能力。

非目标：

- 不改 JobFitReport 数据模型。
- 不引入新的产品记录。
- 不重写 job_agent。
- 不降低质量门禁。
- 不用扩大 full schema 或长 prompt 回退成本优化。

## 5. 方案设计

### 5.1 生成前提供事实边界包

在 `job_agent` 准备生成岗位匹配报告 artifact 时，runtime / context 可以提供一个紧凑事实边界包：

```text
supported_candidate_facts:
  - Python
  - FastAPI
  - RAG
  - Agent 工具调用
  - 多 Agent 委派
  - API 开发
  - 任务队列
  - 日志审计
  - 部署经验

unsupported_or_unconfirmed_jd_requirements:
  - 向量检索
  - 向量数据库
  - MySQL 具体经验
```

实现上可以复用现有 guard 中的候选人事实识别能力，不必引入新事实源。

边界包只用于生成报告，不写入产品记录，不替代 ResumeProfile。

### 5.2 固定报告结构中的事实语义

要求报告 artifact 使用更稳定的栏目语义：

```text
1. 匹配结论
2. 已支持的匹配优势
3. 部分支持 / 等价覆盖
4. 未支持或待确认差距
5. 简历优化方向
6. 面试准备重点
```

其中：

- `已支持的匹配优势` 只能写 `supported_candidate_facts` 中明确支持的能力。
- `部分支持 / 等价覆盖` 可以写 PostgreSQL 对关系型数据库大类有支持，但不能写“候选人具备 MySQL”。
- `未支持或待确认差距` 必须承接 JD 中未被支持的硬要求。

### 5.3 候选人事实守卫反馈更可执行

当前冲突反馈已经能要求重写，但反馈更偏原则。下一步可以让它更像 patch list：

```text
invalid_claims:
  - vector_search 被写成候选人已有能力

rewrite_rules:
  - 保留 Python / FastAPI / RAG / Agent 为优势
  - 将 vector_search 移到 gaps / interview_preparation_focus
  - 不要重新读取资料
  - 只重新创建一个岗位匹配报告 artifact
```

目标是减少第二次重写仍偏航的概率。

### 5.4 合法 artifact 后加强“只保存产品记录”

当 `session_create_text_artifact` 成功生成 `job_fit_report` 后，pending plan 已经会切到：

```text
next_allowed_tools=[career_job_fit_report_save]
missing_outputs=[job_fit_report]
```

下一步可以补强两点：

- 让模型可见的 tool result 更明确：“不要再次创建 report artifact”。
- 对第三次 `session_create_text_artifact` 的 hidden/block 结果保留 `report_artifact_id`、`next_allowed_tools` 和 `required_tools`，避免模型只看到“工具隐藏”而不知道下一步。

## 6. 实施顺序

### 第一步：测试基线

新增确定性测试：

```text
1. 向量检索只允许出现在 gaps / risks，不允许出现在候选人已有能力。
2. PostgreSQL 可以作为关系型数据库部分支持，但不能证明 MySQL 具体经验。
3. report artifact 已成功后，再次 session_create_text_artifact 必须给出 career_job_fit_report_save 的下一步。
```

### 第二步：抽取事实边界包

把现有 `_supported_candidate_facts` 和 `_unsupported_candidate_tech_claims` 相关逻辑整理成可复用结构：

```text
candidate_fact_boundary:
  supported_candidate_facts
  unsupported_candidate_requirements
  partial_support_notes
```

第一版可以先只在 `WorkflowRuntimeGuard` / tool result payload 中使用，不新增 store 字段。

### 第三步：优化 report artifact 生成提示面

通过 runtime plan / guard payload / tool result view 传递更明确的栏目要求和 rewrite rules。

优先使用结构化字段，避免继续扩写 AGENT.md 大段规则。

### 第四步：补强 artifact ready 后的 next step

确保合法 report artifact 后的所有拦截结果都稳定携带：

```text
report_artifact_id
next_allowed_tools=[career_job_fit_report_save]
required_tools=[career_job_fit_report_save]
missing_outputs=[job_fit_report]
```

### 第五步：live smoke 验证

默认配置保持：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
```

先跑：

```text
3 runs / concurrency 3
```

再跑：

```text
6 runs / concurrency 3
```

## 7. 验收标准

质量：

- live smoke `6/6 passed`。
- product store checker `6/6 passed`。
- 不出现关键错误：

```text
Tool call limit
Tool schema search limit
evidence_refs contains invalid reference format
项目动作未回写 CareerApplication
optional string argument must be a string
```

报告生成：

- `job_fit_report_artifact_candidate_facts_conflict` 目标为 0；可接受上限为 `<= 1/6`。
- `job_agent session_create_text_artifact` p95 `<= 1`，最大 `<= 2`。
- 不再出现合法 report artifact 后的第三次报告创建尝试。

性能：

- `job_agent calls` p95 `<= 7`，最大 `<= 8`。
- `job_agent tokens` 最大低于 `50k`。
- 高并发 `max elapsed` 稳定压到 `220s` 以下。

边界：

- 不放松候选人事实守卫。
- 不把向量检索、MySQL、K8s、Kafka 等未支持 JD 技能写成候选人已有能力。
- 不把“等价大类支持”写成“具体技能已掌握”。

## 8. 风险和缓解

### 8.1 事实边界包过窄

风险：

```text
候选人确实有某项能力，但边界包没有识别出来，导致报告过于保守。
```

缓解：

```text
第一版只把明确未支持的高风险技能放入 unsupported。
对部分支持技能使用 partial_support，不强行判为缺失。
```

### 8.2 规则过重导致报告僵硬

风险：

```text
报告结构过死，影响可读性。
```

缓解：

```text
固定事实语义，不固定每句话。
栏目可以稳定，正文表达仍交给模型。
```

### 8.3 守卫误拦截

风险：

```text
模型把 MySQL 写在 JD 要求列中，也被误判为候选人 claim。
```

缓解：

```text
继续区分 JD context、gap context、candidate claim context。
新增测试覆盖表格列、优势段、差距段三类位置。
```

## 9. 开发结论

下一步优先开发：

```text
1. 补事实边界和等价技能误判测试。
2. 优化候选人事实冲突反馈 payload，让重写规则更可执行。
3. 强化合法 report artifact 后的 next_allowed_tools 可见性。
4. 跑 3x3，再跑 6x3。
```

本轮不建议先动 prompt 大段文本。原因是当前数据已经证明 runtime 守卫有效，剩余问题更适合用结构化事实边界和确定性反馈缩短模型修复路径。

## 10. 实现结果

本轮实际落地内容：

```text
1. career_jd_analysis_save 的模型可见 compact view 增加 job_fit_report_artifact_guidance：
   - 下一步只创建唯一岗位匹配报告 artifact
   - 随后调用 career_job_fit_report_save
   - 不把未支持 JD 技能写成候选人能力

2. WorkflowRuntimeGuard 增加结构化 report_fact_boundary：
   - supported_candidate_facts / unsupported_candidate_facts
   - rewrite_rules
   - artifact_rules
   - RAG/向量检索、Docker/K8s、MySQL 等长尾误写规则

3. hidden_tool_result 增加 required_tool / required_tool_call_hint / correction：
   - 当前 workflow 收敛到唯一下一步时，隐藏工具回包直接指出唯一 required tool
   - career_job_fit_report_save 场景给出可用参数和缺失参数来源提示

4. 增强引用和入参容错：
   - career_job_fit_report_save 前自动修复错误 career_profile_id，如 career_profile_status -> career_profile_default
   - career_profile_merge 的 education_summary / experience_summary / career_goal 接受 list-of-strings 并合并为文本
   - career_job_fit_report_save 在 recommendation 被误填成文本列表时优先使用 recommendation_label
```

定向回归：

```text
uv run pytest tests/test_career_tools.py tests/test_runtime_tool_plan.py tests/test_agent_runtime.py \
  tests/test_tool_reveal.py tests/test_tool_context_window.py tests/test_workflow_runtime_guard.py \
  tests/test_agent_task_runtime.py tests/test_tool_result_view.py -q

结果：通过

mypy:
  app/tools/builtin_tools/career.py
  app/runtime/agent/tool_reveal.py
  app/runtime/agent/tool_result_view.py
  app/runtime/workflow/guard.py
  以及相关测试文件
结果：通过
```

live smoke：

```text
3x3 r2: data/live_career_smoke_m24_report_first_pass_3x3_r2
  3/3 passed
  avg elapsed: 193.43s
  max elapsed: 197.89s

6x3 final r4: data/live_career_smoke_m24_report_first_pass_6x3_r4
  6/6 passed
  avg elapsed: 190.35s
  max elapsed: 213.41s
  product store checker: 6/6 passed
  关键错误扫描: no matches
```

6x3 final r4 的 job_agent 统计：

```text
run_001: llm_calls=5, tokens=30,460, fit_artifacts=1, conflicts=0, failed_tools=0
run_002: llm_calls=5, tokens=28,495, fit_artifacts=1, conflicts=0, failed_tools=0
run_003: llm_calls=6, tokens=29,857, fit_artifacts=1, conflicts=0, failed_tools=0
run_004: llm_calls=8, tokens=43,597, fit_artifacts=1, conflicts=0, failed_tools=0
run_005: llm_calls=9, tokens=57,251, fit_artifacts=1, conflicts=0, failed_tools=0
run_006: llm_calls=6, tokens=32,508, fit_artifacts=1, conflicts=0, failed_tools=0
```

结论：

```text
报告事实守卫没有放松，但 final smoke 中候选人事实冲突降为 0。
每个 run 只保留 1 个 job_agent 岗位匹配报告 artifact。
入参容错把 smoke 中暴露的 recoverable 工具失败前移到了工具边界处理。
当前下一步可以转向主链路更高层的失败工具归零和 main-agent 阶段收敛。

## 11. 后续补丁记录

在 `docs/m24_job_agent_jd_fit_tail_optimization_plan.md` 的追加优化中，已继续处理报告保存后的尾部状态：

```text
1. career_job_fit_report_save 成功后，即使 previous_pending_plan 丢失，也进入 jd_fit final plan。
2. hidden_tool_result 标记 tool_executed=false，guard 不再把隐藏工具回包计为真实成功。
3. “匹配分析报告”标题进入 JobFitReport 保存计划。
4. CareerApplication 创建/合并时过滤不存在的 resume_version_id。
```

最终 live smoke：

```text
6x3: data/live_career_smoke_m24_jobfit_final_plan_fallback_6x3_r1
  6/6 passed
  avg elapsed: 177.45s
  max elapsed: 203.57s
  product store checker: 6/6 passed
```
```
