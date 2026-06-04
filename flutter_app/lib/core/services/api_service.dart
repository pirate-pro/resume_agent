import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../constants/app_config.dart';
import '../models/api_models.dart';

class ApiService {
  String _baseUrl;

  ApiService({String? baseUrl})
      : _baseUrl = baseUrl ?? AppConfig.defaultBaseUrl;

  void updateBaseUrl(String url) {
    _baseUrl = url;
  }

  Uri _uri(String path) => Uri.parse("$_baseUrl$path");

  // ── Chat (non-streaming fallback) ─────────────────────────────────────

  Future<ChatResponse> chat({
    required String message,
    String? sessionId,
    List<String> skillNames = const [],
    int maxToolRounds = AppConfig.maxToolRounds,
    List<String>? activeArtifactIds,
  }) async {
    final body = <String, dynamic>{
      "message": message,
      "skill_names": skillNames,
      "max_tool_rounds": maxToolRounds,
      "active_artifact_ids": activeArtifactIds ?? [],
    };
    if (sessionId != null && sessionId.isNotEmpty) {
      body["session_id"] = sessionId;
    }

    final resp = await http.post(
      _uri(AppConfig.chatEndpoint),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    return ChatResponse.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  // ── Chat (streaming / SSE) ────────────────────────────────────────────

  Stream<StreamEvent> chatStream({
    required String message,
    String? sessionId,
    List<String> skillNames = const [],
    int maxToolRounds = AppConfig.maxToolRounds,
    List<String>? activeArtifactIds,
  }) async* {
    final body = <String, dynamic>{
      "message": message,
      "skill_names": skillNames,
      "max_tool_rounds": maxToolRounds,
      "active_artifact_ids": activeArtifactIds ?? [],
    };
    if (sessionId != null && sessionId.isNotEmpty) {
      body["session_id"] = sessionId;
    }

    final request = http.Request("POST", _uri(AppConfig.chatStreamEndpoint));
    request.headers["Content-Type"] = "application/json";
    request.headers["Accept"] = "text/event-stream";
    request.body = jsonEncode(body);

    final streamedResp = await http.Client().send(request);
    if (streamedResp.statusCode != 200) {
      final errBody = await streamedResp.stream.bytesToString();
      throw ApiException(streamedResp.statusCode, errBody);
    }

    String buffer = "";
    await for (final chunk in streamedResp.stream.transform(utf8.decoder)) {
      buffer += chunk.replaceAll("\r\n", "\n").replaceAll("\r", "\n");
      while (buffer.contains("\n\n")) {
        final idx = buffer.indexOf("\n\n");
        final raw = buffer.substring(0, idx);
        buffer = buffer.substring(idx + 2);
        if (raw.trim().isEmpty) continue;
        final parsed = _parseSse(raw);
        if (parsed != null) yield parsed;
      }
    }
    if (buffer.trim().isNotEmpty) {
      final parsed = _parseSse("$buffer\n\n");
      if (parsed != null) yield parsed;
    }
  }

  StreamEvent? _parseSse(String raw) {
    String event = "message";
    final dataLines = <String>[];
    for (final line in raw.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.substring(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.add(line.substring(5).trimLeft());
      }
    }
    if (dataLines.isEmpty) return null;
    final dataStr = dataLines.join("\n");
    dynamic decoded;
    try {
      decoded = jsonDecode(dataStr);
    } catch (_) {
      decoded = dataStr;
    }
    return StreamEvent(event: event, data: decoded);
  }

  // ── Health ────────────────────────────────────────────────────────────

  Future<HealthView?> fetchHealth() async {
    try {
      final resp =
          await http.get(_uri("/health")).timeout(const Duration(seconds: 3));
      if (resp.statusCode != 200) {
        return null;
      }
      final data = _decodeResponseData(resp);
      if (data is! Map<String, dynamic>) {
        return null;
      }
      return HealthView.fromJson(data);
    } catch (_) {
      return null;
    }
  }

  Future<bool> checkHealth() async {
    final health = await fetchHealth();
    return health?.isOnline == true;
  }

  // ── Debug / management telemetry ─────────────────────────────────────

  Future<TokenUsageSummaryView?> fetchTokenUsageSummary({
    int sessionLimit = 8,
    int callLimit = 8,
    int bucketLimit = 6,
  }) async {
    try {
      final uri = _uri("/api/debug/token-usage/summary").replace(
        queryParameters: {
          "session_limit": sessionLimit.toString(),
          "call_limit": callLimit.toString(),
          "bucket_limit": bucketLimit.toString(),
        },
      );
      final resp = await http.get(uri).timeout(const Duration(seconds: 4));
      final data = _decodeResponseData(resp);
      if (data is! Map) {
        return null;
      }
      return TokenUsageSummaryView.fromJson(Map<String, dynamic>.from(data));
    } catch (_) {
      return null;
    }
  }

  // ── Memories ──────────────────────────────────────────────────────────

  Future<List<MemoryView>> listMemories({String? q, int limit = 20}) async {
    final params = <String, String>{"limit": limit.toString()};
    if (q != null && q.isNotEmpty) params["q"] = q;
    final uri = _uri(
      AppConfig.memoriesEndpoint,
    ).replace(queryParameters: params);
    final resp = await http.get(uri);
    final list = _decodeResponseData(resp) as List;
    return list.map((e) => MemoryView.fromJson(e)).toList();
  }

  Future<List<SkillOption>> listSkills() async {
    final resp = await http.get(_uri("/api/skills"));
    final list = _decodeResponseData(resp) as List;
    return list.map((e) => SkillOption.fromJson(e)).toList();
  }

  // ── Learning records ─────────────────────────────────────────────────

  Future<CareerWorkbenchLearningTaskView> createLearningTask({
    required String sourceSessionId,
    required String title,
    String description = "",
    String taskType = "custom",
    String priority = "medium",
    String state = "todo",
    int estimatedMinutes = 0,
    List<String> evidenceRefs = const [],
    List<String> skillTags = const [],
    List<String> successCriteria = const [],
    String progressNotes = "",
  }) async {
    final resp = await http.post(
      _uri("/api/learning-admin/tasks"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "source_session_id": sourceSessionId,
        "evidence_refs": evidenceRefs,
        "title": title,
        "description": description,
        "task_type": taskType,
        "priority": priority,
        "state": state,
        "skill_tags": skillTags,
        "estimated_minutes": estimatedMinutes,
        "success_criteria": successCriteria,
        "progress_notes": progressNotes,
      }),
    );
    return CareerWorkbenchLearningTaskView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<List<LearningTaskDraftView>> generateLearningTaskDrafts({
    required String applicationId,
    int maxDrafts = 3,
    String focus = "general",
    bool excludeExisting = true,
  }) async {
    final resp = await http.post(
      _uri("/api/learning-admin/task-drafts/generate"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "application_id": applicationId,
        "max_drafts": maxDrafts,
        "focus": focus,
        "exclude_existing": excludeExisting,
      }),
    );
    final data = Map<String, dynamic>.from(_decodeResponseData(resp));
    return LearningTaskDraftGenerateResponse.fromJson(data).drafts;
  }

  Future<Map<String, dynamic>> createLearningCheckin({
    required String sourceSessionId,
    required String learningTaskId,
    String? learningPlanId,
    int minutesSpent = 0,
    String progressState = "in_progress",
    String summary = "",
    List<String> blockers = const [],
    String nextAction = "",
    List<String> evidenceRefs = const [],
  }) async {
    final resp = await http.post(
      _uri("/api/learning-admin/checkins"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "source_session_id": sourceSessionId,
        "evidence_refs": evidenceRefs,
        "learning_plan_id": learningPlanId,
        "learning_task_id": learningTaskId,
        "minutes_spent": minutesSpent,
        "progress_state": progressState,
        "summary": summary,
        "blockers": blockers,
        "next_action": nextAction,
      }),
    );
    return Map<String, dynamic>.from(_decodeResponseData(resp));
  }

  Future<CareerWorkbenchLearningTaskView> updateLearningTaskState({
    required String learningTaskId,
    required String state,
    DateTime? completedAt,
  }) async {
    final body = <String, dynamic>{"state": state};
    if (completedAt != null) {
      body["completed_at"] = completedAt.toIso8601String();
    }
    final resp = await http.post(
      _uri(
          "/api/learning-admin/tasks/${Uri.encodeComponent(learningTaskId)}/state"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    return CareerWorkbenchLearningTaskView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<CareerWorkbenchLearningTaskView> archiveLearningTask({
    required String learningTaskId,
  }) async {
    final resp = await http.post(
      _uri(
          "/api/learning-admin/tasks/${Uri.encodeComponent(learningTaskId)}/archive"),
      headers: {"Content-Type": "application/json"},
    );
    return CareerWorkbenchLearningTaskView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<CareerWorkbenchReviewView> updateLearningReviewSchedule({
    required String reviewScheduleId,
    String? state,
    DateTime? lastReviewedAt,
    DateTime? nextReviewAt,
    String? summary,
  }) async {
    final body = <String, dynamic>{};
    if (state != null) body["state"] = state;
    if (lastReviewedAt != null) {
      body["last_reviewed_at"] = lastReviewedAt.toIso8601String();
    }
    if (nextReviewAt != null) {
      body["next_review_at"] = nextReviewAt.toIso8601String();
    }
    if (summary != null) body["summary"] = summary;

    final resp = await http.patch(
      _uri(
        "/api/learning-admin/reviews/${Uri.encodeComponent(reviewScheduleId)}",
      ),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    return CareerWorkbenchReviewView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  // ── Session Artifacts ─────────────────────────────────────────────────────

  Future<SessionArtifactsResponse> listSessionArtifacts(
      String sessionId) async {
    final resp = await http.get(_uri("/api/sessions/$sessionId/artifacts"));
    return SessionArtifactsResponse.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<SessionArtifactView> uploadArtifact({
    required String sessionId,
    required String filename,
    required String contentBase64,
    bool autoActivate = true,
  }) async {
    final resp = await http.post(
      _uri("/api/sessions/$sessionId/artifacts/upload"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "filename": filename,
        "content_base64": contentBase64,
        "auto_activate": autoActivate,
      }),
    );
    return SessionArtifactView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<SessionArtifactsResponse> setActiveArtifacts({
    required String sessionId,
    required List<String> artifactIds,
  }) async {
    final resp = await http.post(
      _uri("/api/sessions/$sessionId/active-artifacts"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"artifact_ids": artifactIds}),
    );
    return SessionArtifactsResponse.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<WorkspaceFilePreview> previewWorkspaceFile({
    required String sessionId,
    required String path,
    int maxChars = 12000,
  }) async {
    final uri =
        _uri("/api/sessions/$sessionId/workspace-files/preview").replace(
      queryParameters: {
        "path": path,
        "max_chars": maxChars.toString(),
      },
    );
    final resp = await http.get(uri);
    return WorkspaceFilePreview.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<SessionArtifactContentView> readSessionArtifactContent({
    required String sessionId,
    required String artifactId,
    int offset = 0,
    int maxChars = 12000,
  }) async {
    final uri = _uri(
      "/api/sessions/${Uri.encodeComponent(sessionId)}/artifacts/"
      "${Uri.encodeComponent(artifactId)}/content",
    ).replace(
      queryParameters: {
        "offset": offset.toString(),
        "max_chars": maxChars.toString(),
      },
    );
    final resp = await http.get(uri);
    return SessionArtifactContentView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  String sessionArtifactDownloadUrl({
    required String sessionId,
    required String artifactId,
  }) {
    return _uri(
      "/api/sessions/${Uri.encodeComponent(sessionId)}/artifacts/"
      "${Uri.encodeComponent(artifactId)}/download",
    ).toString();
  }

  // ── Career Product Assets ─────────────────────────────────────────────

  Future<List<ResumeProfileView>> listCareerResumeProfiles({
    bool includeArchived = false,
  }) async {
    final resp = await http.get(_careerUri("/resumes", includeArchived));
    final list = _decodeResponseData(resp) as List;
    return list
        .map((e) => ResumeProfileView.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  Future<List<CareerProfileView>> listCareerProfiles({
    bool includeArchived = false,
  }) async {
    final resp = await http.get(_careerUri("/profiles", includeArchived));
    final list = _decodeResponseData(resp) as List;
    return list
        .map((e) => CareerProfileView.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  Future<List<JDAnalysisView>> listCareerJobs({
    bool includeArchived = false,
  }) async {
    final resp = await http.get(_careerUri("/jobs", includeArchived));
    final list = _decodeResponseData(resp) as List;
    return list
        .map((e) => JDAnalysisView.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  Future<List<JobFitReportView>> listCareerJobFitReports({
    bool includeArchived = false,
  }) async {
    final resp =
        await http.get(_careerUri("/job-fit-reports", includeArchived));
    final list = _decodeResponseData(resp) as List;
    return list
        .map((e) => JobFitReportView.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  Future<List<ResumeVersionView>> listCareerResumeVersions({
    bool includeArchived = false,
  }) async {
    final resp =
        await http.get(_careerUri("/resume-versions", includeArchived));
    final list = _decodeResponseData(resp) as List;
    return list
        .map((e) => ResumeVersionView.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  Future<ResumeVersionDraftGenerateResponse> generateResumeVersionDraft({
    String? applicationId,
    String? resumeProfileId,
    String? baseResumeVersionId,
    String? targetJdAnalysisId,
    String? jobFitReportId,
    String? title,
    List<String> strategy = const [],
  }) async {
    final body = <String, dynamic>{
      "strategy": strategy,
    };
    if (applicationId != null && applicationId.trim().isNotEmpty) {
      body["application_id"] = applicationId.trim();
    }
    if (resumeProfileId != null && resumeProfileId.trim().isNotEmpty) {
      body["resume_profile_id"] = resumeProfileId.trim();
    }
    if (baseResumeVersionId != null && baseResumeVersionId.trim().isNotEmpty) {
      body["base_resume_version_id"] = baseResumeVersionId.trim();
    }
    if (targetJdAnalysisId != null && targetJdAnalysisId.trim().isNotEmpty) {
      body["target_jd_analysis_id"] = targetJdAnalysisId.trim();
    }
    if (jobFitReportId != null && jobFitReportId.trim().isNotEmpty) {
      body["job_fit_report_id"] = jobFitReportId.trim();
    }
    if (title != null && title.trim().isNotEmpty) {
      body["title"] = title.trim();
    }
    final resp = await http.post(
      _uri("/api/career/resume-version-drafts/generate"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    return ResumeVersionDraftGenerateResponse.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<ResumeVersionDraftAcceptResponse> acceptResumeVersionDraft({
    required String resumeVersionDraftId,
    String? title,
    String? markdown,
    bool linkApplication = true,
  }) async {
    final body = <String, dynamic>{"link_application": linkApplication};
    if (title != null && title.trim().isNotEmpty) {
      body["title"] = title.trim();
    }
    if (markdown != null && markdown.trim().isNotEmpty) {
      body["markdown"] = markdown.trim();
    }
    final resp = await http.post(
      _uri(
        "/api/career/resume-version-drafts/"
        "${Uri.encodeComponent(resumeVersionDraftId)}/accept",
      ),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    return ResumeVersionDraftAcceptResponse.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<List<CareerApplicationView>> listCareerApplications({
    bool includeArchived = false,
  }) async {
    final resp = await http.get(_careerUri("/applications", includeArchived));
    final list = _decodeResponseData(resp) as List;
    return list
        .map(
            (e) => CareerApplicationView.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  Future<CareerWorkbenchListView> getCareerWorkbench({
    bool includeArchived = false,
  }) async {
    final resp = await http.get(
      _uri("/api/career/workbench").replace(
        queryParameters: {"include_archived": includeArchived.toString()},
      ),
    );
    return CareerWorkbenchListView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<CareerApplicationWorkbenchView> getCareerApplicationWorkbench({
    required String applicationId,
    bool includeArchived = false,
  }) async {
    final resp = await http.get(
      _uri(
        "/api/career/workbench/applications/"
        "${Uri.encodeComponent(applicationId)}",
      ).replace(
        queryParameters: {"include_archived": includeArchived.toString()},
      ),
    );
    return CareerApplicationWorkbenchView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<CareerApplicationView> updateCareerApplication({
    required String applicationId,
    String? stage,
    String? priority,
    String? summary,
    List<String>? nextActions,
    List<String>? risks,
    String? notes,
    List<String> evidenceRefs = const [],
    String? sourceArtifactId,
  }) async {
    final body = <String, dynamic>{};
    if (stage != null) body["stage"] = stage;
    if (priority != null) body["priority"] = priority;
    if (summary != null) body["summary"] = summary;
    if (nextActions != null) body["next_actions"] = nextActions;
    if (risks != null) body["risks"] = risks;
    if (notes != null) body["notes"] = notes;
    if (evidenceRefs.isNotEmpty) body["evidence_refs"] = evidenceRefs;
    if (sourceArtifactId != null && sourceArtifactId.trim().isNotEmpty) {
      body["source_artifact_id"] = sourceArtifactId.trim();
    }
    final resp = await http.patch(
      _uri("/api/career/applications/${Uri.encodeComponent(applicationId)}"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    return CareerApplicationView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  // ── Notes ─────────────────────────────────────────────────────────────

  Future<List<NoteView>> listNotes({
    bool includeArchived = false,
    String? collectionId,
    String? relatedApplicationId,
  }) async {
    final params = <String, String>{
      "include_archived": includeArchived.toString(),
    };
    if (collectionId != null && collectionId.trim().isNotEmpty) {
      params["collection_id"] = collectionId.trim();
    }
    if (relatedApplicationId != null &&
        relatedApplicationId.trim().isNotEmpty) {
      params["related_application_id"] = relatedApplicationId.trim();
    }
    final resp = await http.get(
      _uri("/api/notes").replace(queryParameters: params),
    );
    final list = _decodeResponseData(resp) as List;
    return list
        .map((item) => NoteView.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<NoteView> createNote({
    String? noteId,
    required String sourceSessionId,
    String? sourceArtifactId,
    List<String> evidenceRefs = const [],
    required String title,
    required String bodyMarkdown,
    String bodyFormat = "markdown",
    String noteType = "note",
    String origin = "user",
    String? collectionId,
    List<String> tags = const [],
    List<Map<String, dynamic>> sourceRefs = const [],
    String? relatedApplicationId,
    String summary = "",
  }) async {
    final body = <String, dynamic>{
      "source_session_id": sourceSessionId,
      "evidence_refs": evidenceRefs,
      "title": title,
      "body_markdown": bodyMarkdown,
      "body_format": bodyFormat,
      "note_type": noteType,
      "origin": origin,
      "tags": tags,
      "source_refs": sourceRefs,
      "summary": summary,
    };
    if (noteId != null && noteId.trim().isNotEmpty) {
      body["note_id"] = noteId.trim();
    }
    if (sourceArtifactId != null && sourceArtifactId.trim().isNotEmpty) {
      body["source_artifact_id"] = sourceArtifactId.trim();
    }
    if (collectionId != null && collectionId.trim().isNotEmpty) {
      body["collection_id"] = collectionId.trim();
    }
    if (relatedApplicationId != null &&
        relatedApplicationId.trim().isNotEmpty) {
      body["related_application_id"] = relatedApplicationId.trim();
    }
    final resp = await http.post(
      _uri("/api/notes"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    return NoteView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<NoteView> getNote({
    required String noteId,
    bool includeArchived = false,
  }) async {
    final resp = await http.get(
      _uri("/api/notes/${Uri.encodeComponent(noteId)}").replace(
        queryParameters: {"include_archived": includeArchived.toString()},
      ),
    );
    return NoteView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<NoteView> updateNote({
    required String noteId,
    String? title,
    String? bodyMarkdown,
    String? bodyFormat,
    String? noteType,
    String? summary,
    List<String>? tags,
    String? collectionId,
    String? relatedApplicationId,
  }) async {
    final body = <String, dynamic>{};
    if (title != null) body["title"] = title;
    if (bodyMarkdown != null) body["body_markdown"] = bodyMarkdown;
    if (bodyFormat != null) body["body_format"] = bodyFormat;
    if (noteType != null) body["note_type"] = noteType;
    if (summary != null) body["summary"] = summary;
    if (tags != null) body["tags"] = tags;
    if (collectionId != null) body["collection_id"] = collectionId;
    if (relatedApplicationId != null) {
      body["related_application_id"] = relatedApplicationId;
    }
    final resp = await http.patch(
      _uri("/api/notes/${Uri.encodeComponent(noteId)}"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    return NoteView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<NoteView> appendNote({
    required String noteId,
    required String bodyMarkdown,
    List<String> evidenceRefs = const [],
    List<Map<String, dynamic>> sourceRefs = const [],
  }) async {
    final resp = await http.post(
      _uri("/api/notes/${Uri.encodeComponent(noteId)}/append"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "body_markdown": bodyMarkdown,
        "evidence_refs": evidenceRefs,
        "source_refs": sourceRefs,
      }),
    );
    return NoteView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Future<NoteView> archiveNote({
    required String noteId,
  }) async {
    final resp = await http.post(
      _uri("/api/notes/${Uri.encodeComponent(noteId)}/archive"),
      headers: {"Content-Type": "application/json"},
    );
    return NoteView.fromJson(
      Map<String, dynamic>.from(_decodeResponseData(resp)),
    );
  }

  Uri _careerUri(String path, bool includeArchived) {
    return _uri("/api/career$path").replace(
      queryParameters: {"include_archived": includeArchived.toString()},
    );
  }

  // ── Session Events ────────────────────────────────────────────────────

  Future<List<EventView>> listSessionEvents(String sessionId) async {
    final resp = await http.get(_uri("/api/sessions/$sessionId/events"));
    final list = _decodeResponseData(resp) as List;
    return list.map((e) => EventView.fromJson(e)).toList();
  }

  // ── Session Management ────────────────────────────────────────────────

  Future<List<SessionMeta>> listSessions() async {
    final resp = await http.get(_uri("/api/sessions"));
    final list = _decodeResponseData(resp) as List;
    return list
        .map(
          (e) => SessionMeta(
            id: e["session_id"] ?? "",
            title: e["title"] ?? "",
            createdAt:
                DateTime.tryParse(e["created_at"] ?? "") ?? DateTime.now(),
            updatedAt: DateTime.tryParse(e["updated_at"] ?? "") ??
                DateTime.tryParse(e["created_at"] ?? "") ??
                DateTime.now(),
            isPinned: e["is_pinned"] == true,
            pinnedAt: DateTime.tryParse((e["pinned_at"] ?? "").toString()),
            messageCount: 0,
          ),
        )
        .toList();
  }

  Future<SessionMeta> updateSession({
    required String sessionId,
    String? title,
    bool? isPinned,
  }) async {
    final body = <String, dynamic>{};
    if (title != null) body["title"] = title;
    if (isPinned != null) body["is_pinned"] = isPinned;
    final resp = await http.patch(
      _uri("/api/sessions/$sessionId"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    final data = Map<String, dynamic>.from(_decodeResponseData(resp));
    return SessionMeta(
      id: data["session_id"] ?? "",
      title: data["title"] ?? "",
      createdAt: DateTime.tryParse(data["created_at"] ?? "") ?? DateTime.now(),
      updatedAt: DateTime.tryParse(data["updated_at"] ?? "") ??
          DateTime.tryParse(data["created_at"] ?? "") ??
          DateTime.now(),
      isPinned: data["is_pinned"] == true,
      pinnedAt: DateTime.tryParse((data["pinned_at"] ?? "").toString()),
      messageCount: 0,
    );
  }

  Future<List<ChatMessage>> listSessionMessages(String sessionId) async {
    final resp = await http.get(_uri("/api/sessions/$sessionId/messages"));
    final list = _decodeResponseData(resp) as List;
    return list
        .map(
          (e) => ChatMessage(
            role: e["role"] ?? "assistant",
            content: e["content"] ?? "",
            answerFormat: e["answer_format"] ?? "plain_text",
            renderHint: e["render_hint"] ?? "plain",
            layoutHint: e["layout_hint"] ?? "paragraph",
            sourceKind: e["source_kind"] ?? "direct_answer",
            presentationKind: e["presentation_kind"] ?? "chat_text",
            artifacts: (e["artifacts"] as List?)
                    ?.map((item) => AnswerArtifactView.fromJson(
                        Map<String, dynamic>.from(item)))
                    .toList() ??
                const [],
            toolCalls: (e["tool_calls"] as List?)
                    ?.map((item) =>
                        ToolCallView.fromJson(Map<String, dynamic>.from(item)))
                    .toList() ??
                const [],
            timestamp: DateTime.tryParse((e["created_at"] ?? "").toString()) ??
                DateTime.now(),
          ),
        )
        .toList();
  }

  Future<void> deleteSession(String sessionId) async {
    final resp = await http.delete(_uri("/api/sessions/$sessionId"));
    _decodeResponseData(resp);
  }

  dynamic _decodeResponseData(http.Response resp) {
    if (resp.statusCode != 200) {
      throw ApiException(resp.statusCode, resp.body);
    }
    final decoded = jsonDecode(resp.body);
    if (decoded is Map) {
      final map = Map<String, dynamic>.from(decoded);
      if (map.containsKey("code") &&
          map.containsKey("msg") &&
          map.containsKey("data")) {
        final rawCode = map["code"];
        final code = rawCode is int
            ? rawCode
            : rawCode is num
                ? rawCode.toInt()
                : int.tryParse(rawCode.toString()) ?? -1;
        if (code != 0) {
          throw ApiException(code, resp.body);
        }
        return map["data"];
      }
    }
    return decoded;
  }
}

// ── SSE event wrapper ───────────────────────────────────────────────────

class StreamEvent {
  final String event;
  final dynamic data;

  StreamEvent({required this.event, required this.data});

  Map<String, dynamic> get dataMap {
    if (data is Map) return Map<String, dynamic>.from(data);
    return {};
  }
}

// ── Error type ──────────────────────────────────────────────────────────

class ApiException implements Exception {
  final int statusCode;
  final String body;

  ApiException(this.statusCode, this.body);

  String get message {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map && decoded.containsKey("detail")) {
        return decoded["detail"].toString();
      }
      if (decoded is Map && decoded.containsKey("msg")) {
        return decoded["msg"].toString();
      }
    } catch (_) {}
    return body;
  }

  @override
  String toString() => "API Error $statusCode: $message";
}
