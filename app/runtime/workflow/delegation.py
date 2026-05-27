"""Normalization for model-authored delegate_agents arguments."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "DelegateNormalizationDecision",
    "delegate_jd_fit_source_key",
    "delegate_semantic_signature",
    "delegate_signature",
    "is_dependent_application_delegate_task",
    "is_jd_fit_delegate_task",
    "mentions_application_record",
    "normalize_delegate_agents_arguments",
]


@dataclass(slots=True)
class DelegateNormalizationDecision:
    """Result of normalizing a delegate_agents tool payload."""

    status: str
    arguments: dict[str, Any]
    repair_actions: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    reason: str | None = None

    @property
    def changed(self) -> bool:
        return self.status == "normalized"

    @property
    def rejected(self) -> bool:
        return self.status == "rejected"


def normalize_delegate_agents_arguments(
    raw_arguments: Any,
    *,
    phase: str | None = None,
    available_agent_ids: Iterable[str] = ("resume_agent", "job_agent"),
    valid_artifact_ids: Iterable[str] | None = None,
) -> DelegateNormalizationDecision:
    """Normalize delegate_agents arguments before execution.

    The model may propose orchestration-shaped JSON. This function keeps the
    executable boundary in code: only structurally valid, phase-compatible child
    tasks are allowed to reach the actual delegate tool.
    """

    if not isinstance(raw_arguments, dict):
        return DelegateNormalizationDecision(
            status="rejected",
            arguments={},
            errors=[{"field": "delegate_agents", "reason": "arguments_not_object"}],
            reason="delegate_arguments_invalid",
        )

    arguments = dict(raw_arguments)
    raw_tasks = _normalize_raw_tasks(arguments.get("tasks"))
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return DelegateNormalizationDecision(
            status="rejected",
            arguments=arguments,
            errors=[{"field": "delegate_agents.tasks", "reason": "tasks_not_non_empty_list"}],
            reason="delegate_tasks_invalid",
        )

    allowed_agents = {_normalize_string(item) for item in available_agent_ids}
    allowed_agents.discard(None)
    normalized_phase = _normalize_string(phase)
    allowed_artifacts = (
        _normalize_artifact_id_set(valid_artifact_ids)
        if normalized_phase is not None and valid_artifact_ids is not None
        else None
    )
    valid_tasks: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    changed = False

    for index, raw_task in enumerate(raw_tasks):
        task, task_errors, task_changed = _normalize_delegate_task(
            raw_task,
            index=index,
            phase=normalized_phase,
            available_agent_ids={item for item in allowed_agents if item is not None},
            valid_artifact_ids=allowed_artifacts,
        )
        if task_errors:
            errors.extend(task_errors)
            changed = True
            continue
        if task is None:
            changed = True
            continue
        valid_tasks.append(task)
        changed = changed or task_changed

    deduped_tasks, dedupe_changed = _dedupe_delegate_tasks(valid_tasks, phase=normalized_phase)
    changed = changed or dedupe_changed
    valid_tasks = deduped_tasks

    if not valid_tasks:
        return DelegateNormalizationDecision(
            status="rejected",
            arguments=arguments,
            errors=errors or [{"field": "delegate_agents.tasks", "reason": "no_executable_tasks"}],
            reason="delegate_tasks_invalid",
        )

    arguments["tasks"] = valid_tasks
    repair_actions: list[dict[str, str]] = []
    if changed or errors:
        repair_actions.append(
            {
                "field": "delegate_agents.tasks",
                "from": "model_authored_tasks",
                "to": "schema_valid_phase_compatible_tasks",
                "reason": "delegate_task_schema_normalized",
            }
        )
    if dedupe_changed:
        repair_actions.append(
            {
                "field": "delegate_agents.tasks",
                "from": "duplicate_child_tasks",
                "to": "single_task_per_target_and_source",
                "reason": "delegate_task_normalizer_deduped_tasks",
            }
        )

    return DelegateNormalizationDecision(
        status="normalized" if repair_actions else "no_change",
        arguments=arguments,
        repair_actions=repair_actions,
        errors=errors,
    )


def _normalize_delegate_task(
    raw_task: Any,
    *,
    index: int,
    phase: str | None,
    available_agent_ids: set[str],
    valid_artifact_ids: set[str] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, str]], bool]:
    field_prefix = f"delegate_agents.tasks[{index}]"
    if not isinstance(raw_task, dict):
        return None, [{"field": field_prefix, "reason": "task_not_object"}], False

    task = dict(raw_task)
    target_agent_id = _normalize_string(task.get("target_agent_id"))
    instruction = _normalize_string(task.get("instruction"))
    errors: list[dict[str, str]] = []
    if target_agent_id is None:
        errors.append({"field": f"{field_prefix}.target_agent_id", "reason": "missing_target_agent_id"})
    elif available_agent_ids and target_agent_id not in available_agent_ids:
        errors.append({"field": f"{field_prefix}.target_agent_id", "reason": "unknown_target_agent_id"})
    if instruction is None:
        errors.append({"field": f"{field_prefix}.instruction", "reason": "missing_instruction"})
    if errors:
        return None, errors, False

    assert target_agent_id is not None
    assert instruction is not None
    phase_error = _phase_compatibility_error(target_agent_id=target_agent_id, instruction=instruction, phase=phase)
    if phase_error is not None:
        return None, [{"field": field_prefix, "reason": phase_error}], False

    changed = False
    normalized_refs, refs_changed = _normalize_artifact_refs(
        task.get("artifact_refs"),
        instruction=instruction,
        infer_from_instruction=phase in {"jd_fit", "resume_diagnosis"},
        valid_artifact_ids=valid_artifact_ids,
    )
    if refs_changed:
        changed = True
    if normalized_refs:
        task["artifact_refs"] = normalized_refs
    elif "artifact_refs" in task and task.get("artifact_refs") not in (None, []):
        task["artifact_refs"] = []
        changed = True

    normalized_constraints, constraints_changed = _normalize_string_list(task.get("constraints"))
    if constraints_changed:
        changed = True
    if normalized_constraints:
        task["constraints"] = normalized_constraints
    elif "constraints" in task and task.get("constraints") not in (None, []):
        task["constraints"] = []
        changed = True

    max_rounds = task.get("max_tool_rounds")
    if max_rounds is not None and (not isinstance(max_rounds, int) or max_rounds < 0 or max_rounds > 40):
        task["max_tool_rounds"] = 10
        changed = True

    task["target_agent_id"] = target_agent_id
    task["instruction"] = instruction
    return task, [], changed


def _phase_compatibility_error(*, target_agent_id: str, instruction: str, phase: str | None) -> str | None:
    if phase == "jd_fit":
        if target_agent_id != "job_agent":
            return "target_agent_not_allowed_for_jd_fit"
        if is_dependent_application_delegate_task(instruction):
            return "application_action_not_child_task"
    if phase == "resume_diagnosis" and target_agent_id != "resume_agent":
        return "target_agent_not_allowed_for_resume_diagnosis"
    return None


def _normalize_raw_tasks(raw: Any) -> Any:
    if raw is None:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        try:
            return json.loads(stripped)
        except ValueError:
            return raw
    return raw


def _normalize_artifact_refs(
    raw: Any,
    *,
    instruction: str,
    infer_from_instruction: bool,
    valid_artifact_ids: set[str] | None,
) -> tuple[list[str], bool]:
    refs: list[str] = []
    changed = False
    if isinstance(raw, list):
        for item in raw:
            value = _normalize_string(item)
            if value is None:
                changed = True
                continue
            if _is_product_record_ref(value):
                changed = True
                continue
            if valid_artifact_ids is not None and value not in valid_artifact_ids:
                changed = True
                continue
            if value not in refs:
                refs.append(value)
            else:
                changed = True
    elif raw is not None:
        changed = True

    if infer_from_instruction:
        for value in re.findall(r"\bartifact_[A-Za-z0-9_-]+\b", instruction):
            if valid_artifact_ids is not None and value not in valid_artifact_ids:
                continue
            if value not in refs:
                refs.append(value)
                changed = True
    return refs, changed


def _normalize_string_list(raw: Any) -> tuple[list[str], bool]:
    if raw is None:
        return [], False
    if not isinstance(raw, list):
        return [], True
    output: list[str] = []
    changed = False
    for item in raw:
        value = _normalize_string(item)
        if value is None:
            changed = True
            continue
        if value in output:
            changed = True
            continue
        output.append(value)
    return output, changed


def _normalize_artifact_id_set(raw: Iterable[str] | None) -> set[str]:
    if raw is None:
        return set()
    output: set[str] = set()
    for item in raw:
        value = _normalize_string(item)
        if value is not None:
            output.add(value)
    return output


def _dedupe_delegate_tasks(tasks: list[dict[str, Any]], *, phase: str | None) -> tuple[list[dict[str, Any]], bool]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    changed = False
    for task in tasks:
        key = _delegate_task_key(task, phase=phase)
        if key in seen:
            changed = True
            continue
        seen.add(key)
        output.append(task)
    return output, changed


def _delegate_task_key(task: dict[str, Any], *, phase: str | None) -> str:
    target_agent_id = _normalize_string(task.get("target_agent_id")) or ""
    instruction = _normalize_string(task.get("instruction")) or ""
    refs = task.get("artifact_refs")
    artifact_refs = sorted(ref for ref in refs if isinstance(ref, str) and ref.strip()) if isinstance(refs, list) else []
    if phase == "jd_fit" and target_agent_id == "job_agent":
        source = _first_jd_source(artifact_refs, instruction) or ",".join(artifact_refs) or _compact_text(instruction)
        return f"{phase}:{target_agent_id}:{source}"
    if phase == "resume_diagnosis" and target_agent_id == "resume_agent":
        source = _first_resume_source(artifact_refs, instruction) or ",".join(artifact_refs) or _compact_text(instruction)
        return f"{phase}:{target_agent_id}:{source}"
    return f"{target_agent_id}:{','.join(artifact_refs)}:{_compact_text(instruction)}"


def delegate_signature(arguments: Any) -> str | None:
    """Return a structural signature for a delegate_agents call."""

    if not isinstance(arguments, dict):
        return None
    raw_tasks = arguments.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return None
    parts: list[str] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            return None
        target_agent_id = _normalize_string(task.get("target_agent_id"))
        if target_agent_id is None:
            return None
        refs = task.get("artifact_refs")
        artifact_refs = sorted(ref for ref in refs if isinstance(ref, str)) if isinstance(refs, list) else []
        parts.append(f"{target_agent_id}:{','.join(artifact_refs)}")
    return "|".join(sorted(parts))


def delegate_semantic_signature(arguments: Any) -> str | None:
    """Return a semantic signature for delegate_agents stagnation detection."""

    if not isinstance(arguments, dict):
        return None
    raw_tasks = arguments.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return None
    parts: list[str] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            return None
        target_agent_id = _normalize_string(task.get("target_agent_id"))
        if target_agent_id is None:
            return None
        instruction = _normalize_string(task.get("instruction")) or ""
        artifact_refs = _delegate_task_artifact_refs(task, instruction)
        product_refs = _delegate_task_product_refs(task, instruction)
        phase = _delegate_task_phase(target_agent_id, instruction, artifact_refs)
        required_outputs = _delegate_task_required_outputs(target_agent_id, instruction)
        parts.append(
            ":".join(
                [
                    target_agent_id,
                    phase,
                    f"artifacts={','.join(artifact_refs)}",
                    f"products={','.join(product_refs)}",
                    f"outputs={','.join(required_outputs)}",
                ]
            )
        )
    return "|".join(sorted(parts))


def is_jd_fit_delegate_task(task: dict[str, Any], instruction: str) -> bool:
    artifact_refs = _delegate_task_artifact_refs(task, instruction)
    return _delegate_task_phase("job_agent", instruction, artifact_refs) == "jd_fit" and (
        _task_requests_jd_fit_generation(instruction)
        or any(_looks_like_jd_artifact_ref(ref) for ref in artifact_refs)
    )


def is_dependent_application_delegate_task(instruction: str) -> bool:
    if not mentions_application_record(instruction):
        return False
    return not _task_requests_jd_fit_generation(instruction)


def delegate_jd_fit_source_key(task: dict[str, Any], instruction: str) -> str:
    artifact_refs = _delegate_task_artifact_refs(task, instruction)
    jd_refs = [ref for ref in artifact_refs if _looks_like_jd_artifact_ref(ref)]
    if jd_refs:
        return f"jd_artifact:{jd_refs[0]}"
    if artifact_refs:
        return f"artifacts:{','.join(artifact_refs)}"
    product_refs = _delegate_task_product_refs(task, instruction)
    jd_product_refs = [ref for ref in product_refs if ref.startswith("jd_")]
    if jd_product_refs:
        return f"jd_record:{jd_product_refs[0]}"
    return "current_jd_fit"


def _delegate_task_artifact_refs(task: dict[str, Any], instruction: str) -> list[str]:
    refs: list[str] = []
    raw_refs = task.get("artifact_refs")
    if isinstance(raw_refs, list):
        for raw_ref in raw_refs:
            ref = _normalize_string(raw_ref)
            if ref is not None and ref.startswith("artifact_"):
                _append_unique(refs, ref)
    for ref in re.findall(r"\bartifact_[A-Za-z0-9_-]+\b", instruction):
        _append_unique(refs, ref)
    return sorted(refs)


def _delegate_task_product_refs(task: dict[str, Any], instruction: str) -> list[str]:
    refs: list[str] = []
    raw_refs = task.get("artifact_refs")
    texts = [instruction]
    if isinstance(raw_refs, list):
        texts.extend(ref for ref in raw_refs if isinstance(ref, str))
    ignored_field_names = {
        "resume_profile_id",
        "career_profile_id",
        "jd_analysis_id",
        "job_fit_report_id",
        "application_id",
        "resume_version_id",
    }
    pattern = re.compile(
        r"\b(?:resume_profile|career_profile|job_fit_report|resume_version|application|jd|fit)_[A-Za-z0-9_-]+\b"
    )
    for text in texts:
        for ref in pattern.findall(text):
            if ref in ignored_field_names or ref.startswith("artifact_"):
                continue
            _append_unique(refs, ref)
    return sorted(refs)


def _delegate_task_phase(target_agent_id: str, instruction: str, artifact_refs: list[str]) -> str:
    normalized = instruction.casefold()
    compact = _compact_text(instruction)
    if target_agent_id == "job_agent" and (
        _task_requires_job_fit_report(instruction)
        or any(ref.startswith("artifact_jd") for ref in artifact_refs)
        or _has_any(normalized, ("jd", "job description", "岗位", "职位", "匹配"))
    ):
        return "jd_fit"
    if target_agent_id == "resume_agent" and _has_any(
        compact,
        ("简历诊断", "诊断简历", "简历画像", "解析简历", "resumeprofile"),
    ):
        return "resume_diagnosis"
    return "general"


def _delegate_task_required_outputs(target_agent_id: str, instruction: str) -> list[str]:
    normalized = instruction.casefold()
    compact = _compact_text(instruction)
    outputs: list[str] = []
    if target_agent_id == "job_agent":
        if _has_any(normalized, ("jdanalysis", "career_jd_analysis_save")) or _has_any(compact, ("jd分析", "岗位分析")):
            outputs.append("jd_analysis")
        if _task_requires_job_fit_report(instruction):
            _append_unique(outputs, "jd_analysis")
            outputs.append("job_fit_report")
    elif target_agent_id == "resume_agent":
        if _has_any(compact, ("简历画像", "resumeprofile")):
            outputs.append("resume_profile")
        if _has_any(compact, ("诊断报告", "简历诊断")):
            outputs.append("diagnosis_artifact")
    return sorted(outputs)


def _first_jd_source(artifact_refs: list[str], instruction: str) -> str | None:
    for ref in artifact_refs:
        lowered = ref.casefold()
        if lowered.startswith("artifact_jd") or "_jd_" in lowered or lowered.endswith("_jd"):
            return ref
    for ref in re.findall(r"\bartifact_[A-Za-z0-9_-]+\b", instruction):
        lowered = ref.casefold()
        if lowered.startswith("artifact_jd") or "_jd_" in lowered or lowered.endswith("_jd"):
            return ref
    return None


def _first_resume_source(artifact_refs: list[str], instruction: str) -> str | None:
    for ref in artifact_refs:
        lowered = ref.casefold()
        if "resume" in lowered or "简历" in lowered:
            return ref
    for ref in re.findall(r"\bartifact_[A-Za-z0-9_-]+\b", instruction):
        lowered = ref.casefold()
        if "resume" in lowered:
            return ref
    return None


def mentions_application_record(text: str) -> bool:
    normalized = text.strip().casefold()
    compact = _compact_text(text)
    return _has_any(normalized, ("careerapplication", "career_application")) or _has_any(
        compact,
        ("求职项目", "求职申请", "投递项目", "申请项目"),
    )


def _task_requests_jd_fit_generation(text: str) -> bool:
    normalized = text.strip().casefold()
    compact = _compact_text(text)
    return _has_any(
        normalized,
        (
            "jdanalysis",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
            "jobfitreport",
            "job fit report",
        ),
    ) or _has_any(
        compact,
        (
            "分析jd",
            "解析jd",
            "jd分析",
            "岗位分析",
            "职位分析",
            "生成岗位匹配报告",
            "创建岗位匹配报告",
            "保存岗位匹配报告",
            "输出岗位匹配报告",
            "生成匹配报告",
            "创建匹配报告",
            "保存匹配报告",
            "输出匹配报告",
        ),
    )


def _task_requires_job_fit_report(text: str) -> bool:
    normalized = text.strip().casefold()
    if not normalized:
        return False
    compact = _compact_text(text)
    return _has_any(
        normalized,
        (
            "jobfitreport",
            "job fit report",
            "fit report",
            "job_fit_report",
            "career_job_fit_report_save",
        ),
    ) or _has_any(
        compact,
        (
            "岗位匹配",
            "匹配报告",
            "匹配度",
            "适配度",
            "求职匹配",
        ),
    )


def _looks_like_jd_artifact_ref(ref: str) -> bool:
    lowered = ref.casefold()
    return lowered.startswith("artifact_jd") or "_jd_" in lowered or lowered.endswith("_jd")


def _is_product_record_ref(value: str) -> bool:
    return value.startswith(
        (
            "resume_profile_",
            "career_profile_",
            "jd_",
            "fit_",
            "resume_version_",
            "application_",
            "note_",
            "learning_task_",
            "learning_plan_",
            "weakness_",
            "checkin_",
        )
    )


def _normalize_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _append_unique(output: list[str], value: str) -> None:
    if value not in output:
        output.append(value)


def _has_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)
