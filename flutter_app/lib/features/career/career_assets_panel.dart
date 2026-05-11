import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/career_assets_provider.dart';
import '../../core/providers/chat_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/utils/download_stub.dart'
    if (dart.library.html) '../../shared/utils/download_web.dart';
import '../../shared/widgets/career_report.dart';
import '../../shared/widgets/markdown_body.dart';

class CareerAssetsPanel extends ConsumerStatefulWidget {
  final VoidCallback onClose;
  final bool compact;

  const CareerAssetsPanel({
    super.key,
    required this.onClose,
    this.compact = false,
  });

  @override
  ConsumerState<CareerAssetsPanel> createState() => _CareerAssetsPanelState();
}

class _CareerAssetsPanelState extends ConsumerState<CareerAssetsPanel> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(careerAssetsProvider).ensureLoaded());
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<bool>(
      chatProvider.select((provider) => provider.isStreaming),
      (previous, next) {
        if (previous == true && !next) {
          unawaited(ref.read(careerAssetsProvider).refresh());
        }
      },
    );
    final provider = ref.watch(careerAssetsProvider);
    return Container(
      decoration: AppTheme.floatingPanelDecoration(
        radius: widget.compact ? 24 : 28,
        alpha: 0.92,
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          CareerAssetsHeader(
            isRefreshing: provider.isRefreshing,
            assetCount: _groupedAssetCount(provider),
            recordCount: provider.totalCount,
            latestUpdatedAt: _latestUpdatedAt(provider),
            onRefresh: () => unawaited(provider.refresh()),
            onClose: widget.onClose,
          ),
          CareerAssetTabBar(
            activeTab: provider.activeTab,
            provider: provider,
            onChanged: provider.setTab,
          ),
          Expanded(child: _CareerAssetsBody(provider: provider)),
        ],
      ),
    );
  }
}

class CareerAssetsHeader extends StatelessWidget {
  final bool isRefreshing;
  final int assetCount;
  final int recordCount;
  final DateTime? latestUpdatedAt;
  final VoidCallback onRefresh;
  final VoidCallback onClose;

  const CareerAssetsHeader({
    super.key,
    required this.isRefreshing,
    required this.assetCount,
    required this.recordCount,
    required this.latestUpdatedAt,
    required this.onRefresh,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 12, 12),
      child: Row(
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: AppTheme.accent.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: AppTheme.accent.withValues(alpha: 0.22),
              ),
            ),
            child: Icon(
              Icons.work_outline_rounded,
              size: 18,
              color: AppTheme.accent,
            ),
          ),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                "求职资产",
                style: AppTheme.ts(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                _headerSubtitle,
                style: AppTheme.ts(
                  fontSize: 11,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
          const Spacer(),
          _PanelIconButton(
            icon: isRefreshing
                ? Icons.hourglass_top_rounded
                : Icons.refresh_rounded,
            onTap: onRefresh,
          ),
          const SizedBox(width: 6),
          _PanelIconButton(icon: Icons.close_rounded, onTap: onClose),
        ],
      ),
    );
  }

  String get _headerSubtitle {
    if (isRefreshing) {
      return "正在刷新资产";
    }
    final updated = latestUpdatedAt;
    if (updated == null) {
      return "$assetCount 个可用资产 · $recordCount 条记录";
    }
    return "$assetCount 个可用资产 · $recordCount 条记录 · ${_formatTime(updated)}";
  }
}

class CareerAssetTabBar extends StatelessWidget {
  final CareerAssetsTab activeTab;
  final CareerAssetsProvider provider;
  final ValueChanged<CareerAssetsTab> onChanged;

  const CareerAssetTabBar({
    super.key,
    required this.activeTab,
    required this.provider,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    const tabs = CareerAssetsTab.values;
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(18, 0, 18, 12),
      child: Row(
        children: [
          for (final tab in tabs) ...[
            _TabButton(
              icon: _tabIcon(tab),
              label: _tabLabel(tab),
              count: _tabCount(provider, tab),
              selected: tab == activeTab,
              onTap: () => onChanged(tab),
            ),
            if (tab != tabs.last) const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }
}

class _CareerAssetsBody extends StatelessWidget {
  final CareerAssetsProvider provider;

  const _CareerAssetsBody({required this.provider});

  @override
  Widget build(BuildContext context) {
    if (provider.isLoading) {
      return const CareerAssetLoadingState();
    }
    if (provider.error != null) {
      return CareerAssetErrorState(
        error: provider.error!,
        onRetry: provider.refresh,
      );
    }
    if (provider.totalCount == 0) {
      return CareerAssetEmptyState(onRefresh: provider.refresh);
    }

    return Scrollbar(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(18, 0, 18, 20),
        children: [
          _CareerAssetsOverview(provider: provider),
          const SizedBox(height: 10),
          CareerAssetList(provider: provider),
        ],
      ),
    );
  }
}

class CareerAssetList extends StatelessWidget {
  final CareerAssetsProvider provider;

  const CareerAssetList({super.key, required this.provider});

  @override
  Widget build(BuildContext context) {
    final entries = <_CareerAssetCardEntry>[];
    final tab = provider.activeTab;
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.resumes) {
      entries.addAll(
        _groupResumeProfiles(provider.resumeProfiles).map(
          (group) {
            final item = group.current as ResumeProfileView;
            return _CareerAssetCardEntry(
              record: item,
              card: ResumeProfileCard(
                record: item,
                selected: _isSelected(provider.selection, item.resumeProfileId),
                highlighted: _groupHighlighted(provider, group),
                onDetails: () => _showDetails(context, provider, item),
                onPreviewArtifact:
                    _preview(context, provider, item.meta.sourceSessionId),
                previewError: _previewErrorForRecord(provider, item),
                historyCount: group.records.length,
                onHistory: group.records.length > 1
                    ? () => _showHistory(context, provider, group)
                    : null,
              ),
            );
          },
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.profiles) {
      entries.addAll(
        _groupCareerProfiles(provider.careerProfiles).map(
          (group) {
            final item = group.current as CareerProfileView;
            return _CareerAssetCardEntry(
              record: item,
              card: CareerProfileCard(
                record: item,
                selected: _isSelected(provider.selection, item.careerProfileId),
                highlighted: _groupHighlighted(provider, group),
                onDetails: () => _showDetails(context, provider, item),
                historyCount: group.records.length,
                onHistory: group.records.length > 1
                    ? () => _showHistory(context, provider, group)
                    : null,
              ),
            );
          },
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.jobs) {
      entries.addAll(
        _groupJdAnalyses(provider.jdAnalyses).map(
          (group) {
            final item = group.current as JDAnalysisView;
            return _CareerAssetCardEntry(
              record: item,
              card: JDAnalysisCard(
                record: item,
                selected: _isSelected(provider.selection, item.jdAnalysisId),
                highlighted: _groupHighlighted(provider, group),
                onDetails: () => _showDetails(context, provider, item),
                onPreviewArtifact:
                    _preview(context, provider, item.meta.sourceSessionId),
                previewError: _previewErrorForRecord(provider, item),
                historyCount: group.records.length,
                onHistory: group.records.length > 1
                    ? () => _showHistory(context, provider, group)
                    : null,
              ),
            );
          },
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.fitReports) {
      entries.addAll(
        _groupJobFitReports(provider.jobFitReports).map(
          (group) {
            final item = group.current as JobFitReportView;
            return _CareerAssetCardEntry(
              record: item,
              card: JobFitReportCard(
                record: item,
                selected: _isSelected(provider.selection, item.jobFitReportId),
                highlighted: _groupHighlighted(provider, group),
                onDetails: () => _showDetails(context, provider, item),
                onPreviewArtifact:
                    _preview(context, provider, item.meta.sourceSessionId),
                previewError: _previewErrorForRecord(provider, item),
                historyCount: group.records.length,
                onHistory: group.records.length > 1
                    ? () => _showHistory(context, provider, group)
                    : null,
              ),
            );
          },
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.versions) {
      entries.addAll(
        _groupResumeVersions(provider.resumeVersions).map(
          (group) {
            final item = group.current as ResumeVersionView;
            return _CareerAssetCardEntry(
              record: item,
              card: ResumeVersionCard(
                record: item,
                selected: _isSelected(provider.selection, item.resumeVersionId),
                highlighted: _groupHighlighted(provider, group),
                onDetails: () => _showDetails(context, provider, item),
                onPreviewArtifact:
                    _preview(context, provider, item.meta.sourceSessionId),
                previewError: _previewErrorForRecord(provider, item),
                historyCount: group.records.length,
                onHistory: group.records.length > 1
                    ? () => _showHistory(context, provider, group)
                    : null,
              ),
            );
          },
        ),
      );
    }
    if (entries.isEmpty) {
      return _InlineEmptyState(message: "${_tabLabel(tab)}暂无记录");
    }
    if (tab == CareerAssetsTab.all) {
      entries.sort((a, b) => _recordUpdatedAt(b.record).compareTo(
            _recordUpdatedAt(a.record),
          ));
    }
    return Column(
      children: [
        for (final entry in entries) ...[
          entry.card,
          const SizedBox(height: 10),
        ],
      ],
    );
  }

  bool _isSelected(CareerAssetSelection? selection, String recordId) {
    return selection?.recordId == recordId;
  }

  void _showDetails(
    BuildContext context,
    CareerAssetsProvider provider,
    Object record,
  ) {
    provider.selectRecord(record);
    _showCareerAssetDetailSheet(
      context,
      CareerAssetSelection.fromRecord(record),
    );
  }

  void _showHistory(
    BuildContext context,
    CareerAssetsProvider provider,
    _CareerAssetGroup group,
  ) {
    _showCareerAssetHistorySheet(context, provider, group);
  }

  ArtifactPreviewCallback _preview(
    BuildContext context,
    CareerAssetsProvider provider,
    String sourceSessionId,
  ) {
    return (artifactId) => _showArtifactPreviewSheet(
          context,
          provider,
          sourceSessionId: sourceSessionId,
          artifactId: artifactId,
        );
  }
}

class _CareerAssetCardEntry {
  final Object record;
  final Widget card;

  const _CareerAssetCardEntry({
    required this.record,
    required this.card,
  });
}

typedef ArtifactPreviewCallback = Future<void> Function(String artifactId);

class _CareerAssetsOverview extends StatelessWidget {
  final CareerAssetsProvider provider;

  const _CareerAssetsOverview({required this.provider});

  @override
  Widget build(BuildContext context) {
    final groups = _groupsForTab(provider, provider.activeTab);
    if (groups.isEmpty) {
      return const SizedBox.shrink();
    }
    final recordCount = groups.fold<int>(
      0,
      (sum, group) => sum + group.records.length,
    );
    final hiddenHistoryCount = recordCount - groups.length;
    final latest = groups.first.current;
    final latestType = _recordTypeLabel(latest);
    final latestTitle = _recordTitle(latest);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 11),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppTheme.accent.withValues(alpha: AppTheme.isDark ? 0.12 : 0.08),
            AppTheme.surfaceHover
                .withValues(alpha: AppTheme.isDark ? 0.18 : 0.44),
          ],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.16)),
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
                  color: AppTheme.accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(11),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.18),
                  ),
                ),
                child: Icon(
                  Icons.auto_awesome_motion_outlined,
                  size: 16,
                  color: AppTheme.accent,
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "当前资产视图",
                      style: AppTheme.ts(
                        fontSize: 12.5,
                        height: 1.15,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      hiddenHistoryCount > 0
                          ? "优先展示最新资产，历史版本已收起"
                          : "优先展示最新可用资产",
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.6,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 11),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              _AssetOverviewPill(
                icon: Icons.layers_outlined,
                label: "${groups.length} 个当前资产",
                color: AppTheme.accent,
              ),
              if (hiddenHistoryCount > 0)
                _AssetOverviewPill(
                  icon: Icons.history_rounded,
                  label: "$hiddenHistoryCount 条历史已收起",
                  color: AppTheme.textTertiary,
                ),
              _AssetOverviewPill(
                icon: Icons.schedule_rounded,
                label: "最新 ${_formatTime(_recordUpdatedAt(latest))}",
                color: AppTheme.textTertiary,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
            decoration: BoxDecoration(
              color: AppTheme.surface
                  .withValues(alpha: AppTheme.isDark ? 0.42 : 0.78),
              borderRadius: BorderRadius.circular(12),
              border:
                  Border.all(color: AppTheme.border.withValues(alpha: 0.58)),
            ),
            child: Row(
              children: [
                Icon(
                  _recordTypeIcon(latest),
                  size: 15,
                  color: AppTheme.accent,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text.rich(
                    TextSpan(
                      children: [
                        TextSpan(text: "$latestType · "),
                        TextSpan(
                          text: latestTitle,
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                      ],
                    ),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 11.5,
                      height: 1.32,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.textSecondary,
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

class _AssetOverviewPill extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;

  const _AssetOverviewPill({
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
        border: Border.all(color: color.withValues(alpha: 0.13)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 5),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 10.5,
              height: 1.1,
              fontWeight: FontWeight.w800,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerAssetGroup {
  final String key;
  final String title;
  final List<Object> records;

  const _CareerAssetGroup({
    required this.key,
    required this.title,
    required this.records,
  });

  Object get current => records.first;
}

List<_CareerAssetGroup> _groupsForTab(
  CareerAssetsProvider provider,
  CareerAssetsTab tab,
) {
  final groups = <_CareerAssetGroup>[];
  if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.resumes) {
    groups.addAll(_groupResumeProfiles(provider.resumeProfiles));
  }
  if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.profiles) {
    groups.addAll(_groupCareerProfiles(provider.careerProfiles));
  }
  if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.jobs) {
    groups.addAll(_groupJdAnalyses(provider.jdAnalyses));
  }
  if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.fitReports) {
    groups.addAll(_groupJobFitReports(provider.jobFitReports));
  }
  if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.versions) {
    groups.addAll(_groupResumeVersions(provider.resumeVersions));
  }
  groups.sort((a, b) => _recordUpdatedAt(b.current).compareTo(
        _recordUpdatedAt(a.current),
      ));
  return groups;
}

List<_CareerAssetGroup> _groupResumeProfiles(List<ResumeProfileView> records) {
  return _groupRecords<ResumeProfileView>(
    records,
    keyOf: (record) => _firstNonEmpty([
      record.displayName,
      record.rawTextArtifactId,
      record.meta.sourceArtifactId,
      record.resumeProfileId,
    ]),
    titleOf: (record) => record.displayName,
    idOf: (record) => record.resumeProfileId,
    updatedAtOf: (record) => record.meta.updatedAt,
  );
}

List<_CareerAssetGroup> _groupCareerProfiles(List<CareerProfileView> records) {
  return _groupRecords<CareerProfileView>(
    records,
    keyOf: (record) => _firstNonEmpty([
      record.careerProfileId,
      record.careerGoal,
    ]),
    titleOf: (record) =>
        record.careerGoal.isEmpty ? record.careerProfileId : record.careerGoal,
    idOf: (record) => record.careerProfileId,
    updatedAtOf: (record) => record.meta.updatedAt,
  );
}

List<_CareerAssetGroup> _groupJdAnalyses(List<JDAnalysisView> records) {
  return _groupRecords<JDAnalysisView>(
    records,
    keyOf: (record) => _firstNonEmpty([
      record.meta.sourceArtifactId,
      [record.company, record.position]
          .where((item) => item.trim().isNotEmpty)
          .join("|"),
      record.jdAnalysisId,
    ]),
    titleOf: (record) => record.displayTitle,
    idOf: (record) => record.jdAnalysisId,
    updatedAtOf: (record) => record.meta.updatedAt,
  );
}

List<_CareerAssetGroup> _groupJobFitReports(List<JobFitReportView> records) {
  return _groupRecords<JobFitReportView>(
    records,
    keyOf: (record) => _firstNonEmpty([
      "${record.resumeProfileId}|${record.jdAnalysisId}",
      record.jobFitReportId,
    ]),
    titleOf: (record) => "${record.overallScore} 分 · ${record.recommendation}",
    idOf: (record) => record.jobFitReportId,
    updatedAtOf: (record) => record.meta.updatedAt,
  );
}

List<_CareerAssetGroup> _groupResumeVersions(List<ResumeVersionView> records) {
  return _groupRecords<ResumeVersionView>(
    records,
    keyOf: (record) => _firstNonEmpty([
      "${record.baseResumeProfileId}|${record.targetJdAnalysisId ?? ""}|${record.format}",
      record.resumeVersionId,
    ]),
    titleOf: (record) =>
        record.title.isEmpty ? record.resumeVersionId : record.title,
    idOf: (record) => record.resumeVersionId,
    updatedAtOf: (record) => record.meta.updatedAt,
  );
}

List<_CareerAssetGroup> _groupRecords<T extends Object>(
  List<T> records, {
  required String Function(T record) keyOf,
  required String Function(T record) titleOf,
  required String Function(T record) idOf,
  required DateTime Function(T record) updatedAtOf,
}) {
  final grouped = <String, List<T>>{};
  for (final record in records) {
    final key = keyOf(record).trim();
    grouped.putIfAbsent(key.isEmpty ? idOf(record) : key, () => []).add(record);
  }
  final result = grouped.entries.map((entry) {
    final items = [...entry.value]
      ..sort((a, b) => updatedAtOf(b).compareTo(updatedAtOf(a)));
    return _CareerAssetGroup(
      key: entry.key,
      title: titleOf(items.first),
      records: items,
    );
  }).toList()
    ..sort((a, b) => _recordUpdatedAt(b.current).compareTo(
          _recordUpdatedAt(a.current),
        ));
  return result;
}

bool _groupHighlighted(CareerAssetsProvider provider, _CareerAssetGroup group) {
  return group.records.any(
    (record) => provider.isRecentlyCreated(_recordId(record)),
  );
}

String _firstNonEmpty(List<String?> values) {
  for (final value in values) {
    final normalized = value?.trim() ?? "";
    if (normalized.isNotEmpty) {
      return normalized;
    }
  }
  return "";
}

void _showCareerAssetDetailSheet(
  BuildContext context,
  CareerAssetSelection selection,
) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (sheetContext) {
      return _SheetFrame(
        maxWidth: 620,
        heightFactor: 0.46,
        child: _CareerAssetDetailSheet(selection: selection),
      );
    },
  );
}

void _showCareerAssetHistorySheet(
  BuildContext context,
  CareerAssetsProvider provider,
  _CareerAssetGroup group,
) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (sheetContext) {
      return _SheetFrame(
        maxWidth: 680,
        heightFactor: 0.82,
        child: _CareerAssetHistorySheet(
          group: group,
          provider: provider,
        ),
      );
    },
  );
}

Future<void> _showArtifactPreviewSheet(
  BuildContext context,
  CareerAssetsProvider provider, {
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
      return _SheetFrame(
        maxWidth: 1120,
        heightFactor: 0.92,
        child: _ArtifactPreviewSheet(
          artifactId: artifactId,
          previewFuture: previewFuture,
          downloadUrl: downloadUrl,
        ),
      );
    },
  );
}

class _SheetFrame extends StatelessWidget {
  final Widget child;
  final double maxWidth;
  final double heightFactor;

  const _SheetFrame({
    required this.child,
    required this.maxWidth,
    required this.heightFactor,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: FractionallySizedBox(
        heightFactor: heightFactor,
        child: Align(
          alignment: Alignment.bottomCenter,
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: maxWidth),
            child: Container(
              margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              decoration: AppTheme.floatingPanelDecoration(
                radius: 22,
                alpha: 0.96,
              ),
              clipBehavior: Clip.antiAlias,
              child: child,
            ),
          ),
        ),
      ),
    );
  }
}

class _CareerAssetDetailSheet extends StatelessWidget {
  final CareerAssetSelection selection;

  const _CareerAssetDetailSheet({required this.selection});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _SheetHeader(
          icon: Icons.tune_rounded,
          title: _selectionTitle(selection),
          subtitle: "产品记录详情",
          onClose: () => Navigator.of(context).pop(),
        ),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 18),
            child: CareerAssetDetailPane(selection: selection),
          ),
        ),
      ],
    );
  }
}

class _CareerAssetHistorySheet extends StatelessWidget {
  final _CareerAssetGroup group;
  final CareerAssetsProvider provider;

  const _CareerAssetHistorySheet({
    required this.group,
    required this.provider,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _SheetHeader(
          icon: Icons.history_rounded,
          title: group.title,
          subtitle: "${group.records.length} 条历史记录 · 最新在上",
          onClose: () => Navigator.of(context).pop(),
        ),
        Expanded(
          child: ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 18),
            itemCount: group.records.length,
            separatorBuilder: (_, __) => const SizedBox(height: 10),
            itemBuilder: (context, index) {
              final record = group.records[index];
              return _HistoryTimelineItem(
                record: record,
                isCurrent: index == 0,
                provider: provider,
              );
            },
          ),
        ),
      ],
    );
  }
}

class _HistoryTimelineItem extends StatelessWidget {
  final Object record;
  final bool isCurrent;
  final CareerAssetsProvider provider;

  const _HistoryTimelineItem({
    required this.record,
    required this.isCurrent,
    required this.provider,
  });

  @override
  Widget build(BuildContext context) {
    final meta = _recordMeta(record);
    final preview = _previewSpecForRecord(record);
    final previewState = _previewAvailabilityForRecord(provider, record);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
      decoration: BoxDecoration(
        color: isCurrent
            ? AppTheme.accent.withValues(alpha: 0.09)
            : AppTheme.surface.withValues(alpha: 0.78),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isCurrent
              ? AppTheme.accent.withValues(alpha: 0.24)
              : AppTheme.border,
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Column(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(9),
                  border: Border.all(
                      color: AppTheme.accent.withValues(alpha: 0.18)),
                ),
                child: Icon(
                  isCurrent ? Icons.check_rounded : Icons.history_rounded,
                  size: 15,
                  color: AppTheme.accent,
                ),
              ),
            ],
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                        _recordTitle(record),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 13,
                          height: 1.3,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    if (isCurrent) ...[
                      const SizedBox(width: 8),
                      _StatusDot(status: "当前"),
                    ],
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  "${_recordTypeLabel(record)} · 更新于 ${_formatTime(meta.updatedAt)}",
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    color: AppTheme.textTertiary,
                  ),
                ),
                const SizedBox(height: 9),
                _PreviewStatusPill(state: previewState),
                const SizedBox(height: 9),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    _AssetActionButton(
                      label: "详情",
                      icon: Icons.tune_rounded,
                      onTap: () => _showCareerAssetDetailSheet(
                        context,
                        CareerAssetSelection.fromRecord(record),
                      ),
                    ),
                    if (preview != null)
                      _AssetActionButton(
                        label: preview.label,
                        icon: Icons.visibility_outlined,
                        primary: true,
                        onTap: () => _showArtifactPreviewSheet(
                          context,
                          provider,
                          sourceSessionId: preview.sourceSessionId,
                          artifactId: preview.artifactId,
                        ),
                      )
                    else
                      const _UnavailablePreviewBadge(),
                    _AssetActionButton(
                      label: "复制 ID",
                      icon: Icons.copy_rounded,
                      onTap: () => _copyText(
                        context,
                        _recordId(record),
                        "记录 ID 已复制",
                      ),
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

class _ArtifactPreviewSheet extends StatelessWidget {
  final String artifactId;
  final Future<SessionArtifactContentView> previewFuture;
  final String downloadUrl;

  const _ArtifactPreviewSheet({
    required this.artifactId,
    required this.previewFuture,
    required this.downloadUrl,
  });

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<SessionArtifactContentView>(
      future: previewFuture,
      builder: (context, snapshot) {
        final preview = snapshot.data;
        final title =
            preview == null || preview.title.isEmpty ? "文件预览" : preview.title;
        final isCareerReport =
            preview != null && CareerReportView.canRender(preview.content);
        return Column(
          children: [
            _ArtifactPreviewHeader(
              title: title,
              artifactId: artifactId,
              preview: preview,
              isCareerReport: isCareerReport,
              onCopyId: () => _copyText(context, artifactId, "文件编号已复制"),
              onCopyContent: preview == null
                  ? () {}
                  : () => _copyText(context, preview.content, "预览内容已复制"),
              onDownload: () => _openDownload(context, downloadUrl),
              onClose: () => Navigator.of(context).pop(),
            ),
            Expanded(
              child: _ArtifactPreviewStage(
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 180),
                  child: _previewBody(context, snapshot),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _previewBody(
    BuildContext context,
    AsyncSnapshot<SessionArtifactContentView> snapshot,
  ) {
    if (snapshot.connectionState != ConnectionState.done) {
      return const _ArtifactPreviewLoading();
    }
    if (snapshot.hasError) {
      return _ArtifactPreviewError(error: snapshot.error.toString());
    }
    final preview = snapshot.data;
    if (preview == null) {
      return const _ArtifactPreviewError(error: "未读取到 artifact 内容");
    }
    final isCareerReport = CareerReportView.canRender(preview.content);
    return _ArtifactPreviewReader(
      key: const ValueKey("artifact-preview-content"),
      preview: preview,
      isCareerReport: isCareerReport,
    );
  }
}

class _ArtifactPreviewStage extends StatelessWidget {
  final Widget child;

  const _ArtifactPreviewStage({required this.child});

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned.fill(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.2 : 0.48),
                  AppTheme.surfaceHover
                      .withValues(alpha: AppTheme.isDark ? 0.08 : 0.3),
                ],
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
              ),
            ),
          ),
        ),
        Positioned.fill(child: child),
        const _ArtifactPreviewEdgeFade(alignment: Alignment.topCenter),
        const _ArtifactPreviewEdgeFade(alignment: Alignment.bottomCenter),
      ],
    );
  }
}

class _ArtifactPreviewHeader extends StatelessWidget {
  final String title;
  final String artifactId;
  final SessionArtifactContentView? preview;
  final bool isCareerReport;
  final VoidCallback onCopyId;
  final VoidCallback onCopyContent;
  final VoidCallback onDownload;
  final VoidCallback onClose;

  const _ArtifactPreviewHeader({
    required this.title,
    required this.artifactId,
    required this.preview,
    required this.isCareerReport,
    required this.onCopyId,
    required this.onCopyContent,
    required this.onDownload,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    final loaded = preview != null;
    final metaChips = <Widget>[
      _ArtifactPreviewMetaChip(
        icon: isCareerReport
            ? Icons.dashboard_customize_outlined
            : Icons.notes_rounded,
        label: loaded ? (isCareerReport ? "报告阅读" : "Markdown 预览") : "正在准备",
        color: AppTheme.accent,
      ),
      if (loaded)
        _ArtifactPreviewMetaChip(
          icon: Icons.short_text_rounded,
          label: _previewCharacterLabel(preview!),
          color: AppTheme.textSecondary,
        ),
      if (preview?.truncated == true)
        const _ArtifactPreviewMetaChip(
          icon: Icons.content_cut_rounded,
          label: "内容已截断",
          color: Color(0xFFB45309),
        ),
    ];
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 15, 14, 14),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.96),
        border: Border(
          bottom: BorderSide(color: AppTheme.border.withValues(alpha: 0.64)),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: AppTheme.isDark ? 0.1 : 0.03),
            blurRadius: 14,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 680;
          final icon =
              _ArtifactPreviewHeaderIcon(isCareerReport: isCareerReport);
          final titleBlock = _ArtifactPreviewTitleBlock(
            title: title,
            loaded: loaded,
            isCareerReport: isCareerReport,
            metaChips: metaChips,
          );
          final actions = _ArtifactPreviewActionCluster(
            loaded: loaded,
            onDownload: onDownload,
            onCopyContent: onCopyContent,
            onCopyId: onCopyId,
            onClose: onClose,
          );

          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    icon,
                    const SizedBox(width: 12),
                    Expanded(child: titleBlock),
                  ],
                ),
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerRight,
                  child: actions,
                ),
              ],
            );
          }

          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              icon,
              const SizedBox(width: 12),
              Expanded(child: titleBlock),
              const SizedBox(width: 14),
              actions,
            ],
          );
        },
      ),
    );
  }
}

class _ArtifactPreviewHeaderIcon extends StatelessWidget {
  final bool isCareerReport;

  const _ArtifactPreviewHeaderIcon({required this.isCareerReport});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.11),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.2)),
      ),
      child: Icon(
        isCareerReport ? Icons.fact_check_outlined : Icons.article_outlined,
        size: 19,
        color: AppTheme.accent,
      ),
    );
  }
}

class _ArtifactPreviewTitleBlock extends StatelessWidget {
  final String title;
  final bool loaded;
  final bool isCareerReport;
  final List<Widget> metaChips;

  const _ArtifactPreviewTitleBlock({
    required this.title,
    required this.loaded,
    required this.isCareerReport,
    required this.metaChips,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          loaded ? (isCareerReport ? "报告阅读器" : "文档预览") : "正在准备文档",
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppTheme.ts(
            fontSize: 10.5,
            height: 1.1,
            fontWeight: FontWeight.w800,
            color: AppTheme.accent,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          title,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: AppTheme.ts(
            fontSize: 15.5,
            fontWeight: FontWeight.w800,
            height: 1.22,
            color: AppTheme.textPrimary,
          ),
        ),
        const SizedBox(height: 9),
        Wrap(
          spacing: 7,
          runSpacing: 7,
          children: metaChips,
        ),
      ],
    );
  }
}

class _ArtifactPreviewActionCluster extends StatelessWidget {
  final bool loaded;
  final VoidCallback onDownload;
  final VoidCallback onCopyContent;
  final VoidCallback onCopyId;
  final VoidCallback onClose;

  const _ArtifactPreviewActionCluster({
    required this.loaded,
    required this.onDownload,
    required this.onCopyContent,
    required this.onCopyId,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.34 : 0.58),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.7)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (loaded) ...[
            _ArtifactHeaderPrimaryButton(
              icon: Icons.download_rounded,
              label: "下载",
              onTap: onDownload,
            ),
            const SizedBox(width: 4),
            _PanelIconButton(
              icon: Icons.content_copy_rounded,
              tooltip: "复制内容",
              onTap: onCopyContent,
            ),
            const SizedBox(width: 4),
          ],
          _PanelIconButton(
            icon: Icons.tag_rounded,
            tooltip: "复制文件编号",
            onTap: onCopyId,
          ),
          const SizedBox(width: 4),
          _PanelIconButton(
            icon: Icons.close_rounded,
            tooltip: "关闭",
            onTap: onClose,
          ),
        ],
      ),
    );
  }
}

class _ArtifactHeaderPrimaryButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _ArtifactHeaderPrimaryButton({
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
          height: 34,
          padding: const EdgeInsets.symmetric(horizontal: 11),
          decoration: BoxDecoration(
            color: AppTheme.accent.withValues(alpha: 0.13),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.accent.withValues(alpha: 0.23)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: AppTheme.accent),
              const SizedBox(width: 6),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 11.5,
                  height: 1,
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

class _ArtifactPreviewMetaChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;

  const _ArtifactPreviewMetaChip({
    required this.icon,
    required this.label,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: AppTheme.isDark ? 0.12 : 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.15)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12.5, color: color),
          const SizedBox(width: 5),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 10.8,
              height: 1.1,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class _ArtifactPreviewReader extends StatelessWidget {
  final SessionArtifactContentView preview;
  final bool isCareerReport;

  const _ArtifactPreviewReader({
    super.key,
    required this.preview,
    required this.isCareerReport,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 760;
        final maxWidth = isCareerReport ? 900.0 : 780.0;
        final horizontalPadding = wide ? 28.0 : 14.0;
        return Scrollbar(
          child: SingleChildScrollView(
            padding: EdgeInsets.fromLTRB(
              horizontalPadding,
              wide ? 24 : 16,
              horizontalPadding,
              wide ? 42 : 28,
            ),
            child: Center(
              child: ConstrainedBox(
                constraints: BoxConstraints(maxWidth: maxWidth),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (preview.truncated) ...[
                      const _ArtifactPreviewNotice(),
                      const SizedBox(height: 12),
                    ],
                    _ArtifactReaderSurface(
                      isCareerReport: isCareerReport,
                      child: isCareerReport
                          ? CareerReportView(
                              content: preview.content,
                              readerMode: true,
                            )
                          : _ArtifactMarkdownDocument(
                              content: preview.content,
                            ),
                    ),
                    const SizedBox(height: 10),
                    _ArtifactReaderFootnote(
                      artifactId: preview.artifactId,
                      characterLabel: _previewCharacterLabel(preview),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _ArtifactReaderSurface extends StatelessWidget {
  final bool isCareerReport;
  final Widget child;

  const _ArtifactReaderSurface({
    required this.isCareerReport,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final contentPadding = EdgeInsets.fromLTRB(
      isCareerReport ? 14 : 18,
      isCareerReport ? 14 : 18,
      isCareerReport ? 14 : 18,
      isCareerReport ? 16 : 20,
    );
    return Container(
      width: double.infinity,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.68 : 0.9),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppTheme.borderLight.withValues(alpha: 0.64)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.14 : 0.055),
            blurRadius: 26,
            offset: const Offset(0, 16),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            height: isCareerReport ? 4 : 3,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  AppTheme.accent.withValues(alpha: 0.72),
                  const Color(0xFF2563EB)
                      .withValues(alpha: AppTheme.isDark ? 0.44 : 0.34),
                  AppTheme.accent.withValues(alpha: 0.12),
                ],
              ),
            ),
          ),
          Padding(
            padding: contentPadding,
            child: child,
          ),
        ],
      ),
    );
  }
}

class _ArtifactReaderFootnote extends StatelessWidget {
  final String artifactId;
  final String characterLabel;

  const _ArtifactReaderFootnote({
    required this.artifactId,
    required this.characterLabel,
  });

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.center,
      child: Wrap(
        spacing: 8,
        runSpacing: 6,
        alignment: WrapAlignment.center,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _ArtifactPreviewMetaChip(
            icon: Icons.short_text_rounded,
            label: characterLabel,
            color: AppTheme.textTertiary,
          ),
          _ArtifactPreviewMetaChip(
            icon: Icons.fingerprint_rounded,
            label: _shortArtifactId(artifactId),
            color: AppTheme.textTertiary,
          ),
        ],
      ),
    );
  }
}

class _ArtifactPreviewNotice extends StatelessWidget {
  const _ArtifactPreviewNotice();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: const Color(0xFFB45309).withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: const Color(0xFFB45309).withValues(alpha: 0.18),
        ),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.content_cut_rounded,
            size: 16,
            color: Color(0xFFB45309),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              "当前为预览片段，下载原文件可查看完整内容。",
              style: AppTheme.ts(
                fontSize: 11.5,
                height: 1.35,
                fontWeight: FontWeight.w700,
                color: const Color(0xFFB45309),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ArtifactPreviewEdgeFade extends StatelessWidget {
  final Alignment alignment;

  const _ArtifactPreviewEdgeFade({required this.alignment});

  @override
  Widget build(BuildContext context) {
    final isTop = alignment == Alignment.topCenter;
    return IgnorePointer(
      child: Align(
        alignment: alignment,
        child: Container(
          height: isTop ? 18 : 34,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: isTop ? Alignment.topCenter : Alignment.bottomCenter,
              end: isTop ? Alignment.bottomCenter : Alignment.topCenter,
              colors: [
                AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.46 : 0.66),
                AppTheme.bg.withValues(alpha: 0),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ArtifactMarkdownDocument extends StatelessWidget {
  final String content;

  const _ArtifactMarkdownDocument({
    required this.content,
  });

  @override
  Widget build(BuildContext context) {
    return AppMarkdownBody(
      content: content,
      style: AppTheme.ts(
        fontSize: 13.6,
        height: 1.7,
        color: AppTheme.textPrimary,
      ),
    );
  }
}

String _shortArtifactId(String value) {
  final normalized = value.trim();
  if (normalized.length <= 18) {
    return normalized;
  }
  return "${normalized.substring(0, 10)}...${normalized.substring(normalized.length - 5)}";
}

String _previewCharacterLabel(SessionArtifactContentView preview) {
  final formatter = NumberFormat.decimalPattern("zh_CN");
  final returned = formatter.format(preview.returnedChars);
  final total = formatter.format(preview.totalChars);
  if (preview.returnedChars == preview.totalChars) {
    return "$total 字符";
  }
  return "$returned / $total 字符";
}

class _SheetHeader extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onClose;

  const _SheetHeader({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 12, 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: AppTheme.accent.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(11),
              border: Border.all(color: AppTheme.accent.withValues(alpha: 0.2)),
            ),
            child: Icon(icon, size: 17, color: AppTheme.accent),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    height: 1.25,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 4),
                SelectableText(
                  subtitle,
                  style: AppTheme.ts(
                    fontSize: 11,
                    height: 1.35,
                    color: AppTheme.textTertiary,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          _PanelIconButton(
            icon: Icons.close_rounded,
            tooltip: "关闭",
            onTap: onClose,
          ),
        ],
      ),
    );
  }
}

class _ArtifactPreviewLoading extends StatelessWidget {
  const _ArtifactPreviewLoading();

  @override
  Widget build(BuildContext context) {
    return Center(
      key: const ValueKey("artifact-preview-loading"),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: AppTheme.accent,
                  ),
                ),
                const SizedBox(width: 12),
                Text(
                  "正在读取文件正文",
                  style: AppTheme.ts(
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            const _ArtifactPreviewSkeletonCard(),
          ],
        ),
      ),
    );
  }
}

class _ArtifactPreviewSkeletonCard extends StatelessWidget {
  const _ArtifactPreviewSkeletonCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 20),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.74),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.borderLight.withValues(alpha: 0.72)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _ArtifactPreviewSkeletonLine(widthFactor: 0.34, height: 18),
          const SizedBox(height: 12),
          const _ArtifactPreviewSkeletonLine(widthFactor: 0.88),
          const SizedBox(height: 8),
          const _ArtifactPreviewSkeletonLine(widthFactor: 0.72),
          const SizedBox(height: 18),
          Row(
            children: const [
              Expanded(child: _ArtifactPreviewSkeletonLine(height: 72)),
              SizedBox(width: 10),
              Expanded(child: _ArtifactPreviewSkeletonLine(height: 72)),
            ],
          ),
          const SizedBox(height: 10),
          const _ArtifactPreviewSkeletonLine(widthFactor: 0.94),
          const SizedBox(height: 8),
          const _ArtifactPreviewSkeletonLine(widthFactor: 0.66),
        ],
      ),
    );
  }
}

class _ArtifactPreviewSkeletonLine extends StatelessWidget {
  final double widthFactor;
  final double height;

  const _ArtifactPreviewSkeletonLine({
    this.widthFactor = 1,
    this.height = 12,
  });

  @override
  Widget build(BuildContext context) {
    return FractionallySizedBox(
      widthFactor: widthFactor,
      alignment: Alignment.centerLeft,
      child: Container(
        height: height,
        decoration: BoxDecoration(
          color: AppTheme.surfaceActive.withValues(alpha: 0.68),
          borderRadius: BorderRadius.circular(999),
        ),
      ),
    );
  }
}

class _ArtifactPreviewError extends StatelessWidget {
  final String error;

  const _ArtifactPreviewError({required this.error});

  @override
  Widget build(BuildContext context) {
    return Center(
      key: const ValueKey("artifact-preview-error"),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline_rounded, size: 30, color: AppTheme.danger),
            const SizedBox(height: 10),
            Text(
              "预览失败",
              style: AppTheme.ts(
                fontSize: 14,
                fontWeight: FontWeight.w800,
                color: AppTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              error,
              textAlign: TextAlign.center,
              style: AppTheme.ts(
                fontSize: 11.5,
                height: 1.5,
                color: AppTheme.textTertiary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class ResumeProfileCard extends StatelessWidget {
  final ResumeProfileView record;
  final bool selected;
  final bool highlighted;
  final VoidCallback onDetails;
  final ArtifactPreviewCallback onPreviewArtifact;
  final String? previewError;
  final int historyCount;
  final VoidCallback? onHistory;

  const ResumeProfileCard({
    super.key,
    required this.record,
    required this.selected,
    required this.highlighted,
    required this.onDetails,
    required this.onPreviewArtifact,
    this.previewError,
    this.historyCount = 1,
    this.onHistory,
  });

  @override
  Widget build(BuildContext context) {
    return _CareerAssetCardShell(
      icon: Icons.badge_outlined,
      label: "简历画像",
      title: record.displayName,
      id: record.resumeProfileId,
      meta: record.meta,
      selected: selected,
      highlighted: highlighted,
      onDetails: onDetails,
      previewExpected: true,
      previewLabel: "预览诊断",
      previewArtifactId: record.diagnosisArtifactId,
      onPreviewArtifact: onPreviewArtifact,
      previewError: previewError,
      historyCount: historyCount,
      onHistory: onHistory,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _MetricRow(
            items: [
              _MetricItem("技能", record.skills.length),
              _MetricItem("项目", record.projectExperience.length),
              _MetricItem("经历", record.workExperience.length),
            ],
          ),
        ],
      ),
    );
  }
}

class CareerProfileCard extends StatelessWidget {
  final CareerProfileView record;
  final bool selected;
  final bool highlighted;
  final VoidCallback onDetails;
  final int historyCount;
  final VoidCallback? onHistory;

  const CareerProfileCard({
    super.key,
    required this.record,
    required this.selected,
    required this.highlighted,
    required this.onDetails,
    this.historyCount = 1,
    this.onHistory,
  });

  @override
  Widget build(BuildContext context) {
    return _CareerAssetCardShell(
      icon: Icons.track_changes_rounded,
      label: "职业画像",
      title: record.careerGoal.isEmpty
          ? record.careerProfileId
          : record.careerGoal,
      id: record.careerProfileId,
      meta: record.meta,
      selected: selected,
      highlighted: highlighted,
      onDetails: onDetails,
      historyCount: historyCount,
      onHistory: onHistory,
      child: _ChipWrap(
        values: [
          ...record.targetRoles.take(4),
          ...record.preferredCities.take(2),
        ],
        emptyText: "暂无目标岗位或城市",
      ),
    );
  }
}

class JDAnalysisCard extends StatelessWidget {
  final JDAnalysisView record;
  final bool selected;
  final bool highlighted;
  final VoidCallback onDetails;
  final ArtifactPreviewCallback onPreviewArtifact;
  final String? previewError;
  final int historyCount;
  final VoidCallback? onHistory;

  const JDAnalysisCard({
    super.key,
    required this.record,
    required this.selected,
    required this.highlighted,
    required this.onDetails,
    required this.onPreviewArtifact,
    this.previewError,
    this.historyCount = 1,
    this.onHistory,
  });

  @override
  Widget build(BuildContext context) {
    return _CareerAssetCardShell(
      icon: Icons.article_outlined,
      label: "JD 分析",
      title: record.displayTitle,
      id: record.jdAnalysisId,
      meta: record.meta,
      selected: selected,
      highlighted: highlighted,
      onDetails: onDetails,
      previewExpected: true,
      previewLabel: "预览 JD",
      previewArtifactId: record.meta.sourceArtifactId,
      onPreviewArtifact: onPreviewArtifact,
      previewError: previewError,
      historyCount: historyCount,
      onHistory: onHistory,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ChipWrap(
            values: record.requiredSkills.take(5).toList(),
            emptyText: "暂无必备技能",
          ),
        ],
      ),
    );
  }
}

class JobFitReportCard extends StatelessWidget {
  final JobFitReportView record;
  final bool selected;
  final bool highlighted;
  final VoidCallback onDetails;
  final ArtifactPreviewCallback onPreviewArtifact;
  final String? previewError;
  final int historyCount;
  final VoidCallback? onHistory;

  const JobFitReportCard({
    super.key,
    required this.record,
    required this.selected,
    required this.highlighted,
    required this.onDetails,
    required this.onPreviewArtifact,
    this.previewError,
    this.historyCount = 1,
    this.onHistory,
  });

  @override
  Widget build(BuildContext context) {
    return _CareerAssetCardShell(
      icon: Icons.fact_check_outlined,
      label: "匹配报告",
      title: "${record.overallScore} 分 · ${record.recommendation}",
      id: record.jobFitReportId,
      meta: record.meta,
      selected: selected,
      highlighted: highlighted,
      onDetails: onDetails,
      previewExpected: true,
      previewLabel: "预览报告",
      previewArtifactId: record.reportArtifactId,
      onPreviewArtifact: onPreviewArtifact,
      previewError: previewError,
      historyCount: historyCount,
      onHistory: onHistory,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ChipWrap(
            values: _dynamicItems(record.gaps).take(4).toList(),
            emptyText: "暂无主要差距",
          ),
        ],
      ),
    );
  }
}

class ResumeVersionCard extends StatelessWidget {
  final ResumeVersionView record;
  final bool selected;
  final bool highlighted;
  final VoidCallback onDetails;
  final ArtifactPreviewCallback onPreviewArtifact;
  final String? previewError;
  final int historyCount;
  final VoidCallback? onHistory;

  const ResumeVersionCard({
    super.key,
    required this.record,
    required this.selected,
    required this.highlighted,
    required this.onDetails,
    required this.onPreviewArtifact,
    this.previewError,
    this.historyCount = 1,
    this.onHistory,
  });

  @override
  Widget build(BuildContext context) {
    return _CareerAssetCardShell(
      icon: Icons.description_outlined,
      label: "简历版本",
      title: record.title.isEmpty ? record.resumeVersionId : record.title,
      id: record.resumeVersionId,
      meta: record.meta,
      selected: selected,
      highlighted: highlighted,
      onDetails: onDetails,
      previewExpected: true,
      previewLabel: "预览简历",
      previewArtifactId: record.artifactId,
      onPreviewArtifact: onPreviewArtifact,
      previewError: previewError,
      historyCount: historyCount,
      onHistory: onHistory,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ChipWrap(
            values: record.changeSummary.take(4).toList(),
            emptyText: "暂无变更摘要",
          ),
        ],
      ),
    );
  }
}

class CareerAssetDetailPane extends StatelessWidget {
  final CareerAssetSelection selection;

  const CareerAssetDetailPane({super.key, required this.selection});

  @override
  Widget build(BuildContext context) {
    final record = selection.record;
    final lines = _detailLines(record);
    final meta = _recordMeta(record);
    final debugLines = _debugLines(record, selection, meta);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _PanelSection(
          title: "资产摘要",
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final line in lines)
                _DetailLine(label: line.$1, value: line.$2),
              _DetailLine(label: "状态", value: _statusLabel(meta.status)),
              _DetailLine(label: "更新时间", value: _formatTime(meta.updatedAt)),
            ],
          ),
        ),
        const SizedBox(height: 10),
        _DebugInfoDisclosure(lines: debugLines),
      ],
    );
  }

  CareerRecordMetaView _recordMeta(Object record) {
    if (record is ResumeProfileView) return record.meta;
    if (record is CareerProfileView) return record.meta;
    if (record is JDAnalysisView) return record.meta;
    if (record is JobFitReportView) return record.meta;
    if (record is ResumeVersionView) return record.meta;
    throw ArgumentError("Unsupported career asset record type.");
  }

  List<(String, String)> _detailLines(Object record) {
    if (record is ResumeProfileView) {
      return [
        ("姓名", record.displayName),
        ("技能", _joinDynamic(record.skills)),
        ("项目数", record.projectExperience.length.toString()),
      ];
    }
    if (record is CareerProfileView) {
      return [
        ("职业目标", record.careerGoal),
        ("目标岗位", record.targetRoles.join("、")),
        ("目标城市", record.preferredCities.join("、")),
        ("优势", record.strengths.join("、")),
        ("短板", record.weaknesses.join("、")),
      ];
    }
    if (record is JDAnalysisView) {
      return [
        ("公司", record.company),
        ("岗位", record.position),
        ("职级", record.seniority),
        ("关键词", record.keywords.join("、")),
        ("风险信号", record.riskSignals.join("、")),
      ];
    }
    if (record is JobFitReportView) {
      return [
        ("总分", record.overallScore.toString()),
        ("建议", record.recommendation),
      ];
    }
    if (record is ResumeVersionView) {
      return [
        ("标题", record.title),
        ("格式", record.format),
      ];
    }
    return const [];
  }

  List<(String, String)> _debugLines(
    Object record,
    CareerAssetSelection selection,
    CareerRecordMetaView meta,
  ) {
    final lines = <(String, String)>[
      ("记录 ID", selection.recordId),
      ("来源会话", selection.sourceSessionId),
      ("来源文件", meta.sourceArtifactId ?? "-"),
      ("证据引用", meta.evidenceRefs.join("、")),
      ("创建时间", _formatTime(meta.createdAt)),
      ("更新时间", _formatTime(meta.updatedAt)),
    ];
    if (record is ResumeProfileView) {
      lines.add(("诊断 artifact", record.diagnosisArtifactId ?? "-"));
      lines.add(("原文 artifact", record.rawTextArtifactId ?? "-"));
    }
    if (record is JobFitReportView) {
      lines.add(("JD 分析", record.jdAnalysisId));
      lines.add(("简历画像", record.resumeProfileId));
      lines.add(("报告 artifact", record.reportArtifactId ?? "-"));
    }
    if (record is ResumeVersionView) {
      lines.add(("基础简历", record.baseResumeProfileId));
      lines.add(("目标 JD", record.targetJdAnalysisId ?? "-"));
      lines.add(("正文 artifact", record.artifactId));
    }
    return lines;
  }
}

class CareerAssetEmptyState extends StatelessWidget {
  final VoidCallback onRefresh;

  const CareerAssetEmptyState({super.key, required this.onRefresh});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.inventory_2_outlined,
              size: 34,
              color: AppTheme.textTertiary,
            ),
            const SizedBox(height: 12),
            Text(
              "暂无求职资产",
              style: AppTheme.ts(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: AppTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              "完成简历诊断、JD 分析或定制简历后会出现在这里",
              textAlign: TextAlign.center,
              style: AppTheme.ts(
                fontSize: 12,
                height: 1.5,
                color: AppTheme.textTertiary,
              ),
            ),
            const SizedBox(height: 14),
            _TextActionButton(label: "刷新", onTap: onRefresh),
          ],
        ),
      ),
    );
  }
}

class CareerAssetErrorState extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const CareerAssetErrorState({
    super.key,
    required this.error,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline_rounded, size: 34, color: AppTheme.danger),
            const SizedBox(height: 12),
            Text(
              "求职资产加载失败",
              style: AppTheme.ts(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: AppTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              error,
              textAlign: TextAlign.center,
              style: AppTheme.ts(
                fontSize: 11,
                height: 1.5,
                color: AppTheme.textTertiary,
              ),
            ),
            const SizedBox(height: 14),
            _TextActionButton(label: "重试", onTap: onRetry),
          ],
        ),
      ),
    );
  }
}

class CareerAssetLoadingState extends StatelessWidget {
  const CareerAssetLoadingState({super.key});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SizedBox(
        width: 24,
        height: 24,
        child:
            CircularProgressIndicator(strokeWidth: 2, color: AppTheme.accent),
      ),
    );
  }
}

class _CareerAssetCardShell extends StatelessWidget {
  final IconData icon;
  final String label;
  final String title;
  final String id;
  final CareerRecordMetaView meta;
  final bool selected;
  final bool highlighted;
  final VoidCallback onDetails;
  final bool previewExpected;
  final String? previewLabel;
  final String? previewArtifactId;
  final ArtifactPreviewCallback? onPreviewArtifact;
  final String? previewError;
  final int historyCount;
  final VoidCallback? onHistory;
  final Widget child;

  const _CareerAssetCardShell({
    required this.icon,
    required this.label,
    required this.title,
    required this.id,
    required this.meta,
    required this.selected,
    required this.highlighted,
    required this.onDetails,
    this.previewExpected = false,
    this.previewLabel,
    this.previewArtifactId,
    this.onPreviewArtifact,
    this.previewError,
    this.historyCount = 1,
    this.onHistory,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final canPreview = previewArtifactId != null &&
        previewArtifactId!.trim().isNotEmpty &&
        onPreviewArtifact != null;
    final previewState = _previewAvailability(
      previewExpected: previewExpected,
      canPreview: canPreview,
      error: previewError,
    );
    final borderColor = selected
        ? AppTheme.accent.withValues(alpha: 0.38)
        : highlighted
            ? AppTheme.accent.withValues(alpha: 0.26)
            : AppTheme.borderLight.withValues(alpha: 0.78);
    final baseColor = selected
        ? AppTheme.accent.withValues(alpha: 0.1)
        : highlighted
            ? AppTheme.accent.withValues(alpha: 0.065)
            : AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.78 : 0.9);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 11),
      decoration: BoxDecoration(
        color: baseColor,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: borderColor),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(
              alpha: AppTheme.isDark
                  ? (highlighted ? 0.2 : 0.12)
                  : (highlighted ? 0.08 : 0.035),
            ),
            blurRadius: highlighted ? 18 : 12,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _AssetIconBadge(icon: icon, highlighted: highlighted),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        _AssetMetaPill(
                          icon: _assetTypeIcon(label),
                          label: label,
                          color: AppTheme.accent,
                          strong: true,
                        ),
                        _StatusDot(status: meta.status),
                        if (historyCount > 1)
                          _AssetMetaPill(
                            icon: Icons.history_rounded,
                            label: "$historyCount 版",
                            color: AppTheme.textTertiary,
                          ),
                        if (highlighted) const _NewRecordBadge(),
                      ],
                    ),
                    const SizedBox(height: 7),
                    Text(
                      title.isEmpty ? id : title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 14,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                        height: 1.22,
                      ),
                    ),
                    const SizedBox(height: 7),
                    _AssetInlineMetaRow(
                      previewState: previewState,
                      updatedAt: meta.updatedAt,
                    ),
                    if (historyCount > 1) ...[
                      const SizedBox(height: 9),
                      _AssetVersionNotice(
                        historyCount: historyCount,
                        onHistory: onHistory,
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _AssetSummaryFrame(child: child),
          const SizedBox(height: 12),
          _AssetPrimaryAction(
            label: canPreview ? (previewLabel ?? "预览") : "查看详情",
            icon: canPreview ? Icons.visibility_outlined : Icons.tune_rounded,
            onTap: canPreview
                ? () => onPreviewArtifact!(previewArtifactId!)
                : onDetails,
          ),
          if (canPreview || (historyCount > 1 && onHistory != null)) ...[
            const SizedBox(height: 9),
            Row(
              children: [
                if (canPreview)
                  Expanded(
                    child: _AssetActionButton(
                      label: "详情",
                      icon: Icons.tune_rounded,
                      onTap: onDetails,
                    ),
                  ),
                if (canPreview && historyCount > 1 && onHistory != null)
                  const SizedBox(width: 8),
                if (historyCount > 1 && onHistory != null)
                  Expanded(
                    child: _AssetActionButton(
                      label: "历史 $historyCount",
                      icon: Icons.history_rounded,
                      onTap: onHistory!,
                    ),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _AssetIconBadge extends StatelessWidget {
  final IconData icon;
  final bool highlighted;

  const _AssetIconBadge({required this.icon, required this.highlighted});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 34,
      height: 34,
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: highlighted ? 0.16 : 0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.22)),
      ),
      child: Icon(icon, size: 17, color: AppTheme.accent),
    );
  }
}

class _AssetSummaryFrame extends StatelessWidget {
  final Widget child;

  const _AssetSummaryFrame({required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.2 : 0.34),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.72)),
      ),
      child: child,
    );
  }
}

class _AssetMetaPill extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final bool strong;

  const _AssetMetaPill({
    required this.icon,
    required this.label,
    required this.color,
    this.strong = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: strong ? 0.12 : 0.065),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: strong ? 0.2 : 0.12)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 4),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 10,
              height: 1.1,
              fontWeight: strong ? FontWeight.w800 : FontWeight.w700,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class _AssetPrimaryAction extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback onTap;

  const _AssetPrimaryAction({
    required this.label,
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
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: AppTheme.accent.withValues(alpha: 0.13),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.accent.withValues(alpha: 0.24)),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 15, color: AppTheme.accent),
              const SizedBox(width: 7),
              Flexible(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.accent,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NewRecordBadge extends StatelessWidget {
  const _NewRecordBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.22)),
      ),
      child: Text(
        "新",
        style: AppTheme.ts(
          fontSize: 9.5,
          fontWeight: FontWeight.w800,
          color: AppTheme.accent,
        ),
      ),
    );
  }
}

class _PreviewStatus {
  final String label;
  final IconData icon;
  final Color color;

  const _PreviewStatus({
    required this.label,
    required this.icon,
    required this.color,
  });
}

class _PreviewStatusPill extends StatelessWidget {
  final _PreviewStatus state;

  const _PreviewStatusPill({required this.state});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: state.color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: state.color.withValues(alpha: 0.14)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(state.icon, size: 13, color: state.color),
          const SizedBox(width: 4),
          Text(
            state.label,
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: state.color,
            ),
          ),
        ],
      ),
    );
  }
}

class _AssetInlineMetaRow extends StatelessWidget {
  final _PreviewStatus previewState;
  final DateTime updatedAt;

  const _AssetInlineMetaRow({
    required this.previewState,
    required this.updatedAt,
  });

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 10,
      runSpacing: 5,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _AssetInlineMeta(
          icon: previewState.icon,
          label: previewState.label,
          color: previewState.color,
          strong: true,
        ),
        _AssetInlineMeta(
          icon: Icons.schedule_rounded,
          label: "更新 ${_formatTime(updatedAt)}",
          color: AppTheme.textTertiary,
        ),
      ],
    );
  }
}

class _AssetInlineMeta extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final bool strong;

  const _AssetInlineMeta({
    required this.icon,
    required this.label,
    required this.color,
    this.strong = false,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 12, color: color),
        const SizedBox(width: 4),
        Text(
          label,
          style: AppTheme.ts(
            fontSize: 10.5,
            height: 1.1,
            fontWeight: strong ? FontWeight.w700 : FontWeight.w600,
            color: color,
          ),
        ),
      ],
    );
  }
}

class _AssetVersionNotice extends StatelessWidget {
  final int historyCount;
  final VoidCallback? onHistory;

  const _AssetVersionNotice({
    required this.historyCount,
    required this.onHistory,
  });

  @override
  Widget build(BuildContext context) {
    final hiddenCount = historyCount - 1;
    final content = Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(9, 7, 8, 7),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: AppTheme.isDark ? 0.08 : 0.06),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.12)),
      ),
      child: Row(
        children: [
          Icon(
            Icons.stacked_line_chart_rounded,
            size: 13,
            color: AppTheme.accent,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              "当前版本 · $hiddenCount 版历史已收起",
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 10.8,
                fontWeight: FontWeight.w700,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
          if (onHistory != null) ...[
            const SizedBox(width: 8),
            Text(
              "查看",
              style: AppTheme.ts(
                fontSize: 10.8,
                fontWeight: FontWeight.w800,
                color: AppTheme.accent,
              ),
            ),
          ],
        ],
      ),
    );
    if (onHistory == null) {
      return content;
    }
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(11),
        onTap: onHistory,
        child: content,
      ),
    );
  }
}

class _PanelSection extends StatelessWidget {
  final String title;
  final Widget child;

  const _PanelSection({required this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.76),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppTheme.textTertiary,
            ),
          ),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }
}

class _DebugInfoDisclosure extends StatefulWidget {
  final List<(String, String)> lines;

  const _DebugInfoDisclosure({required this.lines});

  @override
  State<_DebugInfoDisclosure> createState() => _DebugInfoDisclosureState();
}

class _DebugInfoDisclosureState extends State<_DebugInfoDisclosure> {
  var _expanded = false;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.64),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        children: [
          Material(
            color: Colors.transparent,
            child: InkWell(
              borderRadius: BorderRadius.circular(12),
              onTap: () => setState(() => _expanded = !_expanded),
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
                child: Row(
                  children: [
                    Icon(
                      Icons.bug_report_outlined,
                      size: 15,
                      color: AppTheme.textTertiary,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        "调试信息",
                        style: AppTheme.ts(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textSecondary,
                        ),
                      ),
                    ),
                    Icon(
                      _expanded
                          ? Icons.keyboard_arrow_up_rounded
                          : Icons.keyboard_arrow_down_rounded,
                      size: 18,
                      color: AppTheme.textTertiary,
                    ),
                  ],
                ),
              ),
            ),
          ),
          AnimatedCrossFade(
            firstChild: const SizedBox.shrink(),
            secondChild: Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Divider(height: 1, color: AppTheme.border),
                  const SizedBox(height: 10),
                  for (final line in widget.lines)
                    _DetailLine(label: line.$1, value: line.$2),
                ],
              ),
            ),
            crossFadeState: _expanded
                ? CrossFadeState.showSecond
                : CrossFadeState.showFirst,
            duration: const Duration(milliseconds: 160),
          ),
        ],
      ),
    );
  }
}

class _TabButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final int count;
  final bool selected;
  final VoidCallback onTap;

  const _TabButton({
    required this.icon,
    required this.label,
    required this.count,
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
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
          decoration: BoxDecoration(
            color: selected
                ? AppTheme.accent.withValues(alpha: 0.15)
                : AppTheme.surface.withValues(alpha: 0.62),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected
                  ? AppTheme.accent.withValues(alpha: 0.28)
                  : AppTheme.border,
            ),
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
                "$label $count",
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: selected ? AppTheme.accent : AppTheme.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MetricItem {
  final String label;
  final int value;

  const _MetricItem(this.label, this.value);
}

class _MetricRow extends StatelessWidget {
  final List<_MetricItem> items;

  const _MetricRow({required this.items});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (final item in items) ...[
          Expanded(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
              decoration: BoxDecoration(
                color: AppTheme.bg.withValues(alpha: 0.34),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: AppTheme.border),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.value.toString(),
                    style: AppTheme.ts(
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                  Text(
                    item.label,
                    style: AppTheme.ts(
                      fontSize: 10.5,
                      color: AppTheme.textTertiary,
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (item != items.last) const SizedBox(width: 8),
        ],
      ],
    );
  }
}

class _ChipWrap extends StatelessWidget {
  final List<String> values;
  final String emptyText;

  const _ChipWrap({required this.values, required this.emptyText});

  @override
  Widget build(BuildContext context) {
    final normalized = values
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    if (normalized.isEmpty) {
      return Text(
        emptyText,
        style: AppTheme.ts(fontSize: 11, color: AppTheme.textTertiary),
      );
    }
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final item in normalized)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
            decoration: BoxDecoration(
              color: AppTheme.bg.withValues(alpha: 0.34),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: AppTheme.border),
            ),
            child: Text(
              item,
              style: AppTheme.ts(fontSize: 10.5, color: AppTheme.textSecondary),
            ),
          ),
      ],
    );
  }
}

class _AssetActionButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback onTap;
  final bool primary;

  const _AssetActionButton({
    required this.label,
    required this.icon,
    required this.onTap,
    this.primary = false,
  });

  @override
  Widget build(BuildContext context) {
    final color = primary ? AppTheme.accent : AppTheme.textSecondary;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: color.withValues(alpha: primary ? 0.13 : 0.06),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: color.withValues(alpha: primary ? 0.24 : 0.12),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 14, color: color),
              const SizedBox(width: 6),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
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

class _UnavailablePreviewBadge extends StatelessWidget {
  const _UnavailablePreviewBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: AppTheme.textTertiary.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.textTertiary.withValues(alpha: 0.1)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.visibility_off_outlined,
            size: 14,
            color: AppTheme.textTertiary,
          ),
          const SizedBox(width: 6),
          Text(
            "无预览文件",
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppTheme.textTertiary,
            ),
          ),
        ],
      ),
    );
  }
}

class _DetailLine extends StatelessWidget {
  final String label;
  final String value;

  const _DetailLine({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    final display = value.trim().isEmpty ? "-" : value.trim();
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: AppTheme.ts(fontSize: 11, color: AppTheme.textTertiary),
            ),
          ),
          Expanded(
            child: SelectableText(
              display,
              style: AppTheme.ts(
                fontSize: 11.5,
                height: 1.45,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusDot extends StatelessWidget {
  final String status;

  const _StatusDot({required this.status});

  @override
  Widget build(BuildContext context) {
    final active = status == "active";
    final label = _statusLabel(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: (active ? AppTheme.accent : AppTheme.textTertiary)
            .withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 9.5,
          fontWeight: FontWeight.w700,
          color: active ? AppTheme.accent : AppTheme.textTertiary,
        ),
      ),
    );
  }
}

class _PanelIconButton extends StatelessWidget {
  final IconData icon;
  final String? tooltip;
  final VoidCallback onTap;

  const _PanelIconButton({
    required this.icon,
    this.tooltip,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final button = Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.82),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.border),
          ),
          child: Icon(icon, size: 17, color: AppTheme.textSecondary),
        ),
      ),
    );
    final message = tooltip;
    if (message == null || message.isEmpty) {
      return button;
    }
    return Tooltip(message: message, child: button);
  }
}

class _TextActionButton extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const _TextActionButton({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
          decoration: BoxDecoration(
            color: AppTheme.accent.withValues(alpha: 0.14),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppTheme.accent.withValues(alpha: 0.24)),
          ),
          child: Text(
            label,
            style: AppTheme.ts(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppTheme.accent,
            ),
          ),
        ),
      ),
    );
  }
}

class _InlineEmptyState extends StatelessWidget {
  final String message;

  const _InlineEmptyState({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      child: Text(
        message,
        style: AppTheme.ts(fontSize: 12, color: AppTheme.textTertiary),
      ),
    );
  }
}

class _PreviewSpec {
  final String label;
  final String sourceSessionId;
  final String artifactId;

  const _PreviewSpec({
    required this.label,
    required this.sourceSessionId,
    required this.artifactId,
  });
}

int _groupedAssetCount(CareerAssetsProvider provider) {
  return _tabCount(provider, CareerAssetsTab.all);
}

DateTime? _latestUpdatedAt(CareerAssetsProvider provider) {
  final times = <DateTime>[
    ...provider.resumeProfiles.map((item) => item.meta.updatedAt),
    ...provider.careerProfiles.map((item) => item.meta.updatedAt),
    ...provider.jdAnalyses.map((item) => item.meta.updatedAt),
    ...provider.jobFitReports.map((item) => item.meta.updatedAt),
    ...provider.resumeVersions.map((item) => item.meta.updatedAt),
  ];
  if (times.isEmpty) return null;
  times.sort((a, b) => b.compareTo(a));
  return times.first;
}

String? _previewErrorForRecord(CareerAssetsProvider provider, Object record) {
  final preview = _previewSpecForRecord(record);
  if (preview == null) return null;
  return provider.artifactPreviewError(
    sourceSessionId: preview.sourceSessionId,
    artifactId: preview.artifactId,
  );
}

_PreviewStatus _previewAvailabilityForRecord(
  CareerAssetsProvider provider,
  Object record,
) {
  final preview = _previewSpecForRecord(record);
  if (preview == null) {
    return _previewAvailability(
      previewExpected: _previewExpectedForRecord(record),
      canPreview: false,
      error: null,
    );
  }
  return _previewAvailability(
    previewExpected: true,
    canPreview: true,
    error: provider.artifactPreviewError(
      sourceSessionId: preview.sourceSessionId,
      artifactId: preview.artifactId,
    ),
  );
}

bool _previewExpectedForRecord(Object record) {
  return record is ResumeProfileView ||
      record is JDAnalysisView ||
      record is JobFitReportView ||
      record is ResumeVersionView;
}

_PreviewStatus _previewAvailability({
  required bool previewExpected,
  required bool canPreview,
  required String? error,
}) {
  if (!previewExpected) {
    return _PreviewStatus(
      label: "产品记录",
      icon: Icons.layers_outlined,
      color: AppTheme.textTertiary,
    );
  }
  if (!canPreview) {
    return _PreviewStatus(
      label: "无文件",
      icon: Icons.visibility_off_outlined,
      color: AppTheme.textTertiary,
    );
  }
  if (error != null && error.trim().isNotEmpty) {
    return _PreviewStatus(
      label: "读取失败",
      icon: Icons.error_outline_rounded,
      color: AppTheme.danger,
    );
  }
  return _PreviewStatus(
    label: "可预览",
    icon: Icons.visibility_outlined,
    color: AppTheme.accent,
  );
}

String _selectionTitle(CareerAssetSelection selection) {
  return _recordTitle(selection.record);
}

CareerRecordMetaView _recordMeta(Object record) {
  if (record is ResumeProfileView) return record.meta;
  if (record is CareerProfileView) return record.meta;
  if (record is JDAnalysisView) return record.meta;
  if (record is JobFitReportView) return record.meta;
  if (record is ResumeVersionView) return record.meta;
  throw ArgumentError("Unsupported career asset record type.");
}

String _recordId(Object record) {
  if (record is ResumeProfileView) return record.resumeProfileId;
  if (record is CareerProfileView) return record.careerProfileId;
  if (record is JDAnalysisView) return record.jdAnalysisId;
  if (record is JobFitReportView) return record.jobFitReportId;
  if (record is ResumeVersionView) return record.resumeVersionId;
  return "";
}

DateTime _recordUpdatedAt(Object record) {
  return _recordMeta(record).updatedAt;
}

String _recordTitle(Object record) {
  if (record is ResumeProfileView) return record.displayName;
  if (record is CareerProfileView) {
    return record.careerGoal.isEmpty
        ? record.careerProfileId
        : record.careerGoal;
  }
  if (record is JDAnalysisView) return record.displayTitle;
  if (record is JobFitReportView) {
    return "${record.overallScore} 分 · ${record.recommendation}";
  }
  if (record is ResumeVersionView) {
    return record.title.isEmpty ? record.resumeVersionId : record.title;
  }
  return "";
}

String _recordTypeLabel(Object record) {
  if (record is ResumeProfileView) return "简历画像";
  if (record is CareerProfileView) return "职业画像";
  if (record is JDAnalysisView) return "JD 分析";
  if (record is JobFitReportView) return "匹配报告";
  if (record is ResumeVersionView) return "简历版本";
  return "求职资产";
}

IconData _recordTypeIcon(Object record) {
  if (record is ResumeProfileView) return Icons.badge_outlined;
  if (record is CareerProfileView) return Icons.track_changes_rounded;
  if (record is JDAnalysisView) return Icons.article_outlined;
  if (record is JobFitReportView) return Icons.fact_check_outlined;
  if (record is ResumeVersionView) return Icons.description_outlined;
  return Icons.inventory_2_outlined;
}

_PreviewSpec? _previewSpecForRecord(Object record) {
  final sourceSessionId = _recordMeta(record).sourceSessionId.trim();
  if (sourceSessionId.isEmpty) {
    return null;
  }
  if (record is ResumeProfileView) {
    final artifactId = record.diagnosisArtifactId?.trim() ?? "";
    if (artifactId.isEmpty) return null;
    return _PreviewSpec(
      label: "预览诊断",
      sourceSessionId: sourceSessionId,
      artifactId: artifactId,
    );
  }
  if (record is JDAnalysisView) {
    final artifactId = record.meta.sourceArtifactId?.trim() ?? "";
    if (artifactId.isEmpty) return null;
    return _PreviewSpec(
      label: "预览 JD",
      sourceSessionId: sourceSessionId,
      artifactId: artifactId,
    );
  }
  if (record is JobFitReportView) {
    final artifactId = record.reportArtifactId?.trim() ?? "";
    if (artifactId.isEmpty) return null;
    return _PreviewSpec(
      label: "预览报告",
      sourceSessionId: sourceSessionId,
      artifactId: artifactId,
    );
  }
  if (record is ResumeVersionView) {
    final artifactId = record.artifactId.trim();
    if (artifactId.isEmpty) return null;
    return _PreviewSpec(
      label: "预览简历",
      sourceSessionId: sourceSessionId,
      artifactId: artifactId,
    );
  }
  return null;
}

void _copyText(BuildContext context, String value, String message) {
  Clipboard.setData(ClipboardData(text: value));
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(message), duration: const Duration(seconds: 1)),
  );
}

void _openDownload(BuildContext context, String url) {
  try {
    openDownloadUrl(url);
  } catch (error) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text("下载打开失败: $error"),
        duration: const Duration(seconds: 2),
      ),
    );
  }
}

String _tabLabel(CareerAssetsTab tab) {
  return switch (tab) {
    CareerAssetsTab.all => "全部",
    CareerAssetsTab.resumes => "简历",
    CareerAssetsTab.profiles => "画像",
    CareerAssetsTab.jobs => "JD",
    CareerAssetsTab.fitReports => "匹配",
    CareerAssetsTab.versions => "版本",
  };
}

IconData _tabIcon(CareerAssetsTab tab) {
  return switch (tab) {
    CareerAssetsTab.all => Icons.dashboard_customize_outlined,
    CareerAssetsTab.resumes => Icons.badge_outlined,
    CareerAssetsTab.profiles => Icons.track_changes_rounded,
    CareerAssetsTab.jobs => Icons.article_outlined,
    CareerAssetsTab.fitReports => Icons.fact_check_outlined,
    CareerAssetsTab.versions => Icons.description_outlined,
  };
}

IconData _assetTypeIcon(String label) {
  return switch (label) {
    "简历画像" => Icons.badge_outlined,
    "职业画像" => Icons.track_changes_rounded,
    "JD 分析" => Icons.article_outlined,
    "匹配报告" => Icons.fact_check_outlined,
    "简历版本" => Icons.description_outlined,
    _ => Icons.layers_outlined,
  };
}

int _tabCount(CareerAssetsProvider provider, CareerAssetsTab tab) {
  return switch (tab) {
    CareerAssetsTab.all =>
      _groupResumeProfiles(provider.resumeProfiles).length +
          _groupCareerProfiles(provider.careerProfiles).length +
          _groupJdAnalyses(provider.jdAnalyses).length +
          _groupJobFitReports(provider.jobFitReports).length +
          _groupResumeVersions(provider.resumeVersions).length,
    CareerAssetsTab.resumes =>
      _groupResumeProfiles(provider.resumeProfiles).length,
    CareerAssetsTab.profiles =>
      _groupCareerProfiles(provider.careerProfiles).length,
    CareerAssetsTab.jobs => _groupJdAnalyses(provider.jdAnalyses).length,
    CareerAssetsTab.fitReports =>
      _groupJobFitReports(provider.jobFitReports).length,
    CareerAssetsTab.versions =>
      _groupResumeVersions(provider.resumeVersions).length,
  };
}

String _formatTime(DateTime time) {
  return DateFormat("MM-dd HH:mm").format(time);
}

String _statusLabel(String status) {
  return switch (status) {
    "active" => "可用",
    "archived" => "已归档",
    _ => status,
  };
}

List<String> _dynamicItems(List<dynamic> values) {
  return values
      .map((item) => item.toString().trim())
      .where((item) => item.isNotEmpty)
      .toList();
}

String _joinDynamic(List<dynamic> values) {
  final items = _dynamicItems(values);
  if (items.isEmpty) return "-";
  return items.take(8).join("、");
}
