# M17 复盘驱动准备建议方案

## 背景

M16 已经把真实求职推进补齐到现有资产里：

```text
面试复盘 -> Note
项目状态 -> CareerApplication
求职进展 -> 工作台展示
```

下一步不应该直接把每次复盘都变成学习任务。真实用户刚面完后，通常先想知道：

- 我哪里答得不好？
- 下一轮应该先补什么？
- 哪些问题值得练？
- 已有计划里有没有能复用的任务？
- 这些建议要不要加入计划？

因此 M17 的第一目标是先把“复盘后的准备建议”做稳，再由用户确认是否转成 LearningTask。

## 产品目标

M17 第一批目标：

- 用户问下一步怎么准备时，系统能基于复盘 Note、求职项目、匹配报告和已有学习资料给出建议。
- 建议默认只回答，不自动写入 LearningTask、WeaknessTracker、CareerApplication、Note 或 memory。
- 用户明确说“加入学习任务 / 创建任务 / 监督我完成”时，才创建 LearningTask。
- 创建 LearningTask 时，要带上复盘 Note、求职项目、匹配报告、已有学习计划、短板、资料或题目的证据引用。
- 不重复创建同类学习任务；如果已有任务，应优先提醒用户复用或更新。

## 边界判断

M17 第一批不新增事实源。

```text
Note = 面试复盘与用户可编辑内容
CareerApplication = 项目状态和当前判断
JobFitReport = 岗位匹配与短板依据
LearningTask = 用户确认后的可执行学习任务
WeaknessTracker = 用户确认跟踪后的能力短板
RetrievalService = 只读召回上下文
memory = 不自动写入
```

关键边界：

- 建议不是任务。
- 短板不是自动跟踪对象。
- 复盘内容不自动进入 memory。
- 只有用户确认后，建议才落到 LearningService。

## 典型用户意图

### 1. 只问准备建议

```text
根据星河智能一面复盘，我下一步该怎么准备？
```

处理规则：

- 先召回相关 `CareerApplication`。
- 再召回匹配报告、复盘 Note、已有 LearningTask、WeaknessTracker 和资料题库。
- 给出准备建议，按优先级组织。
- 不创建 LearningTask。
- 不更新 CareerApplication。
- 不写 memory。

### 2. 明确转成学习任务

```text
把 RAG 评估和 Celery 补强加入学习任务，监督我完成。
```

处理规则：

- 先召回复盘依据。
- 如已有同类任务，优先复用或提醒用户。
- 如果需要新建任务，调用 `learning_task_create`。
- `evidence_refs` 至少包含：
  - `application_id`
  - 复盘 `note_id`
  - 实际依据的 `fit_id`
  - 如适用，包含 `learning_plan_id`、`weakness_id`、`resource_id`、`question_id`
- 不顺手更新 CareerApplication，除非用户同时明确要求更新项目状态。
- 不写 memory。

## Agent 契约

当用户基于面试复盘询问下一步准备时：

1. 如果没有提供产品记录 id，先用 Retrieval 定位相关 `CareerApplication`。
2. 使用 `retrieval_context_pack` 读取项目、匹配报告、复盘 Note、学习任务、短板和资料题库。
3. 只问建议时，默认只回答。
4. 建议内容要包含：
   - 优先级
   - 准备主题
   - 练习产出
   - 验收标准
   - 可复用的已有任务或资料
5. 只有用户明确要求创建任务、加入计划或监督完成，才调用 LearningService。
6. 转成 LearningTask 时，不自动调用 `career_application_merge`。
7. 不写 memory。

## 第一批开发范围

```text
1. 更新 app/agents/default/AGENT.md
2. 增加确定性 runtime 测试
3. 更新产品路线文档
```

第一批不做：

- API 新增。
- 后端模型新增。
- 前端新增按钮。
- 自动任务拆解。
- 自动短板跟踪。
- memory 自动写入。
- live smoke 压力测试。

## 第二批真实链路验证

M17 第二批把复盘建议链路接入 `tools/smoke_career_live_flow.py`，用于低批次验证真实模型是否遵守边界。

新增两个动作：

```text
review_advice
  -> 基于已有复盘 Note 给下一步准备建议
  -> 只读回答，不创建 LearningTask、不更新 CareerApplication、不写 Note、不写 memory

review_to_learning_task
  -> 基于已有复盘 Note 创建 LearningTask
  -> 必须先召回复盘依据
  -> 创建 LearningTask
  -> 不顺手更新 CareerApplication、不保存新 Note、不创建 WeaknessTracker、不写 memory
```

为了控制 token 成本，这两个动作不会额外跑一轮 M16 面试复盘。smoke 会在基础求职链路完成后，用 store 直接种入一条复盘 Note，模拟用户之前已经完成复盘的状态，然后再让模型执行 M17 动作。

基础求职链路中的 JD 也按 artifact-first 处理：smoke 会先创建 `pasted_text` JD artifact，再要求 Agent 基于真实 `artifact_id` 委派 `job_agent` 和保存 `JDAnalysis`。这样验证的是产品主链路，而不是让模型在同一轮里先猜 artifact id 再自我修正。

可选命令：

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

## 验收标准

- 用户只问复盘后的下一步准备时，系统先召回上下文并只回答。
- 只问建议时，不创建 LearningTask。
- 只问建议时，不更新 CareerApplication。
- 只问建议时，不写 Note 或 memory。
- 用户明确要求转学习任务时，系统创建 LearningTask。
- LearningTask 关联复盘 Note、求职项目和实际依据。
- 转任务时不顺手更新 CareerApplication。
- 定向测试通过。

## 后续方向

M17 第一批稳定后，再考虑：

- 在工作台中增加“建议转任务”的显式动作。
- 对已有任务做更强的去重和更新。
- 把多次复盘聚合成准备趋势。
- 对学习任务完成情况反向更新项目准备度。
