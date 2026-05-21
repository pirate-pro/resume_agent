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
    ),
    "career_read": (
        "读取",
        "查询",
        "查看",
        "get",
        "list",
        "已有",
        "已保存",
        "记录",
        "id",
        "详情",
    ),
    "career_diagnosis": (
        "简历",
        "resume",
        "诊断",
        "画像",
        "解析简历",
        "简历画像",
        "职业画像",
        "resume profile",
    ),
    "career_jd_fit": (
        "jd",
        "岗位",
        "职位",
        "匹配",
        "匹配报告",
        "岗位分析",
        "jd analysis",
        "job fit",
    ),
    "career_resume_version": (
        "定制简历",
        "简历版本",
        "custom resume",
        "resume version",
        "版本",
    ),
    "career_application": (
        "求职项目",
        "application",
        "投递",
        "申请",
        "投递前",
        "面试准备",
        "项目动作",
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
_CAREER_GROUPS = (
    "career_read",
    "career_diagnosis",
    "career_jd_fit",
    "career_resume_version",
    "career_application",
)
_CAREER_DOMAIN_KEYWORDS = (
    "career",
    "求职",
    "简历",
    "resume",
    "职业画像",
    "jd",
    "岗位",
    "职位",
    "匹配",
    "投递",
    "申请",
    "application",
    "面试",
    "二面",
    "终面",
    "resume profile",
    "career profile",
    "job fit",
)
_GROUP_ORDER = (
    "retrieval",
    "artifact",
    "career_read",
    "career_diagnosis",
    "career_jd_fit",
    "career_resume_version",
    "career_application",
    "career",
    "note",
    "learning",
    "memory",
    "delegation",
    "state",
)


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
            "routing_guidance": _routing_guidance(
                query=self.query,
                matched_groups=self.matched_groups,
                revealed_tool_names=revealed_tool_names,
            ),
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
        reveal_names = _filter_reveal_names_for_query(
            reveal_names,
            query=normalized_query,
            matched_groups=matched_groups,
        )
        direct_matches = self._direct_matches(
            normalized_query,
            requested_groups,
            matched_groups=set(matched_groups),
        )
        if top_k > 0:
            direct_matches = direct_matches[:top_k]
        for entry in direct_matches:
            if entry.group == "state" and "state" not in requested_groups:
                continue
            reveal_names.append(entry.name)
        reveal_names = _filter_reveal_names_for_query(
            reveal_names,
            query=normalized_query,
            matched_groups=matched_groups,
        )

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

    def entries_for_names(self, names: list[str]) -> list[ToolCatalogEntry]:
        """Return catalog entries for concrete tool names in input order."""

        return self._entries_for_names(names)

    def _direct_matches(
        self,
        query: str,
        requested_groups: set[str],
        *,
        matched_groups: set[str],
    ) -> list[ToolCatalogEntry]:
        if not query and not requested_groups:
            return []
        scored: list[tuple[int, ToolCatalogEntry]] = []
        for entry in self._entries:
            if entry.name == _TOOL_SEARCH_NAME:
                continue
            if (
                entry.group not in matched_groups
                and entry.group not in requested_groups
                and not ("career" in requested_groups and entry.group in _CAREER_GROUPS)
                and entry.name not in query
            ):
                continue
            if (
                entry.group in _CAREER_GROUPS
                and entry.group not in matched_groups
                and entry.name not in query
            ):
                continue
            if requested_groups and not _entry_matches_requested_groups(entry, requested_groups):
                continue
            if "career" in requested_groups and entry.group in _CAREER_GROUPS and entry.group not in matched_groups:
                if entry.name not in query:
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
    if name in {
        "career_resume_profile_get",
        "career_resume_profile_list",
        "career_profile_get",
        "career_jd_analysis_get",
        "career_jd_analysis_list",
        "career_job_fit_report_get",
        "career_job_fit_report_list",
        "career_resume_version_get",
        "career_resume_version_list",
        "career_application_get",
        "career_application_list",
    }:
        return "career_read"
    if name in {"career_resume_profile_save", "career_profile_merge"}:
        return "career_diagnosis"
    if name in {"career_jd_analysis_save", "career_job_fit_report_save"}:
        return "career_jd_fit"
    if name == "career_resume_version_create":
        return "career_resume_version"
    if name in {"career_application_create", "career_application_merge"}:
        return "career_application"
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
    groups: set[str] = {group for group in requested_groups if group != "career"}
    for group, keywords in _GROUP_KEYWORDS.items():
        if group == "state" and group not in requested_groups:
            continue
        if group == "note":
            continue
        if group == "career" or group in _CAREER_GROUPS:
            continue
        if any(keyword in query for keyword in keywords):
            groups.add(group)

    if "career" in requested_groups or _mentions_career_domain(query):
        groups.update(_career_groups_for_query(query))
    if "career_jd_fit" in groups:
        groups.add("career_application")
    if "career_resume_version" in groups:
        groups.add("career_application")
        if not _has_any(query, ("诊断", "画像", "解析简历", "简历画像", "职业画像")):
            groups.discard("career_diagnosis")

    if _has_any(
        query, ("artifact", "文件", "上传", "附件", "资料", "读取文件", "文件内容", "粘贴", "pasted", "pdf")
    ):
        groups.add("artifact")
    if groups.intersection({"career_diagnosis", "career_jd_fit"}):
        groups.add("delegation")
    if "note" in groups and _has_any(query, ("之前", "上次", "已有", "保存过", "复盘")):
        groups.add("retrieval")
    if _is_note_intent(query):
        groups.add("note")
        if _has_any(query, ("之前", "上次", "已有", "保存过", "复盘")):
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
    if group == "career_read":
        return [
            "career_resume_profile_get",
            "career_profile_get",
            "career_jd_analysis_get",
            "career_job_fit_report_get",
            "career_resume_version_get",
            "career_application_get",
        ]
    if group == "career_diagnosis":
        return [
            "career_resume_profile_save",
            "career_resume_profile_get",
            "career_profile_get",
            "career_profile_merge",
        ]
    if group == "career_jd_fit":
        return [
            "career_jd_analysis_save",
            "career_job_fit_report_save",
            "career_jd_analysis_get",
            "career_job_fit_report_get",
            "career_resume_profile_get",
            "career_profile_get",
            "career_application_create",
        ]
    if group == "career_resume_version":
        return [
            "career_resume_version_create",
            "career_resume_version_get",
            "career_resume_profile_get",
            "career_jd_analysis_get",
            "career_job_fit_report_get",
            "career_application_get",
            "career_application_merge",
        ]
    if group == "career_application":
        return [
            "career_application_create",
            "career_application_get",
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


def _filter_reveal_names_for_query(names: list[str], *, query: str, matched_groups: list[str]) -> list[str]:
    if "artifact" not in matched_groups or _is_artifact_write_intent(query):
        return names
    return [name for name in names if name != "session_create_text_artifact"]


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


def _entry_matches_requested_groups(entry: ToolCatalogEntry, requested_groups: set[str]) -> bool:
    if entry.group in requested_groups:
        return True
    return entry.group in _CAREER_GROUPS and "career" in requested_groups


def _career_groups_for_query(query: str) -> set[str]:
    groups: set[str] = set()
    if _has_any(query, ("读取", "查询", "查看", "get", "list", "已有", "已保存", "记录", "id", "详情")):
        groups.add("career_read")
    if _has_any(query, ("定制简历", "简历版本", "custom resume", "resume version", "版本")):
        groups.update({"career_resume_version", "career_application"})
    if _has_any(query, ("简历", "resume", "诊断", "画像", "解析简历", "简历画像", "职业画像", "career profile")):
        groups.add("career_diagnosis")
    if _has_any(query, ("jd", "岗位", "职位", "匹配", "匹配报告", "岗位分析", "job fit")):
        groups.update({"career_jd_fit", "career_application"})
    if _has_any(query, ("求职项目", "application", "投递", "申请", "投递前", "面试准备", "项目动作", "二面")):
        groups.add("career_application")
    if not groups:
        groups.add("career_read")
    return groups


def _mentions_career_domain(query: str) -> bool:
    return _has_any(query, _CAREER_DOMAIN_KEYWORDS)


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
        "career": "需要处理求职产品记录。",
        "career_read": "需要读取已有求职产品记录。",
        "career_diagnosis": "需要创建或更新简历画像和职业画像。",
        "career_jd_fit": "需要创建或读取 JD 分析与岗位匹配报告。",
        "career_resume_version": "需要创建或读取定制简历版本。",
        "career_application": "需要创建或更新求职项目。",
        "note": "需要创建、读取或更新用户笔记。",
        "learning": "需要创建、读取或更新学习计划、学习任务或短板记录。",
        "memory": "需要读写长期偏好、稳定事实或记忆。",
        "delegation": "需要委派专门 agent 执行简历或岗位子任务。",
        "state": "需要更新运行状态或工作视图。",
    }
    return labels.get(group, "工具描述与当前能力搜索匹配。")


def _routing_guidance(*, query: str, matched_groups: list[str], revealed_tool_names: list[str]) -> str | None:
    names = set(revealed_tool_names)
    normalized_query = _normalize(query)
    if (
        "career_jd_fit" in matched_groups
        and "delegate_agents" in names
        and not {"career_jd_analysis_save", "career_job_fit_report_save"}.intersection(names)
        and _has_any(normalized_query, ("save", "保存", "create", "创建", "jd analysis", "job fit report"))
    ):
        return (
            "当前 agent 未直接暴露 JDAnalysis/JobFitReport 保存工具；请调用 delegate_agents 委派 job_agent "
            "完成 JD 分析、匹配报告保存，并使用返回的 ids。不要继续 tool_search 查找 save 工具。"
        )
    if (
        "career_diagnosis" in matched_groups
        and "delegate_agents" in names
        and "career_resume_profile_save" not in names
        and _has_any(normalized_query, ("save", "保存", "resume profile", "简历画像", "诊断"))
    ):
        return (
            "当前 agent 未直接暴露 ResumeProfile 保存工具；请调用 delegate_agents 委派 resume_agent "
            "完成简历解析/诊断，并使用返回的 resume_profile_id 和 artifact_id。不要继续 tool_search 查找 save 工具。"
        )
    return None


def _is_note_intent(query: str) -> bool:
    if "笔记" in query:
        return True
    if _has_any(query, ("note_create", "note_update", "note_append", "note_get", "note_list")):
        return True
    if not _has_any(query, ("note", "notes", "notebook")):
        return False
    if _has_any(query, ("risk note", "risk notes", "风险备注", "风险说明", "风险点", "risk section")):
        return False
    note_phrases = (
        "save note",
        "save as note",
        "save this note",
        "save this as a note",
        "create note",
        "create a note",
        "write note",
        "write a note",
        "add note",
        "append note",
        "update note",
        "read note",
        "list note",
        "my note",
        "notebook",
    )
    return _has_any(query, note_phrases)


def _is_artifact_write_intent(query: str) -> bool:
    return _has_any(
        query,
        (
            "create artifact",
            "create text artifact",
            "save artifact",
            "write artifact",
            "生成 artifact",
            "创建 artifact",
            "保存 artifact",
            "创建文件",
            "生成文件",
            "保存文件",
            "生成报告文件",
            "保存报告",
            "创建报告",
        ),
    )


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)
