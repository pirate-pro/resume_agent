"""External career knowledge asset domain."""

from __future__ import annotations

from app.knowledge.models import (
    CompanyProfile,
    ExperiencePost,
    ExternalResource,
    InterviewDifficulty,
    InterviewQuestion,
    KnowledgeRecordStatus,
    QuestionType,
    ResourceType,
    SkillCategory,
    SkillLevel,
    SkillRequirement,
)
from app.knowledge.store import KnowledgeStore

__all__ = [
    "CompanyProfile",
    "ExperiencePost",
    "ExternalResource",
    "InterviewDifficulty",
    "InterviewQuestion",
    "KnowledgeRecordStatus",
    "KnowledgeStore",
    "QuestionType",
    "ResourceType",
    "SkillCategory",
    "SkillLevel",
    "SkillRequirement",
]
