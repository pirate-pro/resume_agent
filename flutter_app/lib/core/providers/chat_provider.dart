import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../constants/app_config.dart';
import '../models/api_models.dart';
import '../services/api_service.dart';

final apiServiceProvider = Provider<ApiService>((_) => ApiService());

final chatProvider = ChangeNotifierProvider<ChatProvider>((ref) {
  return ChatProvider(ref.read(apiServiceProvider));
});

class ChatProvider extends ChangeNotifier {
  static const _uuid = Uuid();
  static const _streamFlushInterval = Duration(milliseconds: 48);

  final ApiService _api;

  String? _sessionId;
  final List<ChatMessage> _messages = [];
  bool _isStreaming = false;
  bool _isUploadingFile = false;
  bool _isLoadingSkills = false;
  String _streamBuffer = "";
  String _pendingStreamDelta = "";
  Timer? _streamFlushTimer;
  String? _error;
  String? _skillsError;
  final List<SessionMeta> _sessions = [];
  List<String> _activeFileIds = [];
  List<SkillOption> _availableSkills = [];
  List<String> _selectedSkillNames = [];
  int _maxToolRounds = AppConfig.maxToolRounds;
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
  bool get isUploadingFile => _isUploadingFile;
  bool get isLoadingSkills => _isLoadingSkills;
  String get streamBuffer => _streamBuffer;
  String? get error => _error;
  String? get skillsError => _skillsError;
  List<SessionMeta> get sessions => List.unmodifiable(_sessions);
  List<String> get activeFileIds => List.unmodifiable(_activeFileIds);
  List<SkillOption> get availableSkills => List.unmodifiable(_availableSkills);
  List<String> get selectedSkillNames => List.unmodifiable(_selectedSkillNames);
  int get maxToolRounds => _maxToolRounds;
  bool get serverReachable => _serverReachable;
  bool get hasActiveSession => _sessionId != null;
  List<ToolCallView> get lastToolCalls => List.unmodifiable(_lastToolCalls);
  List<MemoryView> get lastMemoryHits => List.unmodifiable(_lastMemoryHits);
  List<EventView> get streamEvents => List.unmodifiable(_streamEvents);
  List<SessionFileView> get sessionFiles => List.unmodifiable(_sessionFiles);

  ChatProvider(this._api) {
    _init();
  }

  @override
  void dispose() {
    _streamFlushTimer?.cancel();
    super.dispose();
  }

  Future<void> _init() async {
    await _loadSessions();
    _checkHealth();
    unawaited(refreshSkills());
    await refreshSessions();
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
          _sessions.add(
            SessionMeta(
              id: item["id"],
              title: item["title"] ?? "新会话",
              createdAt: DateTime.parse(item["created_at"]),
              updatedAt: DateTime.tryParse(item["updated_at"] ?? "") ??
                  DateTime.parse(item["created_at"]),
              isPinned: item["is_pinned"] == true,
              pinnedAt: DateTime.tryParse((item["pinned_at"] ?? "").toString()),
              messageCount: item["message_count"] ?? 0,
            ),
          );
        }
        _sortSessions();
        notifyListeners();
      } catch (_) {}
    }
  }

  Future<void> _saveSessions() async {
    final prefs = await SharedPreferences.getInstance();
    final data = _sessions
        .map(
          (s) => {
            "id": s.id,
            "title": s.title,
            "created_at": s.createdAt.toIso8601String(),
            "updated_at": s.updatedAt.toIso8601String(),
            "is_pinned": s.isPinned,
            "pinned_at": s.pinnedAt?.toIso8601String(),
            "message_count": s.messageCount,
          },
        )
        .toList();
    await prefs.setString("sessions", jsonEncode(data));
  }

  void _registerSession(String id, String firstMessage) {
    final existing = _sessions.where((s) => s.id == id).firstOrNull;
    final nextTitle = _buildSessionTitle(firstMessage);
    if (existing == null) {
      _sessions.insert(
        0,
        SessionMeta(
          id: id,
          title: nextTitle,
          createdAt: DateTime.now(),
          updatedAt: DateTime.now(),
          isPinned: false,
          pinnedAt: null,
          messageCount: 1,
        ),
      );
    } else {
      final shouldReplaceTitle = existing.messageCount == 0 ||
          existing.title == "新会话" ||
          existing.title.startsWith("文件:");
      final idx = _sessions.indexOf(existing);
      _sessions[idx] = SessionMeta(
        id: existing.id,
        title: shouldReplaceTitle ? nextTitle : existing.title,
        createdAt: existing.createdAt,
        updatedAt: DateTime.now(),
        isPinned: existing.isPinned,
        pinnedAt: existing.pinnedAt,
        messageCount: existing.messageCount + 2,
      );
    }
    _sortSessions();
    _saveSessions();
  }

  String _buildSessionTitle(String value) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) return "新会话";
    return trimmed.length > 30 ? "${trimmed.substring(0, 30)}..." : trimmed;
  }

  String _generateSessionId() {
    final raw = _uuid.v4().replaceAll("-", "");
    return "sess_${raw.substring(0, 12)}";
  }

  Future<void> _ensureSessionPlaceholder(String sessionId, String title) async {
    final existing = _sessions.where((s) => s.id == sessionId).firstOrNull;
    if (existing != null) return;
    _sessions.insert(
      0,
      SessionMeta(
        id: sessionId,
        title: title,
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
        isPinned: false,
        pinnedAt: null,
        messageCount: 0,
      ),
    );
    _sortSessions();
    await _saveSessions();
  }

  Future<void> _discardPlaceholderSession(String sessionId) async {
    _sessions.removeWhere((s) => s.id == sessionId);
    if (_sessionId == sessionId) {
      _sessionId = null;
      _sessionFiles = [];
      _activeFileIds = [];
    }
    await _saveSessions();
  }

  Future<void> refreshSessions() async {
    try {
      final remoteSessions = await _api.listSessions();
      if (remoteSessions.isEmpty) {
        return;
      }
      final merged = <String, SessionMeta>{};
      for (final session in _sessions) {
        merged[session.id] = session;
      }
      for (final session in remoteSessions) {
        final existing = merged[session.id];
        merged[session.id] = SessionMeta(
          id: session.id,
          title: session.title.isNotEmpty
              ? session.title
              : (existing?.title ?? "新会话"),
          createdAt: session.createdAt,
          updatedAt: session.updatedAt,
          isPinned: session.isPinned,
          pinnedAt: session.pinnedAt,
          messageCount: existing?.messageCount ?? session.messageCount,
        );
      }
      _sessions
        ..clear()
        ..addAll(merged.values);
      _sortSessions();
      await _saveSessions();
      notifyListeners();
    } catch (_) {}
  }

  void _sortSessions() {
    _sessions.sort((left, right) {
      final pinCompare = (right.isPinned ? 1 : 0).compareTo(
        left.isPinned ? 1 : 0,
      );
      if (pinCompare != 0) return pinCompare;
      final leftPinTime = left.pinnedAt ?? left.updatedAt;
      final rightPinTime = right.pinnedAt ?? right.updatedAt;
      final pinnedTimeCompare = rightPinTime.compareTo(leftPinTime);
      if (pinnedTimeCompare != 0) return pinnedTimeCompare;
      return right.updatedAt.compareTo(left.updatedAt);
    });
  }

  // ── Session management ──────────────────────────────────────────────

  void createNewSession() {
    _sessionId = null;
    _messages.clear();
    _resetStreamingBuffer(notify: false);
    _error = null;
    _activeFileIds = [];
    _lastToolCalls = [];
    _lastMemoryHits = [];
    _streamEvents = [];
    _sessionFiles = [];
    notifyListeners();
  }

  Future<void> refreshSkills() async {
    if (_isLoadingSkills) return;
    _isLoadingSkills = true;
    _skillsError = null;
    notifyListeners();
    try {
      final skills = await _api.listSkills();
      skills.sort((a, b) => a.name.compareTo(b.name));
      _availableSkills = skills;
    } on ApiException catch (e) {
      _skillsError = e.message;
    } catch (e) {
      _skillsError = e.toString();
    } finally {
      _isLoadingSkills = false;
      notifyListeners();
    }
  }

  void toggleSkill(String skillName) {
    final normalized = skillName.trim();
    if (normalized.isEmpty) return;
    final current = List<String>.from(_selectedSkillNames);
    if (current.contains(normalized)) {
      current.remove(normalized);
    } else {
      current.add(normalized);
      current.sort();
    }
    _selectedSkillNames = current;
    notifyListeners();
  }

  void clearSkill(String skillName) {
    final normalized = skillName.trim();
    if (normalized.isEmpty) return;
    _selectedSkillNames =
        _selectedSkillNames.where((item) => item != normalized).toList();
    notifyListeners();
  }

  void setMaxToolRounds(int value) {
    final clamped = value.clamp(0, 10);
    if (_maxToolRounds == clamped) return;
    _maxToolRounds = clamped;
    notifyListeners();
  }

  void resetRuntimeOptions() {
    _selectedSkillNames = [];
    _maxToolRounds = AppConfig.maxToolRounds;
    notifyListeners();
  }

  Future<void> switchSession(String sessionId) async {
    _sessionId = sessionId;
    _messages.clear();
    _resetStreamingBuffer(notify: false);
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

  Future<bool> renameSession(String sessionId, String title) async {
    final normalized = title.trim();
    if (normalized.isEmpty) return false;
    _error = null;
    try {
      final updated = await _api.updateSession(
        sessionId: sessionId,
        title: normalized,
      );
      _replaceSessionMeta(updated);
      return true;
    } on ApiException catch (e) {
      _error = e.message;
    } catch (e) {
      _error = e.toString();
    }
    notifyListeners();
    return false;
  }

  Future<bool> setSessionPinned(String sessionId, bool isPinned) async {
    _error = null;
    try {
      final updated = await _api.updateSession(
        sessionId: sessionId,
        isPinned: isPinned,
      );
      _replaceSessionMeta(updated);
      return true;
    } on ApiException catch (e) {
      _error = e.message;
    } catch (e) {
      _error = e.toString();
    }
    notifyListeners();
    return false;
  }

  void _replaceSessionMeta(SessionMeta updated) {
    final index = _sessions.indexWhere((item) => item.id == updated.id);
    if (index >= 0) {
      _sessions[index] = SessionMeta(
        id: updated.id,
        title: updated.title,
        createdAt: updated.createdAt,
        updatedAt: updated.updatedAt,
        isPinned: updated.isPinned,
        pinnedAt: updated.pinnedAt,
        messageCount: _sessions[index].messageCount,
      );
    } else {
      _sessions.insert(0, updated);
    }
    _sortSessions();
    unawaited(_saveSessions());
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
    _resetStreamingBuffer(notify: false);
    notifyListeners();

    try {
      // Try streaming first
      bool gotEvents = false;
      ChatResponse? doneResponse;

      try {
        await for (final event in _api.chatStream(
          message: content.trim(),
          sessionId: _sessionId,
          skillNames: _selectedSkillNames,
          maxToolRounds: _maxToolRounds,
          activeFileIds: _activeFileIds.isEmpty ? null : _activeFileIds,
        )) {
          gotEvents = true;
          doneResponse = _handleStreamEvent(event);
        }
      } catch (streamErr) {
        // Streaming failed, will fall back below
        debugPrint("[CHAT] streaming error, will fallback: $streamErr");
      }

      // If streaming didn't produce events, fall back to non-streaming
      if (!gotEvents) {
        debugPrint("[CHAT] no SSE events received, falling back to /api/chat");
        final resp = await _api.chat(
          message: content.trim(),
          sessionId: _sessionId,
          skillNames: _selectedSkillNames,
          maxToolRounds: _maxToolRounds,
          activeFileIds: _activeFileIds.isEmpty ? null : _activeFileIds,
        );
        doneResponse = resp;
      }

      _flushPendingStreamDelta(notify: false);

      // done 事件里的 answer 才是最终真值，必须覆盖流式阶段的临时 buffer。
      if (doneResponse != null) {
        _sessionId = doneResponse.sessionId;
        if (doneResponse.answer.isNotEmpty) {
          _streamBuffer = doneResponse.answer;
        }
        _lastToolCalls = doneResponse.toolCalls;
        _lastMemoryHits = doneResponse.memoryHits;
      }

      // Finalize: move stream buffer into a message
      if (_streamBuffer.isNotEmpty) {
        _messages.add(ChatMessage(role: "assistant", content: _streamBuffer));
        _resetStreamingBuffer(notify: false);
      }

      // Register session in local list
      if (_sessionId != null) {
        final lastUserMsg = _messages.lastWhere(
          (m) => m.isUser,
          orElse: () => ChatMessage(role: "user", content: ""),
        );
        _registerSession(_sessionId!, lastUserMsg.content);
      }

      // Refresh files after completion
      if (_sessionId != null) {
        await refreshSessionFiles();
        await refreshSessions();
      }
    } on ApiException catch (e) {
      _flushPendingStreamDelta(notify: false);
      _error = e.message;
    } catch (e) {
      _flushPendingStreamDelta(notify: false);
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
        _queueStreamDelta(delta);
        return null;

      case "answer_reset":
        _resetStreamingBuffer(notify: true);
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
          createdAt:
              DateTime.tryParse(data["created_at"] ?? "") ?? DateTime.now(),
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
        _flushPendingStreamDelta(notify: false);
        try {
          return ChatResponse.fromJson(data);
        } catch (_) {
          return null;
        }

      case "error":
        _flushPendingStreamDelta(notify: false);
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
      final resp = await _api.setActiveFiles(
        sessionId: _sessionId!,
        fileIds: current.toList(),
      );
      _sessionFiles = resp.files;
      _activeFileIds = resp.activeFileIds;
    } catch (_) {}
    notifyListeners();
  }

  Future<void> uploadSessionFile({
    required String filename,
    required Uint8List bytes,
    bool autoActivate = true,
  }) async {
    final trimmed = filename.trim();
    if (trimmed.isEmpty || bytes.isEmpty || _isUploadingFile) return;

    final hadSession = _sessionId != null;
    final sessionId = _sessionId ?? _generateSessionId();

    if (!hadSession) {
      _sessionId = sessionId;
      await _ensureSessionPlaceholder(
        sessionId,
        _buildSessionTitle("文件: $trimmed"),
      );
    }

    _error = null;
    _isUploadingFile = true;
    notifyListeners();

    try {
      await _api.uploadFile(
        sessionId: sessionId,
        filename: trimmed,
        contentBase64: base64Encode(bytes),
        autoActivate: autoActivate,
      );
      await refreshSessionFiles();
    } on ApiException catch (e) {
      _error = e.message;
      if (!hadSession && _messages.isEmpty) {
        await _discardPlaceholderSession(sessionId);
      }
    } catch (e) {
      _error = e.toString();
      if (!hadSession && _messages.isEmpty) {
        await _discardPlaceholderSession(sessionId);
      }
    } finally {
      _isUploadingFile = false;
      notifyListeners();
    }
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

  void _queueStreamDelta(String delta) {
    if (delta.isEmpty) return;
    _pendingStreamDelta += delta;
    if (_pendingStreamDelta.length > 512) {
      _flushPendingStreamDelta();
      return;
    }
    _streamFlushTimer ??= Timer(_streamFlushInterval, _flushPendingStreamDelta);
  }

  void _flushPendingStreamDelta({bool notify = true}) {
    _streamFlushTimer?.cancel();
    _streamFlushTimer = null;
    if (_pendingStreamDelta.isEmpty) return;
    _streamBuffer += _pendingStreamDelta;
    _pendingStreamDelta = "";
    if (notify) {
      notifyListeners();
    }
  }

  void _resetStreamingBuffer({required bool notify}) {
    _streamFlushTimer?.cancel();
    _streamFlushTimer = null;
    _pendingStreamDelta = "";
    _streamBuffer = "";
    if (notify) {
      notifyListeners();
    }
  }
}
