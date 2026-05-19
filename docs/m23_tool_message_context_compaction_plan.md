# M23 工具消息上下文压缩方案

## 1. 背景

`tool_search -> schema reveal` 已经跑通主链路，但 A/B live smoke 说明它只解决了工具 schema 过大的问题，没有解决同一 run 内工具消息反复回放的问题。

本轮 A/B 数据：

```text
full schema:
  LLM 调用数: 27
  provider_prompt_tokens: 370,997
  tools schema 估算: 128,029
  message_tool 估算: 31,239

search reveal:
  LLM 调用数: 42
  provider_prompt_tokens: 464,540
  tools schema 估算: 94,757
  message_tool 估算: 115,647
```

结论：

- `tool_search` 让 schema token 下降。
- 但工具发现和重复 list/get 增加了模型轮次。
- 每轮都会把之前的 assistant tool_calls 和 tool result 继续带入下一轮，导致 `messages / message_tool` 成为新的最大成本来源。

所以 M23 下一步不是继续扩大 `tool_search`，而是压缩同一 run 内已经被模型消费过的工具轨迹。

## 2. 目标

本阶段目标：

- 保留工具调用协议正确性。
- 完整事件日志不丢失，调试仍可看到完整工具输入输出。
- 当前最新一组工具结果仍以 tool message 形式提供给模型。
- 已经被模型消费过的旧工具结果，不再作为 tool message 反复回放。
- 把旧工具结果沉淀成短小、确定性的“工作状态摘要”。
- 降低 search reveal 模式下 `messages` 和 `message_tool` token。
- 不影响 ResumeProfile / JDAnalysis / JobFitReport / ResumeVersion / LearningTask 等产品记录创建质量。

一句话：

```text
完整工具结果进事件日志；模型上下文只保留最新工具交换 + 历史工具摘要。
```

## 3. 非目标

第一阶段不做：

- 不做 LangGraph 迁移。
- 不改工具事实源。
- 不把工具结果写入 memory。
- 不让模型总结工具结果。
- 不做跨 run 的长期工具轨迹压缩。
- 不改变前端事件流展示。
- 不改变 `tool_search` 的 schema reveal 机制。

## 4. 当前问题

当前 `AgentRuntime` 工具循环大致是：

```text
messages = context.messages

round 0:
  model(messages)
  assistant tool_calls -> append messages
  tool result -> append messages

round 1:
  model(messages + round0 assistant tool_calls + round0 tool results)
  assistant tool_calls -> append messages
  tool result -> append messages

round 2:
  model(messages + round0 exchange + round1 exchange)
```

问题在于：

- 工具结果即使已经被模型读过，仍在后续每轮重复发送。
- `compact_tool_result_for_model` 只能压缩单条结果，不能控制历史条数。
- `tool_search` 增加的轮次越多，旧 tool message 累积越快。

## 5. 设计原则

### 5.1 工具协议必须合法

OpenAI-compatible tool calling 要求：

```text
assistant(tool_calls)
tool(tool_call_id=...)
```

如果上下文里保留某个 `tool` message，就必须同时保留它前面的 assistant `tool_calls` message。

因此不能只删除 tool result，也不能只保留 tool result。

正确做法：

```text
保留最新未被下一轮模型消费的完整 exchange
旧 exchange 整组移出 messages，改写为摘要
```

### 5.2 事件日志是完整事实源

`tool_call` / `tool_result` event 仍完整记录：

```text
events.jsonl
  -> tool_call.arguments
  -> tool_result.content
```

压缩只影响下一轮传给模型的 `messages`，不影响审计、调试、前端执行过程。

### 5.3 摘要必须确定性生成

不调用模型总结工具结果。

摘要由 runtime 基于工具名、参数、compact result、成功状态生成，避免额外成本和不稳定。

## 6. 目标结构

新增运行时内部结构：

```text
ToolExchange
  assistant_message
  tool_messages
  observations
  consumed_by_model: bool

ToolObservation
  tool_name
  success
  tool_call_id
  arguments_preview
  ids
  status
  summary
  error
  artifact_refs
  record_refs
  revealed_tool_names

ToolWorkingState
  observations[]
  latest_record_refs
  latest_artifact_refs
  latest_errors[]
```

第一阶段可以不落复杂类名，但代码上需要有一个独立 helper，避免把压缩逻辑直接塞进 `AgentRuntime` 主循环。

建议文件：

```text
app/runtime/agent/tool_context_window.py
tests/test_tool_context_window.py
```

## 7. 模型消息窗口

每轮模型调用前，messages 由三部分组成：

```text
base_messages
  -> ContextAssembler 生成的历史 user/assistant 消息

tool_working_state_message
  -> 历史工具摘要，role=assistant，content 为短 JSON 或短 Markdown

pending_exchange_messages
  -> 最新一组 assistant tool_calls + tool results，保持协议完整
```

也就是：

```text
model_messages =
  context.messages
  + [工具执行摘要]
  + [上一轮 assistant tool_calls]
  + [上一轮 tool results]
```

当模型基于 `pending_exchange_messages` 继续调用工具或生成最终回答后，这组 exchange 就已经被消费，可以移入 `ToolWorkingState`。

## 8. 工具摘要格式

建议第一版使用短 JSON，方便测试和解析：

```json
{
  "runtime_tool_state": "compact",
  "tool_call_count": 8,
  "successful_tools": ["career_resume_profile_get", "career_jd_analysis_get"],
  "latest_refs": {
    "resume_profile_id": "resume_profile_zhangsan_001",
    "jd_analysis_id": "jd_xxx",
    "job_fit_report_id": "fit_xxx",
    "application_id": "application_xxx",
    "resume_version_id": "resume_version_xxx",
    "artifact_ids": ["artifact_xxx"]
  },
  "observations": [
    {
      "tool": "career_application_list",
      "success": true,
      "summary": "找到 1 个 active 求职项目",
      "ids": {
        "application_id": "application_xxx",
        "resume_profile_id": "resume_profile_xxx",
        "jd_analysis_id": "jd_xxx",
        "job_fit_report_id": "fit_xxx"
      }
    }
  ],
  "latest_errors": []
}
```

长度控制：

```text
observations 最多 12 条
每条 summary 最多 180 字符
latest_errors 最多 3 条
整体最多 2500 字符
```

超过上限时，保留：

- 最近错误。
- 最近创建/更新成功的产品记录。
- 最新 artifact id。
- 最新 revealed tool names。
- 最新 retrieval 命中摘要。

## 9. 压缩时机

同步和流式路径都按同一规则：

### 9.1 每轮模型调用前

```text
messages_for_model = context_messages + state_summary + pending_exchange
```

### 9.2 模型返回后

如果模型返回新的 tool calls：

```text
1. 说明 pending_exchange 已经被模型消费。
2. 把 pending_exchange 中的 observations 合并进 ToolWorkingState。
3. 执行新的 tool calls。
4. 新的 assistant tool_calls + tool results 成为 pending_exchange。
```

如果模型返回最终回答：

```text
1. 不需要再构造下一轮 messages。
2. 完整事件日志已经保存。
3. run 正常结束。
```

### 9.3 达到工具轮次上限

保持现有行为，但 `llm_usage` 应能看出：

- `tool_context_window_mode`
- `pending_tool_exchange_count`
- `compacted_tool_observation_count`
- `tool_state_message_tokens`

## 10. 与已有 compact result 的关系

已有：

```text
compact_tool_result_for_model(tool_name, content)
```

作用：把单条工具结果压短。

新增：

```text
ToolContextWindow
```

作用：控制工具消息历史窗口。

关系：

```text
真实工具结果
  -> event log 保存完整 content
  -> compact_tool_result_for_model 生成当前 tool message
  -> ToolContextWindow 下一轮后把旧 exchange 转成工作状态摘要
```

它们是上下游，不是重复能力。

## 11. 与 tool_search 的关系

`tool_search` 仍然负责：

- 工具目录搜索。
- runtime schema reveal。

`ToolContextWindow` 负责：

- 压缩同一 run 内的历史工具调用消息。
- 降低多轮工具调用造成的 message/token 膨胀。

边界：

```text
tool_search = 降低 tools schema
ToolContextWindow = 降低 messages / message_tool
```

## 12. 风险与处理

### 12.1 模型漏掉关键信息

风险：旧工具结果被摘要替代后，模型可能缺少细节。

处理：

- 产品记录工具摘要必须保留关键 id 和核心字段。
- retrieval 摘要必须保留 top hits、source refs、match reason。
- artifact 读取摘要必须保留 `artifact_id`、title、returned_chars、是否 truncated。
- 最新一组工具结果仍完整保留，不立即压缩。

### 12.2 工具协议错误

风险：删除部分 tool message 后，provider 报协议错误。

处理：

- 只按 exchange 整组保留或整组移除。
- 保留 tool message 时，必须保留对应 assistant tool_calls。
- 单测覆盖多 tool_calls 同轮情况。

### 12.3 质量下降

风险：定制简历、学习任务生成质量下降。

处理：

- live smoke 必须覆盖：
  - 简历诊断。
  - JD 匹配。
  - 定制简历。
  - RAG 召回转学习任务。
- 对比 `record_counts`、质量门禁、answer_preview。

## 13. 开发步骤

### 第一步：ToolContextWindow helper

新增：

```text
app/runtime/agent/tool_context_window.py
tests/test_tool_context_window.py
```

能力：

- append pending exchange。
- mark pending consumed。
- render messages。
- render deterministic state summary。
- 保证保留 exchange 时协议合法。

### 第二步：摘要提取器

从 compact result 中提取：

```text
ids
record refs
artifact refs
revealed_tool_names
summary
error
```

不做跨 store 存在性校验。

### 第三步：接入同步 AgentRuntime

替换当前直接 append `messages` 的方式：

```text
messages = tool_context_window.render_messages()
```

工具执行后：

```text
tool_context_window.set_pending_exchange(...)
```

### 第四步：接入流式 AgentRuntime

同步同样逻辑，避免 sync/stream 行为分叉。

### 第五步：观测字段

在 `llm_usage` 增加：

```text
tool_context_window_mode
pending_tool_exchange_count
compacted_tool_observation_count
tool_state_message_estimate_tokens
tool_pending_message_estimate_tokens
```

### 第六步：live smoke A/B

对比三组：

```text
full schema + no window
search reveal + no window
search reveal + ToolContextWindow
```

第一阶段如果不保留 feature flag，也至少保留配置：

```text
TOOL_CONTEXT_WINDOW_MODE=off|compact
```

默认建议：

```text
off
```

等 live smoke 连续稳定后再改为：

```text
compact
```

## 14. 验收标准

必须满足：

- `pytest` 全量通过。
- sync / stream 工具调用协议单测通过。
- 多 tool_calls 同轮工具结果不会触发协议错误。
- live smoke 主链路质量门禁通过。
- `message_tool` 估算显著下降。
- `provider_prompt_tokens` 相比当前 search reveal 下降。
- 完整工具结果仍可在事件日志中查看。

建议目标：

```text
search reveal + ToolContextWindow
  message_tool 估算下降 50%+
  provider_prompt_tokens 低于 full schema 基线
```

## 15. 暂定结论

当前 search reveal 的方向仍然成立，但它只处理 schema 成本。

真正要让总 token 降下来，必须把同一 run 内已经消费过的工具消息从 `messages` 中移除，改成短状态摘要。

下一步应先实现 `ToolContextWindow`，而不是继续扩大 `tool_search` 或恢复旧的意图裁剪。

## 16. 实施记录

已完成：

- 新增 `app/runtime/agent/tool_context_window.py`。
- 同步 `AgentRuntime.run` 和 `AgentRuntime.run_stream` 的工具消息窗口逻辑。
- 新增 `TOOL_CONTEXT_WINDOW_MODE=off|compact` 配置，默认仍为 `off`。
- `llm_usage` 增加工具窗口观测字段，并接入 debug API 与 `tools/report_context_token_breakdown.py`。
- 修复 `career_application_create` 对 `job_fit_report_xxx` 证据引用的归一规则，避免模型把字段名式 ID 放进 `evidence_refs` 时产生可恢复失败。

本地验证：

```text
uv run pytest -q
uv run mypy app/runtime/agent_runtime.py app/runtime/agent/tool_context_window.py app/debug/token_usage.py app/tools/builtin_tools/career.py
```

结果：

```text
pytest 全量通过
mypy 通过
```

live smoke 验证：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=search
TOOL_CONTEXT_WINDOW_MODE=compact
runs=1
concurrency=1
retrieval_action=review_to_learning_task
```

第一把发现 `career_application_create` 对 `job_fit_report_xxx` evidence ref 处理不一致，已修复。

第二把主链路产物齐全，质量门禁通过：

```text
career_applications: 1
career_profiles: 1
jd_analyses: 1
job_fit_reports: 1
learning_tasks: 1
notes: 1
resume_profiles: 1
resume_versions: 1
quality_gate: passed
```

第二把仍有一次可恢复工具失败：

```text
learning_task_create -> resource_refs contains invalid reference format: r_rag_framework_001
```

模型随后去掉非法 `resource_refs` 并成功创建学习任务。这个问题不属于工具消息窗口，需要在后续学习任务工具契约或资源引用策略里单独处理；不建议为了 smoke 直接放宽 `resource_refs` 校验。

Token 对比：

```text
search reveal 无 ToolContextWindow:
  provider_prompt_tokens: 464,540
  tools schema 估算: 94,757
  message_tool 估算: 115,647

search reveal + ToolContextWindow:
  provider_prompt_tokens: 378,550
  tools schema 估算: 96,320
  message_tool 估算: 28,033
  tool_state_message 估算: 8,929
```

结论：

- `message_tool` 下降约 75%。
- 总 prompt token 相比 search reveal 基线下降约 18.5%。
- 当前最大成本已经从历史 tool message 转移到 `workflow_rules` 和可见工具 schema。
- 下一步 token 优化应优先拆 `workflow_rules`，再继续收敛工具 schema reveal 的可见范围。

## 17. 补充处理记录

针对后续 live smoke 暴露出的可恢复失败，补充做了三类工具契约兜底：

- `delegate_agents`：`tasks` 缺失时按空任务 no-op 处理，避免模型误触发委派工具导致整轮失败；非空但格式错误仍然拒绝。
- `learning_task_create`：`resource_refs` 是可选引用，只保留真实受控前缀 `resource_`、`skill_req_`、`artifact_`、`experience_`、`company_`，丢弃模型自造的资源 id；`evidence_refs` 仍保持严格校验。
- `career_application_merge`：忽略 `company`、`position`、`location`、`job_url` 等只读展示字段，避免只读字段导致项目更新失败；真正未知字段仍拒绝。

同时加强了 live smoke 的 M17 提示：

- `retrieval_search` 只用于定位候选记录。
- 创建学习任务前必须调用 `retrieval_context_pack` 读取可追溯上下文。
- 没有召回到真实 `resource_` / `question_` / `skill_req_` id 时，不要自造资源引用。

补充 live smoke：

```text
data_dir: data/live_career_smoke_m23_tool_window_handled2/run_001
session_id: sess_live_career_001_a649e81a
result: passed
elapsed: 183.20s
quality_gate: passed
```

产物：

```text
career_applications: 1
career_profiles: 1
jd_analyses: 1
job_fit_reports: 1
learning_tasks: 1
notes: 1
resume_profiles: 1
resume_versions: 1
```

RAG 召回：

```text
retrieval_search: 1
retrieval_context_pack: 1
max_context_chars: 3101 / 15000
budget_violations: 0
source_types: career_application, career_profile, jd_analysis, job_fit_report, note, resume_profile, resume_version
```

Token：

```text
provider_prompt_tokens: 321,371
estimated_prompt_tokens: 310,615
system_prompt: 152,832
messages: 73,411
tools: 82,389
message_tool: 29,732
tool_state_message: 7,468
```

最终结论：

- 工具消息窗口压缩后，`message_tool` 已稳定从 11 万级降到 2 到 3 万级。
- 当前通过链路的最大成本仍是 `workflow_rules` 和工具 schema。
- 下一步优化重点不应继续压工具历史消息，而是拆分 `workflow_rules`，让规则按任务场景 sparse 召回。
