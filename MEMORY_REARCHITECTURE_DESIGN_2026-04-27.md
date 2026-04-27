# Memory Re-Architecture Design

日期：2026-04-27

## 1. 文档目标

本文档用于定义下一阶段的 memory 系统重构方案。重构目标不是继续扩展当前 memory 子系统的能力边界，而是先把边界收窄、分层、动态化。

核心前提：

- `AGENT.md`：大写，表示静态行为宪法层。
- `SOUL.md`：大写，表示静态或缓变的身份人格层。
- `state`：表示运行态工作区，默认按 agent 隔离，并允许显式发布为共享协作状态。
- `memory`：表示与用户长期互动中形成、会随着时间和证据变化的经验层。

本方案的核心判断如下：

1. `AGENT.md` 和 `SOUL.md` 不应被 runtime 自动写入。
2. `state` 不应与 `memory` 混用。
3. `memory` 不是“所有可复用文本的收纳箱”，而是“长期互动经验”。
4. `memory` 必须是动态的，可强化、可衰减、可被新证据覆盖。
5. `state` 默认是 agent 私有的；只有显式发布的部分才进入共享协作面。

## 2. 当前实现的问题

当前实现中，memory 子系统的代码主体分布在以下模块：

- `app/runtime/memory_manager.py`
- `app/memory/intake.py`
- `app/memory/consolidation.py`
- `app/memory/retrieval.py`
- `app/memory/stores/jsonl_file_store.py`
- `app/runtime/context_assembler.py`
- `app/tools/builtins.py`

当前设计的问题不在于“检索太弱”，而在于“memory 的概念太宽”。

### 2.1 现在的 memory 实际上承载了四种不同对象

当前实现把以下内容都可能写进 memory：

- 用户长期偏好
- 用户或系统约束
- 当前任务状态
- 临时 scratch 信息

这些内容的生命周期、权威来源、检索方式都不同，但现在被统一塞进：

- `agent_short`
- `agent_long`
- `shared_long`

这导致：

1. 长期经验和当前任务状态混在一起。
2. 检索结果污染 prompt。
3. tags 变成事实上的主语义模型，过于脆弱。
4. memory 写入门槛过低，几乎“非空文本即可入库”。

### 2.2 当前 memory 写入机制过宽

当前写入主链路：

1. `memory_write` 工具接收 `content` 和 `tags`
2. `MemoryManager.write_memory(...)` 做最基础校验
3. `intake.py` 用 tags 推断：
   - `scope_hint`
   - `memory_type`
   - `confidence`
4. 进入 candidate 队列
5. 通过 consolidation 晋升到 short / long / shared

这套流程的问题是：

- 没有判断“这是不是 memory”
- 只有判断“如果要存，应该落到哪一层”

也就是说，当前系统缺少的是 admission layer，而不是 storage layer。

### 2.3 当前检索默认把 memory 当作通用上下文补全层

当前 `ContextAssembler` 会在每轮对话前直接按用户 query 检索 memory，然后将命中内容加入系统提示中的 `Relevant memories`。

这会带来两个问题：

1. 只要 memory 被错误写入，后续所有轮次都有可能被持续召回。
2. 没有区分“应该查长期经验”还是“应该查当前任务状态”。

## 3. 新的四层架构

### 3.1 `AGENT.md`

职责：

- 定义不可轻易变动的行为规则
- 定义能力边界
- 定义回答规范
- 定义禁止行为

回答的问题：

- 我必须怎么做
- 我绝不能怎么做

特征：

- 高权威
- 低变化
- 不由 runtime 自动写入
- 不属于 memory

### 3.2 `SOUL.md`

职责：

- 定义身份感
- 定义人格气质
- 定义与用户的关系姿态
- 定义语气基调

回答的问题：

- 我是谁
- 我以什么风格与用户互动

特征：

- 高稳定性
- 可缓慢演化，但不应由每轮对话自动写入
- 不属于 memory

### 3.3 `state`

职责：

- 保存当前任务、当前会话、当前运行阶段的工作状态
- 保存临时目标、待办、步骤、局部结论
- 保存当前上下文窗口之外但仍需短期延续的任务信息
- 为多 agent 协作提供“私有工作区”和“显式共享工作区”

回答的问题：

- 我现在正在做什么
- 当前任务做到哪一步
- 下一步是什么
- 哪些当前状态只属于我这个 agent
- 哪些当前状态已经发布给协作 agent

特征：

- 高变化
- 强会话绑定
- 默认按 agent 隔离
- 默认不跨会话
- 默认不进入长期 memory
- 允许存在显式共享的 `state_shared_session`

### 3.4 `memory`

职责：

- 保存与用户长期互动中形成的经验
- 保存会影响未来多次交互的用户相关状态
- 保存被确认、被重复强化、或被反馈修正过的长期信息

回答的问题：

- 我从与这个用户长期互动中学到了什么
- 这些学习现在是否仍然成立

特征：

- 动态变化
- 允许冲突与覆盖
- 允许衰减
- 允许撤销
- 不等于系统规则
- 不等于当前任务状态

## 4. Memory 的新边界定义

### 4.1 什么算 memory

符合以下全部条件的内容，才应该被视为 memory：

1. 与用户长期互动有关，而不是只服务当前任务。
2. 未来跨会话仍可能复用。
3. 其价值在于“帮助 agent 更好地理解这个用户或与这个用户协作”。
4. 它不是 `AGENT.md` 的规则，不是 `SOUL.md` 的设定，不是 `state` 的临时工作数据。

### 4.2 memory 的推荐类别

建议将 memory 收窄到以下四类：

#### A. `user_preference`

示例：

- 用户希望被称呼为某个名字
- 用户偏好中文或英文
- 用户偏好简洁回答
- 用户不喜欢表格

#### B. `user_fact`

示例：

- 用户长期使用某种技术栈
- 用户所在行业或背景信息
- 用户长期目标

要求：

- 必须是未来高概率复用的事实
- 不能是短期任务环境信息

#### C. `interaction_pattern`

示例：

- 用户多次明确表示不喜欢铺垫
- 用户更接受先结论后细节的结构
- 用户经常要求给出可执行步骤

要求：

- 应主要来自重复行为或明确反馈
- 不建议单轮推断后立即固化

#### D. `feedback_memory`

示例：

- 用户说“不要再用这种格式”
- 用户说“这个结构很好，以后保持”

作用：

- 修正 agent 的互动方式
- 强化或抑制其它 memory

### 4.3 什么不算 memory

以下内容不应进入 memory：

- `AGENT.md` 中的行为规则
- `SOUL.md` 中的身份和人格设定
- 当前任务的 plan / next step / working notes
- 会话中的一次性指令
- 文件原文
- 工具原始输出
- assistant 的草稿推断
- 未经确认的猜测
- 会话事件日志本身
- 系统 policy 和平台 policy

## 5. 引入独立的 State 子系统

### 5.1 设计原则

当前 `agent_short` 的一部分职责更接近 state，而不是 memory。

因此建议从概念上拆分：

- `state`: 当前工作状态
- `memory`: 长期互动经验

同时在 `state` 内部继续拆两层：

- `state_agent_session`: 当前 agent 在当前 session 的私有工作状态
- `state_shared_session`: 当前 session 内显式共享给多个 agent 的协作状态

### 5.2 state 应承载的内容

建议 `state_agent_session` 包含：

- `current_goal`
- `current_plan`
- `working_notes`
- `current_decisions`
- `pending_actions`
- `session_constraints`

建议 `state_shared_session` 仅包含已经显式发布的协作信息，例如：

- `shared_goal`
- `published_decisions`
- `delegation_contracts`
- `shared_checkpoints`
- `handoff_notes`

### 5.3 state 的检索原则

- `state_agent_session`：仅当前 agent、当前 session 默认可见
- `state_shared_session`：当前 session 内具备共享权限的 agent 可见
- 不跨用户
- 不默认晋升为长期 memory
- prompt 注入优先级高于 memory，但生命周期更短
- agent 之间不得直接读取对方私有 state，除非该状态已被发布到 shared state

### 5.4 对现有 scope 的映射建议

当前 scope：

- `agent_short`
- `agent_long`
- `shared_long`

建议未来演进为：

- `state_agent_session`
- `state_shared_session`
- `memory_agent_long`
- `memory_shared_long`

兼容阶段可以保留旧字段，但在内部语义上将：

- `agent_short` 默认逐步迁移为 `state_agent_session`
- 仅显式发布的 `agent_short` 内容才可进入 `state_shared_session`
- `agent_long` 逐步迁移为 `memory_agent_long`
- `shared_long` 逐步迁移为 `memory_shared_long`

这里不建议使用 `memory_user` 作为 scope 名称，因为它会把“subject 是用户”和“可见性是共享还是私有”两个维度混在一起。

对于多 agent 系统，更合理的是分成两个正交维度：

- subject：这条记录是关于谁或什么的
- visibility / ownership：这条记录归哪个 agent，还是共享给多个 agent

在这个模型里：

- “关于用户”的长期经验可以是 `memory_agent_long`
- 也可以在显式晋升后变成 `memory_shared_long`

因此，“user”更适合作为 `kind` 或 `subject_id` 语义，而不适合作为 scope 命名。

## 6. 新的 Memory 数据模型

### 6.1 目标

当前模型以 `tags + scope + type` 为核心，过于依赖自由标签。

新的模型应以“结构化经验”作为核心。

### 6.2 建议字段

建议在长期 memory 记录中引入以下字段：

- `memory_id`
- `subject_id`
- `owner_agent_id`
- `visibility`
- `kind`
- `canonical_key`
- `content`
- `normalized_value`
- `source_kind`
- `source_refs`
- `evidence_count`
- `confidence`
- `stability`
- `activation`
- `first_seen_at`
- `last_seen_at`
- `last_confirmed_at`
- `decay_after_days`
- `status`
- `superseded_by`
- `metadata`

### 6.3 字段语义

#### `kind`

枚举建议：

- `user_preference`
- `user_fact`
- `interaction_pattern`
- `feedback_memory`

#### `owner_agent_id`

表示该长期经验默认归属哪个 agent。

当 `visibility = agent_private` 时：

- 只能由 owner agent 默认读取

当 `visibility = shared` 时：

- 表示该 memory 已被发布到多 agent 可见域

#### `visibility`

枚举建议：

- `agent_private`
- `shared`

#### `canonical_key`

用于归并和冲突覆盖，例如：

- `preferred_name`
- `preferred_language`
- `response_style`
- `disliked_format`
- `long_term_goal`

#### `source_kind`

枚举建议：

- `explicit_user`
- `user_feedback`
- `repeated_behavior`
- `tool_verified`
- `assistant_inferred`

#### `status`

枚举建议：

- `candidate`
- `active`
- `suppressed`
- `contradicted`
- `expired`

#### `stability`

表示这条经验是否稳定，可用 0 到 1 表示。

#### `activation`

表示当前召回优先级，受以下因素影响：

- 最近使用时间
- 用户确认次数
- 重复出现次数
- 正负反馈
- 冲突证据
- 衰减

## 7. Memory 的动态生命周期

### 7.1 候选产生

memory 不应接受任意文本直接入库，而应先形成 candidate。

候选来源仅建议保留以下几类：

- 用户明确说“记住/以后按这个来”
- 用户明确纠正 agent
- 用户长期重复反馈
- 工具验证后的稳定事实
- 多次重复行为归纳出的模式

### 7.2 admission：是否值得记住

新增 `MemoryAdmissionPolicy`，判断候选是否应进入 memory。

建议 admission 必须回答以下问题：

1. 这是长期经验还是当前状态？
2. 它是否描述用户，而不是描述任务？
3. 它未来是否会跨会话复用？
4. 它是否已经达到足够证据门槛？
5. 它应该保留在 agent 私有域，还是值得发布到 shared 域？

admission 结果建议只有以下几种：

- `reject`
- `route_to_state`
- `candidate_memory`
- `active_memory`
- `needs_confirmation`

实现注记（2026-04-27，Admission V1 已落地）：

- runtime 已新增显式 admission 层，对 `memory_write` 进入 `MemoryManager.write_memory(...)` 前做硬拦截。
- 当前第一版先覆盖两个高污染来源：
  - 明显属于 session working state 的内容：拒绝写 memory，并要求改用 `state_set`
  - 明显属于原始文件/工具输出的内容：拒绝写 memory，要求先提炼稳定经验
- 这一版仍是保守规则，不做静默自动分流，不把 `memory_write` 悄悄改写为 `state_set`。

### 7.3 canonicalization：标准化

候选通过 admission 后，不直接以原始文本保存，而要做 canonicalization。

示例：

- “以后叫我老王” -> `preferred_name = 老王`
- “回复尽量简洁” -> `response_style = concise`
- “别用表格” -> `disliked_format = table`

这样后续更新可以基于 `canonical_key` 归并，而不是做全文模糊搜索。

实现注记（2026-04-27，Canonicalization Metadata V1 已落地）：

- 当前尚未把 `kind / canonical_key / source_kind / normalized_value` 升级为 `MemoryRecord` 顶层字段。
- 为降低迁移成本，第一版先在 candidate 写入阶段完成结构化归类，并把结果写入 `metadata`：
  - `kind`
  - `source_kind`
  - `canonical_key`
  - `normalized_value`
  - `subject_kind`
  - `classification_version`
- 这样后续 consolidation、检索、迁移脚本都可以先消费 metadata，再决定何时升级正式 schema。

实现注记（2026-04-27，Canonical Dedup V1 已落地）：

- consolidation 现已开始消费 `canonical_key + normalized_value`。
- 当前策略：
  - 同一批 candidate 内，如果 `canonical_key + normalized_value` 相同，则只保留一条。
  - 若目标作用域内已存在相同 `canonical_key + normalized_value` 的 active record，则本轮跳过重复写入。
- 这一版只做“同语义去重”，暂不做“同 key 不同 value 的冲突覆盖”。

实现注记（2026-04-27，Canonical Supersede V1 已落地）：

- consolidation 现已开始处理“同 `canonical_key`、不同 `normalized_value`”的更新场景。
- 当前策略：
  - 若新候选与既有 active record 的 `canonical_key` 相同、`normalized_value` 不同，则进入 supersede 判定。
  - 当新候选来源权重不低于旧记录时：
    - 旧 active record 归档为 `archived`
    - 新 record 接管该 `canonical_key`
    - 旧 record 在 metadata 中记录 `superseded_by_memory_id` / `superseded_by_normalized_value`
    - 新 record 使用 `parent_memory_id` 连接到上一条被替代记录
  - 当新候选来源权重更低时：
    - 本轮拒绝覆盖
    - 计入 consolidation `conflicts`
- 当前来源优先级已落地到运行时代码：
  - `system_policy`
  - `explicit_user_rule`
  - `explicit_user`
  - `user_feedback`
  - `tool_verified`
  - `repeated_behavior`
  - `assistant_inferred`

实现注记（2026-04-27，`memory_update` Canonical Match V1 已落地）：

- `memory_update` 已不再完全依赖全文搜索。
- 当前策略：
  - 先对 update query 做同一套 canonicalization
  - 如果能提取出 `canonical_key + normalized_value`，则优先做 active record 的 exact match
  - 只有在 query 无法结构化，或当前没有 exact active match 时，才回退到原有全文搜索
- 第一版已覆盖的关键点：
  - 陈述式称呼语句也能结构化识别，例如：
    - `用户称呼是李华`
    - `用户称呼改为小李`
    - `用户名字叫李华`
  - update 结果中会显式返回 `match_strategy`，便于调试和后续审计。
- 这一版的目标不是彻底消灭全文搜索，而是先把“结构化长期经验”的更新主路径拉到 canonical exact match 上。

实现注记（2026-04-27，`memory_update` Canonical Direct V2 已落地）：

- canonical memory 的 update 路径已不再执行 `forget -> write`。
- 当前策略：
  - 如果 target 本身带 `canonical_key`，且新内容能 canonicalize 到同一个 `canonical_key`
  - 则直接提交新 candidate，由 consolidation 决定：
    - `supersede`
    - `semantic_noop`
    - `source_priority_conflict`
- 这样可以避免两个问题：
  - 先删旧值再写新值，导致 supersede 审计链丢失
  - 先删旧值再写新值，导致低优先级来源绕过 source priority 检查
- 目前只有非 canonical target 仍保留 replace fallback。
- update 结果现在会额外返回 `update_mode`，用于区分：
  - `canonical_supersede`
  - `canonical_direct`
  - `replace_rewrite`
- 同时修正了 `source_kind` 推断中的一处实现偏差：
  - 带 `system_policy` / `explicit_user_rule` tag 的 candidate，现在会被正确归类到对应高优先级 source，而不是错误保留为工具名。

实现注记（2026-04-27，Legacy Structured Backfill V1 已落地）：

- 旧 record 即使还没有结构化 metadata，也不再只能走 `replace_rewrite`。
- 当前策略：
  - `memory_update` 在定位到 target 后，会先尝试对该 record 重新跑 classification
  - 如果 target 缺失 `canonical_key / normalized_value / source_kind / kind` 等结构化字段，则先就地回填 metadata
  - 回填完成后，再按新的结构化信息决定是否进入 canonical direct update
- 这样可以覆盖一类重要历史数据：
  - 旧数据内容本身可识别，例如 `以后叫我李华`
  - 但写入发生在 canonicalization 上线前，因此 record 里没有结构化 metadata
- 当前这一版仍是“按需触发的在线回填”：
  - 只有当 legacy record 真正被 update 时，才会补 metadata
  - 还没有做离线批量迁移任务
- 这一步的价值是先把历史数据编辑路径拉进新规则，逐步缩小 `replace_rewrite` fallback 的适用面。

实现注记（2026-04-27，Offline Structured Backfill V1 已落地）：

- 现有 memory store 已支持离线批量回填结构化 metadata。
- 当前策略：
  - 按 `scope / agent_id / session_id` 扫描现存 records
  - 对缺失结构化字段的 legacy records 就地 patch metadata
  - 默认跳过 deleted records，但会处理 active / archived records
  - 同时会修正一小类已知脏值：
    - 旧实现遗留的 `source_kind=memory_write_tool / memory_update_tool / memory_manager ...`
- 这一版采取保守迁移原则：
  - 不主动覆盖已有 `canonical_key / normalized_value`
  - 不重写已有稳定语义，只补缺失字段和少量明确错误字段
  - 迁移操作会写独立 ops 日志，便于审计
- 系统现在同时具备两种 legacy 收敛机制：
  - 在线按需回填：第一次 update 目标 legacy record 时补 metadata
  - 离线批量回填：对现存 memory 库整体治理
- 这一步的目标是进一步减少运行时 fallback，而不是一上来做激进重写。

实现注记（2026-04-27，Canonical-Aware Retrieval V1 已落地）：

- 读取链路现在开始显式消费结构化 metadata。
- 当前策略：
  - 对 query 做轻量 canonical intent 识别
  - 若 query 能映射到 `canonical_key + normalized_value`，则 exact canonical match 优先
  - 若 query 呈现明确 name intent（如 `你叫什么名字`），则 `preferred_name` record 优先于普通文本命中
- 这一版仍是“rerank”，不是彻底改写成 lane-based retrieval：
  - 先保留既有文本召回
  - 再用 canonical metadata 做优先级提升
- 同期还修正了一处分类边界问题：
  - `这个项目名字叫珍格格` 这类文本不再被错误识别成 `preferred_name`
  - statement-form 的名字规则已收窄到句首/用户语境
- 这一步的作用是先让 `memory_search` 和 runtime 的 `Relevant memories` 对长期偏好更敏感，减少“普通文本命中把关键偏好压后”的情况。

### 7.4 reinforce：强化

当同一 `canonical_key` 再次被确认时：

- 增加 `evidence_count`
- 提升 `stability`
- 提升 `activation`
- 更新 `last_confirmed_at`

### 7.5 decay：衰减

当一条 memory 长时间未被触发或确认时：

- `activation` 下降
- 长期不使用则进入 `expired`
- 不是直接物理删除，而是降低召回优先级

### 7.6 contradiction：冲突覆盖

当新证据与旧 memory 冲突时：

- 新证据若权威更高，则旧记录变 `contradicted`
- 新记录接管同一 `canonical_key`
- 保留审计链，不建议直接硬删

权威优先级建议：

- `explicit_user`
- `user_feedback`
- `tool_verified`
- `repeated_behavior`
- `assistant_inferred`

### 7.7 suppression：显式停用

当用户说“不要再按这个记”“不是这个意思”时：

- 对应 memory 进入 `suppressed`
- 默认不再参与检索

## 8. 检索策略重构

### 8.1 总原则

检索不再是“每轮统一 query memory”，而是“按问题类型检索合适的 memory lane”。

### 8.2 检索分流

建议分成如下检索 lane：

- `state_agent retrieval`
- `state_shared retrieval`
- `preference retrieval`
- `fact retrieval`
- `interaction retrieval`
- `feedback retrieval`

示例：

- 问“以后怎么称呼我” -> `preference retrieval`
- 问“用户通常喜欢什么回答方式” -> `interaction retrieval`
- 问“我这个 agent 当前做到哪一步” -> `state_agent retrieval`
- 问“协作流程现在推进到哪一步” -> `state_shared retrieval`

### 8.3 prompt 注入规则

默认不应把所有记忆直接拼到 prompt 中。

建议：

1. 先确定当前问题是否需要 memory。
2. 只注入对应 lane 的 top items。
3. `candidate / contradicted / expired / suppressed` 默认不注入。
4. `state` 单独作为一个上下文块，不与 memory 混排。

### 8.4 排序策略

建议排序不只看文本匹配，还要看：

- `activation`
- `stability`
- `source_kind`
- `last_confirmed_at`
- `query relevance`

最终排序可以是：

`score = relevance + activation + stability + source_weight`

## 9. 工具接口调整建议

### 9.1 当前问题

当前 `memory_write(content, tags=[])` 太宽。

问题：

- 调用方只需给一句文本
- tags 决定过多语义
- 没有 admission

### 9.2 建议的未来工具形态

不建议长期保留一个完全开放的 `memory_write`。

建议逐步演进为：

- `memory_capture_preference(...)`
- `memory_capture_feedback(...)`
- `memory_capture_fact(...)`
- `memory_forget(...)`
- `memory_correct(...)`

兼容阶段可保留 `memory_write`，但内部必须走 admission policy。

### 9.3 state 工具独立

建议将当前任务相关内容改由 state 工具维护，例如：

- `state_set_goal(...)`
- `state_append_note(...)`
- `state_update_plan(...)`
- `state_clear(...)`

对于多 agent 协作，建议额外提供：

- `state_publish_shared(...)`
- `state_read_shared(...)`
- `state_revoke_shared(...)`

## 10. 对现有代码的改造建议

### 10.1 `app/runtime/memory_manager.py`

现状职责过大，建议拆分为：

- `StateManager`
- `MemoryManager`
- `MemoryAdmissionPolicy`
- `MemoryConflictResolver`

### 10.2 `app/memory/intake.py`

现状主要做 tags 推断。

建议改为：

- 候选提取
- candidate 标准化
- `canonical_key` 生成
- `source_kind` 推断
- admission 调用

### 10.3 `app/memory/consolidation.py`

现状主要做：

- short -> long 晋升
- long -> shared 晋升

建议改为：

- candidate -> active
- reinforce
- contradict
- suppress
- decay

### 10.4 `app/runtime/context_assembler.py`

建议改为两条链路：

- `assemble_state_context(...)`
- `assemble_memory_context(...)`

并在上层按 query 意图决定是否调用。

### 10.5 `app/tools/builtins.py`

建议：

- 缩减开放式 `memory_write`
- 增加更窄的 memory/state 工具
- `memory_update` 从全文搜索改为 key-based 优先，文本搜索兜底
  - 实现状态：Canonical Match V1 已落地

### 10.6 `app/config/agent_capabilities.json`

建议增加独立权限：

- `state_read_scopes`
- `state_write_scopes`
- `state_publish_scopes`
- `memory_read_kinds`
- `memory_write_kinds`

并收紧当前：

- 不再默认允许 `short` 跨会话读取
- 不允许 agent 直接读取其他 agent 的私有 state
- 不允许 agent 直接读取其他 agent 的私有 long memory，除非显式共享

## 11. 存储与迁移方案

### 11.1 目录建议

当前目录：

- `memory_v2/agents/...`
- `memory_v2/shared/...`

建议未来拆成：

```text
data/
└── cognition/
    ├── state/
    │   ├── agents/{agent_id}/sessions/{session_id}.jsonl
    │   └── shared/sessions/{session_id}.jsonl
    └── memory/
        ├── agents/{agent_id}/long.jsonl
        └── shared/long.jsonl
```

兼容阶段可以先不改磁盘结构，只改逻辑语义。

### 11.2 旧数据迁移原则

旧的 `agent_short` 不自动当成 memory。

迁移策略建议：

1. `agent_short` 默认迁移到 `state archive`，不直接进入长期 memory。
2. `agent_long` 中只有符合新 memory 定义的记录才保留，并迁入 `memory_agent_long`。
3. `shared_long` 中系统 policy 类内容迁出到静态规则层，不继续当动态 memory。
4. 无法判定的旧记录进入 `legacy_candidate`，不默认参与召回。

## 12. 分阶段实施计划

### Phase 0：冻结边界

目标：

- 明确 `AGENT.md` / `SOUL.md` / `state` / `memory` 四层定义
- 明确哪些内容永远不进 memory

产出：

- 本设计文档
- 新的分类词表和准入规则

### Phase 1：先拆 `state`

目标：

- 将现有 `agent_short` 逻辑上迁移为 `state`
- 关闭跨会话 short 默认召回
- 增加 `state_shared_session` 的显式发布路径

产出：

- `StateManager`
- `state_agent retrieval`
- `state_shared retrieval`

### Phase 2：加入 admission policy

目标：

- 所有 memory 写入必须经过 admission
- 非长期经验直接拒绝或路由到 state

产出：

- `MemoryAdmissionPolicy`
- admission 单元测试

### Phase 3：结构化 memory schema

目标：

- 从 `tags-driven` 改为 `schema-driven`
- 增加 `kind / canonical_key / status / source_kind`

产出：

- 新 record schema
- 新 merge 逻辑

### Phase 4：动态机制

目标：
 
- 引入 reinforce / decay / contradiction / suppression

产出：

- 动态激活分
- 生命周期测试

### Phase 5：检索重构

目标：

- 检索按 lane 走
- memory 不再默认全量注入 prompt

产出：

- lane-based retrieval
- 新的 `ContextAssembler`

## 13. 测试策略

建议新增以下测试集合：

### 13.1 admission tests

- 一次性任务信息不会进入 memory
- 用户显式偏好可进入 memory
- 当前计划会被路由到 state

### 13.2 lifecycle tests

- 同一偏好重复出现会强化
- 长期未触发会衰减
- 新偏好可覆盖旧偏好
- 用户显式否认后旧记录被 suppressed

### 13.3 retrieval tests

- 查询称呼时只召回 `user_preference`
- 查询当前任务时只召回对应 agent 的 `state_agent_session`
- 查询协作状态时只召回 `state_shared_session`
- `contradicted` 记录不会默认注入 prompt

### 13.4 migration tests

- 旧 `agent_short` 不会被误当长期 memory
- 旧 `shared_long` 中的 policy 能正确迁出

## 14. 成功标准

重构完成后，应满足以下标准：

1. runtime 不再把所有“可复用文本”都视为 memory。
2. `AGENT.md`、`SOUL.md`、`state`、`memory` 的职责边界清晰。
3. 当前任务状态不会污染长期 memory。
4. 长期 memory 可以被强化、衰减、修正、停用。
5. prompt 中的 memory 注入显著更少，但更准。
6. memory 的每一次写入都能回答“为什么值得长期保留”。
7. 多 agent 场景下，私有 state 和私有 long memory 默认隔离，只有显式共享的数据能跨 agent 可见。

## 15. 最终结论

下一阶段的重点不应是继续增强“memory 能存什么”，而应是先严格回答下面两个问题：

1. 什么不是 memory？
2. 什么样的经验，值得被长期记住？

本方案的最终方向是：

- `AGENT.md` 负责行为宪法
- `SOUL.md` 负责身份人格
- `state` 负责当前任务工作台，并且默认按 agent 隔离
- `memory` 只负责长期互动经验

只有先完成这个边界收敛，后续再做 embedding、向量检索、复杂召回、跨 agent 共享，才不会继续放大概念混乱的问题。
