import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';
import 'package:gpt_markdown/gpt_markdown.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/career_assets_provider.dart';
import '../../core/providers/chat_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/utils/download_stub.dart'
    if (dart.library.html) '../../shared/utils/download_web.dart';

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
    final cards = <Widget>[];
    final tab = provider.activeTab;
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.resumes) {
      cards.addAll(
        _groupResumeProfiles(provider.resumeProfiles).map(
          (group) {
            final item = group.current as ResumeProfileView;
            return ResumeProfileCard(
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
            );
          },
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.profiles) {
      cards.addAll(
        _groupCareerProfiles(provider.careerProfiles).map(
          (group) {
            final item = group.current as CareerProfileView;
            return CareerProfileCard(
              record: item,
              selected: _isSelected(provider.selection, item.careerProfileId),
              highlighted: _groupHighlighted(provider, group),
              onDetails: () => _showDetails(context, provider, item),
              historyCount: group.records.length,
              onHistory: group.records.length > 1
                  ? () => _showHistory(context, provider, group)
                  : null,
            );
          },
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.jobs) {
      cards.addAll(
        _groupJdAnalyses(provider.jdAnalyses).map(
          (group) {
            final item = group.current as JDAnalysisView;
            return JDAnalysisCard(
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
            );
          },
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.fitReports) {
      cards.addAll(
        _groupJobFitReports(provider.jobFitReports).map(
          (group) {
            final item = group.current as JobFitReportView;
            return JobFitReportCard(
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
            );
          },
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.versions) {
      cards.addAll(
        _groupResumeVersions(provider.resumeVersions).map(
          (group) {
            final item = group.current as ResumeVersionView;
            return ResumeVersionCard(
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
            );
          },
        ),
      );
    }
    if (cards.isEmpty) {
      return _InlineEmptyState(message: "${_tabLabel(tab)}暂无记录");
    }
    return Column(
      children: [
        for (final card in cards) ...[
          card,
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

typedef ArtifactPreviewCallback = Future<void> Function(String artifactId);

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
    builder: (sheetContext) {
      return _SheetFrame(
        maxWidth: 780,
        heightFactor: 0.86,
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
        return Column(
          children: [
            _SheetHeader(
              icon: Icons.description_outlined,
              title: title,
              subtitle: preview == null
                  ? artifactId
                  : "${preview.returnedChars}/${preview.totalChars} 字符"
                      "${preview.truncated ? " · 已截断" : ""}",
              actions: [
                _PanelIconButton(
                  icon: Icons.copy_rounded,
                  onTap: () =>
                      _copyText(context, artifactId, "artifact ID 已复制"),
                ),
                const SizedBox(width: 6),
                _PanelIconButton(
                  icon: Icons.download_rounded,
                  onTap: () => _openDownload(context, downloadUrl),
                ),
              ],
              onClose: () => Navigator.of(context).pop(),
            ),
            Expanded(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 180),
                child: _previewBody(context, snapshot),
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
    return SingleChildScrollView(
      key: const ValueKey("artifact-preview-content"),
      padding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
        decoration: BoxDecoration(
          color: AppTheme.surface.withValues(alpha: 0.78),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppTheme.border),
        ),
        child: GptMarkdown(
          preview.content,
          style: AppTheme.ts(
            fontSize: 13,
            height: 1.62,
            color: AppTheme.textPrimary,
          ),
          onLinkTap: (url, title) => _copyText(context, url, "链接已复制"),
        ),
      ),
    );
  }
}

class _SheetHeader extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final List<Widget> actions;
  final VoidCallback onClose;

  const _SheetHeader({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.actions = const [],
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
          ...actions,
          if (actions.isNotEmpty) const SizedBox(width: 6),
          _PanelIconButton(icon: Icons.close_rounded, onTap: onClose),
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
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 24,
            height: 24,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: AppTheme.accent,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            "正在读取文件正文",
            style: AppTheme.ts(fontSize: 12, color: AppTheme.textSecondary),
          ),
        ],
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
      currentLabel: "当前诊断",
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
      currentLabel: "当前画像",
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
      currentLabel: "当前 JD",
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
      currentLabel: "当前报告",
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
      currentLabel: "当前版本",
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
  final String currentLabel;
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
    required this.currentLabel,
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
    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: selected
            ? AppTheme.accent.withValues(alpha: 0.1)
            : highlighted
                ? AppTheme.accent.withValues(alpha: 0.07)
                : AppTheme.surface.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: selected
              ? AppTheme.accent.withValues(alpha: 0.36)
              : highlighted
                  ? AppTheme.accent.withValues(alpha: 0.26)
                  : AppTheme.border,
        ),
        boxShadow: highlighted
            ? [
                BoxShadow(
                  color: AppTheme.accent.withValues(alpha: 0.12),
                  blurRadius: 16,
                  offset: const Offset(0, 8),
                ),
              ]
            : const [],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(11),
                  border:
                      Border.all(color: AppTheme.accent.withValues(alpha: 0.2)),
                ),
                child: Icon(icon, size: 16, color: AppTheme.accent),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            label,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 10.5,
                              fontWeight: FontWeight.w800,
                              color: AppTheme.accent,
                            ),
                          ),
                        ),
                        const SizedBox(width: 7),
                        _StatusDot(status: meta.status),
                        const SizedBox(width: 6),
                        _CurrentUsageBadge(label: currentLabel),
                        if (highlighted) ...[
                          const SizedBox(width: 6),
                          const _NewRecordBadge(),
                        ],
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      title.isEmpty ? id : title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                        height: 1.25,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        _PreviewStatusPill(state: previewState, compact: true),
                        Text(
                          "更新于 ${_formatTime(meta.updatedAt)}",
                          style: AppTheme.ts(
                            fontSize: 10.5,
                            color: AppTheme.textTertiary,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          child,
          const SizedBox(height: 11),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _AssetActionButton(
                label: "详情",
                icon: Icons.tune_rounded,
                onTap: onDetails,
              ),
              if (canPreview)
                _AssetActionButton(
                  label: previewLabel ?? "预览",
                  icon: Icons.visibility_outlined,
                  primary: true,
                  onTap: () => onPreviewArtifact!(previewArtifactId!),
                ),
              if (historyCount > 1 && onHistory != null)
                _AssetActionButton(
                  label: "历史 $historyCount",
                  icon: Icons.history_rounded,
                  onTap: onHistory!,
                ),
            ],
          ),
        ],
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

class _CurrentUsageBadge extends StatelessWidget {
  final String label;

  const _CurrentUsageBadge({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: AppTheme.textPrimary.withValues(alpha: 0.055),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.9)),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 9.5,
          fontWeight: FontWeight.w800,
          color: AppTheme.textSecondary,
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
  final bool compact;

  const _PreviewStatusPill({
    required this.state,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 0 : 8,
        vertical: compact ? 0 : 5,
      ),
      decoration: compact
          ? null
          : BoxDecoration(
              color: state.color.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: state.color.withValues(alpha: 0.14)),
            ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(state.icon, size: compact ? 12 : 13, color: state.color),
          const SizedBox(width: 4),
          Text(
            state.label,
            style: AppTheme.ts(
              fontSize: compact ? 10.5 : 11,
              fontWeight: compact ? FontWeight.w600 : FontWeight.w700,
              color: state.color,
            ),
          ),
        ],
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
  final VoidCallback onTap;

  const _PanelIconButton({required this.icon, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
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
