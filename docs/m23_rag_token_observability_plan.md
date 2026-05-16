# M23 RAG 质量层与 Token 管理观测方案

## 0. 设计前置说明

2026-05-16 调整：RAG 底座实现先暂停，进入架构设计评审。

当前以 `docs/m23_rag_mcp_architecture_design.md` 作为 RAG / MCP 检索架构讨论草案。该草案确认前，不继续开发 chunking、index store、indexer、search 或 RetrievalService 融合。

需要先明确：

- RAG Index 只是检索投影，不是新的事实源。
- Note / Knowledge / Memory / SessionArtifact 保持各自事实源边界。
- 笔记和中期记忆不是迁移到 RAG，而是由后台任务生成可重建索引。
- MCP 先作为边界预留，不先实现 server。

## 1. 一句话目标

M23 的目标是把当前候选版从“流程可用”推进到“资料召回质量可验证、Token 消耗可观测”。

```text
M23 = RAG 质量层第一阶段 + Token 管理观测增强
```

其中：

- RAG 是产品质量能力，目标是让外部面经、面试题、学习资料、长篇笔记能够被稳定召回并带引用进入回答。
- Token 看板是管理 / 调试能力，目标是让开发和后续运营能看清模型接口消耗，不进入用户产品主流程。

## 2. 当前基础

当前系统已经具备：

- `CareerService`：简历画像、职业画像、JD 分析、匹配报告、简历版本、求职项目。
- `NoteService`：用户可见、可编辑的笔记资产。
- `KnowledgeService`：外部资料、面经、面试题、公司画像、能力要求。
- `LearningService`：学习计划、学习任务、进度打卡、短板跟踪。
- `SessionArtifact`：上传文件和生成文件事实源。
- `RetrievalService`：跨 Career / Note / Knowledge / Learning / SessionArtifact 的规则召回和 `ContextPack`。
- `llm_usage` 事件：记录每次模型调用的 prompt / completion / total token，并在调试面板展示当前会话消耗。

M11 已经完成规则召回，M23 不推翻 M11，而是在它下面增加可重建的索引层。

```text
事实源：
Career / Note / Knowledge / Learning / SessionArtifact

现有召回：
RetrievalService 规则匹配

M23 新增：
RAGIndex projection
  -> Chunk
  -> Search
  -> RetrievalService 融合
  -> ContextPack
```

## 3. 非目标

M23 第一阶段不做：

- 不做自动爬虫。
- 不做 MCP server。
- 不做 memory 自动写入。
- 不把 Note 自动写成 memory。
- 不把索引当事实源。
- 不要求用户手动引用 chunk id。
- 不做复杂后台权限系统。
- 不做按 Token 自动裁剪上下文策略。
- 不做 LangGraph 编排迁移。

Token 当前只做观测，不做强制优化。等看清真实消耗后，再决定是否做上下文预算治理和工具暴露瘦身。

## 4. 边界原则

### 4.1 RAG 索引不是事实源

RAG 索引只是 projection / cache。

源记录来自：

- `Note`
- `ExternalResource`
- `InterviewQuestion`
- `CompanyProfile`
- `SkillRequirement`
- `SessionArtifact`

索引记录可以删除、重建、过期，但不能反向覆盖源记录。

### 4.2 用户自己的面经仍写 Note

用户自己记录的面试经历、复盘、想法、答案草稿，仍进入 `NoteService`。

外部面经、公开面试题、学习资料、资料链接，进入 `KnowledgeService`。

RAG 负责召回二者，不负责决定它们属于哪个事实源。

### 4.3 RetrievalService 仍是 Agent 入口

M23 第一阶段不建议直接给 Agent 暴露一组新的 RAG 工具。

更稳的方式是：

```text
Agent
  -> retrieval_search / retrieval_context_pack
  -> RetrievalService
  -> 规则召回 + RAG 索引召回
```

这样可以保持工具面稳定，减少 prompt 和工具 schema 膨胀。

### 4.4 Token 看板和产品功能隔离

Token 看板只读取事件：

```text
EventRecord(type="llm_usage")
```

它不读取或写入：

- Career 产品记录
- Note
- Knowledge
- Learning
- Memory
- SessionArtifact 正文

后续如果做管理端，也只作为管理 / 调试视图存在，不出现在普通用户产品路径里。

## 5. M23-1：Token 管理观测增强

### 5.1 目标

当前调试面板只能看当前会话的 Token 消耗。M23-1 要补上历史基线能力。

要能回答：

- 哪个会话最耗 Token？
- 哪个 Agent 最耗 Token？
- 哪个阶段最耗 Token？
- 多 Agent 任务平均消耗多少？
- provider 真实 usage 和 estimated 估算各占多少？

### 5.2 建议后端结构

```text
app/debug/token_usage.py
tests/test_token_usage_debug_service.py
```

核心模型：

```text
TokenUsageCall
  event_id
  session_id
  agent_id
  run_id
  parent_run_id
  created_at
  api
  operation
  mode
  phase
  round_index
  model
  prompt_tokens
  completion_tokens
  total_tokens
  estimated
  usage_source

TokenUsageSummary
  call_count
  session_count
  total_tokens
  prompt_tokens
  completion_tokens
  estimated_call_count
  provider_call_count
  by_agent
  by_phase
  by_model
```

### 5.3 建议 API

第一批只做只读 API：

```text
GET /api/debug/token-usage/summary
GET /api/debug/token-usage/calls
GET /api/debug/token-usage/sessions/{session_id}
```

查询参数：

```text
limit
session_id
agent_id
phase
estimated
```

第一阶段不做鉴权和复杂管理系统，但 API 路径必须放在 `debug` 命名空间，避免和产品 API 混在一起。

### 5.4 前端展示

调试面板新增一个可折叠区域：

```text
Token 基线
  总消耗
  最近会话
  Agent 分布
  阶段分布
  最近调用明细
```

现阶段不做精细图表，先做可读表格和小卡片。

### 5.5 验收标准

- 能聚合多个历史会话的 `llm_usage`。
- 能按 Agent / phase / model 分组。
- 不读取产品资产正文。
- 不改变现有用户产品页面。
- `.env` 不进入提交。

## 6. M23-2：RAG 领域设计与索引模型

### 6.1 目标

建立可重建的 RAG 索引模型，让长文本资料从“整条记录规则匹配”升级为“按 chunk 检索”。

### 6.2 建议目录

```text
app/retrieval/index_models.py
app/retrieval/chunking.py
app/retrieval/index_store.py
app/retrieval/indexer.py
tests/test_retrieval_index_store.py
tests/test_retrieval_chunking.py
```

继续放在 `app/retrieval/` 下，而不是新建第二套 `app/rag/`。原因是当前 Agent 入口已经是 RetrievalService，RAG 是 Retrieval 的增强层。

### 6.3 Chunk 模型

```text
RetrievalChunk
  chunk_id
  source_type
  source_id
  source_ref
  source_title
  source_updated_at
  content_hash
  chunk_index
  char_start
  char_end
  text
  token_estimate
  tags
  metadata
  status
  created_at
  updated_at
```

ID 规则：

```text
chunk_<source_type>_<source_id>_<short_hash>
```

示例：

```text
chunk_note_note_rag_review_001_a13f9c
chunk_resource_resource_stargazer_interview_9b2a41
chunk_question_question_rag_chunk_strategy_d812ab
```

### 6.4 分块策略

第一阶段使用确定性分块，不依赖模型。

建议规则：

- Markdown 优先按标题分块。
- 过长标题段落继续按段落切分。
- 代码块、表格尽量不切碎。
- 每块目标大小约 `500-900` token。
- 相邻块保留少量 overlap，默认 `80-120` token。
- 每个 chunk 保留 `source_ref` 和 `char_start / char_end`。

不要一开始就做过多特殊策略。先保证可重建、可测试、可解释。

### 6.5 索引存储

第一阶段可以使用 JSONL / JSON 文件索引，和当前本地 store 风格一致。

建议落点：

```text
data/retrieval_index/chunks.jsonl
data/retrieval_index/manifest.json
```

要求：

- 原子写入。
- 损坏 JSON 稳定失败。
- 可按 source 重建。
- 源记录归档后 chunk 不进入 active search。
- 不做跨 store 强存在性校验，只在 indexer 读取源记录时自然发现。

## 7. M23-3：检索与融合

### 7.1 第一阶段检索方式

第一阶段先做本地 sparse / lexical 检索，不强依赖 embedding。

原因：

- 能快速建立可评估闭环。
- 不引入额外模型成本和网络不稳定性。
- 对面试题、技术词、公司名、岗位名这类查询，关键词检索已经有明显收益。

但模型要预留 embedding 字段和接口边界，后续可以升级为 hybrid search。

### 7.2 检索评分

建议评分因素：

```text
query term 命中
标题命中
标签命中
source_type 权重
related_application_id 命中
最近更新时间
chunk 长度惩罚
```

输出必须包含：

```text
chunk_id
source_type
source_id
title
snippet
score
match_reason
citations
```

### 7.3 融合到 RetrievalService

RetrievalService 现有输出是 `RetrievalHit` 和 `ContextPack`。

M23 建议新增 source type：

```text
rag_chunk
```

或者保留原始 source type，并在 payload 中增加：

```text
chunk_id
chunk_index
source_ref
```

推荐第二种：让用户和 Agent 感知的是“来自笔记 / 资料 / 面试题”，而不是“来自 chunk”。

示例：

```text
source_type: external_resource
source_id: resource_stargazer_interview
source_ref: {"type": "external_resource", "id": "resource_stargazer_interview"}
chunk_id: chunk_resource_resource_stargazer_interview_9b2a41
match_reason: 命中 RAG chunk 策略、召回评估和失败恢复
```

## 8. M23-4：Agent 使用方式

第一阶段不新增 Agent 写入权限。

`agent_main` 使用现有：

```text
retrieval_search
retrieval_context_pack
```

工具描述中补充：

- 当用户询问学习资料、面经、面试题、长篇笔记时，优先用 RetrievalService 召回。
- 回答时自然说明来源，例如“来自你的 RAG 复盘笔记”和“来自星河智能二面资料”。
- 不把 chunk id 直接作为用户体验重点。
- 不把召回结果写 memory。
- 不把外部资料复制成 Note。

`resume_agent` 和 `job_agent` 仍不直接开放全局 RetrievalService，除非后续证明有必要。

## 9. M23-5：RAG 质量评估

RAG 不应该只靠肉眼感觉，需要最小评估集。

### 9.1 评估集

先做 10 条以内固定查询：

```text
1. RAG chunk 策略怎么回答
2. 星河智能二面会问哪些 Agent Runtime 问题
3. Kafka / RabbitMQ 消息队列经验怎么补
4. FastAPI 项目经验怎么表达
5. 多 Agent 编排和工具调用如何讲清楚
6. 面试官问召回评估指标怎么回答
7. 最近学习任务里和 RAG 相关的内容
8. 我之前复盘里提到的失败恢复怎么准备
```

每条查询定义：

```text
query
expected_source_ids
expected_keywords
forbidden_source_types
min_recall_at_k
```

### 9.2 指标

第一阶段指标：

```text
recall@5
expected_source_hit
citation_valid
snippet_contains_keyword
no_archived_source
max_context_chars_respected
```

暂不做复杂语义评分。

### 9.3 测试文件

```text
tests/test_retrieval_rag_index.py
tests/test_retrieval_rag_quality_eval.py
```

必要时补一个脚本：

```text
tools/evaluate_retrieval_rag.py
```

输出 JSON 报告，后续可以和 Token 消耗一起看。

## 10. M23-6：低批次真实链路验证

真实模型验证只跑低批次。

建议新增 smoke action：

```text
--retrieval-action rag_interview_prep
```

验证路径：

```text
种入 Knowledge 外部资料 / 面试题
种入用户 Note
构建 RAG index
用户询问：结合我之前资料，帮我准备 RAG 检索评估和 chunk 策略面试回答
Agent 调用 retrieval
回答带来源说明
不写 memory
不创建 Note
不创建 LearningTask
不更新 CareerApplication
```

质量门禁：

- 先召回。
- 命中预期资料或笔记。
- 回答包含关键点。
- citations 可追溯。
- 不越界写入。
- 记录 token 消耗。

## 11. 开发顺序

推荐顺序：

```text
1. M23-1 Token 管理观测增强
2. M23-2 RetrievalChunk / IndexStore / chunking
3. M23-3 Indexer：从 Note / Knowledge / SessionArtifact 构建 chunk
4. M23-4 Search：本地 sparse 检索和 RetrievalService 融合
5. M23-5 质量评估测试和评估脚本
6. M23-6 Agent 契约微调和低批次真实链路验证
```

第一批建议先做：

```text
app/debug/token_usage.py
tests/test_token_usage_debug_service.py
app/retrieval/index_models.py
app/retrieval/chunking.py
tests/test_retrieval_chunking.py
```

原因：

- Token 看板增强是独立的，风险低。
- chunking 是 RAG 的底座，必须先稳定。
- 先不碰 Agent prompt，避免没有评估集就改变模型行为。

## 12. 验收标准

M23 完成时应该满足：

- 可以查看历史 Token 消耗聚合。
- Token 看板不影响产品主流程。
- Note / Knowledge / SessionArtifact 能构建 chunk。
- chunk 索引可重建，不是事实源。
- RetrievalService 能融合 chunk 检索结果。
- 固定 RAG 评估集通过。
- 低批次真实链路能用资料和笔记回答面试准备问题。
- 不写 memory。
- 不提前引入 MCP。
- 不暴露内部文件路径。

## 13. 风险与处理

### 13.1 RAG 变成第二套知识库

风险：chunk 索引保存太多业务字段，最后和 Knowledge / Note 事实源冲突。

处理：

- chunk 只保存检索需要的文本、来源、位置和摘要性 metadata。
- 源记录更新后重建 chunk。
- 对用户展示和编辑仍回到源记录。

### 13.2 召回太多导致上下文变大

风险：RAG 提升召回后，ContextPack 变长，回答质量未必提升。

处理：

- `max_chars` 必须生效。
- 每个 source 默认最多取少量 chunk。
- 评估集中检查 `max_context_chars_respected`。

M23 暂不做自动 Token 优化，但不能让 RAG 无限制扩张。

### 13.3 用户笔记和外部资料混淆

风险：用户自己的面经被当外部资料，外部资料被当用户经历。

处理：

- 用户输入的个人复盘仍进入 Note。
- 外部资料进入 Knowledge。
- RAG 搜索结果必须保留 source_type。

### 13.4 过早上 embedding 导致调试困难

风险：embedding 接入后召回不稳定，问题难定位。

处理：

- 第一阶段先用 deterministic sparse 检索。
- 先有固定评估集。
- embedding 作为后续 hybrid search 增强，不作为 M23-2 的前置条件。

## 14. 结论

M23 应该优先做 RAG，但要从“可评估的最小闭环”开始。

Token 看板增强用于观测成本，不在 M23 里做强制优化。

推荐第一步先实现：

```text
M23-1 Token 管理观测增强
M23-2 chunking / index model 底座
```

这两步完成后，再接 RetrievalService 融合和 RAG 质量评估。
