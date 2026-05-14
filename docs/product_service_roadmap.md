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

笔记类型先收敛为三类，避免分类过细导致用户理解成本过高：

```text
note      -> 记录：自由想法、总结、过程记录、杂项
learning  -> 学习：知识点、学习计划、短板复盘
resource  -> 资料：面经、文章、链接、资产摘录
```

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
- 笔记可标记为记录、学习或资料，用于后续上下文选择。
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

M10-3 状态：已完成。

M10-3 已完成：

```text
app/tools/builtin_tools/learning.py
app/config/agent_capabilities.json
app/agents/default/AGENT.md
tests/test_learning_tools.py
tests/test_learning_agent_flow.py
```

main-agent 可以创建学习计划、学习任务、进度打卡和短板跟踪，并能更新任务状态和短板状态。`resume_agent` 和 `job_agent` 默认没有 Learning 写权限。Learning 工具不写 memory，不替代 NoteService，也不复制 KnowledgeService 的资料正文。

M10-4 状态：已完成。

M10-4 已完成：

```text
tests/test_learning_career_chain.py
```

已用确定性 runtime 验证从 `CareerApplication + JobFitReport` 到 `LearningPlan + LearningTask + ProgressCheckin + WeaknessTracker` 的低成本真实链路。该验证创建 1 个学习计划、4 个学习任务，模拟完成 1 个 RAG 任务后的打卡和任务状态更新，并把对应短板从 `open` 更新为 `improving`。验证过程不跑真实模型 smoke，不写 memory，不生成 Markdown 快照。

暂不做：

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

方案文档：`求职Agent_M11_RAG_MCP召回边界方案_2026-05-12.md`

原则：

- 先有稳定领域模型，再做 RAG。
- RAG 是召回能力，不是产品资产事实源。
- MCP 可以作为后期 KnowledgeService / RAGService 的对外接口。
- 第一阶段先做 `RetrievalService`，不直接上向量库和 MCP server。

验收标准：

- 用户不需要手动引用笔记或资料 ID。
- 系统能根据当前问题自动召回相关笔记、资料、项目和计划。
- 召回结果可追溯到产品记录或 artifact。

M11-0 状态：已完成。

M11-0 已完成：

```text
求职Agent_M11_RAG_MCP召回边界方案_2026-05-12.md
```

已明确 `RetrievalService`、RAG、MCP、Memory 和各产品事实源的边界。M11 第一阶段只做规则召回、上下文包和可追溯引用，不做 embedding、向量库、MCP server、自动爬虫、前端召回面板和 memory 自动写入。

M11-1 状态：已完成。

M11-1 已完成：

```text
app/retrieval/models.py
app/retrieval/adapters.py
app/retrieval/service.py
tests/test_retrieval_service.py
```

已实现只读 `RetrievalService` 领域层。它可以从 Career、Note、Knowledge、Learning 和当前 SessionArtifact 规则召回 `RetrievalHit`，按 `query / source_types / related_application_id / top_k / max_chars` 过滤、排序和裁剪，并生成按来源分组的 `ContextPack`。测试覆盖跨产品召回、source type 过滤、求职项目过滤、归档记录控制、上下文预算裁剪和不读取跨会话 artifact。

M11-2 状态：已完成。

M11-2 已完成：

```text
app/tools/builtin_tools/retrieval.py
app/config/agent_capabilities.json
app/agents/default/AGENT.md
tests/test_retrieval_tools.py
tests/test_retrieval_agent_flow.py
```

已接入只读 `retrieval_search` 和 `retrieval_context_pack` 工具。工具参数只接受 `query / source_types / related_application_id / top_k / max_chars / include_archived`，`session_id` 由 `RunContext` 提供，不接受路径、store-owned 字段或任意内部目录。工具输出保留 typed refs、`match_reason`、分组 `ContextPack` 和 citations，不暴露内部路径。能力配置只给 `agent_main` 开放 retrieval 工具，`resume_agent` 和 `job_agent` 默认不开放全局召回。确定性 runtime 测试已覆盖用户不提供 ID 时由 main-agent 自动召回求职项目、匹配报告、笔记和学习任务，且不写 memory。

M11-3 状态：已完成。

M11-3 已完成：

```text
tests/test_retrieval_mainline_flow.py
```

已用低成本确定性 runtime 验证主线链路：用户说“根据我之前星河智能岗位准备二面，不用我提供任何 ID，也先别新建记录”时，main-agent 先用 `retrieval_search` 找到相关 `CareerApplication`，再用 `retrieval_context_pack` 按 `related_application_id` 召回 `CareerApplication`、`JobFitReport`、Note、LearningTask、WeaknessTracker、ExternalResource 和 InterviewQuestion，并给出可追溯的二面准备建议。验证同时确认不创建新的 career/note/knowledge/learning/session artifact 记录，不写 memory。

M11 收口评估状态：已完成。

M11 收口评估已完成：

```text
tests/test_retrieval_quality_eval.py
```

已用规则召回覆盖 5 类核心用户入口：二面准备、学习安排、复盘短板、简历与岗位匹配、当前会话文件。评估断言召回结果包含预期来源类型、citations 可追溯、`match_reason` 不为空。当前结论是：规则召回已经足够支撑 M11 第一阶段产品链路验证，暂不进入 M11-4 索引 projection，也不提前引入 embedding / MCP。

### M12：召回驱动求职行动闭环

目标：把 M11 的召回能力用于真实求职动作，让用户不用手动提供 id，也能推进面试准备、学习安排、笔记沉淀和投递前检查。

方案文档：`求职Agent_M12_召回驱动求职行动闭环方案_2026-05-12.md`

第一批状态：已完成。

第一批已完成：

```text
app/agents/default/AGENT.md
tests/test_retrieval_action_flow.py
求职Agent_M12_召回驱动求职行动闭环方案_2026-05-12.md
```

已补充 main-agent 召回后动作契约，并用确定性 runtime 覆盖 4 条真实动作链路：

- 面试准备：先召回，再只回答，不写入。
- 学习安排：先召回，在用户明确要求加入计划时创建 LearningTask，不写 memory。
- 保存笔记：先召回，再写 Note，不写 memory。
- 投递前检查：先召回，再更新 CareerApplication，不重新分析简历或 JD。

暂不做：

- 新服务。
- 索引 projection。
- embedding。
- MCP。
- 前端大改。
- memory 自动写入。

M12 收口 smoke 支持状态：已完成。

已完成：

```text
tools/smoke_career_live_flow.py
tests/test_career_live_smoke_report.py
```

`tools/smoke_career_live_flow.py` 已支持 `--retrieval-action`，可以在原有低批次 live smoke 后追加一轮 M12 召回驱动动作验证。可选动作包括 `interview_prep / learning_task / save_note / pre_apply_check`。报告会检查 M12 动作是否先调用 `retrieval_search` 和 `retrieval_context_pack`，是否误写 memory，以及不同动作是否调用了对应写入工具。

M12 低批次真实 smoke 验收：

```text
2026-05-13：interview_prep 已通过。
2026-05-13：learning_task 已通过。
2026-05-13：save_note 已通过。
2026-05-13：pre_apply_check 已通过。
```

本次真实链路暴露并修复了两个基础兼容问题：

- 当前 Mimo 网关在 thinking 模式下要求工具续轮回传 `reasoning_content`，已在 OpenAI-compatible client 和 runtime 工具消息中保留并回填该字段。
- Retrieval 工具的 `source_types` 已支持 `career / notes / knowledge / learning / artifacts` 组别别名，避免 Agent 必须硬记每个资料子类型。
- 学习安排动作已收紧为只写 LearningPlan / LearningTask；除非用户明确要求同步求职项目，否则不调用 `career_application_merge`，也不把 `learning_plan_` 或 `learning_task_` 作为 CareerApplication 的证据。
- 保存笔记动作已验收为只写 Note；不会写 memory，也不会顺手创建 LearningTask 或更新 CareerApplication。
- 投递前检查已验收为复用召回上下文后更新 CareerApplication；不会重新委派 child-agent，也不会重新保存 ResumeProfile、JDAnalysis 或 JobFitReport。

### M13：求职工作台主流程固化

目标：把 M12 已验证通过的 Agent 能力，固化成用户可稳定使用的求职工作台主流程。

方案文档：`求职Agent_M13_求职工作台主流程固化方案_2026-05-13.md`

第一批已完成：

```text
app/career/workbench.py
app/schemas/career_workbench.py
app/api/career_workbench.py
tests/test_career_workbench_service.py
tests/test_career_workbench_api.py
```

第一批已经实现只读聚合层，不写 store、不调用模型、不改 memory。前端现在可以通过工作台接口拿到 `CareerApplication` 关联的简历画像、职业画像、JD 分析、匹配报告、简历版本、笔记、学习计划、学习任务、短板、复盘安排、准备度、时间线和建议动作。

已验证：

- `uv run pytest tests/test_career_workbench_service.py tests/test_career_workbench_api.py`
- `uv run pytest tests/test_career_api.py tests/test_note_api.py tests/test_learning_api.py tests/test_career_workbench_service.py tests/test_career_workbench_api.py`
- `uv run mypy`

### M14：求职工作台一级页面

目标：把右侧「求职资产」栏从完整管理区降级为轻量入口，新增独立的求职工作台一级页面，承载求职项目、笔记、学习任务、简历资料、JD 与匹配报告。

方案文档：`docs/m14_career_workbench_page.md`

M14 的关键判断：

- 聊天界面继续作为任务入口、流式进度和追问入口。
- 右侧资产栏只保留最近资产、快速预览和打开工作台。
- 求职工作台负责长期管理、检索、预览和推进。
- 工作台不创建新的事实源，继续复用 `CareerProductStore`、`NoteStore`、`LearningStore`、`SessionArtifact`。
- M14 不做 Note 自动进入 memory，不做 RAG / MCP，不做日历提醒。

已完成：

```text
1. 新增 CareerWorkbenchProvider。
2. 新增 CareerWorkbenchPage / Shell / Nav / TopBar。
3. HomeScreen 增加聊天 / 工作台主视图切换。
4. 抽出 M13 项目详情可复用组件。
5. 实现求职项目列表和项目详情侧栏。
6. 右侧资产栏增加“打开工作台”入口。
7. 笔记页支持记录 / 学习 / 资料三类筛选、自由新建、编辑、Markdown 预览和实时渲染。
8. 资料与报告库支持简历资料、JD 分析和匹配报告浏览，并可预览对应 artifact。
9. 学习计划页支持项目切换、计划 / 任务 / 短板 / 复盘分区、任务状态分组和详情弹层。
10. M14 收口完成工作台动作刷新闭环：打开工作台会刷新聚合数据，工作台动作回聊天执行后会刷新工作台和右侧资产栏。
```

### M15：工作台动作闭环

目标：把“工作台发起动作 -> 聊天执行 -> 产物回到工作台”的体验做完整，让用户知道动作是否触发、是否完成、结果在哪里查看。

方案文档：`docs/m15_workbench_action_loop.md`

M15 的关键判断：

- 工作台仍然不绕过聊天执行任务。
- 动作状态第一阶段只做前端临时状态，不新增后端事实源。
- 动作完成后刷新工作台和右侧资产栏。
- 通过动作前后快照生成结果定位提示。
- 后续如果需要持久状态，再基于 run_id 或 AgentTask 扩展。

当前状态：第一批已完成，后续细节优化暂缓，回到产品主线。

### M16：求职项目推进与面试复盘闭环

目标：把投递、面试、反馈和复盘沉淀到现有产品资产里，让求职项目不只停留在“匹配报告”，而是能持续推进。

方案文档：`docs/m16_application_review_loop.md`

M16 的关键判断：

- 第一批不新增 `InterviewRecordStore`。
- 面试复盘和面试题先写入 Note，并关联 `CareerApplication`。
- 求职项目推进状态继续写入 `CareerApplication.stage/summary/risks/next_actions/notes`。
- 只有用户明确要求加入计划或监督补短板时，才创建 LearningTask / WeaknessTracker。
- 不自动写 memory，不重新解析简历，不重新分析 JD。

当前状态：

- M16 第一批已完成 Agent 契约和确定性 runtime 测试。
- M16 第二批已在工作台项目详情增加「求职进展」展示，复用现有 `CareerApplication`、Note 和 timeline 数据，不新增事实源。
- M16 第三批已增加低成本 live smoke 动作 `--retrieval-action interview_review`，用于验证“面试复盘写 Note + 更新 CareerApplication”的真实链路边界。

M16 低成本真实 smoke 命令：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 8 \
  --retrieval-action interview_review \
  --data-dir data/live_career_smoke_m16
```

这条 smoke 只追加一轮面试复盘动作，报告会检查是否先召回、是否写入 Note、是否更新 CareerApplication，以及是否误写 memory、误建学习任务、误重新委派或重新解析核心画像。

### M17：复盘驱动准备建议

目标：把 M16 沉淀下来的面试复盘用于下一步准备建议，但不自动创建学习任务。

方案文档：`docs/m17_review_driven_learning_advice.md`

M17 的关键判断：

- 建议不是任务，用户只问下一步准备时默认只回答。
- 只有用户明确要求“加入学习任务 / 创建任务 / 监督我完成”时，才调用 LearningService。
- 转成 LearningTask 时，证据要包含复盘 Note、CareerApplication、JobFitReport 和实际使用的学习计划、短板、资料或题目。
- 转任务不顺手更新 CareerApplication，除非用户同时明确要求更新项目状态。
- 不新增事实源，不自动写 memory。

当前状态：

- M17 第一批已完成 Agent 契约和确定性 runtime 测试。
- M17 第二批已接入低成本真实 smoke 动作，用于验证“复盘建议默认只回答”和“确认后转 LearningTask”的真实模型边界。

M17 低成本真实 smoke 命令：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --retrieval-action review_advice \
  --data-dir data/live_career_smoke_m17_advice

uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --retrieval-action review_to_learning_task \
  --data-dir data/live_career_smoke_m17_task
```

这两条 smoke 会先跑基础求职链路，再用 store 种入一条复盘 Note 作为前置状态，避免为了准备条件额外消耗一轮真实模型调用。报告会检查 M17 动作是否先召回、是否误写 memory、是否误更新 CareerApplication、是否误保存 Note，以及转任务动作是否真的创建 LearningTask。

### M18：质量验收与压力测试

目标：对当前 MVP 主闭环做一次质量验收，确认后端、Agent、前端、压力测试和真实模型 smoke 能支撑继续产品化。

报告文档：`docs/m18_quality_validation_report.md`

M18 已完成：

- Python 全量测试通过。
- `mypy` 通过。
- Flutter analyze / widget tests 通过。
- memory / flush / compaction 本地压力测试通过。
- 桌面和移动端 UI 截图检查完成。
- `interview_review` 低批次真实模型 smoke 最终通过。

本轮真实 smoke 暴露并修复：

- Retrieval 工具补充 `resume`、`jd`、`fit`、`career_job_fit_report` 等常见 source type 别名。
- Career 产品记录 `evidence_refs` 支持 `note_`，用于面试复盘 Note 回写求职项目。
- `career_resume_version_create` 在写入前拦截占位或替换类表达，避免脏 ResumeVersion 进入 store。

### M19：复盘建议真实链路验证

目标：补上 M17 从确定性测试到真实模型链路的验证入口，确认复盘建议和复盘转学习任务不会越界写入。

M19 已完成：

- `tools/smoke_career_live_flow.py` 新增 `--retrieval-action review_advice`。
- `tools/smoke_career_live_flow.py` 新增 `--retrieval-action review_to_learning_task`。
- 基础求职链路中的 JD 由 smoke 先创建为 `pasted_text` SessionArtifact，再交给 Agent 使用真实 `artifact_id`，避免模型自造 JD artifact id 后再补救。
- M17 动作前会种入一条复盘 Note，模拟用户已经完成面试复盘，不额外消耗一轮 M16 真实模型调用。
- smoke 报告会检查复盘建议只读边界和复盘转任务写入边界。
- 增加确定性报告测试覆盖 M17 越界写入和未创建 LearningTask 场景。
- `review_advice` 真实 smoke 已通过：只调用 retrieval，不写 Note、LearningTask、CareerApplication 或 memory。
- `review_to_learning_task` 真实 smoke 已通过：先召回，再创建 1 个 LearningTask，不更新 CareerApplication、不保存新 Note、不创建 WeaknessTracker、不写 memory。

## 当前优先级

M7 主线闭环和 M8 NoteService 后端主闭环已经完成低成本验证。M9-1 资料与题库后端底座和 M9-2 API 已经完成，M9-3 聊天 Agent 写入工具暂停。M10-1 LearningService 后端底座、M10-2 API、M10-3 工具 / agent 契约、M10-4 低成本主链路验证、M10 收口、M11-1 RetrievalService 领域层、M11-2 只读工具 / agent 契约、M11-3 主线链路验证、M11 收口评估、M12 召回驱动动作闭环真实 smoke、M13 只读工作台聚合层、M13 前端项目工作台弹层、M14 一级工作台页面、M14 笔记页、M14 资料与报告库第一版、M14 学习计划页第一版、M14 收口刷新闭环、M15 第一批动作闭环、M16 求职项目推进与面试复盘闭环、M17 复盘驱动准备建议、M18 质量验收、M19 复盘建议真实链路验证和 M20 学习任务入口产品化已经完成。

当前还不提前接 memory 自动写入、日历同步和提醒系统。

M10 收口已完成：

- 修正 `agent_task_progress` 事件测试预期，明确子 agent 运行进度会投影到 orchestration events。
- 保留当前前端进度面板依赖的 progress 事件，不回退运行逻辑。

推荐下一步：

```text
1. 进入 M21：产品候选版验收与收口。
2. 以完整用户路径做产品级验收：简历、JD、匹配报告、定制简历、工作台、笔记、学习任务和打卡。
3. 只修 P0 / P1 问题，暂不新增 memory 自动写入、日历提醒、外部知识库和 RAG / MCP。
```

这样可以把“目标岗位项目、用户笔记资产、资料题库和学习计划”都作为稳定事实源，再进入自动召回层。

### M20：学习任务入口产品化

目标：把学习任务从“Agent 能创建”推进到“用户能自然使用”，同时支持用户主动添加和系统推荐添加。

方案文档：`docs/m20_learning_task_entry_design.md`

M20 的关键判断：

- 学习任务有两类入口：用户主动添加、系统推荐添加。
- 用户主动添加不强制依赖求职项目、复盘 Note 或匹配报告。
- 系统推荐添加必须带 evidence_refs，保证建议可追溯。
- 第一批不新增 `LearningTask.origin` 字段，先用 `progress_notes` 和 evidence_refs 表达来源语义。
- 创建任务不自动更新 CareerApplication，不自动保存 Note，不自动创建 WeaknessTracker，不自动写 memory。

推荐实施顺序：

```text
1. 更新 Agent 契约。
2. 增加主动添加任务、推荐转任务、打卡更新的确定性 runtime 测试。
3. 再做前端学习任务入口和任务详情交互。
```

当前状态：

- M20 第一批已完成 Agent 契约更新。
- 已增加确定性 runtime 测试，覆盖用户主动添加任务、系统推荐转任务来源保留、打卡并更新任务状态。
- M20 第二批前端入口方案已完成，文档见 `docs/m20_learning_task_ui_design.md`。
- M20 第二批前端第一阶段已完成：工作台学习页支持“新建任务 / 从项目推荐 / 记录进度”，写入仍回到聊天 Agent 执行。
- M20 第二批前端第二阶段已完成：Assistant 学习建议类回复支持“加入学习任务”确认动作，并将建议回流给 Agent 创建任务。
- M20 第三批已接入低批次真实链路验证：`--retrieval-action m20_learning_entries`。
- 该 smoke 一把覆盖“只问建议不创建 / 确认加入后创建 LearningTask / 用户主动添加任务 / 记录进度并更新任务状态”四类入口。
- 2026-05-14 已完成一次低批次真实 run，实际落库链路完整：创建 2 个 LearningTask、1 个 ProgressCheckin，且未越界写 Note、CareerApplication、WeaknessTracker 或 memory。
- 本次 run 暴露了 smoke 规则过度依赖固定 `retrieval_context_pack` 调用的问题；已调整为产品意图级检查，确认加入任务时重点检查召回定位、任务创建、来源标记和 `application_ / note_ / fit_` 核心 evidence refs。
- 2026-05-14 按最新规则复跑通过：`data/live_career_smoke_m20_entries_verify/run_001`，质量门禁通过，M20 学习任务入口真实链路已收口。

### M21：产品候选版验收与收口

目标：不新增主功能，验证当前产品是否已经能稳定完成候选版主路径演示和真实试用。

方案文档：`docs/m21_product_acceptance_plan.md`

第一轮验收报告：`docs/m21_product_acceptance_report.md`

M21 验收主线：

```text
上传简历
-> 生成简历画像和职业画像
-> 分析 JD 和匹配报告
-> 生成定制简历
-> 工作台查看求职项目和资料资产
-> 创建或编辑笔记
-> 基于复盘或短板生成准备建议
-> 确认加入学习任务
-> 主动添加学习任务
-> 记录学习进度并更新任务状态
```

验收原则：

- 以用户路径为中心，不继续扩功能。
- 只修 P0 / P1 问题。
- 同时检查后端事实源、Agent 行为、前端体感和低批次真实 smoke。
- memory 自动写入、外部面经知识库、提醒系统和 RAG / MCP 继续延后。

当前状态：

- 后端 `pytest -q` 和 `mypy` 已通过。
- 前端 `flutter analyze` 和 `flutter test` 已通过。
- M21 低批次 smoke 的产品数据链路和质量门禁通过；`career_resume_version_create` 首次保护性拒绝后成功恢复，已作为 warning 记录。
- 前端截图第一次发现旧 web-server 空白页，重启 38765 端口后桌面和窄屏首页恢复正常。
