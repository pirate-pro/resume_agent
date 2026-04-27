"""CLI entrypoint for offline memory structured metadata backfill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.memory.facade import FileMemoryFacade
from app.memory.models import MemoryScope, MemoryStructuredBackfillRequest
from app.memory.policies import default_memory_policy
from app.memory.stores.jsonl_file_store import JsonlFileMemoryStore

__all__ = ["main"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill structured metadata for legacy memory records.")
    parser.add_argument(
        "--root-dir",
        default="data/memory_v2",
        help="Memory root directory. Defaults to data/memory_v2.",
    )
    parser.add_argument(
        "--scope",
        action="append",
        choices=[scope.value for scope in MemoryScope],
        help="Memory scope to scan. Can be passed multiple times. Defaults to all scopes.",
    )
    parser.add_argument("--agent-id", help="Optional agent id filter for agent-scoped memories.")
    parser.add_argument("--session-id", help="Optional session id filter for agent_short memories.")
    parser.add_argument(
        "--include-deleted",
        action="store_true",
        help="Also patch deleted records. Default is false.",
    )
    args = parser.parse_args()

    scopes = [MemoryScope(value) for value in args.scope] if args.scope else list(MemoryScope)
    store = JsonlFileMemoryStore(root_dir=Path(args.root_dir))
    facade = FileMemoryFacade(store=store, policy=default_memory_policy())
    result = facade.backfill_structured_metadata(
        MemoryStructuredBackfillRequest(
            scopes=scopes,
            agent_id=args.agent_id,
            session_id=args.session_id,
            include_deleted=args.include_deleted,
            write_log=True,
        )
    )
    print(
        json.dumps(
            {
                "scanned_files": result.scanned_files,
                "rewritten_files": result.rewritten_files,
                "scanned_rows": result.scanned_rows,
                "patched_records": result.patched_records,
                "skipped_structured": result.skipped_structured,
                "skipped_deleted": result.skipped_deleted,
                "invalid_rows": result.invalid_rows,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
