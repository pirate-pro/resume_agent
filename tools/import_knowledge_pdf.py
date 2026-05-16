"""Import local PDF files into KnowledgeStore and RetrievalIndexStore."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.api.dependencies.config import get_settings
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.knowledge.pdf_importer import KnowledgePdfImporter
from app.knowledge.store import KnowledgeStore
from app.retrieval.index_store import RetrievalIndexStore


def main() -> None:
    parser = argparse.ArgumentParser(description="导入本地 PDF 到外部资料库和 RAG 索引")
    parser.add_argument("paths", nargs="+", help="PDF 文件路径")
    parser.add_argument("--session-id", default="sess_knowledge_import", help="导入 artifact 所属会话")
    parser.add_argument("--provider", default="本地 PDF 导入", help="资料来源")
    parser.add_argument("--skill-tag", action="append", default=[], help="额外技能标签，可重复传入")
    parser.add_argument("--target-role", action="append", default=[], help="目标岗位，可重复传入")
    parser.add_argument("--no-index", action="store_true", help="只创建 artifact 和 ExternalResource，不重建索引")
    args = parser.parse_args()

    settings = get_settings()
    session_repository = JsonlSessionRepository(data_dir=settings.data_dir)
    knowledge_store = KnowledgeStore(root_dir=settings.data_dir / "knowledge")
    retrieval_index_store = RetrievalIndexStore(root_dir=settings.data_dir / "retrieval_index")
    importer = KnowledgePdfImporter(
        session_repository=session_repository,
        knowledge_store=knowledge_store,
        retrieval_index_store=retrieval_index_store,
    )
    results = []
    for raw_path in args.paths:
        result = importer.import_pdf(
            Path(raw_path),
            session_id=args.session_id,
            provider=args.provider,
            skill_tags=list(args.skill_tag),
            target_roles=list(args.target_role),
            auto_index=not args.no_index,
        )
        results.append({
            "artifact_id": result.artifact_id,
            "chunk_count": result.index_result.chunk_count,
            "indexed_source_count": result.index_result.indexed_source_count,
            "key_points": result.key_points,
            "resource_id": result.resource_id,
            "session_id": result.session_id,
            "text_char_count": result.text_char_count,
            "title": result.title,
            "token_estimate": result.token_estimate,
        })
    print(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
