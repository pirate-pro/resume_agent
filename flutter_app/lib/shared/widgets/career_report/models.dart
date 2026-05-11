part of '../career_report.dart';

enum _CareerReportSectionType {
  score,
  conclusion,
  summary,
  insight,
  risk,
  action,
  markdown,
}

class _CareerReportSection {
  final String title;
  final String body;
  final _CareerReportSectionType type;

  const _CareerReportSection({
    required this.title,
    required this.body,
    required this.type,
  });
}

class _CareerSectionVisual {
  final String role;
  final IconData icon;
  final Color color;

  const _CareerSectionVisual({
    required this.role,
    required this.icon,
    required this.color,
  });
}

class _CareerSummaryField {
  final String label;
  final String value;

  const _CareerSummaryField({required this.label, required this.value});
}

class _CareerReportScore {
  final int value;
  final String label;

  const _CareerReportScore({
    required this.value,
    required this.label,
  });
}

class _CareerReportLeadExtraction {
  final List<String> leadLines;
  final String? scoreTableBody;

  const _CareerReportLeadExtraction({
    required this.leadLines,
    required this.scoreTableBody,
  });
}

class _CareerMarkdownTableExtraction {
  final String body;
  final List<_CareerMarkdownTableBlock> tables;

  const _CareerMarkdownTableExtraction({
    required this.body,
    required this.tables,
  });
}

class _CareerMarkdownTableBlock {
  final String title;
  final String markdown;

  const _CareerMarkdownTableBlock({
    required this.title,
    required this.markdown,
  });
}

class _CareerMarkdownTableData {
  final List<String> headers;
  final List<List<String>> rows;

  const _CareerMarkdownTableData({
    required this.headers,
    required this.rows,
  });
}

class _CareerReportHighlight {
  final String label;
  final IconData icon;
  final Color color;

  const _CareerReportHighlight({
    required this.label,
    required this.icon,
    required this.color,
  });
}

class _CareerReportVerdict {
  final String label;
  final String summary;
  final Color color;
  final IconData icon;

  const _CareerReportVerdict({
    required this.label,
    required this.summary,
    required this.color,
    required this.icon,
  });
}

class _CareerScoreRow {
  final String label;
  final int score;
  final String note;

  const _CareerScoreRow({
    required this.label,
    required this.score,
    required this.note,
  });
}

class _CareerSectionItem {
  final String title;
  final String detail;

  const _CareerSectionItem({required this.title, required this.detail});
}

class _CareerLabelValue {
  final String label;
  final String value;

  const _CareerLabelValue({required this.label, required this.value});
}

class _CareerRiskItem {
  final String title;
  final String level;
  final String detail;

  const _CareerRiskItem({
    required this.title,
    required this.level,
    required this.detail,
  });
}

class _CareerItemVisual {
  final String label;
  final IconData icon;
  final Color color;

  const _CareerItemVisual({
    required this.label,
    required this.icon,
    required this.color,
  });
}

class _CareerRiskLevel {
  final String label;
  final IconData icon;
  final Color color;

  const _CareerRiskLevel({
    required this.label,
    required this.icon,
    required this.color,
  });
}

class _CareerTableStatus {
  final String label;
  final IconData icon;
  final Color color;

  const _CareerTableStatus({
    required this.label,
    required this.icon,
    required this.color,
  });
}
