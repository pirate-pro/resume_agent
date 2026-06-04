import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
import '../../core/providers/theme_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/widgets/chat_bubble.dart';
import '../../shared/widgets/input_bar.dart';

const double _messageRailMaxWidth = 920;
const double _messageListTopPadding = 102;
const double _messageListBottomPadding = 132;
const double _messageBottomContentFadeHeight = 140;
const double _chatHeaderHeight = 72;
const double _jumpToBottomButtonBottom = 112;
const double _jumpToBottomThreshold = 140;

class ChatScreen extends ConsumerStatefulWidget {
  final bool showSidebarToggle;
  final VoidCallback? onSidebarToggle;
  final bool showWorkbenchToggle;
  final bool isWorkbenchOpen;
  final VoidCallback? onWorkbenchToggle;
  final bool showCareerAssetsToggle;
  final bool isCareerAssetsPanelOpen;
  final VoidCallback? onCareerAssetsToggle;
  final bool showDebugToggle;
  final bool isDebugPanelOpen;
  final VoidCallback? onDebugToggle;
  final ChatBubbleStyle messageStyle;

  const ChatScreen({
    super.key,
    this.showSidebarToggle = false,
    this.onSidebarToggle,
    this.showWorkbenchToggle = false,
    this.isWorkbenchOpen = false,
    this.onWorkbenchToggle,
    this.showCareerAssetsToggle = false,
    this.isCareerAssetsPanelOpen = false,
    this.onCareerAssetsToggle,
    this.showDebugToggle = false,
    this.isDebugPanelOpen = false,
    this.onDebugToggle,
    this.messageStyle = ChatBubbleStyle.standard,
  });

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _scrollCtrl = ScrollController();
  bool _showJumpToBottom = false;

  @override
  void initState() {
    super.initState();
    _scrollCtrl.addListener(_handleScroll);
  }

  @override
  void dispose() {
    _scrollCtrl.removeListener(_handleScroll);
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _handleScroll() {
    if (!_scrollCtrl.hasClients) {
      return;
    }
    final distanceToBottom =
        _scrollCtrl.position.maxScrollExtent - _scrollCtrl.position.pixels;
    final nextShow = distanceToBottom > _jumpToBottomThreshold;
    if (nextShow != _showJumpToBottom && mounted) {
      setState(() {
        _showJumpToBottom = nextShow;
      });
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final hasMessages = ref.watch(
      chatProvider.select((provider) {
        return provider.isStreaming || provider.messages.isNotEmpty;
      }),
    );

    ref.listen<(int, int)>(
      chatProvider.select((provider) {
        return (provider.messages.length, provider.streamBuffer.length);
      }),
      (previous, next) {
        if (previous != next) {
          _scrollToBottom();
        }
      },
    );

    return Stack(
      children: [
        if (hasMessages)
          Positioned(
            left: 0,
            right: 0,
            top: 0,
            bottom: 0,
            child: _MessageBottomFade(
              child: _ChatMessageLayer(
                scrollCtrl: _scrollCtrl,
                messageStyle: widget.messageStyle,
              ),
            ),
          )
        else
          const Positioned.fill(child: _WelcomeScreen()),
        Positioned(
          left: 0,
          right: 0,
          top: 0,
          child: _ChatHeaderLayer(
            showSidebarToggle: widget.showSidebarToggle,
            onSidebarToggle: widget.onSidebarToggle,
            showWorkbenchToggle: widget.showWorkbenchToggle,
            isWorkbenchOpen: widget.isWorkbenchOpen,
            onWorkbenchToggle: widget.onWorkbenchToggle,
            showCareerAssetsToggle: widget.showCareerAssetsToggle,
            isCareerAssetsPanelOpen: widget.isCareerAssetsPanelOpen,
            onCareerAssetsToggle: widget.onCareerAssetsToggle,
            showDebugToggle: widget.showDebugToggle,
            isDebugPanelOpen: widget.isDebugPanelOpen,
            onDebugToggle: widget.onDebugToggle,
          ),
        ),
        if (hasMessages)
          Positioned(
            left: 0,
            right: 0,
            bottom: _jumpToBottomButtonBottom,
            child: IgnorePointer(
              ignoring: !_showJumpToBottom,
              child: AnimatedOpacity(
                duration: const Duration(milliseconds: 180),
                opacity: _showJumpToBottom ? 1 : 0,
                child: Center(
                  child: ConstrainedBox(
                    constraints:
                        const BoxConstraints(maxWidth: _messageRailMaxWidth),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Padding(
                          padding: const EdgeInsets.only(right: 28),
                          child: _JumpToBottomButton(
                            onTap: _scrollToBottom,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: const _ChatComposerLayer(),
        ),
      ],
    );
  }
}

class _ChatHeaderLayer extends ConsumerWidget {
  final bool showSidebarToggle;
  final VoidCallback? onSidebarToggle;
  final bool showWorkbenchToggle;
  final bool isWorkbenchOpen;
  final VoidCallback? onWorkbenchToggle;
  final bool showCareerAssetsToggle;
  final bool isCareerAssetsPanelOpen;
  final VoidCallback? onCareerAssetsToggle;
  final bool showDebugToggle;
  final bool isDebugPanelOpen;
  final VoidCallback? onDebugToggle;

  const _ChatHeaderLayer({
    required this.showSidebarToggle,
    required this.onSidebarToggle,
    required this.showWorkbenchToggle,
    required this.isWorkbenchOpen,
    required this.onWorkbenchToggle,
    required this.showCareerAssetsToggle,
    required this.isCareerAssetsPanelOpen,
    required this.onCareerAssetsToggle,
    required this.showDebugToggle,
    required this.isDebugPanelOpen,
    required this.onDebugToggle,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final reachable = ref.watch(
      chatProvider.select((provider) => provider.serverReachable),
    );
    final themeMode = ref.watch(themeModeProvider);
    final isDarkMode = themeMode == ThemeMode.dark;
    final compactHeader = MediaQuery.sizeOf(context).width < 620;
    final headerTitle = ref.watch(
      chatProvider.select((provider) {
        final activeId = provider.sessionId;
        if (activeId != null) {
          for (final session in provider.sessions) {
            if (session.id == activeId && session.title.trim().isNotEmpty) {
              return session.title.trim();
            }
          }
        }
        return "求职 Agent 助手";
      }),
    );

    return _HeaderDock(
      child: Padding(
        padding: EdgeInsets.symmetric(horizontal: compactHeader ? 14 : 32),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: _messageRailMaxWidth),
            child: Row(
              children: [
                if (showSidebarToggle) ...[
                  _HeaderButton(
                    icon: Icons.menu_rounded,
                    onTap: onSidebarToggle,
                  ),
                  const SizedBox(width: 10),
                ],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        headerTitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: compactHeader ? 16 : 18,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      if (!compactHeader) ...[
                        const SizedBox(height: 4),
                        Text(
                          "对话 · 求职资产 · Agent 协作",
                          style: AppTheme.ts(
                            fontSize: 12,
                            fontWeight: FontWeight.w500,
                            color: AppTheme.textTertiary,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(width: 14),
                compactHeader
                    ? _HealthDot(reachable: reachable)
                    : _HealthBadge(reachable: reachable),
                if (showWorkbenchToggle) ...[
                  const SizedBox(width: 8),
                  _HeaderButton(
                    icon: Icons.dashboard_customize_outlined,
                    active: isWorkbenchOpen,
                    label: compactHeader ? null : '工作台',
                    size: compactHeader ? 34 : 36,
                    tooltip: '求职工作台',
                    onTap: onWorkbenchToggle,
                  ),
                ],
                if (showCareerAssetsToggle) ...[
                  const SizedBox(width: 8),
                  _HeaderButton(
                    icon: Icons.work_outline_rounded,
                    active: isCareerAssetsPanelOpen,
                    size: compactHeader ? 34 : 36,
                    tooltip: '求职资产',
                    onTap: onCareerAssetsToggle,
                  ),
                ],
                if (showDebugToggle && !compactHeader) ...[
                  const SizedBox(width: 8),
                  _HeaderButton(
                    icon: isDebugPanelOpen
                        ? Icons.tune_rounded
                        : Icons.developer_board_rounded,
                    active: isDebugPanelOpen,
                    size: 36,
                    onTap: onDebugToggle,
                  ),
                ],
                const SizedBox(width: 8),
                _HeaderButton(
                  icon: isDarkMode
                      ? Icons.light_mode_rounded
                      : Icons.dark_mode_rounded,
                  size: compactHeader ? 34 : 36,
                  tooltip: isDarkMode ? '切换浅色主题' : '切换深色主题',
                  onTap: () => ref.read(themeModeProvider.notifier).toggle(),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ChatMessageLayer extends ConsumerWidget {
  final ScrollController scrollCtrl;
  final ChatBubbleStyle messageStyle;

  const _ChatMessageLayer({
    required this.scrollCtrl,
    required this.messageStyle,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = ref.watch(chatProvider);
    return _MessageList(
      messages: provider.messages,
      scrollCtrl: scrollCtrl,
      isStreaming: provider.isStreaming,
      streamBuffer: provider.streamBuffer,
      streamAnswerFormat: provider.streamAnswerFormat,
      streamRenderHint: provider.streamRenderHint,
      streamLayoutHint: provider.streamLayoutHint,
      streamReasoningBuffer: provider.streamReasoningBuffer,
      streamArtifacts: provider.streamArtifacts,
      streamEvents: provider.streamEvents,
      error: provider.error,
      onClearError: provider.clearError,
      messageStyle: messageStyle,
    );
  }
}

class _ChatComposerLayer extends ConsumerWidget {
  const _ChatComposerLayer();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final viewModel = ref.watch(
      chatProvider.select(_ComposerViewModel.fromProvider),
    );
    final provider = ref.read(chatProvider);

    return _ComposerDock(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _ComposerQuickChips(onSend: provider.sendMessage),
          InputBar(
            enabled: viewModel.enabled,
            isUploading: viewModel.isUploading,
            isLoadingSkills: viewModel.isLoadingSkills,
            sessionArtifacts: viewModel.sessionArtifacts,
            activeArtifactIds: viewModel.activeArtifactIds,
            highlightedArtifactId: viewModel.highlightedArtifactId,
            availableSkills: viewModel.availableSkills,
            selectedSkillNames: viewModel.selectedSkillNames,
            maxToolRounds: viewModel.maxToolRounds,
            skillsError: viewModel.skillsError,
            onSend: (text) => provider.sendMessage(text),
            onUpload: ({required filename, required bytes}) => provider
                .uploadSessionArtifact(filename: filename, bytes: bytes),
            onToggleArtifactActive: (file, active) =>
                provider.toggleArtifactActive(file.artifactId, active),
            onRefreshSkills: provider.refreshSkills,
            onToggleSkill: provider.toggleSkill,
            onMaxToolRoundsChanged: provider.setMaxToolRounds,
            onResetRuntimeOptions: provider.resetRuntimeOptions,
          ),
        ],
      ),
    );
  }
}

class _ComposerQuickChips extends StatelessWidget {
  final Future<void> Function(String) onSend;

  const _ComposerQuickChips({required this.onSend});

  @override
  Widget build(BuildContext context) {
    const chips = [
      (Icons.upload_file_outlined, "上传简历"),
      (Icons.link_rounded, "分析 JD"),
      (Icons.add_circle_outline_rounded, "创建学习任务"),
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 10),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 860),
          child: Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              for (final chip in chips)
                _ComposerQuickChip(
                  icon: chip.$1,
                  label: chip.$2,
                  onTap: () => onSend(chip.$2),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ComposerQuickChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _ComposerQuickChip({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.94),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.border),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: AppTheme.accent),
              const SizedBox(width: 7),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textPrimary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _JumpToBottomButton extends StatelessWidget {
  final VoidCallback onTap;

  const _JumpToBottomButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.9),
            shape: BoxShape.circle,
            border: Border.all(
              color: AppTheme.accent.withValues(
                alpha: AppTheme.isDark ? 0.18 : 0.14,
              ),
            ),
            boxShadow: [
              BoxShadow(
                color: Colors.black
                    .withValues(alpha: AppTheme.isDark ? 0.12 : 0.06),
                blurRadius: 16,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Icon(
            Icons.keyboard_double_arrow_down_rounded,
            size: 19,
            color: AppTheme.accent,
          ),
        ),
      ),
    );
  }
}

class _HeaderDock extends StatelessWidget {
  final Widget child;

  const _HeaderDock({required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: _chatHeaderHeight,
      decoration: BoxDecoration(
        color:
            AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.86 : 0.92),
        border: Border(
          bottom: BorderSide(
            color:
                AppTheme.border.withValues(alpha: AppTheme.isDark ? 0.72 : 1),
          ),
        ),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.18 : 0.03),
            blurRadius: 18,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: SafeArea(
        bottom: false,
        child: child,
      ),
    );
  }
}

class _ComposerViewModel {
  final bool enabled;
  final bool isUploading;
  final bool isLoadingSkills;
  final List<SessionArtifactView> sessionArtifacts;
  final List<String> activeArtifactIds;
  final String? highlightedArtifactId;
  final List<SkillOption> availableSkills;
  final List<String> selectedSkillNames;
  final int maxToolRounds;
  final String? skillsError;

  const _ComposerViewModel({
    required this.enabled,
    required this.isUploading,
    required this.isLoadingSkills,
    required this.sessionArtifacts,
    required this.activeArtifactIds,
    required this.highlightedArtifactId,
    required this.availableSkills,
    required this.selectedSkillNames,
    required this.maxToolRounds,
    required this.skillsError,
  });

  factory _ComposerViewModel.fromProvider(ChatProvider provider) {
    return _ComposerViewModel(
      enabled: !provider.isStreaming,
      isUploading: provider.isUploadingFile,
      isLoadingSkills: provider.isLoadingSkills,
      sessionArtifacts: provider.sessionArtifacts,
      activeArtifactIds: provider.activeArtifactIds,
      highlightedArtifactId: provider.recentActivatedArtifactId,
      availableSkills: provider.availableSkills,
      selectedSkillNames: provider.selectedSkillNames,
      maxToolRounds: provider.maxToolRounds,
      skillsError: provider.skillsError,
    );
  }

  @override
  bool operator ==(Object other) {
    return other is _ComposerViewModel &&
        other.enabled == enabled &&
        other.isUploading == isUploading &&
        other.isLoadingSkills == isLoadingSkills &&
        other.highlightedArtifactId == highlightedArtifactId &&
        other.maxToolRounds == maxToolRounds &&
        other.skillsError == skillsError &&
        _stringListEquals(other.activeArtifactIds, activeArtifactIds) &&
        _sessionArtifactListEquals(other.sessionArtifacts, sessionArtifacts) &&
        _skillOptionListEquals(other.availableSkills, availableSkills) &&
        _stringListEquals(other.selectedSkillNames, selectedSkillNames);
  }

  @override
  int get hashCode => Object.hash(
        enabled,
        isUploading,
        isLoadingSkills,
        highlightedArtifactId,
        maxToolRounds,
        skillsError,
        activeArtifactIds.length,
        sessionArtifacts.length,
        availableSkills.length,
        selectedSkillNames.length,
      );
}

// ── Health badge ─────────────────────────────────────────────────────────

class _HealthBadge extends StatelessWidget {
  final bool reachable;
  const _HealthBadge({required this.reachable});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: reachable
            ? AppTheme.accent.withValues(alpha: 0.15)
            : AppTheme.danger.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: (reachable ? AppTheme.accent : AppTheme.danger)
              .withValues(alpha: 0.2),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.circle,
              size: 7, color: reachable ? AppTheme.accent : AppTheme.danger),
          const SizedBox(width: 5),
          Text(reachable ? "在线" : "离线",
              style: AppTheme.ts(
                  fontSize: 10,
                  fontWeight: FontWeight.w600,
                  color: reachable ? AppTheme.accent : AppTheme.danger)),
        ],
      ),
    );
  }
}

class _HealthDot extends StatelessWidget {
  final bool reachable;

  const _HealthDot({required this.reachable});

  @override
  Widget build(BuildContext context) {
    final color = reachable ? AppTheme.accent : AppTheme.danger;
    return Tooltip(
      message: reachable ? "在线" : "离线",
      child: Container(
        width: 34,
        height: 34,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: color.withValues(alpha: 0.2)),
        ),
        child: Icon(Icons.circle, size: 8, color: color),
      ),
    );
  }
}

class _HeaderButton extends StatelessWidget {
  final IconData icon;
  final bool active;
  final VoidCallback? onTap;
  final String? tooltip;
  final String? label;
  final double size;

  const _HeaderButton({
    required this.icon,
    required this.onTap,
    this.active = false,
    this.tooltip,
    this.label,
    this.size = 38,
  });

  @override
  Widget build(BuildContext context) {
    final normalizedLabel = label?.trim() ?? "";
    final hasLabel = normalizedLabel.isNotEmpty;
    final button = Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: Container(
          width: hasLabel ? null : size,
          constraints: BoxConstraints(minWidth: size),
          height: size,
          padding: hasLabel ? const EdgeInsets.symmetric(horizontal: 10) : null,
          decoration: BoxDecoration(
            color: active
                ? AppTheme.accent.withValues(alpha: 0.16)
                : AppTheme.surface.withValues(alpha: 0.92),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: active
                  ? AppTheme.accent.withValues(alpha: 0.3)
                  : AppTheme.border,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                icon,
                size: 17,
                color: active ? AppTheme.accent : AppTheme.textSecondary,
              ),
              if (hasLabel) ...[
                const SizedBox(width: 6),
                Text(
                  normalizedLabel,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w800,
                    color: active ? AppTheme.accent : AppTheme.textSecondary,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
    if (tooltip == null || tooltip!.isEmpty) {
      return button;
    }
    return Tooltip(message: tooltip!, child: button);
  }
}

// ── Welcome screen ──────────────────────────────────────────────────────

class _WelcomeScreen extends ConsumerWidget {
  const _WelcomeScreen();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Align(
      alignment: Alignment.topCenter,
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(32, 104, 32, 132),
        child: Container(
          constraints: const BoxConstraints(maxWidth: _messageRailMaxWidth),
          padding: const EdgeInsets.symmetric(horizontal: 6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [Color(0xFFE7F7F0), Color(0xFFF6FFFB)],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(
                        color: AppTheme.accent.withValues(alpha: 0.12),
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: AppTheme.accent.withValues(alpha: 0.12),
                          blurRadius: 22,
                          offset: const Offset(0, 10),
                        ),
                      ],
                    ),
                    child: Center(
                      child: Icon(
                        Icons.auto_awesome_rounded,
                        size: 30,
                        color: AppTheme.accent,
                      ),
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          "你好！我是求职 Agent 助手",
                          style: AppTheme.ts(
                            fontSize: 24,
                            fontWeight: FontWeight.w800,
                            color: AppTheme.textPrimary,
                            height: 1.25,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          "我可以帮你规划学习任务、分析岗位、优化简历、准备面试，陪你一起拿下 Offer。",
                          style: AppTheme.ts(
                            fontSize: 14,
                            color: AppTheme.textSecondary,
                            height: 1.55,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 28),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  _QuickPrompt(
                    icon: Icons.upload_file_outlined,
                    text: "上传简历",
                    onSend: (t) => ref.read(chatProvider).sendMessage(t),
                  ),
                  _QuickPrompt(
                    icon: Icons.link_rounded,
                    text: "分析 JD",
                    onSend: (t) => ref.read(chatProvider).sendMessage(t),
                  ),
                  _QuickPrompt(
                    icon: Icons.add_circle_outline_rounded,
                    text: "创建学习任务",
                    onSend: (t) => ref.read(chatProvider).sendMessage(t),
                  ),
                ],
              ),
              const SizedBox(height: 22),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 18,
                  vertical: 16,
                ),
                decoration: BoxDecoration(
                  color: AppTheme.surface.withValues(alpha: 0.86),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppTheme.border),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.04),
                      blurRadius: 18,
                      offset: const Offset(0, 8),
                    ),
                  ],
                ),
                child: const Column(
                  children: [
                    _WelcomeFeature(
                      icon: Icons.badge_outlined,
                      text: "解析简历并生成画像、诊断报告和改进建议",
                    ),
                    SizedBox(height: 10),
                    _WelcomeFeature(
                      icon: Icons.work_outline_rounded,
                      text: "基于目标 JD 生成岗位分析、匹配报告和定制版本",
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WelcomeFeature extends StatelessWidget {
  final IconData icon;
  final String text;

  const _WelcomeFeature({
    required this.icon,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 28,
          height: 28,
          decoration: BoxDecoration(
            color: AppTheme.accent.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Icon(icon, size: 15, color: AppTheme.accent),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            text,
            style: AppTheme.ts(
              fontSize: 12.5,
              color: AppTheme.textSecondary,
              height: 1.45,
            ),
          ),
        ),
      ],
    );
  }
}

class _QuickPrompt extends StatelessWidget {
  final IconData icon;
  final String text;
  final Function(String) onSend;

  const _QuickPrompt({
    required this.icon,
    required this.text,
    required this.onSend,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => onSend(text),
        child: Container(
          height: 40,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.94),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.border),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.03),
                blurRadius: 12,
                offset: const Offset(0, 6),
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(icon, size: 13, color: AppTheme.accent),
              ),
              const SizedBox(width: 8),
              Text(text,
                  style: AppTheme.ts(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.textPrimary)),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Message list ────────────────────────────────────────────────────────

class _MessageList extends StatefulWidget {
  final List<ChatMessage> messages;
  final ScrollController scrollCtrl;
  final bool isStreaming;
  final String streamBuffer;
  final String streamAnswerFormat;
  final String streamRenderHint;
  final String streamLayoutHint;
  final String streamReasoningBuffer;
  final List<AnswerArtifactView> streamArtifacts;
  final List<EventView> streamEvents;
  final String? error;
  final VoidCallback onClearError;
  final ChatBubbleStyle messageStyle;

  const _MessageList({
    required this.messages,
    required this.scrollCtrl,
    required this.isStreaming,
    required this.streamBuffer,
    required this.streamAnswerFormat,
    required this.streamRenderHint,
    required this.streamLayoutHint,
    required this.streamReasoningBuffer,
    required this.streamArtifacts,
    required this.streamEvents,
    required this.error,
    required this.onClearError,
    required this.messageStyle,
  });

  @override
  State<_MessageList> createState() => _MessageListState();
}

class _MessageListState extends State<_MessageList> {
  @override
  Widget build(BuildContext context) {
    final extraItems =
        (widget.isStreaming ? 1 : 0) + (widget.error != null ? 1 : 0);
    final itemCount = widget.messages.length + extraItems;

    return ListView.builder(
      controller: widget.scrollCtrl,
      padding: const EdgeInsets.fromLTRB(
        18,
        _messageListTopPadding,
        18,
        _messageListBottomPadding,
      ),
      itemCount: itemCount,
      itemBuilder: (_, i) {
        Widget child;
        // Error at top
        if (widget.error != null && i == 0) {
          child = _ErrorBanner(
            message: widget.error!,
            onDismiss: widget.onClearError,
          );
        } else {
          final msgIdx = widget.error != null ? i - 1 : i;

          // Streaming bubble at the end
          if (widget.isStreaming && msgIdx == widget.messages.length) {
            child = StreamingBubble(
              buffer: widget.streamBuffer,
              answerFormat: widget.streamAnswerFormat,
              renderHint: widget.streamRenderHint,
              layoutHint: widget.streamLayoutHint,
              reasoningBuffer: widget.streamReasoningBuffer,
              artifacts: widget.streamArtifacts,
              progressEvents: _buildProgressEvents(widget.streamEvents),
              thinkingLines: _buildThinkingLines(widget.streamEvents),
              style: widget.messageStyle,
            );
          } else if (msgIdx < widget.messages.length) {
            // Regular messages
            child = ChatBubble(
              message: widget.messages[msgIdx],
              style: widget.messageStyle,
            );
          } else {
            child = const SizedBox.shrink();
          }
        }

        return Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: _messageRailMaxWidth),
            child: child,
          ),
        );
      },
    );
  }

  List<String> _buildThinkingLines(List<EventView> events) {
    final lines = <String>[];
    for (final e in events) {
      final time = DateFormat("HH:mm:ss").format(e.createdAt);
      switch (e.type) {
        case "assistant_thinking":
          final content = (e.payload["content"] ?? "").toString();
          final short = content.length > 120
              ? "${content.substring(0, 120)}..."
              : content;
          lines.add("[$time] 模型思考: $short");
          break;
        case "tool_call":
          final name = e.payload["name"] ?? "unknown";
          lines.add("[$time] 调用工具 $name");
          break;
        case "tool_result":
          final name = e.payload["tool_name"] ?? "unknown";
          final ok = e.payload["success"] == true ? "成功" : "失败";
          lines.add("[$time] 工具$ok $name");
          break;
      }
    }
    return lines;
  }

  List<EventView> _buildProgressEvents(List<EventView> events) {
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
}

class _MessageBottomFade extends StatelessWidget {
  final Widget child;

  const _MessageBottomFade({required this.child});

  @override
  Widget build(BuildContext context) {
    return ShaderMask(
      blendMode: BlendMode.dstIn,
      shaderCallback: (bounds) {
        final fadeStart =
            ((bounds.height - _messageBottomContentFadeHeight) / bounds.height)
                .clamp(0.0, 1.0)
                .toDouble();
        return LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: const [
            Colors.white,
            Colors.white,
            Colors.transparent,
          ],
          stops: [0, fadeStart, 1],
        ).createShader(bounds);
      },
      child: child,
    );
  }
}

bool _stringListEquals(List<String> left, List<String> right) {
  if (identical(left, right)) {
    return true;
  }
  if (left.length != right.length) {
    return false;
  }
  for (var index = 0; index < left.length; index++) {
    if (left[index] != right[index]) {
      return false;
    }
  }
  return true;
}

bool _skillOptionListEquals(List<SkillOption> left, List<SkillOption> right) {
  if (identical(left, right)) {
    return true;
  }
  if (left.length != right.length) {
    return false;
  }
  for (var index = 0; index < left.length; index++) {
    if (left[index].name != right[index].name ||
        left[index].description != right[index].description) {
      return false;
    }
  }
  return true;
}

bool _sessionArtifactListEquals(
  List<SessionArtifactView> left,
  List<SessionArtifactView> right,
) {
  if (identical(left, right)) {
    return true;
  }
  if (left.length != right.length) {
    return false;
  }
  for (var index = 0; index < left.length; index++) {
    final leftItem = left[index];
    final rightItem = right[index];
    if (leftItem.artifactId != rightItem.artifactId ||
        leftItem.title != rightItem.title ||
        leftItem.mediaType != rightItem.mediaType ||
        leftItem.sizeBytes != rightItem.sizeBytes ||
        leftItem.status != rightItem.status ||
        leftItem.error != rightItem.error ||
        leftItem.textCharCount != rightItem.textCharCount ||
        leftItem.tokenEstimate != rightItem.tokenEstimate ||
        leftItem.createdAt != rightItem.createdAt) {
      return false;
    }
  }
  return true;
}

class _ComposerDock extends StatelessWidget {
  final Widget child;

  const _ComposerDock({required this.child});

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            AppTheme.bg.withValues(alpha: 0),
            AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.9 : 0.96),
          ],
          stops: const [0, 0.34],
        ),
      ),
      child: child,
    );
  }
}

// ── Error banner ────────────────────────────────────────────────────────

class _ErrorBanner extends StatelessWidget {
  final String message;
  final VoidCallback onDismiss;
  const _ErrorBanner({required this.message, required this.onDismiss});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.danger.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.danger.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline_rounded, size: 16, color: AppTheme.danger),
          const SizedBox(width: 10),
          Expanded(
            child: Text(message,
                style: AppTheme.ts(fontSize: 13, color: AppTheme.danger)),
          ),
          SizedBox(
            width: 24,
            height: 24,
            child: IconButton(
              padding: EdgeInsets.zero,
              iconSize: 14,
              icon: Icon(Icons.close_rounded, color: AppTheme.danger),
              onPressed: onDismiss,
            ),
          ),
        ],
      ),
    );
  }
}
