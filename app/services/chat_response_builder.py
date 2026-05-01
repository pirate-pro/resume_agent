"""Build chat API DTOs from runtime outputs."""

from __future__ import annotations

from app.domain.models import AgentRunOutput
from app.services.answer_normalizer import AnswerArtifact, AnswerNormalizer
from app.schemas.chat import AnswerArtifactView, ChatResponse, MemoryView, ToolCallView

__all__ = ["ChatResponseBuilder"]


class ChatResponseBuilder:
    """Convert runtime output into stable chat response DTOs."""

    def __init__(self, answer_normalizer: AnswerNormalizer | None = None) -> None:
        self._answer_normalizer = answer_normalizer or AnswerNormalizer()

    def build(self, run_output: AgentRunOutput, *, title_pending: bool = False) -> ChatResponse:
        normalized = self._answer_normalizer.normalize_assistant_message(
            run_output.answer,
            tool_calls=run_output.tool_calls,
        )
        return ChatResponse(
            session_id=run_output.session_id,
            answer=normalized.content,
            title_pending=title_pending,
            answer_format=normalized.answer_format,
            render_hint=normalized.render_hint,
            layout_hint=normalized.layout_hint,
            source_kind=normalized.source_kind,
            artifacts=[_artifact_to_view(item) for item in normalized.artifacts],
            tool_calls=[ToolCallView(name=call.name, arguments=call.arguments) for call in run_output.tool_calls],
            memory_hits=[
                MemoryView(memory_id=item.memory_id, content=item.content, tags=item.tags)
                for item in run_output.memory_hits
            ],
        )


def _artifact_to_view(item: AnswerArtifact) -> AnswerArtifactView:
    return AnswerArtifactView(type=item.type, path=item.path, role=item.role)
