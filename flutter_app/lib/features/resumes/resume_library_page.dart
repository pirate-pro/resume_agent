import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../../shared/widgets/product_components.dart';
import '../career_ui/career_ui_helpers.dart';
import '../career_workbench/career_workbench_provider.dart';

class ResumeLibraryPage extends ConsumerStatefulWidget {
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenJDMatch;
  final CareerPromptSender? onSendPrompt;

  const ResumeLibraryPage({
    super.key,
    required this.onOpenProjects,
    required this.onOpenJDMatch,
    this.onSendPrompt,
  });

  @override
  ConsumerState<ResumeLibraryPage> createState() => _ResumeLibraryPageState();
}

class _ResumeLibraryPageState extends ConsumerState<ResumeLibraryPage> {
  String? _selectedKey;

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
      return _ResumeError(
        error: provider.error!,
        onRetry: () => unawaited(provider.refresh()),
      );
    }

    final records = _resumeRecords(provider);
    final selected = _selectedRecord(records);
    final linkedApplication = _linkedApplication(provider, selected);
    final baseProfile = _baseResumeProfile(provider, selected);
    final careerProfile = _bestCareerProfile(provider, linkedApplication);

    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= ProductBreakpoints.contentRail;
        final header = _ResumeHeader(
          provider: provider,
          onRefresh: () => unawaited(_refresh(provider)),
          onGenerateVersion: () => _sendGenerateVersion(linkedApplication),
        );
        final stats = _ResumeStatsStrip(provider: provider);
        final list = _ResumeRecordList(
          records: records,
          selectedKey: selected?.key,
          isLoading: provider.isLoadingAssetLibrary,
          onSelected: (record) => setState(() => _selectedKey = record.key),
          onGenerateVersion: () => _sendGenerateVersion(linkedApplication),
        );
        final preview = _ResumePreviewCard(
          selected: selected,
          baseProfile: baseProfile,
          careerProfile: careerProfile,
          linkedApplication: linkedApplication,
          onOptimize: () => _sendOptimizeResume(linkedApplication, selected),
          onGenerateVersion: () => _sendGenerateVersion(linkedApplication),
        );
        final rail = _ResumeRightRail(
          provider: provider,
          selected: selected,
          baseProfile: baseProfile,
          careerProfile: careerProfile,
          linkedApplication: linkedApplication,
          onOpenProjects: widget.onOpenProjects,
          onOpenJDMatch: widget.onOpenJDMatch,
          onSendPrompt: widget.onSendPrompt,
        );
        final history = _VersionHistory(
          versions: provider.resumeVersions,
          selectedKey: selected?.key,
          onSelected: (version) => setState(
            () => _selectedKey = _ResumeRecord.fromResumeVersion(version).key,
          ),
        );

        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              header,
              const SizedBox(height: 14),
              stats,
              const SizedBox(height: 14),
              list,
              const SizedBox(height: 14),
              preview,
              const SizedBox(height: 14),
              rail,
              const SizedBox(height: 14),
              history,
            ],
          );
        }
        return ListView(
          padding: EdgeInsets.zero,
          children: [
            header,
            const SizedBox(height: 14),
            stats,
            const SizedBox(height: 16),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(width: 320, child: list),
                const SizedBox(width: 16),
                Expanded(child: preview),
                const SizedBox(width: 16),
                SizedBox(width: 340, child: rail),
              ],
            ),
            const SizedBox(height: 16),
            history,
          ],
        );
      },
    );
  }

  _ResumeRecord? _selectedRecord(List<_ResumeRecord> records) {
    if (records.isEmpty) return null;
    final selectedKey = _selectedKey;
    if (selectedKey != null) {
      for (final record in records) {
        if (record.key == selectedKey) return record;
      }
    }
    return records.first;
  }

  Future<void> _refresh(CareerWorkbenchProvider provider) async {
    await provider.refresh();
    await provider.loadAssetLibrary(force: true);
  }

  void _sendGenerateVersion(CareerApplicationView? app) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: '生成简历新版本',
      actionType: 'custom_resume',
      origin: 'resume_library',
      detail: '复用当前项目里的简历画像、职业画像、JD 分析和匹配报告，生成一个可预览的定制简历版本。',
    );
  }

  void _sendOptimizeResume(CareerApplicationView? app, _ResumeRecord? record) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: '优化此版本',
      actionType: 'resume_optimize',
      origin: 'resume_library',
      detail: record == null
          ? '请基于当前求职项目优化简历。'
          : '请基于 ${record.title} 的内容继续优化简历表达、关键词和项目证据。',
    );
  }
}

class _ResumeHeader extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final VoidCallback onRefresh;
  final VoidCallback onGenerateVersion;

  const _ResumeHeader({
    required this.provider,
    required this.onRefresh,
    required this.onGenerateVersion,
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
                    '简历资料',
                    style: AppTheme.ts(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: ProductColors.text,
                    ),
                  ),
                  ProductTag(
                    label: '版本管理',
                    tone: ProductTone.info,
                    icon: Icons.description_outlined,
                  ),
                  if (provider.isLoadingAssetLibrary || provider.isRefreshing)
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
                '管理与优化你的简历版本，打造更具竞争力的求职材料。',
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
                child: ElevatedButton.icon(
                  onPressed: onGenerateVersion,
                  icon: const Icon(Icons.add_rounded, size: 17),
                  label: const Text('生成新版本'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: ProductColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
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

class _ResumeStatsStrip extends StatelessWidget {
  final CareerWorkbenchProvider provider;

  const _ResumeStatsStrip({required this.provider});

  @override
  Widget build(BuildContext context) {
    final targetedVersions = provider.resumeVersions
        .where((item) => item.targetJdAnalysisId?.trim().isNotEmpty == true)
        .length;
    final latest = _latestResumeUpdatedAt(provider);
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 980
            ? 4
            : constraints.maxWidth >= 620
                ? 2
                : 1;
        const spacing = 12.0;
        final width =
            (constraints.maxWidth - spacing * (columns - 1)) / columns;
        final cards = [
          ProductMetricCard(
            label: '简历版本',
            value: provider.resumeVersions.length.toString(),
            trend: '全部版本',
            icon: Icons.description_outlined,
            tone: ProductTone.info,
          ),
          ProductMetricCard(
            label: '已优化次数',
            value: provider.resumeVersions
                .fold<int>(0, (sum, item) => sum + item.changeSummary.length)
                .toString(),
            trend: '累计优化',
            icon: Icons.bolt_outlined,
            tone: ProductTone.primary,
          ),
          ProductMetricCard(
            label: '针对岗位版本',
            value: targetedVersions.toString(),
            trend: '面向不同岗位',
            icon: Icons.workspaces_outline,
            tone: ProductTone.purple,
          ),
          ProductMetricCard(
            label: '最近更新',
            value: latest == null ? '-' : careerFormatDateTime(latest),
            trend: '资料库状态',
            icon: Icons.update_rounded,
            tone: ProductTone.primary,
          ),
        ];
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

class _ResumeRecordList extends StatelessWidget {
  final List<_ResumeRecord> records;
  final String? selectedKey;
  final bool isLoading;
  final ValueChanged<_ResumeRecord> onSelected;
  final VoidCallback onGenerateVersion;

  const _ResumeRecordList({
    required this.records,
    required this.selectedKey,
    required this.isLoading,
    required this.onSelected,
    required this.onGenerateVersion,
  });

  @override
  Widget build(BuildContext context) {
    return ProductSection(
      title: '版本列表',
      subtitle: '${records.length} 项资料',
      icon: Icons.view_list_outlined,
      tone: ProductTone.primary,
      trailing: IconButton(
        tooltip: '生成新版本',
        onPressed: onGenerateVersion,
        icon: const Icon(Icons.add_rounded),
      ),
      child: isLoading && records.isEmpty
          ? const SizedBox(
              height: 120,
              child: Center(
                child: CircularProgressIndicator(color: ProductColors.primary),
              ),
            )
          : records.isEmpty
              ? const _EmptyResumeText(
                  text: '还没有简历资料。可以先上传简历并让 Agent 生成画像。',
                )
              : Column(
                  children: [
                    for (final record in records) ...[
                      _ResumeRecordTile(
                        record: record,
                        selected: selectedKey == record.key,
                        onTap: () => onSelected(record),
                      ),
                      if (record != records.last) const SizedBox(height: 10),
                    ],
                  ],
                ),
    );
  }
}

class _ResumeRecordTile extends StatelessWidget {
  final _ResumeRecord record;
  final bool selected;
  final VoidCallback onTap;

  const _ResumeRecordTile({
    required this.record,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final tone = record.tone;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
          decoration: BoxDecoration(
            color: selected
                ? ProductColors.primarySoft
                : productToneStyle(tone).soft.withValues(alpha: 0.32),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: selected
                  ? ProductColors.primary.withValues(alpha: 0.45)
                  : ProductColors.border,
            ),
          ),
          child: Row(
            children: [
              ProductIconTile(icon: record.icon, tone: tone, size: 40),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          record.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 12.6,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.text,
                          ),
                        ),
                        if (selected)
                          ProductTag(label: '当前使用', tone: ProductTone.primary),
                      ],
                    ),
                    const SizedBox(height: 5),
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
              _MiniScore(score: record.score),
            ],
          ),
        ),
      ),
    );
  }
}

class _ResumePreviewCard extends StatelessWidget {
  final _ResumeRecord? selected;
  final ResumeProfileView? baseProfile;
  final CareerProfileView? careerProfile;
  final CareerApplicationView? linkedApplication;
  final VoidCallback onOptimize;
  final VoidCallback onGenerateVersion;

  const _ResumePreviewCard({
    required this.selected,
    required this.baseProfile,
    required this.careerProfile,
    required this.linkedApplication,
    required this.onOptimize,
    required this.onGenerateVersion,
  });

  @override
  Widget build(BuildContext context) {
    if (selected == null && baseProfile == null) {
      return ProductCard(
        padding: const EdgeInsets.fromLTRB(22, 22, 22, 22),
        child: const _EmptyResumeText(
          text: '上传简历后，这里会展示可预览的简历资料和优化建议。',
        ),
      );
    }
    final name = _resumeName(baseProfile);
    final role = careerFirstNonEmpty(
      [
        linkedApplication?.position,
        careerProfile?.targetRoles.isEmpty == false
            ? careerProfile!.targetRoles.first
            : null,
        selected?.title,
      ],
      fallback: '求职候选人',
    );
    final skills = _resumeSkills(baseProfile, careerProfile, selected);
    final projects = _resumeProjects(baseProfile);
    final work = _resumeWork(baseProfile);
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
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
                          selected?.title ?? '简历预览',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 16,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.text,
                          ),
                        ),
                        ProductTag(
                          label: selected?.kindLabel ?? '简历资料',
                          tone: selected?.tone ?? ProductTone.info,
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      selected == null
                          ? '资料预览'
                          : '更新于 ${careerFormatDateTime(selected!.updatedAt)}',
                      style: AppTheme.ts(
                        fontSize: 11.5,
                        color: ProductColors.textMuted,
                      ),
                    ),
                  ],
                ),
              ),
              Wrap(
                spacing: 8,
                children: [
                  OutlinedButton.icon(
                    onPressed: onOptimize,
                    icon: const Icon(Icons.tune_rounded, size: 16),
                    label: const Text('优化此版本'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: ProductColors.primary,
                      side: const BorderSide(color: ProductColors.border),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(11),
                      ),
                    ),
                  ),
                  ElevatedButton.icon(
                    onPressed: onGenerateVersion,
                    icon: const Icon(Icons.add_rounded, size: 16),
                    label: const Text('生成新版本'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: ProductColors.primary,
                      foregroundColor: Colors.white,
                      elevation: 0,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(11),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 16),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(28, 26, 28, 26),
            decoration: BoxDecoration(
              color: ProductColors.surface,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: ProductColors.border),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.04),
                  blurRadius: 18,
                  offset: const Offset(0, 10),
                ),
              ],
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: AppTheme.ts(
                    fontSize: 25,
                    height: 1,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  role,
                  style: AppTheme.ts(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    color: ProductColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 12,
                  runSpacing: 6,
                  children: [
                    _ResumeContact(
                        icon: Icons.location_on_outlined, text: '北京'),
                    _ResumeContact(
                        icon: Icons.phone_outlined, text: '138-****-8888'),
                    _ResumeContact(
                        icon: Icons.email_outlined,
                        text: 'zhangming@example.com'),
                    _ResumeContact(
                        icon: Icons.link_outlined,
                        text: 'github.com/zhangming'),
                  ],
                ),
                const SizedBox(height: 18),
                _ResumePaperSection(
                  title: '个人简介',
                  body: careerFirstNonEmpty(
                    [
                      baseProfile?.selfEvaluation,
                      careerProfile?.experienceSummary,
                      selected?.summary,
                    ],
                    fallback: '具备后端工程、Agent 应用和项目交付经验，能够围绕目标岗位持续优化简历表达。',
                  ),
                ),
                _ResumePaperSection(
                  title: '工作经历',
                  body: work,
                ),
                _ResumePaperSection(
                  title: '项目经历',
                  body: projects,
                ),
                _ResumePaperSection(
                  title: '核心技能',
                  body: skills.join(' / '),
                  last: true,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ResumeRightRail extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final _ResumeRecord? selected;
  final ResumeProfileView? baseProfile;
  final CareerProfileView? careerProfile;
  final CareerApplicationView? linkedApplication;
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenJDMatch;
  final CareerPromptSender? onSendPrompt;

  const _ResumeRightRail({
    required this.provider,
    required this.selected,
    required this.baseProfile,
    required this.careerProfile,
    required this.linkedApplication,
    required this.onOpenProjects,
    required this.onOpenJDMatch,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _AIInsightCard(
          selected: selected,
          baseProfile: baseProfile,
          careerProfile: careerProfile,
        ),
        const SizedBox(height: 14),
        _ResumePushActions(
          selected: selected,
          linkedApplication: linkedApplication,
          onOpenJDMatch: onOpenJDMatch,
          onSendPrompt: onSendPrompt,
        ),
        const SizedBox(height: 14),
        _RelatedJobsCard(
          applications:
              provider.applications.map((item) => item.application).toList(),
          selected: selected,
          onOpenProjects: onOpenProjects,
        ),
        const SizedBox(height: 14),
        _ResumeAssetsCard(
          provider: provider,
          selected: selected,
        ),
      ],
    );
  }
}

class _AIInsightCard extends StatelessWidget {
  final _ResumeRecord? selected;
  final ResumeProfileView? baseProfile;
  final CareerProfileView? careerProfile;

  const _AIInsightCard({
    required this.selected,
    required this.baseProfile,
    required this.careerProfile,
  });

  @override
  Widget build(BuildContext context) {
    final score = selected?.score ?? _diagnosisScore(baseProfile);
    final strengths = [
      ...careerProfile?.strengths ?? const <String>[],
      ...selected?.keywords ?? const <String>[],
    ].take(3).toList();
    final risks = [
      ...careerProfile?.resumeIssues ?? const <String>[],
      ...selected?.risks ?? const <String>[],
    ].take(3).toList();
    return ProductSection(
      title: 'AI 洞察',
      subtitle: '匹配分析和可优化点',
      icon: Icons.auto_awesome_outlined,
      tone: careerScoreTone(score),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ProductScoreRing(score: score, size: 76, label: '整体评分'),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  score == null
                      ? '完成简历诊断后会生成评分和优化建议。'
                      : '简历亮点突出，和目标岗位匹配度较高，仍有可优化空间。',
                  style: AppTheme.ts(
                    fontSize: 12.2,
                    height: 1.48,
                    color: ProductColors.textSecondary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          _MiniBulletBlock(
            title: '亮点',
            items: strengths.isEmpty ? const ['项目经验丰富，技术栈匹配度较高'] : strengths,
            tone: ProductTone.primary,
          ),
          const SizedBox(height: 10),
          _MiniBulletBlock(
            title: '缺失项',
            items: risks.isEmpty ? const ['可进一步补充量化结果和业务影响'] : risks,
            tone: ProductTone.warning,
          ),
        ],
      ),
    );
  }
}

class _ResumePushActions extends StatelessWidget {
  final _ResumeRecord? selected;
  final CareerApplicationView? linkedApplication;
  final VoidCallback onOpenJDMatch;
  final CareerPromptSender? onSendPrompt;

  const _ResumePushActions({
    required this.selected,
    required this.linkedApplication,
    required this.onOpenJDMatch,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    return ProductSection(
      title: '推荐动作',
      subtitle: '围绕当前简历继续推进',
      icon: Icons.auto_fix_high_outlined,
      tone: ProductTone.primary,
      child: Column(
        children: [
          ProductActionTile(
            title: '优化项目描述，突出业务价值',
            subtitle: '补充项目指标、技术难点和结果影响。',
            icon: Icons.tune_rounded,
            tone: ProductTone.primary,
            actionLabel: '预计 5 分钟',
            onTap: () => _sendResumeAction(
              '优化简历项目描述',
              '请优化 ${selected?.title ?? '当前简历'} 的项目描述，突出业务价值、工程难点和量化指标。',
            ),
          ),
          const SizedBox(height: 8),
          ProductActionTile(
            title: '补充开源项目与技术博客链接',
            subtitle: '提升工程可信度和证据完整度。',
            icon: Icons.link_outlined,
            tone: ProductTone.info,
            actionLabel: '预计 10 分钟',
            onTap: () => _sendResumeAction(
              '补充简历证据链接',
              '请基于当前求职项目梳理简历中可补充的开源项目、技术博客和证据链接。',
            ),
          ),
          const SizedBox(height: 8),
          ProductActionTile(
            title: '生成针对该岗位的求职信',
            subtitle: '结合当前简历和 JD 生成简洁求职信。',
            icon: Icons.mail_outline_rounded,
            tone: ProductTone.warning,
            actionLabel: '预计 5 分钟',
            onTap: onOpenJDMatch,
          ),
        ],
      ),
    );
  }

  void _sendResumeAction(String label, String detail) {
    sendCareerPromptAction(
      sender: onSendPrompt,
      application: linkedApplication,
      label: label,
      actionType: 'resume_optimize',
      origin: 'resume_library',
      detail: detail,
    );
  }
}

class _RelatedJobsCard extends StatelessWidget {
  final List<CareerApplicationView> applications;
  final _ResumeRecord? selected;
  final VoidCallback onOpenProjects;

  const _RelatedJobsCard({
    required this.applications,
    required this.selected,
    required this.onOpenProjects,
  });

  @override
  Widget build(BuildContext context) {
    final related = applications
        .where((app) => _isApplicationLinkedToRecord(app, selected))
        .take(3)
        .toList();
    return ProductSection(
      title: '关联岗位',
      subtitle: '当前简历正在服务的目标岗位',
      icon: Icons.business_center_outlined,
      tone: ProductTone.warning,
      trailing: TextButton(
        onPressed: onOpenProjects,
        child: const Text('查看全部'),
      ),
      child: related.isEmpty
          ? const _EmptyResumeText(text: '暂无关联岗位。')
          : Column(
              children: [
                for (final app in related) ...[
                  _RelatedJobRow(application: app, onTap: onOpenProjects),
                  if (app != related.last) const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _ResumeAssetsCard extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final _ResumeRecord? selected;

  const _ResumeAssetsCard({
    required this.provider,
    required this.selected,
  });

  @override
  Widget build(BuildContext context) {
    final items = [
      _AssetCount(
          '项目亮点梳理.md',
          '更新于 ${careerFormatDate(provider.workbench?.updatedAt)}',
          Icons.description_outlined),
      _AssetCount('前端技术栈总结.pdf', '更新于 ${careerFormatDate(selected?.updatedAt)}',
          Icons.picture_as_pdf_outlined),
      _AssetCount('面试题与答案.md', '${provider.notes.length} 条笔记',
          Icons.sticky_note_2_outlined),
    ];
    return ProductSection(
      title: '关联资产',
      subtitle: '和简历优化相关的资料',
      icon: Icons.folder_copy_outlined,
      tone: ProductTone.info,
      child: Column(
        children: [
          for (final item in items) ...[
            _AssetLine(item: item),
            if (item != items.last) const SizedBox(height: 9),
          ],
        ],
      ),
    );
  }
}

class _VersionHistory extends StatelessWidget {
  final List<ResumeVersionView> versions;
  final String? selectedKey;
  final ValueChanged<ResumeVersionView> onSelected;

  const _VersionHistory({
    required this.versions,
    required this.selectedKey,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return ProductSection(
      title: '版本历史',
      subtitle: '按时间查看简历迭代',
      icon: Icons.history_rounded,
      tone: ProductTone.primary,
      child: versions.isEmpty
          ? const _EmptyResumeText(text: '暂无简历版本历史。')
          : SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final version in versions) ...[
                    _VersionHistoryTile(
                      version: version,
                      selected: selectedKey ==
                          _ResumeRecord.fromResumeVersion(version).key,
                      onTap: () => onSelected(version),
                    ),
                    if (version != versions.last) const SizedBox(width: 10),
                  ],
                ],
              ),
            ),
    );
  }
}

class _VersionHistoryTile extends StatelessWidget {
  final ResumeVersionView version;
  final bool selected;
  final VoidCallback onTap;

  const _VersionHistoryTile({
    required this.version,
    required this.selected,
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
          width: 210,
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
          decoration: BoxDecoration(
            color: selected ? ProductColors.primarySoft : ProductColors.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: selected
                  ? ProductColors.primary.withValues(alpha: 0.32)
                  : ProductColors.border,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  ProductTag(
                    label: selected ? '当前' : '优化',
                    tone: selected ? ProductTone.primary : ProductTone.info,
                  ),
                  const Spacer(),
                  const Icon(
                    Icons.chevron_right_rounded,
                    size: 18,
                    color: ProductColors.textMuted,
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                version.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                careerFormatDateTime(version.meta.updatedAt),
                style: AppTheme.ts(
                  fontSize: 10.8,
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

class _ResumeContact extends StatelessWidget {
  final IconData icon;
  final String text;

  const _ResumeContact({
    required this.icon,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 13, color: ProductColors.textMuted),
        const SizedBox(width: 4),
        Text(
          text,
          style: AppTheme.ts(
            fontSize: 10.8,
            color: ProductColors.textSecondary,
          ),
        ),
      ],
    );
  }
}

class _ResumePaperSection extends StatelessWidget {
  final String title;
  final String body;
  final bool last;

  const _ResumePaperSection({
    required this.title,
    required this.body,
    this.last = false,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: last ? 0 : 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: AppTheme.ts(
              fontSize: 14,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 8),
          Container(
            height: 1,
            color: ProductColors.border,
          ),
          const SizedBox(height: 8),
          Text(
            body,
            maxLines: 5,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 12,
              height: 1.55,
              color: ProductColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
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

class _RelatedJobRow extends StatelessWidget {
  final CareerApplicationView application;
  final VoidCallback onTap;

  const _RelatedJobRow({
    required this.application,
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
          padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
          decoration:
              ProductSurface.softCard(tone: ProductTone.warning, radius: 12),
          child: Row(
            children: [
              const ProductIconTile(
                icon: Icons.business_center_outlined,
                tone: ProductTone.warning,
                size: 34,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      application.displayTitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.8,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      '匹配度 ${careerStageLabel(application.stage)}',
                      style: AppTheme.ts(
                        fontSize: 10.6,
                        color: ProductColors.textMuted,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(
                Icons.chevron_right_rounded,
                size: 18,
                color: ProductColors.textMuted,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AssetLine extends StatelessWidget {
  final _AssetCount item;

  const _AssetLine({required this.item});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ProductIconTile(icon: item.icon, tone: ProductTone.info, size: 32),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                item.title,
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
                item.subtitle,
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

class _MiniScore extends StatelessWidget {
  final int? score;

  const _MiniScore({required this.score});

  @override
  Widget build(BuildContext context) {
    final value = score;
    final tone = careerScoreTone(value);
    return Container(
      width: 42,
      height: 42,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(
          color: productToneStyle(tone).color.withValues(alpha: 0.24),
          width: 2,
        ),
      ),
      child: Center(
        child: Text(
          value?.toString() ?? '-',
          style: AppTheme.ts(
            fontSize: 12.5,
            fontWeight: FontWeight.w900,
            color: ProductColors.text,
          ),
        ),
      ),
    );
  }
}

class _EmptyResumeText extends StatelessWidget {
  final String text;

  const _EmptyResumeText({required this.text});

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

class _ResumeError extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const _ResumeError({
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
              '简历资料加载失败',
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

enum _ResumeRecordKind { resumeProfile, careerProfile, version }

class _ResumeRecord {
  final _ResumeRecordKind kind;
  final String id;
  final String title;
  final String subtitle;
  final String summary;
  final DateTime updatedAt;
  final List<String> keywords;
  final List<String> risks;
  final int? score;
  final IconData icon;
  final ProductTone tone;
  final ResumeProfileView? resumeProfile;
  final CareerProfileView? careerProfile;
  final ResumeVersionView? resumeVersion;

  const _ResumeRecord({
    required this.kind,
    required this.id,
    required this.title,
    required this.subtitle,
    required this.summary,
    required this.updatedAt,
    required this.keywords,
    required this.risks,
    required this.score,
    required this.icon,
    required this.tone,
    this.resumeProfile,
    this.careerProfile,
    this.resumeVersion,
  });

  String get key => '${kind.name}:$id';

  String get kindLabel {
    return switch (kind) {
      _ResumeRecordKind.resumeProfile => '简历画像',
      _ResumeRecordKind.careerProfile => '职业画像',
      _ResumeRecordKind.version => '简历版本',
    };
  }

  static _ResumeRecord fromResumeProfile(ResumeProfileView record) {
    final skills = _stringifyList(record.skills).take(8).toList();
    return _ResumeRecord(
      kind: _ResumeRecordKind.resumeProfile,
      id: record.resumeProfileId,
      title: '${record.displayName} 的简历画像',
      subtitle: '基础简历 · 更新于 ${careerFormatDateTime(record.meta.updatedAt)}',
      summary: careerFirstNonEmpty(
        [record.selfEvaluation, '包含教育、工作、项目和技能结构化信息。'],
      ),
      updatedAt: record.meta.updatedAt,
      keywords: skills,
      risks: _diagnosisRisks(record),
      score: _diagnosisScore(record),
      icon: Icons.badge_outlined,
      tone: ProductTone.info,
      resumeProfile: record,
    );
  }

  static _ResumeRecord fromCareerProfile(CareerProfileView record) {
    return _ResumeRecord(
      kind: _ResumeRecordKind.careerProfile,
      id: record.careerProfileId,
      title: '职业画像 · ${careerShortLabel(record.careerGoal)}',
      subtitle: '目标 ${record.targetRoles.take(2).join(" / ")}',
      summary: careerFirstNonEmpty(
        [record.experienceSummary, record.educationSummary, record.careerGoal],
      ),
      updatedAt: record.meta.updatedAt,
      keywords: record.skills.take(8).toList(),
      risks: record.resumeIssues.take(5).toList(),
      score: null,
      icon: Icons.psychology_alt_outlined,
      tone: ProductTone.purple,
      careerProfile: record,
    );
  }

  static _ResumeRecord fromResumeVersion(ResumeVersionView record) {
    return _ResumeRecord(
      kind: _ResumeRecordKind.version,
      id: record.resumeVersionId,
      title: careerShortLabel(record.title, fallback: record.resumeVersionId),
      subtitle:
          'v${record.resumeVersionId.split("_").last} · 更新于 ${careerFormatDateTime(record.meta.updatedAt)}',
      summary: record.changeSummary.isEmpty
          ? '面向岗位生成的简历版本。'
          : record.changeSummary.first,
      updatedAt: record.meta.updatedAt,
      keywords: record.keywordStrategy.take(8).toList(),
      risks: record.riskNotes.take(5).toList(),
      score: _versionScore(record),
      icon: Icons.description_outlined,
      tone: ProductTone.primary,
      resumeVersion: record,
    );
  }
}

class _AssetCount {
  final String title;
  final String subtitle;
  final IconData icon;

  const _AssetCount(this.title, this.subtitle, this.icon);
}

List<_ResumeRecord> _resumeRecords(CareerWorkbenchProvider provider) {
  final records = <_ResumeRecord>[
    for (final version in provider.resumeVersions)
      _ResumeRecord.fromResumeVersion(version),
    for (final profile in provider.resumeProfiles)
      _ResumeRecord.fromResumeProfile(profile),
    for (final profile in provider.careerProfiles)
      _ResumeRecord.fromCareerProfile(profile),
  ];
  records.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  return records;
}

ResumeProfileView? _baseResumeProfile(
  CareerWorkbenchProvider provider,
  _ResumeRecord? selected,
) {
  if (selected?.resumeProfile != null) return selected!.resumeProfile;
  final baseId = selected?.resumeVersion?.baseResumeProfileId.trim() ?? '';
  if (baseId.isNotEmpty) {
    for (final profile in provider.resumeProfiles) {
      if (profile.resumeProfileId == baseId) return profile;
    }
  }
  final selectedApp = provider.selectedApplicationDetail?.resumeProfile ??
      (provider.resumeProfiles.isNotEmpty
          ? provider.resumeProfiles.first
          : null);
  return selectedApp;
}

CareerProfileView? _bestCareerProfile(
  CareerWorkbenchProvider provider,
  CareerApplicationView? linkedApplication,
) {
  final careerId = linkedApplication?.careerProfileId?.trim() ?? '';
  if (careerId.isNotEmpty) {
    for (final profile in provider.careerProfiles) {
      if (profile.careerProfileId == careerId) return profile;
    }
  }
  return provider.selectedApplicationDetail?.careerProfile ??
      (provider.careerProfiles.isNotEmpty
          ? provider.careerProfiles.first
          : null);
}

CareerApplicationView? _linkedApplication(
  CareerWorkbenchProvider provider,
  _ResumeRecord? record,
) {
  final selected = provider.selectedApplicationDetail?.application ??
      provider.selectedApplicationSummary?.application;
  if (_isApplicationLinkedToRecord(selected, record)) return selected;
  for (final item in provider.applications) {
    if (_isApplicationLinkedToRecord(item.application, record)) {
      return item.application;
    }
  }
  return selected;
}

bool _isApplicationLinkedToRecord(
  CareerApplicationView? app,
  _ResumeRecord? record,
) {
  if (app == null || record == null) return false;
  return switch (record.kind) {
    _ResumeRecordKind.resumeProfile => app.resumeProfileId == record.id,
    _ResumeRecordKind.careerProfile => app.careerProfileId == record.id,
    _ResumeRecordKind.version => app.resumeVersionIds.contains(record.id),
  };
}

DateTime? _latestResumeUpdatedAt(CareerWorkbenchProvider provider) {
  final dates = [
    ...provider.resumeProfiles.map((item) => item.meta.updatedAt),
    ...provider.careerProfiles.map((item) => item.meta.updatedAt),
    ...provider.resumeVersions.map((item) => item.meta.updatedAt),
  ];
  if (dates.isEmpty) return null;
  dates.sort((a, b) => b.compareTo(a));
  return dates.first;
}

String _resumeName(ResumeProfileView? profile) {
  return careerShortLabel(profile?.displayName, fallback: '张明');
}

List<String> _resumeSkills(
  ResumeProfileView? profile,
  CareerProfileView? careerProfile,
  _ResumeRecord? selected,
) {
  final skills = [
    ...selected?.keywords ?? const <String>[],
    ...careerProfile?.skills ?? const <String>[],
    ..._stringifyList(profile?.skills ?? const []),
  ].where((item) => item.trim().isNotEmpty).toSet().take(10).toList();
  return skills.isEmpty ? const ['Python', 'FastAPI', 'Agent', 'RAG'] : skills;
}

String _resumeProjects(ResumeProfileView? profile) {
  final projects = _stringifyList(profile?.projectExperience ?? const []);
  if (projects.isEmpty) {
    return '创作客服数据分析平台：负责数据处理、问答服务与可观测能力建设，支撑业务知识库检索与分析。';
  }
  return projects.take(3).join('\n');
}

String _resumeWork(ResumeProfileView? profile) {
  final work = _stringifyList(profile?.workExperience ?? const []);
  if (work.isEmpty) {
    return '前端/后端工程师：参与 AI 应用平台研发，负责核心服务、接口集成、性能优化和交付质量提升。';
  }
  return work.take(3).join('\n');
}

List<String> _stringifyList(List<dynamic> values) {
  return values
      .map(_dynamicToText)
      .where((item) => item.trim().isNotEmpty)
      .toList();
}

String _dynamicToText(dynamic value) {
  if (value == null) return '';
  if (value is String) return value;
  if (value is num || value is bool) return value.toString();
  if (value is Map) {
    final preferred = [
      'summary',
      'description',
      'name',
      'title',
      'project',
      'company',
      'role',
      'text',
    ];
    for (final key in preferred) {
      final item = value[key];
      if (item is String && item.trim().isNotEmpty) return item;
    }
    return value.entries
        .map((entry) => '${entry.key}: ${_dynamicToText(entry.value)}')
        .join('；');
  }
  if (value is Iterable) {
    return value.map(_dynamicToText).where((item) => item.isNotEmpty).join('；');
  }
  return value.toString();
}

int? _diagnosisScore(ResumeProfileView? profile) {
  final diagnosis = profile?.diagnosis ?? const <String, dynamic>{};
  for (final key in ['score', 'overall_score', 'resume_score']) {
    final value = diagnosis[key];
    if (value is num) return value.round().clamp(0, 100);
    if (value is String) {
      final parsed = int.tryParse(value);
      if (parsed != null) return parsed.clamp(0, 100);
    }
  }
  if (profile == null) return null;
  return 82;
}

List<String> _diagnosisRisks(ResumeProfileView record) {
  final diagnosis = record.diagnosis;
  final values = [
    diagnosis['risks'],
    diagnosis['issues'],
    diagnosis['weaknesses'],
  ];
  return values
      .expand((value) => value is List ? value : [value])
      .map(_dynamicToText)
      .where((item) => item.trim().isNotEmpty)
      .take(5)
      .toList();
}

int _versionScore(ResumeVersionView record) {
  var score =
      70 + record.keywordStrategy.length * 3 + record.changeSummary.length * 2;
  score -= record.riskNotes.length * 2;
  return score.clamp(55, 95);
}
