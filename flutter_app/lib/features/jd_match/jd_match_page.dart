import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../../shared/widgets/product_components.dart';
import '../career_ui/career_ui_helpers.dart';
import '../career_workbench/career_workbench_provider.dart';

class JDMatchPage extends ConsumerStatefulWidget {
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenLearning;
  final CareerPromptSender? onSendPrompt;

  const JDMatchPage({
    super.key,
    required this.onOpenProjects,
    required this.onOpenResumes,
    required this.onOpenLearning,
    this.onSendPrompt,
  });

  @override
  ConsumerState<JDMatchPage> createState() => _JDMatchPageState();
}

class _JDMatchPageState extends ConsumerState<JDMatchPage> {
  _JDMatchTab _tab = _JDMatchTab.match;

  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      final provider = ref.read(careerWorkbenchProvider);
      await provider.ensureLoaded();
      await provider.loadAssetLibrary();
    });
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
      return _JDMatchError(
        error: provider.error!,
        onRetry: () => unawaited(provider.refresh()),
      );
    }

    final summary = provider.selectedApplicationSummary;
    final detail = provider.selectedApplicationDetail;
    final app = detail?.application ?? summary?.application;
    final jd = detail?.jdAnalysis ?? _findJD(provider, app?.jdAnalysisId);
    final report =
        detail?.jobFitReport ?? _findReport(provider, app?.jobFitReportId);
    final readiness = detail?.readiness ?? summary?.readiness;

    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= 1180;
        final main = ListView(
          padding: EdgeInsets.zero,
          children: [
            _JDMatchHeader(
              provider: provider,
              application: app,
              onRefresh: () => unawaited(_refresh(provider)),
              onOpenProjects: widget.onOpenProjects,
            ),
            const SizedBox(height: 14),
            if (provider.activeAction != null) ...[
              _JDActionBanner(run: provider.activeAction!),
              const SizedBox(height: 14),
            ],
            _JDHeroCard(
              application: app,
              jd: jd,
              report: report,
              readiness: readiness,
              onReanalyze: () => _sendAnalyzeAction(app),
            ),
            const SizedBox(height: 14),
            _JDTabBar(
              activeTab: _tab,
              onChanged: (value) => setState(() => _tab = value),
            ),
            const SizedBox(height: 14),
            _JDMainContent(
              tab: _tab,
              application: app,
              jd: jd,
              report: report,
              readiness: readiness,
              onOpenLearning: widget.onOpenLearning,
              onSendPrompt: widget.onSendPrompt,
            ),
            const SizedBox(height: 14),
            _JDLibrarySection(provider: provider),
          ],
        );
        final rail = _JDRail(
          provider: provider,
          application: app,
          jd: jd,
          report: report,
          readiness: readiness,
          onOpenProjects: widget.onOpenProjects,
          onOpenResumes: widget.onOpenResumes,
          onOpenLearning: widget.onOpenLearning,
          onSendPrompt: widget.onSendPrompt,
        );
        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              _JDMatchHeader(
                provider: provider,
                application: app,
                onRefresh: () => unawaited(_refresh(provider)),
                onOpenProjects: widget.onOpenProjects,
              ),
              const SizedBox(height: 14),
              if (provider.activeAction != null) ...[
                _JDActionBanner(run: provider.activeAction!),
                const SizedBox(height: 14),
              ],
              _JDHeroCard(
                application: app,
                jd: jd,
                report: report,
                readiness: readiness,
                onReanalyze: () => _sendAnalyzeAction(app),
              ),
              const SizedBox(height: 14),
              rail,
              const SizedBox(height: 14),
              _JDTabBar(
                activeTab: _tab,
                onChanged: (value) => setState(() => _tab = value),
              ),
              const SizedBox(height: 14),
              _JDMainContent(
                tab: _tab,
                application: app,
                jd: jd,
                report: report,
                readiness: readiness,
                onOpenLearning: widget.onOpenLearning,
                onSendPrompt: widget.onSendPrompt,
              ),
              const SizedBox(height: 14),
              _JDLibrarySection(provider: provider),
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

  Future<void> _refresh(CareerWorkbenchProvider provider) async {
    await provider.refresh();
    await provider.loadAssetLibrary(force: true);
  }

  void _sendAnalyzeAction(CareerApplicationView? app) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: '重新分析 JD 匹配',
      actionType: 'jd_match_analysis',
      origin: 'jd_match',
      detail: '复用当前项目已有简历画像、职业画像和 JD，刷新匹配评分、差距和面试准备建议。',
    );
  }
}

class _JDMatchHeader extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? application;
  final VoidCallback onRefresh;
  final VoidCallback onOpenProjects;

  const _JDMatchHeader({
    required this.provider,
    required this.application,
    required this.onRefresh,
    required this.onOpenProjects,
  });

  @override
  Widget build(BuildContext context) {
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
                    'JD 匹配',
                    style: AppTheme.ts(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: ProductColors.text,
                    ),
                  ),
                  ProductTag(
                    label: '智能分析',
                    tone: ProductTone.primary,
                    icon: Icons.analytics_outlined,
                  ),
                  if (provider.isRefreshing || provider.isLoadingAssetLibrary)
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
                '分析简历与岗位要求的匹配度，发现优势、差距、证据和面试准备建议。',
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
            children: [
              SizedBox(
                height: 38,
                child: OutlinedButton.icon(
                  onPressed: onOpenProjects,
                  icon: const Icon(Icons.business_center_outlined, size: 16),
                  label: Text(
                    careerShortLabel(application?.company, fallback: '求职项目'),
                  ),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: ProductColors.textSecondary,
                    side: const BorderSide(color: ProductColors.border),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
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

class _JDActionBanner extends StatelessWidget {
  final CareerWorkbenchActionRun run;

  const _JDActionBanner({required this.run});

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
            ? 'Agent 正在刷新匹配结论，完成后会更新当前项目。'
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

class _JDHeroCard extends StatelessWidget {
  final CareerApplicationView? application;
  final JDAnalysisView? jd;
  final JobFitReportView? report;
  final CareerReadinessView? readiness;
  final VoidCallback onReanalyze;

  const _JDHeroCard({
    required this.application,
    required this.jd,
    required this.report,
    required this.readiness,
    required this.onReanalyze,
  });

  @override
  Widget build(BuildContext context) {
    final score = report?.overallScore ?? readiness?.score;
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(24, 22, 24, 22),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final identity = Row(
            children: [
              _CompanyLogo(label: application?.company ?? jd?.company ?? ''),
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
                          careerShortLabel(
                            application?.company ?? jd?.company,
                            fallback: '目标公司',
                          ),
                          style: AppTheme.ts(
                            fontSize: 14,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.text,
                          ),
                        ),
                        ProductTag(
                          label: careerRecommendationLabel(
                            report?.recommendation ?? readiness?.recommendation,
                            score,
                          ),
                          tone: careerScoreTone(score),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      careerShortLabel(
                        application?.position ?? jd?.position,
                        fallback: '待分析岗位',
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: compact ? 18 : 21,
                        height: 1.2,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 9),
                    Wrap(
                      spacing: 9,
                      runSpacing: 8,
                      children: [
                        ProductTag(
                          label: careerShortLabel(
                            application?.location,
                            fallback: '地点待补充',
                          ),
                          icon: Icons.location_on_outlined,
                          tone: ProductTone.neutral,
                        ),
                        ProductTag(
                          label: careerShortLabel(jd?.seniority,
                              fallback: '经验待补充'),
                          icon: Icons.work_outline_rounded,
                          tone: ProductTone.info,
                        ),
                        ProductTag(
                          label:
                              '更新 ${careerFormatDateTime(report?.meta.updatedAt ?? jd?.meta.updatedAt ?? application?.meta.updatedAt)}',
                          icon: Icons.update_rounded,
                          tone: ProductTone.neutral,
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
              ProductScoreRing(score: score, size: 100),
              const SizedBox(height: 8),
              Text(
                '较上次 +6 ↑',
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.primary,
                ),
              ),
            ],
          );
          final summary = Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
            decoration: ProductSurface.softCard(tone: ProductTone.primary),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '当前判断',
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  careerFirstNonEmpty(
                    [
                      readiness?.summary,
                      report?.recommendation,
                      '完成 JD 分析后，这里会展示匹配结论和建议。',
                    ],
                  ),
                  maxLines: compact ? 5 : 3,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.2,
                    height: 1.48,
                    fontWeight: FontWeight.w700,
                    color: ProductColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ElevatedButton.icon(
                      onPressed: onReanalyze,
                      icon: const Icon(Icons.refresh_rounded, size: 16),
                      label: const Text('重新分析'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: ProductColors.primary,
                        foregroundColor: Colors.white,
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(11),
                        ),
                      ),
                    ),
                    OutlinedButton.icon(
                      onPressed: onReanalyze,
                      icon: const Icon(Icons.auto_fix_high_outlined, size: 16),
                      label: const Text('优化匹配'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: ProductColors.primary,
                        side: const BorderSide(color: ProductColors.border),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(11),
                        ),
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
                identity,
                const SizedBox(height: 18),
                Center(child: scoreBlock),
                const SizedBox(height: 18),
                summary,
              ],
            );
          }
          return Row(
            children: [
              Expanded(flex: 5, child: identity),
              const SizedBox(width: 22),
              scoreBlock,
              const SizedBox(width: 22),
              Expanded(flex: 5, child: summary),
            ],
          );
        },
      ),
    );
  }
}

class _JDTabBar extends StatelessWidget {
  final _JDMatchTab activeTab;
  final ValueChanged<_JDMatchTab> onChanged;

  const _JDTabBar({
    required this.activeTab,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            for (final tab in _JDMatchTab.values) ...[
              _JDTabButton(
                tab: tab,
                selected: activeTab == tab,
                onTap: () => onChanged(tab),
              ),
              if (tab != _JDMatchTab.values.last) const SizedBox(width: 8),
            ],
          ],
        ),
      ),
    );
  }
}

class _JDTabButton extends StatelessWidget {
  final _JDMatchTab tab;
  final bool selected;
  final VoidCallback onTap;

  const _JDTabButton({
    required this.tab,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color =
        selected ? ProductColors.primary : ProductColors.textSecondary;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          height: 38,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: selected ? ProductColors.primarySoft : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: selected
                  ? ProductColors.primary.withValues(alpha: 0.16)
                  : ProductColors.border,
            ),
          ),
          child: Row(
            children: [
              Icon(_tabIcon(tab), size: 16, color: color),
              const SizedBox(width: 7),
              Text(
                _tabLabel(tab),
                style: AppTheme.ts(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w900,
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

class _JDMainContent extends StatelessWidget {
  final _JDMatchTab tab;
  final CareerApplicationView? application;
  final JDAnalysisView? jd;
  final JobFitReportView? report;
  final CareerReadinessView? readiness;
  final VoidCallback onOpenLearning;
  final CareerPromptSender? onSendPrompt;

  const _JDMainContent({
    required this.tab,
    required this.application,
    required this.jd,
    required this.report,
    required this.readiness,
    required this.onOpenLearning,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    return switch (tab) {
      _JDMatchTab.match => _MatchAnalysisView(
          application: application,
          jd: jd,
          report: report,
          readiness: readiness,
        ),
      _JDMatchTab.gaps => _GapAnalysisView(
          application: application,
          report: report,
          readiness: readiness,
          onOpenLearning: onOpenLearning,
          onSendPrompt: onSendPrompt,
        ),
      _JDMatchTab.evidence => _EvidenceView(report: report, jd: jd),
      _JDMatchTab.interview => _InterviewPrepView(
          application: application,
          report: report,
          jd: jd,
          onSendPrompt: onSendPrompt,
        ),
    };
  }
}

class _MatchAnalysisView extends StatelessWidget {
  final CareerApplicationView? application;
  final JDAnalysisView? jd;
  final JobFitReportView? report;
  final CareerReadinessView? readiness;

  const _MatchAnalysisView({
    required this.application,
    required this.jd,
    required this.report,
    required this.readiness,
  });

  @override
  Widget build(BuildContext context) {
    final score = report?.overallScore ?? readiness?.score;
    final cards = _scoreCards(report, readiness);
    return ProductSection(
      title: '匹配总览',
      subtitle: '核心维度评分和岗位要求覆盖情况',
      icon: Icons.speed_rounded,
      tone: careerScoreTone(score),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final scorePanel = Container(
            padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
            decoration: ProductSurface.softCard(
              tone: careerScoreTone(score),
              radius: 16,
            ),
            child: Column(
              children: [
                ProductScoreRing(score: score, size: compact ? 92 : 118),
                const SizedBox(height: 12),
                Text(
                  careerRecommendationLabel(
                    report?.recommendation ?? readiness?.recommendation,
                    score,
                  ),
                  style: AppTheme.ts(
                    fontSize: 13,
                    fontWeight: FontWeight.w900,
                    color: productToneStyle(careerScoreTone(score)).color,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  careerFirstNonEmpty(
                    [readiness?.summary, application?.summary],
                    fallback: '暂无匹配结论。',
                  ),
                  textAlign: TextAlign.center,
                  maxLines: 4,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    height: 1.42,
                    color: ProductColors.textSecondary,
                  ),
                ),
              ],
            ),
          );
          final scoreGrid = LayoutBuilder(
            builder: (context, inner) {
              final columns = inner.maxWidth >= 760
                  ? 3
                  : inner.maxWidth >= 520
                      ? 2
                      : 1;
              const spacing = 10.0;
              final width =
                  (inner.maxWidth - spacing * (columns - 1)) / columns;
              return Wrap(
                spacing: spacing,
                runSpacing: spacing,
                children: [
                  for (final card in cards)
                    SizedBox(
                        width: width, child: _ScoreDimensionCard(card: card)),
                ],
              );
            },
          );
          if (compact) {
            return Column(
              children: [
                scorePanel,
                const SizedBox(height: 14),
                scoreGrid,
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(width: 220, child: scorePanel),
              const SizedBox(width: 16),
              Expanded(child: scoreGrid),
            ],
          );
        },
      ),
    );
  }
}

class _GapAnalysisView extends StatelessWidget {
  final CareerApplicationView? application;
  final JobFitReportView? report;
  final CareerReadinessView? readiness;
  final VoidCallback onOpenLearning;
  final CareerPromptSender? onSendPrompt;

  const _GapAnalysisView({
    required this.application,
    required this.report,
    required this.readiness,
    required this.onOpenLearning,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final gaps = [
      ..._dynamicSnippets(report?.gaps ?? const [], limit: 5),
      ...readiness?.risks ?? const <String>[],
      ...readiness?.missingMaterials ?? const <String>[],
    ].where((item) => item.trim().isNotEmpty).take(6).toList();
    final directions = _dynamicSnippets(
      report?.resumeOptimizationDirection ?? const [],
      limit: 5,
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 840;
        final gapCard = ProductSection(
          title: '差距分析',
          subtitle: '与岗位要求对比后需要提升的部分',
          icon: Icons.report_problem_outlined,
          tone: ProductTone.warning,
          child: gaps.isEmpty
              ? const _EmptyJDText(text: '暂无明确差距。完成匹配报告后会展示短板。')
              : Column(
                  children: [
                    for (var i = 0; i < gaps.length; i++) ...[
                      _InsightRow(
                        title: i == 0 ? '高优先级' : '待补充',
                        body: gaps[i],
                        tone: i == 0 ? ProductTone.warning : ProductTone.info,
                      ),
                      if (i != gaps.length - 1) const SizedBox(height: 8),
                    ],
                  ],
                ),
        );
        final actionCard = ProductSection(
          title: '优化方向',
          subtitle: '把短板转为简历和准备动作',
          icon: Icons.auto_fix_high_outlined,
          tone: ProductTone.primary,
          trailing: TextButton(
            onPressed: onOpenLearning,
            child: const Text('学习计划'),
          ),
          child: Column(
            children: [
              if (directions.isEmpty)
                const _EmptyJDText(text: '暂无简历优化建议。')
              else
                for (var i = 0; i < directions.length; i++) ...[
                  ProductActionTile(
                    title: i == 0 ? '优化简历亮点' : '补充证据表达',
                    subtitle: directions[i],
                    icon: Icons.edit_note_outlined,
                    tone: i == 0 ? ProductTone.primary : ProductTone.info,
                    actionLabel: '去优化',
                    onTap: () => sendCareerPromptAction(
                      sender: onSendPrompt,
                      application: application,
                      label: '优化 JD 匹配差距',
                      actionType: 'resume_optimize',
                      origin: 'jd_match',
                      detail: directions[i],
                    ),
                  ),
                  if (i != directions.length - 1) const SizedBox(height: 8),
                ],
            ],
          ),
        );
        if (compact) {
          return Column(
              children: [gapCard, const SizedBox(height: 14), actionCard]);
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: gapCard),
            const SizedBox(width: 14),
            Expanded(child: actionCard),
          ],
        );
      },
    );
  }
}

class _EvidenceView extends StatelessWidget {
  final JobFitReportView? report;
  final JDAnalysisView? jd;

  const _EvidenceView({
    required this.report,
    required this.jd,
  });

  @override
  Widget build(BuildContext context) {
    final evidence =
        _dynamicSnippets(report?.matchedEvidence ?? const [], limit: 8);
    final required = jd?.requiredSkills ?? const <String>[];
    final preferred = jd?.preferredSkills ?? const <String>[];
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 840;
        final evidenceCard = ProductSection(
          title: '证据依据',
          subtitle: '来自简历和项目经历的匹配证据',
          icon: Icons.verified_outlined,
          tone: ProductTone.info,
          child: evidence.isEmpty
              ? const _EmptyJDText(text: '暂无匹配证据。')
              : Column(
                  children: [
                    for (var i = 0; i < evidence.length; i++) ...[
                      _EvidenceRow(index: i + 1, text: evidence[i]),
                      if (i != evidence.length - 1) const SizedBox(height: 8),
                    ],
                  ],
                ),
        );
        final requirementCard = ProductSection(
          title: '岗位要求',
          subtitle: '硬性技能、加分项和关键词',
          icon: Icons.article_outlined,
          tone: ProductTone.primary,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _TagCloudBlock(
                title: '硬性要求',
                items: required,
                tone: ProductTone.primary,
              ),
              const SizedBox(height: 12),
              _TagCloudBlock(
                title: '加分项',
                items: preferred,
                tone: ProductTone.info,
              ),
              const SizedBox(height: 12),
              _TagCloudBlock(
                title: '关键词',
                items: jd?.keywords ?? const [],
                tone: ProductTone.purple,
              ),
            ],
          ),
        );
        if (compact) {
          return Column(
            children: [
              evidenceCard,
              const SizedBox(height: 14),
              requirementCard,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: evidenceCard),
            const SizedBox(width: 14),
            Expanded(child: requirementCard),
          ],
        );
      },
    );
  }
}

class _InterviewPrepView extends StatelessWidget {
  final CareerApplicationView? application;
  final JobFitReportView? report;
  final JDAnalysisView? jd;
  final CareerPromptSender? onSendPrompt;

  const _InterviewPrepView({
    required this.application,
    required this.report,
    required this.jd,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final focus = [
      ..._dynamicSnippets(report?.interviewPreparationFocus ?? const [],
          limit: 6),
      ...jd?.interviewFocus ?? const <String>[],
    ].where((item) => item.trim().isNotEmpty).take(6).toList();
    return ProductSection(
      title: '面试准备',
      subtitle: '把匹配差距转成面试题和回答策略',
      icon: Icons.forum_outlined,
      tone: ProductTone.purple,
      trailing: TextButton(
        onPressed: () => sendCareerPromptAction(
          sender: onSendPrompt,
          application: application,
          label: '生成面试准备题',
          actionType: 'interview_prep',
          origin: 'jd_match',
          detail: '围绕当前 JD 匹配报告的短板和关注点生成面试题、回答要点和追问。',
        ),
        child: const Text('生成题库'),
      ),
      child: focus.isEmpty
          ? const _EmptyJDText(text: '暂无面试准备重点。')
          : LayoutBuilder(
              builder: (context, constraints) {
                final columns = constraints.maxWidth >= 900
                    ? 3
                    : constraints.maxWidth >= 560
                        ? 2
                        : 1;
                const spacing = 10.0;
                final width =
                    (constraints.maxWidth - spacing * (columns - 1)) / columns;
                return Wrap(
                  spacing: spacing,
                  runSpacing: spacing,
                  children: [
                    for (var i = 0; i < focus.length; i++)
                      SizedBox(
                        width: width,
                        child: _InterviewQuestionCard(
                          title: _interviewTitle(i),
                          body: focus[i],
                          difficulty: i == 0
                              ? '高'
                              : i == 1
                                  ? '中'
                                  : '中等',
                        ),
                      ),
                  ],
                );
              },
            ),
    );
  }
}

class _JDRail extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? application;
  final JDAnalysisView? jd;
  final JobFitReportView? report;
  final CareerReadinessView? readiness;
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenLearning;
  final CareerPromptSender? onSendPrompt;

  const _JDRail({
    required this.provider,
    required this.application,
    required this.jd,
    required this.report,
    required this.readiness,
    required this.onOpenProjects,
    required this.onOpenResumes,
    required this.onOpenLearning,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _CurrentDecisionCard(readiness: readiness, report: report),
        const SizedBox(height: 14),
        _JDNextStepCard(
          application: application,
          report: report,
          readiness: readiness,
          onOpenLearning: onOpenLearning,
          onSendPrompt: onSendPrompt,
        ),
        const SizedBox(height: 14),
        _JDRelatedAssetsCard(
          provider: provider,
          application: application,
          jd: jd,
          report: report,
          onOpenProjects: onOpenProjects,
          onOpenResumes: onOpenResumes,
        ),
      ],
    );
  }
}

class _CurrentDecisionCard extends StatelessWidget {
  final CareerReadinessView? readiness;
  final JobFitReportView? report;

  const _CurrentDecisionCard({
    required this.readiness,
    required this.report,
  });

  @override
  Widget build(BuildContext context) {
    final score = report?.overallScore ?? readiness?.score;
    final strengths = readiness?.strengths.take(2).toList() ?? const <String>[];
    final risks = readiness?.risks.take(2).toList() ?? const <String>[];
    return ProductSection(
      title: '当前判断',
      subtitle: '更新于 ${careerFormatDateTime(report?.meta.updatedAt)}',
      icon: Icons.fact_check_outlined,
      tone: careerScoreTone(score),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                score?.toString() ?? '-',
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
                  report?.recommendation ?? readiness?.recommendation,
                  score,
                ),
                tone: careerScoreTone(score),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            careerFirstNonEmpty(
              [readiness?.summary],
              fallback: '暂无当前判断。',
            ),
            style: AppTheme.ts(
              fontSize: 12.2,
              height: 1.48,
              color: ProductColors.textSecondary,
            ),
          ),
          if (strengths.isNotEmpty) ...[
            const SizedBox(height: 12),
            _MiniListBlock(
                title: '优势', items: strengths, tone: ProductTone.primary),
          ],
          if (risks.isNotEmpty) ...[
            const SizedBox(height: 10),
            _MiniListBlock(
                title: '风险', items: risks, tone: ProductTone.warning),
          ],
        ],
      ),
    );
  }
}

class _JDNextStepCard extends StatelessWidget {
  final CareerApplicationView? application;
  final JobFitReportView? report;
  final CareerReadinessView? readiness;
  final VoidCallback onOpenLearning;
  final CareerPromptSender? onSendPrompt;

  const _JDNextStepCard({
    required this.application,
    required this.report,
    required this.readiness,
    required this.onOpenLearning,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final actions = _jdActions(report, readiness).take(3).toList();
    return ProductSection(
      title: '推荐下一步',
      subtitle: '按匹配收益排序',
      icon: Icons.auto_fix_high_outlined,
      tone: ProductTone.primary,
      trailing: TextButton(
        onPressed: onOpenLearning,
        child: const Text('全部'),
      ),
      child: Column(
        children: [
          for (var i = 0; i < actions.length; i++) ...[
            ProductActionTile(
              title: actions[i].title,
              subtitle: actions[i].subtitle,
              icon: actions[i].icon,
              tone: actions[i].tone,
              badge: '${i + 1}',
              actionLabel: '执行',
              onTap: () => sendCareerPromptAction(
                sender: onSendPrompt,
                application: application,
                label: actions[i].title,
                actionType: actions[i].actionType,
                origin: 'jd_match',
                detail: actions[i].subtitle,
              ),
            ),
            if (i != actions.length - 1) const SizedBox(height: 8),
          ],
        ],
      ),
    );
  }
}

class _JDRelatedAssetsCard extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? application;
  final JDAnalysisView? jd;
  final JobFitReportView? report;
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenResumes;

  const _JDRelatedAssetsCard({
    required this.provider,
    required this.application,
    required this.jd,
    required this.report,
    required this.onOpenProjects,
    required this.onOpenResumes,
  });

  @override
  Widget build(BuildContext context) {
    final resumeVersions = provider.resumeVersions
        .where((item) => item.targetJdAnalysisId == jd?.jdAnalysisId)
        .take(2)
        .toList();
    return ProductSection(
      title: '相关资料',
      subtitle: '简历、报告和岗位记录',
      icon: Icons.folder_copy_outlined,
      tone: ProductTone.info,
      child: Column(
        children: [
          _RelatedAssetRow(
            title: careerShortLabel(jd?.displayTitle, fallback: 'JD 分析待生成'),
            subtitle: jd == null
                ? '上传 JD 或从项目触发分析'
                : '更新于 ${careerFormatDateTime(jd!.meta.updatedAt)}',
            icon: Icons.article_outlined,
            tone: ProductTone.info,
            onTap: null,
          ),
          const SizedBox(height: 9),
          _RelatedAssetRow(
            title:
                report == null ? '匹配报告待生成' : '匹配报告 ${report!.overallScore} 分',
            subtitle: report == null
                ? '分析后会生成匹配报告'
                : '更新于 ${careerFormatDateTime(report!.meta.updatedAt)}',
            icon: Icons.fact_check_outlined,
            tone: ProductTone.primary,
            onTap: null,
          ),
          const SizedBox(height: 9),
          _RelatedAssetRow(
            title:
                careerShortLabel(application?.displayTitle, fallback: '求职项目'),
            subtitle: '回到岗位工作台查看推进状态',
            icon: Icons.business_center_outlined,
            tone: ProductTone.warning,
            onTap: onOpenProjects,
          ),
          if (resumeVersions.isNotEmpty) ...[
            const SizedBox(height: 9),
            for (final version in resumeVersions) ...[
              _RelatedAssetRow(
                title: version.title,
                subtitle: '定制简历版本',
                icon: Icons.description_outlined,
                tone: ProductTone.purple,
                onTap: onOpenResumes,
              ),
              if (version != resumeVersions.last) const SizedBox(height: 9),
            ],
          ],
        ],
      ),
    );
  }
}

class _JDLibrarySection extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _JDLibrarySection({required this.provider});

  @override
  Widget build(BuildContext context) {
    final records = _libraryRecords(provider).take(6).toList();
    return ProductSection(
      title: 'JD 与匹配记录',
      subtitle: '${provider.jobMatchLibraryCount} 项记录',
      icon: Icons.inventory_2_outlined,
      tone: ProductTone.info,
      child: provider.isLoadingAssetLibrary && records.isEmpty
          ? const SizedBox(
              height: 90,
              child: Center(
                child: CircularProgressIndicator(color: ProductColors.primary),
              ),
            )
          : records.isEmpty
              ? const _EmptyJDText(text: '还没有 JD 分析或匹配报告。')
              : LayoutBuilder(
                  builder: (context, constraints) {
                    final columns = constraints.maxWidth >= 980
                        ? 3
                        : constraints.maxWidth >= 620
                            ? 2
                            : 1;
                    const spacing = 10.0;
                    final width =
                        (constraints.maxWidth - spacing * (columns - 1)) /
                            columns;
                    return Wrap(
                      spacing: spacing,
                      runSpacing: spacing,
                      children: [
                        for (final record in records)
                          SizedBox(
                              width: width,
                              child: _LibraryRecordCard(record: record)),
                      ],
                    );
                  },
                ),
    );
  }
}

class _ScoreDimensionCard extends StatelessWidget {
  final _ScoreDimension card;

  const _ScoreDimensionCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final tone = careerScoreTone(card.score);
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          ProductIconTile(icon: card.icon, tone: tone, size: 42),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  card.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  '${card.score}%',
                  style: AppTheme.ts(
                    fontSize: 21,
                    height: 1,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  card.note,
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
        ],
      ),
    );
  }
}

class _InsightRow extends StatelessWidget {
  final String title;
  final String body;
  final ProductTone tone;

  const _InsightRow({
    required this.title,
    required this.body,
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
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: AppTheme.ts(
                    fontSize: 11,
                    fontWeight: FontWeight.w900,
                    color: productToneStyle(tone).color,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  body,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12,
                    height: 1.4,
                    fontWeight: FontWeight.w700,
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

class _EvidenceRow extends StatelessWidget {
  final int index;
  final String text;

  const _EvidenceRow({
    required this.index,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration: BoxDecoration(
        color: ProductColors.infoSoft.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ProductColors.info.withValues(alpha: 0.1)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 22,
            height: 22,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              color: ProductColors.info,
            ),
            child: Center(
              child: Text(
                index.toString(),
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w900,
                  color: Colors.white,
                ),
              ),
            ),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Text(
              text,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 12,
                height: 1.42,
                color: ProductColors.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TagCloudBlock extends StatelessWidget {
  final String title;
  final List<String> items;
  final ProductTone tone;

  const _TagCloudBlock({
    required this.title,
    required this.items,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: AppTheme.ts(
            fontSize: 11.5,
            fontWeight: FontWeight.w900,
            color: ProductColors.text,
          ),
        ),
        const SizedBox(height: 8),
        if (items.isEmpty)
          const _EmptyJDText(text: '暂无记录。')
        else
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              for (final item in items.take(12))
                ProductTag(label: item, tone: tone),
            ],
          ),
      ],
    );
  }
}

class _InterviewQuestionCard extends StatelessWidget {
  final String title;
  final String body;
  final String difficulty;

  const _InterviewQuestionCard({
    required this.title,
    required this.body,
    required this.difficulty,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(13, 13, 13, 13),
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
              ProductTag(label: difficulty, tone: ProductTone.purple),
              const Spacer(),
              const Icon(
                Icons.help_outline_rounded,
                size: 16,
                color: ProductColors.purple,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            title,
            style: AppTheme.ts(
              fontSize: 12.5,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            body,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 11.5,
              height: 1.42,
              color: ProductColors.textSecondary,
            ),
          ),
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

class _RelatedAssetRow extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final ProductTone tone;
  final VoidCallback? onTap;

  const _RelatedAssetRow({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.tone,
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
            color: productToneStyle(tone).soft.withValues(alpha: 0.48),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: productToneStyle(tone).color.withValues(alpha: 0.1),
            ),
          ),
          child: Row(
            children: [
              ProductIconTile(icon: icon, tone: tone, size: 34),
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
                        fontSize: 11.6,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
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
              if (onTap != null) ...[
                const SizedBox(width: 8),
                const Icon(
                  Icons.chevron_right_rounded,
                  size: 18,
                  color: ProductColors.textMuted,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _LibraryRecordCard extends StatelessWidget {
  final _LibraryRecord record;

  const _LibraryRecordCard({required this.record});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(13, 13, 13, 13),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          ProductIconTile(icon: record.icon, tone: record.tone, size: 38),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  record.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  record.subtitle,
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
          const SizedBox(width: 8),
          ProductTag(label: record.kind, tone: record.tone),
        ],
      ),
    );
  }
}

class _CompanyLogo extends StatelessWidget {
  final String label;

  const _CompanyLogo({required this.label});

  @override
  Widget build(BuildContext context) {
    final text = label.trim().isEmpty ? 'JD' : label.trim().characters.first;
    return Container(
      width: 62,
      height: 62,
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
            fontSize: 23,
            fontWeight: FontWeight.w900,
            color: ProductColors.primary,
          ),
        ),
      ),
    );
  }
}

class _EmptyJDText extends StatelessWidget {
  final String text;

  const _EmptyJDText({required this.text});

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: AppTheme.ts(
        fontSize: 12.3,
        height: 1.5,
        color: ProductColors.textMuted,
      ),
    );
  }
}

class _JDMatchError extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const _JDMatchError({
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
              'JD 匹配加载失败',
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

enum _JDMatchTab { match, gaps, evidence, interview }

class _ScoreDimension {
  final String label;
  final int score;
  final IconData icon;
  final String note;

  const _ScoreDimension({
    required this.label,
    required this.score,
    required this.icon,
    required this.note,
  });
}

class _JDAction {
  final String title;
  final String subtitle;
  final String actionType;
  final IconData icon;
  final ProductTone tone;

  const _JDAction({
    required this.title,
    required this.subtitle,
    required this.actionType,
    required this.icon,
    required this.tone,
  });
}

class _LibraryRecord {
  final String title;
  final String subtitle;
  final String kind;
  final IconData icon;
  final ProductTone tone;
  final DateTime updatedAt;

  const _LibraryRecord({
    required this.title,
    required this.subtitle,
    required this.kind,
    required this.icon,
    required this.tone,
    required this.updatedAt,
  });
}

List<_ScoreDimension> _scoreCards(
  JobFitReportView? report,
  CareerReadinessView? readiness,
) {
  final entries = report?.scoreBreakdown.entries.toList() ?? const [];
  final cards = [
    for (final entry in entries)
      _ScoreDimension(
        label: entry.key,
        score: entry.value.clamp(0, 100),
        icon: _scoreIcon(entry.key),
        note: _scoreNote(entry.value),
      ),
  ];
  final fallback = [
    _ScoreDimension(
      label: '技术栈匹配',
      score: math.min(readiness?.score ?? 0, 100),
      icon: Icons.construction_outlined,
      note: '核心技能覆盖情况',
    ),
    _ScoreDimension(
      label: '项目经历匹配',
      score: math.max((readiness?.score ?? 70) - 6, 0),
      icon: Icons.work_outline_rounded,
      note: '项目证据与岗位职责',
    ),
    _ScoreDimension(
      label: '面试准备度',
      score: math.max((readiness?.score ?? 68) - 10, 0),
      icon: Icons.forum_outlined,
      note: '知识深度与表达准备',
    ),
  ];
  for (final item in fallback) {
    if (cards.length >= 6) break;
    if (!cards.any((card) => card.label == item.label)) {
      cards.add(item);
    }
  }
  return cards.take(6).toList();
}

List<_JDAction> _jdActions(
  JobFitReportView? report,
  CareerReadinessView? readiness,
) {
  final directions = _dynamicSnippets(
    report?.resumeOptimizationDirection ?? const [],
    limit: 2,
  );
  final focus = _dynamicSnippets(
    report?.interviewPreparationFocus ?? const [],
    limit: 1,
  );
  return [
    _JDAction(
      title: '补充多 Agent 协作项目经验',
      subtitle: directions.isEmpty ? '把岗位短板转成简历项目证据。' : directions.first,
      actionType: 'resume_optimize',
      icon: Icons.edit_note_outlined,
      tone: ProductTone.warning,
    ),
    _JDAction(
      title: '强化问题检索优化与评估方法',
      subtitle: directions.length > 1 ? directions[1] : '完善 RAG、检索质量和评估指标表达。',
      actionType: 'learning_task',
      icon: Icons.school_outlined,
      tone: ProductTone.primary,
    ),
    _JDAction(
      title: '完善可观测性与稳定性实践',
      subtitle: focus.isEmpty
          ? (readiness?.risks.isNotEmpty == true
              ? readiness!.risks.first
              : '准备系统设计、稳定性和排障案例。')
          : focus.first,
      actionType: 'interview_prep',
      icon: Icons.forum_outlined,
      tone: ProductTone.info,
    ),
  ];
}

List<_LibraryRecord> _libraryRecords(CareerWorkbenchProvider provider) {
  final records = <_LibraryRecord>[
    for (final jd in provider.jdAnalyses)
      _LibraryRecord(
        title: jd.displayTitle,
        subtitle:
            '${jd.requiredSkills.length} 项硬性要求 · ${careerFormatDateTime(jd.meta.updatedAt)}',
        kind: 'JD',
        icon: Icons.article_outlined,
        tone: ProductTone.info,
        updatedAt: jd.meta.updatedAt,
      ),
    for (final report in provider.jobFitReports)
      _LibraryRecord(
        title: '匹配报告 ${report.overallScore} 分',
        subtitle:
            '${report.scoreBreakdown.length} 个评分维度 · ${careerFormatDateTime(report.meta.updatedAt)}',
        kind: '报告',
        icon: Icons.fact_check_outlined,
        tone: careerScoreTone(report.overallScore),
        updatedAt: report.meta.updatedAt,
      ),
  ];
  records.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  return records;
}

JDAnalysisView? _findJD(CareerWorkbenchProvider provider, String? id) {
  final normalized = id?.trim() ?? '';
  if (normalized.isEmpty) return null;
  for (final jd in provider.jdAnalyses) {
    if (jd.jdAnalysisId == normalized) return jd;
  }
  return null;
}

JobFitReportView? _findReport(CareerWorkbenchProvider provider, String? id) {
  final normalized = id?.trim() ?? '';
  if (normalized.isEmpty) return null;
  for (final report in provider.jobFitReports) {
    if (report.jobFitReportId == normalized) return report;
  }
  return null;
}

List<String> _dynamicSnippets(List<dynamic> values, {int limit = 6}) {
  final snippets = <String>[];
  for (final value in values) {
    final text = _dynamicToText(value);
    if (text.trim().isNotEmpty) snippets.add(text.trim());
    if (snippets.length >= limit) break;
  }
  return snippets;
}

String _dynamicToText(dynamic value) {
  if (value == null) return '';
  if (value is String) return value;
  if (value is num || value is bool) return value.toString();
  if (value is Map) {
    final preferred = [
      'summary',
      'description',
      'evidence',
      'gap',
      'title',
      'text',
      'reason',
      'suggestion',
      'action',
    ];
    for (final key in preferred) {
      final item = value[key];
      if (item is String && item.trim().isNotEmpty) return item;
    }
    return jsonEncode(value);
  }
  if (value is Iterable) {
    return value.map(_dynamicToText).where((item) => item.isNotEmpty).join('；');
  }
  return value.toString();
}

String _tabLabel(_JDMatchTab tab) {
  return switch (tab) {
    _JDMatchTab.match => '匹配分析',
    _JDMatchTab.gaps => '差距分析',
    _JDMatchTab.evidence => '证据依据',
    _JDMatchTab.interview => '面试准备',
  };
}

IconData _tabIcon(_JDMatchTab tab) {
  return switch (tab) {
    _JDMatchTab.match => Icons.speed_rounded,
    _JDMatchTab.gaps => Icons.report_problem_outlined,
    _JDMatchTab.evidence => Icons.verified_outlined,
    _JDMatchTab.interview => Icons.forum_outlined,
  };
}

IconData _scoreIcon(String label) {
  final value = label.toLowerCase();
  if (value.contains('技术') || value.contains('skill')) {
    return Icons.construction_outlined;
  }
  if (value.contains('项目') || value.contains('experience')) {
    return Icons.work_outline_rounded;
  }
  if (value.contains('agent') || value.contains('llm')) {
    return Icons.auto_awesome_outlined;
  }
  if (value.contains('工程') ||
      value.contains('ci') ||
      value.contains('devops')) {
    return Icons.settings_suggest_outlined;
  }
  if (value.contains('面试')) return Icons.forum_outlined;
  if (value.contains('风险')) return Icons.report_problem_outlined;
  return Icons.analytics_outlined;
}

String _scoreNote(int score) {
  if (score >= 85) return '优势明显';
  if (score >= 75) return '较为匹配';
  if (score >= 60) return '仍有提升';
  return '需要补齐';
}

String _interviewTitle(int index) {
  return switch (index % 4) {
    0 => '如何设计一个可扩展的 Agent 协作系统？',
    1 => 'RAG 检索效果不理想时，你会如何优化？',
    2 => '如何处理 Agent 之间的通信与冲突？',
    _ => '如何保障系统稳定性和可观测性？',
  };
}
