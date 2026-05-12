# 产品服务化路线规划

## 目标

当前系统已经具备聊天入口、multi-agent 执行、artifact 文件事实源、memory 上下文材料和 career 产品资产。下一阶段的目标不是继续堆单点工具，而是把系统推进成一个可长期使用的求职成长产品。

产品核心定位：

```text
围绕目标岗位 / 目标公司，持续管理用户能力差距、求职资产、学习计划和面试准备。
```

聊天界面继续作为统一入口，但聊天不应该成为唯一事实源。用户在聊天中上传资料、表达目标、触发任务；系统把有长期复用价值的结果沉淀到产品服务层。

## 总体架构

```text
Chat Runtime
  -> 统一入口、意图理解、资料上传、任务触发、过程展示
  -> Agent / Workflow 编排
  -> Product Services

Product Services
  -> CareerService
  -> NoteService
  -> LearningService
  -> KnowledgeService
  -> MemoryService

基础事实源
  -> SessionArtifact：文件事实源
  -> AgentTask：委派任务生命周期事实源
  -> events：运行审计事实源
  -> memory：运行时上下文材料
```

第一阶段不需要把这些服务拆成独立进程，但代码和数据边界要先拆清楚。后续如果需要 MCP、RAG 或独立服务，可以从清晰的领域边界自然演进。

## 服务职责

### CareerService

负责求职产品资产：

- 简历画像
- 职业画像
- JD 分析
- 岗位匹配报告
- 定制简历版本
- 求职项目

`CareerApplication` 是单个目标岗位的项目入口，用来串联 JD、匹配报告、定制简历、投递状态、下一步行动和风险。

### NoteService

负责用户可见、可编辑、可检索的知识资产。

笔记不是 memory，也不是 artifact。它可以来自：

- 用户手写
- 简历诊断整理
- 匹配报告整理
- 面试复盘
- 学习资料摘要
- 外部链接摘要

短期不把笔记写入 memory，避免和 daily、flush、long-term memory 混淆。后期可以通过 RAG 或受控摘要进入上下文，不要求用户手动引用。

### LearningService

负责长期学习计划和执行监督。

它要解决的问题不是“给一份建议”，而是持续回答：

- 用户距离目标岗位还差什么
- 本周应该补什么
- 今天应该做什么
- 学习进度是否偏离
- 计划是否需要调整

面向学生用户时，这一层尤其关键，因为学生往往需要从能力建设开始，而不只是修改简历。

### KnowledgeService

负责外部资料、面经、面试题、课程链接和公司岗位信息。

短期先完成结构化存储和 API，不通过聊天 Agent 写入。后期再接：

- 外部链接解析
- 面经 / 题库结构化
- 公司要求画像
- RAG 索引
- MCP 化知识检索能力

### MemoryService

继续只承担运行时上下文职责。

memory 可以保存长期偏好、稳定事实、目标方向等上下文材料，但不直接承担产品资产职责。笔记、学习计划、求职项目都应该先作为产品记录存在。

后期可以有受控通道：

```text
Note / Learning / Career
  -> RAG 检索
  -> 上下文包
  -> Agent 使用

必要时：
  -> 摘要型 memory
```

但不能让 note 自动混入 memory，也不能让 memory 变成用户看得见的笔记库。

## 关键边界

```text
SessionArtifact = 文件事实源
CareerService = 求职产品资产事实源
NoteService = 用户知识资产事实源
LearningService = 学习计划和进度事实源
KnowledgeService = 外部资料和题库事实源
MemoryService = 运行时上下文材料
events = 审计事实源
AgentTask = 委派执行事实源
```

边界原则：

- 用户可见 Markdown 文件仍然以 artifact 为准。
- 产品服务保存结构化字段和 artifact 引用。
- memory 不替代产品记录。
- note 不直接等于 memory。
- RAG 后期负责长文本召回，不要求用户手动复制 ID。
- 工具和 API 不暴露任意文件路径，只暴露受控 id。

## 开发路线

### M7：求职项目闭环

目标：让一次求职任务从“聊天结果”变成“目标岗位项目”。

已完成：

- CareerApplication 模型和 store
- career application 工具
- agent 契约
- 质量检查
- 前端求职项目可见层
- 求职项目详情和状态更新
- 项目关联资产的更清晰展示
- 项目级快捷动作入口：生成定制简历、投递前检查、面试准备
- 项目级动作 agent 契约
- 低批次 live smoke 验证项目动作链路和质量门禁

不做：

- 笔记系统
- RAG
- 学习计划
- 外部资料库

### M8：笔记资产层

目标：建立 NoteService，但暂不接 memory。

方案文档：`求职Agent_M8_NoteService笔记资产层方案_2026-05-12.md`

建议模型：

```text
Note
NoteCollection
NoteSourceRef
NoteTag
NoteDigest
```

验收标准：

- 用户可以把报告、诊断、面试复盘整理成笔记。
- 笔记可以关联求职项目、artifact、JD、能力点。
- 笔记可读、可编辑、可归档。
- 不自动写入 memory。

已完成：

- Note / NoteCollection / NoteSourceRef 模型和 JSON store。
- Note API、presenter、依赖注入和主应用路由。
- Note 工具、capability 配置和 main-agent 契约。
- 确定性 runtime 闭环测试：保存为笔记写 Note，长期偏好写 memory，普通求职回答不自动写 Note。

暂不做：

- RAG / MCP。
- memory 自动写入。
- 外部资料库。
- 学习计划。
- 前端笔记面板。

### M9：资料与题库层

目标：把外部面经、面试题、资料链接沉淀为可复用知识资产。聊天 Agent 暂不写入 KnowledgeService，用户自己的面试经历和复盘仍进入 NoteService。

方案文档：`求职Agent_M9_资料题库层方案_2026-05-12.md`

建议模型：

```text
ExternalResource
InterviewQuestion
ExperiencePost
CompanyProfile
SkillRequirement
```

长期验收标准：

- 外部资料可以通过导入、清洗、后台管理或后续 RAG/MCP 管线进入 KnowledgeService。
- 系统能提取公司、岗位、能力点、题目和建议准备方向。
- 资料可以关联到求职项目和学习计划。
- 用户个人面经、复盘、被问到的问题和回答感受走 NoteService，不混入公共资料库。

第一批开发范围：

```text
app/knowledge/models.py
app/knowledge/store.py
tests/test_knowledge_store.py
```

状态：已完成。

第一批已完成领域模型、严格校验、JSON store、原子写入、读取、列表、归档、更新和损坏 JSON 稳定失败。

暂不做：

- API。
- 工具。
- prompt。
- 聊天 Agent 写入工具。
- 前端。
- RAG / MCP。
- 自动爬虫。
- 学习计划。
- 跨 store 强存在性校验。

第二批状态：已完成。

第二批已完成：

```text
app/schemas/knowledge.py
app/api/knowledge.py
tests/test_knowledge_api.py
```

资料、面经、题目、公司画像和能力要求均已接入 API。公共 `/api/knowledge` 只读，后台 `/api/knowledge-admin` 承担导入、更新和归档。API 不暴露内部路径，不做跨 store 强存在性校验。

M9-3 状态：暂停。

暂停聊天 Agent 写入 Knowledge 工具。后续如果需要 Agent 使用资料库，优先做只读检索工具，例如：

```text
knowledge_search
knowledge_resource_get
knowledge_question_get
knowledge_company_get
knowledge_skill_requirement_get
```

### M10：学习计划与监督

目标：让产品从“一次性求职助手”变成“长期成长助手”。

方案文档：`求职Agent_M10_LearningService学习计划层方案_2026-05-12.md`

建议模型：

```text
LearningPlan
LearningTask
ProgressCheckin
WeaknessTracker
ReviewSchedule
```

验收标准：

- 能基于目标岗位和当前差距生成计划。
- 能跟踪完成情况。
- 能根据进度和新资料调整计划。
- 能持续提醒用户下一步该做什么。

第一批开发范围：

```text
app/learning/models.py
app/learning/store.py
tests/test_learning_store.py
```

状态：已完成。

第一批已完成领域模型、严格校验、JSON store、原子写入、读取、列表、归档、更新、任务状态更新、checkin 追加、Asia/Shanghai 时间戳和损坏 JSON 稳定失败。

第二批状态：已完成。

第二批已完成：

```text
app/schemas/learning.py
app/api/learning.py
tests/test_learning_api.py
```

学习计划、学习任务、进度打卡、短板跟踪和复习安排均已接入 API。公共 `/api/learning` 只读，后台 `/api/learning-admin` 承担创建、更新、归档和任务状态流转。API 不暴露内部路径，不做跨 store 强存在性校验。

暂不做：

- API。
- 工具。
- prompt。
- 前端。
- RAG / MCP。
- memory 自动写入。
- 日历同步。
- 通知提醒。
- 排期算法。
- 跨 store 强存在性校验。

### M11：RAG / MCP 化

目标：让 note、资料、面经、学习记录和求职项目被自动召回。

原则：

- 先有稳定领域模型，再做 RAG。
- RAG 是召回能力，不是产品资产事实源。
- MCP 可以作为后期 KnowledgeService / RAGService 的对外接口。

验收标准：

- 用户不需要手动引用笔记或资料 ID。
- 系统能根据当前问题自动召回相关笔记、资料、项目和计划。
- 召回结果可追溯到产品记录或 artifact。

## 当前优先级

M7 主线闭环和 M8 NoteService 后端主闭环已经完成低成本验证。M9-1 资料与题库后端底座和 M9-2 API 已经完成，M9-3 聊天 Agent 写入工具暂停。M10-1 LearningService 后端底座和 M10-2 API 已经完成，下一步仍然不提前接 memory 自动写入、RAG、MCP、日历同步和提醒系统。

推荐下一步：

```text
1. 开始 M10-3：app/tools/builtin_tools/learning.py。
2. 配置 main agent 的 Learning 写工具能力。
3. 调整 AGENT.md，明确学习计划、打卡和任务状态的写入边界。
4. 补 learning 工具测试和低成本 agent flow 测试。
```

这样可以先把“目标岗位项目”和“用户笔记资产”作为稳定事实源，再自然引出资料库、学习计划和后续 RAG。
