import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/api_models.dart';
import '../services/api_service.dart';

final apiServiceProvider = Provider<ApiService>((_) => ApiService());

final chatProvider = ChangeNotifierProvider<ChatProvider>((ref) {
  return ChatProvider(ref.read(apiServiceProvider));
});

class ChatProvider extends ChangeNotifier {
  final ApiService _api;

  String? _sessionId;
  final List<ChatMessage> _messages = [];
  bool _isStreaming = false;
  String _streamBuffer = "";
  String? _error;
  final List<SessionMeta> _sessions = [];
  List<String> _activeFileIds = [];
  bool _serverReachable = false;

  // Debug / side panel data
  List<ToolCallView> _lastToolCalls = [];
  List<MemoryView> _lastMemoryHits = [];
  List<EventView> _streamEvents = [];
  List<SessionFileView> _sessionFiles = [];

  // ── Getters ─────────────────────────────────────────────────────────
  String? get sessionId => _sessionId;
  List<ChatMessage> get messages => List.unmodifiable(_messages);
  bool get isStreaming => _isStreaming;
  String get streamBuffer => _streamBuffer;
  String? get error => _error;
  List<SessionMeta> get sessions => List.unmodifiable(_sessions);
  List<String> get activeFileIds => List.unmodifiable(_activeFileIds);
  bool get serverReachable => _serverReachable;
  bool get hasActiveSession => _sessionId != null;
  List<ToolCallView> get lastToolCalls => List.unmodifiable(_lastToolCalls);
  List<MemoryView> get lastMemoryHits => List.unmodifiable(_lastMemoryHits);
  List<EventView> get streamEvents => List.unmodifiable(_streamEvents);
  List<SessionFileView> get sessionFiles => List.unmodifiable(_sessionFiles);

  ChatProvider(this._api) {
    _init();
  }

  Future<void> _init() async {
    await _loadSessions();
    _checkHealth();
    // Also try loading sessions from the backend
    try {
      final remoteSessions = await _api.listSessions();
      if (remoteSessions.isNotEmpty) {
        // Merge: keep local sessions, add remote ones that are missing
        final localIds = _sessions.map((s) => s.id).toSet();
        for (final rs in remoteSessions) {
          if (!localIds.contains(rs.id)) {
            _sessions.add(rs);
          }
        }
        _sessions.sort((a, b) => b.createdAt.compareTo(a.createdAt));
        notifyListeners();
      }
    } catch (_) {}
  }

  Future<void> _checkHealth() async {
    _serverReachable = await _api.checkHealth();
    notifyListeners();
  }

  // ── Session persistence (local) ─────────────────────────────────────

  Future<void> _loadSessions() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString("sessions");
    if (raw != null) {
      try {
        final list = jsonDecode(raw) as List;
        _sessions.clear();
        for (final item in list) {
          _sessions.add(SessionMeta(
            id: item["id"],
            title: item["title"] ?? "新会话",
            createdAt: DateTime.parse(item["created_at"]),
            messageCount: item["message_count"] ?? 0,
          ));
        }
        notifyListeners();
      } catch (_) {}
    }
  }

  Future<void> _saveSessions() async {
    final prefs = await SharedPreferences.getInstance();
    final data = _sessions
        .map((s) => {
              "id": s.id,
              "title": s.title,
              "created_at": s.createdAt.toIso8601String(),
              "message_count": s.messageCount,
            })
        .toList();
    await prefs.setString("sessions", jsonEncode(data));
  }

  void _registerSession(String id, String firstMessage) {
    final existing = _sessions.where((s) => s.id == id).firstOrNull;
    if (existing == null) {
      _sessions.insert(
        0,
        SessionMeta(
          id: id,
          title: firstMessage.length > 30
              ? "${firstMessage.substring(0, 30)}..."
              : firstMessage,
          createdAt: DateTime.now(),
          messageCount: 1,
        ),
      );
    } else {
      final idx = _sessions.indexOf(existing);
      _sessions[idx] = SessionMeta(
        id: existing.id,
        title: existing.title,
        createdAt: existing.createdAt,
        messageCount: existing.messageCount + 2,
      );
    }
    _saveSessions();
  }

  // ── Session management ──────────────────────────────────────────────

  void createNewSession() {
    _sessionId = null;
    _messages.clear();
    _streamBuffer = "";
    _error = null;
    _activeFileIds = [];
    _lastToolCalls = [];
    _lastMemoryHits = [];
    _streamEvents = [];
    _sessionFiles = [];
    notifyListeners();
  }

  Future<void> switchSession(String sessionId) async {
    _sessionId = sessionId;
    _messages.clear();
    _streamBuffer = "";
    _error = null;
    _streamEvents = [];
    notifyListeners();

    // Load messages from backend
    try {
      final msgs = await _api.listSessionMessages(sessionId);
      _messages.addAll(msgs);
      notifyListeners();
    } catch (_) {}

    await refreshSessionFiles();
  }

  Future<void> deleteSession(String sessionId) async {
    try {
      await _api.deleteSession(sessionId);
    } catch (_) {}
    _sessions.removeWhere((s) => s.id == sessionId);
    if (_sessionId == sessionId) {
      _sessionId = null;
      _messages.clear();
    }
    await _saveSessions();
    notifyListeners();
  }

  // ── Chat (streaming) ────────────────────────────────────────────────

  Future<void> sendMessage(String content) async {
    if (content.trim().isEmpty || _isStreaming) return;

    _error = null;
    _lastToolCalls = [];
    _lastMemoryHits = [];
    _streamEvents = [];
    _messages.add(ChatMessage(role: "user", content: content.trim()));
    _isStreaming = true;
    _streamBuffer = "";
    notifyListeners();

    try {
      // Try streaming first
      bool gotEvents = false;
      ChatResponse? doneResponse;

      try {
        await for (final event in _api.chatStream(
          message: content.trim(),
          sessionId: _sessionId,
          activeFileIds: _activeFileIds.isEmpty ? null : _activeFileIds,
        )) {
          gotEvents = true;
          doneResponse = _handleStreamEvent(event);
        }
      } catch (streamErr) {
        // Streaming failed, will fall back below
        print("[CHAT] streaming error, will fallback: $streamErr");
      }

      // If streaming didn't produce events, fall back to non-streaming
      if (!gotEvents) {
        print("[CHAT] no SSE events received, falling back to /api/chat");
        final resp = await _api.chat(
          message: content.trim(),
          sessionId: _sessionId,
          activeFileIds: _activeFileIds.isEmpty ? null : _activeFileIds,
        );
        doneResponse = resp;
      }

      // Apply done response
      if (doneResponse != null) {
        _sessionId = doneResponse.sessionId;
        if (_streamBuffer.isEmpty && doneResponse.answer.isNotEmpty) {
          _streamBuffer = doneResponse.answer;
        }
        _lastToolCalls = doneResponse.toolCalls;
        _lastMemoryHits = doneResponse.memoryHits;
      }

      // Finalize: move stream buffer into a message
      if (_streamBuffer.isNotEmpty) {
        _messages.add(ChatMessage(role: "assistant", content: _streamBuffer));
        _streamBuffer = "";
      }

      // Register session in local list
      if (_sessionId != null) {
        final lastUserMsg =
            _messages.lastWhere((m) => m.isUser, orElse: () => ChatMessage(role: "user", content: ""));
        _registerSession(_sessionId!, lastUserMsg.content);
      }

      // Refresh files after completion
      if (_sessionId != null) {
        await refreshSessionFiles();
      }
    } on ApiException catch (e) {
      _error = e.message;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isStreaming = false;
      notifyListeners();
    }
  }

  /// Returns the ChatResponse from the "done" event, if received.
  ChatResponse? _handleStreamEvent(StreamEvent event) {
    final data = event.dataMap;

    switch (event.event) {
      case "session":
        final sid = data["session_id"]?.toString();
        if (sid != null && sid.isNotEmpty) {
          _sessionId = sid;
        }
        notifyListeners();
        return null;

      case "answer_delta":
        final delta = data["delta"]?.toString() ?? "";
        _streamBuffer += delta;
        notifyListeners();
        return null;

      case "answer_reset":
        _streamBuffer = "";
        notifyListeners();
        return null;

      case "run_event":
        // Store run events for the debug panel
        final eventRecord = EventView(
          eventId: "",
          sessionId: _sessionId ?? "",
          agentId: data["agent_id"] ?? "",
          runId: data["run_id"] ?? "",
          eventVersion: 0,
          type: data["type"] ?? "",
          payload: Map<String, dynamic>.from(data["payload"] ?? {}),
          createdAt: DateTime.tryParse(data["created_at"] ?? "") ?? DateTime.now(),
        );
        _streamEvents.add(eventRecord);
        if (_streamEvents.length > 200) {
          _streamEvents = _streamEvents.sublist(_streamEvents.length - 200);
        }
        notifyListeners();
        return null;

      case "heartbeat":
        // Just keep alive, no action needed
        return null;

      case "done":
        // The done event contains the full ChatResponse
        try {
          return ChatResponse.fromJson(data);
        } catch (_) {
          return null;
        }

      case "error":
        _error = data["detail"]?.toString() ?? "Unknown stream error";
        notifyListeners();
        return null;

      default:
        return null;
    }
  }

  // ── Session files ───────────────────────────────────────────────────

  Future<void> refreshSessionFiles() async {
    if (_sessionId == null) {
      _sessionFiles = [];
      _activeFileIds = [];
      notifyListeners();
      return;
    }
    try {
      final resp = await _api.listSessionFiles(_sessionId!);
      _sessionFiles = resp.files;
      _activeFileIds = resp.activeFileIds;
    } catch (_) {}
    notifyListeners();
  }

  Future<void> toggleFileActive(String fileId, bool active) async {
    if (_sessionId == null) return;
    final current = Set<String>.from(_activeFileIds);
    if (active) {
      current.add(fileId);
    } else {
      current.remove(fileId);
    }
    try {
      final resp =
          await _api.setActiveFiles(sessionId: _sessionId!, fileIds: current.toList());
      _sessionFiles = resp.files;
      _activeFileIds = resp.activeFileIds;
    } catch (_) {}
    notifyListeners();
  }

  // ── Memories ─────────────────────────────────────────────────────────

  Future<List<MemoryView>> fetchMemories({String? q, int limit = 20}) async {
    return _api.listMemories(q: q, limit: limit);
  }

  // ── Events ───────────────────────────────────────────────────────────

  Future<void> refreshEvents() async {
    if (_sessionId == null) {
      _streamEvents = [];
      notifyListeners();
      return;
    }
    try {
      _streamEvents = await _api.listSessionEvents(_sessionId!);
    } catch (_) {}
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
