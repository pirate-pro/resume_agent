import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';
import 'package:agent_runtime/core/state/chat_notifier.dart';
import 'package:agent_runtime/features/chat/widgets/message_bubble.dart';
import 'package:agent_runtime/features/chat/widgets/chat_input.dart';
import 'package:agent_runtime/features/sessions/widgets/session_list.dart';
import 'package:agent_runtime/features/debug/widgets/debug_panel.dart';
import 'package:agent_runtime/features/chat/widgets/quick_test_buttons.dart';
import 'package:agent_runtime/features/chat/widgets/max_rounds_setting.dart';
import 'package:agent_runtime/features/files/widgets/file_list.dart';
import 'package:agent_runtime/features/files/widgets/upload_status.dart';
import 'package:agent_runtime/features/chat/widgets/error_handler.dart';

class ChatPage extends ConsumerWidget {
  const ChatPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chatState = ref.watch(chatProvider);
    final chatNotifier = ref.read(chatProvider.notifier);

    return Scaffold(
      appBar: AppBar(
        title: Text('Agent Runtime'),
        backgroundColor: AppTokens.shellBg,
        elevation: 0,
        actions: [
          IconButton(
            icon: Icon(Icons.refresh),
            onPressed: () {
              chatNotifier.clearError();
            },
          ),
        ],
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          if (constraints.maxWidth < 600) {
            return _buildMobileLayout(chatState, chatNotifier, context);
          } else {
            return _buildDesktopLayout(chatState, chatNotifier, context);
          }
        },
      ),
    );
  }

  Widget _buildMobileLayout(ChatState chatState, ChatNotifier chatNotifier, BuildContext context) {
    return Column(
      children: [
        if (chatState.error != null) ...[
          ErrorHandler(
            error: chatState.error,
            onRetry: () {
              chatNotifier.clearError();
            },
          ),
        ],
        Expanded(
          child: _buildMessageList(chatState),
        ),
        if (chatState.currentSession != null) ...[
          UploadStatus(
            status: chatState.uploadStatus,
            isLoading: chatState.isUploading,
          ),
          FileList(
            sessionId: chatState.currentSession!.id,
            files: chatState.files ?? [],
            activeFileIds: chatState.activeFileIds ?? [],
            onActiveFilesChanged: (fileIds) {
              chatNotifier.updateActiveFiles(fileIds);
            },
          ),
        ],
        QuickTestButtons(
          onTest: (prompt) {
            chatNotifier.sendMessage(prompt, chatState.selectedSkills);
          },
        ),
        MaxRoundsSetting(
          maxRounds: 3,
          onMaxRoundsChanged: (value) {
            // 更新max_tool_rounds
          },
        ),
        ChatInput(
          onSend: chatNotifier.sendMessage,
          isSending: chatState.isSending,
          skills: chatState.skills,
          selectedSkills: chatState.selectedSkills,
          onSkillsChanged: chatNotifier.updateSelectedSkills,
        ),
      ],
    );
  }

  Widget _buildDesktopLayout(ChatState chatState, ChatNotifier chatNotifier, BuildContext context) {
    return Row(
      children: [
        // 左侧会话列表
        SizedBox(
          width: 260,
          child: Column(
            children: [
              _buildSessionHeader(chatNotifier),
              Expanded(
                child: SessionList(
                  sessions: chatState.sessions,
                  currentSessionId: chatState.currentSession?.id,
                  onSelectSession: chatNotifier.switchToSession,
                  onDeleteSession: chatNotifier.deleteSession,
                ),
              ),
            ],
          ),
        ),
        // 中间聊天区域
        Expanded(
          child: Column(
            children: [
              _buildChatHeader(chatState),
              if (chatState.error != null) ...[
                ErrorHandler(
                  error: chatState.error,
                  onRetry: () {
                    chatNotifier.clearError();
                  },
                ),
              ],
              Expanded(
                child: _buildMessageList(chatState),
              ),
              if (chatState.currentSession != null) ...[
                UploadStatus(
                  status: chatState.uploadStatus,
                  isLoading: chatState.isUploading,
                ),
                FileList(
                  sessionId: chatState.currentSession!.id,
                  files: chatState.files ?? [],
                  activeFileIds: chatState.activeFileIds ?? [],
                  onActiveFilesChanged: (fileIds) {
                    chatNotifier.updateActiveFiles(fileIds);
                  },
                ),
              ],
              QuickTestButtons(
                onTest: (prompt) {
                  chatNotifier.sendMessage(prompt, chatState.selectedSkills);
                },
              ),
              MaxRoundsSetting(
                maxRounds: 3,
                onMaxRoundsChanged: (value) {
                  // 更新max_tool_rounds
                },
              ),
              ChatInput(
                onSend: chatNotifier.sendMessage,
                isSending: chatState.isSending,
                skills: chatState.skills,
                selectedSkills: chatState.selectedSkills,
                onSkillsChanged: chatNotifier.updateSelectedSkills,
              ),
            ],
          ),
        ),
        // 右侧调试面板
        if (chatState.currentSession != null)
          SizedBox(
            width: 300,
            child: DebugPanel(sessionId: chatState.currentSession!.id),
          ),
      ],
    );
  }

  Widget _buildSessionHeader(ChatNotifier chatNotifier) {
    return Container(
      padding: EdgeInsets.all(AppTokens.spacingMd),
      decoration: BoxDecoration(
        color: AppTokens.shellBg,
        border: Border(
          bottom: BorderSide(
            color: AppTokens.textSub.withOpacity(0.2),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              '会话历史',
              style: TextStyle(
                fontSize: AppTokens.fontSizeSm,
                fontWeight: AppTokens.fontWeightMedium,
                color: AppTokens.textSub,
              ),
            ),
          ),
          IconButton(
            icon: Icon(Icons.add, color: AppTokens.accent),
            onPressed: () {
              chatNotifier.createNewSession();
            },
          ),
        ],
      ),
    );
  }

  Widget _buildChatHeader(ChatState chatState) {
    return Container(
      padding: EdgeInsets.all(AppTokens.spacingMd),
      decoration: BoxDecoration(
        color: AppTokens.shellBg,
        border: Border(
          bottom: BorderSide(
            color: AppTokens.textSub.withOpacity(0.2),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              chatState.currentSession?.title ?? '选择会话',
              style: TextStyle(
                fontSize: AppTokens.fontSizeLg,
                fontWeight: AppTokens.fontWeightMedium,
                color: AppTokens.textMain,
              ),
            ),
          ),
          if (chatState.currentSession != null) ...[
            Text(
              '在线',
              style: TextStyle(
                fontSize: AppTokens.fontSizeSm,
                color: AppTokens.success,
              ),
            ),
            SizedBox(width: AppTokens.spacingSm),
            Icon(
              Icons.circle,
              color: AppTokens.success,
              size: 12,
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildMessageList(ChatState chatState) {
    return ListView.builder(
      padding: EdgeInsets.all(AppTokens.spacingMd),
      itemCount: chatState.messages.length,
      itemBuilder: (context, index) {
        final message = chatState.messages[index];
        return MessageBubble(message: message);
      },
    );
  }
}
