from __future__ import annotations

import signal
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.main_agent import MainWorkflowAgent
from app.agents.orchestrator.stage_machine import MATCH_STAGES, OPTIMIZATION_STAGES, StageMachine
from app.agents.runtime import AgentResult, serialize_payload
from app.agents.specialists.candidate_profile_agent import CandidateProfileAgent
from app.agents.specialists.job_retrieval_match_agent import JobRetrievalMatchAgent
from app.agents.specialists.resume_parse_agent import ResumeParseAgent
from app.core.config.settings import get_settings
from app.core.db.models.entities import JobMatchResult, MatchTask
from app.core.db.repositories.candidate_repository import CandidateRepository
from app.core.db.repositories.job_repository import JobRepository
from app.core.db.repositories.task_repository import TaskRepository
from app.core.middleware.error_handler import WorkflowError
from app.domain.models.candidate import CandidateProfile, ExperienceFact, ProjectFact, SkillFact
from app.domain.models.matching import GapAnalysis, MatchResult, MatchScoreCard
from app.domain.models.optimization import ChangeItem, OptimizationDraft, RiskNote
from app.domain.models.review import ReviewReport
from app.infra.storage.workspace import WorkspaceManager


class StageExecutionError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


class StageTimeoutError(TimeoutError):
    def __init__(self, stage: str, timeout_sec: int) -> None:
        super().__init__(f"stage_timeout: {stage} exceeded {timeout_sec}s")
        self.stage = stage
        self.timeout_sec = timeout_sec


class WorkflowOrchestrator:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = get_settings()
        self._candidate_repo = CandidateRepository(db)
        self._job_repo = JobRepository(db)
        self._task_repo = TaskRepository(db)
        self._workspace = WorkspaceManager()
        self._parse_agent = ResumeParseAgent()
        self._profile_agent = CandidateProfileAgent()
        self._match_agent = JobRetrievalMatchAgent()
        self._main_agent = MainWorkflowAgent()

    def run_match_task(self, task_id: str) -> dict:
        machine = StageMachine(MATCH_STAGES)
        while True:
            task = self._task_repo.get_match_task(task_id)
            if task is None:
                raise WorkflowError("match_task_not_found", status_code=404)
            if task.task_status in {"completed", "failed", "blocked"}:
                return self.get_match_task_snapshot(task_id)

            if task.stage == "intake":
                self._run_match_intake(task_id)
                machine.ensure_transition("intake", "parse")
                continue
            if task.stage == "parse":
                self._run_match_parse(task_id)
                machine.ensure_transition("parse", "profile")
                continue
            if task.stage == "profile":
                self._run_match_profile(task_id)
                machine.ensure_transition("profile", "retrieve")
                continue
            if task.stage in {"retrieve", "rank", "explain"}:
                self._run_match_retrieve_rank_explain(task_id)
                return self.get_match_task_snapshot(task_id)
            if task.stage == "deliver":
                return self.get_match_task_snapshot(task_id)
            raise WorkflowError(f"unknown_match_stage: {task.stage}", status_code=500)

    def run_optimization_task(self, optimization_task_id: str) -> dict:
        machine = StageMachine(OPTIMIZATION_STAGES)
        while True:
            task = self._task_repo.get_optimization_task(optimization_task_id)
            if task is None:
                raise WorkflowError("optimization_task_not_found", status_code=404)
            if task.status in {"completed", "failed", "blocked"}:
                return self.get_optimization_snapshot(optimization_task_id)

            if task.stage == "optimize":
                self._run_optimization_stage(optimization_task_id)
                machine.ensure_transition("optimize", "review")
                continue
            if task.stage == "review":
                self._run_review_stage(optimization_task_id)
                return self.get_optimization_snapshot(optimization_task_id)
            if task.stage == "deliver":
                return self.get_optimization_snapshot(optimization_task_id)
            raise WorkflowError(f"unknown_optimization_stage: {task.stage}", status_code=500)

    def get_match_task_snapshot(self, task_id: str) -> dict:
        task = self._task_repo.get_match_task(task_id)
        if task is None:
            raise WorkflowError("match_task_not_found", status_code=404)
        results = self._task_repo.list_match_results(task_id)
        events = self._task_repo.list_events(task_id)
        jobs = {job.id: job for job in self._job_repo.list_jobs()}
        return {
            "task_id": task.id,
            "task_status": task.task_status,
            "stage": task.stage,
            "candidate_id": task.candidate_id,
            "resume_id": task.resume_id,
            "failure_reason": task.failure_reason,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "stage_timeout_sec": task.stage_timeout_sec,
            "matches": [
                {
                    "job_posting_id": result.job_posting_id,
                    "company_name": jobs[result.job_posting_id].company.name if result.job_posting_id in jobs else "",
                    "job_title": jobs[result.job_posting_id].job_title if result.job_posting_id in jobs else "",
                    "city": jobs[result.job_posting_id].city if result.job_posting_id in jobs else None,
                    "score_card": {
                        "overall_score": result.overall_score,
                        "skill_score": result.skill_score,
                        "experience_score": result.experience_score,
                        "project_score": result.project_score,
                        "education_score": result.education_score,
                        "preference_score": result.preference_score,
                    },
                    "explanation": result.explanation_json,
                    "gap": result.gap_json,
                    "rank_no": result.rank_no,
                }
                for result in results
            ],
            "events": [
                {
                    "event_type": event.event_type,
                    "payload": event.event_payload_json,
                    "created_at": event.created_at,
                }
                for event in events
            ],
        }

    def get_optimization_snapshot(self, task_id: str) -> dict:
        task = self._task_repo.get_optimization_task(task_id)
        if task is None:
            raise WorkflowError("optimization_task_not_found", status_code=404)
        result = self._task_repo.get_optimization_result(task_id)
        events = self._task_repo.list_events(task_id)
        return {
            "task_id": task.id,
            "task_status": task.status,
            "status": task.status,
            "stage": task.stage,
            "target_job_id": task.target_job_id,
            "failure_reason": task.failure_reason,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "stage_timeout_sec": task.stage_timeout_sec,
            "optimized_resume_markdown": result.optimized_resume_markdown if result else "",
            "change_summary": result.change_summary_json if result else [],
            "risk_notes": result.risk_note_json if result else [],
            "review_report": result.review_report_json if result else {},
            "events": [
                {
                    "event_type": event.event_type,
                    "payload": event.event_payload_json,
                    "created_at": event.created_at,
                }
                for event in events
            ],
        }

    def _run_match_intake(self, task_id: str) -> None:
        task = self._require_match_task(task_id)
        resume = self._candidate_repo.get_resume(task.resume_id)
        if resume is None:
            raise WorkflowError("resume_not_found", status_code=404)
        self._mark_match_stage_started(task_id, "intake")
        self._workspace.copy_resume_into_workspace(resume.file_path, task.id, resume.file_name)
        self._task_repo.log_event(task.id, "task.started", {"stage": "intake"})
        self._task_repo.update_match_task(task.id, stage="parse", stage_started_at=None, failure_reason=None)
        self._db.commit()

    def _run_match_parse(self, task_id: str) -> None:
        task = self._require_match_task(task_id)
        resume = self._candidate_repo.get_resume(task.resume_id)
        if resume is None:
            raise WorkflowError("resume_not_found", status_code=404)
        self._mark_match_stage_started(task_id, "parse")
        parse_result = self._execute_agent(
            parent_task_id=task.id,
            task_type="match",
            agent_role="ResumeParseAgent",
            input_json={"file_path": resume.file_path},
            retry_count=task.retry_count,
            timeout_sec=task.stage_timeout_sec,
            stage="parse",
            runner=lambda: self._parse_agent.run(resume.file_path),
        )
        self._candidate_repo.replace_blocks(resume.id, parse_result.blocks)
        self._candidate_repo.update_resume_status(resume.id, "parsed")
        self._workspace.write_artifact(task.id, "parse_result.json", parse_result.to_dict())
        self._task_repo.log_event(task.id, "stage.parse.completed", parse_result.to_dict())
        self._task_repo.update_match_task(task.id, stage="profile", stage_started_at=None, failure_reason=None)
        self._db.commit()

    def _run_match_profile(self, task_id: str) -> None:
        task = self._require_match_task(task_id)
        self._mark_match_stage_started(task_id, "profile")
        parse_payload = self._workspace.read_artifact(task.id, "parse_result.json")
        parse_result = self._resume_parse_result_from_dict(parse_payload)
        profile = self._execute_agent(
            parent_task_id=task.id,
            task_type="match",
            agent_role="CandidateProfileAgent",
            input_json={"resume_id": task.resume_id},
            retry_count=task.retry_count,
            timeout_sec=task.stage_timeout_sec,
            stage="profile",
            runner=lambda: self._profile_agent.run(task.candidate_id, task.resume_id, parse_result),
        )
        profile.target_city = task.input_json.get("target_city") or profile.target_city
        self._candidate_repo.upsert_profile(profile)
        candidate = self._candidate_repo.get_candidate(task.candidate_id)
        candidate.name = profile.name
        candidate.email = profile.email
        candidate.phone = profile.phone
        candidate.target_city = profile.target_city
        self._db.add(candidate)
        self._workspace.write_artifact(task.id, "candidate_profile.json", profile.to_dict())
        self._task_repo.log_event(task.id, "stage.profile.completed", profile.to_dict())
        self._task_repo.update_match_task(task.id, stage="retrieve", stage_started_at=None, failure_reason=None)
        self._db.commit()

    def _run_match_retrieve_rank_explain(self, task_id: str) -> None:
        task = self._require_match_task(task_id)
        self._mark_match_stage_started(task_id, "retrieve")
        profile_row = self._candidate_repo.get_profile(task.resume_id)
        if profile_row is None:
            raise WorkflowError("candidate_profile_not_found", status_code=400)
        profile = self._candidate_profile_from_row(profile_row.profile_json)
        jobs = self._job_repo.list_jobs()
        results = self._execute_agent(
            parent_task_id=task.id,
            task_type="match",
            agent_role="JobRetrievalMatchAgent",
            input_json={"job_count": len(jobs)},
            retry_count=task.retry_count,
            timeout_sec=task.stage_timeout_sec,
            stage="retrieve",
            runner=lambda: self._match_agent.run(profile, jobs, self._settings.top_k),
        )
        self._task_repo.log_event(task.id, "stage.retrieve.completed", {"job_count": len(results)})
        self._task_repo.update_match_task(task.id, stage="rank", stage_started_at=None, failure_reason=None)
        self._task_repo.log_event(task.id, "stage.rank.completed", {"ranked_count": len(results)})
        self._task_repo.replace_match_results(task.id, results)
        self._workspace.write_artifact(task.id, "match_results.json", [item.to_dict() for item in results])
        self._task_repo.update_match_task(task.id, stage="explain", stage_started_at=None, failure_reason=None)
        self._task_repo.log_event(task.id, "stage.explain.completed", {"explained_count": len(results)})
        self._task_repo.update_match_task(
            task.id,
            task_status="completed",
            stage="deliver",
            locked_at=None,
            locked_by=None,
            stage_started_at=None,
            failure_reason=None,
        )
        self._task_repo.log_event(task.id, "task.completed", {"stage": "deliver"})
        self._db.commit()

    def _run_optimization_stage(self, task_id: str) -> None:
        task = self._require_optimization_task(task_id)
        resume = self._candidate_repo.get_resume(task.resume_id)
        if resume is None:
            raise WorkflowError("resume_not_found", status_code=404)
        self._mark_optimization_stage_started(task_id, "optimize")
        self._workspace.copy_resume_into_workspace(resume.file_path, task.id, resume.file_name)
        profile_row = self._candidate_repo.get_profile(task.resume_id)
        if profile_row is None:
            raise WorkflowError("candidate_profile_not_found", status_code=400)
        profile = self._candidate_profile_from_row(profile_row.profile_json)
        target_job = self._job_repo.get_job(task.target_job_id)
        if target_job is None:
            raise WorkflowError("job_not_found", status_code=404)
        match_result = self._find_match_result_for_job(task.candidate_id, task.resume_id, target_job.id)
        optimization_result = self._execute_agent(
            parent_task_id=task.id,
            task_type="optimization",
            agent_role="MainWorkflowAgent.optimize",
            input_json={"target_job_id": target_job.id},
            retry_count=task.retry_count,
            timeout_sec=task.stage_timeout_sec,
            stage="optimize",
            runner=lambda: self._main_agent.run_optimization(
                task_id=task.id,
                attempt=task.retry_count,
                profile=profile,
                target_job=target_job,
                match_result=match_result,
            ),
        )
        draft = self._unwrap_optimization_output(optimization_result)
        if isinstance(optimization_result, AgentResult):
            self._workspace.write_artifact(task.id, "main_agent_optimize_result.json", optimization_result.to_dict())
        self._workspace.write_artifact(task.id, "optimization_draft.json", draft.to_dict())
        self._task_repo.log_event(task.id, "stage.optimize.completed", self._stage_event_payload(draft, optimization_result))
        self._task_repo.update_optimization_task(task.id, stage="review", stage_started_at=None, failure_reason=None)
        self._db.commit()

    def _run_review_stage(self, task_id: str) -> None:
        task = self._require_optimization_task(task_id)
        self._mark_optimization_stage_started(task_id, "review")
        profile_row = self._candidate_repo.get_profile(task.resume_id)
        if profile_row is None:
            raise WorkflowError("candidate_profile_not_found", status_code=400)
        profile = self._candidate_profile_from_row(profile_row.profile_json)
        target_job = self._job_repo.get_job(task.target_job_id)
        if target_job is None:
            raise WorkflowError("job_not_found", status_code=404)
        match_result = self._find_match_result_for_job(task.candidate_id, task.resume_id, target_job.id)
        draft = self._optimization_draft_from_dict(self._workspace.read_artifact(task.id, "optimization_draft.json"))
        review_result = self._execute_agent(
            parent_task_id=task.id,
            task_type="optimization",
            agent_role="MainWorkflowAgent.review",
            input_json={"target_job_id": target_job.id},
            retry_count=task.retry_count,
            timeout_sec=task.stage_timeout_sec,
            stage="review",
            runner=lambda: self._main_agent.run_review(
                task_id=task.id,
                attempt=task.retry_count,
                profile=profile,
                target_job=target_job,
                match_result=match_result,
                draft=draft,
            ),
        )
        review_report = self._unwrap_review_output(review_result)
        if isinstance(review_result, AgentResult):
            self._workspace.write_artifact(task.id, "main_agent_review_result.json", review_result.to_dict())
        self._task_repo.log_event(task.id, "stage.review.completed", self._stage_event_payload(review_report, review_result))
        self._workspace.write_artifact(task.id, "review_report.json", review_report.to_dict())
        output_path = self._workspace.write_output(task.id, "optimized_resume.md", draft.optimized_resume_markdown)
        self._task_repo.save_optimization_result(task.id, draft, review_report)
        final_status = "completed" if review_report.allow_delivery else "blocked"
        self._task_repo.update_optimization_task(
            task.id,
            status=final_status,
            stage="deliver",
            locked_at=None,
            locked_by=None,
            stage_started_at=None,
            failure_reason=None,
        )
        self._task_repo.log_event(task.id, "task.completed", {"stage": "deliver", "output_path": output_path})
        self._db.commit()

    def _mark_match_stage_started(self, task_id: str, stage: str) -> None:
        now = datetime.now(UTC)
        self._task_repo.update_match_task(
            task_id,
            task_status="running",
            stage=stage,
            stage_started_at=now,
            locked_at=now,
            failure_reason=None,
        )
        self._db.commit()

    def _mark_optimization_stage_started(self, task_id: str, stage: str) -> None:
        now = datetime.now(UTC)
        self._task_repo.update_optimization_task(
            task_id,
            status="running",
            stage=stage,
            stage_started_at=now,
            locked_at=now,
            failure_reason=None,
        )
        self._db.commit()

    def _execute_agent(
        self,
        *,
        parent_task_id: str,
        task_type: str,
        agent_role: str,
        input_json: dict,
        retry_count: int,
        timeout_sec: int,
        stage: str,
        runner,
    ) -> Any:
        agent_task = self._task_repo.create_agent_task(
            parent_task_id,
            task_type,
            agent_role,
            input_json,
            retry_count=retry_count,
            timeout_sec=timeout_sec,
        )
        self._db.commit()
        try:
            with self._timeout_guard(stage=stage, timeout_sec=timeout_sec):
                output = runner()
        except Exception as exc:
            self._task_repo.finalize_agent_task(
                agent_task.id,
                status="failed",
                output_json={"error": str(exc)},
                failure_reason=str(exc),
            )
            self._db.commit()
            raise StageExecutionError(stage, str(exc)) from exc

        if isinstance(output, AgentResult) and output.status == "failed":
            serialized = output.to_dict()
            failure_reason = output.failure_reason or "agent_failed"
            self._task_repo.finalize_agent_task(
                agent_task.id,
                status="failed",
                output_json=serialized,
                failure_reason=failure_reason,
            )
            self._db.commit()
            raise StageExecutionError(stage, failure_reason)

        serialized = serialize_payload(output)
        self._task_repo.finalize_agent_task(agent_task.id, status="completed", output_json=serialized)
        self._db.commit()
        return output

    @contextmanager
    def _timeout_guard(self, *, stage: str, timeout_sec: int):
        if timeout_sec <= 0:
            yield
            return

        def handler(signum, frame):  # pragma: no cover - signal callback
            del signum, frame
            raise StageTimeoutError(stage, timeout_sec)

        previous_handler = signal.signal(signal.SIGALRM, handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_sec)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def _require_match_task(self, task_id: str):
        task = self._task_repo.get_match_task(task_id)
        if task is None:
            raise WorkflowError("match_task_not_found", status_code=404)
        return task

    def _require_optimization_task(self, task_id: str):
        task = self._task_repo.get_optimization_task(task_id)
        if task is None:
            raise WorkflowError("optimization_task_not_found", status_code=404)
        return task

    def _resume_parse_result_from_dict(self, payload: dict):
        from app.domain.models.resume import ResumeBlock, ResumeParseResult

        return ResumeParseResult(
            blocks=[ResumeBlock(**block) for block in payload.get("blocks", [])],
            extracted_fields=payload.get("extracted_fields", {}),
            risk_items=payload.get("risk_items", []),
        )

    def _optimization_draft_from_dict(self, payload: dict) -> OptimizationDraft:
        return OptimizationDraft(
            optimized_resume_markdown=payload.get("optimized_resume_markdown", ""),
            change_summary=[ChangeItem(**item) for item in payload.get("change_summary", [])],
            risk_notes=[RiskNote(**item) for item in payload.get("risk_notes", [])],
        )

    def _unwrap_optimization_output(self, output: Any) -> OptimizationDraft:
        candidate = output.output if isinstance(output, AgentResult) else output
        if not isinstance(candidate, OptimizationDraft):
            raise WorkflowError("optimization_agent_invalid_output", status_code=500)
        return candidate

    def _unwrap_review_output(self, output: Any) -> ReviewReport:
        candidate = output.output if isinstance(output, AgentResult) else output
        if not isinstance(candidate, ReviewReport):
            raise WorkflowError("review_agent_invalid_output", status_code=500)
        return candidate

    def _stage_event_payload(self, payload: Any, output: Any) -> dict:
        result = {"result": serialize_payload(payload)}
        if isinstance(output, AgentResult):
            result["agent"] = {
                "status": output.status,
                "confidence": output.confidence,
                "next_stage_hint": output.next_stage_hint,
                "observations": output.observations,
                "tool_traces": [trace.to_dict() for trace in output.tool_traces],
                "metadata": serialize_payload(output.metadata),
            }
        return result

    def _candidate_profile_from_row(self, payload: dict) -> CandidateProfile:
        return CandidateProfile(
            candidate_id=payload["candidate_id"],
            resume_id=payload["resume_id"],
            name=payload["name"],
            email=payload.get("email"),
            phone=payload.get("phone"),
            summary=payload["summary"],
            target_city=payload.get("target_city"),
            education_level=payload.get("education_level"),
            total_experience_months=payload["total_experience_months"],
            skills=[SkillFact(**skill) for skill in payload.get("skills", [])],
            experiences=[ExperienceFact(**item) for item in payload.get("experiences", [])],
            projects=[ProjectFact(**item) for item in payload.get("projects", [])],
            evidence_summary=payload.get("evidence_summary", {}),
            risk_items=payload.get("risk_items", []),
        )

    def _find_match_result_for_job(self, candidate_id: str, resume_id: str, job_id: str) -> MatchResult:
        stmt = (
            select(JobMatchResult)
            .join(MatchTask, MatchTask.id == JobMatchResult.task_id)
            .where(
                MatchTask.candidate_id == candidate_id,
                MatchTask.resume_id == resume_id,
                MatchTask.task_status == "completed",
                JobMatchResult.job_posting_id == job_id,
            )
            .order_by(JobMatchResult.rank_no)
        )
        row = self._db.scalar(stmt)
        if row is None:
            raise WorkflowError("match_result_for_target_job_not_found", status_code=404)
        job = self._job_repo.get_job(job_id)
        if job is None:
            raise WorkflowError("job_not_found", status_code=404)
        return MatchResult(
            job_posting_id=row.job_posting_id,
            company_name=job.company.name,
            job_title=job.job_title,
            city=job.city,
            score_card=MatchScoreCard(
                overall_score=row.overall_score,
                skill_score=row.skill_score,
                experience_score=row.experience_score,
                project_score=row.project_score,
                education_score=row.education_score,
                preference_score=row.preference_score,
            ),
            explanation=row.explanation_json,
            gap=GapAnalysis(**row.gap_json),
            rank_no=row.rank_no,
        )
