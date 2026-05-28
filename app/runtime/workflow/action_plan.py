"""Action-contract runtime plan helpers."""

from __future__ import annotations

from typing import Any

from app.runtime.tool_capabilities import ACTION_WRITE_TOOL_NAMES
from app.runtime.workflow.contracts import ActionContract, ToolStep, builtin_action_contract_registry

__all__ = [
    "ACTION_WRITE_TOOLS",
    "action_contract_for_phase",
    "action_contract_plan_payload",
    "pending_action_plan_after_tool_result",
]

ACTION_WRITE_TOOLS = list(ACTION_WRITE_TOOL_NAMES)

_FINAL_DISCOURAGED_TOOLS = [
    "tool_search",
    "delegate_agents",
    "session_read_artifact",
    "session_list_artifacts",
    "retrieval_search",
    "retrieval_context_pack",
    "career_resume_profile_get",
    "career_jd_analysis_get",
    "career_job_fit_report_get",
    "career_application_get",
    "career_resume_version_get",
]


def action_contract_for_phase(phase: str | None) -> ActionContract | None:
    return builtin_action_contract_registry().contract_for_phase(phase)


def pending_action_plan_after_tool_result(
    tool_name: str,
    *,
    payload_known_refs: dict[str, Any],
    record_id: Any,
    previous_pending_plan: dict[str, Any] | None,
    record_id_ref_key: str | None,
) -> dict[str, Any] | None:
    if previous_pending_plan is None:
        return None
    contract = action_contract_for_phase(
        previous_pending_plan.get("phase") if isinstance(previous_pending_plan.get("phase"), str) else None
    )
    if contract is None:
        return None
    completed_output = action_completed_output(contract=contract, tool_name=tool_name)
    if completed_output is None:
        return None

    known_refs = _pending_known_refs(previous_pending_plan)
    known_refs.update(payload_known_refs)
    if record_id_ref_key is not None and isinstance(record_id, str) and record_id.strip():
        known_refs[record_id_ref_key] = record_id.strip()

    missing_outputs = [
        item
        for item in _string_items(previous_pending_plan.get("missing_outputs"))
        if item != completed_output
    ]
    if not missing_outputs:
        return action_contract_final_plan_payload(contract=contract, known_refs=known_refs)
    return action_contract_plan_payload(
        contract=contract,
        known_refs=known_refs,
        missing_outputs=missing_outputs,
    )


def action_completed_output(*, contract: ActionContract, tool_name: str) -> str | None:
    for step in contract.steps:
        if step.tool_name != tool_name:
            continue
        output_name = step.only_if_missing_output or step.output_ref
        if isinstance(output_name, str) and output_name.strip():
            return output_name.strip()
    return None


def action_contract_plan_payload(
    *,
    contract: ActionContract,
    known_refs: dict[str, Any],
    missing_outputs: list[str],
) -> dict[str, Any]:
    missing = _dedupe_strings([str(item) for item in missing_outputs if str(item).strip()])
    if not missing:
        return action_contract_final_plan_payload(contract=contract, known_refs=known_refs)
    steps = _next_action_steps(contract=contract, missing_outputs=missing)
    if not steps:
        return action_contract_final_plan_payload(contract=contract, known_refs=known_refs)
    tool_names = _dedupe_strings([step.tool_name for step in steps])
    current_missing_output = _step_missing_output(steps[0])
    upcoming_required_tools = _upcoming_required_tools(
        contract=contract,
        missing_outputs=missing,
        current_missing_output=current_missing_output,
    )
    return {
        "phase": contract.trigger_phases[0],
        "contract_id": contract.contract_id,
        "next_action": _action_next_action(contract=contract, missing_output=current_missing_output),
        "current_allowed_tools": tool_names,
        "next_allowed_tools": tool_names,
        "required_tools": tool_names,
        "upcoming_required_tools": upcoming_required_tools,
        "known_refs": dict(known_refs),
        "missing_outputs": missing,
        "final_answer_ready": False,
        "discouraged_tools": _action_discouraged_tools(contract=contract, allowed_tools=tool_names),
        "schema_groups": _action_schema_groups(tool_names),
    }


def action_contract_final_plan_payload(*, contract: ActionContract, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": contract.trigger_phases[0],
        "contract_id": contract.contract_id,
        "next_action": _action_final_next_action(contract),
        "current_allowed_tools": [],
        "next_allowed_tools": [],
        "required_tools": [],
        "upcoming_required_tools": [],
        "known_refs": dict(known_refs),
        "missing_outputs": [],
        "final_answer_ready": True,
        "discouraged_tools": _dedupe_strings(
            [*_FINAL_DISCOURAGED_TOOLS, *contract.forbidden_write_tools, *ACTION_WRITE_TOOLS]
        ),
    }


def _next_action_steps(*, contract: ActionContract, missing_outputs: list[str]) -> list[ToolStep]:
    missing = set(missing_outputs)
    target_output: str | None = None
    for step in contract.steps:
        output = _step_missing_output(step)
        if output in missing:
            target_output = output
            break
    if target_output is None:
        return []
    return [step for step in contract.steps if _step_missing_output(step) == target_output]


def _upcoming_required_tools(
    *,
    contract: ActionContract,
    missing_outputs: list[str],
    current_missing_output: str,
) -> list[str]:
    current_seen = False
    tools: list[str] = []
    missing = set(missing_outputs)
    for step in contract.steps:
        output = _step_missing_output(step)
        if output == current_missing_output:
            current_seen = True
            continue
        if not current_seen or output not in missing:
            continue
        tools.append(step.tool_name)
    return _dedupe_strings(tools)


def _step_missing_output(step: ToolStep) -> str:
    output = step.only_if_missing_output or step.output_ref or step.tool_name
    return output.strip()


def _action_discouraged_tools(*, contract: ActionContract, allowed_tools: list[str]) -> list[str]:
    return _dedupe_strings(
        [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "retrieval_search",
            "retrieval_context_pack",
            *contract.forbidden_write_tools,
            *[tool for tool in ACTION_WRITE_TOOLS if tool not in set(allowed_tools)],
        ]
    )


def _action_schema_groups(tool_names: list[str]) -> list[str]:
    groups: list[str] = []
    if any(tool.startswith("retrieval_") for tool in tool_names):
        groups.append("retrieval")
    if any(tool.startswith("note_") for tool in tool_names):
        groups.append("notes")
    if any(tool.startswith("learning_") for tool in tool_names):
        groups.append("learning")
    if any(tool.startswith("career_application_") for tool in tool_names):
        groups.append("career_application")
    if "career_profile_merge" in tool_names:
        groups.append("career_diagnosis")
    return groups


def _action_next_action(*, contract: ActionContract, missing_output: str) -> str:
    if missing_output == "retrieval_search":
        return "本轮是带后续写入的召回动作；先调用 retrieval_search 定位相关上下文，不要执行旧 career 项目动作。"
    if missing_output == "retrieval_context_pack":
        return "retrieval_search 已完成；下一步只调用 retrieval_context_pack 组装可追溯上下文，随后继续完成本轮写入。"
    if contract.contract_id == "rag.note.write.v1" and missing_output == "note":
        return "召回上下文已完成；下一步只调用 note_create 或 note_append 保存用户要求的笔记。"
    if contract.contract_id == "note.write.v1" and missing_output == "note":
        return "用户已给出要保存的内容；下一步只调用 note_create 保存为可编辑 Note，不要 retrieval 或写 memory。"
    if contract.contract_id == "rag.learning_task.create.v1" and missing_output == "learning_task":
        return "召回上下文已完成；下一步只调用 learning_task_create 创建学习任务，不要更新求职项目或写 Note。"
    if contract.contract_id == "interview.review.update.v1" and missing_output == "note":
        return "召回上下文已完成；下一步只调用 note_create 或 note_append 保存面试复盘，之后再更新求职项目。"
    if contract.contract_id == "interview.review.update.v1" and missing_output == "career_application_update":
        return "面试复盘 Note 已保存；下一步只调用 career_application_merge 更新当前求职项目。"
    if contract.contract_id == "career.profile.merge.required.v1" and missing_output == "career_profile":
        return "ResumeProfile 和诊断报告已完成；下一步只调用 career_profile_merge 沉淀职业画像，不要重复委派。"
    return "当前 action 还有必需产物未完成；继续调用 required tool，不要直接最终答复。"


def _action_final_next_action(contract: ActionContract) -> str:
    if contract.contract_id == "rag.note.write.v1":
        return "召回内容已保存为 Note；停止工具调用并总结保存结果。"
    if contract.contract_id == "rag.learning_task.create.v1":
        return "召回内容已转成 LearningTask；停止工具调用并总结任务安排。"
    if contract.contract_id == "interview.review.update.v1":
        return "面试复盘已写入 Note 并更新 CareerApplication；停止工具调用并总结结果。"
    if contract.contract_id == "career.profile.merge.required.v1":
        return "职业画像已完成；停止工具调用并总结简历诊断结果。"
    return "当前 action 必需产物已完成；停止工具调用并直接回答用户。"


def _pending_known_refs(plan: dict[str, Any] | None) -> dict[str, Any]:
    if plan is None:
        return {}
    raw_refs = plan.get("known_refs")
    if not isinstance(raw_refs, dict):
        return {}
    return {str(key): value for key, value in raw_refs.items() if isinstance(key, str) and value is not None}


def _string_items(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _dedupe_strings(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw_item in items:
        item = raw_item.strip()
        if not item or item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output
