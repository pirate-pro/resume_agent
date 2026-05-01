"""JSON/JSONL file helpers for file-backed memory storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import StorageError


def ensure_file(path: Path, initial_content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    try:
        path.write_text(initial_content, encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Failed to initialize memory file '{path}': {exc}") from exc


def read_json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StorageError(f"Failed to read memory JSON file '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid memory JSON file '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise StorageError(f"Invalid memory JSON object '{path}'.")
    return {str(key): value for key, value in payload.items()}


def write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        raise StorageError(f"Failed to write memory JSON file '{path}': {exc}") from exc


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        raise StorageError(f"Failed to append memory JSONL file '{path}': {exc}") from exc


def read_jsonl_payloads(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    output: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    output.append(payload)
    except OSError as exc:
        raise StorageError(f"Failed to read memory JSONL file '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise StorageError(f"Invalid memory JSONL file '{path}': {exc}") from exc
    return output


def rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        tmp_path.replace(path)
    except OSError as exc:
        raise StorageError(f"Failed to rewrite memory JSONL file '{path}': {exc}") from exc
