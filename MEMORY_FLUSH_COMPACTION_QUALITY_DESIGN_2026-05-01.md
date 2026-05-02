# Memory Flush / Compaction Quality Design

日期：2026-05-01

## 1. 文档目标

本文档用于定义下一阶段 memory 后台维护链路的质量优先方案，重点覆盖：

1. mid-term flush 的 job / cursor / dirty 语义。
2. flush job snapshot 与 context compaction 的关系。
3. daily / facts / long_term 的质量校验。
4. 模型输出缺失关键内容时的 repair 机制。
5. 后续质量评测集与验收标准。

当前阶段的优先级：

```text
质量 > 顺序正确性 > 可追溯性 > 速度
```

flush / compaction 是后台任务，速度可以后续优化；现阶段不能为了速度牺牲事实保真、顺序和 source trace。

---

## 2. 核心结论

### 2.1 同一 stream 只允许一个原子 flush job

`stream` 定义为：

```text
stream_key = session_id + agent_id
```

同一个 stream 内：

```text
1. 同时只能有一个未完成 flush job。
2. 一次 flush 只覆盖一个连续 event range。
3. 一个 flush job 只提交一次 daily / facts / cursor。
4. 失败只重试原 range。
5. 成功后才推进 cursor。
6. active / retry 期间新 events 到来，只标记 dirty，不创建重叠 job。
7. 旧 job 成功后，如果 dirty=true，再从新 cursor 后重新判断是否需要下一轮 flush。
```

不同 stream 之间：

```text
可以并发处理。
后续通过全局 maintenance limiter 控制并发上限。
```

### 2.2 flush job snapshot 是 raw events 的保险箱

过去容易把安全条件理解为：

```text
raw events -> flush 成功 -> compaction
```

修正后应为：

```text
raw events -> flush job snapshot 已持久化 -> compaction 可以并行
```

原因：

```text
只要待压缩 events 已进入 durable flush job，session events 后续即使被 compaction 改写，
flush worker 仍然可以慢慢处理 job 内的 event snapshot，不会丢失原始语义。
```

因此，compaction 不需要等待 flush 写完 daily/facts；它只需要确认待压缩范围已经被 flush job 或 flush cursor 覆盖。

---

## 3. 当前链路目标结构

```text
run_finished
  -> ensure_flush_job_snapshot()
  -> schedule/process_flush_job()
  -> compact_context_if_covered()
```

### 3.1 ensure_flush_job_snapshot

职责：

```text
1. 读取 stream cursor。
2. 读取 cursor 后的新 events。
3. 判断是否达到 flush 条件。
4. 如果达到条件，创建一个 durable flush job。
5. 如果已有未完成 job，只标记 dirty=true。
```

不做：

```text
1. 不调用模型。
2. 不写 daily。
3. 不写 facts。
4. 不推进 cursor。
```

### 3.2 process_flush_job

职责：

```text
1. 对 pending/retry job 调模型。
2. 校验模型输出。
3. 必要时 repair。
4. 写 daily block。
5. 写 candidate facts。
6. 刷新 long_term summary。
7. job 成功后推进 cursor。
8. 如果 job.dirty=true，成功后重新检查 cursor 后的新 events。
```

失败规则：

```text
1. 失败不推进 cursor。
2. 失败不写部分 daily/facts。
3. 失败保留原 event range。
4. 重试仍处理同一个 job snapshot。
```

### 3.3 compact_context_if_covered

职责：

```text
1. 判断 session events 是否达到 compaction 条件。
2. 计算待压缩 event range。
3. 判断待压缩 range 是否已被 flush job snapshot 或 cursor 覆盖。
4. 覆盖后允许 compaction。
5. 生成 context_summary + retained raw events。
```

不要求：

```text
flush job 必须已经 succeeded。
```

必须要求：

```text
待压缩 events 不能只存在于 session events 中而没有进入 flush job snapshot。
```

---

## 4. Flush Job 状态语义

### 4.1 Job 状态

```text
pending
running
retry
deferred
succeeded
```

### 4.2 dirty 字段

`dirty` 表示：

```text
当前 stream 在该 job 未完成期间又出现了新 events，
job 成功后需要重新读取 cursor 后的新 events 并判断是否创建下一轮 job。
```

`dirty` 不表示：

```text
当前 job 的 event range 需要扩大。
当前 job 需要重新从 session events 构建。
```

### 4.3 Cursor 推进规则

```text
1. cursor 只在 job succeeded 后推进。
2. cursor 推进到 job.event_pack.last_event_id。
3. retry / deferred 不推进 cursor。
4. dirty 不影响当前 job 的 cursor 推进。
```

---

## 5. Compaction 覆盖规则

compaction 的核心风险是 raw events 被替换成 summary 后，flush 再也拿不到完整原文。

因此需要定义覆盖判断：

```text
event E is flush-covered if:
  1. E.event_id <= flush_cursor.last_event_id
     或
  2. E.event_id 落在某个未完成 flush job 的 event_pack.events 中
```

待压缩范围必须满足：

```text
all compressed_event_ids are flush-covered
```

如果不满足：

```text
compaction 必须跳过，等待下一轮。
```

这样可以允许：

```text
flush job 正在慢慢处理
compaction 同时压缩已经被 job snapshot 覆盖的 old events
```

同时禁止：

```text
尚未进入任何 flush job 的 raw events 被提前压缩
```

---

## 6. 质量评测集

现有 synthetic case 已覆盖：

```text
1. 名字纠正：小猪 -> 小明。
2. tool_call / tool_result 成对规则。
3. flush 速度 / daily 保真率 / context compaction 目标。
4. rolling.md 开放问题。
5. MEMORY_DEV_PROGRESS.md 文件引用。
6. 最新 tool_result 保留。
```

下一阶段需要扩充以下场景。

### 6.1 用户偏好冲突

```text
用户说叫小猪。
用户后面改成小明。
用户再改成小王。
```

验收：

```text
1. daily 记录纠正过程。
2. facts 只保留 latest active canonical preferred_name。
3. 旧值 archive，不参与检索和 always inject。
```

### 6.2 架构决策推翻

```text
先决定使用 sqlite。
后面明确改为文件系统主存储，sqlite 只做派生 index 或暂不接入。
```

验收：

```text
1. daily 记录决策变更。
2. long-term facts 不保留被推翻方案为 active。
3. source trace 能回溯新旧证据。
```

### 6.3 工具失败与重试

```text
tool_call A 失败。
用户或 agent 修正参数。
tool_call B 成功。
```

验收：

```text
1. progress 保留失败原因和成功结果。
2. 不把失败结果当成最终事实。
3. tool_call/tool_result 仍成对。
```

### 6.4 多 agent 事件混合

```text
main-agent 调度 worker-agent。
worker-agent 有自己的 events。
main-agent 只记录调度和结果摘要。
```

验收：

```text
1. 各 agent flush 默认只处理自己的 events。
2. main-agent daily 不混入 worker-agent 私有 raw events。
3. 后续跨 agent promotion 需要显式规则。
```

### 6.5 超长 tool_result / 文件引用

```text
tool_result 返回超长内容。
系统只应记录摘要和 artifact/file ref。
```

验收：

```text
1. daily 不塞大段原始输出。
2. facts 不写 raw tool output。
3. artifact_refs 可追溯。
```

### 6.6 用户明确禁止记忆

```text
用户说：这只是临时的，不要记住。
用户说：不要把这条写入 memory。
```

验收：

```text
1. 不产生 candidate_long_term。
2. daily 可以记录临时上下文，但不能提升为 facts。
3. validator 能拒绝模型误提取的 long-term candidate。
```

---

## 7. Validator 设计

### 7.1 Mid-Term Summary Validator

必须校验：

```text
1. JSON schema 完整。
2. evidence_event_ids 全部存在于 job.event_pack.events。
3. progress 中 tool_call/tool_result 成对。
4. candidate_long_term 必须有 evidence。
5. candidate_long_term 不能来自 assistant 无证据推测。
6. explicit user correction 必须保留最新值。
7. 禁止把临时任务状态写成 long-term fact。
8. 用户明确禁止记忆时，不允许产生 long-term candidate。
```

### 7.2 Compaction Validator

必须校验：

```text
1. evidence_event_ids 全部属于 compressed_units。
2. context_summary 不引入不存在的人名、技术选型或完成状态。
3. tool_progress 必须保留 call/result 对。
4. open_threads 不能被写成已完成结论。
5. 最新 retained raw events 不应被 summary 覆盖为旧结论。
```

---

## 8. Repair 机制

模型输出不合格时，不应该直接写坏 daily/facts。

第一版 repair 规则：

```text
1. validator 产出 missing_anchors / invalid_items。
2. repair prompt 只发送：
   - 原始 summary
   - 失败原因
   - 必须修复的 anchors
   - 相关 evidence event snippets
3. repair 只允许补齐或删除不合格字段。
4. repair 后再次 validator。
5. repair 失败则 job retry，不写 daily/facts。
```

适合 repair 的问题：

```text
1. 缺少最新名字。
2. 缺少最新 tool_result。
3. evidence id 漏填。
4. candidate_long_term 写了旧值。
```

不适合 repair 的问题：

```text
1. 模型返回无法解析 JSON。
2. 输出大面积幻觉。
3. 关键 evidence 无法定位。
```

这些应进入 retry。

---

## 9. Memory 写入质量规则

### 9.1 canonical 冲突

对于以下类型必须有 canonical key：

```text
preferred_name
stable_user_preference
project_architecture_decision
forbidden_memory
```

写入规则：

```text
1. 新 active fact 与旧 active fact canonical_key 相同且 value 不同：
   - archive 旧 fact。
   - 写入新 fact。
2. 同值重复：
   - 不重复写入，只更新 source/metadata 或跳过。
3. 低置信新值不能覆盖高置信旧值，除非 evidence 是 explicit_user correction。
```

### 9.2 source trace

facts 必须带：

```text
source.type
source.sessionId
source.eventIds
origin
origin_key
flush_job_id
flush_id
evidence_event_ids
```

### 9.3 long_term summary

long_term summary 只从：

```text
active long-term facts
```

生成。

不能从：

```text
daily 流水账
archived facts
agent_short / working state
context_summary
```

直接生成。

---

## 10. 实施顺序

### Phase 1：质量评测集

目标：

```text
先把质量基线变硬。
```

任务：

```text
1. 扩充 scripts/eval_memory_pipeline.py 的 synthetic cases。
2. 把每类 case 的 critical anchors 显式化。
3. 输出每类 case 的 daily/facts/compaction coverage。
4. 加 pytest pressure tests 覆盖关键质量规则。
```

### Phase 2：Validator 增强

目标：

```text
不合格模型输出不能进入 daily/facts。
```

任务：

```text
1. MidTermSummaryValidator 增加 correction / forbidden memory / tool pair / candidate source 校验。
2. Compaction validator 增加 anchor 和 tool pair 校验。
3. Validator 输出结构化错误，供 repair 使用。
```

当前落地状态：

```text
已完成 mid-term flush validator 硬门禁：
- evidence_event_ids 必须存在且属于当前 job event pack
- progress 引用 tool event 时必须 tool_call/tool_result 成对
- candidate_long_term 不允许 assistant-only evidence
- 用户明确禁止记忆时不允许产生对应 long-term candidate
- 同一 pack 内名字纠正后不允许旧名字 candidate
- 临时任务状态/短期状态标签不允许进入 long-term candidate

已完成 compaction validator 硬门禁：
- 顶层 evidence_event_ids 如果提供，必须属于 compressed units
- tool_progress evidence 必须属于 compressed units
- tool_progress 引用 tool event 时必须 tool_call/tool_result 成对
- summary 不允许引入源事件中不存在的关键实体/结论

未完成：
- 结构化 validation issue 对象
- repair prompt / repair model call
```

### Phase 3：Repair

目标：

```text
模型小错可修复，大错重试。
```

任务：

```text
1. 增加 repair prompt。
2. 增加 repair model call。
3. repair 后二次 validate。
4. repair 失败进入 retry。
```

### Phase 4：Memory 写入质量

目标：

```text
facts active 集合保持一致，不被旧值污染。
```

任务：

```text
1. canonical key 分类增强。
2. explicit correction 覆盖规则。
3. archive old active facts。
4. long_term summary 只吃 active facts。
```

### Phase 5：Compaction 覆盖关系

目标：

```text
compaction 与 flush 并行，但不失帧。
```

任务：

```text
1. 实现 flush-covered 判断。
2. compaction 前确认 compressed_event_ids 均已被 cursor 或 flush job snapshot 覆盖。
3. 不再要求 flush job succeeded。
4. 增加测试：flush job retry 时 compaction 仍可压缩已覆盖 old events。
```

当前落地状态：

```text
已完成：
- 新增 CompactionCoverageChecker / CompactionCoverageResult 协议。
- ContextCompactor 在模型压缩前检查 compressed_events 覆盖状态。
- MidTermFlusher 提供基于 flush cursor 与 durable flush job snapshot 的覆盖判断。
- PostRunMaintenance 不再用 flush succeeded 阻塞 compaction；compaction 自己根据 coverage 决定是否跳过。
- flush job retry 时，只要 raw events 已进入 job snapshot，context compaction 可以继续压缩这些 old events。

安全边界：
- 未进入 cursor 或 job snapshot 的 raw event 不会被 compaction 删除。
- 已存在的 context_summary 不要求再次进入 flush job，因为它本身已经是压缩后的短期摘要。
```

---

## 11. 暂不做

以下内容暂不进入本阶段：

```text
1. 向量数据库。
2. SQLite 派生 index。
3. 多 pending range 队列。
4. 动态并发自适应。
5. 自动模型选择。
```

这些都可以后续优化，但当前阶段会增加复杂度，且不能直接提高质量安全边界。
