# M23 工作流规则稀疏化方案

## 背景

M23 已经完成两类主要优化：

- `tool_search + schema reveal`：默认只常驻少量工具 schema，模型需要工具时先搜索，再由 runtime 只披露目标工具 schema。
- `tool_context_window=compact`：历史工具调用结果不再完整塞回最近消息，只保留本轮未闭合的工具交换，并把已消费结果压缩成状态摘要。

最新 live smoke 已通过完整链路，但 token 拆解显示新的主要消耗点已经转移到系统提示和工作流规则：

```text
calls: 40
provider_prompt_tokens: 321,371
estimated_prompt_tokens: 310,615
system_prompt: 152,832
tools: 82,389
messages: 73,411
workflow_rules: 89,862
message_tool: 29,732
tool_state_message: 7,468
```

这说明下一步不应该继续盲目压缩工具消息，而应该处理 `workflow_rules`。目前它承担了过多“如何完成求职任务”的流程说明，虽然能提升模型执行稳定性，但普通问答、简单澄清、轻量状态查询不应该每轮都携带完整 SOP。

## 目标

1. 把工作流规则拆成更小的规则包，只在当前任务确实需要时注入。
2. 降低普通对话、轻量查询、多轮后续问题的系统提示 token。
3. 不牺牲 live smoke 的主链路质量，尤其是简历诊断、JD 分析、匹配报告、学习任务落地。
4. 保持实现可回滚、可观测，避免再引入一套难维护的隐式工具选择逻辑。

## 非目标

- 不引入 LangGraph。
- 不重构 CareerProductStore、NoteStore、LearningStore。
- 不改 RAG 分块、索引、召回算法。
- 不改前端。
- 不把工具参数契约继续堆到 `AGENT.md` 或大型工作流提示里。

## 当前问题

### 1. 规则粒度仍然偏大

现在已经从 `AGENT.md` 里拆出了一批 workflow skill：

```text
career-workflow
retrieval-workflow
retrieval-career-workflow
note-workflow
learning-workflow
```

但这些规则包仍然偏“流程级”。一旦命中关键词，就会把一整段工作流注入系统提示。比如用户只问“之前那个岗位下一步怎么准备”，可能只需要：

- 先检索已有匹配报告；
- 再根据短板生成学习任务；
- 不需要完整简历解析、JD 解析、版本生成说明。

### 2. 规则选择依据还不够结构化

当前选择主要来自用户输入和激活 artifact 的关键词。这个方向是对的，但下一步需要把规则包继续拆细，并让命中结果可观测，例如：

```json
{
  "workflow_rule_packs": [
    "always_on",
    "retrieval_required",
    "learning_task_create"
  ]
}
```

否则后面 token 降了或质量掉了，都很难判断是哪一组规则导致的。

### 3. 一些工具契约不应由提示承担

这类内容应该下沉到工具 schema、模型校验和工具错误返回，而不是每轮写进工作流提示：

- `career_profile_merge.updates` 允许字段；
- `career_application_merge.updates` 允许字段；
- `resume_version_id / application_id` 前缀；
- 禁止传 `created_at / updated_at / status / source_session_id`；
- `ResumeVersion` 禁止占位词；
- `evidence_refs` 格式；
- `source_artifact_id` 语义。

提示只保留决策层规则：什么时候该用哪个能力、什么顺序、失败时如何恢复。

## 设计原则

### 1. 常驻规则必须极少

常驻规则只保留跨任务都必须遵守的内容：

- 不编造工具名、记录 id、artifact id。
- 如果需要历史资料，先检索或列出，不凭记忆猜。
- 不把内部路径暴露给用户。
- 用户明确要求“记住”或表达长期偏好时，才使用 memory。
- 产品资产、笔记、学习任务、RAG 资料各自归属不同事实源。

### 2. 稀疏规则只解决当前任务

规则包按“当前回合意图”选择，而不是按系统拥有的全部能力选择。

示例：

```text
普通问候
  -> always_on

上传简历后说“帮我诊断”
  -> always_on + career_resume_diagnosis

上传简历和 JD 后说“生成匹配报告”
  -> always_on + career_job_fit

说“把这个总结成笔记”
  -> always_on + note_create

说“之前那个岗位下一步怎么准备”
  -> always_on + retrieval_required + learning_task_create
```

### 3. 工具搜索和规则选择分工明确

`tool_search` 解决“模型能找到哪些工具，以及需要披露哪个工具 schema”。

`workflow_rules` 解决“当前任务的产品流程和质量边界是什么”。

两者不互相替代：

- 规则选择不能决定实际工具 schema 是否暴露；
- 工具搜索结果不能替代流程约束；
- runtime 负责披露 schema；
- prompt 只指导模型什么时候该搜索、什么时候该继续读详情。

### 4. 默认保守，可回滚

第一阶段必须保留开关：

```text
WORKFLOW_RULE_SELECTION_MODE=full | sparse
```

建议默认先用 `full`，live smoke 稳定后再改默认值。开发和压测时用 `sparse` 对比。

## 规则包拆分

### always_on

每轮注入，控制系统级边界。

内容：

- 不编造 id 和工具结果。
- 需要历史资料时使用检索或列表工具。
- 用户看得见的文件以 `SessionArtifact` 为准。
- 产品记录、笔记、学习任务、memory 不混用。
- 工具失败时根据错误修正参数；无法完成时说明缺少什么。

### retrieval_required

命中条件：

- 用户提到“之前、上次、最近、保存过、已有、当前画像、当前匹配、投过、复盘”。
- 当前问题依赖历史资产，但没有明确提供 id。

内容：

- 先用检索定位候选。
- 需要使用内容时，再读取 context pack 或详情。
- 不要根据会话记忆猜已有记录。

### career_resume_diagnosis

命中条件：

- 当前有简历 artifact；
- 用户要求诊断、解析、画像、优化简历。

内容：

- 简历原文来自 artifact。
- 诊断报告作为用户可见 Markdown artifact。
- ResumeProfile 和 CareerProfile 的职责边界。

### career_jd_analysis

命中条件：

- 当前有 JD 文本、JD artifact；
- 用户要求分析岗位或提炼 JD。

内容：

- 粘贴 JD 先转 artifact。
- JDAnalysis 保存结构化结论。
- 不把 JD 原文塞进 memory。

### career_job_fit

命中条件：

- 同时涉及简历和 JD；
- 用户要求匹配、投递建议、面试准备、岗位适配。

内容：

- 优先复用已有 ResumeProfile / CareerProfile / JDAnalysis。
- JobFitReport 的 `source_artifact_id` 指 JD 输入来源。
- 报告输出 artifact 使用 `report_artifact_id`。
- 匹配结论必须给出可执行建议。

### career_application

命中条件：

- 用户提到投递、申请记录、跟进状态、面试阶段、offer、拒信。

内容：

- 投递记录是产品资产，不是笔记。
- 状态更新用 merge，不覆盖历史。
- 关键证据来自 artifact、匹配报告、用户输入。

### note_create

命中条件：

- 用户明确说“记成笔记、保存为笔记、整理成笔记、这是我的面经、这是我的总结”。

内容：

- 笔记由用户可编辑。
- 类型保持少量：学习、面经、通用。
- 先不自动进入 memory。

### learning_task_create

命中条件：

- 用户提到学习计划、学习任务、加入计划、今天该学、监督、打卡、短板补齐。

内容：

- 学习任务可由用户手动创建，也可从匹配报告和短板推荐。
- 推荐任务必须关联来源。
- 不创建虚假的 `resource_id`。

### delegate_agents

命中条件：

- 当前任务需要并行处理简历、JD、匹配报告、版本生成；
- 或主 agent 需要委派专职 agent 完成产品资产生成。

内容：

- 委派时任务要具体。
- 不把所有工作都留给主 agent。
- 子任务结果回到主 agent 汇总。

## 实现方案

### 1. 建立规则目录

新增或改造：

```text
app/runtime/context/workflow_rules.py
```

输出结构建议：

```python
@dataclass(frozen=True)
class WorkflowRulePack:
    name: str
    content: str
    triggers: tuple[str, ...]
    priority: int
```

保留一个入口：

```python
select_workflow_rule_packs(
    role: ContextAssemblyRole,
    user_message: str,
    active_artifacts: list[SessionArtifact],
    selected_skill_names: list[str],
) -> list[WorkflowRulePack]
```

### 2. 用确定性分类，不引入 LLM

规则选择只做轻量关键词和上下文判断，不再调用模型。

原因：

- 规则选择本身是成本优化路径，不能额外引入 LLM 消耗。
- 规则选择错了也要可解释、可调试。
- 后续可以用评估集持续调整关键词。

### 3. 观测规则包命中

`ContextBundle.system_prompt_sections` 已经能记录 section token。下一步增加规则包名：

```json
{
  "section": "workflow_rules",
  "item_count": 3,
  "pack_names": ["always_on", "career_job_fit", "delegate_agents"],
  "tokens": 1280
}
```

`llm_usage` 中也记录：

```json
{
  "workflow_rule_selection_mode": "sparse",
  "workflow_rule_pack_names": ["always_on", "career_job_fit"],
  "workflow_rules_estimate_tokens": 1280
}
```

### 4. 保留 full 回滚路径

配置：

```text
WORKFLOW_RULE_SELECTION_MODE=full
WORKFLOW_RULE_SELECTION_MODE=sparse
```

`full`：保留当前粗粒度 workflow skill 注入逻辑，命中求职、召回、笔记或学习场景时注入对应完整 `SKILL.md` 文本，方便回滚。

`sparse`：只注入 `always_on + selected packs`。

### 5. 不再维护第二套工具意图裁剪

工具 schema 只走：

```text
tool_search -> runtime schema reveal
```

不再恢复“按意图直接暴露一组工具 schema”的旧方式，避免形成僵尸逻辑。

## 测试计划

### 单元测试

新增或扩展：

```text
tests/test_context_assembler.py
tests/test_workflow_rules.py
tests/test_token_usage_debug_service.py
```

覆盖：

- 普通问候只命中 `always_on`。
- 简历诊断命中 `career_resume_diagnosis`。
- 简历 + JD 匹配命中 `career_job_fit` 和必要时 `delegate_agents`。
- “之前那个岗位下一步怎么准备”命中 `retrieval_required + learning_task_create`。
- 明确写笔记命中 `note_create`。
- `full` 模式仍保留原始行为。
- `llm_usage` 能看到规则包名和 token。

### live smoke

使用同一条链路对比：

```bash
TOOL_SCHEMA_DISCLOSURE_MODE=search \
TOOL_CONTEXT_WINDOW_MODE=compact \
WORKFLOW_RULE_SELECTION_MODE=sparse \
TOOL_SCHEMA_ALWAYS_VISIBLE=tool_search,memory_write \
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --retrieval-action review_to_learning_task \
  --data-dir data/live_career_smoke_m23_workflow_sparse
```

验收后再跑并发：

```bash
TOOL_SCHEMA_DISCLOSURE_MODE=search \
TOOL_CONTEXT_WINDOW_MODE=compact \
WORKFLOW_RULE_SELECTION_MODE=sparse \
TOOL_SCHEMA_ALWAYS_VISIBLE=tool_search,memory_write \
uv run python tools/smoke_career_live_flow.py \
  --runs 3 \
  --concurrency 2 \
  --max-tool-rounds 10 \
  --retrieval-action review_to_learning_task \
  --data-dir data/live_career_smoke_m23_workflow_sparse_full
```

## 验收标准

必须满足：

- `uv run pytest -q` 通过。
- `uv run mypy ...` 相关文件通过。
- live smoke `quality_gate=passed`。
- 不出现明显工具搜索失败、漏工具、乱造 id。
- 匹配报告、学习任务、投递资产仍能落地。

目标指标：

```text
workflow_rules token 较当前下降 40% 以上
system_prompt token 较当前下降 25% 以上
总 prompt token 至少下降 15%
```

当前基线：

```text
estimated_prompt_tokens: 310,615
system_prompt: 152,832
workflow_rules: 89,862
tools: 82,389
messages: 73,411
```

## 风险

### 规则漏选

风险：模型没有拿到必要流程说明，导致漏建产品记录或错误调用工具。

处理：

- `always_on` 保留“需要历史资料先检索”“不能编造 id”等底线。
- live smoke 覆盖主链路。
- 规则命中写入 token 观测，失败时能回看缺了哪个 pack。

### 规则包继续膨胀

风险：拆分后每个 pack 又变成小型 AGENT.md。

处理：

- 每个 pack 只写决策规则，不写字段契约。
- 字段约束下沉到工具 schema 和模型校验。
- 每次新增规则包必须有测试和 token 观测。

### 与 tool_search 职责混淆

风险：规则选择又变成另一套工具选择。

处理：

- 规则包只影响 prompt，不影响可调用工具列表。
- schema reveal 仍由 `tool_search` 和 runtime 控制。

## 开发顺序

```text
1. 增加 WORKFLOW_RULE_SELECTION_MODE 配置。
2. 将 workflow rules 拆成 always_on + 细粒度 pack。
3. ContextAssembler 注入选中的 pack。
4. llm_usage 增加 pack_names 和 token 观测。
5. 补单元测试。
6. 跑 live smoke 单轮。
7. 对比 token breakdown。
8. 通过后再跑小并发 smoke。
```

## 结论

下一步应该先优化 `workflow_rules`，不是继续压缩 tool message，也不是马上改 RAG。

原因是当前数据已经很明确：工具历史消息已经降到可控范围，新的大头是系统提示里的流程规则。正确做法是把规则拆细、按任务稀疏注入、保留观测和回滚路径。这样既能降低成本，也能避免产品主链路质量突然下降。
