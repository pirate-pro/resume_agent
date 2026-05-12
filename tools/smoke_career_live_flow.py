"""Live smoke/stress runner for the career agent flow.

Run:
  uv run python tools/smoke_career_live_flow.py --runs 1

This script uses the real configured model endpoint. It is intentionally not
part of pytest because model availability, latency, and tool-call behavior are
environment-dependent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.career.models import CareerApplication, CareerProfile, JDAnalysis, JobFitReport, ResumeProfile, ResumeVersion
from app.career.store import CareerProductStore
from app.core.time import app_now, to_app_iso
from app.core.settings import Settings
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, SessionArtifact
from app.infra.llm.openai_compatible_client import OpenAICompatibleClient
from app.infra.storage.jsonl_agent_task_store import JsonlAgentTaskStore
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry, load_agent_capability_registry
from app.runtime.agent_registry import load_agent_registry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.services.agent_invocation_service import AgentInvocationService
from app.services.agent_task_runtime import AgentTaskRuntime
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import (
    AgentTaskStatusTool,
    CareerApplicationCreateTool,
    CareerApplicationGetTool,
    CareerApplicationListTool,
    CareerApplicationMergeTool,
    CareerJobFitReportGetTool,
    CareerJobFitReportListTool,
    CareerJobFitReportSaveTool,
    CareerJDAnalysisGetTool,
    CareerJDAnalysisListTool,
    CareerJDAnalysisSaveTool,
    CareerProfileGetTool,
    CareerProfileMergeTool,
    CareerResumeProfileGetTool,
    CareerResumeProfileListTool,
    CareerResumeProfileSaveTool,
    CareerResumeVersionCreateTool,
    CareerResumeVersionGetTool,
    CareerResumeVersionListTool,
    DelegateAgentsTool,
    MemoryExplainTool,
    MemoryForgetTool,
    MemoryInspectTool,
    MemorySearchTool,
    MemoryUpdateTool,
    MemoryWriteTool,
    PublishArtifactTool,
    SessionCreateTextArtifactTool,
    SessionListArtifactsTool,
    SessionPlanArtifactAccessTool,
    SessionReadArtifactTool,
    SessionSearchArtifactTool,
    StateListTool,
    StatePublishTool,
    StateSetTool,
    WorkspaceReadFileTool,
    WorkspaceWriteFileTool,
)
from app.tools.registry import ToolRegistry
from tools.check_career_product_store import check_career_product_store


@dataclass(slots=True)
class LiveStack:
    runtime: AgentRuntime
    session_repository: JsonlSessionRepository
    career_store: CareerProductStore
    data_dir: Path


@dataclass(slots=True)
class TurnReport:
    name: str
    answer: str
    elapsed_seconds: float
    tool_calls: list[str]


@dataclass(slots=True)
class FlowReport:
    run_index: int
    session_id: str
    data_dir: Path
    success: bool
    elapsed_seconds: float
    turns: list[TurnReport] = field(default_factory=list)
    record_ids: dict[str, list[str]] = field(default_factory=dict)
    artifact_ids: list[str] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    quality_findings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    last_events: list[str] = field(default_factory=list)
    failed_stage: str | None = None
    missing_records: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    consistency_errors: list[str] = field(default_factory=list)
    quality_gate_passed: bool | None = None
    quality_error_codes: list[str] = field(default_factory=list)


def build_live_stack(*, data_dir: Path, settings: Settings) -> LiveStack:
    session_repository = JsonlSessionRepository(data_dir=data_dir)
    career_store = CareerProductStore(root_dir=data_dir / "career")
    capability_registry = load_agent_capability_registry(settings.agent_capabilities_path)
    memory_manager = MemoryManager(
        capability_registry=capability_registry,
        memory_store=FileMemoryStore(root_dir=data_dir / "memory"),
    )
    state_manager = StateManager(store=JsonlFileStateStore(root_dir=data_dir / "state"))
    skill_repository = MarkdownSkillRepository(skills_dir=Path("app/skills"))
    agent_document_repository = MarkdownAgentDocumentRepository(agents_dir=Path("app/agents"))
    model_client = OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    context_assembler = ContextAssembler(
        session_repository=session_repository,
        skill_repository=skill_repository,
        agent_document_repository=agent_document_repository,
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )
    event_recorder = EventRecorder(session_repository=session_repository)
    runtime = AgentRuntime(
        session_manager=SessionManager(session_repository=session_repository),
        event_recorder=event_recorder,
        context_assembler=context_assembler,
        model_client=model_client,
        tool_executor=tool_registry,
    )
    agent_registry = load_agent_registry(
        settings.agent_registry_path,
        capability_registry=capability_registry,
        document_repository=agent_document_repository,
    )
    invocation_service = AgentInvocationService(
        agent_registry=agent_registry,
        runtime=runtime,
        event_recorder=event_recorder,
        session_repository=session_repository,
    )
    task_store = JsonlAgentTaskStore(data_dir=data_dir)
    task_runtime = AgentTaskRuntime(
        invocation_service=invocation_service,
        task_store=task_store,
        default_max_concurrency=settings.agent_task_max_concurrency,
    )
    register_live_tools(
        registry=tool_registry,
        capability_registry=capability_registry,
        session_repository=session_repository,
        career_store=career_store,
        memory_manager=memory_manager,
        state_manager=state_manager,
        task_runtime=task_runtime,
        task_store=task_store,
    )
    return LiveStack(
        runtime=runtime,
        session_repository=session_repository,
        career_store=career_store,
        data_dir=data_dir,
    )


def register_live_tools(
    *,
    registry: ToolRegistry,
    capability_registry: AgentCapabilityRegistry,
    session_repository: JsonlSessionRepository,
    career_store: CareerProductStore,
    memory_manager: MemoryManager,
    state_manager: StateManager,
    task_runtime: AgentTaskRuntime,
    task_store: JsonlAgentTaskStore,
) -> None:
    _ = capability_registry
    registry.register(DelegateAgentsTool(agent_task_runtime_provider=lambda: task_runtime))
    registry.register(AgentTaskStatusTool(agent_task_store_provider=lambda: task_store))
    registry.register(MemoryWriteTool(memory_manager=memory_manager))
    registry.register(MemorySearchTool(memory_manager=memory_manager))
    registry.register(MemoryInspectTool(memory_manager=memory_manager))
    registry.register(MemoryExplainTool())
    registry.register(MemoryForgetTool(memory_manager=memory_manager))
    registry.register(MemoryUpdateTool(memory_manager=memory_manager))
    registry.register(StateSetTool(state_manager=state_manager))
    registry.register(StatePublishTool(state_manager=state_manager))
    registry.register(StateListTool(state_manager=state_manager))
    registry.register(PublishArtifactTool(session_repository=session_repository))
    registry.register(WorkspaceWriteFileTool(session_repository=session_repository))
    registry.register(WorkspaceReadFileTool(session_repository=session_repository))
    registry.register(SessionCreateTextArtifactTool(session_repository=session_repository))
    registry.register(SessionListArtifactsTool(session_repository=session_repository))
    registry.register(SessionPlanArtifactAccessTool(session_repository=session_repository))
    registry.register(SessionReadArtifactTool(session_repository=session_repository))
    registry.register(SessionSearchArtifactTool(session_repository=session_repository))
    registry.register(CareerResumeProfileSaveTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerResumeProfileGetTool(career_store=career_store))
    registry.register(CareerResumeProfileListTool(career_store=career_store))
    registry.register(CareerProfileGetTool(career_store=career_store))
    registry.register(CareerProfileMergeTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerJDAnalysisSaveTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerJDAnalysisGetTool(career_store=career_store))
    registry.register(CareerJDAnalysisListTool(career_store=career_store))
    registry.register(CareerJobFitReportSaveTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerJobFitReportGetTool(career_store=career_store))
    registry.register(CareerJobFitReportListTool(career_store=career_store))
    registry.register(CareerResumeVersionCreateTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerResumeVersionGetTool(career_store=career_store))
    registry.register(CareerResumeVersionListTool(career_store=career_store))
    registry.register(CareerApplicationCreateTool(career_store=career_store, session_repository=session_repository))
    registry.register(CareerApplicationGetTool(career_store=career_store))
    registry.register(CareerApplicationListTool(career_store=career_store))
    registry.register(CareerApplicationMergeTool(career_store=career_store, session_repository=session_repository))


def run_live_flow(
    *,
    run_index: int,
    root_data_dir: Path,
    settings: Settings,
    max_tool_rounds: int,
    project_action: str = "none",
    progress: Callable[[str], None] | None = None,
) -> FlowReport:
    run_data_dir = root_data_dir / f"run_{run_index:03d}"
    run_data_dir.mkdir(parents=True, exist_ok=True)
    _progress(progress, run_index, f"开始，data_dir={run_data_dir}")
    stack = build_live_stack(data_dir=run_data_dir, settings=settings)
    session_id = f"sess_live_career_{run_index:03d}_{uuid4().hex[:8]}"
    resume_artifact_id = f"artifact_resume_live_{run_index:03d}"
    report = FlowReport(
        run_index=run_index,
        session_id=session_id,
        data_dir=run_data_dir,
        success=False,
        elapsed_seconds=0.0,
    )
    started = time.perf_counter()
    current_stage = "初始化"
    try:
        stack.session_repository.create_session(session_id)
        add_resume_artifact(stack.session_repository, session_id=session_id, artifact_id=resume_artifact_id)
        stack.session_repository.set_active_artifact_ids(session_id, [resume_artifact_id])

        current_stage = "简历诊断与画像沉淀"
        report.turns.append(
            run_turn(
                stack=stack,
                session_id=session_id,
                name=current_stage,
                message=(
                    "我上传了一份简历，请读取并诊断这份简历，沉淀结构化简历画像，"
                    f"并更新职业画像。简历 artifact_id 是 {resume_artifact_id}。"
                ),
                max_tool_rounds=max_tool_rounds,
                run_index=run_index,
                progress=progress,
            )
        )
        current_stage = "JD 匹配分析"
        report.turns.append(
            run_turn(
                stack=stack,
                session_id=session_id,
                name=current_stage,
                message=(
                    "这是目标 JD：公司招聘 AI 应用开发工程师，要求 Python、FastAPI、RAG、Agent "
                    "工程经验，熟悉向量检索和后端服务落地。请先把这段 JD 沉淀为 artifact，"
                    "再分析我和这个岗位的匹配度，并保存岗位分析和匹配报告。"
                    "拿到匹配报告后，请创建或复用 CareerApplication 求职项目。"
                ),
                max_tool_rounds=max_tool_rounds,
                run_index=run_index,
                progress=progress,
            )
        )
        current_stage = "定制简历版本"
        report.turns.append(
            run_turn(
                stack=stack,
                session_id=session_id,
                name=current_stage,
                message=(
                    "请基于刚才已经保存的 ResumeProfile、JDAnalysis 和 JobFitReport，生成一版 markdown "
                    "定制简历，并保存为可复用的简历版本。优先直接调用 career_resume_version_create 并传入 markdown content，"
                    "保存 ResumeVersion 后，请调用 career_application_merge 把 resume_version_id 合并进当前求职项目；"
                    "如果尚未创建 CareerApplication，则先用 career_application_create 基于 job_fit_report_id 创建。"
                    "career_resume_version_create.keyword_strategy 只写已放进简历或已有证据支撑的关键词，"
                    "不要把风险项、证据不足、缺失、需补充、需用户提供写进 keyword_strategy。"
                    "career_resume_version_create 的 content、change_summary、keyword_strategy、risk_notes 都不能包含"
                    "“占位”“替换为真实数据”“待填”“待补”“待完善”“TODO”“TBD”；"
                    "如果公司、学校、时间、联系方式等事实缺失，不要在简历正文里写“待补充”，"
                    "应省略对应字段或使用更保守的已知事实，并把缺失项写入 CareerApplication 的 risks/next_actions。"
                    "让工具一次性创建 artifact 和 ResumeVersion。不要重新诊断简历，不要委派任何 child-agent，"
                    "不要再次委派 resume_agent 或 job_agent，不要调用 career_resume_profile_save，"
                    "不要创建新的 JDAnalysis 或 JobFitReport；如果不确定产品记录 id，先使用 list 工具确认，"
                    "不要猜测或编造 id。"
                ),
                max_tool_rounds=max_tool_rounds,
                run_index=run_index,
                progress=progress,
            )
        )
        if project_action != "none":
            application = _latest_career_application_for_session(stack, session_id)
            if application is None:
                raise RuntimeError("项目动作前未找到 CareerApplication，无法验证 application_id 链路。")
            current_stage = _project_action_stage(project_action)
            report.turns.append(
                run_turn(
                    stack=stack,
                    session_id=session_id,
                    name=current_stage,
                    message=_project_action_message(project_action, application.application_id),
                    max_tool_rounds=max_tool_rounds,
                    run_index=run_index,
                    progress=progress,
                )
            )
    except Exception as exc:  # noqa: BLE001
        report.failed_stage = current_stage
        report.errors.append(str(exc) or exc.__class__.__name__)
        _progress(progress, run_index, f"异常：stage={current_stage} error={report.errors[-1]}")

    report.elapsed_seconds = time.perf_counter() - started
    inspect_flow_outputs(stack=stack, report=report)
    status = "通过" if report.success else "失败"
    _progress(progress, run_index, f"结束：{status}，耗时 {report.elapsed_seconds:.2f}s")
    return report


def run_turn(
    *,
    stack: LiveStack,
    session_id: str,
    name: str,
    message: str,
    max_tool_rounds: int,
    run_index: int,
    progress: Callable[[str], None] | None = None,
) -> TurnReport:
    before_counts = tool_call_counts(stack.session_repository, session_id)
    started = time.perf_counter()
    _progress(progress, run_index, f"阶段开始：{name}")
    output = stack.runtime.run(
        AgentRunInput(
            session_id=session_id,
            user_message=message,
            skill_names=["base", "tools", "file-reader"],
            max_tool_rounds=max_tool_rounds,
            context=run_context(session_id),
        )
    )
    elapsed = time.perf_counter() - started
    after_counts = tool_call_counts(stack.session_repository, session_id)
    tool_calls = diff_tool_calls(before_counts, after_counts)
    _progress(progress, run_index, f"阶段完成：{name}，耗时 {elapsed:.2f}s，tools={tool_calls}")
    return TurnReport(
        name=name,
        answer=output.answer,
        elapsed_seconds=elapsed,
        tool_calls=tool_calls,
    )


def inspect_flow_outputs(*, stack: LiveStack, report: FlowReport) -> None:
    artifacts = stack.session_repository.list_session_artifacts(report.session_id)
    session_artifact_ids = {item.artifact_id for item in artifacts}
    session_started_at = min((item.created_at for item in artifacts), default=None)
    resume_profiles = [
        item for item in stack.career_store.list_resume_profiles() if item.source_session_id == report.session_id
    ]
    career_profiles = [
        item
        for item in stack.career_store.list_career_profiles()
        if _record_touches_session(item, report.session_id, session_artifact_ids, session_started_at=session_started_at)
    ]
    jd_analyses = [item for item in stack.career_store.list_jd_analyses() if item.source_session_id == report.session_id]
    job_fit_reports = [
        item for item in stack.career_store.list_job_fit_reports() if item.source_session_id == report.session_id
    ]
    resume_versions = [
        item for item in stack.career_store.list_resume_versions() if item.source_session_id == report.session_id
    ]
    career_applications = [
        item for item in stack.career_store.list_career_applications() if item.source_session_id == report.session_id
    ]
    record_ids = {
        "resume_profiles": [item.resume_profile_id for item in resume_profiles],
        "career_profiles": [item.career_profile_id for item in career_profiles],
        "jd_analyses": [item.jd_analysis_id for item in jd_analyses],
        "job_fit_reports": [item.job_fit_report_id for item in job_fit_reports],
        "resume_versions": [item.resume_version_id for item in resume_versions],
        "career_applications": [item.application_id for item in career_applications],
    }
    report.record_ids = record_ids
    report.artifact_ids = [item.artifact_id for item in artifacts]
    report.tool_call_counts = tool_call_counts(stack.session_repository, report.session_id)

    required = {
        "resume_profiles": ResumeProfile,
        "career_profiles": CareerProfile,
        "jd_analyses": JDAnalysis,
        "job_fit_reports": JobFitReport,
        "resume_versions": ResumeVersion,
        "career_applications": CareerApplication,
    }
    for key in required:
        if not record_ids[key]:
            report.missing_records.append(key)
            report.errors.append(f"缺少产品记录: {key}")

    failed_tool_results = failed_tool_result_payloads(stack.session_repository, report.session_id)
    for payload in failed_tool_results:
        tool_name = str(payload.get("tool_name") or "unknown")
        if tool_name not in report.failed_tools:
            report.failed_tools.append(tool_name)
        report.errors.append(f"工具失败: {tool_name} -> {payload.get('content')}")

    if any("Tool call limit reached" in turn.answer for turn in report.turns):
        report.errors.append("达到工具调用轮次上限，未得到完整最终回答。")

    if tool_limit_detected(stack.session_repository, report.session_id):
        report.errors.append("检测到子任务或中间步骤触发工具调用轮次上限。")

    if path_argument_leaked(stack.session_repository, report.session_id):
        report.errors.append("检测到工具调用参数中出现 path/file_path/workspace_path。")

    for turn in report.turns:
        if turn.name.startswith("项目动作"):
            if "career_application_get" not in turn.tool_calls:
                report.errors.append("项目动作未读取 CareerApplication。")
            if "career_application_merge" not in turn.tool_calls:
                report.errors.append("项目动作未回写 CareerApplication。")

    quality_report = check_career_product_store(stack.data_dir, session_id=report.session_id)
    report.quality_gate_passed = quality_report.success
    report.quality_findings = [item.format() for item in quality_report.findings]
    for finding in quality_report.findings:
        if finding.severity == "error":
            formatted = finding.format()
            if finding.code not in report.quality_error_codes:
                report.quality_error_codes.append(finding.code)
            report.consistency_errors.append(formatted)
            report.errors.append(f"产品数据一致性错误: {formatted}")

    report.success = not report.errors
    if report.errors and report.failed_stage is None:
        report.failed_stage = infer_failure_stage(report)
    if report.errors:
        report.last_events = latest_event_summaries(stack.session_repository, report.session_id)


def _record_touches_session(
    record: ResumeProfile | CareerProfile | JDAnalysis | JobFitReport | ResumeVersion | CareerApplication,
    session_id: str,
    artifact_ids: set[str],
    *,
    session_started_at: datetime | None,
) -> bool:
    if record.source_session_id == session_id:
        return True
    if session_started_at is None or record.updated_at < session_started_at:
        return False
    return bool(set(record.evidence_refs).intersection(artifact_ids))


def _latest_career_application_for_session(stack: LiveStack, session_id: str) -> CareerApplication | None:
    records = [
        item for item in stack.career_store.list_career_applications() if item.source_session_id == session_id
    ]
    if not records:
        return None
    return max(records, key=lambda item: item.updated_at)


def _project_action_stage(project_action: str) -> str:
    return {
        "checklist": "项目动作：投递前检查",
        "interview": "项目动作：面试准备",
        "custom_resume": "项目动作：生成定制简历",
    }[project_action]


def _project_action_message(project_action: str, application_id: str) -> str:
    context = (
        f"当前求职项目 application_id 是 {application_id}。"
        "请先调用 career_application_get 读取项目，再复用其中已有的 resume_profile_id、career_profile_id、"
        "jd_analysis_id、job_fit_report_id 和 resume_version_ids。不要重新解析简历，不要重新分析 JD，"
        "不要重新创建 ResumeProfile、JDAnalysis 或 JobFitReport。"
    )
    if project_action == "checklist":
        return (
            f"{context}"
            "请执行投递前检查，判断是否可以投递，检查硬性要求、关键词覆盖、简历事实风险、"
            "JD 高风险点和定制简历状态。请调用 career_application_merge 更新 summary、next_actions 和 risks；"
            "如果生成用户可复用检查报告，可以调用 session_create_text_artifact 创建 Markdown artifact。"
        )
    if project_action == "interview":
        return (
            f"{context}"
            "请生成面试准备方案，覆盖高优先级准备项、技术追问方向、项目表达话术、风险短板补齐和练习题。"
            "请调用 career_application_merge 更新 next_actions、risks 或 notes；如需要复用方案，可以创建 Markdown artifact。"
        )
    if project_action == "custom_resume":
        return (
            f"{context}"
            "请生成或更新一版定制简历。必须调用 career_resume_version_create 保存 ResumeVersion，"
            "再调用 career_application_merge 把新的 resume_version_id 合并进当前求职项目。"
            "简历正文只能使用已有产品记录和源 artifact 明确出现的事实，不要编造指标或经历。"
            "ResumeVersion 的 content、change_summary、keyword_strategy、risk_notes 都不能包含"
            "“占位”“替换为真实数据”“待填”“待补”“待完善”“TODO”“TBD”。"
        )
    raise ValueError(f"Unsupported project action: {project_action}")


def infer_failure_stage(report: FlowReport) -> str:
    missing = set(report.missing_records)
    if missing.intersection({"resume_profiles", "career_profiles"}):
        return "简历诊断与画像沉淀"
    if missing.intersection({"jd_analyses", "job_fit_reports"}):
        return "JD 匹配分析"
    if "resume_versions" in missing:
        return "定制简历版本"
    if "career_applications" in missing:
        return "求职项目闭环"
    if report.failed_tools:
        return infer_stage_from_tool(report.failed_tools[0])
    if report.consistency_errors:
        return "产品数据一致性检查"
    if any("工具调用轮次上限" in error or "Tool call limit reached" in error for error in report.errors):
        return "工具轮次控制"
    if any("path/file_path/workspace_path" in error for error in report.errors):
        return "工具参数边界检查"
    return "结果检查"


def infer_stage_from_tool(tool_name: str) -> str:
    if tool_name in {"career_resume_profile_save", "career_profile_merge"}:
        return "简历诊断与画像沉淀"
    if tool_name in {"career_jd_analysis_save", "career_job_fit_report_save"}:
        return "JD 匹配分析"
    if tool_name == "career_resume_version_create":
        return "定制简历版本"
    if tool_name.startswith("career_application_"):
        return "求职项目闭环"
    if tool_name == "delegate_agents":
        return "multi-agent 委派"
    return "工具执行"


def add_resume_artifact(repository: JsonlSessionRepository, *, session_id: str, artifact_id: str) -> None:
    content = """候选人：张三
目标方向：AI 应用开发 / 后端工程师
技能：Python、FastAPI、PostgreSQL、Redis、RAG、Agent 工具调用
项目：构建过简历诊断 Agent，支持多 agent 委派、artifact 管理、结构化画像和岗位匹配报告。
经历：3 年后端开发经验，负责 API、任务队列、日志审计和部署。
教育：计算机相关专业本科。
"""
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    original_path = artifact_dir / "original.bin"
    text_path = artifact_dir / "content.txt"
    original_path.write_text(content, encoding="utf-8")
    text_path.write_text(content, encoding="utf-8")
    now = app_now()
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="uploaded_file",
            title="候选人简历.txt",
            media_type="text/plain",
            size_bytes=original_path.stat().st_size,
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath=str(original_path.relative_to(root)),
            text_relpath=str(text_path.relative_to(root)),
            text_char_count=len(content),
            token_estimate=max(1, (len(content) + 3) // 4),
            parsed_at=now,
        )
    )


def run_context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_live_{uuid4().hex[:12]}",
        agent_id="agent_main",
        turn_id=f"turn_live_{uuid4().hex[:12]}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={"verbose": True},
    )


def tool_call_counts(repository: JsonlSessionRepository, session_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in _all_relevant_events(repository, session_id):
        if event.type != "tool_call" or not isinstance(event.payload, dict):
            continue
        name = event.payload.get("name")
        if isinstance(name, str):
            counts[name] = counts.get(name, 0) + 1
    return counts


def diff_tool_calls(before: dict[str, int], after: dict[str, int]) -> list[str]:
    output: list[str] = []
    for name in sorted(after):
        delta = after[name] - before.get(name, 0)
        output.extend([name] * max(0, delta))
    return output


def failed_tool_result_payloads(repository: JsonlSessionRepository, session_id: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for event in _all_relevant_events(repository, session_id):
        if event.type != "tool_result" or not isinstance(event.payload, dict):
            continue
        if event.payload.get("success") is False:
            payloads.append(event.payload)
    return payloads


def tool_limit_detected(repository: JsonlSessionRepository, session_id: str) -> bool:
    for event in _all_relevant_events(repository, session_id):
        payload = event.payload if isinstance(event.payload, dict) else {}
        text = json.dumps(payload, ensure_ascii=False)
        if "Tool call limit reached" in text:
            return True
    return False


def path_argument_leaked(repository: JsonlSessionRepository, session_id: str) -> bool:
    forbidden = {"path", "file_path", "workspace_path", "absolute_path", "relative_path"}
    for event in _all_relevant_events(repository, session_id):
        if event.type != "tool_call" or not isinstance(event.payload, dict):
            continue
        args = event.payload.get("arguments")
        if isinstance(args, dict) and forbidden.intersection(args.keys()):
            return True
    return False


def latest_event_summaries(repository: JsonlSessionRepository, session_id: str, *, limit: int = 8) -> list[str]:
    events = sorted(_all_relevant_events(repository, session_id), key=lambda item: item.created_at)
    output: list[str] = []
    for event in events[-limit:]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        summary = ""
        if event.type == "tool_call":
            summary = f"tool={payload.get('name')} args={_compact_json(payload.get('arguments'))}"
        elif event.type == "tool_result":
            summary = (
                f"tool={payload.get('tool_name')} success={payload.get('success')} "
                f"content={str(payload.get('content', ''))[:180]}"
            )
        elif event.type in {"assistant_message", "agent_result_summary"}:
            summary = str(payload.get("content") or payload.get("summary") or "")[:180]
        elif event.type == "agent_task_assigned":
            summary = f"target={payload.get('target_agent_id')} task={payload.get('task_id')}"
        else:
            summary = _compact_json(payload)[:180]
        output.append(f"{event.created_at.isoformat()} {event.agent_id} {event.type}: {summary}")
    return output


def _all_relevant_events(repository: JsonlSessionRepository, session_id: str) -> list[Any]:
    events = (
        repository.list_events(session_id)
        + repository.list_agent_events(session_id, "agent_main")
        + repository.list_agent_events(session_id, "resume_agent")
        + repository.list_agent_events(session_id, "job_agent")
    )
    output: list[Any] = []
    seen_event_ids: set[str] = set()
    for event in events:
        event_id = getattr(event, "event_id", "")
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        output.append(event)
    return output


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:240]
    except (TypeError, ValueError):
        return str(value)[:240]


def _compact_text(value: str, max_chars: int) -> str:
    normalized = " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars].rstrip()}..."


def _preview_list(values: list[str], *, limit: int) -> str:
    if not values:
        return "[]"
    visible = values[:limit]
    suffix = "" if len(values) <= limit else f", ... +{len(values) - limit}"
    return "[" + ", ".join(visible) + suffix + "]"


def _record_counts(record_ids: dict[str, list[str]]) -> str:
    if not record_ids:
        return "{}"
    counts = {key: len(value) for key, value in sorted(record_ids.items())}
    return json.dumps(counts, ensure_ascii=False, sort_keys=True)


async def run_all(args: argparse.Namespace) -> list[FlowReport]:
    settings = Settings.load()
    root_data_dir = Path(args.data_dir)
    root_data_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(args.concurrency)

    def progress(message: str) -> None:
        if args.quiet:
            return
        now = to_app_iso(app_now())
        print(f"[{now}] {message}", flush=True)

    async def run_one(index: int) -> FlowReport:
        async with semaphore:
            return await asyncio.to_thread(
                run_live_flow,
                run_index=index,
                root_data_dir=root_data_dir,
                settings=settings,
                max_tool_rounds=args.max_tool_rounds,
                project_action=args.project_action,
                progress=progress,
            )

    tasks = [asyncio.create_task(run_one(index)) for index in range(1, args.runs + 1)]
    return await asyncio.gather(*tasks)


def print_report(reports: list[FlowReport]) -> None:
    print()
    print("=== 求职 Agent Live Smoke 报告 ===")
    if not reports:
        print("没有执行任何 run。")
        return
    elapsed_values = [item.elapsed_seconds for item in reports]
    print(f"运行数: {len(reports)}")
    print(f"成功数: {sum(1 for item in reports if item.success)}")
    print(f"失败数: {sum(1 for item in reports if not item.success)}")
    print(f"平均耗时: {statistics.fmean(elapsed_values):.2f}s")
    print(f"最大耗时: {max(elapsed_values):.2f}s")
    print()
    for item in reports:
        status = "通过" if item.success else "失败"
        print(f"--- Run {item.run_index}: {status} ---")
        print(f"session_id: {item.session_id}")
        print(f"data_dir: {item.data_dir}")
        print(f"elapsed: {item.elapsed_seconds:.2f}s")
        for turn in item.turns:
            print(f"  [{turn.name}] {turn.elapsed_seconds:.2f}s tools={_preview_list(turn.tool_calls, limit=8)}")
            print(f"    answer_preview: {_compact_text(turn.answer, 120)}")
        print(f"  record_counts: {_record_counts(item.record_ids)}")
        print(f"  artifact_count: {len(item.artifact_ids)} ids={_preview_list(item.artifact_ids, limit=8)}")
        print(f"  tool_call_counts: {_compact_json(item.tool_call_counts)}")
        if item.quality_gate_passed is not None:
            gate = "通过" if item.quality_gate_passed else "失败"
            print(f"  质量门禁: {gate} error_codes={_preview_list(item.quality_error_codes, limit=6)}")
        if not item.success:
            print("  失败摘要:")
            print(f"    失败阶段: {item.failed_stage or '未定位'}")
            print(f"    缺失产品记录: {_preview_list(item.missing_records, limit=8)}")
            print(f"    失败工具: {_preview_list(item.failed_tools, limit=8)}")
            if item.quality_error_codes:
                print(f"    质量错误码: {_preview_list(item.quality_error_codes, limit=6)}")
            if item.consistency_errors:
                print(f"    一致性错误: {_preview_list(item.consistency_errors, limit=3)}")
            if item.errors:
                print(f"    关键错误: {_preview_list(item.errors, limit=3)}")
        if item.quality_findings:
            print("  quality_findings:")
            for finding in item.quality_findings[:8]:
                print(f"    - {_compact_text(finding, 260)}")
            if len(item.quality_findings) > 8:
                print(f"    - ... +{len(item.quality_findings) - 8} more")
        if item.errors:
            print("  errors_detail:")
            for error in item.errors[:5]:
                print(f"    - {_compact_text(error, 260)}")
            if len(item.errors) > 5:
                print(f"    - ... +{len(item.errors) - 5} more")
        if item.last_events:
            print("  last_events:")
            for event in item.last_events:
                print(f"    - {event}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行真实模型的求职 Agent smoke/stress 链路。")
    parser.add_argument("--runs", type=int, default=1, help="执行完整三轮求职链路的次数。")
    parser.add_argument("--concurrency", type=int, default=1, help="并发 run 数；每个 run 使用独立 data 子目录。")
    parser.add_argument("--data-dir", type=Path, default=Path("data/live_career_smoke"), help="输出数据根目录。")
    parser.add_argument("--max-tool-rounds", type=int, default=8, help="每轮对话允许的最大工具轮次。")
    parser.add_argument(
        "--project-action",
        choices=("none", "checklist", "interview", "custom_resume"),
        default="none",
        help="是否追加一轮基于 application_id 的项目动作验证；默认不追加以控制 live smoke 成本。",
    )
    parser.add_argument("--verbose", action="store_true", help="打开应用日志。")
    parser.add_argument("--quiet", action="store_true", help="关闭逐 run / 逐阶段进度输出，只打印最终报告。")
    args = parser.parse_args()
    if args.runs <= 0:
        parser.error("--runs must be positive")
    if args.concurrency <= 0:
        parser.error("--concurrency must be positive")
    if args.max_tool_rounds < 1 or args.max_tool_rounds > 10:
        parser.error("--max-tool-rounds must be in range 1..10")
    return args


def _progress(progress: Callable[[str], None] | None, run_index: int, message: str) -> None:
    if progress is not None:
        progress(f"Run {run_index}: {message}")


def main() -> None:
    args = parse_args()
    logging.getLogger().setLevel(logging.INFO if args.verbose else logging.CRITICAL)
    started = app_now()
    print("Live smoke started:", to_app_iso(started))
    print(f"runs={args.runs} concurrency={args.concurrency} data_dir={args.data_dir}")
    reports = asyncio.run(run_all(args))
    print_report(reports)
    ended = app_now()
    print("Live smoke finished:", to_app_iso(ended))
    if any(not item.success for item in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
