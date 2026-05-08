class ChatMessage {
  final String role; // "user" | "assistant"
  final String content;
  final String answerFormat;
  final String renderHint;
  final String layoutHint;
  final String sourceKind;
  final List<AnswerArtifactView> artifacts;
  final List<ToolCallView> toolCalls;
  final List<EventView> progressEvents;
  final DateTime timestamp;

  ChatMessage({
    required this.role,
    required this.content,
    this.answerFormat = "plain_text",
    this.renderHint = "plain",
    this.layoutHint = "paragraph",
    this.sourceKind = "direct_answer",
    this.artifacts = const [],
    this.toolCalls = const [],
    this.progressEvents = const [],
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();

  bool get isUser => role == "user";
}

class AnswerArtifactView {
  final String type;
  final String path;
  final String role;

  const AnswerArtifactView({
    required this.type,
    required this.path,
    required this.role,
  });

  factory AnswerArtifactView.fromJson(Map<String, dynamic> json) {
    return AnswerArtifactView(
      type: json["type"] ?? "",
      path: json["path"] ?? "",
      role: json["role"] ?? "",
    );
  }
}

class ToolCallView {
  final String name;
  final Map<String, dynamic> arguments;

  ToolCallView({required this.name, required this.arguments});

  factory ToolCallView.fromJson(Map<String, dynamic> json) {
    return ToolCallView(
      name: json["name"] ?? "",
      arguments: Map<String, dynamic>.from(json["arguments"] ?? {}),
    );
  }
}

class MemoryView {
  final String memoryId;
  final String content;
  final List<String> tags;

  MemoryView({
    required this.memoryId,
    required this.content,
    required this.tags,
  });

  factory MemoryView.fromJson(Map<String, dynamic> json) {
    return MemoryView(
      memoryId: json["memory_id"] ?? "",
      content: json["content"] ?? "",
      tags: List<String>.from(json["tags"] ?? []),
    );
  }
}

class MidTermFlushQueueView {
  final int targets;
  final int total;
  final int due;
  final int retry;
  final int deferred;
  final int succeeded;

  MidTermFlushQueueView({
    required this.targets,
    required this.total,
    required this.due,
    required this.retry,
    required this.deferred,
    required this.succeeded,
  });

  factory MidTermFlushQueueView.fromJson(Map<String, dynamic> json) {
    int readInt(String key) {
      final raw = json[key];
      if (raw is int) return raw;
      if (raw is num) return raw.toInt();
      if (raw is String) return int.tryParse(raw.trim()) ?? 0;
      return 0;
    }

    return MidTermFlushQueueView(
      targets: readInt("targets"),
      total: readInt("total"),
      due: readInt("due"),
      retry: readInt("retry"),
      deferred: readInt("deferred"),
      succeeded: readInt("succeeded"),
    );
  }
}

class MidTermFlushHealthView {
  final bool workerEnabled;
  final MidTermFlushQueueView? queue;
  final String? error;

  MidTermFlushHealthView({
    required this.workerEnabled,
    required this.queue,
    required this.error,
  });

  factory MidTermFlushHealthView.fromJson(Map<String, dynamic> json) {
    final queueRaw = json["queue"];
    final queue = queueRaw is Map<String, dynamic>
        ? MidTermFlushQueueView.fromJson(queueRaw)
        : queueRaw is Map
            ? MidTermFlushQueueView.fromJson(
                Map<String, dynamic>.from(queueRaw),
              )
            : null;
    final rawWorkerEnabled = json["worker_enabled"];
    final workerEnabled = rawWorkerEnabled == true;
    final rawError = json["error"];
    final error = rawError is String && rawError.trim().isNotEmpty
        ? rawError.trim()
        : null;
    return MidTermFlushHealthView(
      workerEnabled: workerEnabled,
      queue: queue,
      error: error,
    );
  }
}

class HealthView {
  final String status;
  final MidTermFlushHealthView? midTermFlush;

  HealthView({
    required this.status,
    required this.midTermFlush,
  });

  bool get isOnline => status == "ok";

  factory HealthView.fromJson(Map<String, dynamic> json) {
    final rawMidTerm = json["mid_term_flush"];
    final midTerm = rawMidTerm is Map<String, dynamic>
        ? MidTermFlushHealthView.fromJson(rawMidTerm)
        : rawMidTerm is Map
            ? MidTermFlushHealthView.fromJson(
                Map<String, dynamic>.from(rawMidTerm),
              )
            : null;
    return HealthView(
      status: (json["status"] ?? "").toString(),
      midTermFlush: midTerm,
    );
  }
}

class SkillOption {
  final String name;
  final String description;

  SkillOption({required this.name, required this.description});

  factory SkillOption.fromJson(Map<String, dynamic> json) {
    return SkillOption(
      name: json["name"] ?? "",
      description: json["description"] ?? "",
    );
  }
}

class ChatResponse {
  final String sessionId;
  final String answer;
  final bool titlePending;
  final String answerFormat;
  final String renderHint;
  final String layoutHint;
  final String sourceKind;
  final List<AnswerArtifactView> artifacts;
  final List<ToolCallView> toolCalls;
  final List<MemoryView> memoryHits;

  ChatResponse({
    required this.sessionId,
    required this.answer,
    this.titlePending = false,
    this.answerFormat = "plain_text",
    this.renderHint = "plain",
    this.layoutHint = "paragraph",
    this.sourceKind = "direct_answer",
    this.artifacts = const [],
    required this.toolCalls,
    required this.memoryHits,
  });

  factory ChatResponse.fromJson(Map<String, dynamic> json) {
    return ChatResponse(
      sessionId: json["session_id"] ?? "",
      answer: json["answer"] ?? "",
      titlePending: json["title_pending"] == true,
      answerFormat: json["answer_format"] ?? "plain_text",
      renderHint: json["render_hint"] ?? "plain",
      layoutHint: json["layout_hint"] ?? "paragraph",
      sourceKind: json["source_kind"] ?? "direct_answer",
      artifacts: (json["artifacts"] as List?)
              ?.map((e) =>
                  AnswerArtifactView.fromJson(Map<String, dynamic>.from(e)))
              .toList() ??
          const [],
      toolCalls: (json["tool_calls"] as List?)
              ?.map((e) => ToolCallView.fromJson(e))
              .toList() ??
          [],
      memoryHits: (json["memory_hits"] as List?)
              ?.map((e) => MemoryView.fromJson(e))
              .toList() ??
          [],
    );
  }
}

class SessionArtifactView {
  final String artifactId;
  final String title;
  final String kind;
  final String mediaType;
  final int sizeBytes;
  final String status;
  final String visibility;
  final DateTime createdAt;
  final DateTime updatedAt;
  final String? ownerAgentId;
  final String? description;
  final String? error;
  final int? textCharCount;
  final int? tokenEstimate;
  final DateTime? parsedAt;

  SessionArtifactView({
    required this.artifactId,
    required this.title,
    required this.kind,
    required this.mediaType,
    required this.sizeBytes,
    required this.status,
    required this.visibility,
    required this.createdAt,
    required this.updatedAt,
    this.ownerAgentId,
    this.description,
    this.error,
    this.textCharCount,
    this.tokenEstimate,
    this.parsedAt,
  });

  factory SessionArtifactView.fromJson(Map<String, dynamic> json) {
    return SessionArtifactView(
      artifactId: json["artifact_id"] ?? "",
      title: json["title"] ?? "",
      kind: json["kind"] ?? "",
      mediaType: json["media_type"] ?? "",
      sizeBytes: json["size_bytes"] ?? 0,
      status: json["status"] ?? "",
      visibility: json["visibility"] ?? "",
      createdAt: DateTime.parse(
        json["created_at"] ?? DateTime.now().toIso8601String(),
      ),
      updatedAt: DateTime.parse(
        json["updated_at"] ?? DateTime.now().toIso8601String(),
      ),
      ownerAgentId: json["owner_agent_id"],
      description: json["description"],
      error: json["error"],
      textCharCount: json["text_char_count"],
      tokenEstimate: json["token_estimate"],
      parsedAt: json["parsed_at"] == null
          ? null
          : DateTime.tryParse(json["parsed_at"].toString()),
    );
  }

  String get sizeDisplay {
    if (sizeBytes < 1024) return "$sizeBytes B";
    if (sizeBytes < 1024 * 1024) {
      return "${(sizeBytes / 1024).toStringAsFixed(1)} KB";
    }
    return "${(sizeBytes / 1024 / 1024).toStringAsFixed(1)} MB";
  }
}

class SessionArtifactsResponse {
  final String sessionId;
  final List<String> activeArtifactIds;
  final List<SessionArtifactView> artifacts;

  SessionArtifactsResponse({
    required this.sessionId,
    required this.activeArtifactIds,
    required this.artifacts,
  });

  factory SessionArtifactsResponse.fromJson(Map<String, dynamic> json) {
    return SessionArtifactsResponse(
      sessionId: json["session_id"] ?? "",
      activeArtifactIds: List<String>.from(json["active_artifact_ids"] ?? []),
      artifacts: (json["artifacts"] as List?)
              ?.map((e) => SessionArtifactView.fromJson(e))
              .toList() ??
          [],
    );
  }
}

class WorkspaceFilePreview {
  final String sessionId;
  final String path;
  final String content;
  final int sizeBytes;
  final int totalChars;
  final bool truncated;
  final String answerFormat;
  final String renderHint;
  final String layoutHint;

  WorkspaceFilePreview({
    required this.sessionId,
    required this.path,
    required this.content,
    required this.sizeBytes,
    required this.totalChars,
    required this.truncated,
    this.answerFormat = "plain_text",
    this.renderHint = "plain",
    this.layoutHint = "paragraph",
  });

  factory WorkspaceFilePreview.fromJson(Map<String, dynamic> json) {
    return WorkspaceFilePreview(
      sessionId: json["session_id"] ?? "",
      path: json["path"] ?? "",
      content: json["content"] ?? "",
      sizeBytes: json["size_bytes"] ?? 0,
      totalChars: json["total_chars"] ?? 0,
      truncated: json["truncated"] == true,
      answerFormat: json["answer_format"] ?? "plain_text",
      renderHint: json["render_hint"] ?? "plain",
      layoutHint: json["layout_hint"] ?? "paragraph",
    );
  }
}

class SessionMeta {
  final String id;
  final String title;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool isPinned;
  final DateTime? pinnedAt;
  final int messageCount;

  SessionMeta({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.isPinned = false,
    this.pinnedAt,
    this.messageCount = 0,
  });
}

class EventView {
  final String eventId;
  final String sessionId;
  final String agentId;
  final String runId;
  final String? parentRunId;
  final int eventVersion;
  final String type;
  final Map<String, dynamic> payload;
  final DateTime createdAt;

  EventView({
    required this.eventId,
    required this.sessionId,
    required this.agentId,
    required this.runId,
    this.parentRunId,
    required this.eventVersion,
    required this.type,
    required this.payload,
    required this.createdAt,
  });

  factory EventView.fromJson(Map<String, dynamic> json) {
    return EventView(
      eventId: json["event_id"] ?? "",
      sessionId: json["session_id"] ?? "",
      agentId: json["agent_id"] ?? "",
      runId: json["run_id"] ?? "",
      parentRunId: json["parent_run_id"],
      eventVersion: json["event_version"] ?? 0,
      type: json["type"] ?? "",
      payload: Map<String, dynamic>.from(json["payload"] ?? {}),
      createdAt: DateTime.parse(
        json["created_at"] ?? DateTime.now().toIso8601String(),
      ),
    );
  }

  String get shortDescription {
    switch (type) {
      case "run_started":
        return "开始执行任务";
      case "assistant_thinking":
        return "模型思考: ${(payload["content"] ?? "").toString().substring(0, (payload["content"] ?? "").toString().length.clamp(0, 120))}";
      case "tool_call":
        return "调用工具 ${payload["name"] ?? "unknown"}";
      case "tool_result":
        final ok = payload["success"] == true ? "成功" : "失败";
        return "工具$ok ${payload["tool_name"] ?? "unknown"}";
      case "run_finished":
        return "执行完成";
      default:
        return type;
    }
  }
}

class CareerRecordMetaView {
  final String status;
  final String sourceSessionId;
  final String? sourceArtifactId;
  final List<String> evidenceRefs;
  final DateTime createdAt;
  final DateTime updatedAt;

  CareerRecordMetaView({
    required this.status,
    required this.sourceSessionId,
    required this.sourceArtifactId,
    required this.evidenceRefs,
    required this.createdAt,
    required this.updatedAt,
  });

  factory CareerRecordMetaView.fromJson(Map<String, dynamic> json) {
    return CareerRecordMetaView(
      status: (json["status"] ?? "").toString(),
      sourceSessionId: (json["source_session_id"] ?? "").toString(),
      sourceArtifactId: _readOptionalString(json["source_artifact_id"]),
      evidenceRefs: _readStringList(json["evidence_refs"]),
      createdAt: _readDateTime(json["created_at"]),
      updatedAt: _readDateTime(json["updated_at"]),
    );
  }
}

class ResumeProfileView {
  final CareerRecordMetaView meta;
  final String resumeProfileId;
  final Map<String, dynamic> basicInfo;
  final List<dynamic> education;
  final List<dynamic> workExperience;
  final List<dynamic> projectExperience;
  final List<dynamic> skills;
  final List<dynamic> certificates;
  final List<dynamic> awards;
  final String selfEvaluation;
  final String? rawTextArtifactId;
  final String? diagnosisArtifactId;
  final Map<String, dynamic> diagnosis;

  ResumeProfileView({
    required this.meta,
    required this.resumeProfileId,
    required this.basicInfo,
    required this.education,
    required this.workExperience,
    required this.projectExperience,
    required this.skills,
    required this.certificates,
    required this.awards,
    required this.selfEvaluation,
    required this.rawTextArtifactId,
    required this.diagnosisArtifactId,
    required this.diagnosis,
  });

  factory ResumeProfileView.fromJson(Map<String, dynamic> json) {
    return ResumeProfileView(
      meta: CareerRecordMetaView.fromJson(json),
      resumeProfileId: (json["resume_profile_id"] ?? "").toString(),
      basicInfo: _readMap(json["basic_info"]),
      education: _readList(json["education"]),
      workExperience: _readList(json["work_experience"]),
      projectExperience: _readList(json["project_experience"]),
      skills: _readList(json["skills"]),
      certificates: _readList(json["certificates"]),
      awards: _readList(json["awards"]),
      selfEvaluation: (json["self_evaluation"] ?? "").toString(),
      rawTextArtifactId: _readOptionalString(json["raw_text_artifact_id"]),
      diagnosisArtifactId: _readOptionalString(json["diagnosis_artifact_id"]),
      diagnosis: _readMap(json["diagnosis"]),
    );
  }

  String get displayName {
    for (final key in ["name", "姓名", "full_name"]) {
      final value = basicInfo[key];
      if (value is String && value.trim().isNotEmpty) {
        return value.trim();
      }
    }
    return resumeProfileId;
  }
}

class CareerProfileView {
  final CareerRecordMetaView meta;
  final String careerProfileId;
  final String careerGoal;
  final List<String> targetRoles;
  final List<String> preferredIndustries;
  final List<String> preferredCities;
  final List<String> strengths;
  final List<String> weaknesses;
  final List<String> skills;
  final List<String> interests;
  final String educationSummary;
  final String experienceSummary;
  final List<String> resumeIssues;
  final List<String> interviewWeaknesses;

  CareerProfileView({
    required this.meta,
    required this.careerProfileId,
    required this.careerGoal,
    required this.targetRoles,
    required this.preferredIndustries,
    required this.preferredCities,
    required this.strengths,
    required this.weaknesses,
    required this.skills,
    required this.interests,
    required this.educationSummary,
    required this.experienceSummary,
    required this.resumeIssues,
    required this.interviewWeaknesses,
  });

  factory CareerProfileView.fromJson(Map<String, dynamic> json) {
    return CareerProfileView(
      meta: CareerRecordMetaView.fromJson(json),
      careerProfileId: (json["career_profile_id"] ?? "").toString(),
      careerGoal: (json["career_goal"] ?? "").toString(),
      targetRoles: _readStringList(json["target_roles"]),
      preferredIndustries: _readStringList(json["preferred_industries"]),
      preferredCities: _readStringList(json["preferred_cities"]),
      strengths: _readStringList(json["strengths"]),
      weaknesses: _readStringList(json["weaknesses"]),
      skills: _readStringList(json["skills"]),
      interests: _readStringList(json["interests"]),
      educationSummary: (json["education_summary"] ?? "").toString(),
      experienceSummary: (json["experience_summary"] ?? "").toString(),
      resumeIssues: _readStringList(json["resume_issues"]),
      interviewWeaknesses: _readStringList(json["interview_weaknesses"]),
    );
  }
}

class JDAnalysisView {
  final CareerRecordMetaView meta;
  final String jdAnalysisId;
  final String company;
  final String position;
  final String seniority;
  final List<String> requiredSkills;
  final List<String> preferredSkills;
  final List<String> responsibilities;
  final List<String> keywords;
  final List<String> riskSignals;
  final List<String> interviewFocus;

  JDAnalysisView({
    required this.meta,
    required this.jdAnalysisId,
    required this.company,
    required this.position,
    required this.seniority,
    required this.requiredSkills,
    required this.preferredSkills,
    required this.responsibilities,
    required this.keywords,
    required this.riskSignals,
    required this.interviewFocus,
  });

  factory JDAnalysisView.fromJson(Map<String, dynamic> json) {
    return JDAnalysisView(
      meta: CareerRecordMetaView.fromJson(json),
      jdAnalysisId: (json["jd_analysis_id"] ?? "").toString(),
      company: (json["company"] ?? "").toString(),
      position: (json["position"] ?? "").toString(),
      seniority: (json["seniority"] ?? "").toString(),
      requiredSkills: _readStringList(json["required_skills"]),
      preferredSkills: _readStringList(json["preferred_skills"]),
      responsibilities: _readStringList(json["responsibilities"]),
      keywords: _readStringList(json["keywords"]),
      riskSignals: _readStringList(json["risk_signals"]),
      interviewFocus: _readStringList(json["interview_focus"]),
    );
  }

  String get displayTitle {
    final parts = [company, position].where((item) => item.trim().isNotEmpty);
    final title = parts.join(" · ");
    return title.isEmpty ? jdAnalysisId : title;
  }
}

class JobFitReportView {
  final CareerRecordMetaView meta;
  final String jobFitReportId;
  final String jdAnalysisId;
  final String resumeProfileId;
  final String careerProfileId;
  final int overallScore;
  final Map<String, int> scoreBreakdown;
  final List<dynamic> matchedEvidence;
  final List<dynamic> gaps;
  final List<dynamic> resumeOptimizationDirection;
  final List<dynamic> interviewPreparationFocus;
  final String recommendation;
  final String? reportArtifactId;

  JobFitReportView({
    required this.meta,
    required this.jobFitReportId,
    required this.jdAnalysisId,
    required this.resumeProfileId,
    required this.careerProfileId,
    required this.overallScore,
    required this.scoreBreakdown,
    required this.matchedEvidence,
    required this.gaps,
    required this.resumeOptimizationDirection,
    required this.interviewPreparationFocus,
    required this.recommendation,
    required this.reportArtifactId,
  });

  factory JobFitReportView.fromJson(Map<String, dynamic> json) {
    return JobFitReportView(
      meta: CareerRecordMetaView.fromJson(json),
      jobFitReportId: (json["job_fit_report_id"] ?? "").toString(),
      jdAnalysisId: (json["jd_analysis_id"] ?? "").toString(),
      resumeProfileId: (json["resume_profile_id"] ?? "").toString(),
      careerProfileId: (json["career_profile_id"] ?? "").toString(),
      overallScore: _readInt(json["overall_score"]),
      scoreBreakdown: _readIntMap(json["score_breakdown"]),
      matchedEvidence: _readList(json["matched_evidence"]),
      gaps: _readList(json["gaps"]),
      resumeOptimizationDirection:
          _readList(json["resume_optimization_direction"]),
      interviewPreparationFocus: _readList(json["interview_preparation_focus"]),
      recommendation: (json["recommendation"] ?? "").toString(),
      reportArtifactId: _readOptionalString(json["report_artifact_id"]),
    );
  }
}

class ResumeVersionView {
  final CareerRecordMetaView meta;
  final String resumeVersionId;
  final String baseResumeProfileId;
  final String? targetJdAnalysisId;
  final String title;
  final String format;
  final String artifactId;
  final List<String> changeSummary;
  final List<String> keywordStrategy;
  final List<String> riskNotes;

  ResumeVersionView({
    required this.meta,
    required this.resumeVersionId,
    required this.baseResumeProfileId,
    required this.targetJdAnalysisId,
    required this.title,
    required this.format,
    required this.artifactId,
    required this.changeSummary,
    required this.keywordStrategy,
    required this.riskNotes,
  });

  factory ResumeVersionView.fromJson(Map<String, dynamic> json) {
    return ResumeVersionView(
      meta: CareerRecordMetaView.fromJson(json),
      resumeVersionId: (json["resume_version_id"] ?? "").toString(),
      baseResumeProfileId: (json["base_resume_profile_id"] ?? "").toString(),
      targetJdAnalysisId: _readOptionalString(json["target_jd_analysis_id"]),
      title: (json["title"] ?? "").toString(),
      format: (json["format"] ?? "").toString(),
      artifactId: (json["artifact_id"] ?? "").toString(),
      changeSummary: _readStringList(json["change_summary"]),
      keywordStrategy: _readStringList(json["keyword_strategy"]),
      riskNotes: _readStringList(json["risk_notes"]),
    );
  }
}

class SessionArtifactContentView {
  final String sessionId;
  final String artifactId;
  final String title;
  final String mediaType;
  final String status;
  final int totalChars;
  final int offset;
  final int returnedChars;
  final bool truncated;
  final String content;

  SessionArtifactContentView({
    required this.sessionId,
    required this.artifactId,
    required this.title,
    required this.mediaType,
    required this.status,
    required this.totalChars,
    required this.offset,
    required this.returnedChars,
    required this.truncated,
    required this.content,
  });

  factory SessionArtifactContentView.fromJson(Map<String, dynamic> json) {
    return SessionArtifactContentView(
      sessionId: (json["session_id"] ?? "").toString(),
      artifactId: (json["artifact_id"] ?? "").toString(),
      title: (json["title"] ?? "").toString(),
      mediaType: (json["media_type"] ?? "").toString(),
      status: (json["status"] ?? "").toString(),
      totalChars: _readInt(json["total_chars"]),
      offset: _readInt(json["offset"]),
      returnedChars: _readInt(json["returned_chars"]),
      truncated: json["truncated"] == true,
      content: (json["content"] ?? "").toString(),
    );
  }
}

DateTime _readDateTime(dynamic raw) {
  return DateTime.tryParse((raw ?? "").toString()) ?? DateTime.now();
}

String? _readOptionalString(dynamic raw) {
  if (raw == null) return null;
  final value = raw.toString().trim();
  return value.isEmpty ? null : value;
}

Map<String, dynamic> _readMap(dynamic raw) {
  if (raw is Map<String, dynamic>) return raw;
  if (raw is Map) return Map<String, dynamic>.from(raw);
  return {};
}

List<dynamic> _readList(dynamic raw) {
  if (raw is List) return List<dynamic>.from(raw);
  return const [];
}

List<String> _readStringList(dynamic raw) {
  if (raw is! List) return const [];
  return raw
      .map((item) => item.toString().trim())
      .where((item) => item.isNotEmpty)
      .toList();
}

int _readInt(dynamic raw) {
  if (raw is int) return raw;
  if (raw is num) return raw.toInt();
  if (raw is String) return int.tryParse(raw.trim()) ?? 0;
  return 0;
}

Map<String, int> _readIntMap(dynamic raw) {
  if (raw is! Map) return {};
  final result = <String, int>{};
  for (final entry in raw.entries) {
    final key = entry.key.toString().trim();
    if (key.isEmpty) continue;
    result[key] = _readInt(entry.value);
  }
  return result;
}
