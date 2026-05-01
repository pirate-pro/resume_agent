"""Constants used by context assembly."""

from __future__ import annotations

from app.memory.policies import MemoryLane

ACTIVE_FILE_MAX_COUNT = 12
AGENT_STATE_MAX_COUNT = 8
ORCHESTRATION_STATE_MAX_COUNT = 8
RECENT_EVENT_MAX_COUNT = 12
AGENT_TASK_CONTEXT_MAX_COUNT = 8
CHILD_RESULT_CONTEXT_MAX_COUNT = 8

MEMORY_LANE_LABELS = {
    MemoryLane.IDENTITY.value: "Identity",
    MemoryLane.RESPONSE_PREFERENCES.value: "Response preferences",
    MemoryLane.INTERACTION_FEEDBACK.value: "Interaction feedback",
    MemoryLane.USER_PROFILE.value: "User profile",
    MemoryLane.OTHER_MEMORIES.value: "Other relevant memory",
}

MEMORY_SCOPE_LABELS = {
    "shared_long": "Shared",
    "agent_long": "Agent overlay",
    "agent_short": "Agent short",
    "shared": "Shared",
    "agent": "Agent overlay",
    "unknown": "Unknown scope",
}

OUTPUT_FORMAT_RULES = """Answer output rules:
1. Answer directly and keep the structure no heavier than the task needs.
2. Use Markdown naturally; do not wrap an entire Markdown document in a fenced block unless the user asks for source.
3. Use fenced code blocks with language labels for code.
4. If a file was created or read and the user asks for content, include the actual content or the exact file path.
5. Use tables only when rows/columns make comparison clearer.
6. Use emphasis sparingly; never bold whole paragraphs.
7. If information is missing, say what is unknown instead of inventing details."""

MEMORY_ACCESS_RULES = """Memory access rules:
1. Treat session events and state as short-term working context, not durable memory.
2. Use shared memory for cross-agent stable context and the current agent overlay for agent-specific observations.
3. Do not assume private memory from other agents is visible unless the runtime provides it.
4. Prefer high-confidence facts and long-term summaries over mid-term notes when they conflict.
5. If a relevant long-term fact is already included in this context, answer from it directly; do not call memory_search just to verify it."""
