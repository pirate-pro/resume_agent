# M39：确定性 Workflow Executor 与 Live Smoke 矩阵方案

> 状态：M39-A 已落地 Live Smoke Matrix；M39-B 已落地本轮意图边界、只读 RAG 工具链推进和 delegate 参数规范化；M40 已补 live quality gate；M39-C 已落地 executor contract dry-run skeleton；M39-D/F 已覆盖 resume_version project action 的 sync/stream executor；M39-H 已落地 ActionContract 骨架、P1 首批 action phases 与 runtime finalization barrier 单测；M39-K 已修复 custom resume intent boundary、direct note workflow 和 executor 内部 plan 推进；M39-L 已收口 JDAnalysis malformed 参数与 CareerProfile 诊断字段 source drift 误判；M39-M 已统一 Note source_refs/evidence_refs 引用契约；M39-N 已补 retrieval source alias 与 resume_diagnosis child executor，focused smoke 暴露 JD 阶段仍有 malformed delegate_agents 残留，暂不修复，只记录。本文承接 M37/M38 回退结论：不继续沿着 compact / suppress / final-answer fast-path 补丁路线走。下一步在质量门禁稳定后，把唯一正确的固定 workflow 从模型逐步决策中移出。

## 1. 问题重新定义

M37 已证明核心副作用问题可以被任务状态、tool ledger、幂等和 guard 收住：

```text
passed=6/6
duplicate_runs=0/6
harmful_duplicate_runs=0/6
hidden_runs=0/6
stagnation_runs=0/6
hard_safety_runs=0/6
```

后续 M38 的偏差在于：继续通过上下文压缩、hidden/suppress、completion fast path 去减少模型错误，但主流程仍让模型决定大量确定性步骤。结果是局部 token 下降，代码复杂度上升，耗时长尾仍存在。

M39 的核心判断：

```text
guard 是底线，不是主流程。
当 workflow 的下一步唯一且参数可由状态构造时，不应该再问模型。
```

同时不能把系统优化成只适配当前三个 agent：

```text
agent_main
resume_agent
job_agent
```

未来新增 agent 时，应该通过 workflow contract 注册能力，而不是改 runtime 主循环里的 agent_id 分支。

## 2. 先补 Live Smoke 矩阵

当前 live smoke 主要覆盖 career 全链路。它不足以证明系统整体可用，因为产品还有：

```text
仅聊天
单 main-agent 工具流程
main-agent + 单 sub-agent
Note 写入
Memory 写入
RAG 只读召回
RAG -> Note / Learning / Career action
Career 全链路
```

M39 先补一个 live smoke matrix runner，目标不是大规模压测，而是产品化回归。

### 2.1 场景分层

P0 必跑：

```text
chat_only:
  用户普通问答，不应调用工具。

memory_write:
  用户明确要求“记住偏好”，应只写 memory，不写 note。

note_write:
  用户明确要求保存笔记，应写 Note，不写 memory。

rag_read_only:
  用户问“根据之前记录准备面试”，应 retrieval_search/context_pack，只读，不写入。

main_resume_child:
  main-agent 委派 resume_agent，只生成 ResumeProfile + diagnosis artifact。

main_job_child:
  main-agent 基于已有 ResumeProfile/JD 委派 job_agent，只生成 JDAnalysis + JobFitReport。

career_full:
  resume diagnosis -> JD fit -> resume version。
```

P1 定期跑：

```text
career_custom_resume:
  基于 CareerApplication 生成定制简历并回写项目。

rag_to_note:
  召回上下文后保存复盘 Note。

rag_to_learning_task:
  召回岗位/复盘短板后创建 LearningTask。

interview_review:
  面试复盘写 Note，并更新 CareerApplication。
```

P2 压力/回归跑：

```text
career_full_6x3
career_custom_resume_6x3
rag_actions_3x2
mixed_product_canary
```

### 2.2 每个场景的质量门禁

所有场景共同硬门禁：

```text
success == true
hard_safety_runs == 0
stagnation_runs == 0
assistant answer 不泄露 runtime 内部文案
assistant answer 不包含伪工具调用 markup
副作用工具记录数量符合预期
不越权调用无关写入工具
```

场景级门禁：

```text
chat_only:
  tool_calls == []

memory_write:
  memory_write >= 1
  note_create == 0

note_write:
  note_create 或 note_append >= 1
  memory_write == 0

rag_read_only:
  retrieval_search >= 1
  retrieval_context_pack >= 1
  写入工具 == 0

main_resume_child:
  delegate_agents == 1
  resume_profile == 1
  diagnosis_artifact == 1
  job/career application/resume version 写入 == 0

main_job_child:
  delegate_agents == 1
  jd_analysis == 1
  job_fit_report == 1
  career_application == 0

career_full:
  resume_profile == 1
  jd_analysis == 1
  job_fit_report == 1
  career_application == 1
  resume_version == 1
```

## 3. 优化停止线

不要为了几秒或几千 token 继续加复杂分支。M39 的停止线按产品体验定义：

```text
P0 单场景：
  passed=100%
  无越权副作用
  无 hard_safety/stagnation
  无内部 runtime 文案泄露

Career 6x3：
  passed=6/6
  harmful_duplicate_runs=0/6
  hard_safety_runs=0/6
  stagnation_runs=0/6
  hidden_runs 不作为唯一硬失败；若 hidden=0 最好，>0 必须分析是否造成额外轮次
  avg_llm_calls <= 21
  avg_tokens <= 125000
  avg_elapsed <= 220s
```

停止规则：

```text
连续两组 live smoke 达到上述停止线，就停止性能优化，转产品功能。
除非出现：
  - 有害重复写入；
  - 失败率上升；
  - 用户可见输出质量下降；
  - 单 run 超过 360s 且根因是代码路径而非 provider 延迟。
```

也就是说：

```text
少 5 秒或少 5000 tokens 不值得新增一层 runtime 分支。
```

## 4. Deterministic Executor 的边界

Executor 只处理“封闭世界”的唯一正确步骤，不处理开放式推理。

适合 executor：

```text
CareerApplication 已知后读取项目
ResumeVersion 创建后回写 CareerApplication
JDAnalysis + report artifact 已知后保存 JobFitReport
已知 note_id 后 append note
已知 learning_task_id 后 update/checkin
```

不适合 executor：

```text
普通聊天
RAG query 生成
简历正文生成
岗位匹配报告正文生成
面试建议生成
需要用户判断或业务取舍的动作
```

核心原则：

```text
模型负责内容和判断；
代码负责状态机、唯一工具链、幂等和完成判断。
```

## 5. 不能写死当前 Agent

M39 不在 runtime 主循环里写：

```text
if agent_id == "job_agent": ...
if agent_id == "resume_agent": ...
```

而是引入 workflow contract registry：

```python
WorkflowContract(
    contract_id="career.resume_version.project_action.v1",
    domain="career",
    trigger=...,
    required_refs=[
        "application_id",
        "resume_profile_id",
        "jd_analysis_id",
        "job_fit_report_id",
    ],
    steps=[
        ToolStep("career_application_get", args_from_refs=..., only_if_missing_output="career_application_read"),
        ToolStep("career_resume_version_create", args_from_model_payload=...),
        ToolStep("career_application_merge", args_from_previous_result=...),
    ],
    required_capabilities=["career_resume_version_create", "career_application_merge"],
)
```

未来新增 agent 时，只需要新增 contract：

```text
new_agent 能不能执行某个 workflow，不由 agent 名字决定；
由 capability registry + contract.required_capabilities 决定。
```

匹配规则：

```text
1. runtime 根据当前 session state 构造 WorkflowState；
2. contract registry 找到所有可匹配 contract；
3. 如果 0 个匹配：走模型；
4. 如果 1 个高置信匹配：executor 执行；
5. 如果多个匹配：走模型或要求澄清，不自动执行；
6. executor 每一步都写 task/tool ledger，保持幂等。
```

## 6. M39-A：Live Smoke Matrix Runner

先实现：

```text
tools/smoke_live_matrix.py
```

它应复用 `tools/smoke_career_live_flow.py` 里的 stack 构建能力，但不要只绑定 career。

输出必须包含：

```text
scenario
passed
elapsed
llm_calls
tokens
tool_call_counts
write_tool_counts
record_counts
duplicate / harmful_duplicate / recovery_duplicate
hidden / stagnation / hard_safety
quality_error_codes
```

首批参数：

```text
--scenario chat_only
--scenario memory_write
--scenario note_write
--scenario rag_read_only
--scenario main_resume_child
--scenario main_job_child
--scenario career_full
--scenario career_custom_resume
--runs 1
--concurrency 1
```

CI/本地快速检查：

```text
uv run python tools/smoke_live_matrix.py --scenario chat_only --scenario note_write --scenario rag_read_only --runs 1
```

产品化回归：

```text
uv run python tools/smoke_live_matrix.py --all-p0 --runs 1 --concurrency 1
uv run python tools/smoke_live_matrix.py --scenario career_full --runs 6 --concurrency 3
```

当前已实现基础版本：

```text
tools/smoke_live_matrix.py
tests/test_smoke_live_matrix.py
```

已覆盖首批场景：

```text
P0:
  chat_only
  memory_write
  note_write
  rag_read_only
  main_resume_child
  main_job_child
  career_full

P1:
  career_custom_resume
  rag_to_note
  rag_to_learning_task
  interview_review
```

同时把 `tools/smoke_career_live_flow.py` 的效率统计从固定读取
`agent_main/resume_agent/job_agent`，调整为动态读取当前 session 下所有 agent 事件文件。这样后续新增
`research_agent`、`interview_agent` 或其他 agent 时，live smoke 的 token、llm_calls、duplicates、hidden 统计不会漏掉新 agent。

M39-A 只做测试矩阵和观测面，不改变 runtime 主流程。

## 7. M39-B：本轮意图边界与工具链推进

P0 matrix 暴露的第一类根因不是重复调用，而是 runtime 缺少“本轮意图边界”：

```text
只读召回被 career application_action 补全逻辑误推进到 CareerApplication merge；
只委派 resume_agent 的任务被负向短语“不要生成定制简历”误判为 resume_version；
只委派 job_agent 的任务在 JobFitReport 完成后被自动补全到 CareerApplication create；
子任务中的 artifact 预览和事实源规则被误读成只读控制指令。
```

已落地：

```text
app/runtime/workflow/intent_boundary.py
```

边界抽取规则：

```text
只读 / 禁止创建 CareerApplication / 禁止更新 CareerApplication /
禁止生成 ResumeVersion / 禁止 JD fit
```

关键原则：

```text
只从控制面文本抽边界；
遇到 artifact_refs、artifact 事实源规则、artifact 内容预览后停止读取；
artifact 内容中的 RAG、向量检索、不要写入未出现事实，不能触发只读锁。
```

Runtime 消费点：

```text
career_phase / career_flow_state:
  用 TurnIntentBoundary 修正 phase 和 required_outputs。

tool_plan:
  read_only retrieval 固定为 retrieval_search -> retrieval_context_pack -> final answer。
  jd_fit 在用户明确禁止 CareerApplication 时，不再补 application create。

guard:
  只对明确禁止的副作用工具做安全兜底。
  delegate_agents 支持把合法的顶层 instruction 下沉到缺失 instruction 的 task。
```

M39-B live 结果：

```text
data/live_smoke_matrix_m39_b_p0_r3/report.json

P0 passed=7/7
avg_elapsed=60.31s
max_elapsed=251.28s
avg_llm_calls=6.29
max_llm_calls=23
avg_tokens=34650
max_tokens=142586
harmful_duplicate_runs=0/7
hidden_runs=0/7
```

注意：P0 结构门禁已过，但这次 career_full 的最终答复仍出现过 JD 表述漂移风险，例如最终答复提到与源 JD 不一致的 C++ 游戏服务端内容。下一步不能只看结构成功，还需要把“答案/报告是否忠于源 JD 和产品记录”加入 live quality gate。

## 8. M39-C：Executor Contract Skeleton

执行状态：M39-C 已在 M40 live quality gate 之后落地 dry-run skeleton。原因是 M39-B 已证明结构路径可以通过，但 `career_full` 曾出现最终答复 / ResumeVersion 与源 JD 不一致的质量漂移。只有先把质量漂移纳入 live smoke 失败，executor 才不会把错误路径固定化。

在 live smoke matrix 有基线后，再做 executor skeleton：

```text
app/runtime/workflow/executor.py
app/runtime/workflow/contracts.py
tests/test_workflow_executor.py
```

第一步只实现 dry-run / decision，不自动执行工具：

```text
输入：UnifiedWorkflowState + RunContext + tool registry capabilities
输出：
  matched_contract_id
  confidence
  required_refs
  planned_steps
  reason_not_executable
```

验收：

```text
不会影响现有 runtime；
能识别 resume_version project_action 是否满足 executor 条件；
多 contract 匹配时拒绝自动执行；
agent capability 不足时拒绝自动执行。
```

落地文件：

```text
app/runtime/workflow/contracts.py
app/runtime/workflow/executor.py
tests/test_workflow_executor.py
```

当前内置 contract：

```text
career.resume_version.project_action.v1
  trigger_phase=resume_version
  required_refs=application_id,resume_profile_id,jd_analysis_id,job_fit_report_id
  trigger_missing_outputs=resume_version,career_application_resume_version_link
  steps=career_application_get(only if career_application_read missing)
        -> career_resume_version_create
        -> career_application_merge
```

当前行为：

```text
dry-run decision 已作为 M39-D 执行前置判断；
多个 contract 匹配时 reason_not_executable=ambiguous_contracts；
缺少 refs 时 reason_not_executable=missing_required_refs；
缺少工具能力时 reason_not_executable=missing_required_capabilities；
planned_steps 会按当前 missing_outputs 过滤条件步骤；
不绑定 resume_agent/job_agent，未来 agent 只要具备 required tool capabilities 即可 dry-run 通过。
```

## 9. M39-D：Resume Version Project Action Executor

执行状态：已落地同步 runtime 路径。只接入 `career.resume_version.project_action.v1`。

目标场景：

```text
用户明确要求基于 application_id 生成定制简历；
CareerApplication 已存在；
application 中已有 resume_profile_id / jd_analysis_id / job_fit_report_id；
当前没有 resume_version 或用户明确要求新版本。
```

执行方式：

```text
1. 如果 workflow state 仍缺 career_application_read，executor 先调用 career_application_get；
2. refs 已齐时不再读取产品记录，直接调用一次模型生成 ResumeVersionDraftPayload；
3. executor 调用 career_resume_version_create；
4. executor 调用 career_application_merge；
5. runtime 根据结果生成结构化最终答复。
```

2026-05-26 补充：M39-D live smoke 发现旧 runtime plan 在 refs 已齐时会阻止 `career_application_get`，而 executor contract 仍强制读取，形成两个状态机的职责冲突。已把读取步骤改为 contract 条件步骤：只有 `missing_outputs` 里明确包含 `career_application_read` 才计划读取；常规定制简历闭环为 `career_resume_version_create -> career_application_merge`。

验证结果：

```text
data/live_smoke_matrix_m39_d_executor_career_full_r2/report.json
career_full 1/1 passed
定制简历版本阶段 tools=career_application_merge,career_resume_version_create
workflow_executor_contract_matched=1
workflow_executor_completed=1
tool_blocked_by_runtime_state=0
阶段耗时=18.40s
```

失败回退：

```text
contract 不匹配 / refs 不齐 / capability 不足：不执行 executor，走原模型工具循环；
executor 任一步工具失败：记录 workflow_runtime_decision 后回退原模型工具循环；
模型草稿不是合法 JSON：用正文兜底或触发 career_resume_version_create 的 use_safe_fallback；
career_resume_version_create 仍由工具事实校验和 M40 live quality gate 兜底。
```

落地文件：

```text
app/runtime/agent_runtime.py
tests/test_agent_runtime.py::test_runtime_executor_runs_resume_version_project_action_without_tool_loop
```

注意：

```text
不是完全不调模型；
而是不让模型决定固定工具顺序。
```

验收目标：

```text
career_custom_resume 项目动作阶段：
  avg_llm_calls 降低；
  schema_search_suppressed_required_tool_visible 明显减少；
  tool sequence 固定；
  resume_version 和 application merge 不缺失；
  简历事实边界不退化。
```

## 10. M39-F：Streaming / Async Executor Path

执行状态：已落地 `run_stream` 入口。产品真实接口 `/api/chat/stream` 会进入 `ChatService.chat_stream -> AgentRuntime.run_stream`，因此 executor 不能只覆盖同步 smoke 路径。

实现原则：

```text
contract / planned_steps / draft args 解析与 sync 共用；
内部 ResumeVersionDraftPayload 用 generate_stream 收集完整 JSON；
内部 JSON draft 不作为 answer_delta 推给用户；
工具执行走 ToolGateway.execute_async；
只向 channel 推送 workflow_runtime_decision / tool_call / tool_result / 最终 answer_meta / answer_delta。
```

落地文件：

```text
app/runtime/agent_runtime.py
tests/test_agent_runtime.py::test_runtime_stream_executor_runs_resume_version_project_action_without_tool_loop
tools/smoke_live_matrix.py --stream
tools/smoke_career_live_flow.py --stream
```

当前验证：

```text
stream executor 单测通过；
不进入原 tool_loop；
answer_delta 只包含最终结构化答复，不泄露内部 JSON draft。
```

后续仍需补一个真实模型 streaming smoke runner，避免只用 sync live matrix 代表产品入口。
真实模型 streaming smoke runner 已有开关，后续 live 验证优先使用：

```text
uv run python tools/smoke_live_matrix.py --scenario career_full --runs 1 --concurrency 1 --stream
```

## 11. M39-G：回收旧 Guard 分支

执行状态：已开始回收。

当 executor 覆盖固定链路后，逐步清理只为这些链路存在的 suppress 分支。

候选清理：

```text
resume_version project-action 中反复 suppress schema_search 的分支；
为已知 required_tool 反复生成长提示的分支；
只服务 career_custom_resume 的特殊 hidden correction 文案。
```

清理规则：

```text
先有 executor 覆盖和 live smoke 证明；
再删除 guard 分支；
不能边做 executor 边保留所有旧分支无限叠加。
```

2026-05-26 已清理第一批：

```text
删除 WorkflowRuntimeGuard 中旧的 main_project_resume_version 三段 stage gate：
application_get -> resume_version_create -> application_merge。

原因：
这条 project-action 顺序现在由 runtime_tool_plan + workflow executor contract 负责；
WorkflowRuntimeGuard 继续保留会形成第二套状态机，并且会和 executor 的条件读取策略互相影响。

保留：
turn intent boundary；
product get run 内复用；
resume_version_create 参数修正、前置产物校验、幂等复用、质量兜底；
resume_version 已生成后要求 application_merge 的通用 stage gate。
```

验证：

```text
uv run pytest -q \
  tests/test_workflow_runtime_guard.py::test_main_project_resume_version_leaves_initial_order_to_runtime_plan \
  tests/test_workflow_runtime_guard.py::test_main_project_resume_version_reuses_duplicate_application_get_after_read \
  tests/test_workflow_runtime_guard.py::test_main_resume_version_stage_blocks_duplicate_create_until_merge \
  tests/test_workflow_executor.py \
  tests/test_agent_runtime.py::test_runtime_executor_runs_resume_version_project_action_without_tool_loop \
  tests/test_agent_runtime.py::test_runtime_stream_executor_runs_resume_version_project_action_without_tool_loop
```

M39-G live smoke 补充发现：

```text
一组 stream career_full 通过，但 JD 匹配阶段出现 harmful_duplicate_runs=1/1。
根因不是 resume_version executor，也不是工具幂等失效，而是 turn intent boundary 误把 child job_agent 的写入任务判成只读：

子任务同时包含：
- 必须使用已有 resume_profile_id / career_profile_id；
- 不要重新创建 JD artifact；
- 必须调用 career_jd_analysis_save 和 career_job_fit_report_save。

旧 read_only 规则看到“不要创建 + 已有记录”就判整轮只读，阻断了第一次 job_agent 的写入工具，main-agent 随后二次委派才完成，形成时间/token 和 harmful duplicate。
```

修复：

```text
intent_boundary 增加 explicit_write_goal 优先级：
当同一 control-plane 文本明确要求保存/创建 JobFitReport、JDAnalysis、ResumeVersion、CareerApplication 等目标时，
局部的“不要重新创建 artifact / 不要猜 artifact_id”不再升级成整轮 read_only。

保留：
明确“本轮只读 / 只读模式 / read-only”仍然强制只读；
没有正向写入目标的“不要保存、不要创建 + 召回/历史记录/已有记录”仍按只读处理。
```

复测：

```text
uv run python tools/smoke_live_matrix.py \
  --scenario career_full --runs 1 --concurrency 1 --stream \
  --data-dir data/live_smoke_matrix_m39_g_intent_boundary_stream_career_full_r1 \
  --json-report data/live_smoke_matrix_m39_g_intent_boundary_stream_career_full_r1/report.json

结果：
success=1/1
elapsed=247.32s
avg_llm_calls=20.0
avg_tokens=116272
duplicates=0
harmful_duplicates=0
hidden=0
JD 阶段 tools=career_application_create,career_jd_analysis_save,career_job_fit_report_save,delegate_agents,session_create_text_artifact,tool_search
定制简历阶段 tools=career_application_merge,career_resume_version_create
read_only_blocks=0
workflow_executor_contract_matched=1
workflow_executor_completed=1
```

## 12. M39-H：Action Contract 与副作用完成条件

执行状态：ActionContract dry-run、首批 P1 action phases、runtime tool plan finalization barrier 与单测已落地；仍需 live smoke 验证。

### 12.1 本轮失败复盘

2026-05-26 全量 stream live smoke：

```text
data/live_smoke_matrix_m41_all_p0_p1_stream_c6_r1_20260526_235424/report.json

total=11
success=7
failed=4

P0 全通过：
  chat_only
  memory_write
  note_write
  rag_read_only
  main_resume_child
  main_job_child
  career_full

P1 失败：
  career_custom_resume
  rag_to_note
  rag_to_learning_task
  interview_review
```

这组失败不是并发写坏，也不是 tool idempotency 失效：

```text
harmful_duplicate_runs=0/11
failed_tool_results=0
source quality errors=0
```

真正问题是 P1 的复合动作仍然靠模型自由推进：

```text
rag_to_note:
  用户目标是 retrieval -> note write；
  动作轮被旧 career application 状态污染，重复 career_application_merge；
  没有完成 retrieval_search / retrieval_context_pack / note_create。

rag_to_learning_task:
  完成 retrieval_search / retrieval_context_pack；
  但 retrieval 被当成终点，缺 learning_task_create。

interview_review:
  完成 retrieval_search / retrieval_context_pack；
  但缺 note_create/note_append 和 career_application_merge。

career_custom_resume:
  runtime 期待 career_profile_merge；
  模型重复尝试 delegate_agents，required tool gate 卡住后产生 hidden/runtime-hidden。
```

结论：

```text
skill 是软约束，能告诉模型“应该怎么做”；
workflow/action contract 是硬约束，负责“最终产物没落库就不能结束”。
```

因此 M39-H 不继续增加单点 suppress / hidden guard，而是把“带副作用的用户动作”抽象成可注册的 action contract。

### 12.2 Skill 与 Action Contract 的分工

现有 skill 继续保留，用来做意图和业务边界说明：

```text
retrieval-workflow:
  什么时候需要只读召回。

note-workflow:
  什么时候写 Note，什么时候不要写 memory。

learning-workflow:
  什么时候创建 LearningTask，什么时候只给建议。

career-workflow:
  求职项目、JD、匹配报告、定制简历的产品边界。
```

但 skill 不能承担这些职责：

```text
判断 required output 是否已经落库；
判断当前 action 是否允许 final answer；
判断某个写工具是否越界；
判断 retrieval 完成后是否还必须继续写入；
判断旧 career workflow 状态是否污染了当前 RAG action。
```

这些必须由 action contract / workflow executor / tool ledger / product store 共同承担。

### 12.3 Action Contract 最小模型

新增概念不替换已有 `WorkflowContract`，而是把它泛化到“用户动作”的层面。`WorkflowContract` 继续覆盖封闭 career 工具链；`ActionContract` 覆盖跨服务副作用动作。

建议结构：

```python
ActionContract(
    contract_id="rag.note.write.v1",
    domain="note",
    intent_tags=("retrieval_required", "note_write"),
    required_outputs=("note_id",),
    allowed_tools=(
        "retrieval_search",
        "retrieval_context_pack",
        "note_create",
        "note_append",
    ),
    forbidden_write_tools=(
        "career_application_merge",
        "career_resume_version_create",
        "learning_task_create",
        "memory_write",
    ),
    steps=(
        ActionStep("retrieval_search", output_ref="retrieval_result_id"),
        ActionStep("retrieval_context_pack", output_ref="context_pack_id"),
        ActionStep("note_create", requires_model_payload=True, output_ref="note_id"),
    ),
)
```

关键字段：

```text
contract_id:
  稳定版本号，后续新增动作只注册新 contract。

intent_tags:
  来自 TurnIntentBoundary / sparse workflow rules / 用户本轮请求，不直接从 artifact 内容推断。

required_outputs:
  final answer 前必须存在的产品输出，例如 note_id、learning_task_id、application_update。

allowed_tools:
  当前 action 可用工具白名单。

forbidden_write_tools:
  明确禁止的越界写工具，用于避免旧 workflow 状态污染本轮动作。

steps:
  可确定的工具链；需要内容生成的步骤可以保留 requires_model_payload。
```

### 12.4 首批 Contract

首批只覆盖全量 smoke 暴露的 P1 失败，不扩大范围：

```text
rag.note.write.v1
  trigger:
    用户明确要求“召回/根据之前内容/复盘”并保存成笔记。
  required_outputs:
    note_id
  required_chain:
    retrieval_search -> retrieval_context_pack -> note_create/note_append
  final barrier:
    retrieval_context_pack 完成不等于 final；
    note_id 不存在时禁止 final。
  forbidden:
    career_application_merge
    career_resume_version_create
    learning_task_create
    memory_write

rag.learning_task.create.v1
  trigger:
    用户明确要求根据历史/JD/复盘创建学习任务或学习安排。
  required_outputs:
    learning_task_id
  required_chain:
    retrieval_search -> retrieval_context_pack -> learning_task_create
  final barrier:
    learning_task_id 不存在时禁止 final。
  forbidden:
    career_application_merge
    note_create/note_append
    memory_write

interview.review.update.v1
  trigger:
    用户明确要求保存面试复盘，并更新对应求职项目。
  required_outputs:
    note_id
    career_application_update
  required_chain:
    retrieval_search -> retrieval_context_pack -> note_create/note_append -> career_application_merge
  final barrier:
    note_id 和 application update 都存在才允许 final。
  forbidden:
    learning_task_create
    memory_write

career.profile.merge.required.v1
  trigger:
    resume diagnosis 后 runtime 已确定需要 career_profile_merge。
  required_outputs:
    career_profile_id 或 career_profile_update
  required_chain:
    career_profile_merge
  final barrier:
    required profile output 缺失时禁止 final，也不把 delegate_agents 当作替代动作。
```

### 12.5 Finalization Barrier

当前 bug 的共同点是“中间读取完成后过早 final”。M39-H 的核心不是多调用工具，而是修正完成条件：

```text
只读 RAG：
  retrieval_context_pack 完成 -> 可以 final。

RAG -> Note：
  retrieval_context_pack 完成 -> 不可以 final；
  note_id 存在 -> 可以 final。

RAG -> LearningTask：
  retrieval_context_pack 完成 -> 不可以 final；
  learning_task_id 存在 -> 可以 final。

Interview Review：
  retrieval_context_pack 完成 -> 不可以 final；
  note_id + application_update 存在 -> 可以 final。
```

运行时判断：

```python
def can_finalize(action_state: ActionState) -> bool:
    if action_state.contract is None:
        return workflow_state.final_answer_ready
    return all(output in action_state.completed_outputs for output in action_state.contract.required_outputs)
```

如果模型提前给 final answer：

```text
存在 pending required output：
  拒绝 final；
  继续推进 contract 的下一步 required tool。

不存在 pending required output：
  允许 final。
```

### 12.6 状态确认不能消耗额外 LLM 轮次

不要通过模型反复确认状态。状态事实源优先级：

```text
1. 本轮成功 tool result；
2. tool call ledger；
3. product store；
4. UnifiedWorkflowState / ActionState resolver；
5. 必要时才让模型生成 payload。
```

例如：

```text
note_create 返回 note_id；
learning_task_create 返回 learning_task_id；
career_application_merge 返回 application_id / updated fields；
career_profile_merge 返回 career_profile_id。
```

这些结果直接进入 `completed_outputs`，不需要再走一轮 LLM 判断“是否完成”。

### 12.7 与现有 WorkflowContract 的关系

`WorkflowContract` 不删除，继续处理封闭 career 工具链：

```text
career.resume_version.project_action.v1
```

`ActionContract` 处理跨服务动作：

```text
retrieval + note
retrieval + learning
retrieval + career update
resume diagnosis + profile merge
```

二者统一接到 executor decision 层：

```text
1. 根据本轮 intent boundary 识别 action contract；
2. 如果 action contract 命中，以 action contract 的 required_outputs 作为 final barrier；
3. 如果没有 action contract，再使用现有 workflow contract / runtime tool plan；
4. 多 contract 命中时不自动执行，要求模型澄清或走原模型路径；
5. contract 不匹配时，不强行进入 workflow。
```

### 12.8 不做的事

M39-H 明确不做：

```text
不把普通聊天纳入 action contract；
不把只读 RAG 强行变成写入 workflow；
不在 runtime 主循环写 rag_to_note / rag_to_learning_task 的 case-by-case if；
不新增“看到某个工具就 suppress”的局部补丁；
不让模型通过额外工具轮次确认状态；
不为了少几秒或少几千 token 扩大 executor 范围。
```

### 12.9 实施步骤

建议分四批：

```text
H1: 文档与单测骨架
  - 新增 ActionContract / ActionStep / ActionContractRegistry dry-run。
  - 新增 ActionState resolver，从 tool result / ledger / store 提取 completed_outputs。
  - 单测覆盖 contract matching、ambiguous_contracts、missing_outputs。

H2: finalization barrier
  - runtime 接入 action_state.can_finalize。
  - pending required output 时拒绝 premature final answer。
  - retrieval read-only 与 retrieval-write action 分流。

H3: 首批 P1 action contracts
  - rag.note.write.v1
  - rag.learning_task.create.v1
  - interview.review.update.v1
  - career.profile.merge.required.v1

H4: 回收旧补丁
  - 只在 P1 live smoke 通过后清理对应 suppress / hidden 分支。
  - 不边加 contract 边无限保留旧状态机。
```

### 12.10 验收

先跑聚焦 P1：

```text
uv run python tools/smoke_live_matrix.py \
  --scenario career_custom_resume \
  --scenario rag_to_note \
  --scenario rag_to_learning_task \
  --scenario interview_review \
  --runs 1 --concurrency 4 --stream
```

再跑 P0 防回归：

```text
uv run python tools/smoke_live_matrix.py --all-p0 --runs 1 --concurrency 6 --stream
```

最后跑全量：

```text
uv run python tools/smoke_live_matrix.py --all-p0 --all-p1 --runs 1 --concurrency 6 --stream
```

通过标准：

```text
P0 passed=7/7；
P1 四个失败场景通过；
harmful_duplicate_runs=0；
stagnation_runs=0；
hidden/runtime-hidden 不再作为 required tool 推进失败出现；
RAG write 场景没有越界 career/memory 写入；
avg_tokens / avg_elapsed 不明显劣化。
```

停止线：

```text
如果 P0/P1 结构正确且用户可见质量稳定，不继续为了少量 token 或数秒耗时扩展 contract。
后续新增 agent 或产品动作时，只新增 contract / capability，不改 runtime 主循环分支。
```

### 12.11 当前实施记录

已落地：

```text
ActionContract / ActionContractRegistry dry-run；
rag.note.write.v1 / rag.learning_task.create.v1 / interview.review.update.v1；
career.profile.merge.required.v1；
action finalization barrier；
retrieval-write action 与 retrieval_read_only 分流；
tool boundary 对 Note evidence_refs 的 source_ref object -> source_id canonicalization。
```

关键修正：

```text
live smoke 失败根因不是 ActionContract 不生效，而是 intent boundary 被公共召回前缀污染：
“创建任务、保存笔记或更新项目之前必须读取 context pack”
“不要创建学习任务 / 不要更新求职项目”
这类控制性说明被误当成用户动作或只读边界。

修正后，action phase 只认明确动作目标：
rag_note_write / rag_learning_task_create / interview_review_update。
公共前缀只作为执行约束，不再决定业务终点。
```

验证：

```text
unit:
  tests/test_intent_boundary.py
  tests/test_workflow_phase_guard.py
  tests/test_runtime_tool_plan.py
  tests/test_workflow_executor.py
  tests/test_retrieval_action_flow.py
  tests/test_agent_runtime.py
  tests/test_career_live_smoke_report.py
  tests/test_smoke_live_matrix.py
  tests/test_note_tools.py

mypy:
  app/runtime/workflow/intent_boundary.py
  app/runtime/workflow/career_phase.py
  app/runtime/workflow/tool_plan.py
  app/runtime/workflow/contracts.py
  app/runtime/workflow/executor.py
  app/runtime/agent_runtime.py
  app/tools/builtin_tools/notes.py
```

focused live smoke：

```text
command:
uv run python tools/smoke_live_matrix.py \
  --scenario career_custom_resume \
  --scenario rag_to_note \
  --scenario rag_to_learning_task \
  --scenario interview_review \
  --runs 1 --concurrency 4 --stream \
  --data-dir data/live_smoke_matrix_m39_h_intent_boundary_stream_c4_r1 \
  --json-report data/live_smoke_matrix_m39_h_intent_boundary_stream_c4_r1/report.json

result:
success=1/4
career_custom_resume passed
rag_to_note / rag_to_learning_task / interview_review failed

but P1 action routing improved:
rag_to_note tools=[retrieval_search, retrieval_context_pack, note_create]
rag_to_learning_task tools=[retrieval_search, retrieval_context_pack, learning_task_create]
interview_review tools=[retrieval_search, retrieval_context_pack, note_create, career_application_merge]

remaining failures are now outside phase routing:
1. Note evidence_refs object-shape caused first note_create failure, then retry succeeded.
2. Final answer source drift leaked an unsupported C++ claim from rejected/repaired career_profile_merge arguments.
3. ResumeVersion protective validation still sometimes rejects unsupported metrics, then retry succeeds.
```

下一步不继续扩大 ActionContract。优先处理工具边界和 final answer recovery 的事实来源：

```text
1. tool boundary: canonicalize accepted reference shapes before write validation。
2. final answer recovery: user-visible answer must summarize saved product record / repaired tool result,
   not the model's raw attempted tool arguments。
3. smoke report: distinguish action routing failure from recovered validation failure,
   but recovered write failure remains error until final answer recovery no longer leaks invalid attempt facts。
```

Note evidence_refs canonicalization 后补充验证：

```text
command:
uv run python tools/smoke_live_matrix.py \
  --scenario rag_to_note \
  --runs 1 --concurrency 1 --stream \
  --data-dir data/live_smoke_matrix_m39_h_note_refs_stream_c1_r1 \
  --json-report data/live_smoke_matrix_m39_h_note_refs_stream_c1_r1/report.json

result:
success=1/1
harmful_duplicate_runs=0/1
hidden_runs=0/1
action tools=[retrieval_search, retrieval_context_pack, note_create]
note_create=1
failed_tools=0
```

Final answer recovery fact-source 修正后补充验证：

```text
root cause:
final_answer_recovery 复用了 tool-loop repair 的 message window。
该 window 会保留 assistant attempted tool arguments，用于模型修正下一轮工具调用。
但 attempted arguments 不是已提交事实，可能包含后续被工具层修正或拒绝的 unsupported facts。

fix:
保留 tool-loop repair context 不变；
final_answer_recovery 使用 sanitized message window；
sanitized window 移除 assistant tool_call raw arguments、tool/raw content、updates、
source_alignment_repairs 等非最终事实字段；
保留 committed product records、artifact refs、ids 和 repaired marker。

scope:
不降低 live quality gate；
不添加 C++/Java 这类词级过滤；
不扩大 ActionContract；
只把 user-visible final answer 的事实来源从 attempted args 收回到 committed tool results。
```

```text
unit:
  tests/test_tool_context_window.py
  tests/test_tool_result_view.py
  tests/test_agent_runtime.py
  tests/test_retrieval_action_flow.py
  tests/test_intent_boundary.py
  tests/test_workflow_phase_guard.py
  tests/test_runtime_tool_plan.py
  tests/test_workflow_executor.py
  tests/test_note_tools.py
  tests/test_career_live_smoke_report.py
  tests/test_smoke_live_matrix.py
  tests/test_career_live_quality_gate.py

mypy:
  app/runtime/agent/tool_context_window.py
  app/runtime/agent_runtime.py
  app/runtime/agent/__init__.py
```

```text
command:
uv run python tools/smoke_live_matrix.py \
  --scenario rag_to_learning_task \
  --runs 1 --concurrency 1 --stream \
  --data-dir data/live_smoke_matrix_m39_h_final_answer_safe_learning_c1_r1 \
  --json-report data/live_smoke_matrix_m39_h_final_answer_safe_learning_c1_r1/report.json

result:
success=1/1
elapsed=215.49s
harmful_duplicate_runs=0/1
hidden_runs=0/1
llm_calls=23
tokens=122287
action tools=[retrieval_search, retrieval_context_pack, learning_task_create]
final_answer_source_drift=0
```

复合写入场景补充验证：

```text
command:
uv run python tools/smoke_live_matrix.py \
  --scenario interview_review \
  --runs 1 --concurrency 1 --stream \
  --data-dir data/live_smoke_matrix_m39_h_final_answer_safe_interview_c1_r1 \
  --json-report data/live_smoke_matrix_m39_h_final_answer_safe_interview_c1_r1/report.json

result:
success=1/1
elapsed=238.75s
harmful_duplicate_runs=0/1
hidden_runs=0/1
llm_calls=23
tokens=132274
action tools=[retrieval_search, retrieval_context_pack, note_create, career_application_merge]
notes=1
career_applications=1
final_answer_recovery=23690/4

meaning:
RAG 后写 Note 与更新 CareerApplication 的复合终点已通过；
previous evidence_refs object-shape failure 未复现；
previous final answer source drift 未复现；
仍有 1 次 non-harmful duplicate 和较高 final_answer_recovery token，
这属于后续成本治理，不作为本轮继续加 guard 的理由。
```

### 12.12 M39-I：FinalizationPacket 与 recovery system prompt

目标：

```text
不继续扩大 ActionContract；
不降低 live quality gate；
不做具体词过滤；
把 final answer recovery 的输入从“工具修复历史”收敛为 committed finalization facts。
```

实现：

```text
新增 FinalizationPacket：
  user_goal
  phase / next_action / final_answer_ready
  required_outputs / missing_outputs
  known_refs
  completed_tools
  product_refs / artifact_refs
  committed facts
  warnings

final_answer_recovery 不再直接读取完整 tool-loop messages；
有 grounded facts 时，recovery messages 固定为：
  user goal
  FINALIZATION_PACKET
  final answer recovery prompt

同时新增专用 FINAL_ANSWER_RECOVERY_SYSTEM_PROMPT：
  只做最终答复；
  不继承 agent tool/system 编排语义；
  不输出伪工具调用；
  只依据 committed facts / refs 作答。

FinalizationPacket 过滤 internal orchestration refs：
  task_id / task_group_id / run_id / session_id / source_session_id / agent_id / tool_call_id
不进入 product_refs / known_refs，避免最终答复把编排对象当成用户产物。
```

关键教训：

```text
第一次只引入 FinalizationPacket，但仍复用原 agent system prompt，效果变差：
interview_review success=1/1
tokens=130726
final_answer_recovery=43754/8

根因不是 packet 本身，而是 recovery 仍被工具 agent 的 system prompt 牵引。
在 packet 比完整历史更短时，模型更容易“重新开始调用工具”，导致 tool_call_markup 被拒后二次 recovery。
```

修正后验证：

```text
unit:
  tests/test_finalization_packet.py
  tests/test_agent_runtime.py
  tests/test_tool_context_window.py
  tests/test_note_tools.py
  tests/test_career_live_smoke_report.py
  tests/test_smoke_live_matrix.py

mypy:
  app/runtime/agent/finalization_packet.py
  app/runtime/agent/tool_context_window.py
  app/runtime/agent_runtime.py
  app/runtime/agent/__init__.py
  app/runtime/event_recorder.py
  app/prompts/agent_runtime.py
  tools/smoke_career_live_flow.py
  tools/smoke_live_matrix.py
```

```text
command:
uv run python tools/smoke_live_matrix.py \
  --scenario rag_to_learning_task \
  --runs 1 --concurrency 1 --stream \
  --data-dir data/live_smoke_matrix_m39_i_finalization_packet_learning_c1_r1 \
  --json-report data/live_smoke_matrix_m39_i_finalization_packet_learning_c1_r1/report.json

result:
success=1/1
elapsed=236.97s
llm_calls=22
tokens=109837
harmful_duplicate_runs=0/1
hidden_runs=0/1
final_answer_recovery=10627/4
action tools=[retrieval_search, retrieval_context_pack, learning_task_create]
```

与上一轮同场景对比：

```text
before:
tokens=122287
llm_calls=23
final_answer_source_drift=0

after:
tokens=109837
llm_calls=22
final_answer_recovery=10627/4
final_answer_source_drift=0

结论：
finalization packet + dedicated recovery system prompt 对 P1 learning task 有效；
收益来自 system prompt 去工具化和 final facts 收敛，不是牺牲质量。
```

未纳入本轮修复的问题：

```text
interview_review 在 dedicated recovery prompt 后的 focused smoke 失败：
data/live_smoke_matrix_m39_i_finalization_packet_recovery_prompt_interview_c1_r1/report.json

失败点不在 finalization：
  final_answer_recovery=8109/3，成本已明显下降；
  但 M16 action 轮出现 retrieval_context_pack 参数 source_type=resume_source/jd_source 不被支持；
  retry 后 retrieval_context_pack 成功；
  Note 已创建；
  随后 required career_application_merge 阶段模型重复 schema search，最终 ReadTimeout。

这暴露的是另一个结构问题：
Note 后更新 CareerApplication 仍依赖模型生成复杂 merge payload；
ActionContract 只声明了 required tool，还没有 deterministic action payload executor。
下一步如果继续，应做 action payload executor，而不是继续改 finalization。
```

### 12.13 M39-J：interview review action payload executor 与 smoke 判重修正

本轮目标不是继续补 prompt，而是处理 M16 真实暴露的结构问题：

```text
interview_review_update 在 Note 创建后，唯一缺口是 CareerApplication 更新；
模型仍可能在 required career_application_merge 阶段重复 tool_search 或生成不稳定 payload；
因此需要把 Note -> Application update 变成 contract 内的确定性 payload，而不是让模型猜。
```

实现内容：

```text
1. 在 strict runtime plan 下，仅对 phase=interview_review_update 且 required_tool=career_application_merge 的场景，
   构造确定性 career_application_merge payload。
2. 第一次模型重复 schema_search 仍给 runtime notice；
   第二次仍无推进时，把 schema_search 替换为 required career_application_merge。
3. required tool hint / auto-execute event 统一复用同一个 plan-aware hint。
4. 同步路径和 streaming/async 路径共用同一策略。
```

中途发现并修复了一个更根本的误判：

```text
用户消息包含“不要重新生成匹配报告或简历版本”时，
旧 guard 只看到“简历版本”，把 M16 的 career_application_merge 误判成 resume_version merge，
进而把复盘更新 payload 改写成 resume_version_ids merge，并触发 ledger reuse。
```

修复方式：

```text
1. turn intent boundary 支持“不要重新生成 ... 简历版本”这类共享动词否定句。
2. application action intent 增加“面试复盘 / 更新当前求职项目 / 项目备注”等判断。
3. workflow guard 增加单测：
   面试复盘更新项目不得被改写成 resume_version merge。
```

另外修正了 smoke 判重：

```text
career_application_merge 不能只按 application_id 判重；
同一个 Application 上可能先 merge resume_version_ids，后 merge interview review updates。
现在 smoke duplicate fingerprint 会把 updates 的稳定 hash 纳入签名。
```

验证：

```text
unit:
uv run pytest tests/test_agent_runtime.py tests/test_runtime_tool_plan.py tests/test_retrieval_action_flow.py tests/test_workflow_runtime_guard.py tests/test_intent_boundary.py -q
uv run pytest tests/test_finalization_packet.py tests/test_career_live_smoke_report.py tests/test_smoke_live_matrix.py -q
uv run mypy --explicit-package-bases app/runtime/agent_runtime.py app/runtime/workflow/intent_boundary.py app/runtime/workflow/guard.py tests/test_retrieval_action_flow.py tests/test_workflow_runtime_guard.py

focused live:
uv run python tools/smoke_live_matrix.py \
  --scenario interview_review \
  --runs 1 --concurrency 1 --stream \
  --data-dir data/live_smoke_matrix_m39_j_interview_action_payload_executor_c1_r3 \
  --json-report data/live_smoke_matrix_m39_j_interview_action_payload_executor_c1_r3/report.json

result:
success=1/1
elapsed=335.67s
llm_calls=23
tokens=127163
duplicates=0
harmful_duplicates=0
hidden=0
final_answer_recovery=11690/4
M16 tools=[retrieval_search, retrieval_context_pack, note_create, career_application_merge]
Application stage=interviewing
Application notes includes note_adc70d4047e5
Application evidence_refs includes Note
```

剩余观察项：

```text
resume_diagnosis 阶段仍可能多走 tool_search / career_profile_merge；
这是成本与主链路动作收敛问题，不属于 M16 写入正确性。
下一步不建议继续对单个偶发工具写 suppress，而应进入 live matrix + 成本/质量门禁。
```

### 12.14 M39-K：全量高并发 multi-batch live smoke 失败复盘

验证命令：

```text
uv run python tools/smoke_live_matrix.py \
  --all-p0 --all-p1 \
  --runs 2 \
  --concurrency 4 \
  --stream \
  --data-dir data/live_smoke_matrix_m39_k_full_p0p1_c4_r2 \
  --json-report data/live_smoke_matrix_m39_k_full_p0p1_c4_r2/report.json
```

结果：

```text
total=22
passed=17
failed=5

avg_elapsed=262.28s
max_elapsed=1470.16s
avg_tokens=66358
max_tokens=288729
avg_llm_calls=11.77
max_llm_calls=24

harmful_duplicate_tool_calls=0
hidden_tool_result_runs=2/22
failed_tool_result_runs=1/22
```

通过项说明：

```text
chat_only / memory_write / rag_read_only / main_resume_child / main_job_child 基本稳定；
rag_to_note=2/2；
interview_review=2/2，M39-J 的 Note -> CareerApplication deterministic payload executor 在并发下成立；
harmful_duplicate_tool_calls=0，说明幂等与 ledger 没有回归。
```

失败分层：

```text
1. career_custom_resume 2/2 failed
   缺 resume_versions；一次总耗时 1470s，项目动作阶段 1262s。
   真实根因不是 resume_version executor 不存在，而是本轮被路由成 application_action。

   触发方式：
   用户消息里同时出现：
     “不要重新创建 ResumeProfile、JDAnalysis 或 JobFitReport”
     “请生成或更新一版定制简历”

   旧 TurnIntentBoundary 的 negative resume_version regex 在 compact text 上用无界 .*?，
   会跨过前半句的“不要重新创建 ...”一直匹配到后半句的“定制简历”，
   因而误判 forbid_resume_version_create=true。

   结果：
   phase=application_action
   next_allowed_tools=career_application_get -> career_application_merge
   workflow executor 没有机会接管 career_resume_version_create。

2. note_write 1/2 failed
   用户目标是直接保存给定内容为 Note，但 runtime 把它走成 rag_note_write：
     retrieval_search -> retrieval_context_pack -> note_create/note_append

   这里 retrieval 不是必要步骤。
   且 note_create / note_append 被同时作为 required alternatives 暴露，
   strict runtime mode 无法收敛到唯一工具，模型重复 tool_search 后进入 stagnation。

   结构结论：
   direct note write 应该是 note.write.v1，只需要 note_create；
   只有“根据之前记录 / 召回 / 检索上下文后保存”才走 rag.note.write.v1。

3. rag_to_learning_task 1/2 failed
   action 阶段已经正确执行 retrieval_search -> retrieval_context_pack -> learning_task_create。
   失败来自前置 JD 阶段 job_agent 一次 career_jd_analysis_save 参数缺 evidence_refs。
   这是 child tool argument validation / repair 问题，不是 P1 action contract 问题。

4. career_full 1/2 failed
   quality gate 报 career_profile_source_drift：
   CareerProfile 写入了源简历不支持的“教育背景学校”事实。
   这是 source grounding 问题，不是 orchestration / idempotency 问题。
```

下一步修正边界：

```text
1. 修 TurnIntentBoundary 的 negative resume_version detection：
   禁止无界跨句匹配；
   只把短距离、明确指向 resume version 的否定表达判成 forbid_resume_version_create。

2. 把 direct note write 从 rag_note_write 拆出来：
   note.write.v1:
     note_create -> final

   rag.note.write.v1:
     retrieval_search -> retrieval_context_pack -> note_create/note_append -> final

3. 不在本轮处理 job_agent evidence_refs 和 career_profile source drift。
   它们分别属于 child 参数质量和事实 grounding，不能混进 workflow executor 修复里。
```

落地修正：

```text
1. TurnIntentBoundary:
   negative resume_version regex 从无界跨句匹配改为短距离匹配；
   覆盖“不要重新创建 ResumeProfile/JDAnalysis/JobFitReport。请生成定制简历”的回归。

2. Direct note write:
   新增 note.write.v1 action contract；
   phase=note_write 只允许 note_create；
   “把下面内容保存为笔记”不再先 retrieval；
   “把之前/准备内容保存为笔记”仍走 rag.note.write.v1。

3. Workflow executor:
   resume_version executor 内部每完成一步都推进 pending runtime plan；
   career_application_get 后，后续 career_resume_version_create 不再带着旧的
   career_application_read required plan 过 guard，避免 executor 自己被 runtime block。
```

验证：

```text
unit:
uv run pytest tests/test_intent_boundary.py tests/test_workflow_phase_guard.py tests/test_runtime_tool_plan.py \
  tests/test_retrieval_action_flow.py tests/test_workflow_executor.py tests/test_agent_runtime.py \
  tests/test_smoke_live_matrix.py tests/test_career_live_smoke_report.py -q

result:
passed

mypy:
uv run mypy --explicit-package-bases \
  app/runtime/workflow/intent_boundary.py app/runtime/workflow/career_phase.py \
  app/runtime/workflow/contracts.py app/runtime/workflow/tool_plan.py app/runtime/agent_runtime.py \
  tests/test_intent_boundary.py tests/test_workflow_phase_guard.py tests/test_runtime_tool_plan.py

result:
passed
```

focused live:

```text
note_write + career_custom_resume:
uv run python tools/smoke_live_matrix.py \
  --scenario note_write --scenario career_custom_resume \
  --runs 1 --concurrency 2 --stream \
  --data-dir data/live_smoke_matrix_m39_k_fix_note_custom_c2_r1 \
  --json-report data/live_smoke_matrix_m39_k_fix_note_custom_c2_r1/report.json

result:
passed=2/2
note_write tools=[note_create]
career_custom_resume passed, but first run still exposed executor internal stale-plan fallback.
```

executor stale-plan 修正后复验：

```text
uv run python tools/smoke_live_matrix.py \
  --scenario career_custom_resume \
  --runs 1 --concurrency 1 --stream \
  --data-dir data/live_smoke_matrix_m39_k_fix_custom_executor_plan_c1_r1 \
  --json-report data/live_smoke_matrix_m39_k_fix_custom_executor_plan_c1_r1/report.json

result:
passed=1/1
elapsed=189.12s
project_action_elapsed=29.14s
project_action_tools=[career_application_get, career_application_merge, career_resume_version_create]
duplicates=0
harmful_duplicates=0
hidden=0
tokens=80564
llm_calls=16
```

### 12.5 M39-L：JD 参数契约与 CareerProfile 诊断字段边界

全量 smoke 暴露两个剩余问题不能继续放进 workflow executor 修：

```text
rag_to_learning_task:
  career_jd_analysis_save 首次调用时，evidence_refs 被模型拼进 position 字符串；
  第二次重试成功，但 smoke 仍记录 failed_tool_result。

career_full:
  CareerProfile.resume_issues 中的“缺少教育背景学校和时间”被 live quality gate
  当成候选人学校事实，触发 career_profile_source_drift。
```

根因区分：

```text
1. JDAnalysis 是工具入参契约问题：
   模型偶发输出 <parameter=...> markup 残片；
   这不应该导致工具失败后再靠模型重试。

2. CareerProfile 是字段语义问题：
   resume_issues/interview_weaknesses 是诊断字段，不是候选人事实字段；
   quality gate 不能把“缺少学校”这类诊断语句按 source fact drift 判定。
```

落地修正：

```text
1. career_jd_analysis_save:
   对字符串字段中的嵌入式 <parameter=field>value 进行工具边界归一化；
   只接受该工具 schema 允许的字段；
   不覆盖已有显式参数。

2. CareerProfile:
   从 ResumeProfile 派生事实摘要时过滤“未提及/未明确/未提供”等 unknown placeholder；
   支持 level/duration 字段进入 education/experience summary；
   live quality gate 只对 CareerProfile fact fields 做候选人事实漂移检查，
   不再把 resume_issues/interview_weaknesses 当成事实字段。
```

验证：

```text
unit:
uv run pytest tests/test_career_tools.py tests/test_career_live_quality_gate.py \
  tests/test_smoke_live_matrix.py tests/test_workflow_executor.py \
  tests/test_runtime_tool_plan.py tests/test_retrieval_action_flow.py -q

result:
passed

mypy:
uv run mypy --explicit-package-bases \
  app/tools/builtin_tools/career.py tools/career_live_quality_gate.py \
  tests/test_career_tools.py tests/test_career_live_quality_gate.py

result:
passed
```

focused live:

```text
uv run python tools/smoke_live_matrix.py \
  --scenario rag_to_learning_task --scenario career_full \
  --runs 1 --concurrency 2 --stream \
  --data-dir data/live_smoke_matrix_m39_l_evidence_source_fix_c2_r1 \
  --json-report data/live_smoke_matrix_m39_l_evidence_source_fix_c2_r1/report.json

result:
passed=2/2
rag_to_learning_task:
  career_jd_analysis_save=1
  learning_task_create=1
  failed_tool_results=0
career_full:
  source_drift=0
```

full live:

```text
uv run python tools/smoke_live_matrix.py \
  --all-p0 --all-p1 \
  --runs 2 --concurrency 4 --stream \
  --data-dir data/live_smoke_matrix_m39_l_full_p0p1_c4_r2 \
  --json-report data/live_smoke_matrix_m39_l_full_p0p1_c4_r2/report.json

result:
runs=22
passed=18
failed=4
avg_elapsed=126.32s
avg_llm_calls=11.3
avg_tokens=54042
harmful_duplicate_runs=3/22
hidden_runs=1/22
```

已确认收口：

```text
career_full=2/2 passed
career_custom_resume 正向产物已生成，但 run2 因 hidden result 被 smoke 判失败
rag_to_learning_task=2/2 passed
career_jd_analysis_save failed_tool_results=0
career_profile_source_drift=0
```

新暴露但本轮不处理：

```text
rag_to_note:
  2/2 failed
  retrieval 后重复 note_create；
  首次 note_create 参数里 source_refs/evidence_refs 使用了 NoteService 不支持的别名：
    source_type=jd / application
    evidence_refs=application:...
  后续重试成功创建 Note，但 failed_tool_result + harmful duplicate 已经产生。

interview_review:
  1/2 failed
  同样是 note_create 参数别名错误后重试；
  source_type=career_jd_analysis / career_resume_profile 不被 NoteService 接受；
  第三次 note_create 成功，随后 career_application_merge 成功。

career_custom_resume:
  1/2 被 hidden runtime result 判失败；
  业务产物已生成，根因是前置 resume_diagnosis 阶段多了一次 tool_search hidden/suppression，
  不是 project action 失败。
```

下一步候选方向：

```text
不要继续补单个 note_create 重试 case。
先统一 NoteService 的 source_refs/evidence_refs 引用契约：
  - note_create 接受或归一化 career product ref aliases；
  - rag.note.write.v1 / interview.review.update.v1 给出确定的 allowed source_ref types；
  - note_create 成功后，contract barrier 必须终止，不允许重复 note_create；
  - smoke 对“首个失败后成功”的写工具仍保持失败，避免靠重试掩盖契约问题。
```

### 12.6 M39-M：Note 引用契约统一

M39-L full live 后，失败集中到 Note 写入：

```text
rag_to_note:
  2/2 failed
  note_create 首次参数使用了 NoteService 不支持的引用写法：
    source_type=jd / application
    evidence_refs=application:...

interview_review:
  1/2 failed
  note_create 首次参数使用了不支持的 career_* 别名：
    source_type=career_jd_analysis / career_resume_profile

共性：
  后续模型会重试并最终保存成功；
  但已经产生 failed_tool_result 和 harmful duplicate。
```

根因：

```text
NoteService 领域模型支持的 canonical source_type 是：
  artifact
  career_application
  resume_profile
  career_profile
  jd_analysis
  job_fit_report
  resume_version
  chat_message
  manual

但模型自然会输出：
  application / jd / fit
  career_jd_analysis / career_resume_profile
  application:application_xxx 这类 typed evidence ref

这不是 workflow executor 的问题，而是 Note 工具边界的引用契约没有统一。
```

落地修正：

```text
1. note_create / note_append / note_update:
   source_refs.source_type 统一 canonicalize：
     application -> career_application
     jd / career_jd_analysis -> jd_analysis
     fit -> job_fit_report
     career_resume_profile -> resume_profile

2. evidence_refs:
   支持 typed ref 字符串归一化：
     application:application_x -> application_x
     jd_analysis:jd_x -> jd_x
     job_fit_report:fit_x -> fit_x
     resume_profile:resume_profile_x -> resume_profile_x

3. note_create 幂等 key:
   使用 canonical references；
   避免同一条 Note 因引用写法不同绕过 tool ledger。
```

验证：

```text
unit:
uv run pytest tests/test_note_tools.py tests/test_tool_policy.py \
  tests/test_retrieval_action_flow.py tests/test_runtime_tool_plan.py \
  tests/test_smoke_live_matrix.py tests/test_career_live_smoke_report.py -q

result:
passed

mypy:
uv run mypy --explicit-package-bases \
  app/tools/builtin_tools/notes.py app/runtime/workflow/tool_idempotency.py \
  tests/test_note_tools.py tests/test_tool_policy.py

result:
passed
```

focused live:

```text
uv run python tools/smoke_live_matrix.py \
  --scenario rag_to_note --scenario interview_review \
  --runs 2 --concurrency 2 --stream \
  --data-dir data/live_smoke_matrix_m39_m_note_refs_fix_c2_r2 \
  --json-report data/live_smoke_matrix_m39_m_note_refs_fix_c2_r2/report.json

result:
runs=4
passed=4
failed=0
harmful_duplicate_runs=0/4
hidden_runs=0/4

rag_to_note:
  2/2 passed
  final action tools=[retrieval_search, retrieval_context_pack, note_create]
  note_create_count=1/run

interview_review:
  2/2 passed
  final action tools=[retrieval_search, retrieval_context_pack, note_create, career_application_merge]
  note_create_count=1/run
```

剩余观察：

```text
rag_to_note run2 出现 provider/model 长尾：
  total_elapsed=747.91s
  resume_diagnosis_elapsed=576.53s

该长尾不是 Note 引用契约失败；
后续若持续复现，需要单独做模型调用耗时和 resume_diagnosis 阶段 profile。
```

## 13. M39-N：retrieval alias 与 child resume diagnosis executor

本轮处理两个 focused live 暴露的问题：

```text
1. rag_read_only:
   模型会把产品域 source type 写成 career_match_report / career_project；
   retrieval 旧实现只接受 canonical source type，导致第一次 search 失败再恢复。

2. career_full:
   resume_agent 已完成诊断 artifact + ResumeProfile 后，仍可能继续尝试重复保存；
   旧路径靠 runtime suppress/hidden 收住，业务结果没坏但会产生失败门禁或额外轮次。
```

落地方式：

```text
retrieval:
  增加产品域常见 alias canonicalization：
    career_match_report -> job_fit_report
    career_project -> career_application
  仍保留 workspace 等非产品 source type 的严格拒绝。

workflow executor:
  新增 career.resume_diagnosis.child.v1 contract；
  只在 resume_agent + phase=resume_diagnosis + refs/outputs 齐全时触发；
  固定执行：
    model draft -> session_create_text_artifact -> career_resume_profile_save -> final
  不扩大到 main-agent，不把 job_agent 流程一起改掉。
```

验证：

```text
unit:
uv run pytest tests/test_retrieval_tools.py tests/test_workflow_executor.py \
  tests/test_agent_runtime.py::test_child_resume_diagnosis_executor_runs_closed_tool_chain \
  tests/test_retrieval_action_flow.py tests/test_smoke_live_matrix.py -q

result:
37 passed

py_compile:
python -m py_compile app/runtime/agent_runtime.py app/runtime/workflow/contracts.py app/tools/builtin_tools/retrieval.py

result:
passed
```

focused live：

```text
uv run python tools/smoke_live_matrix.py \
  --scenario rag_read_only --scenario career_full \
  --runs 2 --concurrency 2 --stream \
  --data-dir data/live_smoke_matrix_m39_n_retrieval_resume_executor_c2_r2 \
  --json-report data/live_smoke_matrix_m39_n_retrieval_resume_executor_c2_r2/report.json

result:
runs=4
passed=3
failed=1
harmful_duplicate_runs=0/4
hidden_runs=0/4
duplicate_runs=0/4

rag_read_only:
  2/2 passed
  tool chain = retrieval_search -> retrieval_context_pack
  failed_tool_results=0

career_full:
  1/2 passed
  resume_diagnosis child executor triggered in both runs
  child executor tool chain = session_create_text_artifact -> career_resume_profile_save
  hidden=0
  harmful_duplicate=0
  failed run business records still complete:
    ResumeProfile / JDAnalysis / JobFitReport / CareerApplication / ResumeVersion all exist
```

失败记录：

```text
career_full run_001:
  失败原因不是 retrieval alias，也不是 resume_diagnosis 重复保存。
  失败点在 JD 匹配阶段第一次 delegate_agents：

  delegate_agents.tasks[0]:
    缺 target_agent_id
    缺 artifact_refs

  delegate_agents.tasks[1]:
    target_agent_id=job_agent
    artifact_refs=[artifact_resume_live_001, artifact_jd_live_001]

  runtime guard 记录了 repair 动作，但仍把缺 target_agent_id 的 task 留在 tasks 里，
  ToolRunner 严格校验后返回：
    'target_agent_id' must be a non-empty string.

  第二次 delegate_agents 自动恢复成功，后续 CareerApplication 和 ResumeVersion 都完成。
```

当前判断：

```text
已解决：
  retrieval source alias 导致的 search 失败恢复；
  resume_agent 诊断完成后重复保存触发 hidden 的问题。

未解决：
  main-agent JD 阶段可能生成混合 delegate task list：
    一个 malformed task + 一个合法 job_agent task。

下一步不能直接补“缺 target_agent_id 就过滤”这种表层 guard。
更合理的方向是把 delegate_agents 的 tasks 参数也纳入 schema-level normalization：
  先按 task 完整性和 phase contract 归一化；
  对 jd_fit 阶段只保留合法 job_agent task；
  repair 后的最终 arguments 必须重新通过 delegate_agents schema validation；
  validation 失败时不执行工具，而是返回可恢复的 runtime decision。
```

## 14. 实施顺序

推荐顺序：

```text
1. M39-A：live smoke matrix runner + P0 场景门禁。
2. 用 matrix 跑当前基线，不做优化。
3. M39-B：本轮意图边界、只读 RAG 工具链、delegate 参数规范化。
4. M40：live quality gate，覆盖 final answer / generated artifact / product record 源事实漂移。
5. M39-C：executor contract dry-run。
6. M39-D：只实现 resume_version project-action executor。
7. M39-F：接入 streaming / async 产品入口。
8. 对比 matrix，达到停止线就停止性能优化。
9. M39-G：删除被 executor 覆盖的旧 guard 分支。
10. M39-H：对 P1 副作用复合动作引入 Action Contract 与 finalization barrier。
```

暂不做：

```text
不把 resume_agent/job_agent 全部改成 executor；
不做全局 LangGraph 迁移；
不为了单个 live smoke 长尾新增 suppress；
不继续压缩必要事实 token。
不把普通聊天、只读问答、开放式建议强行纳入 action contract。
```
