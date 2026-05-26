"""Career workflow phase detection from deterministic runtime facts."""

from __future__ import annotations

from app.domain.models import RunContext, SessionArtifact
from app.runtime.context.models import CareerFlowState, CurrentWorkflowState
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
    intents: set[str] = set()
    application_action = _is_application_action_message(text)
    non_jd_action = _is_non_jd_career_action_message(text)
    if _requires_application_read_message(text):
        intents.add("application_read_required")
    if application_action or non_jd_action:
        intents.add("application_action")
    if not application_action and _has_any(text, ("定制简历", "简历版本", "生成一版简历", "改简历", "优化简历版本")):
        intents.add("resume_version")
    if _is_jd_fit_message(text, non_jd_action=non_jd_action):
        intents.add("jd_fit")
    if _has_any(text, ("简历", "resume", "画像", "诊断")):
        intents.add("resume_diagnosis")
    if _has_any(text, ("求职项目", "投递前", "面试准备", "申请进度", "application_")):
        intents.add("application_action")
    return intents


def _select_phase(*, intent: set[str], refs: dict[str, str], multi_refs: dict[str, list[str]]) -> str | None:
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
        return [
            _output("jd_analysis", "jd_analysis_id", refs.get("jd_analysis_id")),
            _output("job_fit_report", "job_fit_report_id", refs.get("job_fit_report_id")),
            _output("career_application", "application_id", refs.get("application_id")),
        ]
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
