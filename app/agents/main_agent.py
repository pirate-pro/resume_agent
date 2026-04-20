from __future__ import annotations

from app.agents.context_store import AgentContextStore
from app.agents.execution_modes import ModeActionResult, PlanAndSolveExecutor, PlanStep
from app.agents.runtime import AgentResult, AgentToolTrace, serialize_payload
from app.agents.specialists.contracts import ResumeOptimizationContext, ReviewGuardContext
from app.agents.specialists.resume_optimize_agent import ResumeOptimizeAgent
from app.agents.specialists.review_guard_agent import ReviewGuardAgent
from app.agents.trace.agent_run_recorder import AgentRunRecorder
from app.core.db.models.entities import JobPosting
from app.domain.models.candidate import CandidateProfile
from app.domain.models.matching import MatchResult
from app.domain.models.optimization import OptimizationDraft


class MainWorkflowAgent:
    def __init__(
        self,
        *,
        optimize_agent: ResumeOptimizeAgent | None = None,
        review_agent: ReviewGuardAgent | None = None,
    ) -> None:
        self._optimize_agent = optimize_agent or ResumeOptimizeAgent()
        self._review_agent = review_agent or ReviewGuardAgent()
        self._executor = PlanAndSolveExecutor()

    def run_optimization(
        self,
        *,
        task_id: str,
        attempt: int,
        profile: CandidateProfile,
        target_job: JobPosting,
        match_result: MatchResult,
    ) -> AgentResult:
        objective = "Create targeted resume draft with auditable tool traces."
        recorder = AgentRunRecorder(
            task_id=task_id,
            stage="optimize",
            mode="plan_and_solve",
            objective=objective,
            attempt=attempt,
        )
        context_store = AgentContextStore()
        main_context = context_store.new_context(
            agent_name="MainWorkflowAgent",
            mode="plan_and_solve",
            task_id=task_id,
            shared_refs={"target_job_id": target_job.id, "stage": "optimize"},
        )
        recorder.record_contexts(context_store.to_dict())
        recorder.log_event(
            "context.created",
            {"agent_name": main_context.agent_name, "context_id": main_context.context_id},
            agent_name=main_context.agent_name,
            context_id=main_context.context_id,
        )
        plan_steps: list[PlanStep] = []

        def planner(_: str) -> list[PlanStep]:
            nonlocal plan_steps
            plan_steps = [
                PlanStep("analyze_task", "Analyze optimization objective and create sub-agent context."),
                PlanStep("delegate_sub_agent", "Delegate draft generation to ResumeOptimizeAgent."),
                PlanStep("finalize_result", "Validate delegated result and emit final output."),
            ]
            recorder.log_event(
                "plan.created",
                {"steps": [step.description for step in plan_steps]},
                agent_name=main_context.agent_name,
                context_id=main_context.context_id,
            )
            return plan_steps

        def solver(step: PlanStep, state: dict) -> ModeActionResult:
            recorder.log_event(
                "plan.step.started",
                {"step_id": step.step_id, "description": step.description},
                agent_name=main_context.agent_name,
                context_id=main_context.context_id,
            )
            if step.step_id == "analyze_task":
                main_context.local_memory["objective"] = "Produce a job-targeted resume draft with evidence boundaries."
                action = ModeActionResult(
                    payload={"context_id": main_context.context_id},
                    observations=["Main agent prepared optimization task context."],
                    tool_traces=[AgentToolTrace(tool_name="task_analysis", status="completed")],
                )
                recorder.log_event(
                    "plan.step.completed",
                    {
                        "step_id": step.step_id,
                        "payload": action.payload,
                        "observations": action.observations,
                    },
                    agent_name=main_context.agent_name,
                    context_id=main_context.context_id,
                )
                return action

            if step.step_id == "delegate_sub_agent":
                sub_context = context_store.new_context(
                    agent_name="ResumeOptimizeAgent",
                    mode="reflection",
                    task_id=task_id,
                    parent_context_id=main_context.context_id,
                    shared_refs={"target_job_id": target_job.id, "main_context_id": main_context.context_id},
                )
                sub_result = self._optimize_agent.run(
                    ResumeOptimizationContext(
                        profile=profile,
                        target_job=target_job,
                        match_result=match_result,
                        task_id=task_id,
                        context_id=sub_context.context_id,
                        parent_context_id=main_context.context_id,
                        attempt=attempt,
                        local_memory=sub_context.local_memory,
                        shared_refs=sub_context.shared_refs,
                    )
                )
                state["sub_result"] = sub_result
                recorder.record_contexts(context_store.to_dict())
                recorder.log_event(
                    "sub_agent.dispatched",
                    {
                        "agent_name": sub_context.agent_name,
                        "mode": sub_context.mode,
                        "context_id": sub_context.context_id,
                    },
                    agent_name=main_context.agent_name,
                    context_id=main_context.context_id,
                )
                action = ModeActionResult(
                    payload={"status": sub_result.status, "context_id": sub_context.context_id},
                    observations=["Main agent delegated optimization to ResumeOptimizeAgent."],
                    tool_traces=[
                        AgentToolTrace(
                            tool_name="dispatch_resume_optimize_agent",
                            status="completed",
                            detail=f"context_id={sub_context.context_id}, status={sub_result.status}",
                        ),
                        *sub_result.tool_traces,
                    ],
                )
                recorder.log_event(
                    "sub_agent.completed",
                    {
                        "agent_name": sub_context.agent_name,
                        "status": sub_result.status,
                        "confidence": sub_result.confidence,
                        "next_stage_hint": sub_result.next_stage_hint,
                    },
                    agent_name=sub_context.agent_name,
                    context_id=sub_context.context_id,
                )
                recorder.log_event(
                    "plan.step.completed",
                    {
                        "step_id": step.step_id,
                        "payload": action.payload,
                        "tool_traces": [trace.to_dict() for trace in action.tool_traces[:6]],
                    },
                    agent_name=main_context.agent_name,
                    context_id=main_context.context_id,
                )
                return action

            if step.step_id == "finalize_result":
                sub_result = state.get("sub_result")
                if not isinstance(sub_result, AgentResult):
                    action = ModeActionResult(
                        payload={"status": "failed"},
                        observations=["Sub-agent result missing; cannot finalize optimization output."],
                        tool_traces=[
                            AgentToolTrace(
                                tool_name="finalize_optimization",
                                status="failed",
                                detail="sub_agent_result_missing",
                            )
                        ],
                    )
                    recorder.log_event(
                        "plan.step.completed",
                        {"step_id": step.step_id, "payload": action.payload},
                        level="error",
                        agent_name=main_context.agent_name,
                        context_id=main_context.context_id,
                    )
                    return action
                detail = "ready" if isinstance(sub_result.output, OptimizationDraft) else "invalid_output_type"
                action = ModeActionResult(
                    payload={"status": sub_result.status, "output_type": detail},
                    observations=["Main agent finalized optimization result."],
                    tool_traces=[AgentToolTrace(tool_name="finalize_optimization", status="completed", detail=detail)],
                )
                recorder.log_event(
                    "plan.step.completed",
                    {"step_id": step.step_id, "payload": action.payload},
                    agent_name=main_context.agent_name,
                    context_id=main_context.context_id,
                )
                return action

            action = ModeActionResult(
                payload={"status": "failed"},
                observations=[f"Unsupported plan step: {step.step_id}"],
                tool_traces=[AgentToolTrace(tool_name="unsupported_step", status="failed", detail=step.step_id)],
            )
            recorder.log_event(
                "plan.step.completed",
                {"step_id": step.step_id, "payload": action.payload},
                level="error",
                agent_name=main_context.agent_name,
                context_id=main_context.context_id,
            )
            return action

        delegated_agent = {"name": "ResumeOptimizeAgent", "mode": "reflection"}
        try:
            execution = self._executor.execute(
                objective=objective,
                planner=planner,
                solver=solver,
            )
            sub_result = execution.state.get("sub_result")
            if not isinstance(sub_result, AgentResult):
                result = AgentResult(
                    status="failed",
                    output=None,
                    observations=execution.observations,
                    tool_traces=execution.tool_traces,
                    confidence=0.0,
                    failure_reason="resume_optimize_sub_agent_missing",
                    metadata={
                        "mode": "plan_and_solve",
                        "contexts": context_store.to_dict(),
                        "plan": [step.description for step in execution.plan],
                        "delegated_agent": delegated_agent,
                    },
                )
            else:
                status = "failed" if sub_result.status == "failed" else "completed"
                result = AgentResult(
                    status=status,
                    output=sub_result.output,
                    observations=execution.observations + sub_result.observations,
                    tool_traces=execution.tool_traces,
                    confidence=sub_result.confidence,
                    next_stage_hint="review" if status == "completed" else None,
                    failure_reason=sub_result.failure_reason if status == "failed" else None,
                    metadata={
                        "mode": "plan_and_solve",
                        "contexts": context_store.to_dict(),
                        "plan": [step.description for step in execution.plan],
                        "delegated_agent": delegated_agent,
                        "delegated_result": sub_result.to_dict(),
                    },
                )
        except Exception as exc:
            recorder.log_event(
                "run.exception",
                {"error": str(exc)},
                level="error",
                agent_name=main_context.agent_name,
                context_id=main_context.context_id,
            )
            result = AgentResult(
                status="failed",
                output=None,
                observations=["Main workflow agent execution raised an exception."],
                tool_traces=[AgentToolTrace(tool_name="main_agent_exception", status="failed", detail=str(exc))],
                confidence=0.0,
                failure_reason=str(exc),
                metadata={
                    "mode": "plan_and_solve",
                    "contexts": context_store.to_dict(),
                    "plan": [step.description for step in plan_steps],
                    "delegated_agent": delegated_agent,
                },
            )
        return self._finalize_with_trace(
            recorder=recorder,
            result=result,
            context_store=context_store,
            plan_steps=[step.description for step in plan_steps],
            delegated_agent=delegated_agent,
        )

    def run_review(
        self,
        *,
        task_id: str,
        attempt: int,
        profile: CandidateProfile,
        target_job: JobPosting,
        match_result: MatchResult,
        draft: OptimizationDraft,
    ) -> AgentResult:
        objective = "Review optimized resume and decide delivery policy."
        recorder = AgentRunRecorder(
            task_id=task_id,
            stage="review",
            mode="plan_and_solve",
            objective=objective,
            attempt=attempt,
        )
        context_store = AgentContextStore()
        main_context = context_store.new_context(
            agent_name="MainWorkflowAgent",
            mode="plan_and_solve",
            task_id=task_id,
            shared_refs={"target_job_id": target_job.id, "stage": "review"},
        )
        recorder.record_contexts(context_store.to_dict())
        recorder.log_event(
            "context.created",
            {"agent_name": main_context.agent_name, "context_id": main_context.context_id},
            agent_name=main_context.agent_name,
            context_id=main_context.context_id,
        )
        plan_steps: list[PlanStep] = []

        def planner(_: str) -> list[PlanStep]:
            nonlocal plan_steps
            plan_steps = [
                PlanStep("analyze_task", "Analyze review objective and create sub-agent context."),
                PlanStep("delegate_sub_agent", "Delegate policy review to ReviewGuardAgent."),
                PlanStep("finalize_result", "Validate review verdict and emit final output."),
            ]
            recorder.log_event(
                "plan.created",
                {"steps": [step.description for step in plan_steps]},
                agent_name=main_context.agent_name,
                context_id=main_context.context_id,
            )
            return plan_steps

        def solver(step: PlanStep, state: dict) -> ModeActionResult:
            recorder.log_event(
                "plan.step.started",
                {"step_id": step.step_id, "description": step.description},
                agent_name=main_context.agent_name,
                context_id=main_context.context_id,
            )
            if step.step_id == "analyze_task":
                main_context.local_memory["objective"] = "Produce a delivery-safe review verdict."
                action = ModeActionResult(
                    payload={"context_id": main_context.context_id},
                    observations=["Main agent prepared review task context."],
                    tool_traces=[AgentToolTrace(tool_name="task_analysis", status="completed")],
                )
                recorder.log_event(
                    "plan.step.completed",
                    {
                        "step_id": step.step_id,
                        "payload": action.payload,
                        "observations": action.observations,
                    },
                    agent_name=main_context.agent_name,
                    context_id=main_context.context_id,
                )
                return action

            if step.step_id == "delegate_sub_agent":
                sub_context = context_store.new_context(
                    agent_name="ReviewGuardAgent",
                    mode="react",
                    task_id=task_id,
                    parent_context_id=main_context.context_id,
                    shared_refs={"target_job_id": target_job.id, "main_context_id": main_context.context_id},
                )
                sub_result = self._review_agent.run(
                    ReviewGuardContext(
                        profile=profile,
                        match_result=match_result,
                        draft=draft,
                        target_job_title=target_job.job_title,
                        task_id=task_id,
                        context_id=sub_context.context_id,
                        parent_context_id=main_context.context_id,
                        attempt=attempt,
                        local_memory=sub_context.local_memory,
                        shared_refs=sub_context.shared_refs,
                    )
                )
                state["sub_result"] = sub_result
                recorder.record_contexts(context_store.to_dict())
                recorder.log_event(
                    "sub_agent.dispatched",
                    {
                        "agent_name": sub_context.agent_name,
                        "mode": sub_context.mode,
                        "context_id": sub_context.context_id,
                    },
                    agent_name=main_context.agent_name,
                    context_id=main_context.context_id,
                )
                action = ModeActionResult(
                    payload={"status": sub_result.status, "context_id": sub_context.context_id},
                    observations=["Main agent delegated review to ReviewGuardAgent."],
                    tool_traces=[
                        AgentToolTrace(
                            tool_name="dispatch_review_guard_agent",
                            status="completed",
                            detail=f"context_id={sub_context.context_id}, status={sub_result.status}",
                        ),
                        *sub_result.tool_traces,
                    ],
                )
                recorder.log_event(
                    "sub_agent.completed",
                    {
                        "agent_name": sub_context.agent_name,
                        "status": sub_result.status,
                        "confidence": sub_result.confidence,
                        "next_stage_hint": sub_result.next_stage_hint,
                    },
                    agent_name=sub_context.agent_name,
                    context_id=sub_context.context_id,
                )
                recorder.log_event(
                    "plan.step.completed",
                    {
                        "step_id": step.step_id,
                        "payload": action.payload,
                        "tool_traces": [trace.to_dict() for trace in action.tool_traces[:6]],
                    },
                    agent_name=main_context.agent_name,
                    context_id=main_context.context_id,
                )
                return action

            if step.step_id == "finalize_result":
                sub_result = state.get("sub_result")
                status = sub_result.status if isinstance(sub_result, AgentResult) else "failed"
                action = ModeActionResult(
                    payload={"status": status},
                    observations=["Main agent finalized review result."],
                    tool_traces=[AgentToolTrace(tool_name="finalize_review", status="completed", detail=status)],
                )
                recorder.log_event(
                    "plan.step.completed",
                    {"step_id": step.step_id, "payload": action.payload},
                    agent_name=main_context.agent_name,
                    context_id=main_context.context_id,
                )
                return action

            action = ModeActionResult(
                payload={"status": "failed"},
                observations=[f"Unsupported plan step: {step.step_id}"],
                tool_traces=[AgentToolTrace(tool_name="unsupported_step", status="failed", detail=step.step_id)],
            )
            recorder.log_event(
                "plan.step.completed",
                {"step_id": step.step_id, "payload": action.payload},
                level="error",
                agent_name=main_context.agent_name,
                context_id=main_context.context_id,
            )
            return action

        delegated_agent = {"name": "ReviewGuardAgent", "mode": "react"}
        try:
            execution = self._executor.execute(
                objective=objective,
                planner=planner,
                solver=solver,
            )
            sub_result = execution.state.get("sub_result")
            if not isinstance(sub_result, AgentResult):
                result = AgentResult(
                    status="failed",
                    output=None,
                    observations=execution.observations,
                    tool_traces=execution.tool_traces,
                    confidence=0.0,
                    failure_reason="review_guard_sub_agent_missing",
                    metadata={
                        "mode": "plan_and_solve",
                        "contexts": context_store.to_dict(),
                        "plan": [step.description for step in execution.plan],
                        "delegated_agent": delegated_agent,
                    },
                )
            else:
                status = "blocked" if sub_result.status == "blocked" else ("failed" if sub_result.status == "failed" else "completed")
                result = AgentResult(
                    status=status,
                    output=sub_result.output,
                    observations=execution.observations + sub_result.observations,
                    tool_traces=execution.tool_traces,
                    confidence=sub_result.confidence,
                    next_stage_hint="deliver" if status in {"completed", "blocked"} else None,
                    failure_reason=sub_result.failure_reason if status == "failed" else None,
                    metadata={
                        "mode": "plan_and_solve",
                        "contexts": context_store.to_dict(),
                        "plan": [step.description for step in execution.plan],
                        "delegated_agent": delegated_agent,
                        "delegated_result": sub_result.to_dict(),
                    },
                )
        except Exception as exc:
            recorder.log_event(
                "run.exception",
                {"error": str(exc)},
                level="error",
                agent_name=main_context.agent_name,
                context_id=main_context.context_id,
            )
            result = AgentResult(
                status="failed",
                output=None,
                observations=["Main workflow agent execution raised an exception."],
                tool_traces=[AgentToolTrace(tool_name="main_agent_exception", status="failed", detail=str(exc))],
                confidence=0.0,
                failure_reason=str(exc),
                metadata={
                    "mode": "plan_and_solve",
                    "contexts": context_store.to_dict(),
                    "plan": [step.description for step in plan_steps],
                    "delegated_agent": delegated_agent,
                },
            )
        return self._finalize_with_trace(
            recorder=recorder,
            result=result,
            context_store=context_store,
            plan_steps=[step.description for step in plan_steps],
            delegated_agent=delegated_agent,
        )

    def _finalize_with_trace(
        self,
        *,
        recorder: AgentRunRecorder,
        result: AgentResult,
        context_store: AgentContextStore,
        plan_steps: list[str],
        delegated_agent: dict,
    ) -> AgentResult:
        contexts = context_store.to_dict()
        recorder.record_contexts(contexts)
        recorder.log_event(
            "run.completed" if result.status != "failed" else "run.failed",
            {
                "status": result.status,
                "confidence": result.confidence,
                "next_stage_hint": result.next_stage_hint,
                "failure_reason": result.failure_reason,
                "metadata": serialize_payload(result.metadata),
            },
        )
        trace_info = recorder.finalize(
            result=result,
            plan_steps=plan_steps,
            contexts=contexts,
            delegated_agent=delegated_agent,
        )
        metadata = dict(result.metadata)
        metadata["run_trace"] = trace_info
        result.metadata = metadata
        return result
