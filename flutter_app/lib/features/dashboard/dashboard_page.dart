import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../../shared/widgets/product_components.dart';
import '../career_ui/career_ui_helpers.dart';
import '../career_workbench/career_workbench_provider.dart';

typedef DashboardPromptSender = Future<void> Function(
  String prompt, {
  CareerWorkbenchActionRequest? action,
});

class DashboardPage extends ConsumerStatefulWidget {
  final ValueChanged<String> onOpenProject;
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenLearning;
  final VoidCallback onOpenNotes;
  final DashboardPromptSender? onSendPrompt;

  const DashboardPage({
    super.key,
    required this.onOpenProject,
    required this.onOpenProjects,
    required this.onOpenResumes,
    required this.onOpenLearning,
    required this.onOpenNotes,
    this.onSendPrompt,
  });

  @override
  ConsumerState<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends ConsumerState<DashboardPage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(careerWorkbenchProvider).ensureLoaded());
  }

  @override
  Widget build(BuildContext context) {
    final provider = ref.watch(careerWorkbenchProvider);
    if (provider.isLoading && !provider.hasLoaded) {
      return const _DashboardLoading();
    }
    if (provider.error != null && !provider.hasLoaded) {
      return _DashboardError(
        error: provider.error!,
        onRetry: () => unawaited(provider.refresh()),
      );
    }

    final summary = provider.selectedApplicationSummary;
    final detail = provider.selectedApplicationDetail;
    final apps = provider.applications.take(3).toList();
    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= ProductBreakpoints.contentRail;
        final main = ListView(
          padding: EdgeInsets.zero,
          children: [
            _StatusHeroCard(
              summary: summary,
              detail: detail,
              onPrimary: summary == null
                  ? widget.onOpenProjects
                  : () => widget.onOpenProject(
                        summary.application.applicationId,
                      ),
            ),
            const SizedBox(height: 18),
            _MetricStrip(provider: provider),
            const SizedBox(height: 18),
            _RecentApplicationsSection(
              apps: apps,
              onOpenProject: widget.onOpenProject,
              onSendPrompt: widget.onSendPrompt,
            ),
            const SizedBox(height: 18),
            _TodayActionsSection(
              summary: summary,
              detail: detail,
              onOpenLearning: widget.onOpenLearning,
              onSendPrompt: widget.onSendPrompt,
            ),
          ],
        );
        final rail = _DashboardRightRail(
          provider: provider,
          onOpenResumes: widget.onOpenResumes,
          onOpenLearning: widget.onOpenLearning,
          onOpenNotes: widget.onOpenNotes,
          onSendPrompt: widget.onSendPrompt,
        );
        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              _StatusHeroCard(
                summary: summary,
                detail: detail,
                onPrimary: summary == null
                    ? widget.onOpenProjects
                    : () => widget.onOpenProject(
                          summary.application.applicationId,
                        ),
              ),
              const SizedBox(height: 14),
              _MetricStrip(provider: provider),
              const SizedBox(height: 14),
              rail,
              const SizedBox(height: 14),
              _RecentApplicationsSection(
                apps: apps,
                onOpenProject: widget.onOpenProject,
                onSendPrompt: widget.onSendPrompt,
              ),
              const SizedBox(height: 14),
              _TodayActionsSection(
                summary: summary,
                detail: detail,
                onOpenLearning: widget.onOpenLearning,
                onSendPrompt: widget.onSendPrompt,
              ),
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: main),
            const SizedBox(width: 20),
            SizedBox(width: 340, child: ListView(children: [rail])),
          ],
        );
      },
    );
  }
}

class _StatusHeroCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onPrimary;

  const _StatusHeroCard({
    required this.summary,
    required this.detail,
    required this.onPrimary,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final readiness = detail?.readiness ?? summary?.readiness;
    final score = readiness?.score;
    final title = app == null ? '当前求职状态' : '当前求职状态';
    final rawDescription = _firstNonEmpty([
      readiness?.summary,
      app?.summary,
      app == null
          ? '上传简历和目标岗位后，这里会汇总匹配判断、推进状态和下一步建议。'
          : '整体进展良好，建议继续推进高匹配岗位并补齐关键材料。',
    ]);

    return Container(
      padding: const EdgeInsets.fromLTRB(28, 26, 28, 24),
      decoration: ProductSurface.hero(),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 720;
          final description = careerDisplaySummary(
            rawDescription,
            maxChars: compact ? 94 : 132,
          );
          final content = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    style: AppTheme.ts(
                      fontSize: compact ? 22 : 26,
                      fontWeight: FontWeight.w900,
                      color: ProductColors.text,
                    ),
                  ),
                  const SizedBox(width: 9),
                  const Icon(
                    Icons.auto_awesome_rounded,
                    size: 20,
                    color: ProductColors.primary,
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                description,
                maxLines: compact ? 4 : 2,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 14,
                  height: 1.55,
                  fontWeight: FontWeight.w700,
                  color: ProductColors.textSecondary,
                ),
              ),
              const SizedBox(height: 15),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  ProductTag(
                    label:
                        '目标岗位：${_shortLabel(app?.position, fallback: '待补充')}',
                    tone: ProductTone.primary,
                  ),
                  ProductTag(
                    label:
                        '意向城市：${_shortLabel(app?.location, fallback: '待补充')}',
                    tone: ProductTone.info,
                  ),
                  ProductTag(
                    label: '当前阶段：${_stageLabel(app?.stage)}',
                    tone: ProductTone.neutral,
                  ),
                ],
              ),
              const SizedBox(height: 20),
              SizedBox(
                height: 46,
                child: ElevatedButton.icon(
                  onPressed: onPrimary,
                  icon: const Icon(Icons.arrow_forward_rounded, size: 18),
                  label: Text(
                    app == null ? '开始建立求职项目' : '继续推进岗位',
                    style: AppTheme.ts(
                      fontSize: 14,
                      fontWeight: FontWeight.w900,
                      color: Colors.white,
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: ProductColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(horizontal: 22),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
              ),
            ],
          );
          final ring = Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ProductScoreRing(
                  score: score, size: compact ? 82 : 108, label: '综合进度'),
              const SizedBox(height: 12),
              ProductTag(
                label: _recommendationLabel(readiness?.recommendation, score),
                tone: _scoreTone(score),
                icon: Icons.check_rounded,
              ),
            ],
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: content),
                    const SizedBox(width: 14),
                    Transform.scale(
                      scale: 0.84,
                      alignment: Alignment.topCenter,
                      child: ring,
                    ),
                  ],
                ),
              ],
            );
          }
          return Row(
            children: [
              Expanded(child: content),
              const SizedBox(width: 28),
              ring,
            ],
          );
        },
      ),
    );
  }
}

class _MetricStrip extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _MetricStrip({required this.provider});

  @override
  Widget build(BuildContext context) {
    final apps = provider.applications;
    final scores = apps
        .map((item) => item.readiness.score)
        .whereType<int>()
        .toList(growable: false);
    final avgScore = scores.isEmpty
        ? '-'
        : '${(scores.reduce((a, b) => a + b) / scores.length).round()}%';
    final selectedLearning = provider.selectedApplicationDetail?.learning;
    final openTasks = selectedLearning?.openTaskCount ??
        (provider.workbench?.counts.learningTasks ?? 0);
    final doneTasks = selectedLearning?.doneTaskCount ?? 0;
    final totalTasks = math.max(openTasks + doneTasks, 0);
    final progress =
        totalTasks == 0 ? '-' : '${((doneTasks / totalTasks) * 100).round()}%';
    final metrics = [
      ProductMetricCard(
        label: '已投递岗位',
        value: (provider.workbench?.counts.activeApplications ?? apps.length)
            .toString(),
        trend: apps.isEmpty ? '等待创建项目' : '持续推进中',
        icon: Icons.near_me_outlined,
        tone: ProductTone.info,
      ),
      ProductMetricCard(
        label: '匹配度均值',
        value: avgScore,
        trend: scores.isEmpty ? '暂无评分' : '基于 ${scores.length} 个项目',
        icon: Icons.track_changes_rounded,
        tone: ProductTone.primary,
      ),
      ProductMetricCard(
        label: '待办任务',
        value: openTasks.toString(),
        trend: selectedLearning?.highWeaknessCount == null
            ? null
            : '高优先级 ${selectedLearning!.highWeaknessCount} 个',
        icon: Icons.format_list_bulleted_rounded,
        tone: ProductTone.warning,
      ),
      ProductMetricCard(
        label: '本周学习进度',
        value: progress,
        trend: totalTasks == 0 ? '暂无任务' : '$doneTasks/$totalTasks 已完成',
        icon: Icons.menu_book_outlined,
        tone: ProductTone.purple,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 960
            ? 4
            : constraints.maxWidth >= 620
                ? 2
                : 1;
        final width = (constraints.maxWidth - (columns - 1) * 12) / columns;
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final metric in metrics) SizedBox(width: width, child: metric),
          ],
        );
      },
    );
  }
}

class _RecentApplicationsSection extends StatelessWidget {
  final List<CareerApplicationSummaryView> apps;
  final ValueChanged<String> onOpenProject;
  final DashboardPromptSender? onSendPrompt;

  const _RecentApplicationsSection({
    required this.apps,
    required this.onOpenProject,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    return ProductSection(
      title: '最近推进中的岗位',
      subtitle: apps.isEmpty ? '暂无求职项目' : '按更新时间和推进状态排序',
      icon: Icons.business_center_outlined,
      trailing: TextButton(
        onPressed: apps.isEmpty ? null : () {},
        child: const Text('查看全部'),
      ),
      child: apps.isEmpty
          ? const _EmptyDashboardText(
              text: '还没有求职项目。可以先上传简历和 JD，让 Agent 生成第一个项目。',
            )
          : LayoutBuilder(
              builder: (context, constraints) {
                final columns =
                    (constraints.maxWidth / 290).floor().clamp(1, 3);
                final width =
                    (constraints.maxWidth - (columns - 1) * 12) / columns;
                return Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    for (final app in apps)
                      SizedBox(
                        width: width,
                        child: _RecentApplicationCard(
                          summary: app,
                          onOpen: () =>
                              onOpenProject(app.application.applicationId),
                          onSendPrompt: onSendPrompt,
                        ),
                      ),
                  ],
                );
              },
            ),
    );
  }
}

class _RecentApplicationCard extends StatelessWidget {
  final CareerApplicationSummaryView summary;
  final VoidCallback onOpen;
  final DashboardPromptSender? onSendPrompt;

  const _RecentApplicationCard({
    required this.summary,
    required this.onOpen,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final app = summary.application;
    final action = _firstNonEmpty([
      summary.readiness.nextActions.firstOrNull,
      app.nextActions.firstOrNull,
      '查看详情',
    ]);
    final risk = _firstNonEmpty([
      summary.readiness.risks.firstOrNull,
      app.risks.firstOrNull,
      summary.readiness.strengths.firstOrNull,
      app.summary,
    ]);
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _CompanyAvatar(label: app.company),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _shortLabel(app.position, fallback: app.displayTitle),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 14.2,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _firstNonEmpty([app.company, app.location, '目标岗位']),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.5,
                        color: ProductColors.textMuted,
                      ),
                    ),
                  ],
                ),
              ),
              ProductScoreRing(score: summary.readiness.score, size: 58),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              ProductTag(
                  label: _stageLabel(app.stage), tone: ProductTone.primary),
              ProductTag(
                label: _recommendationLabel(
                  summary.readiness.recommendation,
                  summary.readiness.score,
                ),
                tone: _scoreTone(summary.readiness.score),
              ),
            ],
          ),
          const SizedBox(height: 11),
          Text(
            risk,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 11.7,
              height: 1.42,
              color: ProductColors.textSecondary,
            ),
          ),
          const SizedBox(height: 13),
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 36,
                  child: ElevatedButton(
                    onPressed: () => _sendApplicationAction(
                      summary,
                      action,
                      onSendPrompt,
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: ProductColors.primary,
                      foregroundColor: Colors.white,
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    child: Text(
                      action,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w900,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: SizedBox(
                  height: 36,
                  child: OutlinedButton(
                    onPressed: onOpen,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: ProductColors.textSecondary,
                      side: const BorderSide(color: ProductColors.border),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    child: const Text('查看详情'),
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

class _TodayActionsSection extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenLearning;
  final DashboardPromptSender? onSendPrompt;

  const _TodayActionsSection({
    required this.summary,
    required this.detail,
    required this.onOpenLearning,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final actions = _dashboardActions(summary, detail);
    return ProductSection(
      title: '今日推荐动作',
      subtitle: actions.isEmpty ? '暂无明确待办' : '优先处理最能提升匹配度的动作',
      icon: Icons.auto_awesome_rounded,
      trailing: TextButton(
        onPressed: onOpenLearning,
        child: const Text('查看全部'),
      ),
      child: actions.isEmpty
          ? const _EmptyDashboardText(text: '当前没有推荐动作。继续补充简历或 JD 后会自动生成。')
          : Column(
              children: [
                for (final action in actions) ...[
                  ProductActionTile(
                    title: action.title,
                    subtitle: action.subtitle,
                    icon: action.icon,
                    tone: action.tone,
                    badge: action.badge,
                    actionLabel: action.actionLabel,
                    onTap: () => _sendDashboardAction(action, onSendPrompt),
                  ),
                  if (action != actions.last) const SizedBox(height: 9),
                ],
              ],
            ),
    );
  }
}

class _DashboardRightRail extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenLearning;
  final VoidCallback onOpenNotes;
  final DashboardPromptSender? onSendPrompt;

  const _DashboardRightRail({
    required this.provider,
    required this.onOpenResumes,
    required this.onOpenLearning,
    required this.onOpenNotes,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final summary = provider.selectedApplicationSummary;
    final detail = provider.selectedApplicationDetail;
    return Column(
      children: [
        _CurrentJudgmentCard(summary: summary, detail: detail),
        const SizedBox(height: 14),
        _NextStepCard(
          summary: summary,
          detail: detail,
          onOpenLearning: onOpenLearning,
          onSendPrompt: onSendPrompt,
        ),
        const SizedBox(height: 14),
        _AssetSummaryCard(
          provider: provider,
          onOpenResumes: onOpenResumes,
          onOpenNotes: onOpenNotes,
        ),
      ],
    );
  }
}

class _CurrentJudgmentCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;

  const _CurrentJudgmentCard({
    required this.summary,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final readiness = detail?.readiness ?? summary?.readiness;
    final strengths = readiness?.strengths.take(2).toList() ?? const <String>[];
    final risks = readiness?.risks.take(2).toList() ?? const <String>[];
    return ProductSection(
      title: '当前判断',
      subtitle: '基于最近求职项目',
      icon: Icons.fact_check_outlined,
      tone: _scoreTone(readiness?.score),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (readiness?.summary.trim().isNotEmpty == true)
            Text(
              careerDisplaySummary(readiness!.summary, maxChars: 130),
              maxLines: 4,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 12.4,
                height: 1.52,
                fontWeight: FontWeight.w700,
                color: ProductColors.textSecondary,
              ),
            )
          else
            const _EmptyDashboardText(text: '暂无当前判断。'),
          if (strengths.isNotEmpty) ...[
            const SizedBox(height: 12),
            _MiniListBlock(
              title: '优势领域',
              items: strengths,
              tone: ProductTone.primary,
            ),
          ],
          if (risks.isNotEmpty) ...[
            const SizedBox(height: 10),
            _MiniListBlock(
              title: '待提升领域',
              items: risks,
              tone: ProductTone.warning,
            ),
          ],
        ],
      ),
    );
  }
}

class _NextStepCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenLearning;
  final DashboardPromptSender? onSendPrompt;

  const _NextStepCard({
    required this.summary,
    required this.detail,
    required this.onOpenLearning,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final actions = _dashboardActions(summary, detail).take(3).toList();
    return ProductSection(
      title: '推荐下一步',
      subtitle: '按收益和风险排序',
      icon: Icons.auto_fix_high_outlined,
      trailing: TextButton(
        onPressed: onOpenLearning,
        child: const Text('全部'),
      ),
      child: actions.isEmpty
          ? const _EmptyDashboardText(text: '暂无推荐下一步。')
          : Column(
              children: [
                for (var i = 0; i < actions.length; i++) ...[
                  ProductActionTile(
                    title: actions[i].title,
                    subtitle: actions[i].subtitle,
                    icon: actions[i].icon,
                    tone: actions[i].tone,
                    badge: '${i + 1}',
                    actionLabel: '执行',
                    onTap: () => _sendDashboardAction(actions[i], onSendPrompt),
                  ),
                  if (i != actions.length - 1) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _AssetSummaryCard extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenNotes;

  const _AssetSummaryCard({
    required this.provider,
    required this.onOpenResumes,
    required this.onOpenNotes,
  });

  @override
  Widget build(BuildContext context) {
    final counts = provider.workbench?.counts;
    final detail = provider.selectedApplicationDetail;
    final assets = detail?.linkedAssets.take(3).toList() ??
        const <CareerLinkedAssetView>[];
    return ProductSection(
      title: '关联资产',
      subtitle: '简历、笔记和报告集中管理',
      icon: Icons.folder_copy_outlined,
      tone: ProductTone.info,
      child: Column(
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final itemWidth = (constraints.maxWidth - 10) / 2;
              return Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  SizedBox(
                    width: itemWidth,
                    child: _AssetCountTile(
                      label: '简历版本',
                      value: counts?.resumeVersions ??
                          provider.resumeVersions.length,
                      icon: Icons.description_outlined,
                      onTap: onOpenResumes,
                    ),
                  ),
                  SizedBox(
                    width: itemWidth,
                    child: _AssetCountTile(
                      label: '笔记文档',
                      value: counts?.notes ?? provider.notes.length,
                      icon: Icons.sticky_note_2_outlined,
                      onTap: onOpenNotes,
                    ),
                  ),
                  SizedBox(
                    width: itemWidth,
                    child: _AssetCountTile(
                      label: '学习任务',
                      value: counts?.learningTasks ?? 0,
                      icon: Icons.school_outlined,
                      onTap: null,
                    ),
                  ),
                  SizedBox(
                    width: itemWidth,
                    child: _AssetCountTile(
                      label: '项目资料',
                      value: detail?.linkedAssets.length ?? 0,
                      icon: Icons.inventory_2_outlined,
                      onTap: null,
                    ),
                  ),
                ],
              );
            },
          ),
          if (assets.isNotEmpty) ...[
            const SizedBox(height: 14),
            for (final asset in assets) ...[
              _AssetRow(asset: asset),
              if (asset != assets.last) const SizedBox(height: 8),
            ],
          ],
        ],
      ),
    );
  }
}

class _MiniListBlock extends StatelessWidget {
  final String title;
  final List<String> items;
  final ProductTone tone;

  const _MiniListBlock({
    required this.title,
    required this.items,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: ProductSurface.softCard(tone: tone, radius: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: AppTheme.ts(
              fontSize: 11.5,
              fontWeight: FontWeight.w900,
              color: productToneStyle(tone).color,
            ),
          ),
          const SizedBox(height: 7),
          for (final item in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    Icons.check_circle_outline_rounded,
                    size: 14,
                    color: productToneStyle(tone).color,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      item,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11,
                        height: 1.36,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _AssetCountTile extends StatelessWidget {
  final String label;
  final int value;
  final IconData icon;
  final VoidCallback? onTap;

  const _AssetCountTile({
    required this.label,
    required this.value,
    required this.icon,
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
          padding: const EdgeInsets.fromLTRB(9, 9, 9, 9),
          decoration: BoxDecoration(
            color: ProductColors.infoSoft.withValues(alpha: 0.6),
            borderRadius: BorderRadius.circular(12),
            border:
                Border.all(color: ProductColors.info.withValues(alpha: 0.1)),
          ),
          child: Column(
            children: [
              Icon(icon, size: 18, color: ProductColors.info),
              const SizedBox(height: 7),
              Text(
                value.toString(),
                style: AppTheme.ts(
                  fontSize: 17,
                  height: 1,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 10.5,
                  color: ProductColors.textMuted,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AssetRow extends StatelessWidget {
  final CareerLinkedAssetView asset;

  const _AssetRow({required this.asset});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const ProductIconTile(
          icon: Icons.insert_drive_file_outlined,
          tone: ProductTone.info,
          size: 32,
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _firstNonEmpty([asset.title, asset.subtitle, asset.id]),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                asset.updatedAt == null
                    ? asset.type
                    : _formatTime(asset.updatedAt!),
                style: AppTheme.ts(
                  fontSize: 10.4,
                  color: ProductColors.textMuted,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _CompanyAvatar extends StatelessWidget {
  final String label;

  const _CompanyAvatar({required this.label});

  @override
  Widget build(BuildContext context) {
    final text = label.trim().isEmpty ? '岗' : label.trim().characters.first;
    return Container(
      width: 48,
      height: 48,
      decoration: BoxDecoration(
        color: ProductColors.primarySoft,
        borderRadius: BorderRadius.circular(16),
        border:
            Border.all(color: ProductColors.primary.withValues(alpha: 0.13)),
      ),
      child: Center(
        child: Text(
          text,
          style: AppTheme.ts(
            fontSize: 18,
            fontWeight: FontWeight.w900,
            color: ProductColors.primary,
          ),
        ),
      ),
    );
  }
}

class _DashboardLoading extends StatelessWidget {
  const _DashboardLoading();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: CircularProgressIndicator(color: ProductColors.primary),
    );
  }
}

class _DashboardError extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const _DashboardError({
    required this.error,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ProductCard(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const ProductIconTile(
              icon: Icons.error_outline_rounded,
              tone: ProductTone.danger,
            ),
            const SizedBox(height: 12),
            Text(
              '工作台加载失败',
              style: AppTheme.ts(
                fontSize: 16,
                fontWeight: FontWeight.w900,
                color: ProductColors.text,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              error,
              textAlign: TextAlign.center,
              style: AppTheme.ts(
                fontSize: 12,
                color: ProductColors.textSecondary,
              ),
            ),
            const SizedBox(height: 14),
            ElevatedButton(onPressed: onRetry, child: const Text('重试')),
          ],
        ),
      ),
    );
  }
}

class _EmptyDashboardText extends StatelessWidget {
  final String text;

  const _EmptyDashboardText({required this.text});

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: AppTheme.ts(
        fontSize: 12.4,
        height: 1.5,
        color: ProductColors.textMuted,
      ),
    );
  }
}

class _DashboardAction {
  final String title;
  final String subtitle;
  final IconData icon;
  final ProductTone tone;
  final String badge;
  final String actionLabel;
  final CareerApplicationView? application;
  final String actionType;

  const _DashboardAction({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.tone,
    required this.badge,
    required this.actionLabel,
    required this.application,
    required this.actionType,
  });
}

List<_DashboardAction> _dashboardActions(
  CareerApplicationSummaryView? summary,
  CareerApplicationWorkbenchView? detail,
) {
  final app = detail?.application ?? summary?.application;
  final suggested =
      detail?.suggestedActions ?? const <CareerSuggestedActionView>[];
  final actions = <_DashboardAction>[];
  for (final action in suggested.take(3)) {
    actions.add(
      _DashboardAction(
        title: _shortLabel(action.label, fallback: '推进求职动作'),
        subtitle:
            _firstNonEmpty([action.reason, action.promptIntent, app?.summary]),
        icon: _actionIcon(action.actionType),
        tone: _priorityTone(action.priority),
        badge: _priorityLabel(action.priority),
        actionLabel: '去执行',
        application: app,
        actionType: action.actionType,
      ),
    );
  }
  final fallbackActions = [
    _DashboardAction(
      title: '生成定制简历',
      subtitle: '基于当前岗位匹配结论优化简历表述。',
      icon: Icons.description_outlined,
      tone: ProductTone.primary,
      badge: '提升匹配',
      actionLabel: '去生成',
      application: app,
      actionType: 'custom_resume',
    ),
    _DashboardAction(
      title: '准备面试题',
      subtitle: '围绕风险点生成面试问题和参考答案。',
      icon: Icons.chat_bubble_outline_rounded,
      tone: ProductTone.purple,
      badge: '面试准备',
      actionLabel: '去准备',
      application: app,
      actionType: 'interview_prep',
    ),
    _DashboardAction(
      title: '创建学习任务',
      subtitle: '把高优先级短板转成今天可完成的任务。',
      icon: Icons.school_outlined,
      tone: ProductTone.warning,
      badge: '补短板',
      actionLabel: '去创建',
      application: app,
      actionType: 'learning_task',
    ),
  ];
  for (final action in fallbackActions) {
    if (actions.length >= 3) break;
    if (!actions.any((item) => item.actionType == action.actionType)) {
      actions.add(action);
    }
  }
  return actions;
}

void _sendDashboardAction(
  _DashboardAction action,
  DashboardPromptSender? sender,
) {
  final app = action.application;
  if (sender == null || app == null) return;
  unawaited(
    sender(
      '请基于求职项目 ${app.applicationId} 执行：${action.title}。${action.subtitle}',
      action: CareerWorkbenchActionRequest(
        applicationId: app.applicationId,
        actionType: action.actionType,
        label: action.title,
        origin: 'dashboard',
      ),
    ),
  );
}

void _sendApplicationAction(
  CareerApplicationSummaryView summary,
  String label,
  DashboardPromptSender? sender,
) {
  if (sender == null) return;
  final app = summary.application;
  unawaited(
    sender(
      '请基于求职项目 ${app.applicationId} 执行：$label。',
      action: CareerWorkbenchActionRequest(
        applicationId: app.applicationId,
        actionType: 'dashboard_action',
        label: label,
        origin: 'dashboard',
      ),
    ),
  );
}

String _firstNonEmpty(List<String?> values) {
  for (final value in values) {
    final text = value?.trim() ?? '';
    if (text.isNotEmpty) return text;
  }
  return '';
}

String _shortLabel(String? value, {String fallback = '待补充'}) {
  final text = value?.trim() ?? '';
  return text.isEmpty ? fallback : text;
}

String _stageLabel(String? stage) {
  return switch ((stage ?? '').trim()) {
    'draft' => '草稿',
    'ready_to_apply' => '准备投递',
    'applied' => '已投递',
    'screening' => '简历筛选',
    'interviewing' => '多轮面试中',
    'offer' => 'Offer',
    'rejected' => '已结束',
    'paused' => '暂停',
    _ => '待推进',
  };
}

String _recommendationLabel(String? recommendation, int? score) {
  final value = (recommendation ?? '').trim();
  if (value == 'recommended' || value == 'strong') return '良好';
  if (value == 'cautious') return '谨慎推进';
  if (value == 'not_recommended') return '高风险';
  if (score == null) return '待评估';
  if (score >= 80) return '良好';
  if (score >= 60) return '谨慎推进';
  return '高风险';
}

ProductTone _scoreTone(int? score) {
  if (score == null) return ProductTone.neutral;
  if (score >= 80) return ProductTone.primary;
  if (score >= 60) return ProductTone.warning;
  return ProductTone.danger;
}

ProductTone _priorityTone(String value) {
  return switch (value.trim()) {
    'high' => ProductTone.warning,
    'urgent' => ProductTone.danger,
    'low' => ProductTone.info,
    _ => ProductTone.primary,
  };
}

String _priorityLabel(String value) {
  return switch (value.trim()) {
    'high' => '高优先',
    'urgent' => '紧急',
    'low' => '低风险',
    _ => '推荐',
  };
}

IconData _actionIcon(String value) {
  if (value.contains('resume')) return Icons.description_outlined;
  if (value.contains('interview')) return Icons.chat_bubble_outline_rounded;
  if (value.contains('learning')) return Icons.school_outlined;
  if (value.contains('note')) return Icons.sticky_note_2_outlined;
  return Icons.auto_awesome_rounded;
}

String _formatTime(DateTime time) {
  return DateFormat('MM-dd HH:mm').format(time);
}
