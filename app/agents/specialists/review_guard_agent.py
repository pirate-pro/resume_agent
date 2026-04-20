from app.agents.execution_modes import ModeActionResult, ReActExecutor, ReActLoopStep
from app.agents.runtime import AgentResult, AgentToolTrace
from app.agents.specialists.contracts import ReviewGuardContext
from app.agents.tools.draft_quality_tool import DraftQualityIssue, DraftQualityTool
from app.domain.models.review import ReviewIssue, ReviewReport
from app.domain.services.review_guard_service import ReviewGuardService


class ReviewGuardAgent:
    def __init__(
        self,
        service: ReviewGuardService | None = None,
        quality_tool: DraftQualityTool | None = None,
    ) -> None:
        self._service = service or ReviewGuardService()
        self._quality_tool = quality_tool or DraftQualityTool()
        self._executor = ReActExecutor()

    def run(
        self,
        context: ReviewGuardContext,
    ) -> AgentResult:
        def step_runner(step_index: int, state: dict) -> tuple[ReActLoopStep, ModeActionResult, bool]:
            if step_index == 0:
                quality_report = self._quality_tool.inspect(
                    context.profile,
                    context.match_result,
                    context.draft,
                    expected_job_title=context.target_job_title,
                )
                state["quality_report"] = quality_report
                return (
                    ReActLoopStep(
                        thought="Evaluate whether draft structure and evidence boundaries are safe.",
                        action="draft_quality_review",
                        observation="Draft quality inspection completed.",
                    ),
                    ModeActionResult(
                        payload=quality_report,
                        tool_traces=[
                            AgentToolTrace(
                                tool_name="draft_quality_review",
                                status="completed",
                                detail=f"blocking={quality_report.blocking_issue_count}, advisory={quality_report.advisory_issue_count}",
                            )
                        ],
                    ),
                    False,
                )

            if step_index == 1:
                review_report = self._service.review(context.profile, context.match_result, context.draft)
                state["review_report"] = review_report
                return (
                    ReActLoopStep(
                        thought="Check semantic compliance with evidence and prohibited attributes policy.",
                        action="review_guard_service",
                        observation="ReviewGuard compliance analysis completed.",
                    ),
                    ModeActionResult(
                        payload=review_report,
                        tool_traces=[
                            AgentToolTrace(
                                tool_name="review_guard_service",
                                status="completed",
                                detail=f"issues={len(review_report.issues)}",
                            )
                        ],
                    ),
                    False,
                )

            quality_report = state.get("quality_report")
            review_report = state.get("review_report")
            if not isinstance(review_report, ReviewReport):
                review_report = ReviewReport(allow_delivery=False, risk_level="high", issues=[ReviewIssue(level="high", message="review_report_missing")])
            quality_issues = quality_report.issues if quality_report is not None else []
            normalized_report = self._apply_delivery_policy(review_report, quality_issues)
            state["normalized_report"] = normalized_report
            return (
                ReActLoopStep(
                    thought="Apply deterministic delivery gate after reasoning steps.",
                    action="delivery_policy",
                    observation=f"Delivery policy decided allow_delivery={normalized_report.allow_delivery}.",
                ),
                ModeActionResult(
                    payload=normalized_report,
                    tool_traces=[
                        AgentToolTrace(
                            tool_name="delivery_policy",
                            status="completed",
                            detail=f"allow_delivery={normalized_report.allow_delivery}",
                        )
                    ],
                ),
                True,
            )

        execution = self._executor.execute(
            objective=context.objective,
            max_steps=3,
            step_runner=step_runner,
        )
        normalized_report = execution.state.get("normalized_report")
        if not isinstance(normalized_report, ReviewReport):
            return AgentResult(
                status="failed",
                output=None,
                observations=[context.objective, *execution.observations],
                tool_traces=execution.tool_traces,
                confidence=0.0,
                failure_reason="review_normalization_failed",
                metadata={
                    "mode": "react",
                    "context_id": context.context_id,
                    "parent_context_id": context.parent_context_id,
                    "loop": [self._loop_step_to_dict(step) for step in execution.loop],
                },
            )

        blocked = not normalized_report.allow_delivery
        observations = [context.objective, *execution.observations]
        observations.append("Delivery blocked due to unresolved high-risk issues." if blocked else "Draft passed delivery policy.")
        observations.extend(issue.message for issue in normalized_report.issues[:3])
        return AgentResult(
            status="blocked" if blocked else "completed",
            output=normalized_report,
            observations=observations,
            tool_traces=execution.tool_traces,
            confidence=self._resolve_confidence(execution.state.get("quality_report")),
            next_stage_hint="deliver" if not blocked else "blocked",
            metadata={
                "mode": "react",
                "context_id": context.context_id,
                "parent_context_id": context.parent_context_id,
                "quality_report": self._resolve_quality_report(execution.state.get("quality_report")),
                "loop": [self._loop_step_to_dict(step) for step in execution.loop],
            },
        )

    def _apply_delivery_policy(
        self,
        review_report: ReviewReport,
        quality_issues: list[DraftQualityIssue],
    ) -> ReviewReport:
        merged = {(issue.level, issue.message): issue for issue in review_report.issues}
        for issue in quality_issues:
            merged.setdefault((issue.level, issue.message), ReviewIssue(level=issue.level, message=issue.message))
        issues = list(merged.values())
        allow_delivery = not any(issue.level == "high" for issue in issues)
        risk_level = "high" if not allow_delivery else ("medium" if issues else "low")
        return ReviewReport(allow_delivery=allow_delivery, risk_level=risk_level, issues=issues)

    def _resolve_confidence(self, quality_report: object) -> float:
        if quality_report is None:
            return 0.0
        return float(getattr(quality_report, "confidence", 0.0))

    def _resolve_quality_report(self, quality_report: object) -> dict:
        if quality_report is None:
            return {}
        to_dict = getattr(quality_report, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        return {}

    def _loop_step_to_dict(self, step: ReActLoopStep) -> dict:
        return {"thought": step.thought, "action": step.action, "observation": step.observation}
