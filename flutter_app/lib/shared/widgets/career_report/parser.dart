part of '../career_report.dart';

class _CareerReportPresentation {
  final String rawContent;
  final String lead;
  final List<_CareerReportSection> sections;

  const _CareerReportPresentation({
    required this.rawContent,
    required this.lead,
    required this.sections,
  });

  static _CareerReportPresentation? tryParse(String content) {
    final normalized =
        content.replaceAll('\r\n', '\n').replaceAll('\r', '\n').trim();
    if (!_looksLikeCareerReport(normalized)) {
      return null;
    }
    final leadLines = <String>[];
    final sections = <_CareerReportSection>[];
    String? currentTitle;
    final currentBody = <String>[];

    void flushSection() {
      final title = currentTitle;
      if (title == null) return;
      final body = currentBody.join('\n').trim();
      sections.add(
        _CareerReportSection(
          title: title,
          body: body,
          type: _careerReportSectionType(title: title, body: body),
        ),
      );
      currentBody.clear();
    }

    for (final rawLine in normalized.split('\n')) {
      final heading = _careerSectionHeading(rawLine);
      if (heading != null) {
        flushSection();
        currentTitle = heading;
        continue;
      }
      final trimmed = rawLine.trim();
      if (currentTitle == null) {
        if (trimmed == '---' || trimmed.isEmpty) {
          continue;
        }
        leadLines.add(rawLine);
      } else {
        currentBody.add(rawLine);
      }
    }
    flushSection();
    final extractedLead = _extractCareerReportLead(leadLines);
    final reportSections = <_CareerReportSection>[
      if (extractedLead.scoreTableBody != null &&
          _careerScoreRows(extractedLead.scoreTableBody!).isNotEmpty)
        _CareerReportSection(
          title: normalized.contains("匹配") ? "匹配评分" : "综合评分",
          body: extractedLead.scoreTableBody!,
          type: _CareerReportSectionType.score,
        ),
      ...sections,
    ];
    if (reportSections.length < 2) {
      return null;
    }
    return _CareerReportPresentation(
      rawContent: normalized,
      lead: extractedLead.leadLines.join('\n').trim(),
      sections: reportSections,
    );
  }
}

String _careerReportDisplayTitle(_CareerReportPresentation report) {
  final joinedTitles =
      report.sections.map((section) => section.title).join(" ");
  if (joinedTitles.contains("匹配") || joinedTitles.contains("差距")) {
    return "岗位匹配报告";
  }
  if (joinedTitles.contains("JD")) {
    return "JD 分析报告";
  }
  if (joinedTitles.contains("优化")) {
    return "简历优化报告";
  }
  return "简历诊断报告";
}

_CareerReportLeadExtraction _extractCareerReportLead(List<String> leadLines) {
  final cleanedLead = <String>[];
  final scoreTable = <String>[];
  var skippingAssetTable = false;
  var collectingScoreTable = false;

  void closeScoreTable() {
    collectingScoreTable = false;
  }

  for (final rawLine in leadLines) {
    final trimmed = rawLine.trim();
    final isTableLine = trimmed.startsWith("|");
    if (trimmed.isEmpty || trimmed == "---") {
      if (collectingScoreTable) {
        closeScoreTable();
      }
      continue;
    }

    if (skippingAssetTable) {
      if (isTableLine || _looksLikeAssetReferenceLine(trimmed)) {
        continue;
      }
      skippingAssetTable = false;
    }

    if (collectingScoreTable) {
      if (isTableLine) {
        scoreTable.add(rawLine);
        continue;
      }
      closeScoreTable();
    }

    if (_isCareerAssetSummaryLead(trimmed)) {
      skippingAssetTable = true;
      continue;
    }
    if (_isCareerAssetTableHeader(trimmed)) {
      skippingAssetTable = true;
      continue;
    }
    if (_looksLikeAssetReferenceLine(trimmed)) {
      continue;
    }
    if (_isTechnicalCareerMetadataLine(trimmed)) {
      continue;
    }
    if (_isCareerScoreTableHeader(trimmed)) {
      collectingScoreTable = true;
      scoreTable.add(rawLine);
      continue;
    }
    if (_isCareerOverallScoreLine(trimmed)) {
      continue;
    }
    cleanedLead.add(rawLine);
  }

  return _CareerReportLeadExtraction(
    leadLines: cleanedLead,
    scoreTableBody: scoreTable.isEmpty ? null : scoreTable.join("\n").trim(),
  );
}

bool _isCareerAssetSummaryLead(String line) {
  return RegExp(
    r"(多\s*Agent\s*协作已完成|启动多\s*Agent\s*协作|已完成.*产品记录|已创建.*求职资产|已创建.*产品记录)",
  ).hasMatch(line);
}

bool _isCareerAssetTableHeader(String line) {
  if (!line.startsWith("|")) {
    return false;
  }
  final compact = line.replaceAll(" ", "");
  return compact.contains("类型") &&
      compact.contains("ID") &&
      compact.contains("说明");
}

bool _looksLikeAssetReferenceLine(String line) {
  return RegExp(
    r"\b(artifact|resume_profile|career_profile|jd_|fit_|resume_version)_[A-Za-z0-9][A-Za-z0-9_-]*\b",
  ).hasMatch(line);
}

bool _isCareerScoreTableHeader(String line) {
  if (!line.startsWith("|")) {
    return false;
  }
  final compact = line.replaceAll(" ", "");
  return compact.contains("维度") &&
      (compact.contains("得分") || compact.contains("评分"));
}

bool _isCareerOverallScoreLine(String line) {
  return RegExp(
    r"(?:总体|整体)?匹配度[^0-9]{0,24}[0-9]{1,3}\s*(?:/|／)\s*100",
  ).hasMatch(line);
}

bool _looksLikeCareerReport(String content) {
  if (content.isEmpty) {
    return false;
  }
  final hits =
      _careerSectionTitles.where((title) => content.contains(title)).length;
  return hits >= 2 &&
      (content.contains("简历") ||
          content.contains("诊断") ||
          content.contains("JD") ||
          content.contains("匹配"));
}

String? _careerSectionHeading(String line) {
  var text = line.trim();
  if (text.isEmpty) {
    return null;
  }
  text = text
      .replaceFirst(RegExp(r'^#{1,6}\s*'), '')
      .replaceFirst(RegExp(r'^\*\*'), '')
      .replaceFirst(RegExp(r'\*\*$'), '')
      .replaceFirst(RegExp(r'^__'), '')
      .replaceFirst(RegExp(r'__$'), '')
      .replaceFirst(RegExp(r'^[(（]?[一二三四五六七八九十]+[)）、.．]\s*'), '')
      .replaceFirst(RegExp(r'^\d+[\.、]\s*'), '')
      .replaceAll(RegExp(r'[:：]\s*$'), '')
      .trim();
  for (final title in _careerSectionTitles) {
    if (text == title ||
        text.startsWith("$title ") ||
        text.startsWith("$title：") ||
        text.startsWith("$title:")) {
      return title;
    }
  }
  return null;
}

const _careerSectionTitles = [
  "诊断摘要",
  "匹配结论",
  "核心优势",
  "核心亮点",
  "核心匹配点",
  "关键匹配点",
  "风险点",
  "主要风险点",
  "主要问题",
  "关键改进建议",
  "改进建议",
  "简历优化建议",
  "改进优先级",
  "匹配摘要",
  "候选人概况",
  "岗位核心要求 vs 候选人能力",
  "岗位核心要求",
  "关键匹配证据",
  "主要差距",
  "简历优化方向",
  "面试准备重点",
  "面试准备优先级",
];
