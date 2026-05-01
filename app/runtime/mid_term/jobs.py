"""Persistence for mid-term flush jobs."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.errors import ValidationError
from app.runtime.mid_term.models import MidTermFlushJob, MidTermFlushJobStatus
from app.runtime.mid_term.shared import read_json, write_json_atomic

_logger = logging.getLogger(__name__)


class MidTermFlushJobStore:
    """Persist and query flush jobs by session and agent."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir

    def create_job(self, job: MidTermFlushJob) -> None:
        self._write_job(job)

    def update_job(self, job: MidTermFlushJob) -> None:
        self._write_job(job)

    def get_job(self, *, session_id: str, agent_id: str, job_id: str) -> MidTermFlushJob | None:
        path = self._job_path(session_id=session_id, agent_id=agent_id, job_id=job_id)
        if not path.exists():
            return None
        payload = read_json(path)
        return MidTermFlushJob.from_payload(payload)

    def list_jobs(self, *, session_id: str, agent_id: str) -> list[MidTermFlushJob]:
        base = self._job_dir(session_id=session_id, agent_id=agent_id)
        if not base.exists():
            return []
        jobs: list[MidTermFlushJob] = []
        for path in sorted(base.glob("*.json")):
            try:
                payload = read_json(path)
                jobs.append(MidTermFlushJob.from_payload(payload))
            except ValidationError as exc:
                _logger.warning("skip invalid mid-term job payload: path=%s error=%s", path, exc)
        jobs.sort(key=lambda item: item.created_at)
        return jobs

    def find_duplicate_job(
        self,
        *,
        session_id: str,
        agent_id: str,
        first_event_id: str,
        last_event_id: str,
    ) -> MidTermFlushJob | None:
        for job in self.list_jobs(session_id=session_id, agent_id=agent_id):
            if job.event_pack.first_event_id != first_event_id:
                continue
            if job.event_pack.last_event_id != last_event_id:
                continue
            if job.status in {
                MidTermFlushJobStatus.PENDING,
                MidTermFlushJobStatus.RUNNING,
                MidTermFlushJobStatus.RETRY,
                MidTermFlushJobStatus.DEFERRED,
                MidTermFlushJobStatus.SUCCEEDED,
            }:
                return job
        return None

    def list_job_targets(self) -> list[tuple[str, str]]:
        """Return `(session_id, agent_id)` pairs that have persisted flush jobs."""
        agents_root = self._root_dir / "agents"
        if not agents_root.exists():
            return []
        pairs: list[tuple[str, str]] = []
        for agent_dir in sorted(agents_root.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_id = agent_dir.name.strip()
            if not agent_id:
                continue
            jobs_root = agent_dir / "mid_term" / "flush_jobs"
            if not jobs_root.exists():
                continue
            for session_dir in sorted(jobs_root.iterdir()):
                if not session_dir.is_dir():
                    continue
                session_id = session_dir.name.strip()
                if not session_id:
                    continue
                has_job_file = any(path.is_file() and path.suffix == ".json" for path in session_dir.iterdir())
                if not has_job_file:
                    continue
                pairs.append((session_id, agent_id))
        return pairs

    def list_all_jobs(self) -> list[MidTermFlushJob]:
        """Return all persisted jobs across agents/sessions."""
        jobs: list[MidTermFlushJob] = []
        for session_id, agent_id in self.list_job_targets():
            jobs.extend(self.list_jobs(session_id=session_id, agent_id=agent_id))
        return jobs

    def _job_dir(self, *, session_id: str, agent_id: str) -> Path:
        path = self._root_dir / "agents" / agent_id / "mid_term" / "flush_jobs" / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _job_path(self, *, session_id: str, agent_id: str, job_id: str) -> Path:
        return self._job_dir(session_id=session_id, agent_id=agent_id) / f"{job_id}.json"

    def _write_job(self, job: MidTermFlushJob) -> None:
        path = self._job_path(session_id=job.session_id, agent_id=job.agent_id, job_id=job.job_id)
        write_json_atomic(path, job.to_payload())
