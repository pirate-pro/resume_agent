"""Seed deterministic career product data for frontend panel validation."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
)
from app.career.store import CareerProductStore
from app.core.time import app_now
from app.domain.models import SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository

DEFAULT_SESSION_ID = "sess_m4_frontend_demo"

RESUME_ARTIFACT_ID = "artifact_m4_resume"
DIAGNOSIS_ARTIFACT_ID = "artifact_m4_diagnosis"
JD_ARTIFACT_ID = "artifact_m4_jd"
FIT_REPORT_ARTIFACT_ID = "artifact_m4_fit_report"
RESUME_VERSION_ARTIFACT_ID = "artifact_m4_resume_version"

RESUME_PROFILE_ID = "resume_profile_m4_demo"
CAREER_PROFILE_ID = "career_profile_m4_demo"
JD_ANALYSIS_ID = "jd_m4_demo"
JOB_FIT_REPORT_ID = "fit_m4_demo"
RESUME_VERSION_ID = "resume_version_m4_demo"
CAREER_APPLICATION_ID = "application_m4_demo"


@dataclass(frozen=True, slots=True)
class DemoSeedSummary:
    data_dir: str
    session_id: str
    artifact_ids: list[str]
    resume_profile_id: str
    career_profile_id: str
    jd_analysis_id: str
    job_fit_report_id: str
    resume_version_id: str
    career_application_id: str


def seed_demo_data(data_dir: Path, *, session_id: str = DEFAULT_SESSION_ID) -> DemoSeedSummary:
    """Create or update deterministic demo data under one data directory."""

    normalized_data_dir = data_dir.expanduser().resolve()
    session_repository = JsonlSessionRepository(data_dir=normalized_data_dir)
    career_store = CareerProductStore(root_dir=normalized_data_dir / "career")

    session_repository.create_session(session_id)
    session_repository.update_session_title(session_id, "M4 前端求职资产演示")

    artifact_ids = _seed_artifacts(session_repository, session_id)
    _seed_career_records(career_store, session_id)
    session_repository.set_active_artifact_ids(session_id, artifact_ids)

    return DemoSeedSummary(
        data_dir=str(normalized_data_dir),
        session_id=session_id,
        artifact_ids=artifact_ids,
        resume_profile_id=RESUME_PROFILE_ID,
        career_profile_id=CAREER_PROFILE_ID,
        jd_analysis_id=JD_ANALYSIS_ID,
        job_fit_report_id=JOB_FIT_REPORT_ID,
        resume_version_id=RESUME_VERSION_ID,
        career_application_id=CAREER_APPLICATION_ID,
    )


def _seed_artifacts(repository: JsonlSessionRepository, session_id: str) -> list[str]:
    artifacts = [
        (
            RESUME_ARTIFACT_ID,
            "M4 演示简历.txt",
            "uploaded_file",
            "text/plain",
            None,
            _resume_text(),
        ),
        (
            DIAGNOSIS_ARTIFACT_ID,
            "M4 简历诊断.md",
            "generated_file",
            "text/markdown",
            "resume_agent",
            _diagnosis_markdown(),
        ),
        (
            JD_ARTIFACT_ID,
            "M4 目标岗位 JD.txt",
            "pasted_text",
            "text/plain",
            "agent_main",
            _jd_text(),
        ),
        (
            FIT_REPORT_ARTIFACT_ID,
            "M4 岗位匹配报告.md",
            "generated_file",
            "text/markdown",
            "job_agent",
            _fit_report_markdown(),
        ),
        (
            RESUME_VERSION_ARTIFACT_ID,
            "M4 定制简历版本.md",
            "generated_file",
            "text/markdown",
            "agent_main",
            _resume_version_markdown(),
        ),
    ]
    artifact_ids: list[str] = []
    for artifact_id, title, kind, media_type, owner_agent_id, content in artifacts:
        _write_text_artifact(
            repository,
            session_id=session_id,
            artifact_id=artifact_id,
            title=title,
            kind=kind,
            media_type=media_type,
            owner_agent_id=owner_agent_id,
            content=content,
        )
        artifact_ids.append(artifact_id)
    return artifact_ids


def _seed_career_records(store: CareerProductStore, session_id: str) -> None:
    now = app_now()
    store.save_resume_profile(
        ResumeProfile(
            resume_profile_id=RESUME_PROFILE_ID,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=RESUME_ARTIFACT_ID,
            evidence_refs=[RESUME_ARTIFACT_ID, DIAGNOSIS_ARTIFACT_ID],
            created_at=now,
            updated_at=now,
            basic_info={
                "name": "林一凡",
                "email": "lin.demo@example.com",
                "phone": "13800000000",
                "city": "上海",
            },
            education=[
                {
                    "school": "华东示例大学",
                    "degree": "本科",
                    "major": "计算机科学与技术",
                    "period": "2019-2023",
                }
            ],
            work_experience=[
                {
                    "company": "示例科技",
                    "role": "后端工程师",
                    "period": "2023-至今",
                    "highlights": ["负责 RAG 服务接口", "维护 FastAPI 任务编排服务"],
                }
            ],
            project_experience=[
                {
                    "name": "企业知识库问答系统",
                    "role": "核心开发",
                    "highlights": ["实现文档解析和向量检索", "优化接口 P95 延迟 32%"],
                },
                {
                    "name": "Agent 工具调用审计台",
                    "role": "全栈开发",
                    "highlights": ["接入事件流", "沉淀工具调用可观测数据"],
                },
            ],
            skills=["Python", "FastAPI", "PostgreSQL", "Redis", "RAG", "Docker"],
            certificates=["大学英语六级"],
            awards=["校级优秀毕业设计"],
            self_evaluation="偏后端和 AI 应用工程，能把模型能力接入稳定产品链路。",
            raw_text_artifact_id=RESUME_ARTIFACT_ID,
            diagnosis_artifact_id=DIAGNOSIS_ARTIFACT_ID,
            diagnosis={
                "summary": "项目经历清楚，但业务指标和岗位关键词需要更集中。",
                "issues": ["部分成果缺少量化结果", "AI 工程关键词分布不够集中"],
                "suggestions": ["强化 RAG、Agent、性能优化案例", "将项目描述改成问题-动作-结果结构"],
            },
        )
    )
    store.save_career_profile(
        CareerProfile(
            career_profile_id=CAREER_PROFILE_ID,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=RESUME_ARTIFACT_ID,
            evidence_refs=[RESUME_PROFILE_ID, RESUME_ARTIFACT_ID, DIAGNOSIS_ARTIFACT_ID],
            created_at=now,
            updated_at=now,
            career_goal="AI 应用后端工程师",
            target_roles=["AI 应用开发工程师", "Agent 后端工程师", "RAG 平台工程师"],
            preferred_industries=["企业服务", "AI Infra", "知识管理"],
            preferred_cities=["上海", "杭州", "远程"],
            strengths=["后端工程基础扎实", "有 RAG 和工具调用经验", "能关注可观测性和稳定性"],
            weaknesses=["大规模分布式经验需要补强", "简历里业务结果表达偏弱"],
            skills=["Python", "FastAPI", "RAG", "Agent", "PostgreSQL", "Redis"],
            interests=["AI 应用产品化", "工程效率", "知识库"],
            education_summary="计算机本科，具备后端开发基础。",
            experience_summary="1 年以上后端与 AI 应用工程经验。",
            resume_issues=["项目成果量化不足", "目标岗位关键词需要前置"],
            interview_weaknesses=["系统设计深度题", "RAG 评测指标表达"],
        )
    )
    store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id=JD_ANALYSIS_ID,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=JD_ARTIFACT_ID,
            evidence_refs=[JD_ARTIFACT_ID],
            created_at=now,
            updated_at=now,
            company="星河智能",
            position="AI 应用后端工程师",
            seniority="中级",
            required_skills=["Python", "FastAPI", "RAG", "向量检索", "异步任务", "Docker"],
            preferred_skills=["Agent 工具调用", "LLM 评测", "可观测性"],
            responsibilities=["建设企业知识库问答服务", "维护模型调用和工具编排链路", "优化接口稳定性和响应延迟"],
            keywords=["RAG", "Agent", "FastAPI", "向量数据库", "可观测性"],
            risk_signals=["需要线上稳定性经验", "可能关注高并发和成本控制"],
            interview_focus=["RAG 检索质量评估", "工具调用失败恢复", "异步任务和审计日志设计"],
        )
    )
    store.save_job_fit_report(
        JobFitReport(
            job_fit_report_id=JOB_FIT_REPORT_ID,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=JD_ARTIFACT_ID,
            evidence_refs=[
                RESUME_PROFILE_ID,
                CAREER_PROFILE_ID,
                JD_ANALYSIS_ID,
                JD_ARTIFACT_ID,
                FIT_REPORT_ARTIFACT_ID,
            ],
            created_at=now,
            updated_at=now,
            jd_analysis_id=JD_ANALYSIS_ID,
            resume_profile_id=RESUME_PROFILE_ID,
            career_profile_id=CAREER_PROFILE_ID,
            overall_score=82,
            score_breakdown={
                "技能匹配": 86,
                "项目经验": 82,
                "业务结果": 72,
                "岗位动机": 88,
            },
            matched_evidence=[
                "有 FastAPI 服务和 RAG 项目经验",
                "有 Agent 工具调用审计台项目",
                "关注接口稳定性和可观测性",
            ],
            gaps=[
                "高并发生产案例不足",
                "RAG 评测指标需要表达得更具体",
                "业务收益量化不够",
            ],
            resume_optimization_direction=[
                "把 RAG 项目放到第一项目",
                "补充延迟、准确率、节省人力等指标",
                "增加 Agent 工具失败恢复描述",
            ],
            interview_preparation_focus=[
                "准备 RAG 检索链路白板题",
                "准备 FastAPI 异步任务和日志追踪设计",
                "准备一次线上问题排查案例",
            ],
            recommendation="recommended",
            report_artifact_id=FIT_REPORT_ARTIFACT_ID,
        )
    )
    store.save_resume_version(
        ResumeVersion(
            resume_version_id=RESUME_VERSION_ID,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=RESUME_VERSION_ARTIFACT_ID,
            evidence_refs=[
                RESUME_PROFILE_ID,
                CAREER_PROFILE_ID,
                JD_ANALYSIS_ID,
                JOB_FIT_REPORT_ID,
                RESUME_VERSION_ARTIFACT_ID,
            ],
            created_at=now,
            updated_at=now,
            base_resume_profile_id=RESUME_PROFILE_ID,
            target_jd_analysis_id=JD_ANALYSIS_ID,
            title="AI 应用后端工程师定制简历",
            format="markdown",
            artifact_id=RESUME_VERSION_ARTIFACT_ID,
            change_summary=["突出 RAG 和 Agent 项目", "把量化结果前置", "弱化无关经历"],
            keyword_strategy=["FastAPI", "RAG", "Agent 工具调用", "向量检索", "可观测性"],
            risk_notes=["高并发经验需在面试中补充", "不要夸大模型评测经验"],
        )
    )
    store.save_career_application(
        CareerApplication(
            application_id=CAREER_APPLICATION_ID,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=JD_ARTIFACT_ID,
            evidence_refs=[
                RESUME_PROFILE_ID,
                CAREER_PROFILE_ID,
                JD_ANALYSIS_ID,
                JOB_FIT_REPORT_ID,
                RESUME_VERSION_ID,
                JD_ARTIFACT_ID,
            ],
            created_at=now,
            updated_at=now,
            company="星河智能",
            position="AI 应用后端工程师",
            location="上海",
            stage="ready_to_apply",
            priority="high",
            resume_profile_id=RESUME_PROFILE_ID,
            career_profile_id=CAREER_PROFILE_ID,
            jd_analysis_id=JD_ANALYSIS_ID,
            job_fit_report_id=JOB_FIT_REPORT_ID,
            resume_version_ids=[RESUME_VERSION_ID],
            summary="匹配度较高，已生成诊断、JD 分析、匹配报告和定制简历，可进入投递准备。",
            next_actions=["复核定制简历事实准确性", "准备 RAG 检索评估和工具失败恢复面试题"],
            risks=["高并发生产案例需要补充口径", "RAG 指标需要用项目事实支撑"],
            notes="M4 前端演示求职项目。",
        )
    )


def _write_text_artifact(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    artifact_id: str,
    title: str,
    kind: str,
    media_type: str,
    owner_agent_id: str | None,
    content: str,
) -> None:
    session_root = repository.get_session_root_path(session_id)
    artifact_dir = session_root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    storage_path = artifact_dir / "original.bin"
    text_path = artifact_dir / "content.txt"
    storage_path.write_text(content, encoding="utf-8")
    text_path.write_text(content, encoding="utf-8")

    now = app_now()
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind=kind,
            title=title,
            media_type=media_type,
            size_bytes=len(content.encode("utf-8")),
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath=str(storage_path.resolve().relative_to(session_root.resolve())),
            text_relpath=str(text_path.resolve().relative_to(session_root.resolve())),
            owner_agent_id=owner_agent_id,
            description=f"M4 前端演示 artifact: {title}",
            source_type="demo_seed",
            source_event_id=None,
            error=None,
            text_char_count=len(content),
            token_estimate=max(1, len(content) // 4),
            parsed_at=now,
        )
    )


def _resume_text() -> str:
    return """姓名：林一凡
城市：上海
邮箱：lin.demo@example.com

教育经历：
- 华东示例大学 计算机科学与技术 本科

工作经历：
- 示例科技 后端工程师
- 负责 FastAPI 服务、RAG 检索链路、Agent 工具调用审计台。

项目经历：
- 企业知识库问答系统：实现文档解析、向量检索、答案生成和接口监控。
- Agent 工具调用审计台：沉淀工具调用事件，支持问题追踪和链路复盘。
"""


def _diagnosis_markdown() -> str:
    return """# 简历诊断

## 总体判断

这份简历适合投递 AI 应用后端、RAG 平台和 Agent 工具链相关岗位。

## 主要问题

- 项目成果有技术动作，但业务结果量化不足。
- RAG、Agent、可观测性等关键词需要在摘要和项目标题中前置。
- 面试风险集中在高并发生产经验和 RAG 评测体系。

## 修改建议

1. 将“企业知识库问答系统”放到项目第一位。
2. 每个项目补充延迟、准确率、节省人力或稳定性指标。
3. 将工具调用失败恢复、审计日志、链路追踪写成独立亮点。
"""


def _jd_text() -> str:
    return """星河智能招聘 AI 应用后端工程师。

职责：
- 建设企业知识库问答服务。
- 维护模型调用和工具编排链路。
- 优化接口稳定性和响应延迟。

要求：
- 熟悉 Python、FastAPI、异步任务。
- 熟悉 RAG、向量检索和文档处理。
- 有 Agent 工具调用、LLM 评测、可观测性经验优先。
"""


def _fit_report_markdown() -> str:
    return """# 岗位匹配报告

## 匹配分数

综合匹配度：82 / 100

## 匹配证据

- 简历中已有 FastAPI 服务经验。
- 有企业知识库问答系统，与 JD 中 RAG 要求直接匹配。
- 有 Agent 工具调用审计台，能支撑工具编排和可观测性话题。

## 差距

- 高并发生产案例不足。
- RAG 评测指标需要表达得更具体。
- 业务收益量化不够。

## 建议

推荐投递。简历应优先强化 RAG 项目、Agent 工具链和稳定性治理。
"""


def _resume_version_markdown() -> str:
    return """# 林一凡 - AI 应用后端工程师

## 个人优势

- 熟悉 Python、FastAPI、RAG、Agent 工具调用和接口可观测性。
- 有企业知识库问答系统和工具调用审计台项目经验。
- 能从产品链路角度处理文档解析、检索、生成、日志和问题追踪。

## 核心项目

### 企业知识库问答系统

- 负责文档解析、向量检索、答案生成和接口监控。
- 优化检索链路和接口响应，支撑企业内部知识问答场景。

### Agent 工具调用审计台

- 接入工具调用事件，沉淀审计日志。
- 支持工具失败定位、调用链路复盘和产品资产追踪。

## 技能

Python / FastAPI / RAG / Agent / PostgreSQL / Redis / Docker
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 M4 前端求职资产面板演示数据。")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="目标数据目录，默认 data。")
    parser.add_argument(
        "--session-id",
        default=DEFAULT_SESSION_ID,
        help=f"演示会话 id，默认 {DEFAULT_SESSION_ID}。",
    )
    args = parser.parse_args()

    summary = seed_demo_data(args.data_dir, session_id=args.session_id)
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
