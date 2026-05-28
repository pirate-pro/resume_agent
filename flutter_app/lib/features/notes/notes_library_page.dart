import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../../shared/widgets/markdown_body.dart';
import '../../shared/widgets/product_components.dart';
import '../career_ui/career_ui_helpers.dart';
import '../career_workbench/career_workbench_provider.dart';

class NotesLibraryPage extends ConsumerStatefulWidget {
  final String? currentSessionId;
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenLearning;
  final CareerPromptSender? onSendPrompt;

  const NotesLibraryPage({
    super.key,
    required this.currentSessionId,
    required this.onOpenProjects,
    required this.onOpenLearning,
    this.onSendPrompt,
  });

  @override
  ConsumerState<NotesLibraryPage> createState() => _NotesLibraryPageState();
}

class _NotesLibraryPageState extends ConsumerState<NotesLibraryPage> {
  String _selectedType = '';
  String? _selectedNoteId;
  NoteView? _draftNote;
  int _editorRevision = 0;

  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      final provider = ref.read(careerWorkbenchProvider);
      await provider.ensureLoaded();
      await provider.loadNotes();
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = ref.watch(careerWorkbenchProvider);
    final notes = provider.notes;
    final visibleNotes = _visibleNotes(notes);
    final selected = _selectedNote(visibleNotes, notes);
    final selectedType = _noteTypeMeta(selected?.noteType ?? _selectedType);
    final selectedApplication = _relatedApplication(provider, selected);

    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= 1180;
        final header = _NotesHeader(
          provider: provider,
          onRefresh: () => unawaited(provider.loadNotes(force: true)),
          onNewNote: () => _startDraft(provider),
          onGenerateReview: () => _sendReviewNote(selectedApplication),
        );
        final stats = _NotesMetricStrip(
          notes: notes,
          provider: provider,
        );
        final list = _NotesListPanel(
          notes: notes,
          visibleNotes: visibleNotes,
          selectedType: _selectedType,
          selectedNoteId: selected?.noteId,
          loading: provider.isLoadingNotes,
          error: provider.notesError,
          onTypeChanged: (value) => setState(() {
            _selectedType = value;
            _draftNote = null;
          }),
          onSelectNote: (note) => setState(() {
            _selectedNoteId = note.noteId;
            _draftNote = null;
            _editorRevision++;
          }),
          onNewNote: () => _startDraft(provider),
        );
        final editor = _NotesEditorPanel(
          key: ValueKey('${selected?.noteId ?? 'empty'}-$_editorRevision'),
          note: selected,
          typeMeta: selectedType,
          onSave:
              selected == null ? null : (draft) => _saveNote(provider, draft),
          onCancelDraft: _draftNote == null
              ? null
              : () => setState(() {
                    _draftNote = null;
                    _editorRevision++;
                  }),
        );
        final rail = _NotesRightRail(
          note: selected,
          typeMeta: selectedType,
          provider: provider,
          relatedApplication: selectedApplication,
          onOpenProjects: widget.onOpenProjects,
          onOpenLearning: widget.onOpenLearning,
          onNewNote: () => _startDraft(provider),
          onGenerateReview: () => _sendReviewNote(selectedApplication),
        );

        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              header,
              const SizedBox(height: 14),
              stats,
              const SizedBox(height: 14),
              rail,
              const SizedBox(height: 14),
              list,
              const SizedBox(height: 14),
              editor,
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
                SizedBox(width: 330, child: list),
                const SizedBox(width: 16),
                Expanded(child: editor),
                const SizedBox(width: 16),
                SizedBox(width: 340, child: rail),
              ],
            ),
          ],
        );
      },
    );
  }

  List<NoteView> _visibleNotes(List<NoteView> notes) {
    if (_selectedType.isEmpty) return notes;
    return notes
        .where((note) => _normalizeNoteType(note.noteType) == _selectedType)
        .toList(growable: false);
  }

  NoteView? _selectedNote(List<NoteView> visibleNotes, List<NoteView> notes) {
    final draft = _draftNote;
    if (draft != null) return draft;
    final selectedId = _selectedNoteId;
    if (selectedId != null) {
      for (final note in notes) {
        if (note.noteId == selectedId) return note;
      }
    }
    if (visibleNotes.isNotEmpty) return visibleNotes.first;
    return notes.isNotEmpty ? notes.first : null;
  }

  void _startDraft(CareerWorkbenchProvider provider) {
    const title = '新建笔记';
    setState(() {
      _draftNote = NoteView(
        noteId: 'note_draft',
        status: 'active',
        sourceSessionId: _noteSourceSessionId(
          provider,
          widget.currentSessionId,
        ),
        sourceArtifactId: null,
        evidenceRefs: const [],
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
        title: title,
        bodyMarkdown: '# $title\n\n',
        bodyFormat: 'markdown',
        noteType: _selectedType.isEmpty ? 'note' : _selectedType,
        origin: 'user',
        collectionId: null,
        tags: const [],
        sourceRefs: const [],
        relatedApplicationId:
            provider.selectedApplicationSummary?.application.applicationId,
        summary: '',
      );
      _selectedNoteId = 'note_draft';
      _editorRevision++;
    });
  }

  Future<void> _saveNote(
    CareerWorkbenchProvider provider,
    _NoteDraft draft,
  ) async {
    final current = _draftNote ?? _selectedNote(provider.notes, provider.notes);
    if (current == null) return;
    if (current.noteId == 'note_draft') {
      final created = await provider.createNote(
        sourceSessionId: current.sourceSessionId,
        sourceArtifactId: current.sourceArtifactId,
        evidenceRefs: current.evidenceRefs,
        sourceRefs: [
          for (final source in current.sourceRefs)
            {
              'source_type': source.sourceType,
              if (source.sourceId != null) 'source_id': source.sourceId,
              if (source.sourceSessionId != null)
                'source_session_id': source.sourceSessionId,
              'title': source.title,
              'quote': source.quote,
            },
        ],
        relatedApplicationId: current.relatedApplicationId,
        title: draft.title,
        bodyMarkdown: draft.bodyMarkdown,
        summary: draft.summary,
        tags: draft.tags,
        noteType: draft.noteType,
        origin: 'user',
      );
      if (!mounted) return;
      setState(() {
        _draftNote = null;
        _selectedNoteId = created.noteId;
        _editorRevision++;
      });
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text('笔记已创建')),
      );
      return;
    }

    await provider.updateNote(
      noteId: current.noteId,
      title: draft.title,
      bodyMarkdown: draft.bodyMarkdown,
      summary: draft.summary,
      tags: draft.tags,
      noteType: draft.noteType,
    );
    if (!mounted) return;
    setState(() {
      _selectedNoteId = current.noteId;
      _editorRevision++;
    });
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(
      const SnackBar(content: Text('笔记已保存')),
    );
  }

  CareerApplicationView? _relatedApplication(
    CareerWorkbenchProvider provider,
    NoteView? note,
  ) {
    final relatedId = note?.relatedApplicationId?.trim() ?? '';
    if (relatedId.isNotEmpty) {
      for (final app in provider.applications) {
        if (app.application.applicationId == relatedId) {
          return app.application;
        }
      }
    }
    return provider.selectedApplicationSummary?.application;
  }

  void _sendReviewNote(CareerApplicationView? app) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: '生成面试复盘笔记',
      actionType: 'note_create',
      origin: 'notes_library',
      detail: '请基于当前求职项目、面试记录和相关资料生成一条结构化复盘 Note；如果缺少面试输入，先询问用户。',
    );
  }
}

class _NotesHeader extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final VoidCallback onRefresh;
  final VoidCallback onNewNote;
  final VoidCallback onGenerateReview;

  const _NotesHeader({
    required this.provider,
    required this.onRefresh,
    required this.onNewNote,
    required this.onGenerateReview,
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
                    '笔记',
                    style: AppTheme.ts(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: ProductColors.text,
                    ),
                  ),
                  const ProductTag(
                    label: '知识沉淀',
                    tone: ProductTone.warning,
                    icon: Icons.sticky_note_2_outlined,
                  ),
                  if (provider.isLoadingNotes)
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
                '沉淀求职复盘、面试记录、学习想法和资料引用。',
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
                child: OutlinedButton.icon(
                  onPressed: onRefresh,
                  icon: const Icon(Icons.refresh_rounded, size: 16),
                  label: const Text('刷新'),
                  style: _outlineButtonStyle(),
                ),
              ),
              SizedBox(
                height: 38,
                child: OutlinedButton.icon(
                  onPressed: onGenerateReview,
                  icon: const Icon(Icons.auto_awesome_rounded, size: 16),
                  label: const Text('复盘整理'),
                  style: _outlineButtonStyle(),
                ),
              ),
              SizedBox(
                height: 38,
                child: ElevatedButton.icon(
                  onPressed: onNewNote,
                  icon: const Icon(Icons.add_rounded, size: 17),
                  label: const Text('新建笔记'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: ProductColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(horizontal: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    textStyle: AppTheme.ts(
                      fontSize: 12,
                      fontWeight: FontWeight.w900,
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
              const SizedBox(width: 14),
              controls,
            ],
          );
        },
      ),
    );
  }
}

class _NotesMetricStrip extends StatelessWidget {
  final List<NoteView> notes;
  final CareerWorkbenchProvider provider;

  const _NotesMetricStrip({
    required this.notes,
    required this.provider,
  });

  @override
  Widget build(BuildContext context) {
    final relatedCount = notes
        .where(
            (note) => (note.relatedApplicationId?.trim().isNotEmpty ?? false))
        .length;
    final resourceCount = notes
        .where((note) => _normalizeNoteType(note.noteType) == 'resource')
        .length;
    final learningCount = notes
        .where((note) => _normalizeNoteType(note.noteType) == 'learning')
        .length;
    final todayCount = notes
        .where((note) => _isSameDay(note.updatedAt, DateTime.now()))
        .length;
    final metrics = [
      ProductMetricCard(
        label: '全部笔记',
        value: notes.length.toString(),
        trend: provider.isLoadingNotes ? '同步中' : '已同步',
        icon: Icons.library_books_outlined,
        tone: ProductTone.warning,
      ),
      ProductMetricCard(
        label: '关联项目',
        value: relatedCount.toString(),
        trend: relatedCount == 0 ? '待关联' : '可追踪',
        icon: Icons.work_outline_rounded,
        tone: ProductTone.info,
      ),
      ProductMetricCard(
        label: '资料引用',
        value: resourceCount.toString(),
        trend: '学习 $learningCount 条',
        icon: Icons.bookmark_border_rounded,
        tone: ProductTone.primary,
      ),
      ProductMetricCard(
        label: '今日更新',
        value: todayCount.toString(),
        trend: todayCount == 0 ? '暂无更新' : '刚刚沉淀',
        icon: Icons.update_rounded,
        tone: ProductTone.purple,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns =
            (constraints.maxWidth / 230).floor().clamp(1, 4).toInt();
        final width =
            (constraints.maxWidth - (columns - 1) * 12) / math.max(columns, 1);
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final metric in metrics) SizedBox(width: width, child: metric),
          ],
        );
      },
    );
  }
}

class _NotesListPanel extends StatelessWidget {
  final List<NoteView> notes;
  final List<NoteView> visibleNotes;
  final String selectedType;
  final String? selectedNoteId;
  final bool loading;
  final String? error;
  final ValueChanged<String> onTypeChanged;
  final ValueChanged<NoteView> onSelectNote;
  final VoidCallback onNewNote;

  const _NotesListPanel({
    required this.notes,
    required this.visibleNotes,
    required this.selectedType,
    required this.selectedNoteId,
    required this.loading,
    required this.error,
    required this.onTypeChanged,
    required this.onSelectNote,
    required this.onNewNote,
  });

  @override
  Widget build(BuildContext context) {
    return ProductSection(
      title: '笔记库',
      subtitle: loading ? '读取中' : '${visibleNotes.length}/${notes.length} 条',
      icon: Icons.sticky_note_2_outlined,
      tone: ProductTone.warning,
      trailing: IconButton(
        tooltip: '新建笔记',
        onPressed: onNewNote,
        icon: const Icon(Icons.add_rounded),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _NoteFilterBar(
            notes: notes,
            value: selectedType,
            onChanged: onTypeChanged,
          ),
          const SizedBox(height: 12),
          if (loading && notes.isEmpty)
            const SizedBox(
              height: 180,
              child: Center(
                child: CircularProgressIndicator(color: ProductColors.primary),
              ),
            )
          else if (error != null && notes.isEmpty)
            _EmptyNoteBox(message: '笔记读取失败：$error')
          else if (notes.isEmpty)
            const _EmptyNoteBox(message: '还没有笔记。可以先新建一条自由笔记。')
          else if (visibleNotes.isEmpty)
            const _EmptyNoteBox(message: '当前筛选下暂无笔记。')
          else
            Column(
              children: [
                for (final note in visibleNotes.take(12)) ...[
                  _NoteTile(
                    note: note,
                    selected: note.noteId == selectedNoteId,
                    onTap: () => onSelectNote(note),
                  ),
                  if (note != visibleNotes.take(12).last)
                    const SizedBox(height: 9),
                ],
              ],
            ),
        ],
      ),
    );
  }
}

class _NoteFilterBar extends StatelessWidget {
  final List<NoteView> notes;
  final String value;
  final ValueChanged<String> onChanged;

  const _NoteFilterBar({
    required this.notes,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final counts = <String, int>{
      '': notes.length,
      for (final option in _noteTypeOptions) option.value: 0,
    };
    for (final note in notes) {
      final type = _normalizeNoteType(note.noteType);
      counts[type] = (counts[type] ?? 0) + 1;
    }
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _NoteFilterChip(
            label: '全部',
            count: counts[''] ?? 0,
            icon: Icons.all_inbox_outlined,
            tone: ProductTone.neutral,
            selected: value.isEmpty,
            onTap: () => onChanged(''),
          ),
          const SizedBox(width: 7),
          for (final option in _noteTypeOptions) ...[
            _NoteFilterChip(
              label: option.label,
              count: counts[option.value] ?? 0,
              icon: option.icon,
              tone: option.tone,
              selected: value == option.value,
              onTap: () => onChanged(option.value),
            ),
            if (option != _noteTypeOptions.last) const SizedBox(width: 7),
          ],
        ],
      ),
    );
  }
}

class _NoteFilterChip extends StatelessWidget {
  final String label;
  final int count;
  final IconData icon;
  final ProductTone tone;
  final bool selected;
  final VoidCallback onTap;

  const _NoteFilterChip({
    required this.label,
    required this.count,
    required this.icon,
    required this.tone,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: selected
                ? style.soft.withValues(alpha: 0.88)
                : ProductColors.surface,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected
                  ? style.color.withValues(alpha: 0.24)
                  : ProductColors.border,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon,
                  size: 13,
                  color: selected ? style.color : ProductColors.textMuted),
              const SizedBox(width: 5),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  color: selected ? style.color : ProductColors.textSecondary,
                ),
              ),
              const SizedBox(width: 5),
              Text(
                '$count',
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w800,
                  color: selected ? style.color : ProductColors.textMuted,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoteTile extends StatelessWidget {
  final NoteView note;
  final bool selected;
  final VoidCallback onTap;

  const _NoteTile({
    required this.note,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final meta = _noteTypeMeta(note.noteType);
    final style = productToneStyle(meta.tone);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
          decoration: BoxDecoration(
            color: selected
                ? style.soft.withValues(alpha: 0.72)
                : style.soft.withValues(alpha: 0.34),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: selected
                  ? style.color.withValues(alpha: 0.28)
                  : style.color.withValues(alpha: 0.1),
            ),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ProductIconTile(icon: meta.icon, tone: meta.tone, size: 34),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            note.title.trim().isEmpty ? '未命名笔记' : note.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 12.3,
                              fontWeight: FontWeight.w900,
                              color: ProductColors.text,
                            ),
                          ),
                        ),
                        ProductTag(label: meta.label, tone: meta.tone),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _noteSummary(note),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11,
                        height: 1.38,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 5,
                      runSpacing: 5,
                      children: [
                        ProductTag(
                          label: careerFormatDateTime(note.updatedAt),
                          tone: ProductTone.neutral,
                        ),
                        if (note.relatedApplicationId?.trim().isNotEmpty ==
                            true)
                          const ProductTag(
                            label: '关联项目',
                            tone: ProductTone.info,
                          ),
                        for (final tag in note.tags.take(2))
                          ProductTag(label: tag, tone: meta.tone),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NotesEditorPanel extends StatefulWidget {
  final NoteView? note;
  final _NoteTypeMeta typeMeta;
  final Future<void> Function(_NoteDraft draft)? onSave;
  final VoidCallback? onCancelDraft;

  const _NotesEditorPanel({
    super.key,
    required this.note,
    required this.typeMeta,
    required this.onSave,
    required this.onCancelDraft,
  });

  @override
  State<_NotesEditorPanel> createState() => _NotesEditorPanelState();
}

class _NotesEditorPanelState extends State<_NotesEditorPanel> {
  late final TextEditingController _titleController;
  late final TextEditingController _summaryController;
  late final TextEditingController _tagsController;
  late final TextEditingController _bodyController;
  late String _noteType;
  _NoteBodyMode _mode = _NoteBodyMode.preview;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final note = widget.note;
    _titleController = TextEditingController(text: note?.title ?? '');
    _summaryController = TextEditingController(text: note?.summary ?? '');
    _tagsController = TextEditingController(text: note?.tags.join('，') ?? '');
    _bodyController = TextEditingController(text: note?.bodyMarkdown ?? '');
    _bodyController.addListener(_handleBodyChanged);
    _noteType = _normalizeNoteType(note?.noteType ?? 'note');
    _mode = note?.noteId == 'note_draft'
        ? _NoteBodyMode.edit
        : _NoteBodyMode.preview;
  }

  @override
  void dispose() {
    _bodyController.removeListener(_handleBodyChanged);
    _titleController.dispose();
    _summaryController.dispose();
    _tagsController.dispose();
    _bodyController.dispose();
    super.dispose();
  }

  void _handleBodyChanged() {
    if (!mounted || _mode != _NoteBodyMode.live) return;
    setState(() {});
  }

  Future<void> _save() async {
    final save = widget.onSave;
    if (save == null) return;
    final title = _titleController.text.trim();
    final body = _bodyController.text.trim();
    if (title.isEmpty) {
      setState(() => _error = '标题不能为空');
      return;
    }
    if (body.isEmpty) {
      setState(() => _error = '正文不能为空');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await save(
        _NoteDraft(
          title: title,
          summary: _summaryController.text.trim(),
          bodyMarkdown: body,
          noteType: _noteType,
          tags: _parseTags(_tagsController.text),
        ),
      );
      if (!mounted) return;
      setState(() => _saving = false);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = '保存失败：$error';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final note = widget.note;
    if (note == null) {
      return const ProductCard(
        child: _EmptyNoteBox(message: '选择一条笔记，或新建笔记开始记录。'),
      );
    }
    final meta = _noteTypeMeta(_noteType);
    return ProductSection(
      title: note.noteId == 'note_draft' ? '新建笔记' : '编辑笔记',
      subtitle: note.noteId == 'note_draft'
          ? '创建后会进入笔记库'
          : '更新 ${careerFormatDateTime(note.updatedAt)}',
      icon: meta.icon,
      tone: meta.tone,
      trailing: _EditorModeSwitch(
        mode: _mode,
        onChanged: (value) => setState(() => _mode = value),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final titleField = TextField(
                key: const Key('notes_title_field'),
                controller: _titleController,
                decoration: _inputDecoration('标题'),
                style: AppTheme.ts(
                  fontSize: 13,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              );
              final tagField = TextField(
                key: const Key('notes_tags_field'),
                controller: _tagsController,
                decoration: _inputDecoration('标签，用逗号分隔'),
                style: AppTheme.ts(
                  fontSize: 12.2,
                  color: ProductColors.text,
                ),
              );
              if (constraints.maxWidth < 620) {
                return Column(
                  children: [
                    titleField,
                    const SizedBox(height: 10),
                    tagField,
                  ],
                );
              }
              return Row(
                children: [
                  Expanded(child: titleField),
                  const SizedBox(width: 10),
                  SizedBox(width: 260, child: tagField),
                ],
              );
            },
          ),
          const SizedBox(height: 12),
          _NoteTypeSelector(
            value: _noteType,
            onChanged: (value) => setState(() => _noteType = value),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('notes_summary_field'),
            controller: _summaryController,
            minLines: 2,
            maxLines: 3,
            decoration: _inputDecoration('摘要'),
            style: AppTheme.ts(
              fontSize: 12.2,
              height: 1.45,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 12),
          _NoteBodyArea(
            mode: _mode,
            controller: _bodyController,
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(
              _error!,
              style: AppTheme.ts(
                fontSize: 11.5,
                fontWeight: FontWeight.w800,
                color: ProductColors.danger,
              ),
            ),
          ],
          const SizedBox(height: 14),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            alignment: WrapAlignment.end,
            children: [
              if (widget.onCancelDraft != null)
                SizedBox(
                  height: 38,
                  child: OutlinedButton.icon(
                    onPressed: _saving ? null : widget.onCancelDraft,
                    icon: const Icon(Icons.close_rounded, size: 16),
                    label: const Text('取消'),
                    style: _outlineButtonStyle(),
                  ),
                ),
              SizedBox(
                height: 38,
                child: ElevatedButton.icon(
                  onPressed: _saving ? null : _save,
                  icon: Icon(
                    _saving ? Icons.hourglass_top_rounded : Icons.check_rounded,
                    size: 17,
                  ),
                  label: Text(_saving ? '保存中' : '保存'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: ProductColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(horizontal: 18),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    textStyle: AppTheme.ts(
                      fontSize: 12,
                      fontWeight: FontWeight.w900,
                    ),
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

class _NoteTypeSelector extends StatelessWidget {
  final String value;
  final ValueChanged<String> onChanged;

  const _NoteTypeSelector({
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return ProductCard(
      soft: true,
      tone: _noteTypeMeta(value).tone,
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '笔记类型',
            style: AppTheme.ts(
              fontSize: 11.5,
              fontWeight: FontWeight.w900,
              color: ProductColors.textSecondary,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              for (final option in _noteTypeOptions)
                _NoteTypePill(
                  meta: option,
                  selected: option.value == value,
                  onTap: () => onChanged(option.value),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            _noteTypeMeta(value).hint,
            style: AppTheme.ts(
              fontSize: 10.8,
              height: 1.35,
              color: ProductColors.textMuted,
            ),
          ),
        ],
      ),
    );
  }
}

class _NoteTypePill extends StatelessWidget {
  final _NoteTypeMeta meta;
  final bool selected;
  final VoidCallback onTap;

  const _NoteTypePill({
    required this.meta,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(meta.tone);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: selected ? style.soft : ProductColors.surface,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected
                  ? style.color.withValues(alpha: 0.25)
                  : ProductColors.border,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                meta.icon,
                size: 13,
                color: selected ? style.color : ProductColors.textMuted,
              ),
              const SizedBox(width: 5),
              Text(
                meta.label,
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  color: selected ? style.color : ProductColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EditorModeSwitch extends StatelessWidget {
  final _NoteBodyMode mode;
  final ValueChanged<_NoteBodyMode> onChanged;

  const _EditorModeSwitch({
    required this.mode,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _ModeButton(
            label: '编辑',
            icon: Icons.edit_outlined,
            selected: mode == _NoteBodyMode.edit,
            onTap: () => onChanged(_NoteBodyMode.edit),
          ),
          _ModeButton(
            label: '实时',
            icon: Icons.splitscreen_rounded,
            selected: mode == _NoteBodyMode.live,
            onTap: () => onChanged(_NoteBodyMode.live),
          ),
          _ModeButton(
            label: '预览',
            icon: Icons.visibility_outlined,
            selected: mode == _NoteBodyMode.preview,
            onTap: () => onChanged(_NoteBodyMode.preview),
          ),
        ],
      ),
    );
  }
}

class _ModeButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  const _ModeButton({
    required this.label,
    required this.icon,
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
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
          decoration: BoxDecoration(
            color: selected ? ProductColors.surface : Colors.transparent,
            borderRadius: BorderRadius.circular(999),
            boxShadow: selected
                ? [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.05),
                      blurRadius: 10,
                      offset: const Offset(0, 4),
                    ),
                  ]
                : null,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                icon,
                size: 13,
                color:
                    selected ? ProductColors.primary : ProductColors.textMuted,
              ),
              const SizedBox(width: 4),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 10.8,
                  fontWeight: FontWeight.w900,
                  color: selected
                      ? ProductColors.primary
                      : ProductColors.textMuted,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoteBodyArea extends StatelessWidget {
  final _NoteBodyMode mode;
  final TextEditingController controller;

  const _NoteBodyArea({
    required this.mode,
    required this.controller,
  });

  @override
  Widget build(BuildContext context) {
    if (mode == _NoteBodyMode.live) {
      return LayoutBuilder(
        builder: (context, constraints) {
          final editor = _MarkdownEditor(controller: controller);
          final preview = _MarkdownPreview(content: controller.text);
          if (constraints.maxWidth < 760) {
            return Column(
              children: [
                SizedBox(height: 260, child: editor),
                const SizedBox(height: 10),
                SizedBox(height: 260, child: preview),
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: SizedBox(height: 430, child: editor)),
              const SizedBox(width: 10),
              Expanded(child: SizedBox(height: 430, child: preview)),
            ],
          );
        },
      );
    }
    if (mode == _NoteBodyMode.preview) {
      return SizedBox(
          height: 520, child: _MarkdownPreview(content: controller.text));
    }
    return SizedBox(
        height: 520, child: _MarkdownEditor(controller: controller));
  }
}

class _MarkdownEditor extends StatelessWidget {
  final TextEditingController controller;

  const _MarkdownEditor({required this.controller});

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: const Key('notes_body_field'),
      controller: controller,
      expands: true,
      maxLines: null,
      minLines: null,
      textAlignVertical: TextAlignVertical.top,
      decoration: _inputDecoration('正文（Markdown）'),
      style: AppTheme.ts(
        fontSize: 13,
        height: 1.56,
        color: ProductColors.text,
      ),
    );
  }
}

class _MarkdownPreview extends StatelessWidget {
  final String content;

  const _MarkdownPreview({required this.content});

  @override
  Widget build(BuildContext context) {
    final normalized = content.trim();
    return Container(
      key: const Key('notes_markdown_preview'),
      width: double.infinity,
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: normalized.isEmpty
          ? const Center(child: Text('暂无内容'))
          : ClipRRect(
              borderRadius: BorderRadius.circular(14),
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
                child: AppMarkdownBody(
                  content: normalized,
                  style: AppTheme.ts(
                    fontSize: 13,
                    height: 1.62,
                    color: ProductColors.text,
                  ),
                ),
              ),
            ),
    );
  }
}

class _NotesRightRail extends StatelessWidget {
  final NoteView? note;
  final _NoteTypeMeta typeMeta;
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? relatedApplication;
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenLearning;
  final VoidCallback onNewNote;
  final VoidCallback onGenerateReview;

  const _NotesRightRail({
    required this.note,
    required this.typeMeta,
    required this.provider,
    required this.relatedApplication,
    required this.onOpenProjects,
    required this.onOpenLearning,
    required this.onNewNote,
    required this.onGenerateReview,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        ProductSection(
          title: '当前笔记',
          subtitle: note == null ? '未选择' : typeMeta.label,
          icon: typeMeta.icon,
          tone: typeMeta.tone,
          child: note == null
              ? const _EmptyNoteBox(message: '选择笔记后查看类型、来源和关联对象。')
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      note!.title.trim().isEmpty ? '未命名笔记' : note!.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 14,
                        height: 1.25,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _noteSummary(note!),
                      maxLines: 4,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12,
                        height: 1.45,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        ProductTag(label: typeMeta.label, tone: typeMeta.tone),
                        ProductTag(
                          label: _originLabel(note!.origin),
                          tone: ProductTone.neutral,
                        ),
                        ProductTag(
                          label: careerFormatDateTime(note!.updatedAt),
                          tone: ProductTone.neutral,
                        ),
                      ],
                    ),
                  ],
                ),
        ),
        const SizedBox(height: 14),
        ProductSection(
          title: '推荐动作',
          subtitle: '沉淀后继续推进',
          icon: Icons.auto_awesome_rounded,
          tone: ProductTone.primary,
          child: Column(
            children: [
              ProductActionTile(
                title: '新建自由笔记',
                subtitle: '记录新的想法、面试反馈或资料摘录。',
                icon: Icons.add_rounded,
                tone: ProductTone.primary,
                actionLabel: '新建',
                onTap: onNewNote,
              ),
              const SizedBox(height: 8),
              ProductActionTile(
                title: '整理面试复盘',
                subtitle: '让 Agent 把面试输入整理成结构化 Note。',
                icon: Icons.psychology_alt_outlined,
                tone: ProductTone.warning,
                actionLabel: '生成',
                onTap: onGenerateReview,
              ),
              const SizedBox(height: 8),
              ProductActionTile(
                title: '转成学习任务',
                subtitle: '把笔记里的短板转成可执行学习计划。',
                icon: Icons.school_outlined,
                tone: ProductTone.purple,
                actionLabel: '查看',
                onTap: onOpenLearning,
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        ProductSection(
          title: '关联项目',
          subtitle: relatedApplication == null
              ? '未关联'
              : careerStageLabel(relatedApplication!.stage),
          icon: Icons.work_outline_rounded,
          tone: ProductTone.info,
          child: ProductActionTile(
            title: relatedApplication?.displayTitle ?? '选择求职项目',
            subtitle: relatedApplication == null
                ? '关联项目后，笔记会成为岗位推进和复盘的上下文。'
                : careerFirstNonEmpty(
                    [
                      relatedApplication!.summary,
                      '${relatedApplication!.company} · ${relatedApplication!.location}',
                    ],
                    fallback: '查看当前项目和关联资料。',
                  ),
            icon: Icons.business_center_outlined,
            tone: ProductTone.info,
            actionLabel: '查看',
            onTap: onOpenProjects,
          ),
        ),
        const SizedBox(height: 14),
        ProductSection(
          title: '来源引用',
          subtitle: note == null ? '暂无' : '${note!.sourceRefs.length} 个来源',
          icon: Icons.link_rounded,
          tone: ProductTone.neutral,
          child: note == null || note!.sourceRefs.isEmpty
              ? const _EmptyNoteBox(message: '资料引用、报告摘录和会话来源会显示在这里。')
              : Column(
                  children: [
                    for (final source in note!.sourceRefs.take(4)) ...[
                      _SourceRefRow(source: source),
                      if (source != note!.sourceRefs.take(4).last)
                        const Divider(height: 16, color: ProductColors.border),
                    ],
                  ],
                ),
        ),
      ],
    );
  }
}

class _SourceRefRow extends StatelessWidget {
  final NoteSourceRefView source;

  const _SourceRefRow({required this.source});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ProductIconTile(
          icon: Icons.link_rounded,
          tone: ProductTone.neutral,
          size: 32,
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                source.title.trim().isEmpty
                    ? _sourceTypeLabel(source.sourceType)
                    : source.title.trim(),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                source.quote.trim().isEmpty
                    ? _compactLabel(
                        source.sourceId ?? source.sourceSessionId ?? '')
                    : source.quote.trim(),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 10.8,
                  height: 1.35,
                  color: ProductColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _EmptyNoteBox extends StatelessWidget {
  final String message;

  const _EmptyNoteBox({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: ProductSurface.softCard(tone: ProductTone.neutral),
      child: Text(
        message,
        style: AppTheme.ts(
          fontSize: 12,
          height: 1.45,
          color: ProductColors.textSecondary,
        ),
      ),
    );
  }
}

class _NoteDraft {
  final String title;
  final String summary;
  final String bodyMarkdown;
  final String noteType;
  final List<String> tags;

  const _NoteDraft({
    required this.title,
    required this.summary,
    required this.bodyMarkdown,
    required this.noteType,
    required this.tags,
  });
}

class _NoteTypeMeta {
  final String value;
  final String label;
  final String hint;
  final IconData icon;
  final ProductTone tone;

  const _NoteTypeMeta({
    required this.value,
    required this.label,
    required this.hint,
    required this.icon,
    required this.tone,
  });
}

const _noteTypeOptions = <_NoteTypeMeta>[
  _NoteTypeMeta(
    value: 'note',
    label: '记录',
    hint: '适合想法、总结、过程记录和杂项内容，后续作为个人上下文参考。',
    icon: Icons.edit_note_outlined,
    tone: ProductTone.warning,
  ),
  _NoteTypeMeta(
    value: 'learning',
    label: '学习',
    hint: '适合知识点、学习计划和短板复盘，后续学习建议会优先参考。',
    icon: Icons.school_outlined,
    tone: ProductTone.purple,
  ),
  _NoteTypeMeta(
    value: 'resource',
    label: '资料',
    hint: '适合面经、文章、链接或资产摘录，后续检索时作为参考材料。',
    icon: Icons.bookmark_border_rounded,
    tone: ProductTone.primary,
  ),
];

enum _NoteBodyMode { edit, live, preview }

_NoteTypeMeta _noteTypeMeta(String value) {
  final normalized = _normalizeNoteType(value);
  for (final option in _noteTypeOptions) {
    if (option.value == normalized) return option;
  }
  return _noteTypeOptions.first;
}

String _normalizeNoteType(String value) {
  final normalized = value.trim().toLowerCase();
  if (normalized == 'learning' || normalized == 'resource') return normalized;
  return 'note';
}

String _noteSummary(NoteView note) {
  return careerFirstNonEmpty(
    [note.summary, _plainSnippet(note.bodyMarkdown)],
    fallback: '暂无摘要。',
  );
}

String _plainSnippet(String markdown) {
  final text = markdown
      .replaceAll(RegExp(r'^#{1,6}\s*', multiLine: true), '')
      .replaceAll(RegExp(r'[*_`>#-]'), ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (text.length <= 88) return text;
  return '${text.substring(0, 88)}...';
}

List<String> _parseTags(String value) {
  return value
      .split(RegExp(r'[,，、\n]'))
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toSet()
      .take(8)
      .toList(growable: false);
}

String _noteSourceSessionId(
  CareerWorkbenchProvider provider,
  String? currentSessionId,
) {
  for (final value in [
    currentSessionId,
    provider.selectedApplicationSummary?.application.meta.sourceSessionId,
    provider.selectedApplicationDetail?.application.meta.sourceSessionId,
  ]) {
    final normalized = value?.trim() ?? '';
    if (normalized.startsWith('sess_')) return normalized;
  }
  return 'sess_workbench';
}

String _originLabel(String origin) {
  return switch (origin.trim().toLowerCase()) {
    'user' => '手写',
    'agent' => 'Agent 整理',
    _ => '来源未知',
  };
}

String _sourceTypeLabel(String sourceType) {
  return switch (sourceType.trim()) {
    'artifact' => '来源文件',
    'career_application' => '求职项目',
    'resume_profile' => '简历画像',
    'career_profile' => '职业画像',
    'jd_analysis' => 'JD 分析',
    'job_fit_report' => '匹配报告',
    'resume_version' => '简历版本',
    _ => '来源',
  };
}

String _compactLabel(String value) {
  final normalized = value.trim();
  if (normalized.length <= 28) return normalized;
  return '${normalized.substring(0, 12)}...${normalized.substring(normalized.length - 8)}';
}

bool _isSameDay(DateTime left, DateTime right) {
  return left.year == right.year &&
      left.month == right.month &&
      left.day == right.day;
}

InputDecoration _inputDecoration(String label) {
  return InputDecoration(
    labelText: label,
    filled: true,
    fillColor: ProductColors.surface,
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: ProductColors.border),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: ProductColors.border),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: ProductColors.primary),
    ),
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
  );
}

ButtonStyle _outlineButtonStyle() {
  return OutlinedButton.styleFrom(
    foregroundColor: ProductColors.primary,
    side: const BorderSide(color: ProductColors.borderStrong),
    padding: const EdgeInsets.symmetric(horizontal: 12),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    textStyle: AppTheme.ts(fontSize: 12, fontWeight: FontWeight.w900),
  );
}
