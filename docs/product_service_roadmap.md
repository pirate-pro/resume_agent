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

短期可以从用户粘贴或上传内容开始，后期再接：

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

### M9：资料与题库层

目标：把外部面经、面试题、资料链接沉淀为可复用知识资产。

建议模型：

```text
ExternalResource
InterviewQuestion
ExperiencePost
CompanyProfile
SkillRequirement
```

验收标准：

- 用户可以保存资料链接或粘贴面经。
- 系统能提取公司、岗位、能力点、题目和建议准备方向。
- 资料可以关联到求职项目和学习计划。

### M10：学习计划与监督

目标：让产品从“一次性求职助手”变成“长期成长助手”。

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

M7 主线闭环已经完成低批次验证。下一步进入 M8，但仍然不提前接 memory 和 RAG。

M8 最小下一步：

```text
1. 先落 NoteService 领域方案，明确 note 不是 memory。
2. 只做 note 产品记录模型、store 和 API 草案，不接 RAG。
3. 再评估 note 与求职项目、artifact、面试复盘的关联方式。
```

这样可以先把“目标岗位项目”跑成主线，再自然引出笔记、资料和学习计划。
