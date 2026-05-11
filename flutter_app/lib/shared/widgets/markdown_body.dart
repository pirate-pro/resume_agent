import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_highlight/themes/atom-one-dark.dart';
import 'package:flutter_highlight/themes/atom-one-light.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:gpt_markdown/gpt_markdown.dart';
import 'package:highlight/highlight.dart' as hl;
import 'package:highlight/highlight.dart' show Node;

import '../theme/app_theme.dart';

const int _autoCollapseCodeLines = 40;
const int _collapsedCodePreviewLines = 24;

class AssistantMarkdownBody extends StatelessWidget {
  final String content;

  const AssistantMarkdownBody({required this.content});

  @override
  Widget build(BuildContext context) {
    return AppMarkdownBody(
      content: content,
      style: AppTheme.ts(
        fontSize: 15,
        color: AppTheme.textPrimary,
        height: 1.65,
      ),
      enableLatex: _looksLikeLatex(content),
    );
  }
}

class AppMarkdownBody extends StatelessWidget {
  final String content;
  final TextStyle style;
  final bool compact;
  final bool enableLatex;

  const AppMarkdownBody({
    required this.content,
    required this.style,
    this.compact = false,
    this.enableLatex = false,
  });

  @override
  Widget build(BuildContext context) {
    if (compact) {
      return GptMarkdown(
        content,
        style: style,
        useDollarSignsForLatex: enableLatex,
        onLinkTap: (url, title) => _copyInlineMarkdownLink(context, url),
        tableBuilder: (context, tableRows, textStyle, config) {
          return _MarkdownTableCard(
            tableRows: tableRows,
            textStyle: textStyle,
          );
        },
        latexBuilder: (context, tex, textStyle, inline) {
          return _LatexBlock(
            tex: tex,
            inline: inline,
            textStyle: textStyle,
          );
        },
      );
    }
    return GptMarkdown(
      content,
      style: style,
      useDollarSignsForLatex: enableLatex,
      onLinkTap: (url, title) => _copyInlineMarkdownLink(context, url),
      codeBuilder: (context, name, code, closed) {
        return CodeBlockCard(
          language: name,
          code: code,
          closed: closed,
        );
      },
      tableBuilder: (context, tableRows, textStyle, config) {
        return _MarkdownTableCard(
          tableRows: tableRows,
          textStyle: textStyle,
        );
      },
      latexBuilder: (context, tex, textStyle, inline) {
        return _LatexBlock(
          tex: tex,
          inline: inline,
          textStyle: textStyle,
        );
      },
    );
  }
}

class _MarkdownTableCard extends StatelessWidget {
  final List<CustomTableRow> tableRows;
  final TextStyle textStyle;

  const _MarkdownTableCard({
    required this.tableRows,
    required this.textStyle,
  });

  @override
  Widget build(BuildContext context) {
    final normalizedRows = _normalizeTableRows(tableRows);
    if (normalizedRows.isEmpty) {
      return const SizedBox.shrink();
    }
    final schemaRow = normalizedRows.firstWhere(
      (row) => row.fields.isNotEmpty,
      orElse: () => normalizedRows.first,
    );
    final columnCount = schemaRow.fields.length;
    if (columnCount == 0) {
      return const SizedBox.shrink();
    }
    final displayRows = normalizedRows
        .map(
          (row) => CustomTableRow(
            isHeader: row.isHeader,
            fields: row.fields.take(columnCount).toList(),
          ),
        )
        .toList();
    final numericColumns = List<bool>.generate(
      columnCount,
      (columnIndex) => _looksLikeNumericTableColumn(displayRows, columnIndex),
    );

    final columnFlexes = _tableColumnFlexes(displayRows, columnCount);
    return LayoutBuilder(
      builder: (context, constraints) {
        final minWidth = constraints.maxWidth.isFinite
            ? constraints.maxWidth
            : columnCount * 180.0;
        final contentWidth = columnCount > 4
            ? (columnCount * 180.0).clamp(minWidth, 1200.0).toDouble()
            : minWidth;
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: EdgeInsets.zero,
            child: SizedBox(
              width: contentWidth,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: AppTheme.surface.withValues(
                    alpha: AppTheme.isDark ? 0.58 : 0.78,
                  ),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: AppTheme.borderLight.withValues(alpha: 0.58),
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: AppTheme.isDark
                          ? Colors.black.withValues(alpha: 0.08)
                          : Colors.black.withValues(alpha: 0.025),
                      blurRadius: 14,
                      offset: const Offset(0, 6),
                    ),
                  ],
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      for (var rowIndex = 0;
                          rowIndex < displayRows.length;
                          rowIndex += 1)
                        _MarkdownTableRowView(
                          row: displayRows[rowIndex],
                          textStyle: textStyle,
                          columnCount: columnCount,
                          columnFlexes: columnFlexes,
                          numericColumns: numericColumns,
                          isLast: rowIndex == displayRows.length - 1,
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

List<int> _tableColumnFlexes(List<CustomTableRow> rows, int columnCount) {
  if (columnCount <= 0) {
    return const [];
  }
  final scores = List<int>.filled(columnCount, 4);
  for (var columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
    var maxChars = 0;
    for (final row in rows) {
      if (columnIndex >= row.fields.length) {
        continue;
      }
      final value = _normalizedTableCellValue(row.fields[columnIndex].data);
      if (value.length > maxChars) {
        maxChars = value.length;
      }
    }
    scores[columnIndex] = maxChars.clamp(4, 24).toInt();
  }
  final minScore = scores.reduce((a, b) => a < b ? a : b);
  return scores
      .map((score) => (score / minScore).round().clamp(1, 4).toInt())
      .toList();
}

class _MarkdownTableRowView extends StatelessWidget {
  final CustomTableRow row;
  final TextStyle textStyle;
  final int columnCount;
  final List<int> columnFlexes;
  final List<bool> numericColumns;
  final bool isLast;

  const _MarkdownTableRowView({
    required this.row,
    required this.textStyle,
    required this.columnCount,
    required this.columnFlexes,
    required this.numericColumns,
    required this.isLast,
  });

  @override
  Widget build(BuildContext context) {
    final isHeader = row.isHeader;
    return Container(
      decoration: BoxDecoration(
        color: isHeader
            ? AppTheme.accent.withValues(alpha: AppTheme.isDark ? 0.14 : 0.08)
            : Colors.transparent,
        border: Border(
          bottom: isLast
              ? BorderSide.none
              : BorderSide(
                  color: AppTheme.border.withValues(alpha: 0.58),
                ),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var columnIndex = 0; columnIndex < columnCount; columnIndex += 1)
            Expanded(
              flex: columnFlexes[columnIndex],
              child: _MarkdownTableCell(
                text: columnIndex < row.fields.length
                    ? row.fields[columnIndex].data
                    : '',
                textStyle: textStyle,
                isHeader: isHeader,
                alignRight: columnIndex < row.fields.length
                    ? row.fields[columnIndex].alignment == TextAlign.right ||
                        numericColumns[columnIndex]
                    : numericColumns[columnIndex],
                showRightBorder: columnIndex < columnCount - 1,
              ),
            ),
        ],
      ),
    );
  }
}

class _MarkdownTableCell extends StatelessWidget {
  final String text;
  final TextStyle textStyle;
  final bool isHeader;
  final bool alignRight;
  final bool showRightBorder;

  const _MarkdownTableCell({
    required this.text,
    required this.textStyle,
    required this.isHeader,
    required this.alignRight,
    required this.showRightBorder,
  });

  @override
  Widget build(BuildContext context) {
    final cellStyle = textStyle.copyWith(
      fontSize: isHeader ? 12.5 : 12.8,
      fontWeight: isHeader ? FontWeight.w800 : FontWeight.w500,
      height: 1.52,
      color: isHeader ? AppTheme.textPrimary : AppTheme.textSecondary,
    );
    return Container(
      alignment: alignRight ? Alignment.centerRight : Alignment.centerLeft,
      padding:
          EdgeInsets.fromLTRB(13, isHeader ? 10 : 11, 13, isHeader ? 10 : 11),
      decoration: BoxDecoration(
        border: Border(
          right: showRightBorder
              ? BorderSide(color: AppTheme.border.withValues(alpha: 0.42))
              : BorderSide.none,
        ),
      ),
      child: SelectableText.rich(
        TextSpan(
          style: cellStyle,
          children: _buildPlainInlineSpans(text, cellStyle),
        ),
        textAlign: alignRight ? TextAlign.right : TextAlign.left,
      ),
    );
  }
}

class _LatexBlock extends StatelessWidget {
  final String tex;
  final bool inline;
  final TextStyle textStyle;

  const _LatexBlock({
    required this.tex,
    required this.inline,
    required this.textStyle,
  });

  @override
  Widget build(BuildContext context) {
    final widget = Math.tex(
      tex,
      mathStyle: inline ? MathStyle.text : MathStyle.display,
      textStyle: textStyle.copyWith(color: AppTheme.textPrimary),
      onErrorFallback: (error) {
        return SelectableText(
          tex,
          style: textStyle.copyWith(
            color: AppTheme.textSecondary,
            fontFamily: 'monospace',
          ),
        );
      },
    );
    if (inline) {
      return widget;
    }
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: widget,
      ),
    );
  }
}

class CodeBlockCard extends StatefulWidget {
  final String language;
  final String code;
  final bool closed;

  const CodeBlockCard({
    required this.language,
    required this.code,
    required this.closed,
  });

  @override
  State<CodeBlockCard> createState() => _CodeBlockCardState();
}

class _CodeBlockCardState extends State<CodeBlockCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final codeText = widget.code.trimRight();
    final lines = (codeText.isEmpty ? const [''] : codeText.split('\n'));
    final shouldCollapse =
        widget.closed && lines.length > _autoCollapseCodeLines;
    final visibleLines = shouldCollapse && !_expanded
        ? lines.take(_collapsedCodePreviewLines).toList()
        : lines;
    final lineNumbers = List<String>.generate(
      visibleLines.length,
      (index) => '${index + 1}',
    ).join('\n');
    final visibleCodeText = visibleLines.join('\n');
    final codeTheme = _codeHighlightTheme();
    final rootStyle = (codeTheme['root'] ?? const TextStyle()).merge(
      AppTheme.ts(
        fontSize: 13,
        height: 1.6,
      ).copyWith(fontFamily: 'monospace'),
    );
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 4),
      decoration: BoxDecoration(
        color: _codeSurfaceColor(),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
            decoration: BoxDecoration(
              color: _codeHeaderColor(),
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(14),
              ),
              border: Border(bottom: BorderSide(color: AppTheme.border)),
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: AppTheme.surfaceActive,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    widget.language.trim().isEmpty
                        ? 'code'
                        : widget.language.trim(),
                    style: AppTheme.ts(
                      fontSize: 11,
                      color: AppTheme.isDark
                          ? const Color(0xFFC5D1DD)
                          : const Color(0xFF445468),
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (!widget.closed) ...[
                  const SizedBox(width: 8),
                  Text(
                    '生成中',
                    style: AppTheme.ts(
                      fontSize: 11,
                      color: AppTheme.accent,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
                if (shouldCollapse) ...[
                  const SizedBox(width: 8),
                  Text(
                    _expanded
                        ? '已展开 ${lines.length} 行'
                        : '预览 ${visibleLines.length}/${lines.length} 行',
                    style: AppTheme.ts(
                      fontSize: 11,
                      color: AppTheme.textTertiary,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
                const Spacer(),
                CodeCopyButton(text: codeText),
              ],
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(12, 12, 14, 14),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SelectableText(
                  lineNumbers,
                  style: AppTheme.ts(
                    fontSize: 13,
                    color: AppTheme.isDark
                        ? const Color(0xFF6D7A88)
                        : const Color(0xFF8A96A3),
                    height: 1.6,
                  ).copyWith(fontFamily: 'monospace'),
                ),
                Container(
                  width: 1,
                  height: (visibleLines.length * 22)
                      .toDouble()
                      .clamp(24, 1200)
                      .toDouble(),
                  margin: const EdgeInsets.symmetric(horizontal: 12),
                  color: AppTheme.border,
                ),
                SelectableText.rich(
                  TextSpan(
                    style: rootStyle,
                    children: _buildHighlightedCodeSpans(
                      visibleCodeText,
                      widget.language,
                      codeTheme,
                      rootStyle,
                    ),
                  ),
                ),
              ],
            ),
          ),
          if (shouldCollapse)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: () => setState(() => _expanded = !_expanded),
                  style: TextButton.styleFrom(
                    foregroundColor: AppTheme.textPrimary,
                    textStyle: AppTheme.ts(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  icon: Icon(
                    _expanded
                        ? Icons.expand_less_rounded
                        : Icons.expand_more_rounded,
                    size: 16,
                  ),
                  label: Text(_expanded ? '收起代码' : '展开完整代码'),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class CodeCopyButton extends StatelessWidget {
  final String text;
  final String label;

  const CodeCopyButton({
    required this.text,
    this.label = '复制',
  });

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: () {
        Clipboard.setData(ClipboardData(text: text));
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('代码已复制'),
            duration: Duration(seconds: 1),
          ),
        );
      },
      style: TextButton.styleFrom(
        foregroundColor: AppTheme.textSecondary,
        textStyle: AppTheme.ts(fontSize: 12, fontWeight: FontWeight.w600),
      ),
      icon: const Icon(Icons.content_copy_rounded, size: 14),
      label: Text(label),
    );
  }
}

Map<String, TextStyle> _codeHighlightTheme() {
  return AppTheme.isDark ? atomOneDarkTheme : atomOneLightTheme;
}

Color _codeSurfaceColor() {
  return AppTheme.isDark ? const Color(0xFF171C22) : const Color(0xFFF5F8FC);
}

Color _codeHeaderColor() {
  return AppTheme.isDark
      ? Colors.white.withValues(alpha: 0.04)
      : const Color(0xFFEFF3F8);
}

List<InlineSpan> _buildHighlightedCodeSpans(
  String source,
  String language,
  Map<String, TextStyle> theme,
  TextStyle rootStyle,
) {
  final normalizedLanguage = _normalizeHighlightLanguage(language);
  final result = _safeParseHighlightedCode(source, normalizedLanguage);
  final nodes = result.nodes;
  if (nodes == null || nodes.isEmpty) {
    return [TextSpan(text: source, style: rootStyle)];
  }
  return _convertHighlightNodes(nodes, theme, rootStyle);
}

hl.Result _safeParseHighlightedCode(String source, String? language) {
  try {
    return hl.highlight.parse(
      source,
      language: language,
      autoDetection: language == null,
    );
  } catch (_) {
    return hl.highlight.parse(
      source,
      autoDetection: true,
    );
  }
}

List<InlineSpan> _convertHighlightNodes(
  List<Node> nodes,
  Map<String, TextStyle> theme,
  TextStyle rootStyle,
) {
  List<InlineSpan> traverse(List<Node> input, TextStyle inheritedStyle) {
    final spans = <InlineSpan>[];
    for (final node in input) {
      final nodeStyle = node.className == null
          ? inheritedStyle
          : inheritedStyle.merge(theme[node.className!]);
      if (node.value != null) {
        spans.add(
          TextSpan(
            text: node.value,
            style: nodeStyle,
          ),
        );
        continue;
      }
      final children = node.children;
      if (children == null || children.isEmpty) {
        continue;
      }
      spans.add(
        TextSpan(
          style: nodeStyle,
          children: traverse(children, nodeStyle),
        ),
      );
    }
    return spans;
  }

  return traverse(nodes, rootStyle);
}

String? _normalizeHighlightLanguage(String language) {
  final normalized = language.trim().toLowerCase();
  if (normalized.isEmpty || normalized == 'text' || normalized == 'plaintext') {
    return null;
  }
  const aliases = <String, String>{
    'py': 'python',
    'js': 'javascript',
    'ts': 'typescript',
    'shell': 'bash',
    'sh': 'bash',
    'zsh': 'bash',
    'md': 'markdown',
    'yml': 'yaml',
    'rb': 'ruby',
    'rs': 'rust',
    'kt': 'kotlin',
    'c++': 'cpp',
    'c#': 'csharp',
    'objc': 'objectivec',
  };
  return aliases[normalized] ?? normalized;
}

bool _looksLikeNumericTableColumn(List<CustomTableRow> rows, int columnIndex) {
  final values = <String>[];
  for (final row in rows) {
    if (row.isHeader || columnIndex >= row.fields.length) {
      continue;
    }
    final value = row.fields[columnIndex].data.trim();
    if (value.isNotEmpty) {
      values.add(value);
    }
  }
  if (values.isEmpty) {
    return false;
  }
  final numericLikeCount = values.where(_looksLikeNumericTableCell).length;
  return numericLikeCount >= ((values.length + 1) ~/ 2);
}

List<CustomTableRow> _trimEmptyTableColumns(List<CustomTableRow> rows) {
  if (rows.isEmpty) {
    return const [];
  }
  final maxColumns = rows.fold<int>(
    0,
    (maxCount, row) =>
        row.fields.length > maxCount ? row.fields.length : maxCount,
  );
  if (maxColumns == 0) {
    return const [];
  }

  var start = 0;
  var end = maxColumns - 1;

  while (start <= end && _isTableColumnEmpty(rows, start)) {
    start += 1;
  }
  while (end >= start && _isTableColumnEmpty(rows, end)) {
    end -= 1;
  }

  if (start > end) {
    return const [];
  }

  return rows
      .map(
        (row) => CustomTableRow(
          isHeader: row.isHeader,
          fields: row.fields.sublist(
            start.clamp(0, row.fields.length),
            end + 1 > row.fields.length ? row.fields.length : end + 1,
          ),
        ),
      )
      .toList();
}

List<CustomTableRow> _normalizeTableRows(List<CustomTableRow> rows) {
  final trimmedRows = rows
      .map((row) {
        final normalizedFields = row.fields
            .map(
              (field) => CustomTableField(
                data: field.data.trim(),
                alignment: field.alignment,
              ),
            )
            .toList();
        var end = normalizedFields.length;
        while (end > 0 &&
            _normalizedTableCellValue(normalizedFields[end - 1].data).isEmpty) {
          end -= 1;
        }
        var start = 0;
        while (start < end &&
            _normalizedTableCellValue(normalizedFields[start].data).isEmpty) {
          start += 1;
        }
        return CustomTableRow(
          isHeader: row.isHeader,
          fields: normalizedFields.sublist(start, end),
        );
      })
      .where((row) => row.fields.isNotEmpty)
      .toList();
  return _trimEmptyTableColumns(trimmedRows);
}

bool _isTableColumnEmpty(List<CustomTableRow> rows, int columnIndex) {
  for (final row in rows) {
    if (columnIndex >= row.fields.length) {
      continue;
    }
    if (_normalizedTableCellValue(row.fields[columnIndex].data).isNotEmpty) {
      return false;
    }
  }
  return true;
}

String _normalizedTableCellValue(String value) {
  return value
      .replaceAll(RegExp(r'[\u00A0\u200B-\u200D\uFEFF]'), '')
      .replaceAll('&nbsp;', '')
      .replaceAll(RegExp(r'[\s\r\n\t]+'), '')
      .replaceAll(RegExp(r'^[:\-|]+$'), '')
      .trim();
}

bool _looksLikeNumericTableCell(String value) {
  final normalized = value.replaceAll(',', '').replaceAll('，', '').trim();
  if (normalized.isEmpty) {
    return false;
  }
  final patterns = <RegExp>[
    RegExp(r'^[¥￥$]?\d+(\.\d+)?([万千百十亿])?([/%])?$'),
    RegExp(
        r'^约?[¥￥$]?\d+(\.\d+)?\s*[-~～]\s*[¥￥$]?\d+(\.\d+)?([万千百十亿])?([/%])?$'),
    RegExp(r'^\d+\s*[-~～]\s*\d+([/%])?$'),
    RegExp(r'^\d+(\.\d+)?\s*(元|万元|天|晚|小时|km|公里|人|项)$'),
  ];
  return patterns.any((pattern) => pattern.hasMatch(normalized));
}

List<InlineSpan> _buildPlainInlineSpans(String text, TextStyle baseStyle) {
  final spans = <InlineSpan>[];
  var index = 0;
  while (index < text.length) {
    if (text.startsWith('**', index)) {
      final closing = text.indexOf('**', index + 2);
      if (closing > index + 2) {
        final value = text.substring(index + 2, closing);
        if (!value.contains('\n')) {
          spans.add(
            TextSpan(
              text: value,
              style: baseStyle.copyWith(
                fontWeight: FontWeight.w700,
                color: AppTheme.textPrimary,
              ),
            ),
          );
          index = closing + 2;
          continue;
        }
      }
    }
    if (text.startsWith('`', index)) {
      final closing = text.indexOf('`', index + 1);
      if (closing > index + 1) {
        final value = text.substring(index + 1, closing);
        if (!value.contains('\n')) {
          spans.add(
            TextSpan(
              text: value,
              style: baseStyle.copyWith(
                fontFamily: 'monospace',
                fontSize: 14,
                color: AppTheme.accent,
                backgroundColor: AppTheme.surfaceActive,
              ),
            ),
          );
          index = closing + 1;
          continue;
        }
      }
    }
    if (text.startsWith('*', index) && !text.startsWith('**', index)) {
      final closing = text.indexOf('*', index + 1);
      if (closing > index + 1 && !text.startsWith('*', closing)) {
        final value = text.substring(index + 1, closing);
        if (!value.contains('\n')) {
          spans.add(
            TextSpan(
              text: value,
              style: baseStyle.copyWith(
                fontStyle: FontStyle.italic,
                color: AppTheme.textPrimary,
              ),
            ),
          );
          index = closing + 1;
          continue;
        }
      }
    }

    final nextSpecial = _findNextInlineSpecial(text, index);
    if (nextSpecial == index) {
      spans.add(TextSpan(text: text[index], style: baseStyle));
      index += 1;
      continue;
    }
    spans.add(
        TextSpan(text: text.substring(index, nextSpecial), style: baseStyle));
    index = nextSpecial;
  }
  return spans;
}

int _findNextInlineSpecial(String text, int start) {
  var next = text.length;
  for (final token in const ['**', '`', '*']) {
    final found = text.indexOf(token, start);
    if (found >= 0 && found < next) {
      next = found;
    }
  }
  return next;
}

void _copyInlineMarkdownLink(BuildContext context, String url) {
  Clipboard.setData(ClipboardData(text: url));
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(url.isEmpty ? "链接为空" : "链接已复制"),
      duration: const Duration(seconds: 1),
    ),
  );
}

bool _looksLikeLatex(String content) {
  if (content.contains(r'\(') || content.contains(r'\[')) {
    return true;
  }
  if (content.contains(r'$$')) {
    return true;
  }
  return RegExp(r'(?<!\\)\$[^$\n]{1,120}(?<!\\)\$').hasMatch(content);
}
