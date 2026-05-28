# M43：产品验收与回归基线方案

> 状态：M43-B 两批并发验收已完成。M42 已把 runtime / action contract / tool gateway 的主要结构边界收口，最新全量 P0/P1 live matrix 曾达到 `11/11 passed`、`hidden_runs=0/11`、`harmful_duplicate_runs=0/11`。M43 不继续追逐单点 runtime 细节，转向产品可交付验收和稳定回归基线。

## 1. 背景

M42 后系统已经解决了几类核心问题：

```text
1. 工具重复调用的副作用风险：
   harmful_duplicate_runs=0。

2. hidden/runtime-hidden 工具结果：
   hidden_runs=0。

3. 多阶段 action 的工具边界：
   current_allowed_tools 与 upcoming_required_tools 已拆分。

4. RAG 后写入动作：
   rag_to_note / rag_to_learning_task / interview_review 均通过 live smoke。
```

当前不应该继续把精力放在“再压一点 token / 再省几秒 / 再防一个偶发工具选择”上。产品推进更需要一个稳定验收基线：

```text
哪些场景必须通过？
失败时如何判断是否阻断发布？
成本和耗时到什么程度可以接受？
什么时候停止继续优化？
```

## 2. M43 目标

M43 的目标不是改架构，而是形成产品验收基线。

```text
1. 建立 P0/P1 live smoke 全量验收矩阵。
2. 记录 M42 后的真实并发稳定性基线。
3. 定义产品停止线，避免继续陷入长尾补丁。
4. 为后续新增 agent / skill / workflow 提供回归样本。
```

## 3. 验收范围

本轮覆盖 `tools/smoke_live_matrix.py` 已定义的 P0/P1 场景。

P0：

```text
chat_only
memory_write
note_write
rag_read_only
main_resume_child
main_job_child
career_full
```

P1：

```text
career_custom_resume
rag_to_note
rag_to_learning_task
interview_review
```

这些场景覆盖的产品能力：

```text
仅聊天；
长期记忆写入；
笔记写入；
RAG 只读召回；
main-agent + resume-agent；
main-agent + job-agent；
完整 career 主链路；
基于已有求职项目生成定制简历；
RAG 后保存 Note；
RAG 后创建 LearningTask；
面试复盘写 Note 并更新 CareerApplication。
```

## 4. 验收命令

本轮先跑两批全量 P0/P1，并发为 6，每批每场景 1 run。

第一批：

```bash
uv run python tools/smoke_live_matrix.py \
  --all-p0 \
  --all-p1 \
  --runs 1 \
  --concurrency 6 \
  --stream \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m43_acceptance_c6_b1 \
  --json-report data/live_smoke_matrix_m43_acceptance_c6_b1/report.json \
  --quiet
```

第二批：

```bash
uv run python tools/smoke_live_matrix.py \
  --all-p0 \
  --all-p1 \
  --runs 1 \
  --concurrency 6 \
  --stream \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m43_acceptance_c6_b2 \
  --json-report data/live_smoke_matrix_m43_acceptance_c6_b2/report.json \
  --quiet
```

## 5. 产品停止线

M43 不追求数学上的零波动，而是定义产品可接受的停止线。

必须满足：

```text
P0 全通过。
P1 不出现副作用错误。
harmful_duplicate_runs = 0。
hidden_runs = 0。
failed_tool_results 不来自产品写入主路径。
不能出现 hard_safety / tool_loop_stagnation / internal runtime answer 泄漏。
```

允许但需要记录：

```text
harmless duplicate；
recovery duplicate；
单个场景耗时偏高但业务完成；
final_answer_recovery 偏贵但最终答复可用；
provider 侧偶发慢响应。
```

阻断发布：

```text
P0 任一失败；
写错产品记录；
漏写必需产品记录；
副作用重复写入；
hidden/runtime-hidden 重新出现；
模型最终答复暴露 runtime 内部状态；
RAG 写入场景只召回不写入；
career 主链路缺少 ResumeProfile / JDAnalysis / JobFitReport / CareerApplication / ResumeVersion。
```

## 6. 成本基线

M42 最新参考基线：

```text
data/live_smoke_matrix_m42_upcoming_tools_full_c6_r1/report.json
passed=11/11
avg_elapsed=112.17s
max_elapsed=247.53s
avg_llm_calls=9.5
max_llm_calls=20
avg_tokens=46286
max_tokens=102145
harmful_duplicate_runs=0/11
hidden_runs=0/11
```

M43 不把“几秒钟、几千 token”的波动视为必须优化。

需要关注的是：

```text
avg_tokens 比 M42 基线增加超过 25%；
avg_elapsed 比 M42 基线增加超过 25%；
max_tokens 超过 150k；
max_elapsed 超过 360s；
final_answer_recovery 频繁成为主耗时；
agent_main token 占比异常升高。
```

## 7. 失败处理规则

本轮 live smoke 如果遇到失败：

```text
1. 不立刻改代码。
2. 先记录 report.json、session_id、data_dir、失败场景、失败 turn。
3. 区分业务失败、runtime 表达失败、provider 波动、测试断言过严。
4. 只有确认是结构性问题后，才进入 M44 或单独修复计划。
```

分析时优先看：

```text
tool_calls/tool_calls.jsonl
agents/agent_main/events.jsonl
record_counts
write_tool_counts
efficiency.hidden_tool_results
efficiency.failed_tool_results
efficiency.workflow_decisions
retrieval_quality
last_events
```

## 8. 不做事项

```text
不改 .env。
不新增 runtime guard。
不把 smoke 失败直接转成黑名单。
不因为 harmless duplicate 修改工具链。
不把所有 action 都改 deterministic executor。
不在 M43 中继续做 token 压缩。
```

## 9. M43 产出

```text
1. 两批 full matrix 报告路径。
2. 通过率和失败列表。
3. hidden / harmful duplicate / failed tool result 统计。
4. avg/max elapsed、avg/max tokens、avg/max LLM calls。
5. 是否达到产品停止线。
6. 如果未达到，给出 M44 候选方向，不直接修改代码。
```

## 10. 两批验收结果

第一批：

```text
report: data/live_smoke_matrix_m43_acceptance_c6_b1/report.json
runs=11
passed=9/11
failed=2/11
avg_elapsed=127.20s
max_elapsed=281.48s
avg_llm_calls=10.5
max_llm_calls=25
avg_tokens=50285
max_tokens=130177
hidden=0
harmful_duplicate=1
failed_tool_results=2
```

失败样本：

```text
main_resume_child
session_id=sess_live_main_resume_child_001_8129605b
data_dir=data/live_smoke_matrix_m43_acceptance_c6_b1/main_resume_child/run_001
问题：agent_main 先调用 career_profile_merge 失败，随后再次调用并成功。
失败原因：evidence_refs contains invalid reference format: session_conversation_20260327_152154_8c321266
影响：ResumeProfile 与诊断 artifact 均已生成；失败来自一次无效 CareerProfile merge 尝试，被 smoke 计为有害重复和失败工具结果。

rag_to_note
session_id=sess_live_career_001_c4f90b2d
data_dir=data/live_smoke_matrix_m43_acceptance_c6_b1/rag_to_note/run_001
问题：M12 动作中先调用 note_append 失败，随后 note_create 成功。
失败原因：note_append 的 body_markdown 为换行空内容，工具拒绝。
影响：Note 最终成功创建；失败来自同一动作内错误选择 append 以及空正文参数。
```

第二批：

```text
report: data/live_smoke_matrix_m43_acceptance_c6_b2/report.json
runs=11
passed=11/11
failed=0/11
avg_elapsed=146.58s
max_elapsed=313.65s
avg_llm_calls=9.6
max_llm_calls=21
avg_tokens=47106
max_tokens=110989
hidden=0
harmful_duplicate=0
failed_tool_results=0
```

两批合并观察：

```text
total_runs=22
passed=20/22
failed=2/22
hidden=0/22
harmful_duplicate_failed_runs=1/22
```

结论：

```text
1. hidden/runtime-hidden 没有复现，M42 的主要结构修复有效。
2. RAG 后写 Note / LearningTask / InterviewReview 的终止条件在第二批全部通过。
3. 第一批两个失败都属于“工具最终可恢复，但中间出现失败工具结果”。
4. 当前还不能把 M43 标记为严格产品冻结基线，因为第一批存在 P0 失败和 failed_tool_results。
5. 但两类失败没有在第二批复现，暂不应该立刻新增 runtime guard。
```

## 11. 根因候选

`main_resume_child`：

```text
现象：resume_agent 已完成 ResumeProfile 与诊断 artifact，main-agent 仍尝试 career_profile_merge。
直接失败原因：evidence_refs 包含 session_conversation_*，不符合当前产品引用格式校验。
根因候选：career_profile_merge 的证据来源边界仍允许模型把对话级引用混进产品 evidence_refs。
建议：先观察是否复现；若复现，再从“产品引用标准化/过滤”层处理，不在 main_resume_child 场景里加专用 guard。
```

`rag_to_note`：

```text
现象：retrieval 完成后，runtime 当前可用工具为 note_create / note_append，模型先尝试 note_append。
直接失败原因：note_append.body_markdown 只有换行。
根因候选：缺少已有 note_id 时，contract 暴露 note_append 会增加错误选择概率；note_append 的参数生成没有通过正文非空预检。
建议：若后续复现，应在 notes action contract 层区分 create vs append 的适用条件，而不是按场景黑名单处理。
```

## 12. M44 候选方向

M44 不建议继续做大范围 runtime 改造。只有当 M43 后续批次继续复现同类失败时，再做小而结构化的收口：

```text
1. product_ref / evidence_ref 标准化层：
   所有写产品记录的 evidence_refs 进入工具前统一过滤或规范化。
   目标是解决 session_conversation_* 这类非产品引用混入写记录的问题。

2. note action contract 细化：
   没有 existing note_id 时只暴露 note_create；
   有明确 existing note_id 时才暴露 note_append；
   note_append 进入工具前做正文非空校验。

3. smoke 分级：
   区分“最终业务失败”和“中间可恢复失败”。
   当前 M43 仍保留 failed_tool_results 为阻断项，但后续产品验收可以单独统计 recovery failure。
```
