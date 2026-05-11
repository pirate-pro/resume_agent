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
