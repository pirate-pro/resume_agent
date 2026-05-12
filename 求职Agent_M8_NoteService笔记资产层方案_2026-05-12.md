# 求职 Agent M8 NoteService 笔记资产层方案

日期：2026-05-12

## 1. M8 一句话目标

建立一个用户可见、可编辑、可复用的笔记资产层，让报告、诊断、面试复盘、聊天摘录和学习材料可以沉淀为产品记录。

M8 不做 memory 自动写入，不做 RAG，不做学习计划，不做外部资料库。先把 NoteService 的领域边界和最小闭环做稳。

```text
聊天 / 报告 / artifact / 求职项目
  -> NoteService
  -> 可编辑笔记
  -> 后续 RAG / 学习计划 / 面试复盘可复用
```

## 2. 为什么现在做 NoteService

M7 已经把一次求职任务组织成 `CareerApplication`，用户可以围绕一个目标岗位管理 JD、匹配报告、定制简历、投递状态和下一步行动。

但长期产品还缺一个“用户自己的知识沉淀层”：

- 用户面试后需要记录问题、回答、反馈和情绪。
- 用户看完报告后需要整理成自己的行动笔记。
- 用户学习 RAG、Agent、后端工程等能力时，需要记录资料和阶段性理解。
- 后续学习计划和 RAG 召回需要稳定的产品资产，而不是从聊天记录里临时翻。

所以 M8 的目标不是做一个复杂知识库，而是先建立 NoteService 的事实源。

## 3. 核心边界

### 3.1 Note 不是 memory

Note 是用户可见、可编辑、可归档的产品资产。

Memory 是运行时上下文材料，用于帮助 agent 理解长期偏好、稳定事实和交互经验。

M8 规则：

- NoteService 不主动调用 `memory_write`。
- Note 创建、编辑、追加、归档都不等于写 memory。
- 用户说“存到笔记 / 记到笔记 / 保存为笔记”时，默认进入 NoteService。
- 用户明确说“记住我长期偏好 / 以后都按这个目标”时，才按现有 memory 规则处理。
- 现有 flush / memory 管线仍可能基于聊天事件做运行时摘要，但这不是 NoteService 的职责，也不能把 Note 当成 memory 的事实源。

后续如果要从 note 生成 memory，必须新增受控策略，例如用户确认、摘要级别限制、来源追溯和冲突处理。M8 不做。

### 3.2 Note 不是 artifact

Artifact 是文件事实源，适合保存上传文件、粘贴文本、生成报告、定制简历等文件型资产。

Note 是可编辑知识资产，它的正文事实源在 NoteService。

M8 规则：

- 简历原文、JD 原文、诊断报告、匹配报告、定制简历仍以 `SessionArtifact` 为文件事实源。
- Note 可以引用 artifact，但不复制 artifact 作为自己的事实源。
- Note 正文保存在 NoteService，不再额外创建 `data/notes/*.md` 双事实源。
- 如果用户要下载或导出笔记，后续可以创建导出 artifact；导出 artifact 是快照，不反向覆盖 Note。

### 3.3 Note 不是 CareerApplication

`CareerApplication` 是单个目标岗位的求职项目。

Note 可以挂到求职项目上，例如：

- 某个岗位的面试复盘
- 某个岗位的投递前检查笔记
- 某份匹配报告的整理版
- 针对某个短板的学习记录

但 Note 不替代 CareerApplication 的状态、风险和下一步行动。求职项目仍由 CareerService 维护。

### 3.4 Note 暂不接 RAG

M8 只做可管理的产品记录，不做向量索引和自动召回。

后续 M11 再做：

```text
Note / CareerApplication / ExternalResource / LearningTask
  -> RAG index
  -> 上下文召回
  -> 可追溯引用
```

M8 的数据模型要为 RAG 留出 source、tag、summary、updated_at 等字段，但不实现检索索引。

## 4. M8 范围

### 4.1 做

- `app/notes/` 领域层。
- Note / NoteCollection / NoteSourceRef 模型。
- 文件型 JSON store。
- ID、status、source ref、时间戳校验。
- 原子写入。
- get / list / archive。
- create / update / append。
- 损坏 JSON 稳定失败。
- API 草案和工具契约设计。
- agent 契约：什么时候写 note，什么时候不写 memory。

### 4.2 不做

- RAG。
- memory 自动写入。
- 学习计划。
- 外部资料库。
- 富文本编辑器。
- 多人协作。
- note 版本历史。
- note 导出 artifact。
- 跨 store 强存在性校验。

## 5. 产品对象

### 5.1 Note

用户的一条可编辑笔记。

建议字段：

```text
note_id
status
source_session_id
source_artifact_id
evidence_refs
created_at
updated_at

collection_id
title
body_markdown
body_format
tags
source_refs
related_application_id
summary
```

字段说明：

- `note_id`：`note_` 前缀。
- `status`：`active | archived`。
- `source_session_id`：创建这条笔记的来源会话，`sess_` 前缀。
- `source_artifact_id`：如果笔记主要来自某个 artifact，指向该 artifact，`artifact_` 前缀。
- `evidence_refs`：轻量字符串引用，只做格式校验，不做跨 store 存在性校验。
- `collection_id`：所属笔记集合，可为空。
- `title`：用户可见标题。
- `body_markdown`：笔记正文，M8 使用 Markdown 字符串。
- `body_format`：第一版固定 `markdown`。
- `tags`：简单字符串标签，M8 不单独建 Tag 表。
- `source_refs`：结构化来源引用。
- `related_application_id`：可选，关联求职项目。
- `summary`：短摘要，用于列表展示和后续 RAG 摘要入口。

来源字段分工：

- `source_artifact_id` 是便捷主来源，主要用于列表和常见查询。
- `evidence_refs` 延续现有产品记录风格，只保留字符串前缀校验，避免 M8 引入跨 store 耦合。
- `source_refs` 是 NoteService 自己的结构化来源视图，用于 UI 展示和后续追溯。它不改变 CareerService 里 `evidence_refs` 的规则。

### 5.2 NoteCollection

笔记集合，用于组织笔记。

建议字段：

```text
collection_id
status
source_session_id
created_at
updated_at

name
description
kind
tags
```

建议 `kind`：

```text
general
career_project
interview
learning
resume
resource
```

M8 不强依赖 collection。没有 collection 的 note 也应该能存在。

### 5.3 NoteSourceRef

Note 的来源引用，用于 UI 展示和后续追溯。

建议字段：

```text
source_type
source_id
source_session_id
title
quote
```

建议 `source_type`：

```text
artifact
career_application
resume_profile
career_profile
jd_analysis
job_fit_report
resume_version
chat_message
manual
```

规则：

- `source_type=artifact` 时，`source_id` 必须是 `artifact_` 前缀。
- `source_type=career_application` 时，`source_id` 必须是 `application_` 前缀。
- `source_type=resume_profile` 时，`source_id` 必须是 `resume_profile_` 前缀。
- `source_type=career_profile` 时，`source_id` 必须是 `career_profile_` 前缀。
- `source_type=jd_analysis` 时，`source_id` 必须是 `jd_` 或 `jd_analysis_` 前缀，兼容当前已有记录。
- `source_type=job_fit_report` 时，`source_id` 必须是 `fit_` 前缀。
- `source_type=resume_version` 时，`source_id` 必须是 `resume_version_` 前缀。
- `source_type=manual` 时，`source_id` 可以为空。
- `source_session_id` 如果存在，必须是 `sess_` 前缀。
- M8 只校验格式，不校验引用对象是否真实存在。

### 5.4 NoteDigest

M8 不单独实现持久化 `NoteDigest`。

先在 Note 上保留 `summary` 字段即可。后续 RAG 或学习计划需要更复杂摘要时，再把 digest 拆出去。

## 6. 存储设计

建议目录：

```text
data/notes/
  collections/
    collection_xxx.json
  notes/
    note_xxx.json
```

不创建：

```text
data/notes/*.md
data/notes/exports/*.md
data/notes/index/
```

原因：

- 避免 JSON 与 Markdown 双事实源。
- 避免提前引入 RAG / index。
- 避免 note 编辑后 artifact 快照过期。

写入要求：

- JSON 原子写入。
- store 统一维护 `created_at / updated_at`。
- 时间使用上海时区。
- 损坏 JSON 读取时抛稳定 `StorageError`。
- 模型校验严格失败，不做宽松类型转换。

## 7. API 草案

M8 第一阶段可以先做 store，不急着接 API。API 草案如下：

```text
GET    /api/notes
POST   /api/notes
GET    /api/notes/{note_id}
PATCH  /api/notes/{note_id}
POST   /api/notes/{note_id}/append
POST   /api/notes/{note_id}/archive

GET    /api/note-collections
POST   /api/note-collections
GET    /api/note-collections/{collection_id}
PATCH  /api/note-collections/{collection_id}
POST   /api/note-collections/{collection_id}/archive
```

`POST /api/notes` 最小请求：

```json
{
  "title": "星河智能投递前检查复盘",
  "body_markdown": "## 结论\n暂不投递，先补向量检索项目。",
  "body_format": "markdown",
  "collection_id": "collection_interview",
  "tags": ["投递前检查", "RAG"],
  "related_application_id": "application_xxx",
  "source_refs": [
    {
      "source_type": "artifact",
      "source_id": "artifact_xxx",
      "source_session_id": "sess_xxx",
      "title": "投递前检查报告"
    }
  ],
  "evidence_refs": ["application_xxx", "artifact_xxx"]
}
```

## 8. 工具草案

M8 工具建议：

```text
note_create
note_get
note_list
note_update
note_append
note_archive
note_collection_create
note_collection_get
note_collection_list
note_collection_update
note_collection_archive
```

工具边界：

- 工具参数只接受受控 id，不接受任意路径。
- `note_create` 和 `note_append` 不调用 memory。
- `note_create` 可以引用 artifact 或 career 记录 id。
- `note_update` 只允许更新标题、正文、标签、summary、collection、source_refs、related_application_id。
- `note_archive` 只改 status，不删除文件。

权限建议：

```text
agent_main:
  note_create / note_get / note_list / note_update / note_append / note_archive

resume_agent:
  默认不开放 note 写入

job_agent:
  默认不开放 note 写入
```

后续如果需要专门的 `note_agent`，再独立拆。

## 9. Agent 契约

### 9.1 什么时候创建 Note

用户明确表达以下意图时，可以创建 Note：

```text
存到笔记
保存为笔记
整理成笔记
记录这次复盘
把这份报告整理一下以后看
把面试题记下来
```

### 9.2 什么时候不能创建 Note

以下情况不能自动创建 Note：

- 用户只是普通提问。
- 用户只是要求简历诊断、JD 分析或匹配报告。
- agent 认为内容“可能有用”，但用户没有表达保存意图。
- flush / compaction 过程中不创建 Note。

### 9.3 Note 与 memory 的分流

```text
用户说：记到笔记
  -> note_create / note_append

用户说：记住我以后都想投 AI 应用后端
  -> 按现有 memory 规则判断是否写 memory

用户说：这次面试复盘帮我保存
  -> note_create
  -> 不自动 memory_write

用户说：这次面试暴露了我 RAG chunk 策略很弱，以后提醒我
  -> note_create 可保存复盘
  -> 是否 memory_write 需要按现有长期偏好/稳定事实规则单独判断
```

M8 先不做最后一种的自动联动。

## 10. 与前端的关系

M8 后端第一阶段可以不做复杂前端。

前端后续建议：

- 右侧求职资产面板不直接塞入完整笔记系统。
- 可以新增“笔记”入口或独立侧栏。
- 在 artifact 预览、匹配报告、投递前检查报告里提供“保存为笔记”动作。
- 在求职项目工作台里展示关联笔记数量和最近笔记。
- 笔记编辑器第一版用 Markdown textarea，不做富文本。

## 11. 质量门禁

M8 store 测试至少覆盖：

- Note / NoteCollection 持久化。
- ID 前缀校验。
- status 校验。
- source_refs 格式校验。
- evidence_refs 格式校验。
- 原子写入。
- get / list / archive。
- update / append。
- 时间戳由 store 维护。
- 上海时区序列化。
- 损坏 JSON 稳定失败。
- schema 类型不匹配稳定失败。
- 不做跨 store 强存在性校验。

M8 工具测试至少覆盖：

- `note_create` 不接受任意 path。
- `note_create` 能关联 artifact 和 CareerApplication。
- `note_append` 只追加正文，不覆盖来源。
- `note_update` 拒绝未知字段。
- `note_archive` 不删除文件。
- note 工具不会调用 memory。

## 12. 开发顺序

第一批只做领域底座：

```text
1. app/notes/models.py
2. app/notes/store.py
3. tests/test_note_store.py
```

第二批做 API 和 presenter：

```text
4. app/schemas/notes.py
5. app/api/notes.py
6. tests/test_note_api.py
```

第三批做工具和 agent 契约：

```text
7. app/tools/builtin_tools/notes.py
8. app/api/dependencies/tools.py
9. app/agents/default/AGENT.md
10. tests/test_note_tools.py
```

第四批再做前端入口：

```text
11. flutter_app/lib/core/models/api_models.dart
12. flutter_app/lib/core/providers/note_provider.dart
13. flutter_app/lib/features/notes/...
```

## 13. M8 完成标准

M8 完成后，用户应该能完成这条路径：

```text
打开某个匹配报告或投递前检查报告
  -> 保存为笔记
  -> 笔记关联当前求职项目和报告 artifact
  -> 后续可以继续追加面试反馈
  -> 不自动写入 memory
```

后端完成标准：

- NoteService 有独立模型和 store。
- Note 可以关联 artifact 和 CareerApplication。
- Note 可以 create / append / update / archive。
- API 和工具只暴露受控 id。
- 测试覆盖损坏 JSON 和格式校验。

产品边界完成标准：

- NoteService 是用户知识资产事实源。
- MemoryService 仍是运行时上下文材料。
- SessionArtifact 仍是文件事实源。
- CareerService 仍是求职项目事实源。

## 14. 风险与控制

### 14.1 和 memory 混淆

风险：用户说“记一下”时，agent 不知道写 note 还是 memory。

控制：

- “保存为笔记 / 记到笔记”写 Note。
- “记住长期偏好 / 以后都这样”走 memory。
- 不确定时追问，不自动双写。

### 14.2 和 artifact 双事实源

风险：报告 artifact 保存一份，note 又复制一份，后续不知道谁是最新。

控制：

- 报告正文仍是 artifact。
- Note 是用户整理后的可编辑内容。
- Note 通过 source_refs 指向 artifact。
- 导出 artifact 只是快照。

### 14.3 范围膨胀到知识库

风险：一做 note 就想做 RAG、外部链接、面经库。

控制：

- M8 只做 NoteService。
- M9 再做资料与题库。
- M11 再做 RAG / MCP。

## 15. 当前实现状态

截至 2026-05-12，M8 后端主闭环已完成：

- 已完成 `app/notes/models.py`、`app/notes/store.py` 和 `tests/test_note_store.py`。
- 已完成 `app/schemas/notes.py`、`app/api/notes.py` 和 `tests/test_note_api.py`。
- 已完成 `app/tools/builtin_tools/notes.py`、工具注册、capability 配置和 `tests/test_note_tools.py`。
- 已更新 `app/agents/default/AGENT.md`，明确 NoteService 与 memory / artifact / CareerApplication 的边界。
- 已补 `tests/test_note_agent_flow.py`，验证明确“保存为笔记”会创建 Note，长期偏好仍写 memory，普通求职回答不会自动创建 Note。

已验证命令：

```text
uv run pytest tests/test_note_store.py tests/test_note_api.py tests/test_note_tools.py tests/test_note_agent_flow.py tests/test_career_tools.py tests/test_tool_registry.py tests/test_multi_agent_contracts.py
uv run mypy app tests
```

仍然不做：

- RAG / MCP。
- memory 自动写入。
- 外部资料库。
- 学习计划。
- 前端笔记面板。
- 富文本编辑器。

## 16. 建议下一步

M8 后端底座已经可用。下一步有两个方向：

1. 如果继续完善 M8，就做前端入口：报告预览里的“保存为笔记”、关联笔记列表、笔记详情编辑。
2. 如果继续主线能力，就进入 M9：外部面经、面试题、资料链接和公司岗位资料的产品资产层。

建议优先进入 M9 方案设计，因为笔记前端可以在 M9/M10 的资料和学习计划入口一起统一设计，避免先做一个孤立笔记面板。
