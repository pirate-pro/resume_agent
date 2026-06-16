import 'package:flutter/material.dart';

import '../../core/models/api_models.dart';
import '../theme/app_theme.dart';

class WorkflowInterruptPanel extends StatelessWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic> payload) onSubmit;

  const WorkflowInterruptPanel({
    super.key,
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  Widget build(BuildContext context) {
    return switch (interrupt.type) {
      "source_selection" => _SourceSelectionForm(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
      "note_review" => _NoteReviewForm(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
      "interview_review_scope" => _InterviewScopeForm(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
      "interview_review_confirmation" => _InterviewConfirmationForm(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
      "career_input_confirmation" => _CareerInputConfirmationForm(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
      "workflow_task_retry" => _TaskRetryForm(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
      "career_project_confirmation" => _CareerProjectConfirmationForm(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
      "workflow_write_retry" => _WriteRetryForm(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
      _ => _UnknownInterrupt(
          interrupt: interrupt,
          isSubmitting: isSubmitting,
          onSubmit: onSubmit,
        ),
    };
  }
}

class _CareerInputConfirmationForm extends StatefulWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _CareerInputConfirmationForm({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  State<_CareerInputConfirmationForm> createState() =>
      _CareerInputConfirmationFormState();
}

class _CareerInputConfirmationFormState
    extends State<_CareerInputConfirmationForm> {
  String? _resumeArtifactId;
  String? _jdArtifactId;

  List<Map<String, dynamic>> get _candidates =>
      _mapList(widget.interrupt.payload["candidates"]);

  @override
  void initState() {
    super.initState();
    _resumeArtifactId =
        _initialArtifactId("resume_artifact_id", roleHint: "resume");
    _jdArtifactId = _initialArtifactId("jd_artifact_id", roleHint: "jd");
  }

  String? _initialArtifactId(String key, {required String roleHint}) {
    final configured = widget.interrupt.payload[key]?.toString().trim() ?? "";
    if (configured.isNotEmpty) return configured;
    for (final candidate in _candidates) {
      if (candidate["role_hint"] == roleHint) {
        return candidate["artifact_id"]?.toString();
      }
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final canContinue = _resumeArtifactId != null &&
        _jdArtifactId != null &&
        _resumeArtifactId != _jdArtifactId;
    return _PanelShell(
      title: "确认分析资料",
      question: widget.interrupt.question,
      isSubmitting: widget.isSubmitting,
      child: Column(
        children: [
          DropdownButtonFormField<String>(
            key: const Key("workflow-resume-artifact"),
            initialValue: _resumeArtifactId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: "简历"),
            items: _artifactItems(),
            onChanged: widget.isSubmitting
                ? null
                : (value) => setState(() => _resumeArtifactId = value),
          ),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            key: const Key("workflow-jd-artifact"),
            initialValue: _jdArtifactId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: "目标岗位 JD"),
            items: _artifactItems(),
            onChanged: widget.isSubmitting
                ? null
                : (value) => setState(() => _jdArtifactId = value),
          ),
          if (_resumeArtifactId == _jdArtifactId &&
              _resumeArtifactId != null) ...[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                "简历和 JD 不能选择同一份资料。",
                style: AppTheme.ts(fontSize: 12, color: AppTheme.danger),
              ),
            ),
          ],
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.icon(
              key: const Key("workflow-continue"),
              onPressed: widget.isSubmitting || !canContinue
                  ? null
                  : () => widget.onSubmit({
                        "resume_artifact_id": _resumeArtifactId,
                        "jd_artifact_id": _jdArtifactId,
                      }),
              icon: const Icon(Icons.play_arrow_rounded, size: 18),
              label: const Text("开始分析"),
            ),
          ),
        ],
      ),
    );
  }

  List<DropdownMenuItem<String>> _artifactItems() {
    return [
      for (final candidate in _candidates)
        DropdownMenuItem(
          value: candidate["artifact_id"]?.toString(),
          child: Text(
            _candidateTitle(candidate),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ),
    ];
  }
}

class _TaskRetryForm extends StatelessWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _TaskRetryForm({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  Widget build(BuildContext context) {
    final failedTasks = _mapList(interrupt.payload["failed_tasks"]);
    final completedTasks = (interrupt.payload["completed_tasks"] as List?)
            ?.map((item) => item.toString())
            .toList() ??
        const <String>[];
    return _PanelShell(
      title: "分析步骤需要重试",
      question: interrupt.question,
      isSubmitting: isSubmitting,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final task in failedTasks)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    Icons.error_outline_rounded,
                    size: 18,
                    color: AppTheme.danger,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          (task["title"] ?? "分析步骤").toString(),
                          style: AppTheme.ts(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: AppTheme.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          (task["error"] ?? "执行失败").toString(),
                          style: AppTheme.ts(
                            fontSize: 12,
                            color: AppTheme.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Text(
                    "第 ${task["attempt"] ?? 1} 次",
                    style: AppTheme.ts(
                      fontSize: 11,
                      color: AppTheme.textTertiary,
                    ),
                  ),
                ],
              ),
            ),
          if (completedTasks.isNotEmpty)
            Text(
              "已完成步骤会保留，本次不会重复执行。",
              style: AppTheme.ts(
                fontSize: 12,
                color: AppTheme.textSecondary,
              ),
            ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                key: const Key("workflow-cancel"),
                onPressed:
                    isSubmitting ? null : () => onSubmit({"action": "cancel"}),
                child: const Text("停止流程"),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                key: const Key("workflow-retry-failed"),
                onPressed: isSubmitting
                    ? null
                    : () => onSubmit({"action": "retry_failed"}),
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: const Text("只重试失败步骤"),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CareerProjectConfirmationForm extends StatefulWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _CareerProjectConfirmationForm({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  State<_CareerProjectConfirmationForm> createState() =>
      _CareerProjectConfirmationFormState();
}

class _CareerProjectConfirmationFormState
    extends State<_CareerProjectConfirmationForm> {
  late final TextEditingController _company;
  late final TextEditingController _position;
  late final TextEditingController _location;
  late final TextEditingController _summary;
  late String _stage;
  late String _priority;

  Map<String, dynamic> get _preview =>
      _map(widget.interrupt.payload["project_preview"]);

  @override
  void initState() {
    super.initState();
    _company =
        TextEditingController(text: (_preview["company"] ?? "").toString());
    _position =
        TextEditingController(text: (_preview["position"] ?? "").toString());
    _location =
        TextEditingController(text: (_preview["location"] ?? "").toString());
    _summary =
        TextEditingController(text: (_preview["summary"] ?? "").toString());
    _stage = (_preview["stage"] ?? "draft").toString();
    _priority = (_preview["priority"] ?? "medium").toString();
  }

  @override
  void dispose() {
    _company.dispose();
    _position.dispose();
    _location.dispose();
    _summary.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _PanelShell(
      title: "确认创建求职项目",
      question: widget.interrupt.question,
      isSubmitting: widget.isSubmitting,
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  key: const Key("workflow-project-company"),
                  controller: _company,
                  enabled: !widget.isSubmitting,
                  decoration: const InputDecoration(labelText: "公司"),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: TextField(
                  key: const Key("workflow-project-position"),
                  controller: _position,
                  enabled: !widget.isSubmitting,
                  decoration: const InputDecoration(labelText: "岗位"),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            key: const Key("workflow-project-location"),
            controller: _location,
            enabled: !widget.isSubmitting,
            decoration: const InputDecoration(labelText: "地点"),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  key: const Key("workflow-project-stage"),
                  initialValue: _stage,
                  decoration: const InputDecoration(labelText: "阶段"),
                  items: const [
                    DropdownMenuItem(value: "draft", child: Text("草稿")),
                    DropdownMenuItem(value: "analyzing", child: Text("分析中")),
                    DropdownMenuItem(
                        value: "ready_to_apply", child: Text("待投递")),
                  ],
                  onChanged: widget.isSubmitting
                      ? null
                      : (value) => setState(() => _stage = value ?? "draft"),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: DropdownButtonFormField<String>(
                  key: const Key("workflow-project-priority"),
                  initialValue: _priority,
                  decoration: const InputDecoration(labelText: "优先级"),
                  items: const [
                    DropdownMenuItem(value: "high", child: Text("高")),
                    DropdownMenuItem(value: "medium", child: Text("中")),
                    DropdownMenuItem(value: "low", child: Text("低")),
                  ],
                  onChanged: widget.isSubmitting
                      ? null
                      : (value) =>
                          setState(() => _priority = value ?? "medium"),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            key: const Key("workflow-project-summary"),
            controller: _summary,
            enabled: !widget.isSubmitting,
            minLines: 2,
            maxLines: 4,
            decoration: const InputDecoration(labelText: "项目摘要"),
          ),
          const SizedBox(height: 12),
          _ReviewActions(
            isSubmitting: widget.isSubmitting,
            onCancel: () => widget.onSubmit({"action": "cancel"}),
            onApprove: () => widget.onSubmit({
              "action": "edit_project_fields",
              "edited_project_fields": {
                "company": _company.text.trim(),
                "position": _position.text.trim(),
                "location": _location.text.trim(),
                "stage": _stage,
                "priority": _priority,
                "summary": _summary.text.trim(),
              },
            }),
          ),
        ],
      ),
    );
  }
}

class _WriteRetryForm extends StatelessWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _WriteRetryForm({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  Widget build(BuildContext context) {
    final error = (interrupt.payload["error"] ?? "未知写入错误").toString();
    final retryCount = interrupt.payload["retry_count"] ?? 1;
    final operationLabel =
        (interrupt.payload["operation_label"] ?? "保存").toString();
    return _PanelShell(
      title: "$operationLabel失败",
      question: interrupt.question,
      isSubmitting: isSubmitting,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppTheme.danger.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: AppTheme.danger.withValues(alpha: 0.2),
              ),
            ),
            child: Text(
              "$error\n\n已尝试 $retryCount 轮。重试只会重新执行“$operationLabel”步骤。",
              style: AppTheme.ts(
                fontSize: 13,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                key: const Key("workflow-cancel"),
                onPressed:
                    isSubmitting ? null : () => onSubmit({"action": "cancel"}),
                child: const Text("取消"),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                key: const Key("workflow-retry"),
                onPressed:
                    isSubmitting ? null : () => onSubmit({"action": "retry"}),
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: Text("重试$operationLabel"),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PanelShell extends StatelessWidget {
  final String title;
  final String question;
  final bool isSubmitting;
  final Widget child;

  const _PanelShell({
    required this.title,
    required this.question,
    required this.isSubmitting,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key("workflow-interrupt-panel"),
      width: double.infinity,
      constraints: const BoxConstraints(maxHeight: 420),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        border: Border(top: BorderSide(color: AppTheme.border)),
      ),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 16, 24, 14),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 860),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      Icons.account_tree_outlined,
                      size: 18,
                      color: AppTheme.accent,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        title,
                        style: AppTheme.ts(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                Text(
                  question,
                  style: AppTheme.ts(
                    fontSize: 13,
                    color: AppTheme.textSecondary,
                  ),
                ),
                if (isSubmitting) ...[
                  const SizedBox(height: 12),
                  const _SubmittingNotice(),
                ],
                const SizedBox(height: 14),
                child,
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SubmittingNotice extends StatelessWidget {
  const _SubmittingNotice();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key("workflow-submitting-notice"),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.surfaceActive,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppTheme.borderLight),
      ),
      child: Row(
        children: [
          SizedBox.square(
            dimension: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: AppTheme.accent,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              "流程正在执行，当前确认项会在执行完成后自动更新。",
              style: AppTheme.ts(
                fontSize: 12,
                color: AppTheme.textPrimary,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SourceSelectionForm extends StatefulWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _SourceSelectionForm({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  State<_SourceSelectionForm> createState() => _SourceSelectionFormState();
}

class _SourceSelectionFormState extends State<_SourceSelectionForm> {
  final _supplement = TextEditingController();
  final Set<int> _selected = {};

  List<Map<String, dynamic>> get _candidates =>
      _mapList(widget.interrupt.payload["candidates"]);

  @override
  void initState() {
    super.initState();
    for (var i = 0; i < _candidates.length && i < 3; i++) {
      _selected.add(i);
    }
  }

  @override
  void dispose() {
    _supplement.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _PanelShell(
      title: "选择笔记依据",
      question: widget.interrupt.question,
      isSubmitting: widget.isSubmitting,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < _candidates.length; i++)
            CheckboxListTile(
              key: Key("workflow-source-$i"),
              dense: true,
              contentPadding: EdgeInsets.zero,
              value: _selected.contains(i),
              title: Text(_candidateTitle(_candidates[i])),
              subtitle: _candidateSubtitle(_candidates[i]),
              controlAffinity: ListTileControlAffinity.leading,
              onChanged: widget.isSubmitting
                  ? null
                  : (selected) => setState(() {
                        if (selected == true) {
                          _selected.add(i);
                        } else {
                          _selected.remove(i);
                        }
                      }),
            ),
          TextField(
            key: const Key("workflow-user-supplement"),
            controller: _supplement,
            enabled: !widget.isSubmitting,
            onChanged: (_) => setState(() {}),
            minLines: 1,
            maxLines: 3,
            decoration: const InputDecoration(
              labelText: "补充内容",
              hintText: "可补充重点、背景或必须包含的信息",
            ),
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.icon(
              key: const Key("workflow-continue"),
              onPressed: widget.isSubmitting ||
                      (_selected.isEmpty && _supplement.text.trim().isEmpty)
                  ? null
                  : () => widget.onSubmit({
                        "selected_source_refs": [
                          for (final index in _selected)
                            _candidates[index]["source_ref"] ??
                                _candidates[index],
                        ],
                        if (_supplement.text.trim().isNotEmpty)
                          "user_supplement": _supplement.text.trim(),
                      }),
              icon: widget.isSubmitting
                  ? const SizedBox.square(
                      dimension: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.arrow_forward_rounded, size: 18),
              label: const Text("继续生成"),
            ),
          ),
        ],
      ),
    );
  }
}

class _NoteReviewForm extends StatefulWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _NoteReviewForm({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  State<_NoteReviewForm> createState() => _NoteReviewFormState();
}

class _NoteReviewFormState extends State<_NoteReviewForm> {
  late final TextEditingController _title;
  late final TextEditingController _body;
  late final TextEditingController _summary;

  Map<String, dynamic> get _draft => _map(widget.interrupt.payload["draft"]);

  @override
  void initState() {
    super.initState();
    _title = TextEditingController(text: (_draft["title"] ?? "").toString());
    _body =
        TextEditingController(text: (_draft["body_markdown"] ?? "").toString());
    _summary =
        TextEditingController(text: (_draft["summary"] ?? "").toString());
  }

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    _summary.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _PanelShell(
      title: "确认笔记草稿",
      question: widget.interrupt.question,
      isSubmitting: widget.isSubmitting,
      child: Column(
        children: [
          TextField(
            key: const Key("workflow-note-title"),
            controller: _title,
            enabled: !widget.isSubmitting,
            decoration: const InputDecoration(labelText: "标题"),
          ),
          const SizedBox(height: 10),
          TextField(
            key: const Key("workflow-note-body"),
            controller: _body,
            enabled: !widget.isSubmitting,
            minLines: 4,
            maxLines: 9,
            decoration: const InputDecoration(labelText: "正文"),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _summary,
            enabled: !widget.isSubmitting,
            minLines: 1,
            maxLines: 2,
            decoration: const InputDecoration(labelText: "摘要"),
          ),
          const SizedBox(height: 12),
          _ReviewActions(
            isSubmitting: widget.isSubmitting,
            onCancel: () => widget.onSubmit({"action": "cancel"}),
            onApprove: () {
              final edited = Map<String, dynamic>.from(_draft)
                ..["title"] = _title.text.trim()
                ..["body_markdown"] = _body.text.trim()
                ..["summary"] = _summary.text.trim();
              return widget.onSubmit({
                "action": "edit",
                "edited_draft": edited,
              });
            },
          ),
        ],
      ),
    );
  }
}

class _InterviewScopeForm extends StatefulWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _InterviewScopeForm({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  State<_InterviewScopeForm> createState() => _InterviewScopeFormState();
}

class _InterviewScopeFormState extends State<_InterviewScopeForm> {
  final _supplement = TextEditingController();
  String? _applicationId;
  bool _saveNote = true;
  bool _updateApplication = true;

  List<Map<String, dynamic>> get _applications =>
      _mapList(widget.interrupt.payload["application_candidates"]);

  @override
  void initState() {
    super.initState();
    if (_applications.isNotEmpty) {
      _applicationId = (_applications.first["application_id"] ?? "").toString();
    }
  }

  @override
  void dispose() {
    _supplement.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _PanelShell(
      title: "确认面试复盘范围",
      question: widget.interrupt.question,
      isSubmitting: widget.isSubmitting,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          DropdownButtonFormField<String>(
            key: const Key("workflow-application-select"),
            initialValue: _applicationId,
            decoration: const InputDecoration(labelText: "关联求职项目"),
            items: [
              for (final item in _applications)
                DropdownMenuItem(
                  value: (item["application_id"] ?? "").toString(),
                  child: Text(_candidateTitle(item)),
                ),
            ],
            onChanged: widget.isSubmitting
                ? null
                : (value) => setState(() => _applicationId = value),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text("保存复盘笔记"),
            value: _saveNote,
            onChanged: widget.isSubmitting
                ? null
                : (value) => setState(() {
                      _saveNote = value;
                      if (!value) _updateApplication = false;
                    }),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text("更新求职项目"),
            value: _updateApplication,
            onChanged: widget.isSubmitting || !_saveNote
                ? null
                : (value) => setState(() => _updateApplication = value),
          ),
          TextField(
            key: const Key("workflow-review-supplement"),
            controller: _supplement,
            enabled: !widget.isSubmitting,
            minLines: 1,
            maxLines: 3,
            decoration: const InputDecoration(labelText: "本次面试补充"),
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.icon(
              key: const Key("workflow-continue"),
              onPressed: widget.isSubmitting ||
                      (_updateApplication &&
                          (_applicationId == null || _applicationId!.isEmpty))
                  ? null
                  : () => widget.onSubmit({
                        "selected_application_id": _applicationId,
                        "save_note": _saveNote,
                        "update_application": _updateApplication,
                        "update_fields": const [
                          "stage",
                          "risks",
                          "next_actions",
                          "notes",
                        ],
                        if (_supplement.text.trim().isNotEmpty)
                          "user_supplement": _supplement.text.trim(),
                      }),
              icon: const Icon(Icons.arrow_forward_rounded, size: 18),
              label: const Text("生成复盘草稿"),
            ),
          ),
        ],
      ),
    );
  }
}

class _InterviewConfirmationForm extends StatefulWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _InterviewConfirmationForm({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  State<_InterviewConfirmationForm> createState() =>
      _InterviewConfirmationFormState();
}

class _InterviewConfirmationFormState
    extends State<_InterviewConfirmationForm> {
  late final TextEditingController _title;
  late final TextEditingController _body;
  late final TextEditingController _projectNotes;

  Map<String, dynamic> get _note =>
      _map(widget.interrupt.payload["note_draft"]);
  Map<String, dynamic> get _updates =>
      _map(widget.interrupt.payload["application_update_preview"]);

  @override
  void initState() {
    super.initState();
    _title = TextEditingController(text: (_note["title"] ?? "").toString());
    _body =
        TextEditingController(text: (_note["body_markdown"] ?? "").toString());
    _projectNotes =
        TextEditingController(text: (_updates["notes"] ?? "").toString());
  }

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    _projectNotes.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _PanelShell(
      title: "确认复盘写入",
      question: widget.interrupt.question,
      isSubmitting: widget.isSubmitting,
      child: Column(
        children: [
          TextField(
            key: const Key("workflow-review-title"),
            controller: _title,
            enabled: !widget.isSubmitting,
            decoration: const InputDecoration(labelText: "复盘标题"),
          ),
          const SizedBox(height: 10),
          TextField(
            key: const Key("workflow-review-body"),
            controller: _body,
            enabled: !widget.isSubmitting,
            minLines: 4,
            maxLines: 8,
            decoration: const InputDecoration(labelText: "复盘正文"),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _projectNotes,
            enabled: !widget.isSubmitting,
            minLines: 2,
            maxLines: 4,
            decoration: const InputDecoration(labelText: "项目备注更新"),
          ),
          const SizedBox(height: 12),
          _ReviewActions(
            isSubmitting: widget.isSubmitting,
            onCancel: () => widget.onSubmit({"action": "cancel"}),
            onApprove: () {
              final editedNote = Map<String, dynamic>.from(_note)
                ..["title"] = _title.text.trim()
                ..["body_markdown"] = _body.text.trim();
              final editedUpdates = Map<String, dynamic>.from(_updates)
                ..["notes"] = _projectNotes.text.trim();
              return widget.onSubmit({
                "action": "edit",
                "edited_note_draft": editedNote,
                "edited_application_updates": editedUpdates,
              });
            },
          ),
        ],
      ),
    );
  }
}

class _ReviewActions extends StatelessWidget {
  final bool isSubmitting;
  final Future<void> Function() onCancel;
  final Future<void> Function() onApprove;

  const _ReviewActions({
    required this.isSubmitting,
    required this.onCancel,
    required this.onApprove,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.end,
      children: [
        TextButton(
          key: const Key("workflow-cancel"),
          onPressed: isSubmitting ? null : onCancel,
          child: const Text("取消"),
        ),
        const SizedBox(width: 8),
        FilledButton.icon(
          key: const Key("workflow-approve"),
          onPressed: isSubmitting ? null : onApprove,
          icon: isSubmitting
              ? const SizedBox.square(
                  dimension: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.check_rounded, size: 18),
          label: const Text("确认并继续"),
        ),
      ],
    );
  }
}

class _UnknownInterrupt extends StatelessWidget {
  final WorkflowInterruptView interrupt;
  final bool isSubmitting;
  final Future<void> Function(Map<String, dynamic>) onSubmit;

  const _UnknownInterrupt({
    required this.interrupt,
    required this.isSubmitting,
    required this.onSubmit,
  });

  @override
  Widget build(BuildContext context) {
    return _PanelShell(
      title: "流程等待确认",
      question: interrupt.question,
      isSubmitting: isSubmitting,
      child: Align(
        alignment: Alignment.centerRight,
        child: FilledButton(
          key: const Key("workflow-approve"),
          onPressed:
              isSubmitting ? null : () => onSubmit({"action": "approve"}),
          child: const Text("继续"),
        ),
      ),
    );
  }
}

List<Map<String, dynamic>> _mapList(dynamic value) {
  if (value is! List) return const [];
  return value.whereType<Map>().map(Map<String, dynamic>.from).toList();
}

Map<String, dynamic> _map(dynamic value) {
  if (value is Map) return Map<String, dynamic>.from(value);
  return {};
}

String _candidateTitle(Map<String, dynamic> candidate) {
  for (final key in ["title", "application_id", "source_id"]) {
    final value = candidate[key]?.toString().trim() ?? "";
    if (value.isNotEmpty) return value;
  }
  return "未命名来源";
}

Widget? _candidateSubtitle(Map<String, dynamic> candidate) {
  final value =
      (candidate["snippet"] ?? candidate["summary"] ?? "").toString().trim();
  if (value.isEmpty) return null;
  return Text(
    value,
    maxLines: 2,
    overflow: TextOverflow.ellipsis,
  );
}
