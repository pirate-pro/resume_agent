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
  String _streamAnswerFormat = "plain_text";
  String _streamRenderHint = "plain";
  String _streamLayoutHint = "paragraph";
  String _streamSourceKind = "direct_answer";
  String _streamPresentationKind = "chat_text";
  String _streamReasoningBuffer = "";
  List<AnswerArtifactView> _streamArtifacts = [];
  String _pendingStreamDelta = "";
  String _pendingReasoningDelta = "";
  Timer? _streamFlushTimer;
  Timer? _reasoningFlushTimer;
  Timer? _eventPollingTimer;
  Timer? _recentActivatedArtifactTimer;
  final Map<String, Future<void>> _pendingTitleRefreshes = {};
  String? _error;
  String? _skillsError;
  String? _recentActivatedArtifactId;
  final List<SessionMeta> _sessions = [];
  List<String> _activeArtifactIds = [];
  List<SkillOption> _availableSkills = [];
  List<String> _selectedSkillNames = [];
  int _maxToolRounds = AppConfig.maxToolRounds;
  bool _serverReachable = false;
  HealthView? _healthView;
  String? _activeRunId;

  // Debug / side panel data
  List<ToolCallView> _lastToolCalls = [];
  List<MemoryView> _lastMemoryHits = [];
  List<EventView> _streamEvents = [];
  List<SessionArtifactView> _sessionArtifacts = [];
  TokenUsageSummaryView? _tokenUsageSummary;
  bool _isLoadingTokenUsageSummary = false;

  // ── Getters ─────────────────────────────────────────────────────────
  String? get sessionId => _sessionId;
  List<ChatMessage> get messages => List.unmodifiable(_messages);
  bool get isStreaming => _isStreaming;
  bool get isUploadingFile => _isUploadingFile;
  bool get isLoadingSkills => _isLoadingSkills;
  String get streamBuffer => _streamBuffer;
  String get streamAnswerFormat => _streamAnswerFormat;
  String get streamRenderHint => _streamRenderHint;
  String get streamLayoutHint => _streamLayoutHint;
  String get streamSourceKind => _streamSourceKind;
  String get streamPresentationKind => _streamPresentationKind;
  String get streamReasoningBuffer => _streamReasoningBuffer;
  List<AnswerArtifactView> get streamArtifacts =>
      List.unmodifiable(_streamArtifacts);
  String? get error => _error;
  String? get skillsError => _skillsError;
  List<SessionMeta> get sessions => List.unmodifiable(_sessions);
  List<String> get activeArtifactIds => List.unmodifiable(_activeArtifactIds);
  List<SkillOption> get availableSkills => List.unmodifiable(_availableSkills);
  List<String> get selectedSkillNames => List.unmodifiable(_selectedSkillNames);
  int get maxToolRounds => _maxToolRounds;
  bool get serverReachable => _serverReachable;
  HealthView? get healthView => _healthView;
  bool get hasActiveSession => _sessionId != null;
  List<ToolCallView> get lastToolCalls => List.unmodifiable(_lastToolCalls);
  List<MemoryView> get lastMemoryHits => List.unmodifiable(_lastMemoryHits);
  List<EventView> get streamEvents => List.unmodifiable(_streamEvents);
  List<SessionArtifactView> get sessionArtifacts =>
      List.unmodifiable(_sessionArtifacts);
  TokenUsageSummaryView? get tokenUsageSummary => _tokenUsageSummary;
  bool get isLoadingTokenUsageSummary => _isLoadingTokenUsageSummary;
  String? get recentActivatedArtifactId => _recentActivatedArtifactId;

  ChatProvider(this._api) {
    _init();
  }

  @override
  void dispose() {
    _streamFlushTimer?.cancel();
    _eventPollingTimer?.cancel();
    _recentActivatedArtifactTimer?.cancel();
    super.dispose();
  }

  Future<void> _init() async {
    await _loadSessions();
    _checkHealth();
    unawaited(refreshSkills());
    unawaited(refreshTokenUsageSummary());
    await refreshSessions();
  }

  Future<void> _checkHealth() async {
    final health = await _api.fetchHealth();
    _healthView = health;
    _serverReachable = health?.isOnline == true;
    notifyListeners();
  }

  Future<void> refreshHealth() async {
    await _checkHealth();
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
      _sessionArtifacts = [];
      _activeArtifactIds = [];
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
    _clearRecentActivatedArtifact(notify: false);
    _error = null;
    _activeArtifactIds = [];
    _lastToolCalls = [];
    _lastMemoryHits = [];
    _streamEvents = [];
    _sessionArtifacts = [];
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
    final clamped = value.clamp(0, 20);
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
    _clearRecentActivatedArtifact(notify: false);
    _error = null;
    _streamEvents = [];
    notifyListeners();

    // Load messages from backend
    try {
      final msgs = await _api.listSessionMessages(sessionId);
      _messages.addAll(msgs);
      notifyListeners();
    } catch (_) {}

    await refreshSessionArtifacts();
    await refreshEvents();
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

  Future<void> _refreshSessionTitleUntilSettled(
    String sessionId, {
    required String provisionalTitle,
  }) async {
    final current = _pendingTitleRefreshes[sessionId];
    if (current != null) {
      await current;
      return;
    }

    final task = _doRefreshSessionTitleUntilSettled(
      sessionId,
      provisionalTitle: provisionalTitle,
    );
    _pendingTitleRefreshes[sessionId] = task;
    try {
      await task;
    } finally {
      _pendingTitleRefreshes.remove(sessionId);
    }
  }

  Future<void> _doRefreshSessionTitleUntilSettled(
    String sessionId, {
    required String provisionalTitle,
  }) async {
    const delays = <Duration>[
      Duration(milliseconds: 350),
      Duration(milliseconds: 900),
      Duration(milliseconds: 1800),
    ];

    for (final delay in delays) {
      await Future<void>.delayed(delay);
      await refreshSessions();
      final session =
          _sessions.where((item) => item.id == sessionId).firstOrNull;
      if (session == null) {
        return;
      }
      if (session.title != provisionalTitle &&
          session.title != "新会话" &&
          session.title != "New Session") {
        return;
      }
    }
  }

  // ── Chat (streaming) ────────────────────────────────────────────────

  Future<void> sendMessage(String content) async {
    if (content.trim().isEmpty || _isStreaming) return;

    _error = null;
    _lastToolCalls = [];
    _lastMemoryHits = [];
    _streamEvents = [];
    _activeRunId = null;
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
          activeArtifactIds:
              _activeArtifactIds.isEmpty ? null : _activeArtifactIds,
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
          activeArtifactIds:
              _activeArtifactIds.isEmpty ? null : _activeArtifactIds,
        );
        doneResponse = resp;
      }

      if (_sessionId != null) {
        await _pollCurrentRunEvents();
      }
      _flushPendingStreamDelta(notify: false);
      _flushPendingReasoningDelta(notify: false);

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
        _messages.add(
          ChatMessage(
            role: "assistant",
            content: _streamBuffer,
            answerFormat: doneResponse?.answerFormat ?? "plain_text",
            renderHint: doneResponse?.renderHint ?? "plain",
            layoutHint: doneResponse?.layoutHint ?? "paragraph",
            sourceKind: doneResponse?.sourceKind ?? "direct_answer",
            presentationKind: doneResponse?.presentationKind ?? "chat_text",
            artifacts: doneResponse?.artifacts ?? const [],
            toolCalls: doneResponse?.toolCalls ?? const [],
            progressEvents: _progressTraceEvents(_streamEvents),
          ),
        );
        _resetStreamingBuffer(notify: false);
      }

      // Register session in local list
      if (_sessionId != null) {
        final lastUserMsg = _messages.lastWhere(
          (m) => m.isUser,
          orElse: () => ChatMessage(role: "user", content: ""),
        );
        _registerSession(_sessionId!, lastUserMsg.content);
        if (doneResponse?.titlePending == true) {
          unawaited(
            _refreshSessionTitleUntilSettled(
              _sessionId!,
              provisionalTitle: _buildSessionTitle(lastUserMsg.content),
            ),
          );
        }
      }

      // Refresh active artifacts after completion.
      if (_sessionId != null) {
        await refreshSessionArtifacts();
        await refreshSessions();
      }
    } on ApiException catch (e) {
      _flushPendingStreamDelta(notify: false);
      _flushPendingReasoningDelta(notify: false);
      _error = e.message;
    } catch (e) {
      _flushPendingStreamDelta(notify: false);
      _flushPendingReasoningDelta(notify: false);
      _error = e.toString();
    } finally {
      _isStreaming = false;
      _stopEventPolling();
      unawaited(_checkHealth());
      unawaited(refreshTokenUsageSummary());
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
          _startEventPolling();
        }
        notifyListeners();
        return null;

      case "answer_delta":
        final delta = data["delta"]?.toString() ?? "";
        _queueStreamDelta(delta);
        return null;

      case "reasoning_delta":
        final delta = data["delta"]?.toString() ?? "";
        _queueReasoningDelta(delta);
        return null;

      case "answer_meta":
        // 流式阶段优先吃后端协议，避免前端每次都重新猜测渲染模式。
        _streamAnswerFormat = data["answer_format"]?.toString() ?? "plain_text";
        _streamRenderHint = data["render_hint"]?.toString() ?? "plain";
        _streamLayoutHint = data["layout_hint"]?.toString() ?? "paragraph";
        _streamSourceKind = data["source_kind"]?.toString() ?? "direct_answer";
        _streamPresentationKind =
            data["presentation_kind"]?.toString() ?? "chat_text";
        _streamArtifacts = (data["artifacts"] as List?)
                ?.map((item) => AnswerArtifactView.fromJson(
                    Map<String, dynamic>.from(item)))
                .toList() ??
            const [];
        notifyListeners();
        return null;

      case "answer_meta_reset":
        _resetStreamingMeta(notify: true);
        return null;

      case "answer_reset":
        _resetAnswerBuffer(notify: true);
        return null;

      case "run_event":
        // Store run events for the debug panel
        final eventRecord = EventView(
          eventId: data["event_id"]?.toString() ?? "",
          sessionId: data["session_id"]?.toString() ?? _sessionId ?? "",
          agentId: data["agent_id"]?.toString() ?? "",
          runId: data["run_id"]?.toString() ?? "",
          parentRunId: data["parent_run_id"]?.toString(),
          eventVersion: _readInt(data["event_version"]),
          type: data["type"]?.toString() ?? "",
          payload: Map<String, dynamic>.from(data["payload"] ?? {}),
          createdAt:
              DateTime.tryParse(data["created_at"] ?? "") ?? DateTime.now(),
        );
        if (eventRecord.type == "run_started" &&
            eventRecord.parentRunId == null) {
          _activeRunId = eventRecord.runId;
        }
        _mergeStreamEvents([eventRecord]);
        if (_streamEvents.length > 500) {
          _streamEvents = _streamEvents.sublist(_streamEvents.length - 500);
        }
        notifyListeners();
        return null;

      case "heartbeat":
        // Just keep alive, no action needed
        return null;

      case "done":
        // The done event contains the full ChatResponse
        _flushPendingStreamDelta(notify: false);
        _flushPendingReasoningDelta(notify: false);
        try {
          return ChatResponse.fromJson(data);
        } catch (_) {
          return null;
        }

      case "error":
        _flushPendingStreamDelta(notify: false);
        _flushPendingReasoningDelta(notify: false);
        _error = data["detail"]?.toString() ?? "Unknown stream error";
        notifyListeners();
        return null;

      default:
        return null;
    }
  }

  void _startEventPolling() {
    if (_eventPollingTimer != null || _sessionId == null) {
      return;
    }
    _eventPollingTimer = Timer.periodic(
      const Duration(milliseconds: 900),
      (_) => unawaited(_pollCurrentRunEvents()),
    );
    unawaited(_pollCurrentRunEvents());
  }

  void _stopEventPolling() {
    _eventPollingTimer?.cancel();
    _eventPollingTimer = null;
  }

  Future<void> _pollCurrentRunEvents() async {
    final sessionId = _sessionId;
    if (!_isStreaming || sessionId == null) {
      return;
    }
    try {
      final events = await _api.listSessionEvents(sessionId);
      final runId = _activeRunId;
      final visibleEvents = runId == null
          ? events
          : events
              .where(
                (event) => event.runId == runId || event.parentRunId == runId,
              )
              .toList();
      _mergeStreamEvents(visibleEvents);
      notifyListeners();
    } catch (_) {
      // 进度轮询只增强体验，失败时不影响主 SSE 输出。
    }
  }

  void _mergeStreamEvents(List<EventView> events) {
    if (events.isEmpty) {
      return;
    }
    final byKey = <String, EventView>{};
    for (final event in _streamEvents) {
      byKey[_eventKey(event)] = event;
    }
    for (final event in events) {
      byKey[_eventKey(event)] = event;
    }
    final merged = byKey.values.toList()
      ..sort((left, right) => left.createdAt.compareTo(right.createdAt));
    _streamEvents =
        merged.length > 500 ? merged.sublist(merged.length - 500) : merged;
  }

  String _eventKey(EventView event) {
    if (event.eventId.isNotEmpty) {
      return event.eventId;
    }
    return [
      event.runId,
      event.type,
      event.createdAt.toIso8601String(),
    ].join(":");
  }

  List<EventView> _progressTraceEvents(List<EventView> events) {
    return events
        .where(
          (event) =>
              event.type.startsWith("agent_task_") ||
              {
                "run_started",
                "assistant_thinking",
                "tool_call",
                "tool_result",
                "run_finished",
              }.contains(event.type),
        )
        .toList();
  }

  int _readInt(dynamic value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) return int.tryParse(value.trim()) ?? 0;
    return 0;
  }

  // ── Session artifacts ───────────────────────────────────────────────────

  Future<void> refreshSessionArtifacts() async {
    if (_sessionId == null) {
      _sessionArtifacts = [];
      _activeArtifactIds = [];
      _clearRecentActivatedArtifact(notify: false);
      notifyListeners();
      return;
    }
    try {
      final resp = await _api.listSessionArtifacts(_sessionId!);
      _sessionArtifacts = resp.artifacts;
      _activeArtifactIds = resp.activeArtifactIds;
    } catch (_) {}
    notifyListeners();
  }

  Future<void> toggleArtifactActive(String artifactId, bool active) async {
    if (_sessionId == null) return;
    final current = Set<String>.from(_activeArtifactIds);
    if (active) {
      current.add(artifactId);
    } else {
      current.remove(artifactId);
    }
    try {
      final resp = await _api.setActiveArtifacts(
        sessionId: _sessionId!,
        artifactIds: current.toList(),
      );
      _sessionArtifacts = resp.artifacts;
      _activeArtifactIds = resp.activeArtifactIds;
      if (active && _activeArtifactIds.contains(artifactId)) {
        _markRecentActivatedArtifact(artifactId, notify: false);
      } else if (!active && _recentActivatedArtifactId == artifactId) {
        _clearRecentActivatedArtifact(notify: false);
      }
    } catch (_) {}
    notifyListeners();
  }

  Future<bool> activateArtifact(String artifactId) async {
    if (_sessionId == null) return false;
    final current = Set<String>.from(_activeArtifactIds)..add(artifactId);
    try {
      final resp = await _api.setActiveArtifacts(
        sessionId: _sessionId!,
        artifactIds: current.toList(),
      );
      _sessionArtifacts = resp.artifacts;
      _activeArtifactIds = resp.activeArtifactIds;
      final activated = _activeArtifactIds.contains(artifactId);
      if (activated) {
        _markRecentActivatedArtifact(artifactId, notify: false);
      }
      notifyListeners();
      return activated;
    } on ApiException catch (error) {
      _error = error.message;
    } catch (error) {
      _error = error.toString();
    }
    notifyListeners();
    return false;
  }

  Future<WorkspaceFilePreview> previewWorkspaceFile(
    String path, {
    int maxChars = 12000,
  }) async {
    final sessionId = _sessionId;
    if (sessionId == null || sessionId.isEmpty) {
      throw StateError("当前没有可预览 workspace 文件的会话。");
    }
    return _api.previewWorkspaceFile(
      sessionId: sessionId,
      path: path,
      maxChars: maxChars,
    );
  }

  Future<SessionArtifactContentView> readSessionArtifactContent(
    String artifactId, {
    int offset = 0,
    int maxChars = 12000,
  }) async {
    final sessionId = _sessionId;
    if (sessionId == null || sessionId.isEmpty) {
      throw StateError("当前没有可预览 artifact 的会话。");
    }
    return _api.readSessionArtifactContent(
      sessionId: sessionId,
      artifactId: artifactId,
      offset: offset,
      maxChars: maxChars,
    );
  }

  String? sessionArtifactDownloadUrl(String artifactId) {
    final sessionId = _sessionId;
    if (sessionId == null || sessionId.isEmpty) {
      return null;
    }
    return _api.sessionArtifactDownloadUrl(
      sessionId: sessionId,
      artifactId: artifactId,
    );
  }

  Future<void> uploadSessionArtifact({
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
      await _api.uploadArtifact(
        sessionId: sessionId,
        filename: trimmed,
        contentBase64: base64Encode(bytes),
        autoActivate: autoActivate,
      );
      await refreshSessionArtifacts();
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

  Future<void> refreshTokenUsageSummary() async {
    if (_isLoadingTokenUsageSummary) return;
    _isLoadingTokenUsageSummary = true;
    notifyListeners();
    try {
      _tokenUsageSummary = await _api.fetchTokenUsageSummary();
    } catch (_) {
      _tokenUsageSummary = null;
    } finally {
      _isLoadingTokenUsageSummary = false;
      notifyListeners();
    }
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

  void _queueReasoningDelta(String delta) {
    if (delta.isEmpty) return;
    _pendingReasoningDelta += delta;
    if (_pendingReasoningDelta.length > 512) {
      _flushPendingReasoningDelta();
      return;
    }
    _reasoningFlushTimer ??=
        Timer(_streamFlushInterval, _flushPendingReasoningDelta);
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

  void _flushPendingReasoningDelta({bool notify = true}) {
    _reasoningFlushTimer?.cancel();
    _reasoningFlushTimer = null;
    if (_pendingReasoningDelta.isEmpty) return;
    _streamReasoningBuffer += _pendingReasoningDelta;
    _pendingReasoningDelta = "";
    if (notify) {
      notifyListeners();
    }
  }

  void _resetStreamingBuffer({required bool notify}) {
    _resetAnswerBuffer(notify: false);
    _reasoningFlushTimer?.cancel();
    _reasoningFlushTimer = null;
    _pendingReasoningDelta = "";
    _streamReasoningBuffer = "";
    if (notify) {
      notifyListeners();
    }
  }

  void _resetAnswerBuffer({required bool notify}) {
    _streamFlushTimer?.cancel();
    _streamFlushTimer = null;
    _pendingStreamDelta = "";
    _streamBuffer = "";
    _resetStreamingMeta(notify: false);
    if (notify) {
      notifyListeners();
    }
  }

  void _resetStreamingMeta({required bool notify}) {
    _streamAnswerFormat = "plain_text";
    _streamRenderHint = "plain";
    _streamLayoutHint = "paragraph";
    _streamSourceKind = "direct_answer";
    _streamPresentationKind = "chat_text";
    _streamArtifacts = [];
    if (notify) {
      notifyListeners();
    }
  }

  void _markRecentActivatedArtifact(String artifactId, {required bool notify}) {
    _recentActivatedArtifactTimer?.cancel();
    _recentActivatedArtifactId = artifactId;
    _recentActivatedArtifactTimer = Timer(const Duration(seconds: 3), () {
      _recentActivatedArtifactId = null;
      notifyListeners();
    });
    if (notify) {
      notifyListeners();
    }
  }

  void _clearRecentActivatedArtifact({required bool notify}) {
    _recentActivatedArtifactTimer?.cancel();
    _recentActivatedArtifactTimer = null;
    _recentActivatedArtifactId = null;
    if (notify) {
      notifyListeners();
    }
  }
}
