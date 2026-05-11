part of '../career_report.dart';

class CareerReportView extends StatelessWidget {
  final String content;
  final bool readerMode;
  final _CareerReportPresentation? _initialReport;

  const CareerReportView({
    super.key,
    required this.content,
    this.readerMode = false,
  }) : _initialReport = null;

  static bool canRender(String content) {
    return _CareerReportPresentation.tryParse(content) != null;
  }

  @override
  Widget build(BuildContext context) {
    final report =
        _initialReport ?? _CareerReportPresentation.tryParse(content);
    if (report == null) {
      return AssistantMarkdownBody(content: content);
    }
    final reportTitle = _careerReportDisplayTitle(report);
    final score = _careerReportScore(report.rawContent);
    final verdict = _careerReportVerdict(report, score);
    final highlights = _careerReportHighlights(report);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _CareerReportHeader(
          title: reportTitle,
          sectionCount: report.sections.length,
          score: score,
          verdict: verdict,
          highlights: highlights,
        ),
        const SizedBox(height: 12),
        if (report.sections.length >= 3) ...[
          readerMode
              ? _CareerReportReaderOutline(sections: report.sections)
              : _CareerReportOutline(sections: report.sections),
          SizedBox(height: readerMode ? 10 : 12),
        ],
        if (report.lead.isNotEmpty) ...[
          _CareerReportLeadBlock(content: report.lead),
          const SizedBox(height: 14),
        ],
        for (var index = 0; index < report.sections.length; index++) ...[
          _CareerReportSectionBlock(
            section: report.sections[index],
            index: index + 1,
          ),
          if (index < report.sections.length - 1) const SizedBox(height: 12),
        ],
      ],
    );
  }
}

class _CareerReportOutline extends StatelessWidget {
  final List<_CareerReportSection> sections;

  const _CareerReportOutline({required this.sections});

  @override
  Widget build(BuildContext context) {
    final visibleSections = sections.take(6).toList();
    final remainingCount = sections.length - visibleSections.length;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 13, 14, 14),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.68 : 0.9),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.borderLight.withValues(alpha: 0.76)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.07 : 0.025),
            blurRadius: 16,
            offset: const Offset(0, 7),
          ),
        ],
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
                  color: AppTheme.accent.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.17),
                  ),
                ),
                child: Icon(
                  Icons.view_agenda_outlined,
                  size: 16,
                  color: AppTheme.accent,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "报告导览",
                      style: AppTheme.ts(
                        fontSize: 14,
                        height: 1.2,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      "${sections.length} 个重点模块 · 先扫结构再看细节",
                      style: AppTheme.ts(
                        fontSize: 11,
                        height: 1.2,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
              if (remainingCount > 0)
                _CareerMiniBadge(
                  label: "+$remainingCount",
                  color: AppTheme.textSecondary,
                ),
            ],
          ),
          const SizedBox(height: 11),
          LayoutBuilder(
            builder: (context, constraints) {
              final useGrid =
                  constraints.maxWidth >= 620 && visibleSections.length > 1;
              final tileWidth = useGrid
                  ? (constraints.maxWidth - 8) / 2
                  : constraints.maxWidth;
              return Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (var index = 0; index < visibleSections.length; index++)
                    SizedBox(
                      width: tileWidth,
                      child: _CareerReportOutlineTile(
                        section: visibleSections[index],
                        index: index + 1,
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
}

class _CareerReportReaderOutline extends StatelessWidget {
  final List<_CareerReportSection> sections;

  const _CareerReportReaderOutline({required this.sections});

  @override
  Widget build(BuildContext context) {
    final visibleSections = sections.take(8).toList();
    final remainingCount = sections.length - visibleSections.length;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 11),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.7 : 0.88),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: AppTheme.borderLight.withValues(alpha: 0.7)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 26,
                height: 26,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(9),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.16),
                  ),
                ),
                child: Icon(
                  Icons.format_list_bulleted_rounded,
                  size: 15,
                  color: AppTheme.accent,
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  "阅读目录",
                  style: AppTheme.ts(
                    fontSize: 13,
                    height: 1.2,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ),
              Text(
                "${sections.length} 个章节",
                style: AppTheme.ts(
                  fontSize: 11,
                  height: 1.2,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (var index = 0; index < visibleSections.length; index++)
                  Padding(
                    padding: EdgeInsets.only(
                      right: index == visibleSections.length - 1 ? 0 : 8,
                    ),
                    child: _CareerReaderOutlineChip(
                      section: visibleSections[index],
                      index: index + 1,
                    ),
                  ),
                if (remainingCount > 0) ...[
                  const SizedBox(width: 8),
                  _CareerMiniBadge(
                    label: "+$remainingCount",
                    color: AppTheme.textSecondary,
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerReaderOutlineChip extends StatelessWidget {
  final _CareerReportSection section;
  final int index;

  const _CareerReaderOutlineChip({
    required this.section,
    required this.index,
  });

  @override
  Widget build(BuildContext context) {
    final visual = _careerSectionVisual(section.type);
    return Container(
      constraints: const BoxConstraints(maxWidth: 170),
      padding: const EdgeInsets.fromLTRB(9, 7, 10, 7),
      decoration: BoxDecoration(
        color: visual.color.withValues(alpha: AppTheme.isDark ? 0.1 : 0.065),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: visual.color.withValues(alpha: 0.17)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            index.toString().padLeft(2, "0"),
            style: AppTheme.ts(
              fontSize: 10.5,
              height: 1,
              fontWeight: FontWeight.w900,
              color: visual.color,
            ),
          ),
          const SizedBox(width: 7),
          Icon(visual.icon, size: 13, color: visual.color),
          const SizedBox(width: 5),
          Flexible(
            child: Text(
              section.title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 11.2,
                height: 1.1,
                fontWeight: FontWeight.w800,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerReportOutlineTile extends StatelessWidget {
  final _CareerReportSection section;
  final int index;

  const _CareerReportOutlineTile({
    required this.section,
    required this.index,
  });

  @override
  Widget build(BuildContext context) {
    final visual = _careerSectionVisual(section.type);
    final preview = _careerSectionPreviewText(section);
    return Container(
      constraints: const BoxConstraints(minHeight: 76),
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            visual.color.withValues(alpha: AppTheme.isDark ? 0.09 : 0.055),
            AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.26 : 0.42),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: visual.color.withValues(alpha: 0.16)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 34,
            height: 34,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: visual.color.withValues(alpha: 0.11),
              borderRadius: BorderRadius.circular(11),
              border: Border.all(color: visual.color.withValues(alpha: 0.18)),
            ),
            child: Text(
              index.toString().padLeft(2, "0"),
              style: AppTheme.ts(
                fontSize: 11,
                height: 1,
                fontWeight: FontWeight.w900,
                color: visual.color,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Icon(visual.icon, size: 13, color: visual.color),
                    const SizedBox(width: 5),
                    Expanded(
                      child: Text(
                        visual.role,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 10.5,
                          height: 1.15,
                          fontWeight: FontWeight.w800,
                          color: visual.color,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  section.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    height: 1.2,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
                if (preview.isNotEmpty) ...[
                  const SizedBox(height: 5),
                  Text(
                    preview,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 11.2,
                      height: 1.35,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerReportSectionBlock extends StatelessWidget {
  final _CareerReportSection section;
  final int index;

  const _CareerReportSectionBlock({
    required this.section,
    required this.index,
  });

  @override
  Widget build(BuildContext context) {
    final visual = _careerSectionVisual(section.type);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 13, 14, 14),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.72 : 0.9),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.borderLight.withValues(alpha: 0.74)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.08 : 0.03),
            blurRadius: 16,
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
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: visual.color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: visual.color.withValues(alpha: 0.16),
                  ),
                ),
                child: Icon(
                  visual.icon,
                  size: 16,
                  color: visual.color,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      section.title,
                      style: AppTheme.ts(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                        height: 1.25,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      "模块 ${index.toString().padLeft(2, "0")} · ${visual.role}",
                      style: AppTheme.ts(
                        fontSize: 11,
                        color: AppTheme.textTertiary,
                        height: 1.25,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (section.body.isNotEmpty) ...[
            const SizedBox(height: 12),
            _CareerReportSectionBody(section: section, visual: visual),
          ],
        ],
      ),
    );
  }
}

class _CareerReportSectionBody extends StatelessWidget {
  final _CareerReportSection section;
  final _CareerSectionVisual visual;

  const _CareerReportSectionBody({
    required this.section,
    required this.visual,
  });

  @override
  Widget build(BuildContext context) {
    final body = section.body.trim();
    return switch (section.type) {
      _CareerReportSectionType.score => _CareerScoreBody(body: body),
      _CareerReportSectionType.conclusion ||
      _CareerReportSectionType.summary =>
        _CareerSummarySection(type: section.type, body: body),
      _CareerReportSectionType.risk => _CareerRiskListSection(body: body),
      _CareerReportSectionType.insight => _CareerInsightGridSection(
          body: body,
          color: visual.color,
          icon: visual.icon,
        ),
      _CareerReportSectionType.action => _CareerActionListSection(
          body: body,
          color: visual.color,
          icon: visual.icon,
        ),
      _CareerReportSectionType.markdown => AssistantMarkdownBody(content: body),
    };
  }
}

class _CareerScoreBody extends StatelessWidget {
  final String body;

  const _CareerScoreBody({required this.body});

  @override
  Widget build(BuildContext context) {
    final scoreRows = _careerScoreRows(body);
    if (scoreRows.isEmpty) {
      return AssistantMarkdownBody(content: body);
    }
    return _CareerScoreBreakdownSection(rows: scoreRows);
  }
}

class _CareerReportHeader extends StatelessWidget {
  final String title;
  final int sectionCount;
  final _CareerReportScore? score;
  final _CareerReportVerdict verdict;
  final List<_CareerReportHighlight> highlights;

  const _CareerReportHeader({
    required this.title,
    required this.sectionCount,
    required this.score,
    required this.verdict,
    required this.highlights,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 15, 16, 15),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            verdict.color.withValues(alpha: AppTheme.isDark ? 0.18 : 0.105),
            const Color(0xFF2563EB)
                .withValues(alpha: AppTheme.isDark ? 0.13 : 0.07),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: verdict.color.withValues(alpha: 0.22)),
        boxShadow: [
          BoxShadow(
            color:
                verdict.color.withValues(alpha: AppTheme.isDark ? 0.09 : 0.055),
            blurRadius: 18,
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
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: AppTheme.surface.withValues(alpha: 0.72),
                  borderRadius: BorderRadius.circular(13),
                  border: Border.all(
                    color: verdict.color.withValues(alpha: 0.24),
                  ),
                ),
                child: Icon(
                  verdict.icon,
                  size: 19,
                  color: verdict.color,
                ),
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
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textSecondary,
                        height: 1.18,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      "$sectionCount 个分析模块 · 先看判断，再看证据",
                      style: AppTheme.ts(
                        fontSize: 11.5,
                        color: AppTheme.textTertiary,
                        height: 1.35,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 13),
          _CareerVerdictPanel(
            verdict: verdict,
            score: score,
          ),
          if (highlights.isNotEmpty) ...[
            const SizedBox(height: 13),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final item in highlights.take(3))
                  _CareerHeroHighlightChip(highlight: item),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _CareerVerdictPanel extends StatelessWidget {
  final _CareerReportVerdict verdict;
  final _CareerReportScore? score;

  const _CareerVerdictPanel({
    required this.verdict,
    required this.score,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(13, 12, 13, 13),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.56 : 0.7),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: verdict.color.withValues(alpha: 0.17)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 560;
          final verdictText = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(verdict.icon, size: 14, color: verdict.color),
                  const SizedBox(width: 6),
                  Text(
                    "推荐判断",
                    style: AppTheme.ts(
                      fontSize: 11,
                      height: 1.1,
                      fontWeight: FontWeight.w800,
                      color: verdict.color,
                    ),
                  ),
                  if (compact && score != null) ...[
                    const SizedBox(width: 8),
                    _CareerMiniBadge(
                      label: "${score!.value}/100",
                      color: verdict.color,
                      filled: true,
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 7),
              Text(
                verdict.label,
                style: AppTheme.ts(
                  fontSize: compact ? 20 : 22,
                  height: 1.05,
                  fontWeight: FontWeight.w900,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 8),
              _CompactMarkdownBody(
                content: verdict.summary,
                style: AppTheme.ts(
                  fontSize: 12.6,
                  height: 1.55,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textSecondary,
                ),
              ),
            ],
          );
          if (compact || score == null) {
            return verdictText;
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(child: verdictText),
              const SizedBox(width: 16),
              Container(
                width: 92,
                padding: const EdgeInsets.symmetric(vertical: 10),
                decoration: BoxDecoration(
                  color: verdict.color.withValues(alpha: 0.07),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: verdict.color.withValues(alpha: 0.14),
                  ),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _CareerScoreDial(score: score!),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _CareerScoreDial extends StatelessWidget {
  final _CareerReportScore score;

  const _CareerScoreDial({required this.score});

  @override
  Widget build(BuildContext context) {
    final color = _scoreColor(score.value);
    return SizedBox(
      width: 62,
      height: 62,
      child: Stack(
        alignment: Alignment.center,
        children: [
          SizedBox(
            width: 58,
            height: 58,
            child: CircularProgressIndicator(
              value: score.value.clamp(0, 100) / 100,
              strokeWidth: 5,
              backgroundColor: AppTheme.surface.withValues(alpha: 0.72),
              color: color,
              strokeCap: StrokeCap.round,
            ),
          ),
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                "${score.value}",
                style: AppTheme.ts(
                  fontSize: 16,
                  height: 1,
                  fontWeight: FontWeight.w900,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 3),
              Text(
                score.label,
                style: AppTheme.ts(
                  fontSize: 9,
                  height: 1,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CareerHeroHighlightChip extends StatelessWidget {
  final _CareerReportHighlight highlight;

  const _CareerHeroHighlightChip({required this.highlight});

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 220),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: highlight.color.withValues(alpha: 0.18)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(highlight.icon, size: 13, color: highlight.color),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              highlight.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 11,
                height: 1.15,
                fontWeight: FontWeight.w700,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerReportLeadBlock extends StatelessWidget {
  final String content;

  const _CareerReportLeadBlock({required this.content});

  @override
  Widget build(BuildContext context) {
    final normalized = _careerLeadContent(content);
    if (normalized.isEmpty) {
      return const SizedBox.shrink();
    }
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: AppTheme.accent.withValues(alpha: 0.18),
        ),
      ),
      child: _CompactMarkdownBody(
        content: normalized,
        style: AppTheme.ts(
          fontSize: 13,
          height: 1.55,
          fontWeight: FontWeight.w600,
          color: AppTheme.textPrimary,
        ),
      ),
    );
  }
}

class _CareerSummarySection extends StatelessWidget {
  final _CareerReportSectionType type;
  final String body;

  const _CareerSummarySection({
    required this.type,
    required this.body,
  });

  @override
  Widget build(BuildContext context) {
    final tableExtraction = _extractCareerMarkdownTables(body);
    final displayBody = tableExtraction.body;
    final fields = _careerSummaryFields(displayBody);
    final conclusion = _careerConclusionText(displayBody);
    final tables = tableExtraction.tables;
    if (type == _CareerReportSectionType.conclusion && conclusion != null) {
      final remainingFields =
          fields.where((field) => !_isConclusionField(field)).toList();
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _CareerConclusionCard(content: conclusion),
          if (remainingFields.isNotEmpty) ...[
            const SizedBox(height: 10),
            _CareerSummaryFieldWrap(fields: remainingFields),
          ],
          if (tables.isNotEmpty) ...[
            const SizedBox(height: 10),
            _CareerMarkdownTableList(
              tables: tables,
              color: AppTheme.accent,
            ),
          ],
        ],
      );
    }
    if (fields.isEmpty && tables.isEmpty) {
      return AssistantMarkdownBody(content: body);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (fields.isNotEmpty) _CareerSummaryFieldWrap(fields: fields),
        if (fields.isNotEmpty && tables.isNotEmpty) const SizedBox(height: 10),
        if (tables.isNotEmpty)
          _CareerMarkdownTableList(
            tables: tables,
            color: AppTheme.accent,
          ),
      ],
    );
  }
}

class _CareerConclusionCard extends StatelessWidget {
  final String content;

  const _CareerConclusionCard({required this.content});

  @override
  Widget build(BuildContext context) {
    final lines = _careerConclusionDisplayLines(content);
    final primary = lines.isEmpty ? content.trim() : lines.first;
    final details = lines.skip(1).join("\n").trim();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            AppTheme.accent.withValues(alpha: AppTheme.isDark ? 0.16 : 0.09),
            const Color(0xFF2563EB)
                .withValues(alpha: AppTheme.isDark ? 0.08 : 0.045),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.2)),
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
                  color: AppTheme.surface.withValues(alpha: 0.72),
                  borderRadius: BorderRadius.circular(11),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.24),
                  ),
                ),
                child: Icon(
                  Icons.check_circle_outline_rounded,
                  size: 17,
                  color: AppTheme.accent,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "投递判断",
                      style: AppTheme.ts(
                        fontSize: 11,
                        height: 1.2,
                        fontWeight: FontWeight.w900,
                        color: AppTheme.accent,
                      ),
                    ),
                    const SizedBox(height: 7),
                    _CompactMarkdownBody(
                      content: primary,
                      style: AppTheme.ts(
                        fontSize: 14.2,
                        height: 1.55,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (details.isNotEmpty) ...[
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
              decoration: BoxDecoration(
                color: AppTheme.surface.withValues(alpha: 0.56),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: AppTheme.accent.withValues(alpha: 0.11),
                ),
              ),
              child: _CompactMarkdownBody(
                content: details,
                style: AppTheme.ts(
                  fontSize: 12.3,
                  height: 1.55,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textSecondary,
                ),
              ),
            ),
          ],
          const SizedBox(height: 11),
          Row(
            children: [
              Icon(
                Icons.arrow_forward_rounded,
                size: 13,
                color: AppTheme.accent,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  "继续向下查看匹配证据、风险和行动建议",
                  style: AppTheme.ts(
                    fontSize: 11.2,
                    height: 1.25,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textTertiary,
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

class _CareerSummaryFieldWrap extends StatelessWidget {
  final List<_CareerSummaryField> fields;

  const _CareerSummaryFieldWrap({required this.fields});

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final field in fields)
          Container(
            constraints: const BoxConstraints(minWidth: 180, maxWidth: 310),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            decoration: BoxDecoration(
              color: AppTheme.bg.withValues(alpha: 0.34),
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: AppTheme.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  field.label,
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textTertiary,
                  ),
                ),
                const SizedBox(height: 4),
                _CompactMarkdownBody(
                  content: field.value,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    height: 1.4,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _CareerScoreBreakdownSection extends StatelessWidget {
  final List<_CareerScoreRow> rows;

  const _CareerScoreBreakdownSection({
    required this.rows,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var index = 0; index < rows.length; index++) ...[
          _CareerScoreBreakdownRow(row: rows[index]),
          if (index < rows.length - 1) const SizedBox(height: 9),
        ],
      ],
    );
  }
}

class _CareerScoreBreakdownRow extends StatelessWidget {
  final _CareerScoreRow row;

  const _CareerScoreBreakdownRow({
    required this.row,
  });

  @override
  Widget build(BuildContext context) {
    final value = row.score.clamp(0, 100).toInt();
    final rowColor = _scoreColor(value);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.28 : 0.38),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.86)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(
                  color: rowColor.withValues(alpha: 0.11),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  _careerScoreIcon(row.label),
                  size: 13,
                  color: rowColor,
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  row.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    height: 1.25,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Text(
                "$value",
                style: AppTheme.ts(
                  fontSize: 13,
                  height: 1,
                  fontWeight: FontWeight.w900,
                  color: rowColor,
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              minHeight: 7,
              value: value / 100,
              backgroundColor: AppTheme.surfaceActive.withValues(alpha: 0.7),
              color: rowColor,
            ),
          ),
          if (row.note.isNotEmpty) ...[
            const SizedBox(height: 8),
            _CompactMarkdownBody(
              content: row.note,
              style: AppTheme.ts(
                fontSize: 11.5,
                height: 1.45,
                color: AppTheme.textSecondary,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _CareerRiskListSection extends StatelessWidget {
  final String body;

  const _CareerRiskListSection({required this.body});

  @override
  Widget build(BuildContext context) {
    final risks = _careerRiskItems(body);
    if (risks.isEmpty) {
      return AssistantMarkdownBody(content: body);
    }
    return Column(
      children: [
        for (var index = 0; index < risks.length; index++) ...[
          _CareerRiskCard(risk: risks[index]),
          if (index < risks.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _CareerRiskCard extends StatelessWidget {
  final _CareerRiskItem risk;

  const _CareerRiskCard({required this.risk});

  @override
  Widget build(BuildContext context) {
    final level = _careerRiskLevel(risk.level);
    final visual = _careerItemVisual(
      "${risk.title} ${risk.detail}",
      fallbackColor: level.color,
      fallbackIcon: level.icon,
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
      decoration: BoxDecoration(
        color: level.color.withValues(alpha: AppTheme.isDark ? 0.075 : 0.045),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: level.color.withValues(alpha: 0.22)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 5,
            height: 76,
            decoration: BoxDecoration(
              color: level.color.withValues(alpha: 0.72),
              borderRadius: BorderRadius.circular(999),
            ),
          ),
          const SizedBox(width: 10),
          Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              color: level.color.withValues(alpha: 0.13),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: level.color.withValues(alpha: 0.18)),
            ),
            child: Icon(visual.icon, size: 15, color: level.color),
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
                        risk.title.isEmpty ? "待补风险" : risk.title,
                        style: AppTheme.ts(
                          fontSize: 12.8,
                          height: 1.3,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    _CareerMiniBadge(
                      label: level.label,
                      color: level.color,
                      filled: true,
                    ),
                  ],
                ),
                if (visual.label.isNotEmpty) ...[
                  const SizedBox(height: 7),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      _CareerMiniBadge(
                          label: visual.label, color: visual.color),
                      _CareerMiniBadge(label: "需要补强", color: level.color),
                    ],
                  ),
                ],
                if (risk.detail.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  _CompactMarkdownBody(
                    content: risk.detail,
                    style: AppTheme.ts(
                      fontSize: 12,
                      height: 1.55,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerInsightGridSection extends StatelessWidget {
  final String body;
  final Color color;
  final IconData icon;

  const _CareerInsightGridSection({
    required this.body,
    required this.color,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final tableExtraction = _extractCareerMarkdownTables(body);
    final items = _careerSectionItems(tableExtraction.body);
    final tables = tableExtraction.tables;
    if (items.isEmpty && tables.isEmpty) {
      return AssistantMarkdownBody(content: body);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (items.isNotEmpty)
          _CareerInsightItemsLayout(
            items: items,
            color: color,
            icon: icon,
          ),
        if (items.isNotEmpty && tables.isNotEmpty) const SizedBox(height: 10),
        if (tables.isNotEmpty)
          _CareerMarkdownTableList(
            tables: tables,
            color: color,
          ),
      ],
    );
  }
}

class _CareerInsightItemsLayout extends StatelessWidget {
  final List<_CareerSectionItem> items;
  final Color color;
  final IconData icon;

  const _CareerInsightItemsLayout({
    required this.items,
    required this.color,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final useGrid = constraints.maxWidth >= 760 &&
            items.length > 1 &&
            items.length <= 6;
        if (!useGrid) {
          return Column(
            children: [
              for (var index = 0; index < items.length; index++) ...[
                _CareerReportItemCard(
                  item: items[index],
                  color: color,
                  icon: icon,
                  index: index + 1,
                  dense: false,
                ),
                if (index < items.length - 1) const SizedBox(height: 8),
              ],
            ],
          );
        }
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (var index = 0; index < items.length; index++)
              SizedBox(
                width: (constraints.maxWidth - 8) / 2,
                child: _CareerReportItemCard(
                  item: items[index],
                  color: color,
                  icon: icon,
                  index: index + 1,
                  dense: true,
                ),
              ),
          ],
        );
      },
    );
  }
}

class _CareerMarkdownTableList extends StatelessWidget {
  final List<_CareerMarkdownTableBlock> tables;
  final Color color;

  const _CareerMarkdownTableList({
    required this.tables,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var index = 0; index < tables.length; index++) ...[
          _CareerMarkdownTableCard(
            table: tables[index],
            color: color,
          ),
          if (index < tables.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _CareerMarkdownTableCard extends StatelessWidget {
  final _CareerMarkdownTableBlock table;
  final Color color;

  const _CareerMarkdownTableCard({
    required this.table,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    final title = _careerReadableTableTitle(table);
    final parsedTable = _parseCareerMarkdownTable(table.markdown);
    final subtitle = parsedTable == null
        ? "可阅读信息"
        : "${parsedTable.rows.length} 条信息 · 已整理为阅读卡片";
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            color.withValues(alpha: AppTheme.isDark ? 0.08 : 0.045),
            AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.62 : 0.88),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.14)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.08 : 0.025),
            blurRadius: 14,
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
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: color.withValues(alpha: 0.15)),
                ),
                child: Icon(_careerTableIcon(title), size: 15, color: color),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 13.2,
                        height: 1.25,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.8,
                        height: 1.2,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (parsedTable == null)
            AppMarkdownBody(
              content: table.markdown,
              style: AppTheme.ts(
                fontSize: 12.5,
                height: 1.5,
                color: AppTheme.textPrimary,
              ),
            )
          else
            _CareerReadableTableBody(
              table: parsedTable,
              color: color,
            ),
        ],
      ),
    );
  }
}

class _CareerReadableTableBody extends StatelessWidget {
  final _CareerMarkdownTableData table;
  final Color color;

  const _CareerReadableTableBody({
    required this.table,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    if (_isCareerKeyValueTable(table)) {
      return _CareerKeyValueTableGrid(table: table, color: color);
    }
    if (_isCareerComparisonTable(table)) {
      return _CareerComparisonTableList(table: table, color: color);
    }
    if (_isCareerEvidenceTable(table)) {
      return _CareerEvidenceTableGrid(table: table, color: color);
    }
    return _CareerGenericTableCards(table: table, color: color);
  }
}

class _CareerKeyValueTableGrid extends StatelessWidget {
  final _CareerMarkdownTableData table;
  final Color color;

  const _CareerKeyValueTableGrid({
    required this.table,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final useGrid = constraints.maxWidth >= 620 && table.rows.length > 2;
        final tileWidth =
            useGrid ? (constraints.maxWidth - 8) / 2 : constraints.maxWidth;
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final row in table.rows)
              SizedBox(
                width: tileWidth,
                child: _CareerInfoTile(
                  label: _careerTableCell(row, 0),
                  value: _careerTableCell(row, 1),
                  color: color,
                ),
              ),
          ],
        );
      },
    );
  }
}

class _CareerInfoTile extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  const _CareerInfoTile({
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    final visual = _careerItemVisual(
      "$label $value",
      fallbackColor: color,
      fallbackIcon: Icons.label_important_outline_rounded,
    );
    return Container(
      constraints: const BoxConstraints(minHeight: 70),
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.58 : 0.8),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: visual.color.withValues(alpha: 0.14)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: visual.color.withValues(alpha: 0.11),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Icon(visual.icon, size: 14, color: visual.color),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _cleanCareerTableText(label),
                  style: AppTheme.ts(
                    fontSize: 10.8,
                    height: 1.2,
                    fontWeight: FontWeight.w800,
                    color: visual.color,
                  ),
                ),
                const SizedBox(height: 6),
                _CompactMarkdownBody(
                  content: _careerTableDisplayText(value),
                  style: AppTheme.ts(
                    fontSize: 12.4,
                    height: 1.48,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.textPrimary,
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

class _CareerComparisonTableList extends StatelessWidget {
  final _CareerMarkdownTableData table;
  final Color color;

  const _CareerComparisonTableList({
    required this.table,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    final requirementIndex = _careerTableColumnIndex(
      table,
      const ["硬性要求", "要求", "岗位要求", "能力要求"],
      fallback: 0,
    );
    final candidateIndex = _careerTableColumnIndex(
      table,
      const ["候选人", "状态", "能力", "证据"],
      fallback: table.headers.length > 1 ? 1 : 0,
    );
    final matchIndex = _careerTableColumnIndex(
      table,
      const ["匹配度", "匹配", "结果"],
      fallback: table.headers.length > 2 ? 2 : candidateIndex,
    );
    return Column(
      children: [
        for (var index = 0; index < table.rows.length; index++) ...[
          _CareerComparisonRowCard(
            requirement: _careerTableCell(table.rows[index], requirementIndex),
            candidate: _careerTableCell(table.rows[index], candidateIndex),
            match: _careerTableCell(table.rows[index], matchIndex),
            color: color,
          ),
          if (index < table.rows.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _CareerComparisonRowCard extends StatelessWidget {
  final String requirement;
  final String candidate;
  final String match;
  final Color color;

  const _CareerComparisonRowCard({
    required this.requirement,
    required this.candidate,
    required this.match,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    final status = _careerTableStatus(match.isEmpty ? candidate : match);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
      decoration: BoxDecoration(
        color: status.color.withValues(alpha: AppTheme.isDark ? 0.07 : 0.04),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: status.color.withValues(alpha: 0.16)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 680;
          if (!wide) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _CareerStatusPill(status: status),
                const SizedBox(height: 9),
                _CareerTableLabeledText(
                  label: "岗位要求",
                  value: requirement,
                  color: color,
                ),
                const SizedBox(height: 9),
                _CareerTableLabeledText(
                  label: "候选人证据",
                  value: candidate,
                  color: status.color,
                ),
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 6,
                child: _CareerTableLabeledText(
                  label: "岗位要求",
                  value: requirement,
                  color: color,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 7,
                child: _CareerTableLabeledText(
                  label: "候选人证据",
                  value: candidate,
                  color: status.color,
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                width: 108,
                child: Align(
                  alignment: Alignment.topRight,
                  child: _CareerStatusPill(status: status),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _CareerEvidenceTableGrid extends StatelessWidget {
  final _CareerMarkdownTableData table;
  final Color color;

  const _CareerEvidenceTableGrid({
    required this.table,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    final itemIndex = _careerTableColumnIndex(
      table,
      const ["匹配项", "要求", "能力", "项目"],
      fallback: 0,
    );
    final evidenceIndex = _careerTableColumnIndex(
      table,
      const ["证据", "来源", "候选人"],
      fallback: table.headers.length > 1 ? 1 : 0,
    );
    final matchIndex = _careerTableColumnIndex(
      table,
      const ["匹配度", "匹配", "结果"],
      fallback: table.headers.length > 2 ? 2 : evidenceIndex,
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        final useGrid = constraints.maxWidth >= 720 && table.rows.length > 1;
        final tileWidth =
            useGrid ? (constraints.maxWidth - 8) / 2 : constraints.maxWidth;
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final row in table.rows)
              SizedBox(
                width: tileWidth,
                child: _CareerEvidenceCard(
                  title: _careerTableCell(row, itemIndex),
                  evidence: _careerTableCell(row, evidenceIndex),
                  match: _careerTableCell(row, matchIndex),
                  color: color,
                ),
              ),
          ],
        );
      },
    );
  }
}

class _CareerEvidenceCard extends StatelessWidget {
  final String title;
  final String evidence;
  final String match;
  final Color color;

  const _CareerEvidenceCard({
    required this.title,
    required this.evidence,
    required this.match,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    final status = _careerTableStatus(match);
    final visual = _careerItemVisual(
      "$title $evidence",
      fallbackColor: color,
      fallbackIcon: Icons.fact_check_outlined,
    );
    return Container(
      constraints: const BoxConstraints(minHeight: 96),
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.58 : 0.8),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: visual.color.withValues(alpha: 0.16)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: visual.color.withValues(alpha: 0.11),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(visual.icon, size: 14, color: visual.color),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: _CompactMarkdownBody(
                  content: _careerTableDisplayText(title),
                  style: AppTheme.ts(
                    fontSize: 12.6,
                    height: 1.35,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              _CareerStatusPill(status: status),
            ],
          ),
          if (evidence.trim().isNotEmpty) ...[
            const SizedBox(height: 9),
            _CareerTableLabeledText(
              label: "证据来源",
              value: evidence,
              color: visual.color,
            ),
          ],
        ],
      ),
    );
  }
}

class _CareerGenericTableCards extends StatelessWidget {
  final _CareerMarkdownTableData table;
  final Color color;

  const _CareerGenericTableCards({
    required this.table,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var rowIndex = 0; rowIndex < table.rows.length; rowIndex++) ...[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
            decoration: BoxDecoration(
              color: AppTheme.surface.withValues(
                alpha: AppTheme.isDark ? 0.58 : 0.8,
              ),
              borderRadius: BorderRadius.circular(13),
              border: Border.all(color: color.withValues(alpha: 0.13)),
            ),
            child: Wrap(
              spacing: 10,
              runSpacing: 9,
              children: [
                for (var index = 0; index < table.headers.length; index++)
                  SizedBox(
                    width: 220,
                    child: _CareerTableLabeledText(
                      label: table.headers[index],
                      value: _careerTableCell(table.rows[rowIndex], index),
                      color: color,
                    ),
                  ),
              ],
            ),
          ),
          if (rowIndex < table.rows.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _CareerTableLabeledText extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  const _CareerTableLabeledText({
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          _cleanCareerTableText(label),
          style: AppTheme.ts(
            fontSize: 10.5,
            height: 1.2,
            fontWeight: FontWeight.w800,
            color: color,
          ),
        ),
        const SizedBox(height: 5),
        _CompactMarkdownBody(
          content: _careerTableDisplayText(value),
          style: AppTheme.ts(
            fontSize: 12.1,
            height: 1.5,
            fontWeight: FontWeight.w600,
            color: AppTheme.textSecondary,
          ),
        ),
      ],
    );
  }
}

class _CareerStatusPill extends StatelessWidget {
  final _CareerTableStatus status;

  const _CareerStatusPill({required this.status});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: status.color.withValues(alpha: AppTheme.isDark ? 0.13 : 0.09),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: status.color.withValues(alpha: 0.18)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(status.icon, size: 12, color: status.color),
          const SizedBox(width: 5),
          Text(
            status.label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 10.5,
              height: 1,
              fontWeight: FontWeight.w800,
              color: status.color,
            ),
          ),
        ],
      ),
    );
  }
}

String _careerReadableTableTitle(_CareerMarkdownTableBlock table) {
  final explicitTitle = _careerReadableExplicitTableTitle(table.title);
  if (explicitTitle.isNotEmpty) {
    return explicitTitle;
  }
  final header = _careerMarkdownTableHeaders(table.markdown)
      .map((item) => item.replaceAll(" ", ""))
      .join(" ");
  if (header.contains("硬性要求") || header.contains("候选人状态")) {
    return "岗位要求对照";
  }
  if (header.contains("匹配项") || header.contains("证据来源")) {
    return "匹配证据";
  }
  if (header.contains("维度") && header.contains("信息")) {
    return "候选人信息";
  }
  if (header.contains("风险")) {
    return "风险清单";
  }
  if (header.contains("得分") || header.contains("评分")) {
    return "评分拆解";
  }
  return "关键信息";
}

String _careerReadableExplicitTableTitle(String title) {
  final normalized = _stripMarkdownInline(title).trim();
  if (normalized.isEmpty) {
    return "";
  }
  final compact = normalized.replaceAll(" ", "");
  if (compact.contains("结构化明细") || compact.contains("结构化表格")) {
    return "";
  }
  if (compact.contains("证据")) {
    return "匹配证据";
  }
  if (compact.contains("风险")) {
    return "风险清单";
  }
  if (compact.contains("评分")) {
    return "评分拆解";
  }
  return normalized;
}

IconData _careerTableIcon(String title) {
  final compact = title.replaceAll(" ", "");
  if (compact.contains("要求") || compact.contains("对照")) {
    return Icons.rule_folder_outlined;
  }
  if (compact.contains("证据") || compact.contains("匹配")) {
    return Icons.fact_check_outlined;
  }
  if (compact.contains("候选人") || compact.contains("信息")) {
    return Icons.badge_outlined;
  }
  if (compact.contains("风险")) {
    return Icons.warning_amber_rounded;
  }
  if (compact.contains("评分")) {
    return Icons.speed_rounded;
  }
  return Icons.view_agenda_outlined;
}

bool _isCareerKeyValueTable(_CareerMarkdownTableData table) {
  if (table.headers.length != 2) {
    return false;
  }
  final header = table.headers.map(_cleanCareerTableText).join(" ");
  return _containsAny(header, ["维度", "信息", "项目", "内容"]);
}

bool _isCareerComparisonTable(_CareerMarkdownTableData table) {
  final header = table.headers.map(_cleanCareerTableText).join(" ");
  return _containsAny(header, ["硬性要求", "岗位要求", "候选人状态"]) &&
      _containsAny(header, ["匹配度", "匹配"]);
}

bool _isCareerEvidenceTable(_CareerMarkdownTableData table) {
  final header = table.headers.map(_cleanCareerTableText).join(" ");
  return _containsAny(header, ["匹配项", "证据来源", "证据"]);
}

int _careerTableColumnIndex(
  _CareerMarkdownTableData table,
  List<String> keywords, {
  required int fallback,
}) {
  for (var index = 0; index < table.headers.length; index++) {
    final header = _cleanCareerTableText(table.headers[index]);
    if (_containsAny(header, keywords)) {
      return index;
    }
  }
  return fallback.clamp(0, table.headers.length - 1).toInt();
}

String _careerTableCell(List<String> row, int index) {
  if (index < 0 || index >= row.length) {
    return "";
  }
  return row[index].trim();
}

String _careerTableDisplayText(String value) {
  final normalized = value.trim();
  if (normalized.isEmpty) {
    return "未提供";
  }
  final clean = _cleanCareerTableText(normalized);
  if (_looksLikeAssetReferenceLine(clean) ||
      RegExp(r"^(artifact|jd|resume_profile|fit|career_profile)_")
          .hasMatch(clean)) {
    return "已关联资料";
  }
  return normalized;
}

_CareerTableStatus _careerTableStatus(String value) {
  final clean = _cleanCareerTableText(value);
  if (_containsAny(clean, ["缺失", "不匹配", "不足", "无直接", "失败"])) {
    return const _CareerTableStatus(
      label: "需补强",
      icon: Icons.close_rounded,
      color: Color(0xFFDC2626),
    );
  }
  if (_containsAny(clean, ["部分", "间接", "谨慎", "待确认", "未明确", "风险"])) {
    return const _CareerTableStatus(
      label: "部分匹配",
      icon: Icons.warning_amber_rounded,
      color: Color(0xFFB45309),
    );
  }
  if (_containsAny(clean, ["完全", "直接", "超出", "匹配", "具备", "覆盖"])) {
    return _CareerTableStatus(
      label: clean.isEmpty ? "匹配" : clean,
      icon: Icons.check_rounded,
      color: AppTheme.accent,
    );
  }
  return _CareerTableStatus(
    label: clean.isEmpty ? "已记录" : clean,
    icon: Icons.circle_outlined,
    color: AppTheme.textTertiary,
  );
}

List<String> _careerMarkdownTableHeaders(String markdown) {
  final firstLine = markdown
      .replaceAll("\r\n", "\n")
      .replaceAll("\r", "\n")
      .split("\n")
      .map((line) => line.trim())
      .firstWhere((line) => line.startsWith("|"), orElse: () => "");
  if (firstLine.isEmpty) {
    return const [];
  }
  return firstLine
      .replaceFirst(RegExp(r"^\|"), "")
      .replaceFirst(RegExp(r"\|$"), "")
      .split(RegExp(r"[|｜]"))
      .map(_stripMarkdownInline)
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();
}

class _CareerActionListSection extends StatelessWidget {
  final String body;
  final Color color;
  final IconData icon;

  const _CareerActionListSection({
    required this.body,
    required this.color,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final tableExtraction = _extractCareerMarkdownTables(body);
    final items = _careerSectionItems(tableExtraction.body);
    final tables = tableExtraction.tables;
    if (items.isEmpty && tables.isEmpty) {
      return AssistantMarkdownBody(content: body);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (items.isNotEmpty)
          for (var index = 0; index < items.length; index++) ...[
            _CareerActionStepCard(
              item: items[index],
              color: color,
              icon: icon,
              index: index + 1,
              isLast: index == items.length - 1,
            ),
            if (index < items.length - 1) const SizedBox(height: 8),
          ],
        if (items.isNotEmpty && tables.isNotEmpty) const SizedBox(height: 10),
        if (tables.isNotEmpty)
          _CareerMarkdownTableList(
            tables: tables,
            color: color,
          ),
      ],
    );
  }
}

class _CareerActionStepCard extends StatelessWidget {
  final _CareerSectionItem item;
  final Color color;
  final IconData icon;
  final int index;
  final bool isLast;

  const _CareerActionStepCard({
    required this.item,
    required this.color,
    required this.icon,
    required this.index,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    final visual = _careerItemVisual(
      "${item.title} ${item.detail}",
      fallbackColor: color,
      fallbackIcon: icon,
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: BoxDecoration(
        color: visual.color.withValues(alpha: AppTheme.isDark ? 0.08 : 0.045),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: visual.color.withValues(alpha: 0.18)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Column(
            children: [
              Container(
                width: 32,
                height: 32,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: visual.color.withValues(alpha: 0.13),
                  borderRadius: BorderRadius.circular(10),
                  border:
                      Border.all(color: visual.color.withValues(alpha: 0.2)),
                ),
                child: Text(
                  index.toString().padLeft(2, "0"),
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    height: 1,
                    fontWeight: FontWeight.w900,
                    color: visual.color,
                  ),
                ),
              ),
              if (!isLast)
                Container(
                  width: 2,
                  height: 34,
                  margin: const EdgeInsets.only(top: 6),
                  decoration: BoxDecoration(
                    color: visual.color.withValues(alpha: 0.2),
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
            ],
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: SelectableText(
                        item.title.isEmpty ? item.detail : item.title,
                        style: AppTheme.ts(
                          fontSize: 13,
                          height: 1.35,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    if (visual.label.isNotEmpty) ...[
                      const SizedBox(width: 8),
                      _CareerMiniBadge(
                          label: visual.label, color: visual.color),
                    ],
                  ],
                ),
                if (item.title.isNotEmpty && item.detail.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  _CompactMarkdownBody(
                    content: item.detail,
                    style: AppTheme.ts(
                      fontSize: 12,
                      height: 1.55,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerReportItemCard extends StatelessWidget {
  final _CareerSectionItem item;
  final Color color;
  final IconData icon;
  final int index;
  final bool dense;

  const _CareerReportItemCard({
    required this.item,
    required this.color,
    required this.icon,
    required this.index,
    required this.dense,
  });

  @override
  Widget build(BuildContext context) {
    final visual = _careerItemVisual(
      "${item.title} ${item.detail}",
      fallbackColor: color,
      fallbackIcon: icon,
    );
    return Container(
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(11, dense ? 10 : 11, 11, dense ? 10 : 11),
      decoration: BoxDecoration(
        color:
            AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.62 : 0.78),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: visual.color.withValues(alpha: 0.16)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: visual.color.withValues(alpha: 0.13),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: visual.color.withValues(alpha: 0.16)),
            ),
            child: Icon(visual.icon, size: 14, color: visual.color),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (visual.label.isNotEmpty) ...[
                  _CareerMiniBadge(label: visual.label, color: visual.color),
                  const SizedBox(height: 6),
                ],
                if (item.title.isNotEmpty) ...[
                  SelectableText(
                    item.title,
                    style: AppTheme.ts(
                      fontSize: 12.5,
                      height: 1.35,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                  if (item.detail.isNotEmpty) const SizedBox(height: 5),
                ],
                if (item.detail.isNotEmpty)
                  _CompactMarkdownBody(
                    content: item.detail,
                    style: AppTheme.ts(
                      fontSize: 12,
                      height: 1.5,
                      color: AppTheme.textSecondary,
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

class _CareerMiniBadge extends StatelessWidget {
  final String label;
  final Color color;
  final bool filled;

  const _CareerMiniBadge({
    required this.label,
    required this.color,
    this.filled = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: filled ? 0.14 : 0.08),
        borderRadius: BorderRadius.circular(999),
        border:
            Border.all(color: color.withValues(alpha: filled ? 0.22 : 0.14)),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 10,
          height: 1.1,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }
}

class _CompactMarkdownBody extends StatelessWidget {
  final String content;
  final TextStyle style;

  const _CompactMarkdownBody({
    required this.content,
    required this.style,
  });

  @override
  Widget build(BuildContext context) {
    return AppMarkdownBody(
      content: content,
      style: style,
      compact: true,
    );
  }
}
