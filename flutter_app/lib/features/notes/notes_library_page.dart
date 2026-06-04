import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
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
  String _searchQuery = '';
  bool _projectOnly = false;
  bool _todayOnly = false;
  String? _selectedNoteId;
  NoteView? _draftNote;
  bool _isEditing = false;
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
        final desktop = constraints.maxWidth >= ProductBreakpoints.contentRail;
        final header = _NotesHeader(
          searchQuery: _searchQuery,
          loading: provider.isLoadingNotes,
          onSearchChanged: (value) => setState(() => _searchQuery = value),
          onRefresh: () => unawaited(provider.loadNotes(force: true)),
          onNewNote: () => _startDraft(provider),
        );
        final stats = _NotesMetricStrip(
          notes: notes,
          provider: provider,
          selectedType: _selectedType,
          projectOnly: _projectOnly,
          todayOnly: _todayOnly,
          onShowAll: () => setState(() {
            _selectedType = '';
            _projectOnly = false;
            _todayOnly = false;
          }),
          onShowProjectNotes: () => setState(() {
            _selectedType = '';
            _projectOnly = !_projectOnly;
            _todayOnly = false;
          }),
          onShowLearningNotes: () => setState(() {
            _selectedType = _selectedType == 'learning' ? '' : 'learning';
            _projectOnly = false;
            _todayOnly = false;
          }),
          onShowToday: () => setState(() {
            _todayOnly = !_todayOnly;
            _projectOnly = false;
            _selectedType = '';
          }),
        );
        final list = _NotesListPanel(
          notes: notes,
          visibleNotes: visibleNotes,
          selectedType: _selectedType,
          searchQuery: _searchQuery,
          selectedNoteId: selected?.noteId,
          loading: provider.isLoadingNotes,
          error: provider.notesError,
          onSearchChanged: (value) => setState(() => _searchQuery = value),
          onTypeChanged: (value) => setState(() {
            _selectedType = value;
            _projectOnly = false;
            _todayOnly = false;
            _draftNote = null;
            _isEditing = false;
          }),
          onClearFilters: () => setState(() {
            _selectedType = '';
            _searchQuery = '';
            _projectOnly = false;
            _todayOnly = false;
          }),
          onSelectNote: (note) => setState(() {
            _selectedNoteId = note.noteId;
            _draftNote = null;
            _isEditing = false;
            _editorRevision++;
          }),
          onNewNote: () => _startDraft(provider),
        );
        final editor = _NoteReaderEditor(
          key: ValueKey(
            '${selected?.noteId ?? 'empty'}-$_isEditing-$_editorRevision',
          ),
          note: selected,
          typeMeta: selectedType,
          isEditing: _isEditing,
          onStartEdit: selected == null
              ? null
              : () => setState(() {
                    _isEditing = true;
                    _editorRevision++;
                  }),
          onSave:
              selected == null ? null : (draft) => _saveNote(provider, draft),
          onCancelEdit: () => _cancelEdit(),
          onAppend: selected == null ? null : () => _showAppendDialog(selected),
          onArchive: selected == null
              ? null
              : () => _showArchiveDialog(provider, selected),
          onCopy: selected == null ? null : () => _copyNoteReference(selected),
          onReviewDraft: selected == null
              ? null
              : () => _showReviewDraftDialog(provider, selected),
          onActionDraft: selected == null
              ? null
              : () => _showActionDraftDialog(provider, selected),
        );
        final rail = _NoteContextRail(
          note: selected,
          typeMeta: selectedType,
          provider: provider,
          relatedApplication: selectedApplication,
          onOpenProjects: widget.onOpenProjects,
          onNewNote: () => _startDraft(provider),
          onAppend: selected == null ? null : () => _showAppendDialog(selected),
          onReviewDraft: selected == null
              ? null
              : () => _showReviewDraftDialog(provider, selected),
          onActionDraft: selected == null
              ? null
              : () => _showActionDraftDialog(provider, selected),
        );

        if (!desktop) {
          return ListView(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 18),
            children: [
              header,
              const SizedBox(height: 12),
              stats,
              const SizedBox(height: 12),
              list,
              const SizedBox(height: 12),
              editor,
              const SizedBox(height: 12),
              rail,
            ],
          );
        }

        return ListView(
          padding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
          children: [
            header,
            const SizedBox(height: 14),
            stats,
            const SizedBox(height: 14),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(width: 330, child: list),
                const SizedBox(width: 14),
                Expanded(child: editor),
                const SizedBox(width: 14),
                SizedBox(width: 340, child: rail),
              ],
            ),
          ],
        );
      },
    );
  }

  List<NoteView> _visibleNotes(List<NoteView> notes) {
    final query = _searchQuery.trim().toLowerCase();
    return notes.where((note) {
      if (_selectedType.isNotEmpty &&
          _normalizeNoteType(note.noteType) != _selectedType) {
        return false;
      }
      if (_projectOnly &&
          !(note.relatedApplicationId?.trim().isNotEmpty ?? false)) {
        return false;
      }
      if (_todayOnly && !_isSameDay(note.updatedAt, DateTime.now())) {
        return false;
      }
      if (query.isEmpty) return true;
      final haystack = [
        note.title,
        note.summary,
        note.bodyMarkdown,
        note.tags.join(' '),
        note.relatedApplicationId ?? '',
      ].join(' ').toLowerCase();
      return haystack.contains(query);
    }).toList(growable: false);
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
        title: '',
        bodyMarkdown: '',
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
      _isEditing = true;
      _editorRevision++;
    });
  }

  void _cancelEdit() {
    setState(() {
      if (_draftNote != null) {
        _draftNote = null;
        _selectedNoteId = null;
      }
      _isEditing = false;
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
        sourceRefs: _sourceRefsPayload(current.sourceRefs),
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
        _isEditing = false;
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
      _isEditing = false;
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

  Future<void> _copyNoteReference(NoteView note) async {
    final title = note.title.trim().isEmpty ? '未命名笔记' : note.title.trim();
    await Clipboard.setData(
      ClipboardData(text: '$title · ${note.noteId}'),
    );
    if (!mounted) return;
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(
      const SnackBar(content: Text('已复制笔记引用')),
    );
  }

  Future<void> _showAppendDialog(NoteView note) async {
    final content = await showDialog<String>(
      context: context,
      builder: (context) => _AppendNoteDialog(note: note),
    );
    if (!mounted || content == null || content.trim().isEmpty) return;
    final provider = ref.read(careerWorkbenchProvider);
    try {
      await provider.appendNote(
        noteId: note.noteId,
        bodyMarkdown: _appendBlock(content.trim()),
      );
      if (!mounted) return;
      setState(() {
        _selectedNoteId = note.noteId;
        _draftNote = null;
        _isEditing = false;
        _editorRevision++;
      });
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text('追加记录已保存')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text('追加记录失败：$error')),
      );
    }
  }

  Future<void> _showArchiveDialog(
    CareerWorkbenchProvider provider,
    NoteView note,
  ) async {
    if (note.noteId == 'note_draft') {
      _cancelEdit();
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => _ArchiveNoteDialog(note: note),
    );
    if (!mounted || confirmed != true) return;
    try {
      await provider.archiveNote(noteId: note.noteId);
      if (!mounted) return;
      final next = provider.notes.where((item) => item.noteId != note.noteId);
      setState(() {
        _selectedNoteId = next.isEmpty ? null : next.first.noteId;
        _draftNote = null;
        _isEditing = false;
        _editorRevision++;
      });
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(content: Text('笔记已归档')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text('归档失败：$error')),
      );
    }
  }

  Future<void> _showReviewDraftDialog(
    CareerWorkbenchProvider provider,
    NoteView note,
  ) async {
    final draft = _buildReviewDraft(note, _relatedApplication(provider, note));
    final action = await showDialog<_ReviewDraftAction>(
      context: context,
      builder: (context) => _ReviewDraftDialog(note: note, draft: draft),
    );
    if (!mounted || action == null) return;
    final messenger = ScaffoldMessenger.maybeOf(context);
    try {
      if (action == _ReviewDraftAction.append) {
        await provider.appendNote(
          noteId: note.noteId,
          bodyMarkdown: _appendBlock(draft),
        );
        setState(() {
          _selectedNoteId = note.noteId;
          _isEditing = false;
          _editorRevision++;
        });
        messenger?.showSnackBar(
          const SnackBar(content: Text('复盘草案已追加到当前笔记')),
        );
        return;
      }
      if (action == _ReviewDraftAction.create) {
        final created = await provider.createNote(
          sourceSessionId: note.sourceSessionId,
          sourceArtifactId: note.sourceArtifactId,
          evidenceRefs: note.evidenceRefs,
          sourceRefs: _sourceRefsPayload(note.sourceRefs),
          relatedApplicationId: note.relatedApplicationId,
          title: '复盘草案：${_safeTitle(note)}',
          bodyMarkdown: draft,
          summary: '基于「${_safeTitle(note)}」整理的结构化复盘草案。',
          tags: {...note.tags, '复盘'}.take(8).toList(),
          noteType: 'note',
          origin: 'agent',
        );
        setState(() {
          _selectedNoteId = created.noteId;
          _draftNote = null;
          _isEditing = false;
          _editorRevision++;
        });
        messenger?.showSnackBar(
          const SnackBar(content: Text('复盘草案已保存为新笔记')),
        );
      }
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text('处理复盘草案失败：$error')),
      );
    }
  }

  Future<void> _showActionDraftDialog(
    CareerWorkbenchProvider provider,
    NoteView note,
  ) async {
    final drafts = _buildActionDrafts(note);
    final result = await showDialog<_ActionDraftResult>(
      context: context,
      builder: (context) => _ActionDraftDialog(note: note, drafts: drafts),
    );
    if (!mounted || result == null || result.isEmpty) return;
    final messenger = ScaffoldMessenger.maybeOf(context);
    try {
      for (final draft in result.learningTasks) {
        await ref.read(apiServiceProvider).createLearningTask(
              sourceSessionId: _noteSourceSessionId(
                provider,
                widget.currentSessionId,
              ),
              title: draft.title,
              description: draft.description,
              priority: draft.priority,
              estimatedMinutes: draft.estimatedMinutes,
              evidenceRefs: note.evidenceRefs,
              skillTags: draft.skillTags,
              successCriteria: draft.successCriteria,
              progressNotes: '来源：笔记行动项草案；note_id=${note.noteId}',
            );
      }
      if (result.appendToNote.isNotEmpty) {
        await provider.appendNote(
          noteId: note.noteId,
          bodyMarkdown:
              _appendBlock(_actionDraftsMarkdown(result.appendToNote)),
        );
      }
      await provider.refresh();
      await provider.loadNotes(force: true);
      if (!mounted) return;
      messenger?.showSnackBar(
        SnackBar(
          content: Text(
            [
              if (result.learningTasks.isNotEmpty)
                '已创建 ${result.learningTasks.length} 个学习任务',
              if (result.appendToNote.isNotEmpty)
                '已追加 ${result.appendToNote.length} 条行动项',
            ].join('，'),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text('采纳行动项失败：$error')),
      );
    }
  }
}

class _NotesHeader extends StatelessWidget {
  final String searchQuery;
  final bool loading;
  final ValueChanged<String> onSearchChanged;
  final VoidCallback onRefresh;
  final VoidCallback onNewNote;

  const _NotesHeader({
    required this.searchQuery,
    required this.loading,
    required this.onSearchChanged,
    required this.onRefresh,
    required this.onNewNote,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 880;
        final title = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '笔记',
              style: AppTheme.ts(
                fontSize: 22,
                fontWeight: FontWeight.w900,
                color: ProductColors.text,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              '沉淀面试准备、复盘和资料摘记',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 12.5,
                color: ProductColors.textSecondary,
              ),
            ),
          ],
        );
        final search = _NotesSearchField(
          value: searchQuery,
          hint: '搜索笔记标题、内容、标签或项目...',
          onChanged: onSearchChanged,
        );
        final actions = Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _NotesButton(
              label: loading ? '同步中' : '刷新',
              icon: Icons.refresh_rounded,
              onPressed: loading ? null : onRefresh,
            ),
            const SizedBox(width: 10),
            _NotesButton(
              label: '新建笔记',
              icon: Icons.add_rounded,
              primary: true,
              onPressed: onNewNote,
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
              actions,
            ],
          );
        }
        return SizedBox(
          height: 66,
          child: Row(
            children: [
              SizedBox(width: 260, child: title),
              const SizedBox(width: 18),
              Expanded(
                  child: Center(
                      child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 560),
                child: search,
              ))),
              const SizedBox(width: 18),
              actions,
            ],
          ),
        );
      },
    );
  }
}

class _NotesMetricStrip extends StatelessWidget {
  final List<NoteView> notes;
  final CareerWorkbenchProvider provider;
  final String selectedType;
  final bool projectOnly;
  final bool todayOnly;
  final VoidCallback onShowAll;
  final VoidCallback onShowProjectNotes;
  final VoidCallback onShowLearningNotes;
  final VoidCallback onShowToday;

  const _NotesMetricStrip({
    required this.notes,
    required this.provider,
    required this.selectedType,
    required this.projectOnly,
    required this.todayOnly,
    required this.onShowAll,
    required this.onShowProjectNotes,
    required this.onShowLearningNotes,
    required this.onShowToday,
  });

  @override
  Widget build(BuildContext context) {
    final projectCount = notes
        .where(
          (note) => (note.relatedApplicationId?.trim().isNotEmpty ?? false),
        )
        .length;
    final learningCount = notes
        .where((note) => _normalizeNoteType(note.noteType) == 'learning')
        .length;
    final todayCount = notes
        .where((note) => _isSameDay(note.updatedAt, DateTime.now()))
        .length;
    final metrics = [
      _NoteMetricData(
        label: '全部笔记',
        value: notes.length.toString(),
        caption: provider.isLoadingNotes ? '同步中' : '所有笔记总数',
        icon: Icons.library_books_outlined,
        tone: ProductTone.primary,
        active: selectedType.isEmpty && !projectOnly && !todayOnly,
        onTap: onShowAll,
      ),
      _NoteMetricData(
        label: '项目笔记',
        value: projectCount.toString(),
        caption: '与求职项目相关',
        icon: Icons.work_outline_rounded,
        tone: ProductTone.info,
        active: projectOnly,
        onTap: onShowProjectNotes,
      ),
      _NoteMetricData(
        label: '学习笔记',
        value: learningCount.toString(),
        caption: '学习与知识沉淀',
        icon: Icons.school_outlined,
        tone: ProductTone.purple,
        active: selectedType == 'learning',
        onTap: onShowLearningNotes,
      ),
      _NoteMetricData(
        label: '今日更新',
        value: todayCount.toString(),
        caption: todayCount == 0 ? '较昨日 +0' : '刚刚沉淀',
        icon: Icons.update_rounded,
        tone: ProductTone.warning,
        active: todayOnly,
        onTap: onShowToday,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns =
            (constraints.maxWidth / 250).floor().clamp(1, 4).toInt();
        final width =
            (constraints.maxWidth - (columns - 1) * 12) / math.max(columns, 1);
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final metric in metrics)
              SizedBox(width: width, child: _NoteMetricCard(metric: metric)),
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
  final String searchQuery;
  final String? selectedNoteId;
  final bool loading;
  final String? error;
  final ValueChanged<String> onSearchChanged;
  final ValueChanged<String> onTypeChanged;
  final VoidCallback onClearFilters;
  final ValueChanged<NoteView> onSelectNote;
  final VoidCallback onNewNote;

  const _NotesListPanel({
    required this.notes,
    required this.visibleNotes,
    required this.selectedType,
    required this.searchQuery,
    required this.selectedNoteId,
    required this.loading,
    required this.error,
    required this.onSearchChanged,
    required this.onTypeChanged,
    required this.onClearFilters,
    required this.onSelectNote,
    required this.onNewNote,
  });

  @override
  Widget build(BuildContext context) {
    final displayed = visibleNotes.take(30).toList(growable: false);
    return _NotesPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _PanelHeader(
            icon: Icons.sticky_note_2_outlined,
            tone: ProductTone.warning,
            title: '笔记库',
            subtitle: '按更新时间排序的笔记',
            trailing: IconButton(
              tooltip: '新建笔记',
              onPressed: onNewNote,
              icon: const Icon(Icons.add_rounded),
              color: ProductColors.primary,
            ),
          ),
          const SizedBox(height: 12),
          _NotesSearchField(
            value: searchQuery,
            hint: '搜索笔记标题或内容...',
            dense: true,
            onChanged: onSearchChanged,
          ),
          const SizedBox(height: 10),
          _NoteFilterBar(
            notes: notes,
            value: selectedType,
            onChanged: onTypeChanged,
          ),
          const SizedBox(height: 14),
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
            _NotesEmptyState(
              title: '还没有笔记',
              message: '可以记录面试反馈、学习心得或资料摘录，后续会成为简历优化和学习计划的上下文。',
              actionLabel: '新建笔记',
              onAction: onNewNote,
            )
          else if (visibleNotes.isEmpty)
            _NotesEmptyState(
              title: '没有符合条件的笔记',
              message: '可以清空筛选，或新建一条当前类型的笔记。',
              actionLabel: '清空筛选',
              onAction: onClearFilters,
            )
          else
            Column(
              children: [
                for (final note in displayed) ...[
                  _NoteTile(
                    note: note,
                    selected: note.noteId == selectedNoteId,
                    onTap: () => onSelectNote(note),
                  ),
                  if (note != displayed.last) const SizedBox(height: 10),
                ],
              ],
            ),
        ],
      ),
    );
  }
}

class _NoteReaderEditor extends StatefulWidget {
  final NoteView? note;
  final _NoteTypeMeta typeMeta;
  final bool isEditing;
  final VoidCallback? onStartEdit;
  final Future<void> Function(_NoteDraft draft)? onSave;
  final VoidCallback onCancelEdit;
  final VoidCallback? onAppend;
  final VoidCallback? onArchive;
  final VoidCallback? onCopy;
  final VoidCallback? onReviewDraft;
  final VoidCallback? onActionDraft;

  const _NoteReaderEditor({
    super.key,
    required this.note,
    required this.typeMeta,
    required this.isEditing,
    required this.onStartEdit,
    required this.onSave,
    required this.onCancelEdit,
    required this.onAppend,
    required this.onArchive,
    required this.onCopy,
    required this.onReviewDraft,
    required this.onActionDraft,
  });

  @override
  State<_NoteReaderEditor> createState() => _NoteReaderEditorState();
}

class _NoteReaderEditorState extends State<_NoteReaderEditor> {
  late final TextEditingController _titleController;
  late final TextEditingController _summaryController;
  late final TextEditingController _tagsController;
  late final TextEditingController _bodyController;
  late String _noteType;
  _NoteBodyMode _mode = _NoteBodyMode.edit;
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
    _mode = widget.isEditing || note?.noteId == 'note_draft'
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
      return _NotesPanel(
        child: _NotesEmptyState(
          title: '选择一条笔记查看内容',
          message: '你可以从左侧笔记库选择，也可以新建一条面试、学习或资料笔记。',
          actionLabel: '新建笔记',
          onAction: null,
        ),
      );
    }
    if (!widget.isEditing) {
      return _NoteReader(
        note: note,
        typeMeta: widget.typeMeta,
        onStartEdit: widget.onStartEdit,
        onAppend: widget.onAppend,
        onArchive: widget.onArchive,
        onCopy: widget.onCopy,
        onReviewDraft: widget.onReviewDraft,
        onActionDraft: widget.onActionDraft,
      );
    }
    return _NoteEditor(
      note: note,
      mode: _mode,
      noteType: _noteType,
      saving: _saving,
      error: _error,
      titleController: _titleController,
      summaryController: _summaryController,
      tagsController: _tagsController,
      bodyController: _bodyController,
      onModeChanged: (value) => setState(() => _mode = value),
      onTypeChanged: (value) => setState(() => _noteType = value),
      onCancel: widget.onCancelEdit,
      onSave: _saving ? null : _save,
    );
  }
}

class _NoteContextRail extends StatelessWidget {
  final NoteView? note;
  final _NoteTypeMeta typeMeta;
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? relatedApplication;
  final VoidCallback onOpenProjects;
  final VoidCallback onNewNote;
  final VoidCallback? onAppend;
  final VoidCallback? onReviewDraft;
  final VoidCallback? onActionDraft;

  const _NoteContextRail({
    required this.note,
    required this.typeMeta,
    required this.provider,
    required this.relatedApplication,
    required this.onOpenProjects,
    required this.onNewNote,
    required this.onAppend,
    required this.onReviewDraft,
    required this.onActionDraft,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _CurrentNoteContextCard(note: note, typeMeta: typeMeta),
        const SizedBox(height: 14),
        _NoteNextActionsCard(
          note: note,
          typeMeta: typeMeta,
          onNewNote: onNewNote,
          onAppend: onAppend,
          onReviewDraft: onReviewDraft,
          onActionDraft: onActionDraft,
        ),
        const SizedBox(height: 14),
        _RelatedProjectCard(
          application: relatedApplication,
          onOpenProjects: onOpenProjects,
        ),
        const SizedBox(height: 14),
        _SourceRefsCard(note: note),
      ],
    );
  }
}

class _NoteReader extends StatelessWidget {
  final NoteView note;
  final _NoteTypeMeta typeMeta;
  final VoidCallback? onStartEdit;
  final VoidCallback? onAppend;
  final VoidCallback? onArchive;
  final VoidCallback? onCopy;
  final VoidCallback? onReviewDraft;
  final VoidCallback? onActionDraft;

  const _NoteReader({
    required this.note,
    required this.typeMeta,
    required this.onStartEdit,
    required this.onAppend,
    required this.onArchive,
    required this.onCopy,
    required this.onReviewDraft,
    required this.onActionDraft,
  });

  @override
  Widget build(BuildContext context) {
    final title = _safeTitle(note);
    final summary = _noteSummary(note);
    final tags = note.tags.take(8).toList(growable: false);
    return _NotesPanel(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ProductIconTile(
                  icon: typeMeta.icon, tone: typeMeta.tone, size: 44),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: AppTheme.ts(
                        fontSize: 24,
                        height: 1.25,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        ProductTag(label: typeMeta.label, tone: typeMeta.tone),
                        ProductTag(
                          label: _originLabel(note.origin),
                          tone: ProductTone.neutral,
                        ),
                        ProductTag(
                          label: '更新于 ${careerFormatDateTime(note.updatedAt)}',
                          tone: ProductTone.neutral,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              _IconPillButton(
                key: const Key('notes_reader_header_edit_button'),
                tooltip: '编辑',
                icon: Icons.edit_outlined,
                label: '编辑',
                onTap: onStartEdit,
              ),
            ],
          ),
          const SizedBox(height: 18),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
            decoration: ProductSurface.softCard(
              tone: ProductTone.primary,
              radius: 14,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '摘要',
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  summary,
                  style: AppTheme.ts(
                    fontSize: 13,
                    height: 1.55,
                    color: ProductColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
            decoration: BoxDecoration(
              color: ProductColors.surface,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: ProductColors.border),
            ),
            child: note.bodyMarkdown.trim().isEmpty
                ? Text(
                    '暂无正文。',
                    style: AppTheme.ts(
                      fontSize: 13,
                      color: ProductColors.textMuted,
                    ),
                  )
                : AppMarkdownBody(
                    content: note.bodyMarkdown.trim(),
                    style: AppTheme.ts(
                      fontSize: 14,
                      height: 1.7,
                      color: ProductColors.text,
                    ),
                  ),
          ),
          if (tags.isNotEmpty) ...[
            const SizedBox(height: 16),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                for (final tag in tags)
                  ProductTag(label: tag, tone: typeMeta.tone),
              ],
            ),
          ],
          const SizedBox(height: 18),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              _NotesButton(
                key: const Key('notes_reader_edit_button'),
                label: '编辑',
                icon: Icons.edit_outlined,
                onPressed: onStartEdit,
              ),
              _NotesButton(
                label: '追加记录',
                icon: Icons.add_comment_outlined,
                onPressed: onAppend,
              ),
              _NotesButton(
                label: '复制引用',
                icon: Icons.copy_rounded,
                onPressed: onCopy,
              ),
              _NotesButton(
                label: '整理复盘',
                icon: Icons.fact_check_outlined,
                onPressed: onReviewDraft,
              ),
              _NotesButton(
                label: '提取行动',
                icon: Icons.checklist_rounded,
                onPressed: onActionDraft,
              ),
              _NotesButton(
                label: '归档笔记',
                icon: Icons.archive_outlined,
                danger: true,
                onPressed: onArchive,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _NoteEditor extends StatelessWidget {
  final NoteView note;
  final _NoteBodyMode mode;
  final String noteType;
  final bool saving;
  final String? error;
  final TextEditingController titleController;
  final TextEditingController summaryController;
  final TextEditingController tagsController;
  final TextEditingController bodyController;
  final ValueChanged<_NoteBodyMode> onModeChanged;
  final ValueChanged<String> onTypeChanged;
  final VoidCallback onCancel;
  final VoidCallback? onSave;

  const _NoteEditor({
    required this.note,
    required this.mode,
    required this.noteType,
    required this.saving,
    required this.error,
    required this.titleController,
    required this.summaryController,
    required this.tagsController,
    required this.bodyController,
    required this.onModeChanged,
    required this.onTypeChanged,
    required this.onCancel,
    required this.onSave,
  });

  @override
  Widget build(BuildContext context) {
    return _NotesPanel(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _EditorModeSwitch(mode: mode, onChanged: onModeChanged),
              const Spacer(),
              _NotesButton(
                label: '取消',
                icon: Icons.close_rounded,
                onPressed: saving ? null : onCancel,
              ),
              const SizedBox(width: 10),
              _NotesButton(
                label: saving ? '保存中' : '保存笔记',
                icon:
                    saving ? Icons.hourglass_top_rounded : Icons.check_rounded,
                primary: true,
                onPressed: onSave,
              ),
            ],
          ),
          const SizedBox(height: 18),
          Text(
            '标题 *',
            style: _fieldLabelStyle(),
          ),
          const SizedBox(height: 7),
          TextField(
            key: const Key('notes_title_field'),
            controller: titleController,
            autofocus: note.noteId == 'note_draft',
            decoration: _inputDecoration('输入笔记标题'),
            style: AppTheme.ts(
              fontSize: 14,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 14),
          Text('标签', style: _fieldLabelStyle()),
          const SizedBox(height: 7),
          TextField(
            key: const Key('notes_tags_field'),
            controller: tagsController,
            decoration: _inputDecoration('输入标签后按 Enter，用逗号分隔也可以'),
            style: AppTheme.ts(fontSize: 13, color: ProductColors.text),
          ),
          const SizedBox(height: 14),
          Text('笔记类型', style: _fieldLabelStyle()),
          const SizedBox(height: 7),
          _NoteTypeSelector(value: noteType, onChanged: onTypeChanged),
          const SizedBox(height: 14),
          Text('摘要', style: _fieldLabelStyle()),
          const SizedBox(height: 7),
          TextField(
            key: const Key('notes_summary_field'),
            controller: summaryController,
            minLines: 3,
            maxLines: 5,
            maxLength: 300,
            decoration: _inputDecoration('整理这条笔记的背景、重点和用途'),
            style: AppTheme.ts(
              fontSize: 13,
              height: 1.5,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 12),
          Text('内容（Markdown）', style: _fieldLabelStyle()),
          const SizedBox(height: 7),
          _NoteBodyArea(mode: mode, controller: bodyController),
          if (error != null) ...[
            const SizedBox(height: 10),
            Text(
              error!,
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: ProductColors.danger,
              ),
            ),
          ],
          const SizedBox(height: 14),
          Align(
            alignment: Alignment.centerRight,
            child: Wrap(
              spacing: 10,
              children: [
                _NotesButton(
                  label: '取消',
                  icon: Icons.close_rounded,
                  onPressed: saving ? null : onCancel,
                ),
                _NotesButton(
                  label: saving ? '保存中' : '保存笔记',
                  icon: saving
                      ? Icons.hourglass_top_rounded
                      : Icons.check_rounded,
                  primary: true,
                  onPressed: onSave,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CurrentNoteContextCard extends StatelessWidget {
  final NoteView? note;
  final _NoteTypeMeta typeMeta;

  const _CurrentNoteContextCard({
    required this.note,
    required this.typeMeta,
  });

  @override
  Widget build(BuildContext context) {
    return _ContextCard(
      title: '当前笔记上下文',
      icon: Icons.route_outlined,
      tone: typeMeta.tone,
      trailing: note == null
          ? null
          : ProductTag(label: typeMeta.label, tone: typeMeta.tone),
      child: note == null
          ? const _EmptyNoteBox(message: '选择笔记后查看类型、来源和关联对象。')
          : Column(
              children: [
                _ContextRow(label: '类型', value: typeMeta.label),
                _ContextRow(label: '来源', value: _originLabel(note!.origin)),
                _ContextRow(
                  label: '更新时间',
                  value: careerFormatDateTime(note!.updatedAt),
                ),
                _ContextRow(
                  label: '关联项目',
                  value: note!.relatedApplicationId?.trim().isNotEmpty == true
                      ? '已关联'
                      : '未关联',
                  valueColor:
                      note!.relatedApplicationId?.trim().isNotEmpty == true
                          ? ProductColors.primary
                          : ProductColors.textMuted,
                ),
                _ContextRow(
                  label: '标签',
                  customValue: note!.tags.isEmpty
                      ? Text(
                          '暂无标签',
                          style: AppTheme.ts(
                            fontSize: 13,
                            color: ProductColors.textMuted,
                          ),
                        )
                      : Wrap(
                          spacing: 6,
                          runSpacing: 6,
                          children: [
                            for (final tag in note!.tags.take(4))
                              ProductTag(label: tag, tone: typeMeta.tone),
                          ],
                        ),
                ),
                _ContextRow(
                  label: '引用数量',
                  value: '${note!.sourceRefs.length} 个来源引用',
                ),
              ],
            ),
    );
  }
}

class _NoteNextActionsCard extends StatelessWidget {
  final NoteView? note;
  final _NoteTypeMeta typeMeta;
  final VoidCallback onNewNote;
  final VoidCallback? onAppend;
  final VoidCallback? onReviewDraft;
  final VoidCallback? onActionDraft;

  const _NoteNextActionsCard({
    required this.note,
    required this.typeMeta,
    required this.onNewNote,
    required this.onAppend,
    required this.onReviewDraft,
    required this.onActionDraft,
  });

  @override
  Widget build(BuildContext context) {
    return _ContextCard(
      title: '推荐下一步',
      icon: Icons.auto_awesome_rounded,
      tone: ProductTone.primary,
      child: Column(
        children: [
          if (note == null)
            _NoteActionTile(
              title: '新建笔记',
              subtitle: '记录新的想法、面试反馈或资料摘录。',
              icon: Icons.add_rounded,
              tone: ProductTone.primary,
              actionLabel: '新建',
              onTap: onNewNote,
            )
          else ...[
            _NoteActionTile(
              title: _normalizeNoteType(note!.noteType) == 'resource'
                  ? '生成资料摘要'
                  : '整理成复盘草案',
              subtitle: _normalizeNoteType(note!.noteType) == 'resource'
                  ? '把资料沉淀成可复用摘要和面试表达。'
                  : '生成结构化复盘，便于后续回顾。',
              icon: Icons.fact_check_outlined,
              tone: ProductTone.primary,
              actionLabel: '整理',
              onTap: onReviewDraft,
            ),
            const SizedBox(height: 8),
            _NoteActionTile(
              title: '提取行动项',
              subtitle: '从笔记中提炼可执行动作并生成草案。',
              icon: Icons.checklist_rounded,
              tone: ProductTone.info,
              actionLabel: '提取',
              onTap: onActionDraft,
            ),
            const SizedBox(height: 8),
            _NoteActionTile(
              title: '追加记录',
              subtitle: '把新的学习、面试或复盘进展接到当前笔记后面。',
              icon: Icons.add_comment_outlined,
              tone: typeMeta.tone,
              actionLabel: '追加',
              onTap: onAppend,
            ),
          ],
        ],
      ),
    );
  }
}

class _RelatedProjectCard extends StatelessWidget {
  final CareerApplicationView? application;
  final VoidCallback onOpenProjects;

  const _RelatedProjectCard({
    required this.application,
    required this.onOpenProjects,
  });

  @override
  Widget build(BuildContext context) {
    return _ContextCard(
      title: '关联项目',
      icon: Icons.work_outline_rounded,
      tone: ProductTone.info,
      child: _NoteActionTile(
        title: application?.displayTitle ?? '未关联求职项目',
        subtitle: application == null
            ? '关联后，这条笔记会参与复盘、学习建议和简历优化。'
            : careerFirstNonEmpty(
                [
                  application!.summary,
                  '${application!.company} · ${application!.location}',
                ],
                fallback: careerStageLabel(application!.stage),
              ),
        icon: Icons.business_center_outlined,
        tone: ProductTone.info,
        actionLabel: application == null ? '关联' : '查看项目',
        onTap: onOpenProjects,
      ),
    );
  }
}

class _SourceRefsCard extends StatelessWidget {
  final NoteView? note;

  const _SourceRefsCard({required this.note});

  @override
  Widget build(BuildContext context) {
    final sources = note?.sourceRefs ?? const <NoteSourceRefView>[];
    return _ContextCard(
      title: '来源引用',
      icon: Icons.link_rounded,
      tone: ProductTone.neutral,
      subtitle: sources.isEmpty ? '暂无来源引用' : '${sources.length} 个来源',
      child: sources.isEmpty
          ? const _EmptyNoteBox(
              message: '手写笔记可以没有来源。Agent 整理、资料摘录和报告引用会在这里显示来源。',
            )
          : Column(
              children: [
                for (final source in sources.take(5)) ...[
                  _SourceRefRow(source: source),
                  if (source != sources.take(5).last)
                    const Divider(height: 16, color: ProductColors.border),
                ],
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
            tone: ProductTone.primary,
            selected: value.isEmpty,
            onTap: () => onChanged(''),
          ),
          const SizedBox(width: 7),
          for (final option in _noteTypeOptions) ...[
            _NoteFilterChip(
              label: option.shortLabel,
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
          height: 30,
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(
            color: selected ? style.color : ProductColors.surface,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected ? style.color : ProductColors.border,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w900,
                  color: selected ? Colors.white : ProductColors.textSecondary,
                ),
              ),
              const SizedBox(width: 6),
              Text(
                '$count',
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  color: selected ? Colors.white : style.color,
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
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
          decoration: BoxDecoration(
            color: selected
                ? ProductColors.primarySoft.withValues(alpha: 0.58)
                : ProductColors.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: selected ? ProductColors.primary : ProductColors.border,
            ),
            boxShadow: selected
                ? [
                    BoxShadow(
                      color: ProductColors.primary.withValues(alpha: 0.08),
                      blurRadius: 18,
                      offset: const Offset(0, 8),
                    ),
                  ]
                : null,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ProductIconTile(icon: meta.icon, tone: meta.tone, size: 36),
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
                            _safeTitle(note),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 13,
                              fontWeight: FontWeight.w900,
                              color: ProductColors.text,
                            ),
                          ),
                        ),
                        ProductTag(label: meta.shortLabel, tone: meta.tone),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _noteSummary(note),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.5,
                        height: 1.42,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 9),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        ProductTag(
                          label: careerFormatDateTime(note.updatedAt),
                          tone: ProductTone.neutral,
                        ),
                        if (note.relatedApplicationId?.trim().isNotEmpty ==
                            true)
                          const ProductTag(
                            label: '项目',
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

class _NotesSearchField extends StatefulWidget {
  final String value;
  final String hint;
  final bool dense;
  final ValueChanged<String> onChanged;

  const _NotesSearchField({
    required this.value,
    required this.hint,
    required this.onChanged,
    this.dense = false,
  });

  @override
  State<_NotesSearchField> createState() => _NotesSearchFieldState();
}

class _NotesSearchFieldState extends State<_NotesSearchField> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.value);
  }

  @override
  void didUpdateWidget(covariant _NotesSearchField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != _controller.text) {
      _controller.value = TextEditingValue(
        text: widget.value,
        selection: TextSelection.collapsed(offset: widget.value.length),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: widget.dense ? 38 : 42,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: ProductColors.border),
        boxShadow: widget.dense
            ? null
            : [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.04),
                  blurRadius: 16,
                  offset: const Offset(0, 6),
                ),
              ],
      ),
      child: Row(
        children: [
          const Icon(Icons.search_rounded,
              size: 18, color: ProductColors.textMuted),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: _controller,
              onChanged: widget.onChanged,
              decoration: InputDecoration(
                border: InputBorder.none,
                hintText: widget.hint,
                hintStyle: AppTheme.ts(
                  fontSize: 13,
                  color: ProductColors.textMuted,
                ),
              ),
              style: AppTheme.ts(fontSize: 13, color: ProductColors.text),
            ),
          ),
          if (_controller.text.isNotEmpty)
            InkWell(
              borderRadius: BorderRadius.circular(999),
              onTap: () {
                _controller.clear();
                widget.onChanged('');
              },
              child: const Padding(
                padding: EdgeInsets.all(4),
                child: Icon(
                  Icons.close_rounded,
                  size: 16,
                  color: ProductColors.textMuted,
                ),
              ),
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
    return LayoutBuilder(
      builder: (context, constraints) {
        final itemWidth = constraints.maxWidth < 620
            ? constraints.maxWidth
            : (constraints.maxWidth - 20) / 3;
        return Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            for (final option in _noteTypeOptions)
              SizedBox(
                width: itemWidth,
                child: _NoteTypePill(
                  meta: option,
                  selected: option.value == value,
                  onTap: () => onChanged(option.value),
                ),
              ),
          ],
        );
      },
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
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          height: 40,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            color: selected ? style.soft : ProductColors.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: selected
                  ? style.color.withValues(alpha: 0.42)
                  : ProductColors.border,
            ),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(meta.icon, size: 15, color: style.color),
              const SizedBox(width: 7),
              Text(
                meta.shortLabel,
                style: AppTheme.ts(
                  fontSize: 12,
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
            label: '双栏',
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
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
          decoration: BoxDecoration(
            color: selected ? ProductColors.primarySoft : Colors.transparent,
            borderRadius: BorderRadius.circular(999),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                icon,
                size: 14,
                color:
                    selected ? ProductColors.primary : ProductColors.textMuted,
              ),
              const SizedBox(width: 5),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 12,
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
                SizedBox(height: 300, child: editor),
                const SizedBox(height: 10),
                SizedBox(height: 300, child: preview),
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: SizedBox(height: 520, child: editor)),
              const SizedBox(width: 10),
              Expanded(child: SizedBox(height: 520, child: preview)),
            ],
          );
        },
      );
    }
    if (mode == _NoteBodyMode.preview) {
      return SizedBox(
        height: 560,
        child: _MarkdownPreview(content: controller.text),
      );
    }
    return SizedBox(
        height: 560, child: _MarkdownEditor(controller: controller));
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
      decoration: _inputDecoration('记录面试反馈、学习心得、资料摘录或关键想法...'),
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
          ? Center(
              child: Text(
                '暂无内容',
                style: AppTheme.ts(
                  fontSize: 13,
                  color: ProductColors.textMuted,
                ),
              ),
            )
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
                        source.sourceId ?? source.sourceSessionId ?? '',
                      )
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

class _AppendNoteDialog extends StatefulWidget {
  final NoteView note;

  const _AppendNoteDialog({required this.note});

  @override
  State<_AppendNoteDialog> createState() => _AppendNoteDialogState();
}

class _AppendNoteDialogState extends State<_AppendNoteDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 20, 22, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _DialogHeader(
                title: '追加记录',
                subtitle: _safeTitle(widget.note),
                icon: Icons.add_comment_outlined,
                tone: ProductTone.primary,
                onClose: () => Navigator.of(context).pop(),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _controller,
                autofocus: true,
                minLines: 7,
                maxLines: 12,
                decoration: _inputDecoration('写下新的学习、面试或复盘进展...'),
                style: AppTheme.ts(
                  fontSize: 13,
                  height: 1.55,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  _NotesButton(
                    label: '取消',
                    icon: Icons.close_rounded,
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                  const SizedBox(width: 10),
                  _NotesButton(
                    label: '保存追加',
                    icon: Icons.check_rounded,
                    primary: true,
                    onPressed: () =>
                        Navigator.of(context).pop(_controller.text),
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

class _ArchiveNoteDialog extends StatelessWidget {
  final NoteView note;

  const _ArchiveNoteDialog({required this.note});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('归档这条笔记？'),
      content: Text(
        '「${_safeTitle(note)}」归档后默认不会在笔记库中显示。',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('取消'),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: TextButton.styleFrom(foregroundColor: ProductColors.danger),
          child: const Text('归档'),
        ),
      ],
    );
  }
}

class _ReviewDraftDialog extends StatelessWidget {
  final NoteView note;
  final String draft;

  const _ReviewDraftDialog({
    required this.note,
    required this.draft,
  });

  @override
  Widget build(BuildContext context) {
    final sections = _splitMarkdownSections(draft);
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760, maxHeight: 780),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 20, 22, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _DialogHeader(
                title: '整理成复盘草案',
                subtitle: '系统将当前笔记整理为结构化复盘草案，便于后续回顾。',
                icon: Icons.fact_check_outlined,
                tone: ProductTone.primary,
                onClose: () => Navigator.of(context).pop(),
              ),
              const SizedBox(height: 14),
              Flexible(
                child: SingleChildScrollView(
                  child: Column(
                    children: [
                      for (final section in sections)
                        _DraftSection(section: section),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  _NotesButton(
                    label: '取消',
                    icon: Icons.close_rounded,
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                  const SizedBox(width: 10),
                  _NotesButton(
                    label: '追加到当前笔记',
                    icon: Icons.add_rounded,
                    onPressed: () =>
                        Navigator.of(context).pop(_ReviewDraftAction.append),
                  ),
                  const SizedBox(width: 10),
                  _NotesButton(
                    label: '保存为新笔记',
                    icon: Icons.check_rounded,
                    primary: true,
                    onPressed: () =>
                        Navigator.of(context).pop(_ReviewDraftAction.create),
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

class _ActionDraftDialog extends StatefulWidget {
  final NoteView note;
  final List<_ActionDraft> drafts;

  const _ActionDraftDialog({
    required this.note,
    required this.drafts,
  });

  @override
  State<_ActionDraftDialog> createState() => _ActionDraftDialogState();
}

class _ActionDraftDialogState extends State<_ActionDraftDialog> {
  late final Set<int> _learningTaskIndexes;
  late final Set<int> _appendIndexes;
  late final Set<int> _ignoredIndexes;

  @override
  void initState() {
    super.initState();
    _learningTaskIndexes = <int>{};
    _appendIndexes = <int>{};
    _ignoredIndexes = <int>{};
  }

  void _markAsLearningTask(int index) {
    setState(() {
      _learningTaskIndexes.add(index);
      _appendIndexes.remove(index);
      _ignoredIndexes.remove(index);
    });
  }

  void _markAsAppend(int index) {
    setState(() {
      _appendIndexes.add(index);
      _learningTaskIndexes.remove(index);
      _ignoredIndexes.remove(index);
    });
  }

  void _markAsIgnored(int index) {
    setState(() {
      _ignoredIndexes.add(index);
      _learningTaskIndexes.remove(index);
      _appendIndexes.remove(index);
    });
  }

  _ActionDraftResult _currentResult() {
    return _ActionDraftResult(
      learningTasks: [
        for (final index in _learningTaskIndexes) widget.drafts[index],
      ],
      appendToNote: [
        for (final index in _appendIndexes) widget.drafts[index],
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 840, maxHeight: 820),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 20, 22, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _DialogHeader(
                title: '提取行动项',
                subtitle: '系统已从当前笔记中提炼出可执行的下一步，供你选择采纳。',
                icon: Icons.checklist_rounded,
                tone: ProductTone.info,
                onClose: () => Navigator.of(context).pop(),
              ),
              const SizedBox(height: 14),
              Flexible(
                child: SingleChildScrollView(
                  child: Column(
                    children: [
                      for (var i = 0; i < widget.drafts.length; i++) ...[
                        _ActionDraftCard(
                          index: i + 1,
                          draft: widget.drafts[i],
                          action: _learningTaskIndexes.contains(i)
                              ? _ActionDraftChoice.learningTask
                              : _appendIndexes.contains(i)
                                  ? _ActionDraftChoice.appendToNote
                                  : _ignoredIndexes.contains(i)
                                      ? _ActionDraftChoice.ignored
                                      : _ActionDraftChoice.none,
                          onAccept: () => _markAsLearningTask(i),
                          onAppend: () => _markAsAppend(i),
                          onIgnore: () => _markAsIgnored(i),
                        ),
                        if (i != widget.drafts.length - 1)
                          const SizedBox(height: 10),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '可采纳为学习任务，也可以稍后再处理。',
                      style: AppTheme.ts(
                        fontSize: 12,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ),
                  _NotesButton(
                    label: '稍后再看',
                    icon: Icons.close_rounded,
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                  const SizedBox(width: 10),
                  _NotesButton(
                    label: '采纳全部 (${widget.drafts.length})',
                    icon: Icons.check_circle_outline_rounded,
                    primary: true,
                    onPressed: () => Navigator.of(context).pop(
                      _ActionDraftResult(learningTasks: widget.drafts),
                    ),
                  ),
                  if (!_currentResult().isEmpty) ...[
                    const SizedBox(width: 10),
                    _NotesButton(
                      label: '保存选择',
                      icon: Icons.save_alt_rounded,
                      primary: true,
                      onPressed: () =>
                          Navigator.of(context).pop(_currentResult()),
                    ),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ActionDraftCard extends StatelessWidget {
  final int index;
  final _ActionDraft draft;
  final _ActionDraftChoice action;
  final VoidCallback onAccept;
  final VoidCallback onAppend;
  final VoidCallback onIgnore;

  const _ActionDraftCard({
    required this.index,
    required this.draft,
    required this.action,
    required this.onAccept,
    required this.onAppend,
    required this.onIgnore,
  });

  @override
  Widget build(BuildContext context) {
    final isChosen = action != _ActionDraftChoice.none;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 140),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: isChosen
            ? ProductColors.primarySoft.withValues(alpha: 0.42)
            : ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: isChosen ? ProductColors.primary : ProductColors.border,
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 15,
            backgroundColor: ProductColors.primarySoft,
            child: Text(
              '$index',
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: FontWeight.w900,
                color: ProductColors.primary,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  draft.title,
                  style: AppTheme.ts(
                    fontSize: 14,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 7),
                Text(
                  draft.description,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    height: 1.45,
                    color: ProductColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 7,
                  runSpacing: 7,
                  children: [
                    ProductTag(
                      label: '预计 ${draft.estimatedMinutes} 分钟',
                      tone: ProductTone.neutral,
                      icon: Icons.schedule_rounded,
                    ),
                    ProductTag(
                      label: _priorityLabel(draft.priority),
                      tone: draft.priority == 'high'
                          ? ProductTone.warning
                          : ProductTone.info,
                    ),
                    for (final tag in draft.skillTags.take(4))
                      ProductTag(label: tag, tone: ProductTone.purple),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          SizedBox(
            width: 126,
            child: Column(
              children: [
                _DraftMiniButton(
                  label: action == _ActionDraftChoice.learningTask
                      ? '已采纳'
                      : '采纳为任务',
                  icon: Icons.check_circle_outline_rounded,
                  primary: true,
                  onPressed: onAccept,
                ),
                const SizedBox(height: 7),
                _DraftMiniButton(
                  label: action == _ActionDraftChoice.appendToNote
                      ? '已追加'
                      : '追加到笔记',
                  icon: Icons.note_add_outlined,
                  primary: action == _ActionDraftChoice.appendToNote,
                  onPressed: onAppend,
                ),
                const SizedBox(height: 7),
                _DraftMiniButton(
                  label: action == _ActionDraftChoice.ignored ? '已忽略' : '忽略此项',
                  icon: Icons.close_rounded,
                  primary: action == _ActionDraftChoice.ignored,
                  onPressed: onIgnore,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DraftMiniButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool primary;
  final VoidCallback onPressed;

  const _DraftMiniButton({
    required this.label,
    required this.icon,
    required this.primary,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final foreground = primary ? Colors.white : ProductColors.textSecondary;
    return SizedBox(
      width: double.infinity,
      height: 34,
      child: OutlinedButton.icon(
        onPressed: onPressed,
        icon: Icon(icon, size: 15),
        label: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
        style: OutlinedButton.styleFrom(
          backgroundColor:
              primary ? ProductColors.primary : ProductColors.surface,
          foregroundColor: foreground,
          side: BorderSide(
            color: primary ? ProductColors.primary : ProductColors.border,
          ),
          padding: const EdgeInsets.symmetric(horizontal: 8),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
          textStyle: AppTheme.ts(fontSize: 11.5, fontWeight: FontWeight.w900),
        ),
      ),
    );
  }
}

class _DraftSection extends StatelessWidget {
  final _MarkdownSection section;

  const _DraftSection({required this.section});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(14, 13, 14, 13),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ProductIconTile(
            icon: section.icon,
            tone: section.tone,
            size: 36,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  section.title,
                  style: AppTheme.ts(
                    fontSize: 14,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  section.body,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    height: 1.52,
                    color: ProductColors.textSecondary,
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

class _DialogHeader extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final ProductTone tone;
  final VoidCallback onClose;

  const _DialogHeader({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.tone,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ProductIconTile(icon: icon, tone: tone, size: 40),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              if (subtitle.trim().isNotEmpty) ...[
                const SizedBox(height: 5),
                Text(
                  subtitle,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    height: 1.45,
                    color: ProductColors.textSecondary,
                  ),
                ),
              ],
            ],
          ),
        ),
        IconButton(
          tooltip: '关闭',
          onPressed: onClose,
          icon: const Icon(Icons.close_rounded),
          color: ProductColors.textSecondary,
        ),
      ],
    );
  }
}

class _ContextCard extends StatelessWidget {
  final String title;
  final String? subtitle;
  final IconData icon;
  final ProductTone tone;
  final Widget child;
  final Widget? trailing;

  const _ContextCard({
    required this.title,
    required this.icon,
    required this.child,
    this.subtitle,
    this.tone = ProductTone.primary,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return _NotesPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ProductIconTile(icon: icon, tone: tone, size: 36),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: AppTheme.ts(
                        fontSize: 15,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    if (subtitle?.trim().isNotEmpty == true) ...[
                      const SizedBox(height: 2),
                      Text(
                        subtitle!.trim(),
                        style: AppTheme.ts(
                          fontSize: 11,
                          color: ProductColors.textMuted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (trailing != null) trailing!,
            ],
          ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

class _ContextRow extends StatelessWidget {
  final String label;
  final String? value;
  final Widget? customValue;
  final Color? valueColor;

  const _ContextRow({
    required this.label,
    this.value,
    this.customValue,
    this.valueColor,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: AppTheme.ts(
                fontSize: 12,
                color: ProductColors.textMuted,
              ),
            ),
          ),
          Expanded(
            child: customValue ??
                Text(
                  value ?? '-',
                  style: AppTheme.ts(
                    fontSize: 13,
                    height: 1.35,
                    fontWeight: FontWeight.w800,
                    color: valueColor ?? ProductColors.text,
                  ),
                ),
          ),
        ],
      ),
    );
  }
}

class _NoteActionTile extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final ProductTone tone;
  final String actionLabel;
  final VoidCallback? onTap;

  const _NoteActionTile({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.tone,
    required this.actionLabel,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
          decoration: BoxDecoration(
            color: ProductColors.surfaceSoft,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: ProductColors.border),
          ),
          child: Row(
            children: [
              ProductIconTile(icon: icon, tone: tone, size: 34),
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
                        fontSize: 11,
                        height: 1.35,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Text(
                actionLabel,
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w900,
                  color: style.color,
                ),
              ),
              const SizedBox(width: 4),
              Icon(Icons.chevron_right_rounded, size: 17, color: style.color),
            ],
          ),
        ),
      ),
    );
  }
}

class _PanelHeader extends StatelessWidget {
  final IconData icon;
  final ProductTone tone;
  final String title;
  final String subtitle;
  final Widget? trailing;

  const _PanelHeader({
    required this.icon,
    required this.tone,
    required this.title,
    required this.subtitle,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ProductIconTile(icon: icon, tone: tone, size: 36),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: AppTheme.ts(
                  fontSize: 12,
                  color: ProductColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
        if (trailing != null) trailing!,
      ],
    );
  }
}

class _NotesPanel extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;

  const _NotesPanel({
    required this.child,
    this.padding = const EdgeInsets.all(16),
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: ProductSurface.card(radius: 18),
      child: child,
    );
  }
}

class _NoteMetricData {
  final String label;
  final String value;
  final String caption;
  final IconData icon;
  final ProductTone tone;
  final bool active;
  final VoidCallback onTap;

  const _NoteMetricData({
    required this.label,
    required this.value,
    required this.caption,
    required this.icon,
    required this.tone,
    required this.active,
    required this.onTap,
  });
}

class _NoteMetricCard extends StatelessWidget {
  final _NoteMetricData metric;

  const _NoteMetricCard({required this.metric});

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(metric.tone);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: metric.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          height: 92,
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          decoration: BoxDecoration(
            color: metric.active
                ? style.soft.withValues(alpha: 0.64)
                : ProductColors.surface,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: metric.active
                  ? style.color.withValues(alpha: 0.24)
                  : ProductColors.border,
            ),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.04),
                blurRadius: 16,
                offset: const Offset(0, 6),
              ),
            ],
          ),
          child: Row(
            children: [
              ProductIconTile(icon: metric.icon, tone: metric.tone, size: 42),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      metric.value,
                      style: AppTheme.ts(
                        fontSize: 23,
                        height: 1,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      metric.label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      metric.caption,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.8,
                        color: ProductColors.textMuted,
                      ),
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

class _NotesButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool primary;
  final bool danger;
  final VoidCallback? onPressed;

  const _NotesButton({
    super.key,
    required this.label,
    required this.icon,
    required this.onPressed,
    this.primary = false,
    this.danger = false,
  });

  @override
  Widget build(BuildContext context) {
    if (primary) {
      return SizedBox(
        height: 38,
        child: ElevatedButton.icon(
          onPressed: onPressed,
          icon: Icon(icon, size: 16),
          label: Text(label),
          style: ElevatedButton.styleFrom(
            backgroundColor: ProductColors.primary,
            foregroundColor: Colors.white,
            disabledBackgroundColor: ProductColors.border,
            disabledForegroundColor: ProductColors.textMuted,
            elevation: 0,
            padding: const EdgeInsets.symmetric(horizontal: 15),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
            textStyle: AppTheme.ts(fontSize: 12.5, fontWeight: FontWeight.w900),
          ),
        ),
      );
    }
    return SizedBox(
      height: 38,
      child: OutlinedButton.icon(
        onPressed: onPressed,
        icon: Icon(icon, size: 16),
        label: Text(label),
        style: OutlinedButton.styleFrom(
          foregroundColor:
              danger ? ProductColors.danger : ProductColors.primary,
          disabledForegroundColor: ProductColors.textMuted,
          side: BorderSide(
            color: danger
                ? ProductColors.danger.withValues(alpha: 0.32)
                : ProductColors.borderStrong,
          ),
          padding: const EdgeInsets.symmetric(horizontal: 13),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: AppTheme.ts(fontSize: 12.5, fontWeight: FontWeight.w900),
        ),
      ),
    );
  }
}

class _IconPillButton extends StatelessWidget {
  final String tooltip;
  final IconData icon;
  final String label;
  final VoidCallback? onTap;

  const _IconPillButton({
    super.key,
    required this.tooltip,
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Container(
          height: 34,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            color: ProductColors.primarySoft,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: ProductColors.primary.withValues(alpha: 0.16),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: ProductColors.primary),
              const SizedBox(width: 6),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.primary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NotesEmptyState extends StatelessWidget {
  final String title;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  const _NotesEmptyState({
    required this.title,
    required this.message,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 18),
      decoration: ProductSurface.softCard(tone: ProductTone.neutral),
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
          const SizedBox(height: 6),
          Text(
            message,
            style: AppTheme.ts(
              fontSize: 12,
              height: 1.45,
              color: ProductColors.textSecondary,
            ),
          ),
          if (actionLabel != null && onAction != null) ...[
            const SizedBox(height: 12),
            _NotesButton(
              label: actionLabel!,
              icon: Icons.add_rounded,
              primary: true,
              onPressed: onAction,
            ),
          ],
        ],
      ),
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

class _ActionDraft {
  final String title;
  final String description;
  final String priority;
  final int estimatedMinutes;
  final List<String> skillTags;
  final List<String> successCriteria;

  const _ActionDraft({
    required this.title,
    required this.description,
    required this.priority,
    required this.estimatedMinutes,
    required this.skillTags,
    required this.successCriteria,
  });
}

class _ActionDraftResult {
  final List<_ActionDraft> learningTasks;
  final List<_ActionDraft> appendToNote;

  const _ActionDraftResult({
    this.learningTasks = const [],
    this.appendToNote = const [],
  });

  bool get isEmpty => learningTasks.isEmpty && appendToNote.isEmpty;
}

enum _ActionDraftChoice { none, learningTask, appendToNote, ignored }

class _NoteTypeMeta {
  final String value;
  final String label;
  final String shortLabel;
  final String hint;
  final IconData icon;
  final ProductTone tone;

  const _NoteTypeMeta({
    required this.value,
    required this.label,
    required this.shortLabel,
    required this.hint,
    required this.icon,
    required this.tone,
  });
}

const _noteTypeOptions = <_NoteTypeMeta>[
  _NoteTypeMeta(
    value: 'note',
    label: '随记与记录',
    shortLabel: '随记',
    hint: '适合想法、总结、过程记录和杂项内容，后续作为个人上下文参考。',
    icon: Icons.edit_note_outlined,
    tone: ProductTone.warning,
  ),
  _NoteTypeMeta(
    value: 'learning',
    label: '学习笔记',
    shortLabel: '学习',
    hint: '适合知识点、学习计划和短板复盘，后续学习建议会优先参考。',
    icon: Icons.school_outlined,
    tone: ProductTone.purple,
  ),
  _NoteTypeMeta(
    value: 'resource',
    label: '资料摘记',
    shortLabel: '资料',
    hint: '适合面经、文章、链接或资产摘录，后续检索时作为参考材料。',
    icon: Icons.bookmark_border_rounded,
    tone: ProductTone.info,
  ),
];

enum _NoteBodyMode { edit, live, preview }

enum _ReviewDraftAction { append, create }

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

String _safeTitle(NoteView note) {
  return note.title.trim().isEmpty ? '未命名笔记' : note.title.trim();
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
  if (text.length <= 108) return text;
  return '${text.substring(0, 108)}...';
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
    'artifact' => '资料文件',
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

String _appendBlock(String content) {
  final now = DateTime.now();
  final date =
      '${now.year.toString().padLeft(4, '0')}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
  return '## $date 追加记录\n\n$content';
}

String _actionDraftsMarkdown(List<_ActionDraft> drafts) {
  final buffer = StringBuffer()
    ..writeln('### 行动项整理')
    ..writeln();
  for (var i = 0; i < drafts.length; i++) {
    final draft = drafts[i];
    buffer
      ..writeln('${i + 1}. **${draft.title}**')
      ..writeln('   - 为什么要做：${draft.description}')
      ..writeln('   - 优先级：${_priorityLabel(draft.priority)}')
      ..writeln('   - 预计耗时：${draft.estimatedMinutes} 分钟')
      ..writeln('   - 技能标签：${draft.skillTags.join(' / ')}')
      ..writeln('   - 完成标准：${draft.successCriteria.join('；')}')
      ..writeln();
  }
  return buffer.toString().trim();
}

List<Map<String, dynamic>> _sourceRefsPayload(List<NoteSourceRefView> refs) {
  return [
    for (final source in refs)
      {
        'source_type': source.sourceType,
        if (source.sourceId != null) 'source_id': source.sourceId,
        if (source.sourceSessionId != null)
          'source_session_id': source.sourceSessionId,
        'title': source.title,
        'quote': source.quote,
      },
  ];
}

String _buildReviewDraft(NoteView note, CareerApplicationView? app) {
  final title = _safeTitle(note);
  final project = app?.displayTitle ?? '当前求职项目';
  final summary = _noteSummary(note);
  final body = _plainSnippet(note.bodyMarkdown);
  return '''
## 面试背景

$project 相关笔记：「$title」。$summary

## 被问到的问题

- ${body.isEmpty ? '根据当前笔记补充面试问题。' : body}
- 围绕岗位要求、项目经验、系统设计和工程化能力继续补充。

## 回答表现

- 已经沉淀了关键上下文，后续可以继续补充具体回答和证据。
- 建议把回答整理成 STAR 结构，补齐量化结果和技术取舍。

## 暴露短板

- 需要把笔记中的泛化描述落到具体项目证据。
- 需要补充技术细节、边界条件、失败处理和复盘结果。

## 后续行动

- 将薄弱点拆成学习任务。
- 将可复用回答追加到面试准备笔记。
- 将关键证据同步到简历优化材料。

## 可转学习任务

- 针对「$title」整理 1-2 个可验证的练习任务。
''';
}

List<_ActionDraft> _buildActionDrafts(NoteView note) {
  final tags = note.tags.isEmpty ? ['复盘'] : note.tags.take(4).toList();
  final title = _safeTitle(note);
  return [
    _ActionDraft(
      title: '整理 ${_shortTitle(title)} 知识总结',
      description: '把当前笔记中的关键知识、经验和问题整理成结构化总结，方便后续复盘和检索。',
      priority: 'high',
      estimatedMinutes: 90,
      skillTags: tags,
      successCriteria: const ['输出一份结构化总结', '列出至少 3 条可复用表达', '标注后续待补充问题'],
    ),
    _ActionDraft(
      title: '补齐面试表达证据',
      description: '围绕当前笔记中的项目或面试问题补充量化结果、技术取舍和个人贡献。',
      priority: 'high',
      estimatedMinutes: 60,
      skillTags: {...tags, '面试表达'}.take(5).toList(),
      successCriteria: const ['补齐一段 STAR 表达', '包含技术难点和结果', '可以直接用于面试回答'],
    ),
    _ActionDraft(
      title: '拆解关联学习任务',
      description: '将笔记中提到的薄弱点拆成可执行学习任务，形成今天可以推进的练习。',
      priority: 'medium',
      estimatedMinutes: 45,
      skillTags: {...tags, '学习任务'}.take(5).toList(),
      successCriteria: const ['形成一条可执行任务', '包含预计耗时', '定义完成标准'],
    ),
    _ActionDraft(
      title: '沉淀可复用模板',
      description: '把当前笔记整理成后续可复用的问答、复盘或资料模板，减少重复整理成本。',
      priority: 'medium',
      estimatedMinutes: 30,
      skillTags: {...tags, '模板'}.take(5).toList(),
      successCriteria: const ['输出模板结构', '补充使用场景', '记录示例内容'],
    ),
  ];
}

String _shortTitle(String value) {
  final normalized = value.trim();
  if (normalized.length <= 16) return normalized;
  return '${normalized.substring(0, 16)}...';
}

String _priorityLabel(String value) {
  return switch (value.trim()) {
    'high' => '高优先级',
    'low' => '低优先级',
    _ => '中优先级',
  };
}

List<_MarkdownSection> _splitMarkdownSections(String markdown) {
  final lines = markdown.split('\n');
  final sections = <_MarkdownSection>[];
  String? title;
  final buffer = <String>[];
  void flush() {
    final sectionTitle = title;
    if (sectionTitle == null) return;
    sections.add(
      _MarkdownSection(
        title: sectionTitle,
        body: buffer.join('\n').trim(),
        icon: _sectionIcon(sectionTitle),
        tone: _sectionTone(sectionTitle),
      ),
    );
    buffer.clear();
  }

  for (final line in lines) {
    if (line.startsWith('## ')) {
      flush();
      title = line.replaceFirst('## ', '').trim();
    } else if (title != null) {
      buffer.add(line);
    }
  }
  flush();
  if (sections.isEmpty) {
    sections.add(
      _MarkdownSection(
        title: '草案内容',
        body: markdown.trim(),
        icon: Icons.description_outlined,
        tone: ProductTone.primary,
      ),
    );
  }
  return sections;
}

IconData _sectionIcon(String title) {
  if (title.contains('背景')) return Icons.calendar_month_outlined;
  if (title.contains('问题')) return Icons.help_outline_rounded;
  if (title.contains('表现')) return Icons.verified_outlined;
  if (title.contains('短板')) return Icons.warning_amber_rounded;
  if (title.contains('行动')) return Icons.flag_outlined;
  if (title.contains('学习')) return Icons.school_outlined;
  return Icons.description_outlined;
}

ProductTone _sectionTone(String title) {
  if (title.contains('背景')) return ProductTone.primary;
  if (title.contains('问题')) return ProductTone.info;
  if (title.contains('表现')) return ProductTone.purple;
  if (title.contains('短板')) return ProductTone.warning;
  if (title.contains('行动')) return ProductTone.primary;
  if (title.contains('学习')) return ProductTone.info;
  return ProductTone.neutral;
}

class _MarkdownSection {
  final String title;
  final String body;
  final IconData icon;
  final ProductTone tone;

  const _MarkdownSection({
    required this.title,
    required this.body,
    required this.icon,
    required this.tone,
  });
}

TextStyle _fieldLabelStyle() {
  return AppTheme.ts(
    fontSize: 12,
    fontWeight: FontWeight.w900,
    color: ProductColors.text,
  );
}

InputDecoration _inputDecoration(String label) {
  return InputDecoration(
    hintText: label,
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
      borderSide: const BorderSide(color: ProductColors.primary, width: 1.2),
    ),
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
  );
}
