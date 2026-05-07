# AgentTask System Design

Date: 2026-05-07

## 1. Goal

AgentTask is the task coordination layer for multi-agent collaboration.

It should make child-agent delegation observable, durable, and queryable without replacing the existing runtime, memory, event, artifact, or state systems.

The first version focuses on a stable task protocol:

- main-agent can create a task group.
- each child task has a durable lifecycle.
- main-agent can inspect task progress and results.
- child-agent raw events remain physically isolated.
- session orchestration events remain a lightweight audit timeline.

LangGraph can be introduced later as an optional orchestrator on top of this protocol, not as the source of task truth.

## 2. Current Problem

The current implementation has a useful execution skeleton but weak task persistence:

- `AgentTaskRuntime` executes child-agent tasks concurrently.
- `InMemoryAgentTaskStore` stores task status only in process memory.
- `delegate_agents(wait=true)` returns aggregated results, but there is no durable task history.
- If later `wait=false`, status polling, retry, resume, or LangGraph orchestration is added, the current in-memory store is not enough.

This creates a boundary problem:

- events are audit logs.
- agent events are raw execution history.
- memory is durable knowledge.
- state is current working context.
- AgentTask should be the durable task lifecycle source.

## 3. Non-Goals

The first version will not implement:

- LangGraph integration.
- distributed queue.
- background `wait=false`.
- cancellation.
- retry policy.
- dependency DAG.
- task leasing across processes.
- task result vector indexing.

These can be added after the durable task protocol is stable.

## 4. Storage Layout

Agent tasks are session-scoped coordination data.

They live under the session directory, separate from session events and agent private event logs.

```text
data/sessions/<session_id>/
  events.jsonl
  agents/
    <agent_id>/
      events.jsonl
  agent_tasks/
    task_groups.jsonl
    tasks.jsonl
  artifacts.json
  workspaces/
    <agent_id>/
```

Rationale:

- task data belongs to the session where delegation happens.
- task data is not memory.
- task data is not raw agent events.
- task data should be readable without scanning event logs.

## 5. Domain Model

### 5.1 AgentTaskGroupRecord

```json
{
  "task_group_id": "task_group_xxx",
  "session_id": "sess_xxx",
  "source_agent_id": "agent_main",
  "source_run_id": "run_main",
  "status": "running",
  "max_concurrency": 3,
  "task_ids": ["task_xxx", "task_yyy"],
  "created_at": "2026-05-07T00:00:00Z",
  "updated_at": "2026-05-07T00:00:00Z"
}
```

### 5.2 AgentTaskRecord

```json
{
  "task_id": "task_xxx",
  "task_group_id": "task_group_xxx",
  "session_id": "sess_xxx",
  "source_agent_id": "agent_main",
  "source_run_id": "run_main",
  "target_agent_id": "resume_agent",
  "instruction": "Extract resume highlights.",
  "constraints": [],
  "artifact_refs": [],
  "skill_names": ["base", "tools", "file-reader"],
  "max_tool_rounds": 2,
  "status": "queued",
  "child_run_id": null,
  "summary": null,
  "answer": null,
  "error": null,
  "created_at": "2026-05-07T00:00:00Z",
  "started_at": null,
  "completed_at": null,
  "updated_at": "2026-05-07T00:00:00Z"
}
```

## 6. Status Model

### 6.1 Task Status

```text
queued -> running -> completed
queued -> running -> failed
queued -> cancelled
running -> cancelled
```

`cancelled` is reserved in the schema, but the first implementation does not need to expose cancellation.

### 6.2 Group Status

```text
queued
running
completed
partial_failed
failed
cancelled
```

Rules:

- `queued`: tasks are created but none has started.
- `running`: at least one task is running or queued.
- `completed`: all tasks completed.
- `partial_failed`: at least one task failed and at least one completed.
- `failed`: all tasks failed.
- `cancelled`: all tasks cancelled, or cancellation is explicitly applied later.

## 7. Store Interface

AgentTaskStore should be independent from `SessionRepository`.

`SessionRepository` already handles session metadata, event logs, artifact registry, and workspace paths. Adding task lifecycle to it would make it too broad.

```python
class AgentTaskStore(Protocol):
    def create_group(
        self,
        *,
        session_id: str,
        source_agent_id: str,
        source_run_id: str,
        max_concurrency: int,
        specs: list[AgentTaskSpec],
    ) -> AgentTaskGroupRecord: ...

    def get_group(self, session_id: str, task_group_id: str) -> AgentTaskGroupRecord | None: ...

    def list_group_tasks(self, session_id: str, task_group_id: str) -> list[AgentTaskRecord]: ...

    def get_task(self, session_id: str, task_id: str) -> AgentTaskRecord | None: ...

    def mark_running(self, session_id: str, task_id: str, *, child_run_id: str) -> AgentTaskRecord: ...

    def mark_completed(
        self,
        session_id: str,
        task_id: str,
        *,
        summary: str,
        answer: str,
        artifact_refs: list[str],
    ) -> AgentTaskRecord: ...

    def mark_failed(self, session_id: str, task_id: str, *, error: str) -> AgentTaskRecord: ...
```

Implementation:

```text
app/domain/agent_tasks.py
app/domain/agent_task_protocols.py
app/infra/storage/jsonl_agent_task_store.py
```

## 8. Runtime Integration

Current flow:

```text
delegate_agents tool
  -> AgentTaskRuntime.run_group
  -> InMemoryAgentTaskStore.create_group
  -> concurrent AgentInvocationService.invoke
  -> aggregate result
```

Target flow:

```text
delegate_agents tool
  -> AgentTaskRuntime.run_group
  -> AgentTaskStore.create_group
  -> each task: mark_running(child_run_id)
  -> AgentInvocationService.invoke
  -> each task: mark_completed / mark_failed
  -> group status derived from task statuses
  -> aggregate result returned to main-agent
```

Important boundary:

- `AgentTaskRuntime` owns task lifecycle updates.
- `AgentInvocationService` owns one child-agent run.
- `EventRecorder` owns audit events.
- `JsonlSessionRepository` owns event storage.

`AgentInvocationService` should not become the task store writer. It should return execution output and let `AgentTaskRuntime` update task status.

## 9. Event Relationship

AgentTaskStore is the lifecycle source of truth.

Events are an audit trail.

Expected event writes:

```text
agent_task_assigned
  -> written to source agent private event log
  -> written to session orchestration log

agent_result_summary
  -> written to child agent private event log
  -> written to session orchestration log
```

Expected task writes:

```text
task queued
task running
task completed / failed
group status derived from tasks
```

The two systems must not replace each other.

## 10. Tooling

### 10.1 delegate_agents

Keep the existing main-agent entrypoint.

First version keeps `wait=true` as the only supported mode.

The response should include:

```json
{
  "task_group_id": "task_group_xxx",
  "status": "completed",
  "max_concurrency": 2,
  "results": []
}
```

### 10.2 agent_task_status

Add a read-only status tool.

Input:

```json
{
  "task_group_id": "task_group_xxx"
}
```

Output:

```json
{
  "task_group_id": "task_group_xxx",
  "status": "completed",
  "tasks": [
    {
      "task_id": "task_xxx",
      "target_agent_id": "resume_agent",
      "status": "completed",
      "summary": "Done.",
      "child_run_id": "run_xxx",
      "artifact_refs": [],
      "error": null
    }
  ]
}
```

Access rule:

- first version only exposes this tool to main-agent.
- child-agent should not inspect sibling task groups by default.

## 11. Context Injection

Do not inject all task history by default.

Main-agent context can receive a compact task status section only when relevant:

- current `delegate_agents` call returns immediate results.
- future `wait=false` can inject active task group status.

Child-agent context should receive only:

- assigned task instruction.
- constraints.
- allowed artifact refs.
- own state/events/memory.

Child-agent should not receive sibling task group state.

## 12. Testing Plan

Required tests:

- store creates task group and task records on disk.
- store reloads task group and task records after re-instantiation.
- `mark_running` stores `child_run_id` and timestamps.
- `mark_completed` stores summary, answer, artifact refs, and group status becomes `completed`.
- one failed and one completed task makes group status `partial_failed`.
- all failed tasks make group status `failed`.
- `AgentTaskRuntime` still runs independent child tasks concurrently.
- `delegate_agents` response remains compatible with current main-agent usage.
- `agent_task_status` returns durable status after runtime completion.
- task status writes do not pollute agent private event logs.
- child-agent raw events remain under `agents/<agent_id>/events.jsonl`.
- session orchestration log contains only task assignment and result summary events.

## 13. Implementation Order

1. Add domain records and store protocol.
2. Add JSONL task store.
3. Replace `InMemoryAgentTaskStore` with the new store in `AgentTaskRuntime`.
4. Keep `delegate_agents(wait=true)` behavior unchanged.
5. Add `agent_task_status` read-only tool.
6. Add tests for persistence, runtime, tool output, event isolation.
7. Run full tests and pressure tests.

## 14. Future LangGraph Integration

LangGraph can later become an implementation of a higher-level orchestrator:

```text
AgentOrchestrator
  InternalAgentOrchestrator
  LangGraphAgentOrchestrator
```

LangGraph nodes should call the existing task protocol:

```text
plan_node
dispatch_node -> AgentTaskRuntime
join_node -> AgentTaskStore
synthesize_node -> main-agent runtime
```

LangGraph checkpoint should be execution recovery metadata only.

It should not replace:

- AgentTaskStore
- EventRecorder
- MemoryManager
- SessionArtifact registry
- per-agent event logs

