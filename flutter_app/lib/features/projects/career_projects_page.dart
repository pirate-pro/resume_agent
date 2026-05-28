import 'dart:async';
import 'dart:math' as math;

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
  final CareerPromptSender? onSendPrompt;

  const CareerProjectsPage({
    super.key,
    required this.onOpenProject,
    required this.onOpenResumes,
    required this.onOpenJDMatch,
    required this.onOpenLearning,
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

    final selectedSummary = provider.selectedApplicationSummary;
    final detail = provider.selectedApplicationDetail;
    final selectedApp = detail?.application ?? selectedSummary?.application;

    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= 1180;
        final main = ListView(
          padding: EdgeInsets.zero,
          children: [
            _ProjectHeader(
              provider: provider,
              selectedApplication: selectedApp,
              onRefresh: () => unawaited(provider.refresh()),
            ),
            const SizedBox(height: 14),
            if (provider.activeAction != null) ...[
              _ProjectActionBanner(run: provider.activeAction!),
              const SizedBox(height: 14),
            ],
            _ProjectHeroCard(
              summary: selectedSummary,
              detail: detail,
              onOpenJDMatch: widget.onOpenJDMatch,
              onSendPrompt: widget.onSendPrompt,
            ),
            const SizedBox(height: 16),
            _PositionOverviewCard(summary: selectedSummary, detail: detail),
            const SizedBox(height: 16),
            _ExecutionBoard(
              summary: selectedSummary,
              detail: detail,
              onSendPrompt: widget.onSendPrompt,
            ),
            const SizedBox(height: 16),
            _RiskActionGrid(
              summary: selectedSummary,
              detail: detail,
              onOpenLearning: widget.onOpenLearning,
              onSendPrompt: widget.onSendPrompt,
            ),
          ],
        );
        final rail = _ProjectRightRail(
          provider: provider,
          summary: selectedSummary,
          detail: detail,
          onOpenResumes: widget.onOpenResumes,
          onOpenJDMatch: widget.onOpenJDMatch,
        );
        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              _ProjectHeader(
                provider: provider,
                selectedApplication: selectedApp,
                onRefresh: () => unawaited(provider.refresh()),
              ),
              const SizedBox(height: 14),
              if (provider.activeAction != null) ...[
                _ProjectActionBanner(run: provider.activeAction!),
                const SizedBox(height: 14),
              ],
              _ProjectHeroCard(
                summary: selectedSummary,
                detail: detail,
                onOpenJDMatch: widget.onOpenJDMatch,
                onSendPrompt: widget.onSendPrompt,
              ),
              const SizedBox(height: 14),
              rail,
              const SizedBox(height: 14),
              _PositionOverviewCard(summary: selectedSummary, detail: detail),
              const SizedBox(height: 14),
              _ExecutionBoard(
                summary: selectedSummary,
                detail: detail,
                onSendPrompt: widget.onSendPrompt,
              ),
              const SizedBox(height: 14),
              _RiskActionGrid(
                summary: selectedSummary,
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
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final title = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 8,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    '求职项目',
                    style: AppTheme.ts(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: ProductColors.text,
                    ),
                  ),
                  ProductTag(
                    label: '岗位工作台',
                    tone: ProductTone.primary,
                    icon: Icons.business_center_outlined,
                  ),
                  if (provider.isRefreshing)
                    const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: ProductColors.primary,
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 5),
              Text(
                '围绕一个目标岗位管理匹配判断、执行进度、风险差距和关联资产。',
                maxLines: compact ? 2 : 1,
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
      CareerWorkbenchActionState.running => '执行中：${run.request.label}',
      CareerWorkbenchActionState.completed => '已完成：${run.request.label}',
      CareerWorkbenchActionState.failed => '执行失败：${run.request.label}',
    };
    final subtitle = run.state == CareerWorkbenchActionState.failed
        ? run.error ?? '动作执行失败'
        : run.resultHints.isEmpty
            ? 'Agent 正在通过聊天链路执行，并会在结束后刷新项目状态。'
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

class _ProjectHeroCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenJDMatch;
  final CareerPromptSender? onSendPrompt;

  const _ProjectHeroCard({
    required this.summary,
    required this.detail,
    required this.onOpenJDMatch,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final readiness = detail?.readiness ?? summary?.readiness;
    if (app == null) {
      return ProductCard(
        padding: const EdgeInsets.fromLTRB(22, 22, 22, 22),
        child: Row(
          children: [
            const ProductIconTile(
              icon: Icons.business_center_outlined,
              tone: ProductTone.primary,
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Text(
                '还没有求职项目。可以先上传简历和 JD，让 Agent 生成第一个岗位工作台。',
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

    return Container(
      padding: const EdgeInsets.fromLTRB(24, 22, 24, 22),
      decoration: ProductSurface.hero(),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final leading = Row(
            children: [
              _CompanyAvatar(label: app.company),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          careerShortLabel(app.company, fallback: '目标公司'),
                          style: AppTheme.ts(
                            fontSize: 13,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.textSecondary,
                          ),
                        ),
                        ProductTag(
                          label: careerStageLabel(app.stage),
                          tone: careerStageTone(app.stage),
                        ),
                      ],
                    ),
                    const SizedBox(height: 7),
                    Text(
                      careerShortLabel(app.position, fallback: '目标岗位'),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: compact ? 18 : 20,
                        height: 1.2,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 10,
                      runSpacing: 8,
                      children: [
                        ProductTag(
                          label: careerShortLabel(app.location),
                          icon: Icons.location_on_outlined,
                          tone: ProductTone.neutral,
                        ),
                        ProductTag(
                          label: '优先级 ${careerPriorityLabel(app.priority)}',
                          tone: careerPriorityTone(app.priority),
                        ),
                        ProductTag(
                          label:
                              '更新 ${careerFormatDateTime(app.meta.updatedAt)}',
                          tone: ProductTone.info,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          );
          final score = Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ProductScoreRing(score: readiness?.score, size: 92),
              const SizedBox(height: 8),
              ProductTag(
                label: careerRecommendationLabel(
                  readiness?.recommendation,
                  readiness?.score,
                ),
                tone: careerScoreTone(readiness?.score),
              ),
            ],
          );
          final summaryBlock = Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
            decoration: BoxDecoration(
              color: ProductColors.surface.withValues(alpha: 0.72),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(
                color: ProductColors.primary.withValues(alpha: 0.12),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'AI 总结',
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 7),
                Text(
                  careerFirstNonEmpty(
                    [readiness?.summary, app.summary],
                    fallback: '完成 JD 匹配后会在这里展示岗位判断、核心风险和推进建议。',
                  ),
                  maxLines: compact ? 5 : 3,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.2,
                    height: 1.48,
                    color: ProductColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    SizedBox(
                      height: 34,
                      child: ElevatedButton(
                        onPressed: () => sendCareerPromptAction(
                          sender: onSendPrompt,
                          application: app,
                          label: '生成定制简历',
                          actionType: 'custom_resume',
                          origin: 'projects',
                          detail: '基于当前岗位匹配结论生成定制简历版本。',
                        ),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: ProductColors.primary,
                          foregroundColor: Colors.white,
                          elevation: 0,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(11),
                          ),
                        ),
                        child: const Text('生成定制简历'),
                      ),
                    ),
                    SizedBox(
                      height: 34,
                      child: OutlinedButton(
                        onPressed: onOpenJDMatch,
                        style: OutlinedButton.styleFrom(
                          foregroundColor: ProductColors.primary,
                          side: const BorderSide(color: ProductColors.border),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(11),
                          ),
                        ),
                        child: const Text('查看完整分析报告'),
                      ),
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
                leading,
                const SizedBox(height: 18),
                Center(child: score),
                const SizedBox(height: 18),
                summaryBlock,
              ],
            );
          }
          return Row(
            children: [
              Expanded(flex: 5, child: leading),
              const SizedBox(width: 22),
              score,
              const SizedBox(width: 22),
              Expanded(flex: 4, child: summaryBlock),
            ],
          );
        },
      ),
    );
  }
}

class _PositionOverviewCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;

  const _PositionOverviewCard({
    required this.summary,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final jd = detail?.jdAnalysis;
    final report = detail?.jobFitReport;
    return ProductSection(
      title: '岗位总览',
      subtitle: '投递信息、岗位来源和材料完整度',
      icon: Icons.dashboard_customize_outlined,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final columns = constraints.maxWidth >= 900
              ? 5
              : constraints.maxWidth >= 620
                  ? 3
                  : 2;
          const spacing = 10.0;
          final width =
              (constraints.maxWidth - spacing * (columns - 1)) / columns;
          final metrics = [
            _OverviewMetricData(
              icon: Icons.calendar_today_outlined,
              label: '投递时间',
              value: careerFormatDate(app?.meta.createdAt),
              tone: ProductTone.primary,
            ),
            _OverviewMetricData(
              icon: Icons.campaign_outlined,
              label: '岗位来源',
              value:
                  app?.jobUrl.trim().isNotEmpty == true ? '链接导入' : 'Agent 记录',
              tone: ProductTone.info,
            ),
            _OverviewMetricData(
              icon: Icons.people_alt_outlined,
              label: '招聘类型',
              value: careerFirstNonEmpty([jd?.seniority], fallback: '社招'),
              tone: ProductTone.info,
            ),
            _OverviewMetricData(
              icon: Icons.local_fire_department_outlined,
              label: '岗位热度',
              value: careerPriorityLabel(app?.priority),
              tone: careerPriorityTone(app?.priority),
            ),
            _OverviewMetricData(
              icon: Icons.fact_check_outlined,
              label: '证据覆盖',
              value: report == null
                  ? '${summary?.linkedAssetCount ?? 0} 份资料'
                  : '${report.scoreBreakdown.length} 项评分',
              tone: ProductTone.purple,
            ),
          ];
          return Wrap(
            spacing: spacing,
            runSpacing: spacing,
            children: [
              for (final metric in metrics)
                SizedBox(width: width, child: _OverviewMetric(metric: metric)),
            ],
          );
        },
      ),
    );
  }
}

class _ExecutionBoard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final CareerPromptSender? onSendPrompt;

  const _ExecutionBoard({
    required this.summary,
    required this.detail,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 860;
        final timeline = _InterviewTimelineCard(
          application: detail?.application ?? summary?.application,
          timeline: detail?.timeline ?? const [],
        );
        final agents = _AgentExecutionCard(
          summary: summary,
          detail: detail,
          onSendPrompt: onSendPrompt,
        );
        if (compact) {
          return Column(
            children: [
              timeline,
              const SizedBox(height: 14),
              agents,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(width: 260, child: timeline),
            const SizedBox(width: 14),
            Expanded(child: agents),
          ],
        );
      },
    );
  }
}

class _InterviewTimelineCard extends StatelessWidget {
  final CareerApplicationView? application;
  final List<CareerTimelineItemView> timeline;

  const _InterviewTimelineCard({
    required this.application,
    required this.timeline,
  });

  @override
  Widget build(BuildContext context) {
    final currentStage = application?.stage;
    final steps = [
      _TimelineStep('简历投递', 'applied', Icons.send_outlined),
      _TimelineStep('简历筛选', 'screening', Icons.fact_check_outlined),
      _TimelineStep('技术面试', 'interviewing', Icons.code_rounded),
      _TimelineStep('综合面试', 'interviewing', Icons.groups_outlined),
      _TimelineStep('Offer', 'offer', Icons.verified_outlined),
    ];
    return ProductSection(
      title: '面试流程时间线',
      subtitle: timeline.isEmpty ? '按当前阶段推断' : '来自项目事件',
      icon: Icons.timeline_outlined,
      tone: ProductTone.primary,
      child: Column(
        children: [
          for (var i = 0; i < steps.length; i++) ...[
            _TimelineStepRow(
              step: steps[i],
              active: _isStageActive(currentStage, steps[i].stage, i),
              done: _isStageDone(currentStage, i),
              subtitle: _timelineSubtitle(timeline, steps[i].label),
            ),
            if (i != steps.length - 1) const SizedBox(height: 8),
          ],
        ],
      ),
    );
  }
}

class _AgentExecutionCard extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final CareerPromptSender? onSendPrompt;

  const _AgentExecutionCard({
    required this.summary,
    required this.detail,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final agents = [
      _AgentStep(
        title: '简历解析 Agent',
        subtitle: detail?.resumeProfile == null ? '等待简历画像' : '提取关键项目与技能',
        icon: Icons.article_outlined,
        done: detail?.resumeProfile != null ||
            app?.resumeProfileId?.trim().isNotEmpty == true,
        tone: ProductTone.primary,
      ),
      _AgentStep(
        title: 'JD 分析 Agent',
        subtitle: detail?.jdAnalysis == null ? '等待岗位要求' : '解析岗位要求与职责',
        icon: Icons.near_me_outlined,
        done: detail?.jdAnalysis != null ||
            app?.jdAnalysisId?.trim().isNotEmpty == true,
        tone: ProductTone.info,
      ),
      _AgentStep(
        title: '匹配评估 Agent',
        subtitle: '评估匹配度与差距',
        icon: Icons.analytics_outlined,
        done: (detail?.readiness.score ?? summary?.readiness.score) != null,
        tone: ProductTone.info,
      ),
      _AgentStep(
        title: '简历改写 Agent',
        subtitle:
            detail?.resumeVersions.isEmpty == false ? '已生成定制版本' : '可生成岗位定制简历',
        icon: Icons.edit_note_outlined,
        done: detail?.resumeVersions.isEmpty == false ||
            app?.resumeVersionIds.isNotEmpty == true,
        tone: ProductTone.warning,
        actionLabel: '生成定制简历',
        actionType: 'custom_resume',
      ),
      _AgentStep(
        title: '面试准备 Agent',
        subtitle: '生成面试问题与答案',
        icon: Icons.forum_outlined,
        done: detail?.learning.openTaskCount != null &&
            (detail?.learning.openTaskCount ?? 0) > 0,
        tone: ProductTone.purple,
        actionLabel: '继续执行',
        actionType: 'interview_prep',
      ),
    ];
    return ProductSection(
      title: '多 Agent 执行进度',
      subtitle: '展示当前岗位已完成和可继续的执行链路',
      icon: Icons.account_tree_outlined,
      tone: ProductTone.info,
      trailing: Text(
        '${agents.where((item) => item.done).length}/${agents.length}',
        style: AppTheme.ts(
          fontSize: 12,
          fontWeight: FontWeight.w900,
          color: ProductColors.primary,
        ),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final columns = constraints.maxWidth >= 860
              ? 3
              : constraints.maxWidth >= 560
                  ? 2
                  : 1;
          const spacing = 12.0;
          final width =
              (constraints.maxWidth - spacing * (columns - 1)) / columns;
          return Wrap(
            spacing: spacing,
            runSpacing: spacing,
            children: [
              for (final agent in agents)
                SizedBox(
                  width: width,
                  child: _AgentStepCard(
                    step: agent,
                    application: app,
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

class _RiskActionGrid extends StatelessWidget {
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;
  final VoidCallback onOpenLearning;
  final CareerPromptSender? onSendPrompt;

  const _RiskActionGrid({
    required this.summary,
    required this.detail,
    required this.onOpenLearning,
    required this.onSendPrompt,
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
          onSendPrompt: onSendPrompt,
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
      title: '风险与差距',
      subtitle: '优先处理会影响推进的短板',
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
  final CareerPromptSender? onSendPrompt;

  const _ProjectRecommendedActions({
    required this.summary,
    required this.detail,
    required this.onOpenLearning,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final app = detail?.application ?? summary?.application;
    final actions = _recommendedProjectActions(app, detail).take(3).toList();
    return ProductSection(
      title: '推荐动作',
      subtitle: '从当前岗位状态推导下一步',
      icon: Icons.auto_fix_high_outlined,
      tone: ProductTone.primary,
      trailing: TextButton(
        onPressed: onOpenLearning,
        child: const Text('全部'),
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
                    onTap: () => sendCareerPromptAction(
                      sender: onSendPrompt,
                      application: app,
                      label: actions[i].label,
                      actionType: actions[i].actionType,
                      origin: 'projects',
                      detail: actions[i].reason,
                    ),
                  ),
                  if (i != actions.length - 1) const SizedBox(height: 8),
                ],
              ],
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

  const _ProjectRightRail({
    required this.provider,
    required this.summary,
    required this.detail,
    required this.onOpenResumes,
    required this.onOpenJDMatch,
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
        ),
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
    final readiness = detail?.readiness ?? summary?.readiness;
    return ProductSection(
      title: '当前判断',
      subtitle: '匹配度与推进建议',
      icon: Icons.psychology_alt_outlined,
      tone: careerScoreTone(readiness?.score),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                readiness?.score?.toString() ?? '-',
                style: AppTheme.ts(
                  fontSize: 34,
                  height: 1,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.primary,
                ),
              ),
              const SizedBox(width: 6),
              Text(
                '匹配度',
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                  color: ProductColors.textSecondary,
                ),
              ),
              const Spacer(),
              ProductTag(
                label: careerRecommendationLabel(
                  readiness?.recommendation,
                  readiness?.score,
                ),
                tone: careerScoreTone(readiness?.score),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            careerFirstNonEmpty(
              [readiness?.summary],
              fallback: '完成匹配后这里会展示 AI 判断。',
            ),
            style: AppTheme.ts(
              fontSize: 12.2,
              height: 1.48,
              color: ProductColors.textSecondary,
            ),
          ),
          if (readiness?.strengths.isNotEmpty == true) ...[
            const SizedBox(height: 12),
            _MiniBulletBlock(
              title: '优势',
              items: readiness!.strengths.take(2).toList(),
              tone: ProductTone.primary,
            ),
          ],
          if (readiness?.risks.isNotEmpty == true) ...[
            const SizedBox(height: 10),
            _MiniBulletBlock(
              title: '风险',
              items: readiness!.risks.take(2).toList(),
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
    const total = 6;
    final done = _stageIndex(app?.stage).clamp(0, total);
    return ProductSection(
      title: '求职进展',
      subtitle: '$done / $total 完成流程',
      icon: Icons.route_outlined,
      tone: ProductTone.primary,
      child: Column(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              minHeight: 7,
              value: done / total,
              color: ProductColors.primary,
              backgroundColor: ProductColors.primary.withValues(alpha: 0.12),
            ),
          ),
          const SizedBox(height: 12),
          _ProgressCompactRow(
            label: '简历投递',
            done: done >= 1,
            active: done == 1,
          ),
          _ProgressCompactRow(
            label: '简历筛选',
            done: done >= 2,
            active: done == 2,
          ),
          _ProgressCompactRow(
            label: '技术面试',
            done: done >= 3,
            active: done == 3,
          ),
          _ProgressCompactRow(
            label: '综合面试',
            done: done >= 4,
            active: done == 4,
          ),
          _ProgressCompactRow(
            label: 'Offer',
            done: done >= 5,
            active: done >= 5,
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

  const _ProjectLinkedAssetsCard({
    required this.provider,
    required this.detail,
    required this.onOpenResumes,
    required this.onOpenJDMatch,
  });

  @override
  Widget build(BuildContext context) {
    final assets = detail?.linkedAssets.take(4).toList() ??
        const <CareerLinkedAssetView>[];
    return ProductSection(
      title: '关联资产',
      subtitle: '简历、JD、笔记和报告',
      icon: Icons.folder_copy_outlined,
      tone: ProductTone.info,
      trailing: TextButton(
        onPressed: onOpenResumes,
        child: const Text('全部资产'),
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
                      onTap: null,
                    ),
                  ),
                  SizedBox(
                    width: width,
                    child: _AssetShortcut(
                      label: '资料',
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
              _AssetLine(asset: asset),
              if (asset != assets.last) const SizedBox(height: 9),
            ],
          ],
        ],
      ),
    );
  }
}

class _OverviewMetricData {
  final IconData icon;
  final String label;
  final String value;
  final ProductTone tone;

  const _OverviewMetricData({
    required this.icon,
    required this.label,
    required this.value,
    required this.tone,
  });
}

class _OverviewMetric extends StatelessWidget {
  final _OverviewMetricData metric;

  const _OverviewMetric({required this.metric});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: productToneStyle(metric.tone).soft.withValues(alpha: 0.45),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: productToneStyle(metric.tone).color.withValues(alpha: 0.1),
        ),
      ),
      child: Row(
        children: [
          ProductIconTile(icon: metric.icon, tone: metric.tone, size: 34),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  metric.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    color: ProductColors.textMuted,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  metric.value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.3,
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

class _TimelineStep {
  final String label;
  final String stage;
  final IconData icon;

  const _TimelineStep(this.label, this.stage, this.icon);
}

class _TimelineStepRow extends StatelessWidget {
  final _TimelineStep step;
  final bool active;
  final bool done;
  final String? subtitle;

  const _TimelineStepRow({
    required this.step,
    required this.active,
    required this.done,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    final tone = done || active ? ProductTone.primary : ProductTone.neutral;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        color: active
            ? ProductColors.primarySoft
            : done
                ? ProductColors.surfaceMint.withValues(alpha: 0.55)
                : Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: active
              ? ProductColors.primary.withValues(alpha: 0.18)
              : Colors.transparent,
        ),
      ),
      child: Row(
        children: [
          Icon(
            done
                ? Icons.check_circle_rounded
                : active
                    ? step.icon
                    : Icons.radio_button_unchecked_rounded,
            size: 18,
            color: productToneStyle(tone).color,
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  step.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.2,
                    fontWeight: FontWeight.w900,
                    color: done || active
                        ? ProductColors.text
                        : ProductColors.textMuted,
                  ),
                ),
                if (subtitle?.trim().isNotEmpty == true) ...[
                  const SizedBox(height: 2),
                  Text(
                    subtitle!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 10.5,
                      color: ProductColors.textMuted,
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (active) ProductTag(label: '进行中', tone: ProductTone.primary),
        ],
      ),
    );
  }
}

class _AgentStep {
  final String title;
  final String subtitle;
  final IconData icon;
  final bool done;
  final ProductTone tone;
  final String? actionLabel;
  final String? actionType;

  const _AgentStep({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.done,
    required this.tone,
    this.actionLabel,
    this.actionType,
  });
}

class _AgentStepCard extends StatelessWidget {
  final _AgentStep step;
  final CareerApplicationView? application;
  final CareerPromptSender? onSendPrompt;

  const _AgentStepCard({
    required this.step,
    required this.application,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(step.tone);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
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
              ProductIconTile(icon: step.icon, tone: step.tone, size: 38),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  step.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
              ),
              Icon(
                step.done ? Icons.check_circle_rounded : Icons.schedule_rounded,
                size: 16,
                color:
                    step.done ? ProductColors.primary : ProductColors.warning,
              ),
            ],
          ),
          const SizedBox(height: 10),
          ProductTag(
            label: step.done ? '已完成' : '可继续',
            tone: step.done ? ProductTone.primary : ProductTone.warning,
          ),
          const SizedBox(height: 10),
          Text(
            step.subtitle,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 11.3,
              height: 1.35,
              color: ProductColors.textSecondary,
            ),
          ),
          if (!step.done && step.actionLabel != null) ...[
            const SizedBox(height: 12),
            SizedBox(
              height: 32,
              width: double.infinity,
              child: OutlinedButton(
                onPressed: () => sendCareerPromptAction(
                  sender: onSendPrompt,
                  application: application,
                  label: step.actionLabel!,
                  actionType: step.actionType ?? 'project_action',
                  origin: 'projects',
                  detail: step.subtitle,
                ),
                style: OutlinedButton.styleFrom(
                  foregroundColor: style.color,
                  side: BorderSide(color: style.color.withValues(alpha: 0.22)),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
                child: Text(step.actionLabel!),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _RiskRow extends StatelessWidget {
  final String risk;
  final ProductTone tone;

  const _RiskRow({
    required this.risk,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
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
            color: productToneStyle(tone).color,
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

  const _ProjectActionItem({
    required this.label,
    required this.reason,
    required this.actionType,
    required this.tone,
    required this.actionLabel,
  });
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
  final bool done;
  final bool active;

  const _ProgressCompactRow({
    required this.label,
    required this.done,
    required this.active,
  });

  @override
  Widget build(BuildContext context) {
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
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: active ? FontWeight.w900 : FontWeight.w700,
                color: done || active
                    ? ProductColors.text
                    : ProductColors.textMuted,
              ),
            ),
          ),
          if (active) ProductTag(label: '进行中', tone: ProductTone.primary),
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
          icon: Icons.insert_drive_file_outlined,
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

class _CompanyAvatar extends StatelessWidget {
  final String label;

  const _CompanyAvatar({required this.label});

  @override
  Widget build(BuildContext context) {
    final text = label.trim().isEmpty ? '岗' : label.trim().characters.first;
    return Container(
      width: 64,
      height: 64,
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
            fontSize: 24,
            fontWeight: FontWeight.w900,
            color: ProductColors.primary,
          ),
        ),
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

List<_ProjectActionItem> _recommendedProjectActions(
  CareerApplicationView? app,
  CareerApplicationWorkbenchView? detail,
) {
  final actions = <_ProjectActionItem>[];
  for (final action in detail?.suggestedActions ?? const []) {
    if (!action.enabled) continue;
    actions.add(
      _ProjectActionItem(
        label: careerShortLabel(action.label, fallback: '推进求职动作'),
        reason: careerFirstNonEmpty(
          [action.reason, action.promptIntent, app?.summary],
          fallback: '基于当前项目状态继续推进。',
        ),
        actionType: action.actionType,
        tone: careerPriorityTone(action.priority),
        actionLabel: '去执行',
      ),
    );
  }
  final fallback = [
    _ProjectActionItem(
      label: '生成定制简历',
      reason: '围绕目标岗位改写项目经历、关键词和能力表达。',
      actionType: 'custom_resume',
      tone: ProductTone.primary,
      actionLabel: '去优化简历',
    ),
    _ProjectActionItem(
      label: '准备技术面试',
      reason: '根据 JD 风险点生成面试问题和参考答案。',
      actionType: 'interview_prep',
      tone: ProductTone.purple,
      actionLabel: '开始准备',
    ),
    _ProjectActionItem(
      label: '补充项目案例',
      reason: '把缺失证据转成可补齐的项目表述和学习任务。',
      actionType: 'learning_task',
      tone: ProductTone.info,
      actionLabel: '去补充',
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

bool _isStageActive(String? currentStage, String stepStage, int index) {
  final current = _stageIndex(currentStage);
  final step = math.min(index + 1, 5);
  if ((currentStage ?? '').trim() == 'interviewing' &&
      stepStage == 'interviewing') {
    return index == 2;
  }
  return current == step;
}

bool _isStageDone(String? currentStage, int index) {
  return _stageIndex(currentStage) > index + 1;
}

int _stageIndex(String? stage) {
  return switch ((stage ?? '').trim()) {
    'draft' => 0,
    'ready_to_apply' => 1,
    'applied' => 1,
    'screening' => 2,
    'interviewing' => 3,
    'offer' => 5,
    'rejected' => 6,
    _ => 0,
  };
}

String? _timelineSubtitle(List<CareerTimelineItemView> timeline, String label) {
  for (final item in timeline) {
    if (item.title.contains(label) || label.contains(item.title)) {
      return careerFormatDateTime(item.occurredAt);
    }
  }
  return null;
}
