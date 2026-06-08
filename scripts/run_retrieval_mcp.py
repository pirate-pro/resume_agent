"""Run the retrieval MCP server."""

from __future__ import annotations

import argparse

from app.mcp.retrieval_server import RetrievalPrincipal, run_retrieval_mcp_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the resume-agent retrieval MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport to run.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP host for streamable-http transport.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP port for streamable-http transport.",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="HTTP path for streamable-http transport.",
    )
    parser.add_argument(
        "--app-session-id",
        default=None,
        help="Optional app session id used to allow SessionArtifact retrieval.",
    )
    parser.add_argument(
        "--owner-user-id",
        default="user_local",
        help="Server-owned owner id for future scoped retrieval.",
    )
    parser.add_argument(
        "--workspace-id",
        default="workspace_default",
        help="Server-owned workspace id for future scoped retrieval.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow non-localhost HTTP binding. Do not use without external access controls.",
    )
    args = parser.parse_args()
    principal = RetrievalPrincipal(
        session_id=_empty_to_none(args.app_session_id),
        owner_user_id=args.owner_user_id,
        workspace_id=args.workspace_id,
    )
    run_retrieval_mcp_server(
        transport=args.transport,
        principal=principal,
        host=args.host,
        port=args.port,
        path=args.path,
        allow_remote=args.allow_remote,
    )


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


if __name__ == "__main__":
    main()
