# M40：Live Quality Gate 方案

> 状态：已落地第一版质量门禁和 P0 stop-line。M39 已把 P0 结构门禁跑通，但 `career_full` 曾出现最终答复把 AI 应用开发 JD 漂移成 C++ 游戏服务端的风险。M40 不继续压 token，也不继续为偶发工具路径加 guard；先把用户可见质量和产品记录忠实度纳入 live smoke。

2026-05-26 验证结果：

```text
data/live_smoke_matrix_m40_p0_compact_repair_view_r1/report.json

P0 passed=7/7
harmful_duplicate_runs=0/7
hidden_runs=0/7
failed_tool_result_runs=0/7
live_quality error_codes=[]

career_full:
  elapsed=239.98s
  tokens=109994
  llm_calls=19
  duplicate_tool_call_count=1
  harmful_duplicate_tool_call_count=0
```

本轮修复的根因：

```text
1. career_profile_merge 已能在工具层把 source drift 修成 ResumeProfile/源 artifact 支持的事实；
2. 但 compact tool result 曾隐藏“实际提交后的 CareerProfile record / source_alignment_repairs”，
   导致模型最终答复复述自己传入的错误 C++ 参数；
3. 已改为把修复后的 committed record 和 source_alignment_guidance 放回模型可见结果；
4. repair metadata 不再使用 resume_profile_*/career_profile_* 这类伪 id 前缀，避免污染后续任务上下文。
```

剩余问题不再作为 M40 stop-line：

```text
career_full 仍有非有害重复和偏高成本；
下一阶段应进入成本/确定性流程优化，而不是继续给 M40 增加 case guard。
```

## 1. 为什么要先做质量门禁

M39-B 的结构结果已经可用：

```text
P0 passed=7/7
harmful_duplicate_runs=0/7
hidden_runs=0/7
```

但结构通过不等于产品可交付。当前缺口是：

```text
工具顺序正确；
产品记录也能保存；
最终答复或生成 artifact 仍可能偏离源 JD / 源简历 / 已保存产品记录。
```

所以 M40 的目标不是让模型少说几句话，而是先回答：

```text
这次 live smoke 生成的答案和资产，是否忠于源材料？
```

## 2. 边界

M40 只做检测和门禁，不先改生成链路：

```text
做：
  - final answer / agent summary / generated artifact 的源事实一致性检查；
  - JDAnalysis / JobFitReport / ResumeVersion 的明显漂移检查；
  - 把质量错误写入 smoke report 的 quality_error_codes；
  - 保持 agent-agnostic，未来新增 agent 不需要改门禁。

不做：
  - 不新增 agent_id 分支；
  - 不把所有输出改成 deterministic final answer；
  - 不为了压缩 token 删除必要事实；
  - 不把语义判断完全交给另一个 LLM。
```

## 3. 输入和输出

质量门禁只读取这些持久化事实：

```text
SessionArtifact:
  原始 resume / JD artifact
  generated_file artifact

Career product records:
  ResumeProfile
  CareerProfile
  JDAnalysis
  JobFitReport
  ResumeVersion
  CareerApplication

Event logs:
  assistant_message
  agent_result_summary
```

输出：

```text
LiveQualityFinding:
  severity
  code
  message
  reference

LiveQualityReport:
  success
  findings
```

这些 finding 会进入：

```text
FlowReport.quality_findings
FlowReport.quality_error_codes
FlowReport.errors
ScenarioReport.quality_error_codes
ScenarioReport.errors
```

## 4. 第一版检测规则

第一版只抓高置信问题，避免误伤。

### 4.1 源 JD / 最终答复漂移

典型失败：

```text
源 JD: AI 应用开发工程师，Python / FastAPI / RAG / Agent / 向量检索
最终答复: C++ 游戏服务端开发工程师，Linux / MySQL / 网络编程
```

门禁逻辑：

```text
如果源材料没有出现 C++ / 游戏服务端等强特征，
但 assistant_message、agent_result_summary 或 generated artifact 出现这些强特征，
判为 source drift。
```

### 4.2 JDAnalysis 产品记录漂移

`JDAnalysis.required_skills / keywords / responsibilities / position` 中如果出现源 JD 不支持的强特征，判为错误。

### 4.3 JobFitReport / ResumeVersion 漂移

`JobFitReport` 和 `ResumeVersion` 可以引用 JD 中的差距，例如“需要补齐向量检索经验”。这不是错误。

错误是：

```text
把源材料里不存在的岗位方向、技术栈或项目领域写成事实。
```

### 4.4 只做强特征

第一版不做宽泛事实抽取，只抓高置信漂移：

```text
C++ / CPP / C＋＋
游戏服务端 / 游戏服务器 / 游戏后端 / 游戏开发
```

后续如需扩展，按“强特征 + 源事实缺失 + 用户可见输出”增加，而不是在 runtime 中补 prompt。

## 5. Agent-agnostic 原则

不能写：

```text
if agent_id == "job_agent": ...
if agent_id == "resume_agent": ...
```

门禁按事件和记录类型工作：

```text
所有 agents/*/events.jsonl
所有 assistant_message
所有 agent_result_summary
当前 session 的产品记录
当前 session 的 artifacts
```

因此未来加入 `research_agent`、`interview_agent` 或其他 agent，质量门禁仍会读取它们的输出。

## 6. 与 M39 的关系

M39 证明结构路径：

```text
任务有没有完成；
工具有没有越权；
是否出现有害重复；
是否触发 hard safety / stagnation。
```

M40 补充产品质量：

```text
最终答复是否忠于源材料；
生成 artifact 是否忠于源材料；
产品记录是否出现明显语义漂移。
```

只有 M39 + M40 都稳定后，才继续做 M39-C executor skeleton。否则 executor 只会让错误更稳定地发生。

## 7. 验收

单元测试：

```text
源 JD 是 AI/Python/FastAPI/RAG，最终答复说 C++ 游戏服务端 => fail
源 JD 和最终答复都围绕 Python/FastAPI/RAG => pass
JobFitReport 把向量检索作为 JD 差距/准备项 => pass
main_job_child / career_full 的 smoke report 会携带 live_quality error code
```

Live smoke：

```text
先跑 P0 单组。
若结构通过但质量门禁失败，停止继续优化性能，先修生成源事实链路。
若结构和质量都通过，再进入 executor dry-run。
```

## 8. 停止线

M40 不追求把所有语义问题一次性解决。第一阶段停止线：

```text
P0 live smoke:
  structural passed=100%
  live_quality error_codes=[]

Career 6x3:
  harmful_duplicate_runs=0/6
  hard_safety_runs=0/6
  live_quality error runs=0/6
```

如果只剩几秒耗时或几千 token 差异，不继续加复杂分支。

2026-05-26 补充：停止线已经进入 `tools/smoke_live_matrix.py`，不只停留在文档。

硬失败：

```text
harmful_duplicate_tool_call_count > 0
hidden_tool_result_count > 0
failed_tool_result_count > 0
hard_model_round_limit_reached
tool_loop_stagnation
premature_final_answer_stagnation
retrieval budget_violations > 0
live_quality error_codes 非空
各 scenario 自身的越权工具/缺失产物
```

只警告，不失败：

```text
P0 场景超过建议耗时；
P0 场景超过建议 LLM calls；
P0 场景超过建议 tokens。
```

原因：

```text
结构正确性、越权、副作用、重复调用和事实漂移会直接影响产品可信度，必须 fail；
几秒耗时或几千 token 波动只影响成本体验，先作为 warning，避免继续为小幅性能波动打补丁。
```
