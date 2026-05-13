import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/utils/download_stub.dart'
    if (dart.library.html) '../../shared/utils/download_web.dart';
import '../../shared/widgets/markdown_body.dart';
import 'career_workbench_provider.dart';

typedef WorkbenchPromptSender = Future<void> Function(String prompt);

class CareerWorkbenchPage extends ConsumerStatefulWidget {
  final VoidCallback onBackToChat;
  final WorkbenchPromptSender? onSendPrompt;

  const CareerWorkbenchPage({
    super.key,
    required this.onBackToChat,
    this.onSendPrompt,
  });

  @override
  ConsumerState<CareerWorkbenchPage> createState() =>
      _CareerWorkbenchPageState();
}

class _CareerWorkbenchPageState extends ConsumerState<CareerWorkbenchPage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(careerWorkbenchProvider).ensureLoaded());
  }

  @override
  Widget build(BuildContext context) {
    final provider = ref.watch(careerWorkbenchProvider);
    final currentSessionId = ref.watch(
      chatProvider.select((provider) => provider.sessionId),
    );
    return Container(
      decoration: AppTheme.floatingPanelDecoration(radius: 30, alpha: 0.78),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          _WorkbenchTopBar(
            provider: provider,
            onBackToChat: widget.onBackToChat,
            onRefresh: () => unawaited(provider.refresh()),
          ),
          Expanded(
            child: _WorkbenchShell(
              provider: provider,
              currentSessionId: currentSessionId,
              onBackToChat: widget.onBackToChat,
              onSendPrompt: widget.onSendPrompt,
            ),
          ),
        ],
      ),
    );
  }
}

class _WorkbenchTopBar extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final VoidCallback onBackToChat;
  final VoidCallback onRefresh;

  const _WorkbenchTopBar({
    required this.provider,
    required this.onBackToChat,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    final counts = provider.workbench?.counts;
    final subtitle = counts == null
        ? "项目 · 笔记 · 学习计划"
        : "${counts.applications} 个项目 · ${counts.notes} 条笔记 · ${counts.learningTasks} 个学习任务";
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 16, 12),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: AppTheme.accent.withValues(alpha: 0.13),
              borderRadius: BorderRadius.circular(14),
              border:
                  Border.all(color: AppTheme.accent.withValues(alpha: 0.22)),
            ),
            child: Icon(
              Icons.space_dashboard_outlined,
              size: 19,
              color: AppTheme.accent,
            ),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  "求职工作台",
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 16,
                    fontWeight: FontWeight.w900,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.textTertiary,
                  ),
                ),
              ],
            ),
          ),
          _WorkbenchTopAction(
            label: "返回聊天",
            icon: Icons.chat_bubble_outline_rounded,
            onTap: onBackToChat,
          ),
          const SizedBox(width: 8),
          _WorkbenchIconButton(
            icon: provider.isRefreshing
                ? Icons.hourglass_top_rounded
                : Icons.refresh_rounded,
            tooltip: "刷新工作台",
            onTap: onRefresh,
          ),
        ],
      ),
    );
  }
}

class _WorkbenchShell extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final String? currentSessionId;
  final VoidCallback onBackToChat;
  final WorkbenchPromptSender? onSendPrompt;

  const _WorkbenchShell({
    required this.provider,
    required this.currentSessionId,
    required this.onBackToChat,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    if (provider.isLoading && !provider.hasLoaded) {
      return const _WorkbenchLoading();
    }
    if (provider.error != null && !provider.hasLoaded) {
      return _WorkbenchError(
        error: provider.error!,
        onRetry: () => unawaited(provider.refresh()),
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 980;
        if (compact) {
          return Column(
            children: [
              _WorkbenchHorizontalNav(provider: provider),
              Expanded(
                child: _WorkbenchMainPane(
                  provider: provider,
                  currentSessionId: currentSessionId,
                  compact: true,
                  onBackToChat: onBackToChat,
                  onSendPrompt: onSendPrompt,
                ),
              ),
            ],
          );
        }
        return Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(width: 188, child: _WorkbenchNav(provider: provider)),
              const SizedBox(width: 12),
              Expanded(
                child: _WorkbenchMainPane(
                  provider: provider,
                  currentSessionId: currentSessionId,
                  compact: false,
                  onBackToChat: onBackToChat,
                  onSendPrompt: onSendPrompt,
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                width: constraints.maxWidth < 1220 ? 350 : 390,
                child: _ProjectDetailPane(
                  provider: provider,
                  currentSessionId: currentSessionId,
                  onBackToChat: onBackToChat,
                  onSendPrompt: onSendPrompt,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _WorkbenchNav extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _WorkbenchNav({required this.provider});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: _workbenchPanelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final tab in CareerWorkbenchTab.values) ...[
            _WorkbenchNavItem(
              tab: tab,
              selected: provider.activeTab == tab,
              count: _tabCount(provider, tab),
              onTap: () => provider.setTab(tab),
            ),
            if (tab != CareerWorkbenchTab.values.last)
              const SizedBox(height: 6),
          ],
          const Spacer(),
          _WorkbenchHintBox(
            title: "工作台模式",
            body: "长期资产在这里管理；任务执行仍回到聊天里展示过程。",
          ),
        ],
      ),
    );
  }
}

class _WorkbenchHorizontalNav extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _WorkbenchHorizontalNav({required this.provider});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 58,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
        scrollDirection: Axis.horizontal,
        children: [
          for (final tab in CareerWorkbenchTab.values) ...[
            _WorkbenchNavChip(
              tab: tab,
              selected: provider.activeTab == tab,
              count: _tabCount(provider, tab),
              onTap: () => provider.setTab(tab),
            ),
            const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }
}

class _WorkbenchMainPane extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final String? currentSessionId;
  final bool compact;
  final VoidCallback onBackToChat;
  final WorkbenchPromptSender? onSendPrompt;

  const _WorkbenchMainPane({
    required this.provider,
    required this.currentSessionId,
    required this.compact,
    required this.onBackToChat,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final child = switch (provider.activeTab) {
      CareerWorkbenchTab.overview => _OverviewView(provider: provider),
      CareerWorkbenchTab.projects => _ProjectListView(provider: provider),
      CareerWorkbenchTab.resumes => _LibraryPlaceholder(
          icon: Icons.badge_outlined,
          title: "简历资料",
          body: "M14-4 会把原始简历、简历画像、诊断报告和定制简历版本集中到这里。",
        ),
      CareerWorkbenchTab.jobs => _LibraryPlaceholder(
          icon: Icons.fact_check_outlined,
          title: "JD 与匹配",
          body: "M14-4 会按公司和岗位管理 JD 分析、匹配报告与可预览 artifact。",
        ),
      CareerWorkbenchTab.learning => _LearningOverview(provider: provider),
      CareerWorkbenchTab.notes => _NotesOverview(
          provider: provider,
          currentSessionId: currentSessionId,
        ),
    };
    if (!compact) {
      return child;
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final detailPane = _ProjectDetailPane(
          provider: provider,
          currentSessionId: currentSessionId,
          onBackToChat: onBackToChat,
          onSendPrompt: onSendPrompt,
        );
        if (constraints.maxWidth < 760) {
          return Column(
            children: [
              Expanded(child: child),
              const SizedBox(height: 10),
              SizedBox(height: 340, child: detailPane),
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: child),
            const SizedBox(width: 10),
            SizedBox(width: 330, child: detailPane),
          ],
        );
      },
    );
  }
}

class _OverviewView extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _OverviewView({required this.provider});

  @override
  Widget build(BuildContext context) {
    final counts = provider.workbench?.counts;
    final apps = provider.applications.take(4).toList();
    return ListView(
      padding: EdgeInsets.zero,
      children: [
        _OverviewMetricRow(
          metrics: [
            _OverviewMetric(
              label: "求职项目",
              value: counts?.applications ?? 0,
              icon: Icons.work_history_outlined,
              color: AppTheme.accent,
            ),
            _OverviewMetric(
              label: "学习任务",
              value: counts?.learningTasks ?? 0,
              icon: Icons.school_outlined,
              color: const Color(0xFF2563EB),
            ),
            _OverviewMetric(
              label: "项目笔记",
              value: counts?.notes ?? 0,
              icon: Icons.sticky_note_2_outlined,
              color: const Color(0xFFB45309),
            ),
            _OverviewMetric(
              label: "简历版本",
              value: counts?.resumeVersions ?? 0,
              icon: Icons.description_outlined,
              color: const Color(0xFF7C3AED),
            ),
          ],
        ),
        const SizedBox(height: 12),
        _WorkbenchSection(
          icon: Icons.priority_high_rounded,
          title: "当前最该处理",
          subtitle: "按更新时间和项目准备度排序",
          child: apps.isEmpty
              ? const _EmptyText("暂无求职项目。")
              : Column(
                  children: [
                    for (final item in apps) ...[
                      _ProjectSummaryTile(
                        summary: item,
                        selected: item.application.applicationId ==
                            provider.selectedApplicationId,
                        onTap: () => unawaited(
                          provider.selectApplication(
                            item.application.applicationId,
                          ),
                        ),
                      ),
                      if (item != apps.last) const SizedBox(height: 8),
                    ],
                  ],
                ),
        ),
      ],
    );
  }
}

class _ProjectListView extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _ProjectListView({required this.provider});

  @override
  Widget build(BuildContext context) {
    final records = provider.filteredApplications;
    return Container(
      decoration: _workbenchPanelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 14, 14, 10),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        "求职项目",
                        style: AppTheme.ts(
                          fontSize: 16,
                          fontWeight: FontWeight.w900,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        "围绕目标岗位管理画像、JD、报告、笔记和学习任务",
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.5,
                          color: AppTheme.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
                _TinyStatus(label: "${records.length} 个项目"),
              ],
            ),
          ),
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
              children: [
                for (final filter in CareerProjectFilter.values) ...[
                  _FilterChipButton(
                    label: _projectFilterLabel(filter),
                    selected: provider.projectFilter == filter,
                    onTap: () => provider.setProjectFilter(filter),
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          Expanded(
            child: records.isEmpty
                ? const Center(child: _EmptyText("当前筛选下暂无项目。"))
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                    itemBuilder: (context, index) {
                      final item = records[index];
                      return _ProjectCard(
                        summary: item,
                        selected: item.application.applicationId ==
                            provider.selectedApplicationId,
                        onTap: () => unawaited(
                          provider.selectApplication(
                            item.application.applicationId,
                          ),
                        ),
                      );
                    },
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemCount: records.length,
                  ),
          ),
        ],
      ),
    );
  }
}

class _LearningOverview extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _LearningOverview({required this.provider});

  @override
  Widget build(BuildContext context) {
    final detail = provider.selectedApplicationDetail;
    final learning = detail?.learning;
    final tasks = learning?.tasks.take(8).toList() ?? const [];
    final weaknesses = learning?.weaknesses.take(6).toList() ?? const [];
    return _WorkbenchSection(
      icon: Icons.school_outlined,
      title: "学习计划",
      subtitle: "M14-3 会升级为完整学习任务管理页",
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (tasks.isEmpty && weaknesses.isEmpty)
            const _EmptyText("当前选中项目暂无学习任务或短板记录。"),
          for (final task in tasks) ...[
            _CompactRecordTile(
              icon: Icons.checklist_rounded,
              color: _priorityColor(task.priority),
              title: task.title,
              subtitle: _firstNonEmpty([task.description, task.progressNotes]),
              meta: _taskStateLabel(task.state),
            ),
            const SizedBox(height: 8),
          ],
          for (final weakness in weaknesses)
            _CompactRecordTile(
              icon: Icons.report_problem_outlined,
              color: weakness.severity == "high"
                  ? AppTheme.danger
                  : const Color(0xFFB45309),
              title: weakness.title,
              subtitle: weakness.description,
              meta: _weaknessSeverityLabel(weakness.severity),
            ),
        ],
      ),
    );
  }
}

class _NotesOverview extends StatefulWidget {
  final CareerWorkbenchProvider provider;
  final String? currentSessionId;

  const _NotesOverview({
    required this.provider,
    required this.currentSessionId,
  });

  @override
  State<_NotesOverview> createState() => _NotesOverviewState();
}

class _NotesOverviewState extends State<_NotesOverview> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => widget.provider.loadNotes());
  }

  @override
  Widget build(BuildContext context) {
    final provider = widget.provider;
    final notes = provider.notes;
    return Container(
      decoration: _workbenchPanelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 14, 14, 10),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        "笔记库",
                        style: AppTheme.ts(
                          fontSize: 16,
                          fontWeight: FontWeight.w900,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        "沉淀求职复盘、面试记录、学习想法和资产引用",
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.5,
                          color: AppTheme.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
                _SmallTextButton(
                  label: "新建笔记",
                  icon: Icons.add_rounded,
                  onTap: () => _showNewNoteEditorSheet(
                    context,
                    provider,
                    sourceSessionId: _noteSourceSessionId(
                      provider,
                      widget.currentSessionId,
                    ),
                    relatedApplicationId: provider
                        .selectedApplicationSummary?.application.applicationId,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: provider.isLoadingNotes && notes.isEmpty
                ? const Center(child: _WorkbenchLoading())
                : provider.notesError != null && notes.isEmpty
                    ? Padding(
                        padding: const EdgeInsets.all(14),
                        child: _EmptyText("笔记读取失败：${provider.notesError}"),
                      )
                    : notes.isEmpty
                        ? const Padding(
                            padding: EdgeInsets.all(14),
                            child: _EmptyText("还没有笔记。可以先新建一条自由笔记。"),
                          )
                        : ListView.separated(
                            padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                            itemBuilder: (context, index) {
                              final note = notes[index];
                              return _NoteSummaryTile(
                                provider: provider,
                                note: _summaryFromNote(note),
                              );
                            },
                            separatorBuilder: (_, __) =>
                                const SizedBox(height: 9),
                            itemCount: notes.length,
                          ),
          ),
        ],
      ),
    );
  }
}

class _ProjectDetailPane extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final String? currentSessionId;
  final VoidCallback onBackToChat;
  final WorkbenchPromptSender? onSendPrompt;

  const _ProjectDetailPane({
    required this.provider,
    required this.currentSessionId,
    required this.onBackToChat,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final summary = provider.selectedApplicationSummary;
    final detail = provider.selectedApplicationDetail;
    if (summary == null) {
      return const _DetailEmptyPane();
    }
    final applicationId = summary.application.applicationId;
    if (provider.isApplicationLoading(applicationId) && detail == null) {
      return const _DetailLoadingPane();
    }
    final error = provider.detailError(applicationId);
    if (error != null && detail == null) {
      return _DetailErrorPane(
        error: error,
        onRetry: () => unawaited(
          provider.loadApplicationDetail(applicationId, force: true),
        ),
      );
    }
    final view = detail;
    if (view == null) {
      return _DetailSkeletonFromSummary(summary: summary);
    }
    return Container(
      decoration: _workbenchPanelDecoration(),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
        children: [
          _ProjectDetailHeader(view: view),
          const SizedBox(height: 12),
          _DetailJudgmentCard(readiness: view.readiness),
          const SizedBox(height: 12),
          _DetailActionSection(
            view: view,
            onBackToChat: onBackToChat,
            onSendPrompt: onSendPrompt,
          ),
          const SizedBox(height: 12),
          _DetailLinkedAssets(
            provider: provider,
            application: view.application,
            currentSessionId: currentSessionId,
            assets: view.linkedAssets,
          ),
          const SizedBox(height: 12),
          _DetailRiskSection(readiness: view.readiness),
          const SizedBox(height: 12),
          _DetailNotesSection(
            provider: provider,
            currentSessionId: currentSessionId,
            application: view.application,
            notes: view.notes,
          ),
        ],
      ),
    );
  }
}

class _ProjectDetailHeader extends StatelessWidget {
  final CareerApplicationWorkbenchView view;

  const _ProjectDetailHeader({required this.view});

  @override
  Widget build(BuildContext context) {
    final app = view.application;
    return Container(
      padding: const EdgeInsets.fromLTRB(13, 13, 13, 13),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppTheme.accent.withValues(alpha: 0.12),
            const Color(0xFF38BDF8).withValues(alpha: 0.12),
            AppTheme.surface.withValues(alpha: 0.68),
          ],
        ),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.18)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 7,
                  runSpacing: 7,
                  children: [
                    _MetaPill(
                      icon: Icons.flag_outlined,
                      label: _stageLabel(app.stage),
                      color: AppTheme.accent,
                    ),
                    _MetaPill(
                      icon: Icons.priority_high_rounded,
                      label: _priorityLabel(app.priority),
                      color: _priorityColor(app.priority),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  app.displayTitle,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 16,
                    height: 1.22,
                    fontWeight: FontWeight.w900,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  _firstNonEmpty([
                    view.readiness.summary,
                    app.summary,
                    "当前项目仍在整理中。",
                  ]),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.8,
                    height: 1.45,
                    color: AppTheme.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          _ScoreRing(score: view.readiness.score),
        ],
      ),
    );
  }
}

class _DetailJudgmentCard extends StatelessWidget {
  final CareerReadinessView readiness;

  const _DetailJudgmentCard({required this.readiness});

  @override
  Widget build(BuildContext context) {
    final strengths = readiness.strengths.take(4).toList();
    return _WorkbenchSection(
      icon: Icons.fact_check_outlined,
      title: "当前判断",
      subtitle: _recommendationLabel(readiness.recommendation),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (readiness.summary.trim().isNotEmpty)
            Text(
              readiness.summary.trim(),
              style: AppTheme.ts(
                fontSize: 12.2,
                height: 1.5,
                fontWeight: FontWeight.w700,
                color: AppTheme.textPrimary,
              ),
            ),
          if (strengths.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                for (final item in strengths)
                  _TinyTag(
                    label: _compactLabel(item),
                    color: AppTheme.accent,
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _DetailActionSection extends StatelessWidget {
  final CareerApplicationWorkbenchView view;
  final VoidCallback onBackToChat;
  final WorkbenchPromptSender? onSendPrompt;

  const _DetailActionSection({
    required this.view,
    required this.onBackToChat,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final actions = view.suggestedActions.take(4).toList();
    return _WorkbenchSection(
      icon: Icons.auto_awesome_rounded,
      title: "推荐下一步",
      subtitle: "动作会回到聊天中执行",
      child: actions.isEmpty
          ? const _EmptyText("暂无推荐动作。")
          : Column(
              children: [
                for (final action in actions) ...[
                  _ActionTile(
                    action: action,
                    onTap: () => _sendSuggestedAction(context, action),
                  ),
                  if (action != actions.last) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }

  Future<void> _sendSuggestedAction(
    BuildContext context,
    CareerSuggestedActionView action,
  ) async {
    final sender = onSendPrompt;
    final messenger = ScaffoldMessenger.maybeOf(context);
    if (sender == null) {
      messenger?.showSnackBar(
        const SnackBar(content: Text("当前入口暂不可用")),
      );
      return;
    }
    final prompt = _promptForAction(action, view.application);
    onBackToChat();
    await sender(prompt);
  }
}

class _DetailLinkedAssets extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationView application;
  final String? currentSessionId;
  final List<CareerLinkedAssetView> assets;

  const _DetailLinkedAssets({
    required this.provider,
    required this.application,
    required this.currentSessionId,
    required this.assets,
  });

  @override
  Widget build(BuildContext context) {
    final visible = assets.take(6).toList();
    return _WorkbenchSection(
      icon: Icons.folder_copy_outlined,
      title: "关联资产",
      subtitle: "${visible.length} 个可查看资料",
      child: visible.isEmpty
          ? const _EmptyText("暂无关联资产。")
          : Column(
              children: [
                for (final asset in visible) ...[
                  _LinkedAssetTile(
                    provider: provider,
                    currentSessionId: currentSessionId,
                    relatedApplicationId: application.applicationId,
                    asset: asset,
                  ),
                  if (asset != visible.last) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _DetailRiskSection extends StatelessWidget {
  final CareerReadinessView readiness;

  const _DetailRiskSection({required this.readiness});

  @override
  Widget build(BuildContext context) {
    final risks = readiness.risks.take(4).toList();
    return _WorkbenchSection(
      icon: Icons.warning_amber_rounded,
      title: "主要风险",
      subtitle: "${risks.length} 个待处理阻碍",
      child: risks.isEmpty
          ? const _EmptyText("暂无风险记录。")
          : Column(
              children: [
                for (final risk in risks) ...[
                  _RiskTile(text: risk),
                  if (risk != risks.last) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _DetailNotesSection extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final String? currentSessionId;
  final CareerApplicationView application;
  final List<CareerNoteSummaryView> notes;

  const _DetailNotesSection({
    required this.provider,
    required this.currentSessionId,
    required this.application,
    required this.notes,
  });

  @override
  Widget build(BuildContext context) {
    final visible = notes.take(4).toList();
    return _WorkbenchSection(
      icon: Icons.sticky_note_2_outlined,
      title: "项目笔记",
      subtitle: "${visible.length} 条上下文 · 点击笔记进入编辑",
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SmallTextButton(
            label: "新建项目笔记",
            icon: Icons.add_rounded,
            onTap: () => _showNewNoteEditorSheet(
              context,
              provider,
              sourceSessionId: _noteSourceSessionId(
                provider,
                currentSessionId,
              ),
              relatedApplicationId: application.applicationId,
              seedTitle: "${application.displayTitle} 笔记",
              seedSummary: application.summary,
              evidenceRefs: [application.applicationId],
            ),
          ),
          if (visible.isEmpty) ...[
            const SizedBox(height: 8),
            const _EmptyText("暂无关联笔记。"),
          ] else ...[
            const SizedBox(height: 10),
            for (final note in visible) ...[
              _NoteSummaryTile(
                provider: provider,
                note: note,
              ),
              if (note != visible.last) const SizedBox(height: 8),
            ],
          ],
        ],
      ),
    );
  }
}

class _ProjectCard extends StatelessWidget {
  final CareerApplicationSummaryView summary;
  final bool selected;
  final VoidCallback onTap;

  const _ProjectCard({
    required this.summary,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final app = summary.application;
    final score = summary.readiness.score;
    final risk = summary.readiness.risks.isEmpty
        ? "暂无高优先级风险"
        : summary.readiness.risks.first;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.fromLTRB(14, 13, 14, 13),
          decoration: BoxDecoration(
            color: selected
                ? AppTheme.accent.withValues(alpha: 0.08)
                : AppTheme.surface.withValues(alpha: 0.7),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: selected
                  ? AppTheme.accent.withValues(alpha: 0.26)
                  : AppTheme.border.withValues(alpha: 0.82),
            ),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 7,
                      runSpacing: 7,
                      children: [
                        _MetaPill(
                          icon: Icons.flag_outlined,
                          label: _stageLabel(app.stage),
                          color: AppTheme.accent,
                        ),
                        _MetaPill(
                          icon: Icons.priority_high_rounded,
                          label: _priorityLabel(app.priority),
                          color: _priorityColor(app.priority),
                        ),
                        _MetaPill(
                          icon: Icons.inventory_2_outlined,
                          label: "${summary.linkedAssetCount} 项资产",
                          color: AppTheme.textSecondary,
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Text(
                      app.displayTitle,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 14.2,
                        height: 1.25,
                        fontWeight: FontWeight.w900,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 7),
                    Text(
                      risk,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.7,
                        height: 1.45,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      "更新 ${_formatTime(summary.updatedAt)}",
                      style: AppTheme.ts(
                        fontSize: 10.5,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              _ScoreRing(score: score),
            ],
          ),
        ),
      ),
    );
  }
}

class _ProjectSummaryTile extends StatelessWidget {
  final CareerApplicationSummaryView summary;
  final bool selected;
  final VoidCallback onTap;

  const _ProjectSummaryTile({
    required this.summary,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return _CompactRecordTile(
      icon: Icons.work_history_outlined,
      color: selected ? AppTheme.accent : AppTheme.textSecondary,
      title: summary.application.displayTitle,
      subtitle: _firstNonEmpty([
        summary.readiness.summary,
        summary.application.summary,
      ]),
      meta: summary.readiness.score == null
          ? _stageLabel(summary.application.stage)
          : "${summary.readiness.score} 分",
      onTap: onTap,
    );
  }
}

class _LinkedAssetTile extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final String? currentSessionId;
  final String? relatedApplicationId;
  final CareerLinkedAssetView asset;

  const _LinkedAssetTile({
    required this.provider,
    required this.currentSessionId,
    required this.relatedApplicationId,
    required this.asset,
  });

  @override
  Widget build(BuildContext context) {
    final color = _assetColor(asset.type);
    final canPreview = (asset.previewArtifactId?.trim().isNotEmpty ?? false) &&
        (asset.sourceSessionId?.trim().isNotEmpty ?? false);
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.045),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withValues(alpha: 0.13)),
      ),
      child: Row(
        children: [
          Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(_assetIcon(asset.type), size: 16, color: color),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  asset.subtitle.trim().isEmpty
                      ? _assetTypeLabel(asset.type)
                      : asset.subtitle.trim(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w900,
                    color: color,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  asset.title.trim().isEmpty ? asset.id : asset.title.trim(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.8,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ],
            ),
          ),
          if (canPreview) ...[
            const SizedBox(width: 8),
            _SmallTextButton(
              label: "预览",
              icon: Icons.visibility_outlined,
              onTap: () => _showArtifactPreviewSheet(
                context,
                provider,
                sourceSessionId: asset.sourceSessionId!.trim(),
                artifactId: asset.previewArtifactId!.trim(),
              ),
            ),
          ],
          const SizedBox(width: 8),
          _SmallTextButton(
            label: "引用",
            icon: Icons.add_link_rounded,
            onTap: () => _showNewNoteEditorSheet(
              context,
              provider,
              sourceSessionId: _noteSourceSessionId(
                provider,
                currentSessionId,
                fallback: asset.sourceSessionId,
              ),
              sourceArtifactId:
                  asset.type == "artifact" ? asset.id : asset.previewArtifactId,
              relatedApplicationId: relatedApplicationId,
              seedTitle:
                  "关于 ${asset.title.trim().isEmpty ? _assetTypeLabel(asset.type) : asset.title.trim()} 的笔记",
              seedSummary: "引用 ${_assetTypeLabel(asset.type)} 作为资料来源。",
              seedBody: _assetNoteSeedBody(asset),
              evidenceRefs: _assetEvidenceRefs(asset, relatedApplicationId),
              sourceRefs: [_assetSourceRef(asset)],
            ),
          ),
        ],
      ),
    );
  }
}

class _ActionTile extends StatelessWidget {
  final CareerSuggestedActionView action;
  final VoidCallback onTap;

  const _ActionTile({
    required this.action,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = _priorityColor(action.priority);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: action.enabled ? onTap : null,
        child: Opacity(
          opacity: action.enabled ? 1 : 0.56,
          child: Container(
            padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.055),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: color.withValues(alpha: 0.14)),
            ),
            child: Row(
              children: [
                Icon(_actionIcon(action.actionType), size: 16, color: color),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        action.label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 12,
                          fontWeight: FontWeight.w900,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      if (action.reason.trim().isNotEmpty) ...[
                        const SizedBox(height: 3),
                        Text(
                          action.reason.trim(),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 10.5,
                            color: AppTheme.textTertiary,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _RiskTile extends StatelessWidget {
  final String text;

  const _RiskTile({required this.text});

  @override
  Widget build(BuildContext context) {
    final high = text.contains("高") || text.toLowerCase().contains("high");
    final color = high ? AppTheme.danger : const Color(0xFFB45309);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.055),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withValues(alpha: 0.15)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.warning_amber_rounded, size: 16, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: AppTheme.ts(
                fontSize: 11.5,
                height: 1.42,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _NoteSummaryTile extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerNoteSummaryView note;

  const _NoteSummaryTile({
    required this.provider,
    required this.note,
  });

  @override
  Widget build(BuildContext context) {
    final tags = note.tags.take(3).toList();
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => _showNoteEditorSheet(
          context,
          provider,
          noteId: note.noteId,
        ),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
          decoration: BoxDecoration(
            color: const Color(0xFFB45309).withValues(alpha: 0.045),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: const Color(0xFFB45309).withValues(alpha: 0.13),
            ),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: const Color(0xFFB45309).withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: const Color(0xFFB45309).withValues(alpha: 0.16),
                  ),
                ),
                child: const Icon(
                  Icons.sticky_note_2_outlined,
                  size: 16,
                  color: Color(0xFFB45309),
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            note.title.trim().isEmpty ? "未命名笔记" : note.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 12.4,
                              fontWeight: FontWeight.w900,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          _formatTime(note.updatedAt),
                          style: AppTheme.ts(
                            fontSize: 10.4,
                            fontWeight: FontWeight.w800,
                            color: AppTheme.textTertiary,
                          ),
                        ),
                      ],
                    ),
                    if (note.summary.trim().isNotEmpty) ...[
                      const SizedBox(height: 5),
                      Text(
                        note.summary.trim(),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.2,
                          height: 1.4,
                          color: AppTheme.textSecondary,
                        ),
                      ),
                    ],
                    if (tags.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final tag in tags)
                            _TinyTag(
                              label: tag,
                              color: const Color(0xFFB45309),
                            ),
                        ],
                      ),
                    ],
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Icon(
                          Icons.edit_note_rounded,
                          size: 13,
                          color: AppTheme.textTertiary,
                        ),
                        const SizedBox(width: 5),
                        Text(
                          "点击进入笔记",
                          style: AppTheme.ts(
                            fontSize: 10.5,
                            fontWeight: FontWeight.w800,
                            color: AppTheme.textTertiary,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Icon(
                Icons.chevron_right_rounded,
                size: 18,
                color: AppTheme.textTertiary,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoteEditDraft {
  final String title;
  final String bodyMarkdown;
  final String summary;
  final List<String> tags;

  const _NoteEditDraft({
    required this.title,
    required this.bodyMarkdown,
    required this.summary,
    required this.tags,
  });
}

class _NoteEditorForm extends StatefulWidget {
  final NoteView note;
  final VoidCallback onCancel;
  final Future<void> Function(_NoteEditDraft draft) onSave;

  const _NoteEditorForm({
    required this.note,
    required this.onCancel,
    required this.onSave,
  });

  @override
  State<_NoteEditorForm> createState() => _NoteEditorFormState();
}

class _NoteEditorFormState extends State<_NoteEditorForm> {
  late final TextEditingController _titleController;
  late final TextEditingController _summaryController;
  late final TextEditingController _tagsController;
  late final TextEditingController _bodyController;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.note.title);
    _summaryController = TextEditingController(text: widget.note.summary);
    _tagsController = TextEditingController(text: widget.note.tags.join("，"));
    _bodyController = TextEditingController(text: widget.note.bodyMarkdown);
  }

  @override
  void dispose() {
    _titleController.dispose();
    _summaryController.dispose();
    _tagsController.dispose();
    _bodyController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final title = _titleController.text.trim();
    final body = _bodyController.text.trim();
    if (title.isEmpty) {
      setState(() => _error = "标题不能为空");
      return;
    }
    if (body.isEmpty) {
      setState(() => _error = "正文不能为空");
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onSave(
        _NoteEditDraft(
          title: title,
          bodyMarkdown: body,
          summary: _summaryController.text.trim(),
          tags: _parseTags(_tagsController.text),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = "保存失败：$error";
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 18,
        right: 18,
        top: 16,
        bottom: 16 + MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: Column(
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final titleField = TextField(
                key: const Key("career_note_title_field"),
                controller: _titleController,
                decoration: _noteInputDecoration("标题"),
                style: AppTheme.ts(
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textPrimary,
                ),
              );
              final tagsField = TextField(
                key: const Key("career_note_tags_field"),
                controller: _tagsController,
                decoration: _noteInputDecoration("标签，用逗号分隔"),
                style: AppTheme.ts(
                  fontSize: 12.2,
                  color: AppTheme.textPrimary,
                ),
              );
              if (constraints.maxWidth < 560) {
                return Column(
                  children: [
                    titleField,
                    const SizedBox(height: 10),
                    tagsField,
                  ],
                );
              }
              return Row(
                children: [
                  Expanded(child: titleField),
                  const SizedBox(width: 10),
                  SizedBox(width: 260, child: tagsField),
                ],
              );
            },
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key("career_note_summary_field"),
            controller: _summaryController,
            minLines: 2,
            maxLines: 3,
            decoration: _noteInputDecoration("摘要"),
            style: AppTheme.ts(
              fontSize: 12.2,
              height: 1.45,
              color: AppTheme.textPrimary,
            ),
          ),
          const SizedBox(height: 12),
          Expanded(
            child: TextField(
              key: const Key("career_note_body_field"),
              controller: _bodyController,
              expands: true,
              maxLines: null,
              minLines: null,
              textAlignVertical: TextAlignVertical.top,
              decoration: _noteInputDecoration("正文（Markdown）"),
              style: AppTheme.ts(
                fontSize: 13.2,
                height: 1.58,
                color: AppTheme.textPrimary,
              ),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                _error!,
                style: AppTheme.ts(
                  fontSize: 11.5,
                  color: AppTheme.danger,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              _WorkbenchTopAction(
                label: "取消",
                icon: Icons.close_rounded,
                onTap: _saving ? () {} : widget.onCancel,
              ),
              const SizedBox(width: 10),
              _WorkbenchTopAction(
                label: _saving ? "保存中" : "保存",
                icon:
                    _saving ? Icons.hourglass_top_rounded : Icons.check_rounded,
                onTap: _saving ? () {} : _save,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CompactRecordTile extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final String meta;
  final VoidCallback? onTap;

  const _CompactRecordTile({
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
    required this.meta,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final child = Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.045),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withValues(alpha: 0.13)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 17, color: color),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        title.trim().isEmpty ? "未命名记录" : title.trim(),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 12.4,
                          fontWeight: FontWeight.w900,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    if (meta.trim().isNotEmpty)
                      Text(
                        meta.trim(),
                        style: AppTheme.ts(
                          fontSize: 10.4,
                          fontWeight: FontWeight.w800,
                          color: color,
                        ),
                      ),
                  ],
                ),
                if (subtitle.trim().isNotEmpty) ...[
                  const SizedBox(height: 5),
                  Text(
                    subtitle.trim(),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 11.2,
                      height: 1.4,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
    if (onTap == null) return child;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: child,
      ),
    );
  }
}

class _WorkbenchSection extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Widget child;

  const _WorkbenchSection({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: _workbenchPanelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(11),
                  border: Border.all(
                      color: AppTheme.accent.withValues(alpha: 0.18)),
                ),
                child: Icon(icon, size: 16, color: AppTheme.accent),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: AppTheme.ts(
                        fontSize: 13.2,
                        fontWeight: FontWeight.w900,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.8,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 13),
          child,
        ],
      ),
    );
  }
}

class _LibraryPlaceholder extends StatelessWidget {
  final IconData icon;
  final String title;
  final String body;

  const _LibraryPlaceholder({
    required this.icon,
    required this.title,
    required this.body,
  });

  @override
  Widget build(BuildContext context) {
    return _WorkbenchSection(
      icon: icon,
      title: title,
      subtitle: "后续批次展开",
      child: _EmptyText(body),
    );
  }
}

class _OverviewMetricRow extends StatelessWidget {
  final List<_OverviewMetric> metrics;

  const _OverviewMetricRow({required this.metrics});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns =
            (constraints.maxWidth / 180).floor().clamp(1, 4).toInt();
        final itemWidth = (constraints.maxWidth - (columns - 1) * 10) / columns;
        return Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            for (final metric in metrics)
              SizedBox(
                width: itemWidth,
                child: Container(
                  padding: const EdgeInsets.fromLTRB(13, 12, 13, 12),
                  decoration: _workbenchPanelDecoration(),
                  child: Row(
                    children: [
                      Icon(metric.icon, size: 18, color: metric.color),
                      const SizedBox(width: 9),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              metric.value.toString(),
                              style: AppTheme.ts(
                                fontSize: 18,
                                fontWeight: FontWeight.w900,
                                color: AppTheme.textPrimary,
                              ),
                            ),
                            Text(
                              metric.label,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: AppTheme.ts(
                                fontSize: 11,
                                color: AppTheme.textTertiary,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _OverviewMetric {
  final String label;
  final int value;
  final IconData icon;
  final Color color;

  const _OverviewMetric({
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
  });
}

class _WorkbenchNavItem extends StatelessWidget {
  final CareerWorkbenchTab tab;
  final bool selected;
  final int count;
  final VoidCallback onTap;

  const _WorkbenchNavItem({
    required this.tab,
    required this.selected,
    required this.count,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
          decoration: BoxDecoration(
            color: selected
                ? AppTheme.accent.withValues(alpha: 0.11)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: selected
                  ? AppTheme.accent.withValues(alpha: 0.2)
                  : Colors.transparent,
            ),
          ),
          child: Row(
            children: [
              Icon(
                _tabIcon(tab),
                size: 17,
                color: selected ? AppTheme.accent : AppTheme.textTertiary,
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  _tabLabel(tab),
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: selected
                        ? AppTheme.textPrimary
                        : AppTheme.textSecondary,
                  ),
                ),
              ),
              if (count > 0) _CountBadge(count: count, selected: selected),
            ],
          ),
        ),
      ),
    );
  }
}

class _WorkbenchNavChip extends StatelessWidget {
  final CareerWorkbenchTab tab;
  final bool selected;
  final int count;
  final VoidCallback onTap;

  const _WorkbenchNavChip({
    required this.tab,
    required this.selected,
    required this.count,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = selected ? AppTheme.accent : AppTheme.textSecondary;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: color.withValues(alpha: selected ? 0.13 : 0.055),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: color.withValues(alpha: 0.16)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(_tabIcon(tab), size: 14, color: color),
              const SizedBox(width: 6),
              Text(
                count > 0 ? "${_tabLabel(tab)} $count" : _tabLabel(tab),
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  color: color,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _FilterChipButton extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _FilterChipButton({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = selected ? AppTheme.accent : AppTheme.textSecondary;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
          decoration: BoxDecoration(
            color: color.withValues(alpha: selected ? 0.12 : 0.05),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: color.withValues(alpha: 0.14)),
          ),
          child: Text(
            label,
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w800,
              color: color,
            ),
          ),
        ),
      ),
    );
  }
}

class _ScoreRing extends StatelessWidget {
  final int? score;

  const _ScoreRing({required this.score});

  @override
  Widget build(BuildContext context) {
    final value = ((score ?? 0).clamp(0, 100) / 100).toDouble();
    final color = _scoreColor(score);
    return SizedBox(
      width: 66,
      height: 66,
      child: Stack(
        alignment: Alignment.center,
        children: [
          CircularProgressIndicator(
            value: score == null ? null : value,
            strokeWidth: 5,
            strokeCap: StrokeCap.round,
            color: color,
            backgroundColor: color.withValues(alpha: 0.12),
          ),
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                score?.toString() ?? "-",
                style: AppTheme.ts(
                  fontSize: 15,
                  height: 1,
                  fontWeight: FontWeight.w900,
                  color: AppTheme.textPrimary,
                ),
              ),
              Text(
                "匹配",
                style: AppTheme.ts(
                  fontSize: 9,
                  height: 1.05,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MetaPill extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;

  const _MetaPill({
    required this.icon,
    required this.label,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.14)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 4),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 10.2,
              fontWeight: FontWeight.w800,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class _TinyTag extends StatelessWidget {
  final String label;
  final Color color;

  const _TinyTag({
    required this.label,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.075),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.13)),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 10.2,
          fontWeight: FontWeight.w800,
          color: color,
        ),
      ),
    );
  }
}

class _TinyStatus extends StatelessWidget {
  final String label;

  const _TinyStatus({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.14)),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 10.8,
          fontWeight: FontWeight.w800,
          color: AppTheme.accent,
        ),
      ),
    );
  }
}

class _CountBadge extends StatelessWidget {
  final int count;
  final bool selected;

  const _CountBadge({required this.count, required this.selected});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: selected
            ? AppTheme.accent.withValues(alpha: 0.16)
            : AppTheme.surfaceHover.withValues(alpha: 0.42),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        count.toString(),
        style: AppTheme.ts(
          fontSize: 10,
          fontWeight: FontWeight.w800,
          color: selected ? AppTheme.accent : AppTheme.textTertiary,
        ),
      ),
    );
  }
}

class _WorkbenchTopAction extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback onTap;

  const _WorkbenchTopAction({
    required this.label,
    required this.icon,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.74),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppTheme.border),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: AppTheme.textSecondary),
              const SizedBox(width: 6),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WorkbenchIconButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;

  const _WorkbenchIconButton({
    required this.icon,
    required this.tooltip,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: AppTheme.surface.withValues(alpha: 0.74),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppTheme.border),
            ),
            child: Icon(icon, size: 17, color: AppTheme.textSecondary),
          ),
        ),
      ),
    );
  }
}

class _SmallTextButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback onTap;

  const _SmallTextButton({
    required this.label,
    required this.icon,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            color: AppTheme.accent.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppTheme.accent.withValues(alpha: 0.18)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 13, color: AppTheme.accent),
              const SizedBox(width: 4),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.accent,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WorkbenchHintBox extends StatelessWidget {
  final String title;
  final String body;

  const _WorkbenchHintBox({
    required this.title,
    required this.body,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.42),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.7)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: AppTheme.ts(
              fontSize: 11.2,
              fontWeight: FontWeight.w900,
              color: AppTheme.textPrimary,
            ),
          ),
          const SizedBox(height: 5),
          Text(
            body,
            style: AppTheme.ts(
              fontSize: 10.5,
              height: 1.45,
              color: AppTheme.textTertiary,
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyText extends StatelessWidget {
  final String text;

  const _EmptyText(this.text);

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.38),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.64)),
      ),
      child: Text(
        text,
        style: AppTheme.ts(
          fontSize: 11.6,
          height: 1.45,
          color: AppTheme.textTertiary,
        ),
      ),
    );
  }
}

class _WorkbenchLoading extends StatelessWidget {
  const _WorkbenchLoading();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SizedBox(
        width: 26,
        height: 26,
        child: CircularProgressIndicator(
          strokeWidth: 2.6,
          color: AppTheme.accent,
        ),
      ),
    );
  }
}

class _WorkbenchError extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const _WorkbenchError({
    required this.error,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        constraints: const BoxConstraints(maxWidth: 520),
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: AppTheme.danger.withValues(alpha: 0.06),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppTheme.danger.withValues(alpha: 0.18)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              "工作台读取失败",
              style: AppTheme.ts(
                fontSize: 14,
                fontWeight: FontWeight.w900,
                color: AppTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              error,
              style: AppTheme.ts(
                fontSize: 12,
                height: 1.45,
                color: AppTheme.textSecondary,
              ),
            ),
            const SizedBox(height: 12),
            _SmallTextButton(
              label: "重试",
              icon: Icons.refresh_rounded,
              onTap: onRetry,
            ),
          ],
        ),
      ),
    );
  }
}

class _DetailEmptyPane extends StatelessWidget {
  const _DetailEmptyPane();

  @override
  Widget build(BuildContext context) {
    return _WorkbenchSection(
      icon: Icons.work_outline_rounded,
      title: "项目详情",
      subtitle: "选择一个项目查看",
      child: const _EmptyText("暂无选中项目。"),
    );
  }
}

class _DetailLoadingPane extends StatelessWidget {
  const _DetailLoadingPane();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: _workbenchPanelDecoration(),
      child: const Center(child: _WorkbenchLoading()),
    );
  }
}

class _DetailErrorPane extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const _DetailErrorPane({
    required this.error,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return _WorkbenchError(error: error, onRetry: onRetry);
  }
}

class _DetailSkeletonFromSummary extends StatelessWidget {
  final CareerApplicationSummaryView summary;

  const _DetailSkeletonFromSummary({required this.summary});

  @override
  Widget build(BuildContext context) {
    return _WorkbenchSection(
      icon: Icons.work_history_outlined,
      title: summary.application.displayTitle,
      subtitle: "正在读取项目详情",
      child: const _EmptyText("稍后会显示关联资产、笔记、学习任务和推荐动作。"),
    );
  }
}

Future<void> _showNewNoteEditorSheet(
  BuildContext context,
  CareerWorkbenchProvider provider, {
  required String sourceSessionId,
  String? sourceArtifactId,
  String? relatedApplicationId,
  String seedTitle = "",
  String seedSummary = "",
  String seedBody = "",
  List<String> evidenceRefs = const [],
  List<Map<String, dynamic>> sourceRefs = const [],
}) {
  final title = seedTitle.trim().isEmpty ? "新建笔记" : seedTitle.trim();
  final draft = NoteView(
    noteId: "note_draft",
    status: "active",
    sourceSessionId: sourceSessionId,
    sourceArtifactId: sourceArtifactId,
    evidenceRefs: evidenceRefs,
    createdAt: DateTime.now(),
    updatedAt: DateTime.now(),
    title: title,
    bodyMarkdown: seedBody.trim().isEmpty ? "# $title\n\n" : seedBody,
    bodyFormat: "markdown",
    collectionId: null,
    tags: const [],
    sourceRefs: const [],
    relatedApplicationId: relatedApplicationId,
    summary: seedSummary,
  );
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    constraints: const BoxConstraints(maxWidth: double.infinity),
    builder: (sheetContext) {
      return SafeArea(
        top: false,
        child: FractionallySizedBox(
          heightFactor: 0.92,
          child: Align(
            alignment: Alignment.bottomCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 980),
              child: Container(
                margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                decoration: AppTheme.floatingPanelDecoration(
                  radius: 24,
                  alpha: 0.97,
                ),
                clipBehavior: Clip.antiAlias,
                child: Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(18, 16, 12, 12),
                      child: Row(
                        children: [
                          Icon(
                            Icons.note_add_outlined,
                            size: 20,
                            color: AppTheme.accent,
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              "新建笔记",
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: AppTheme.ts(
                                fontSize: 14,
                                fontWeight: FontWeight.w900,
                                color: AppTheme.textPrimary,
                              ),
                            ),
                          ),
                          _WorkbenchIconButton(
                            icon: Icons.close_rounded,
                            tooltip: "关闭",
                            onTap: () => Navigator.of(sheetContext).pop(),
                          ),
                        ],
                      ),
                    ),
                    Divider(height: 1, color: AppTheme.border),
                    Expanded(
                      child: _NoteEditorForm(
                        note: draft,
                        onCancel: () => Navigator.of(sheetContext).pop(),
                        onSave: (noteDraft) async {
                          final navigator = Navigator.of(sheetContext);
                          final messenger =
                              ScaffoldMessenger.maybeOf(sheetContext);
                          await provider.createNote(
                            sourceSessionId: sourceSessionId,
                            sourceArtifactId: sourceArtifactId,
                            relatedApplicationId: relatedApplicationId,
                            evidenceRefs: evidenceRefs,
                            sourceRefs: sourceRefs,
                            title: noteDraft.title,
                            bodyMarkdown: noteDraft.bodyMarkdown,
                            summary: noteDraft.summary,
                            tags: noteDraft.tags,
                          );
                          if (sheetContext.mounted) {
                            navigator.pop();
                            messenger?.showSnackBar(
                              const SnackBar(
                                content: Text("笔记已创建"),
                                duration: Duration(seconds: 2),
                              ),
                            );
                          }
                        },
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    },
  );
}

Future<void> _showNoteEditorSheet(
  BuildContext context,
  CareerWorkbenchProvider provider, {
  required String noteId,
}) {
  final noteFuture = provider.loadNote(noteId, force: true);
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    constraints: const BoxConstraints(maxWidth: double.infinity),
    builder: (sheetContext) {
      return SafeArea(
        top: false,
        child: FractionallySizedBox(
          heightFactor: 0.92,
          child: Align(
            alignment: Alignment.bottomCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 980),
              child: Container(
                margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                decoration: AppTheme.floatingPanelDecoration(
                  radius: 24,
                  alpha: 0.97,
                ),
                clipBehavior: Clip.antiAlias,
                child: FutureBuilder<NoteView>(
                  future: noteFuture,
                  builder: (context, snapshot) {
                    final note = snapshot.data;
                    return Column(
                      children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(18, 16, 12, 12),
                          child: Row(
                            children: [
                              Icon(
                                Icons.edit_note_rounded,
                                size: 20,
                                color: AppTheme.accent,
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Text(
                                  note?.title ?? "编辑笔记",
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: AppTheme.ts(
                                    fontSize: 14,
                                    fontWeight: FontWeight.w900,
                                    color: AppTheme.textPrimary,
                                  ),
                                ),
                              ),
                              _WorkbenchIconButton(
                                icon: Icons.close_rounded,
                                tooltip: "关闭",
                                onTap: () => Navigator.of(sheetContext).pop(),
                              ),
                            ],
                          ),
                        ),
                        Divider(height: 1, color: AppTheme.border),
                        Expanded(
                          child: snapshot.connectionState ==
                                      ConnectionState.waiting &&
                                  !snapshot.hasData
                              ? const _WorkbenchLoading()
                              : snapshot.hasError
                                  ? Padding(
                                      padding: const EdgeInsets.all(18),
                                      child: _EmptyText(
                                        "笔记读取失败：${snapshot.error}",
                                      ),
                                    )
                                  : _NoteEditorForm(
                                      note: note!,
                                      onCancel: () =>
                                          Navigator.of(sheetContext).pop(),
                                      onSave: (draft) async {
                                        final navigator =
                                            Navigator.of(sheetContext);
                                        final messenger =
                                            ScaffoldMessenger.maybeOf(
                                          sheetContext,
                                        );
                                        await provider.updateNote(
                                          noteId: noteId,
                                          title: draft.title,
                                          bodyMarkdown: draft.bodyMarkdown,
                                          summary: draft.summary,
                                          tags: draft.tags,
                                        );
                                        if (sheetContext.mounted) {
                                          navigator.pop();
                                          messenger?.showSnackBar(
                                            const SnackBar(
                                                content: Text("笔记已保存"),
                                                duration: Duration(seconds: 2)),
                                          );
                                        }
                                      },
                                    ),
                        ),
                      ],
                    );
                  },
                ),
              ),
            ),
          ),
        ),
      );
    },
  );
}

Future<void> _showArtifactPreviewSheet(
  BuildContext context,
  CareerWorkbenchProvider provider, {
  required String sourceSessionId,
  required String artifactId,
}) {
  final previewFuture = provider.loadArtifactPreview(
    sourceSessionId: sourceSessionId,
    artifactId: artifactId,
  );
  final downloadUrl = provider.artifactDownloadUrl(
    sourceSessionId: sourceSessionId,
    artifactId: artifactId,
  );
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    constraints: const BoxConstraints(maxWidth: double.infinity),
    builder: (sheetContext) {
      return SafeArea(
        top: false,
        child: FractionallySizedBox(
          heightFactor: 0.9,
          child: Align(
            alignment: Alignment.bottomCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 980),
              child: Container(
                margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                decoration: AppTheme.floatingPanelDecoration(
                  radius: 24,
                  alpha: 0.96,
                ),
                clipBehavior: Clip.antiAlias,
                child: FutureBuilder<SessionArtifactContentView>(
                  future: previewFuture,
                  builder: (context, snapshot) {
                    final preview = snapshot.data;
                    return Column(
                      children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(18, 16, 12, 12),
                          child: Row(
                            children: [
                              Icon(
                                Icons.article_outlined,
                                size: 20,
                                color: AppTheme.accent,
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      preview?.title ?? "正在准备预览",
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: AppTheme.ts(
                                        fontSize: 14,
                                        fontWeight: FontWeight.w900,
                                        color: AppTheme.textPrimary,
                                      ),
                                    ),
                                    const SizedBox(height: 3),
                                    Text(
                                      preview == null
                                          ? artifactId
                                          : "${preview.returnedChars}/${preview.totalChars} 字符",
                                      style: AppTheme.ts(
                                        fontSize: 10.8,
                                        color: AppTheme.textTertiary,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              _WorkbenchIconButton(
                                icon: Icons.download_rounded,
                                tooltip: "下载",
                                onTap: () =>
                                    _openDownload(context, downloadUrl),
                              ),
                              const SizedBox(width: 8),
                              _WorkbenchIconButton(
                                icon: Icons.close_rounded,
                                tooltip: "关闭",
                                onTap: () => Navigator.of(context).pop(),
                              ),
                            ],
                          ),
                        ),
                        Divider(height: 1, color: AppTheme.border),
                        Expanded(
                          child: snapshot.connectionState ==
                                      ConnectionState.waiting &&
                                  !snapshot.hasData
                              ? const _WorkbenchLoading()
                              : snapshot.hasError
                                  ? Padding(
                                      padding: const EdgeInsets.all(18),
                                      child: _EmptyText(
                                        "预览失败：${snapshot.error}",
                                      ),
                                    )
                                  : SingleChildScrollView(
                                      padding: const EdgeInsets.fromLTRB(
                                        24,
                                        22,
                                        24,
                                        28,
                                      ),
                                      child: AppMarkdownBody(
                                        content: preview?.content ?? "",
                                        style: AppTheme.ts(
                                          fontSize: 13.8,
                                          height: 1.68,
                                          color: AppTheme.textPrimary,
                                        ),
                                      ),
                                    ),
                        ),
                      ],
                    );
                  },
                ),
              ),
            ),
          ),
        ),
      );
    },
  );
}

void _openDownload(BuildContext context, String url) {
  try {
    openDownloadUrl(url);
  } catch (error) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text("下载打开失败：$error"),
        duration: const Duration(seconds: 2),
      ),
    );
  }
}

BoxDecoration _workbenchPanelDecoration() {
  return BoxDecoration(
    color: AppTheme.surface.withValues(alpha: 0.72),
    borderRadius: BorderRadius.circular(20),
    border: Border.all(color: AppTheme.border.withValues(alpha: 0.86)),
    boxShadow: [
      BoxShadow(
        color: Colors.black.withValues(alpha: AppTheme.isDark ? 0.18 : 0.04),
        blurRadius: 18,
        offset: const Offset(0, 8),
      ),
    ],
  );
}

int _tabCount(CareerWorkbenchProvider provider, CareerWorkbenchTab tab) {
  final counts = provider.workbench?.counts;
  return switch (tab) {
    CareerWorkbenchTab.overview => 0,
    CareerWorkbenchTab.projects => counts?.applications ?? 0,
    CareerWorkbenchTab.resumes => counts?.resumeVersions ?? 0,
    CareerWorkbenchTab.jobs => provider.applications
        .where((item) => item.application.jdAnalysisId != null)
        .length,
    CareerWorkbenchTab.learning => counts?.learningTasks ?? 0,
    CareerWorkbenchTab.notes => counts?.notes ?? 0,
  };
}

String _tabLabel(CareerWorkbenchTab tab) {
  return switch (tab) {
    CareerWorkbenchTab.overview => "总览",
    CareerWorkbenchTab.projects => "求职项目",
    CareerWorkbenchTab.resumes => "简历资料",
    CareerWorkbenchTab.jobs => "JD 与匹配",
    CareerWorkbenchTab.learning => "学习计划",
    CareerWorkbenchTab.notes => "笔记",
  };
}

IconData _tabIcon(CareerWorkbenchTab tab) {
  return switch (tab) {
    CareerWorkbenchTab.overview => Icons.dashboard_customize_outlined,
    CareerWorkbenchTab.projects => Icons.work_history_outlined,
    CareerWorkbenchTab.resumes => Icons.badge_outlined,
    CareerWorkbenchTab.jobs => Icons.fact_check_outlined,
    CareerWorkbenchTab.learning => Icons.school_outlined,
    CareerWorkbenchTab.notes => Icons.sticky_note_2_outlined,
  };
}

String _projectFilterLabel(CareerProjectFilter filter) {
  return switch (filter) {
    CareerProjectFilter.all => "全部",
    CareerProjectFilter.draft => "准备中",
    CareerProjectFilter.readyToApply => "可投递",
    CareerProjectFilter.applied => "已投递",
    CareerProjectFilter.interviewing => "面试中",
    CareerProjectFilter.paused => "已暂停",
  };
}

String _stageLabel(String stage) {
  return switch (stage) {
    "draft" => "准备中",
    "analyzing" => "分析中",
    "ready_to_apply" => "可投递",
    "applied" => "已投递",
    "interviewing" => "面试中",
    "offer" => "已拿 Offer",
    "rejected" => "未通过",
    "paused" => "已暂停",
    _ => stage.isEmpty ? "准备中" : stage,
  };
}

String _priorityLabel(String priority) {
  return switch (priority) {
    "high" => "高优先级",
    "medium" => "中优先级",
    "low" => "低优先级",
    _ => priority.isEmpty ? "中优先级" : priority,
  };
}

Color _priorityColor(String priority) {
  return switch (priority) {
    "high" => AppTheme.accent,
    "medium" => const Color(0xFFB45309),
    "low" => AppTheme.textTertiary,
    _ => AppTheme.textTertiary,
  };
}

Color _scoreColor(int? score) {
  if (score == null) return AppTheme.textTertiary;
  if (score >= 80) return AppTheme.accent;
  if (score >= 60) return const Color(0xFFB45309);
  return AppTheme.danger;
}

String _recommendationLabel(String value) {
  return switch (value) {
    "strong" => "强推荐",
    "recommended" => "建议投递",
    "recommend" => "建议投递",
    "cautious" => "谨慎推荐",
    "weak" => "暂缓投递",
    "unknown" => "待评估",
    _ => value.trim().isEmpty ? "待评估" : value,
  };
}

IconData _assetIcon(String type) {
  return switch (type) {
    "resume_profile" => Icons.badge_outlined,
    "career_profile" => Icons.track_changes_rounded,
    "jd_analysis" => Icons.article_outlined,
    "job_fit_report" => Icons.fact_check_outlined,
    "resume_version" => Icons.description_outlined,
    "note" => Icons.sticky_note_2_outlined,
    _ => Icons.layers_outlined,
  };
}

String _assetTypeLabel(String type) {
  return switch (type) {
    "resume_profile" => "简历画像",
    "career_profile" => "职业画像",
    "jd_analysis" => "JD 分析",
    "job_fit_report" => "匹配报告",
    "resume_version" => "简历版本",
    "note" => "笔记",
    _ => "资料",
  };
}

Color _assetColor(String type) {
  return switch (type) {
    "job_fit_report" => const Color(0xFF0EA5E9),
    "resume_version" => const Color(0xFF2563EB),
    "career_profile" => const Color(0xFF7C3AED),
    "jd_analysis" => const Color(0xFF0891B2),
    "note" => const Color(0xFFB45309),
    _ => AppTheme.accent,
  };
}

IconData _actionIcon(String actionType) {
  return switch (actionType) {
    "custom_resume" => Icons.auto_fix_high_rounded,
    "pre_apply_check" => Icons.fact_check_rounded,
    "interview_prep" => Icons.psychology_alt_outlined,
    "learning_task" => Icons.school_outlined,
    "resume_diagnosis" => Icons.badge_outlined,
    "jd_analysis" => Icons.article_outlined,
    "job_fit_report" => Icons.fact_check_outlined,
    "save_note" => Icons.sticky_note_2_outlined,
    _ => Icons.arrow_forward_rounded,
  };
}

String _taskStateLabel(String state) {
  return switch (state) {
    "todo" => "待办",
    "doing" => "进行中",
    "blocked" => "受阻",
    "done" => "完成",
    _ => state.trim().isEmpty ? "待办" : state,
  };
}

String _weaknessSeverityLabel(String severity) {
  return switch (severity) {
    "high" => "高风险",
    "medium" => "中风险",
    "low" => "低风险",
    _ => severity.trim().isEmpty ? "风险" : severity,
  };
}

String _formatTime(DateTime time) {
  return DateFormat("MM-dd HH:mm").format(time);
}

String _compactLabel(String value) {
  final normalized = value.trim();
  if (normalized.length <= 16) return normalized;
  return "${normalized.substring(0, math.min(16, normalized.length))}…";
}

String _firstNonEmpty(List<String?> values) {
  for (final value in values) {
    final normalized = value?.trim() ?? "";
    if (normalized.isNotEmpty) return normalized;
  }
  return "";
}

CareerNoteSummaryView _summaryFromNote(NoteView note) {
  return CareerNoteSummaryView(
    noteId: note.noteId,
    title: note.title,
    summary: note.summary.isNotEmpty
        ? note.summary
        : _plainSnippet(note.bodyMarkdown),
    status: note.status,
    updatedAt: note.updatedAt,
    sourceArtifactId: note.sourceArtifactId,
    relatedApplicationId: note.relatedApplicationId,
    tags: note.tags,
  );
}

String _plainSnippet(String markdown) {
  final text = markdown
      .replaceAll(RegExp(r"^#{1,6}\s*", multiLine: true), "")
      .replaceAll(RegExp(r"[*_`>#-]"), " ")
      .replaceAll(RegExp(r"\s+"), " ")
      .trim();
  if (text.length <= 80) return text;
  return "${text.substring(0, 80)}...";
}

String _noteSourceSessionId(
  CareerWorkbenchProvider provider,
  String? currentSessionId, {
  String? fallback,
}) {
  for (final value in [
    currentSessionId,
    fallback,
    provider.selectedApplicationSummary?.application.meta.sourceSessionId,
    provider.selectedApplicationDetail?.application.meta.sourceSessionId,
  ]) {
    final normalized = value?.trim() ?? "";
    if (normalized.startsWith("sess_")) {
      return normalized;
    }
  }
  return "sess_workbench";
}

String _assetNoteSeedBody(CareerLinkedAssetView asset) {
  final title = asset.title.trim().isEmpty
      ? _assetTypeLabel(asset.type)
      : asset.title.trim();
  return '''
# 关于 $title 的笔记

> 引用来源：${_assetTypeLabel(asset.type)} `${asset.id}`

## 记录

''';
}

List<String> _assetEvidenceRefs(
  CareerLinkedAssetView asset,
  String? relatedApplicationId,
) {
  final refs = <String>[];
  for (final value in [
    relatedApplicationId,
    asset.id,
    asset.previewArtifactId
  ]) {
    final normalized = value?.trim() ?? "";
    if (_isEvidenceRef(normalized) && !refs.contains(normalized)) {
      refs.add(normalized);
    }
  }
  return refs;
}

Map<String, dynamic> _assetSourceRef(CareerLinkedAssetView asset) {
  return {
    "source_type": _noteSourceTypeForAsset(asset.type),
    "source_id": asset.id,
    "source_session_id": asset.sourceSessionId,
    "title": asset.title,
    "quote": "",
  };
}

String _noteSourceTypeForAsset(String type) {
  return switch (type) {
    "resume_profile" => "resume_profile",
    "career_profile" => "career_profile",
    "jd_analysis" => "jd_analysis",
    "job_fit_report" => "job_fit_report",
    "resume_version" => "resume_version",
    "artifact" => "artifact",
    _ => "manual",
  };
}

bool _isEvidenceRef(String value) {
  return RegExp(
    r"^(application|artifact|career_profile|collection|fit|jd|jd_analysis|note|resume_profile|resume_version|sess)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
  ).hasMatch(value);
}

List<String> _parseTags(String raw) {
  final seen = <String>{};
  final tags = <String>[];
  for (final part in raw.split(RegExp(r"[,，\s]+"))) {
    final normalized = part.trim();
    if (normalized.isEmpty || seen.contains(normalized)) {
      continue;
    }
    tags.add(normalized);
    seen.add(normalized);
  }
  return tags;
}

InputDecoration _noteInputDecoration(String label) {
  return InputDecoration(
    labelText: label,
    labelStyle: AppTheme.ts(
      fontSize: 11.5,
      color: AppTheme.textTertiary,
      fontWeight: FontWeight.w700,
    ),
    filled: true,
    fillColor: AppTheme.surfaceHover.withValues(alpha: 0.34),
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: BorderSide(color: AppTheme.border.withValues(alpha: 0.78)),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: BorderSide(color: AppTheme.accent.withValues(alpha: 0.42)),
    ),
  );
}

String _promptForAction(
  CareerSuggestedActionView action,
  CareerApplicationView record,
) {
  final lines = <String>[
    "- application_id: ${record.applicationId}",
    if (record.company.trim().isNotEmpty) "- company: ${record.company.trim()}",
    if (record.position.trim().isNotEmpty)
      "- position: ${record.position.trim()}",
    if (record.resumeProfileId?.trim().isNotEmpty == true)
      "- resume_profile_id: ${record.resumeProfileId!.trim()}",
    if (record.careerProfileId?.trim().isNotEmpty == true)
      "- career_profile_id: ${record.careerProfileId!.trim()}",
    if (record.jdAnalysisId?.trim().isNotEmpty == true)
      "- jd_analysis_id: ${record.jdAnalysisId!.trim()}",
    if (record.jobFitReportId?.trim().isNotEmpty == true)
      "- job_fit_report_id: ${record.jobFitReportId!.trim()}",
  ];
  return '''
请执行求职项目动作：${action.label}

项目信息：
${lines.join("\n")}

动作意图：
${_firstNonEmpty([action.promptIntent, action.reason])}

执行要求：
1. 先读取 CareerApplication，并复用项目里已有的产品记录。
2. 不要重复创建已存在的简历画像、JD 分析或匹配报告。
3. 如果产生可复用结果，请保存为对应产品记录或 session artifact。
4. 不要写 memory。
5. 最终回复请说明执行结果、更新的记录 id 和下一步建议。
''';
}
