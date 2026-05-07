# Multi-Agent Artifact-First 资料系统设计

## 1. 目标

本设计用于解决 multi-agent 协作中的共享资料、私有工作台和上下文注入边界问题。

核心目标：

- `artifact` 是 session 共享资料的唯一事实源。
- `workspace` 只做 agent 私有中间产物，不再被当作跨 agent 共享资料。
- `child-agent` 只能通过受控 `artifact_id` 读取共享资料，不能读取 main-agent 的 workspace path。
- 当前轮用户刚提供的资料是高优先级上下文，不能因为普通检索或截断策略被静默丢失。
- 如果高优先级资料放不进上下文，先触发 flush + compact，再重新组装；仍放不下则明确失败。

## 2. 硬切原则

这次不做历史结构兼容。

硬规则：

- 废弃 `files.json` 作为 session 资料主存储。
- 废弃 `SessionArtifact` 作为领域模型主概念。
- 不再把上传文件放进 `workspace/uploads`。
- 不再把解析文本放进 `workspace/.parsed`。
- 不再允许 `artifact_refs` 传裸文件名、相对路径或 workspace path。
- 旧数据可以清空重建，不做自动迁移兜底。

外部 API、DTO、前端状态也不保留旧命名，统一使用 artifact 语义。

## 3. 核心边界

### 3.1 Artifact

`artifact` 表示 session 级共享资料。

适合保存：

- 用户上传文件。
- 用户粘贴的长文本材料。
- agent 显式发布给其他 agent 使用的产物。
- 用户可下载或预览的最终交付物。

不保存：

- agent 私有草稿。
- 临时推理片段。
- memory。
- state。
- raw event log。

### 3.2 Workspace

`workspace` 表示 agent 私有工作台。

适合保存：

- 当前 agent 的草稿。
- 中间 JSON、表格、分析片段。
- 尚未发布的报告候选稿。

不适合保存：

- 上传文件唯一副本。
- child-agent 可直接读取的资料。
- 长期 memory。
- session state。

workspace 文件只有显式 `publish_artifact` 后，才会进入 artifact 层。

### 3.3 Events

`events.jsonl` 是短期原始事件流。

事件是 memory 和 mid-term 的来源，但不是 memory 本体，也不是 artifact。

## 4. 数据结构

目标目录：

```text
data/sessions/<session_id>/
  metadata.json
  events.jsonl
  artifacts.json
  artifacts/
    artifact_xxx/
      original.bin
      content.txt
      metadata.json
  workspaces/
    agent_main/
      draft.md
    resume_agent/
      notes.json
```

`artifacts.json` 是索引，`artifacts/<artifact_id>/` 是内容目录。

## 5. Artifact Schema

领域模型：

```json
{
  "artifact_id": "artifact_xxx",
  "session_id": "sess_xxx",
  "kind": "uploaded_file | pasted_text | generated_file | answer_file",
  "title": "候选人简历",
  "description": "用户上传的简历原文",
  "media_type": "text/plain",
  "size_bytes": 12000,
  "token_estimate": 3200,
  "visibility": "session_shared | agent_private | user_visible",
  "owner_agent_id": "agent_main",
  "source": {
    "type": "upload | user_message | workspace_publish | generated_answer",
    "event_id": "evt_xxx",
    "workspace_path": null
  },
  "status": "ready | parsing | failed",
  "created_at": "2026-05-06T00:00:00Z",
  "updated_at": "2026-05-06T00:00:00Z",
  "storage_relpath": "artifacts/artifact_xxx/original.bin",
  "text_relpath": "artifacts/artifact_xxx/content.txt",
  "metadata_relpath": "artifacts/artifact_xxx/metadata.json"
}
```

第一版必须具备：

- `artifact_id`
- `session_id`
- `kind`
- `title`
- `media_type`
- `size_bytes`
- `token_estimate`
- `visibility`
- `owner_agent_id`
- `status`
- `storage_relpath`
- `text_relpath`
- `created_at`
- `updated_at`

## 6. 上传与写入策略

上传文件流程：

```text
receive upload
  -> 校验文件大小和可解析类型
  -> 提取文本
  -> 估算 token
  -> 如果明显超过单模型可接受上限，拒绝上传
  -> 写入 artifacts/<artifact_id>/
  -> 更新 artifacts.json
```

关键规则：

- 上传阶段可以拒绝超大资料。
- 不能在上下文组装阶段悄悄截断刚上传的关键资料。
- 对于普通大文件，后续可以加 chunk/index；第一版先保证不失真。

## 7. 上下文优先级

上下文组装按优先级处理：

```text
P0 AGENT.md / SOUL.md / runtime hard rules
P1 当前用户消息
P2 当前任务显式依赖的 required artifacts
P3 当前 agent state / assigned task
P4 当前 agent recent events
P5 always-inject long-term memory
P6 query-retrieved facts / mid-term notes
P7 skill catalog / tool catalog
```

解释：

- P0-P3 是任务正确性的基础，不能被低优先级内容挤掉。
- P2 中的 required artifacts 是本轮任务输入，不是普通检索结果。
- P6 是可召回补充，不应该覆盖当前轮用户刚给的材料。
- P7 可以渐进式披露，必要时只注入 name + description。

## 8. Context Budget 预检

上下文组装前必须做预算预检。

流程：

```text
assemble_context(candidate)
  -> estimate_tokens
  -> if under budget: return context
  -> if over budget:
       trigger mid-term flush job for already accumulated events
       trigger context compaction for compressible recent events
       reassemble_context
  -> if still over budget:
       fail fast with explicit error
```

注意：

- flush 和 compact 可以并行，不要求 flush 完成后才能 compact。
- flush 只要把待处理 events 纳入 job，就不会失帧。
- compact 必须保证 tool_call/tool_result 成对压缩或成对保留。
- 如果 P2 required artifact 本身过大，应该在上传或 artifact 绑定阶段拒绝，而不是注入时截断。

## 9. Multi-Agent 资料传递

main-agent 委派 child-agent 时：

```text
delegate_agents(
  tasks=[
    {
      "agent_id": "resume_agent",
      "instruction": "...",
      "artifact_refs": ["artifact_resume_001"]
    }
  ]
)
```

规则：

- `artifact_refs` 必须存在于当前 session 的 artifact registry。
- `artifact_refs` 必须对目标 agent 可见。
- child-agent 上下文中，assigned task 和 required artifacts 属于高优先级 P2/P3。
- child-agent 不注入 main-agent 的 session 总体 state。
- main-agent 可以读取 child-agent 的任务结果、进度和必要状态摘要。

## 10. Workspace 发布

workspace 写入：

```text
workspace_write_file(path="draft.md")
  -> data/sessions/<session_id>/workspaces/<agent_id>/draft.md
```

发布为 artifact：

```text
publish_artifact(path="draft.md", title="匹配报告草稿")
  -> artifacts/artifact_xxx/
  -> visibility=session_shared
```

清理规则：

- 未发布 workspace 文件可以按 TTL 清理。
- 已发布 artifact 不依赖 workspace 原路径。
- answer artifact 面向用户展示，不自动等价于 session_shared，除非显式发布。

## 11. 工具设计

第一版工具：

```text
session_list_artifacts
session_read_artifact
session_search_artifact
publish_artifact
workspace_write_file
workspace_read_file
```

旧工具处理原则：

- 旧 session file 工具不再注册、不再暴露给 agent。
- 前端 HTTP 路由统一使用 `/artifacts`。

## 12. Memory 与 Artifact 的关系

artifact 不是 memory。

关系：

```text
artifact
  当前 session 的共享资料实体

events
  使用 artifact、讨论 artifact、分析 artifact 的过程记录

mid-term
  从 events 中抽取出的阶段性自然语言摘要

long-term
  从 events/mid-term 中提炼出的稳定用户画像、偏好、背景、事实
```

memory 可以引用 artifact id，但不能把大段 artifact 原文直接塞进 long-term。

## 13. 实施顺序

### Phase 1: Artifact 存储主链路

- 新增 `SessionArtifact` 领域模型。
- 新增 repository 方法：写入、读取、列表、active artifact。
- `create_session` 创建 `artifacts.json` 和 `artifacts/`。
- 上传服务改为写 artifact，不再写 `files.json/workspace/uploads`。

### Phase 2: 工具切换

- 新增 artifact 工具。
- child-agent 能力配置暴露 artifact 工具。
- 旧 file 工具从 agent 能力和工具注册中移除。

### Phase 3: ContextAssembler 接入

- active artifacts 替代 active artifacts。
- required artifacts 按 P2 注入。
- 添加 context budget 预检。
- over budget 时触发 flush + compact，然后重组。

### Phase 4: Workspace 私有化

- workspace 路径改为 `workspaces/<agent_id>/`。
- 移除跨目录 fallback。
- 新增 `publish_artifact`。

### Phase 5: 清理旧结构

- 删除 `files.json` 写入逻辑。
- 清理旧 prompt 中的 file-first 表述。
- 清理测试中的旧 file 主链路假设。
- 删除 `SessionArtifact` 外部 DTO 过渡层。

## 14. 当前验收标准

第一轮实现完成后，必须满足：

- 新 session 不创建 `files.json`。
- 上传文件只进入 `artifacts.json/artifacts/`。
- agent 不能把 workspace path 作为 `artifact_refs` 传给 child-agent。
- child-agent 可以读取被授权 artifact。
- ContextAssembler 能看到 active artifacts，而不是 active artifacts。
- 旧压力测试不能因为历史 file 逻辑通过，必须验证 artifact 主链路。
