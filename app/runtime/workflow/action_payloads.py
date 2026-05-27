"""Deterministic payload builders for action contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from app.domain.models import ToolCall
from app.runtime.workflow.tool_hints import build_required_tool_call_hint
from app.runtime.workflow.tool_plan import runtime_plan_completion_tools

__all__ = [
    "ActionPayloadBuilder",
    "build_action_payload_tool_call_from_plan",
    "build_required_tool_call_hint_for_plan",
]


@dataclass(frozen=True, slots=True)
class ActionPayloadBuilder:
    """Build deterministic tool payloads from runtime plan refs.

    This boundary owns payloads that can be derived from known refs and a
    contract phase. It should not generate open-ended business content.
    """

    def build_tool_call_from_plan(
        self,
        *,
        pending_runtime_plan: dict[str, Any] | None,
        visible_tool_names_for_round: Iterable[str],
        tool_call_id: str | None = None,
    ) -> ToolCall | None:
        if pending_runtime_plan is None or pending_runtime_plan.get("final_answer_ready") is True:
            return None
        if pending_runtime_plan.get("phase") != "interview_review_update":
            return None
        if runtime_plan_completion_tools(pending_runtime_plan) != ["career_application_merge"]:
            return None
        if "career_application_merge" not in set(visible_tool_names_for_round):
            return None
        missing_outputs = set(_string_list(pending_runtime_plan.get("missing_outputs")))
        if "career_application_update" not in missing_outputs:
            return None
        arguments = self.interview_review_application_merge_arguments(pending_runtime_plan)
        if arguments is None:
            return None
        return ToolCall(name="career_application_merge", arguments=_json_clone(arguments), tool_call_id=tool_call_id)

    def required_tool_call_hint(
        self,
        required_tool: str,
        pending_runtime_plan: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if pending_runtime_plan is None:
            return build_required_tool_call_hint(required_tool, {})
        known_refs = _runtime_plan_known_refs(pending_runtime_plan)
        if pending_runtime_plan.get("phase") == "interview_review_update" and required_tool == "career_application_merge":
            arguments = self.interview_review_application_merge_arguments(pending_runtime_plan)
            missing_args: list[str] = []
            if _non_empty_string(known_refs.get("application_id")) is None and _non_empty_string(
                known_refs.get("related_application_id")
            ) is None:
                missing_args.append("application_id")
            if _non_empty_string(known_refs.get("note_id")) is None and _non_empty_string(known_refs.get("record_id")) is None:
                missing_args.append("note_id")
            if arguments is None:
                return {
                    "tool_name": "career_application_merge",
                    "available_args": {},
                    "missing_args": missing_args or ["evidence_refs"],
                    "retry_tool_call_skeleton": {},
                    "instruction": "面试复盘 Note 已保存后，只调用 career_application_merge 更新当前求职项目；不要 tool_search/get/list。",
                }
            return {
                "tool_name": "career_application_merge",
                "available_args": _json_clone(arguments),
                "missing_args": missing_args,
                "retry_tool_call_skeleton": _json_clone(arguments),
                "instruction": "面试复盘 Note 已保存后，直接用该 payload 调用 career_application_merge；不要 tool_search/get/list。",
            }
        return build_required_tool_call_hint(required_tool, known_refs)

    def interview_review_application_merge_arguments(self, pending_runtime_plan: dict[str, Any]) -> dict[str, Any] | None:
        known_refs = _runtime_plan_known_refs(pending_runtime_plan)
        application_id = _non_empty_string(known_refs.get("application_id")) or _non_empty_string(
            known_refs.get("related_application_id")
        )
        note_id = _non_empty_string(known_refs.get("note_id")) or _non_empty_string(known_refs.get("record_id"))
        if application_id is None or note_id is None:
            return None
        evidence_refs = _interview_review_application_merge_evidence_refs(
            known_refs,
            application_id=application_id,
            note_id=note_id,
        )
        if not evidence_refs:
            return None
        return {
            "application_id": application_id,
            "updates": {
                "stage": "interviewing",
                "next_actions": [
                    f"根据面试复盘 Note {note_id} 补强薄弱问题并准备后续面试。",
                    "复盘下一轮可能追问的系统设计、RAG 评估和工程化问题。",
                ],
                "risks": [
                    f"本次面试复盘仍有待补强问题，详见 Note {note_id}。",
                ],
                "notes": f"面试复盘已保存为 Note {note_id}；项目阶段已更新为面试中。",
            },
            "evidence_refs": evidence_refs,
        }


_DEFAULT_ACTION_PAYLOAD_BUILDER = ActionPayloadBuilder()


def build_action_payload_tool_call_from_plan(
    *,
    pending_runtime_plan: dict[str, Any] | None,
    visible_tool_names_for_round: Iterable[str],
    tool_call_id: str | None = None,
) -> ToolCall | None:
    return _DEFAULT_ACTION_PAYLOAD_BUILDER.build_tool_call_from_plan(
        pending_runtime_plan=pending_runtime_plan,
        visible_tool_names_for_round=visible_tool_names_for_round,
        tool_call_id=tool_call_id,
    )


def build_required_tool_call_hint_for_plan(
    required_tool: str,
    pending_runtime_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _DEFAULT_ACTION_PAYLOAD_BUILDER.required_tool_call_hint(required_tool, pending_runtime_plan)


def _interview_review_application_merge_evidence_refs(
    known_refs: dict[str, Any],
    *,
    application_id: str,
    note_id: str,
) -> list[str]:
    return _dedupe_non_empty_strings(
        [
            application_id,
            note_id,
            _non_empty_string(known_refs.get("resume_profile_id")),
            _non_empty_string(known_refs.get("career_profile_id")),
            _non_empty_string(known_refs.get("jd_analysis_id")),
            _non_empty_string(known_refs.get("job_fit_report_id")),
            _non_empty_string(known_refs.get("report_artifact_id")),
            _non_empty_string(known_refs.get("resume_version_id")),
            _non_empty_string(known_refs.get("resume_source_artifact_id")),
            _non_empty_string(known_refs.get("jd_source_artifact_id")),
            _non_empty_string(known_refs.get("diagnosis_artifact_id")),
            _non_empty_string(known_refs.get("resume_version_artifact_id")),
        ]
    )


def _runtime_plan_known_refs(plan: dict[str, Any] | None) -> dict[str, Any]:
    if plan is None:
        return {}
    raw_refs = plan.get("known_refs")
    if not isinstance(raw_refs, dict):
        return {}
    return {str(key): value for key, value in raw_refs.items() if isinstance(key, str) and value is not None}


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return output


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _dedupe_non_empty_strings(values: list[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None:
            continue
        item = str(raw).strip()
        if not item or item == "None" or item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _json_clone(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))
