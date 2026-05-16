# M23 RAG / MCP 检索架构设计草案

## 1. 当前结论

RAG 不应该被设计成新的事实源，也不应该把笔记、中期记忆或外部资料“迁移”进去。

更准确的定位是：

```text
Note / Knowledge / Memory / Artifact / Career / Learning = 事实源
RAG Index = 可删除、可重建、可过期的检索投影
RetrievalService = Agent 使用的统一召回入口
```

也就是说，后台任务做的是“索引投影”，不是“数据迁移”。

## 2. 核心目标

M23 的 RAG 目标不是一上来追求复杂向量库，而是先让系统具备稳定的资料召回能力：

- 用户不用手动引用笔记、资料、面经或记忆 ID。
- 系统能从笔记、外部资料、上传资料和中期记忆摘要里找到相关内容。
- 召回结果必须能追溯回原始事实源。
- RAG 索引可以重建，损坏或过期时不影响原始产品数据。
- 后续可以自然抽成 MCP 服务，但当前不先做 MCP server。

## 3. 事实源分层

### 3.1 Note

`Note` 是用户自己的知识资产。

适合进入 Note 的内容：

- 用户自己的面试复盘。
- 用户自己的学习笔记。
- 用户整理的答案草稿。
- 用户自己的项目总结。
- 用户随手记录的想法、杂事、经验。

Note 可以被 RAG 索引，但 Note 不等于 memory，也不应该自动写入 memory。

### 3.2 Knowledge

`Knowledge` 是外部资料和题库资产。

适合进入 Knowledge 的内容：

- 平台预设的面经。
- 平台预设的面试题。
- 外部学习资料链接。
- 公开文章、课程、仓库、书籍。
- 用户上传但明确作为“外部资料 / 题库 / 面经库”管理的内容。

用户上传的资料不应该直接跳进 RAG。建议路径是：

```text
上传文件 / 粘贴文本
-> SessionArtifact
-> 结构化识别和规范校验
-> 用户确认归类
-> Knowledge 或 Note
-> RAG Index
```

### 3.3 SessionArtifact

`SessionArtifact` 是上传文件和生成文件的文件事实源。

它可以有两种索引用法：

- 临时会话索引：只在当前会话内检索，不沉淀为长期知识。
- 持久资料入口：用户确认后转成 Note 或 Knowledge，再进入长期 RAG。

第一阶段建议优先做持久资料入口，不急着做大规模临时索引。

### 3.4 MidTermMemory

中期记忆不应该被迁移到 Note 或 Knowledge。

中期记忆更适合这样进入 RAG：

```text
会话事件
-> flush / compaction
-> 中期摘要单元
-> MidTermMemory 事实源
-> RAG Index 投影
```

索引时只索引摘要单元，不索引完整原始对话。

每条中期记忆索引必须带：

- `session_id`
- `agent_id`
- `time_range`
- `scope`
- `sensitivity`
- `confidence`
- `source_event_refs`

召回中期记忆时要比 Note / Knowledge 更谨慎。默认只在用户意图明显需要“我之前说过什么 / 我最近做过什么 / 我的历史上下文”时提高权重。

### 3.5 LongTermMemory

长期记忆仍然走 memory 管线。

长期记忆适合保存：

- 长期偏好。
- 稳定目标。
- 稳定事实。
- 用户明确要求“记住”的内容。

长期记忆可以后续加 RAG 投影，但第一阶段没有必要替代现有 `memory_search`。更稳的方式是 RetrievalService 做多路融合：

```text
RAG Note / Knowledge / MidTermMemory
+ LongTermMemory 精准召回
+ Career / Learning 规则召回
```

## 4. RAG Index 的定位

RAG Index 是 projection / cache。

它保存的是检索所需的最小信息：

```text
chunk_id
source_type
source_id
source_ref
source_title
source_updated_at
char_start
char_end
text
token_estimate
tags
metadata
content_hash
index_version
status
created_at
updated_at
```

它不能保存完整业务对象，也不能反向覆盖事实源。

用户看到和编辑的永远是原始资产：

```text
命中 chunk
-> 展示来源：笔记 / 外部资料 / 面试题 / 中期摘要
-> 点击后回到 Note / Knowledge / Memory 解释视图
```

chunk id 是系统调试信息，不应该成为普通用户体验重点。

## 5. 外部资料与预设资料库

后续如果要做资料库，建议分两层：

```text
GlobalKnowledgeCatalog
  平台预设资料、面经、题库、学习路径

UserKnowledgeLibrary
  用户选择加入的资料
  用户上传并确认归类的资料
```

用户不是直接修改全局资料，而是把资料“加入自己的资料库”。

这样可以支持：

- 平台预设资料持续更新。
- 用户决定哪些资料与自己相关。
- 用户资料库有独立索引、独立权限、独立学习计划关联。
- 后续做 MCP 时，全局库和用户库可以作为不同 scope 暴露。

## 6. MCP 的接入时机

当前不建议先做 MCP server。

更稳的路线是先把内部能力设计成 MCP 兼容的边界：

```text
rag.ingest(source_ref)
rag.rebuild(source_ref)
rag.archive(source_ref)
rag.search(query, scope, filters)
rag.context_pack(query, scope, budget)
```

阶段划分：

```text
阶段 1：内部 RAG 模块
  app/retrieval 内完成索引、检索和融合

阶段 2：MCP 兼容接口
  内部 service 方法稳定，参数和返回值接近 MCP tool/resource 形态

阶段 3：独立 MCP 服务
  把 RAG 能力拆出去，聊天入口仍通过 RetrievalService 调用
```

这样后续迁移成 MCP 时，不需要重写产品事实源。

## 7. 检索策略

第一阶段建议做 deterministic sparse / lexical search。

原因：

- 技术词、公司名、岗位名、框架名、面试题命中率高。
- 不引入额外模型成本。
- 好测试、好解释、好调试。
- 可以先建立质量评估集。

后续再升级 hybrid search：

```text
sparse keyword
+ embedding vector
+ rerank
+ source-aware fusion
```

但 embedding 不是第一阶段前置条件。

## 8. 多路召回与融合

Agent 不直接操作 RAG Index。

统一入口仍然是：

```text
retrieval_search
retrieval_context_pack
```

内部由 `RetrievalService` 融合：

```text
Career 规则召回
Learning 规则召回
Note RAG
Knowledge RAG
MidTermMemory RAG
LongTermMemory 精准召回
SessionArtifact 当前会话召回
```

融合时需要做：

- source type 权重。
- query term 命中。
- 标题 / 标签命中加权。
- 相关求职项目命中加权。
- 时间衰减。
- 每个 source 的 chunk 数量上限。
- 每类 source 的上下文预算上限。
- 同一 source 多 chunk 去重合并。
- 敏感 source gating。

## 9. 上下文注入规则

不是所有召回都应该进入上下文。

建议按用户意图分 gating：

### 9.1 问资料和面试题

优先：

- Knowledge
- Note
- SessionArtifact

谨慎：

- MidTermMemory
- LongTermMemory

### 9.2 问“我之前说过什么”

优先：

- MidTermMemory
- LongTermMemory
- Note

谨慎：

- Knowledge

### 9.3 问求职项目推进

优先：

- Career
- Learning
- Note
- JobFitReport / JDAnalysis

谨慎：

- 外部 Knowledge
- MidTermMemory

### 9.4 问学习计划

优先：

- Learning
- WeaknessTracker
- Note
- Knowledge
- MidTermMemory 中与学习进度有关的摘要

## 10. 后台索引任务

索引任务应该异步执行，不阻塞产品写入。

触发方式：

```text
Note 创建 / 更新 / 归档
Knowledge 创建 / 更新 / 归档
SessionArtifact 转为持久资料
MidTermMemory flush 成功
手动重建索引
定时全量校验
```

失败处理：

- 写入事实源成功不依赖索引成功。
- 索引失败记录 job error。
- 支持 retry。
- 支持按 source 重建。
- 支持全量 rebuild。
- 检索时发现 index stale，可以降级到规则召回或提示调试告警。

## 11. 权限与作用域

每个 chunk 至少需要：

```text
owner_user_id
workspace_id
source_type
source_id
scope
sensitivity
status
```

当前单用户阶段可以先不做复杂权限系统，但模型字段和接口边界要预留。

推荐 scope：

```text
global_catalog
user_library
user_private
session_only
memory_private
```

中期记忆默认是 `memory_private`，不和外部资料混排展示。

## 12. 笔记和中期记忆的关系

笔记和中期记忆都可以帮助系统了解用户，但语义不同：

```text
Note = 用户可见、可编辑、主动沉淀的知识资产
MidTermMemory = 系统从运行历史压缩出的上下文摘要
```

它们可以同时进入 RAG Index，但必须保留 source_type。

不能做：

- 把 Note 自动写成 memory。
- 把 MidTermMemory 自动变成 Note。
- 让 RAG Index 变成第三套笔记库。

可以做：

- Note 被检索召回。
- MidTermMemory 摘要被检索召回。
- RetrievalService 根据意图决定用哪个。
- 用户可以把某条中期摘要手动整理成 Note，但必须是明确动作。

## 13. 成本控制

RAG 会提升召回能力，也可能扩大上下文。

第一阶段必须有预算约束：

- 每次 context pack 有 `max_chars`。
- 每个 source 最多取少量 chunk。
- 每类 source 有预算比例。
- 中期记忆默认只给短摘要。
- 外部资料长文默认只给片段，不整篇塞入 prompt。
- Token 看板继续记录真实消耗，作为后续优化依据。

## 14. 质量评估

RAG 不应该靠感觉验收。

最小评估集应覆盖：

- 用户笔记召回。
- 外部面经召回。
- 面试题召回。
- 中期记忆摘要召回。
- 当前会话 artifact 召回。
- 求职项目相关过滤。
- 不误召回 archived source。
- citations 可追溯。
- max context budget 生效。

示例查询：

```text
RAG chunk 策略怎么回答？
我之前复盘里提到的失败恢复怎么准备？
星河智能二面可能问哪些 Agent Runtime 问题？
最近我学习 RAG 评估有什么进展？
Kafka / RabbitMQ 消息队列经验怎么补？
```

## 15. 推荐开发路线

当前应先进入设计评审，不直接开发。

建议路线：

```text
M23-D1：确认事实源边界和 source_type 设计
M23-D2：确认 Note / Knowledge / Artifact / MidTermMemory 入索引规则
M23-D3：确认检索融合和上下文预算策略
M23-D4：确认质量评估集
M23-D5：再开始实现内部 RAG index
M23-D6：接 RetrievalService 融合
M23-D7：低批次真实链路验证
M23-D8：评估是否抽成 MCP
```

## 16. 当前待讨论问题

1. 中期记忆是否默认参与所有“我的历史上下文”类查询，还是必须更严格 gating？
2. 用户上传面经时，默认归 Note，还是让用户选择 Note / Knowledge？
3. 平台预设资料是否需要全局 catalog 和用户 library 两层？
4. 第一阶段是否只索引 Note / Knowledge，暂缓 MidTermMemory？
5. chunk 是否需要在用户侧可见，还是只展示原始资料和引用片段？
6. MCP 是作为后期外部接口，还是较早独立成服务进程？

## 17. 当前建议

我建议第一阶段先这样定：

- RAG Index 只是 projection。
- Note 和 Knowledge 先入索引。
- MidTermMemory 先设计字段和 gating，第二批再接。
- SessionArtifact 只在用户确认转 Note / Knowledge 后进入长期索引。
- 先做 sparse search，不做 embedding。
- 先通过 RetrievalService 融合，不新增 Agent 工具。
- MCP 只做接口边界预留，不先实现 server。
