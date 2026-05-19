# M24 Main-Agent 状态编排增强方案

## 1. 背景

当前 multi-agent 底座已经成立：

```text
main-agent
  -> 理解用户目标
  -> 调用 delegate_agents
  -> 等待 child-agent 结果
  -> 继续推进求职产品动作

child-agent
  -> 加载自己的 AGENT.md / skill / capability
  -> 自己调用自己的工具
  -> 写入自己职责内的产品记录或 artifact
  -> 返回结构化结果摘要
```

这说明最初设计方向没有错：main-agent 是编排者，child-agent 是自主执行者。

但 M23 live smoke 暴露出一个核心问题：main-agent 的编排粒度太低。它不仅在做高层任务编排，还在反复做低层状态确认：

```text
career_application_get
career_resume_profile_get / list
career_jd_analysis_get / list
career_job_fit_report_get / list
career_resume_version_get
career_resume_version_create
career_application_merge
```

这会带来三个问题：

- 工具轮次变多，耗时变长。
- 每轮都重复携带 system prompt、workflow rules、tool schema、工具状态，token 消耗高。
- LLM 对“当前流程是否已经完成”缺少确定性信号，容易重复读取、重复创建和重复确认。

因此 M24 的目标不是推翻 main-agent 编排，也不是立刻引入完整 LangGraph，而是补上 main-agent 编排所缺的确定性状态层。

## 2. 核心判断

### 2.1 main-agent 仍然是编排者

main-agent 应继续负责：

- 判断用户是否只是普通对话。
- 判断是否进入求职流程。
- 判断是否需要委派 resume_agent / job_agent。
- 判断是否需要生成定制简历、投递前检查、面试准备、学习任务。
- 组织最终面向用户的回答。

这部分需要语言理解和产品判断，适合 main-agent。

### 2.2 child-agent 仍然自主执行

child-agent 不应由 main-agent 代替调用细节工具。

例如：

```text
resume_agent
  -> session_read_artifact
  -> career_resume_profile_save
  -> session_create_text_artifact

job_agent
  -> session_read_artifact
  -> career_jd_analysis_save
  -> career_job_fit_report_save
  -> session_create_text_artifact
```

child-agent 应继续自己加载能力、调用工具、返回 manifest。main-agent 只消费结果。

### 2.3 低层状态编排不能继续靠 prompt 猜

main-agent 当前重复 `get/list` 的根因，不是“它在聪明地轮询任务状态”，而是它缺少一个可信的当前流程状态。

任务是否完成，应来自：

```text
AgentTask
delegate_agents compact result
agent_result_summary
successful tool_result
CareerProductStore
```

不应该靠 main-agent 一轮轮重新查。

## 3. M24 目标

M24 要做的是：

```text
给 main-agent 一个确定性、短小、可信的 CareerFlowState。
```

它要回答：

- 当前有哪些已确认产品记录？
- 当前求职项目串联了哪些记录？
- 哪些步骤已经完成？
- 哪些步骤缺失？
- 哪些工具在本 run 或当前流程里不要重复调用？
- 当前是否已经可以最终答复？
- 如果还没完成，下一步最小必要动作是什么？

目标效果：

```text
main-agent 继续做高层编排
runtime 提供确定性状态摘要
child-agent 继续自主执行
不引入固定 DAG
不把普通聊天强行塞进 career workflow
```

## 4. 非目标

M24 第一阶段不做：

- 不直接引入 LangGraph 依赖。
- 不新增完整 workflow runtime 服务。
- 不把主流程写死成固定 DAG。
- 不让 workflow 层替代 main-agent 的意图判断。
- 不取消 child-agent 自主工具调用。
- 不改变 CareerProductStore / SessionArtifact / AgentTask / memory 的事实源边界。
- 不做前端 UI。
- 不做 RAG 召回优化。

## 5. 与 LangGraph 的关系

LangGraph 的价值在于：

- 显式状态。
- 节点执行。
- 条件边。
- checkpoint。
- 失败恢复。
- human-in-the-loop。
- 可视化和可测试的执行图。

这些思想是对的，也是后续 harness 的核心。

但当前阶段直接接入 LangGraph 有两个风险：

- 容易把 main-agent 的编排权过早迁出去，和现有架构职责重叠。
- 当前真正痛点还不是复杂 DAG，而是 main-agent 缺少可信状态，导致重复确认和重复执行。

因此 M24 采用“先做状态抽象，后续可迁移到 LangGraph”的路径。

```text
M24 CareerFlowState
  -> 明确状态结构、完成条件、去重约束、下一步提示

后续 LangGraph / harness
  -> 把 CareerFlowState 作为 graph state
  -> 把 child-agent 委派、产品记录写入、RAG 召回变成 node
  -> 把 completed / missing / next_action_hint 变成条件边依据
```

也就是说，M24 是 LangGraph 前置底座，不是替代 LangGraph。

## 6. 总体设计

新增轻量状态编排层：

```text
ContextAssembler
  -> ShortTermContextPlan
  -> CareerFlowStateExtractor
  -> current_career_flow_state section
  -> main-agent
```

它不执行工具，不调用模型，不启动 agent，只做确定性状态归纳。

### 6.1 状态来源

第一阶段从这些来源提取：

```text
successful tool_result
agent_result_summary
child-agent compact result
current_workflow_state
CareerProductStore 当前 active 记录
SessionArtifact 当前 active artifact
```

优先级：

```text
本 run 成功工具结果
  > child-agent result summary
  > 当前会话最近产品记录
  > active artifacts
  > 历史摘要
```

M24 第一阶段可以先不做深度跨 store 扫描，只基于当前会话事件和已进入 `current_workflow_state` 的 refs。若要进一步减少跨 turn 的重复确认，再增加 CareerProductStore 查询。

### 6.2 CareerFlowState 模型

建议新增：

```text
app/runtime/context/career_flow_state.py
```

核心结构：

```text
CareerFlowState
  application_id
  resume_source_artifact_id
  jd_source_artifact_id
  resume_profile_id
  career_profile_id
  jd_analysis_id
  job_fit_report_id
  report_artifact_id
  diagnosis_artifact_id
  resume_version_ids
  resume_version_artifact_ids
  completed_steps
  missing_steps
  reusable_refs
  do_not_repeat_tools
  next_action_hint
  final_answer_ready
```

示例：

```json
{
  "application_id": "application_xxx",
  "resume_profile_id": "resume_profile_xxx",
  "career_profile_id": "career_profile_default",
  "jd_analysis_id": "jd_xxx",
  "job_fit_report_id": "fit_xxx",
  "resume_version_ids": ["resume_version_xxx"],
  "completed_steps": [
    "resume_profile",
    "career_profile",
    "jd_analysis",
    "job_fit_report",
    "career_application",
    "resume_version"
  ],
  "missing_steps": [],
  "do_not_repeat_tools": [
    "career_resume_profile_get",
    "career_jd_analysis_get",
    "career_job_fit_report_get",
    "career_resume_version_create"
  ],
  "next_action_hint": "定制简历已创建并合并进求职项目，应直接给最终答复。",
  "final_answer_ready": true
}
```

## 7. 状态推导规则

### 7.1 completed_steps

第一版规则：

```text
resume_profile
  有 resume_profile_id

career_profile
  有 career_profile_id，通常为 career_profile_default

jd_analysis
  有 jd_analysis_id

job_fit_report
  有 job_fit_report_id

career_application
  有 application_id

resume_version
  有 resume_version_id 或 resume_version_ids 非空
```

### 7.2 missing_steps

按用户当前意图决定，不做固定全流程。

例如：

```text
普通聊天
  missing_steps = []

只做简历诊断
  需要 resume_profile / career_profile

只做 JD 分析
  需要 jd_analysis

简历 + JD 匹配
  需要 resume_profile / career_profile / jd_analysis / job_fit_report / career_application

生成定制简历
  需要 resume_profile / jd_analysis / job_fit_report / career_application / resume_version

项目动作：生成定制简历
  先需要 application_id
  再复用 application 关联 refs
  如果已有可用 resume_version 且用户没有要求另一版，可以 final_answer_ready
```

第一阶段可以先用关键词 + refs 推导，不做复杂 LLM intent 分类。

### 7.3 do_not_repeat_tools

状态层要给 main-agent 明确去重边界：

```text
如果本 run 已成功读取某记录：
  不要重复 get 同一 id

如果已保存 JDAnalysis：
  不要再次 career_jd_analysis_save 同一 JD

如果已保存 JobFitReport：
  不要再次 career_job_fit_report_save 同一 JD / ResumeProfile

如果已创建 ResumeVersion：
  除非用户明确要求另一版，否则不要再次 career_resume_version_create

如果 ResumeVersion 已合并进 CareerApplication：
  直接最终答复，不要重新读取全部关联记录
```

### 7.4 next_action_hint

`next_action_hint` 必须是短句，不做长推理。

示例：

```text
已拿到 resume_profile_id 和 JD artifact，可委派 job_agent 生成 JDAnalysis 和 JobFitReport。

已拿到 jd_analysis_id、job_fit_report_id 和 resume_profile_id，应创建或更新 CareerApplication。

定制简历已创建并已合并进 CareerApplication，应直接给最终答复。

当前只是普通聊天，不需要进入 career workflow。
```

## 8. Context 注入

新增 section：

```text
current_career_flow_state
```

只对 main-agent 注入，child-agent 不需要。

格式必须短：

```text
Current career flow state:
- application_id=application_xxx
- resume_profile_id=resume_profile_xxx
- jd_analysis_id=jd_xxx
- job_fit_report_id=fit_xxx
- resume_version_ids=resume_version_xxx
- completed=resume_profile,jd_analysis,job_fit_report,career_application,resume_version
- final_answer_ready=true
- next_action=定制简历已创建并合并进求职项目，应直接给最终答复。
- do_not_repeat=career_resume_profile_get,career_jd_analysis_get,career_job_fit_report_get,career_resume_version_create
```

控制目标：

```text
300-600 tokens
```

不要把完整产品记录塞进去。

## 9. 与 current_workflow_state 的关系

当前已有 `current_workflow_state`，它主要做：

```text
从成功工具结果里抽取最新 refs
```

M24 不替代它，而是在它之上增加语义层：

```text
current_workflow_state
  -> 有哪些 id

current_career_flow_state
  -> 这些 id 代表哪些步骤已完成
  -> 哪些工具不要重复调
  -> 下一步该做什么
  -> 是否可以最终答复
```

如果实现时发现 section 重叠，可以在 M24 后续把二者合并成一个更强的状态 section，避免 token 重复。

## 10. 并发编排原则

M24 不直接实现完整 DAG，但要把并发原则写入状态和规则中。

### 10.1 可以并发的情况

当用户同时提供简历和 JD，且两者都需要处理：

```text
resume_agent
  -> 解析简历 / 生成 ResumeProfile

job_agent
  -> 解析 JD / 生成 JDAnalysis
```

如果 job_fit_report 需要 resume_profile_id，则可以拆成：

```text
并发第一层：
  resume_agent -> ResumeProfile
  job_agent -> JDAnalysis

barrier：
  等 ResumeProfile + JDAnalysis

第二层：
  job_agent 或 main-agent -> JobFitReport
  main-agent -> CareerApplication
```

当前 delegate_agents 只支持 independent child tasks，不能传 depends_on。M24 不强行实现依赖图，但要避免 main-agent 把可并发任务拆成多个串行 delegate 调用。

### 10.2 不需要启动 child-agent 的情况

```text
普通聊天
  不启动 child-agent

已有 application_id，用户要求查看 / 总结 / 继续推进
  先复用 application 关联 refs
  不启动 resume_agent / job_agent

已有 ResumeProfile，用户要求定制简历
  不启动 resume_agent

已有 JDAnalysis / JobFitReport，用户要求定制简历
  不启动 job_agent
```

## 11. 开发计划

### 11.1 第一批

```text
1. app/runtime/context/career_flow_state.py
2. app/runtime/context/models.py 增加 CareerFlowState
3. app/runtime/context_assembler.py 提取 career flow state
4. app/runtime/context/section_builder.py 注入 current_career_flow_state
5. tests/test_career_flow_state.py
6. tests/test_context_assembler.py 补 section 验证
```

第一批只做状态提取和 prompt 注入，不改工具、不改前端、不改 agent capability。

### 11.2 第二批

根据 smoke 结果决定是否继续：

```text
1. 将 career workflow rules 中重复 get/list 的提示收敛
2. 将 current_workflow_state 与 current_career_flow_state 合并或去重
3. 对 project-action custom_resume 增加完成条件门禁
4. 增加 token debug 中 career flow state 的统计字段
```

### 11.3 第三批

为后续 LangGraph / harness 做准备：

```text
1. 将 CareerFlowState 转为 graph state 兼容结构
2. 定义 CareerFlowNode 枚举
3. 定义节点输入输出 manifest
4. 定义 barrier / dependency 表达
5. 评估是否接入 LangGraph
```

## 12. 测试计划

### 12.1 单元测试

覆盖：

- 从 `career_resume_profile_save` 提取 `resume_profile_id`。
- 从 `career_jd_analysis_save` 提取 `jd_analysis_id`。
- 从 `career_job_fit_report_save` 提取 `job_fit_report_id` 和 `report_artifact_id`。
- 从 `career_application_create/get/merge` 提取关联 refs。
- 从 `career_resume_version_create` 提取 `resume_version_id` 和 artifact。
- 成功创建 ResumeVersion + merge CareerApplication 后，`final_answer_ready=true`。
- 已完成记录生成 `do_not_repeat_tools`。
- 普通聊天不注入 career flow state。

### 12.2 确定性 runtime 测试

构造模型序列：

```text
1. tool_search
2. career_application_get
3. career_resume_version_create
4. career_application_merge
5. final answer
```

验证：

- merge 后下一轮上下文包含 `final_answer_ready=true`。
- 模型不需要再次 get 全部 linked records。
- 工具轮次不被 tool_search 过度消耗。

### 12.3 live smoke

低成本验证：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
WORKFLOW_RULE_SELECTION_MODE=sparse
```

指标：

```text
主链路通过
main-agent total_tokens 下降或不回升
main-agent LLM calls 不增加
career_*_get/list 重复次数下降
项目动作不再重复创建 ResumeVersion
```

## 13. 验收标准

M24 第一阶段通过标准：

- 不破坏普通对话。
- 不破坏简历诊断、JD 匹配、定制简历主链路。
- `current_career_flow_state` 在相关求职流程中可见。
- 已完成定制简历并 merge 后，main-agent 能直接最终答复。
- `career_resume_profile_get`、`career_jd_analysis_get`、`career_job_fit_report_get` 重复调用次数下降。
- search+compact+sparse live smoke 通过。

建议目标：

```text
main-agent total_tokens 比 M23 guided smoke 再下降 15%-25%
项目动作阶段工具调用数降到 6-8 个以内
项目动作阶段 tool_search 不超过 1 次
项目动作阶段不重复创建 ResumeVersion
```

## 14. 风险与控制

### 14.1 状态误判

风险：状态层把未完成流程标记为完成。

控制：

- 只基于 successful tool_result / AgentTask completed / active product record。
- `final_answer_ready` 只在强条件满足时为 true。
- 缺少关键 id 时只给 next_action_hint，不强行完成。

### 14.2 过度约束 main-agent

风险：main-agent 因为 `do_not_repeat_tools` 不敢处理用户明确要求的新版本。

控制：

- 文案写成“除非用户明确要求另一版”。
- `do_not_repeat_tools` 是提示，不是 runtime 拦截。
- 真正的工具保护仍由模型校验和 store 校验负责。

### 14.3 token 反增

风险：新增 section 反而增加 prompt。

控制：

- section 控制在 300-600 tokens。
- 如果 `current_career_flow_state` 与 `current_workflow_state` 重复，后续合并。
- 不塞完整记录正文。

## 15. 结论

M24 的核心不是新增一个庞大的 workflow runtime，而是把 main-agent 编排中最脆弱的部分确定化：

```text
main-agent 继续做高层编排
child-agent 继续自主执行
runtime 提供确定性 CareerFlowState
```

这一步抓住当前核心矛盾：

- 不是 child-agent 不自主。
- 不是 main-agent 不该编排。
- 不是必须立即接 LangGraph。
- 而是 main-agent 缺少可信流程状态，导致低层重复确认和重复执行。

先把 CareerFlowState 做稳，后续如果流程节点、依赖和恢复逻辑继续复杂化，再把这层自然迁到 LangGraph / harness。
