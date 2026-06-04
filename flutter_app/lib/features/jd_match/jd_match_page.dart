import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

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
  final VoidCallback onOpenNotes;
  final CareerPromptSender? onSendPrompt;

  const JDMatchPage({
    super.key,
    required this.onOpenProjects,
    required this.onOpenResumes,
    required this.onOpenLearning,
    required this.onOpenNotes,
    this.onSendPrompt,
  });

  @override
  ConsumerState<JDMatchPage> createState() => _JDMatchPageState();
}

class _JDMatchPageState extends ConsumerState<JDMatchPage> {
  _JDMatchTab _tab = _JDMatchTab.match;
  _EvidenceDraftSeed? _activeEvidenceDraft;
  bool _isSavingEvidence = false;

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
        final desktop = constraints.maxWidth >= ProductBreakpoints.contentRail;
        final usePageEvidencePanel = desktop && _activeEvidenceDraft != null;
        final main = ListView(
          padding: EdgeInsets.zero,
          children: [
            if (provider.activeAction != null) ...[
              _JDActionBanner(run: provider.activeAction!),
              const SizedBox(height: 14),
            ],
            _JDHeroCard(
              application: app,
              jd: jd,
              report: report,
              readiness: readiness,
              onPrimaryAction: () => _handleHeroPrimaryAction(app, jd, report),
              onReanalyze: () => _sendAnalyzeAction(app),
              onCustomResume: () => _sendCustomResumeAction(app),
            ),
            const SizedBox(height: 14),
            if (_tab == _JDMatchTab.evidence &&
                _activeEvidenceDraft != null) ...[
              const _JDEvidenceInlineBanner(),
              const SizedBox(height: 14),
            ],
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
              activeEvidenceDraft: _activeEvidenceDraft,
              renderEvidenceDraftInline: !usePageEvidencePanel,
              isSavingEvidence: _isSavingEvidence,
              onOpenEvidenceDraft: (seed) =>
                  _openEvidenceDraft(seed, switchToEvidenceTab: true),
              onCloseEvidenceDraft: _closeEvidenceDraft,
              onSaveProjectEvidence: (draft) => _saveProjectEvidence(
                provider: provider,
                application: app,
                jd: jd,
                report: report,
                draft: draft,
              ),
              onSaveInterviewNote: (title, body) =>
                  _saveInterviewQuestionAsNote(
                provider: provider,
                application: app,
                jd: jd,
                report: report,
                title: title,
                body: body,
              ),
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
          activeTab: _tab,
          onOpenProjects: widget.onOpenProjects,
          onOpenResumes: widget.onOpenResumes,
          onOpenNotes: widget.onOpenNotes,
          onSendPrompt: widget.onSendPrompt,
          onOpenEvidenceDraft: (seed) =>
              _openEvidenceDraft(seed, switchToEvidenceTab: true),
        );
        final primaryRail = _JDRail(
          provider: provider,
          application: app,
          jd: jd,
          report: report,
          readiness: readiness,
          activeTab: _tab,
          onOpenProjects: widget.onOpenProjects,
          onOpenResumes: widget.onOpenResumes,
          onOpenNotes: widget.onOpenNotes,
          onSendPrompt: widget.onSendPrompt,
          onOpenEvidenceDraft: (seed) =>
              _openEvidenceDraft(seed, switchToEvidenceTab: true),
          includeRelated: false,
        );
        final relatedRail = _JDRail(
          provider: provider,
          application: app,
          jd: jd,
          report: report,
          readiness: readiness,
          activeTab: _tab,
          onOpenProjects: widget.onOpenProjects,
          onOpenResumes: widget.onOpenResumes,
          onOpenNotes: widget.onOpenNotes,
          onSendPrompt: widget.onSendPrompt,
          onOpenEvidenceDraft: (seed) =>
              _openEvidenceDraft(seed, switchToEvidenceTab: true),
          includePrimary: false,
        );
        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              if (provider.activeAction != null) ...[
                _JDActionBanner(run: provider.activeAction!),
                const SizedBox(height: 14),
              ],
              _JDHeroCard(
                application: app,
                jd: jd,
                report: report,
                readiness: readiness,
                onPrimaryAction: () =>
                    _handleHeroPrimaryAction(app, jd, report),
                onReanalyze: () => _sendAnalyzeAction(app),
                onCustomResume: () => _sendCustomResumeAction(app),
              ),
              const SizedBox(height: 14),
              if (_tab == _JDMatchTab.evidence &&
                  _activeEvidenceDraft != null) ...[
                const _JDEvidenceInlineBanner(),
                const SizedBox(height: 14),
              ],
              primaryRail,
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
                activeEvidenceDraft: _activeEvidenceDraft,
                renderEvidenceDraftInline: true,
                isSavingEvidence: _isSavingEvidence,
                onOpenEvidenceDraft: (seed) =>
                    _openEvidenceDraft(seed, switchToEvidenceTab: true),
                onCloseEvidenceDraft: _closeEvidenceDraft,
                onSaveProjectEvidence: (draft) => _saveProjectEvidence(
                  provider: provider,
                  application: app,
                  jd: jd,
                  report: report,
                  draft: draft,
                ),
                onSaveInterviewNote: (title, body) =>
                    _saveInterviewQuestionAsNote(
                  provider: provider,
                  application: app,
                  jd: jd,
                  report: report,
                  title: title,
                  body: body,
                ),
              ),
              const SizedBox(height: 14),
              _JDLibrarySection(provider: provider),
              const SizedBox(height: 14),
              relatedRail,
            ],
          );
        }
        final evidencePanel = usePageEvidencePanel
            ? _EvidenceDraftPanel(
                key: ValueKey(
                  'page_evidence_draft_${_activeEvidenceDraft!.title}_${_activeEvidenceDraft!.description}',
                ),
                application: app,
                seed: _activeEvidenceDraft!,
                isSaving: _isSavingEvidence,
                onClose: _closeEvidenceDraft,
                onSave: (draft) => _saveProjectEvidence(
                  provider: provider,
                  application: app,
                  jd: jd,
                  report: report,
                  draft: draft,
                ),
              )
            : null;
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: main),
            if (evidencePanel != null) ...[
              const SizedBox(width: 14),
              SizedBox(
                width: 430,
                child: ListView(
                  padding: EdgeInsets.zero,
                  children: [evidencePanel],
                ),
              ),
            ],
            const SizedBox(width: 20),
            SizedBox(width: 340, child: ListView(children: [rail])),
          ],
        );
      },
    );
  }

  void _sendAnalyzeAction(CareerApplicationView? app) {
    _sendJDPromptAction(
      context,
      sender: widget.onSendPrompt,
      application: app,
      label: '重新分析匹配',
      actionType: 'jd_match_analysis',
      origin: 'jd_match',
      detail: '复用当前项目已有简历画像、职业画像和 JD，刷新匹配评分、差距和面试准备建议。',
    );
  }

  void _handleHeroPrimaryAction(
    CareerApplicationView? app,
    JDAnalysisView? jd,
    JobFitReportView? report,
  ) {
    final action = _jdHeroPrimaryAction(app: app, jd: jd, report: report);
    switch (action.actionType) {
      case 'resume_upload':
        widget.onOpenResumes();
        return;
      case 'custom_resume':
        _sendCustomResumeAction(app);
        return;
      case 'gap_optimize':
        setState(() => _tab = _JDMatchTab.gaps);
        _sendGapOptimizeAction(app);
        return;
      case 'interview_prep':
        setState(() => _tab = _JDMatchTab.interview);
        return;
      default:
        _sendAnalyzeAction(app);
    }
  }

  void _sendGapOptimizeAction(CareerApplicationView? app) {
    _sendJDPromptAction(
      context,
      sender: widget.onSendPrompt,
      application: app,
      label: '优化简历差距',
      actionType: 'resume_optimize',
      origin: 'jd_match',
      detail: '基于当前 JD 匹配差距生成简历改写方向，优先补齐影响投递的证据表达。',
    );
  }

  void _sendCustomResumeAction(CareerApplicationView? app) {
    _sendJDPromptAction(
      context,
      sender: widget.onSendPrompt,
      application: app,
      label: '生成定制简历',
      actionType: 'custom_resume',
      origin: 'jd_match',
      detail: '基于当前 JD 分析和匹配报告生成岗位定制简历草案，保存前不覆盖已有版本。',
    );
  }

  void _openEvidenceDraft(
    _EvidenceDraftSeed seed, {
    bool switchToEvidenceTab = false,
  }) {
    setState(() {
      if (switchToEvidenceTab) {
        _tab = _JDMatchTab.evidence;
      }
      _activeEvidenceDraft = seed;
    });
  }

  void _closeEvidenceDraft() {
    setState(() => _activeEvidenceDraft = null);
  }

  Future<void> _saveProjectEvidence({
    required CareerWorkbenchProvider provider,
    required CareerApplicationView? application,
    required JDAnalysisView? jd,
    required JobFitReportView? report,
    required _ProjectEvidenceDraft draft,
  }) async {
    final sourceSessionId = careerFirstNonEmpty([
      report?.meta.sourceSessionId,
      jd?.meta.sourceSessionId,
      application?.meta.sourceSessionId,
    ]);
    final messenger = ScaffoldMessenger.maybeOf(context);
    if (sourceSessionId.isEmpty) {
      messenger?.showSnackBar(
        const SnackBar(content: Text('缺少 source_session_id，暂时不能保存项目证据')),
      );
      return;
    }
    setState(() => _isSavingEvidence = true);
    final title = draft.title.trim();
    final description = draft.description.trim();
    final skills = draft.skillTags;
    final outcomes = draft.outcomes.trim();
    final appTitle =
        careerShortLabel(application?.displayTitle, fallback: '当前求职项目');
    final markdown = StringBuffer()
      ..writeln('# $title')
      ..writeln()
      ..writeln('关联项目：$appTitle')
      ..writeln()
      ..writeln('## 证据说明')
      ..writeln(description)
      ..writeln();
    if (skills.isNotEmpty) {
      markdown
        ..writeln('## 关键技术点')
        ..writeln(skills.map((item) => '- $item').join('\n'))
        ..writeln();
    }
    if (outcomes.isNotEmpty) {
      markdown
        ..writeln('## 量化成果')
        ..writeln(outcomes)
        ..writeln();
    }
    markdown
      ..writeln('## 来源')
      ..writeln('- 来源页面：JD 匹配 / 证据依据')
      ..writeln('- 关联 JD：${jd?.displayTitle ?? '当前 JD'}')
      ..writeln('- 关联匹配报告：${report?.jobFitReportId ?? '暂无'}');
    try {
      final evidenceRefs = <String>[
        if (application?.applicationId.trim().isNotEmpty == true)
          application!.applicationId,
        if (jd?.jdAnalysisId.trim().isNotEmpty == true) jd!.jdAnalysisId,
        if (report?.jobFitReportId.trim().isNotEmpty == true)
          report!.jobFitReportId,
      ];
      await provider.createNote(
        sourceSessionId: sourceSessionId,
        title: title,
        bodyMarkdown: markdown.toString(),
        summary: description,
        noteType: 'note',
        origin: 'jd_match',
        relatedApplicationId: application?.applicationId,
        evidenceRefs: evidenceRefs,
        tags: [
          '项目证据',
          'JD匹配',
          ...skills.take(5),
        ],
        sourceRefs: [
          if (application != null)
            {
              'source_type': 'career_application',
              'source_id': application.applicationId,
              'source_session_id': application.meta.sourceSessionId,
              'title': application.displayTitle,
              'quote': '',
            },
          if (jd != null)
            {
              'source_type': 'jd_analysis',
              'source_id': jd.jdAnalysisId,
              'source_session_id': jd.meta.sourceSessionId,
              'title': jd.displayTitle,
              'quote': '',
            },
          if (report != null)
            {
              'source_type': 'job_fit_report',
              'source_id': report.jobFitReportId,
              'source_session_id': report.meta.sourceSessionId,
              'title': '匹配报告 ${report.overallScore} 分',
              'quote': '',
            },
        ],
      );
      if (!mounted) return;
      setState(() {
        _activeEvidenceDraft = null;
        _isSavingEvidence = false;
      });
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('已保存为项目证据笔记；建议重新分析匹配让新证据参与评分'),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _isSavingEvidence = false);
      messenger?.showSnackBar(
        SnackBar(content: Text('保存项目证据失败：$error')),
      );
    }
  }

  Future<void> _saveInterviewQuestionAsNote({
    required CareerWorkbenchProvider provider,
    required CareerApplicationView? application,
    required JDAnalysisView? jd,
    required JobFitReportView? report,
    required String title,
    required String body,
  }) async {
    final messenger = ScaffoldMessenger.maybeOf(context);
    final sourceSessionId = careerFirstNonEmpty([
      report?.meta.sourceSessionId,
      jd?.meta.sourceSessionId,
      application?.meta.sourceSessionId,
    ]);
    if (sourceSessionId.isEmpty) {
      messenger?.showSnackBar(
        const SnackBar(content: Text('缺少 source_session_id，暂时不能保存为笔记')),
      );
      return;
    }
    final appTitle =
        careerShortLabel(application?.displayTitle, fallback: '当前岗位');
    final noteTitle = '面试题：$title';
    final markdown = StringBuffer()
      ..writeln('# $noteTitle')
      ..writeln()
      ..writeln('关联岗位：$appTitle')
      ..writeln()
      ..writeln('## 考察点')
      ..writeln(body.trim().isEmpty ? '待补充。' : body.trim())
      ..writeln()
      ..writeln('## 回答组织建议')
      ..writeln('- 先说明项目背景和约束条件。')
      ..writeln('- 再解释技术方案、取舍和关键实现。')
      ..writeln('- 补充指标、稳定性、成本或效率上的结果。')
      ..writeln('- 最后说明复盘改进和可迁移经验。');
    try {
      await provider.createNote(
        sourceSessionId: sourceSessionId,
        title: noteTitle,
        bodyMarkdown: markdown.toString(),
        summary: body.trim(),
        noteType: 'note',
        origin: 'jd_match',
        tags: const ['面试准备', 'JD匹配'],
        relatedApplicationId: application?.applicationId,
        sourceRefs: [
          if (application != null)
            {
              'type': 'career_application',
              'id': application.applicationId,
              'title': application.displayTitle,
            },
          if (jd != null)
            {
              'type': 'jd_analysis',
              'id': jd.jdAnalysisId,
              'title': jd.displayTitle,
            },
          if (report != null)
            {
              'type': 'job_fit_report',
              'id': report.jobFitReportId,
              'title': '匹配报告 ${report.overallScore} 分',
            },
        ],
      );
      if (!mounted) return;
      messenger?.showSnackBar(
        const SnackBar(content: Text('已保存为面试准备笔记')),
      );
    } catch (error) {
      if (!mounted) return;
      messenger?.showSnackBar(
        SnackBar(content: Text('保存笔记失败：$error')),
      );
    }
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
      CareerWorkbenchActionState.running => '正在${run.request.label}',
      CareerWorkbenchActionState.completed => '${run.request.label}已完成',
      CareerWorkbenchActionState.failed => '${run.request.label}失败',
    };
    final subtitle = run.state == CareerWorkbenchActionState.failed
        ? run.error ?? '请检查当前项目是否已有 JD 分析和基础简历画像。'
        : run.resultHints.isEmpty
            ? '完成后会刷新：匹配分数、差距分析、证据依据和面试准备建议。'
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

class _JDEvidenceInlineBanner extends StatelessWidget {
  const _JDEvidenceInlineBanner();

  @override
  Widget build(BuildContext context) {
    return ProductCard(
      soft: true,
      tone: ProductTone.primary,
      padding: const EdgeInsets.fromLTRB(14, 11, 14, 11),
      child: Row(
        children: [
          ProductIconTile(
            icon: Icons.auto_fix_high_rounded,
            tone: ProductTone.primary,
            size: 34,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '正在补充项目证据，保存后会刷新证据清单、来源引用和关联笔记。',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 12.5,
                fontWeight: FontWeight.w900,
                color: ProductColors.primary,
              ),
            ),
          ),
          Text(
            '填写后保存',
            style: AppTheme.ts(
              fontSize: 11.5,
              fontWeight: FontWeight.w900,
              color: ProductColors.primary,
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
  final VoidCallback onPrimaryAction;
  final VoidCallback onReanalyze;
  final VoidCallback onCustomResume;

  const _JDHeroCard({
    required this.application,
    required this.jd,
    required this.report,
    required this.readiness,
    required this.onPrimaryAction,
    required this.onReanalyze,
    required this.onCustomResume,
  });

  @override
  Widget build(BuildContext context) {
    final score = report?.overallScore ?? readiness?.score;
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(22, 18, 22, 18),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 620;
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
              ProductScoreRing(score: score, size: 94),
              const SizedBox(height: 7),
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
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
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
                const SizedBox(height: 6),
                Text(
                  careerDisplaySummary(
                    careerFirstNonEmpty(
                      [
                        readiness?.summary,
                        report?.recommendation,
                        '完成 JD 分析后，这里会展示匹配结论和建议。',
                      ],
                    ),
                    maxChars: compact ? 116 : 140,
                  ),
                  maxLines: compact ? 4 : 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12,
                    height: 1.42,
                    fontWeight: FontWeight.w700,
                    color: ProductColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ElevatedButton.icon(
                      onPressed: onReanalyze,
                      icon: const Icon(Icons.refresh_rounded, size: 16),
                      label: Text(report == null ? '生成匹配报告' : '重新分析'),
                      style: ElevatedButton.styleFrom(
                        minimumSize: const Size(0, 34),
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        backgroundColor: ProductColors.primary,
                        foregroundColor: Colors.white,
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(11),
                        ),
                      ),
                    ),
                    OutlinedButton.icon(
                      onPressed:
                          report == null ? onCustomResume : onPrimaryAction,
                      icon: Icon(
                        report == null
                            ? Icons.description_outlined
                            : Icons.auto_fix_high_rounded,
                        size: 16,
                      ),
                      label: Text(report == null ? '生成定制简历' : '优化匹配'),
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(0, 34),
                        padding: const EdgeInsets.symmetric(horizontal: 12),
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
  final _EvidenceDraftSeed? activeEvidenceDraft;
  final bool renderEvidenceDraftInline;
  final bool isSavingEvidence;
  final void Function(_EvidenceDraftSeed seed) onOpenEvidenceDraft;
  final VoidCallback onCloseEvidenceDraft;
  final Future<void> Function(_ProjectEvidenceDraft draft)
      onSaveProjectEvidence;
  final Future<void> Function(String title, String body) onSaveInterviewNote;

  const _JDMainContent({
    required this.tab,
    required this.application,
    required this.jd,
    required this.report,
    required this.readiness,
    required this.onOpenLearning,
    required this.onSendPrompt,
    required this.activeEvidenceDraft,
    required this.renderEvidenceDraftInline,
    required this.isSavingEvidence,
    required this.onOpenEvidenceDraft,
    required this.onCloseEvidenceDraft,
    required this.onSaveProjectEvidence,
    required this.onSaveInterviewNote,
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
          onOpenEvidenceDraft: onOpenEvidenceDraft,
        ),
      _JDMatchTab.evidence => _EvidenceView(
          application: application,
          report: report,
          jd: jd,
          activeDraft: activeEvidenceDraft,
          renderDraftInline: renderEvidenceDraftInline,
          isSaving: isSavingEvidence,
          onOpenDraft: onOpenEvidenceDraft,
          onCloseDraft: onCloseEvidenceDraft,
          onSaveDraft: onSaveProjectEvidence,
        ),
      _JDMatchTab.interview => _InterviewPrepView(
          application: application,
          report: report,
          jd: jd,
          onSendPrompt: onSendPrompt,
          onSaveInterviewNote: onSaveInterviewNote,
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
          final compact = constraints.maxWidth < 620;
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
                  careerDisplaySummary(
                    careerFirstNonEmpty(
                      [readiness?.summary, application?.summary],
                      fallback: '暂无匹配结论。',
                    ),
                    maxChars: compact ? 110 : 126,
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
          final strengths = [
            ...readiness?.strengths ?? const <String>[],
            ..._dynamicSnippets(report?.matchedEvidence ?? const [], limit: 3),
          ].where((item) => item.trim().isNotEmpty).take(4).toList();
          final risks = [
            ...readiness?.risks ?? const <String>[],
            ..._dynamicSnippets(report?.gaps ?? const [], limit: 3),
          ].where((item) => item.trim().isNotEmpty).take(4).toList();
          final summaryGrid = LayoutBuilder(
            builder: (context, summaryConstraints) {
              final stacked = summaryConstraints.maxWidth < 720;
              final children = [
                _SummaryInfoCard(
                  title: '主要优势',
                  subtitle: '支撑当前匹配分的证据',
                  icon: Icons.thumb_up_alt_outlined,
                  tone: ProductTone.primary,
                  items: strengths,
                  emptyText: '暂无明确优势证据。',
                ),
                _SummaryInfoCard(
                  title: '主要风险',
                  subtitle: '最影响投递和面试的差距',
                  icon: Icons.warning_amber_rounded,
                  tone: ProductTone.warning,
                  items: risks,
                  emptyText: '暂无明确风险。',
                ),
              ];
              if (stacked) {
                return Column(
                  children: [
                    children[0],
                    const SizedBox(height: 12),
                    children[1],
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: children[0]),
                  const SizedBox(width: 12),
                  Expanded(child: children[1]),
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
                const SizedBox(height: 14),
                summaryGrid,
              ],
            );
          }
          return Column(
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(width: 220, child: scorePanel),
                  const SizedBox(width: 16),
                  Expanded(child: scoreGrid),
                ],
              ),
              const SizedBox(height: 14),
              summaryGrid,
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
  final void Function(_EvidenceDraftSeed seed) onOpenEvidenceDraft;

  const _GapAnalysisView({
    required this.application,
    required this.report,
    required this.readiness,
    required this.onOpenLearning,
    required this.onSendPrompt,
    required this.onOpenEvidenceDraft,
  });

  @override
  Widget build(BuildContext context) {
    final reportGaps = _dynamicSnippets(report?.gaps ?? const [], limit: 5);
    final risks = readiness?.risks ?? const <String>[];
    final missing = readiness?.missingMaterials ?? const <String>[];
    final gaps = [
      ...reportGaps,
      ...risks,
      ...missing,
    ].where((item) => item.trim().isNotEmpty).take(6).toList();
    final directions = _dynamicSnippets(
      report?.resumeOptimizationDirection ?? const [],
      limit: 5,
    );
    return ProductSection(
      title: '关键差距与优先级',
      subtitle: '差距分析：把每个短板转成简历、学习、证据或面试动作',
      icon: Icons.report_problem_outlined,
      tone: ProductTone.warning,
      trailing: TextButton(
        onPressed: onOpenLearning,
        child: const Text('学习计划'),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _GapFilterRow(),
          const SizedBox(height: 14),
          if (gaps.isEmpty)
            const _EmptyJDText(text: '暂无明确差距。完成匹配报告后会展示短板。')
          else
            for (var i = 0; i < gaps.length; i++) ...[
              _GapItemCard(
                index: i + 1,
                gap: gaps[i],
                direction: directions.isEmpty
                    ? '围绕这个差距补齐简历证据、学习任务或面试表达。'
                    : directions[math.min(i, directions.length - 1)],
                application: application,
                onSendPrompt: onSendPrompt,
                onOpenEvidenceDraft: onOpenEvidenceDraft,
              ),
              if (i != gaps.length - 1) const SizedBox(height: 10),
            ],
        ],
      ),
    );
  }
}

class _GapFilterRow extends StatelessWidget {
  const _GapFilterRow();

  @override
  Widget build(BuildContext context) {
    const filters = ['全部', '高优先级', '学习类', '简历类', '面试类'];
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (var i = 0; i < filters.length; i++) ...[
            ProductTag(
              label: filters[i],
              tone: i == 0 ? ProductTone.primary : ProductTone.neutral,
            ),
            if (i != filters.length - 1) const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }
}

class _GapItemCard extends StatelessWidget {
  final int index;
  final String gap;
  final String direction;
  final CareerApplicationView? application;
  final CareerPromptSender? onSendPrompt;
  final void Function(_EvidenceDraftSeed seed) onOpenEvidenceDraft;

  const _GapItemCard({
    required this.index,
    required this.gap,
    required this.direction,
    required this.application,
    required this.onSendPrompt,
    required this.onOpenEvidenceDraft,
  });

  @override
  Widget build(BuildContext context) {
    final highPriority = index <= 2;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: ProductColors.border),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final header = Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: highPriority
                      ? ProductColors.dangerSoft
                      : ProductColors.warningSoft,
                ),
                child: Center(
                  child: Text(
                    index.toString(),
                    style: AppTheme.ts(
                      fontSize: 13,
                      fontWeight: FontWeight.w900,
                      color: highPriority
                          ? ProductColors.danger
                          : ProductColors.warning,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      gap,
                      maxLines: compact ? 3 : 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 13.5,
                        height: 1.35,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 7,
                      runSpacing: 7,
                      children: [
                        ProductTag(
                          label: highPriority ? '高优先级' : '中优先级',
                          tone: highPriority
                              ? ProductTone.danger
                              : ProductTone.warning,
                        ),
                        const ProductTag(
                            label: '简历类', tone: ProductTone.purple),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          );
          final analysis = _GapInfoColumns(gap: gap, direction: direction);
          final actions = _GapActionButtons(
            application: application,
            onSendPrompt: onSendPrompt,
            onOpenEvidenceDraft: onOpenEvidenceDraft,
            evidenceTitle: gap,
            detail: '$gap；建议：$direction',
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                header,
                const SizedBox(height: 12),
                analysis,
                const SizedBox(height: 12),
                actions,
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(flex: 4, child: header),
              const SizedBox(width: 12),
              Expanded(flex: 5, child: analysis),
              const SizedBox(width: 12),
              SizedBox(width: 230, child: actions),
            ],
          );
        },
      ),
    );
  }
}

class _GapInfoColumns extends StatelessWidget {
  final String gap;
  final String direction;

  const _GapInfoColumns({
    required this.gap,
    required this.direction,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final stacked = constraints.maxWidth < 380;
        final children = [
          _GapInfoBlock(
            label: 'JD 要求',
            text: '需要更明确的岗位相关能力、项目证据和可交付成果。',
          ),
          _GapInfoBlock(label: '当前差距', text: gap),
          _GapInfoBlock(label: '行动建议', text: direction),
        ];
        if (stacked) {
          return Column(
            children: [
              for (var i = 0; i < children.length; i++) ...[
                children[i],
                if (i != children.length - 1) const SizedBox(height: 8),
              ],
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < children.length; i++) ...[
              Expanded(child: children[i]),
              if (i != children.length - 1) const SizedBox(width: 10),
            ],
          ],
        );
      },
    );
  }
}

class _GapInfoBlock extends StatelessWidget {
  final String label;
  final String text;

  const _GapInfoBlock({
    required this.label,
    required this.text,
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
            color: ProductColors.textMuted,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          text,
          maxLines: 3,
          overflow: TextOverflow.ellipsis,
          style: AppTheme.ts(
            fontSize: 11.4,
            height: 1.38,
            color: ProductColors.textSecondary,
          ),
        ),
      ],
    );
  }
}

class _GapActionButtons extends StatelessWidget {
  final CareerApplicationView? application;
  final CareerPromptSender? onSendPrompt;
  final void Function(_EvidenceDraftSeed seed) onOpenEvidenceDraft;
  final String evidenceTitle;
  final String detail;

  const _GapActionButtons({
    required this.application,
    required this.onSendPrompt,
    required this.onOpenEvidenceDraft,
    required this.evidenceTitle,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final actions = [
      ('优化简历表达', 'resume_optimize', Icons.edit_note_outlined),
      ('创建学习任务', 'learning_task', Icons.school_outlined),
      ('补充项目证据', 'evidence_add', Icons.add_link_outlined),
      ('准备面试', 'interview_prep', Icons.forum_outlined),
    ];
    return Wrap(
      alignment: WrapAlignment.end,
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final action in actions)
          OutlinedButton.icon(
            onPressed: () {
              if (action.$2 == 'evidence_add') {
                onOpenEvidenceDraft(
                  _EvidenceDraftSeed(
                    title: evidenceTitle,
                    description: detail,
                  ),
                );
                return;
              }
              _sendJDPromptAction(
                context,
                sender: onSendPrompt,
                application: application,
                label: action.$1,
                actionType: action.$2,
                origin: 'jd_match',
                detail: detail,
              );
            },
            icon: Icon(action.$3, size: 14),
            label: Text(action.$1),
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(0, 32),
              padding: const EdgeInsets.symmetric(horizontal: 10),
              foregroundColor: ProductColors.primary,
              side: const BorderSide(color: ProductColors.borderStrong),
              textStyle: AppTheme.ts(
                fontSize: 11.5,
                fontWeight: FontWeight.w900,
              ),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(9),
              ),
            ),
          ),
      ],
    );
  }
}

class _EvidenceView extends StatelessWidget {
  final CareerApplicationView? application;
  final JobFitReportView? report;
  final JDAnalysisView? jd;
  final _EvidenceDraftSeed? activeDraft;
  final bool renderDraftInline;
  final bool isSaving;
  final void Function(_EvidenceDraftSeed seed) onOpenDraft;
  final VoidCallback onCloseDraft;
  final Future<void> Function(_ProjectEvidenceDraft draft) onSaveDraft;

  const _EvidenceView({
    required this.application,
    required this.report,
    required this.jd,
    required this.activeDraft,
    required this.renderDraftInline,
    required this.isSaving,
    required this.onOpenDraft,
    required this.onCloseDraft,
    required this.onSaveDraft,
  });

  @override
  Widget build(BuildContext context) {
    final evidence =
        _dynamicSnippets(report?.matchedEvidence ?? const [], limit: 8);
    final required = jd?.requiredSkills ?? const <String>[];
    final preferred = jd?.preferredSkills ?? const <String>[];
    final missing = _evidenceMissingRequirements(
      report: report,
      jd: jd,
      evidence: evidence,
    );
    final visibleEvidence = evidence.take(4).toList();
    final visibleMissing = missing.take(4).toList();
    final evidenceBody = Column(
      children: [
        _EvidenceFilterRow(
          matchedCount: evidence.length,
          missingCount: missing.length,
        ),
        const SizedBox(height: 12),
        LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < 640;
            final matchedCard = _EvidenceColumnCard(
              title: '已命中证据',
              subtitle: '${evidence.length} 条来自简历和项目经历',
              icon: Icons.check_circle_outline_rounded,
              tone: ProductTone.primary,
              rowTone: ProductTone.info,
              items: visibleEvidence,
              totalCount: evidence.length,
              footerLabel: '查看全部已命中证据',
              emptyText: '暂无匹配证据。',
              onShowAll: () => _showEvidenceListDialog(
                context,
                title: '已命中证据',
                subtitle: '${evidence.length} 条来自简历和项目经历',
                tone: ProductTone.primary,
                rowTone: ProductTone.info,
                items: evidence,
              ),
            );
            final missingCard = _EvidenceColumnCard(
              title: '未命中要求',
              subtitle: '可补充项目证据或创建学习任务',
              icon: Icons.warning_amber_rounded,
              tone: ProductTone.warning,
              rowTone: ProductTone.warning,
              items: visibleMissing,
              totalCount: missing.length,
              footerLabel: '查看全部未命中要求',
              emptyText: '暂无明显未命中要求。',
              onAddEvidence: (item) =>
                  onOpenDraft(_draftSeedForRequirement(item)),
              onShowAll: () => _showEvidenceListDialog(
                context,
                title: '未命中要求',
                subtitle: '${missing.length} 条可转为项目证据或学习任务',
                tone: ProductTone.warning,
                rowTone: ProductTone.warning,
                items: missing,
                onAddEvidence: (item) =>
                    onOpenDraft(_draftSeedForRequirement(item)),
              ),
            );
            if (compact) {
              return Column(
                children: [
                  matchedCard,
                  const SizedBox(height: 14),
                  missingCard,
                ],
              );
            }
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: matchedCard),
                const SizedBox(width: 14),
                Expanded(child: missingCard),
              ],
            );
          },
        ),
        const SizedBox(height: 14),
        _EvidenceSourceCard(
          requiredSkills: required,
          preferredSkills: preferred,
          keywords: jd?.keywords ?? const [],
        ),
      ],
    );
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 1040;
          final draft = activeDraft;
          if (draft == null || !renderDraftInline) return evidenceBody;
          final panel = _EvidenceDraftPanel(
            key: ValueKey('evidence_draft_${draft.title}_${draft.description}'),
            application: application,
            seed: draft,
            isSaving: isSaving,
            onClose: onCloseDraft,
            onSave: onSaveDraft,
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                evidenceBody,
                const SizedBox(height: 14),
                panel,
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: evidenceBody),
              const SizedBox(width: 14),
              SizedBox(width: 430, child: panel),
            ],
          );
        },
      ),
    );
  }

  static bool _isCoveredRequirement(String requirement, List<String> evidence) {
    final normalized = requirement.toLowerCase();
    final haystack = evidence.join(' ').toLowerCase();
    if (normalized.contains('python') && haystack.contains('python')) {
      return true;
    }
    if (normalized.contains('fastapi') && haystack.contains('fastapi')) {
      return true;
    }
    if (normalized.contains('postgresql') && haystack.contains('postgresql')) {
      return true;
    }
    if (normalized.contains('redis') && haystack.contains('redis')) {
      return true;
    }
    if (normalized.contains('runtime') && haystack.contains('runtime')) {
      return true;
    }
    return evidence.any((item) => item.toLowerCase().contains(normalized));
  }

  static List<String> _evidenceMissingRequirements({
    required JobFitReportView? report,
    required JDAnalysisView? jd,
    required List<String> evidence,
  }) {
    final raw = [
      ..._dynamicSnippets(report?.gaps ?? const [], limit: 8),
      ...jd?.requiredSkills ?? const <String>[],
      ...jd?.preferredSkills ?? const <String>[],
      ...jd?.keywords ?? const <String>[],
      ...evidence,
    ].join(' ').toLowerCase();
    final result = <String>[];
    void add(String item) {
      if (!result.contains(item)) result.add(item);
    }

    if (raw.contains('langgraph') || raw.contains('langchain')) {
      add('LangGraph 实战经验');
    }
    if (raw.contains('rag') || raw.contains('召回')) {
      add('RAG 召回-重排-评估闭环');
    }
    if (raw.contains('sse') || raw.contains('高并发') || raw.contains('流式')) {
      add('高并发 SSE 优化量化结果');
    }
    if (raw.contains('文件解析') || raw.contains('结构化抽取')) {
      add('文件解析吞吐量变更与准确率');
    }

    if (result.length < 4) {
      final skillGaps = [
        ...?jd?.requiredSkills,
        ...?jd?.preferredSkills,
      ].where((item) => !_isCoveredRequirement(item, evidence));
      for (final item in skillGaps) {
        add(item);
        if (result.length >= 4) break;
      }
    }
    return result.take(4).toList();
  }

  static _EvidenceDraftSeed _draftSeedForRequirement(String item) {
    if (item.contains('LangGraph')) {
      return const _EvidenceDraftSeed(
        title: 'LangGraph实战：多 Agent任务编排与状态管理',
        description:
            '在智能客服 Agent 平台中使用 LangGraph 构建多 Agent 流程编排，覆盖 StateGraph 节点流转、工具调用、状态管理和异常恢复，用于补充 JD 匹配证据。',
      );
    }
    if (item.contains('RAG')) {
      return const _EvidenceDraftSeed(
        title: 'RAG 实战：召回、重排与评估闭环',
        description: '补充 RAG 检索链路中的召回、重排、生成与评估指标，说明可验证的项目实践和优化结果。',
      );
    }
    if (item.contains('SSE')) {
      return const _EvidenceDraftSeed(
        title: '高并发 SSE 流式链路优化',
        description: '补充 SSE 流式输出在高并发场景下的稳定性、吞吐、延迟和错误恢复优化证据。',
      );
    }
    if (item.contains('文件解析')) {
      return const _EvidenceDraftSeed(
        title: '文件解析吞吐量与准确率优化',
        description: '补充文件解析与结构化抽取链路的吞吐、准确率、失败恢复和业务落地指标。',
      );
    }
    return _EvidenceDraftSeed(
      title: item,
      description: '补充与「$item」相关的项目证据，用于支撑 JD 匹配。',
    );
  }
}

class _EvidenceColumnCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final ProductTone tone;
  final ProductTone rowTone;
  final List<String> items;
  final int? totalCount;
  final String? footerLabel;
  final String emptyText;
  final void Function(String item)? onAddEvidence;
  final VoidCallback? onShowAll;

  const _EvidenceColumnCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.tone,
    this.rowTone = ProductTone.info,
    required this.items,
    this.totalCount,
    this.footerLabel,
    required this.emptyText,
    this.onAddEvidence,
    this.onShowAll,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 13, 14, 13),
      decoration: ProductSurface.softCard(tone: tone, radius: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: style.color),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: AppTheme.ts(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: AppTheme.ts(
              fontSize: 11,
              color: ProductColors.textMuted,
            ),
          ),
          const SizedBox(height: 9),
          if (items.isEmpty)
            _EmptyJDText(text: emptyText)
          else
            for (var i = 0; i < items.length; i++) ...[
              _EvidenceRow(
                index: i + 1,
                text: items[i],
                tone: rowTone,
                onAddEvidence: onAddEvidence == null
                    ? null
                    : () => onAddEvidence!(items[i]),
              ),
              if (i != items.length - 1) const SizedBox(height: 7),
            ],
          if ((totalCount ?? items.length) > items.length &&
              footerLabel != null) ...[
            const SizedBox(height: 10),
            Center(
              child: TextButton.icon(
                onPressed: onShowAll,
                icon: const Icon(Icons.format_list_bulleted_rounded, size: 14),
                label: Text('$footerLabel (${totalCount ?? items.length})'),
                style: TextButton.styleFrom(
                  minimumSize: const Size(0, 30),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  foregroundColor: style.color,
                  textStyle: AppTheme.ts(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _EvidenceFilterRow extends StatelessWidget {
  final int matchedCount;
  final int missingCount;

  const _EvidenceFilterRow({
    required this.matchedCount,
    required this.missingCount,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        _EvidenceFilterChip(
          label: '全部',
          count: matchedCount + missingCount,
          active: true,
        ),
        const SizedBox(width: 8),
        _EvidenceFilterChip(label: '已命中', count: matchedCount),
        const SizedBox(width: 8),
        _EvidenceFilterChip(label: '未命中', count: missingCount),
        const SizedBox(width: 8),
        _EvidenceFilterChip(label: '按匹配维度', trailingIcon: Icons.expand_more),
      ],
    );
  }
}

class _EvidenceFilterChip extends StatelessWidget {
  final String label;
  final int? count;
  final bool active;
  final IconData? trailingIcon;

  const _EvidenceFilterChip({
    required this.label,
    this.count,
    this.active = false,
    this.trailingIcon,
  });

  @override
  Widget build(BuildContext context) {
    final fg = active ? ProductColors.primary : ProductColors.textSecondary;
    return Container(
      height: 31,
      padding: const EdgeInsets.symmetric(horizontal: 11),
      decoration: BoxDecoration(
        color: active ? ProductColors.primarySoft : ProductColors.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: active ? ProductColors.borderStrong : ProductColors.border,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 11.5,
              fontWeight: FontWeight.w900,
              color: fg,
            ),
          ),
          if (count != null) ...[
            const SizedBox(width: 5),
            Text(
              '($count)',
              style: AppTheme.ts(
                fontSize: 10.5,
                fontWeight: FontWeight.w800,
                color: active ? ProductColors.primary : ProductColors.textMuted,
              ),
            ),
          ],
          if (trailingIcon != null) ...[
            const SizedBox(width: 5),
            Icon(trailingIcon, size: 14, color: fg),
          ],
        ],
      ),
    );
  }
}

class _EvidenceSourceCard extends StatelessWidget {
  final List<String> requiredSkills;
  final List<String> preferredSkills;
  final List<String> keywords;

  const _EvidenceSourceCard({
    required this.requiredSkills,
    required this.preferredSkills,
    required this.keywords,
  });

  @override
  Widget build(BuildContext context) {
    final rows = <_EvidenceSourceRowData>[
      for (final item in requiredSkills.take(2))
        _EvidenceSourceRowData(
          title: item,
          type: '岗位要求',
          source: 'JD 分析',
          project: '当前项目',
          time: '05-10 00:45',
        ),
      for (final item in preferredSkills.take(1))
        _EvidenceSourceRowData(
          title: item,
          type: '加分项',
          source: '匹配报告',
          project: '当前项目',
          time: '05-09 23:18',
        ),
      for (final item in keywords.take(1))
        _EvidenceSourceRowData(
          title: item,
          type: '关键词',
          source: '简历画像',
          project: '候选人画像',
          time: '05-09 22:40',
        ),
    ];
    final totalReferenceCount = math.min(
      12,
      math.max(
        rows.length,
        requiredSkills.length + preferredSkills.length,
      ),
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 13, 14, 13),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: ProductColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Row(
                  children: [
                    Text(
                      '来源引用',
                      style: AppTheme.ts(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(width: 8),
                    ProductTag(
                      label: totalReferenceCount.toString(),
                      tone: ProductTone.neutral,
                    ),
                  ],
                ),
              ),
              TextButton.icon(
                onPressed: rows.isEmpty
                    ? null
                    : () => _copyEvidenceChecklist(
                          context,
                          rows: rows,
                          requiredSkills: requiredSkills,
                          preferredSkills: preferredSkills,
                          keywords: keywords,
                        ),
                icon: const Icon(Icons.download_rounded, size: 14),
                label: const Text('导出证据清单'),
                style: TextButton.styleFrom(
                  disabledForegroundColor:
                      ProductColors.primary.withValues(alpha: 0.78),
                  textStyle: AppTheme.ts(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            '证据的原始出处与引用，供面试与简历优化使用',
            style: AppTheme.ts(
              fontSize: 11,
              color: ProductColors.textMuted,
            ),
          ),
          const SizedBox(height: 12),
          if (rows.isEmpty)
            const _EmptyJDText(text: '暂无来源引用。')
          else
            LayoutBuilder(
              builder: (context, constraints) {
                final compact = constraints.maxWidth < 720;
                if (compact) {
                  return Column(
                    children: [
                      for (var i = 0; i < rows.length; i++) ...[
                        _EvidenceSourceCompactRow(row: rows[i]),
                        if (i != rows.length - 1) const SizedBox(height: 8),
                      ],
                    ],
                  );
                }
                return _EvidenceSourceTable(rows: rows);
              },
            ),
        ],
      ),
    );
  }
}

Future<void> _showEvidenceListDialog(
  BuildContext context, {
  required String title,
  required String subtitle,
  required ProductTone tone,
  required ProductTone rowTone,
  required List<String> items,
  void Function(String item)? onAddEvidence,
}) async {
  final style = productToneStyle(tone);
  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return Dialog(
        insetPadding: const EdgeInsets.all(24),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680, maxHeight: 720),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    ProductIconTile(
                      icon: tone == ProductTone.warning
                          ? Icons.warning_amber_rounded
                          : Icons.fact_check_outlined,
                      tone: tone,
                      size: 40,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  title,
                                  style: AppTheme.ts(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w900,
                                    color: ProductColors.text,
                                  ),
                                ),
                              ),
                              ProductTag(
                                label: items.length.toString(),
                                tone: tone,
                              ),
                            ],
                          ),
                          const SizedBox(height: 3),
                          Text(
                            subtitle,
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
                if (items.isEmpty)
                  Expanded(
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(18),
                      decoration: BoxDecoration(
                        color: style.soft.withValues(alpha: 0.42),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: style.color.withValues(alpha: 0.14),
                        ),
                      ),
                      child: Center(
                        child: Text(
                          '暂无内容。',
                          style: AppTheme.ts(
                            fontSize: 13,
                            color: ProductColors.textSecondary,
                          ),
                        ),
                      ),
                    ),
                  )
                else
                  Expanded(
                    child: ListView.separated(
                      itemCount: items.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 8),
                      itemBuilder: (context, index) {
                        return _EvidenceRow(
                          index: index + 1,
                          text: items[index],
                          tone: rowTone,
                          onAddEvidence: onAddEvidence == null
                              ? null
                              : () {
                                  Navigator.of(dialogContext).pop();
                                  onAddEvidence(items[index]);
                                },
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

void _copyEvidenceChecklist(
  BuildContext context, {
  required List<_EvidenceSourceRowData> rows,
  required List<String> requiredSkills,
  required List<String> preferredSkills,
  required List<String> keywords,
}) {
  final text = _buildEvidenceChecklistText(
    rows: rows,
    requiredSkills: requiredSkills,
    preferredSkills: preferredSkills,
    keywords: keywords,
  );
  Clipboard.setData(ClipboardData(text: text));
  ScaffoldMessenger.maybeOf(context)?.showSnackBar(
    const SnackBar(content: Text('证据清单已复制，可粘贴到笔记或文档中。')),
  );
}

String _buildEvidenceChecklistText({
  required List<_EvidenceSourceRowData> rows,
  required List<String> requiredSkills,
  required List<String> preferredSkills,
  required List<String> keywords,
}) {
  final buffer = StringBuffer()
    ..writeln('JD 匹配证据清单')
    ..writeln()
    ..writeln('## 来源引用');
  for (var i = 0; i < rows.length; i++) {
    final row = rows[i];
    buffer
      ..writeln('${i + 1}. ${row.title}')
      ..writeln('   - 类型：${row.type}')
      ..writeln('   - 来源：${row.source}')
      ..writeln('   - 关联项目：${row.project}')
      ..writeln('   - 时间：${row.time}');
  }
  void writeList(String title, List<String> items) {
    if (items.isEmpty) return;
    buffer
      ..writeln()
      ..writeln('## $title');
    for (final item in items) {
      buffer.writeln('- $item');
    }
  }

  writeList('硬性要求', requiredSkills);
  writeList('加分项', preferredSkills);
  writeList('关键词', keywords);
  return buffer.toString().trim();
}

class _EvidenceSourceTable extends StatelessWidget {
  final List<_EvidenceSourceRowData> rows;

  const _EvidenceSourceTable({required this.rows});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ProductColors.border),
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
            decoration: BoxDecoration(
              color: ProductColors.surfaceSoft,
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(12),
              ),
              border: Border(
                bottom: BorderSide(color: ProductColors.border),
              ),
            ),
            child: Row(
              children: [
                _EvidenceSourceHeaderCell('证据标题', flex: 3),
                _EvidenceSourceHeaderCell('类型', flex: 1),
                _EvidenceSourceHeaderCell('来源', flex: 2),
                _EvidenceSourceHeaderCell('关联项目', flex: 2),
                _EvidenceSourceHeaderCell('更新/引用时间', flex: 2),
                const SizedBox(width: 92),
              ],
            ),
          ),
          for (var i = 0; i < rows.length; i++) ...[
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                children: [
                  _EvidenceSourceBodyCell(rows[i].title, flex: 3),
                  _EvidenceSourcePillCell(rows[i].type),
                  _EvidenceSourceBodyCell(rows[i].source, flex: 2),
                  _EvidenceSourceBodyCell(rows[i].project, flex: 2),
                  _EvidenceSourceBodyCell(rows[i].time, flex: 2),
                  SizedBox(
                    width: 92,
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        _EvidenceSourceTextAction(
                          label: '查看',
                          color: ProductColors.textSecondary,
                          onTap: () => _showJDAssetLocationSnack(
                            context,
                            '证据「${rows[i].title}」的来源已在当前行展示。',
                          ),
                        ),
                        const SizedBox(width: 8),
                        _EvidenceSourceTextAction(
                          label: '复制',
                          color: ProductColors.primary,
                          onTap: () => _copyEvidenceSourceRow(context, rows[i]),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            if (i != rows.length - 1)
              Divider(height: 1, color: ProductColors.border),
          ],
        ],
      ),
    );
  }
}

class _EvidenceSourceTextAction extends StatelessWidget {
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _EvidenceSourceTextAction({
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(6),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 3),
        child: Text(
          label,
          style: AppTheme.ts(
            fontSize: 11,
            fontWeight: FontWeight.w900,
            color: color,
          ),
        ),
      ),
    );
  }
}

void _copyEvidenceSourceRow(BuildContext context, _EvidenceSourceRowData row) {
  final text = [
    '证据：${row.title}',
    '类型：${row.type}',
    '来源：${row.source}',
    '关联项目：${row.project}',
    '时间：${row.time}',
  ].join('\n');
  Clipboard.setData(ClipboardData(text: text));
  ScaffoldMessenger.maybeOf(context)?.showSnackBar(
    const SnackBar(content: Text('证据引用已复制。')),
  );
}

class _EvidenceSourceCompactRow extends StatelessWidget {
  final _EvidenceSourceRowData row;

  const _EvidenceSourceCompactRow({required this.row});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration:
          ProductSurface.softCard(tone: ProductTone.neutral, radius: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            row.title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 12.5,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              ProductTag(label: row.type, tone: ProductTone.primary),
              ProductTag(label: row.source, tone: ProductTone.info),
              ProductTag(label: row.time, tone: ProductTone.neutral),
            ],
          ),
        ],
      ),
    );
  }
}

class _EvidenceSourceHeaderCell extends StatelessWidget {
  final String text;
  final int flex;

  const _EvidenceSourceHeaderCell(this.text, {required this.flex});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      flex: flex,
      child: Text(
        text,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: AppTheme.ts(
          fontSize: 11,
          fontWeight: FontWeight.w900,
          color: ProductColors.textMuted,
        ),
      ),
    );
  }
}

class _EvidenceSourceBodyCell extends StatelessWidget {
  final String text;
  final int flex;

  const _EvidenceSourceBodyCell(this.text, {required this.flex});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      flex: flex,
      child: Text(
        text,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: AppTheme.ts(
          fontSize: 11.5,
          fontWeight: FontWeight.w700,
          color: ProductColors.textSecondary,
        ),
      ),
    );
  }
}

class _EvidenceSourcePillCell extends StatelessWidget {
  final String text;

  const _EvidenceSourcePillCell(this.text);

  @override
  Widget build(BuildContext context) {
    return Expanded(
      flex: 1,
      child: Align(
        alignment: Alignment.centerLeft,
        child: ProductTag(label: text, tone: ProductTone.primary),
      ),
    );
  }
}

class _EvidenceSourceRowData {
  final String title;
  final String type;
  final String source;
  final String project;
  final String time;

  const _EvidenceSourceRowData({
    required this.title,
    required this.type,
    required this.source,
    required this.project,
    required this.time,
  });
}

class _EvidenceDraftPanel extends StatefulWidget {
  final CareerApplicationView? application;
  final _EvidenceDraftSeed seed;
  final bool isSaving;
  final VoidCallback onClose;
  final Future<void> Function(_ProjectEvidenceDraft draft) onSave;

  const _EvidenceDraftPanel({
    super.key,
    required this.application,
    required this.seed,
    required this.isSaving,
    required this.onClose,
    required this.onSave,
  });

  @override
  State<_EvidenceDraftPanel> createState() => _EvidenceDraftPanelState();
}

class _EvidenceDraftPanelState extends State<_EvidenceDraftPanel> {
  late final TextEditingController _titleController;
  late final TextEditingController _descriptionController;
  late final TextEditingController _skillsController;
  late final TextEditingController _outcomesController;
  bool _submitted = false;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.seed.title);
    _descriptionController =
        TextEditingController(text: widget.seed.description);
    _skillsController = TextEditingController();
    _outcomesController = TextEditingController();
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _skillsController.dispose();
    _outcomesController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final appTitle = careerShortLabel(
      widget.application?.displayTitle,
      fallback: '当前求职项目',
    );
    final titleError =
        _submitted && _titleController.text.trim().isEmpty ? '请填写证据标题' : null;
    final descriptionError =
        _submitted && _descriptionController.text.trim().isEmpty
            ? '请补充项目背景、个人贡献或实现细节'
            : null;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: ProductColors.border),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 18,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '补充项目证据',
                      style: AppTheme.ts(
                        fontSize: 17,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '为未命中要求补充可验证的项目证据，提升匹配度。',
                      style: AppTheme.ts(
                        fontSize: 12,
                        height: 1.4,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: '关闭',
                onPressed: widget.isSaving ? null : widget.onClose,
                icon: const Icon(Icons.close_rounded),
                color: ProductColors.textSecondary,
              ),
            ],
          ),
          const SizedBox(height: 14),
          _EvidenceFormField(
            fieldKey: const Key('jd_evidence_title_field'),
            label: '证据标题 *',
            controller: _titleController,
            maxLength: 80,
            errorText: titleError,
            onChanged: (_) => _refreshErrors(),
          ),
          const SizedBox(height: 12),
          _EvidenceProjectSelectorField(
            value: appTitle,
          ),
          const SizedBox(height: 12),
          _EvidenceFormField(
            fieldKey: const Key('jd_evidence_description_field'),
            label: '补充描述 *',
            controller: _descriptionController,
            minLines: 5,
            maxLines: 8,
            maxLength: 1000,
            errorText: descriptionError,
            onChanged: (_) => _refreshErrors(),
          ),
          const SizedBox(height: 12),
          _EvidenceFormField(
            fieldKey: const Key('jd_evidence_skills_field'),
            label: '关键技术点',
            controller: _skillsController,
            hint: '例如 LangGraph、StateGraph、ToolNode、状态管理',
          ),
          const SizedBox(height: 8),
          const _EvidenceSuggestionChips(
            labels: ['LangGraph', 'StateGraph', 'ToolNode', '并行分支', '状态管理'],
          ),
          const SizedBox(height: 12),
          _EvidenceFormField(
            fieldKey: const Key('jd_evidence_outcomes_field'),
            label: '量化成果（可选）',
            controller: _outcomesController,
            minLines: 3,
            maxLines: 5,
            hint: '例如 日均处理会话 18w+、流程失败率 < 0.6%',
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: widget.isSaving
                  ? null
                  : () {
                      final current = _outcomesController.text.trim();
                      const preset = '日均处理会话 18w+，流程失败率 < 0.6%。';
                      _outcomesController.text =
                          current.isEmpty ? preset : '$current\n$preset';
                    },
              icon: const Icon(Icons.add_rounded, size: 14),
              label: const Text('添加成果'),
              style: OutlinedButton.styleFrom(
                minimumSize: const Size(0, 32),
                padding: const EdgeInsets.symmetric(horizontal: 10),
                foregroundColor: ProductColors.primary,
                side: const BorderSide(color: ProductColors.borderStrong),
                textStyle: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w900,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(9),
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          const _EvidenceLinkedSourcesBlock(),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: widget.isSaving ? null : widget.onClose,
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(0, 40),
                    foregroundColor: ProductColors.textSecondary,
                    side: const BorderSide(color: ProductColors.border),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  child: const Text('取消'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton.icon(
                  key: const Key('jd_evidence_save_button'),
                  onPressed: widget.isSaving ? null : _handleSave,
                  icon: widget.isSaving
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.save_outlined, size: 15),
                  label: Text(widget.isSaving ? '保存中' : '保存为项目证据'),
                  style: ElevatedButton.styleFrom(
                    minimumSize: const Size(0, 40),
                    backgroundColor: ProductColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    textStyle: AppTheme.ts(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w900,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _refreshErrors() {
    if (_submitted) {
      setState(() {});
    }
  }

  void _handleSave() {
    setState(() => _submitted = true);
    final title = _titleController.text.trim();
    final description = _descriptionController.text.trim();
    if (title.isEmpty || description.isEmpty) return;
    unawaited(
      widget.onSave(
        _ProjectEvidenceDraft(
          title: title,
          description: description,
          skillTags: _splitEvidenceTags(_skillsController.text),
          outcomes: _outcomesController.text.trim(),
        ),
      ),
    );
  }
}

class _EvidenceFormField extends StatelessWidget {
  final Key? fieldKey;
  final String label;
  final TextEditingController controller;
  final String? hint;
  final int? maxLength;
  final int minLines;
  final int maxLines;
  final String? errorText;
  final ValueChanged<String>? onChanged;

  const _EvidenceFormField({
    this.fieldKey,
    required this.label,
    required this.controller,
    this.hint,
    this.maxLength,
    this.minLines = 1,
    this.maxLines = 1,
    this.errorText,
    this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: AppTheme.ts(
            fontSize: 12,
            fontWeight: FontWeight.w900,
            color: ProductColors.text,
          ),
        ),
        const SizedBox(height: 7),
        TextField(
          key: fieldKey,
          controller: controller,
          minLines: minLines,
          maxLines: maxLines,
          maxLength: maxLength,
          onChanged: onChanged,
          decoration: _evidenceInputDecoration(
            hintText: hint ?? label.replaceAll(' *', ''),
            errorText: errorText,
          ),
          style: AppTheme.ts(
            fontSize: 12.5,
            height: 1.45,
            color: ProductColors.text,
          ),
        ),
      ],
    );
  }
}

class _EvidenceProjectSelectorField extends StatelessWidget {
  final String value;

  const _EvidenceProjectSelectorField({required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '关联项目 *',
          style: AppTheme.ts(
            fontSize: 12,
            fontWeight: FontWeight.w900,
            color: ProductColors.text,
          ),
        ),
        const SizedBox(height: 7),
        Row(
          children: [
            Expanded(
              child: Container(
                constraints: const BoxConstraints(minHeight: 42),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: ProductColors.surfaceSoft,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: ProductColors.border),
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.business_center_outlined,
                      size: 16,
                      color: ProductColors.primary,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        value,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w800,
                          color: ProductColors.text,
                        ),
                      ),
                    ),
                    const Icon(
                      Icons.keyboard_arrow_down_rounded,
                      size: 17,
                      color: ProductColors.textMuted,
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
              onPressed: () {
                ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                  const SnackBar(
                    content: Text('新建求职项目请从“求职项目”页进入；当前证据会先绑定到已选项目。'),
                  ),
                );
              },
              icon: const Icon(Icons.add_rounded, size: 14),
              label: const Text('新建项目'),
              style: OutlinedButton.styleFrom(
                minimumSize: const Size(0, 42),
                foregroundColor: ProductColors.primary,
                side: BorderSide(
                  color: ProductColors.primary.withValues(alpha: 0.18),
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                textStyle: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _EvidenceSuggestionChips extends StatelessWidget {
  final List<String> labels;

  const _EvidenceSuggestionChips({required this.labels});

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final label in labels)
          ProductTag(label: label, tone: ProductTone.primary),
      ],
    );
  }
}

class _EvidenceLinkedSourcesBlock extends StatelessWidget {
  const _EvidenceLinkedSourcesBlock();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
      decoration:
          ProductSurface.softCard(tone: ProductTone.neutral, radius: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.link_rounded,
                size: 16,
                color: ProductColors.textSecondary,
              ),
              const SizedBox(width: 8),
              Text(
                '附件 / 引用（可选）',
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: const [
              _EvidenceSourceChip(
                icon: Icons.article_outlined,
                label: '当前 JD',
                tone: ProductTone.info,
              ),
              _EvidenceSourceChip(
                icon: Icons.fact_check_outlined,
                label: '匹配报告',
                tone: ProductTone.primary,
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            '本次先保存为可追溯笔记，后续接入项目证据表和附件上传。',
            style: AppTheme.ts(
              fontSize: 11,
              height: 1.38,
              color: ProductColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _EvidenceSourceChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final ProductTone tone;

  const _EvidenceSourceChip({
    required this.icon,
    required this.label,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      height: 36,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: style.color),
          const SizedBox(width: 7),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 11.5,
              fontWeight: FontWeight.w800,
              color: ProductColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _InterviewPrepView extends StatelessWidget {
  final CareerApplicationView? application;
  final JobFitReportView? report;
  final JDAnalysisView? jd;
  final CareerPromptSender? onSendPrompt;
  final Future<void> Function(String title, String body) onSaveInterviewNote;

  const _InterviewPrepView({
    required this.application,
    required this.report,
    required this.jd,
    required this.onSendPrompt,
    required this.onSaveInterviewNote,
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
        onPressed: () => _sendJDPromptAction(
          context,
          sender: onSendPrompt,
          application: application,
          label: '生成面试准备题',
          actionType: 'interview_prep',
          origin: 'jd_match',
          detail: '围绕当前 JD 匹配报告的短板和关注点生成面试题、回答要点和追问。',
        ),
        child: const Text('生成面试题'),
      ),
      child: focus.isEmpty
          ? const _EmptyJDText(text: '暂无面试准备重点。')
          : Column(
              children: [
                _InterviewSummaryGrid(questionCount: focus.length),
                const SizedBox(height: 14),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final columns = constraints.maxWidth >= 900
                        ? 2
                        : constraints.maxWidth >= 560
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
                              onSaveNote: () => onSaveInterviewNote(
                                  _interviewTitle(i), focus[i]),
                              onMockAnswer: () => _sendMockInterview(
                                context,
                                _interviewTitle(i),
                                focus[i],
                              ),
                              onExpand: () => _showInterviewQuestionDialog(
                                context,
                                title: _interviewTitle(i),
                                body: focus[i],
                                difficulty: i == 0
                                    ? '高'
                                    : i == 1
                                        ? '中'
                                        : '中等',
                              ),
                            ),
                          ),
                      ],
                    );
                  },
                ),
              ],
            ),
    );
  }

  void _sendMockInterview(BuildContext context, String title, String body) {
    _sendJDPromptAction(
      context,
      sender: onSendPrompt,
      application: application,
      label: '模拟面试问答',
      actionType: 'interview_prep',
      origin: 'jd_match',
      detail: '围绕面试题“$title”生成模拟追问和回答要点。考察点：$body',
    );
  }

  void _showInterviewQuestionDialog(
    BuildContext context, {
    required String title,
    required String body,
    required String difficulty,
  }) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => _InterviewQuestionDetailDialog(
        title: title,
        body: body,
        difficulty: difficulty,
        onSaveNote: () async {
          await onSaveInterviewNote(title, body);
          if (dialogContext.mounted) {
            Navigator.of(dialogContext).pop();
          }
        },
        onMockAnswer: () {
          Navigator.of(dialogContext).pop();
          _sendMockInterview(context, title, body);
        },
      ),
    );
  }
}

class _InterviewSummaryGrid extends StatelessWidget {
  final int questionCount;

  const _InterviewSummaryGrid({required this.questionCount});

  @override
  Widget build(BuildContext context) {
    final cards = [
      const _InterviewMetric(
        label: '重点追问方向',
        value: '5',
        note: '基于 JD 差距',
        icon: Icons.radar_outlined,
        tone: ProductTone.purple,
      ),
      const _InterviewMetric(
        label: '答题难度',
        value: '中等',
        note: '仍需准备',
        icon: Icons.bar_chart_rounded,
        tone: ProductTone.warning,
      ),
      _InterviewMetric(
        label: '高频问题数',
        value: (questionCount * 3).toString(),
        note: '预计追问',
        icon: Icons.quiz_outlined,
        tone: ProductTone.info,
      ),
      const _InterviewMetric(
        label: '预计准备时长',
        value: '60-75',
        note: '分钟',
        icon: Icons.schedule_rounded,
        tone: ProductTone.primary,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 760 ? 4 : 2;
        const spacing = 10.0;
        final width =
            (constraints.maxWidth - spacing * (columns - 1)) / columns;
        return Wrap(
          spacing: spacing,
          runSpacing: spacing,
          children: [
            for (final card in cards) SizedBox(width: width, child: card),
          ],
        );
      },
    );
  }
}

class _InterviewMetric extends StatelessWidget {
  final String label;
  final String value;
  final String note;
  final IconData icon;
  final ProductTone tone;

  const _InterviewMetric({
    required this.label,
    required this.value,
    required this.note,
    required this.icon,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minHeight: 78),
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: ProductSurface.softCard(tone: tone, radius: 14),
      child: Row(
        children: [
          ProductIconTile(icon: icon, tone: tone, size: 36),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 20,
                    height: 1,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  label,
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
                  note,
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

class _JDRail extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? application;
  final JDAnalysisView? jd;
  final JobFitReportView? report;
  final CareerReadinessView? readiness;
  final _JDMatchTab activeTab;
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenResumes;
  final VoidCallback onOpenNotes;
  final CareerPromptSender? onSendPrompt;
  final void Function(_EvidenceDraftSeed seed) onOpenEvidenceDraft;
  final bool includePrimary;
  final bool includeRelated;

  const _JDRail({
    required this.provider,
    required this.application,
    required this.jd,
    required this.report,
    required this.readiness,
    required this.activeTab,
    required this.onOpenProjects,
    required this.onOpenResumes,
    required this.onOpenNotes,
    required this.onSendPrompt,
    required this.onOpenEvidenceDraft,
    this.includePrimary = true,
    this.includeRelated = true,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        if (includePrimary) ...[
          _CurrentDecisionCard(readiness: readiness, report: report),
          const SizedBox(height: 14),
          _JDNextStepCard(
            application: application,
            report: report,
            readiness: readiness,
            activeTab: activeTab,
            onSendPrompt: onSendPrompt,
            onOpenEvidenceDraft: onOpenEvidenceDraft,
          ),
        ],
        if (includePrimary && includeRelated) const SizedBox(height: 14),
        if (includeRelated) ...[
          _JDRelatedAssetsCard(
            provider: provider,
            application: application,
            jd: jd,
            report: report,
            onOpenProjects: onOpenProjects,
            onOpenResumes: onOpenResumes,
          ),
          const SizedBox(height: 14),
          _JDRelatedNotesCard(provider: provider, onOpenNotes: onOpenNotes),
        ],
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
            careerDisplaySummary(
              careerFirstNonEmpty(
                [readiness?.summary],
                fallback: '暂无当前判断。',
              ),
              maxChars: 132,
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
  final _JDMatchTab activeTab;
  final CareerPromptSender? onSendPrompt;
  final void Function(_EvidenceDraftSeed seed) onOpenEvidenceDraft;

  const _JDNextStepCard({
    required this.application,
    required this.report,
    required this.readiness,
    required this.activeTab,
    required this.onSendPrompt,
    required this.onOpenEvidenceDraft,
  });

  @override
  Widget build(BuildContext context) {
    final evidenceMode = activeTab == _JDMatchTab.evidence;
    final allActions = evidenceMode
        ? _jdEvidenceActions(report)
        : _jdActions(report, readiness);
    final actions = allActions.take(3).toList();
    return ProductSection(
      title: '推荐下一步',
      subtitle: evidenceMode ? '按证据缺口排序' : '按匹配收益排序',
      icon: Icons.auto_fix_high_outlined,
      tone: ProductTone.primary,
      trailing: evidenceMode
          ? null
          : TextButton(
              onPressed: () => _showJDNextActionsDialog(
                context,
                title: '全部推荐动作',
                actions: allActions,
                application: application,
                onSendPrompt: onSendPrompt,
                onOpenEvidenceDraft: onOpenEvidenceDraft,
              ),
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
              badge: actions[i].badge ?? (evidenceMode ? null : '${i + 1}'),
              actionLabel: actions[i].actionLabel ??
                  _jdActionButtonLabel(actions[i].actionType),
              onTap: () {
                if (actions[i].actionType == 'evidence_add') {
                  onOpenEvidenceDraft(
                    _EvidenceView._draftSeedForRequirement(actions[i].seedKey),
                  );
                  return;
                }
                _sendJDPromptAction(
                  context,
                  sender: onSendPrompt,
                  application: application,
                  label: actions[i].title,
                  actionType: actions[i].actionType,
                  origin: 'jd_match',
                  detail: actions[i].subtitle,
                );
              },
            ),
            if (i != actions.length - 1) const SizedBox(height: 8),
          ],
          if (evidenceMode) ...[
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () => _showJDNextActionsDialog(
                  context,
                  title: '全部证据建议',
                  actions: allActions,
                  application: application,
                  onSendPrompt: onSendPrompt,
                  onOpenEvidenceDraft: onOpenEvidenceDraft,
                ),
                icon: const Icon(Icons.arrow_forward_rounded, size: 14),
                label: const Text('查看全部建议'),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(0, 34),
                  foregroundColor: ProductColors.primary,
                  side: const BorderSide(color: ProductColors.borderStrong),
                  textStyle: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

void _showJDAssetLocationSnack(BuildContext context, String message) {
  ScaffoldMessenger.maybeOf(context)?.showSnackBar(
    SnackBar(content: Text(message)),
  );
}

bool _sendJDPromptAction(
  BuildContext context, {
  required CareerPromptSender? sender,
  required CareerApplicationView? application,
  required String label,
  required String actionType,
  required String origin,
  String? detail,
}) {
  final messenger = ScaffoldMessenger.maybeOf(context);
  if (application == null) {
    messenger?.showSnackBar(
      const SnackBar(content: Text('当前没有可用求职项目，暂时不能执行这个动作。')),
    );
    return false;
  }
  if (sender == null) {
    messenger?.showSnackBar(
      SnackBar(content: Text('已识别动作「$label」，但当前页面还没有接入 Agent 执行通道。')),
    );
    return false;
  }
  sendCareerPromptAction(
    sender: sender,
    application: application,
    label: label,
    actionType: actionType,
    origin: origin,
    detail: detail,
  );
  messenger?.showSnackBar(
    SnackBar(content: Text('已发起「$label」，完成后会刷新当前 JD 匹配结果。')),
  );
  return true;
}

Future<void> _showJDNextActionsDialog(
  BuildContext context, {
  required String title,
  required List<_JDAction> actions,
  required CareerApplicationView? application,
  required CareerPromptSender? onSendPrompt,
  required void Function(_EvidenceDraftSeed seed) onOpenEvidenceDraft,
}) async {
  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return Dialog(
        insetPadding: const EdgeInsets.all(24),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560, maxHeight: 680),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const ProductIconTile(
                      icon: Icons.auto_fix_high_outlined,
                      tone: ProductTone.primary,
                      size: 40,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            title,
                            style: AppTheme.ts(
                              fontSize: 18,
                              fontWeight: FontWeight.w900,
                              color: ProductColors.text,
                            ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            '这些动作会在当前 JD 匹配上下文里执行或打开对应草案。',
                            style: AppTheme.ts(
                              fontSize: 12.5,
                              color: ProductColors.textSecondary,
                            ),
                          ),
                        ],
                      ),
                    ),
                    ProductTag(
                      label: actions.length.toString(),
                      tone: ProductTone.primary,
                    ),
                    const SizedBox(width: 4),
                    IconButton(
                      tooltip: '关闭',
                      onPressed: () => Navigator.of(dialogContext).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                if (actions.isEmpty)
                  const _EmptyJDText(text: '暂无推荐动作。')
                else
                  Flexible(
                    child: ListView.separated(
                      shrinkWrap: true,
                      itemCount: actions.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 8),
                      itemBuilder: (_, index) {
                        final action = actions[index];
                        return ProductActionTile(
                          title: action.title,
                          subtitle: action.subtitle,
                          icon: action.icon,
                          tone: action.tone,
                          badge: action.badge,
                          actionLabel: action.actionLabel ??
                              _jdActionButtonLabel(action.actionType),
                          onTap: () {
                            Navigator.of(dialogContext).pop();
                            if (action.actionType == 'evidence_add') {
                              onOpenEvidenceDraft(
                                _EvidenceView._draftSeedForRequirement(
                                  action.seedKey,
                                ),
                              );
                              return;
                            }
                            _sendJDPromptAction(
                              context,
                              sender: onSendPrompt,
                              application: application,
                              label: action.title,
                              actionType: action.actionType,
                              origin: 'jd_match',
                              detail: action.subtitle,
                            );
                          },
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
            onTap: () => _showJDAssetLocationSnack(
              context,
              jd == null ? '当前还没有 JD 分析。' : '当前 JD 分析已经在本页展示。',
            ),
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
            onTap: () => _showJDAssetLocationSnack(
              context,
              report == null ? '当前还没有匹配报告。' : '当前匹配报告已经在本页展示。',
            ),
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

class _JDRelatedNotesCard extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final VoidCallback onOpenNotes;

  const _JDRelatedNotesCard({
    required this.provider,
    required this.onOpenNotes,
  });

  @override
  Widget build(BuildContext context) {
    final notes = provider.selectedApplicationDetail?.notes.take(4).toList() ??
        const <CareerNoteSummaryView>[];
    return ProductSection(
      title: '相关笔记',
      subtitle: notes.isEmpty ? '暂无关联笔记' : '${notes.length} 条面试和学习笔记',
      icon: Icons.sticky_note_2_outlined,
      tone: ProductTone.warning,
      child: notes.isEmpty
          ? const _EmptyJDText(text: '保存面试题、证据补充或学习任务后，会在这里形成关联笔记。')
          : Column(
              children: [
                for (var i = 0; i < notes.length; i++) ...[
                  _RelatedAssetRow(
                    title: notes[i].title,
                    subtitle: careerFormatDateTime(notes[i].updatedAt),
                    icon: Icons.notes_outlined,
                    tone: ProductTone.warning,
                    onTap: onOpenNotes,
                  ),
                  if (i != notes.length - 1) const SizedBox(height: 9),
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

class _SummaryInfoCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final ProductTone tone;
  final List<String> items;
  final String emptyText;

  const _SummaryInfoCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.tone,
    required this.items,
    required this.emptyText,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 13, 14, 13),
      decoration: ProductSurface.softCard(tone: tone, radius: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 17, color: style.color),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: AppTheme.ts(
                    fontSize: 13,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: AppTheme.ts(
              fontSize: 11,
              color: ProductColors.textMuted,
            ),
          ),
          const SizedBox(height: 10),
          if (items.isEmpty)
            _EmptyJDText(text: emptyText)
          else
            for (final item in items.take(4))
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.check_circle_outline_rounded,
                      size: 14,
                      color: style.color,
                    ),
                    const SizedBox(width: 7),
                    Expanded(
                      child: Text(
                        item,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.5,
                          height: 1.36,
                          fontWeight: FontWeight.w700,
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

class _EvidenceRow extends StatelessWidget {
  final int index;
  final String text;
  final ProductTone tone;
  final VoidCallback? onAddEvidence;

  const _EvidenceRow({
    required this.index,
    required this.text,
    required this.tone,
    this.onAddEvidence,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    final isMissing = onAddEvidence != null;
    final detail =
        isMissing ? _missingDetail(text) : _matchedDetail(index, text);
    final source = isMissing ? 'JD 要求' : _matchedSource(index);
    final badge = isMissing ? '待补' : _matchedBadge(index);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onAddEvidence,
      child: Container(
        padding: const EdgeInsets.fromLTRB(9, 8, 9, 8),
        decoration: BoxDecoration(
          color: style.soft.withValues(alpha: 0.62),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: style.color.withValues(alpha: 0.13)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 20,
              height: 20,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: style.color,
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
            const SizedBox(width: 7),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    text,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 11.8,
                      fontWeight: FontWeight.w900,
                      color: ProductColors.text,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    detail,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 10.5,
                      height: 1.22,
                      color: ProductColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 5,
                    runSpacing: 3,
                    children: [
                      _EvidenceMetaChip(label: source, tone: tone),
                      _EvidenceMetaChip(label: badge, tone: tone),
                    ],
                  ),
                ],
              ),
            ),
            if (onAddEvidence != null) ...[
              const SizedBox(width: 7),
              TextButton(
                onPressed: onAddEvidence,
                style: TextButton.styleFrom(
                  minimumSize: const Size(0, 26),
                  padding: const EdgeInsets.symmetric(horizontal: 7),
                  foregroundColor: style.color,
                  textStyle: AppTheme.ts(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                child: const Text('补充证据'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  static String _matchedDetail(int index, String text) {
    final normalized = text.trim();
    if (normalized.contains('Python')) {
      return '项目经历与基础简历均体现后端开发年限，可直接支撑硬性要求。';
    }
    if (normalized.contains('FastAPI')) {
      return '服务端项目中使用 FastAPI 构建接口服务，技术栈与 JD 要求匹配。';
    }
    if (normalized.contains('PostgreSQL') || normalized.contains('Redis')) {
      return '项目记录中包含数据库与缓存实践，能支撑工程落地能力。';
    }
    if (normalized.contains('Runtime') || normalized.contains('Agent')) {
      return '多 Agent 调度、工具调用和任务状态维护经验可支撑岗位核心职责。';
    }
    if (normalized.contains('SSE') || normalized.contains('流式')) {
      return '流式输出和稳定性优化记录可作为响应链路优化证据。';
    }
    return index <= 4 ? '来自简历和项目经历，可用于解释当前匹配分数。' : '来自项目记录或投递材料，可作为辅助匹配证据。';
  }

  static String _missingDetail(String text) {
    final normalized = text.trim();
    if (normalized.contains('LangGraph')) {
      return 'JD 要求具备 LangGraph 实战经验，当前缺少明确项目证据。';
    }
    if (normalized.contains('RAG')) {
      return '当前缺少召回、重排、评估指标等可验证的 RAG 深度实践。';
    }
    if (normalized.contains('Redis') || normalized.contains('队列')) {
      return '需要补充高并发、队列或缓存体系中的具体实现和指标。';
    }
    return '当前材料中缺少直接证据，建议补充项目描述或创建学习任务。';
  }

  static String _matchedSource(int index) {
    if (index <= 3) return '来源：简历 v3.2';
    if (index <= 6) return '来源：项目记录';
    return '来源：职业画像';
  }

  static String _matchedBadge(int index) {
    if (index <= 3) return '高匹配';
    if (index <= 6) return '可引用';
    return '辅助证据';
  }
}

class _EvidenceMetaChip extends StatelessWidget {
  final String label;
  final ProductTone tone;

  const _EvidenceMetaChip({
    required this.label,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      height: 18,
      padding: const EdgeInsets.symmetric(horizontal: 7),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: style.color.withValues(alpha: 0.18)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 9.6,
              fontWeight: FontWeight.w800,
              color: style.color,
            ),
          ),
        ],
      ),
    );
  }
}

class _InterviewQuestionCard extends StatelessWidget {
  final String title;
  final String body;
  final String difficulty;
  final Future<void> Function() onSaveNote;
  final VoidCallback onMockAnswer;
  final VoidCallback onExpand;

  const _InterviewQuestionCard({
    required this.title,
    required this.body,
    required this.difficulty,
    required this.onSaveNote,
    required this.onMockAnswer,
    required this.onExpand,
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
          const SizedBox(height: 11),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _MiniOutlineButton(
                label: '保存为笔记',
                icon: Icons.bookmark_border,
                onTap: () => unawaited(onSaveNote()),
              ),
              _MiniOutlineButton(
                label: '模拟问答',
                icon: Icons.chat_outlined,
                onTap: onMockAnswer,
              ),
              _MiniOutlineButton(
                label: '展开要点',
                icon: Icons.expand_more,
                onTap: onExpand,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MiniOutlineButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback onTap;

  const _MiniOutlineButton({
    required this.label,
    required this.icon,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: ProductColors.surface,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          height: 28,
          padding: const EdgeInsets.symmetric(horizontal: 9),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: ProductColors.border),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 13, color: ProductColors.primary),
              const SizedBox(width: 5),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 10.8,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.primary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InterviewQuestionDetailDialog extends StatelessWidget {
  final String title;
  final String body;
  final String difficulty;
  final Future<void> Function() onSaveNote;
  final VoidCallback onMockAnswer;

  const _InterviewQuestionDetailDialog({
    required this.title,
    required this.body,
    required this.difficulty,
    required this.onSaveNote,
    required this.onMockAnswer,
  });

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 680),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 20, 22, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          title,
                          style: AppTheme.ts(
                            fontSize: 20,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.text,
                          ),
                        ),
                        const SizedBox(height: 10),
                        ProductTag(
                          label: '难度 $difficulty',
                          tone: ProductTone.purple,
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: '关闭',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              _DialogInfoBlock(
                title: '考察点',
                icon: Icons.psychology_alt_outlined,
                child: Text(
                  body.trim().isEmpty ? '暂无考察点说明。' : body.trim(),
                  style: AppTheme.ts(
                    fontSize: 13,
                    height: 1.55,
                    color: ProductColors.textSecondary,
                  ),
                ),
              ),
              const SizedBox(height: 10),
              _DialogInfoBlock(
                title: '回答组织',
                icon: Icons.format_list_numbered_rounded,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    _AnswerHint(text: '先用 1-2 句话说明项目场景、目标和约束。'),
                    _AnswerHint(text: '再讲具体方案、关键技术取舍和复杂点。'),
                    _AnswerHint(text: '补充指标结果，例如稳定性、延迟、成本或效率变化。'),
                    _AnswerHint(text: '最后说明复盘改进，避免只停留在方案描述。'),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              Row(
                children: [
                  const Spacer(),
                  OutlinedButton.icon(
                    onPressed: () => unawaited(onSaveNote()),
                    icon: const Icon(Icons.bookmark_border, size: 16),
                    label: const Text('保存为笔记'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: ProductColors.primary,
                      side: const BorderSide(color: ProductColors.borderStrong),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  ElevatedButton.icon(
                    onPressed: onMockAnswer,
                    icon:
                        const Icon(Icons.chat_bubble_outline_rounded, size: 16),
                    label: const Text('模拟问答'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: ProductColors.primary,
                      foregroundColor: Colors.white,
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DialogInfoBlock extends StatelessWidget {
  final String title;
  final IconData icon;
  final Widget child;

  const _DialogInfoBlock({
    required this.title,
    required this.icon,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 17, color: ProductColors.primary),
              const SizedBox(width: 8),
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }
}

class _AnswerHint extends StatelessWidget {
  final String text;

  const _AnswerHint({required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(top: 5),
            child: Icon(
              Icons.check_circle_rounded,
              size: 13,
              color: ProductColors.primary,
            ),
          ),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              text,
              style: AppTheme.ts(
                fontSize: 12.5,
                height: 1.45,
                color: ProductColors.textSecondary,
              ),
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

class _EvidenceDraftSeed {
  final String title;
  final String description;

  const _EvidenceDraftSeed({
    required this.title,
    required this.description,
  });
}

class _ProjectEvidenceDraft {
  final String title;
  final String description;
  final List<String> skillTags;
  final String outcomes;

  const _ProjectEvidenceDraft({
    required this.title,
    required this.description,
    required this.skillTags,
    required this.outcomes,
  });
}

List<String> _splitEvidenceTags(String value) {
  final seen = <String>{};
  final items = <String>[];
  for (final raw in value.split(RegExp(r'[,，、\s]+'))) {
    final item = raw.trim();
    if (item.isEmpty || !seen.add(item)) continue;
    items.add(item);
    if (items.length >= 8) break;
  }
  return items;
}

InputDecoration _evidenceInputDecoration({
  required String hintText,
  String? errorText,
}) {
  return InputDecoration(
    hintText: hintText,
    errorText: errorText,
    counterStyle: AppTheme.ts(
      fontSize: 10.5,
      color: ProductColors.textMuted,
    ),
    hintStyle: AppTheme.ts(
      fontSize: 12,
      color: ProductColors.textMuted,
    ),
    filled: true,
    fillColor: ProductColors.surface,
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: ProductColors.border),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: ProductColors.primary),
    ),
    errorBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: ProductColors.danger),
    ),
    focusedErrorBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: ProductColors.danger),
    ),
  );
}

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
  final String? badge;
  final String? actionLabel;
  final String seedKey;

  const _JDAction({
    required this.title,
    required this.subtitle,
    required this.actionType,
    required this.icon,
    required this.tone,
    this.badge,
    this.actionLabel,
    String? seedKey,
  }) : seedKey = seedKey ?? title;
}

class _JDHeroAction {
  final String label;
  final String actionType;
  final IconData icon;

  const _JDHeroAction({
    required this.label,
    required this.actionType,
    required this.icon,
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

_JDHeroAction _jdHeroPrimaryAction({
  required CareerApplicationView? app,
  required JDAnalysisView? jd,
  required JobFitReportView? report,
}) {
  if (jd == null) {
    return const _JDHeroAction(
      label: '粘贴 JD 并解析',
      actionType: 'jd_match_analysis',
      icon: Icons.article_outlined,
    );
  }
  if (app?.resumeProfileId?.trim().isEmpty ?? true) {
    return const _JDHeroAction(
      label: '上传简历画像',
      actionType: 'resume_upload',
      icon: Icons.upload_file_outlined,
    );
  }
  if (report == null) {
    return const _JDHeroAction(
      label: '生成匹配报告',
      actionType: 'jd_match_analysis',
      icon: Icons.fact_check_outlined,
    );
  }
  if (report.gaps.isNotEmpty) {
    return const _JDHeroAction(
      label: '优化简历差距',
      actionType: 'gap_optimize',
      icon: Icons.auto_fix_high_outlined,
    );
  }
  if (app?.resumeVersionIds.isEmpty ?? true) {
    return const _JDHeroAction(
      label: '生成定制简历',
      actionType: 'custom_resume',
      icon: Icons.description_outlined,
    );
  }
  return const _JDHeroAction(
    label: '查看面试准备',
    actionType: 'interview_prep',
    icon: Icons.forum_outlined,
  );
}

List<_ScoreDimension> _scoreCards(
  JobFitReportView? report,
  CareerReadinessView? readiness,
) {
  final entries = report?.scoreBreakdown.entries.toList() ?? const [];
  final cards = [
    for (final entry in entries)
      _ScoreDimension(
        label: _scoreLabel(entry.key),
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
      title: '优化简历差距',
      subtitle: directions.isEmpty ? '把岗位短板转成简历项目证据。' : directions.first,
      actionType: 'resume_optimize',
      icon: Icons.edit_note_outlined,
      tone: ProductTone.warning,
    ),
    _JDAction(
      title: '创建学习任务',
      subtitle: directions.length > 1 ? directions[1] : '完善 RAG、检索质量和评估指标表达。',
      actionType: 'learning_task',
      icon: Icons.school_outlined,
      tone: ProductTone.primary,
    ),
    _JDAction(
      title: '生成面试题',
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

List<_JDAction> _jdEvidenceActions(JobFitReportView? report) {
  final gaps = _dynamicSnippets(report?.gaps ?? const [], limit: 4)
      .join(' ')
      .toLowerCase();
  return [
    _JDAction(
      title: '补充 LangGraph 实践经验',
      subtitle: gaps.contains('langgraph')
          ? '补齐多 Agent 编排、状态管理和异常恢复证据。'
          : '补齐多 Agent 任务编排和状态管理项目证据。',
      actionType: 'evidence_add',
      icon: Icons.warning_amber_rounded,
      tone: ProductTone.warning,
      badge: '优先',
      actionLabel: '补充',
      seedKey: 'LangGraph 实战经验',
    ),
    const _JDAction(
      title: '完善 RAG 评估与量化数据',
      subtitle: '补充召回、重排、评估指标和可验证优化结果。',
      actionType: 'evidence_add',
      icon: Icons.auto_graph_outlined,
      tone: ProductTone.info,
      actionLabel: '完善',
      seedKey: 'RAG 召回-重排-评估闭环',
    ),
    const _JDAction(
      title: '补充高并发 SSE 优化数据',
      subtitle: '补齐吞吐、延迟、稳定性和错误恢复指标。',
      actionType: 'evidence_add',
      icon: Icons.bolt_outlined,
      tone: ProductTone.info,
      actionLabel: '补充',
      seedKey: '高并发 SSE 优化量化结果',
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
  if (value.contains('technical') || value.contains('stack')) {
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

String _scoreLabel(String label) {
  final value = label.trim();
  final lower = value.toLowerCase();
  if (lower.contains('engineering')) return '工程能力';
  if (lower.contains('interview')) return '面试准备度';
  if (lower.contains('langchain')) return 'LangChain 经验';
  if (lower.contains('project')) return '项目经历';
  if (lower.contains('rag')) return 'RAG 经验';
  if (lower.contains('agent') || lower.contains('llm')) return 'Agent / LLM 经验';
  if (lower.contains('skill') ||
      lower.contains('technical') ||
      lower.contains('stack')) {
    return '技术栈匹配';
  }
  if (!value.contains('_')) return value;
  return value
      .split('_')
      .where((part) => part.trim().isNotEmpty)
      .map((part) => switch (part.toLowerCase()) {
            'match' => '匹配',
            'gap' => '差距',
            'capability' => '能力',
            'experience' => '经验',
            'readiness' => '准备度',
            _ => part,
          })
      .join(' ');
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

String _jdActionButtonLabel(String actionType) {
  return switch (actionType) {
    'resume_optimize' => '去优化',
    'learning_task' => '去创建',
    'evidence_add' => '去补充',
    'interview_prep' => '去生成',
    'custom_resume' => '去生成',
    'jd_match_analysis' => '去分析',
    _ => '查看',
  };
}
