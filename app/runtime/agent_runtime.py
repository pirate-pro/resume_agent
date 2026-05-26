"""Single-agent run orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, ToolCall, ToolExecutionResult
from app.domain.protocols import ChatModelClient, ModelResponse, TokenUsage, ToolExecutor
from app.domain.tool_call_protocols import ToolCallLedger
from app.prompts.agent_runtime import FINAL_ANSWER_RECOVERY_PROMPT
from app.runtime.agent import (
    PostRunMaintenanceScheduler,
    ToolContextWindow,
    ToolExecutionRunner,
    ToolGateway,
    build_assistant_tool_call_message,
    build_tool_result_message,
    build_tool_observation,
    compact_tool_result_for_model,
    ensure_tool_call_ids,
    normalize_tool_context_window_mode,
    to_model_tool_schema,
)
from app.runtime.agent.tool_reveal import (
    ToolRevealState,
    hidden_tool_result,
    normalize_always_visible_tool_names,
    normalize_tool_schema_disclosure_mode,
)
from app.runtime.context_assembler import ContextAssembler
from app.runtime.context_compaction.text_utils import estimate_tokens_from_object, estimate_tokens_from_text
from app.runtime.context_compactor import ContextCompactor
from app.runtime.event_channel import EventChannel
from app.runtime.event_recorder import EventRecorder
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.session_manager import SessionManager
from app.runtime.workflow import WorkflowGuardDecision, WorkflowRuntimeGuard
from app.runtime.workflow.tool_plan import (
    is_premature_runtime_plan_answer,
    known_refs_from_successful_tool_result,
    merge_pending_runtime_plan,
    pending_runtime_plan_from_context_bundle,
    pending_runtime_plan_from_successful_tool_result,
    pending_runtime_plan_from_tool_search_result,
    pending_runtime_plan_from_workflow_result,
    runtime_plan_completion_tools,
    runtime_plan_discouraged_tools,
    runtime_plan_next_allowed_tools,
    runtime_plan_notice,
    workflow_incomplete_answer,
)
from app.runtime.workflow.tool_hints import build_required_tool_call_hint
from app.services.answer_normalizer import AnswerNormalizer

__all__ = ["AgentRuntime"]
_logger = logging.getLogger(__name__)
_SCHEMA_SEARCH_TOOL_NAME = "tool_search"
_MAX_SCHEMA_SEARCH_ROUNDS = 3
_MAX_PENDING_SCHEMA_SEARCH_NOTICE_ROUNDS = 2
_MAX_PREMATURE_WORKFLOW_REMINDERS = 2
_MAX_HIDDEN_RUNTIME_TOOL_SUPPRESSIONS_PER_PLAN = 1
_HARD_MODEL_ROUND_FLOOR = 12
_HARD_MODEL_ROUND_MULTIPLIER = 3
_MAX_NO_PROGRESS_OBSERVATIONS = 3
_MAX_REPEATED_NO_PROGRESS_FINGERPRINTS = 2
_MAX_REPEATED_ERROR_SIGNATURES = 2
_MAX_SCHEMA_SEARCH_WITHOUT_NEW_REVEAL = 2
_MAX_SUPPRESSED_REQUIRED_SCHEMA_SEARCH_RETRY_ROUNDS = 1
_STRICT_AUTO_EXECUTE_REQUIRED_TOOLS = {
    "career_application_merge",
    "career_job_fit_report_save",
    "career_resume_version_create",
}
_TEXT_TOOL_INVOCATION_RE = re.compile(r"^\s*<tool_invocation\b[^>]*?/>\s*$", re.IGNORECASE | re.DOTALL)
_TEXT_TOOL_CALL_MARKUP_RE = re.compile(
    r"<\s*/?\s*tool_call\b|<\s*function\s*=|<\s*/\s*function\s*>|<\s*parameter\s*=",
    re.IGNORECASE,
)
_INTERNAL_FINAL_ANSWER_MARKERS = (
    "Tool call limit reached",
    "Tool schema search limit reached",
    "max_tool_rounds",
    "schema search limit",
    "runtime_tool_state",
    "运行时工具状态摘要",
    "完整工具结果见事件日志",
    "workflow_runtime_result",
    "hidden_tool_by_runtime_plan",
    "tool_hidden_by_runtime_plan",
)
_WEAK_FINAL_ANSWER_EXACT = {
    "(no answer)",
    "我无法处理你的请求",
    "我无法处理你的请求。",
    "无法处理你的请求",
    "无法处理你的请求。",
    "抱歉，我无法处理你的请求",
    "抱歉，我无法处理你的请求。",
}
_WEAK_COMPLETED_WORKFLOW_ACTION_PATTERNS = (
    re.compile(r"我将[^。]*(?:读取|调用|创建|生成)", re.IGNORECASE),
    re.compile(r"(?:我)?需要[^。]*(?:委派|调用|读取|创建|生成|保存|合并)", re.IGNORECASE),
    re.compile(r"(?:workflow|工具|守卫)[^。]*(?:限制|无法|不能)[^。]*(?:调用|执行|处理)", re.IGNORECASE),
    re.compile(r"首先(?:读取|调用|创建|生成)", re.IGNORECASE),
    re.compile(r"然后(?:读取|调用|创建|生成)", re.IGNORECASE),
    re.compile(r"现在(?:读取|调用|创建|生成)", re.IGNORECASE),
    re.compile(r"需要先(?:读取|调用|创建|生成|获取)", re.IGNORECASE),
)


@dataclass(slots=True)
class _ToolLoopProgressTracker:
    """Track whether the tool loop is still making durable progress."""

    fingerprint_counts: dict[str, int] = field(default_factory=dict)
    error_signature_counts: dict[str, int] = field(default_factory=dict)
    seen_progress_refs: set[str] = field(default_factory=set)
    consecutive_no_progress_observations: int = 0
    repeated_no_progress_fingerprints: int = 0
    schema_search_without_new_reveal: int = 0
    soft_budget_exceeded: bool = False
    stop_reason: str | None = None

    def mark_soft_budget_exceeded(self, reason: str) -> None:
        self.soft_budget_exceeded = True
        if not self.stop_reason and self.consecutive_no_progress_observations > 0:
            self.stop_reason = reason

    def observe_tool_result(
        self,
        *,
        tool_call: ToolCall,
        result: ToolExecutionResult,
        revealed_before: set[str],
        revealed_after: set[str],
        pending_plan_before: dict[str, Any] | None,
        pending_plan_after: dict[str, Any] | None,
    ) -> bool:
        fingerprint = _tool_call_fingerprint(tool_call)
        previous_count = self.fingerprint_counts.get(fingerprint, 0)
        self.fingerprint_counts[fingerprint] = previous_count + 1

        newly_revealed = revealed_after - revealed_before
        new_refs = _extract_progress_refs(result) - self.seen_progress_refs
        self.seen_progress_refs.update(new_refs)
        plan_progressed = _runtime_plan_progressed(
            before=pending_plan_before,
            after=pending_plan_after,
        )
        generic_first_success = (
            result.success
            and previous_count == 0
            and tool_call.name != _SCHEMA_SEARCH_TOOL_NAME
            and not _is_runtime_hidden_result(result)
        )
        progressed = bool(newly_revealed or new_refs or plan_progressed or generic_first_success)

        if progressed:
            self.consecutive_no_progress_observations = 0
            self.schema_search_without_new_reveal = 0
            return True

        self.consecutive_no_progress_observations += 1
        if previous_count >= 1:
            self.repeated_no_progress_fingerprints += 1
        if tool_call.name == _SCHEMA_SEARCH_TOOL_NAME and not newly_revealed:
            self.schema_search_without_new_reveal += 1

        error_signature = _tool_error_signature(result)
        if error_signature is not None:
            self.error_signature_counts[error_signature] = self.error_signature_counts.get(error_signature, 0) + 1

        self._refresh_stop_reason()
        return False

    def should_finalize(self) -> bool:
        self._refresh_stop_reason()
        return self.stop_reason is not None

    def _refresh_stop_reason(self) -> None:
        if self.stop_reason is not None:
            return
        if self.soft_budget_exceeded and self.consecutive_no_progress_observations >= 1:
            self.stop_reason = "soft_budget_exceeded_without_progress"
            return
        if self.repeated_no_progress_fingerprints >= _MAX_REPEATED_NO_PROGRESS_FINGERPRINTS:
            self.stop_reason = "repeated_tool_without_progress"
            return
        if self.consecutive_no_progress_observations >= _MAX_NO_PROGRESS_OBSERVATIONS:
            self.stop_reason = "consecutive_tool_calls_without_progress"
            return
        if self.schema_search_without_new_reveal >= _MAX_SCHEMA_SEARCH_WITHOUT_NEW_REVEAL:
            self.stop_reason = "schema_search_without_new_reveal"
            return
        if any(count >= _MAX_REPEATED_ERROR_SIGNATURES for count in self.error_signature_counts.values()):
            self.stop_reason = "repeated_tool_error_without_progress"


class AgentRuntime:
    """Execute one complete agent run with optional tool loops."""

    def __init__(
        self,
        session_manager: SessionManager,
        event_recorder: EventRecorder,
        context_assembler: ContextAssembler,
        model_client: ChatModelClient,
        tool_executor: ToolExecutor,
        mid_term_flusher: MidTermFlusher | None = None,
        context_compactor: ContextCompactor | None = None,
        tool_schema_disclosure_mode: str = "full",
        tool_schema_always_visible: str | list[str] | None = None,
        tool_context_window_mode: str = "off",
        workflow_guard: WorkflowRuntimeGuard | None = None,
        tool_call_ledger: ToolCallLedger | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._event_recorder = event_recorder
        self._context_assembler = context_assembler
        self._model_client = model_client
        self._tool_executor = tool_executor
        self._mid_term_flusher = mid_term_flusher
        self._context_compactor = context_compactor
        self._tool_schema_disclosure_mode = normalize_tool_schema_disclosure_mode(tool_schema_disclosure_mode)
        self._tool_schema_always_visible = normalize_always_visible_tool_names(tool_schema_always_visible)
        self._tool_context_window_mode = normalize_tool_context_window_mode(tool_context_window_mode)
        self._workflow_guard = workflow_guard
        self._answer_normalizer = AnswerNormalizer()
        self._tool_runner = ToolExecutionRunner(tool_executor=tool_executor)
        self._tool_gateway = (
            ToolGateway(
                tool_executor=tool_executor,
                ledger=tool_call_ledger,
                workflow_guard=workflow_guard,
            )
            if tool_call_ledger is not None
            else None
        )
        self._post_run_maintenance = PostRunMaintenanceScheduler(
            mid_term_flusher_provider=lambda: self._mid_term_flusher,
            context_compactor_provider=lambda: self._context_compactor,
        )

    def run(self, run_input: AgentRunInput) -> AgentRunOutput:
        if not isinstance(run_input, AgentRunInput):
            raise ValidationError("run_input must be an AgentRunInput.")

        _logger.info(
            "开始执行 agent run: session_id=%s message_len=%s skill_count=%s max_tool_rounds=%s",
            run_input.session_id,
            len(run_input.user_message),
            len(run_input.skill_names),
            run_input.max_tool_rounds,
        )
        session_meta = self._session_manager.get_or_create_session(run_input.session_id)
        session_id = session_meta.session_id
        run_context = self._resolve_run_context(session_id=session_id, run_input=run_input)

        self._event_recorder.record(
            context=run_context,
            event_type="run_started",
            payload={"max_tool_rounds": run_input.max_tool_rounds},
        )
        self._event_recorder.record(
            context=run_context,
            event_type="user_message",
            payload={"content": run_input.user_message},
        )

        context = self._context_assembler.assemble(
            context=run_context,
            user_message=run_input.user_message,
            skill_names=run_input.skill_names,
        )
        _logger.debug(
            "上下文组装完成: session_id=%s messages=%s memories=%s tools=%s",
            session_id,
            len(context.messages),
            len(context.memory_hits),
            len(context.tool_definitions),
        )
        self._event_recorder.record(
            context=run_context,
            event_type="memory_retrieval",
            payload=context.memory_summary,
        )

        tool_reveal_state = ToolRevealState.create(
            mode=self._tool_schema_disclosure_mode_for_context(run_context),
            available_definitions=context.tool_definitions,
            always_visible_tool_names=self._initial_visible_tool_names(context.initial_visible_tool_names),
        )
        tool_context_window = ToolContextWindow(
            base_messages=list(context.messages),
            mode=self._tool_context_window_mode,
        )
        used_tool_calls: list[ToolCall] = []
        answer = ""

        # `max_tool_rounds` 约束业务工具轮次；纯 tool_search 只是 schema 揭示，
        # 单独给少量额外轮次，避免 search 模式天然少一次业务动作。
        round_index = 0
        business_tool_rounds = 0
        schema_search_rounds = 0
        premature_workflow_reminders = 0
        premature_answer_reminders = 0
        hidden_runtime_tool_suppression_counts: dict[str, int] = {}
        pending_runtime_plan = pending_runtime_plan_from_context_bundle(context.runtime_tool_plan)
        runtime_known_refs = _runtime_plan_known_refs(pending_runtime_plan)
        progress_tracker = _ToolLoopProgressTracker()
        max_model_rounds = _hard_model_round_limit(run_input.max_tool_rounds)
        while round_index <= max_model_rounds:
            strict_runtime_tool_mode = _strict_runtime_tool_mode(
                tool_reveal_state=tool_reveal_state,
                pending_runtime_plan=pending_runtime_plan,
            )
            visible_tool_definitions = _visible_tool_definitions_for_runtime_plan(
                tool_reveal_state=tool_reveal_state,
                pending_runtime_plan=pending_runtime_plan,
            )
            messages = tool_context_window.render_messages(
                runtime_plan=pending_runtime_plan,
                strict_mode=strict_runtime_tool_mode,
            )
            if strict_runtime_tool_mode:
                messages.append({"role": "assistant", "content": _strict_runtime_plan_notice(pending_runtime_plan)})
            visible_tool_names_for_round = {definition.name for definition in visible_tool_definitions}
            tools_payload = [to_model_tool_schema(tool) for tool in visible_tool_definitions]
            _logger.debug("模型调用开始: session_id=%s round=%s message_count=%s", session_id, round_index, len(messages))
            model_response = self._model_client.generate(
                system_prompt=context.system_prompt,
                messages=messages,
                tools=tools_payload,
            )
            _logger.debug(
                "模型调用完成: session_id=%s round=%s content_len=%s tool_call_count=%s",
                session_id,
                round_index,
                len(model_response.content),
                len(model_response.tool_calls),
            )

            resolved_tool_calls = ensure_tool_call_ids(model_response.tool_calls)
            self._record_llm_usage(
                run_context=run_context,
                system_prompt=context.system_prompt,
                system_prompt_sections=context.system_prompt_sections,
                messages=messages,
                tools=tools_payload,
                model_response=model_response,
                tool_calls=resolved_tool_calls,
                mode="sync",
                phase="tool_loop",
                round_index=round_index,
                tool_disclosure=tool_reveal_state.usage_payload(visible_definitions=visible_tool_definitions),
                tool_context=tool_context_window.usage_payload(
                    runtime_plan=pending_runtime_plan,
                    strict_mode=strict_runtime_tool_mode,
                ),
            )

            if not resolved_tool_calls:
                answer = (model_response.content or "").strip()
                early_rejection_reason = _final_answer_rejection_reason(
                    answer,
                    pending_runtime_plan=pending_runtime_plan,
                )
                if early_rejection_reason is not None:
                    self._event_recorder.record(
                        context=run_context,
                        event_type="assistant_answer_rejected",
                        payload={"reason": early_rejection_reason, "content_preview": answer[:160]},
                    )
                    answer = ""
                if _is_premature_workflow_answer(
                    pending_runtime_plan=pending_runtime_plan,
                    tool_reveal_state=tool_reveal_state,
                ):
                    auto_tool_call = (
                        _strict_required_tool_auto_call_from_plan(
                            pending_runtime_plan=pending_runtime_plan,
                            visible_tool_names_for_round=visible_tool_names_for_round,
                        )
                        if premature_answer_reminders >= 1
                        else None
                    )
                    if auto_tool_call is not None:
                        resolved_tool_calls = ensure_tool_call_ids([auto_tool_call])
                        answer = ""
                        self._event_recorder.record(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload=_strict_auto_execute_event_payload(
                                blocked_tool_call=None,
                                replacement_tool_call=resolved_tool_calls[0],
                                pending_runtime_plan=pending_runtime_plan,
                            ),
                        )
                    else:
                        premature_workflow_reminders += 1
                        premature_answer_reminders += 1
                        if premature_answer_reminders > _MAX_PREMATURE_WORKFLOW_REMINDERS:
                            self._event_recorder.record(
                                context=run_context,
                                event_type="workflow_runtime_decision",
                                payload={
                                    "policy": "finalize",
                                    "reason": "premature_final_answer_stagnation",
                                    "runtime_plan": pending_runtime_plan,
                                    "reminder_index": premature_answer_reminders,
                                    "soft_budget": _MAX_PREMATURE_WORKFLOW_REMINDERS,
                                },
                            )
                            answer = workflow_incomplete_answer(pending_runtime_plan)
                            break
                        notice = runtime_plan_notice(pending_runtime_plan)
                        self._event_recorder.record(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload={
                                "policy": "continue",
                                "reason": "premature_final_answer_with_pending_runtime_tools",
                                "runtime_plan": pending_runtime_plan,
                                "reminder_index": premature_answer_reminders,
                            },
                        )
                        tool_context_window.append_runtime_notice(notice)
                        round_index += 1
                        continue
                if not resolved_tool_calls:
                    if not answer:
                        answer = self._recover_final_answer(
                            run_context=run_context,
                            system_prompt=context.system_prompt,
                            messages=messages,
                            original_user_message=run_input.user_message,
                        )
                    answer = answer or "(no answer)"
                    break

            schema_search_only = _is_schema_search_only(resolved_tool_calls)
            suppressed_required_schema_search_notice_index = 0
            if schema_search_only and _is_premature_workflow_answer(
                pending_runtime_plan=pending_runtime_plan,
                tool_reveal_state=tool_reveal_state,
            ):
                premature_workflow_reminders += 1
                suppressed_required_schema_search_notice_index = premature_workflow_reminders
                self._event_recorder.record(
                    context=run_context,
                    event_type="workflow_runtime_decision",
                    payload={
                        "policy": "suppress",
                        "reason": "schema_search_suppressed_required_tool_visible",
                        "runtime_plan": pending_runtime_plan,
                        "reminder_index": premature_workflow_reminders,
                    },
                )
                tool_context_window.append_runtime_notice(runtime_plan_notice(pending_runtime_plan))
                if premature_workflow_reminders <= _MAX_SCHEMA_SEARCH_ROUNDS:
                    schema_search_rounds += 1
                    round_index += 1
                    continue
            if schema_search_only and _is_final_answer_ready_runtime_plan(pending_runtime_plan):
                schema_search_rounds = 0
            elif schema_search_only:
                if schema_search_rounds >= _MAX_SCHEMA_SEARCH_ROUNDS:
                    _logger.warning("达到工具 schema 搜索轮次上限: session_id=%s round=%s", session_id, round_index)
                    progress_tracker.mark_soft_budget_exceeded("schema_search_soft_budget_exceeded")
                    self._event_recorder.record(
                        context=run_context,
                        event_type="workflow_runtime_decision",
                        payload={
                            "policy": "continue",
                            "reason": "schema_search_soft_budget_exceeded",
                            "schema_search_rounds": schema_search_rounds,
                            "soft_budget": _MAX_SCHEMA_SEARCH_ROUNDS,
                        },
                    )
                schema_search_rounds += 1
            hidden_runtime_tool_names = _hidden_runtime_tool_names_to_suppress(
                resolved_tool_calls,
                pending_runtime_plan=pending_runtime_plan,
                visible_tool_names_for_round=visible_tool_names_for_round,
                strict_runtime_tool_mode=strict_runtime_tool_mode,
            )
            if hidden_runtime_tool_names:
                if _is_final_answer_ready_runtime_plan(pending_runtime_plan):
                    self._event_recorder.record(
                        context=run_context,
                        event_type="workflow_runtime_decision",
                        payload={
                            "policy": "finalize",
                            "reason": "hidden_tools_suppressed_final_answer_ready",
                            "runtime_plan": pending_runtime_plan,
                            "blocked_tools": hidden_runtime_tool_names,
                        },
                    )
                    answer = _deterministic_final_answer_fallback(pending_runtime_plan)
                    break
                suppression_key = _hidden_runtime_tool_suppression_key(
                    pending_runtime_plan=pending_runtime_plan,
                    hidden_tool_names=hidden_runtime_tool_names,
                )
                suppression_count = hidden_runtime_tool_suppression_counts.get(suppression_key, 0)
                if suppression_count >= _MAX_HIDDEN_RUNTIME_TOOL_SUPPRESSIONS_PER_PLAN:
                    self._event_recorder.record(
                        context=run_context,
                        event_type="workflow_runtime_decision",
                        payload={
                            "policy": "continue",
                            "reason": "hidden_tool_suppression_budget_exceeded",
                            "runtime_plan": pending_runtime_plan,
                            "blocked_tools": hidden_runtime_tool_names,
                            "suppressions": suppression_count,
                        },
                    )
                    if business_tool_rounds >= run_input.max_tool_rounds:
                        _logger.warning("达到工具调用上限: session_id=%s round=%s", session_id, round_index)
                        progress_tracker.mark_soft_budget_exceeded("tool_call_soft_budget_exceeded")
                        self._event_recorder.record(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload={
                                "policy": "continue",
                                "reason": "tool_call_soft_budget_exceeded",
                                "business_tool_rounds": business_tool_rounds,
                                "soft_budget": run_input.max_tool_rounds,
                            },
                        )
                    business_tool_rounds += 1
                    schema_search_rounds = 0
                else:
                    hidden_runtime_tool_suppression_counts[suppression_key] = suppression_count + 1
                    self._event_recorder.record(
                        context=run_context,
                        event_type="workflow_runtime_decision",
                        payload={
                            "policy": "suppress",
                            "reason": "hidden_tools_suppressed_required_tool_visible",
                            "runtime_plan": pending_runtime_plan,
                            "blocked_tools": hidden_runtime_tool_names,
                            "reminder_index": suppression_count + 1,
                        },
                    )
                    tool_context_window.append_runtime_notice(runtime_plan_notice(pending_runtime_plan))
                    round_index += 1
                    continue
            elif schema_search_only:
                pass
            elif business_tool_rounds >= run_input.max_tool_rounds:
                _logger.warning("达到工具调用上限: session_id=%s round=%s", session_id, round_index)
                progress_tracker.mark_soft_budget_exceeded("tool_call_soft_budget_exceeded")
                self._event_recorder.record(
                    context=run_context,
                    event_type="workflow_runtime_decision",
                    payload={
                        "policy": "continue",
                        "reason": "tool_call_soft_budget_exceeded",
                        "business_tool_rounds": business_tool_rounds,
                        "soft_budget": run_input.max_tool_rounds,
                    },
                )
                business_tool_rounds += 1
                schema_search_rounds = 0
            else:
                business_tool_rounds += 1
                schema_search_rounds = 0

            if model_response.content.strip():
                # 一些模型会在 tool_call 前返回推理摘要，记录下来供前端“执行过程/思考”展示。
                self._event_recorder.record(
                    context=run_context,
                    event_type="assistant_thinking",
                    payload={"content": model_response.content},
                )

            # 遇到工具调用时，必须先把 assistant 的 tool_calls 消息回填到上下文，
            # 后续 tool 角色消息才是协议上合法的。
            assistant_tool_call_message = build_assistant_tool_call_message(
                model_response.content,
                resolved_tool_calls,
                reasoning_content=model_response.reasoning_content,
            )
            tool_context_window.consume_pending_exchange()
            tool_messages: list[dict[str, Any]] = []
            tool_observations = []
            terminal_workflow_results: list[bool] = []

            for tool_call in resolved_tool_calls:
                used_tool_calls.append(tool_call)
                plan_before_tool = pending_runtime_plan
                revealed_before_tool = set(tool_reveal_state.revealed_tool_names)
                self._event_recorder.record(
                    context=run_context,
                    event_type="tool_call",
                    payload={
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                )
                execution_tool_call = tool_call
                if tool_call.name not in visible_tool_names_for_round:
                    support_tool_allowed = _hidden_runtime_support_tool_allowed(
                        tool_call,
                        pending_runtime_plan=pending_runtime_plan,
                    )
                    replacement_tool_call = (
                        _strict_required_tool_auto_call(
                            tool_call,
                            pending_runtime_plan=pending_runtime_plan,
                            visible_tool_names_for_round=visible_tool_names_for_round,
                        )
                        if strict_runtime_tool_mode and not support_tool_allowed
                        else None
                    )
                    if replacement_tool_call is not None:
                        execution_tool_call = replacement_tool_call
                        self._event_recorder.record(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload=_strict_auto_execute_event_payload(
                                blocked_tool_call=tool_call,
                                replacement_tool_call=replacement_tool_call,
                                pending_runtime_plan=pending_runtime_plan,
                            ),
                        )
                        self._event_recorder.record(
                            context=run_context,
                            event_type="tool_call",
                            payload={
                                "name": replacement_tool_call.name,
                                "arguments": replacement_tool_call.arguments,
                                "tool_call_id": replacement_tool_call.tool_call_id,
                                "auto_executed": True,
                                "replaced_tool_name": tool_call.name,
                            },
                        )
                        used_tool_calls.append(replacement_tool_call)
                        if self._tool_gateway is not None:
                            gateway_result = self._tool_gateway.execute(
                                replacement_tool_call,
                                run_context,
                                pending_runtime_plan=pending_runtime_plan,
                            )
                            execution_tool_call = gateway_result.tool_call
                            result = gateway_result.result
                            if gateway_result.event_payload is not None:
                                self._event_recorder.record(
                                    context=run_context,
                                    event_type="workflow_runtime_decision",
                                    payload=gateway_result.event_payload,
                                )
                        else:
                            guard_decision = self._inspect_workflow_guard(replacement_tool_call, run_context)
                            execution_tool_call = guard_decision.tool_call
                            if guard_decision.event_payload is not None:
                                self._event_recorder.record(
                                    context=run_context,
                                    event_type="workflow_runtime_decision",
                                    payload=guard_decision.event_payload,
                                )
                            if guard_decision.result is not None:
                                result = guard_decision.result
                            else:
                                result = self._tool_runner.execute_safely(execution_tool_call, run_context)
                    else:
                        if support_tool_allowed:
                            self._event_recorder.record(
                                context=run_context,
                                event_type="workflow_runtime_decision",
                                payload={
                                    "workflow_runtime_result": True,
                                    "policy": "allow",
                                    "reason": "hidden_support_tool_allowed_by_runtime_plan",
                                    "tool_name": tool_call.name,
                                    "runtime_plan": pending_runtime_plan,
                                },
                            )
                            if self._tool_gateway is not None:
                                gateway_result = self._tool_gateway.execute(
                                    tool_call,
                                    run_context,
                                    pending_runtime_plan=pending_runtime_plan,
                                )
                                execution_tool_call = gateway_result.tool_call
                                result = gateway_result.result
                                if gateway_result.event_payload is not None:
                                    self._event_recorder.record(
                                        context=run_context,
                                        event_type="workflow_runtime_decision",
                                        payload=gateway_result.event_payload,
                                    )
                            else:
                                guard_decision = self._inspect_workflow_guard(tool_call, run_context)
                                execution_tool_call = guard_decision.tool_call
                                if guard_decision.event_payload is not None:
                                    self._event_recorder.record(
                                        context=run_context,
                                        event_type="workflow_runtime_decision",
                                        payload=guard_decision.event_payload,
                                    )
                                if guard_decision.result is not None:
                                    result = guard_decision.result
                                else:
                                    result = self._tool_runner.execute_safely(execution_tool_call, run_context)
                        else:
                            result = hidden_tool_result(
                                tool_call.name,
                                runtime_plan=pending_runtime_plan,
                                strict_runtime_plan=strict_runtime_tool_mode,
                            )
                else:
                    if self._tool_gateway is not None:
                        gateway_result = self._tool_gateway.execute(
                            tool_call,
                            run_context,
                            pending_runtime_plan=pending_runtime_plan,
                        )
                        execution_tool_call = gateway_result.tool_call
                        result = gateway_result.result
                        if gateway_result.event_payload is not None:
                            self._event_recorder.record(
                                context=run_context,
                                event_type="workflow_runtime_decision",
                                payload=gateway_result.event_payload,
                            )
                    else:
                        guard_decision = self._inspect_workflow_guard(tool_call, run_context)
                        execution_tool_call = guard_decision.tool_call
                        if guard_decision.event_payload is not None:
                            self._event_recorder.record(
                                context=run_context,
                                event_type="workflow_runtime_decision",
                                payload=guard_decision.event_payload,
                            )
                        if guard_decision.result is not None:
                            result = guard_decision.result
                        else:
                            result = self._tool_runner.execute_safely(execution_tool_call, run_context)
                _logger.info(
                    "工具调用完成: session_id=%s tool=%s success=%s content_len=%s",
                    session_id,
                    tool_call.name,
                    result.success,
                    len(result.content),
                )
                self._event_recorder.record(
                    context=run_context,
                    event_type="tool_result",
                    payload={
                        "tool_name": result.tool_name,
                        "success": result.success,
                        "content": result.content,
                        "tool_call_id": execution_tool_call.tool_call_id,
                    },
                )
                terminal_workflow_results.append(_is_terminal_workflow_result(result))
                if execution_tool_call.name == "memory_write" and result.success:
                    self._event_recorder.record(
                        context=run_context,
                        event_type="memory_write",
                        payload={
                            "arguments": execution_tool_call.arguments,
                            "result": result.content,
                        },
                    )
                if result.success:
                    previous_pending_plan = _runtime_plan_with_known_refs(pending_runtime_plan, runtime_known_refs)
                    workflow_runtime_plan = pending_runtime_plan_from_workflow_result(result.content)
                    if workflow_runtime_plan is not None:
                        runtime_known_refs.update(_runtime_plan_known_refs(workflow_runtime_plan))
                        pending_runtime_plan = merge_pending_runtime_plan(
                            current=previous_pending_plan,
                            incoming=workflow_runtime_plan,
                        )
                        pending_runtime_plan = _runtime_plan_with_known_refs(pending_runtime_plan, runtime_known_refs)
                        tool_reveal_state.reveal_tool_names(runtime_plan_next_allowed_tools(workflow_runtime_plan))
                        if not _is_runtime_hidden_result(result):
                            premature_workflow_reminders = 0
                            premature_answer_reminders = 0
                    if execution_tool_call.name == "tool_search":
                        tool_reveal_state.apply_tool_search_result(result.content)
                        search_runtime_plan = pending_runtime_plan_from_tool_search_result(result.content)
                        if search_runtime_plan is not None:
                            runtime_known_refs.update(_runtime_plan_known_refs(search_runtime_plan))
                            pending_runtime_plan = merge_pending_runtime_plan(
                                current=_runtime_plan_with_known_refs(pending_runtime_plan, runtime_known_refs),
                                incoming=search_runtime_plan,
                            )
                            pending_runtime_plan = _runtime_plan_with_known_refs(pending_runtime_plan, runtime_known_refs)
                            tool_reveal_state.reveal_tool_names(runtime_plan_next_allowed_tools(search_runtime_plan))
                            premature_workflow_reminders = 0
                            premature_answer_reminders = 0
                    else:
                        runtime_known_refs.update(
                            known_refs_from_successful_tool_result(execution_tool_call.name, result.content)
                        )
                        success_runtime_plan = pending_runtime_plan_from_successful_tool_result(
                            execution_tool_call.name,
                            result.content,
                            previous_pending_plan=previous_pending_plan,
                        )
                        if success_runtime_plan is not None:
                            pending_runtime_plan = _runtime_plan_with_known_refs(success_runtime_plan, runtime_known_refs)
                            tool_reveal_state.reveal_tool_names(runtime_plan_next_allowed_tools(success_runtime_plan))
                            premature_workflow_reminders = 0
                            premature_answer_reminders = 0
                        if (
                            success_runtime_plan is None
                            and workflow_runtime_plan is None
                            and previous_pending_plan is not None
                            and execution_tool_call.name in runtime_plan_completion_tools(previous_pending_plan)
                        ):
                            pending_runtime_plan = None
                if not _skip_stagnation_observation_for_suppressed_schema_search(
                    notice_index=suppressed_required_schema_search_notice_index,
                    tool_call=execution_tool_call,
                    result=result,
                ):
                    progress_tracker.observe_tool_result(
                        tool_call=execution_tool_call,
                        result=result,
                        revealed_before=revealed_before_tool,
                        revealed_after=set(tool_reveal_state.revealed_tool_names),
                        pending_plan_before=plan_before_tool,
                        pending_plan_after=pending_runtime_plan,
                    )
                model_visible_content = compact_tool_result_for_model(
                    tool_name=result.tool_name,
                    success=result.success,
                    content=result.content,
                )
                tool_message = (
                    build_tool_result_message(
                        tool_call_id=execution_tool_call.tool_call_id,
                        content=model_visible_content,
                    )
                )
                tool_messages.append(tool_message)
                tool_observations.append(
                    build_tool_observation(
                        tool_call=execution_tool_call,
                        result=result,
                        model_visible_content=model_visible_content,
                    )
                )

            tool_context_window.set_pending_exchange(
                assistant_message=assistant_tool_call_message,
                tool_messages=tool_messages,
                observations=tool_observations,
            )
            if _is_final_answer_ready_runtime_plan(pending_runtime_plan):
                self._event_recorder.record(
                    context=run_context,
                    event_type="workflow_runtime_decision",
                    payload={
                        "policy": "finalize",
                        "reason": "workflow_final_answer_ready",
                        "business_tool_rounds": business_tool_rounds,
                        "schema_search_rounds": schema_search_rounds,
                    },
                )
                answer = self._recover_final_answer(
                    run_context=run_context,
                    system_prompt=context.system_prompt,
                    messages=tool_context_window.render_messages(),
                    original_user_message=run_input.user_message,
                )
                answer = answer or _deterministic_final_answer_fallback(pending_runtime_plan)
                break
            if terminal_workflow_results and all(terminal_workflow_results):
                answer = self._recover_final_answer(
                    run_context=run_context,
                    system_prompt=context.system_prompt,
                    messages=tool_context_window.render_messages(),
                    original_user_message=run_input.user_message,
                )
                answer = answer or "(no answer)"
                break
            if progress_tracker.should_finalize():
                stop_reason = progress_tracker.stop_reason or "tool_loop_stagnation"
                self._event_recorder.record(
                    context=run_context,
                    event_type="workflow_runtime_decision",
                    payload={
                        "policy": "finalize",
                        "reason": "tool_loop_stagnation",
                        "stop_reason": stop_reason,
                        "business_tool_rounds": business_tool_rounds,
                        "schema_search_rounds": schema_search_rounds,
                        "soft_budget_exceeded": progress_tracker.soft_budget_exceeded,
                    },
                )
                tool_context_window.append_runtime_notice(_tool_loop_stagnation_notice(stop_reason))
                answer = self._recover_final_answer(
                    run_context=run_context,
                    system_prompt=context.system_prompt,
                    messages=tool_context_window.render_messages(),
                    original_user_message=run_input.user_message,
                )
                answer = answer or _deterministic_final_answer_fallback(pending_runtime_plan)
                break
            round_index += 1

        if not answer and round_index > max_model_rounds:
            self._event_recorder.record(
                context=run_context,
                event_type="workflow_runtime_decision",
                payload={
                    "policy": "finalize",
                    "reason": "hard_model_round_limit_reached",
                    "max_model_rounds": max_model_rounds,
                },
            )
            answer = self._recover_final_answer(
                run_context=run_context,
                system_prompt=context.system_prompt,
                messages=tool_context_window.render_messages(),
                original_user_message=run_input.user_message,
            )
            answer = answer or _deterministic_final_answer_fallback(pending_runtime_plan)
        if not answer and _is_premature_workflow_answer(
            pending_runtime_plan=pending_runtime_plan,
            tool_reveal_state=tool_reveal_state,
        ):
            answer = workflow_incomplete_answer(pending_runtime_plan)
        if not answer:
            answer = "(no answer)"
        answer = self._sanitize_final_answer_sync(
            answer=answer,
            run_context=run_context,
            system_prompt=context.system_prompt,
            messages=tool_context_window.render_messages(),
            original_user_message=run_input.user_message,
            pending_runtime_plan=pending_runtime_plan,
        )

        self._event_recorder.record(
            context=run_context,
            event_type="assistant_message",
            payload={"content": answer},
        )
        self._event_recorder.record(
            context=run_context,
            event_type="run_finished",
            payload={"answer_length": len(answer), "tool_calls": len(used_tool_calls)},
        )
        self._dispatch_post_run_maintenance_sync(run_context)
        _logger.info(
            "agent run 完成: session_id=%s answer_len=%s tool_calls=%s",
            session_id,
            len(answer),
            len(used_tool_calls),
        )

        return AgentRunOutput(
            session_id=session_id,
            answer=answer,
            tool_calls=used_tool_calls,
            memory_hits=context.memory_hits,
        )

    async def run_stream(self, run_input: AgentRunInput, channel: EventChannel) -> AgentRunOutput:
        if not isinstance(run_input, AgentRunInput):
            raise ValidationError("run_input must be an AgentRunInput.")
        if not isinstance(channel, EventChannel):
            raise ValidationError("channel must be an EventChannel.")

        _logger.info(
            "开始执行流式 agent run: session_id=%s message_len=%s skill_count=%s max_tool_rounds=%s",
            run_input.session_id,
            len(run_input.user_message),
            len(run_input.skill_names),
            run_input.max_tool_rounds,
        )
        session_meta = await asyncio.to_thread(self._session_manager.get_or_create_session, run_input.session_id)
        session_id = session_meta.session_id
        run_context = self._resolve_run_context(session_id=session_id, run_input=run_input)

        await self._event_recorder.record_async(
            context=run_context,
            event_type="run_started",
            payload={"max_tool_rounds": run_input.max_tool_rounds},
            channel=channel,
        )
        await self._event_recorder.record_async(
            context=run_context,
            event_type="user_message",
            payload={"content": run_input.user_message},
            channel=channel,
        )

        context = await asyncio.to_thread(
            self._context_assembler.assemble,
            context=run_context,
            user_message=run_input.user_message,
            skill_names=run_input.skill_names,
        )
        _logger.debug(
            "流式上下文组装完成: session_id=%s messages=%s memories=%s tools=%s",
            session_id,
            len(context.messages),
            len(context.memory_hits),
            len(context.tool_definitions),
        )
        await self._event_recorder.record_async(
            context=run_context,
            event_type="memory_retrieval",
            payload=context.memory_summary,
            channel=channel,
        )

        tool_reveal_state = ToolRevealState.create(
            mode=self._tool_schema_disclosure_mode_for_context(run_context),
            available_definitions=context.tool_definitions,
            always_visible_tool_names=self._initial_visible_tool_names(context.initial_visible_tool_names),
        )
        tool_context_window = ToolContextWindow(
            base_messages=list(context.messages),
            mode=self._tool_context_window_mode,
        )
        used_tool_calls: list[ToolCall] = []
        answer = ""

        round_index = 0
        business_tool_rounds = 0
        schema_search_rounds = 0
        premature_workflow_reminders = 0
        premature_answer_reminders = 0
        hidden_runtime_tool_suppression_counts: dict[str, int] = {}
        pending_runtime_plan = pending_runtime_plan_from_context_bundle(context.runtime_tool_plan)
        runtime_known_refs = _runtime_plan_known_refs(pending_runtime_plan)
        progress_tracker = _ToolLoopProgressTracker()
        max_model_rounds = _hard_model_round_limit(run_input.max_tool_rounds)
        while round_index <= max_model_rounds:
            strict_runtime_tool_mode = _strict_runtime_tool_mode(
                tool_reveal_state=tool_reveal_state,
                pending_runtime_plan=pending_runtime_plan,
            )
            visible_tool_definitions = _visible_tool_definitions_for_runtime_plan(
                tool_reveal_state=tool_reveal_state,
                pending_runtime_plan=pending_runtime_plan,
            )
            messages = tool_context_window.render_messages(
                runtime_plan=pending_runtime_plan,
                strict_mode=strict_runtime_tool_mode,
            )
            if strict_runtime_tool_mode:
                messages.append({"role": "assistant", "content": _strict_runtime_plan_notice(pending_runtime_plan)})
            visible_tool_names_for_round = {definition.name for definition in visible_tool_definitions}
            tools_payload = [to_model_tool_schema(tool) for tool in visible_tool_definitions]
            _logger.debug("流式模型调用开始: session_id=%s round=%s message_count=%s", session_id, round_index, len(messages))
            round_content_parts: list[str] = []
            round_content_deltas: list[str] = []
            round_reasoning_parts: list[str] = []
            resolved_tool_calls: list[ToolCall] = []
            round_usage: TokenUsage | None = None
            round_model: str | None = None

            async for chunk in self._model_client.generate_stream(
                system_prompt=context.system_prompt,
                messages=messages,
                tools=tools_payload,
            ):
                if chunk.delta:
                    round_content_parts.append(chunk.delta)
                    round_content_deltas.append(chunk.delta)
                if chunk.reasoning_delta:
                    round_reasoning_parts.append(chunk.reasoning_delta)
                if chunk.usage is not None:
                    round_usage = chunk.usage
                if chunk.model:
                    round_model = chunk.model

                if chunk.finished:
                    resolved_tool_calls = ensure_tool_call_ids(chunk.tool_calls or [])

            round_content = "".join(round_content_parts).strip()
            round_reasoning = "".join(round_reasoning_parts).strip()
            _logger.debug(
                "流式模型调用完成: session_id=%s round=%s content_len=%s tool_call_count=%s",
                session_id,
                round_index,
                len(round_content),
                len(resolved_tool_calls),
            )
            await self._record_llm_usage_async(
                run_context=run_context,
                system_prompt=context.system_prompt,
                system_prompt_sections=context.system_prompt_sections,
                messages=messages,
                tools=tools_payload,
                content=round_content,
                reasoning_content=round_reasoning,
                tool_calls=resolved_tool_calls,
                usage=round_usage,
                model=round_model,
                mode="stream",
                phase="tool_loop",
                round_index=round_index,
                channel=channel,
                tool_disclosure=tool_reveal_state.usage_payload(visible_definitions=visible_tool_definitions),
                tool_context=tool_context_window.usage_payload(
                    runtime_plan=pending_runtime_plan,
                    strict_mode=strict_runtime_tool_mode,
                ),
            )

            if not resolved_tool_calls:
                answer = round_content
                early_rejection_reason = _final_answer_rejection_reason(
                    answer,
                    pending_runtime_plan=pending_runtime_plan,
                )
                if early_rejection_reason is not None:
                    await self._event_recorder.record_async(
                        context=run_context,
                        event_type="assistant_answer_rejected",
                        payload={"reason": early_rejection_reason, "content_preview": answer[:160]},
                        channel=channel,
                    )
                    answer = ""
                    round_content_deltas = []
                if _is_premature_workflow_answer(
                    pending_runtime_plan=pending_runtime_plan,
                    tool_reveal_state=tool_reveal_state,
                ):
                    auto_tool_call = (
                        _strict_required_tool_auto_call_from_plan(
                            pending_runtime_plan=pending_runtime_plan,
                            visible_tool_names_for_round=visible_tool_names_for_round,
                        )
                        if premature_answer_reminders >= 1
                        else None
                    )
                    if auto_tool_call is not None:
                        resolved_tool_calls = ensure_tool_call_ids([auto_tool_call])
                        answer = ""
                        round_content_deltas = []
                        await self._event_recorder.record_async(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload=_strict_auto_execute_event_payload(
                                blocked_tool_call=None,
                                replacement_tool_call=resolved_tool_calls[0],
                                pending_runtime_plan=pending_runtime_plan,
                            ),
                            channel=channel,
                        )
                    else:
                        premature_workflow_reminders += 1
                        premature_answer_reminders += 1
                        if premature_answer_reminders > _MAX_PREMATURE_WORKFLOW_REMINDERS:
                            await self._event_recorder.record_async(
                                context=run_context,
                                event_type="workflow_runtime_decision",
                                payload={
                                    "policy": "finalize",
                                    "reason": "premature_final_answer_stagnation",
                                    "runtime_plan": pending_runtime_plan,
                                    "reminder_index": premature_answer_reminders,
                                    "soft_budget": _MAX_PREMATURE_WORKFLOW_REMINDERS,
                                },
                                channel=channel,
                            )
                            round_content_deltas = []
                            answer = workflow_incomplete_answer(pending_runtime_plan)
                            break
                        notice = runtime_plan_notice(pending_runtime_plan)
                        await self._event_recorder.record_async(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload={
                                "policy": "continue",
                                "reason": "premature_final_answer_with_pending_runtime_tools",
                                "runtime_plan": pending_runtime_plan,
                                "reminder_index": premature_answer_reminders,
                            },
                            channel=channel,
                        )
                        tool_context_window.append_runtime_notice(notice)
                        round_index += 1
                        continue
                if not resolved_tool_calls:
                    if _contains_internal_final_answer(answer):
                        await self._event_recorder.record_async(
                            context=run_context,
                            event_type="assistant_answer_rejected",
                            payload={"reason": "internal_runtime_text", "content_preview": answer[:160]},
                            channel=channel,
                        )
                        round_content_deltas = []
                        answer = await self._recover_final_answer_stream(
                            run_context=run_context,
                            system_prompt=context.system_prompt,
                            messages=messages,
                            original_user_message=run_input.user_message,
                            previous_tool_calls=used_tool_calls,
                            channel=channel,
                        )
                    if answer and round_content_deltas:
                        emitted_answer_meta: tuple[str, str, str, str, str] | None = None
                        cumulative_parts: list[str] = []
                        for delta in round_content_deltas:
                            cumulative_parts.append(delta)
                            emitted_answer_meta = await self._emit_stream_answer_meta_if_changed(
                                channel=channel,
                                content="".join(cumulative_parts),
                                tool_calls=used_tool_calls,
                                previous_meta=emitted_answer_meta,
                            )
                            await channel.emit("answer_delta", {"delta": delta})
                    if not answer:
                        answer = await self._recover_final_answer_stream(
                            run_context=run_context,
                            system_prompt=context.system_prompt,
                            messages=messages,
                            original_user_message=run_input.user_message,
                            previous_tool_calls=used_tool_calls,
                            channel=channel,
                        )
                    answer = answer or "(no answer)"
                    break

            schema_search_only = _is_schema_search_only(resolved_tool_calls)
            suppressed_required_schema_search_notice_index = 0
            if schema_search_only and _is_premature_workflow_answer(
                pending_runtime_plan=pending_runtime_plan,
                tool_reveal_state=tool_reveal_state,
            ):
                premature_workflow_reminders += 1
                suppressed_required_schema_search_notice_index = premature_workflow_reminders
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="workflow_runtime_decision",
                    payload={
                        "policy": "suppress",
                        "reason": "schema_search_suppressed_required_tool_visible",
                        "runtime_plan": pending_runtime_plan,
                        "reminder_index": premature_workflow_reminders,
                    },
                    channel=channel,
                )
                tool_context_window.append_runtime_notice(runtime_plan_notice(pending_runtime_plan))
                if premature_workflow_reminders <= _MAX_SCHEMA_SEARCH_ROUNDS:
                    schema_search_rounds += 1
                    round_index += 1
                    continue
            if schema_search_only and _is_final_answer_ready_runtime_plan(pending_runtime_plan):
                schema_search_rounds = 0
            elif schema_search_only:
                if schema_search_rounds >= _MAX_SCHEMA_SEARCH_ROUNDS:
                    _logger.warning("达到工具 schema 搜索轮次上限(流式): session_id=%s round=%s", session_id, round_index)
                    progress_tracker.mark_soft_budget_exceeded("schema_search_soft_budget_exceeded")
                    await self._event_recorder.record_async(
                        context=run_context,
                        event_type="workflow_runtime_decision",
                        payload={
                            "policy": "continue",
                            "reason": "schema_search_soft_budget_exceeded",
                            "schema_search_rounds": schema_search_rounds,
                            "soft_budget": _MAX_SCHEMA_SEARCH_ROUNDS,
                        },
                        channel=channel,
                    )
                schema_search_rounds += 1
            hidden_runtime_tool_names = _hidden_runtime_tool_names_to_suppress(
                resolved_tool_calls,
                pending_runtime_plan=pending_runtime_plan,
                visible_tool_names_for_round=visible_tool_names_for_round,
                strict_runtime_tool_mode=strict_runtime_tool_mode,
            )
            if hidden_runtime_tool_names:
                if _is_final_answer_ready_runtime_plan(pending_runtime_plan):
                    await self._event_recorder.record_async(
                        context=run_context,
                        event_type="workflow_runtime_decision",
                        payload={
                            "policy": "finalize",
                            "reason": "hidden_tools_suppressed_final_answer_ready",
                            "runtime_plan": pending_runtime_plan,
                            "blocked_tools": hidden_runtime_tool_names,
                        },
                        channel=channel,
                    )
                    round_content_deltas = []
                    answer = _deterministic_final_answer_fallback(pending_runtime_plan)
                    break
                suppression_key = _hidden_runtime_tool_suppression_key(
                    pending_runtime_plan=pending_runtime_plan,
                    hidden_tool_names=hidden_runtime_tool_names,
                )
                suppression_count = hidden_runtime_tool_suppression_counts.get(suppression_key, 0)
                if suppression_count >= _MAX_HIDDEN_RUNTIME_TOOL_SUPPRESSIONS_PER_PLAN:
                    await self._event_recorder.record_async(
                        context=run_context,
                        event_type="workflow_runtime_decision",
                        payload={
                            "policy": "continue",
                            "reason": "hidden_tool_suppression_budget_exceeded",
                            "runtime_plan": pending_runtime_plan,
                            "blocked_tools": hidden_runtime_tool_names,
                            "suppressions": suppression_count,
                        },
                        channel=channel,
                    )
                    if business_tool_rounds >= run_input.max_tool_rounds:
                        _logger.warning("达到工具调用上限(流式): session_id=%s round=%s", session_id, round_index)
                        progress_tracker.mark_soft_budget_exceeded("tool_call_soft_budget_exceeded")
                        await self._event_recorder.record_async(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload={
                                "policy": "continue",
                                "reason": "tool_call_soft_budget_exceeded",
                                "business_tool_rounds": business_tool_rounds,
                                "soft_budget": run_input.max_tool_rounds,
                            },
                            channel=channel,
                        )
                    business_tool_rounds += 1
                    schema_search_rounds = 0
                else:
                    hidden_runtime_tool_suppression_counts[suppression_key] = suppression_count + 1
                    await self._event_recorder.record_async(
                        context=run_context,
                        event_type="workflow_runtime_decision",
                        payload={
                            "policy": "suppress",
                            "reason": "hidden_tools_suppressed_required_tool_visible",
                            "runtime_plan": pending_runtime_plan,
                            "blocked_tools": hidden_runtime_tool_names,
                            "reminder_index": suppression_count + 1,
                        },
                        channel=channel,
                    )
                    tool_context_window.append_runtime_notice(runtime_plan_notice(pending_runtime_plan))
                    round_index += 1
                    continue
            elif schema_search_only:
                pass
            elif business_tool_rounds >= run_input.max_tool_rounds:
                _logger.warning("达到工具调用上限(流式): session_id=%s round=%s", session_id, round_index)
                progress_tracker.mark_soft_budget_exceeded("tool_call_soft_budget_exceeded")
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="workflow_runtime_decision",
                    payload={
                        "policy": "continue",
                        "reason": "tool_call_soft_budget_exceeded",
                        "business_tool_rounds": business_tool_rounds,
                        "soft_budget": run_input.max_tool_rounds,
                    },
                    channel=channel,
                )
                business_tool_rounds += 1
                schema_search_rounds = 0
            else:
                business_tool_rounds += 1
                schema_search_rounds = 0

            if round_content:
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="assistant_thinking",
                    payload={"content": round_content},
                    channel=channel,
                )

            assistant_tool_call_message = build_assistant_tool_call_message(
                round_content,
                resolved_tool_calls,
                reasoning_content=round_reasoning,
            )
            tool_context_window.consume_pending_exchange()
            tool_messages: list[dict[str, Any]] = []
            tool_observations = []
            terminal_workflow_results: list[bool] = []

            for tool_call in resolved_tool_calls:
                used_tool_calls.append(tool_call)
                plan_before_tool = pending_runtime_plan
                revealed_before_tool = set(tool_reveal_state.revealed_tool_names)
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="tool_call",
                    payload={
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "tool_call_id": tool_call.tool_call_id,
                    },
                    channel=channel,
                )
                execution_tool_call = tool_call
                if tool_call.name not in visible_tool_names_for_round:
                    support_tool_allowed = _hidden_runtime_support_tool_allowed(
                        tool_call,
                        pending_runtime_plan=pending_runtime_plan,
                    )
                    replacement_tool_call = (
                        _strict_required_tool_auto_call(
                            tool_call,
                            pending_runtime_plan=pending_runtime_plan,
                            visible_tool_names_for_round=visible_tool_names_for_round,
                        )
                        if strict_runtime_tool_mode and not support_tool_allowed
                        else None
                    )
                    if replacement_tool_call is not None:
                        execution_tool_call = replacement_tool_call
                        await self._event_recorder.record_async(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload=_strict_auto_execute_event_payload(
                                blocked_tool_call=tool_call,
                                replacement_tool_call=replacement_tool_call,
                                pending_runtime_plan=pending_runtime_plan,
                            ),
                            channel=channel,
                        )
                        await self._event_recorder.record_async(
                            context=run_context,
                            event_type="tool_call",
                            payload={
                                "name": replacement_tool_call.name,
                                "arguments": replacement_tool_call.arguments,
                                "tool_call_id": replacement_tool_call.tool_call_id,
                                "auto_executed": True,
                                "replaced_tool_name": tool_call.name,
                            },
                            channel=channel,
                        )
                        used_tool_calls.append(replacement_tool_call)
                        if self._tool_gateway is not None:
                            gateway_result = await self._tool_gateway.execute_async(
                                replacement_tool_call,
                                run_context,
                                pending_runtime_plan=pending_runtime_plan,
                            )
                            execution_tool_call = gateway_result.tool_call
                            result = gateway_result.result
                            if gateway_result.event_payload is not None:
                                await self._event_recorder.record_async(
                                    context=run_context,
                                    event_type="workflow_runtime_decision",
                                    payload=gateway_result.event_payload,
                                    channel=channel,
                                )
                        else:
                            guard_decision = self._inspect_workflow_guard(replacement_tool_call, run_context)
                            execution_tool_call = guard_decision.tool_call
                            if guard_decision.event_payload is not None:
                                await self._event_recorder.record_async(
                                    context=run_context,
                                    event_type="workflow_runtime_decision",
                                    payload=guard_decision.event_payload,
                                    channel=channel,
                                )
                            if guard_decision.result is not None:
                                result = guard_decision.result
                            else:
                                result = await self._tool_runner.execute_safely_async(execution_tool_call, run_context)
                    elif support_tool_allowed:
                        await self._event_recorder.record_async(
                            context=run_context,
                            event_type="workflow_runtime_decision",
                            payload={
                                "workflow_runtime_result": True,
                                "policy": "allow",
                                "reason": "hidden_support_tool_allowed_by_runtime_plan",
                                "tool_name": tool_call.name,
                                "runtime_plan": pending_runtime_plan,
                            },
                            channel=channel,
                        )
                        if self._tool_gateway is not None:
                            gateway_result = await self._tool_gateway.execute_async(
                                tool_call,
                                run_context,
                                pending_runtime_plan=pending_runtime_plan,
                            )
                            execution_tool_call = gateway_result.tool_call
                            result = gateway_result.result
                            if gateway_result.event_payload is not None:
                                await self._event_recorder.record_async(
                                    context=run_context,
                                    event_type="workflow_runtime_decision",
                                    payload=gateway_result.event_payload,
                                    channel=channel,
                                )
                        else:
                            guard_decision = self._inspect_workflow_guard(tool_call, run_context)
                            execution_tool_call = guard_decision.tool_call
                            if guard_decision.event_payload is not None:
                                await self._event_recorder.record_async(
                                    context=run_context,
                                    event_type="workflow_runtime_decision",
                                    payload=guard_decision.event_payload,
                                    channel=channel,
                                )
                            if guard_decision.result is not None:
                                result = guard_decision.result
                            else:
                                result = await self._tool_runner.execute_safely_async(execution_tool_call, run_context)
                    else:
                        result = hidden_tool_result(
                            tool_call.name,
                            runtime_plan=pending_runtime_plan,
                            strict_runtime_plan=strict_runtime_tool_mode,
                        )
                else:
                    if self._tool_gateway is not None:
                        gateway_result = await self._tool_gateway.execute_async(
                            tool_call,
                            run_context,
                            pending_runtime_plan=pending_runtime_plan,
                        )
                        execution_tool_call = gateway_result.tool_call
                        result = gateway_result.result
                        if gateway_result.event_payload is not None:
                            await self._event_recorder.record_async(
                                context=run_context,
                                event_type="workflow_runtime_decision",
                                payload=gateway_result.event_payload,
                                channel=channel,
                            )
                    else:
                        guard_decision = self._inspect_workflow_guard(tool_call, run_context)
                        execution_tool_call = guard_decision.tool_call
                        if guard_decision.event_payload is not None:
                            await self._event_recorder.record_async(
                                context=run_context,
                                event_type="workflow_runtime_decision",
                                payload=guard_decision.event_payload,
                                channel=channel,
                            )
                        if guard_decision.result is not None:
                            result = guard_decision.result
                        else:
                            result = await self._tool_runner.execute_safely_async(execution_tool_call, run_context)
                _logger.info(
                    "流式工具调用完成: session_id=%s tool=%s success=%s content_len=%s",
                    session_id,
                    tool_call.name,
                    result.success,
                    len(result.content),
                )
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="tool_result",
                    payload={
                        "tool_name": result.tool_name,
                        "success": result.success,
                        "content": result.content,
                        "tool_call_id": execution_tool_call.tool_call_id,
                    },
                    channel=channel,
                )
                terminal_workflow_results.append(_is_terminal_workflow_result(result))
                if execution_tool_call.name == "memory_write" and result.success:
                    await self._event_recorder.record_async(
                        context=run_context,
                        event_type="memory_write",
                        payload={
                            "arguments": execution_tool_call.arguments,
                            "result": result.content,
                        },
                        channel=channel,
                    )
                if result.success:
                    previous_pending_plan = _runtime_plan_with_known_refs(pending_runtime_plan, runtime_known_refs)
                    workflow_runtime_plan = pending_runtime_plan_from_workflow_result(result.content)
                    if workflow_runtime_plan is not None:
                        runtime_known_refs.update(_runtime_plan_known_refs(workflow_runtime_plan))
                        pending_runtime_plan = merge_pending_runtime_plan(
                            current=previous_pending_plan,
                            incoming=workflow_runtime_plan,
                        )
                        pending_runtime_plan = _runtime_plan_with_known_refs(pending_runtime_plan, runtime_known_refs)
                        tool_reveal_state.reveal_tool_names(runtime_plan_next_allowed_tools(workflow_runtime_plan))
                        if not _is_runtime_hidden_result(result):
                            premature_workflow_reminders = 0
                            premature_answer_reminders = 0
                    if execution_tool_call.name == "tool_search":
                        tool_reveal_state.apply_tool_search_result(result.content)
                        search_runtime_plan = pending_runtime_plan_from_tool_search_result(result.content)
                        if search_runtime_plan is not None:
                            runtime_known_refs.update(_runtime_plan_known_refs(search_runtime_plan))
                            pending_runtime_plan = merge_pending_runtime_plan(
                                current=_runtime_plan_with_known_refs(pending_runtime_plan, runtime_known_refs),
                                incoming=search_runtime_plan,
                            )
                            pending_runtime_plan = _runtime_plan_with_known_refs(pending_runtime_plan, runtime_known_refs)
                            tool_reveal_state.reveal_tool_names(runtime_plan_next_allowed_tools(search_runtime_plan))
                            premature_workflow_reminders = 0
                            premature_answer_reminders = 0
                    else:
                        runtime_known_refs.update(
                            known_refs_from_successful_tool_result(execution_tool_call.name, result.content)
                        )
                        success_runtime_plan = pending_runtime_plan_from_successful_tool_result(
                            execution_tool_call.name,
                            result.content,
                            previous_pending_plan=previous_pending_plan,
                        )
                        if success_runtime_plan is not None:
                            pending_runtime_plan = _runtime_plan_with_known_refs(success_runtime_plan, runtime_known_refs)
                            tool_reveal_state.reveal_tool_names(runtime_plan_next_allowed_tools(success_runtime_plan))
                            premature_workflow_reminders = 0
                            premature_answer_reminders = 0
                        if (
                            success_runtime_plan is None
                            and workflow_runtime_plan is None
                            and previous_pending_plan is not None
                            and execution_tool_call.name in runtime_plan_completion_tools(previous_pending_plan)
                        ):
                            pending_runtime_plan = None
                if not _skip_stagnation_observation_for_suppressed_schema_search(
                    notice_index=suppressed_required_schema_search_notice_index,
                    tool_call=execution_tool_call,
                    result=result,
                ):
                    progress_tracker.observe_tool_result(
                        tool_call=execution_tool_call,
                        result=result,
                        revealed_before=revealed_before_tool,
                        revealed_after=set(tool_reveal_state.revealed_tool_names),
                        pending_plan_before=plan_before_tool,
                        pending_plan_after=pending_runtime_plan,
                    )
                model_visible_content = compact_tool_result_for_model(
                    tool_name=result.tool_name,
                    success=result.success,
                    content=result.content,
                )
                tool_message = (
                    build_tool_result_message(
                        tool_call_id=execution_tool_call.tool_call_id,
                        content=model_visible_content,
                    )
                )
                tool_messages.append(tool_message)
                tool_observations.append(
                    build_tool_observation(
                        tool_call=execution_tool_call,
                        result=result,
                        model_visible_content=model_visible_content,
                    )
                )

            tool_context_window.set_pending_exchange(
                assistant_message=assistant_tool_call_message,
                tool_messages=tool_messages,
                observations=tool_observations,
            )
            if _is_final_answer_ready_runtime_plan(pending_runtime_plan):
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="workflow_runtime_decision",
                    payload={
                        "policy": "finalize",
                        "reason": "workflow_final_answer_ready",
                        "business_tool_rounds": business_tool_rounds,
                        "schema_search_rounds": schema_search_rounds,
                    },
                    channel=channel,
                )
                answer = await self._recover_final_answer_stream(
                    run_context=run_context,
                    system_prompt=context.system_prompt,
                    messages=tool_context_window.render_messages(),
                    original_user_message=run_input.user_message,
                    previous_tool_calls=used_tool_calls,
                    channel=channel,
                )
                answer = answer or _deterministic_final_answer_fallback(pending_runtime_plan)
                break
            if terminal_workflow_results and all(terminal_workflow_results):
                answer = await self._recover_final_answer_stream(
                    run_context=run_context,
                    system_prompt=context.system_prompt,
                    messages=tool_context_window.render_messages(),
                    original_user_message=run_input.user_message,
                    previous_tool_calls=used_tool_calls,
                    channel=channel,
                )
                answer = answer or "(no answer)"
                break
            if progress_tracker.should_finalize():
                stop_reason = progress_tracker.stop_reason or "tool_loop_stagnation"
                await self._event_recorder.record_async(
                    context=run_context,
                    event_type="workflow_runtime_decision",
                    payload={
                        "policy": "finalize",
                        "reason": "tool_loop_stagnation",
                        "stop_reason": stop_reason,
                        "business_tool_rounds": business_tool_rounds,
                        "schema_search_rounds": schema_search_rounds,
                        "soft_budget_exceeded": progress_tracker.soft_budget_exceeded,
                    },
                    channel=channel,
                )
                tool_context_window.append_runtime_notice(_tool_loop_stagnation_notice(stop_reason))
                answer = await self._recover_final_answer_stream(
                    run_context=run_context,
                    system_prompt=context.system_prompt,
                    messages=tool_context_window.render_messages(),
                    original_user_message=run_input.user_message,
                    previous_tool_calls=used_tool_calls,
                    channel=channel,
                )
                answer = answer or _deterministic_final_answer_fallback(pending_runtime_plan)
                break
            round_index += 1

        if not answer and round_index > max_model_rounds:
            await self._event_recorder.record_async(
                context=run_context,
                event_type="workflow_runtime_decision",
                payload={
                    "policy": "finalize",
                    "reason": "hard_model_round_limit_reached",
                    "max_model_rounds": max_model_rounds,
                },
                channel=channel,
            )
            answer = await self._recover_final_answer_stream(
                run_context=run_context,
                system_prompt=context.system_prompt,
                messages=tool_context_window.render_messages(),
                original_user_message=run_input.user_message,
                previous_tool_calls=used_tool_calls,
                channel=channel,
            )
            answer = answer or _deterministic_final_answer_fallback(pending_runtime_plan)
        if not answer and _is_premature_workflow_answer(
            pending_runtime_plan=pending_runtime_plan,
            tool_reveal_state=tool_reveal_state,
        ):
            answer = workflow_incomplete_answer(pending_runtime_plan)
        if not answer:
            answer = "(no answer)"
        answer = await self._sanitize_final_answer_stream(
            answer=answer,
            run_context=run_context,
            system_prompt=context.system_prompt,
            messages=tool_context_window.render_messages(),
            original_user_message=run_input.user_message,
            previous_tool_calls=used_tool_calls,
            channel=channel,
            pending_runtime_plan=pending_runtime_plan,
        )

        await self._event_recorder.record_async(
            context=run_context,
            event_type="assistant_message",
            payload={"content": answer},
            channel=channel,
        )
        await self._event_recorder.record_async(
            context=run_context,
            event_type="run_finished",
            payload={"answer_length": len(answer), "tool_calls": len(used_tool_calls)},
            channel=channel,
        )
        self._dispatch_post_run_maintenance_async(run_context)
        _logger.info(
            "流式 agent run 完成: session_id=%s answer_len=%s tool_calls=%s",
            session_id,
            len(answer),
            len(used_tool_calls),
        )

        return AgentRunOutput(
            session_id=session_id,
            answer=answer,
            tool_calls=used_tool_calls,
            memory_hits=context.memory_hits,
        )

    def _dispatch_post_run_maintenance_sync(self, context: RunContext) -> None:
        self._post_run_maintenance.dispatch_sync(context)

    def _dispatch_post_run_maintenance_async(self, context: RunContext) -> None:
        self._post_run_maintenance.dispatch_async(context)

    def _inspect_workflow_guard(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        if self._workflow_guard is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        return self._workflow_guard.inspect(tool_call, context)

    def _initial_visible_tool_names(self, runtime_plan_tool_names: list[str]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for raw_name in [*self._tool_schema_always_visible, *runtime_plan_tool_names]:
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            name = raw_name.strip()
            if name in seen:
                continue
            output.append(name)
            seen.add(name)
        return output

    def _sanitize_final_answer_sync(
        self,
        *,
        answer: str,
        run_context: RunContext,
        system_prompt: str,
        messages: list[dict[str, Any]],
        original_user_message: str,
        pending_runtime_plan: dict[str, Any] | None,
    ) -> str:
        normalized = (answer or "").strip()
        rejection_reason = _final_answer_rejection_reason(
            normalized,
            pending_runtime_plan=pending_runtime_plan,
        )
        if rejection_reason is None:
            return normalized or "(no answer)"
        self._event_recorder.record(
            context=run_context,
            event_type="assistant_answer_rejected",
            payload={"reason": rejection_reason, "content_preview": normalized[:160]},
        )
        recovered = self._recover_final_answer(
            run_context=run_context,
            system_prompt=system_prompt,
            messages=messages,
            original_user_message=original_user_message,
        )
        recovered_rejection_reason = _final_answer_rejection_reason(
            recovered,
            pending_runtime_plan=pending_runtime_plan,
        )
        if recovered and recovered_rejection_reason is None:
            return recovered
        if recovered:
            self._event_recorder.record(
                context=run_context,
                event_type="assistant_answer_rejected",
                payload={
                    "reason": f"{recovered_rejection_reason or 'empty'}_after_recovery",
                    "content_preview": recovered[:160],
                },
            )
        return _deterministic_final_answer_fallback(pending_runtime_plan)

    async def _sanitize_final_answer_stream(
        self,
        *,
        answer: str,
        run_context: RunContext,
        system_prompt: str,
        messages: list[dict[str, Any]],
        original_user_message: str,
        previous_tool_calls: list[ToolCall],
        channel: EventChannel,
        pending_runtime_plan: dict[str, Any] | None,
    ) -> str:
        normalized = (answer or "").strip()
        rejection_reason = _final_answer_rejection_reason(
            normalized,
            pending_runtime_plan=pending_runtime_plan,
        )
        if rejection_reason is None:
            return normalized or "(no answer)"
        await self._event_recorder.record_async(
            context=run_context,
            event_type="assistant_answer_rejected",
            payload={"reason": rejection_reason, "content_preview": normalized[:160]},
            channel=channel,
        )
        recovered = await self._recover_final_answer_stream(
            run_context=run_context,
            system_prompt=system_prompt,
            messages=messages,
            original_user_message=original_user_message,
            previous_tool_calls=previous_tool_calls,
            channel=channel,
        )
        recovered_rejection_reason = _final_answer_rejection_reason(
            recovered,
            pending_runtime_plan=pending_runtime_plan,
        )
        if recovered and recovered_rejection_reason is None:
            return recovered
        if recovered:
            await self._event_recorder.record_async(
                context=run_context,
                event_type="assistant_answer_rejected",
                payload={
                    "reason": f"{recovered_rejection_reason or 'empty'}_after_recovery",
                    "content_preview": recovered[:160],
                },
                channel=channel,
            )
        return _deterministic_final_answer_fallback(pending_runtime_plan)

    def _recover_final_answer(
        self,
        *,
        run_context: RunContext,
        system_prompt: str,
        messages: list[dict[str, Any]],
        original_user_message: str,
    ) -> str:
        _logger.warning("最终轮未返回正文，触发同步补答: user_message=%s", original_user_message[:120])
        recovery_messages = [
            *messages,
            {
                "role": "assistant",
                "content": FINAL_ANSWER_RECOVERY_PROMPT,
            },
        ]
        model_response = self._model_client.generate(
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
        )
        self._record_llm_usage(
            run_context=run_context,
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
            model_response=model_response,
            tool_calls=ensure_tool_call_ids(model_response.tool_calls),
            mode="sync",
            phase="final_answer_recovery",
            round_index=None,
        )
        if model_response.tool_calls:
            _logger.warning("补答轮仍返回 tool_calls，已忽略: tool_call_count=%s", len(model_response.tool_calls))
        return (model_response.content or "").strip()

    async def _recover_final_answer_stream(
        self,
        *,
        run_context: RunContext,
        system_prompt: str,
        messages: list[dict[str, Any]],
        original_user_message: str,
        previous_tool_calls: list[ToolCall],
        channel: EventChannel,
    ) -> str:
        _logger.warning("最终轮未返回正文，触发流式补答: user_message=%s", original_user_message[:120])
        recovery_messages = [
            *messages,
            {
                "role": "assistant",
                "content": FINAL_ANSWER_RECOVERY_PROMPT,
            },
        ]
        parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: TokenUsage | None = None
        model: str | None = None
        resolved_tool_calls: list[ToolCall] = []
        async for chunk in self._model_client.generate_stream(
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
        ):
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.reasoning_delta:
                reasoning_parts.append(chunk.reasoning_delta)
            if chunk.usage is not None:
                usage = chunk.usage
            if chunk.model:
                model = chunk.model
            if chunk.finished:
                resolved_tool_calls = ensure_tool_call_ids(chunk.tool_calls or [])
        await self._record_llm_usage_async(
            run_context=run_context,
            system_prompt=system_prompt,
            messages=recovery_messages,
            tools=[],
            content="".join(parts).strip(),
            reasoning_content="".join(reasoning_parts).strip(),
            tool_calls=resolved_tool_calls,
            usage=usage,
            model=model,
            mode="stream",
            phase="final_answer_recovery",
            round_index=None,
            channel=channel,
        )
        return "".join(parts).strip()

    async def _emit_stream_answer_meta_if_changed(
        self,
        *,
        channel: EventChannel,
        content: str,
        tool_calls: list[ToolCall],
        previous_meta: tuple[str, str, str, str, str] | None,
    ) -> tuple[str, str, str, str, str] | None:
        normalized = self._answer_normalizer.normalize_assistant_message(
            content,
            tool_calls=tool_calls,
        )
        artifact_signature = "|".join(
            f"{item.type}:{item.path}:{item.role}" for item in normalized.artifacts
        )
        current_meta = (
            normalized.answer_format,
            normalized.render_hint,
            normalized.layout_hint,
            normalized.source_kind,
            artifact_signature,
        )
        if current_meta == previous_meta:
            return previous_meta
        await channel.emit(
            "answer_meta",
            {
                "answer_format": normalized.answer_format,
                "render_hint": normalized.render_hint,
                "layout_hint": normalized.layout_hint,
                "source_kind": normalized.source_kind,
                "artifacts": [
                    {
                        "type": item.type,
                        "path": item.path,
                        "role": item.role,
                    }
                    for item in normalized.artifacts
                ],
            },
        )
        return current_meta

    def _record_llm_usage(
        self,
        *,
        run_context: RunContext,
        system_prompt: str,
        system_prompt_sections: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model_response: ModelResponse,
        tool_calls: list[ToolCall],
        mode: str,
        phase: str,
        round_index: int | None,
        tool_disclosure: dict[str, Any] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> None:
        payload = _build_llm_usage_payload(
            system_prompt=system_prompt,
            system_prompt_sections=system_prompt_sections,
            messages=messages,
            tools=tools,
            content=model_response.content,
            reasoning_content=model_response.reasoning_content,
            tool_calls=tool_calls,
            usage=model_response.usage,
            model=model_response.model or _client_model_name(self._model_client),
            mode=mode,
            phase=phase,
            round_index=round_index,
            tool_disclosure=tool_disclosure,
            tool_context=tool_context,
        )
        self._event_recorder.record(
            context=run_context,
            event_type="llm_usage",
            payload=payload,
        )

    async def _record_llm_usage_async(
        self,
        *,
        run_context: RunContext,
        system_prompt: str,
        system_prompt_sections: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        content: str,
        reasoning_content: str,
        tool_calls: list[ToolCall],
        usage: TokenUsage | None,
        model: str | None,
        mode: str,
        phase: str,
        round_index: int | None,
        channel: EventChannel,
        tool_disclosure: dict[str, Any] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> None:
        payload = _build_llm_usage_payload(
            system_prompt=system_prompt,
            system_prompt_sections=system_prompt_sections,
            messages=messages,
            tools=tools,
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            usage=usage,
            model=model or _client_model_name(self._model_client),
            mode=mode,
            phase=phase,
            round_index=round_index,
            tool_disclosure=tool_disclosure,
            tool_context=tool_context,
        )
        await self._event_recorder.record_async(
            context=run_context,
            event_type="llm_usage",
            payload=payload,
            channel=channel,
        )

    def _resolve_run_context(self, session_id: str, run_input: AgentRunInput) -> RunContext:
        if run_input.context is None:
            raise ValidationError("run_input.context is required.")
        if run_input.context.session_id != session_id:
            raise ValidationError("run_input.context.session_id must match resolved session_id.")
        return run_input.context

    def _tool_schema_disclosure_mode_for_context(self, context: RunContext) -> str:
        if self._tool_schema_disclosure_mode != "search":
            return "full"
        if context.agent_id == "agent_main" and context.agent_id == context.entry_agent_id:
            return "search"
        return "full"


def _is_schema_search_only(tool_calls: list[ToolCall]) -> bool:
    return bool(tool_calls) and all(tool_call.name == _SCHEMA_SEARCH_TOOL_NAME for tool_call in tool_calls)


def _looks_like_text_tool_invocation(content: str) -> bool:
    normalized = content.strip()
    return bool(_TEXT_TOOL_INVOCATION_RE.fullmatch(normalized) or _contains_tool_call_markup(normalized))


def _strict_runtime_tool_mode(
    *,
    tool_reveal_state: ToolRevealState,
    pending_runtime_plan: dict[str, Any] | None,
) -> bool:
    if pending_runtime_plan is None or pending_runtime_plan.get("final_answer_ready") is True:
        return False
    completion_tools = runtime_plan_completion_tools(pending_runtime_plan)
    if len(completion_tools) != 1:
        return False
    return tool_reveal_state.is_visible(completion_tools[0])


def _strict_runtime_plan_notice(pending_runtime_plan: dict[str, Any] | None) -> str:
    completion_tools = runtime_plan_completion_tools(pending_runtime_plan or {})
    required_tool = completion_tools[0] if len(completion_tools) == 1 else "未明确"
    raw_known_refs = pending_runtime_plan.get("known_refs") if pending_runtime_plan is not None else None
    known_refs: dict[str, Any] = raw_known_refs if isinstance(raw_known_refs, dict) else {}
    hint = build_required_tool_call_hint(required_tool, known_refs) if required_tool != "未明确" else None
    missing_outputs = ", ".join(_string_list_from_runtime_plan((pending_runtime_plan or {}).get("missing_outputs")))
    lines = [
        f"运行时守卫：当前 workflow 已锁定唯一下一步工具：{required_tool}。",
        "本轮没有工具搜索阶段；不要调用 tool_search、memory_write、get/list 或其它隐藏工具。",
        f"直接调用 {required_tool}。",
    ]
    if missing_outputs:
        lines.append(f"仍缺少产物：{missing_outputs}。")
    if hint is not None:
        lines.append(f"参数提示：{json.dumps(hint, ensure_ascii=False)}")
    report_contract_notice = _report_artifact_contract_notice(pending_runtime_plan)
    if report_contract_notice is not None:
        lines.append(report_contract_notice)
    return "\n".join(lines)


def _report_artifact_contract_notice(pending_runtime_plan: dict[str, Any] | None) -> str | None:
    if pending_runtime_plan is None:
        return None
    raw_contract = pending_runtime_plan.get("report_artifact_contract")
    if not isinstance(raw_contract, dict):
        return None
    contract = {
        "supported_candidate_facts": raw_contract.get("supported_candidate_facts"),
        "unsupported_candidate_facts": raw_contract.get("unsupported_candidate_facts"),
        "rewrite_rules": raw_contract.get("rewrite_rules"),
        "artifact_rules": raw_contract.get("artifact_rules"),
    }
    content = json.dumps(_shorten_runtime_notice_payload(contract), ensure_ascii=False, separators=(",", ":"))
    if len(content) > 1400:
        content = content[:1399] + "…"
    return "匹配报告事实边界：生成报告正文时只把 supported_candidate_facts 当作候选人事实；unsupported_candidate_facts 只能写入差距/风险/面试准备。\n" + content


def _visible_tool_definitions_for_runtime_plan(
    *,
    tool_reveal_state: ToolRevealState,
    pending_runtime_plan: dict[str, Any] | None,
) -> list[Any]:
    visible_definitions = tool_reveal_state.visible_definitions()
    if pending_runtime_plan is None:
        return visible_definitions
    if pending_runtime_plan.get("final_answer_ready") is True:
        return []
    required_tool_is_visible = any(
        tool_reveal_state.is_visible(tool_name) for tool_name in runtime_plan_completion_tools(pending_runtime_plan)
    )
    if not required_tool_is_visible:
        return visible_definitions
    completion_tools = set(runtime_plan_completion_tools(pending_runtime_plan))
    allowed_tools = completion_tools | set(runtime_plan_next_allowed_tools(pending_runtime_plan))
    if len(completion_tools) == 1:
        return [definition for definition in visible_definitions if definition.name in allowed_tools]
    hidden_tools = set(runtime_plan_discouraged_tools(pending_runtime_plan)) - allowed_tools
    hidden_tools.add(_SCHEMA_SEARCH_TOOL_NAME)
    return [definition for definition in visible_definitions if definition.name not in hidden_tools]


def _strict_required_tool_auto_call(
    tool_call: ToolCall,
    *,
    pending_runtime_plan: dict[str, Any] | None,
    visible_tool_names_for_round: set[str],
) -> ToolCall | None:
    return _strict_required_tool_auto_call_from_plan(
        pending_runtime_plan=pending_runtime_plan,
        visible_tool_names_for_round=visible_tool_names_for_round,
        tool_call_id=tool_call.tool_call_id,
    )


def _strict_required_tool_auto_call_from_plan(
    *,
    pending_runtime_plan: dict[str, Any] | None,
    visible_tool_names_for_round: set[str],
    tool_call_id: str | None = None,
) -> ToolCall | None:
    if pending_runtime_plan is None or pending_runtime_plan.get("final_answer_ready") is True:
        return None
    completion_tools = runtime_plan_completion_tools(pending_runtime_plan)
    if len(completion_tools) != 1:
        return None
    required_tool = completion_tools[0]
    if required_tool not in _STRICT_AUTO_EXECUTE_REQUIRED_TOOLS:
        return None
    if required_tool not in visible_tool_names_for_round:
        return None
    raw_known_refs = pending_runtime_plan.get("known_refs")
    known_refs: dict[str, Any] = raw_known_refs if isinstance(raw_known_refs, dict) else {}
    hint = build_required_tool_call_hint(required_tool, known_refs)
    if hint is None:
        return None
    if _string_list_from_runtime_plan(hint.get("missing_args")):
        if required_tool != "career_resume_version_create":
            return None
    if required_tool == "career_resume_version_create":
        raw_arguments = _strict_resume_version_create_auto_args(hint)
    else:
        raw_arguments = hint.get("retry_tool_call_skeleton")
        if not isinstance(raw_arguments, dict):
            raw_arguments = hint.get("available_args")
    if not isinstance(raw_arguments, dict) or not raw_arguments:
        return None
    arguments = json.loads(json.dumps(raw_arguments, ensure_ascii=False))
    return ToolCall(name=required_tool, arguments=arguments, tool_call_id=tool_call_id)


def _strict_resume_version_create_auto_args(hint: dict[str, Any]) -> dict[str, Any] | None:
    missing_args = _string_list_from_runtime_plan(hint.get("missing_args"))
    blocking_missing_args = [item for item in missing_args if item != "content_or_artifact_id"]
    if blocking_missing_args:
        return None
    available_args = hint.get("available_args")
    if not isinstance(available_args, dict):
        return None
    required_fields = ("base_resume_profile_id", "target_jd_analysis_id", "evidence_refs")
    if any(field not in available_args for field in required_fields):
        return None
    arguments = dict(available_args)
    if _non_empty_string(arguments.get("artifact_id")) is None and _non_empty_string(arguments.get("content")) is None:
        arguments["use_safe_fallback"] = True
    return arguments


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _hidden_runtime_support_tool_allowed(
    tool_call: ToolCall,
    *,
    pending_runtime_plan: dict[str, Any] | None,
) -> bool:
    if pending_runtime_plan is None or pending_runtime_plan.get("final_answer_ready") is True:
        return False
    if pending_runtime_plan.get("phase") != "resume_version":
        return False
    if tool_call.name != "session_create_text_artifact":
        return False
    if "resume_version" not in _string_list_from_runtime_plan(pending_runtime_plan.get("missing_outputs")):
        return False
    arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
    title = arguments.get("title")
    kind = arguments.get("kind")
    if kind is not None and kind != "generated_file":
        return False
    return isinstance(title, str) and _looks_like_resume_version_artifact_title(title)


def _looks_like_resume_version_artifact_title(title: str) -> bool:
    normalized = title.strip().casefold()
    compact = "".join(ch for ch in normalized if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if "简历" in compact and ("诊断" in compact or "画像" in compact):
        return False
    if "简历版本" in compact or "定制简历" in compact:
        return True
    return "resume" in compact and "version" in compact


def _hidden_runtime_tool_names_to_suppress(
    tool_calls: list[ToolCall],
    *,
    pending_runtime_plan: dict[str, Any] | None,
    visible_tool_names_for_round: set[str],
    strict_runtime_tool_mode: bool,
) -> list[str]:
    if pending_runtime_plan is None or not tool_calls:
        return []
    if not _is_final_answer_ready_runtime_plan(pending_runtime_plan) and not any(
        tool_name in visible_tool_names_for_round for tool_name in runtime_plan_completion_tools(pending_runtime_plan)
    ):
        return []
    blocked: list[str] = []
    for tool_call in tool_calls:
        if tool_call.name in visible_tool_names_for_round:
            return []
        if _hidden_runtime_support_tool_allowed(tool_call, pending_runtime_plan=pending_runtime_plan):
            return []
        if strict_runtime_tool_mode and _strict_required_tool_auto_call(
            tool_call,
            pending_runtime_plan=pending_runtime_plan,
            visible_tool_names_for_round=visible_tool_names_for_round,
        ) is not None:
            return []
        blocked.append(tool_call.name)
    output: list[str] = []
    seen: set[str] = set()
    for name in blocked:
        if name in seen:
            continue
        output.append(name)
        seen.add(name)
    return output


def _hidden_runtime_tool_suppression_key(
    *,
    pending_runtime_plan: dict[str, Any] | None,
    hidden_tool_names: list[str],
) -> str:
    raw_refs = pending_runtime_plan.get("known_refs") if pending_runtime_plan is not None else None
    known_refs = raw_refs if isinstance(raw_refs, dict) else {}
    payload = {
        "phase": pending_runtime_plan.get("phase") if pending_runtime_plan is not None else None,
        "required_tools": runtime_plan_completion_tools(pending_runtime_plan or {}),
        "missing_outputs": _string_list_from_runtime_plan(
            pending_runtime_plan.get("missing_outputs") if pending_runtime_plan is not None else None
        ),
        "blocked_tools": hidden_tool_names,
        "known_ref_keys": sorted(str(key) for key in known_refs),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _strict_auto_execute_event_payload(
    *,
    blocked_tool_call: ToolCall | None,
    replacement_tool_call: ToolCall,
    pending_runtime_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    raw_known_refs = pending_runtime_plan.get("known_refs") if pending_runtime_plan is not None else None
    known_refs: dict[str, Any] = raw_known_refs if isinstance(raw_known_refs, dict) else {}
    reason = (
        "strict_premature_answer_replaced_with_required_tool"
        if blocked_tool_call is None
        else "strict_hidden_tool_replaced_with_required_tool"
    )
    return {
        "workflow_runtime_result": True,
        "policy": "repair",
        "reason": reason,
        "strict_runtime_plan": True,
        "tool_executed": True,
        "blocked_tool_name": blocked_tool_call.name if blocked_tool_call is not None else None,
        "tool_name": replacement_tool_call.name,
        "required_tool": replacement_tool_call.name,
        "required_tool_call_hint": build_required_tool_call_hint(replacement_tool_call.name, known_refs),
    }


def _is_premature_workflow_answer(
    *,
    pending_runtime_plan: dict[str, Any] | None,
    tool_reveal_state: ToolRevealState,
) -> bool:
    visible_tool_names = {definition.name for definition in tool_reveal_state.visible_definitions()}
    return is_premature_runtime_plan_answer(
        pending_runtime_plan=pending_runtime_plan,
        visible_tool_names=visible_tool_names,
    )


def _is_final_answer_ready_runtime_plan(pending_runtime_plan: dict[str, Any] | None) -> bool:
    return pending_runtime_plan is not None and pending_runtime_plan.get("final_answer_ready") is True


def _hard_model_round_limit(max_tool_rounds: int) -> int:
    return max(
        _HARD_MODEL_ROUND_FLOOR,
        max_tool_rounds * _HARD_MODEL_ROUND_MULTIPLIER + _MAX_SCHEMA_SEARCH_ROUNDS + 1,
    )


def _contains_internal_final_answer(content: str) -> bool:
    normalized = content.strip()
    if not normalized:
        return False
    return any(marker in normalized for marker in _INTERNAL_FINAL_ANSWER_MARKERS)


def _final_answer_rejection_reason(
    content: str,
    *,
    pending_runtime_plan: dict[str, Any] | None,
) -> str | None:
    normalized = content.strip()
    if not normalized:
        return None
    if _looks_like_text_tool_invocation(normalized):
        return "tool_call_markup"
    if _contains_internal_final_answer(normalized):
        return "internal_runtime_text"
    if _looks_like_weak_completed_workflow_answer(normalized, pending_runtime_plan=pending_runtime_plan):
        return "weak_completed_workflow_answer"
    return None


def _contains_tool_call_markup(content: str) -> bool:
    return bool(_TEXT_TOOL_CALL_MARKUP_RE.search(content))


def _looks_like_weak_completed_workflow_answer(
    content: str,
    *,
    pending_runtime_plan: dict[str, Any] | None,
) -> bool:
    normalized = " ".join(content.strip().split())
    if normalized in _WEAK_FINAL_ANSWER_EXACT:
        return True
    if pending_runtime_plan is None or pending_runtime_plan.get("final_answer_ready") is not True:
        return False
    return any(pattern.search(normalized) for pattern in _WEAK_COMPLETED_WORKFLOW_ACTION_PATTERNS)


def _deterministic_final_answer_fallback(pending_runtime_plan: dict[str, Any] | None) -> str:
    if pending_runtime_plan is None:
        return "当前没有生成可用的最终答复。我已停止继续执行重复步骤，避免无效消耗；请补充关键信息后再试。"

    missing_outputs = _string_list_from_runtime_plan(pending_runtime_plan.get("missing_outputs"))
    next_action = pending_runtime_plan.get("next_action")
    if pending_runtime_plan.get("final_answer_ready") is True:
        return _deterministic_completed_workflow_answer(pending_runtime_plan)
    if missing_outputs:
        missing_text = "、".join(missing_outputs)
        if isinstance(next_action, str) and next_action.strip():
            return f"当前阶段还缺少：{missing_text}。已停止继续执行重复步骤；下一步建议：{next_action.strip()}"
        return f"当前阶段还缺少：{missing_text}。已停止继续执行重复步骤；请补充必要信息后再试。"
    if isinstance(next_action, str) and next_action.strip():
        return f"已停止继续执行重复步骤。下一步建议：{next_action.strip()}"
    return "当前没有生成可用的最终答复。我已停止继续执行重复步骤，避免无效消耗；请补充关键信息后再试。"


def _deterministic_completed_workflow_answer(pending_runtime_plan: dict[str, Any]) -> str:
    phase = pending_runtime_plan.get("phase")
    phase_name = _workflow_phase_display_name(phase)
    known_refs = _runtime_plan_known_refs(pending_runtime_plan)
    lines = [f"{phase_name}已完成，关键产物已经写入系统。"]
    ref_lines = _workflow_ref_summary_lines(known_refs)
    if ref_lines:
        lines.append("")
        lines.append("产物清单：")
        lines.extend(ref_lines)
    next_step = _workflow_completed_next_step(phase)
    if next_step:
        lines.append("")
        lines.append(next_step)
    return "\n".join(lines)


def _workflow_phase_display_name(phase: Any) -> str:
    if phase == "resume_diagnosis":
        return "简历诊断与画像沉淀"
    if phase == "jd_fit":
        return "JD 分析与岗位匹配"
    if phase == "resume_version":
        return "定制简历版本生成"
    if phase == "application_action":
        return "求职项目更新"
    return "当前阶段"


def _workflow_completed_next_step(phase: Any) -> str | None:
    if phase == "resume_diagnosis":
        return "下一步可以继续进行 JD 匹配分析，或基于已有画像推进求职项目。"
    if phase == "jd_fit":
        return "下一步可以基于匹配结果生成定制简历，或继续推进当前求职项目。"
    if phase == "resume_version":
        return "定制简历版本已关联到求职项目，可以继续查看、修改或推进投递准备。"
    if phase == "application_action":
        return "求职项目已更新，可以继续查看项目状态或执行下一步动作。"
    return None


def _workflow_ref_summary_lines(known_refs: dict[str, Any]) -> list[str]:
    labels = {
        "resume_profile_id": "ResumeProfile",
        "career_profile_id": "CareerProfile",
        "diagnosis_artifact_id": "简历诊断报告",
        "jd_analysis_id": "JDAnalysis",
        "job_fit_report_id": "JobFitReport",
        "report_artifact_id": "匹配报告 artifact",
        "application_id": "CareerApplication",
        "resume_version_id": "ResumeVersion",
        "resume_version_artifact_id": "定制简历 artifact",
    }
    output: list[str] = []
    for key, label in labels.items():
        value = known_refs.get(key)
        if isinstance(value, str) and value.strip():
            output.append(f"- {label}: `{value.strip()}`")
    return output


def _tool_loop_stagnation_notice(stop_reason: str) -> str:
    return (
        "Runtime notice: 当前工具循环没有产生新的记录、文件或阶段推进。"
        f" stop_reason={stop_reason}。"
        " 不要继续调用工具；请基于已经完成的上下文生成最终回答。"
    )


def _tool_call_fingerprint(tool_call: ToolCall) -> str:
    return json.dumps(
        {
            "name": tool_call.name,
            "arguments": _fingerprint_value(tool_call.arguments),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _fingerprint_value(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, list):
        return [_fingerprint_value(item) for item in value[:20]]
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) <= 180:
            return stripped
        return {"prefix": stripped[:120], "chars": len(stripped)}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _runtime_plan_known_refs(plan: dict[str, Any] | None) -> dict[str, Any]:
    if plan is None:
        return {}
    raw_refs = plan.get("known_refs")
    if not isinstance(raw_refs, dict):
        return {}
    return {str(key): value for key, value in raw_refs.items() if isinstance(key, str) and value is not None}


def _runtime_plan_with_known_refs(plan: dict[str, Any] | None, known_refs: dict[str, Any]) -> dict[str, Any] | None:
    if not known_refs:
        return plan
    if plan is None:
        return {"known_refs": dict(known_refs)}
    merged = dict(plan)
    raw_refs = merged.get("known_refs")
    refs = dict(raw_refs) if isinstance(raw_refs, dict) else {}
    refs.update(known_refs)
    merged["known_refs"] = refs
    return merged


def _runtime_plan_progressed(*, before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    if before == after:
        return False
    if after is None:
        return False
    if before is None:
        return True
    if after.get("final_answer_ready") is True and before.get("final_answer_ready") is not True:
        return True
    before_missing = set(_string_list_from_runtime_plan(before.get("missing_outputs")))
    after_missing = set(_string_list_from_runtime_plan(after.get("missing_outputs")))
    if len(after_missing) < len(before_missing):
        return True
    before_required = set(_string_list_from_runtime_plan(before.get("required_tools")))
    after_required = set(_string_list_from_runtime_plan(after.get("required_tools")))
    if after_required != before_required:
        return True
    before_next = set(_string_list_from_runtime_plan(before.get("next_allowed_tools")))
    after_next = set(_string_list_from_runtime_plan(after.get("next_allowed_tools")))
    return after_next != before_next


def _extract_progress_refs(result: ToolExecutionResult) -> set[str]:
    if not result.success:
        return set()
    payload = _json_object(result.content)
    if payload is None:
        return set()
    refs: set[str] = set()
    for key in ("record_id", "artifact_id", "source_artifact_id", "report_artifact_id", "diagnosis_artifact_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            refs.add(f"{key}:{value.strip()}")
    record = payload.get("record")
    if isinstance(record, dict):
        for key in ("record_id", "artifact_id", "resume_version_id", "application_id", "jd_analysis_id", "job_fit_report_id"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                refs.add(f"{key}:{value.strip()}")
    for key in ("product_refs", "output_artifact_refs", "artifact_refs", "revealed_tool_names"):
        raw_values = payload.get(key)
        if isinstance(raw_values, list):
            for value in raw_values:
                if isinstance(value, str) and value.strip():
                    refs.add(f"{key}:{value.strip()}")
    return refs


def _is_runtime_hidden_result(result: ToolExecutionResult) -> bool:
    payload = _json_object(result.content)
    if payload is None:
        return False
    return payload.get("event_type") == "tool_schema_not_revealed" or payload.get("reason") in {
        "tool_hidden_by_runtime_plan",
        "final_answer_ready_no_more_tools",
    }


def _skip_stagnation_observation_for_suppressed_schema_search(
    *,
    notice_index: int,
    tool_call: ToolCall,
    result: ToolExecutionResult,
) -> bool:
    return (
        0 < notice_index <= _MAX_SUPPRESSED_REQUIRED_SCHEMA_SEARCH_RETRY_ROUNDS
        and tool_call.name == _SCHEMA_SEARCH_TOOL_NAME
        and _is_runtime_hidden_result(result)
    )


def _tool_error_signature(result: ToolExecutionResult) -> str | None:
    if result.success:
        return None
    payload = _json_object(result.content)
    if payload is not None:
        code = payload.get("error_code") or payload.get("code") or payload.get("reason")
        if isinstance(code, str) and code.strip():
            return f"{result.tool_name}:{code.strip()}"
    content = result.content.strip()
    if not content:
        return result.tool_name
    return f"{result.tool_name}:{content[:160]}"


def _json_object(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _shorten_runtime_notice_payload(value: Any) -> Any:
    if isinstance(value, str):
        stripped = " ".join(value.strip().split())
        return stripped if len(stripped) <= 220 else stripped[:219] + "…"
    if isinstance(value, list):
        return [_shorten_runtime_notice_payload(item) for item in value[:12]]
    if isinstance(value, dict):
        return {
            str(key): _shorten_runtime_notice_payload(item)
            for key, item in list(value.items())[:12]
            if isinstance(key, str) and item not in (None, [], {})
        }
    return value


def _string_list_from_runtime_plan(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return output


def _is_terminal_workflow_result(result: ToolExecutionResult) -> bool:
    if not result.success:
        return False
    try:
        payload = json.loads(result.content)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("workflow_runtime_result") is True
        and payload.get("policy") == "block"
        and payload.get("terminal") is True
    )


def _build_llm_usage_payload(
    *,
    system_prompt: str,
    system_prompt_sections: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    content: str,
    reasoning_content: str,
    tool_calls: list[ToolCall],
    usage: TokenUsage | None,
    model: str | None,
    mode: str,
    phase: str,
    round_index: int | None,
    tool_disclosure: dict[str, Any] | None = None,
    tool_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_usage = usage or _estimate_usage(
        system_prompt=system_prompt,
        messages=messages,
        tools=tools,
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
    )
    payload: dict[str, Any] = {
        "api": "POST /v1/chat/completions",
        "operation": "model.generate_stream" if mode == "stream" else "model.generate",
        "mode": mode,
        "phase": phase,
        "round_index": round_index,
        "model": model or "unknown",
        "prompt_tokens": normalized_usage.prompt_tokens,
        "completion_tokens": normalized_usage.completion_tokens,
        "total_tokens": normalized_usage.total_tokens,
        "estimated": normalized_usage.estimated,
        "usage_source": normalized_usage.source,
        "message_count": len(messages) + 1,
        "tool_schema_count": len(tools),
        "returned_tool_call_count": len(tool_calls),
        "content_chars": len(content or ""),
        "reasoning_chars": len(reasoning_content or ""),
    }
    payload.update(
        _estimate_prompt_breakdown(
            system_prompt=system_prompt,
            system_prompt_sections=system_prompt_sections,
            messages=messages,
            tools=tools,
        )
    )
    if tool_disclosure:
        payload.update(tool_disclosure)
    if tool_context:
        payload.update(tool_context)
    return payload


def _estimate_prompt_breakdown(
    *,
    system_prompt: str,
    system_prompt_sections: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    message_tokens_by_role = {
        "assistant": 0,
        "other": 0,
        "tool": 0,
        "user": 0,
    }
    for message in messages:
        role = str(message.get("role") or "other")
        role_key = role if role in message_tokens_by_role else "other"
        message_tokens_by_role[role_key] += estimate_tokens_from_object(message)

    system_tokens = estimate_tokens_from_text(system_prompt)
    section_items = _normalize_system_prompt_sections(system_prompt_sections or [])
    workflow_rule_sections = [item for item in section_items if item.get("name") == "workflow_rules"]
    workflow_rule_pack_names: list[str] = []
    workflow_rule_selection_mode = "none"
    workflow_rules_tokens = 0
    for section in workflow_rule_sections:
        workflow_rules_tokens += _safe_int(section.get("tokens"))
        raw_mode = section.get("selection_mode")
        if isinstance(raw_mode, str) and raw_mode.strip():
            workflow_rule_selection_mode = raw_mode.strip()
        raw_pack_names = section.get("pack_names")
        if isinstance(raw_pack_names, list):
            for name in raw_pack_names:
                normalized_name = str(name).strip()
                if normalized_name and normalized_name not in workflow_rule_pack_names:
                    workflow_rule_pack_names.append(normalized_name)
    messages_tokens = estimate_tokens_from_object(messages)
    tools_tokens = estimate_tokens_from_object(tools) if tools else 0
    prompt_estimate_total = estimate_tokens_from_object(
        {
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "tools": tools,
        }
        if tools
        else {"messages": [{"role": "system", "content": system_prompt}, *messages]}
    )
    return {
        "prompt_estimate_total_tokens": prompt_estimate_total,
        "system_prompt_estimate_tokens": system_tokens,
        "system_prompt_section_count": len(section_items),
        "system_prompt_sections": section_items,
        "messages_estimate_tokens": messages_tokens,
        "tools_estimate_tokens": tools_tokens,
        "message_user_estimate_tokens": message_tokens_by_role["user"],
        "message_assistant_estimate_tokens": message_tokens_by_role["assistant"],
        "message_tool_estimate_tokens": message_tokens_by_role["tool"],
        "message_other_estimate_tokens": message_tokens_by_role["other"],
        "workflow_rule_selection_mode": workflow_rule_selection_mode,
        "workflow_rule_pack_names": workflow_rule_pack_names,
        "workflow_rules_estimate_tokens": workflow_rules_tokens,
    }


def _normalize_system_prompt_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        section = {
            "name": name,
            "tokens": _safe_int(item.get("tokens")),
            "chars": _safe_int(item.get("chars")),
            "item_count": _safe_int(item.get("item_count")),
        }
        pack_names = item.get("pack_names")
        if isinstance(pack_names, list):
            section["pack_names"] = [str(pack_name) for pack_name in pack_names if str(pack_name).strip()]
        selection_mode = item.get("selection_mode")
        if isinstance(selection_mode, str) and selection_mode.strip():
            section["selection_mode"] = selection_mode.strip()
        normalized.append(section)
    return normalized


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _estimate_usage(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    content: str,
    reasoning_content: str,
    tool_calls: list[ToolCall],
) -> TokenUsage:
    prompt_payload: dict[str, Any] = {
        "messages": [{"role": "system", "content": system_prompt}, *messages],
    }
    if tools:
        prompt_payload["tools"] = tools
    completion_payload: dict[str, Any] = {
        "content": content,
        "reasoning_content": reasoning_content,
        "tool_calls": [
            {
                "id": item.tool_call_id,
                "name": item.name,
                "arguments": item.arguments,
            }
            for item in tool_calls
        ],
    }
    prompt_tokens = estimate_tokens_from_object(prompt_payload)
    completion_tokens = estimate_tokens_from_object(completion_payload)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        estimated=True,
        source="estimate",
    )


def _client_model_name(client: ChatModelClient) -> str | None:
    raw = getattr(client, "model", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    raw = getattr(client, "_model", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None
