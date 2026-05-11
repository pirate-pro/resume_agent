part of '../career_report.dart';

_CareerReportScore? _careerReportScore(String content) {
  final patterns = [
    RegExp(
      r'(?:总体匹配度|整体匹配度|匹配度|评分|得分)[^0-9]{0,16}([0-9]{1,3})\s*(?:/|／)\s*100',
    ),
    RegExp(r'([0-9]{1,3})\s*(?:/|／)\s*100'),
  ];
  for (final pattern in patterns) {
    final match = pattern.firstMatch(content);
    if (match == null) {
      continue;
    }
    final value = int.tryParse(match.group(1) ?? "");
    if (value == null || value < 0 || value > 100) {
      continue;
    }
    final label = content.contains("匹配") ? "匹配度" : "评分";
    return _CareerReportScore(value: value, label: label);
  }
  return null;
}

_CareerReportVerdict _careerReportVerdict(
  _CareerReportPresentation report,
  _CareerReportScore? score,
) {
  final explicitLabel = _careerExplicitRecommendation(report.rawContent);
  final label = explicitLabel ?? _careerScoreRecommendation(score);
  final color = _careerRecommendationColor(label, score);
  return _CareerReportVerdict(
    label: label,
    summary: _careerReportPrimaryConclusion(report),
    color: color,
    icon: _careerRecommendationIcon(label, score),
  );
}

String? _careerExplicitRecommendation(String content) {
  for (final rawLine
      in content.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n")) {
    final line = _careerDisplayLine(rawLine);
    if (line.isEmpty) {
      continue;
    }
    final field = _splitCareerLabelValue(line, maxLabelChars: 18);
    if (field != null &&
        _containsAny(field.label.replaceAll(" ", ""), ["推荐等级", "推荐结论", "推荐"])) {
      final value = _cleanRecommendationLabel(field.value);
      if (value.isNotEmpty) {
        return value;
      }
    }
    final inlineMatch = RegExp(
      r"(强烈推荐|高度推荐|谨慎推荐|建议推荐|可以投递|可尝试|暂不建议|不建议|不推荐)",
    ).firstMatch(line);
    if (inlineMatch != null) {
      return _cleanRecommendationLabel(inlineMatch.group(1) ?? "");
    }
  }
  return null;
}

String _cleanRecommendationLabel(String value) {
  final cleaned = _stripMarkdownInline(value)
      .replaceAll(RegExp(r"[（(][a-zA-Z_\-\s]+[）)]"), "")
      .replaceAll(RegExp(r"\s+"), " ")
      .trim();
  if (cleaned.contains("强烈推荐")) return "强烈推荐";
  if (cleaned.contains("高度推荐")) return "高度推荐";
  if (cleaned.contains("谨慎推荐")) return "谨慎推荐";
  if (cleaned.contains("建议推荐")) return "建议推荐";
  if (cleaned.contains("可以投递")) return "可以投递";
  if (cleaned.contains("可尝试")) return "可尝试";
  if (cleaned.contains("暂不建议")) return "暂不建议";
  if (cleaned.contains("不建议") || cleaned.contains("不推荐")) return "暂不建议";
  return cleaned.length > 14
      ? _compactCareerPreview(cleaned, maxChars: 14)
      : cleaned;
}

String _careerScoreRecommendation(_CareerReportScore? score) {
  final value = score?.value;
  if (value == null) {
    return "已完成分析";
  }
  if (value >= 86) return "强烈推荐";
  if (value >= 78) return "高度匹配";
  if (value >= 68) return "谨慎推荐";
  if (value >= 58) return "可尝试";
  return "暂不建议";
}

Color _careerRecommendationColor(String label, _CareerReportScore? score) {
  final value = score?.value;
  if (_containsAny(label, ["暂不建议", "不建议", "不推荐"]) ||
      (value != null && value < 58)) {
    return AppTheme.danger;
  }
  if (_containsAny(label, ["谨慎", "可尝试"]) || (value != null && value < 78)) {
    return const Color(0xFFB45309);
  }
  return AppTheme.accent;
}

IconData _careerRecommendationIcon(String label, _CareerReportScore? score) {
  final value = score?.value;
  if (_containsAny(label, ["暂不建议", "不建议", "不推荐"]) ||
      (value != null && value < 58)) {
    return Icons.report_gmailerrorred_outlined;
  }
  if (_containsAny(label, ["谨慎", "可尝试"]) || (value != null && value < 78)) {
    return Icons.tips_and_updates_outlined;
  }
  return Icons.verified_outlined;
}

String _careerReportPrimaryConclusion(_CareerReportPresentation report) {
  for (final section in report.sections) {
    if (section.type != _CareerReportSectionType.conclusion) {
      continue;
    }
    final conclusion = _careerConclusionText(section.body);
    final cleaned = _careerHeroConclusionText(conclusion ?? "");
    if (cleaned.isNotEmpty) {
      return cleaned;
    }
  }
  final leadConclusion = _careerHeroConclusionText(report.lead);
  if (leadConclusion.isNotEmpty) {
    return leadConclusion;
  }
  final insightSection = report.sections.firstWhere(
    (section) => section.type == _CareerReportSectionType.insight,
    orElse: () => const _CareerReportSection(
      title: "",
      body: "",
      type: _CareerReportSectionType.markdown,
    ),
  );
  final insightItems = _careerSectionItems(insightSection.body);
  if (insightItems.isNotEmpty) {
    final item = insightItems.first;
    return _compactCareerPreview(
      item.title.isNotEmpty ? item.title : item.detail,
      maxChars: 86,
    );
  }
  return "报告已整理为可阅读视图，可先看结论，再查看匹配点、风险和建议。";
}

String _careerHeroConclusionText(String content) {
  final lines = content
      .replaceAll("\r\n", "\n")
      .replaceAll("\r", "\n")
      .split("\n")
      .map(_careerDisplayLine)
      .where((line) => line.isNotEmpty)
      .where((line) => !_isHeroMetadataLine(line))
      .map(_cleanCareerMarkdownValue)
      .where((line) => line.isNotEmpty)
      .toList();
  if (lines.isEmpty) {
    return "";
  }
  return _compactCareerPreview(lines.join(" "), maxChars: 108);
}

bool _isHeroMetadataLine(String line) {
  final field = _splitCareerLabelValue(line, maxLabelChars: 18);
  final label = field?.label.replaceAll(" ", "") ?? "";
  return _containsAny(label, [
    "目标岗位",
    "推荐等级",
    "推荐结论",
    "匹配度",
    "综合匹配度",
    "整体匹配度",
    "评分",
    "得分",
  ]);
}

List<_CareerReportHighlight> _careerReportHighlights(
  _CareerReportPresentation report,
) {
  final highlights = <_CareerReportHighlight>[];

  final riskItems = report.sections
      .where((section) => section.type == _CareerReportSectionType.risk)
      .expand((section) => _careerRiskItems(section.body))
      .toList();
  final insightSection = report.sections.firstWhere(
    (section) => section.type == _CareerReportSectionType.insight,
    orElse: () => const _CareerReportSection(
      title: "",
      body: "",
      type: _CareerReportSectionType.markdown,
    ),
  );
  final insightItems = _careerSectionItems(insightSection.body);
  final firstInsight = insightItems.isEmpty ? null : insightItems.first;
  if (firstInsight != null) {
    final visual = _careerItemVisual(
      "${firstInsight.title} ${firstInsight.detail}",
      fallbackColor: AppTheme.accent,
      fallbackIcon: Icons.trending_up_rounded,
    );
    final label = firstInsight.title.isEmpty
        ? _stripMarkdownInline(firstInsight.detail)
        : firstInsight.title;
    if (label.isNotEmpty) {
      highlights.add(
        _CareerReportHighlight(
          label: label,
          icon: visual.icon,
          color: visual.color,
        ),
      );
    }
  }

  if (riskItems.isNotEmpty) {
    final firstRisk = riskItems.first;
    final level = _careerRiskLevel(firstRisk.level);
    highlights.add(
      _CareerReportHighlight(
        label: _compactCareerPreview(
          firstRisk.title.isEmpty ? "识别风险点" : firstRisk.title,
          maxChars: 24,
        ),
        icon: level.icon,
        color: level.color,
      ),
    );
  }

  final actionCount = report.sections
      .where((section) => section.type == _CareerReportSectionType.action)
      .expand((section) => _careerSectionItems(section.body))
      .length;
  if (actionCount > 0) {
    highlights.add(
      _CareerReportHighlight(
        label: "$actionCount 条下一步建议",
        icon: Icons.auto_fix_high_rounded,
        color: const Color(0xFF2563EB),
      ),
    );
  }

  return highlights;
}

String _careerSectionPreviewText(_CareerReportSection section) {
  final tableExtraction = _extractCareerMarkdownTables(section.body);
  final body = tableExtraction.body.trim();
  final tables = tableExtraction.tables;
  if (body.isEmpty) {
    if (tables.isNotEmpty) {
      final tableTitle = tables.first.title.trim();
      return tableTitle.isEmpty ? "关键信息" : tableTitle;
    }
    return _careerSectionVisual(section.type).role;
  }
  switch (section.type) {
    case _CareerReportSectionType.score:
      final rows = _careerScoreRows(body);
      if (rows.isNotEmpty) {
        final row = rows.first;
        return _compactCareerPreview("${row.label} ${row.score}/100");
      }
      break;
    case _CareerReportSectionType.conclusion:
      final conclusion = _careerConclusionText(body);
      if (conclusion != null) {
        return _compactCareerPreview(conclusion);
      }
      break;
    case _CareerReportSectionType.summary:
      final fields = _careerSummaryFields(body);
      if (fields.isNotEmpty) {
        final field = fields.first;
        return _compactCareerPreview("${field.label}: ${field.value}");
      }
      break;
    case _CareerReportSectionType.insight:
    case _CareerReportSectionType.action:
      final items = _careerSectionItems(body);
      if (items.isNotEmpty) {
        final item = items.first;
        final text = item.title.isNotEmpty ? item.title : item.detail;
        return _compactCareerPreview(text);
      }
      break;
    case _CareerReportSectionType.risk:
      final risks = _careerRiskItems(body);
      if (risks.isNotEmpty) {
        final risk = risks.first;
        final level = _careerRiskLevel(risk.level).label;
        return _compactCareerPreview("${risk.title} · $level");
      }
      break;
    case _CareerReportSectionType.markdown:
      break;
  }
  return _compactCareerPreview(_careerDisplayBlock(body));
}

String _compactCareerPreview(String value, {int maxChars = 44}) {
  final cleaned = _stripMarkdownInline(value)
      .replaceAll(RegExp(r"^[-*•]\s+"), "")
      .replaceAll(RegExp(r"[\r\n]+"), " ")
      .replaceAll(RegExp(r"\s+"), " ")
      .trim();
  if (cleaned.length <= maxChars) {
    return cleaned;
  }
  return "${cleaned.substring(0, maxChars).trimRight()}...";
}

List<_CareerScoreRow> _careerScoreRows(String body) {
  final rows = <_CareerScoreRow>[];
  for (final rawLine in body.split("\n")) {
    final line = rawLine.trim();
    if (line.isEmpty || _isMarkdownTableDivider(line) || !line.contains("|")) {
      continue;
    }
    final normalized = line
        .replaceFirst(RegExp(r"^\|"), "")
        .replaceFirst(RegExp(r"\|$"), "")
        .trim();
    final parts = normalized
        .split(RegExp(r"[|｜]"))
        .map((part) => _stripMarkdownInline(part).trim())
        .where((part) => part.isNotEmpty)
        .toList();
    if (parts.length < 2) {
      continue;
    }
    final label = parts.first;
    if (label.contains("维度") || label.contains("指标")) {
      continue;
    }
    int? score;
    var scoreIndex = -1;
    for (var index = 1; index < parts.length; index++) {
      final match =
          RegExp(r"([0-9]{1,3})(?:\s*/\s*100)?").firstMatch(parts[index]);
      final value = int.tryParse(match?.group(1) ?? "");
      if (value != null && value >= 0 && value <= 100) {
        score = value;
        scoreIndex = index;
        break;
      }
    }
    if (score == null || label.isEmpty) {
      continue;
    }
    final noteParts = <String>[];
    for (var index = 1; index < parts.length; index++) {
      if (index == scoreIndex) {
        continue;
      }
      noteParts.add(parts[index]);
    }
    rows.add(
      _CareerScoreRow(
        label: label,
        score: score,
        note: noteParts.join(" · "),
      ),
    );
    if (rows.length >= 8) {
      break;
    }
  }
  return rows;
}

Color _scoreColor(int value) {
  if (value >= 80) return AppTheme.accent;
  if (value >= 60) return const Color(0xFFB45309);
  return AppTheme.danger;
}

IconData _careerScoreIcon(String label) {
  final value = label.toLowerCase();
  if (_containsAny(value, ["技术", "栈", "能力"])) return Icons.terminal_rounded;
  if (_containsAny(value, ["工程", "质量", "测试", "ci"])) {
    return Icons.verified_outlined;
  }
  if (_containsAny(value, ["agent", "架构", "平台", "系统"])) {
    return Icons.account_tree_rounded;
  }
  if (_containsAny(value, ["团队", "协作", "沟通"])) {
    return Icons.groups_2_outlined;
  }
  if (_containsAny(value, ["rag", "模型", "llm", "ai"])) {
    return Icons.psychology_alt_outlined;
  }
  if (_containsAny(value, ["匹配", "岗位", "jd"])) {
    return Icons.work_outline_rounded;
  }
  return Icons.bar_chart_rounded;
}

_CareerReportSectionType _careerReportSectionType({
  required String title,
  required String body,
}) {
  if (title.contains("评分") || _hasCareerScoreTable(body)) {
    return _CareerReportSectionType.score;
  }
  if (title.contains("结论")) {
    return _CareerReportSectionType.conclusion;
  }
  if (title.contains("摘要")) {
    return _CareerReportSectionType.summary;
  }
  if (title.contains("概况") || title.contains("要求")) {
    return _CareerReportSectionType.summary;
  }
  if (title.contains("风险") || title.contains("差距") || title.contains("问题")) {
    return _CareerReportSectionType.risk;
  }
  if (title.contains("优势") ||
      title.contains("匹配点") ||
      title.contains("亮点") ||
      title.contains("证据")) {
    return _CareerReportSectionType.insight;
  }
  if (title.contains("建议") ||
      title.contains("优化") ||
      title.contains("面试") ||
      title.contains("优先级")) {
    return _CareerReportSectionType.action;
  }
  return _CareerReportSectionType.markdown;
}

bool _hasCareerScoreTable(String body) {
  final hasScoreHeader = body
      .replaceAll("\r\n", "\n")
      .replaceAll("\r", "\n")
      .split("\n")
      .any((line) => _isCareerScoreTableHeader(line.trim()));
  return hasScoreHeader && _careerScoreRows(body).isNotEmpty;
}

_CareerMarkdownTableExtraction _extractCareerMarkdownTables(String body) {
  final lines =
      body.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n");
  final output = <String>[];
  final tables = <_CareerMarkdownTableBlock>[];
  var index = 0;

  while (index < lines.length) {
    final tableLine = _normalizedMarkdownTableLine(lines[index]);
    final nextTableLine = index + 1 < lines.length
        ? _normalizedMarkdownTableLine(lines[index + 1])
        : null;
    final startsTable = tableLine != null &&
        nextTableLine != null &&
        _isMarkdownTableDivider(nextTableLine);
    if (!startsTable) {
      output.add(lines[index]);
      index += 1;
      continue;
    }

    final tableLines = <String>[tableLine, nextTableLine];
    index += 2;
    while (index < lines.length) {
      final normalized = _normalizedMarkdownTableLine(lines[index]);
      if (normalized == null) {
        break;
      }
      tableLines.add(normalized);
      index += 1;
    }

    var title = "";
    final titleIndex = _lastMeaningfulLineIndex(output);
    if (titleIndex != null && _looksLikeCareerTableTitle(output[titleIndex])) {
      title = _careerDisplayLine(output[titleIndex]);
      output.removeRange(titleIndex, output.length);
    }
    tables.add(
      _CareerMarkdownTableBlock(
        title: title,
        markdown: tableLines.join("\n").trim(),
      ),
    );
  }

  return _CareerMarkdownTableExtraction(
    body: output.join("\n").trim(),
    tables: tables,
  );
}

_CareerMarkdownTableData? _parseCareerMarkdownTable(String markdown) {
  final lines = markdown
      .replaceAll("\r\n", "\n")
      .replaceAll("\r", "\n")
      .split("\n")
      .map((line) => line.trim())
      .where((line) => line.startsWith("|"))
      .where((line) => !_isMarkdownTableDivider(line))
      .toList();
  if (lines.length < 2) {
    return null;
  }
  final headers = _splitCareerMarkdownTableLine(lines.first);
  if (headers.isEmpty) {
    return null;
  }
  final rows = <List<String>>[];
  for (final line in lines.skip(1)) {
    final cells = _splitCareerMarkdownTableLine(line);
    if (cells.isEmpty) {
      continue;
    }
    final normalized = List<String>.generate(
      headers.length,
      (index) => index < cells.length ? cells[index] : "",
    );
    if (normalized.any((cell) => cell.trim().isNotEmpty)) {
      rows.add(normalized);
    }
  }
  if (rows.isEmpty) {
    return null;
  }
  return _CareerMarkdownTableData(headers: headers, rows: rows);
}

List<String> _splitCareerMarkdownTableLine(String line) {
  return line
      .trim()
      .replaceFirst(RegExp(r"^\|"), "")
      .replaceFirst(RegExp(r"\|$"), "")
      .split(RegExp(r"[|｜]"))
      .map(_cleanCareerMarkdownValue)
      .map((item) => item.trim())
      .toList();
}

String? _normalizedMarkdownTableLine(String rawLine) {
  final trimmed = rawLine.trim();
  if (trimmed.isEmpty) {
    return null;
  }
  final withoutListMarker = trimmed.replaceFirst(
    RegExp(r"^([-*•]|\d+[\.\)、])\s+(?=\|)"),
    "",
  );
  if (!withoutListMarker.startsWith("|")) {
    return null;
  }
  return withoutListMarker;
}

int? _lastMeaningfulLineIndex(List<String> lines) {
  for (var index = lines.length - 1; index >= 0; index -= 1) {
    final line = lines[index].trim();
    if (line.isEmpty || _isMarkdownHorizontalRule(line)) {
      continue;
    }
    return index;
  }
  return null;
}

bool _looksLikeCareerTableTitle(String rawLine) {
  final line = _careerDisplayLine(rawLine);
  if (line.isEmpty) {
    return false;
  }
  return _containsAny(line, [
    "证据",
    "要求",
    "能力",
    "概况",
    "维度",
    "评分",
    "匹配",
  ]);
}

String _careerLeadContent(String content) {
  final lines =
      content.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n");
  final output = <String>[];
  for (final rawLine in lines) {
    final trimmed = rawLine.trim();
    if (trimmed.isEmpty || trimmed == "---") {
      continue;
    }
    final heading = trimmed.replaceFirst(RegExp(r"^#{1,6}\s*"), "").trim();
    final duplicatedReportTitle = trimmed.startsWith("#") &&
        (heading.contains("诊断报告") ||
            heading.contains("匹配报告") ||
            heading.contains("分析报告") ||
            heading.contains("优化报告"));
    if (duplicatedReportTitle) {
      continue;
    }
    output.add(rawLine);
  }
  return output.join("\n").trim();
}

List<_CareerSummaryField> _careerSummaryFields(String body) {
  final fields = <_CareerSummaryField>[];
  for (final rawLine in body.split("\n")) {
    final line = _careerDisplayLine(rawLine);
    if (line.isEmpty) {
      continue;
    }
    final field = _splitCareerLabelValue(line, maxLabelChars: 24);
    if (field == null) {
      continue;
    }
    final summaryField =
        _CareerSummaryField(label: field.label, value: field.value);
    if (_isScoreSummaryField(summaryField)) {
      continue;
    }
    fields.add(summaryField);
    if (fields.length >= 8) {
      break;
    }
  }
  return fields;
}

String? _careerConclusionText(String body) {
  final fields = _careerSummaryFields(body);
  for (final field in fields) {
    if (_isConclusionField(field)) {
      return field.value;
    }
  }
  final fallback = _careerDisplayBlock(body);
  return fallback.isEmpty ? null : fallback;
}

List<String> _careerConclusionDisplayLines(String content) {
  final lines = content
      .replaceAll("\r\n", "\n")
      .replaceAll("\r", "\n")
      .split("\n")
      .map(_careerDisplayLine)
      .where((line) => line.isNotEmpty)
      .where((line) => !_isHeroMetadataLine(line))
      .map(_cleanCareerMarkdownValue)
      .where((line) => line.isNotEmpty)
      .toList();
  if (lines.isNotEmpty) {
    return lines;
  }
  final fallback = _careerDisplayBlock(content);
  return fallback.isEmpty ? const [] : [fallback];
}

bool _isConclusionField(_CareerSummaryField field) {
  final label = _stripMarkdownInline(field.label).replaceAll(" ", "");
  return label.contains("结论") || label.contains("判断");
}

bool _isScoreSummaryField(_CareerSummaryField field) {
  final label = _stripMarkdownInline(field.label).replaceAll(" ", "");
  final looksLikeScoreLabel =
      label.contains("匹配度") || label.contains("评分") || label.contains("得分");
  if (!looksLikeScoreLabel) {
    return false;
  }
  return RegExp(r"[0-9]{1,3}\s*(?:/|／)\s*100").hasMatch(field.value);
}

List<_CareerSectionItem> _careerSectionItems(String body) {
  final groups = <String>[];
  final current = <String>[];
  final rawLines =
      body.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n");
  final primaryItemPattern = RegExp(r"^\d+[\.\)、]\s+");
  final bulletItemPattern = RegExp(r"^[-*•]\s+");
  final hasPrimaryItems =
      rawLines.any((rawLine) => primaryItemPattern.hasMatch(rawLine.trim()));

  void flush() {
    final value = current.join("\n").trim();
    if (value.isNotEmpty) {
      groups.add(value);
    }
    current.clear();
  }

  for (final rawLine in rawLines) {
    final trimmed = rawLine.trim();
    if (trimmed.isEmpty) {
      continue;
    }
    final startsPrimaryItem = primaryItemPattern.hasMatch(trimmed);
    final startsBulletItem = bulletItemPattern.hasMatch(trimmed);
    final startsItem =
        startsPrimaryItem || (!hasPrimaryItems && startsBulletItem);
    final line = _careerDisplayLine(rawLine);
    if (line.isEmpty) {
      continue;
    }
    if (startsItem) {
      flush();
    }
    current.add(line);
  }
  flush();
  if (groups.isEmpty && body.trim().isNotEmpty) {
    groups.add(_careerDisplayBlock(body));
  }
  return groups
      .where((item) => item.isNotEmpty)
      .map(_careerSectionItemFromText)
      .toList();
}

_CareerSectionItem _careerSectionItemFromText(String text) {
  final normalized = text.trim();
  final lines = normalized
      .split("\n")
      .map((line) => line.trim())
      .where((line) => line.isNotEmpty)
      .toList();
  if (lines.length > 1) {
    final title = _stripMarkdownInline(lines.first);
    final detail = lines
        .skip(1)
        .map(_cleanCareerMarkdownValue)
        .where((line) => line.isNotEmpty)
        .map((line) => "- $line")
        .join("\n");
    if (title.isNotEmpty) {
      return _CareerSectionItem(title: title, detail: detail);
    }
  }
  final field = _splitCareerLabelValue(normalized, maxLabelChars: 36);
  if (field != null) {
    return _CareerSectionItem(title: field.label, detail: field.value);
  }
  return _CareerSectionItem(title: "", detail: normalized);
}

String _careerDisplayLine(String value) {
  final normalized = value
      .trim()
      .replaceFirst(RegExp(r"^#{1,6}\s*"), "")
      .replaceFirst(RegExp(r"^[(（]?[一二三四五六七八九十]+[)）、.．]\s*"), "")
      .replaceFirst(RegExp(r"^(\d+[\.\)、]|[-*•])\s+"), "")
      .trim();
  if (normalized.isEmpty ||
      _isMarkdownHorizontalRule(normalized) ||
      _isMarkdownTableDivider(normalized) ||
      _isTechnicalCareerMetadataLine(normalized)) {
    return "";
  }
  return normalized;
}

String _careerDisplayBlock(String value) {
  return value
      .replaceAll("\r\n", "\n")
      .replaceAll("\r", "\n")
      .split("\n")
      .map(_careerDisplayLine)
      .where((line) => line.isNotEmpty)
      .join("\n")
      .trim();
}

_CareerLabelValue? _splitCareerLabelValue(
  String line, {
  required int maxLabelChars,
}) {
  final normalized = line.trim();
  if (normalized.isEmpty) {
    return null;
  }
  final boldLabelPatterns = [
    RegExp(r"^\*\*([^*\n:：]{1,48})[:：]\*\*\s*(.+)$", dotAll: true),
    RegExp(r"^__([^_\n:：]{1,48})[:：]__\s*(.+)$", dotAll: true),
    RegExp(r"^\*\*([^*\n]{1,48})\*\*\s*[:：]\s*(.+)$", dotAll: true),
    RegExp(r"^__([^_\n]{1,48})__\s*[:：]\s*(.+)$", dotAll: true),
  ];
  for (final pattern in boldLabelPatterns) {
    final match = pattern.firstMatch(normalized);
    if (match == null) {
      continue;
    }
    final label = _stripMarkdownInline(match.group(1) ?? "").trim();
    final value = _cleanCareerMarkdownValue(match.group(2) ?? "");
    if (label.isNotEmpty && label.length <= maxLabelChars && value.isNotEmpty) {
      return _CareerLabelValue(label: label, value: value);
    }
  }
  final separator = RegExp(r"[:：]").firstMatch(normalized);
  if (separator == null || separator.start == 0) {
    return null;
  }
  final label =
      _stripMarkdownInline(normalized.substring(0, separator.start)).trim();
  final value = _cleanCareerMarkdownValue(normalized.substring(separator.end));
  if (label.isEmpty || label.length > maxLabelChars || value.isEmpty) {
    return null;
  }
  return _CareerLabelValue(label: label, value: value);
}

String _cleanCareerMarkdownValue(String value) {
  return value
      .trim()
      .replaceFirst(RegExp(r"^(\*\*|__)\s*"), "")
      .replaceFirst(RegExp(r"\s*(\*\*|__)$"), "")
      .trim();
}

String _stripMarkdownInline(String value) {
  return value
      .replaceAllMapped(
        RegExp(r"\*\*([^*]+)\*\*"),
        (match) => match.group(1) ?? "",
      )
      .replaceAllMapped(
        RegExp(r"__([^_]+)__"),
        (match) => match.group(1) ?? "",
      )
      .replaceAllMapped(
        RegExp(r"\[([^\]]+)\]\([^)]+\)"),
        (match) => match.group(1) ?? "",
      )
      .replaceAllMapped(
        RegExp(r"`([^`]+)`"),
        (match) => match.group(1) ?? "",
      )
      .trim();
}

String _cleanCareerTableText(String value) {
  return _stripMarkdownInline(value)
      .replaceAll(RegExp(r"^[✅⚠❌⭕✔✘✓×]\uFE0F?\s*"), "")
      .replaceAll(RegExp(r"\s+"), " ")
      .trim();
}

List<_CareerRiskItem> _careerRiskItems(String body) {
  final risks = <_CareerRiskItem>[];

  for (final rawLine in body.split("\n")) {
    final displayLine = _careerDisplayLine(rawLine);
    if (displayLine.isEmpty || _isMarkdownTableDivider(displayLine)) {
      continue;
    }
    final risk = _riskItemFromPipeLine(displayLine);
    if (risk != null) {
      risks.add(risk);
      continue;
    }
  }

  if (risks.isNotEmpty) {
    return risks;
  }

  final fallbackItems = _careerSectionItems(body);
  return fallbackItems
      .where((item) => item.title.isNotEmpty || item.detail.isNotEmpty)
      .map(
        (item) => _CareerRiskItem(
          title: item.title.isEmpty
              ? _riskTitleFromDetail(item.detail)
              : item.title,
          level: _riskLevelFromText("${item.title} ${item.detail}"),
          detail: item.title.isEmpty ? item.detail : item.detail,
        ),
      )
      .toList();
}

_CareerRiskItem? _riskItemFromPipeLine(String line) {
  var normalized = line
      .replaceFirst(RegExp(r"^\|"), "")
      .replaceFirst(RegExp(r"\|$"), "")
      .trim();
  normalized = normalized
      .replaceFirst(RegExp(r"^\[[^\]]*(风险项|等级|说明)[^\]]*\]\s*\|?\s*"), "")
      .trim();
  if (_isMarkdownTableHeader(normalized)) {
    return null;
  }
  final delimiter = normalized.contains("|") ? "|" : "｜";
  final parts = normalized
      .split(delimiter)
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();
  if (parts.length < 3) {
    return null;
  }
  final title = _stripMarkdownInline(parts[0]).trim();
  final level = _stripMarkdownInline(parts[1]).trim();
  final detail = _cleanCareerMarkdownValue(parts.sublist(2).join(" | "));
  if (title.isEmpty || detail.isEmpty) {
    return null;
  }
  return _CareerRiskItem(title: title, level: level, detail: detail);
}

bool _isMarkdownTableHeader(String line) {
  final compact = _stripMarkdownInline(line).replaceAll(" ", "");
  return compact.contains("风险项") &&
      compact.contains("等级") &&
      compact.contains("说明");
}

bool _isMarkdownTableDivider(String line) {
  return RegExp(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$").hasMatch(line);
}

bool _isMarkdownHorizontalRule(String line) {
  return RegExp(r"^[-*_]{3,}$").hasMatch(line.replaceAll(" ", ""));
}

bool _isTechnicalCareerMetadataLine(String line) {
  final normalized = line.trim();
  if (normalized.isEmpty) {
    return false;
  }
  if (_looksLikeAssetReferenceLine(normalized)) {
    return true;
  }
  final compact = normalized.replaceAll(" ", "").toLowerCase();
  return compact.contains("jd分析id") ||
      compact.contains("数据来源") ||
      compact.contains("sourceartifact") ||
      compact.contains("artifactid") ||
      compact.contains("记录id");
}

String _riskTitleFromDetail(String detail) {
  final clean = _stripMarkdownInline(detail).trim();
  final separator = RegExp(r"[，,。；;]").firstMatch(clean);
  if (separator == null || separator.start < 4) {
    return clean.length > 18 ? "${clean.substring(0, 18)}..." : clean;
  }
  return clean.substring(0, separator.start).trim();
}

String _riskLevelFromText(String text) {
  if (RegExp(r"(高风险|严重|高\s*[｜|:]|等级[:：]?\s*高)").hasMatch(text)) {
    return "高";
  }
  if (RegExp(r"(低风险|轻微|低\s*[｜|:]|等级[:：]?\s*低)").hasMatch(text)) {
    return "低";
  }
  if (RegExp(r"(中风险|中等|中\s*[｜|:]|等级[:：]?\s*中)").hasMatch(text)) {
    return "中";
  }
  return "中";
}

_CareerRiskLevel _careerRiskLevel(String value) {
  final normalized = value.trim();
  if (normalized.contains("高")) {
    return const _CareerRiskLevel(
      label: "高风险",
      icon: Icons.priority_high_rounded,
      color: Color(0xFFDC2626),
    );
  }
  if (normalized.contains("低")) {
    return const _CareerRiskLevel(
      label: "低风险",
      icon: Icons.info_outline_rounded,
      color: Color(0xFF0F766E),
    );
  }
  return const _CareerRiskLevel(
    label: "中风险",
    icon: Icons.warning_amber_rounded,
    color: Color(0xFFB45309),
  );
}

_CareerItemVisual _careerItemVisual(
  String text, {
  required Color fallbackColor,
  required IconData fallbackIcon,
}) {
  final value = _stripMarkdownInline(text).toLowerCase();
  if (_containsAny(value, [
    "python",
    "fastapi",
    "postgres",
    "redis",
    "mysql",
    "elasticsearch",
    "pydantic",
    "技术栈",
    "后端"
  ])) {
    return const _CareerItemVisual(
      label: "技术栈",
      icon: Icons.terminal_rounded,
      color: Color(0xFF0F9B78),
    );
  }
  if (_containsAny(value,
      ["pytest", "mypy", "测试", "覆盖率", "ci", "cd", "github actions", "质量"])) {
    return const _CareerItemVisual(
      label: "质量验证",
      icon: Icons.verified_outlined,
      color: Color(0xFF2563EB),
    );
  }
  if (_containsAny(value, [
    "架构",
    "runtime",
    "langchain",
    "agent",
    "multi-agent",
    "工具调用",
    "事件",
    "审计",
    "jsonl"
  ])) {
    return const _CareerItemVisual(
      label: "架构能力",
      icon: Icons.account_tree_rounded,
      color: Color(0xFF7C3AED),
    );
  }
  if (_containsAny(value, ["性能", "延迟", "失败率", "吞吐", "压测", "压力", "优化", "效率"])) {
    return const _CareerItemVisual(
      label: "性能优化",
      icon: Icons.speed_rounded,
      color: Color(0xFFB45309),
    );
  }
  if (_containsAny(value, ["项目", "成果", "量化", "指标", "贡献", "落地", "实践"])) {
    return const _CareerItemVisual(
      label: "项目成果",
      icon: Icons.insights_rounded,
      color: Color(0xFF0E7490),
    );
  }
  if (_containsAny(value, ["模型", "机器学习", "训练", "mlops", "算法", "llm"])) {
    return const _CareerItemVisual(
      label: "模型经验",
      icon: Icons.psychology_alt_outlined,
      color: Color(0xFFB45309),
    );
  }
  if (_containsAny(value, ["简历", "表达", "描述", "措辞", "补充", "改写"])) {
    return const _CareerItemVisual(
      label: "表达优化",
      icon: Icons.edit_note_rounded,
      color: Color(0xFF2563EB),
    );
  }
  if (_containsAny(value, ["岗位", "jd", "匹配", "筛选", "投递"])) {
    return const _CareerItemVisual(
      label: "岗位匹配",
      icon: Icons.work_outline_rounded,
      color: Color(0xFF0F766E),
    );
  }
  return _CareerItemVisual(
    label: "",
    icon: fallbackIcon,
    color: fallbackColor,
  );
}

bool _containsAny(String value, List<String> keywords) {
  return keywords.any((keyword) => value.contains(keyword.toLowerCase()));
}

_CareerSectionVisual _careerSectionVisual(_CareerReportSectionType type) {
  return switch (type) {
    _CareerReportSectionType.score => const _CareerSectionVisual(
        role: "量化判断",
        icon: Icons.speed_rounded,
        color: Color(0xFF0E7490),
      ),
    _CareerReportSectionType.conclusion => _CareerSectionVisual(
        role: "先看结论",
        icon: Icons.fact_check_outlined,
        color: AppTheme.accent,
      ),
    _CareerReportSectionType.summary => _CareerSectionVisual(
        role: "先看结论",
        icon: Icons.summarize_outlined,
        color: AppTheme.accent,
      ),
    _CareerReportSectionType.insight => _CareerSectionVisual(
        role: "可复用卖点",
        icon: Icons.trending_up_rounded,
        color: AppTheme.accent,
      ),
    _CareerReportSectionType.risk => const _CareerSectionVisual(
        role: "投递前风险",
        icon: Icons.warning_amber_rounded,
        color: Color(0xFFB45309),
      ),
    _CareerReportSectionType.action => const _CareerSectionVisual(
        role: "下一步动作",
        icon: Icons.auto_fix_high_rounded,
        color: Color(0xFF2563EB),
      ),
    _CareerReportSectionType.markdown => _CareerSectionVisual(
        role: "结构化分析",
        icon: Icons.summarize_outlined,
        color: AppTheme.textSecondary,
      ),
  };
}
