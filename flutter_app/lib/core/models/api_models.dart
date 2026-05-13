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

class CareerApplicationView {
  final CareerRecordMetaView meta;
  final String applicationId;
  final String company;
  final String position;
  final String location;
  final String jobUrl;
  final String stage;
  final String priority;
  final String? resumeProfileId;
  final String? careerProfileId;
  final String? jdAnalysisId;
  final String? jobFitReportId;
  final List<String> resumeVersionIds;
  final String summary;
  final List<String> nextActions;
  final List<String> risks;
  final String notes;

  CareerApplicationView({
    required this.meta,
    required this.applicationId,
    required this.company,
    required this.position,
    required this.location,
    required this.jobUrl,
    required this.stage,
    required this.priority,
    required this.resumeProfileId,
    required this.careerProfileId,
    required this.jdAnalysisId,
    required this.jobFitReportId,
    required this.resumeVersionIds,
    required this.summary,
    required this.nextActions,
    required this.risks,
    required this.notes,
  });

  factory CareerApplicationView.fromJson(Map<String, dynamic> json) {
    return CareerApplicationView(
      meta: CareerRecordMetaView.fromJson(json),
      applicationId: (json["application_id"] ?? "").toString(),
      company: (json["company"] ?? "").toString(),
      position: (json["position"] ?? "").toString(),
      location: (json["location"] ?? "").toString(),
      jobUrl: (json["job_url"] ?? "").toString(),
      stage: (json["stage"] ?? "draft").toString(),
      priority: (json["priority"] ?? "medium").toString(),
      resumeProfileId: _readOptionalString(json["resume_profile_id"]),
      careerProfileId: _readOptionalString(json["career_profile_id"]),
      jdAnalysisId: _readOptionalString(json["jd_analysis_id"]),
      jobFitReportId: _readOptionalString(json["job_fit_report_id"]),
      resumeVersionIds: _readStringList(json["resume_version_ids"]),
      summary: (json["summary"] ?? "").toString(),
      nextActions: _readStringList(json["next_actions"]),
      risks: _readStringList(json["risks"]),
      notes: (json["notes"] ?? "").toString(),
    );
  }

  String get displayTitle {
    final parts = [company, position].where((item) => item.trim().isNotEmpty);
    final title = parts.join(" · ");
    return title.isEmpty ? applicationId : title;
  }
}

class CareerReadinessView {
  final int? score;
  final String level;
  final String recommendation;
  final String summary;
  final List<String> strengths;
  final List<String> risks;
  final List<String> missingMaterials;
  final List<String> nextActions;

  CareerReadinessView({
    required this.score,
    required this.level,
    required this.recommendation,
    required this.summary,
    required this.strengths,
    required this.risks,
    required this.missingMaterials,
    required this.nextActions,
  });

  factory CareerReadinessView.fromJson(Map<String, dynamic> json) {
    return CareerReadinessView(
      score: json["score"] == null ? null : _readInt(json["score"]),
      level: (json["level"] ?? "unknown").toString(),
      recommendation: (json["recommendation"] ?? "unknown").toString(),
      summary: (json["summary"] ?? "").toString(),
      strengths: _readStringList(json["strengths"]),
      risks: _readStringList(json["risks"]),
      missingMaterials: _readStringList(json["missing_materials"]),
      nextActions: _readStringList(json["next_actions"]),
    );
  }
}

class CareerLinkedAssetView {
  final String type;
  final String id;
  final String title;
  final String subtitle;
  final String status;
  final DateTime? updatedAt;
  final String? previewArtifactId;
  final String? sourceSessionId;
  final bool isCurrent;
  final List<String> actions;

  CareerLinkedAssetView({
    required this.type,
    required this.id,
    required this.title,
    required this.subtitle,
    required this.status,
    required this.updatedAt,
    required this.previewArtifactId,
    required this.sourceSessionId,
    required this.isCurrent,
    required this.actions,
  });

  factory CareerLinkedAssetView.fromJson(Map<String, dynamic> json) {
    return CareerLinkedAssetView(
      type: (json["type"] ?? "").toString(),
      id: (json["id"] ?? "").toString(),
      title: (json["title"] ?? "").toString(),
      subtitle: (json["subtitle"] ?? "").toString(),
      status: (json["status"] ?? "active").toString(),
      updatedAt: _readOptionalDateTime(json["updated_at"]),
      previewArtifactId: _readOptionalString(json["preview_artifact_id"]),
      sourceSessionId: _readOptionalString(json["source_session_id"]),
      isCurrent: json["is_current"] == true,
      actions: _readStringList(json["actions"]),
    );
  }
}

class CareerTimelineItemView {
  final String type;
  final String title;
  final String subtitle;
  final DateTime occurredAt;
  final String sourceType;
  final String sourceId;

  CareerTimelineItemView({
    required this.type,
    required this.title,
    required this.subtitle,
    required this.occurredAt,
    required this.sourceType,
    required this.sourceId,
  });

  factory CareerTimelineItemView.fromJson(Map<String, dynamic> json) {
    return CareerTimelineItemView(
      type: (json["type"] ?? "").toString(),
      title: (json["title"] ?? "").toString(),
      subtitle: (json["subtitle"] ?? "").toString(),
      occurredAt: _readDateTime(json["occurred_at"]),
      sourceType: (json["source_type"] ?? "").toString(),
      sourceId: (json["source_id"] ?? "").toString(),
    );
  }
}

class CareerSuggestedActionView {
  final String actionType;
  final String label;
  final String promptIntent;
  final String priority;
  final bool enabled;
  final String reason;

  CareerSuggestedActionView({
    required this.actionType,
    required this.label,
    required this.promptIntent,
    required this.priority,
    required this.enabled,
    required this.reason,
  });

  factory CareerSuggestedActionView.fromJson(Map<String, dynamic> json) {
    return CareerSuggestedActionView(
      actionType: (json["action_type"] ?? "").toString(),
      label: (json["label"] ?? "").toString(),
      promptIntent: (json["prompt_intent"] ?? "").toString(),
      priority: (json["priority"] ?? "medium").toString(),
      enabled: json["enabled"] != false,
      reason: (json["reason"] ?? "").toString(),
    );
  }
}

class NoteSourceRefView {
  final String sourceType;
  final String? sourceId;
  final String? sourceSessionId;
  final String title;
  final String quote;

  NoteSourceRefView({
    required this.sourceType,
    required this.sourceId,
    required this.sourceSessionId,
    required this.title,
    required this.quote,
  });

  factory NoteSourceRefView.fromJson(Map<String, dynamic> json) {
    return NoteSourceRefView(
      sourceType: (json["source_type"] ?? "").toString(),
      sourceId: _readOptionalString(json["source_id"]),
      sourceSessionId: _readOptionalString(json["source_session_id"]),
      title: (json["title"] ?? "").toString(),
      quote: (json["quote"] ?? "").toString(),
    );
  }
}

class NoteView {
  final String noteId;
  final String status;
  final String sourceSessionId;
  final String? sourceArtifactId;
  final List<String> evidenceRefs;
  final DateTime createdAt;
  final DateTime updatedAt;
  final String title;
  final String bodyMarkdown;
  final String bodyFormat;
  final String noteType;
  final String? collectionId;
  final List<String> tags;
  final List<NoteSourceRefView> sourceRefs;
  final String? relatedApplicationId;
  final String summary;

  NoteView({
    required this.noteId,
    required this.status,
    required this.sourceSessionId,
    required this.sourceArtifactId,
    required this.evidenceRefs,
    required this.createdAt,
    required this.updatedAt,
    required this.title,
    required this.bodyMarkdown,
    required this.bodyFormat,
    this.noteType = 'note',
    required this.collectionId,
    required this.tags,
    required this.sourceRefs,
    required this.relatedApplicationId,
    required this.summary,
  });

  factory NoteView.fromJson(Map<String, dynamic> json) {
    return NoteView(
      noteId: (json["note_id"] ?? "").toString(),
      status: (json["status"] ?? "active").toString(),
      sourceSessionId: (json["source_session_id"] ?? "").toString(),
      sourceArtifactId: _readOptionalString(json["source_artifact_id"]),
      evidenceRefs: _readStringList(json["evidence_refs"]),
      createdAt: _readDateTime(json["created_at"]),
      updatedAt: _readDateTime(json["updated_at"]),
      title: (json["title"] ?? "").toString(),
      bodyMarkdown: (json["body_markdown"] ?? "").toString(),
      bodyFormat: (json["body_format"] ?? "markdown").toString(),
      noteType: (json["note_type"] ?? "note").toString(),
      collectionId: _readOptionalString(json["collection_id"]),
      tags: _readStringList(json["tags"]),
      sourceRefs: _readList(json["source_refs"])
          .map((item) => NoteSourceRefView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      relatedApplicationId: _readOptionalString(json["related_application_id"]),
      summary: (json["summary"] ?? "").toString(),
    );
  }
}

class CareerNoteSummaryView {
  final String noteId;
  final String title;
  final String summary;
  final String status;
  final DateTime updatedAt;
  final String noteType;
  final String? sourceArtifactId;
  final String? relatedApplicationId;
  final List<String> tags;

  CareerNoteSummaryView({
    required this.noteId,
    required this.title,
    required this.summary,
    required this.status,
    required this.updatedAt,
    this.noteType = 'note',
    required this.sourceArtifactId,
    required this.relatedApplicationId,
    required this.tags,
  });

  factory CareerNoteSummaryView.fromJson(Map<String, dynamic> json) {
    return CareerNoteSummaryView(
      noteId: (json["note_id"] ?? "").toString(),
      title: (json["title"] ?? "").toString(),
      summary: (json["summary"] ?? "").toString(),
      status: (json["status"] ?? "active").toString(),
      updatedAt: _readDateTime(json["updated_at"]),
      noteType: (json["note_type"] ?? "note").toString(),
      sourceArtifactId: _readOptionalString(json["source_artifact_id"]),
      relatedApplicationId: _readOptionalString(json["related_application_id"]),
      tags: _readStringList(json["tags"]),
    );
  }
}

class CareerWorkbenchLearningPlanView {
  final String status;
  final String sourceSessionId;
  final String? sourceArtifactId;
  final String learningPlanId;
  final String title;
  final String description;
  final String planType;
  final String? targetApplicationId;
  final String targetRole;
  final String targetCompany;
  final String priority;
  final List<String> goals;
  final List<String> focusSkillTags;
  final String progressSummary;
  final DateTime updatedAt;

  CareerWorkbenchLearningPlanView({
    required this.status,
    required this.sourceSessionId,
    required this.sourceArtifactId,
    required this.learningPlanId,
    required this.title,
    required this.description,
    required this.planType,
    required this.targetApplicationId,
    required this.targetRole,
    required this.targetCompany,
    required this.priority,
    required this.goals,
    required this.focusSkillTags,
    required this.progressSummary,
    required this.updatedAt,
  });

  factory CareerWorkbenchLearningPlanView.fromJson(
    Map<String, dynamic> json,
  ) {
    return CareerWorkbenchLearningPlanView(
      status: (json["status"] ?? "active").toString(),
      sourceSessionId: (json["source_session_id"] ?? "").toString(),
      sourceArtifactId: _readOptionalString(json["source_artifact_id"]),
      learningPlanId: (json["learning_plan_id"] ?? "").toString(),
      title: (json["title"] ?? "").toString(),
      description: (json["description"] ?? "").toString(),
      planType: (json["plan_type"] ?? "custom").toString(),
      targetApplicationId: _readOptionalString(json["target_application_id"]),
      targetRole: (json["target_role"] ?? "").toString(),
      targetCompany: (json["target_company"] ?? "").toString(),
      priority: (json["priority"] ?? "medium").toString(),
      goals: _readStringList(json["goals"]),
      focusSkillTags: _readStringList(json["focus_skill_tags"]),
      progressSummary: (json["progress_summary"] ?? "").toString(),
      updatedAt: _readDateTime(json["updated_at"]),
    );
  }
}

class CareerWorkbenchLearningTaskView {
  final String status;
  final String sourceSessionId;
  final String? sourceArtifactId;
  final String learningTaskId;
  final String title;
  final String? learningPlanId;
  final String description;
  final String taskType;
  final String priority;
  final String state;
  final List<String> skillTags;
  final int estimatedMinutes;
  final DateTime? dueDate;
  final DateTime? completedAt;
  final List<String> successCriteria;
  final String progressNotes;
  final DateTime updatedAt;

  CareerWorkbenchLearningTaskView({
    required this.status,
    required this.sourceSessionId,
    required this.sourceArtifactId,
    required this.learningTaskId,
    required this.title,
    required this.learningPlanId,
    required this.description,
    required this.taskType,
    required this.priority,
    required this.state,
    required this.skillTags,
    required this.estimatedMinutes,
    required this.dueDate,
    required this.completedAt,
    required this.successCriteria,
    required this.progressNotes,
    required this.updatedAt,
  });

  factory CareerWorkbenchLearningTaskView.fromJson(
    Map<String, dynamic> json,
  ) {
    return CareerWorkbenchLearningTaskView(
      status: (json["status"] ?? "active").toString(),
      sourceSessionId: (json["source_session_id"] ?? "").toString(),
      sourceArtifactId: _readOptionalString(json["source_artifact_id"]),
      learningTaskId: (json["learning_task_id"] ?? "").toString(),
      title: (json["title"] ?? "").toString(),
      learningPlanId: _readOptionalString(json["learning_plan_id"]),
      description: (json["description"] ?? "").toString(),
      taskType: (json["task_type"] ?? "custom").toString(),
      priority: (json["priority"] ?? "medium").toString(),
      state: (json["state"] ?? "todo").toString(),
      skillTags: _readStringList(json["skill_tags"]),
      estimatedMinutes: _readInt(json["estimated_minutes"]),
      dueDate: _readOptionalDateTime(json["due_date"]),
      completedAt: _readOptionalDateTime(json["completed_at"]),
      successCriteria: _readStringList(json["success_criteria"]),
      progressNotes: (json["progress_notes"] ?? "").toString(),
      updatedAt: _readDateTime(json["updated_at"]),
    );
  }
}

class CareerWorkbenchWeaknessView {
  final String status;
  final String sourceSessionId;
  final String? sourceArtifactId;
  final String weaknessId;
  final String title;
  final String description;
  final String weaknessType;
  final String severity;
  final String state;
  final List<String> skillTags;
  final List<String> relatedTaskIds;
  final DateTime updatedAt;

  CareerWorkbenchWeaknessView({
    required this.status,
    required this.sourceSessionId,
    required this.sourceArtifactId,
    required this.weaknessId,
    required this.title,
    required this.description,
    required this.weaknessType,
    required this.severity,
    required this.state,
    required this.skillTags,
    required this.relatedTaskIds,
    required this.updatedAt,
  });

  factory CareerWorkbenchWeaknessView.fromJson(Map<String, dynamic> json) {
    return CareerWorkbenchWeaknessView(
      status: (json["status"] ?? "active").toString(),
      sourceSessionId: (json["source_session_id"] ?? "").toString(),
      sourceArtifactId: _readOptionalString(json["source_artifact_id"]),
      weaknessId: (json["weakness_id"] ?? "").toString(),
      title: (json["title"] ?? "").toString(),
      description: (json["description"] ?? "").toString(),
      weaknessType: (json["weakness_type"] ?? "other").toString(),
      severity: (json["severity"] ?? "medium").toString(),
      state: (json["state"] ?? "open").toString(),
      skillTags: _readStringList(json["skill_tags"]),
      relatedTaskIds: _readStringList(json["related_task_ids"]),
      updatedAt: _readDateTime(json["updated_at"]),
    );
  }
}

class CareerWorkbenchReviewView {
  final String status;
  final String sourceSessionId;
  final String? sourceArtifactId;
  final String reviewScheduleId;
  final String title;
  final String reviewType;
  final String state;
  final DateTime? reviewAt;
  final DateTime? nextReviewAt;
  final String summary;
  final DateTime updatedAt;

  CareerWorkbenchReviewView({
    required this.status,
    required this.sourceSessionId,
    required this.sourceArtifactId,
    required this.reviewScheduleId,
    required this.title,
    required this.reviewType,
    required this.state,
    required this.reviewAt,
    required this.nextReviewAt,
    required this.summary,
    required this.updatedAt,
  });

  factory CareerWorkbenchReviewView.fromJson(Map<String, dynamic> json) {
    return CareerWorkbenchReviewView(
      status: (json["status"] ?? "active").toString(),
      sourceSessionId: (json["source_session_id"] ?? "").toString(),
      sourceArtifactId: _readOptionalString(json["source_artifact_id"]),
      reviewScheduleId: (json["review_schedule_id"] ?? "").toString(),
      title: (json["title"] ?? "").toString(),
      reviewType: (json["review_type"] ?? "custom").toString(),
      state: (json["state"] ?? "scheduled").toString(),
      reviewAt: _readOptionalDateTime(json["review_at"]),
      nextReviewAt: _readOptionalDateTime(json["next_review_at"]),
      summary: (json["summary"] ?? "").toString(),
      updatedAt: _readDateTime(json["updated_at"]),
    );
  }
}

class CareerLearningSummaryView {
  final List<CareerWorkbenchLearningPlanView> plans;
  final List<CareerWorkbenchLearningTaskView> tasks;
  final List<CareerWorkbenchWeaknessView> weaknesses;
  final List<CareerWorkbenchReviewView> reviews;
  final int openTaskCount;
  final int doneTaskCount;
  final int highWeaknessCount;

  CareerLearningSummaryView({
    required this.plans,
    required this.tasks,
    required this.weaknesses,
    required this.reviews,
    required this.openTaskCount,
    required this.doneTaskCount,
    required this.highWeaknessCount,
  });

  factory CareerLearningSummaryView.fromJson(Map<String, dynamic> json) {
    return CareerLearningSummaryView(
      plans: _readList(json["plans"])
          .map((item) => CareerWorkbenchLearningPlanView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      tasks: _readList(json["tasks"])
          .map((item) => CareerWorkbenchLearningTaskView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      weaknesses: _readList(json["weaknesses"])
          .map((item) => CareerWorkbenchWeaknessView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      reviews: _readList(json["reviews"])
          .map((item) => CareerWorkbenchReviewView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      openTaskCount: _readInt(json["open_task_count"]),
      doneTaskCount: _readInt(json["done_task_count"]),
      highWeaknessCount: _readInt(json["high_weakness_count"]),
    );
  }
}

class CareerApplicationSummaryView {
  final CareerApplicationView application;
  final CareerReadinessView readiness;
  final int linkedAssetCount;
  final int noteCount;
  final int learningTaskCount;
  final DateTime updatedAt;

  CareerApplicationSummaryView({
    required this.application,
    required this.readiness,
    required this.linkedAssetCount,
    required this.noteCount,
    required this.learningTaskCount,
    required this.updatedAt,
  });

  factory CareerApplicationSummaryView.fromJson(Map<String, dynamic> json) {
    return CareerApplicationSummaryView(
      application: CareerApplicationView.fromJson(
        Map<String, dynamic>.from(json["application"] ?? const {}),
      ),
      readiness: CareerReadinessView.fromJson(
        Map<String, dynamic>.from(json["readiness"] ?? const {}),
      ),
      linkedAssetCount: _readInt(json["linked_asset_count"]),
      noteCount: _readInt(json["note_count"]),
      learningTaskCount: _readInt(json["learning_task_count"]),
      updatedAt: _readDateTime(json["updated_at"]),
    );
  }
}

class CareerWorkbenchCountsView {
  final int applications;
  final int activeApplications;
  final int notes;
  final int learningTasks;
  final int resumeVersions;

  CareerWorkbenchCountsView({
    required this.applications,
    required this.activeApplications,
    required this.notes,
    required this.learningTasks,
    required this.resumeVersions,
  });

  factory CareerWorkbenchCountsView.fromJson(Map<String, dynamic> json) {
    return CareerWorkbenchCountsView(
      applications: _readInt(json["applications"]),
      activeApplications: _readInt(json["active_applications"]),
      notes: _readInt(json["notes"]),
      learningTasks: _readInt(json["learning_tasks"]),
      resumeVersions: _readInt(json["resume_versions"]),
    );
  }
}

class CareerWorkbenchListView {
  final List<CareerApplicationSummaryView> applications;
  final String? activeApplicationId;
  final CareerWorkbenchCountsView counts;
  final DateTime? updatedAt;

  CareerWorkbenchListView({
    required this.applications,
    required this.activeApplicationId,
    required this.counts,
    required this.updatedAt,
  });

  factory CareerWorkbenchListView.fromJson(Map<String, dynamic> json) {
    return CareerWorkbenchListView(
      applications: _readList(json["applications"])
          .map((item) => CareerApplicationSummaryView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      activeApplicationId: _readOptionalString(json["active_application_id"]),
      counts: CareerWorkbenchCountsView.fromJson(
        Map<String, dynamic>.from(json["counts"] ?? const {}),
      ),
      updatedAt: _readOptionalDateTime(json["updated_at"]),
    );
  }
}

class CareerApplicationWorkbenchView {
  final CareerApplicationView application;
  final ResumeProfileView? resumeProfile;
  final CareerProfileView? careerProfile;
  final JDAnalysisView? jdAnalysis;
  final JobFitReportView? jobFitReport;
  final List<ResumeVersionView> resumeVersions;
  final CareerReadinessView readiness;
  final List<CareerLinkedAssetView> linkedAssets;
  final List<CareerNoteSummaryView> notes;
  final CareerLearningSummaryView learning;
  final List<CareerTimelineItemView> timeline;
  final List<CareerSuggestedActionView> suggestedActions;

  CareerApplicationWorkbenchView({
    required this.application,
    required this.resumeProfile,
    required this.careerProfile,
    required this.jdAnalysis,
    required this.jobFitReport,
    required this.resumeVersions,
    required this.readiness,
    required this.linkedAssets,
    required this.notes,
    required this.learning,
    required this.timeline,
    required this.suggestedActions,
  });

  factory CareerApplicationWorkbenchView.fromJson(Map<String, dynamic> json) {
    return CareerApplicationWorkbenchView(
      application: CareerApplicationView.fromJson(
        Map<String, dynamic>.from(json["application"] ?? const {}),
      ),
      resumeProfile: json["resume_profile"] is Map
          ? ResumeProfileView.fromJson(
              Map<String, dynamic>.from(json["resume_profile"]),
            )
          : null,
      careerProfile: json["career_profile"] is Map
          ? CareerProfileView.fromJson(
              Map<String, dynamic>.from(json["career_profile"]),
            )
          : null,
      jdAnalysis: json["jd_analysis"] is Map
          ? JDAnalysisView.fromJson(
              Map<String, dynamic>.from(json["jd_analysis"]),
            )
          : null,
      jobFitReport: json["job_fit_report"] is Map
          ? JobFitReportView.fromJson(
              Map<String, dynamic>.from(json["job_fit_report"]),
            )
          : null,
      resumeVersions: _readList(json["resume_versions"])
          .map((item) => ResumeVersionView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      readiness: CareerReadinessView.fromJson(
        Map<String, dynamic>.from(json["readiness"] ?? const {}),
      ),
      linkedAssets: _readList(json["linked_assets"])
          .map((item) => CareerLinkedAssetView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      notes: _readList(json["notes"])
          .map((item) => CareerNoteSummaryView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      learning: CareerLearningSummaryView.fromJson(
        Map<String, dynamic>.from(json["learning"] ?? const {}),
      ),
      timeline: _readList(json["timeline"])
          .map((item) => CareerTimelineItemView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
      suggestedActions: _readList(json["suggested_actions"])
          .map((item) => CareerSuggestedActionView.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
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

DateTime? _readOptionalDateTime(dynamic raw) {
  final value = raw?.toString().trim() ?? "";
  if (value.isEmpty) return null;
  return DateTime.tryParse(value);
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
