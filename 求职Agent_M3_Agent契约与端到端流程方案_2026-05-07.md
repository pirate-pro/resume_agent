# 求职 Agent M3 Agent 契约与端到端流程方案

日期：2026-05-07

## 1. 目标

M3 的目标是让已经具备的 M1 产品记录层和 M2 工具层真正进入 agent 行为闭环。

M3 不新增产品模型，不新增 API，不做前端。它只解决一个问题：

```text
agent 在求职任务中必须创建和复用产品记录，而不是只返回自然语言分析。
```

完成 M3 后，最小求职闭环应该可以通过确定性 fake model 测试跑通：

```text
上传或创建简历 artifact
  -> agent_main 委派 resume_agent
  -> resume_agent 创建诊断 artifact 和 ResumeProfile
  -> agent_main merge CareerProfile
  -> 用户粘贴 JD
  -> agent_main 创建 pasted_text artifact
  -> agent_main 委派 job_agent
  -> job_agent 创建 JDAnalysis 和 JobFitReport
  -> agent_main 创建 ResumeVersion
```

## 2. M3 范围

### 2.1 包含

- 更新三份 agent 静态契约：
  - `app/agents/default/AGENT.md`
  - `app/agents/resume_agent/AGENT.md`
  - `app/agents/job_agent/AGENT.md`
- 让 child-agent 的汇总结果能稳定带回产品记录引用。
- 新增确定性流程测试，验证工具调用序列和最终产品资产存在。
- 必要时小幅补充 `AgentInvocationService` / `AgentTaskRuntime` 的结果引用协议。

### 2.2 不包含

- 不新增或修改 career 数据模型。
- 不新增 career 工具。
- 不改 memory 策略。
- 不做 API。
- 不做前端。
- 不做复杂自然语言评测。
- 不依赖真实 LLM 稳定性。
- 不实现 `wait=false` 委派。

## 3. 当前缺口

M2 之后，工具已经可以完成产品记录写入，但 agent 行为还没有被收紧。

当前风险：

- `resume_agent` 可能只输出简历诊断文本，不调用 `career_resume_profile_save`。
- `job_agent` 可能只输出岗位匹配文本，不调用 `career_jd_analysis_save` 和 `career_job_fit_report_save`。
- `agent_main` 可能把 child-agent 结果直接转述给用户，不更新 `CareerProfile`。
- child-agent 创建了记录，但主 agent 只能从自然语言 summary 里猜测 id。
- 端到端测试如果只断言回答文本，无法证明产品资产真的落地。

M3 要把这些风险通过契约和测试收住。

## 4. Agent 契约调整

### 4.1 `agent_main`

新增职责：

- 识别求职资产创建场景。
- 对简历、JD、匹配、简历版本流程优先使用 career 工具。
- 编排 child-agent，但最终产品资产闭环由 main-agent 确认。
- 汇总 child-agent 结果后，更新 `CareerProfile`。
- 创建最终 `ResumeVersion`。

需要写入 `app/agents/default/AGENT.md` 的规则：

```text
## 求职产品资产规则

- 当用户要求简历诊断、岗位匹配、JD 分析或定制简历时，不能只给自然语言回答；需要优先创建或复用 career 产品记录。
- 用户粘贴 JD 时，必须先调用 session_create_text_artifact 创建 pasted_text artifact，再把 artifact_id 传给 job_agent。
- 委派 resume_agent 处理简历 artifact 后，必须从结果中确认 resume_profile_id 和 diagnosis_artifact_id。
- 拿到 ResumeProfile 后，使用 career_profile_merge 更新 career_profile_default。
- 委派 job_agent 分析 JD 后，必须从结果中确认 jd_analysis_id、job_fit_report_id 和 report_artifact_id。
- 创建最终 markdown 简历版本前，必须先调用 session_create_text_artifact 创建 generated_file artifact，再调用 career_resume_version_create。
- 不把 workspace path 传给 child-agent；跨 agent 资料只传 artifact_id 和产品记录 id。
- 如果必须创建产品记录但缺少关键 artifact_id 或产品记录 id，应先补齐，不要假装已经完成。
```

边界：

- 不直接保存 `ResumeProfile`。
- 不直接保存 `JDAnalysis`。
- 不直接保存 `JobFitReport`。
- 不把 `CareerProfile` 写入 memory。

### 4.2 `resume_agent`

新增职责：

- 读取简历 artifact 或 instruction 内简历文本。
- 创建用户可读诊断 artifact。
- 保存结构化 `ResumeProfile`。
- 在最终回答中明确返回产品记录引用。

需要写入 `app/agents/resume_agent/AGENT.md` 的规则：

```text
## 求职产品记录规则

- 当任务要求解析或诊断简历，并且有可用简历 artifact_id 时，必须调用 career_resume_profile_save 保存 ResumeProfile。
- 简历诊断如果需要给用户复用，必须先调用 session_create_text_artifact 创建 generated_file artifact，再把 artifact_id 写入 diagnosis_artifact_id。
- career_resume_profile_save 的 source_artifact_id 必须指向简历原文 artifact。
- evidence_refs 至少包含简历原文 artifact_id；如创建了诊断 artifact，也应包含该 artifact_id。
- 最终回答必须包含 resume_profile_id、source_artifact_id、diagnosis_artifact_id。
- 不更新 CareerProfile。
- 不保存 JDAnalysis、JobFitReport、ResumeVersion。
```

输出约定：

```text
创建记录：
- resume_profile_id: resume_profile_xxx
- source_artifact_id: artifact_xxx
- diagnosis_artifact_id: artifact_xxx
```

### 4.3 `job_agent`

新增职责：

- 读取 JD artifact。
- 读取已有 `ResumeProfile` 和 `CareerProfile`。
- 保存 `JDAnalysis`。
- 创建用户可读匹配报告 artifact。
- 保存 `JobFitReport`。
- 在最终回答中明确返回产品记录引用。

需要写入 `app/agents/job_agent/AGENT.md` 的规则：

```text
## 求职产品记录规则

- 当任务要求 JD 分析时，必须调用 career_jd_analysis_save 保存 JDAnalysis。
- 当任务要求岗位匹配时，必须先读取 resume_profile_id 和 career_profile_id，再调用 career_job_fit_report_save 保存 JobFitReport。
- 匹配报告如果面向用户可见，必须先调用 session_create_text_artifact 创建 generated_file artifact，再把 artifact_id 写入 report_artifact_id。
- JobFitReport.source_artifact_id 指 JD artifact；report_artifact_id 指报告 artifact。
- evidence_refs 至少包含 resume_profile_id、career_profile_id、jd_analysis_id、JD artifact_id 和 report_artifact_id。
- 最终回答必须包含 jd_analysis_id、job_fit_report_id、source_artifact_id、report_artifact_id。
- 不更新 CareerProfile。
- 不保存 ResumeProfile。
- 不创建最终 ResumeVersion。
```

输出约定：

```text
创建记录：
- jd_analysis_id: jd_xxx
- job_fit_report_id: fit_xxx
- source_artifact_id: artifact_xxx
- report_artifact_id: artifact_xxx
```

## 5. Child-Agent 结果引用协议

当前 `AgentInvocationResult.artifact_refs` 只保留委派时传入的 artifact refs，不能表达 child-agent 新创建的产品记录。

M3 建议先做轻量协议，不新增复杂模型：

### 5.1 文本协议

要求 child-agent 最终回答包含固定小节：

```text
创建记录：
- resume_profile_id: resume_profile_xxx
- diagnosis_artifact_id: artifact_xxx
```

或：

```text
创建记录：
- jd_analysis_id: jd_xxx
- job_fit_report_id: fit_xxx
- report_artifact_id: artifact_xxx
```

优点：

- 不改运行时数据结构也能工作。
- fake model 测试可以稳定断言。
- 主 agent 可以根据文本继续调用读取工具。

缺点：

- 仍然依赖文本格式。

### 5.2 后续结构化协议

后续可扩展 `AgentInvocationResult`：

```json
{
  "artifact_refs": [],
  "product_refs": [
    {"type": "resume_profile", "id": "resume_profile_xxx"},
    {"type": "job_fit_report", "id": "fit_xxx"}
  ]
}
```

M3 暂不引入该结构，先用文本协议和确定性测试把流程跑通。

## 6. 确定性测试设计

新增测试文件建议：

```text
tests/test_career_agent_flow.py
```

测试不依赖真实模型，使用 `SequenceModelClient` 固定每轮工具调用。

### 6.1 测试一：简历画像流程

目标：

```text
agent_main -> delegate_agents(resume_agent)
resume_agent -> session_create_text_artifact
resume_agent -> career_resume_profile_save
agent_main -> career_resume_profile_get
agent_main -> career_profile_merge
```

断言：

- `ResumeProfile` 存在。
- `diagnosis_artifact_id` 是 session artifact。
- `CareerProfile` 存在并包含 merge 后字段。
- main visible events 有 `agent_task_assigned` 和 `agent_result_summary`。
- child-agent events 里有 `career_resume_profile_save` 工具调用。

### 6.2 测试二：JD 匹配流程

目标：

```text
agent_main -> session_create_text_artifact(kind=pasted_text)
agent_main -> delegate_agents(job_agent, artifact_refs=[jd_artifact_id])
job_agent -> career_resume_profile_get
job_agent -> career_profile_get
job_agent -> career_jd_analysis_save
job_agent -> session_create_text_artifact(kind=generated_file)
job_agent -> career_job_fit_report_save
agent_main -> career_job_fit_report_get
```

断言：

- JD artifact kind 为 `pasted_text`。
- `JDAnalysis.source_artifact_id` 指 JD artifact。
- `JobFitReport.source_artifact_id` 指 JD artifact。
- `JobFitReport.report_artifact_id` 指报告 artifact。
- 不出现 workspace path 参数。

### 6.3 测试三：定制简历版本流程

目标：

```text
agent_main -> session_create_text_artifact(kind=generated_file, media_type=text/markdown)
agent_main -> career_resume_version_create
```

断言：

- `ResumeVersion.format == markdown`。
- `ResumeVersion.artifact_id` 是 session artifact。
- `ResumeVersion.source_artifact_id == artifact_id`。
- `evidence_refs` 包含 `resume_profile_id`、`jd_analysis_id`、`job_fit_report_id` 和简历版本 artifact。

### 6.4 测试四：权限保护

目标：

- `resume_agent` 不能调用 `career_jd_analysis_save`。
- `job_agent` 不能调用 `career_profile_merge`。
- `agent_main` 不能调用 `career_resume_profile_save`、`career_jd_analysis_save`、`career_job_fit_report_save`。

这部分已有 M2 测试覆盖一部分，M3 可以只补端到端流程中容易绕过的场景。

## 7. 推荐开发顺序

```text
1. 更新 app/agents/default/AGENT.md
2. 更新 app/agents/resume_agent/AGENT.md
3. 更新 app/agents/job_agent/AGENT.md
4. 新增 tests/test_career_agent_flow.py 的测试 fixture
5. 写简历画像流程确定性测试
6. 写 JD 匹配流程确定性测试
7. 写定制简历版本流程确定性测试
8. 视测试需要补最小运行时引用协议
9. 跑 mypy 和全量 pytest
```

顺序理由：

- 先固定 agent 行为契约，再用测试证明契约可执行。
- 不先改运行时，避免过早设计 `product_refs`。
- 如果文本协议足够，M3 可以不改 runtime 数据结构。

## 8. 需要注意的边界

### 8.1 不把产品资产写入 memory

`CareerProfile` 是产品资产，不是 memory。M3 的 prompt 里不要要求 agent 把简历画像、JD 分析、匹配报告写入 memory。

### 8.2 不把粘贴 JD 直接交给 job_agent 后就结束

用户粘贴 JD 时，main-agent 必须先创建 `SessionArtifact`。如果直接把 JD 原文塞进 child instruction，虽然当前 delegate 工具支持，但会破坏 M2 的 artifact-first 目标。

### 8.3 不让 child-agent 访问 workspace path

所有跨 agent 资料传递只用：

```text
artifact_id
resume_profile_id
career_profile_id
jd_analysis_id
job_fit_report_id
resume_version_id
```

### 8.4 不在 M3 引入前端验收

M3 的验收以后端产品记录和 event log 为准。前端读取视图进入 M4。

## 9. 验收标准

M3 完成时需要满足：

1. 三份 `AGENT.md` 已明确 career 产品记录创建规则。
2. 简历画像流程确定性测试通过。
3. JD 匹配流程确定性测试通过。
4. 简历版本创建流程确定性测试通过。
5. 测试能证明产品记录真实写入 `CareerProductStore`。
6. 测试能证明用户可见 markdown 输出先写入 `SessionArtifact`。
7. 测试能证明粘贴 JD 先写入 `SessionArtifact(kind=pasted_text)`。
8. 测试能证明权限矩阵没有被绕过。
9. `uv run pytest tests/test_career_product_store.py` 通过。
10. `uv run pytest tests/test_career_tools.py` 通过。
11. `uv run pytest tests/test_career_agent_flow.py` 通过。
12. `uv run mypy` 通过。
13. `uv run pytest` 通过。

## 10. M4 预告

M3 通过后，下一步建议进入 M4：

```text
Career API + 最小前端读取视图
```

M4 才开始解决用户在聊天之外查看这些资产的问题。M3 只负责让后端 agent 流程稳定产出资产。
