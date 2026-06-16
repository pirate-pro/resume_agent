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
  String _searchQuery = '';
  _ResumeFilter _filter = _ResumeFilter.all;
  _ResumeStageMode _stageMode = _ResumeStageMode.preview;
  final _searchController = TextEditingController();

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
  void dispose() {
    _searchController.dispose();
    super.dispose();
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
    final profileRecord = _firstRecordOfKind(
      records,
      _ResumeRecordKind.resumeProfile,
    );
    final versionRecords = records
        .where((record) => record.kind == _ResumeRecordKind.version)
        .toList();
    final filteredVersions = _filterResumeRecords(
      versionRecords,
      filter: _filter,
      query: _searchQuery,
      selectedKey: _selectedKey,
    );
    final selectionPool = [
      ...versionRecords,
      if (profileRecord != null) profileRecord,
    ];
    final selected = _selectedRecord(selectionPool);
    final compareTarget = _compareTargetRecord(versionRecords, selected);
    final linkedApplication = _linkedApplication(provider, selected);
    final baseProfile = _baseResumeProfile(provider, selected);
    final careerProfile = _bestCareerProfile(provider, linkedApplication);

    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= ProductBreakpoints.contentRail;
        final header = _ResumeHeader(
          provider: provider,
          searchController: _searchController,
          compareMode: _stageMode == _ResumeStageMode.compare,
          onSearchChanged: (value) => setState(() => _searchQuery = value),
          onRefresh: () => unawaited(_refresh(provider)),
          onExport: () => _showExportDialog(selected),
          onBackToPreview: () =>
              setState(() => _stageMode = _ResumeStageMode.preview),
          onGenerateVersion: () => _showGenerateVersionDialog(
            provider: provider,
            app: linkedApplication,
            baseProfile: baseProfile,
            selected: selected,
          ),
        );
        final stats = _ResumeStatsStrip(provider: provider);
        final list = _ResumeRecordList(
          profileRecord: profileRecord,
          records: filteredVersions,
          selectedKey: selected?.key,
          filter: _filter,
          isLoading: provider.isLoadingAssetLibrary,
          onFilterChanged: (filter) => setState(() => _filter = filter),
          onSelected: (record) => setState(() {
            _selectedKey = record.key;
            _stageMode = _ResumeStageMode.preview;
          }),
        );
        final stage = _stageMode == _ResumeStageMode.compare
            ? _ResumeCompareStage(
                current: selected,
                target: compareTarget,
                baseProfile: baseProfile,
                careerProfile: careerProfile,
                linkedApplication: linkedApplication,
                onBack: () =>
                    setState(() => _stageMode = _ResumeStageMode.preview),
                onExport: () => _showExportDialog(selected),
                onSave: () => _showLocalOnlySnack('版本对比结果需要接入保存新版本接口。'),
              )
            : _ResumeMainStage(
                selected: selected,
                baseProfile: baseProfile,
                careerProfile: careerProfile,
                linkedApplication: linkedApplication,
                versions: provider.resumeVersions,
                onOptimize: () =>
                    _showOptimizeDialog(linkedApplication, selected),
                onCompare: versionRecords.length >= 2
                    ? () =>
                        setState(() => _stageMode = _ResumeStageMode.compare)
                    : () => _showLocalOnlySnack('至少需要两个简历版本才能对比。'),
                onExport: () => _showExportDialog(selected),
                onGenerateVersion: () => _showGenerateVersionDialog(
                  provider: provider,
                  app: linkedApplication,
                  baseProfile: baseProfile,
                  selected: selected,
                ),
                onHistorySelected: (version) => setState(() {
                  _selectedKey = _ResumeRecord.fromResumeVersion(version).key;
                  _stageMode = _ResumeStageMode.preview;
                }),
              );
        final rail = _ResumeRightRail(
          provider: provider,
          selected: selected,
          baseProfile: baseProfile,
          careerProfile: careerProfile,
          linkedApplication: linkedApplication,
          onOpenProjects: widget.onOpenProjects,
          onOptimize: () => _showOptimizeDialog(linkedApplication, selected),
          onCompare: () =>
              setState(() => _stageMode = _ResumeStageMode.compare),
          onExport: () => _showExportDialog(selected),
          onGenerateVersion: () => _showGenerateVersionDialog(
            provider: provider,
            app: linkedApplication,
            baseProfile: baseProfile,
            selected: selected,
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
              stage,
              const SizedBox(height: 14),
              rail,
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
                Expanded(child: stage),
                const SizedBox(width: 16),
                SizedBox(width: 340, child: rail),
              ],
            ),
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

  Future<void> _showGenerateVersionDialog({
    required CareerWorkbenchProvider provider,
    required CareerApplicationView? app,
    required ResumeProfileView? baseProfile,
    required _ResumeRecord? selected,
  }) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _GenerateResumeVersionDialog(
        provider: provider,
        application: app,
        baseProfile: baseProfile,
        selected: selected,
        onStart: (targetApp, strategy) {
          Navigator.of(dialogContext).pop();
          unawaited(_generateResumeVersionDraft(
            provider: provider,
            app: targetApp,
            baseProfile: baseProfile,
            selected: selected,
            strategy: strategy,
          ));
        },
      ),
    );
  }

  Future<void> _generateResumeVersionDraft({
    required CareerWorkbenchProvider provider,
    required CareerApplicationView app,
    required ResumeProfileView? baseProfile,
    required _ResumeRecord? selected,
    required List<String> strategy,
  }) async {
    if (baseProfile == null) {
      _showLocalOnlySnack('需要先有基础简历画像，才能生成岗位定制版。');
      return;
    }
    _showLocalOnlySnack('正在生成岗位定制版草案...');
    try {
      final draft = await provider.generateResumeVersionDraft(
        applicationId: app.applicationId,
        resumeProfileId: baseProfile.resumeProfileId,
        baseResumeVersionId: selected?.resumeVersion?.resumeVersionId,
        targetJdAnalysisId: app.jdAnalysisId,
        jobFitReportId: app.jobFitReportId,
        title: '${app.displayTitle} 定制版草案',
        strategy: strategy,
      );
      if (!mounted) return;
      final accepted = await showDialog<ResumeVersionView>(
        context: context,
        builder: (dialogContext) => _ResumeVersionDraftPreviewDialog(
          draft: draft,
          provider: provider,
        ),
      );
      if (!mounted || accepted == null) return;
      setState(() {
        _selectedKey = _ResumeRecord.fromResumeVersion(accepted).key;
        _stageMode = _ResumeStageMode.preview;
      });
      _showLocalOnlySnack('已保存为新简历版本。');
    } catch (error) {
      if (!mounted) return;
      _showLocalOnlySnack('生成岗位定制版失败：$error');
    }
  }

  Future<void> _showOptimizeDialog(
    CareerApplicationView? app,
    _ResumeRecord? record,
  ) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _OptimizeResumeDialog(
        record: record,
        application: app,
        onStart: (direction) {
          Navigator.of(dialogContext).pop();
          _sendOptimizeResume(app, record, direction: direction);
          _showLocalOnlySnack('已发起优化草案生成，完成后可刷新版本库查看。');
        },
      ),
    );
  }

  Future<void> _showExportDialog(_ResumeRecord? record) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _ExportResumeDialog(
        record: record,
        onClose: () => Navigator.of(dialogContext).pop(),
      ),
    );
  }

  void _showLocalOnlySnack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  void _sendOptimizeResume(
    CareerApplicationView? app,
    _ResumeRecord? record, {
    String? direction,
  }) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: '优化此版本',
      actionType: 'resume_optimize',
      origin: 'resume_library',
      detail: record == null
          ? '请基于当前求职项目优化简历。'
          : '请基于 ${record.title} 的内容继续优化简历表达、关键词和项目证据。'
              '${direction?.trim().isNotEmpty == true ? "优化方向：${direction!.trim()}。" : ""}',
    );
  }
}

class _ResumeHeader extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final TextEditingController searchController;
  final bool compareMode;
  final ValueChanged<String> onSearchChanged;
  final VoidCallback onRefresh;
  final VoidCallback onExport;
  final VoidCallback onBackToPreview;
  final VoidCallback onGenerateVersion;

  const _ResumeHeader({
    required this.provider,
    required this.searchController,
    required this.compareMode,
    required this.onSearchChanged,
    required this.onRefresh,
    required this.onExport,
    required this.onBackToPreview,
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
          final search = ConstrainedBox(
            constraints:
                BoxConstraints(maxWidth: compact ? double.infinity : 520),
            child: SizedBox(
              height: 38,
              child: TextField(
                controller: searchController,
                onChanged: onSearchChanged,
                style: AppTheme.ts(fontSize: 12.5, color: ProductColors.text),
                decoration: InputDecoration(
                  prefixIcon: const Icon(
                    Icons.search_rounded,
                    size: 18,
                    color: ProductColors.textMuted,
                  ),
                  hintText: '搜索简历版本、岗位、技能或修改记录...',
                  hintStyle: AppTheme.ts(
                    fontSize: 12.5,
                    color: ProductColors.textMuted,
                  ),
                  contentPadding: EdgeInsets.zero,
                  filled: true,
                  fillColor: ProductColors.surface,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(999),
                    borderSide: const BorderSide(color: ProductColors.border),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(999),
                    borderSide: const BorderSide(color: ProductColors.border),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(999),
                    borderSide:
                        const BorderSide(color: ProductColors.borderStrong),
                  ),
                ),
              ),
            ),
          );
          final controls = Wrap(
            spacing: 8,
            runSpacing: 8,
            alignment: WrapAlignment.end,
            children: [
              if (compareMode)
                SizedBox(
                  height: 38,
                  child: OutlinedButton.icon(
                    onPressed: onBackToPreview,
                    icon: const Icon(Icons.arrow_back_rounded, size: 16),
                    label: const Text('返回预览'),
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
              SizedBox(
                height: 38,
                child: OutlinedButton.icon(
                  onPressed: onExport,
                  icon: const Icon(Icons.download_rounded, size: 16),
                  label: const Text('导出投递版'),
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
                child: ElevatedButton.icon(
                  onPressed: onGenerateVersion,
                  icon: const Icon(Icons.auto_awesome_rounded, size: 16),
                  label: const Text('生成岗位定制版'),
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
            ],
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                title,
                const SizedBox(height: 12),
                search,
                const SizedBox(height: 12),
                controls,
              ],
            );
          }
          return Row(
            children: [
              Expanded(child: title),
              const SizedBox(width: 16),
              Expanded(child: search),
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
  final _ResumeRecord? profileRecord;
  final List<_ResumeRecord> records;
  final String? selectedKey;
  final _ResumeFilter filter;
  final bool isLoading;
  final ValueChanged<_ResumeFilter> onFilterChanged;
  final ValueChanged<_ResumeRecord> onSelected;

  const _ResumeRecordList({
    required this.profileRecord,
    required this.records,
    required this.selectedKey,
    required this.filter,
    required this.isLoading,
    required this.onFilterChanged,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return ProductSection(
      title: '版本库',
      subtitle: '基础画像与可投递简历版本',
      icon: Icons.view_list_outlined,
      tone: ProductTone.primary,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final item in _ResumeFilter.values)
                _ResumeFilterChip(
                  label: item.label,
                  selected: filter == item,
                  onTap: () => onFilterChanged(item),
                ),
            ],
          ),
          if (profileRecord != null) ...[
            const SizedBox(height: 14),
            _ResumeProfileTile(
              record: profileRecord!,
              selected: selectedKey == profileRecord!.key,
              onTap: () => onSelected(profileRecord!),
            ),
          ],
          const SizedBox(height: 14),
          if (isLoading && records.isEmpty)
            const SizedBox(
              height: 120,
              child: Center(
                child: CircularProgressIndicator(color: ProductColors.primary),
              ),
            )
          else if (records.isEmpty)
            const _EmptyResumeText(
              text: '当前筛选下没有简历版本。可以生成岗位定制版，或切换到“全部”。',
            )
          else
            Column(
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
        ],
      ),
    );
  }
}

class _ResumeFilterChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _ResumeFilterChip({
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
        child: Container(
          height: 30,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            color: selected ? ProductColors.primary : ProductColors.surface,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected ? ProductColors.primary : ProductColors.border,
            ),
          ),
          child: Center(
            child: Text(
              label,
              style: AppTheme.ts(
                fontSize: 11.5,
                fontWeight: FontWeight.w900,
                color: selected ? Colors.white : ProductColors.textSecondary,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ResumeProfileTile extends StatelessWidget {
  final _ResumeRecord record;
  final bool selected;
  final VoidCallback onTap;

  const _ResumeProfileTile({
    required this.record,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final skills = record.keywords.length;
    final projects = _stringifyList(
      record.resumeProfile?.projectExperience ?? const [],
    ).length;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
          decoration: BoxDecoration(
            color: ProductColors.primarySoft.withValues(alpha: 0.78),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: selected
                  ? ProductColors.primary
                  : ProductColors.primary.withValues(alpha: 0.18),
            ),
          ),
          child: Row(
            children: [
              const ProductIconTile(
                icon: Icons.badge_outlined,
                tone: ProductTone.primary,
                size: 40,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '基础简历画像',
                      style: AppTheme.ts(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      '技能 $skills · 项目 $projects · 诊断可用',
                      style: AppTheme.ts(
                        fontSize: 11,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(
                Icons.chevron_right_rounded,
                color: ProductColors.textMuted,
              ),
            ],
          ),
        ),
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
            color: selected ? ProductColors.primarySoft : ProductColors.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: selected ? ProductColors.primary : ProductColors.border,
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
                            fontSize: 12.8,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.text,
                          ),
                        ),
                        if (selected)
                          ProductTag(label: '当前使用', tone: ProductTone.primary),
                        ProductTag(
                          label: record.isTargetedVersion ? '岗位定制' : '通用版本',
                          tone: record.isTargetedVersion
                              ? ProductTone.info
                              : ProductTone.neutral,
                        ),
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
                    if (record.summary.trim().isNotEmpty) ...[
                      const SizedBox(height: 5),
                      Text(
                        record.summary,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11,
                          height: 1.35,
                          color: ProductColors.textSecondary,
                        ),
                      ),
                    ],
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

class _ResumeMainStage extends StatelessWidget {
  final _ResumeRecord? selected;
  final ResumeProfileView? baseProfile;
  final CareerProfileView? careerProfile;
  final CareerApplicationView? linkedApplication;
  final List<ResumeVersionView> versions;
  final VoidCallback onOptimize;
  final VoidCallback onCompare;
  final VoidCallback onExport;
  final VoidCallback onGenerateVersion;
  final ValueChanged<ResumeVersionView> onHistorySelected;

  const _ResumeMainStage({
    required this.selected,
    required this.baseProfile,
    required this.careerProfile,
    required this.linkedApplication,
    required this.versions,
    required this.onOptimize,
    required this.onCompare,
    required this.onExport,
    required this.onGenerateVersion,
    required this.onHistorySelected,
  });

  @override
  Widget build(BuildContext context) {
    if (selected == null && baseProfile == null) {
      return ProductCard(
        padding: const EdgeInsets.fromLTRB(22, 22, 22, 22),
        child: const _EmptyResumeText(
          text: '上传简历后，这里会展示可投递版本、岗位定制草案和版本历史。',
        ),
      );
    }
    final selectedVersion = selected?.resumeVersion;
    final isTargeted = selected?.isTargetedVersion == true;
    final title = selected?.title ?? '基础简历画像';
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ResumeStageHeader(
            title: title,
            selected: selected,
            linkedApplication: linkedApplication,
            isTargeted: isTargeted,
            onOptimize: onOptimize,
            onCompare: onCompare,
            onExport: onExport,
            onGenerateVersion: onGenerateVersion,
          ),
          const SizedBox(height: 16),
          _ResumePaperPreview(
            selected: selected,
            baseProfile: baseProfile,
            careerProfile: careerProfile,
            linkedApplication: linkedApplication,
          ),
          const SizedBox(height: 16),
          _ResumeVersionSummary(
            selected: selected,
            version: selectedVersion,
            careerProfile: careerProfile,
          ),
          const SizedBox(height: 16),
          _VersionHistory(
            versions: versions,
            selectedKey: selected?.key,
            onSelected: onHistorySelected,
          ),
        ],
      ),
    );
  }
}

class _ResumeStageHeader extends StatelessWidget {
  final String title;
  final _ResumeRecord? selected;
  final CareerApplicationView? linkedApplication;
  final bool isTargeted;
  final VoidCallback onOptimize;
  final VoidCallback onCompare;
  final VoidCallback onExport;
  final VoidCallback onGenerateVersion;

  const _ResumeStageHeader({
    required this.title,
    required this.selected,
    required this.linkedApplication,
    required this.isTargeted,
    required this.onOptimize,
    required this.onCompare,
    required this.onExport,
    required this.onGenerateVersion,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 760;
        final titleBlock = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 18,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                if (selected?.kind == _ResumeRecordKind.version)
                  ProductTag(
                    label: isTargeted ? '岗位定制' : '通用版本',
                    tone: isTargeted ? ProductTone.info : ProductTone.neutral,
                  ),
                if (selected?.key != null)
                  ProductTag(label: '当前使用', tone: ProductTone.primary),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              linkedApplication == null
                  ? '未关联目标岗位'
                  : '关联岗位：${linkedApplication!.displayTitle}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: linkedApplication == null
                    ? ProductColors.textMuted
                    : ProductColors.primary,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              selected == null
                  ? '资料预览'
                  : '更新于 ${careerFormatDateTime(selected!.updatedAt)}',
              style: AppTheme.ts(
                fontSize: 11.2,
                color: ProductColors.textMuted,
              ),
            ),
          ],
        );
        final actions = Wrap(
          spacing: 8,
          runSpacing: 8,
          alignment: WrapAlignment.end,
          children: [
            _SmallActionButton(
              label: '预览简历',
              icon: Icons.visibility_outlined,
              onPressed: onExport,
            ),
            _SmallActionButton(
              label: '优化此版本',
              icon: Icons.auto_fix_high_outlined,
              onPressed: onOptimize,
            ),
            _SmallActionButton(
              label: '对比版本',
              icon: Icons.compare_arrows_rounded,
              onPressed: onCompare,
            ),
            _SmallActionButton(
              label: '生成新版本',
              icon: Icons.add_rounded,
              primary: true,
              onPressed: onGenerateVersion,
            ),
          ],
        );
        if (compact) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              titleBlock,
              const SizedBox(height: 12),
              actions,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: titleBlock),
            const SizedBox(width: 16),
            actions,
          ],
        );
      },
    );
  }
}

class _SmallActionButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool primary;
  final VoidCallback onPressed;

  const _SmallActionButton({
    required this.label,
    required this.icon,
    required this.onPressed,
    this.primary = false,
  });

  @override
  Widget build(BuildContext context) {
    final style = primary
        ? ElevatedButton.styleFrom(
            backgroundColor: ProductColors.primary,
            foregroundColor: Colors.white,
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(11),
            ),
          )
        : OutlinedButton.styleFrom(
            foregroundColor: ProductColors.textSecondary,
            side: const BorderSide(color: ProductColors.border),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(11),
            ),
          );
    return SizedBox(
      height: 34,
      child: primary
          ? ElevatedButton.icon(
              onPressed: onPressed,
              icon: Icon(icon, size: 15),
              label: Text(label),
              style: style,
            )
          : OutlinedButton.icon(
              onPressed: onPressed,
              icon: Icon(icon, size: 15),
              label: Text(label),
              style: style,
            ),
    );
  }
}

class _ResumePaperPreview extends StatelessWidget {
  final _ResumeRecord? selected;
  final ResumeProfileView? baseProfile;
  final CareerProfileView? careerProfile;
  final CareerApplicationView? linkedApplication;

  const _ResumePaperPreview({
    required this.selected,
    required this.baseProfile,
    required this.careerProfile,
    required this.linkedApplication,
  });

  @override
  Widget build(BuildContext context) {
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
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(28, 26, 28, 24),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: ProductColors.border),
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
            children: const [
              _ResumeContact(icon: Icons.location_on_outlined, text: '北京'),
              _ResumeContact(icon: Icons.phone_outlined, text: '138-****-8888'),
              _ResumeContact(
                icon: Icons.email_outlined,
                text: 'zhangming@example.com',
              ),
              _ResumeContact(
                icon: Icons.link_outlined,
                text: 'github.com/zhangming',
              ),
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
            body: _resumeWork(baseProfile),
          ),
          _ResumePaperSection(
            title: '项目经历',
            body: _resumeProjects(baseProfile),
          ),
          _ResumePaperSection(
            title: '核心技能',
            body: skills.join(' / '),
            last: true,
          ),
        ],
      ),
    );
  }
}

class _ResumeVersionSummary extends StatelessWidget {
  final _ResumeRecord? selected;
  final ResumeVersionView? version;
  final CareerProfileView? careerProfile;

  const _ResumeVersionSummary({
    required this.selected,
    required this.version,
    required this.careerProfile,
  });

  @override
  Widget build(BuildContext context) {
    final changes = version?.changeSummary.isNotEmpty == true
        ? version!.changeSummary
        : const ['强化岗位相关项目经历', '突出 LLM 应用落地能力', '优化技术栈和成果表达'];
    final keywords = version?.keywordStrategy.isNotEmpty == true
        ? version!.keywordStrategy
        : _resumeSkills(null, careerProfile, selected).take(6).toList();
    final risks = version?.riskNotes.isNotEmpty == true
        ? version!.riskNotes
        : [
            ...careerProfile?.resumeIssues ?? const <String>[],
          ].take(3).toList();
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 760 ? 3 : 1;
        return GridView.count(
          crossAxisCount: columns,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          crossAxisSpacing: 12,
          mainAxisSpacing: 12,
          mainAxisExtent: 118,
          childAspectRatio: columns == 1 ? 4.2 : 1.9,
          children: [
            _ResumeSummaryCard(
              title: '本版改动',
              icon: Icons.auto_awesome_outlined,
              tone: ProductTone.primary,
              items: changes,
            ),
            _ResumeSummaryCard(
              title: '关键词策略',
              icon: Icons.track_changes_rounded,
              tone: ProductTone.info,
              items: keywords,
            ),
            _ResumeSummaryCard(
              title: '风险提醒',
              icon: Icons.warning_amber_rounded,
              tone: ProductTone.warning,
              items: risks.isEmpty ? const ['项目结果量化仍可进一步补充'] : risks,
            ),
          ],
        );
      },
    );
  }
}

class _ResumeSummaryCard extends StatelessWidget {
  final String title;
  final IconData icon;
  final ProductTone tone;
  final List<String> items;

  const _ResumeSummaryCard({
    required this.title,
    required this.icon,
    required this.tone,
    required this.items,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      padding: const EdgeInsets.all(13),
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
              Icon(icon, size: 16, color: style.color),
              const SizedBox(width: 7),
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 12.6,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          for (final item in items.take(3))
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Text(
                '• $item',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 11.2,
                  color: ProductColors.textSecondary,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _ResumeCompareStage extends StatelessWidget {
  final _ResumeRecord? current;
  final _ResumeRecord? target;
  final ResumeProfileView? baseProfile;
  final CareerProfileView? careerProfile;
  final CareerApplicationView? linkedApplication;
  final VoidCallback onBack;
  final VoidCallback onExport;
  final VoidCallback onSave;

  const _ResumeCompareStage({
    required this.current,
    required this.target,
    required this.baseProfile,
    required this.careerProfile,
    required this.linkedApplication,
    required this.onBack,
    required this.onExport,
    required this.onSave,
  });

  @override
  Widget build(BuildContext context) {
    final currentRecord = current;
    final targetRecord = target;
    if (currentRecord == null || targetRecord == null) {
      return ProductCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '版本对比',
              style: AppTheme.ts(
                fontSize: 18,
                fontWeight: FontWeight.w900,
                color: ProductColors.text,
              ),
            ),
            const SizedBox(height: 10),
            const _EmptyResumeText(text: '至少需要两个简历版本才能进入对比。'),
            const SizedBox(height: 14),
            OutlinedButton.icon(
              onPressed: onBack,
              icon: const Icon(Icons.arrow_back_rounded),
              label: const Text('返回预览'),
            ),
          ],
        ),
      );
    }
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      '版本对比',
                      style: AppTheme.ts(
                        fontSize: 18,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    ProductTag(label: '对比中', tone: ProductTone.info),
                  ],
                ),
              ),
              _SmallActionButton(
                label: '返回预览',
                icon: Icons.arrow_back_rounded,
                onPressed: onBack,
              ),
              const SizedBox(width: 8),
              _SmallActionButton(
                label: '导出差异',
                icon: Icons.download_rounded,
                onPressed: onExport,
              ),
              const SizedBox(width: 8),
              _SmallActionButton(
                label: '保存为新版本',
                icon: Icons.save_outlined,
                primary: true,
                onPressed: onSave,
              ),
            ],
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: ProductColors.surfaceSoft,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: ProductColors.border),
            ),
            child: Row(
              children: const [
                Expanded(
                  child: _CompareMetric(
                    label: '关键词覆盖',
                    value: '+12',
                    tone: ProductTone.primary,
                  ),
                ),
                Expanded(
                  child: _CompareMetric(
                    label: '项目表达更聚焦',
                    value: '✓',
                    tone: ProductTone.primary,
                  ),
                ),
                Expanded(
                  child: _CompareMetric(
                    label: '风险项',
                    value: '-2',
                    tone: ProductTone.warning,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 820 ? 2 : 1;
              final children = [
                _CompareResumePanel(
                  label: '当前版本',
                  record: currentRecord,
                  baseProfile: baseProfile,
                  careerProfile: careerProfile,
                  linkedApplication: linkedApplication,
                ),
                _CompareResumePanel(
                  label: '目标版本',
                  record: targetRecord,
                  baseProfile: baseProfile,
                  careerProfile: careerProfile,
                  linkedApplication: linkedApplication,
                ),
              ];
              if (columns == 1) {
                return Column(
                  children: [
                    children.first,
                    const SizedBox(height: 12),
                    children.last,
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: children.first),
                  const SizedBox(width: 14),
                  Expanded(child: children.last),
                ],
              );
            },
          ),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 760 ? 3 : 1;
              return GridView.count(
                crossAxisCount: columns,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 12,
                mainAxisSpacing: 12,
                childAspectRatio: columns == 1 ? 4.4 : 2.25,
                children: const [
                  _DiffSummaryCard(
                      title: '项目描述变化', value: '+6', desc: '更聚焦岗位业务场景与工程实践。'),
                  _DiffSummaryCard(
                      title: '关键词变化',
                      value: '+12',
                      desc: '强化 Agent、RAG、工程化等关键词。'),
                  _DiffSummaryCard(
                      title: '风险变化', value: '-2', desc: '减少泛化描述，补充证据表达。'),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _CompareMetric extends StatelessWidget {
  final String label;
  final String value;
  final ProductTone tone;

  const _CompareMetric({
    required this.label,
    required this.value,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(
          value,
          style: AppTheme.ts(
            fontSize: 14,
            fontWeight: FontWeight.w900,
            color: style.color,
          ),
        ),
        const SizedBox(width: 6),
        Flexible(
          child: Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 12,
              fontWeight: FontWeight.w800,
              color: ProductColors.text,
            ),
          ),
        ),
      ],
    );
  }
}

class _CompareResumePanel extends StatelessWidget {
  final String label;
  final _ResumeRecord record;
  final ResumeProfileView? baseProfile;
  final CareerProfileView? careerProfile;
  final CareerApplicationView? linkedApplication;

  const _CompareResumePanel({
    required this.label,
    required this.record,
    required this.baseProfile,
    required this.careerProfile,
    required this.linkedApplication,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: ProductColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ProductTag(
            label: label,
            tone: label == '当前版本' ? ProductTone.primary : ProductTone.warning,
          ),
          const SizedBox(height: 10),
          Text(
            record.title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 14,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 10),
          _ResumePaperSection(
            title: '个人简介',
            body: careerFirstNonEmpty(
              [
                baseProfile?.selfEvaluation,
                careerProfile?.experienceSummary,
                record.summary
              ],
              fallback: '围绕目标岗位优化后的简历表达。',
            ),
          ),
          _ResumePaperSection(
            title: '项目经历',
            body: _resumeProjects(baseProfile),
          ),
          _ResumePaperSection(
            title: '核心技能',
            body: _resumeSkills(baseProfile, careerProfile, record).join(' / '),
            last: true,
          ),
        ],
      ),
    );
  }
}

class _DiffSummaryCard extends StatelessWidget {
  final String title;
  final String value;
  final String desc;

  const _DiffSummaryCard({
    required this.title,
    required this.value,
    required this.desc,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: AppTheme.ts(
              fontSize: 12.6,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            value,
            style: AppTheme.ts(
              fontSize: 22,
              fontWeight: FontWeight.w900,
              color: ProductColors.primary,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            desc,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 11.2,
              color: ProductColors.textSecondary,
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
  final VoidCallback onOptimize;
  final VoidCallback onCompare;
  final VoidCallback onExport;
  final VoidCallback onGenerateVersion;

  const _ResumeRightRail({
    required this.provider,
    required this.selected,
    required this.baseProfile,
    required this.careerProfile,
    required this.linkedApplication,
    required this.onOpenProjects,
    required this.onOptimize,
    required this.onCompare,
    required this.onExport,
    required this.onGenerateVersion,
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
          onOptimize: onOptimize,
          onCompare: onCompare,
          onExport: onExport,
          onGenerateVersion: onGenerateVersion,
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
  final VoidCallback onOptimize;
  final VoidCallback onCompare;
  final VoidCallback onExport;
  final VoidCallback onGenerateVersion;

  const _ResumePushActions({
    required this.onOptimize,
    required this.onCompare,
    required this.onExport,
    required this.onGenerateVersion,
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
            actionLabel: '优化',
            onTap: onOptimize,
          ),
          const SizedBox(height: 8),
          ProductActionTile(
            title: '补充开源项目与技术博客链接',
            subtitle: '提升工程可信度和证据完整度。',
            icon: Icons.link_outlined,
            tone: ProductTone.info,
            actionLabel: '生成新版',
            onTap: onGenerateVersion,
          ),
          const SizedBox(height: 8),
          ProductActionTile(
            title: '对比当前版本与基础版',
            subtitle: '查看改动、风险变化和匹配提升。',
            icon: Icons.compare_arrows_rounded,
            tone: ProductTone.warning,
            actionLabel: '对比',
            onTap: onCompare,
          ),
          const SizedBox(height: 8),
          ProductActionTile(
            title: '导出投递版',
            subtitle: '生成可投递的简历文件或导出包。',
            icon: Icons.download_rounded,
            tone: ProductTone.primary,
            actionLabel: '导出',
            onTap: onExport,
          ),
        ],
      ),
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

class _GenerateResumeVersionDialog extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? application;
  final ResumeProfileView? baseProfile;
  final _ResumeRecord? selected;
  final void Function(CareerApplicationView application, List<String> strategy)
      onStart;

  const _GenerateResumeVersionDialog({
    required this.provider,
    required this.application,
    required this.baseProfile,
    required this.selected,
    required this.onStart,
  });

  @override
  Widget build(BuildContext context) {
    final app = application ??
        (provider.applications.isNotEmpty
            ? provider.applications.first.application
            : null);
    final skills = _stringifyList(baseProfile?.skills ?? const []).length;
    final projects =
        _stringifyList(baseProfile?.projectExperience ?? const []).length;
    const strategy = [
      '突出 Agent 项目',
      '补强量化成果',
      '补充关键词覆盖',
    ];
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 22, 24, 18),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
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
                          const SizedBox(height: 6),
                          Text(
                            '系统将基于基础简历画像、目标岗位 JD 和匹配报告生成新的定制版草案。',
                            style: AppTheme.ts(
                              fontSize: 12.5,
                              color: ProductColors.textSecondary,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                _DialogStepSection(
                  step: '1',
                  title: '选择目标岗位',
                  child: _DialogInfoTile(
                    icon: Icons.business_center_outlined,
                    title: app?.displayTitle ?? '尚未选择目标岗位',
                    subtitle: app == null
                        ? '需要先创建或选择一个求职项目。'
                        : careerStageLabel(app.stage),
                    trailing: const Icon(Icons.keyboard_arrow_down_rounded),
                  ),
                ),
                _DialogStepSection(
                  step: '2',
                  title: '基础简历画像',
                  child: _DialogInfoTile(
                    icon: Icons.badge_outlined,
                    title: baseProfile == null
                        ? '暂无基础简历画像'
                        : '${baseProfile!.displayName} 的基础简历画像',
                    subtitle: '技能 $skills 项 · 项目 $projects 个 · 作为所有版本的事实底座',
                    trailing: const Text('查看详情'),
                  ),
                ),
                _DialogStepSection(
                  step: '3',
                  title: '证据与来源',
                  child: Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      _EvidenceChip(label: 'JD 分析', available: app != null),
                      _EvidenceChip(label: '匹配报告', available: app != null),
                      _EvidenceChip(
                          label: '原始简历', available: baseProfile != null),
                    ],
                  ),
                ),
                _DialogStepSection(
                  step: '4',
                  title: '本次生成策略',
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final wide = constraints.maxWidth >= 620;
                      const cards = [
                        _StrategyCard(
                            title: '突出 Agent 项目',
                            subtitle: '强化 AI Agent、工具调用和工程化表达。'),
                        _StrategyCard(
                            title: '补强量化成果', subtitle: '补充吞吐、响应、成本和业务影响。'),
                        _StrategyCard(
                            title: '补充关键词覆盖',
                            subtitle: '覆盖 LLM、RAG、LangChain 等岗位关键词。'),
                      ];
                      if (!wide) {
                        return Column(
                          children: [
                            for (final card in cards) ...[
                              card,
                              if (card != cards.last)
                                const SizedBox(height: 10),
                            ],
                          ],
                        );
                      }
                      return Row(
                        children: [
                          for (final card in cards) ...[
                            Expanded(child: card),
                            if (card != cards.last) const SizedBox(width: 10),
                          ],
                        ],
                      );
                    },
                  ),
                ),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: ProductSurface.softCard(
                    tone: ProductTone.primary,
                    radius: 12,
                  ),
                  child: Text(
                    '生成会创建新的简历版本，不会覆盖当前版本。',
                    style: AppTheme.ts(
                      fontSize: 12.2,
                      color: ProductColors.primary,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                const SizedBox(height: 18),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    OutlinedButton(
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Text('取消'),
                    ),
                    const SizedBox(width: 10),
                    OutlinedButton(
                      onPressed: baseProfile == null
                          ? null
                          : () => _showBaseResumeProfileDialog(
                                context,
                                baseProfile!,
                              ),
                      child: const Text('查看基础简历'),
                    ),
                    const SizedBox(width: 10),
                    ElevatedButton.icon(
                      onPressed: app == null || baseProfile == null
                          ? null
                          : () => onStart(app, strategy),
                      icon: const Icon(Icons.auto_awesome_rounded, size: 16),
                      label: const Text('开始生成草案'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: ProductColors.primary,
                        foregroundColor: Colors.white,
                        elevation: 0,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ResumeVersionDraftPreviewDialog extends StatefulWidget {
  final ResumeVersionDraftView draft;
  final CareerWorkbenchProvider provider;

  const _ResumeVersionDraftPreviewDialog({
    required this.draft,
    required this.provider,
  });

  @override
  State<_ResumeVersionDraftPreviewDialog> createState() =>
      _ResumeVersionDraftPreviewDialogState();
}

class _ResumeVersionDraftPreviewDialogState
    extends State<_ResumeVersionDraftPreviewDialog> {
  late final TextEditingController _titleController;
  late final TextEditingController _markdownController;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.draft.title);
    _markdownController = TextEditingController(text: widget.draft.markdown);
  }

  @override
  void dispose() {
    _titleController.dispose();
    _markdownController.dispose();
    super.dispose();
  }

  Future<void> _saveDraft() async {
    final title = _titleController.text.trim();
    final markdown = _markdownController.text.trim();
    if (title.isEmpty || markdown.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('标题和正文不能为空。')),
      );
      return;
    }
    setState(() => _isSaving = true);
    try {
      final version = await widget.provider.acceptResumeVersionDraft(
        resumeVersionDraftId: widget.draft.resumeVersionDraftId,
        title: title,
        markdown: markdown,
        linkApplication: true,
      );
      if (!mounted) return;
      Navigator.of(context).pop(version);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('保存草案失败：$error')),
      );
      setState(() => _isSaving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final viewport = MediaQuery.of(context).size;
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 920,
          maxHeight: viewport.height - 64,
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 22, 24, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  ProductIconTile(
                    icon: Icons.description_outlined,
                    tone: ProductTone.primary,
                    size: 40,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '岗位定制简历草案',
                          style: AppTheme.ts(
                            fontSize: 20,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.text,
                          ),
                        ),
                        const SizedBox(height: 5),
                        Text(
                          '请确认草案内容，保存后会生成新的简历版本，不覆盖当前版本。',
                          style: AppTheme.ts(
                            fontSize: 12.4,
                            color: ProductColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed:
                        _isSaving ? null : () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _titleController,
                enabled: !_isSaving,
                decoration: InputDecoration(
                  labelText: '版本标题',
                  filled: true,
                  fillColor: ProductColors.surfaceSoft,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: ProductColors.border),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: ProductColors.border),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: ProductColors.primary),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Expanded(
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final wide = constraints.maxWidth >= 760;
                    final editor = TextField(
                      controller: _markdownController,
                      enabled: !_isSaving,
                      minLines: wide ? 22 : 14,
                      maxLines: wide ? 30 : 20,
                      style: AppTheme.ts(
                        fontSize: 13,
                        height: 1.62,
                        color: ProductColors.text,
                      ),
                      decoration: InputDecoration(
                        alignLabelWithHint: true,
                        labelText: '草案正文（Markdown）',
                        filled: true,
                        fillColor: ProductColors.surface,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: BorderSide(color: ProductColors.border),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: BorderSide(color: ProductColors.border),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: BorderSide(color: ProductColors.primary),
                        ),
                      ),
                    );
                    final side = Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _DraftDetailCard(
                          icon: Icons.check_circle_outline_rounded,
                          title: '本版改动',
                          items: widget.draft.changeSummary,
                          tone: ProductTone.primary,
                        ),
                        const SizedBox(height: 10),
                        _DraftDetailCard(
                          icon: Icons.sell_outlined,
                          title: '关键词策略',
                          items: widget.draft.keywordStrategy,
                          tone: ProductTone.info,
                        ),
                        const SizedBox(height: 10),
                        _DraftDetailCard(
                          icon: Icons.warning_amber_rounded,
                          title: '风险提醒',
                          items: widget.draft.riskNotes,
                          tone: ProductTone.warning,
                        ),
                      ],
                    );
                    final content = wide
                        ? Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(flex: 3, child: editor),
                              const SizedBox(width: 14),
                              Expanded(flex: 2, child: side),
                            ],
                          )
                        : Column(
                            children: [
                              editor,
                              const SizedBox(height: 14),
                              side,
                            ],
                          );
                    return SingleChildScrollView(child: content);
                  },
                ),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Text(
                    '来源：${widget.draft.draftSource}',
                    style: AppTheme.ts(
                      fontSize: 12,
                      color: ProductColors.textMuted,
                    ),
                  ),
                  const Spacer(),
                  OutlinedButton(
                    onPressed:
                        _isSaving ? null : () => Navigator.of(context).pop(),
                    child: const Text('取消'),
                  ),
                  const SizedBox(width: 10),
                  ElevatedButton.icon(
                    onPressed: _isSaving ? null : _saveDraft,
                    icon: _isSaving
                        ? const SizedBox(
                            width: 15,
                            height: 15,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.check_rounded, size: 16),
                    label: Text(_isSaving ? '保存中' : '保存为新版本'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: ProductColors.primary,
                      foregroundColor: Colors.white,
                      elevation: 0,
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

class _DraftDetailCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final List<String> items;
  final ProductTone tone;

  const _DraftDetailCard({
    required this.icon,
    required this.title,
    required this.items,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    final visible =
        items.where((item) => item.trim().isNotEmpty).take(6).toList();
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: ProductSurface.card(radius: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ProductIconTile(icon: icon, tone: tone, size: 32),
              const SizedBox(width: 10),
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
          const SizedBox(height: 10),
          if (visible.isEmpty)
            Text(
              '暂无内容',
              style: AppTheme.ts(
                fontSize: 12,
                color: ProductColors.textSecondary,
              ),
            )
          else
            for (final item in visible) ...[
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    Icons.check_circle_rounded,
                    size: 15,
                    color: ProductColors.primary,
                  ),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      item,
                      style: AppTheme.ts(
                        fontSize: 12,
                        height: 1.42,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 7),
            ],
        ],
      ),
    );
  }
}

class _DialogStepSection extends StatelessWidget {
  final String step;
  final String title;
  final Widget child;

  const _DialogStepSection({
    required this.step,
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
                decoration: const BoxDecoration(
                  color: ProductColors.primary,
                  shape: BoxShape.circle,
                ),
                child: Center(
                  child: Text(
                    step,
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

class _DialogInfoTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Widget? trailing;

  const _DialogInfoTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          ProductIconTile(icon: icon, tone: ProductTone.primary, size: 36),
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
                    fontSize: 13,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.4,
                    color: ProductColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          if (trailing != null) ...[
            const SizedBox(width: 10),
            DefaultTextStyle(
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: ProductColors.textSecondary,
              ),
              child: trailing!,
            ),
          ],
        ],
      ),
    );
  }
}

class _EvidenceChip extends StatelessWidget {
  final String label;
  final bool available;

  const _EvidenceChip({
    required this.label,
    required this.available,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 190,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
      decoration: BoxDecoration(
        color: available ? ProductColors.surfaceSoft : ProductColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          Icon(
            available
                ? Icons.check_circle_rounded
                : Icons.radio_button_unchecked,
            size: 16,
            color: available ? ProductColors.primary : ProductColors.textMuted,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              label,
              style: AppTheme.ts(
                fontSize: 12.2,
                fontWeight: FontWeight.w800,
                color: ProductColors.text,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StrategyCard extends StatelessWidget {
  final String title;
  final String subtitle;

  const _StrategyCard({
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ProductColors.border),
      ),
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
          const SizedBox(height: 5),
          Text(
            subtitle,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 11.2,
              height: 1.35,
              color: ProductColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _OptimizeResumeDialog extends StatelessWidget {
  final _ResumeRecord? record;
  final CareerApplicationView? application;
  final ValueChanged<String> onStart;

  const _OptimizeResumeDialog({
    required this.record,
    required this.application,
    required this.onStart,
  });

  @override
  Widget build(BuildContext context) {
    const directions = [
      '强化项目量化成果',
      '补充岗位关键词',
      '压缩冗余经历',
      '突出工程化能力',
      '优化面试表达',
    ];
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 22, 24, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '优化此版本',
                      style: AppTheme.ts(
                        fontSize: 20,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                record == null ? '请选择要优化的简历版本。' : '当前版本：${record!.title}',
                style: AppTheme.ts(
                  fontSize: 12.5,
                  color: ProductColors.textSecondary,
                ),
              ),
              const SizedBox(height: 18),
              for (final direction in directions) ...[
                ProductActionTile(
                  title: direction,
                  subtitle: application == null
                      ? '基于当前简历内容生成优化草案。'
                      : '结合 ${application!.displayTitle} 的岗位要求生成优化草案。',
                  icon: Icons.auto_fix_high_outlined,
                  tone: ProductTone.primary,
                  actionLabel: '选择',
                  onTap: () => onStart(direction),
                ),
                if (direction != directions.last) const SizedBox(height: 8),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ExportResumeDialog extends StatelessWidget {
  final _ResumeRecord? record;
  final VoidCallback onClose;

  const _ExportResumeDialog({
    required this.record,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    final hasArtifact =
        record?.resumeVersion?.artifactId.trim().isNotEmpty == true;
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 20, 22, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '导出投递版',
                style: AppTheme.ts(
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 10),
              Text(
                hasArtifact
                    ? '当前版本已有 artifact，可接入下载或导出 API 后生成 PDF / DOCX / Markdown。'
                    : '当前版本缺少可导出 artifact。请先生成或保存一个简历版本。',
                style: AppTheme.ts(
                  fontSize: 12.5,
                  height: 1.5,
                  color: ProductColors.textSecondary,
                ),
              ),
              const SizedBox(height: 16),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: const [
                  _ExportFormatChip(label: 'PDF'),
                  _ExportFormatChip(label: 'DOCX'),
                  _ExportFormatChip(label: 'Markdown'),
                ],
              ),
              const SizedBox(height: 18),
              Align(
                alignment: Alignment.centerRight,
                child: ElevatedButton(
                  onPressed: onClose,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: ProductColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                  ),
                  child: const Text('知道了'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ExportFormatChip extends StatelessWidget {
  final String label;

  const _ExportFormatChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 34,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: ProductColors.border),
      ),
      child: Center(
        child: Text(
          label,
          style: AppTheme.ts(
            fontSize: 12,
            fontWeight: FontWeight.w800,
            color: ProductColors.textSecondary,
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

enum _ResumeFilter { all, current, targeted, general }

extension _ResumeFilterLabel on _ResumeFilter {
  String get label {
    return switch (this) {
      _ResumeFilter.all => '全部',
      _ResumeFilter.current => '当前使用',
      _ResumeFilter.targeted => '岗位定制',
      _ResumeFilter.general => '通用版本',
    };
  }
}

enum _ResumeStageMode { preview, compare }

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
    this.resumeVersion,
  });

  String get key => '${kind.name}:$id';

  bool get isTargetedVersion {
    return resumeVersion?.targetJdAnalysisId?.trim().isNotEmpty == true;
  }

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
  ];
  records.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  return records;
}

_ResumeRecord? _firstRecordOfKind(
  List<_ResumeRecord> records,
  _ResumeRecordKind kind,
) {
  for (final record in records) {
    if (record.kind == kind) return record;
  }
  return null;
}

List<_ResumeRecord> _filterResumeRecords(
  List<_ResumeRecord> records, {
  required _ResumeFilter filter,
  required String query,
  required String? selectedKey,
}) {
  final normalizedQuery = query.trim().toLowerCase();
  return records.where((record) {
    final matchesFilter = switch (filter) {
      _ResumeFilter.all => true,
      _ResumeFilter.current => selectedKey == null || record.key == selectedKey,
      _ResumeFilter.targeted => record.isTargetedVersion,
      _ResumeFilter.general => !record.isTargetedVersion,
    };
    if (!matchesFilter) return false;
    if (normalizedQuery.isEmpty) return true;
    final haystack = [
      record.title,
      record.subtitle,
      record.summary,
      ...record.keywords,
      ...record.risks,
    ].join(' ').toLowerCase();
    return haystack.contains(normalizedQuery);
  }).toList();
}

_ResumeRecord? _compareTargetRecord(
  List<_ResumeRecord> records,
  _ResumeRecord? current,
) {
  if (records.length < 2) return null;
  for (final record in records) {
    if (record.key != current?.key) return record;
  }
  return records.first;
}

Future<void> _showBaseResumeProfileDialog(
  BuildContext context,
  ResumeProfileView profile,
) async {
  final skills = _stringifyList(profile.skills).take(12).toList();
  final projects = _stringifyList(profile.projectExperience).take(4).toList();
  final work = _stringifyList(profile.workExperience).take(3).toList();
  final diagnosis = _diagnosisScore(profile);
  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return Dialog(
        insetPadding: const EdgeInsets.all(24),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760, maxHeight: 780),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(22, 20, 22, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    ProductIconTile(
                      icon: Icons.badge_outlined,
                      tone: ProductTone.primary,
                      size: 42,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${profile.displayName} 的基础简历画像',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 18,
                              fontWeight: FontWeight.w900,
                              color: ProductColors.text,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '基础画像用于生成和优化简历版本，不会在这里直接编辑。',
                            style: AppTheme.ts(
                              fontSize: 12.4,
                              color: ProductColors.textSecondary,
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (diagnosis != null)
                      ProductTag(
                        label: '诊断 $diagnosis',
                        tone: ProductTone.primary,
                      ),
                    IconButton(
                      tooltip: '关闭',
                      onPressed: () => Navigator.of(dialogContext).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: ListView(
                    children: [
                      _BaseProfileDialogSection(
                        title: '核心技能',
                        emptyText: '暂无技能画像。',
                        items: skills,
                        tone: ProductTone.primary,
                      ),
                      const SizedBox(height: 12),
                      _BaseProfileDialogSection(
                        title: '项目经历',
                        emptyText: '暂无项目经历。',
                        items: projects,
                        tone: ProductTone.info,
                      ),
                      const SizedBox(height: 12),
                      _BaseProfileDialogSection(
                        title: '工作经历',
                        emptyText: '暂无工作经历。',
                        items: work,
                        tone: ProductTone.warning,
                      ),
                      if (profile.selfEvaluation.trim().isNotEmpty) ...[
                        const SizedBox(height: 12),
                        _BaseProfileTextSection(
                          title: '自我评价',
                          text: profile.selfEvaluation.trim(),
                        ),
                      ],
                    ],
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

class _BaseProfileDialogSection extends StatelessWidget {
  final String title;
  final String emptyText;
  final List<String> items;
  final ProductTone tone;

  const _BaseProfileDialogSection({
    required this.title,
    required this.emptyText,
    required this.items,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: style.soft.withValues(alpha: 0.42),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: style.color.withValues(alpha: 0.13)),
      ),
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
          const SizedBox(height: 10),
          if (items.isEmpty)
            Text(
              emptyText,
              style: AppTheme.ts(
                fontSize: 12.4,
                color: ProductColors.textMuted,
              ),
            )
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final item in items) ProductTag(label: item, tone: tone),
              ],
            ),
        ],
      ),
    );
  }
}

class _BaseProfileTextSection extends StatelessWidget {
  final String title;
  final String text;

  const _BaseProfileTextSection({
    required this.title,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
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
          const SizedBox(height: 8),
          Text(
            text,
            style: AppTheme.ts(
              fontSize: 12.6,
              height: 1.55,
              color: ProductColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
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
