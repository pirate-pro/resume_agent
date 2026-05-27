"""Career workflow phase detection from deterministic runtime facts."""

from __future__ import annotations

import re

from app.domain.models import RunContext, SessionArtifact
from app.runtime.context.models import CareerFlowState, CurrentWorkflowState
from app.runtime.workflow.intent_boundary import build_turn_intent_boundary
from app.runtime.workflow.phase import WorkflowPhaseSnapshot, WorkflowRequiredOutput

__all__ = ["build_career_phase_snapshot"]


def build_career_phase_snapshot(
    *,
    context: RunContext,
    user_message: str,
    workflow_state: CurrentWorkflowState,
    career_flow_state: CareerFlowState,
    active_artifacts: list[SessionArtifact],
) -> WorkflowPhaseSnapshot:
    """Build a read-only career phase snapshot for the main agent."""

    if context.agent_id != context.entry_agent_id:
        return WorkflowPhaseSnapshot()

    intent = _career_intent(user_message)
    refs = _merged_refs(workflow_state=workflow_state, career_flow_state=career_flow_state)
    multi_refs = career_flow_state.multi_refs
    active_input_refs = _active_input_refs(active_artifacts)
    if not intent and not refs and not multi_refs and not active_input_refs:
        return WorkflowPhaseSnapshot()

    phase_name = _select_phase(intent=intent, refs=refs, multi_refs=multi_refs)
    if phase_name is None:
        return WorkflowPhaseSnapshot()

    required_outputs = _required_outputs(
        phase_name=phase_name,
        intent=intent,
        refs=refs,
        multi_refs=multi_refs,
        career_flow_state=career_flow_state,
    )
    missing = [item.name for item in required_outputs if not item.completed]

    return WorkflowPhaseSnapshot(
        phase_name=phase_name,
        confidence=_confidence(intent=intent, refs=refs, active_input_refs=active_input_refs),
        input_refs=_phase_input_refs(phase_name=phase_name, refs=refs, active_input_refs=active_input_refs),
        required_outputs=required_outputs,
        allowed_tool_groups=_allowed_tool_groups(phase_name),
        blocked_tool_names=_blocked_tool_names(phase_name=phase_name, missing_outputs=missing),
        next_action_hint=_next_action_hint(
            phase_name=phase_name,
            missing_outputs=missing,
            final_answer_ready=career_flow_state.final_answer_ready,
        ),
        final_answer_ready=career_flow_state.final_answer_ready,
    )


def _career_intent(user_message: str) -> set[str]:
    text = user_message.strip().casefold()
    boundary = build_turn_intent_boundary(user_message)
    intents: set[str] = set()
    if boundary.read_only:
        intents.add("retrieval_read_only")
        return intents
    if _is_interview_review_update_message(text) and not boundary.forbid_career_application_merge:
        intents.add("interview_review_update")
    elif _is_learning_task_create_message(text):
        intents.add("rag_learning_task_create")
    elif _is_note_write_message(text):
        intents.add("rag_note_write" if _requires_retrieval_for_note_write(text) else "note_write")
    application_action = _is_application_action_message(text)
    non_jd_action = _is_non_jd_career_action_message(text)
    if _requires_application_read_message(text):
        intents.add("application_read_required")
    if application_action or non_jd_action:
        intents.add("application_action")
    if (
        not boundary.forbid_resume_version_create
        and not application_action
        and _has_any(text, ("定制简历", "简历版本", "生成一版简历", "改简历", "优化简历版本"))
    ):
        intents.add("resume_version")
    if not boundary.forbid_jd_fit and _is_jd_fit_message(text, non_jd_action=non_jd_action):
        intents.add("jd_fit")
    if _has_any(text, ("简历", "resume", "画像", "诊断")):
        intents.add("resume_diagnosis")
    if boundary.forbid_career_application_create:
        intents.add("no_career_application_create")
    if _has_any(text, ("求职项目", "投递前", "面试准备", "申请进度", "application_")) and not (
        boundary.forbid_career_application_create and "jd_fit" not in intents
    ):
        intents.add("application_action")
    return intents


def _select_phase(*, intent: set[str], refs: dict[str, str], multi_refs: dict[str, list[str]]) -> str | None:
    if "retrieval_read_only" in intent:
        return "retrieval_read_only"
    if "interview_review_update" in intent:
        return "interview_review_update"
    if "rag_learning_task_create" in intent:
        return "rag_learning_task_create"
    if "rag_note_write" in intent:
        return "rag_note_write"
    if "note_write" in intent:
        return "note_write"
    if "resume_version" in intent:
        return "resume_version"
    if "application_action" in intent and "application_id" in refs:
        return "application_action"
    if "application_action" in intent and "jd_fit" not in intent:
        return None
    if "jd_fit" in intent:
        return "jd_fit"
    if "resume_diagnosis" in intent:
        return "resume_diagnosis"
    if multi_refs.get("resume_version_ids"):
        return "resume_version"
    if "job_fit_report_id" in refs or "jd_analysis_id" in refs:
        return "jd_fit"
    if "resume_profile_id" in refs:
        return "resume_diagnosis"
    return None


def _required_outputs(
    *,
    phase_name: str,
    intent: set[str],
    refs: dict[str, str],
    multi_refs: dict[str, list[str]],
    career_flow_state: CareerFlowState,
) -> list[WorkflowRequiredOutput]:
    if phase_name == "resume_diagnosis":
        return [
            _output("resume_profile", "resume_profile_id", refs.get("resume_profile_id")),
            _output("diagnosis_artifact", "diagnosis_artifact_id", refs.get("diagnosis_artifact_id")),
            _output("career_profile", "career_profile_id", refs.get("career_profile_id")),
        ]
    if phase_name == "jd_fit":
        outputs = [
            _output("jd_analysis", "jd_analysis_id", refs.get("jd_analysis_id")),
            _output("job_fit_report", "job_fit_report_id", refs.get("job_fit_report_id")),
        ]
        if "no_career_application_create" not in intent:
            outputs.append(_output("career_application", "application_id", refs.get("application_id")))
        return outputs
    if phase_name == "resume_version":
        resume_version_id = _last(multi_refs.get("resume_version_ids"))
        application_link = refs.get("application_id") if career_flow_state.final_answer_ready else None
        outputs = [
            _output("resume_profile", "resume_profile_id", refs.get("resume_profile_id")),
            _output("jd_analysis", "jd_analysis_id", refs.get("jd_analysis_id")),
            _output("job_fit_report", "job_fit_report_id", refs.get("job_fit_report_id")),
            _output("career_application", "application_id", refs.get("application_id")),
            _output("resume_version", "resume_version_id", resume_version_id),
            _output("career_application_resume_version_link", "application_id", application_link),
        ]
        if _resume_version_requires_application_read(intent=intent, career_flow_state=career_flow_state):
            outputs.insert(4, _output("career_application_read", "application_id", None))
        return outputs
    if phase_name == "application_action":
        return [_output("career_application", "application_id", refs.get("application_id"))]
    if phase_name == "retrieval_read_only":
        completed_tools = set(career_flow_state.do_not_repeat_tools)
        return [
            _output(
                "retrieval_search",
                "retrieval_search",
                "retrieval_search" if "retrieval_search" in completed_tools else None,
            ),
            _output(
                "retrieval_context_pack",
                "retrieval_context_pack",
                "retrieval_context_pack" if "retrieval_context_pack" in completed_tools else None,
            ),
        ]
    if phase_name == "note_write":
        return [_output("note", "note_id", None)]
    if phase_name in {"rag_note_write", "rag_learning_task_create", "interview_review_update"}:
        completed_tools = set(career_flow_state.do_not_repeat_tools)
        outputs = [
            _output(
                "retrieval_search",
                "retrieval_search",
                "retrieval_search" if "retrieval_search" in completed_tools else None,
            ),
            _output(
                "retrieval_context_pack",
                "retrieval_context_pack",
                "retrieval_context_pack" if "retrieval_context_pack" in completed_tools else None,
            ),
        ]
        if phase_name == "rag_note_write":
            outputs.append(_output("note", "note_id", None))
        elif phase_name == "rag_learning_task_create":
            outputs.append(_output("learning_task", "learning_task_id", None))
        else:
            outputs.extend(
                [
                    _output("note", "note_id", None),
                    _output("career_application_update", "application_id", None),
                ]
            )
        return outputs
    return []


def _output(name: str, ref_key: str, ref_value: str | None) -> WorkflowRequiredOutput:
    return WorkflowRequiredOutput(
        name=name,
        ref_key=ref_key,
        status="completed" if ref_value else "missing",
        ref_value=ref_value,
    )


def _merged_refs(*, workflow_state: CurrentWorkflowState, career_flow_state: CareerFlowState) -> dict[str, str]:
    refs = dict(workflow_state.refs)
    refs.update(career_flow_state.refs)
    return refs


def _active_input_refs(active_artifacts: list[SessionArtifact]) -> list[str]:
    output: list[str] = []
    for artifact in active_artifacts:
        if artifact.status != "ready":
            continue
        output.append(artifact.artifact_id)
    return output[:5]


def _phase_input_refs(*, phase_name: str, refs: dict[str, str], active_input_refs: list[str]) -> list[str]:
    output: list[str] = []
    if phase_name in {"resume_diagnosis", "jd_fit", "resume_version"}:
        _append_if_present(output, refs.get("resume_source_artifact_id"))
    if phase_name in {"jd_fit", "resume_version", "application_action"}:
        _append_if_present(output, refs.get("jd_source_artifact_id"))
    for ref in active_input_refs:
        _append_if_present(output, ref)
    return output[:6]


def _allowed_tool_groups(phase_name: str) -> list[str]:
    if phase_name == "resume_diagnosis":
        return ["session_artifacts", "delegate_agents", "resume_profile", "career_profile"]
    if phase_name == "jd_fit":
        return ["session_artifacts", "delegate_agents", "jd_analysis", "job_fit_report", "career_application"]
    if phase_name == "resume_version":
        return ["session_artifacts", "resume_version", "career_application"]
    if phase_name == "application_action":
        return ["career_application", "resume_version", "learning", "notes"]
    if phase_name == "retrieval_read_only":
        return ["retrieval"]
    if phase_name == "note_write":
        return ["notes"]
    if phase_name == "rag_note_write":
        return ["retrieval", "notes"]
    if phase_name == "rag_learning_task_create":
        return ["retrieval", "learning"]
    if phase_name == "interview_review_update":
        return ["retrieval", "notes", "career_application"]
    return []


def _blocked_tool_names(*, phase_name: str, missing_outputs: list[str]) -> list[str]:
    if phase_name == "resume_diagnosis":
        return [
            "career_jd_analysis_save",
            "career_job_fit_report_save",
            "career_application_create",
            "career_resume_version_create",
        ]
    if phase_name == "jd_fit":
        blocked: list[str] = []
        if "job_fit_report" in missing_outputs or "career_application" in missing_outputs:
            blocked.append("career_resume_version_create")
        return blocked
    if phase_name == "resume_version" and (
        "career_application_read" in missing_outputs
        or "job_fit_report" in missing_outputs
        or "career_application" in missing_outputs
    ):
        return ["career_resume_version_create"]
    if phase_name == "retrieval_read_only":
        return [
            "memory_write",
            "note_create",
            "note_append",
            "learning_task_create",
            "career_application_create",
            "career_application_merge",
            "career_resume_version_create",
            "career_resume_profile_save",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
        ]
    if phase_name == "note_write":
        return [
            "memory_write",
            "retrieval_search",
            "retrieval_context_pack",
            "learning_task_create",
            "career_application_create",
            "career_application_merge",
            "career_resume_version_create",
            "career_resume_profile_save",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
        ]
    if phase_name == "rag_note_write":
        return [
            "memory_write",
            "learning_task_create",
            "career_application_create",
            "career_application_merge",
            "career_resume_version_create",
            "career_resume_profile_save",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
        ]
    if phase_name == "rag_learning_task_create":
        return [
            "memory_write",
            "note_create",
            "note_append",
            "career_application_create",
            "career_application_merge",
            "career_resume_version_create",
            "career_resume_profile_save",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
        ]
    if phase_name == "interview_review_update":
        return [
            "memory_write",
            "learning_task_create",
            "career_application_create",
            "career_resume_version_create",
            "career_resume_profile_save",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
        ]
    return []


def _next_action_hint(*, phase_name: str, missing_outputs: list[str], final_answer_ready: bool) -> str | None:
    if final_answer_ready:
        return "关键产物已完成，可以停止工具调用并面向用户总结结果。"
    if phase_name == "resume_diagnosis":
        if "resume_profile" in missing_outputs:
            return "先基于简历 artifact 生成 ResumeProfile 和诊断报告。"
        if "career_profile" in missing_outputs:
            return "将稳定求职信息 merge 到 CareerProfile；没有可合并内容时在答复中说明。"
        return "简历诊断产物已齐，避免继续创建 JD 或简历版本产物。"
    if phase_name == "jd_fit":
        if "jd_analysis" in missing_outputs:
            return "先基于 JD artifact 生成 JDAnalysis。"
        if "job_fit_report" in missing_outputs:
            return "先保存 JobFitReport，再创建或更新 CareerApplication。"
        if "career_application" in missing_outputs:
            return "先创建 CareerApplication，把简历画像、JD 分析和匹配报告串起来。"
        return "匹配阶段产物已齐，可以总结匹配报告或进入定制简历。"
    if phase_name == "resume_version":
        if "career_application_read" in missing_outputs:
            return "先调用 career_application_get 读取当前 CareerApplication，再基于其关联记录生成 ResumeVersion。"
        if "resume_version" in missing_outputs:
            return "先生成 ResumeVersion；生成后必须 merge 回 CareerApplication。"
        if "career_application_resume_version_link" in missing_outputs:
            return "ResumeVersion 已生成，下一步只需把 resume_version_id merge 回 CareerApplication。"
        return "定制简历阶段产物已齐，可以最终答复。"
    if phase_name == "application_action":
        return "围绕已确认的 CareerApplication 执行用户指定动作。"
    if phase_name == "retrieval_read_only":
        if "retrieval_search" in missing_outputs:
            return "本轮只读；先调用 retrieval_search 召回相关上下文，不要执行任何写入工具。"
        if "retrieval_context_pack" in missing_outputs:
            return "retrieval_search 已完成；下一步只调用 retrieval_context_pack 组装可追溯上下文。"
        return "只读召回上下文已完成；停止工具调用并直接回答用户。"
    if phase_name == "note_write":
        if "note" in missing_outputs:
            return "用户已给出要保存的内容；直接调用 note_create 保存为 Note，不要先做 retrieval 或 memory_write。"
        return "Note 已保存；可以最终答复。"
    if phase_name == "rag_note_write":
        if "retrieval_search" in missing_outputs:
            return "先召回相关上下文，再保存为 Note。"
        if "retrieval_context_pack" in missing_outputs:
            return "先组装召回上下文，再保存为 Note。"
        if "note" in missing_outputs:
            return "召回上下文已完成；保存为 Note 后才能最终答复。"
        return "Note 已保存；可以最终答复。"
    if phase_name == "rag_learning_task_create":
        if "retrieval_search" in missing_outputs:
            return "先召回相关上下文，再创建 LearningTask。"
        if "retrieval_context_pack" in missing_outputs:
            return "先组装召回上下文，再创建 LearningTask。"
        if "learning_task" in missing_outputs:
            return "召回上下文已完成；创建 LearningTask 后才能最终答复。"
        return "LearningTask 已创建；可以最终答复。"
    if phase_name == "interview_review_update":
        if "retrieval_search" in missing_outputs:
            return "先召回相关上下文，再保存面试复盘并更新求职项目。"
        if "retrieval_context_pack" in missing_outputs:
            return "先组装召回上下文，再保存面试复盘并更新求职项目。"
        if "note" in missing_outputs:
            return "召回上下文已完成；先保存面试复盘 Note。"
        if "career_application_update" in missing_outputs:
            return "面试复盘 Note 已保存；再更新 CareerApplication。"
        return "面试复盘和求职项目更新已完成；可以最终答复。"
    return None


def _confidence(*, intent: set[str], refs: dict[str, str], active_input_refs: list[str]) -> str:
    if intent and refs:
        return "high"
    if intent and active_input_refs:
        return "medium"
    if intent:
        return "medium"
    if refs:
        return "low"
    return "none"


def _append_if_present(output: list[str], value: str | None) -> None:
    if value and value not in output:
        output.append(value)


def _last(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[-1]


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _compact_text(text: str) -> str:
    return re.sub(r"[\s`*_：:，,。；;！!？?、（）()\[\]【】\"'“”‘’\-.]+", "", text)


def _has_unnegated_any(text: str, values: tuple[str, ...]) -> bool:
    return any(_has_unnegated(text, value) for value in values)


def _has_unnegated(text: str, value: str) -> bool:
    start = 0
    while True:
        index = text.find(value, start)
        if index < 0:
            return False
        prefix = text[max(0, index - 8) : index]
        if not prefix.endswith(("不要", "无需", "不用", "禁止", "避免", "不必", "先别", "别", "不")):
            return True
        start = index + len(value)


def _has_unnegated_pattern(text: str, pattern: str) -> bool:
    for match in re.finditer(pattern, text):
        prefix = text[max(0, match.start() - 8) : match.start()]
        if prefix.endswith(("不要", "无需", "不用", "禁止", "避免", "不必", "先别", "别", "不")):
            continue
        return True
    return False


def _is_application_action_message(text: str) -> bool:
    return _has_any(
        text,
        (
            "投递前检查",
            "面试准备",
            "申请进度",
            "项目动作",
            "pre_apply",
            "pre-apply",
            "interview prep",
        ),
    )


def _is_note_write_message(text: str) -> bool:
    compact = _compact_text(text)
    return (
        _has_unnegated_pattern(compact, r"保存[为成].{0,12}(笔记|note)")
        or _has_unnegated_pattern(compact, r"(存到|整理成|写入).{0,8}(笔记|note)")
        or _has_unnegated_any(
            compact,
            (
                "调用note_create",
                "调用note_append",
                "记录复盘",
                "记录这次复盘",
                "把面试题记下来",
            ),
        )
    )


def _requires_retrieval_for_note_write(text: str) -> bool:
    compact = _compact_text(text)
    return _has_any(
        compact,
        (
            "先召回",
            "自动召回",
            "召回相关上下文",
            "召回依据",
            "先检索",
            "检索上下文",
            "之前",
            "根据之前",
            "根据历史",
            "之前保存",
            "历史求职资产",
            "准备内容",
            "相关上下文",
            "contextpack",
            "retrieval",
            "先召回依据",
        ),
    )


def _is_learning_task_create_message(text: str) -> bool:
    compact = _compact_text(text)
    return (
        _has_unnegated_pattern(compact, r"(创建|新建).{0,12}学习任务")
        or _has_unnegated_any(
            compact,
            (
                "加入学习任务",
                "加入学习监督",
                "监督我完成",
                "学习安排",
            ),
        )
    )


def _is_interview_review_update_message(text: str) -> bool:
    compact = _compact_text(text)
    return (
        _has_any(compact, ("面试复盘", "面完", "一面", "二面", "复盘"))
        and (
            _has_unnegated_pattern(compact, r"(保存|记录|写入).{0,16}(复盘|笔记|note)")
            or _has_unnegated_any(compact, ("保存成一条note", "保存为一条note", "保存成一条笔记", "保存为一条笔记"))
        )
        and _has_application_update_goal(compact)
    )


def _has_application_update_goal(compact_text: str) -> bool:
    return _has_unnegated_any(
        compact_text,
        (
            "并更新项目",
            "并更新求职项目",
            "并更新当前求职项目",
            "同时更新项目",
            "同时更新求职项目",
            "同时更新当前求职项目",
            "更新当前项目",
            "更新当前求职项目",
            "更新求职项目的",
            "更新项目的",
            "写回项目",
            "写回求职项目",
            "更新careerapplication",
            "写回careerapplication",
        ),
    )


def _is_non_jd_career_action_message(text: str) -> bool:
    return _has_any(
        text,
        (
            "学习计划",
            "学习任务",
            "打卡",
            "复盘",
            "二面",
            "一面",
            "面试",
            "保存为笔记",
            "记住",
            "先不要保存",
            "先别新建",
            "先不要建任务",
            "不用我提供",
            "不用提供",
            "监督我完成",
            "短板",
        ),
    )


def _is_jd_fit_message(text: str, *, non_jd_action: bool) -> bool:
    if _has_any(text, ("做匹配分析", "岗位匹配", "适配分析")):
        return True
    if non_jd_action:
        return False
    return _has_any(text, ("jd", "岗位描述", "职位描述", "投递建议", "匹配报告")) or (
        _has_any(text, ("岗位", "职位")) and _has_any(text, ("匹配", "适配", "分析"))
    )


def _requires_application_read_message(text: str) -> bool:
    return "career_application_get" in text or ("先调用" in text and "读取项目" in text)


def _resume_version_requires_application_read(
    *,
    intent: set[str],
    career_flow_state: CareerFlowState,
) -> bool:
    return (
        "resume_version" in intent
        and "application_read_required" in intent
        and "career_application_get" not in set(career_flow_state.do_not_repeat_tools)
    )
