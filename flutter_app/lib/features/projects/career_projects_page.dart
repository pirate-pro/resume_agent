import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../../shared/widgets/product_components.dart';
import '../career_ui/career_ui_helpers.dart';
import '../career_workbench/career_workbench_provider.dart';

class CareerProjectsPage extends ConsumerStatefulWidget {
  final ValueChanged<String> onOpenProject;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenJDMatch;
  final VoidCallback onOpenLearning;
  final VoidCallback onOpenNotes;
  final CareerPromptSender? onSendPrompt;

  const CareerProjectsPage({
    super.key,
    required this.onOpenProject,
    required this.onOpenResumes,
    required this.onOpenJDMatch,
    required this.onOpenLearning,
    required this.onOpenNotes,
    this.onSendPrompt,
  });

  @override
  ConsumerState<CareerProjectsPage> createState() => _CareerProjectsPageState();
}

class _CareerProjectsPageState extends ConsumerState<CareerProjectsPage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(careerWorkbenchProvider).ensureLoaded());
  }

  void _sendAction(
    CareerApplicationView? app, {
    required String label,
    required String actionType,
    String? detail,
  }) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: label,
      actionType: actionType,
      origin: 'projects',
      detail: detail,
    );
  }

  Future<void> _showCustomResumeDialog(
    CareerApplicationView app,
    CareerApplicationWorkbenchView? detail,
  ) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return _CustomResumeDialog(
          application: app,
          detail: detail,
          onStart: () {
            Navigator.of(dialogContext).pop();
            _sendAction(
              app,
              label: '生成岗位定制简历',
              actionType: 'custom_resume',
              detail: '基于基础简历画像、JD 分析和匹配报告生成岗位定制简历草案。',
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = ref.watch(careerWorkbenchProvider);
    if (provider.isLoading && !provider.hasLoaded) {
      return const Center(
        child: CircularProgressIndicator(color: ProductColors.primary),
      );
    }
    if (provider.error != null && !provider.hasLoaded) {
      return _ProjectsError(
        error: provider.error!,
        onRetry: () => unawaited(provider.refresh()),
      );
    }

    final summary = provider.selectedApplicationSummary;
    final detail = provider.selectedApplicationDetail;
    final app = detail?.application ?? summary?.application;

    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= ProductBreakpoints.contentRail;
        final main = ListView(
          padding: EdgeInsets.zero,
          children: [
            _ProjectHeader(
              provider: provider,
              selectedApplication: app,
              onRefresh: () => unawaited(provider.refresh()),
            ),
            const SizedBox(height: 14),
            _ProjectHeroCard(
              summary: summary,
              detail: detail,
              onOpenJDMatch: widget.onOpenJDMatch,
              onOpenResumes: widget.onOpenResumes,
              onPrimaryAction:
                  app == null ? null : () => _handlePrimaryAction(app, detail),
            ),
            if (provider.activeAction != null) ...[
              const SizedBox(height: 12),
              _ProjectActionBanner(run: provider.activeAction!),
            ],
            const SizedBox(height: 14),
            _ProjectFactStrip(summary: summary, detail: detail),
            const SizedBox(height: 14),
            _ProjectWorkflowCard(summary: summary, detail: detail),
            const SizedBox(height: 14),
            _RiskActionGrid(
              summary: summary,
              detail: detail,
              onOpenLearning: widget.onOpenLearning,
              onOpenResumes: widget.onOpenResumes,
              onOpenJDMatch: widget.onOpenJDMatch,
              onCustomResume: app == null
                  ? null
                  : () => _showCustomResumeDialog(app, detail),
              onSendAction: _sendAction,
            ),
            const SizedBox(height: 14),
            _ProjectTimelineCard(detail: detail),
          ],
        );

        final rail = _ProjectRightRail(
          provider: provider,
          summary: summary,
          detail: detail,
          onOpenResumes: widget.onOpenResumes,
          onOpenJDMatch: widget.onOpenJDMatch,
          onOpenNotes: widget.onOpenNotes,
        );

        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              _ProjectHeader(
                provider: provider,
                selectedApplication: app,
                onRefresh: () => unawaited(provider.refresh()),
              ),
              const SizedBox(height: 14),
              _ProjectHeroCard(
                summary: summary,
                detail: detail,
                onOpenJDMatch: widget.onOpenJDMatch,
                onOpenResumes: widget.onOpenResumes,
                onPrimaryAction: app == null
                    ? null
                    : () => _handlePrimaryAction(app, detail),
              ),
              if (provider.activeAction != null) ...[
                const SizedBox(height: 12),
                _ProjectActionBanner(run: provider.activeAction!),
              ],
              const SizedBox(height: 14),
              rail,
              const SizedBox(height: 14),
              _ProjectFactStrip(summary: summary, detail: detail),
              const SizedBox(height: 14),
              _ProjectWorkflowCard(summary: summary, detail: detail),
              const SizedBox(height: 14),
              _RiskActionGrid(
                summary: summary,
                detail: detail,
                onOpenLearning: widget.onOpenLearning,
                onOpenResumes: widget.onOpenResumes,
                onOpenJDMatch: widget.onOpenJDMatch,
                onCustomResume: app == null
                    ? null
                    : () => _showCustomResumeDialog(app, detail),
                onSendAction: _sendAction,
              ),
              const SizedBox(height: 14),
              _ProjectTimelineCard(detail: detail),
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

  void _handlePrimaryAction(
    CareerApplicationView app,
    CareerApplicationWorkbenchView? detail,
  ) {
    final action = _primaryProjectAction(app, detail);
    if (action.actionType == 'custom_resume') {
      unawaited(_showCustomResumeDialog(app, detail));
      return;
    }
    if (action.actionType == 'jd_match_analysis') {
      widget.onOpenJDMatch();
      return;
    }
    if (action.actionType == 'resume_view') {
      widget.onOpenResumes();
      return;
    }
    _sendAction(
      app,
      label: action.label,
      actionType: action.actionType,
      detail: action.reason,
    );
  }
}

class _ProjectHeader extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? selectedApplication;
  final VoidCallback onRefresh;

  const _ProjectHeader({
    required this.provider,
    required this.selectedApplication,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    final applications = provider.applications;
    return Padding(
      padding: const EdgeInsets.fromLTRB(2, 0, 2, 0),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < ProductBreakpoints.compact;
          final title = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '求职项目',
                style: AppTheme.ts(
                  fontSize: 23,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '在这里推进一个目标岗位，跟踪进度，提升命中率',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 12.5,
                  color: ProductColors.textSecondary,
                ),
              ),
            ],
          );
          final controls = Wrap(
            spacing: 8,
            runSpacing: 8,
            alignment: WrapAlignment.end,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (provider.isRefreshing)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: ProductColors.primary,
                  ),
                ),
              _ProjectFilterMenu(provider: provider),
              if (applications.length > 1)
                _ProjectSelector(
                  provider: provider,
                  applications: applications,
                  selectedApplication: selectedApplication,
                ),
              SizedBox(
                height: 38,
                child: OutlinedButton.icon(
                  onPressed: onRefresh,
                  icon: const Icon(Icons.refresh_rounded, size: 16),
                  label: const Text('刷新'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: ProductColors.primary,
                    side: const BorderSide(color: ProductColors.border),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
              ),
            ],
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                title,
                const SizedBox(height: 12),
                controls,
              ],
            );
          }
          return Row(
            children: [
              Expanded(child: title),
              const SizedBox(width: 16),
              controls,
            ],
          );
        },
      ),
    );
  }
}

class _ProjectFilterMenu extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _ProjectFilterMenu({required this.provider});

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<CareerProjectFilter>(
      tooltip: '筛选项目',
      initialValue: provider.projectFilter,
      onSelected: provider.setProjectFilter,
      itemBuilder: (context) {
        return [
          for (final filter in CareerProjectFilter.values)
            PopupMenuItem(
              value: filter,
              child: Text(_projectFilterLabel(filter)),
            ),
        ];
      },
      child: Container(
        height: 38,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: ProductColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: ProductColors.border),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.filter_list_rounded,
              size: 16,
              color: ProductColors.textSecondary,
            ),
            const SizedBox(width: 7),
            Text(
              _projectFilterLabel(provider.projectFilter),
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: ProductColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProjectSelector extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final List<CareerApplicationSummaryView> applications;
  final CareerApplicationView? selectedApplication;

  const _ProjectSelector({
    required this.provider,
    required this.applications,
    required this.selectedApplication,
  });

  @override
  Widget build(BuildContext context) {
    final selectedId = selectedApplication?.applicationId;
    return DropdownButtonHideUnderline(
      child: Container(
        height: 38,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: ProductColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: ProductColors.border),
        ),
        child: DropdownButton<String>(
          value: applications.any(
            (item) => item.application.applicationId == selectedId,
          )
              ? selectedId
              : applications.first.application.applicationId,
          icon: const Icon(Icons.keyboard_arrow_down_rounded, size: 17),
          style: AppTheme.ts(
            fontSize: 12,
            fontWeight: FontWeight.w800,
            color: ProductColors.text,
          ),
          items: [
            for (final item in applications)
              DropdownMenuItem(
                value: item.application.applicationId,
                child: Text(
                  item.application.displayTitle,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
          onChanged: (value) {
            if (value == null) return;
            unawaited(provider.selectApplication(value));
          },
        ),
      ),
    );
  }
}

class _ProjectHeroCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenJDMatch;
  final VoidCallback onOpenResumes;
  final VoidCallback? onPrimaryAction;

  const _ProjectHeroCard({
    required this.summary,
    required this.detail,
    required this.onOpenJDMatch,
    required this.onOpenResumes,
    required this.onPrimaryAction,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final readiness = detail?.readiness ?? summary?.readiness;
    if (app == null) {
      return ProductCard(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
        child: Row(
          children: [
            const ProductIconTile(
              icon: Icons.business_center_outlined,
              tone: ProductTone.primary,
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Text(
                '还没有求职项目。可以先上传简历和 JD，让 Agent 生成第一个岗位推进工作台。',
                style: AppTheme.ts(
                  fontSize: 13,
                  height: 1.5,
                  color: ProductColors.textSecondary,
                ),
              ),
            ),
          ],
        ),
      );
    }

    final primaryAction = _primaryProjectAction(app, detail);
    return Container(
      padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
      decoration: ProductSurface.hero().copyWith(
        borderRadius: BorderRadius.circular(22),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final titleBlock = Row(
            children: [
              _CompanyAvatar(label: app.company),
              const SizedBox(width: 18),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      careerShortLabel(app.company, fallback: '目标公司'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 14,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 7),
                    Text(
                      careerShortLabel(app.position, fallback: '目标岗位'),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: compact ? 22 : 26,
                        height: 1.18,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 9,
                      runSpacing: 8,
                      children: [
                        ProductTag(
                          label: careerShortLabel(app.location),
                          icon: Icons.location_on_outlined,
                          tone: ProductTone.neutral,
                        ),
                        ProductTag(
                          label: careerStageLabel(app.stage),
                          tone: careerStageTone(app.stage),
                        ),
                        ProductTag(
                          label: '优先级 ${careerPriorityLabel(app.priority)}',
                          tone: careerPriorityTone(app.priority),
                        ),
                        ProductTag(
                          label:
                              '更新于 ${careerFormatDateTime(app.meta.updatedAt)}',
                          tone: ProductTone.info,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          );

          final scoreBlock = Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ProductScoreRing(
                score: readiness?.score,
                size: 118,
                label: '匹配度',
              ),
              const SizedBox(height: 10),
              ProductTag(
                label: careerRecommendationLabel(
                  readiness?.recommendation,
                  readiness?.score,
                ),
                tone: careerScoreTone(readiness?.score),
              ),
            ],
          );

          final judgement = Container(
            padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
            decoration: BoxDecoration(
              color: ProductColors.surface.withValues(alpha: 0.72),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: ProductColors.primary.withValues(alpha: 0.12),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '整体准备度：${readiness?.score?.toString() ?? '-'} / 100（${careerStageLabel(app.stage)}阶段）',
                  style: AppTheme.ts(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  careerDisplaySummary(
                    careerFirstNonEmpty(
                      [readiness?.summary, app.summary],
                      fallback: '完成 JD 匹配后会在这里展示项目判断、风险和推进建议。',
                    ),
                    maxChars: compact ? 128 : 176,
                  ),
                  maxLines: compact ? 4 : 3,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.4,
                    height: 1.5,
                    color: ProductColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 14),
                Wrap(
                  spacing: 10,
                  runSpacing: 8,
                  children: [
                    _PrimaryProjectButton(
                      label: primaryAction.label,
                      icon: primaryAction.icon,
                      onPressed: onPrimaryAction,
                    ),
                    _SecondaryProjectButton(
                      label: detail?.jobFitReport == null
                          ? '分析 JD 匹配'
                          : '查看完整匹配判断',
                      icon: Icons.analytics_outlined,
                      onPressed: onOpenJDMatch,
                    ),
                  ],
                ),
              ],
            ),
          );

          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                titleBlock,
                const SizedBox(height: 20),
                Center(child: scoreBlock),
                const SizedBox(height: 18),
                judgement,
              ],
            );
          }

          return Row(
            children: [
              Expanded(flex: 5, child: titleBlock),
              const SizedBox(width: 24),
              scoreBlock,
              const SizedBox(width: 26),
              Expanded(flex: 5, child: judgement),
            ],
          );
        },
      ),
    );
  }
}

class _ProjectActionBanner extends StatelessWidget {
  final CareerWorkbenchActionRun run;

  const _ProjectActionBanner({required this.run});

  @override
  Widget build(BuildContext context) {
    final tone = switch (run.state) {
      CareerWorkbenchActionState.running => ProductTone.info,
      CareerWorkbenchActionState.completed => ProductTone.primary,
      CareerWorkbenchActionState.failed => ProductTone.danger,
    };
    final title = switch (run.state) {
      CareerWorkbenchActionState.running => '正在${run.request.label}',
      CareerWorkbenchActionState.completed => '${run.request.label}已完成',
      CareerWorkbenchActionState.failed => '${run.request.label}失败',
    };
    final subtitle = run.state == CareerWorkbenchActionState.failed
        ? run.error ?? '动作执行失败，请检查输入资料后重试。'
        : run.resultHints.isEmpty
            ? '完成后会刷新当前项目、关联资产、推荐下一步和时间线。'
            : run.resultHints.join('；');
    return ProductCard(
      soft: true,
      tone: tone,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      child: Row(
        children: [
          ProductIconTile(
            icon: run.state == CareerWorkbenchActionState.running
                ? Icons.sync_rounded
                : run.state == CareerWorkbenchActionState.completed
                    ? Icons.check_circle_outline_rounded
                    : Icons.error_outline_rounded,
            tone: tone,
            size: 38,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: AppTheme.ts(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  subtitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    height: 1.35,
                    color: ProductColors.textSecondary,
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

class _ProjectFactStrip extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;

  const _ProjectFactStrip({
    required this.summary,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final jd = detail?.jdAnalysis;
    final report = detail?.jobFitReport;
    final metrics = [
      _FactMetric(
        icon: Icons.calendar_today_outlined,
        label: '投递时间',
        value: careerFormatDate(app?.meta.createdAt),
        tone: ProductTone.primary,
      ),
      _FactMetric(
        icon: Icons.link_rounded,
        label: '来源渠道',
        value: app?.jobUrl.trim().isNotEmpty == true ? '岗位链接' : 'Agent 记录',
        tone: ProductTone.info,
      ),
      _FactMetric(
        icon: Icons.people_alt_outlined,
        label: '招聘类型',
        value: careerFirstNonEmpty([jd?.seniority], fallback: '待补充'),
        tone: ProductTone.info,
      ),
      _FactMetric(
        icon: Icons.local_fire_department_outlined,
        label: '岗位热度',
        value: careerPriorityLabel(app?.priority),
        tone: careerPriorityTone(app?.priority),
      ),
      _FactMetric(
        icon: Icons.fact_check_outlined,
        label: '证据覆盖 / 评估信度',
        value: report == null
            ? '${summary?.linkedAssetCount ?? 0} 份资料'
            : '${report.scoreBreakdown.length} 项评分',
        tone: ProductTone.purple,
      ),
    ];
    return ProductSection(
      title: '岗位信息',
      subtitle: '投递信息、岗位来源和材料完整度',
      icon: Icons.dashboard_customize_outlined,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final columns = constraints.maxWidth >= 960
              ? 5
              : constraints.maxWidth >= 680
                  ? 3
                  : 2;
          const spacing = 12.0;
          final width =
              (constraints.maxWidth - spacing * (columns - 1)) / columns;
          return Wrap(
            spacing: spacing,
            runSpacing: spacing,
            children: [
              for (final metric in metrics)
                SizedBox(width: width, child: _FactMetricTile(metric: metric)),
            ],
          );
        },
      ),
    );
  }
}

class _ProjectWorkflowCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;

  const _ProjectWorkflowCard({
    required this.summary,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final steps = _workflowSteps(app, detail);
    final done = steps.where((step) => step.status == _StepStatus.done).length;
    return ProductSection(
      title: '项目推进流程',
      subtitle: '跟踪当前岗位的求职全流程进度',
      icon: Icons.route_outlined,
      tone: ProductTone.primary,
      trailing: Text(
        '$done / ${steps.length} 步完成',
        style: AppTheme.ts(
          fontSize: 12,
          fontWeight: FontWeight.w900,
          color: ProductColors.primary,
        ),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final columns = constraints.maxWidth >= 960
              ? 6
              : constraints.maxWidth >= 720
                  ? 3
                  : 2;
          const spacing = 10.0;
          final width =
              (constraints.maxWidth - spacing * (columns - 1)) / columns;
          return Wrap(
            spacing: spacing,
            runSpacing: spacing,
            children: [
              for (var i = 0; i < steps.length; i++)
                SizedBox(
                  width: width,
                  child: _WorkflowStepTile(index: i + 1, step: steps[i]),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _RiskActionGrid extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenLearning;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenJDMatch;
  final VoidCallback? onCustomResume;
  final void Function(
    CareerApplicationView? app, {
    required String label,
    required String actionType,
    String? detail,
  }) onSendAction;

  const _RiskActionGrid({
    required this.summary,
    required this.detail,
    required this.onOpenLearning,
    required this.onOpenResumes,
    required this.onOpenJDMatch,
    required this.onCustomResume,
    required this.onSendAction,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 820;
        final risks = _ProjectRisksCard(summary: summary, detail: detail);
        final actions = _ProjectRecommendedActions(
          summary: summary,
          detail: detail,
          onOpenLearning: onOpenLearning,
          onOpenResumes: onOpenResumes,
          onOpenJDMatch: onOpenJDMatch,
          onCustomResume: onCustomResume,
          onSendAction: onSendAction,
        );
        if (compact) {
          return Column(
            children: [
              risks,
              const SizedBox(height: 14),
              actions,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: risks),
            const SizedBox(width: 14),
            Expanded(child: actions),
          ],
        );
      },
    );
  }
}

class _ProjectRisksCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;

  const _ProjectRisksCard({
    required this.summary,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final readiness = detail?.readiness ?? summary?.readiness;
    final risks = [
      ...readiness?.risks ?? const <String>[],
      ...readiness?.missingMaterials ?? const <String>[],
      ...app?.risks ?? const <String>[],
    ].where((item) => item.trim().isNotEmpty).take(4).toList();
    return ProductSection(
      title: '当前风险与提醒',
      subtitle: '基于岗位要求与匹配分析',
      icon: Icons.report_problem_outlined,
      tone: ProductTone.warning,
      child: risks.isEmpty
          ? Text(
              '当前没有明确风险。后续 JD 匹配、面试复盘或简历优化会继续补充。',
              style: AppTheme.ts(
                fontSize: 12.3,
                height: 1.5,
                color: ProductColors.textMuted,
              ),
            )
          : Column(
              children: [
                for (var i = 0; i < risks.length; i++) ...[
                  _RiskRow(
                    risk: risks[i],
                    tone: i == 0 ? ProductTone.warning : ProductTone.info,
                    level: i == 0 ? '中风险' : '提醒',
                  ),
                  if (i != risks.length - 1) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _ProjectRecommendedActions extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenLearning;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenJDMatch;
  final VoidCallback? onCustomResume;
  final void Function(
    CareerApplicationView? app, {
    required String label,
    required String actionType,
    String? detail,
  }) onSendAction;

  const _ProjectRecommendedActions({
    required this.summary,
    required this.detail,
    required this.onOpenLearning,
    required this.onOpenResumes,
    required this.onOpenJDMatch,
    required this.onCustomResume,
    required this.onSendAction,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final actions = _recommendedProjectActions(app, detail).take(3).toList();
    return ProductSection(
      title: '推荐下一步',
      subtitle: '优先完成以下行动，提升命中率',
      icon: Icons.auto_fix_high_outlined,
      tone: ProductTone.primary,
      trailing: TextButton(
        onPressed: onOpenLearning,
        child: const Text('全部行动'),
      ),
      child: actions.isEmpty
          ? Text(
              '暂无推荐动作。继续补充简历、JD 或面试记录后会自动生成。',
              style: AppTheme.ts(
                fontSize: 12.3,
                height: 1.5,
                color: ProductColors.textMuted,
              ),
            )
          : Column(
              children: [
                for (var i = 0; i < actions.length; i++) ...[
                  ProductActionTile(
                    title: actions[i].label,
                    subtitle: actions[i].reason,
                    icon: careerActionIcon(actions[i].actionType),
                    tone: actions[i].tone,
                    actionLabel: actions[i].actionLabel,
                    onTap: () {
                      final action = actions[i];
                      if (action.actionType == 'custom_resume') {
                        onCustomResume?.call();
                        return;
                      }
                      if (action.actionType == 'jd_match_analysis') {
                        onOpenJDMatch();
                        return;
                      }
                      if (action.actionType == 'resume_view') {
                        onOpenResumes();
                        return;
                      }
                      if (action.actionType == 'learning_task') {
                        onOpenLearning();
                        return;
                      }
                      onSendAction(
                        app,
                        label: action.label,
                        actionType: action.actionType,
                        detail: action.reason,
                      );
                    },
                  ),
                  if (i != actions.length - 1) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _ProjectTimelineCard extends StatelessWidget {
  final CareerApplicationWorkbenchView? detail;

  const _ProjectTimelineCard({required this.detail});

  @override
  Widget build(BuildContext context) {
    final allTimeline =
        detail?.timeline.toList() ?? const <CareerTimelineItemView>[];
    final timeline =
        detail?.timeline.take(4).toList() ?? const <CareerTimelineItemView>[];
    return ProductSection(
      title: '时间线 / 最近记录',
      subtitle: '记录关键进展与里程碑',
      icon: Icons.timeline_outlined,
      tone: ProductTone.primary,
      trailing: TextButton(
        onPressed: allTimeline.isEmpty
            ? null
            : () => _showProjectTimelineDialog(context, allTimeline),
        child: const Text('查看全部记录'),
      ),
      child: timeline.isEmpty
          ? Text(
              '暂无项目动态。完成 JD 匹配、生成简历或记录复盘后会沉淀到这里。',
              style: AppTheme.ts(
                fontSize: 12.2,
                height: 1.5,
                color: ProductColors.textMuted,
              ),
            )
          : LayoutBuilder(
              builder: (context, constraints) {
                final columns = constraints.maxWidth >= 760 ? 4 : 2;
                const spacing = 12.0;
                final width =
                    (constraints.maxWidth - spacing * (columns - 1)) / columns;
                return Wrap(
                  spacing: spacing,
                  runSpacing: spacing,
                  children: [
                    for (final item in timeline)
                      SizedBox(
                          width: width, child: _TimelineMiniItem(item: item)),
                  ],
                );
              },
            ),
    );
  }
}

class _ProjectRightRail extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenJDMatch;
  final VoidCallback onOpenNotes;

  const _ProjectRightRail({
    required this.provider,
    required this.summary,
    required this.detail,
    required this.onOpenResumes,
    required this.onOpenJDMatch,
    required this.onOpenNotes,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _ProjectJudgmentCard(summary: summary, detail: detail),
        const SizedBox(height: 14),
        _ProjectProgressCard(summary: summary, detail: detail),
        const SizedBox(height: 14),
        _ProjectLinkedAssetsCard(
          provider: provider,
          detail: detail,
          onOpenResumes: onOpenResumes,
          onOpenJDMatch: onOpenJDMatch,
          onOpenNotes: onOpenNotes,
        ),
        const SizedBox(height: 14),
        _ProjectRelatedNotesCard(detail: detail, onOpenNotes: onOpenNotes),
      ],
    );
  }
}

class _ProjectJudgmentCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;

  const _ProjectJudgmentCard({
    required this.summary,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final readiness = detail?.readiness ?? summary?.readiness;
    final strengths = readiness?.strengths.take(3).toList() ?? const <String>[];
    final risks = readiness?.risks.take(2).toList() ?? const <String>[];
    return ProductSection(
      title: '当前判断',
      subtitle: '基于评分与推进建议',
      icon: Icons.psychology_alt_outlined,
      tone: careerScoreTone(readiness?.score),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                readiness?.score?.toString() ?? '-',
                style: AppTheme.ts(
                  fontSize: 36,
                  height: 1,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.primary,
                ),
              ),
              const SizedBox(width: 4),
              Text(
                '/100',
                style: AppTheme.ts(
                  fontSize: 14,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.textSecondary,
                ),
              ),
              const Spacer(),
              ProductTag(
                label: careerStageLabel(app?.stage),
                tone: careerStageTone(app?.stage),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            careerDisplaySummary(
              careerFirstNonEmpty(
                [readiness?.summary],
                fallback: '完成匹配后这里会展示 AI 判断。',
              ),
              maxChars: 142,
            ),
            maxLines: 5,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 12.2,
              height: 1.48,
              color: ProductColors.textSecondary,
            ),
          ),
          if (strengths.isNotEmpty) ...[
            const SizedBox(height: 14),
            _MiniBulletBlock(
              title: '主要优势',
              items: strengths,
              tone: ProductTone.primary,
            ),
          ],
          if (risks.isNotEmpty) ...[
            const SizedBox(height: 10),
            _MiniBulletBlock(
              title: '主要风险',
              items: risks,
              tone: ProductTone.warning,
            ),
          ],
        ],
      ),
    );
  }
}

class _ProjectProgressCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;

  const _ProjectProgressCard({
    required this.summary,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final steps = _workflowSteps(app, detail);
    final done = steps.where((step) => step.status == _StepStatus.done).length;
    final progress = steps.isEmpty ? 0.0 : done / steps.length;
    return ProductSection(
      title: '求职进度',
      subtitle: '$done / ${steps.length} 步完成',
      icon: Icons.route_outlined,
      tone: ProductTone.primary,
      child: Column(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              minHeight: 7,
              value: progress,
              color: ProductColors.primary,
              backgroundColor: ProductColors.primary.withValues(alpha: 0.12),
            ),
          ),
          const SizedBox(height: 12),
          for (final step in steps)
            _ProgressCompactRow(
              label: step.title,
              status: step.status,
              timestamp: _stepTimestamp(step, detail),
            ),
        ],
      ),
    );
  }
}

class _ProjectLinkedAssetsCard extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenJDMatch;
  final VoidCallback onOpenNotes;

  const _ProjectLinkedAssetsCard({
    required this.provider,
    required this.detail,
    required this.onOpenResumes,
    required this.onOpenJDMatch,
    required this.onOpenNotes,
  });

  @override
  Widget build(BuildContext context) {
    final assets = detail?.linkedAssets.take(5).toList() ??
        const <CareerLinkedAssetView>[];
    return ProductSection(
      title: '关联资产',
      subtitle: '简历、JD、笔记和报告',
      icon: Icons.folder_copy_outlined,
      tone: ProductTone.info,
      trailing: TextButton(
        onPressed: onOpenResumes,
        child: const Text('查看全部'),
      ),
      child: Column(
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final width = (constraints.maxWidth - 8) / 2;
              return Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  SizedBox(
                    width: width,
                    child: _AssetShortcut(
                      label: '简历',
                      value: provider.resumeLibraryCount,
                      icon: Icons.description_outlined,
                      onTap: onOpenResumes,
                    ),
                  ),
                  SizedBox(
                    width: width,
                    child: _AssetShortcut(
                      label: 'JD',
                      value: provider.jobMatchLibraryCount,
                      icon: Icons.analytics_outlined,
                      onTap: onOpenJDMatch,
                    ),
                  ),
                  SizedBox(
                    width: width,
                    child: _AssetShortcut(
                      label: '笔记',
                      value: provider.notes.length,
                      icon: Icons.sticky_note_2_outlined,
                      onTap: onOpenNotes,
                    ),
                  ),
                  SizedBox(
                    width: width,
                    child: _AssetShortcut(
                      label: '资料',
                      value: detail?.linkedAssets.length ?? 0,
                      icon: Icons.inventory_2_outlined,
                      onTap: () {
                        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                          const SnackBar(
                            content: Text('项目资料暂时汇总在当前项目和关联资产中，独立资料页后续再接入。'),
                          ),
                        );
                      },
                    ),
                  ),
                ],
              );
            },
          ),
          if (assets.isNotEmpty) ...[
            const SizedBox(height: 14),
            for (final asset in assets) ...[
              _AssetLine(asset: asset),
              if (asset != assets.last) const SizedBox(height: 9),
            ],
          ],
        ],
      ),
    );
  }
}

class _ProjectRelatedNotesCard extends StatelessWidget {
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenNotes;

  const _ProjectRelatedNotesCard({
    required this.detail,
    required this.onOpenNotes,
  });

  @override
  Widget build(BuildContext context) {
    final notes =
        detail?.notes.take(3).toList() ?? const <CareerNoteSummaryView>[];
    return ProductSection(
      title: '关联笔记',
      subtitle: notes.isEmpty ? '暂无笔记' : '${notes.length} 条最近笔记',
      icon: Icons.sticky_note_2_outlined,
      tone: ProductTone.warning,
      trailing: TextButton(onPressed: onOpenNotes, child: const Text('查看全部')),
      child: notes.isEmpty
          ? Text(
              '面试准备、复盘和项目备注会沉淀到这里。',
              style: AppTheme.ts(
                fontSize: 12.2,
                height: 1.5,
                color: ProductColors.textMuted,
              ),
            )
          : Column(
              children: [
                for (final note in notes) ...[
                  _NoteMiniItem(note: note),
                  if (note != notes.last) const SizedBox(height: 10),
                ],
              ],
            ),
    );
  }
}

class _CustomResumeDialog extends StatelessWidget {
  final CareerApplicationView application;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onStart;

  const _CustomResumeDialog({
    required this.application,
    required this.detail,
    required this.onStart,
  });

  @override
  Widget build(BuildContext context) {
    final jdReady = detail?.jdAnalysis != null ||
        application.jdAnalysisId?.trim().isNotEmpty == true;
    final fitReady = detail?.jobFitReport != null ||
        application.jobFitReportId?.trim().isNotEmpty == true;
    final resumeReady = detail?.resumeProfile != null ||
        application.resumeProfileId?.trim().isNotEmpty == true;
    final availableHeight = MediaQuery.sizeOf(context).height - 48;
    final dialogHeight = availableHeight < 520
        ? availableHeight
        : availableHeight > 760
            ? 760.0
            : availableHeight;
    return Dialog(
      insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: SizedBox(
        width: 760,
        height: dialogHeight,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 22, 24, 18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _CustomResumeDialogHeader(
                onClose: () => Navigator.of(context).pop(),
              ),
              const SizedBox(height: 18),
              Expanded(
                child: SingleChildScrollView(
                  child: Column(
                    children: [
                      _DialogSection(
                        number: '1',
                        title: '目标岗位',
                        child: _DialogTargetJob(application: application),
                      ),
                      _DialogSection(
                        number: '2',
                        title: '基础简历画像',
                        child: _ResumeBaseSummary(detail: detail),
                      ),
                      _DialogSection(
                        number: '3',
                        title: '生成依据',
                        child: Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          children: [
                            _EvidenceChip(label: 'JD 分析', ready: jdReady),
                            _EvidenceChip(label: '匹配报告', ready: fitReady),
                            _EvidenceChip(label: '基础简历画像', ready: resumeReady),
                          ],
                        ),
                      ),
                      _DialogSection(
                        number: '4',
                        title: '本次优化重点',
                        child: Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          children: const [
                            _StrategyChip(label: '强化 Agent 工程化'),
                            _StrategyChip(label: '补齐 RAG 细节'),
                            _StrategyChip(label: '强调量化结果'),
                            _StrategyChip(label: '突出系统稳定性'),
                          ],
                        ),
                      ),
                      _DialogSection(
                        number: '5',
                        title: '预期产物',
                        child: Column(
                          children: const [
                            _DialogOutcomeRow(
                              icon: Icons.description_outlined,
                              title: '岗位定制简历草案',
                              subtitle: '围绕目标岗位改写项目经历、关键词和能力表达。',
                            ),
                            SizedBox(height: 8),
                            _DialogOutcomeRow(
                              icon: Icons.folder_copy_outlined,
                              title: '关联项目资产',
                              subtitle: '生成后刷新当前项目的简历版本和关联资产。',
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 14),
              _CustomResumeDialogFooter(
                onCancel: () => Navigator.of(context).pop(),
                onStart: onStart,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CustomResumeDialogHeader extends StatelessWidget {
  final VoidCallback onClose;

  const _CustomResumeDialogHeader({required this.onClose});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ProductIconTile(
          icon: Icons.auto_awesome_rounded,
          tone: ProductTone.primary,
          size: 38,
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '生成岗位定制版',
                style: AppTheme.ts(
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '基于岗位需求与已有材料，生成更贴合岗位的定制简历草案。',
                style: AppTheme.ts(
                  fontSize: 12.5,
                  color: ProductColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
        IconButton(
          onPressed: onClose,
          icon: const Icon(Icons.close_rounded),
        ),
      ],
    );
  }
}

class _CustomResumeDialogFooter extends StatelessWidget {
  final VoidCallback onCancel;
  final VoidCallback onStart;

  const _CustomResumeDialogFooter({
    required this.onCancel,
    required this.onStart,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.end,
      children: [
        OutlinedButton(
          onPressed: onCancel,
          child: const Text('取消'),
        ),
        const SizedBox(width: 10),
        ElevatedButton.icon(
          onPressed: onStart,
          icon: const Icon(Icons.auto_awesome_rounded, size: 16),
          label: const Text('开始生成草案'),
          style: ElevatedButton.styleFrom(
            backgroundColor: ProductColors.primary,
            foregroundColor: Colors.white,
            elevation: 0,
            padding: const EdgeInsets.symmetric(horizontal: 18),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(11),
            ),
          ),
        ),
      ],
    );
  }
}

class _FactMetric {
  final IconData icon;
  final String label;
  final String value;
  final ProductTone tone;

  const _FactMetric({
    required this.icon,
    required this.label,
    required this.value,
    required this.tone,
  });
}

class _FactMetricTile extends StatelessWidget {
  final _FactMetric metric;

  const _FactMetricTile({required this.metric});

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(metric.tone);
    return Container(
      constraints: const BoxConstraints(minHeight: 64),
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: style.soft.withValues(alpha: 0.48),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: style.color.withValues(alpha: 0.1)),
      ),
      child: Row(
        children: [
          ProductIconTile(icon: metric.icon, tone: metric.tone, size: 36),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  metric.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11,
                    color: ProductColors.textMuted,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  metric.value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 13,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
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

enum _StepStatus { done, active, pending, blocked }

class _WorkflowStep {
  final String title;
  final String subtitle;
  final IconData icon;
  final _StepStatus status;

  const _WorkflowStep({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.status,
  });
}

class _WorkflowStepTile extends StatelessWidget {
  final int index;
  final _WorkflowStep step;

  const _WorkflowStepTile({
    required this.index,
    required this.step,
  });

  @override
  Widget build(BuildContext context) {
    final tone = switch (step.status) {
      _StepStatus.done => ProductTone.primary,
      _StepStatus.active => ProductTone.primary,
      _StepStatus.blocked => ProductTone.warning,
      _StepStatus.pending => ProductTone.neutral,
    };
    final style = productToneStyle(tone);
    return Container(
      constraints: const BoxConstraints(minHeight: 92),
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: step.status == _StepStatus.active
            ? ProductColors.primarySoft
            : step.status == _StepStatus.done
                ? ProductColors.surfaceMint.withValues(alpha: 0.56)
                : step.status == _StepStatus.blocked
                    ? ProductColors.warningSoft
                    : ProductColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: step.status == _StepStatus.active
              ? ProductColors.primary
              : style.color.withValues(alpha: 0.14),
        ),
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
                  color: step.status == _StepStatus.done
                      ? ProductColors.primary
                      : style.soft,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Center(
                  child: step.status == _StepStatus.done
                      ? const Icon(
                          Icons.check_rounded,
                          size: 17,
                          color: Colors.white,
                        )
                      : Text(
                          index.toString(),
                          style: AppTheme.ts(
                            fontSize: 13,
                            fontWeight: FontWeight.w900,
                            color: style.color,
                          ),
                        ),
                ),
              ),
              const Spacer(),
              Icon(step.icon, size: 16, color: style.color),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            step.title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 12.4,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            step.subtitle,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 10.8,
              color: ProductColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _RiskRow extends StatelessWidget {
  final String risk;
  final ProductTone tone;
  final String level;

  const _RiskRow({
    required this.risk,
    required this.tone,
    required this.level,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration: ProductSurface.softCard(tone: tone, radius: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            tone == ProductTone.warning
                ? Icons.warning_amber_rounded
                : Icons.info_outline_rounded,
            size: 17,
            color: style.color,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              risk,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 12,
                height: 1.4,
                fontWeight: FontWeight.w700,
                color: ProductColors.textSecondary,
              ),
            ),
          ),
          const SizedBox(width: 8),
          ProductTag(label: level, tone: tone),
        ],
      ),
    );
  }
}

class _ProjectActionItem {
  final String label;
  final String reason;
  final String actionType;
  final ProductTone tone;
  final String actionLabel;
  final IconData icon;

  const _ProjectActionItem({
    required this.label,
    required this.reason,
    required this.actionType,
    required this.tone,
    required this.actionLabel,
    required this.icon,
  });
}

class _TimelineMiniItem extends StatelessWidget {
  final CareerTimelineItemView item;

  const _TimelineMiniItem({required this.item});

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minHeight: 62),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.check_circle_outline_rounded,
            size: 17,
            color: ProductColors.primary,
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  item.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  careerFirstNonEmpty(
                    [item.subtitle, careerFormatDateTime(item.occurredAt)],
                    fallback: '-',
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 10.8,
                    color: ProductColors.textMuted,
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

Future<void> _showProjectTimelineDialog(
  BuildContext context,
  List<CareerTimelineItemView> timeline,
) async {
  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return Dialog(
        insetPadding: const EdgeInsets.all(24),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720, maxHeight: 760),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    ProductIconTile(
                      icon: Icons.timeline_outlined,
                      tone: ProductTone.primary,
                      size: 40,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '全部项目记录',
                            style: AppTheme.ts(
                              fontSize: 18,
                              fontWeight: FontWeight.w900,
                              color: ProductColors.text,
                            ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            '共 ${timeline.length} 条推进记录，按时间倒序展示。',
                            style: AppTheme.ts(
                              fontSize: 12.5,
                              color: ProductColors.textSecondary,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      tooltip: '关闭',
                      onPressed: () => Navigator.of(dialogContext).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Expanded(
                  child: ListView.separated(
                    itemCount: timeline.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, index) {
                      final item = timeline[index];
                      return Container(
                        padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
                        decoration: BoxDecoration(
                          color: ProductColors.surfaceSoft,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: ProductColors.border),
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            ProductIconTile(
                              icon: Icons.check_circle_outline_rounded,
                              tone: ProductTone.primary,
                              size: 34,
                            ),
                            const SizedBox(width: 10),
                            Expanded(
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
                                            fontSize: 13,
                                            fontWeight: FontWeight.w900,
                                            color: ProductColors.text,
                                          ),
                                        ),
                                      ),
                                      const SizedBox(width: 10),
                                      Text(
                                        careerFormatDateTime(item.occurredAt),
                                        style: AppTheme.ts(
                                          fontSize: 11.5,
                                          color: ProductColors.textMuted,
                                        ),
                                      ),
                                    ],
                                  ),
                                  if (item.subtitle.trim().isNotEmpty) ...[
                                    const SizedBox(height: 5),
                                    Text(
                                      item.subtitle,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: AppTheme.ts(
                                        fontSize: 12,
                                        height: 1.45,
                                        color: ProductColors.textSecondary,
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerRight,
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(dialogContext).pop(),
                    child: const Text('关闭'),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    },
  );
}

class _MiniBulletBlock extends StatelessWidget {
  final String title;
  final List<String> items;
  final ProductTone tone;

  const _MiniBulletBlock({
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

class _ProgressCompactRow extends StatelessWidget {
  final String label;
  final _StepStatus status;
  final String? timestamp;

  const _ProgressCompactRow({
    required this.label,
    required this.status,
    required this.timestamp,
  });

  @override
  Widget build(BuildContext context) {
    final done = status == _StepStatus.done;
    final active = status == _StepStatus.active;
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Row(
        children: [
          Icon(
            done
                ? Icons.check_circle_rounded
                : active
                    ? Icons.radio_button_checked_rounded
                    : Icons.radio_button_unchecked_rounded,
            size: 15,
            color: done || active
                ? ProductColors.primary
                : ProductColors.textMuted,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: active ? FontWeight.w900 : FontWeight.w700,
                color: done || active
                    ? ProductColors.text
                    : ProductColors.textMuted,
              ),
            ),
          ),
          if (timestamp?.trim().isNotEmpty == true)
            Text(
              timestamp!,
              style: AppTheme.ts(
                fontSize: 10.5,
                color: ProductColors.textMuted,
              ),
            )
          else if (active)
            ProductTag(label: '进行中', tone: ProductTone.primary),
        ],
      ),
    );
  }
}

class _AssetShortcut extends StatelessWidget {
  final String label;
  final int value;
  final IconData icon;
  final VoidCallback? onTap;

  const _AssetShortcut({
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
          padding: const EdgeInsets.fromLTRB(9, 10, 9, 10),
          decoration: BoxDecoration(
            color: ProductColors.infoSoft.withValues(alpha: 0.58),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: ProductColors.info.withValues(alpha: 0.1),
            ),
          ),
          child: Column(
            children: [
              Icon(icon, size: 18, color: ProductColors.info),
              const SizedBox(height: 6),
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

class _AssetLine extends StatelessWidget {
  final CareerLinkedAssetView asset;

  const _AssetLine({required this.asset});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ProductIconTile(
          icon: _assetIcon(asset.type),
          tone: asset.isCurrent ? ProductTone.primary : ProductTone.info,
          size: 32,
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                careerFirstNonEmpty(
                  [asset.title, asset.subtitle, asset.id],
                  fallback: '关联资料',
                ),
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
                '${careerAssetTypeLabel(asset.type)} · ${careerFormatDateTime(asset.updatedAt)}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
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

class _NoteMiniItem extends StatelessWidget {
  final CareerNoteSummaryView note;

  const _NoteMiniItem({required this.note});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ProductIconTile(
          icon: Icons.sticky_note_2_outlined,
          tone: ProductTone.warning,
          size: 32,
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                careerShortLabel(note.title, fallback: '项目笔记'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                careerFormatDateTime(note.updatedAt),
                style: AppTheme.ts(
                  fontSize: 10.5,
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
      width: 74,
      height: 74,
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: ProductColors.primary.withValues(alpha: 0.1)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 16,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Center(
        child: Text(
          text,
          style: AppTheme.ts(
            fontSize: 26,
            fontWeight: FontWeight.w900,
            color: ProductColors.primary,
          ),
        ),
      ),
    );
  }
}

class _PrimaryProjectButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback? onPressed;

  const _PrimaryProjectButton({
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: ElevatedButton.icon(
        onPressed: onPressed,
        icon: Icon(icon, size: 16),
        label: Text(label),
        style: ElevatedButton.styleFrom(
          backgroundColor: ProductColors.primary,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 18),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
    );
  }
}

class _SecondaryProjectButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback onPressed;

  const _SecondaryProjectButton({
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: OutlinedButton.icon(
        onPressed: onPressed,
        icon: Icon(icon, size: 16),
        label: Text(label),
        style: OutlinedButton.styleFrom(
          foregroundColor: ProductColors.primary,
          side: const BorderSide(color: ProductColors.borderStrong),
          padding: const EdgeInsets.symmetric(horizontal: 18),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
    );
  }
}

class _DialogSection extends StatelessWidget {
  final String number;
  final String title;
  final Widget child;

  const _DialogSection({
    required this.number,
    required this.title,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 22,
                height: 22,
                decoration: BoxDecoration(
                  color: ProductColors.primary,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Center(
                  child: Text(
                    number,
                    style: AppTheme.ts(
                      fontSize: 11,
                      fontWeight: FontWeight.w900,
                      color: Colors.white,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 13,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
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

class _DialogTargetJob extends StatelessWidget {
  final CareerApplicationView application;

  const _DialogTargetJob({required this.application});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration:
          ProductSurface.softCard(tone: ProductTone.primary, radius: 12),
      child: Row(
        children: [
          _CompanyAvatar(label: application.company),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  careerShortLabel(application.company, fallback: '目标公司'),
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  careerShortLabel(application.position, fallback: '目标岗位'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 14,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    ProductTag(
                      label: careerShortLabel(application.location),
                      tone: ProductTone.neutral,
                    ),
                    ProductTag(
                      label: '优先级 ${careerPriorityLabel(application.priority)}',
                      tone: careerPriorityTone(application.priority),
                    ),
                    ProductTag(
                      label: careerStageLabel(application.stage),
                      tone: careerStageTone(application.stage),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ResumeBaseSummary extends StatelessWidget {
  final CareerApplicationWorkbenchView? detail;

  const _ResumeBaseSummary({required this.detail});

  @override
  Widget build(BuildContext context) {
    final profile = detail?.resumeProfile;
    final skills = profile?.skills.take(8).toList() ?? const <String>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          profile == null ? '尚未读取到基础简历画像' : '已读取基础简历画像',
          style: AppTheme.ts(
            fontSize: 12.5,
            fontWeight: FontWeight.w900,
            color: ProductColors.text,
          ),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 7,
          runSpacing: 7,
          children: [
            for (final skill in skills)
              ProductTag(label: skill, tone: ProductTone.info),
            if (skills.isEmpty)
              ProductTag(label: '等待简历画像', tone: ProductTone.warning),
          ],
        ),
      ],
    );
  }
}

class _EvidenceChip extends StatelessWidget {
  final String label;
  final bool ready;

  const _EvidenceChip({
    required this.label,
    required this.ready,
  });

  @override
  Widget build(BuildContext context) {
    return ProductTag(
      label: '$label ${ready ? '已完成' : '待补充'}',
      icon: ready ? Icons.check_circle_rounded : Icons.pending_outlined,
      tone: ready ? ProductTone.primary : ProductTone.warning,
    );
  }
}

class _StrategyChip extends StatelessWidget {
  final String label;

  const _StrategyChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return ProductTag(
      label: label,
      icon: Icons.check_rounded,
      tone: ProductTone.primary,
    );
  }
}

class _DialogOutcomeRow extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;

  const _DialogOutcomeRow({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration:
          ProductSurface.softCard(tone: ProductTone.primary, radius: 12),
      child: Row(
        children: [
          ProductIconTile(icon: icon, tone: ProductTone.primary, size: 32),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  style: AppTheme.ts(
                    fontSize: 11,
                    height: 1.35,
                    color: ProductColors.textSecondary,
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

class _ProjectsError extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const _ProjectsError({
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
              '求职项目加载失败',
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

List<_WorkflowStep> _workflowSteps(
  CareerApplicationView? app,
  CareerApplicationWorkbenchView? detail,
) {
  final jdDone = detail?.jdAnalysis != null ||
      app?.jdAnalysisId?.trim().isNotEmpty == true;
  final fitDone = detail?.jobFitReport != null ||
      app?.jobFitReportId?.trim().isNotEmpty == true;
  final resumeDone = detail?.resumeVersions.isNotEmpty == true ||
      app?.resumeVersionIds.isNotEmpty == true;
  final applied = _stageOrder(app?.stage) >= _stageOrder('applied');
  final interview = _stageOrder(app?.stage) >= _stageOrder('interviewing');
  final hasNotes = detail?.notes.isNotEmpty == true;

  final data = [
    _StepSeed(
      title: 'JD 匹配',
      subtitle: jdDone || fitDone ? '已完成' : '待分析',
      icon: Icons.analytics_outlined,
      done: jdDone || fitDone,
    ),
    _StepSeed(
      title: '定制简历',
      subtitle: resumeDone ? '已完成' : '待生成',
      icon: Icons.description_outlined,
      done: resumeDone,
    ),
    _StepSeed(
      title: '投递前检查',
      subtitle: applied ? '已完成' : '待进行',
      icon: Icons.checklist_rounded,
      done: applied,
    ),
    _StepSeed(
      title: '简历投递',
      subtitle: applied ? '进行中' : '待进行',
      icon: Icons.send_outlined,
      done: _stageOrder(app?.stage) > _stageOrder('applied'),
    ),
    _StepSeed(
      title: '面试准备',
      subtitle: interview ? '进行中' : '待进行',
      icon: Icons.forum_outlined,
      done: _stageOrder(app?.stage) > _stageOrder('interviewing'),
    ),
    _StepSeed(
      title: '复盘记录',
      subtitle: hasNotes ? '有笔记' : '待记录',
      icon: Icons.sticky_note_2_outlined,
      done: hasNotes && _stageOrder(app?.stage) >= _stageOrder('interviewing'),
    ),
  ];

  var activeAssigned = false;
  return [
    for (final item in data)
      _WorkflowStep(
        title: item.title,
        subtitle: item.subtitle,
        icon: item.icon,
        status: item.done
            ? _StepStatus.done
            : activeAssigned
                ? _StepStatus.pending
                : (activeAssigned = true) == true
                    ? _StepStatus.active
                    : _StepStatus.pending,
      ),
  ];
}

class _StepSeed {
  final String title;
  final String subtitle;
  final IconData icon;
  final bool done;

  const _StepSeed({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.done,
  });
}

String? _stepTimestamp(
  _WorkflowStep step,
  CareerApplicationWorkbenchView? detail,
) {
  for (final item in detail?.timeline ?? const <CareerTimelineItemView>[]) {
    if (item.title.contains(step.title) || step.title.contains(item.title)) {
      return careerFormatDateTime(item.occurredAt);
    }
  }
  return null;
}

_ProjectActionItem _primaryProjectAction(
  CareerApplicationView app,
  CareerApplicationWorkbenchView? detail,
) {
  if (detail?.jdAnalysis == null &&
      app.jdAnalysisId?.trim().isNotEmpty != true) {
    return const _ProjectActionItem(
      label: '分析 JD 匹配',
      reason: '补齐岗位要求和匹配判断。',
      actionType: 'jd_match_analysis',
      tone: ProductTone.info,
      actionLabel: '去分析',
      icon: Icons.analytics_outlined,
    );
  }
  if (detail?.jobFitReport == null &&
      app.jobFitReportId?.trim().isNotEmpty != true) {
    return const _ProjectActionItem(
      label: '生成匹配报告',
      reason: '结合简历画像和 JD 生成岗位匹配报告。',
      actionType: 'jd_match_analysis',
      tone: ProductTone.info,
      actionLabel: '去生成',
      icon: Icons.fact_check_outlined,
    );
  }
  if (detail?.resumeVersions.isNotEmpty != true &&
      app.resumeVersionIds.isEmpty) {
    return const _ProjectActionItem(
      label: '生成定制简历',
      reason: '基于岗位匹配结果生成 tailored 简历版本。',
      actionType: 'custom_resume',
      tone: ProductTone.primary,
      actionLabel: '去生成',
      icon: Icons.description_outlined,
    );
  }
  if ((app.stage).trim() == 'ready_to_apply') {
    return const _ProjectActionItem(
      label: '投递前检查',
      reason: '检查简历、匹配报告和投递材料。',
      actionType: 'pre_apply_check',
      tone: ProductTone.warning,
      actionLabel: '去检查',
      icon: Icons.checklist_rounded,
    );
  }
  if ((app.stage).trim() == 'interviewing') {
    return const _ProjectActionItem(
      label: '准备面试题',
      reason: '基于岗位风险生成面试问题和答案草案。',
      actionType: 'interview_prep',
      tone: ProductTone.purple,
      actionLabel: '去准备',
      icon: Icons.forum_outlined,
    );
  }
  return const _ProjectActionItem(
    label: '查看下一步',
    reason: '查看当前推荐动作。',
    actionType: 'project_next',
    tone: ProductTone.primary,
    actionLabel: '查看',
    icon: Icons.arrow_forward_rounded,
  );
}

List<_ProjectActionItem> _recommendedProjectActions(
  CareerApplicationView? app,
  CareerApplicationWorkbenchView? detail,
) {
  final actions = <_ProjectActionItem>[];
  for (final action in detail?.suggestedActions ?? const []) {
    if (!action.enabled) continue;
    actions.add(
      _ProjectActionItem(
        label: _projectActionLabel(action.actionType, action.label),
        reason: careerFirstNonEmpty(
          [action.reason, action.promptIntent, app?.summary],
          fallback: '基于当前项目状态继续推进。',
        ),
        actionType: _normalizeActionType(action.actionType),
        tone: careerPriorityTone(action.priority),
        actionLabel: _projectActionButton(action.actionType),
        icon: careerActionIcon(action.actionType),
      ),
    );
  }
  final fallback = [
    const _ProjectActionItem(
      label: '生成定制简历',
      reason: '围绕目标岗位改写项目经历、关键词和能力表达。',
      actionType: 'custom_resume',
      tone: ProductTone.primary,
      actionLabel: '去生成',
      icon: Icons.description_outlined,
    ),
    const _ProjectActionItem(
      label: '投递前检查',
      reason: '检查简历与岗位匹配度，优化投递材料。',
      actionType: 'pre_apply_check',
      tone: ProductTone.warning,
      actionLabel: '去检查',
      icon: Icons.checklist_rounded,
    ),
    const _ProjectActionItem(
      label: '准备面试题',
      reason: '根据 JD 风险点生成面试问题和参考答案。',
      actionType: 'interview_prep',
      tone: ProductTone.purple,
      actionLabel: '去准备',
      icon: Icons.forum_outlined,
    ),
  ];
  for (final item in fallback) {
    if (actions.length >= 4) break;
    if (!actions.any((action) => action.actionType == item.actionType)) {
      actions.add(item);
    }
  }
  return actions;
}

String _projectActionLabel(String type, String fallback) {
  final normalized = _normalizeActionType(type);
  return switch (normalized) {
    'jd_match_analysis' => '分析 JD 匹配',
    'custom_resume' => '生成定制简历',
    'resume_optimize' => '优化当前简历',
    'pre_apply_check' => '投递前检查',
    'interview_prep' => '准备面试题',
    'learning_task' => '转成学习任务',
    'note_review' => '记录复盘',
    _ => careerShortLabel(fallback, fallback: '推进求职动作'),
  };
}

String _projectActionButton(String type) {
  final normalized = _normalizeActionType(type);
  return switch (normalized) {
    'jd_match_analysis' => '去分析',
    'custom_resume' => '去生成',
    'resume_optimize' => '去优化',
    'pre_apply_check' => '去检查',
    'interview_prep' => '去准备',
    'learning_task' => '去学习页',
    'note_review' => '去记录',
    _ => '去执行',
  };
}

String _normalizeActionType(String type) {
  return switch (type.trim()) {
    'jd_match' || 'job_fit' || 'fit_report' => 'jd_match_analysis',
    'preflight_check' || 'pre_apply' => 'pre_apply_check',
    'note' || 'note_create' => 'note_review',
    _ => type.trim(),
  };
}

String _projectFilterLabel(CareerProjectFilter filter) {
  return switch (filter) {
    CareerProjectFilter.all => '全部项目',
    CareerProjectFilter.draft => '草稿',
    CareerProjectFilter.readyToApply => '准备投递',
    CareerProjectFilter.applied => '已投递',
    CareerProjectFilter.interviewing => '面试中',
    CareerProjectFilter.paused => '暂停',
  };
}

int _stageOrder(String? stage) {
  return switch ((stage ?? '').trim()) {
    'draft' => 0,
    'ready_to_apply' => 1,
    'applied' => 2,
    'screening' => 3,
    'interviewing' => 4,
    'offer' => 5,
    'rejected' => 6,
    _ => 0,
  };
}

IconData _assetIcon(String type) {
  return switch (type.trim()) {
    'resume_profile' || 'resume_version' => Icons.description_outlined,
    'jd_analysis' => Icons.analytics_outlined,
    'job_fit_report' => Icons.fact_check_outlined,
    'note' => Icons.sticky_note_2_outlined,
    'learning_task' => Icons.school_outlined,
    _ => Icons.insert_drive_file_outlined,
  };
}
