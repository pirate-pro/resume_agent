# 求职 Agent M11 RAG / MCP 召回边界方案

## 1. M11 一句话目标

建立 `RetrievalService`，让 Agent 能在用户不手动引用 ID 的情况下，自动从 Career、Note、Knowledge、Learning 和当前 SessionArtifact 中召回相关上下文。

M11 第一阶段不直接做向量库、不做 MCP server、不做自动爬虫、不自动写 memory、不复制资料正文。先把“哪些内容可以被召回、如何追溯、如何注入上下文、如何避免混成新事实源”定清楚。

```text
Career / Note / Knowledge / Learning / SessionArtifact
  -> RetrievalService
  -> ContextPack
  -> Agent 使用

后续可选：
RetrievalService
  -> Index / Embedding / RAG
  -> MCP 只读接口
```

## 2. 为什么现在做

M7 到 M10 已经把主要产品事实源拆出来：

- `CareerService`：求职项目、简历画像、JD 分析、匹配报告。
- `NoteService`：用户自己的笔记、复盘、学习理解。
- `KnowledgeService`：外部资料、面经、题库、公司画像、能力要求。
- `LearningService`：学习计划、任务、进度、短板。
- `SessionArtifact`：上传文件和生成文件事实源。

现在的问题不再是“有没有地方保存”，而是“Agent 如何在需要时自动找回来”。

用户不应该记住：

```text
note_xxx
resource_xxx
fit_xxx
learning_plan_xxx
artifact_xxx
```

用户只会说：

```text
根据我之前的星河智能岗位准备一下二面
我上次 RAG 没答好的地方帮我复习
结合我简历和最近学习进度，给我今天的任务
把之前保存的面经和我的匹配报告一起看
```

M11 的价值是把这些自然语言请求转成可追溯的上下文包。

## 3. 核心定位

### 3.1 RetrievalService 不是新的事实源

`RetrievalService` 只负责召回、排序、裁剪和组装上下文。

它不能替代：

- `CareerProductStore`
- `NoteStore`
- `KnowledgeStore`
- `LearningStore`
- `SessionArtifact`
- `MemoryStore`

如果后续做索引，索引也只是 projection / cache。源记录删除、归档或更新后，索引必须能重建，不能反向覆盖源记录。

### 3.2 RAG 不是第一阶段的全部

RAG 通常意味着：

```text
chunk
embedding
vector search
rerank
context injection
generation
```

但当前系统第一阶段更需要：

```text
受控来源
结构化过滤
关键词 / 标签 / 摘要匹配
可追溯引用
上下文预算
Agent 契约
```

所以 M11 第一批先做 Retrieval，不急着做 embedding。

### 3.3 MCP 是对外接口，不是内部事实源

MCP 后续可以把检索能力暴露出去，例如：

```text
career.search_context
career.get_record
knowledge.search
note.search
learning.search
```

但 MCP 只应该调用已有服务，不直接读写底层文件，也不创建第二套知识库。

M11 第一批不实现 MCP server，只保留接口边界。

### 3.4 RetrievalService 不是 MemoryService

memory 仍然是运行时上下文材料。

Retrieval 召回的是用户可见、可追溯的产品记录和 artifact。它不主动写 memory，也不把召回结果变成 memory。

后续如果确实需要把某些长期学习状态提炼成 memory，必须走单独策略：

- 用户确认或明确长期偏好。
- 摘要级别限制。
- 来源可追溯。
- 冲突处理。

M11 不做 memory 自动写入。

## 4. 可召回来源

### 4.1 CareerService

可召回：

- `CareerApplication`
- `ResumeProfile`
- `CareerProfile`
- `JDAnalysis`
- `JobFitReport`
- `ResumeVersion`

典型用途：

- 根据目标岗位召回求职项目。
- 根据公司、岗位、技能召回匹配报告。
- 根据简历画像和职业画像补上下文。
- 根据求职项目定位相关 artifact 和后续学习计划。

召回字段优先级：

```text
title / company / position / target_roles
summary / diagnosis / gaps / risks / next_actions
skills / keywords / interview_focus
evidence_refs / artifact refs
updated_at
```

### 4.2 NoteService

可召回：

- `Note`
- `NoteCollection`

典型用途：

- 召回用户自己的面试复盘。
- 召回学习笔记、答案草稿、阶段性理解。
- 召回与某个求职项目关联的笔记。

召回字段优先级：

```text
title
summary
tags
related_application_id
source_refs
body_markdown 的裁剪片段
updated_at
```

注意：

- Note 正文事实源仍在 NoteService。
- Retrieval 返回片段和引用，不复制 Note。
- 用户写新笔记仍走 NoteService，不走 Retrieval。

### 4.3 KnowledgeService

可召回：

- `ExternalResource`
- `ExperiencePost`
- `InterviewQuestion`
- `CompanyProfile`
- `SkillRequirement`

典型用途：

- 根据目标公司召回公司画像和面经。
- 根据岗位能力点召回资料和题目。
- 根据学习计划任务召回相关资料引用。

召回字段优先级：

```text
title / company / position / target_roles
skill_tags
summary / key_points
question_text / answer_outline
requirements / signals
raw_artifact_id
updated_at
```

注意：

- 外部资料长正文以 artifact 或 Knowledge 原记录为准。
- Retrieval 不复制外部资料正文。
- 用户自己的面经和复盘仍走 NoteService。

### 4.4 LearningService

可召回：

- `LearningPlan`
- `LearningTask`
- `ProgressCheckin`
- `WeaknessTracker`
- `ReviewSchedule`

典型用途：

- 回答“我今天该学什么”。
- 根据目标岗位召回未完成任务和短板。
- 根据用户最近进度调整学习计划。
- 面试前召回未解决的能力弱点。

召回字段优先级：

```text
title / description
target_application_id
goals / focus_skill_tags
task state / priority / due_date
weakness severity / state / skill_tags
progress_summary / checkin summary
updated_at
```

注意：

- LearningTask 只保存任务和短备注。
- 长篇学习理解、答案草稿、复盘正文仍走 NoteService。

### 4.5 SessionArtifact

可召回：

- 当前会话上传文件。
- 当前会话生成文件。
- 与产品记录引用的 artifact。

典型用途：

- 用户刚上传文件后，优先读取当前会话 artifact。
- 产品记录引用了报告 artifact，需要预览或补充上下文。
- 检索原始 JD、简历、生成报告或定制简历。

注意：

- artifact 是文件事实源。
- Retrieval 可以返回 artifact 元数据、短片段和 `artifact_id`。
- 不暴露内部路径。
- 跨会话 artifact 召回必须先有明确产品记录引用，不做全局乱搜。

## 5. 不进入 Retrieval 的内容

以下内容默认不进入 M11 第一批召回：

- `workspace`：agent 私有中间产物，不作为跨 agent 资料源。
- 原始 `events`：运行审计日志，不作为用户知识库。
- `AgentTask`：委派生命周期事实源，不作为求职知识。
- 未被产品记录引用的历史聊天正文。
- memory 原始记录。
- 已归档记录，除非查询显式要求 `include_archived=true`。

如果后续要检索聊天历史或事件日志，应该单独设计审计查询或会话检索，不混进产品 Retrieval。

## 6. 统一召回模型

### 6.1 RetrievalSourceRef

建议 M11 使用 typed ref，而不是只返回裸字符串：

```json
{
  "source_type": "note",
  "source_id": "note_rag_review_001",
  "source_session_id": "sess_xxx",
  "artifact_id": "artifact_xxx"
}
```

M11 可以先在内部使用 dataclass，不要求所有旧模型立刻迁移。

建议支持的 `source_type`：

```text
career_application
resume_profile
career_profile
jd_analysis
job_fit_report
resume_version
note
note_collection
external_resource
experience_post
interview_question
company_profile
skill_requirement
learning_plan
learning_task
progress_checkin
weakness_tracker
review_schedule
session_artifact
```

### 6.2 RetrievalHit

一次召回命中的最小结果：

```json
{
  "source": {
    "source_type": "job_fit_report",
    "source_id": "fit_stargazer_backend",
    "source_session_id": "sess_xxx",
    "artifact_id": "artifact_fit_report_xxx"
  },
  "title": "星河智能 AI Agent 后端工程师匹配报告",
  "summary": "整体匹配度 76，主要短板是 RAG 检索评估和多 Agent 架构表达。",
  "snippet": "RAG 检索评估证据不足，需要补 chunk 策略、召回评估和失败恢复。",
  "tags": ["RAG", "Agent Runtime", "后端"],
  "score": 0.82,
  "match_reason": "命中目标公司、岗位和 RAG 短板",
  "updated_at": "2026-05-12T10:00:00+08:00",
  "evidence_refs": ["application_stargazer_backend", "artifact_fit_report_xxx"]
}
```

要求：

- `source_type` 和 `source_id` 必须可追溯。
- `snippet` 是裁剪片段，不是新事实源。
- `score` 可以先用规则分，不要求语义分。
- `match_reason` 用于调试和前端解释。

### 6.3 ContextPack

Agent 真正消费的不是散乱 hit，而是预算后的上下文包：

```json
{
  "query": "准备星河智能二面",
  "hits": [],
  "grouped_context": {
    "career": [],
    "notes": [],
    "knowledge": [],
    "learning": [],
    "artifacts": []
  },
  "citations": [],
  "omitted": []
}
```

上下文包职责：

- 控制总字符数。
- 按来源分组，避免不同事实源混在一起。
- 保留引用，方便回答中说明依据。
- 记录被省略内容，方便调试。

## 7. 召回策略

### 7.1 M11-1 先做规则召回

M11-1 不上向量库，先做：

- 标题匹配。
- 标签匹配。
- 公司 / 岗位 / 技能字段匹配。
- `related_application_id` / `target_application_id` 关联匹配。
- `evidence_refs` 关联扩展。
- `updated_at` 新近性排序。
- 任务状态和短板严重度加权。

这样能低成本验证产品链路，也避免一开始把问题甩给 embedding。

### 7.2 M11-2 再做索引投影

当规则召回稳定后，再引入 `RetrievalIndexStore`：

```text
RetrievalIndexRecord
  -> source_type
  -> source_id
  -> source_updated_at
  -> title
  -> searchable_text
  -> tags
  -> refs
  -> chunk_id
```

索引是可重建 projection，不是事实源。

### 7.3 M11-3 再做 embedding / rerank

embedding 只用于排序和语义召回。

要求：

- 命中结果仍然返回 `source_type` 和 `source_id`。
- 不允许只返回一段无来源文本。
- 索引失效时能回退到规则召回。
- 不把 embedding 结果写 memory。

### 7.4 M11-4 再考虑 MCP

MCP 可以在 RetrievalService 稳定后提供只读能力：

```text
retrieval.search
retrieval.get_context_pack
career.get_record
note.get_record
knowledge.get_record
learning.get_record
artifact.get_metadata
```

第一版 MCP 不提供写入能力。

## 8. Agent 使用规则

### 8.1 什么时候调用 Retrieval

适合调用：

- 用户问“之前、上次、最近、我保存过的、我投过的、我的计划”。
- 用户要求基于历史资料做面试准备、学习安排、复盘总结。
- 用户没有给 ID，但提到公司、岗位、技能、项目或学习目标。
- 生成学习计划、面试准备、复习任务前需要找上下文。

不适合调用：

- 用户刚上传文件并明确要分析当前文件，优先读取当前 artifact。
- 用户只是闲聊或问通用问题。
- 用户明确要求写入 Note / Learning / Career，应该先用对应服务写入。
- 用户明确要求“记住长期偏好”，仍按 memory 规则判断。

### 8.2 谁可以调用

第一阶段建议：

- `agent_main` 可以调用 retrieval 工具。
- `resume_agent` / `job_agent` 默认不直接调用全局 retrieval。
- child-agent 如需资料，由 main-agent 委派时传入明确 artifact / product id，或者后续开放只读、受限范围的 retrieval。

原因：

- 避免 child-agent 擅自扩大检索范围。
- 保持主流程可审计。
- 避免多 agent 同时召回造成上下文重复和 token 膨胀。

### 8.3 回答要求

Agent 使用 Retrieval 后：

- 必须基于召回结果回答。
- 不确定时说明“没有找到明确记录”。
- 涉及用户历史资料时尽量带来源描述。
- 不把召回片段当作永久事实写入 memory。
- 不把 `source_id` 暴露成主要用户体验，但可以在调试区域保留。

## 9. 工具和 API 建议

### 9.1 工具

第一批建议只做两个只读工具：

```text
retrieval_search
retrieval_context_pack
```

`retrieval_search` 返回较轻的命中列表。

`retrieval_context_pack` 返回给 Agent 使用的预算后上下文包。

工具参数只允许：

```text
query
source_types
related_application_id
session_id 默认来自 RunContext，不让模型传
top_k
max_chars
include_archived
```

不允许：

- 文件路径。
- 任意 store 路径。
- raw SQL / glob。
- 让模型选择内部数据目录。

### 9.2 API

公共 API 可以后置。

如果前端需要预览召回依据，可提供：

```text
GET /api/retrieval/search
POST /api/retrieval/context-pack
```

但 M11 第一批可以先只做内部 service 和工具测试。

### 9.3 MCP

MCP 暂不实现。

后续实现时必须遵守：

- 只读优先。
- 走服务层，不直接读文件。
- 返回 typed refs。
- 不暴露路径。
- 不自动创建 Note / Learning / Memory。

## 10. 上下文预算

M11 必须做预算，否则 RAG 会把上下文塞爆。

建议默认：

```text
context_pack.max_chars = 12000
single_hit.max_snippet_chars = 1200
note_body.max_chars = 2000
artifact_snippet.max_chars = 2000
top_k = 8
per_source_type_limit = 3
```

优先级建议：

1. 当前 `CareerApplication` 和直接关联记录。
2. 当前会话 artifact。
3. 用户自己的 Note。
4. 当前目标相关 Learning 短板和未完成任务。
5. Knowledge 外部资料。
6. 较旧的通用记录。

## 11. 质量和安全边界

### 11.1 可追溯

每个命中必须能追溯到：

```text
source_type
source_id
source_session_id 可选
artifact_id 可选
updated_at
```

没有来源的文本不能进入上下文包。

### 11.2 不跨权限

当前系统暂未做多用户权限，但 M11 设计要预留：

```text
owner_id
workspace_id
visibility
```

第一阶段至少不要做跨会话 artifact 全局乱搜。

### 11.3 不复制事实源

Retrieval 命中和索引记录不能成为新的产品记录。

如果用户要保存总结：

- 保存为 Note。
- 生成文件则保存为 SessionArtifact。
- 求职状态写 Career。
- 学习状态写 Learning。

### 11.4 不自动写 memory

Retrieval 只读。

即使召回到“用户 RAG 很弱”这种内容，也不能自动写 memory。只有用户明确表达长期偏好、稳定目标或长期事实时，才按现有 memory 规则处理。

## 12. M11 开发顺序

### M11-1：RetrievalService 领域层

文件建议：

```text
app/retrieval/models.py
app/retrieval/adapters.py
app/retrieval/service.py
tests/test_retrieval_service.py
```

验收：

- 能从 Career、Note、Knowledge、Learning 和当前 SessionArtifact 构建 `RetrievalHit`。
- 能按 query、source_types、related_application_id、top_k、max_chars 过滤和裁剪。
- 能生成 `ContextPack`。
- 不写任何源 store。
- 不读 workspace。
- 不读取未引用的跨会话 artifact。
- 不写 memory。

### M11-2：只读工具和 agent 契约

文件建议：

```text
app/tools/builtin_tools/retrieval.py
app/config/agent_capabilities.json
app/agents/default/AGENT.md
tests/test_retrieval_tools.py
tests/test_retrieval_agent_flow.py
```

验收：

- `agent_main` 可以调用 `retrieval_search` 和 `retrieval_context_pack`。
- child-agent 默认不开放全局 retrieval。
- 工具参数不接受路径。
- 工具输出包含 typed refs 和 match_reason。
- 确定性 runtime 测试覆盖“用户不提供 ID，Agent 自动召回相关求职项目和笔记”。

### M11-3：主线链路验证

验收：

- 用户说“根据我之前星河智能岗位准备二面”，不用手动提供 ID。
- Agent 召回对应 `CareerApplication`、`JobFitReport`、相关 Note、LearningTask 和 Knowledge 资料。
- Agent 给出可追溯的准备建议。
- 不创建新记录，除非用户明确要求保存。
- 不写 memory。

### M11-4：索引 projection

前提：

- M11-1 到 M11-3 运行稳定。
- 规则召回的不足点明确。

验收：

- 能构建可重建 `RetrievalIndexRecord`。
- 源记录更新或归档后索引可刷新。
- 索引损坏可以删除重建。
- 不把索引当事实源。

### M11-5：Embedding / MCP

前提：

- 有足够真实数据证明规则召回不够。
- 上下文包、引用、权限和预算已经稳定。

验收：

- embedding 结果可追溯。
- MCP 只读。
- MCP 不绕过服务层。
- MCP 不暴露路径。

## 13. 第一阶段明确不做

```text
向量数据库
embedding
rerank 模型
MCP server
自动爬虫
外部链接抓取
聊天历史全局检索
events 检索
workspace 检索
memory 自动写入
跨用户权限系统
前端召回面板
```

## 14. 当前建议

下一步先做 M11-1：

```text
app/retrieval/models.py
app/retrieval/adapters.py
app/retrieval/service.py
tests/test_retrieval_service.py
```

只做规则召回和上下文包，不接工具、不改 prompt、不做 MCP、不做 embedding。

这一步做好后，再接 M11-2 只读工具和 agent 契约。
