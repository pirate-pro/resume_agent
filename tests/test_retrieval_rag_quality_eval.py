"""Deterministic M23 RAG quality evaluation over indexed retrieval chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from app.core.time import APP_TIMEZONE
from app.domain.models import SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.knowledge.models import (
    ExperiencePost,
    ExternalResource,
    InterviewDifficulty,
    InterviewQuestion,
    KnowledgeRecordStatus,
    QuestionType,
    ResourceType,
)
from app.knowledge.store import KnowledgeStore
from app.learning.models import (
    ConfidenceLevel,
    LearningPlan,
    LearningPlanType,
    LearningPriority,
    LearningRecordStatus,
    LearningTask,
    LearningTaskState,
    LearningTaskType,
    ProgressCheckin,
    ProgressState,
)
from app.learning.store import LearningStore
from app.notes.models import Note, NoteOrigin, NoteRecordStatus, NoteType
from app.notes.store import NoteStore
from app.retrieval.chunking import ChunkingOptions
from app.retrieval.index_store import RetrievalIndexStore
from app.retrieval.indexer import RetrievalIndexer
from app.retrieval.models import RetrievalHit, RetrievalQuery, validate_source_type
from app.retrieval.service import RetrievalService

__all__ = []


@dataclass(frozen=True, slots=True)
class RagEvalCase:
    name: str
    query: str
    source_types: list[str]
    expected_source_ids: set[str]
    expected_keywords: set[str]
    forbidden_source_ids: set[str] = field(default_factory=set)
    forbidden_source_types: set[str] = field(default_factory=set)
    min_recall_at_k: float = 1.0
    top_k: int = 5
    max_chars: int = 6000


class _Clock:
    def __init__(self) -> None:
        self._value = datetime(2026, 5, 16, 15, 0, tzinfo=APP_TIMEZONE)

    def __call__(self) -> datetime:
        current = self._value
        self._value += timedelta(minutes=1)
        return current


def test_m23_rag_quality_eval_covers_core_retrieval_paths(tmp_path: Path) -> None:
    service = _seed_indexed_service(tmp_path)
    cases = [
        RagEvalCase(
            name="用户手写笔记",
            query="用户手写 失败恢复 队列重试 幂等 怎么准备",
            source_types=["note"],
            expected_source_ids={"note_user_failure_recovery"},
            expected_keywords={"用户手写", "队列重试", "幂等"},
            forbidden_source_ids={"note_archived_shadow"},
        ),
        RagEvalCase(
            name="Agent 整理笔记",
            query="Agent整理 Star Agent Runtime 任务编排 tool calling",
            source_types=["note"],
            expected_source_ids={"note_agent_runtime_review"},
            expected_keywords={"Agent整理", "任务编排", "tool calling"},
            forbidden_source_ids={"note_archived_shadow"},
        ),
        RagEvalCase(
            name="外部 PDF C++ 资料",
            query="C++ 指针 引用 区别 空指针 必须初始化",
            source_types=["external_resource"],
            expected_source_ids={"resource_pdf_cpp_baguwen"},
            expected_keywords={"指针可以为空", "引用必须初始化"},
        ),
        RagEvalCase(
            name="外部 PDF Java 资料",
            query="Java HashMap 扩容 红黑树 volatile synchronized",
            source_types=["external_resource"],
            expected_source_ids={"resource_pdf_java_baguwen"},
            expected_keywords={"HashMap 扩容", "volatile", "synchronized"},
        ),
        RagEvalCase(
            name="当前会话文件",
            query="当前 JD RAG 召回评估 recall@5 chunk 策略",
            source_types=["session_artifact"],
            expected_source_ids={"artifact_current_jd"},
            expected_keywords={"recall@5", "chunk 策略"},
            forbidden_source_ids={"artifact_other_session_jd"},
        ),
        RagEvalCase(
            name="学习任务",
            query="RAG recall@5 chunk 学习任务 打卡 今天该学什么",
            source_types=["learning_plan", "learning_task", "progress_checkin"],
            expected_source_ids={"learning_task_rag_eval", "checkin_rag_eval"},
            expected_keywords={"recall@5", "chunk 召回", "今天完成"},
            top_k=8,
        ),
        RagEvalCase(
            name="面试题召回",
            query="面试官问 RAG 召回评估指标 recall@5 precision citation 怎么回答",
            source_types=["interview_question"],
            expected_source_ids={"question_rag_eval_metrics"},
            expected_keywords={"recall@5", "precision@k", "citation"},
        ),
        RagEvalCase(
            name="消息队列经验",
            query="Kafka RabbitMQ 消息队列 经验 怎么补",
            source_types=["experience_post", "external_resource"],
            expected_source_ids={"experience_queue_gap", "resource_queue_interview"},
            expected_keywords={"Kafka", "RabbitMQ", "消息队列"},
            top_k=8,
        ),
    ]

    for case in cases:
        query = RetrievalQuery(
            query=case.query,
            session_id="sess_alpha",
            source_types=case.source_types,
            top_k=case.top_k,
            max_chars=case.max_chars,
            max_snippet_chars=1200,
        )
        hits = service.search(query)
        actual_ids = {hit.source.source_id for hit in hits[: case.top_k]}
        actual_types = {validate_source_type(hit.source.source_type).value for hit in hits}
        combined_text = _combined_hit_text(hits)
        recall_at_k = len(case.expected_source_ids & actual_ids) / len(case.expected_source_ids)

        assert recall_at_k >= case.min_recall_at_k, case.name
        assert not (case.forbidden_source_ids & actual_ids), case.name
        assert not (case.forbidden_source_types & actual_types), case.name
        assert actual_types <= set(case.source_types), case.name
        for keyword in case.expected_keywords:
            assert keyword in combined_text, case.name

        pack = service.build_context_pack(query)
        assert len(pack.citations) == len(pack.hits), case.name
        assert all(citation.source_id for citation in pack.citations), case.name
        assert sum(hit.content_length() for hit in pack.hits) <= case.max_chars, case.name
        assert all(hit.match_reason for hit in pack.hits), case.name
        assert not (case.forbidden_source_ids & {hit.source.source_id for hit in pack.hits}), case.name


def _combined_hit_text(hits: list[RetrievalHit]) -> str:
    parts: list[str] = []
    for hit in hits:
        parts.extend(
            [
                hit.title,
                hit.summary,
                hit.snippet,
                " ".join(hit.tags),
                str(hit.metadata),
            ]
        )
    return "\n".join(parts)


def _seed_indexed_service(tmp_path: Path) -> RetrievalService:
    clock = _Clock()
    note_store = NoteStore(root_dir=tmp_path / "notes", clock=clock)
    knowledge_store = KnowledgeStore(root_dir=tmp_path / "knowledge", clock=clock)
    learning_store = LearningStore(root_dir=tmp_path / "learning", clock=clock)
    session_repository = JsonlSessionRepository(tmp_path / "sessions")
    index_store = RetrievalIndexStore(root_dir=tmp_path / "retrieval_index", clock=clock)
    indexer = RetrievalIndexer(
        index_store=index_store,
        chunking_options=ChunkingOptions(target_tokens=120, max_tokens=180, overlap_tokens=20, min_chunk_tokens=12),
        clock=clock,
        session_repository=session_repository,
    )

    session_repository.create_session("sess_alpha")
    session_repository.create_session("sess_beta")
    _seed_notes(note_store)
    _seed_artifacts(session_repository)
    _seed_knowledge(knowledge_store)
    _seed_learning(learning_store)

    indexer.sync_notes(note_store)
    indexer.sync_knowledge(knowledge_store)
    indexer.sync_session_artifacts(session_repository, session_id="sess_alpha")
    indexer.sync_session_artifacts(session_repository, session_id="sess_beta")

    return RetrievalService(
        note_store=note_store,
        knowledge_store=knowledge_store,
        learning_store=learning_store,
        session_repository=session_repository,
        index_store=index_store,
    )


def _seed_notes(note_store: NoteStore) -> None:
    note_store.save_note(
        _note(
            note_id="note_user_failure_recovery",
            title="失败恢复手写复盘",
            body_markdown=(
                "我自己写的失败恢复怎么准备：回答时先讲任务幂等，再讲队列重试、"
                "指数退避、降级兜底和审计事件。不要只说 try/except。"
            ),
            origin=NoteOrigin.USER,
            note_type=NoteType.NOTE,
            tags=["RAG", "失败恢复", "用户复盘"],
        )
    )
    note_store.save_note(
        _note(
            note_id="note_agent_runtime_review",
            title="Star Agent Runtime 复盘",
            body_markdown=(
                "Agent 整理的 Star Agent Runtime 复盘：重点解释任务编排、tool calling、"
                "SSE 流式输出和多 Agent 委派后的状态审计。"
            ),
            origin=NoteOrigin.AGENT,
            note_type=NoteType.LEARNING,
            tags=["Agent", "Runtime", "tool calling"],
        )
    )
    note_store.save_note(
        _note(
            note_id="note_archived_shadow",
            title="已归档失败恢复旧笔记",
            body_markdown="我自己写的失败恢复怎么准备：这条旧笔记不应该进入 active RAG 结果。",
            origin=NoteOrigin.USER,
            note_type=NoteType.NOTE,
            tags=["归档"],
        )
    )
    note_store.archive_note("note_archived_shadow")


def _seed_artifacts(repository: JsonlSessionRepository) -> None:
    artifacts = [
        _session_artifact(
            repository,
            session_id="sess_alpha",
            artifact_id="artifact_pdf_cpp",
            title="C++ 八股文 PDF",
            text=(
                "C++ 指针和引用区别 怎么回答：指针可以为空，可以改变指向；"
                "引用必须初始化，初始化后通常不能再绑定到其他对象。"
            ),
        ),
        _session_artifact(
            repository,
            session_id="sess_alpha",
            artifact_id="artifact_pdf_java",
            title="Java 八股文 PDF",
            text=(
                "Java HashMap 扩容 会在负载因子超过阈值后触发 resize，链表过长会树化为红黑树。"
                "volatile 保证可见性和一定有序性，synchronized 提供互斥和可见性。"
            ),
        ),
        _session_artifact(
            repository,
            session_id="sess_alpha",
            artifact_id="artifact_current_jd",
            title="当前会话 JD",
            text="当前 JD 要求候选人说明 RAG 召回评估 recall@5、chunk 策略和引用追踪。",
        ),
        _session_artifact(
            repository,
            session_id="sess_beta",
            artifact_id="artifact_other_session_jd",
            title="其他会话 JD",
            text="其他会话也包含 RAG 召回评估 recall@5 和 chunk 策略，但当前会话不能召回。",
        ),
    ]
    for artifact in artifacts:
        repository.add_or_update_session_artifact(artifact)


def _seed_knowledge(knowledge_store: KnowledgeStore) -> None:
    knowledge_store.save_external_resource(
        _external_resource(
            resource_id="resource_pdf_cpp_baguwen",
            artifact_id="artifact_pdf_cpp",
            title="代码随想录 C++ 八股文",
            skill_tags=["C++", "八股文", "面试题"],
        )
    )
    knowledge_store.save_external_resource(
        _external_resource(
            resource_id="resource_pdf_java_baguwen",
            artifact_id="artifact_pdf_java",
            title="代码随想录 Java 八股文",
            skill_tags=["Java", "HashMap", "并发"],
        )
    )
    knowledge_store.save_external_resource(
        _external_resource(
            resource_id="resource_queue_interview",
            artifact_id=None,
            title="消息队列面试资料",
            skill_tags=["Kafka", "RabbitMQ", "消息队列"],
            summary="Kafka 和 RabbitMQ 的使用场景、可靠性、消费确认、重试和死信队列。",
            key_points=["说明 Kafka 分区和消费组", "说明 RabbitMQ ack、重试和死信队列"],
        )
    )
    knowledge_store.save_interview_question(
        _interview_question(
            question_id="question_rag_eval_metrics",
            question_text="RAG 召回评估指标怎么设计？",
            answer_outline=(
                "先定义离线评估集，再看 recall@5、precision@k、MRR、citation 命中率，"
                "最后用人工抽检验证答案是否引用正确。"
            ),
            skill_tags=["RAG", "评估", "检索"],
            evaluation_points=["recall@5", "precision@k", "citation"],
        )
    )
    knowledge_store.save_experience_post(
        _experience_post(
            experience_id="experience_queue_gap",
            summary=(
                "候选人 Kafka / RabbitMQ 消息队列经验不足，建议准备消费确认、幂等、"
                "顺序消费、重试和死信队列案例。"
            ),
            questions=["Kafka 如何保证消息顺序？", "RabbitMQ ack 和死信队列怎么用？"],
            tags=["Kafka", "RabbitMQ", "消息队列"],
        )
    )


def _seed_learning(learning_store: LearningStore) -> None:
    learning_store.save_learning_plan(
        LearningPlan(
            learning_plan_id="learning_plan_rag_eval",
            status=LearningRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id=None,
            evidence_refs=["sess_alpha", "note_user_failure_recovery"],
            created_at=_now(),
            updated_at=_now(),
            title="RAG 评估补强计划",
            description="围绕 RAG recall@5、chunk 召回和引用追踪补齐面试表达。",
            plan_type=LearningPlanType.INTERVIEW_PREP,
            priority=LearningPriority.HIGH,
            goals=["能讲清 recall@5 指标", "能解释 chunk 召回失败时的排查路径"],
            focus_skill_tags=["RAG", "recall@5", "chunk"],
            task_ids=["learning_task_rag_eval"],
            progress_summary="今天完成 RAG 评估口径和 chunk 召回复盘。",
        )
    )
    learning_store.save_learning_task(
        LearningTask(
            learning_task_id="learning_task_rag_eval",
            status=LearningRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id=None,
            evidence_refs=["learning_plan_rag_eval", "note_user_failure_recovery"],
            created_at=_now(),
            updated_at=_now(),
            title="整理 RAG recall@5 和 chunk 召回答法",
            learning_plan_id="learning_plan_rag_eval",
            description="今天完成 RAG recall@5、precision@k、chunk 召回和 citation 引用追踪的面试回答。",
            task_type=LearningTaskType.WRITE_ANSWER,
            priority=LearningPriority.HIGH,
            state=LearningTaskState.DOING,
            skill_tags=["RAG", "recall@5", "chunk 召回"],
            estimated_minutes=45,
            resource_refs=["resource_pdf_java_baguwen"],
            question_refs=["question_rag_eval_metrics"],
            note_refs=["note_user_failure_recovery"],
            success_criteria=["能说出 recall@5 和 precision@k 的区别", "能解释 chunk 召回失败排查"],
            progress_notes="今天完成第一版回答，仍需补 citation 示例。",
        )
    )
    learning_store.save_progress_checkin(
        ProgressCheckin(
            checkin_id="checkin_rag_eval",
            status=LearningRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id=None,
            evidence_refs=["learning_task_rag_eval"],
            created_at=_now(),
            updated_at=_now(),
            learning_plan_id="learning_plan_rag_eval",
            learning_task_id="learning_task_rag_eval",
            checkin_date=_now(),
            minutes_spent=30,
            progress_state=ProgressState.IN_PROGRESS,
            summary="今天完成 RAG recall@5 和 chunk 召回笔记整理。",
            blockers=["citation 示例还不够"],
            confidence=ConfidenceLevel.MEDIUM,
            next_action="补一个真实 citation 追踪案例。",
            note_refs=["note_user_failure_recovery"],
        )
    )


def _note(
    *,
    note_id: str,
    title: str,
    body_markdown: str,
    origin: NoteOrigin,
    note_type: NoteType,
    tags: list[str],
) -> Note:
    return Note(
        note_id=note_id,
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["sess_alpha"],
        created_at=_now(),
        updated_at=_now(),
        title=title,
        body_markdown=body_markdown,
        note_type=note_type,
        origin=origin,
        tags=tags,
        summary=title,
    )


def _external_resource(
    *,
    resource_id: str,
    artifact_id: str | None,
    title: str,
    skill_tags: list[str],
    summary: str = "外部 PDF 资料，正文来自 SessionArtifact。",
    key_points: list[str] | None = None,
) -> ExternalResource:
    return ExternalResource(
        resource_id=resource_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=artifact_id,
        evidence_refs=["sess_alpha", *( [artifact_id] if artifact_id is not None else [] )],
        created_at=_now(),
        updated_at=_now(),
        title=title,
        resource_type=ResourceType.UPLOADED_FILE if artifact_id else ResourceType.PASTED_TEXT,
        provider="代码随想录知识星球" if artifact_id else "用户资料库",
        target_roles=["后端工程师"],
        skill_tags=skill_tags,
        summary=summary,
        key_points=key_points or ["面试高频知识点"],
        raw_artifact_id=artifact_id,
    )


def _interview_question(
    *,
    question_id: str,
    question_text: str,
    answer_outline: str,
    skill_tags: list[str],
    evaluation_points: list[str],
) -> InterviewQuestion:
    return InterviewQuestion(
        question_id=question_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["sess_alpha"],
        created_at=_now(),
        updated_at=_now(),
        question_text=question_text,
        question_type=QuestionType.SYSTEM_DESIGN,
        difficulty=InterviewDifficulty.MEDIUM,
        skill_tags=skill_tags,
        company="星河智能",
        position="AI Agent 后端工程师",
        answer_outline=answer_outline,
        evaluation_points=evaluation_points,
        common_pitfalls=["只谈 embedding，不谈质量评估和引用有效性"],
    )


def _experience_post(
    *,
    experience_id: str,
    summary: str,
    questions: list[str],
    tags: list[str],
) -> ExperiencePost:
    return ExperiencePost(
        experience_id=experience_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["sess_alpha"],
        created_at=_now(),
        updated_at=_now(),
        company="星河智能",
        position="AI Agent 后端工程师",
        seniority="二面",
        interview_process=["项目深挖", "中间件追问"],
        questions=questions,
        outcome="待准备",
        difficulty=InterviewDifficulty.MEDIUM,
        summary=summary,
        tags=tags,
    )


def _session_artifact(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    artifact_id: str,
    title: str,
    text: str,
) -> SessionArtifact:
    now = _now()
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    original_path = artifact_dir / "original.txt"
    text_path = artifact_dir / "parsed.txt"
    original_path.write_text(text, encoding="utf-8")
    text_path.write_text(text, encoding="utf-8")
    return SessionArtifact(
        artifact_id=artifact_id,
        session_id=session_id,
        kind="uploaded_file",
        title=title,
        media_type="text/plain",
        size_bytes=original_path.stat().st_size,
        status="ready",
        visibility="user_visible",
        created_at=now,
        updated_at=now,
        storage_relpath=str(original_path.relative_to(root)),
        text_relpath=str(text_path.relative_to(root)),
        text_char_count=len(text),
        token_estimate=max(len(text) // 4, 1),
        parsed_at=now,
    )


def _now() -> datetime:
    return datetime(2026, 5, 16, 14, 0, tzinfo=APP_TIMEZONE)
