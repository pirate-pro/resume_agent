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
    List<String>? activeFileIds,
  }) async {
    final body = <String, dynamic>{
      "message": message,
      "skill_names": skillNames,
      "max_tool_rounds": maxToolRounds,
      "active_file_ids": activeFileIds ?? [],
    };
    if (sessionId != null && sessionId.isNotEmpty) {
      body["session_id"] = sessionId;
    }

    final resp = await http.post(
      _uri(AppConfig.chatEndpoint),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode(body),
    );
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    return ChatResponse.fromJson(jsonDecode(resp.body));
  }

  // ── Chat (streaming / SSE) ────────────────────────────────────────────

  Stream<StreamEvent> chatStream({
    required String message,
    String? sessionId,
    List<String> skillNames = const [],
    int maxToolRounds = AppConfig.maxToolRounds,
    List<String>? activeFileIds,
  }) async* {
    final body = <String, dynamic>{
      "message": message,
      "skill_names": skillNames,
      "max_tool_rounds": maxToolRounds,
      "active_file_ids": activeFileIds ?? [],
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

  Future<bool> checkHealth() async {
    try {
      final resp =
          await http.get(_uri("/health")).timeout(const Duration(seconds: 3));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        return data["status"] == "ok";
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  // ── Memories ──────────────────────────────────────────────────────────

  Future<List<MemoryView>> listMemories({String? q, int limit = 20}) async {
    final params = <String, String>{"limit": limit.toString()};
    if (q != null && q.isNotEmpty) params["q"] = q;
    final uri =
        _uri(AppConfig.memoriesEndpoint).replace(queryParameters: params);
    final resp = await http.get(uri);
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    final list = jsonDecode(resp.body) as List;
    return list.map((e) => MemoryView.fromJson(e)).toList();
  }

  Future<List<SkillOption>> listSkills() async {
    final resp = await http.get(_uri("/api/skills"));
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    final list = jsonDecode(resp.body) as List;
    return list.map((e) => SkillOption.fromJson(e)).toList();
  }

  // ── Session Files ─────────────────────────────────────────────────────

  Future<SessionFilesResponse> listSessionFiles(String sessionId) async {
    final resp = await http.get(_uri("/api/sessions/$sessionId/files"));
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    return SessionFilesResponse.fromJson(jsonDecode(resp.body));
  }

  Future<SessionFileView> uploadFile({
    required String sessionId,
    required String filename,
    required String contentBase64,
    bool autoActivate = true,
  }) async {
    final resp = await http.post(
      _uri("/api/sessions/$sessionId/files/upload"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "filename": filename,
        "content_base64": contentBase64,
        "auto_activate": autoActivate,
      }),
    );
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    return SessionFileView.fromJson(jsonDecode(resp.body));
  }

  Future<SessionFilesResponse> setActiveFiles({
    required String sessionId,
    required List<String> fileIds,
  }) async {
    final resp = await http.post(
      _uri("/api/sessions/$sessionId/active-files"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"file_ids": fileIds}),
    );
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    return SessionFilesResponse.fromJson(jsonDecode(resp.body));
  }

  // ── Session Events ────────────────────────────────────────────────────

  Future<List<EventView>> listSessionEvents(String sessionId) async {
    final resp = await http.get(_uri("/api/sessions/$sessionId/events"));
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    final list = jsonDecode(resp.body) as List;
    return list.map((e) => EventView.fromJson(e)).toList();
  }

  // ── Session Management ────────────────────────────────────────────────

  Future<List<SessionMeta>> listSessions() async {
    final resp = await http.get(_uri("/api/sessions"));
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    final list = jsonDecode(resp.body) as List;
    return list
        .map((e) => SessionMeta(
              id: e["session_id"] ?? "",
              title: e["title"] ?? "",
              createdAt:
                  DateTime.tryParse(e["created_at"] ?? "") ?? DateTime.now(),
              updatedAt: DateTime.tryParse(e["updated_at"] ?? "") ??
                  DateTime.tryParse(e["created_at"] ?? "") ??
                  DateTime.now(),
              messageCount: 0,
            ))
        .toList();
  }

  Future<List<ChatMessage>> listSessionMessages(String sessionId) async {
    final resp = await http.get(_uri("/api/sessions/$sessionId/messages"));
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    final list = jsonDecode(resp.body) as List;
    return list
        .map((e) => ChatMessage(
              role: e["role"] ?? "assistant",
              content: e["content"] ?? "",
            ))
        .toList();
  }

  Future<void> deleteSession(String sessionId) async {
    final resp = await http.delete(_uri("/api/sessions/$sessionId"));
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
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
    } catch (_) {}
    return body;
  }

  @override
  String toString() => "API Error $statusCode: $message";
}
