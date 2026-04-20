from __future__ import annotations

import argparse

from app.application.task_worker import DatabaseTaskWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DB-driven worker for resume agent tasks.")
    parser.add_argument(
        "--task-type",
        choices=["all", "match", "optimization"],
        default="all",
        help="Which task queue to consume.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one task and exit.",
    )
    parser.add_argument(
        "--until-idle",
        action="store_true",
        help="Process tasks until no claimable task remains, then exit.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    worker = DatabaseTaskWorker()
    if args.once:
        worker.process_next_task(task_type=args.task_type)
        return
    if args.until_idle:
        worker.run_until_idle(task_type=args.task_type)
        return
    worker.run_forever(task_type=args.task_type)


if __name__ == "__main__":
    main()
