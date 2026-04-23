import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:agent_runtime/shared/api/chat_api.dart';
import 'package:agent_runtime/shared/models/message.dart';
import 'package:agent_runtime/shared/models/session.dart';
import 'package:agent_runtime/shared/models/skill.dart';

class ChatState {
  final Session? currentSession;
  final List<Message> messages;
  final bool isSending;
  final String? error;
  final bool isLoading;
  final List<Session> sessions;
  final List<Skill> skills;
  final List<String> selectedSkills;
  final List<dynamic>? files;
  final List<String>? activeFileIds;
  final String? uploadStatus;
  final bool isUploading;

  const ChatState({
    this.currentSession,
    this.messages = const [],
    this.isSending = false,
    this.error,
    this.isLoading = false,
    this.sessions = const [],
    this.skills = const [],
    this.selectedSkills = const [],
    this.files,
    this.activeFileIds,
    this.uploadStatus,
    this.isUploading = false,
  });

  ChatState copyWith({
    Session? currentSession,
    List<Message>? messages,
    bool? isSending,
    String? error,
    bool clearError = false,
    bool? isLoading,
    List<Session>? sessions,
    List<Skill>? skills,
    List<String>? selectedSkills,
    List<dynamic>? files,
    List<String>? activeFileIds,
    String? uploadStatus,
    bool? isUploading,
  }) {
    return ChatState(
      currentSession: currentSession ?? this.currentSession,
      messages: messages ?? this.messages,
      isSending: isSending ?? this.isSending,
      error: clearError ? null : (error ?? this.error),
      isLoading: isLoading ?? this.isLoading,
      sessions: sessions ?? this.sessions,
      skills: skills ?? this.skills,
      selectedSkills: selectedSkills ?? this.selectedSkills,
      files: files ?? this.files,
      activeFileIds: activeFileIds ?? this.activeFileIds,
      uploadStatus: uploadStatus ?? this.uploadStatus,
      isUploading: isUploading ?? this.isUploading,
    );
  }
}

class ChatNotifier extends StateNotifier<ChatState> {
  final ChatApiClient _apiClient;
  StreamSubscription<Message>? _streamSubscription;

  ChatNotifier(this._apiClient) : super(const ChatState());

  Future<void> initialize() async {
    state = state.copyWith(isLoading: true);
    try {
      final sessions = await _apiClient.getSessions();
      final skills = await _apiClient.getSkills();
      state = state.copyWith(
        sessions: sessions,
        skills: skills,
        selectedSkills: ['base', 'memory', 'memory-editor', 'tools'],
        isLoading: false,
      );

      if (sessions.isNotEmpty) {
        await switchToSession(sessions.first.id);
      } else {
        await createNewSession();
      }
    } catch (e) {
      state = state.copyWith(error: e.toString(), isLoading: false);
    }
  }

  Future<void> createNewSession() async {
    try {
      final session = await _apiClient.createSession();
      state = state.copyWith(
        currentSession: session,
        messages: [],
        sessions: [session, ...state.sessions],
      );
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  Future<void> switchToSession(String sessionId) async {
    try {
      final session = state.sessions.firstWhere((s) => s.id == sessionId);
      state = state.copyWith(
        currentSession: session,
        messages: session.messages,
      );
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  Future<void> deleteSession(String sessionId) async {
    try {
      await _apiClient.deleteSession(sessionId);
      final newSessions = state.sessions.where((s) => s.id != sessionId).toList();

      if (state.currentSession?.id == sessionId) {
        if (newSessions.isNotEmpty) {
          await switchToSession(newSessions.first.id);
        } else {
          await createNewSession();
        }
      }

      state = state.copyWith(sessions: newSessions);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  Future<void> sendMessage(String message, List<String> skills) async {
    if (state.isSending || state.currentSession == null) return;

    final currentSession = state.currentSession!;
    final newMessage = Message(
      id: 'user-${DateTime.now().millisecondsSinceEpoch}',
      role: 'user',
      content: message,
    );

    state = state.copyWith(
      messages: [...state.messages, newMessage],
      isSending: true,
    );

    _streamSubscription?.cancel();
    _streamSubscription = _apiClient.streamMessages(
      message: message,
      sessionId: currentSession.id,
      skillNames: skills,
    ).listen(
      (streamMessage) {
        state = state.copyWith(messages: [...state.messages, streamMessage]);
      },
      onError: (error) {
        state = state.copyWith(
          messages: [
            ...state.messages,
            Message(
              id: 'error-${DateTime.now().millisecondsSinceEpoch}',
              role: 'error',
              content: 'Error: $error',
            ),
          ],
          isSending: false,
        );
      },
      onDone: () {
        state = state.copyWith(isSending: false);
        _streamSubscription?.cancel();
        _streamSubscription = null;

        // 更新会话预览
        if (state.currentSession != null) {
          final lastUserMessage = state.messages
              .where((m) => m.role == 'user')
              .lastOrNull?.content;

          final updatedSession = state.currentSession!.copyWith(
            preview: lastUserMessage ?? state.currentSession!.preview,
            messages: state.messages,
          );

          state = state.copyWith(
            currentSession: updatedSession,
            sessions: state.sessions.map((s) {
              if (s.id == updatedSession.id) return updatedSession;
              return s;
            }).toList(),
          );
        }
      },
    );
  }

  Future<void> uploadFile(String filePath, String fileName) async {
    if (state.currentSession == null) return;

    state = state.copyWith(isUploading: true, uploadStatus: '上传中...');

    try {
      await _apiClient.uploadFile(
        sessionId: state.currentSession!.id,
        filePath: filePath,
        fileName: fileName,
      );
      state = state.copyWith(uploadStatus: '上传完成');
      await refreshFiles();
    } catch (e) {
      state = state.copyWith(uploadStatus: '上传失败: $e');
    } finally {
      state = state.copyWith(isUploading: false);
    }
  }

  Future<void> refreshFiles() async {
    if (state.currentSession == null) return;

    try {
      final files = await _apiClient.getSessionFiles(state.currentSession!.id);
      state = state.copyWith(files: files);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  Future<void> updateActiveFiles(List<String> fileIds) async {
    if (state.currentSession == null) return;

    try {
      await _apiClient.updateActiveFiles(
        sessionId: state.currentSession!.id,
        fileIds: fileIds,
      );
      state = state.copyWith(activeFileIds: fileIds);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  void updateSelectedSkills(List<String> skills) {
    state = state.copyWith(selectedSkills: skills);
  }

  void clearError() {
    state = state.copyWith(clearError: true);
  }
}

final chatProvider = StateNotifierProvider<ChatNotifier, ChatState>((ref) {
  final apiClient = ChatApiClient();
  final notifier = ChatNotifier(apiClient);
  notifier.initialize();
  return notifier;
});
