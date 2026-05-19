# M23 工具搜索与 Schema 渐进式披露方案

## 1. 背景

当前 token 消耗里有两类明显大头：

- 工具执行结果在同一轮多次回放。
- 每次模型调用携带大量工具 schema。

第一类已经通过“模型可见工具结果压缩”处理：完整工具结果仍进事件日志，模型下一轮只看 compact view。

第二类不能简单做关键词裁剪。因为工具能力本身是产品能力的一部分，如果模型不知道有什么工具、工具能做什么，就会降低路径规划能力，甚至错过本该调用的产品工具。

因此这里采用更稳的设计：

```text
tool_search
  -> 返回可用工具目录候选
  -> runtime 在下一轮注入候选工具的完整 schema
  -> 模型再调用真实业务工具
```

这不是隐藏能力，而是把“全部 schema 一次性塞给模型”改成“先发现能力，再展开需要的 schema”。

## 2. 目标

M23 工具披露优化的目标：

- 降低普通对话和轻量任务的工具 schema token。
- 不牺牲模型对系统能力的发现能力。
- 不破坏现有 capability 权限边界。
- 不让模型调用没有 schema 的工具。
- 不影响事件日志、工具事实源和调试能力。
- 支持逐步灰度，必要时一键回退到 full schema 模式。

一句话：

```text
用 tool_search 做工具目录检索，用 runtime 做 schema reveal。
```

## 3. 非目标

第一阶段不做：

- 不做 LangGraph 迁移。
- 不做复杂语义向量检索工具目录。
- 不把工具参数校验下放给 LLM。
- 不让模型凭 name/description 直接调用真实工具。
- 不移除现有业务工具。
- 不改变 Career / Note / Learning / Retrieval 的事实源边界。
- 不做面向最终用户的工具目录 UI。

## 4. 关键判断

### 4.1 只给 name/description 不能让模型稳定调用工具

对 OpenAI-compatible tool calling 来说，模型要真正调用某个工具，当前请求里必须带该工具 schema。

只在 prompt 里告诉模型“有一个工具叫 career_profile_merge”是不够的：

- 模型不知道完整参数结构。
- 模型可能编错字段。
- provider 不一定允许它调用未声明工具。
- 运行时也不应该执行本轮未暴露的工具。

所以合理路径不是“先给 name/description，然后直接调用”，而是：

```text
第一轮：
  tools = [tool_search]

模型调用：
  tool_search(query="简历诊断和生成画像需要哪些工具")

runtime：
  根据 tool_search 结果，把相关工具 schema 加入 visible tools

第二轮：
  tools = [tool_search, session_read_artifact, career_resume_profile_create, ...]

模型调用真实工具。
```

### 4.2 搜索即披露，避免额外 reveal 工具

不单独设计 `tool_reveal`。

原因：

- `tool_search -> tool_reveal -> 真实工具` 会多一轮模型调用。
- 模型选择 reveal 名单也可能不稳定。
- runtime 更适合根据搜索结果、工具包和 capability 做确定性展开。

第一阶段采用：

```text
tool_search 返回候选工具
runtime 同步把候选工具加入本 run 的 revealed_tool_names
下一轮模型即可调用这些工具
```

## 5. 总体链路

### 5.1 full schema 模式

当前模式：

```text
ContextAssembler
  -> 按 capability / dynamic selection 得到所有可用工具
AgentRuntime
  -> 每轮模型调用都发送完整 tools_payload
```

### 5.2 search reveal 模式

目标模式：

```text
ContextAssembler
  -> 得到本 agent 可用工具全集

ToolCatalog
  -> 构建工具目录摘要
  -> 按 group / keyword / description 做确定性搜索

AgentRuntime
  -> 初始 visible tools = 常驻工具
  -> 模型调用 tool_search
  -> runtime 记录 revealed_tool_names
  -> 下一轮 visible tools = 常驻工具 + revealed 工具
  -> 模型调用真实工具
```

状态只在当前 run 内有效，不跨会话持久化。

## 6. 组件设计

### 6.1 ToolCatalog

建议新增：

```text
app/runtime/tool_catalog.py
```

职责：

- 从 `ToolDefinition` 构建工具目录。
- 给工具打能力分组。
- 支持按 query 搜索候选工具。
- 支持按工具包展开。
- 只返回当前 agent capability 允许的工具。

工具目录项：

```text
ToolCatalogEntry
  name
  description
  group
  keywords
  reveal_pack
  risk_level
```

第一阶段不需要持久化目录。可以由代码中的分组规则生成，后续再迁到配置。

### 6.2 工具分组

建议第一版分组：

```text
core
  tool_search

artifact
  session_list_artifacts
  session_read_artifact
  session_search_artifact
  session_create_text_artifact
  session_plan_artifact_access

retrieval
  retrieval_search
  retrieval_context_pack

career
  career_* 工具

note
  note_* 工具

learning
  learning_* 工具

memory
  memory_write
  memory_search
  memory_update
  memory_forget
  memory_inspect
  memory_explain

delegation
  delegate_agents
  agent_task_status

state
  state_* 工具
```

`state` 工具第一阶段不建议主动暴露给模型作为业务能力。它更像 runtime / 编排内部能力，后续应继续评估是否下沉。

### 6.3 ToolSearchTool

建议新增：

```text
app/tools/builtin_tools/tool_search.py
```

工具 schema：

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Describe the capability needed."
    },
    "groups": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Optional capability groups to search."
    },
    "top_k": {
      "type": "integer",
      "default": 8,
      "minimum": 1,
      "maximum": 20
    }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

返回内容：

```json
{
  "query": "...",
  "matched_groups": ["retrieval", "career"],
  "revealed_tools": [
    {
      "name": "retrieval_context_pack",
      "description": "...",
      "group": "retrieval",
      "why": "用户提到之前/保存过/目标岗位，需要召回产品记录"
    }
  ],
  "reveal_packs": ["retrieval", "career_read"],
  "next_step": "下一轮可以调用 revealed_tools 中的真实工具。"
}
```

注意：返回结果不包含完整 schema。

### 6.4 Runtime Reveal State

建议在 `AgentRuntime.run` 和 `run_stream` 内维护本地状态：

```text
ToolRevealState
  mode
  always_visible_tool_names
  revealed_tool_names
  available_definitions_by_name
  reveal_events
```

每轮模型调用前：

```text
visible_tool_definitions =
  always_visible_tool_names
  + revealed_tool_names
```

执行 `tool_search` 后：

```text
1. 解析 tool_search 结果。
2. 根据 result.revealed_tools / reveal_packs 展开真实工具名。
3. 与 capability 允许工具取交集。
4. 写入 revealed_tool_names。
5. 下一轮模型调用携带这些工具 schema。
```

### 6.5 常驻工具

第一阶段常驻工具要少，但不能太少。

建议：

```text
必须常驻：
  tool_search

可配置常驻：
  memory_write
```

`memory_write` 是否常驻需要单独决策：

- 常驻优点：用户明确说“记住”时模型不用先 search。
- 常驻缺点：普通对话也会带 memory schema。

建议第一阶段用配置控制：

```text
TOOL_SCHEMA_DISCLOSURE_MODE=full|search
TOOL_SCHEMA_ALWAYS_VISIBLE=tool_search,memory_write
```

默认开发阶段可以先：

```text
full
```

等测试通过后再切：

```text
search
```

## 7. 运行时约束

### 7.1 未 reveal 的工具不执行

search reveal 模式下，runtime 应拒绝执行当前轮未 visible 的工具。

原因：

- 防止模型凭历史记忆或幻觉调用隐藏工具。
- 防止绕过 schema 渐进式披露。
- 保证 token 优化和权限边界一致。

失败返回建议：

```json
{
  "recoverable": true,
  "error_type": "tool_schema_not_revealed",
  "tool_name": "...",
  "message": "该工具本轮尚未揭示。请先调用 tool_search 搜索相关能力。"
}
```

### 7.2 capability 仍是最高权限边界

`tool_search` 只能返回当前 agent capability 允许的工具。

即使目录命中某工具，如果 capability 不允许，也不能出现在结果中。

```text
allowed_by_capability ∩ matched_by_search = revealed_tools
```

### 7.3 本 run 内持续保留 revealed schema

一旦某个工具在本 run 被 reveal，后续工具轮继续保留，直到当前用户请求结束。

原因：

- 多步工作流会连续调用 retrieval、note、learning、career 工具。
- 如果每轮都需要重新 search，会增加延迟和不稳定性。

### 7.4 工具包展开要保守

`tool_search` 不应该只 reveal 一个孤立工具。

比如用户问“根据之前星河智能岗位准备二面”：

应该展开：

```text
retrieval_search
retrieval_context_pack
```

如果用户还说“保存为笔记”：

再展开：

```text
note_create
note_append
note_update
```

如果用户说“加入学习任务”：

再展开：

```text
learning_task_create
learning_task_update
learning_plan_get/list 类工具
```

这样能减少“只搜到一个工具但缺少配套工具”的断链。

## 8. 与旧动态工具选择的关系

旧版 `tool_selection` 曾经负责“先分析意图，再暴露某个类别的工具 schema”。

M23 收敛后不再保留这条工具筛选主链路，原因是它和 `tool_search -> schema reveal` 都在解决“该给模型哪些工具 schema”的问题。两套机制长期并存会制造僵尸代码和排障歧义。

最终边界调整为：

```text
workflow_rules
  -> 只决定当前 prompt 是否注入某类流程说明

capability
  -> 只作为 agent 可用工具权限上限

tool_search
  -> 模型主动发现能力

ToolRevealState
  -> runtime 决定下一轮真实 schema

full schema mode
  -> 只作为调试 / 回退路径，直接暴露 capability 允许的全部 schema
```

因此 `app/runtime/tool_selection.py` 和对应测试已移除。后续如果需要更强的工具发现能力，应增强 `ToolCatalog` / `tool_search`，不要恢复第二套意图裁剪系统。

## 9. 与 RAG 的关系

这里的 `tool_search` 是“工具目录检索”，不是产品知识 RAG。

它和产品 RAG 的关系：

```text
tool_search
  -> 搜工具能力

retrieval_context_pack
  -> 搜用户产品资产和知识资料
```

两者不能混成一个工具。

用户问“我之前星河智能岗位准备到哪了”：

```text
1. tool_search 搜到 retrieval_context_pack schema
2. 模型调用 retrieval_context_pack
3. RetrievalService / RAG 搜产品上下文
4. 模型回答
```

## 10. 失败处理

### 10.1 tool_search 没搜准

返回：

```text
matched_groups = []
revealed_tools = []
next_step = "没有找到明确工具；可以直接回答，或换一个更具体的能力描述重新搜索。"
```

runtime 不自动展开全部工具。

### 10.2 模型需要多个能力

模型可以一次搜索更宽的 query，也可以多次 tool_search。

runtime 将 reveal 结果合并：

```text
revealed_tool_names = union(previous, current)
```

### 10.3 关键主链路失败

如果 live smoke 发现求职主链路因为 schema reveal 断链，优先处理：

```text
1. 调整工具包展开规则。
2. 调整 tool_search 描述和返回 next_step。
3. 调整 workflow skill，让模型搜索最终动作而不是只搜索第一步。
4. 最后才考虑扩大常驻工具集。
```

不要直接回到全量工具长期运行，除非作为临时回退。

## 11. 观测指标

需要在 `llm_usage` 或 debug 统计中增加：

```text
tool_disclosure_mode
visible_tool_count
available_tool_count
revealed_tool_count
visible_tool_names
revealed_tool_names
tools_estimate_tokens
```

用于回答：

- search 模式每轮实际带了几个工具？
- schema token 降了多少？
- 哪些工具经常被 reveal 但不调用？
- 哪些工具从未 reveal？
- tool_search 本身增加了多少模型轮次？

## 12. 开发步骤

### 第一步：设计和测试骨架

```text
app/runtime/tool_catalog.py
tests/test_tool_catalog.py
```

只做确定性目录搜索，不接 runtime。

验收：

- 能按 query 命中 retrieval / career / note / learning / delegation。
- capability 不允许的工具不会返回。
- 同组工具按包展开。

### 第二步：ToolSearchTool

```text
app/tools/builtin_tools/tool_search.py
tests/test_tool_search_tool.py
```

验收：

- 返回候选工具摘要，不返回 schema。
- 返回 reveal_packs。
- 返回结果稳定、可 JSON 解析。

### 第三步：Runtime schema reveal

```text
app/runtime/agent/tool_reveal.py
app/runtime/agent_runtime.py
tests/test_agent_runtime_tool_reveal.py
```

验收：

- search 模式首轮只带常驻工具。
- tool_search 后下一轮带 revealed 工具 schema。
- 未 reveal 工具不会执行。
- full 模式行为保持不变。

### 第四步：主链路回归

重点测试：

```text
普通聊天
记住偏好
简历诊断
JD 分析
简历 + JD 匹配
历史岗位召回
保存笔记
创建学习任务
多 agent 委派
```

### 第五步：live smoke 与 token 对比

对比：

```text
full schema 模式
search reveal 模式
```

看：

- tools_estimate_tokens
- prompt_estimate_total_tokens
- tool_search 额外轮次
- 最终结果质量
- 工具调用成功率

## 13. 验收标准

第一阶段通过标准：

- full 模式全量测试不回退。
- search 模式关键主链路测试通过。
- 普通聊天 tools schema token 显著下降。
- 求职主流程没有明显质量下降。
- 所有真实工具调用前都已经 visible。
- capability 边界仍然有效。
- 事件日志能看出每轮 visible / revealed 工具情况。

## 14. 暂定结论

可以做 `tool_search`，但不能把它做成简单的“关键词裁剪工具”。

正确方向是：

```text
工具目录搜索
  -> runtime schema reveal
  -> 本 run 内持续保留
  -> capability 约束
  -> 可观测
  -> 可回退
```

这比直接动态裁剪更稳，也更符合后续 MCP / LangGraph / RAG 工具化扩展方向。

## 15. 实施记录

2026-05-18 已完成第一阶段实现：

- 新增 `ToolCatalog` 和 `tool_search`，工具搜索只返回目录摘要，不返回参数 schema。
- `agent_main` 支持 search reveal 模式：首轮只带常驻工具，`tool_search` 后下一轮注入匹配工具 schema。
- child-agent 不走 search reveal，避免简历/JD 子任务缺少业务工具。
- 未 reveal 的工具调用会被 runtime 拒绝，不会执行真实工具。
- `llm_usage` 已记录每轮 visible / revealed 工具数量和名称。
- 产品工具结果在模型可见消息里使用 compact view，完整结果仍进入事件日志。
- `CareerResumeVersion` 未显式传 `target_jd_analysis_id` 时，可从唯一 JD evidence ref 推断。

验收结果：

- `uv run pytest -q` 通过。
- search reveal live smoke 单并发通过，已完成简历诊断、JD 匹配、定制简历版本创建和求职项目合并。
- 本轮 smoke 仍出现一次可恢复的工具保护性拒绝：模型首次生成 ResumeVersion 时在 `change_summary` 中写入了禁用的“占位”相关表述，工具拒绝后重试成功。该问题不阻断主链路，但后续还需要继续降低错误重试成本。

2026-05-18 A/B live smoke 复测后补充结论：

- `tool_search` 确实降低了 tools schema token。
- 但 search reveal 增加了工具发现轮次，历史 tool message 在同一 run 内继续累积，总 prompt token 反而上升。
- 下一阶段不继续扩大 `tool_search`，转向工具消息上下文窗口压缩，详见 `docs/m23_tool_message_context_compaction_plan.md`。
