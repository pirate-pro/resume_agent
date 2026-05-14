# M16 求职项目推进与面试复盘闭环方案

## 背景

当前系统已经完成简历画像、JD 分析、岗位匹配、定制简历、笔记、学习计划和工作台管理。下一步主线不应该继续堆前端细节，而是补上真实求职过程里最关键的一段：

```text
投递
  -> 面试 / 笔试 / HR 沟通
  -> 记录问题和反馈
  -> 更新求职项目判断
  -> 生成下一步准备重点
  -> 继续学习和复盘
```

这段链路决定用户是否会长期使用产品。用户不可能只上传一次简历，真实过程会持续出现：

- “我投了这家公司。”
- “刚面完一面，被问到 RAG 和 Celery。”
- “HR 说下周二面。”
- “挂了，反馈是项目深度不够。”
- “这轮问题帮我记下来，后面复盘。”

M16 要把这些信息沉淀到现有产品资产里，而不是散落在聊天记录中。

## 产品目标

M16 第一批目标：

- 用户能通过自然语言更新求职项目推进状态。
- 用户能把面试题、回答表现、HR 反馈、失败原因保存为 Note。
- 面试复盘 Note 能关联到对应 `CareerApplication`。
- `CareerApplication` 能同步更新 `stage`、`summary`、`risks`、`next_actions`、`notes`。
- 用户明确要求后，才进一步创建 LearningTask 或 WeaknessTracker。

## 边界判断

M16 第一批不新增后端事实源。

```text
CareerApplication = 求职项目状态和当前判断
Note = 用户可见、可编辑的面试复盘和问题记录
LearningTask / WeaknessTracker = 用户明确要求监督或转学习计划时再创建
SessionArtifact = 用户可见文件事实源
memory = 运行时上下文材料，不自动写
```

不新增 `InterviewRecordStore` 的原因：

- 现在的面试记录形态还不稳定。
- Note 已经能保存长文本复盘、题目、反馈和情绪。
- CareerApplication 已经能保存项目阶段和下一步行动。
- 先用现有事实源跑通闭环，比提前建新模型更稳。

后续如果面试记录结构稳定，再考虑抽出 `InterviewEvent` 或 `ApplicationEvent`。

## 典型用户意图

### 1. 投递状态更新

```text
我已经投了星河智能这个岗位
```

处理规则：

- 先召回或读取对应 `CareerApplication`。
- 使用 `career_application_merge` 更新：
  - `stage = applied`
  - `summary`
  - `next_actions`
  - `notes`
- 不自动创建 Note。
- 不写 memory。

### 2. 面试安排

```text
星河智能约我下周二面
```

处理规则：

- 更新 `CareerApplication.stage = interviewing`。
- 更新下一步准备项。
- 如果用户只是通知，不自动创建 Note。
- 如果用户要求记录安排，可以创建 Note。

### 3. 面试复盘

```text
我刚面完星河智能一面，被问到 RAG chunk 策略和 Celery 延迟队列，答得一般，帮我记录复盘并更新项目。
```

处理规则：

- 先召回对应 `CareerApplication` 和上下文。
- 用 `note_create` 保存复盘，`related_application_id` 指向项目。
- 用 `career_application_merge` 更新项目判断。
- 不重新解析简历，不重新分析 JD，不重新生成匹配报告。
- 不自动创建 LearningTask，除非用户明确说“加入计划 / 监督我补”。
- 不写 memory。

### 4. 面试失败或 offer

```text
这家公司挂了，反馈是项目深度不够。
```

处理规则：

- 更新 `CareerApplication.stage = rejected` 或 `offer`。
- 保存复盘 Note，记录反馈和原因。
- 更新 `risks` 和 `next_actions`，用于后续岗位修正。
- 不自动写 memory。

## Agent 契约

当用户表达投递进展、面试安排、面试复盘或结果反馈时：

1. 如果没有提供 `application_id`，先用 Retrieval 定位相关 `CareerApplication`。
2. 如果召回到多个候选且无法判断，先让用户确认。
3. 如果用户只是询问准备建议，默认只回答，不写记录。
4. 如果用户明确要求“记录 / 复盘 / 更新项目”，按需调用：
   - `note_create` 或 `note_append`
   - `career_application_merge`
5. `note_create` 的 `evidence_refs` 只使用 NoteService 支持的受控 id。
6. `career_application_merge` 的 `evidence_refs` 只使用 CareerService 支持的受控 id。
7. 不因为复盘内容有短板就自动创建 LearningTask。
8. 不写 memory。

## 第一批开发范围

```text
1. 更新 app/agents/default/AGENT.md
2. 增加确定性 runtime 测试
3. 更新产品路线文档
```

第一批不做：

- API 新增。
- 后端模型新增。
- 前端新增页面。
- smoke 压力测试。
- RAG / MCP。
- memory 自动写入。

## 验收标准

- 用户表达面试复盘并要求记录时，系统先召回项目上下文。
- 系统创建一条关联 `CareerApplication` 的 Note。
- 系统更新对应 `CareerApplication` 的阶段、风险和下一步行动。
- 不重新委派 `resume_agent` 或 `job_agent`。
- 不重新创建 `ResumeProfile`、`JDAnalysis`、`JobFitReport`。
- 不创建 LearningTask，除非用户明确要求加入计划。
- 不写 memory。
- 定向测试通过。

## 后续方向

M16 第一批验证后，再考虑：

- 工作台项目详情中更清晰展示面试复盘时间线。
- 把多条复盘聚合为项目风险趋势。
- 根据多次面试反馈生成求职策略调整建议。
- 如果面试记录形态稳定，再抽象 `InterviewEvent`。
