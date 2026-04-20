import json
import shutil
from pathlib import Path

from app.core.config.settings import get_settings


class WorkspaceManager:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._settings.file_root_path.mkdir(parents=True, exist_ok=True)
        self._settings.artifact_root_path.mkdir(parents=True, exist_ok=True)

    def save_upload(self, resume_id: str, file_name: str, content: bytes) -> str:
        target_dir = self._settings.file_root_path / "uploads" / resume_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / file_name
        target_path.write_bytes(content)
        return str(target_path)

    def create_task_workspace(self, task_id: str) -> dict[str, str]:
        root = self._settings.artifact_root_path / task_id
        paths = {
            "root": str(root),
            "uploads": str(root / "uploads"),
            "workspace": str(root / "workspace"),
            "artifacts": str(root / "artifacts"),
            "outputs": str(root / "outputs"),
        }
        for path in paths.values():
            Path(path).mkdir(parents=True, exist_ok=True)
        return paths

    def copy_resume_into_workspace(self, source_path: str, task_id: str, file_name: str) -> str:
        workspace = self.create_task_workspace(task_id)
        target_path = Path(workspace["uploads"]) / file_name
        shutil.copy2(source_path, target_path)
        return str(target_path)

    def write_artifact(self, task_id: str, name: str, payload: dict | list) -> str:
        workspace = self.create_task_workspace(task_id)
        path = Path(workspace["artifacts"]) / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(path)

    def write_output(self, task_id: str, name: str, content: str) -> str:
        workspace = self.create_task_workspace(task_id)
        path = Path(workspace["outputs"]) / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def read_artifact(self, task_id: str, name: str) -> dict | list:
        workspace = self.create_task_workspace(task_id)
        path = Path(workspace["artifacts"]) / name
        return json.loads(path.read_text(encoding="utf-8"))
