# M62 LangGraph 多 Agent 编排迁移方案

> 状态：待审核。本文只定义方案，不修改 `AgentTaskRuntime`、`delegate_agents`、LangGraph runner 或前端代码。

## 1. 背景

M59-M61 已经验证 LangGraph 可以承担：

- checkpoint 持久化；
- interrupt / resume；
- 服务重启恢复；
- 并发 resume lease；
- 写节点失败后的用户重试；
- ToolGateway / ToolCallLedger 下的副作用幂等。

但多 Agent 执行仍走旧链路：

```text
main-agent
  -> delegate_agents(wait=true)
  -> AgentTaskRuntime.run_group_async
  -> asyncio.gather
  -> child-agent 全部结束
  -> 聚合结果返回 main-agent
```

当前限制：

- `depends_on` 虽已存在于 `AgentTaskSpec`，但 runtime 和工具入口明确拒绝使用；
- task group 只支持一次性独立并发，不支持 DAG；
- 单个 child-agent 失败后不能暂停 workflow 等待用户重试；
- 服务在 child-agent 执行中退出时，无法从 child run 中间恢复；
- graph 节点若直接重放整个 `run_group_async`，可能重复调用 child-agent；
- main-agent 仍需理解子任务结果并决定下一步委派或写入。

M62 的目标不是给 `delegate_agents` 增加更多参数，而是把确定性的多 Agent 流程交给 LangGraph。

## 2. 首条迁移流程

首条 workflow：

```text
career.intake.analysis.interactive.v1
```

面向场景：

```text
用户提供简历和目标 JD，
希望完成简历画像、JD 分析、岗位匹配报告，
并在确认后创建求职项目。
```

流程：

```text
resolve_inputs
  -> input_confirmation interrupt（仅输入不明确时）
  -> fan-out
       resume_agent: 简历诊断 + ResumeProfile
       job_agent: JDAnalysis
  -> join_analysis
  -> resolve_fit_inputs
  -> job_agent: JobFitReport
  -> career_project_confirmation interrupt
  -> career_application_create
  -> final_answer
```

依赖关系：

```text
resume_analysis ───────┐
                       ├─> job_fit_analysis ─> project_confirmation
jd_analysis ───────────┘
```

选择这条流程的原因：

- 前两步真实独立，适合验证 fan-out；
- JobFitReport 同时依赖 ResumeProfile 和 JDAnalysis，适合验证 join / `depends_on`；
- CareerApplication 是清晰的最终副作用，可以放在用户确认之后；
- 已有 child-agent、工具合同和产品记录可复用；
- 不需要同时迁移定制简历、学习计划和面试复盘。

## 3. 第一阶段目标

M62 第一阶段必须实现：

1. 代码定义任务图，不让模型生成 DAG。
2. 独立子任务并发执行。
3. 依赖任务只在前置任务成功后启动。
4. child-agent 失败后 workflow 进入可恢复 interrupt。
5. 用户重试时只重新执行失败任务。
6. 已完成任务不重复执行。
7. 服务重启后可从等待重试、等待确认状态恢复。
8. 最终 CareerApplication 写入继续经过 ToolGateway。
9. 前端能展示任务状态和重试操作。
10. 旧 `delegate_agents` 路径保持兼容。

## 4. 非目标

第一阶段不做：

- 不迁移普通聊天。
- 不开放任意动态 DAG。
- 不让模型提交 `depends_on`。
- 不支持用户自定义 agent 拓扑。
- 不恢复 child-agent 内部某一轮 LLM/tool loop。
- 不把 LangGraph checkpoint 替换成 AgentTaskStore。
- 不取消现有 `delegate_agents`。
- 不迁移 `career_full` 的定制简历阶段。
- 不在第一批增加分布式 task queue。
- 不允许缺少 ResumeProfile 或 JDAnalysis 时强行生成 JobFitReport。

## 5. 核心边界

### 5.1 LangGraph

负责：

- workflow phase；
- 任务依赖；
- fan-out / join；
- checkpoint；
- interrupt / resume；
- 哪个失败任务允许重试；
- 最终确认和结束条件。

不负责：

- child-agent 专业推理；
- 工具业务参数校验；
- 产品写入幂等。

### 5.2 AgentTaskRuntime

继续负责：

- 调用指定 child-agent；
- child RunContext 隔离；
- task context 构建；
- child 结果引用提取；
- child 完成条件校验；
- 安全进度事件。

M62 需要把当前“一次创建并执行整个 group”的接口拆成可重入能力，但不重写 child-agent runtime。

### 5.3 AgentTaskStore

作为 child task 执行账本：

- task spec；
- attempt；
- queued / running / completed / failed；
- child_run_id；
- summary / error；
- output artifact refs / product refs。

它不是 graph checkpoint，也不决定 graph 下一条边。

### 5.4 ToolGateway / ToolCallLedger

继续负责：

- child-agent 内工具执行；
- `career_application_create` 等最终副作用；
- 幂等键；
- guard；
- 工具结果事实。

## 6. Workflow State

新增窄状态：

```text
MultiAgentCareerGraphState
  session_id
  run_id
  workflow_instance_id
  thread_id
  contract_id
  phase

  resume_artifact_id
  jd_artifact_id
  selected_career_profile_id

  task_specs
  task_execution_keys
  task_group_ids
  task_attempts
  task_results
  failed_task_keys

  known_refs
  outputs
  retry_counters
  pending_question
  last_error
  answer
```

`task_results` 只保存结构化摘要：

```json
{
  "resume_analysis": {
    "status": "completed",
    "task_id": "task_xxx",
    "child_run_id": "run_xxx",
    "product_refs": ["resume_profile_xxx"],
    "output_artifact_refs": ["artifact_xxx"]
  }
}
```

不把 child-agent 完整 prompt、完整消息历史或长报告正文放进 graph state。

## 7. 稳定任务定义

任务必须由代码注册：

```text
resume_analysis
  target_agent_id = resume_agent
  required_inputs = [resume_artifact_id]
  required_outputs = [resume_profile_id, diagnosis_artifact_id]
  depends_on = []

jd_analysis
  target_agent_id = job_agent
  required_inputs = [jd_artifact_id]
  required_outputs = [jd_analysis_id]
  depends_on = []

job_fit_analysis
  target_agent_id = job_agent
  required_inputs = [resume_profile_id, career_profile_id, jd_analysis_id]
  required_outputs = [job_fit_report_id, report_artifact_id]
  depends_on = [resume_analysis, jd_analysis]
```

`career_profile_id` 不作为并行 JDAnalysis 的输入。join 后优先复用
`resume_analysis` 返回的 CareerProfile；没有新引用时使用当前 active/default
CareerProfile，再启动 `job_fit_analysis`。

执行键：

```text
execution_key =
  workflow_instance_id
  + task_key
  + canonical input refs/hash
  + contract_version
```

同一个 execution key 已完成时直接复用，不再次调用 child-agent。

显式重试创建新的 attempt，但沿用 task key：

```text
resume_analysis attempt=1 failed
resume_analysis attempt=2 completed
```

## 8. Graph 结构

建议节点：

```text
init_request
resolve_inputs
input_confirmation
prepare_parallel_tasks
run_resume_analysis
run_jd_analysis
join_analysis
resolve_fit_inputs
run_job_fit_analysis
task_failure_review
prepare_project_preview
project_confirmation
create_career_application
write_retry
final_answer
```

并发采用 LangGraph fan-out：

```text
prepare_parallel_tasks
  -> Send(run_resume_analysis)
  -> Send(run_jd_analysis)
```

join 条件：

```text
resume_analysis.status == completed
and jd_analysis.status == completed
```

只有满足 join 条件才进入 `run_job_fit_analysis`。

## 9. 可重入任务执行适配层

不能直接在 graph node 中调用当前 `run_group_async()`，因为该方法会：

- 每次创建新 task group；
- 立即启动全部任务；
- 在进程内等待 gather；
- 无法按稳定 task key 复用。

M62 应新增窄适配层，例如：

```text
GraphAgentTaskExecutor
  ensure_task(...)
  execute_task(...)
  read_result(...)
  retry_task(...)
  reconcile_stale_task(...)
```

行为：

```text
ensure_task:
  按 execution_key 查找已有 attempt；
  completed -> 复用；
  failed -> 等待显式 retry；
  running 且 lease 有效 -> 不重复启动；
  running 且 lease 过期 -> 标记 stale/failed；
  不存在 -> 创建 queued attempt。

execute_task:
  queued -> acquire lease -> running -> invoke child-agent；
  成功后校验 required_outputs；
  completed/failed 写入 AgentTaskStore；
  释放 lease。
```

第一阶段仍是单机执行，但必须预留 task lease，避免多 Uvicorn 进程重复启动同一 child task。

## 10. 进程中断语义

M62 不承诺恢复 child-agent 内部模型循环。

正确语义：

```text
checkpoint 已完成 task:
  直接复用结果。

checkpoint 前 child task 正在运行，进程退出:
  task lease 过期后标记 stale/failed；
  workflow 进入 task_failure_review；
  用户确认重试后启动新 attempt。

child task 内已成功写入产品记录但进程未写回 task completed:
  新 attempt 仍通过 ToolGateway / ToolCallLedger / 业务自然键复用已有产物；
  completion validator 根据真实 product refs 判定完成。
```

不能在重启后静默重放全部 fan-out 节点。

## 11. 失败、重试和继续

新增 interrupt：

```text
workflow_task_retry
```

payload：

```json
{
  "type": "workflow_task_retry",
  "workflow_instance_id": "wf_xxx",
  "failed_tasks": [
    {
      "task_key": "jd_analysis",
      "target_agent_id": "job_agent",
      "attempt": 1,
      "error": "..."
    }
  ],
  "completed_tasks": ["resume_analysis"],
  "actions": ["retry_failed", "cancel"]
}
```

规则：

- required task 失败：只允许 `retry_failed` / `cancel`；
- optional task 失败：以后可增加 `skip_failed`，第一阶段不开放；
- retry 只创建失败 task 的新 attempt；
- 成功分支及其输出 refs 保留；
- dependent task 尚未执行时不算失败；
- cancel 不回滚已经生成的 ResumeProfile / JDAnalysis，只停止后续 JobFitReport 和 CareerApplication。

## 12. 用户确认

输入不明确时：

```text
input_confirmation
  选择简历 artifact
  选择 JD artifact
  可补充目标岗位说明
```

分析完成后：

```text
career_project_confirmation
  展示 ResumeProfile / JDAnalysis / JobFitReport 摘要
  展示拟创建的 CareerApplication
  actions = approve / edit_project_fields / cancel
```

确认前不创建 CareerApplication。

ResumeProfile、JDAnalysis、JobFitReport 属于分析产物，child-agent 执行成功后已持久化；取消只阻止最终项目创建，不删除分析产物。

## 13. 前端

第一阶段复用现有 chat workflow 和 agent task progress，不新增独立页面。

需要补充：

- fan-out 中每个 task 的 queued / running / completed / failed；
- join 等待状态；
- `workflow_task_retry` 的“重试失败步骤 / 取消”；
- 页面刷新后恢复 pending interrupt；
- 已完成步骤保持完成状态，不因重试失败步骤而回退。

不要把 graph 内部 node 名直接展示给用户。展示业务名称：

```text
解析简历
分析岗位
生成匹配报告
创建求职项目
```

## 14. 路由和兼容

新增独立 feature flag：

```text
LANGGRAPH_MULTI_AGENT_CAREER_ENABLED=false
```

路由必须保守：

命中：

```text
用户明确要求同时处理简历和 JD，
并生成匹配分析或求职项目。
```

不命中：

- 只解析简历；
- 只分析 JD；
- 已有完整产品记录的查看或总结；
- 定制简历；
- 普通问答；
- 用户明确只要只读建议。

未命中或 flag 关闭时继续走旧 runtime。

第一阶段不修改 `delegate_agents` schema，不向模型暴露 `depends_on`。

## 15. 分阶段实施

### M62-A：合同和 skeleton

- workflow id / state；
- task graph registry；
- router flag；
- runner skeleton；
- 不接 ChatService 默认路径。

### M62-B：可重入任务执行层

- execution key；
- task attempt；
- task lease；
- stale running reconciliation；
- 单任务执行和结果复用；
- 保留现有 `AgentTaskRuntime.run_group_async`。

### M62-C：fan-out / join

- `resume_analysis` 与 `jd_analysis` 并发；
- checkpoint；
- required output 校验；
- join；
- 单元测试验证真实并发。

### M62-D：依赖任务和用户重试

- `job_fit_analysis`；
- `workflow_task_retry`；
- 只重试失败 task；
- SQLite 重启恢复；
- 已完成分支 exactly-once。

### M62-E：项目确认和写入

- project preview；
- confirmation interrupt；
- `career_application_create`；
- 写入失败复用 M61-D `workflow_write_retry`。

### M62-F：真实入口和 live smoke

- dispatcher 注册；
- 前端 progress / retry；
- 进程级 crash injection；
- 新旧矩阵回归；
- 评估是否扩大路由。

## 16. 测试计划

单元测试：

- task graph 依赖校验；
- execution key 稳定性；
- completed task 复用；
- failed task 新 attempt；
- required output 缺失不得 completed；
- join 不提前；
- 只重试失败分支；
- cancel 不创建 CareerApplication。

SQLite 集成测试：

- fan-out 完成后重建 runner；
- 一个分支完成、一个分支失败后重启；
- retry 后只执行失败分支；
- confirmation 刷新恢复；
- stale running task reconciliation。

进程级 smoke：

1. 两个 child task 真实并发。
2. 注入 `jd_analysis` 首次失败。
3. `resume_analysis` 成功并保留。
4. workflow 在 retry interrupt 停止。
5. 杀掉 Uvicorn。
6. 新进程恢复并只重试 `jd_analysis`。
7. JobFitReport 只生成一次。
8. CareerApplication 只创建一次。

旧矩阵：

- P0 全量；
- `career_full`；
- `career_custom_resume`；
- `rag_to_note`；
- `rag_to_learning_task`；
- `interview_review`；
- 两条已有 LangGraph interactive workflow。

## 17. 验收标准

功能：

```text
fan-out 真实并发
depends_on 由代码图定义
required task 失败不会继续下游
retry 只执行失败 task
服务重启后可恢复
页面刷新后可恢复
CareerApplication exactly-once
```

稳定性：

```text
无 stale running 永久卡死
无重复 child task 副作用
无跨进程并发重复执行
旧矩阵无回归
```

效率：

```text
同输入下不比旧串行委派增加 child-agent 调用数
已完成 task 重试时不增加 LLM 调用
main-agent 不再负责生成 delegate_agents DAG 参数
```

## 18. 风险

### 风险 1：把旧 runtime 简单包进 graph

会导致进程重启后重复创建 task group。

控制：

- 先做 execution key / attempt / lease；
- graph node 只调用可重入 executor。

### 风险 2：双重状态源

控制：

```text
LangGraph checkpoint = workflow 推进事实源
AgentTaskStore = child task 执行账本
ToolCallLedger = 工具副作用账本
WorkflowInstanceStore = 查询投影
```

### 风险 3：并发写同一状态

控制：

- fan-out 节点只写各自 task key；
- join 统一聚合；
- 不让并发节点覆盖整个 `task_results`；
- 使用 reducer 或节点独立字段。

### 风险 4：child-agent 产物已写入但 task 状态丢失

控制：

- 稳定业务自然键；
- ToolGateway / ledger 复用；
- 重试后按真实产品记录重新完成判定。

### 风险 5：迁移范围过大

控制：

- 第一条只做到 CareerApplication 创建；
- 定制简历和后续项目动作继续走旧 workflow；
- flag 默认关闭；
- 完成 crash smoke 后才扩大路由。

## 19. 结论

M62 不应直接“给 `delegate_agents` 加 `depends_on`”。

正确顺序：

```text
稳定 task graph
  -> 可重入 task executor
  -> execution key / attempt / lease
  -> LangGraph fan-out / join
  -> 失败 interrupt
  -> 重启恢复
  -> 最终副作用确认
```

第一条迁移完成后，系统才具备继续迁移更长 Career workflow 的基础。
