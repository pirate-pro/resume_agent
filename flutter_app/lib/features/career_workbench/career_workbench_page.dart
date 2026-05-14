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

typedef WorkbenchPromptSender = Future<void> Function(
  String prompt, {
  CareerWorkbenchActionRequest? action,
});

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
          if (provider.activeAction != null) ...[
            _WorkbenchActionBanner(
              provider: provider,
              action: provider.activeAction!,
              onBackToChat: widget.onBackToChat,
            ),
            const SizedBox(height: 8),
          ],
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

class _WorkbenchActionBanner extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerWorkbenchActionRun action;
  final VoidCallback onBackToChat;

  const _WorkbenchActionBanner({
    required this.provider,
    required this.action,
    required this.onBackToChat,
  });

  @override
  Widget build(BuildContext context) {
    final state = action.state;
    final color = _actionStateColor(state);
    final icon = _actionStateIcon(state);
    final title = switch (state) {
      CareerWorkbenchActionState.running => "正在执行：${action.request.label}",
      CareerWorkbenchActionState.completed => "已完成：${action.request.label}",
      CareerWorkbenchActionState.failed => "执行失败：${action.request.label}",
    };
    final subtitle = switch (state) {
      CareerWorkbenchActionState.running => "已回到聊天处理，完成后会同步刷新工作台。",
      CareerWorkbenchActionState.completed => action.resultHints.isEmpty
          ? "工作台和求职资产已同步刷新。"
          : action.resultHints.join(" · "),
      CareerWorkbenchActionState.failed =>
        action.error?.trim().isNotEmpty == true
            ? action.error!.trim()
            : "聊天执行没有完成，可以回到聊天查看错误。",
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 0, 16, 0),
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.075),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: color.withValues(alpha: 0.2)),
        ),
        child: Row(
          children: [
            Container(
              width: 34,
              height: 34,
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(13),
                border: Border.all(color: color.withValues(alpha: 0.18)),
              ),
              child: action.isRunning
                  ? Padding(
                      padding: const EdgeInsets.all(8),
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: color,
                      ),
                    )
                  : Icon(icon, size: 17, color: color),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 12.3,
                      fontWeight: FontWeight.w900,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    subtitle,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 11,
                      height: 1.35,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            if (state == CareerWorkbenchActionState.completed)
              _SmallTextButton(
                label: "查看项目",
                icon: Icons.open_in_new_rounded,
                onTap: () => unawaited(provider.focusActiveActionTarget()),
              )
            else if (state == CareerWorkbenchActionState.failed)
              _SmallTextButton(
                label: "回聊天",
                icon: Icons.chat_bubble_outline_rounded,
                onTap: onBackToChat,
              ),
            if (state != CareerWorkbenchActionState.running) ...[
              const SizedBox(width: 6),
              _WorkbenchIconButton(
                icon: Icons.close_rounded,
                tooltip: "关闭动作提示",
                onTap: provider.clearAction,
              ),
            ],
          ],
        ),
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
      CareerWorkbenchTab.resumes => _ResumeLibraryView(provider: provider),
      CareerWorkbenchTab.jobs => _JobMatchLibraryView(provider: provider),
      CareerWorkbenchTab.learning => _LearningPlanView(
          provider: provider,
          onBackToChat: onBackToChat,
          onSendPrompt: onSendPrompt,
        ),
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
              label: "笔记",
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

enum _ResumeLibraryFilter { all, resumeProfiles, careerProfiles, versions }

enum _JobMatchLibraryFilter { all, jdAnalyses, fitReports }

class _ResumeLibraryView extends StatefulWidget {
  final CareerWorkbenchProvider provider;

  const _ResumeLibraryView({required this.provider});

  @override
  State<_ResumeLibraryView> createState() => _ResumeLibraryViewState();
}

class _ResumeLibraryViewState extends State<_ResumeLibraryView> {
  _ResumeLibraryFilter _filter = _ResumeLibraryFilter.all;

  @override
  void initState() {
    super.initState();
    Future.microtask(() => widget.provider.loadAssetLibrary());
  }

  @override
  Widget build(BuildContext context) {
    final provider = widget.provider;
    final items = _resumeLibraryItems(provider, _filter);
    return _AssetLibraryPanel(
      title: "简历资料",
      subtitle: "原始简历、画像、诊断和定制版本集中管理",
      statusLabel: "${items.length} 项资料",
      isLoading: provider.isLoadingAssetLibrary && items.isEmpty,
      error: provider.assetLibraryError,
      onRetry: () => unawaited(provider.loadAssetLibrary(force: true)),
      filters: [
        _AssetFilterOption(
          label: "全部",
          count: provider.resumeLibraryCount,
          selected: _filter == _ResumeLibraryFilter.all,
          onTap: () => setState(() => _filter = _ResumeLibraryFilter.all),
        ),
        _AssetFilterOption(
          label: "画像",
          count: provider.resumeProfiles.length,
          selected: _filter == _ResumeLibraryFilter.resumeProfiles,
          onTap: () =>
              setState(() => _filter = _ResumeLibraryFilter.resumeProfiles),
        ),
        _AssetFilterOption(
          label: "职业画像",
          count: provider.careerProfiles.length,
          selected: _filter == _ResumeLibraryFilter.careerProfiles,
          onTap: () =>
              setState(() => _filter = _ResumeLibraryFilter.careerProfiles),
        ),
        _AssetFilterOption(
          label: "版本",
          count: provider.resumeVersions.length,
          selected: _filter == _ResumeLibraryFilter.versions,
          onTap: () => setState(() => _filter = _ResumeLibraryFilter.versions),
        ),
      ],
      emptyText: "还没有可管理的简历资料。可以先在聊天里上传简历并触发诊断。",
      items: items,
      provider: provider,
    );
  }
}

class _JobMatchLibraryView extends StatefulWidget {
  final CareerWorkbenchProvider provider;

  const _JobMatchLibraryView({required this.provider});

  @override
  State<_JobMatchLibraryView> createState() => _JobMatchLibraryViewState();
}

class _JobMatchLibraryViewState extends State<_JobMatchLibraryView> {
  _JobMatchLibraryFilter _filter = _JobMatchLibraryFilter.all;

  @override
  void initState() {
    super.initState();
    Future.microtask(() => widget.provider.loadAssetLibrary());
  }

  @override
  Widget build(BuildContext context) {
    final provider = widget.provider;
    final items = _jobMatchLibraryItems(provider, _filter);
    return _AssetLibraryPanel(
      title: "JD 与匹配",
      subtitle: "按岗位集中查看 JD 分析、匹配结论和报告文件",
      statusLabel: "${items.length} 项记录",
      isLoading: provider.isLoadingAssetLibrary && items.isEmpty,
      error: provider.assetLibraryError,
      onRetry: () => unawaited(provider.loadAssetLibrary(force: true)),
      filters: [
        _AssetFilterOption(
          label: "全部",
          count: provider.jobMatchLibraryCount,
          selected: _filter == _JobMatchLibraryFilter.all,
          onTap: () => setState(() => _filter = _JobMatchLibraryFilter.all),
        ),
        _AssetFilterOption(
          label: "JD 分析",
          count: provider.jdAnalyses.length,
          selected: _filter == _JobMatchLibraryFilter.jdAnalyses,
          onTap: () =>
              setState(() => _filter = _JobMatchLibraryFilter.jdAnalyses),
        ),
        _AssetFilterOption(
          label: "匹配报告",
          count: provider.jobFitReports.length,
          selected: _filter == _JobMatchLibraryFilter.fitReports,
          onTap: () =>
              setState(() => _filter = _JobMatchLibraryFilter.fitReports),
        ),
      ],
      emptyText: "还没有 JD 分析或匹配报告。可以先上传 JD，或从项目详情里触发匹配分析。",
      items: items,
      provider: provider,
    );
  }
}

class _AssetLibraryPanel extends StatelessWidget {
  final String title;
  final String subtitle;
  final String statusLabel;
  final bool isLoading;
  final String? error;
  final VoidCallback onRetry;
  final List<_AssetFilterOption> filters;
  final String emptyText;
  final List<_AssetLibraryItem> items;
  final CareerWorkbenchProvider provider;

  const _AssetLibraryPanel({
    required this.title,
    required this.subtitle,
    required this.statusLabel,
    required this.isLoading,
    required this.error,
    required this.onRetry,
    required this.filters,
    required this.emptyText,
    required this.items,
    required this.provider,
  });

  @override
  Widget build(BuildContext context) {
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
                        title,
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
                          color: AppTheme.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
                _TinyStatus(label: statusLabel),
              ],
            ),
          ),
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
              children: [
                for (final filter in filters) ...[
                  _AssetFilterChip(option: filter),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          Expanded(
            child: Builder(
              builder: (context) {
                if (isLoading) {
                  return const Center(child: _WorkbenchLoading());
                }
                if (error != null && items.isEmpty) {
                  return Padding(
                    padding: const EdgeInsets.all(14),
                    child: _WorkbenchError(error: error!, onRetry: onRetry),
                  );
                }
                if (items.isEmpty) {
                  return Padding(
                    padding: const EdgeInsets.all(14),
                    child: _EmptyText(emptyText),
                  );
                }
                return ListView.separated(
                  padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                  itemBuilder: (context, index) => _AssetLibraryCard(
                    item: items[index],
                    provider: provider,
                  ),
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemCount: items.length,
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _AssetFilterOption {
  final String label;
  final int count;
  final bool selected;
  final VoidCallback onTap;

  const _AssetFilterOption({
    required this.label,
    required this.count,
    required this.selected,
    required this.onTap,
  });
}

class _AssetFilterChip extends StatelessWidget {
  final _AssetFilterOption option;

  const _AssetFilterChip({required this.option});

  @override
  Widget build(BuildContext context) {
    final color = option.selected ? AppTheme.accent : AppTheme.textSecondary;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: option.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
          decoration: BoxDecoration(
            color: color.withValues(alpha: option.selected ? 0.12 : 0.05),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: color.withValues(alpha: 0.15)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                option.label,
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  color: color,
                ),
              ),
              const SizedBox(width: 5),
              Text(
                option.count.toString(),
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w800,
                  color: color.withValues(alpha: 0.78),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AssetLibraryCard extends StatelessWidget {
  final _AssetLibraryItem item;
  final CareerWorkbenchProvider provider;

  const _AssetLibraryCard({
    required this.item,
    required this.provider,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: item.color.withValues(alpha: 0.045),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: item.color.withValues(alpha: 0.14)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: item.color.withValues(alpha: 0.11),
                  borderRadius: BorderRadius.circular(13),
                  border: Border.all(color: item.color.withValues(alpha: 0.16)),
                ),
                child: Icon(item.icon, size: 18, color: item.color),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        _TinyTag(label: item.typeLabel, color: item.color),
                        if (item.projectLabel.isNotEmpty)
                          _TinyTag(
                            label: item.projectLabel,
                            color: AppTheme.textSecondary,
                          ),
                      ],
                    ),
                    const SizedBox(height: 7),
                    Text(
                      item.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 13.4,
                        height: 1.25,
                        fontWeight: FontWeight.w900,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    if (item.subtitle.isNotEmpty) ...[
                      const SizedBox(height: 5),
                      Text(
                        item.subtitle,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.4,
                          height: 1.4,
                          color: AppTheme.textSecondary,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Text(
                _formatTime(item.updatedAt),
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
          if (item.stats.isNotEmpty) ...[
            const SizedBox(height: 11),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final stat in item.stats)
                  _AssetStatPill(stat: stat, color: item.color),
              ],
            ),
          ],
          if (item.tags.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final tag in item.tags.take(6))
                  _TinyTag(label: tag, color: item.color),
              ],
            ),
          ],
          const SizedBox(height: 11),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _SmallTextButton(
                label: "详情",
                icon: Icons.open_in_new_rounded,
                onTap: () => _showLibraryDetailSheet(context, item),
              ),
              for (final action in item.previewActions)
                _SmallTextButton(
                  label: action.label,
                  icon: action.icon,
                  onTap: () => _showArtifactPreviewSheet(
                    context,
                    provider,
                    sourceSessionId: action.sourceSessionId,
                    artifactId: action.artifactId,
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _AssetStatPill extends StatelessWidget {
  final _AssetStat stat;
  final Color color;

  const _AssetStatPill({
    required this.stat,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minWidth: 86),
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.54),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.72)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(stat.icon, size: 13, color: color),
          const SizedBox(width: 5),
          Text(
            stat.label,
            style: AppTheme.ts(
              fontSize: 10.6,
              fontWeight: FontWeight.w800,
              color: AppTheme.textSecondary,
            ),
          ),
          const SizedBox(width: 5),
          Text(
            stat.value,
            style: AppTheme.ts(
              fontSize: 11.2,
              fontWeight: FontWeight.w900,
              color: AppTheme.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}

class _AssetLibraryItem {
  final String id;
  final String typeLabel;
  final String title;
  final String subtitle;
  final String projectLabel;
  final IconData icon;
  final Color color;
  final DateTime updatedAt;
  final List<_AssetStat> stats;
  final List<String> tags;
  final List<_AssetPreviewAction> previewActions;
  final String detailMarkdown;

  const _AssetLibraryItem({
    required this.id,
    required this.typeLabel,
    required this.title,
    required this.subtitle,
    required this.projectLabel,
    required this.icon,
    required this.color,
    required this.updatedAt,
    required this.stats,
    required this.tags,
    required this.previewActions,
    required this.detailMarkdown,
  });
}

class _AssetStat {
  final String label;
  final String value;
  final IconData icon;

  const _AssetStat({
    required this.label,
    required this.value,
    required this.icon,
  });
}

class _AssetPreviewAction {
  final String label;
  final IconData icon;
  final String sourceSessionId;
  final String artifactId;

  const _AssetPreviewAction({
    required this.label,
    required this.icon,
    required this.sourceSessionId,
    required this.artifactId,
  });
}

class _LearningPlanView extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final VoidCallback onBackToChat;
  final WorkbenchPromptSender? onSendPrompt;

  const _LearningPlanView({
    required this.provider,
    required this.onBackToChat,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final selected = provider.selectedApplicationSummary;
    final detail = provider.selectedApplicationDetail;
    final learning = detail?.learning;
    final selectedId = selected?.application.applicationId ?? "";
    final loading =
        selectedId.isNotEmpty && provider.isApplicationLoading(selectedId);
    final tasks = [...?learning?.tasks]
      ..sort((a, b) => _taskSortRank(a).compareTo(_taskSortRank(b)));
    final plans = [...?learning?.plans]
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    final weaknesses = [...?learning?.weaknesses]
      ..sort((a, b) => _weaknessSortRank(a).compareTo(_weaknessSortRank(b)));
    final reviews = [...?learning?.reviews]
      ..sort((a, b) => _reviewSortTime(a).compareTo(_reviewSortTime(b)));
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
                        "学习计划",
                        style: AppTheme.ts(
                          fontSize: 16,
                          fontWeight: FontWeight.w900,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        selected == null
                            ? "选择求职项目后查看学习推进"
                            : "${selected.application.displayTitle} · 短板、任务和复盘安排",
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
                _TinyStatus(label: "${tasks.length} 个任务"),
              ],
            ),
          ),
          if (provider.applications.isNotEmpty)
            SizedBox(
              height: 48,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
                children: [
                  for (final app in provider.applications) ...[
                    _LearningProjectChip(
                      summary: app,
                      selected: app.application.applicationId == selectedId,
                      onTap: () => unawaited(
                        provider
                            .selectApplication(app.application.applicationId),
                      ),
                    ),
                    const SizedBox(width: 8),
                  ],
                ],
              ),
            ),
          Expanded(
            child: loading && detail == null
                ? const Center(child: _WorkbenchLoading())
                : selected == null
                    ? Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _LearningTaskEntryPanel(
                              application: null,
                              tasks: const [],
                              plans: const [],
                              weaknesses: const [],
                              reviews: const [],
                              onBackToChat: onBackToChat,
                              onSendPrompt: onSendPrompt,
                            ),
                            const SizedBox(height: 12),
                            const _EmptyText(
                              "暂无求职项目。可以先新建一个全局学习任务，后续再关联到目标岗位。",
                            ),
                          ],
                        ),
                      )
                    : ListView(
                        padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                        children: [
                          _LearningMetricStrip(
                            plans: plans,
                            tasks: tasks,
                            weaknesses: weaknesses,
                            reviews: reviews,
                          ),
                          const SizedBox(height: 12),
                          _LearningTaskEntryPanel(
                            application: selected.application,
                            tasks: tasks,
                            plans: plans,
                            weaknesses: weaknesses,
                            reviews: reviews,
                            onBackToChat: onBackToChat,
                            onSendPrompt: onSendPrompt,
                          ),
                          const SizedBox(height: 12),
                          if (plans.isEmpty &&
                              tasks.isEmpty &&
                              weaknesses.isEmpty &&
                              reviews.isEmpty)
                            const _EmptyText(
                              "当前项目还没有学习计划。可以从这里回到聊天，让 Agent 基于匹配报告生成学习任务。",
                            )
                          else ...[
                            _LearningPlanSection(plans: plans),
                            const SizedBox(height: 12),
                            _LearningTaskBoard(tasks: tasks),
                            const SizedBox(height: 12),
                            _LearningWeaknessSection(weaknesses: weaknesses),
                            const SizedBox(height: 12),
                            _LearningReviewSection(reviews: reviews),
                          ],
                        ],
                      ),
          ),
        ],
      ),
    );
  }
}

class _LearningProjectChip extends StatelessWidget {
  final CareerApplicationSummaryView summary;
  final bool selected;
  final VoidCallback onTap;

  const _LearningProjectChip({
    required this.summary,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = selected ? AppTheme.accent : AppTheme.textSecondary;
    final count = summary.learningTaskCount;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          constraints: const BoxConstraints(maxWidth: 260),
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
          decoration: BoxDecoration(
            color: color.withValues(alpha: selected ? 0.12 : 0.05),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: color.withValues(alpha: 0.16)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.work_outline_rounded, size: 13, color: color),
              const SizedBox(width: 5),
              Flexible(
                child: Text(
                  summary.application.displayTitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11,
                    fontWeight: FontWeight.w900,
                    color: color,
                  ),
                ),
              ),
              if (count > 0) ...[
                const SizedBox(width: 6),
                Text(
                  "$count",
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w900,
                    color: color.withValues(alpha: 0.82),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _LearningMetricStrip extends StatelessWidget {
  final List<CareerWorkbenchLearningPlanView> plans;
  final List<CareerWorkbenchLearningTaskView> tasks;
  final List<CareerWorkbenchWeaknessView> weaknesses;
  final List<CareerWorkbenchReviewView> reviews;

  const _LearningMetricStrip({
    required this.plans,
    required this.tasks,
    required this.weaknesses,
    required this.reviews,
  });

  @override
  Widget build(BuildContext context) {
    final openTasks = tasks
        .where((task) => task.state != "done" && task.state != "cancelled")
        .length;
    final doneTasks = tasks.where((task) => task.state == "done").length;
    final highWeaknesses =
        weaknesses.where((weakness) => weakness.severity == "high").length;
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns =
            (constraints.maxWidth / 170).floor().clamp(2, 4).toInt();
        final itemWidth = (constraints.maxWidth - (columns - 1) * 8) / columns;
        final metrics = [
          _LearningMetric(
            label: "计划",
            value: plans.length.toString(),
            icon: Icons.route_outlined,
            color: AppTheme.accent,
          ),
          _LearningMetric(
            label: "待推进",
            value: openTasks.toString(),
            icon: Icons.checklist_rounded,
            color: const Color(0xFF2563EB),
          ),
          _LearningMetric(
            label: "已完成",
            value: doneTasks.toString(),
            icon: Icons.check_circle_outline_rounded,
            color: const Color(0xFF059669),
          ),
          _LearningMetric(
            label: "高风险短板",
            value: highWeaknesses.toString(),
            icon: Icons.warning_amber_rounded,
            color: highWeaknesses > 0 ? AppTheme.danger : AppTheme.textTertiary,
          ),
        ];
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final metric in metrics)
              SizedBox(
                width: itemWidth,
                child: Container(
                  padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
                  decoration: BoxDecoration(
                    color: metric.color.withValues(alpha: 0.055),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(
                      color: metric.color.withValues(alpha: 0.14),
                    ),
                  ),
                  child: Row(
                    children: [
                      Icon(metric.icon, size: 17, color: metric.color),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              metric.value,
                              style: AppTheme.ts(
                                fontSize: 17,
                                fontWeight: FontWeight.w900,
                                color: AppTheme.textPrimary,
                              ),
                            ),
                            Text(
                              metric.label,
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
                ),
              ),
          ],
        );
      },
    );
  }
}

class _LearningMetric {
  final String label;
  final String value;
  final IconData icon;
  final Color color;

  const _LearningMetric({
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
  });
}

class _LearningTaskEntryPanel extends StatelessWidget {
  final CareerApplicationView? application;
  final List<CareerWorkbenchLearningTaskView> tasks;
  final List<CareerWorkbenchLearningPlanView> plans;
  final List<CareerWorkbenchWeaknessView> weaknesses;
  final List<CareerWorkbenchReviewView> reviews;
  final VoidCallback onBackToChat;
  final WorkbenchPromptSender? onSendPrompt;

  const _LearningTaskEntryPanel({
    required this.application,
    required this.tasks,
    required this.plans,
    required this.weaknesses,
    required this.reviews,
    required this.onBackToChat,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final openTasks = tasks
        .where((task) => task.state != "done" && task.state != "archived")
        .length;
    final doneTasks = tasks.where((task) => task.state == "done").length;
    final hasProject = application != null;
    final subtitle = !hasProject
        ? "先记录一个全局学习目标，后续可以再关联到求职项目。"
        : tasks.isEmpty
            ? "当前项目还没有任务，可以自己添加，也可以让 Agent 基于短板推荐。"
            : "$openTasks 个待推进 · $doneTasks 个已完成，继续打卡或补充新任务。";
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.38),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.68)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final narrow = constraints.maxWidth < 680;
          final headline = Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(11),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.16),
                  ),
                ),
                child: Icon(
                  Icons.school_outlined,
                  size: 16,
                  color: AppTheme.accent,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "今天要推进什么？",
                      style: AppTheme.ts(
                        fontSize: 13.2,
                        fontWeight: FontWeight.w900,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.2,
                        height: 1.42,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          );
          final actions = Wrap(
            spacing: 8,
            runSpacing: 8,
            alignment: narrow ? WrapAlignment.start : WrapAlignment.end,
            children: [
              _LearningTaskActionButton(
                label: "新建任务",
                icon: Icons.add_task_rounded,
                color: AppTheme.accent,
                onTap: () => _showLearningTaskCreateSheet(
                  context,
                  application: application,
                  onBackToChat: onBackToChat,
                  onSendPrompt: onSendPrompt,
                ),
              ),
              _LearningTaskActionButton(
                label: "从项目推荐",
                icon: Icons.auto_awesome_rounded,
                color: const Color(0xFF7C3AED),
                enabled: hasProject,
                disabledMessage: "暂无求职项目，先新建任务或完成一次岗位匹配",
                onTap: () => _sendLearningPrompt(
                  context,
                  application,
                  label: "推荐任务",
                  actionType: "learning_recommend",
                  intent: _learningRecommendationIntent(
                    plans: plans.length,
                    tasks: tasks.length,
                    weaknesses: weaknesses.length,
                    reviews: reviews.length,
                  ),
                  onBackToChat: onBackToChat,
                  onSendPrompt: onSendPrompt,
                ),
              ),
              _LearningTaskActionButton(
                label: "记录进度",
                icon: Icons.fact_check_outlined,
                color: const Color(0xFF2563EB),
                enabled: tasks.isNotEmpty,
                disabledMessage: "当前还没有学习任务，先新建或生成推荐任务",
                onTap: () => _showLearningTaskCheckinSheet(
                  context,
                  application: application,
                  tasks: tasks,
                  onBackToChat: onBackToChat,
                  onSendPrompt: onSendPrompt,
                ),
              ),
            ],
          );
          if (narrow) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                headline,
                const SizedBox(height: 12),
                actions,
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(child: headline),
              const SizedBox(width: 14),
              actions,
            ],
          );
        },
      ),
    );
  }
}

class _LearningTaskActionButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;
  final bool enabled;
  final String? disabledMessage;
  final VoidCallback onTap;

  const _LearningTaskActionButton({
    required this.label,
    required this.icon,
    required this.color,
    required this.onTap,
    this.enabled = true,
    this.disabledMessage,
  });

  @override
  Widget build(BuildContext context) {
    final effectiveColor = enabled ? color : AppTheme.textTertiary;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: enabled
            ? onTap
            : () {
                final message = disabledMessage;
                if (message == null) return;
                ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                  SnackBar(
                    content: Text(message),
                    duration: const Duration(seconds: 1),
                  ),
                );
              },
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: effectiveColor.withValues(alpha: enabled ? 0.1 : 0.055),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: effectiveColor.withValues(alpha: enabled ? 0.2 : 0.12),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 14, color: effectiveColor),
              const SizedBox(width: 5),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  color: effectiveColor,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

Future<void> _showLearningTaskCreateSheet(
  BuildContext context, {
  required CareerApplicationView? application,
  required VoidCallback onBackToChat,
  required WorkbenchPromptSender? onSendPrompt,
}) {
  final titleController = TextEditingController();
  final descriptionController = TextEditingController();
  final minutesController = TextEditingController();
  var priority = "medium";
  var error = "";

  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    constraints: const BoxConstraints(maxWidth: double.infinity),
    builder: (sheetContext) {
      return StatefulBuilder(
        builder: (context, setSheetState) {
          Future<void> submit() async {
            final title = titleController.text.trim();
            if (title.isEmpty) {
              setSheetState(() => error = "先写一个任务标题");
              return;
            }
            final rawMinutes = minutesController.text.trim();
            final estimatedMinutes = rawMinutes.isEmpty
                ? 0
                : int.tryParse(rawMinutes.replaceAll(RegExp(r"[^0-9]"), ""));
            Navigator.of(sheetContext).pop();
            await _sendLearningPrompt(
              context,
              application,
              label: "新建任务",
              actionType: "learning_task_manual",
              intent: _manualLearningTaskIntent(
                title: title,
                description: descriptionController.text.trim(),
                priority: priority,
                estimatedMinutes: estimatedMinutes ?? 0,
              ),
              onBackToChat: onBackToChat,
              onSendPrompt: onSendPrompt,
            );
          }

          return SafeArea(
            top: false,
            child: Padding(
              padding: EdgeInsets.only(
                left: 12,
                right: 12,
                bottom: 12 + MediaQuery.viewInsetsOf(context).bottom,
              ),
              child: Align(
                alignment: Alignment.bottomCenter,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 720),
                  child: Container(
                    decoration: AppTheme.floatingPanelDecoration(
                      radius: 24,
                      alpha: 0.98,
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Container(
                                width: 34,
                                height: 34,
                                decoration: BoxDecoration(
                                  color: AppTheme.accent.withValues(alpha: 0.1),
                                  borderRadius: BorderRadius.circular(12),
                                  border: Border.all(
                                    color:
                                        AppTheme.accent.withValues(alpha: 0.18),
                                  ),
                                ),
                                child: Icon(
                                  Icons.add_task_rounded,
                                  size: 17,
                                  color: AppTheme.accent,
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      "新建学习任务",
                                      style: AppTheme.ts(
                                        fontSize: 14,
                                        fontWeight: FontWeight.w900,
                                        color: AppTheme.textPrimary,
                                      ),
                                    ),
                                    const SizedBox(height: 3),
                                    Text(
                                      application == null
                                          ? "创建一个全局任务，后续可以再关联到项目。"
                                          : "任务会优先关联当前求职项目，但仍由 Agent 执行写入。",
                                      style: AppTheme.ts(
                                        fontSize: 11,
                                        color: AppTheme.textTertiary,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              _WorkbenchIconButton(
                                icon: Icons.close_rounded,
                                tooltip: "关闭",
                                onTap: () => Navigator.of(sheetContext).pop(),
                              ),
                            ],
                          ),
                          const SizedBox(height: 16),
                          TextField(
                            controller: titleController,
                            decoration: _noteInputDecoration("任务标题"),
                            style: AppTheme.ts(
                              fontSize: 13,
                              fontWeight: FontWeight.w800,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 10),
                          TextField(
                            controller: descriptionController,
                            minLines: 3,
                            maxLines: 5,
                            decoration: _noteInputDecoration("任务目标或说明（可选）"),
                            style: AppTheme.ts(
                              fontSize: 12.5,
                              height: 1.48,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 10),
                          LayoutBuilder(
                            builder: (context, constraints) {
                              final prioritySelector = _LearningChoiceGroup(
                                label: "优先级",
                                value: priority,
                                options: const [
                                  _LearningChoiceOption("high", "优先"),
                                  _LearningChoiceOption("medium", "常规"),
                                  _LearningChoiceOption("low", "可稍后"),
                                ],
                                onChanged: (value) => setSheetState(() {
                                  priority = value;
                                }),
                              );
                              final minutesField = TextField(
                                controller: minutesController,
                                keyboardType: TextInputType.number,
                                decoration: _noteInputDecoration("预计分钟数"),
                                style: AppTheme.ts(
                                  fontSize: 12.5,
                                  color: AppTheme.textPrimary,
                                ),
                              );
                              if (constraints.maxWidth < 560) {
                                return Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    prioritySelector,
                                    const SizedBox(height: 10),
                                    minutesField,
                                  ],
                                );
                              }
                              return Row(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Expanded(child: prioritySelector),
                                  const SizedBox(width: 10),
                                  SizedBox(width: 180, child: minutesField),
                                ],
                              );
                            },
                          ),
                          if (error.isNotEmpty) ...[
                            const SizedBox(height: 10),
                            Text(
                              error,
                              style: AppTheme.ts(
                                fontSize: 11.5,
                                fontWeight: FontWeight.w800,
                                color: AppTheme.danger,
                              ),
                            ),
                          ],
                          const SizedBox(height: 16),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.end,
                            children: [
                              TextButton(
                                onPressed: () =>
                                    Navigator.of(sheetContext).pop(),
                                child: Text(
                                  "取消",
                                  style: AppTheme.ts(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w800,
                                    color: AppTheme.textSecondary,
                                  ),
                                ),
                              ),
                              const SizedBox(width: 8),
                              _SmallTextButton(
                                label: "交给 Agent 创建",
                                icon: Icons.arrow_forward_rounded,
                                onTap: () => unawaited(submit()),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
        },
      );
    },
  ).whenComplete(() {
    titleController.dispose();
    descriptionController.dispose();
    minutesController.dispose();
  });
}

Future<void> _showLearningTaskCheckinSheet(
  BuildContext context, {
  required CareerApplicationView? application,
  required List<CareerWorkbenchLearningTaskView> tasks,
  required VoidCallback onBackToChat,
  required WorkbenchPromptSender? onSendPrompt,
}) {
  if (tasks.isEmpty) {
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(
      const SnackBar(
        content: Text("当前还没有学习任务"),
        duration: Duration(seconds: 1),
      ),
    );
    return Future<void>.value();
  }
  final summaryController = TextEditingController();
  final blockersController = TextEditingController();
  final nextActionController = TextEditingController();
  final minutesController = TextEditingController();
  final orderedTasks = [...tasks]
    ..sort((a, b) => _taskSortRank(a).compareTo(_taskSortRank(b)));
  var selectedTaskId = orderedTasks.first.learningTaskId;
  var nextState = "";
  var error = "";

  CareerWorkbenchLearningTaskView selectedTask() {
    return orderedTasks.firstWhere(
      (task) => task.learningTaskId == selectedTaskId,
      orElse: () => orderedTasks.first,
    );
  }

  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    constraints: const BoxConstraints(maxWidth: double.infinity),
    builder: (sheetContext) {
      return StatefulBuilder(
        builder: (context, setSheetState) {
          Future<void> submit() async {
            final summary = summaryController.text.trim();
            final blockers = blockersController.text.trim();
            final nextAction = nextActionController.text.trim();
            if (summary.isEmpty && blockers.isEmpty && nextAction.isEmpty) {
              setSheetState(() => error = "至少写一项进展、卡点或下一步");
              return;
            }
            final rawMinutes = minutesController.text.trim();
            final minutes = rawMinutes.isEmpty
                ? 0
                : int.tryParse(rawMinutes.replaceAll(RegExp(r"[^0-9]"), ""));
            final task = selectedTask();
            Navigator.of(sheetContext).pop();
            await _sendLearningPrompt(
              context,
              application,
              label: "记录进度",
              actionType: "learning_checkin",
              intent: _learningCheckinIntent(
                task: task,
                summary: summary,
                blockers: blockers,
                nextAction: nextAction,
                minutes: minutes ?? 0,
                nextState: nextState,
              ),
              onBackToChat: onBackToChat,
              onSendPrompt: onSendPrompt,
            );
          }

          return SafeArea(
            top: false,
            child: Padding(
              padding: EdgeInsets.only(
                left: 12,
                right: 12,
                bottom: 12 + MediaQuery.viewInsetsOf(context).bottom,
              ),
              child: Align(
                alignment: Alignment.bottomCenter,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 760),
                  child: Container(
                    decoration: AppTheme.floatingPanelDecoration(
                      radius: 24,
                      alpha: 0.98,
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Container(
                                width: 34,
                                height: 34,
                                decoration: BoxDecoration(
                                  color: const Color(0xFF2563EB)
                                      .withValues(alpha: 0.1),
                                  borderRadius: BorderRadius.circular(12),
                                  border: Border.all(
                                    color: const Color(0xFF2563EB)
                                        .withValues(alpha: 0.18),
                                  ),
                                ),
                                child: const Icon(
                                  Icons.fact_check_outlined,
                                  size: 17,
                                  color: Color(0xFF2563EB),
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      "记录今日进度",
                                      style: AppTheme.ts(
                                        fontSize: 14,
                                        fontWeight: FontWeight.w900,
                                        color: AppTheme.textPrimary,
                                      ),
                                    ),
                                    const SizedBox(height: 3),
                                    Text(
                                      "只记录你明确提交的进展；状态变化也需要你主动选择。",
                                      style: AppTheme.ts(
                                        fontSize: 11,
                                        color: AppTheme.textTertiary,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              _WorkbenchIconButton(
                                icon: Icons.close_rounded,
                                tooltip: "关闭",
                                onTap: () => Navigator.of(sheetContext).pop(),
                              ),
                            ],
                          ),
                          const SizedBox(height: 16),
                          DropdownButtonFormField<String>(
                            initialValue: selectedTaskId,
                            isExpanded: true,
                            decoration: _noteInputDecoration("学习任务"),
                            items: [
                              for (final task in orderedTasks)
                                DropdownMenuItem(
                                  value: task.learningTaskId,
                                  child: Text(
                                    task.title.trim().isEmpty
                                        ? task.learningTaskId
                                        : task.title.trim(),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                            ],
                            onChanged: (value) => setSheetState(() {
                              selectedTaskId = value ?? selectedTaskId;
                            }),
                          ),
                          const SizedBox(height: 10),
                          TextField(
                            controller: summaryController,
                            minLines: 2,
                            maxLines: 4,
                            decoration: _noteInputDecoration("今天完成了什么"),
                            style: AppTheme.ts(
                              fontSize: 12.5,
                              height: 1.48,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 10),
                          LayoutBuilder(
                            builder: (context, constraints) {
                              final blockersField = TextField(
                                controller: blockersController,
                                minLines: 2,
                                maxLines: 3,
                                decoration: _noteInputDecoration("当前卡点（可选）"),
                                style: AppTheme.ts(
                                  fontSize: 12.5,
                                  height: 1.48,
                                  color: AppTheme.textPrimary,
                                ),
                              );
                              final nextField = TextField(
                                controller: nextActionController,
                                minLines: 2,
                                maxLines: 3,
                                decoration: _noteInputDecoration("下一步（可选）"),
                                style: AppTheme.ts(
                                  fontSize: 12.5,
                                  height: 1.48,
                                  color: AppTheme.textPrimary,
                                ),
                              );
                              if (constraints.maxWidth < 620) {
                                return Column(
                                  children: [
                                    blockersField,
                                    const SizedBox(height: 10),
                                    nextField,
                                  ],
                                );
                              }
                              return Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Expanded(child: blockersField),
                                  const SizedBox(width: 10),
                                  Expanded(child: nextField),
                                ],
                              );
                            },
                          ),
                          const SizedBox(height: 10),
                          LayoutBuilder(
                            builder: (context, constraints) {
                              final stateSelector = _LearningChoiceGroup(
                                label: "状态变化",
                                value: nextState,
                                options: const [
                                  _LearningChoiceOption("", "不变"),
                                  _LearningChoiceOption("doing", "进行中"),
                                  _LearningChoiceOption("blocked", "受阻"),
                                  _LearningChoiceOption("done", "完成"),
                                ],
                                onChanged: (value) => setSheetState(() {
                                  nextState = value;
                                }),
                              );
                              final minutesField = TextField(
                                controller: minutesController,
                                keyboardType: TextInputType.number,
                                decoration: _noteInputDecoration("投入分钟数"),
                                style: AppTheme.ts(
                                  fontSize: 12.5,
                                  color: AppTheme.textPrimary,
                                ),
                              );
                              if (constraints.maxWidth < 560) {
                                return Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    stateSelector,
                                    const SizedBox(height: 10),
                                    minutesField,
                                  ],
                                );
                              }
                              return Row(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Expanded(child: stateSelector),
                                  const SizedBox(width: 10),
                                  SizedBox(width: 180, child: minutesField),
                                ],
                              );
                            },
                          ),
                          if (error.isNotEmpty) ...[
                            const SizedBox(height: 10),
                            Text(
                              error,
                              style: AppTheme.ts(
                                fontSize: 11.5,
                                fontWeight: FontWeight.w800,
                                color: AppTheme.danger,
                              ),
                            ),
                          ],
                          const SizedBox(height: 16),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.end,
                            children: [
                              TextButton(
                                onPressed: () =>
                                    Navigator.of(sheetContext).pop(),
                                child: Text(
                                  "取消",
                                  style: AppTheme.ts(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w800,
                                    color: AppTheme.textSecondary,
                                  ),
                                ),
                              ),
                              const SizedBox(width: 8),
                              _SmallTextButton(
                                label: "交给 Agent 记录",
                                icon: Icons.arrow_forward_rounded,
                                onTap: () => unawaited(submit()),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
        },
      );
    },
  ).whenComplete(() {
    summaryController.dispose();
    blockersController.dispose();
    nextActionController.dispose();
    minutesController.dispose();
  });
}

class _LearningChoiceOption {
  final String value;
  final String label;

  const _LearningChoiceOption(this.value, this.label);
}

class _LearningChoiceGroup extends StatelessWidget {
  final String label;
  final String value;
  final List<_LearningChoiceOption> options;
  final ValueChanged<String> onChanged;

  const _LearningChoiceGroup({
    required this.label,
    required this.value,
    required this.options,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: AppTheme.ts(
            fontSize: 10.8,
            fontWeight: FontWeight.w900,
            color: AppTheme.textTertiary,
          ),
        ),
        const SizedBox(height: 7),
        Wrap(
          spacing: 7,
          runSpacing: 7,
          children: [
            for (final option in options)
              _LearningChoicePill(
                label: option.label,
                selected: option.value == value,
                onTap: () => onChanged(option.value),
              ),
          ],
        ),
      ],
    );
  }
}

class _LearningChoicePill extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _LearningChoicePill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: selected
                ? AppTheme.accent.withValues(alpha: 0.1)
                : AppTheme.surfaceHover.withValues(alpha: 0.34),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected
                  ? AppTheme.accent.withValues(alpha: 0.22)
                  : AppTheme.border.withValues(alpha: 0.72),
            ),
          ),
          child: Text(
            label,
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w900,
              color: selected ? AppTheme.accent : AppTheme.textSecondary,
            ),
          ),
        ),
      ),
    );
  }
}

class _LearningPlanSection extends StatelessWidget {
  final List<CareerWorkbenchLearningPlanView> plans;

  const _LearningPlanSection({required this.plans});

  @override
  Widget build(BuildContext context) {
    return _LearningSection(
      icon: Icons.route_outlined,
      title: "学习路线",
      subtitle: plans.isEmpty ? "暂无计划" : "${plans.length} 个计划",
      child: plans.isEmpty
          ? const _EmptyText("当前项目暂无学习计划。")
          : Column(
              children: [
                for (final plan in plans) ...[
                  _LearningPlanCard(plan: plan),
                  if (plan != plans.last) const SizedBox(height: 9),
                ],
              ],
            ),
    );
  }
}

class _LearningPlanCard extends StatelessWidget {
  final CareerWorkbenchLearningPlanView plan;

  const _LearningPlanCard({required this.plan});

  @override
  Widget build(BuildContext context) {
    final color = _priorityColor(plan.priority);
    return _LearningCard(
      icon: Icons.route_outlined,
      color: color,
      title: plan.title,
      subtitle: _firstNonEmpty([plan.progressSummary, plan.description]),
      chips: [
        _priorityLabel(plan.priority),
        if (plan.targetRole.trim().isNotEmpty) plan.targetRole.trim(),
        if (plan.targetCompany.trim().isNotEmpty) plan.targetCompany.trim(),
      ],
      tags: plan.focusSkillTags,
      footer: plan.goals.take(3).toList(),
      onTap: () => _showLearningDetailSheet(
        context,
        icon: Icons.route_outlined,
        color: color,
        title: plan.title,
        subtitle: "学习路线 · 更新 ${_formatTime(plan.updatedAt)}",
        markdown: _learningPlanMarkdown(plan),
      ),
    );
  }
}

class _LearningTaskBoard extends StatelessWidget {
  final List<CareerWorkbenchLearningTaskView> tasks;

  const _LearningTaskBoard({required this.tasks});

  @override
  Widget build(BuildContext context) {
    final todo = tasks
        .where((task) => task.state == "todo" || task.state.trim().isEmpty)
        .toList();
    final doing = tasks
        .where((task) => task.state == "doing" || task.state == "blocked")
        .toList();
    final done = tasks.where((task) => task.state == "done").toList();
    return _LearningSection(
      icon: Icons.checklist_rounded,
      title: "学习任务",
      subtitle: tasks.isEmpty ? "暂无任务" : "${tasks.length} 个任务",
      child: tasks.isEmpty
          ? const _EmptyText("还没有学习任务。可以使用上方入口新建，或基于当前项目生成推荐。")
          : LayoutBuilder(
              builder: (context, constraints) {
                final narrow = constraints.maxWidth < 780;
                final columns = [
                  _LearningTaskColumn(title: "待推进", tasks: todo),
                  _LearningTaskColumn(title: "进行中", tasks: doing),
                  _LearningTaskColumn(title: "已完成", tasks: done),
                ];
                if (narrow) {
                  return Column(
                    children: [
                      for (final column in columns) ...[
                        column,
                        if (column != columns.last) const SizedBox(height: 10),
                      ],
                    ],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final column in columns) ...[
                      Expanded(child: column),
                      if (column != columns.last) const SizedBox(width: 10),
                    ],
                  ],
                );
              },
            ),
    );
  }
}

class _LearningTaskColumn extends StatelessWidget {
  final String title;
  final List<CareerWorkbenchLearningTaskView> tasks;

  const _LearningTaskColumn({
    required this.title,
    required this.tasks,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.42),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.68)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 11.8,
                  fontWeight: FontWeight.w900,
                  color: AppTheme.textPrimary,
                ),
              ),
              const Spacer(),
              _CountBadge(count: tasks.length, selected: false),
            ],
          ),
          const SizedBox(height: 9),
          if (tasks.isEmpty)
            const _EmptyText("暂无")
          else
            for (final task in tasks) ...[
              _LearningTaskCard(task: task),
              if (task != tasks.last) const SizedBox(height: 8),
            ],
        ],
      ),
    );
  }
}

class _LearningTaskCard extends StatelessWidget {
  final CareerWorkbenchLearningTaskView task;

  const _LearningTaskCard({required this.task});

  @override
  Widget build(BuildContext context) {
    final color = task.state == "blocked"
        ? AppTheme.danger
        : _priorityColor(task.priority);
    return _LearningCard(
      icon: task.state == "done"
          ? Icons.check_circle_outline_rounded
          : Icons.checklist_rounded,
      color: color,
      title: task.title,
      subtitle: _firstNonEmpty([task.progressNotes, task.description]),
      chips: [
        _learningTaskSourceLabel(task),
        _taskStateLabel(task.state),
        _priorityLabel(task.priority),
        if (task.estimatedMinutes > 0) "${task.estimatedMinutes} 分钟",
        if (task.dueDate != null) "截止 ${_formatDate(task.dueDate!)}",
      ],
      tags: task.skillTags,
      footer: task.successCriteria.take(2).toList(),
      onTap: () => _showLearningDetailSheet(
        context,
        icon: Icons.checklist_rounded,
        color: color,
        title: task.title,
        subtitle:
            "${_taskStateLabel(task.state)} · 更新 ${_formatTime(task.updatedAt)}",
        markdown: _learningTaskMarkdown(task),
      ),
    );
  }
}

class _LearningWeaknessSection extends StatelessWidget {
  final List<CareerWorkbenchWeaknessView> weaknesses;

  const _LearningWeaknessSection({required this.weaknesses});

  @override
  Widget build(BuildContext context) {
    return _LearningSection(
      icon: Icons.report_problem_outlined,
      title: "短板跟踪",
      subtitle: weaknesses.isEmpty ? "暂无短板" : "${weaknesses.length} 个短板",
      child: weaknesses.isEmpty
          ? const _EmptyText("当前项目暂无短板跟踪。")
          : Column(
              children: [
                for (final weakness in weaknesses) ...[
                  _LearningWeaknessCard(weakness: weakness),
                  if (weakness != weaknesses.last) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _LearningWeaknessCard extends StatelessWidget {
  final CareerWorkbenchWeaknessView weakness;

  const _LearningWeaknessCard({required this.weakness});

  @override
  Widget build(BuildContext context) {
    final color = switch (weakness.severity) {
      "high" => AppTheme.danger,
      "low" => const Color(0xFF059669),
      _ => const Color(0xFFB45309),
    };
    return _LearningCard(
      icon: Icons.report_problem_outlined,
      color: color,
      title: weakness.title,
      subtitle: weakness.description,
      chips: [
        _weaknessSeverityLabel(weakness.severity),
        _weaknessStateLabel(weakness.state),
        _weaknessTypeLabel(weakness.weaknessType),
      ],
      tags: weakness.skillTags,
      footer: weakness.relatedTaskIds
          .map((id) => "关联任务 ${_compactLabel(id)}")
          .toList(),
      onTap: () => _showLearningDetailSheet(
        context,
        icon: Icons.report_problem_outlined,
        color: color,
        title: weakness.title,
        subtitle:
            "${_weaknessSeverityLabel(weakness.severity)} · 更新 ${_formatTime(weakness.updatedAt)}",
        markdown: _learningWeaknessMarkdown(weakness),
      ),
    );
  }
}

class _LearningReviewSection extends StatelessWidget {
  final List<CareerWorkbenchReviewView> reviews;

  const _LearningReviewSection({required this.reviews});

  @override
  Widget build(BuildContext context) {
    return _LearningSection(
      icon: Icons.event_repeat_outlined,
      title: "复盘安排",
      subtitle: reviews.isEmpty ? "暂无复盘" : "${reviews.length} 个安排",
      child: reviews.isEmpty
          ? const _EmptyText("当前项目暂无复盘安排。")
          : Column(
              children: [
                for (final review in reviews) ...[
                  _LearningReviewCard(review: review),
                  if (review != reviews.last) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _LearningReviewCard extends StatelessWidget {
  final CareerWorkbenchReviewView review;

  const _LearningReviewCard({required this.review});

  @override
  Widget build(BuildContext context) {
    final color =
        review.state == "done" ? const Color(0xFF059669) : AppTheme.accent;
    return _LearningCard(
      icon: Icons.event_repeat_outlined,
      color: color,
      title: review.title,
      subtitle: review.summary,
      chips: [
        _reviewStateLabel(review.state),
        _reviewTypeLabel(review.reviewType),
        if (review.reviewAt != null) "复盘 ${_formatDate(review.reviewAt!)}",
        if (review.nextReviewAt != null)
          "下次 ${_formatDate(review.nextReviewAt!)}",
      ],
      tags: const [],
      footer: const [],
      onTap: () => _showLearningDetailSheet(
        context,
        icon: Icons.event_repeat_outlined,
        color: color,
        title: review.title,
        subtitle:
            "${_reviewStateLabel(review.state)} · 更新 ${_formatTime(review.updatedAt)}",
        markdown: _learningReviewMarkdown(review),
      ),
    );
  }
}

class _LearningSection extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Widget child;

  const _LearningSection({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.76)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(11),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.18),
                  ),
                ),
                child: Icon(icon, size: 15, color: AppTheme.accent),
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
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }
}

class _LearningCard extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final List<String> chips;
  final List<String> tags;
  final List<String> footer;
  final VoidCallback onTap;

  const _LearningCard({
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
    required this.chips,
    required this.tags,
    required this.footer,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(15),
        onTap: onTap,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.045),
            borderRadius: BorderRadius.circular(15),
            border: Border.all(color: color.withValues(alpha: 0.13)),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: color.withValues(alpha: 0.16)),
                ),
                child: Icon(icon, size: 15, color: color),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        for (final chip in chips
                            .where((item) => item.trim().isNotEmpty)
                            .take(4))
                          _TinyTag(label: chip.trim(), color: color),
                      ],
                    ),
                    if (chips.isNotEmpty) const SizedBox(height: 7),
                    Text(
                      title.trim().isEmpty ? "未命名学习项" : title.trim(),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12.6,
                        height: 1.28,
                        fontWeight: FontWeight.w900,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    if (subtitle.trim().isNotEmpty) ...[
                      const SizedBox(height: 5),
                      Text(
                        subtitle.trim(),
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.3,
                          height: 1.42,
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
                          for (final tag in tags.take(5))
                            _TinyTag(label: tag, color: color),
                        ],
                      ),
                    ],
                    if (footer.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      for (final item in footer.take(3))
                        Padding(
                          padding: const EdgeInsets.only(bottom: 3),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(
                                Icons.check_rounded,
                                size: 13,
                                color: color.withValues(alpha: 0.84),
                              ),
                              const SizedBox(width: 5),
                              Expanded(
                                child: Text(
                                  item,
                                  style: AppTheme.ts(
                                    fontSize: 10.8,
                                    height: 1.35,
                                    color: AppTheme.textTertiary,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 6),
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
  String _selectedNoteType = "";

  @override
  void initState() {
    super.initState();
    Future.microtask(() => widget.provider.loadNotes());
  }

  List<NoteView> _visibleNotes(List<NoteView> notes) {
    if (_selectedNoteType.isEmpty) {
      return notes;
    }
    return notes
        .where((note) => _normalizeNoteType(note.noteType) == _selectedNoteType)
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final provider = widget.provider;
    final notes = provider.notes;
    final visibleNotes = _visibleNotes(notes);
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
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
            child: _NoteTypeFilterBar(
              value: _selectedNoteType,
              notes: notes,
              onChanged: (value) => setState(() {
                _selectedNoteType = value;
              }),
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
                        : visibleNotes.isEmpty
                            ? const Padding(
                                padding: EdgeInsets.all(14),
                                child: _EmptyText("当前筛选下暂无笔记。"),
                              )
                            : ListView.separated(
                                padding:
                                    const EdgeInsets.fromLTRB(14, 0, 14, 14),
                                itemBuilder: (context, index) {
                                  final note = visibleNotes[index];
                                  return _NoteSummaryTile(
                                    provider: provider,
                                    note: _summaryFromNote(note),
                                    sourceLabels:
                                        _noteSourceLabelsFromNote(note),
                                  );
                                },
                                separatorBuilder: (_, __) =>
                                    const SizedBox(height: 9),
                                itemCount: visibleNotes.length,
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
          _DetailProgressTimeline(
            application: view.application,
            notes: view.notes,
            timeline: view.timeline,
          ),
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

class _DetailProgressTimeline extends StatelessWidget {
  final CareerApplicationView application;
  final List<CareerNoteSummaryView> notes;
  final List<CareerTimelineItemView> timeline;

  const _DetailProgressTimeline({
    required this.application,
    required this.notes,
    required this.timeline,
  });

  @override
  Widget build(BuildContext context) {
    final items = _applicationProgressItems(application, notes, timeline);
    return _WorkbenchSection(
      icon: Icons.timeline_rounded,
      title: "求职进展",
      subtitle: items.isEmpty ? "暂无推进记录" : "${items.length} 条关键进展",
      child: items.isEmpty
          ? const _EmptyText("暂无投递或面试复盘记录。")
          : Column(
              children: [
                for (var index = 0; index < items.length; index++) ...[
                  _ProgressTimelineTile(
                    item: items[index],
                    isLast: index == items.length - 1,
                  ),
                ],
              ],
            ),
    );
  }
}

class _ProgressTimelineTile extends StatelessWidget {
  final _ProgressTimelineItem item;
  final bool isLast;

  const _ProgressTimelineTile({
    required this.item,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 30,
          child: Column(
            children: [
              Container(
                width: 26,
                height: 26,
                decoration: BoxDecoration(
                  color: item.color.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: item.color.withValues(alpha: 0.18)),
                ),
                child: Icon(item.icon, size: 14, color: item.color),
              ),
              if (!isLast)
                Container(
                  width: 1,
                  height: 48,
                  margin: const EdgeInsets.symmetric(vertical: 5),
                  color: AppTheme.border.withValues(alpha: 0.82),
                ),
            ],
          ),
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Container(
            margin: EdgeInsets.only(bottom: isLast ? 0 : 10),
            padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
            decoration: BoxDecoration(
              color: item.color.withValues(alpha: 0.045),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: item.color.withValues(alpha: 0.13)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        item.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 12.1,
                          fontWeight: FontWeight.w900,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      _formatTime(item.occurredAt),
                      style: AppTheme.ts(
                        fontSize: 10.2,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
                if (item.subtitle.trim().isNotEmpty) ...[
                  const SizedBox(height: 5),
                  Text(
                    item.subtitle.trim(),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 11,
                      height: 1.4,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
                if (item.tags.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final tag in item.tags.take(3))
                        _TinyTag(label: tag, color: item.color),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
      ],
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
    await sender(
      prompt,
      action: CareerWorkbenchActionRequest(
        applicationId: view.application.applicationId,
        actionType: action.actionType,
        label: action.label,
        origin: "project",
      ),
    );
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
      title: "关联笔记",
      subtitle: "${visible.length} 条上下文 · 点击笔记进入编辑",
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SmallTextButton(
            label: "新建笔记",
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
              seedNoteType: "resource",
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

class _NoteTypeFilterBar extends StatelessWidget {
  final String value;
  final List<NoteView> notes;
  final ValueChanged<String> onChanged;

  const _NoteTypeFilterBar({
    required this.value,
    required this.notes,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final counts = <String, int>{
      "": notes.length,
      for (final option in _noteTypeOptions) option.value: 0,
    };
    for (final note in notes) {
      final type = _normalizeNoteType(note.noteType);
      counts[type] = (counts[type] ?? 0) + 1;
    }
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _NoteTypeFilterChip(
            key: const Key("career_note_filter_all"),
            label: "全部",
            count: counts[""] ?? 0,
            icon: Icons.all_inbox_outlined,
            color: AppTheme.accent,
            selected: value.isEmpty,
            onTap: () => onChanged(""),
          ),
          const SizedBox(width: 7),
          for (final option in _noteTypeOptions) ...[
            _NoteTypeFilterChip(
              key: Key("career_note_filter_${option.value}"),
              label: option.label,
              count: counts[option.value] ?? 0,
              icon: option.icon,
              color: option.color,
              selected: value == option.value,
              onTap: () => onChanged(option.value),
            ),
            if (option != _noteTypeOptions.last) const SizedBox(width: 7),
          ],
        ],
      ),
    );
  }
}

class _NoteTypeFilterChip extends StatelessWidget {
  final String label;
  final int count;
  final IconData icon;
  final Color color;
  final bool selected;
  final VoidCallback onTap;

  const _NoteTypeFilterChip({
    super.key,
    required this.label,
    required this.count,
    required this.icon,
    required this.color,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: selected
                ? color.withValues(alpha: 0.11)
                : Colors.white.withValues(alpha: 0.56),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected
                  ? color.withValues(alpha: 0.28)
                  : AppTheme.border.withValues(alpha: 0.72),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                icon,
                size: 13,
                color: selected ? color : AppTheme.textTertiary,
              ),
              const SizedBox(width: 5),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  color: selected ? color : AppTheme.textSecondary,
                ),
              ),
              const SizedBox(width: 5),
              Text(
                "$count",
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w800,
                  color: selected ? color : AppTheme.textTertiary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoteSummaryTile extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerNoteSummaryView note;
  final List<String> sourceLabels;

  const _NoteSummaryTile({
    required this.provider,
    required this.note,
    this.sourceLabels = const [],
  });

  @override
  Widget build(BuildContext context) {
    final tags = note.tags.take(3).toList();
    final typeMeta = _noteTypeMeta(note.noteType);
    final metaItems = _noteSummaryMetaItems(note, sourceLabels);
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
            color: typeMeta.color.withValues(alpha: 0.045),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: typeMeta.color.withValues(alpha: 0.13),
            ),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: typeMeta.color.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: typeMeta.color.withValues(alpha: 0.16),
                  ),
                ),
                child: Icon(
                  typeMeta.icon,
                  size: 16,
                  color: typeMeta.color,
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
                        _TinyTag(
                          label: typeMeta.label,
                          color: typeMeta.color,
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
                    if (metaItems.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final item in metaItems)
                            _NoteMetaChip(
                              icon: item.icon,
                              label: item.label,
                            ),
                        ],
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
                              color: typeMeta.color,
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

class _NoteMetaItem {
  final IconData icon;
  final String label;

  const _NoteMetaItem({
    required this.icon,
    required this.label,
  });
}

class _NoteMetaChip extends StatelessWidget {
  final IconData icon;
  final String label;

  const _NoteMetaChip({
    required this.icon,
    required this.label,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 260),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.42),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.72)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: AppTheme.textTertiary),
          const SizedBox(width: 5),
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 10.3,
                fontWeight: FontWeight.w800,
                color: AppTheme.textTertiary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ProgressTimelineItem {
  final String title;
  final String subtitle;
  final DateTime occurredAt;
  final IconData icon;
  final Color color;
  final List<String> tags;

  const _ProgressTimelineItem({
    required this.title,
    required this.subtitle,
    required this.occurredAt,
    required this.icon,
    required this.color,
    this.tags = const [],
  });
}

class _NoteTypeMeta {
  final String value;
  final String label;
  final String hint;
  final IconData icon;
  final Color color;

  const _NoteTypeMeta({
    required this.value,
    required this.label,
    required this.hint,
    required this.icon,
    required this.color,
  });
}

const _noteTypeOptions = <_NoteTypeMeta>[
  _NoteTypeMeta(
    value: "note",
    label: "记录",
    hint: "适合想法、总结、过程记录和杂项内容，后续作为个人上下文参考。",
    icon: Icons.edit_note_outlined,
    color: Color(0xFFB45309),
  ),
  _NoteTypeMeta(
    value: "learning",
    label: "学习",
    hint: "适合知识点、学习计划和短板复盘，后续学习建议会优先参考。",
    icon: Icons.school_outlined,
    color: Color(0xFF2563EB),
  ),
  _NoteTypeMeta(
    value: "resource",
    label: "资料",
    hint: "适合面经、文章、链接或资产摘录，后续检索时作为参考材料。",
    icon: Icons.bookmark_border_rounded,
    color: Color(0xFF059669),
  ),
];

_NoteTypeMeta _noteTypeMeta(String value) {
  final normalized = _normalizeNoteType(value);
  for (final option in _noteTypeOptions) {
    if (option.value == normalized) return option;
  }
  return _noteTypeOptions.first;
}

String _normalizeNoteType(String value) {
  final normalized = value.trim().toLowerCase();
  if (normalized == "learning" || normalized == "resource") {
    return normalized;
  }
  return "note";
}

enum _NoteBodyMode { edit, preview, live }

class _NoteEditDraft {
  final String title;
  final String bodyMarkdown;
  final String summary;
  final List<String> tags;
  final String noteType;

  const _NoteEditDraft({
    required this.title,
    required this.bodyMarkdown,
    required this.summary,
    required this.tags,
    required this.noteType,
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
  late String _noteType;
  late _NoteBodyMode _bodyMode;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.note.title);
    _summaryController = TextEditingController(text: widget.note.summary);
    _tagsController = TextEditingController(text: widget.note.tags.join("，"));
    _bodyController = TextEditingController(text: widget.note.bodyMarkdown);
    _bodyController.addListener(_handleBodyChanged);
    _noteType = _normalizeNoteType(widget.note.noteType);
    _bodyMode = widget.note.noteId != "note_draft"
        ? _NoteBodyMode.preview
        : _NoteBodyMode.edit;
  }

  @override
  void dispose() {
    _bodyController.removeListener(_handleBodyChanged);
    _titleController.dispose();
    _summaryController.dispose();
    _tagsController.dispose();
    _bodyController.dispose();
    super.dispose();
  }

  void _handleBodyChanged() {
    if (!mounted || _bodyMode != _NoteBodyMode.live) {
      return;
    }
    setState(() {});
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
          noteType: _noteType,
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
          _NoteEditorMetaStrip(
            note: widget.note,
            noteType: _noteType,
          ),
          const SizedBox(height: 12),
          _NoteTypeSelector(
            value: _noteType,
            onChanged: (value) => setState(() {
              _noteType = _normalizeNoteType(value);
            }),
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
          _NoteBodyHeader(
            mode: _bodyMode,
            onChanged: (value) => setState(() => _bodyMode = value),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: switch (_bodyMode) {
              _NoteBodyMode.edit => _NoteMarkdownEditor(
                  controller: _bodyController,
                ),
              _NoteBodyMode.preview => _NoteMarkdownPreview(
                  content: _bodyController.text,
                  onEdit: () => setState(() => _bodyMode = _NoteBodyMode.edit),
                ),
              _NoteBodyMode.live => _NoteLiveMarkdownEditor(
                  controller: _bodyController,
                ),
            },
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

class _NoteEditorMetaStrip extends StatelessWidget {
  final NoteView note;
  final String noteType;

  const _NoteEditorMetaStrip({
    required this.note,
    required this.noteType,
  });

  @override
  Widget build(BuildContext context) {
    final typeMeta = _noteTypeMeta(noteType);
    final items = <_NoteMetaItem>[
      _NoteMetaItem(icon: typeMeta.icon, label: "类型 ${typeMeta.label}"),
    ];
    if (note.noteId == "note_draft") {
      items.add(
        const _NoteMetaItem(
          icon: Icons.fiber_new_rounded,
          label: "新笔记",
        ),
      );
    } else {
      items.add(
        _NoteMetaItem(
          icon: Icons.schedule_rounded,
          label: "更新 ${_formatTime(note.updatedAt)}",
        ),
      );
    }
    final relatedApplicationId = note.relatedApplicationId?.trim() ?? "";
    if (relatedApplicationId.isNotEmpty) {
      items.add(
        _NoteMetaItem(
          icon: Icons.work_outline_rounded,
          label: "关联项目 ${_compactLabel(relatedApplicationId)}",
        ),
      );
    }
    final sourceArtifactId = note.sourceArtifactId?.trim() ?? "";
    if (sourceArtifactId.isNotEmpty) {
      items.add(
        _NoteMetaItem(
          icon: Icons.insert_drive_file_outlined,
          label: "来源文件 ${_compactLabel(sourceArtifactId)}",
        ),
      );
    }
    for (final label in _noteSourceLabelsFromNote(note)) {
      items.add(_NoteMetaItem(icon: Icons.link_rounded, label: label));
    }
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.28),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.62)),
      ),
      child: Wrap(
        spacing: 7,
        runSpacing: 7,
        children: [
          for (final item in items)
            _NoteMetaChip(
              icon: item.icon,
              label: item.label,
            ),
        ],
      ),
    );
  }
}

class _NoteTypeSelector extends StatelessWidget {
  final String value;
  final ValueChanged<String> onChanged;

  const _NoteTypeSelector({
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final selected = _noteTypeMeta(value);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.66),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.78)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                "笔记类型",
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w900,
                  color: AppTheme.textSecondary,
                ),
              ),
              const Spacer(),
              Text(
                "影响后续检索和建议",
                style: AppTheme.ts(
                  fontSize: 10.5,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              for (final option in _noteTypeOptions)
                _NoteTypePill(
                  meta: option,
                  selected: option.value == selected.value,
                  onTap: () => onChanged(option.value),
                ),
            ],
          ),
          const SizedBox(height: 7),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                selected.icon,
                size: 13,
                color: selected.color.withValues(alpha: 0.78),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  selected.hint,
                  style: AppTheme.ts(
                    fontSize: 10.8,
                    height: 1.35,
                    color: AppTheme.textTertiary,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _NoteTypePill extends StatelessWidget {
  final _NoteTypeMeta meta;
  final bool selected;
  final VoidCallback onTap;

  const _NoteTypePill({
    required this.meta,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        key: Key("career_note_type_${meta.value}"),
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: selected
                ? meta.color.withValues(alpha: 0.1)
                : Colors.white.withValues(alpha: 0.68),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected
                  ? meta.color.withValues(alpha: 0.28)
                  : AppTheme.border.withValues(alpha: 0.8),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                meta.icon,
                size: 13,
                color: selected ? meta.color : AppTheme.textTertiary,
              ),
              const SizedBox(width: 5),
              Text(
                meta.label,
                style: AppTheme.ts(
                  fontSize: 11.2,
                  fontWeight: selected ? FontWeight.w900 : FontWeight.w700,
                  color: selected ? meta.color : AppTheme.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoteBodyHeader extends StatelessWidget {
  final _NoteBodyMode mode;
  final ValueChanged<_NoteBodyMode> onChanged;

  const _NoteBodyHeader({
    required this.mode,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final hint = switch (mode) {
      _NoteBodyMode.edit => "支持 Markdown，保存后仍可预览",
      _NoteBodyMode.preview => "已按 Markdown 渲染",
      _NoteBodyMode.live => "左侧编辑，右侧实时渲染",
    };
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                "正文",
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w900,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                hint,
                style: AppTheme.ts(
                  fontSize: 10.6,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
        ),
        _NoteBodyModeSwitch(
          mode: mode,
          onChanged: onChanged,
        ),
      ],
    );
  }
}

class _NoteBodyModeSwitch extends StatelessWidget {
  final _NoteBodyMode mode;
  final ValueChanged<_NoteBodyMode> onChanged;

  const _NoteBodyModeSwitch({
    required this.mode,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.52),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.76)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _NoteBodyModePill(
            label: "编辑",
            icon: Icons.edit_outlined,
            selected: mode == _NoteBodyMode.edit,
            onTap: () => onChanged(_NoteBodyMode.edit),
          ),
          _NoteBodyModePill(
            label: "实时",
            icon: Icons.splitscreen_rounded,
            selected: mode == _NoteBodyMode.live,
            onTap: () => onChanged(_NoteBodyMode.live),
          ),
          _NoteBodyModePill(
            label: "预览",
            icon: Icons.visibility_outlined,
            selected: mode == _NoteBodyMode.preview,
            onTap: () => onChanged(_NoteBodyMode.preview),
          ),
        ],
      ),
    );
  }
}

class _NoteBodyModePill extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  const _NoteBodyModePill({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        key: Key("career_note_body_mode_$label"),
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: selected
                ? Colors.white.withValues(alpha: 0.86)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(999),
            boxShadow: selected
                ? [
                    BoxShadow(
                      color: AppTheme.textPrimary.withValues(alpha: 0.06),
                      blurRadius: 10,
                      offset: const Offset(0, 4),
                    ),
                  ]
                : null,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                icon,
                size: 13,
                color: selected ? AppTheme.accent : AppTheme.textTertiary,
              ),
              const SizedBox(width: 5),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  color: selected ? AppTheme.accent : AppTheme.textTertiary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoteMarkdownEditor extends StatelessWidget {
  final TextEditingController controller;

  const _NoteMarkdownEditor({required this.controller});

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: const Key("career_note_body_field"),
      controller: controller,
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
    );
  }
}

class _NoteLiveMarkdownEditor extends StatelessWidget {
  final TextEditingController controller;

  const _NoteLiveMarkdownEditor({required this.controller});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final editor = _NoteRealtimePane(
          label: "Markdown",
          icon: Icons.edit_outlined,
          child: _NoteMarkdownEditor(controller: controller),
        );
        final preview = _NoteRealtimePane(
          label: "实时预览",
          icon: Icons.visibility_outlined,
          child: _NoteMarkdownPreview(
            content: controller.text,
          ),
        );
        if (constraints.maxWidth < 720) {
          return Column(
            children: [
              Expanded(child: editor),
              const SizedBox(height: 10),
              Expanded(child: preview),
            ],
          );
        }
        return Row(
          children: [
            Expanded(child: editor),
            const SizedBox(width: 10),
            Expanded(child: preview),
          ],
        );
      },
    );
  }
}

class _NoteRealtimePane extends StatelessWidget {
  final String label;
  final IconData icon;
  final Widget child;

  const _NoteRealtimePane({
    required this.label,
    required this.icon,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 13, color: AppTheme.textTertiary),
            const SizedBox(width: 5),
            Text(
              label,
              style: AppTheme.ts(
                fontSize: 10.8,
                fontWeight: FontWeight.w900,
                color: AppTheme.textTertiary,
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Expanded(child: child),
      ],
    );
  }
}

class _NoteMarkdownPreview extends StatelessWidget {
  final String content;
  final VoidCallback? onEdit;

  const _NoteMarkdownPreview({
    required this.content,
    this.onEdit,
  });

  @override
  Widget build(BuildContext context) {
    final normalized = content.trim();
    return Container(
      key: const Key("career_note_markdown_preview"),
      width: double.infinity,
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.7),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.78)),
      ),
      child: normalized.isEmpty
          ? Center(
              child: onEdit == null
                  ? const _EmptyText("暂无内容。")
                  : _SmallTextButton(
                      label: "开始编辑",
                      icon: Icons.edit_outlined,
                      onTap: onEdit!,
                    ),
            )
          : ClipRRect(
              borderRadius: BorderRadius.circular(16),
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
                child: AppMarkdownBody(
                  content: normalized,
                  style: AppTheme.ts(
                    fontSize: 13.2,
                    height: 1.62,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ),
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
  String seedNoteType = "note",
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
    noteType: _normalizeNoteType(seedNoteType),
    collectionId: null,
    tags: const [],
    sourceRefs:
        sourceRefs.map((item) => NoteSourceRefView.fromJson(item)).toList(),
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
                            noteType: noteDraft.noteType,
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
                                          noteType: draft.noteType,
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

List<_AssetLibraryItem> _resumeLibraryItems(
  CareerWorkbenchProvider provider,
  _ResumeLibraryFilter filter,
) {
  final apps = provider.applications.map((item) => item.application).toList();
  final items = <_AssetLibraryItem>[];
  if (filter == _ResumeLibraryFilter.all ||
      filter == _ResumeLibraryFilter.resumeProfiles) {
    for (final record in provider.resumeProfiles) {
      final linkedApps = apps
          .where((app) => app.resumeProfileId == record.resumeProfileId)
          .toList();
      items.add(
        _AssetLibraryItem(
          id: record.resumeProfileId,
          typeLabel: "简历画像",
          title: record.displayName,
          subtitle: _firstNonEmpty([
            record.selfEvaluation,
            "从简历中提取的候选人结构化画像",
          ]),
          projectLabel: _projectLabel(linkedApps),
          icon: Icons.badge_outlined,
          color: AppTheme.accent,
          updatedAt: record.meta.updatedAt,
          stats: [
            _AssetStat(
              label: "技能",
              value: record.skills.length.toString(),
              icon: Icons.auto_awesome_motion_outlined,
            ),
            _AssetStat(
              label: "项目",
              value: record.projectExperience.length.toString(),
              icon: Icons.workspaces_outline,
            ),
            _AssetStat(
              label: "经历",
              value: record.workExperience.length.toString(),
              icon: Icons.business_center_outlined,
            ),
          ],
          tags: _dynamicSnippets(record.skills, limit: 5),
          previewActions: [
            ..._artifactPreviewActions(
              sourceSessionId: record.meta.sourceSessionId,
              artifactId: record.rawTextArtifactId,
              label: "原文",
              icon: Icons.article_outlined,
            ),
            ..._artifactPreviewActions(
              sourceSessionId: record.meta.sourceSessionId,
              artifactId: record.diagnosisArtifactId,
              label: "诊断",
              icon: Icons.fact_check_outlined,
            ),
          ],
          detailMarkdown: _resumeProfileMarkdown(record, linkedApps),
        ),
      );
    }
  }
  if (filter == _ResumeLibraryFilter.all ||
      filter == _ResumeLibraryFilter.careerProfiles) {
    for (final record in provider.careerProfiles) {
      final linkedApps = apps
          .where((app) => app.careerProfileId == record.careerProfileId)
          .toList();
      items.add(
        _AssetLibraryItem(
          id: record.careerProfileId,
          typeLabel: "职业画像",
          title: _firstNonEmpty([record.careerGoal, record.careerProfileId]),
          subtitle: _firstNonEmpty([
            record.experienceSummary,
            record.educationSummary,
            "长期可复用的职业方向、优势和短板记录",
          ]),
          projectLabel: _projectLabel(linkedApps),
          icon: Icons.track_changes_rounded,
          color: const Color(0xFF7C3AED),
          updatedAt: record.meta.updatedAt,
          stats: [
            _AssetStat(
              label: "目标",
              value: record.targetRoles.length.toString(),
              icon: Icons.flag_outlined,
            ),
            _AssetStat(
              label: "优势",
              value: record.strengths.length.toString(),
              icon: Icons.trending_up_rounded,
            ),
            _AssetStat(
              label: "短板",
              value: record.weaknesses.length.toString(),
              icon: Icons.warning_amber_rounded,
            ),
          ],
          tags: [
            ...record.targetRoles,
            ...record.preferredCities,
            ...record.skills,
          ],
          previewActions: const [],
          detailMarkdown: _careerProfileMarkdown(record, linkedApps),
        ),
      );
    }
  }
  if (filter == _ResumeLibraryFilter.all ||
      filter == _ResumeLibraryFilter.versions) {
    for (final record in provider.resumeVersions) {
      final linkedApps = apps
          .where((app) => app.resumeVersionIds.contains(record.resumeVersionId))
          .toList();
      items.add(
        _AssetLibraryItem(
          id: record.resumeVersionId,
          typeLabel: "简历版本",
          title: record.title.trim().isEmpty
              ? record.resumeVersionId
              : record.title.trim(),
          subtitle: _firstNonEmpty([
            record.changeSummary.isEmpty ? null : record.changeSummary.first,
            "面向岗位生成的可预览简历版本",
          ]),
          projectLabel: _projectLabel(linkedApps),
          icon: Icons.description_outlined,
          color: const Color(0xFF2563EB),
          updatedAt: record.meta.updatedAt,
          stats: [
            _AssetStat(
              label: "改写",
              value: record.changeSummary.length.toString(),
              icon: Icons.edit_note_outlined,
            ),
            _AssetStat(
              label: "关键词",
              value: record.keywordStrategy.length.toString(),
              icon: Icons.key_outlined,
            ),
            _AssetStat(
              label: "风险",
              value: record.riskNotes.length.toString(),
              icon: Icons.warning_amber_rounded,
            ),
          ],
          tags: record.keywordStrategy,
          previewActions: _artifactPreviewActions(
            sourceSessionId: record.meta.sourceSessionId,
            artifactId: record.artifactId,
            label: "预览",
            icon: Icons.visibility_outlined,
          ),
          detailMarkdown: _resumeVersionMarkdown(record, linkedApps),
        ),
      );
    }
  }
  items.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  return items;
}

List<_AssetLibraryItem> _jobMatchLibraryItems(
  CareerWorkbenchProvider provider,
  _JobMatchLibraryFilter filter,
) {
  final apps = provider.applications.map((item) => item.application).toList();
  final jdById = {
    for (final jd in provider.jdAnalyses) jd.jdAnalysisId: jd,
  };
  final items = <_AssetLibraryItem>[];
  if (filter == _JobMatchLibraryFilter.all ||
      filter == _JobMatchLibraryFilter.jdAnalyses) {
    for (final record in provider.jdAnalyses) {
      final linkedApps =
          apps.where((app) => app.jdAnalysisId == record.jdAnalysisId).toList();
      items.add(
        _AssetLibraryItem(
          id: record.jdAnalysisId,
          typeLabel: "JD 分析",
          title: record.displayTitle,
          subtitle: _firstNonEmpty([
            record.responsibilities.isEmpty
                ? null
                : record.responsibilities.first,
            "岗位要求、关键词、风险和面试关注点",
          ]),
          projectLabel: _projectLabel(linkedApps),
          icon: Icons.article_outlined,
          color: const Color(0xFF0891B2),
          updatedAt: record.meta.updatedAt,
          stats: [
            _AssetStat(
              label: "硬性",
              value: record.requiredSkills.length.toString(),
              icon: Icons.check_circle_outline_rounded,
            ),
            _AssetStat(
              label: "加分",
              value: record.preferredSkills.length.toString(),
              icon: Icons.add_circle_outline_rounded,
            ),
            _AssetStat(
              label: "风险",
              value: record.riskSignals.length.toString(),
              icon: Icons.warning_amber_rounded,
            ),
          ],
          tags: [
            ...record.requiredSkills,
            ...record.preferredSkills,
            ...record.keywords,
          ],
          previewActions: _artifactPreviewActions(
            sourceSessionId: record.meta.sourceSessionId,
            artifactId: record.meta.sourceArtifactId,
            label: "JD 原文",
            icon: Icons.visibility_outlined,
          ),
          detailMarkdown: _jdAnalysisMarkdown(record, linkedApps),
        ),
      );
    }
  }
  if (filter == _JobMatchLibraryFilter.all ||
      filter == _JobMatchLibraryFilter.fitReports) {
    for (final record in provider.jobFitReports) {
      final linkedApps = apps
          .where((app) => app.jobFitReportId == record.jobFitReportId)
          .toList();
      final jd = jdById[record.jdAnalysisId];
      items.add(
        _AssetLibraryItem(
          id: record.jobFitReportId,
          typeLabel: "匹配报告",
          title: _firstNonEmpty([
            linkedApps.isEmpty ? null : linkedApps.first.displayTitle,
            jd?.displayTitle,
            record.jobFitReportId,
          ]),
          subtitle: _recommendationLabel(record.recommendation),
          projectLabel: _projectLabel(linkedApps),
          icon: Icons.fact_check_outlined,
          color: const Color(0xFF0EA5E9),
          updatedAt: record.meta.updatedAt,
          stats: [
            _AssetStat(
              label: "匹配",
              value: "${record.overallScore}/100",
              icon: Icons.speed_rounded,
            ),
            _AssetStat(
              label: "证据",
              value: record.matchedEvidence.length.toString(),
              icon: Icons.verified_outlined,
            ),
            _AssetStat(
              label: "短板",
              value: record.gaps.length.toString(),
              icon: Icons.report_problem_outlined,
            ),
          ],
          tags: record.scoreBreakdown.keys.toList(),
          previewActions: _artifactPreviewActions(
            sourceSessionId: record.meta.sourceSessionId,
            artifactId: record.reportArtifactId,
            label: "报告",
            icon: Icons.visibility_outlined,
          ),
          detailMarkdown: _jobFitReportMarkdown(record, linkedApps, jd),
        ),
      );
    }
  }
  items.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  return items;
}

List<_AssetPreviewAction> _artifactPreviewActions({
  required String sourceSessionId,
  required String? artifactId,
  required String label,
  required IconData icon,
}) {
  final normalizedArtifactId = artifactId?.trim() ?? "";
  final normalizedSessionId = sourceSessionId.trim();
  if (normalizedArtifactId.isEmpty || normalizedSessionId.isEmpty) {
    return const [];
  }
  return [
    _AssetPreviewAction(
      label: label,
      icon: icon,
      sourceSessionId: normalizedSessionId,
      artifactId: normalizedArtifactId,
    ),
  ];
}

String _projectLabel(List<CareerApplicationView> apps) {
  if (apps.isEmpty) return "";
  if (apps.length == 1) return _compactLabel(apps.first.displayTitle);
  return "关联 ${apps.length} 个项目";
}

List<String> _dynamicSnippets(List<dynamic> values, {int limit = 6}) {
  final seen = <String>{};
  final result = <String>[];
  for (final value in values) {
    final text = _dynamicSnippet(value);
    if (text.isEmpty || seen.contains(text)) continue;
    result.add(text);
    seen.add(text);
    if (result.length >= limit) break;
  }
  return result;
}

String _dynamicSnippet(dynamic value) {
  if (value == null) return "";
  if (value is String) return value.trim();
  if (value is num || value is bool) return value.toString();
  if (value is Map) {
    for (final key in [
      "name",
      "title",
      "skill",
      "keyword",
      "project_name",
      "company",
      "school",
      "role",
      "description",
      "summary",
    ]) {
      final candidate = value[key];
      if (candidate is String && candidate.trim().isNotEmpty) {
        return candidate.trim();
      }
    }
    for (final entry in value.entries) {
      final text = _dynamicSnippet(entry.value);
      if (text.isNotEmpty) return text;
    }
  }
  if (value is Iterable) {
    return value
        .map(_dynamicSnippet)
        .where((item) => item.isNotEmpty)
        .join(" / ");
  }
  return value.toString().trim();
}

String _bulletSection(String title, List<String> items) {
  final visible =
      items.map((item) => item.trim()).where((item) => item.isNotEmpty);
  if (visible.isEmpty) return "";
  return "## $title\n\n${visible.map((item) => "- $item").join("\n")}\n";
}

String _metaSection(CareerRecordMetaView meta) {
  return """
## 记录信息

- 状态：${meta.status}
- 来源会话：${meta.sourceSessionId}
${meta.sourceArtifactId == null ? "" : "- 来源文件：${meta.sourceArtifactId}\n"}- 更新：${_formatTime(meta.updatedAt)}
""";
}

String _resumeProfileMarkdown(
  ResumeProfileView record,
  List<CareerApplicationView> apps,
) {
  return """
# ${record.displayName}

${_projectLine(apps)}

${_bulletSection("技能", _dynamicSnippets(record.skills, limit: 12))}
${_bulletSection("项目经历", _dynamicSnippets(record.projectExperience, limit: 8))}
${_bulletSection("工作经历", _dynamicSnippets(record.workExperience, limit: 8))}
${_bulletSection("教育经历", _dynamicSnippets(record.education, limit: 4))}
${record.selfEvaluation.trim().isEmpty ? "" : "## 自我评价\n\n${record.selfEvaluation.trim()}\n"}
${_metaSection(record.meta)}
""";
}

String _careerProfileMarkdown(
  CareerProfileView record,
  List<CareerApplicationView> apps,
) {
  return """
# ${_firstNonEmpty([record.careerGoal, record.careerProfileId])}

${_projectLine(apps)}

${_bulletSection("目标方向", record.targetRoles)}
${_bulletSection("核心优势", record.strengths)}
${_bulletSection("当前短板", record.weaknesses)}
${_bulletSection("技能关键词", record.skills)}
${record.experienceSummary.trim().isEmpty ? "" : "## 经历摘要\n\n${record.experienceSummary.trim()}\n"}
${record.educationSummary.trim().isEmpty ? "" : "## 教育摘要\n\n${record.educationSummary.trim()}\n"}
${_metaSection(record.meta)}
""";
}

String _resumeVersionMarkdown(
  ResumeVersionView record,
  List<CareerApplicationView> apps,
) {
  return """
# ${record.title.trim().isEmpty ? record.resumeVersionId : record.title.trim()}

${_projectLine(apps)}

- 格式：${record.format}
- 基础画像：${record.baseResumeProfileId}
${record.targetJdAnalysisId == null ? "" : "- 目标 JD：${record.targetJdAnalysisId}\n"}
${_bulletSection("改写摘要", record.changeSummary)}
${_bulletSection("关键词策略", record.keywordStrategy)}
${_bulletSection("风险提醒", record.riskNotes)}
${_metaSection(record.meta)}
""";
}

String _jdAnalysisMarkdown(
  JDAnalysisView record,
  List<CareerApplicationView> apps,
) {
  return """
# ${record.displayTitle}

${_projectLine(apps)}

- 公司：${record.company}
- 岗位：${record.position}
- 级别：${record.seniority}

${_bulletSection("硬性要求", record.requiredSkills)}
${_bulletSection("加分项", record.preferredSkills)}
${_bulletSection("岗位职责", record.responsibilities)}
${_bulletSection("风险信号", record.riskSignals)}
${_bulletSection("面试关注点", record.interviewFocus)}
${_metaSection(record.meta)}
""";
}

String _jobFitReportMarkdown(
  JobFitReportView record,
  List<CareerApplicationView> apps,
  JDAnalysisView? jd,
) {
  final breakdown = record.scoreBreakdown.entries
      .map((entry) => "${entry.key}：${entry.value}")
      .toList();
  return """
# ${_firstNonEmpty([
        apps.isEmpty ? null : apps.first.displayTitle,
        jd?.displayTitle,
        record.jobFitReportId,
      ])}

${_projectLine(apps)}

- 综合匹配：${record.overallScore}/100
- 推荐结论：${_recommendationLabel(record.recommendation)}
- JD 分析：${record.jdAnalysisId}
- 简历画像：${record.resumeProfileId}
- 职业画像：${record.careerProfileId}

${_bulletSection("评分维度", breakdown)}
${_bulletSection("匹配证据", _dynamicSnippets(record.matchedEvidence, limit: 12))}
${_bulletSection("主要短板", _dynamicSnippets(record.gaps, limit: 10))}
${_bulletSection("简历优化方向", _dynamicSnippets(record.resumeOptimizationDirection, limit: 10))}
${_bulletSection("面试准备重点", _dynamicSnippets(record.interviewPreparationFocus, limit: 10))}
${_metaSection(record.meta)}
""";
}

String _projectLine(List<CareerApplicationView> apps) {
  if (apps.isEmpty) return "";
  return "关联项目：${apps.map((app) => app.displayTitle).join("、")}\n";
}

Future<void> _showLibraryDetailSheet(
  BuildContext context,
  _AssetLibraryItem item,
) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    constraints: const BoxConstraints(maxWidth: double.infinity),
    builder: (sheetContext) {
      return SafeArea(
        top: false,
        child: FractionallySizedBox(
          heightFactor: 0.88,
          child: Align(
            alignment: Alignment.bottomCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 920),
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
                          Container(
                            width: 34,
                            height: 34,
                            decoration: BoxDecoration(
                              color: item.color.withValues(alpha: 0.11),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(
                                color: item.color.withValues(alpha: 0.18),
                              ),
                            ),
                            child: Icon(
                              item.icon,
                              size: 17,
                              color: item.color,
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  item.title,
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
                                  "${item.typeLabel} · 更新 ${_formatTime(item.updatedAt)}",
                                  style: AppTheme.ts(
                                    fontSize: 10.8,
                                    color: AppTheme.textTertiary,
                                  ),
                                ),
                              ],
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
                      child: SingleChildScrollView(
                        padding: const EdgeInsets.fromLTRB(24, 22, 24, 28),
                        child: AppMarkdownBody(
                          content: item.detailMarkdown.trim(),
                          style: AppTheme.ts(
                            fontSize: 13.8,
                            height: 1.68,
                            color: AppTheme.textPrimary,
                          ),
                        ),
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

int _taskSortRank(CareerWorkbenchLearningTaskView task) {
  final stateRank = switch (task.state) {
    "doing" => 0,
    "blocked" => 1,
    "todo" => 2,
    "done" => 4,
    _ => 3,
  };
  final due = task.dueDate?.millisecondsSinceEpoch ?? 9999999999999;
  final priority = switch (task.priority) {
    "high" => 0,
    "medium" => 1,
    "low" => 2,
    _ => 3,
  };
  return stateRank * 10000000000000 + due + priority;
}

int _weaknessSortRank(CareerWorkbenchWeaknessView weakness) {
  final severity = switch (weakness.severity) {
    "high" => 0,
    "medium" => 1,
    "low" => 2,
    _ => 3,
  };
  final state = weakness.state == "resolved" ? 10 : 0;
  return state + severity;
}

int _reviewSortTime(CareerWorkbenchReviewView review) {
  return (review.reviewAt ?? review.nextReviewAt ?? review.updatedAt)
      .millisecondsSinceEpoch;
}

String _formatDate(DateTime time) {
  return DateFormat("MM-dd").format(time);
}

String _weaknessStateLabel(String state) {
  return switch (state) {
    "open" => "待处理",
    "tracking" => "跟踪中",
    "resolved" => "已改善",
    _ => state.trim().isEmpty ? "待处理" : state,
  };
}

String _weaknessTypeLabel(String type) {
  return switch (type) {
    "skill" => "技能",
    "experience" => "经历",
    "project" => "项目",
    "interview" => "面试",
    "resume" => "简历",
    _ => type.trim().isEmpty ? "短板" : type,
  };
}

String _reviewStateLabel(String state) {
  return switch (state) {
    "scheduled" => "已安排",
    "done" => "已复盘",
    "skipped" => "已跳过",
    _ => state.trim().isEmpty ? "已安排" : state,
  };
}

String _reviewTypeLabel(String type) {
  return switch (type) {
    "daily" => "日复盘",
    "weekly" => "周复盘",
    "interview" => "面试复盘",
    "task" => "任务复盘",
    _ => type.trim().isEmpty ? "复盘" : type,
  };
}

Future<void> _sendLearningPrompt(
  BuildContext context,
  CareerApplicationView? application, {
  required String label,
  required String actionType,
  required String intent,
  required VoidCallback onBackToChat,
  required WorkbenchPromptSender? onSendPrompt,
}) async {
  final sender = onSendPrompt;
  final messenger = ScaffoldMessenger.maybeOf(context);
  if (sender == null) {
    messenger?.showSnackBar(
      const SnackBar(content: Text("当前入口暂不可用")),
    );
    return;
  }
  onBackToChat();
  await sender(
    _learningActionPrompt(application, intent),
    action: application == null
        ? null
        : CareerWorkbenchActionRequest(
            applicationId: application.applicationId,
            actionType: actionType,
            label: label,
            origin: "learning",
          ),
  );
}

String _learningActionPrompt(
  CareerApplicationView? application,
  String intent,
) {
  final lines = application == null
      ? <String>[
          "- 当前没有绑定求职项目",
          "- 可以创建用户主动添加的全局 LearningTask",
        ]
      : <String>[
          "- application_id: ${application.applicationId}",
          if (application.company.trim().isNotEmpty)
            "- company: ${application.company.trim()}",
          if (application.position.trim().isNotEmpty)
            "- position: ${application.position.trim()}",
          if (application.jdAnalysisId?.trim().isNotEmpty == true)
            "- jd_analysis_id: ${application.jdAnalysisId!.trim()}",
          if (application.jobFitReportId?.trim().isNotEmpty == true)
            "- job_fit_report_id: ${application.jobFitReportId!.trim()}",
          if (application.resumeProfileId?.trim().isNotEmpty == true)
            "- resume_profile_id: ${application.resumeProfileId!.trim()}",
          if (application.careerProfileId?.trim().isNotEmpty == true)
            "- career_profile_id: ${application.careerProfileId!.trim()}",
        ];
  return '''
请执行求职学习推进：

项目信息：
${lines.join("\n")}

动作意图：
$intent

执行要求：
1. 先读取并复用当前求职项目、匹配报告、已有学习计划和学习任务。
2. 只有确实需要沉淀时，才创建或更新 LearningPlan、LearningTask、WeaknessTracker、ProgressCheckin。
3. 不要重复创建已有学习计划或任务。
4. 不要写 memory。
5. 最终回复请说明本次更新了哪些学习记录，以及下一步建议。
''';
}

String _manualLearningTaskIntent({
  required String title,
  required String description,
  required String priority,
  required int estimatedMinutes,
}) {
  return '''
请创建一个用户主动添加的学习任务。

任务草稿：
- title: $title
${description.trim().isEmpty ? "" : "- description: ${description.trim()}\n"}- priority: $priority
${estimatedMinutes <= 0 ? "" : "- estimated_minutes: $estimatedMinutes\n"}
执行要求：
1. 调用 learning_task_create。
2. progress_notes 写明“来源：用户主动添加”。
3. 如果当前有求职项目上下文，将 application_id 加入 evidence_refs；如果没有项目，也不要拒绝创建。
4. 不要自动创建 Note、WeaknessTracker、CareerApplication 更新或 memory。
''';
}

String _learningRecommendationIntent({
  required int plans,
  required int tasks,
  required int weaknesses,
  required int reviews,
}) {
  return '''
请基于当前求职项目生成可加入学习任务的推荐建议。

当前工作台概况：
- learning_plans: $plans
- learning_tasks: $tasks
- weaknesses: $weaknesses
- reviews: $reviews

执行要求：
1. 先召回并复用当前求职项目、匹配报告、复盘、短板和已有学习任务。
2. 推荐 1 到 3 个最值得推进的学习任务，说明来源和优先级。
3. 如果已有高度相似任务，不要重复创建，直接指出可继续推进的任务。
4. 本次只做推荐和确认，不要静默批量创建任务；除非用户在本轮明确要求“直接创建”。
5. 不要写 Note、CareerApplication、WeaknessTracker 或 memory。
''';
}

String _learningCheckinIntent({
  required CareerWorkbenchLearningTaskView task,
  required String summary,
  required String blockers,
  required String nextAction,
  required int minutes,
  required String nextState,
}) {
  return '''
请记录学习任务今日进度。

任务信息：
- learning_task_id: ${task.learningTaskId}
- title: ${task.title}
- current_state: ${task.state}

进度内容：
${summary.trim().isEmpty ? "" : "- summary: ${summary.trim()}\n"}${blockers.trim().isEmpty ? "" : "- blockers: ${blockers.trim()}\n"}${nextAction.trim().isEmpty ? "" : "- next_action: ${nextAction.trim()}\n"}${minutes <= 0 ? "" : "- minutes_spent: $minutes\n"}${nextState.trim().isEmpty ? "- state_change: 不变\n" : "- state_change: $nextState\n"}
执行要求：
1. 先读取并定位该 LearningTask。
2. 调用 learning_checkin_create 记录本次进度。
3. 只有 state_change 不是“不变”时，才调用 learning_task_update_state。
4. 不要自动写 Note、CareerApplication、WeaknessTracker 或 memory。
''';
}

String _learningPlanMarkdown(CareerWorkbenchLearningPlanView plan) {
  return """
# ${plan.title}

- 类型：${plan.planType}
- 优先级：${_priorityLabel(plan.priority)}
${plan.targetRole.trim().isEmpty ? "" : "- 目标岗位：${plan.targetRole}\n"}${plan.targetCompany.trim().isEmpty ? "" : "- 目标公司：${plan.targetCompany}\n"}${plan.targetApplicationId == null ? "" : "- 关联项目：${plan.targetApplicationId}\n"}- 更新：${_formatTime(plan.updatedAt)}

${plan.description.trim().isEmpty ? "" : "## 说明\n\n${plan.description.trim()}\n"}
${plan.progressSummary.trim().isEmpty ? "" : "## 当前进展\n\n${plan.progressSummary.trim()}\n"}
${_bulletSection("目标", plan.goals)}
${_bulletSection("重点技能", plan.focusSkillTags)}
""";
}

String _learningTaskMarkdown(CareerWorkbenchLearningTaskView task) {
  return """
# ${task.title}

- 状态：${_taskStateLabel(task.state)}
- 优先级：${_priorityLabel(task.priority)}
- 类型：${task.taskType}
${task.learningPlanId == null ? "" : "- 所属计划：${task.learningPlanId}\n"}${task.estimatedMinutes <= 0 ? "" : "- 预计耗时：${task.estimatedMinutes} 分钟\n"}${task.dueDate == null ? "" : "- 截止日期：${_formatDate(task.dueDate!)}\n"}${task.completedAt == null ? "" : "- 完成时间：${_formatTime(task.completedAt!)}\n"}- 更新：${_formatTime(task.updatedAt)}

${task.description.trim().isEmpty ? "" : "## 任务说明\n\n${task.description.trim()}\n"}
${task.progressNotes.trim().isEmpty ? "" : "## 进展记录\n\n${task.progressNotes.trim()}\n"}
${_bulletSection("验收标准", task.successCriteria)}
${_bulletSection("技能标签", task.skillTags)}
""";
}

String _learningWeaknessMarkdown(CareerWorkbenchWeaknessView weakness) {
  return """
# ${weakness.title}

- 严重度：${_weaknessSeverityLabel(weakness.severity)}
- 状态：${_weaknessStateLabel(weakness.state)}
- 类型：${_weaknessTypeLabel(weakness.weaknessType)}
- 更新：${_formatTime(weakness.updatedAt)}

${weakness.description.trim().isEmpty ? "" : "## 问题说明\n\n${weakness.description.trim()}\n"}
${_bulletSection("技能标签", weakness.skillTags)}
${_bulletSection("关联任务", weakness.relatedTaskIds)}
""";
}

String _learningReviewMarkdown(CareerWorkbenchReviewView review) {
  return """
# ${review.title}

- 状态：${_reviewStateLabel(review.state)}
- 类型：${_reviewTypeLabel(review.reviewType)}
${review.reviewAt == null ? "" : "- 复盘时间：${_formatTime(review.reviewAt!)}\n"}${review.nextReviewAt == null ? "" : "- 下次复盘：${_formatTime(review.nextReviewAt!)}\n"}- 更新：${_formatTime(review.updatedAt)}

${review.summary.trim().isEmpty ? "" : "## 复盘摘要\n\n${review.summary.trim()}\n"}
""";
}

Future<void> _showLearningDetailSheet(
  BuildContext context, {
  required IconData icon,
  required Color color,
  required String title,
  required String subtitle,
  required String markdown,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    constraints: const BoxConstraints(maxWidth: double.infinity),
    builder: (sheetContext) {
      return SafeArea(
        top: false,
        child: FractionallySizedBox(
          heightFactor: 0.82,
          child: Align(
            alignment: Alignment.bottomCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 860),
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
                          Container(
                            width: 34,
                            height: 34,
                            decoration: BoxDecoration(
                              color: color.withValues(alpha: 0.11),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(
                                color: color.withValues(alpha: 0.18),
                              ),
                            ),
                            child: Icon(icon, size: 17, color: color),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  title,
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
                                  subtitle,
                                  style: AppTheme.ts(
                                    fontSize: 10.8,
                                    color: AppTheme.textTertiary,
                                  ),
                                ),
                              ],
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
                      child: SingleChildScrollView(
                        padding: const EdgeInsets.fromLTRB(24, 22, 24, 28),
                        child: AppMarkdownBody(
                          content: markdown.trim(),
                          style: AppTheme.ts(
                            fontSize: 13.8,
                            height: 1.68,
                            color: AppTheme.textPrimary,
                          ),
                        ),
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

int _tabCount(CareerWorkbenchProvider provider, CareerWorkbenchTab tab) {
  final counts = provider.workbench?.counts;
  return switch (tab) {
    CareerWorkbenchTab.overview => 0,
    CareerWorkbenchTab.projects => counts?.applications ?? 0,
    CareerWorkbenchTab.resumes => provider.hasLoadedAssetLibrary
        ? provider.resumeLibraryCount
        : counts?.resumeVersions ?? 0,
    CareerWorkbenchTab.jobs => provider.hasLoadedAssetLibrary
        ? provider.jobMatchLibraryCount
        : provider.applications
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
    "learning_plan" => Icons.route_outlined,
    "learning_sync" => Icons.update_rounded,
    "resume_diagnosis" => Icons.badge_outlined,
    "jd_analysis" => Icons.article_outlined,
    "job_fit_report" => Icons.fact_check_outlined,
    "save_note" => Icons.sticky_note_2_outlined,
    _ => Icons.arrow_forward_rounded,
  };
}

Color _actionStateColor(CareerWorkbenchActionState state) {
  return switch (state) {
    CareerWorkbenchActionState.running => const Color(0xFF2563EB),
    CareerWorkbenchActionState.completed => AppTheme.accent,
    CareerWorkbenchActionState.failed => const Color(0xFFDC2626),
  };
}

IconData _actionStateIcon(CareerWorkbenchActionState state) {
  return switch (state) {
    CareerWorkbenchActionState.running => Icons.autorenew_rounded,
    CareerWorkbenchActionState.completed => Icons.check_rounded,
    CareerWorkbenchActionState.failed => Icons.error_outline_rounded,
  };
}

List<_ProgressTimelineItem> _applicationProgressItems(
  CareerApplicationView application,
  List<CareerNoteSummaryView> notes,
  List<CareerTimelineItemView> timeline,
) {
  final items = <_ProgressTimelineItem>[
    _ProgressTimelineItem(
      title: _stageProgressTitle(application.stage),
      subtitle: _firstNonEmpty([
        application.summary,
        application.notes,
        application.displayTitle,
      ]),
      occurredAt: application.meta.updatedAt,
      icon: _stageProgressIcon(application.stage),
      color: _stageProgressColor(application.stage),
      tags: [
        _stageLabel(application.stage),
        _priorityLabel(application.priority),
      ],
    ),
  ];

  final reviewNotes = notes.where(_isReviewNote).toList()
    ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  for (final note in reviewNotes.take(4)) {
    items.add(
      _ProgressTimelineItem(
        title: note.title.trim().isEmpty ? "面试复盘" : note.title.trim(),
        subtitle: _firstNonEmpty([note.summary, note.tags.join(" · ")]),
        occurredAt: note.updatedAt,
        icon: Icons.rate_review_outlined,
        color: _reviewNoteColor(note),
        tags: note.tags,
      ),
    );
  }

  final eventItems = timeline.where(_isProgressTimelineEvent).toList()
    ..sort((a, b) => b.occurredAt.compareTo(a.occurredAt));
  for (final event in eventItems.take(5)) {
    items.add(
      _ProgressTimelineItem(
        title: event.title.trim().isEmpty
            ? _timelineEventLabel(event.type)
            : event.title.trim(),
        subtitle: event.subtitle,
        occurredAt: event.occurredAt,
        icon: _timelineEventIcon(event.type),
        color: _timelineEventColor(event.type),
      ),
    );
  }

  items.sort((a, b) => b.occurredAt.compareTo(a.occurredAt));
  final unique = <_ProgressTimelineItem>[];
  final seen = <String>{};
  for (final item in items) {
    final key = "${item.title}|${item.occurredAt.toIso8601String()}";
    if (seen.add(key)) {
      unique.add(item);
    }
  }
  return unique.take(6).toList(growable: false);
}

bool _isReviewNote(CareerNoteSummaryView note) {
  final text = [
    note.title,
    note.summary,
    ...note.tags,
  ].join(" ").toLowerCase();
  return text.contains("面试") ||
      text.contains("复盘") ||
      text.contains("笔试") ||
      text.contains("hr") ||
      text.contains("offer") ||
      text.contains("挂") ||
      text.contains("interview") ||
      text.contains("review");
}

bool _isProgressTimelineEvent(CareerTimelineItemView item) {
  return switch (item.type) {
    "note" || "review" || "learning_task" || "weakness" => true,
    _ => false,
  };
}

String _stageProgressTitle(String stage) {
  return switch (stage) {
    "applied" => "已投递",
    "interviewing" => "进入面试",
    "offer" => "拿到 Offer",
    "rejected" => "流程结束",
    "paused" => "项目暂停",
    "ready_to_apply" => "准备投递",
    _ => "项目更新",
  };
}

IconData _stageProgressIcon(String stage) {
  return switch (stage) {
    "applied" => Icons.send_outlined,
    "interviewing" => Icons.record_voice_over_outlined,
    "offer" => Icons.emoji_events_outlined,
    "rejected" => Icons.block_outlined,
    "paused" => Icons.pause_circle_outline_rounded,
    "ready_to_apply" => Icons.task_alt_rounded,
    _ => Icons.flag_outlined,
  };
}

Color _stageProgressColor(String stage) {
  return switch (stage) {
    "offer" => AppTheme.accent,
    "interviewing" => const Color(0xFF7C3AED),
    "applied" => const Color(0xFF2563EB),
    "rejected" => AppTheme.danger,
    "paused" => AppTheme.textTertiary,
    "ready_to_apply" => const Color(0xFF0EA5E9),
    _ => AppTheme.accent,
  };
}

Color _reviewNoteColor(CareerNoteSummaryView note) {
  if (note.tags.any((tag) => tag.toLowerCase().contains("面试"))) {
    return const Color(0xFF7C3AED);
  }
  return _noteTypeMeta(note.noteType).color;
}

String _timelineEventLabel(String type) {
  return switch (type) {
    "note" => "笔记更新",
    "review" => "复盘安排",
    "learning_task" => "学习任务",
    "weakness" => "短板更新",
    _ => _assetTypeLabel(type),
  };
}

IconData _timelineEventIcon(String type) {
  return switch (type) {
    "note" => Icons.sticky_note_2_outlined,
    "review" => Icons.event_repeat_outlined,
    "learning_task" => Icons.school_outlined,
    "weakness" => Icons.warning_amber_rounded,
    _ => Icons.timeline_rounded,
  };
}

Color _timelineEventColor(String type) {
  return switch (type) {
    "note" => const Color(0xFFB45309),
    "review" => const Color(0xFF7C3AED),
    "learning_task" => const Color(0xFF2563EB),
    "weakness" => AppTheme.danger,
    _ => AppTheme.accent,
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

String _learningTaskSourceLabel(CareerWorkbenchLearningTaskView task) {
  final notes = task.progressNotes;
  if (notes.contains("来源：用户主动添加")) return "用户添加";
  if (notes.contains("来源：面试复盘建议")) return "复盘建议";
  if (notes.contains("来源：岗位匹配短板")) return "匹配短板";
  if (notes.contains("来源：系统推荐")) return "推荐加入";
  if (task.evidenceRefs.any((ref) => ref.startsWith("fit_"))) {
    return "匹配短板";
  }
  if (task.evidenceRefs.any((ref) => ref.startsWith("note_"))) {
    return "复盘建议";
  }
  return "学习任务";
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
    noteType: note.noteType,
    sourceArtifactId: note.sourceArtifactId,
    relatedApplicationId: note.relatedApplicationId,
    tags: note.tags,
  );
}

List<_NoteMetaItem> _noteSummaryMetaItems(
  CareerNoteSummaryView note,
  List<String> sourceLabels,
) {
  final items = <_NoteMetaItem>[];
  final relatedApplicationId = note.relatedApplicationId?.trim() ?? "";
  if (relatedApplicationId.isNotEmpty) {
    items.add(
      _NoteMetaItem(
        icon: Icons.work_outline_rounded,
        label: "关联项目 ${_compactLabel(relatedApplicationId)}",
      ),
    );
  }
  final sourceArtifactId = note.sourceArtifactId?.trim() ?? "";
  if (sourceArtifactId.isNotEmpty) {
    items.add(
      _NoteMetaItem(
        icon: Icons.insert_drive_file_outlined,
        label: "来源文件 ${_compactLabel(sourceArtifactId)}",
      ),
    );
  }
  for (final label in sourceLabels) {
    final normalized = label.trim();
    if (normalized.isEmpty) {
      continue;
    }
    items.add(
      _NoteMetaItem(
        icon: Icons.link_rounded,
        label: normalized,
      ),
    );
    if (items.length >= 3) {
      break;
    }
  }
  return items;
}

List<String> _noteSourceLabelsFromNote(NoteView note) {
  final labels = <String>[];
  for (final sourceRef in note.sourceRefs) {
    final label = _sourceRefLabel(sourceRef);
    if (label.isNotEmpty && !labels.contains(label)) {
      labels.add(label);
    }
    if (labels.length >= 2) {
      break;
    }
  }
  return labels;
}

String _sourceRefLabel(NoteSourceRefView sourceRef) {
  final title = sourceRef.title.trim();
  if (title.isNotEmpty) {
    return "资料引用 ${_compactLabel(title)}";
  }
  final sourceId = sourceRef.sourceId?.trim() ?? "";
  if (sourceId.isNotEmpty) {
    return "${_sourceTypeLabel(sourceRef.sourceType)} ${_compactLabel(sourceId)}";
  }
  return "";
}

String _sourceTypeLabel(String sourceType) {
  return switch (sourceType.trim()) {
    "artifact" => "来源文件",
    "career_application" => "求职项目",
    "resume_profile" => "简历画像",
    "career_profile" => "职业画像",
    "jd_analysis" => "JD 分析",
    "job_fit_report" => "匹配报告",
    "resume_version" => "简历版本",
    _ => "来源",
  };
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
