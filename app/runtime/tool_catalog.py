"""Deterministic catalog search for runtime tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.models import ToolDefinition

__all__ = [
    "ToolCatalog",
    "ToolCatalogEntry",
    "ToolCatalogSearchResult",
]

_TOOL_SEARCH_NAME = "tool_search"
_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "artifact": (
        "artifact",
        "文件",
        "上传",
        "附件",
        "资料",
        "读取文件",
        "文件内容",
        "粘贴",
        "pasted",
        "pdf",
        "markdown",
    ),
    "retrieval": (
        "retrieval",
        "rag",
        "召回",
        "检索",
        "之前",
        "上次",
        "历史",
        "保存过",
        "已有",
        "以前",
        "不用我提供",
        "不用提供 id",
    ),
    "career": (
        "career",
        "求职",
        "简历",
        "resume",
        "jd",
        "岗位",
        "职位",
        "匹配",
        "投递",
        "诊断",
        "画像",
        "定制",
        "版本",
        "简历版本",
        "custom resume",
        "resume version",
        "求职项目",
    ),
    "note": (
        "note",
        "笔记",
        "记录",
        "保存",
        "复盘",
        "总结",
        "追加",
    ),
    "learning": (
        "learning",
        "学习",
        "学习任务",
        "学习计划",
        "计划",
        "打卡",
        "监督",
        "短板",
        "补强",
    ),
    "memory": (
        "memory",
        "记住",
        "记忆",
        "长期偏好",
        "偏好",
        "以后",
        "忘记",
    ),
    "delegation": (
        "delegate",
        "agent",
        "多 agent",
        "multi-agent",
        "并行",
        "委派",
        "resume_agent",
        "job_agent",
    ),
    "state": (
        "state",
        "状态",
        "进度",
        "工作视图",
    ),
}
_GROUP_ORDER = ("retrieval", "artifact", "career", "note", "learning", "memory", "delegation", "state")


@dataclass(frozen=True, slots=True)
class ToolCatalogEntry:
    """Small model-facing description for one callable tool."""

    name: str
    description: str
    group: str
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self, *, why: str) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "group": self.group,
            "why": why,
        }


@dataclass(frozen=True, slots=True)
class ToolCatalogSearchResult:
    """Deterministic search result for model-visible tool discovery."""

    query: str
    matched_groups: list[str]
    revealed_tools: list[ToolCatalogEntry]
    reveal_packs: list[str]
    available_tool_count: int

    def to_payload(self) -> dict[str, Any]:
        revealed_tool_names = [entry.name for entry in self.revealed_tools]
        return {
            "query": self.query,
            "matched_groups": self.matched_groups,
            "reveal_packs": self.reveal_packs,
            "revealed_tools": [
                entry.to_payload(why=_why_for_group(entry.group))
                for entry in self.revealed_tools
            ],
            "revealed_tool_names": revealed_tool_names,
            "available_tool_count": self.available_tool_count,
            "revealed_tool_count": len(self.revealed_tools),
            "next_step": (
                "下一轮这些工具 schema 会变为可见；如果目标工具已在 revealed_tool_names 中，请直接调用它，不要再次 tool_search。"
                if self.revealed_tools
                else "没有找到明确工具；可以直接回答，或用更具体的能力描述重新搜索。"
            ),
            "search_guidance": (
                "tool_search 只用于发现尚未可见的能力；同一任务里已经揭示过的工具可连续调用。"
                if revealed_tool_names
                else "仅当缺少能力或工具名不确定时再搜索。"
            ),
        }


class ToolCatalog:
    """Sparse tool directory over the currently allowed tool definitions."""

    def __init__(self, definitions: list[ToolDefinition]) -> None:
        self._entries = [_entry_from_definition(definition) for definition in definitions]
        self._by_name = {entry.name: entry for entry in self._entries}

    def search(
        self,
        *,
        query: str,
        groups: list[str] | None = None,
        top_k: int = 8,
    ) -> ToolCatalogSearchResult:
        normalized_query = _normalize(query)
        requested_groups = _normalize_groups(groups or [])
        matched_groups = _matched_groups(normalized_query, requested_groups)
        reveal_names = self.resolve_reveal_names(matched_groups=matched_groups)
        direct_matches = self._direct_matches(normalized_query, requested_groups)
        if top_k > 0:
            direct_matches = direct_matches[:top_k]
        for entry in direct_matches:
            if entry.group == "state" and "state" not in requested_groups:
                continue
            reveal_names.append(entry.name)

        revealed_entries = self._entries_for_names(reveal_names)
        return ToolCatalogSearchResult(
            query=query.strip(),
            matched_groups=matched_groups,
            revealed_tools=revealed_entries,
            reveal_packs=matched_groups,
            available_tool_count=len(self._entries),
        )

    def resolve_reveal_names(self, *, matched_groups: list[str]) -> list[str]:
        output: list[str] = []
        for group in matched_groups:
            output.extend(_pack_names(group))
        return _dedupe_names(output)

    def _direct_matches(self, query: str, requested_groups: set[str]) -> list[ToolCatalogEntry]:
        if not query and not requested_groups:
            return []
        scored: list[tuple[int, ToolCatalogEntry]] = []
        for entry in self._entries:
            if entry.name == _TOOL_SEARCH_NAME:
                continue
            if requested_groups and entry.group not in requested_groups:
                continue
            score = _score_entry(entry, query=query, requested_groups=requested_groups)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], _group_rank(item[1].group), item[1].name))
        return [entry for _, entry in scored]

    def _entries_for_names(self, names: list[str]) -> list[ToolCatalogEntry]:
        output: list[ToolCatalogEntry] = []
        seen: set[str] = set()
        for name in names:
            entry = self._by_name.get(name)
            if entry is None or entry.name in seen or entry.name == _TOOL_SEARCH_NAME:
                continue
            output.append(entry)
            seen.add(entry.name)
        return output


def _entry_from_definition(definition: ToolDefinition) -> ToolCatalogEntry:
    group = _group_for_name(definition.name)
    return ToolCatalogEntry(
        name=definition.name,
        description=_compact_description(definition.description),
        group=group,
        keywords=_GROUP_KEYWORDS.get(group, ()),
    )


def _group_for_name(name: str) -> str:
    if name == _TOOL_SEARCH_NAME:
        return "core"
    if name.startswith("session_") or name.startswith("workspace_") or name == "publish_artifact":
        return "artifact"
    if name.startswith("retrieval_"):
        return "retrieval"
    if name.startswith("career_"):
        return "career"
    if name.startswith("note_"):
        return "note"
    if name.startswith("learning_"):
        return "learning"
    if name.startswith("memory_"):
        return "memory"
    if name in {"delegate_agents", "agent_task_status"}:
        return "delegation"
    if name.startswith("state_"):
        return "state"
    return "other"


def _matched_groups(query: str, requested_groups: set[str]) -> list[str]:
    groups: set[str] = set(requested_groups)
    for group, keywords in _GROUP_KEYWORDS.items():
        if group == "state" and group not in requested_groups:
            continue
        if any(keyword in query for keyword in keywords):
            groups.add(group)

    if "career" in groups and _has_any(query, ("简历", "jd", "岗位", "职位", "匹配", "投递")):
        groups.add("artifact")
    if "career" in groups and _has_any(query, ("诊断", "分析", "匹配", "画像", "多 agent", "委派")):
        groups.add("delegation")
    if "note" in groups and _has_any(query, ("之前", "上次", "已有", "保存过", "复盘")):
        groups.add("retrieval")
    if "learning" in groups:
        groups.add("retrieval")

    ordered = [group for group in _GROUP_ORDER if group in groups]
    return ordered


def _pack_names(group: str) -> list[str]:
    if group == "artifact":
        return [
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_read_artifact",
            "session_search_artifact",
            "session_create_text_artifact",
        ]
    if group == "retrieval":
        return ["retrieval_search", "retrieval_context_pack"]
    if group == "career":
        return [
            "career_resume_profile_get",
            "career_resume_profile_list",
            "career_profile_get",
            "career_profile_merge",
            "career_jd_analysis_get",
            "career_jd_analysis_list",
            "career_job_fit_report_get",
            "career_job_fit_report_list",
            "career_resume_version_create",
            "career_resume_version_get",
            "career_resume_version_list",
            "career_application_create",
            "career_application_get",
            "career_application_list",
            "career_application_merge",
        ]
    if group == "note":
        return [
            "note_create",
            "note_get",
            "note_list",
            "note_update",
            "note_append",
            "note_archive",
        ]
    if group == "learning":
        return [
            "learning_plan_create",
            "learning_plan_get",
            "learning_plan_list",
            "learning_task_create",
            "learning_task_get",
            "learning_task_list",
            "learning_task_update_state",
            "learning_checkin_create",
            "learning_weakness_create",
            "learning_weakness_update",
        ]
    if group == "memory":
        return [
            "memory_write",
            "memory_search",
            "memory_update",
            "memory_forget",
            "memory_explain",
            "memory_inspect",
        ]
    if group == "delegation":
        return ["delegate_agents", "agent_task_status"]
    if group == "state":
        return ["state_set", "state_publish", "state_list"]
    return []


def _score_entry(entry: ToolCatalogEntry, *, query: str, requested_groups: set[str]) -> int:
    score = 0
    if entry.group in requested_groups:
        score += 6
    if entry.name in query:
        score += 8
    for token in entry.name.split("_"):
        if token and token in query:
            score += 2
    for keyword in entry.keywords:
        if keyword in query:
            score += 3
    description = _normalize(entry.description)
    for keyword in entry.keywords:
        if keyword in description and keyword in query:
            score += 1
    return score


def _normalize(value: str) -> str:
    return value.strip().casefold()


def _normalize_groups(groups: list[str]) -> set[str]:
    output: set[str] = set()
    for raw in groups:
        if not isinstance(raw, str):
            continue
        group = raw.strip().casefold()
        if group in _GROUP_KEYWORDS or group in {"core", "other"}:
            output.add(group)
    return output


def _dedupe_names(names: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        output.append(name)
        seen.add(name)
    return output


def _compact_description(description: str) -> str:
    text = " ".join(description.strip().split())
    return text if len(text) <= 220 else f"{text[:219]}…"


def _group_rank(group: str) -> int:
    try:
        return _GROUP_ORDER.index(group)
    except ValueError:
        return len(_GROUP_ORDER)


def _why_for_group(group: str) -> str:
    labels = {
        "artifact": "需要读取或创建当前会话资料 artifact。",
        "retrieval": "需要召回已保存的产品记录、笔记、学习任务或资料。",
        "career": "需要处理简历、JD、匹配报告、简历版本或求职项目。",
        "note": "需要创建、读取或更新用户笔记。",
        "learning": "需要创建、读取或更新学习计划、学习任务或短板记录。",
        "memory": "需要读写长期偏好、稳定事实或记忆。",
        "delegation": "需要委派专门 agent 执行简历或岗位子任务。",
        "state": "需要更新运行状态或工作视图。",
    }
    return labels.get(group, "工具描述与当前能力搜索匹配。")


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)
