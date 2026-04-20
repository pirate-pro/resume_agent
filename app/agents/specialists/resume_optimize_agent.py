from app.agents.execution_modes import ModeActionResult, ReflectionExecutor
from app.agents.runtime import AgentResult, AgentToolTrace
from app.agents.specialists.contracts import ResumeOptimizationContext
from app.agents.tools.draft_quality_tool import DraftQualityReport, DraftQualityTool
from app.domain.models.optimization import OptimizationDraft
from app.domain.services.resume_optimization_service import ResumeOptimizationService


class ResumeOptimizeAgent:
    def __init__(
        self,
        service: ResumeOptimizationService | None = None,
        quality_tool: DraftQualityTool | None = None,
    ) -> None:
        self._service = service or ResumeOptimizationService()
        self._quality_tool = quality_tool or DraftQualityTool()
        self._executor = ReflectionExecutor()

    def run(
        self,
        context: ResumeOptimizationContext,
    ) -> AgentResult:
        profile = context.profile
        target_job = context.target_job
        match_result = context.match_result

        def actor() -> ModeActionResult:
            draft = self._service.create_targeted_resume(profile, target_job, match_result)
            return ModeActionResult(
                payload=draft,
                observations=["Generated primary targeted resume draft."],
                tool_traces=[AgentToolTrace(tool_name="targeted_resume_generation", status="completed")],
            )

        def critic(primary_draft: OptimizationDraft) -> ModeActionResult:
            quality_report = self._quality_tool.inspect(
                profile,
                match_result,
                primary_draft,
                expected_job_title=target_job.job_title,
            )
            return ModeActionResult(
                payload=quality_report,
                observations=["Reviewed primary draft quality."],
                tool_traces=[self._quality_trace("draft_quality_review", quality_report)],
            )

        def reviser(primary_draft: OptimizationDraft, quality_report: DraftQualityReport) -> ModeActionResult:
            selected_draft = primary_draft
            selected_report = quality_report
            selected_strategy = "primary"
            observations = []
            tool_traces: list[AgentToolTrace] = []
            if quality_report.has_blocking_issues():
                fallback_draft = self._service.create_rule_based_resume(profile, target_job, match_result)
                tool_traces.append(AgentToolTrace(tool_name="rule_based_resume_fallback", status="completed"))
                fallback_report = self._quality_tool.inspect(
                    profile,
                    match_result,
                    fallback_draft,
                    expected_job_title=target_job.job_title,
                )
                tool_traces.append(self._quality_trace("fallback_draft_quality_review", fallback_report))
                if self._prefer_quality_candidate(fallback_report, quality_report):
                    selected_draft = fallback_draft
                    selected_report = fallback_report
                    selected_strategy = "rule_based_fallback"
                    observations.append("Fallback draft replaced primary draft after reflection.")
                else:
                    selected_strategy = "primary_with_warnings"
                    observations.append("Fallback draft did not improve quality; retained primary draft.")
            return ModeActionResult(
                payload={
                    "draft": selected_draft,
                    "quality_report": selected_report,
                    "selected_strategy": selected_strategy,
                },
                observations=observations,
                tool_traces=tool_traces,
            )

        execution = self._executor.execute(
            objective=context.objective,
            actor=actor,
            critic=critic,
            reviser=reviser,
        )
        final_payload = execution.final_payload if isinstance(execution.final_payload, dict) else {}
        draft = final_payload.get("draft") if isinstance(final_payload.get("draft"), OptimizationDraft) else execution.initial_payload
        quality_report = final_payload.get("quality_report")
        if not isinstance(quality_report, DraftQualityReport):
            quality_report = execution.critique_payload if isinstance(execution.critique_payload, DraftQualityReport) else DraftQualityReport(confidence=0.0, issues=[])
        selected_strategy = str(final_payload.get("selected_strategy", "primary"))
        observations = execution.observations + [issue.message for issue in quality_report.issues[:3]]
        status = "completed" if isinstance(draft, OptimizationDraft) and draft.optimized_resume_markdown.strip() else "failed"
        failure_reason = None if status == "completed" else "optimization_draft_empty"
        return AgentResult(
            status=status,
            output=draft,
            observations=observations,
            tool_traces=execution.tool_traces,
            confidence=quality_report.confidence,
            next_stage_hint="review" if status == "completed" else None,
            failure_reason=failure_reason,
            metadata={
                "mode": "reflection",
                "context_id": context.context_id,
                "parent_context_id": context.parent_context_id,
                "selected_strategy": selected_strategy,
                "quality_report": quality_report.to_dict(),
            },
        )

    def _quality_trace(self, tool_name: str, report: DraftQualityReport) -> AgentToolTrace:
        return AgentToolTrace(
            tool_name=tool_name,
            status="completed",
            detail=f"blocking={report.blocking_issue_count}, advisory={report.advisory_issue_count}",
        )

    def _prefer_quality_candidate(
        self,
        candidate_report: DraftQualityReport,
        baseline_report: DraftQualityReport,
    ) -> bool:
        if candidate_report.blocking_issue_count != baseline_report.blocking_issue_count:
            return candidate_report.blocking_issue_count < baseline_report.blocking_issue_count
        if candidate_report.advisory_issue_count != baseline_report.advisory_issue_count:
            return candidate_report.advisory_issue_count < baseline_report.advisory_issue_count
        return candidate_report.confidence >= baseline_report.confidence
