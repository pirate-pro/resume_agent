import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/career_assets_provider.dart';
import '../../core/providers/chat_provider.dart';
import '../../shared/theme/app_theme.dart';

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
            onRefresh: () => unawaited(provider.refresh()),
            onClose: widget.onClose,
          ),
          CareerAssetsSummaryStrip(provider: provider),
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
  final VoidCallback onRefresh;
  final VoidCallback onClose;

  const CareerAssetsHeader({
    super.key,
    required this.isRefreshing,
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
                "产品记录 · Artifact 预览",
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
}

class CareerAssetsSummaryStrip extends StatelessWidget {
  final CareerAssetsProvider provider;

  const CareerAssetsSummaryStrip({super.key, required this.provider});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(18, 0, 18, 12),
      child: Row(
        children: [
          _SummaryPill(label: "简历", value: provider.resumeProfiles.length),
          _SummaryPill(label: "画像", value: provider.careerProfiles.length),
          _SummaryPill(label: "JD", value: provider.jdAnalyses.length),
          _SummaryPill(label: "匹配", value: provider.jobFitReports.length),
          _SummaryPill(label: "版本", value: provider.resumeVersions.length),
        ],
      ),
    );
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
        padding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
        children: [
          CareerAssetList(provider: provider),
          if (provider.selection != null) ...[
            const SizedBox(height: 14),
            CareerAssetDetailPane(selection: provider.selection!),
          ],
          const SizedBox(height: 14),
          ArtifactPreviewPanel(
            isLoading: provider.isPreviewLoading,
            error: provider.previewError,
            preview: provider.preview,
          ),
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
        provider.resumeProfiles.map(
          (item) => ResumeProfileCard(
            record: item,
            selected: _isSelected(provider.selection, item.resumeProfileId),
            onTap: () => provider.selectRecord(item),
            onPreviewArtifact: _preview(provider, item.meta.sourceSessionId),
          ),
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.profiles) {
      cards.addAll(
        provider.careerProfiles.map(
          (item) => CareerProfileCard(
            record: item,
            selected: _isSelected(provider.selection, item.careerProfileId),
            onTap: () => provider.selectRecord(item),
          ),
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.jobs) {
      cards.addAll(
        provider.jdAnalyses.map(
          (item) => JDAnalysisCard(
            record: item,
            selected: _isSelected(provider.selection, item.jdAnalysisId),
            onTap: () => provider.selectRecord(item),
            onPreviewArtifact: _preview(provider, item.meta.sourceSessionId),
          ),
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.fitReports) {
      cards.addAll(
        provider.jobFitReports.map(
          (item) => JobFitReportCard(
            record: item,
            selected: _isSelected(provider.selection, item.jobFitReportId),
            onTap: () => provider.selectRecord(item),
            onPreviewArtifact: _preview(provider, item.meta.sourceSessionId),
          ),
        ),
      );
    }
    if (tab == CareerAssetsTab.all || tab == CareerAssetsTab.versions) {
      cards.addAll(
        provider.resumeVersions.map(
          (item) => ResumeVersionCard(
            record: item,
            selected: _isSelected(provider.selection, item.resumeVersionId),
            onTap: () => provider.selectRecord(item),
            onPreviewArtifact: _preview(provider, item.meta.sourceSessionId),
          ),
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

  ValueChanged<String> _preview(
    CareerAssetsProvider provider,
    String sourceSessionId,
  ) {
    return (artifactId) => provider.previewArtifact(
          sourceSessionId: sourceSessionId,
          artifactId: artifactId,
        );
  }
}

class ResumeProfileCard extends StatelessWidget {
  final ResumeProfileView record;
  final bool selected;
  final VoidCallback onTap;
  final ValueChanged<String> onPreviewArtifact;

  const ResumeProfileCard({
    super.key,
    required this.record,
    required this.selected,
    required this.onTap,
    required this.onPreviewArtifact,
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
      onTap: onTap,
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
          if (record.diagnosisArtifactId != null) ...[
            const SizedBox(height: 10),
            _ArtifactButton(
              label: "预览诊断",
              artifactId: record.diagnosisArtifactId!,
              onTap: onPreviewArtifact,
            ),
          ],
        ],
      ),
    );
  }
}

class CareerProfileCard extends StatelessWidget {
  final CareerProfileView record;
  final bool selected;
  final VoidCallback onTap;

  const CareerProfileCard({
    super.key,
    required this.record,
    required this.selected,
    required this.onTap,
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
      onTap: onTap,
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
  final VoidCallback onTap;
  final ValueChanged<String> onPreviewArtifact;

  const JDAnalysisCard({
    super.key,
    required this.record,
    required this.selected,
    required this.onTap,
    required this.onPreviewArtifact,
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
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ChipWrap(
            values: record.requiredSkills.take(5).toList(),
            emptyText: "暂无必备技能",
          ),
          if (record.meta.sourceArtifactId != null) ...[
            const SizedBox(height: 10),
            _ArtifactButton(
              label: "预览 JD",
              artifactId: record.meta.sourceArtifactId!,
              onTap: onPreviewArtifact,
            ),
          ],
        ],
      ),
    );
  }
}

class JobFitReportCard extends StatelessWidget {
  final JobFitReportView record;
  final bool selected;
  final VoidCallback onTap;
  final ValueChanged<String> onPreviewArtifact;

  const JobFitReportCard({
    super.key,
    required this.record,
    required this.selected,
    required this.onTap,
    required this.onPreviewArtifact,
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
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ChipWrap(
            values: _dynamicItems(record.gaps).take(4).toList(),
            emptyText: "暂无主要差距",
          ),
          if (record.reportArtifactId != null) ...[
            const SizedBox(height: 10),
            _ArtifactButton(
              label: "预览报告",
              artifactId: record.reportArtifactId!,
              onTap: onPreviewArtifact,
            ),
          ],
        ],
      ),
    );
  }
}

class ResumeVersionCard extends StatelessWidget {
  final ResumeVersionView record;
  final bool selected;
  final VoidCallback onTap;
  final ValueChanged<String> onPreviewArtifact;

  const ResumeVersionCard({
    super.key,
    required this.record,
    required this.selected,
    required this.onTap,
    required this.onPreviewArtifact,
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
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _ChipWrap(
            values: record.changeSummary.take(4).toList(),
            emptyText: "暂无变更摘要",
          ),
          const SizedBox(height: 10),
          _ArtifactButton(
            label: "预览简历",
            artifactId: record.artifactId,
            onTap: onPreviewArtifact,
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
    return _PanelSection(
      title: "记录详情",
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _DetailLine(label: "记录 ID", value: selection.recordId),
          _DetailLine(label: "来源会话", value: selection.sourceSessionId),
          for (final line in lines) _DetailLine(label: line.$1, value: line.$2),
        ],
      ),
    );
  }

  List<(String, String)> _detailLines(Object record) {
    if (record is ResumeProfileView) {
      return [
        ("姓名", record.displayName),
        ("技能", _joinDynamic(record.skills)),
        ("项目数", record.projectExperience.length.toString()),
        ("诊断 artifact", record.diagnosisArtifactId ?? "-"),
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
        ("JD 分析", record.jdAnalysisId),
        ("简历画像", record.resumeProfileId),
        ("报告 artifact", record.reportArtifactId ?? "-"),
      ];
    }
    if (record is ResumeVersionView) {
      return [
        ("标题", record.title),
        ("基础简历", record.baseResumeProfileId),
        ("目标 JD", record.targetJdAnalysisId ?? "-"),
        ("格式", record.format),
        ("正文 artifact", record.artifactId),
      ];
    }
    return const [];
  }
}

class ArtifactPreviewPanel extends StatelessWidget {
  final bool isLoading;
  final String? error;
  final SessionArtifactContentView? preview;

  const ArtifactPreviewPanel({
    super.key,
    required this.isLoading,
    required this.error,
    required this.preview,
  });

  @override
  Widget build(BuildContext context) {
    if (isLoading) {
      return _PanelSection(
        title: "Artifact 预览",
        child: Row(
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: AppTheme.accent,
              ),
            ),
            const SizedBox(width: 10),
            Text(
              "正在读取正文",
              style: AppTheme.ts(fontSize: 12, color: AppTheme.textSecondary),
            ),
          ],
        ),
      );
    }
    if (error != null) {
      return _PanelSection(
        title: "Artifact 预览",
        child: Text(
          error!,
          style: AppTheme.ts(fontSize: 12, color: AppTheme.danger, height: 1.5),
        ),
      );
    }
    if (preview == null) {
      return _PanelSection(
        title: "Artifact 预览",
        child: Text(
          "点击记录里的预览按钮查看 Markdown 正文",
          style: AppTheme.ts(fontSize: 12, color: AppTheme.textTertiary),
        ),
      );
    }
    return _PanelSection(
      title: "Artifact 预览",
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            preview!.title,
            style: AppTheme.ts(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppTheme.textPrimary,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            "${preview!.returnedChars}/${preview!.totalChars} 字符"
            "${preview!.truncated ? " · 已截断" : ""}",
            style: AppTheme.ts(fontSize: 11, color: AppTheme.textTertiary),
          ),
          const SizedBox(height: 10),
          Container(
            width: double.infinity,
            constraints: const BoxConstraints(maxHeight: 360),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppTheme.bg.withValues(alpha: 0.46),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppTheme.border),
            ),
            child: SingleChildScrollView(
              child: SelectableText(
                preview!.content,
                style: AppTheme.ts(
                  fontSize: 11,
                  height: 1.55,
                  color: AppTheme.textSecondary,
                ),
              ),
            ),
          ),
        ],
      ),
    );
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
  final VoidCallback onTap;
  final Widget child;

  const _CareerAssetCardShell({
    required this.icon,
    required this.label,
    required this.title,
    required this.id,
    required this.meta,
    required this.selected,
    required this.onTap,
    required this.child,
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
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: selected
                ? AppTheme.accent.withValues(alpha: 0.12)
                : AppTheme.surface.withValues(alpha: 0.76),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: selected
                  ? AppTheme.accent.withValues(alpha: 0.34)
                  : AppTheme.border,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 30,
                    height: 30,
                    decoration: BoxDecoration(
                      color: AppTheme.surfaceActive.withValues(alpha: 0.9),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: AppTheme.border),
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
                            Text(
                              label,
                              style: AppTheme.ts(
                                fontSize: 10.5,
                                fontWeight: FontWeight.w700,
                                color: AppTheme.accent,
                              ),
                            ),
                            const SizedBox(width: 8),
                            _StatusDot(status: meta.status),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          title.isEmpty ? id : title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: AppTheme.textPrimary,
                            height: 1.25,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                id,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style:
                    AppTheme.ts(fontSize: 10.5, color: AppTheme.textTertiary),
              ),
              const SizedBox(height: 10),
              child,
              const SizedBox(height: 10),
              Text(
                "更新于 ${_formatTime(meta.updatedAt)}",
                style:
                    AppTheme.ts(fontSize: 10.5, color: AppTheme.textTertiary),
              ),
            ],
          ),
        ),
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

class _SummaryPill extends StatelessWidget {
  final String label;
  final int value;

  const _SummaryPill({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(right: 8),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: AppTheme.ts(fontSize: 11, color: AppTheme.textTertiary),
          ),
          const SizedBox(width: 6),
          Text(
            value.toString(),
            style: AppTheme.ts(
              fontSize: 12,
              fontWeight: FontWeight.w800,
              color: AppTheme.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}

class _TabButton extends StatelessWidget {
  final String label;
  final int count;
  final bool selected;
  final VoidCallback onTap;

  const _TabButton({
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
          child: Text(
            "$label $count",
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: selected ? AppTheme.accent : AppTheme.textSecondary,
            ),
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

class _ArtifactButton extends StatelessWidget {
  final String label;
  final String artifactId;
  final ValueChanged<String> onTap;

  const _ArtifactButton({
    required this.label,
    required this.artifactId,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => onTap(artifactId),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
            decoration: BoxDecoration(
              color: AppTheme.accent.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: AppTheme.accent.withValues(alpha: 0.22),
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.visibility_outlined,
                    size: 14, color: AppTheme.accent),
                const SizedBox(width: 6),
                Text(
                  label,
                  style: AppTheme.ts(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.accent,
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
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: (active ? AppTheme.accent : AppTheme.textTertiary)
            .withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        active ? "active" : status,
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

int _tabCount(CareerAssetsProvider provider, CareerAssetsTab tab) {
  return switch (tab) {
    CareerAssetsTab.all => provider.totalCount,
    CareerAssetsTab.resumes => provider.resumeProfiles.length,
    CareerAssetsTab.profiles => provider.careerProfiles.length,
    CareerAssetsTab.jobs => provider.jdAnalyses.length,
    CareerAssetsTab.fitReports => provider.jobFitReports.length,
    CareerAssetsTab.versions => provider.resumeVersions.length,
  };
}

String _formatTime(DateTime time) {
  return DateFormat("MM-dd HH:mm").format(time);
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
