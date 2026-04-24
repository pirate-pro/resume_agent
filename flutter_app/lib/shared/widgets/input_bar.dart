import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/models/api_models.dart';
import '../theme/app_theme.dart';

typedef UploadSessionFileCallback = Future<void> Function({
  required String filename,
  required Uint8List bytes,
});

typedef ToggleSessionFileCallback = Future<void> Function(
  SessionFileView file,
  bool active,
);

enum _UploadAction { file, image }

class InputBar extends StatefulWidget {
  final Future<void> Function(String) onSend;
  final UploadSessionFileCallback onUpload;
  final ToggleSessionFileCallback onToggleFileActive;
  final List<SessionFileView> sessionFiles;
  final List<String> activeFileIds;
  final bool enabled;
  final bool isUploading;
  final String? hintText;

  const InputBar({
    super.key,
    required this.onSend,
    required this.onUpload,
    required this.onToggleFileActive,
    required this.sessionFiles,
    required this.activeFileIds,
    this.enabled = true,
    this.isUploading = false,
    this.hintText,
  });

  @override
  State<InputBar> createState() => _InputBarState();
}

class _InputBarState extends State<InputBar> {
  final _ctrl = TextEditingController();
  final _focus = FocusNode();

  bool _hasText = false;
  String? _slashQuery;

  @override
  void initState() {
    super.initState();
    _ctrl.addListener(_handleComposerChange);
    _focus.addListener(_handleFocusChange);
  }

  @override
  void dispose() {
    _ctrl
      ..removeListener(_handleComposerChange)
      ..dispose();
    _focus
      ..removeListener(_handleFocusChange)
      ..dispose();
    super.dispose();
  }

  void _handleComposerChange() {
    final hasText = _ctrl.text.trim().isNotEmpty;
    final slashQuery = _extractSlashQuery(_ctrl.text);
    if (hasText != _hasText || slashQuery != _slashQuery) {
      setState(() {
        _hasText = hasText;
        _slashQuery = slashQuery;
      });
    }
  }

  void _handleFocusChange() {
    setState(() {});
  }

  String? _extractSlashQuery(String raw) {
    if (!raw.startsWith("/")) return null;
    if (raw.contains("\n")) return null;
    return raw.substring(1);
  }

  bool get _inSlashMode => _slashQuery != null;

  bool _isFileActive(SessionFileView file) {
    return widget.activeFileIds.contains(file.fileId);
  }

  bool _isImage(SessionFileView file) {
    return file.mediaType.toLowerCase().startsWith("image/");
  }

  IconData _fileIcon(SessionFileView file) {
    if (_isImage(file)) return Icons.image_outlined;
    final lower = file.filename.toLowerCase();
    if (lower.endsWith(".pdf")) return Icons.picture_as_pdf_outlined;
    if (lower.endsWith(".json")) return Icons.data_object_rounded;
    return Icons.insert_drive_file_outlined;
  }

  String _fileTypeLabel(SessionFileView file) {
    if (_isImage(file)) return "图片";
    return "文件";
  }

  List<SessionFileView> get _activeFiles {
    final activeIds = widget.activeFileIds.toSet();
    return widget.sessionFiles
        .where((file) => activeIds.contains(file.fileId))
        .toList()
      ..sort((a, b) => b.uploadedAt.compareTo(a.uploadedAt));
  }

  List<SessionFileView> get _slashCandidates {
    final query = (_slashQuery ?? "").trim().toLowerCase();
    final files = widget.sessionFiles.where((file) {
      if (query.isEmpty) return true;
      return file.filename.toLowerCase().contains(query);
    }).toList();
    files.sort((a, b) {
      final aActive = _isFileActive(a);
      final bActive = _isFileActive(b);
      if (aActive != bActive) return aActive ? 1 : -1;
      return b.uploadedAt.compareTo(a.uploadedAt);
    });
    return files;
  }

  Future<void> _send() async {
    final text = _ctrl.text.trim();
    if (text.isEmpty || !widget.enabled || _inSlashMode) return;
    _ctrl.clear();
    await widget.onSend(text);
    if (mounted) {
      _focus.requestFocus();
    }
  }

  Future<void> _handleUploadAction(_UploadAction action) async {
    final result = await FilePicker.platform.pickFiles(
      allowMultiple: false,
      withData: true,
      type: FileType.custom,
      dialogTitle: action == _UploadAction.image ? "选择图片" : "选择文件",
      allowedExtensions: action == _UploadAction.image
          ? const ["png", "jpg", "jpeg", "webp"]
          : const ["pdf", "md", "markdown", "json", "txt"],
    );

    if (!mounted || result == null || result.files.isEmpty) return;

    final file = result.files.single;
    final bytes = file.bytes;
    if (bytes == null || bytes.isEmpty) {
      _showSnackBar("无法读取所选内容，请重新选择。");
      return;
    }

    await widget.onUpload(filename: file.name, bytes: bytes);
    if (mounted) {
      _focus.requestFocus();
    }
  }

  Future<void> _openUploadMenu(BuildContext buttonContext) async {
    if (!widget.enabled || widget.isUploading) return;

    final button = buttonContext.findRenderObject();
    final overlay = Overlay.of(context).context.findRenderObject();
    if (button is! RenderBox || overlay is! RenderBox) return;

    final buttonRect = Rect.fromPoints(
      button.localToGlobal(Offset.zero, ancestor: overlay),
      button.localToGlobal(button.size.bottomRight(Offset.zero), ancestor: overlay),
    );

    final action = await showMenu<_UploadAction>(
      context: context,
      position: RelativeRect.fromRect(buttonRect, Offset.zero & overlay.size),
      color: AppTheme.surface,
      elevation: 12,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: AppTheme.border),
      ),
      items: const [
        PopupMenuItem<_UploadAction>(
          value: _UploadAction.file,
          child: _UploadMenuRow(
            icon: Icons.insert_drive_file_outlined,
            title: "上传文件",
            subtitle: "PDF / Markdown / JSON / TXT",
          ),
        ),
        PopupMenuItem<_UploadAction>(
          value: _UploadAction.image,
          child: _UploadMenuRow(
            icon: Icons.image_outlined,
            title: "上传图片",
            subtitle: "PNG / JPG / JPEG / WEBP",
          ),
        ),
      ],
    );

    if (action != null) {
      await _handleUploadAction(action);
    }
  }

  Future<void> _activateFromSlash(SessionFileView file) async {
    if (!_isFileActive(file)) {
      await widget.onToggleFileActive(file, true);
    }
    if (!mounted) return;
    _ctrl.clear();
    _focus.requestFocus();
  }

  void _showSnackBar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  KeyEventResult _handleKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) return KeyEventResult.ignored;
    if (event.logicalKey != LogicalKeyboardKey.enter) {
      return KeyEventResult.ignored;
    }
    final shift = HardwareKeyboard.instance.isShiftPressed;
    if (shift) return KeyEventResult.ignored;
    if (_inSlashMode) return KeyEventResult.handled;
    _send();
    return KeyEventResult.handled;
  }

  @override
  Widget build(BuildContext context) {
    final canSend = _hasText && widget.enabled && !_inSlashMode;
    final borderColor = _focus.hasFocus || _inSlashMode
        ? AppTheme.accent
        : AppTheme.border;
    final borderWidth = _focus.hasFocus || _inSlashMode ? 1.5 : 1.0;
    final slashCandidates = _slashCandidates;
    final activeFiles = _activeFiles;

    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
      decoration: const BoxDecoration(
        color: AppTheme.surface,
        border: Border(top: BorderSide(color: AppTheme.border, width: 0.5)),
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 820),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (activeFiles.isNotEmpty) ...[
                _ActiveFilesTray(
                  files: activeFiles,
                  iconForFile: _fileIcon,
                  onRemove: (file) {
                    widget.onToggleFileActive(file, false);
                  },
                ),
                const SizedBox(height: 10),
              ],
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 160),
                child: _inSlashMode
                    ? _SlashCommandTray(
                        key: ValueKey("slash-${_slashQuery ?? ""}"),
                        files: slashCandidates,
                        hasUploadedFiles: widget.sessionFiles.isNotEmpty,
                        isFileActive: _isFileActive,
                        iconForFile: _fileIcon,
                        typeLabelForFile: _fileTypeLabel,
                        onSelect: (file) {
                          _activateFromSlash(file);
                        },
                      )
                    : const SizedBox.shrink(),
              ),
              Container(
                decoration: BoxDecoration(
                  color: AppTheme.bg,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: borderColor, width: borderWidth),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Builder(
                      builder: (buttonContext) {
                        return Padding(
                          padding: const EdgeInsets.only(left: 8, bottom: 8),
                          child: _ComposerActionButton(
                            icon: Icons.add_rounded,
                            enabled: widget.enabled && !widget.isUploading,
                            busy: widget.isUploading,
                            onPressed: () => _openUploadMenu(buttonContext),
                          ),
                        );
                      },
                    ),
                    Expanded(
                      child: Focus(
                        focusNode: _focus,
                        onKeyEvent: _handleKey,
                        child: TextField(
                          controller: _ctrl,
                          enabled: widget.enabled,
                          maxLines: 6,
                          minLines: 1,
                          textInputAction: TextInputAction.newline,
                          keyboardType: TextInputType.multiline,
                          style: AppTheme.ts(
                            fontSize: 15,
                            color: AppTheme.textPrimary,
                            height: 1.5,
                          ),
                          decoration: InputDecoration(
                            hintText: widget.hintText ??
                                "输入消息，或键入 / 激活文件和图片",
                            hintStyle: AppTheme.ts(
                              color: AppTheme.textTertiary,
                              fontSize: 14,
                            ),
                            border: InputBorder.none,
                            enabledBorder: InputBorder.none,
                            focusedBorder: InputBorder.none,
                            contentPadding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 14,
                            ),
                          ),
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8, right: 8),
                      child: _ComposerActionButton(
                        icon: Icons.arrow_upward_rounded,
                        enabled: canSend,
                        accent: true,
                        onPressed: _send,
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

class _ComposerActionButton extends StatelessWidget {
  final IconData icon;
  final bool enabled;
  final bool accent;
  final bool busy;
  final VoidCallback? onPressed;

  const _ComposerActionButton({
    required this.icon,
    required this.enabled,
    required this.onPressed,
    this.accent = false,
    this.busy = false,
  });

  @override
  Widget build(BuildContext context) {
    final backgroundColor = accent
        ? (enabled ? AppTheme.accent : AppTheme.surfaceActive)
        : (enabled ? AppTheme.surface : AppTheme.surfaceActive);
    final borderColor = accent
        ? Colors.transparent
        : (enabled ? AppTheme.borderLight : AppTheme.border);
    final iconColor = accent
        ? (enabled ? Colors.white : AppTheme.textTertiary)
        : (enabled ? AppTheme.textSecondary : AppTheme.textTertiary);

    return AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      width: 36,
      height: 36,
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: borderColor, width: accent ? 0 : 1),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: enabled ? onPressed : null,
          child: Center(
            child: busy
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 1.8,
                      color: AppTheme.textSecondary,
                    ),
                  )
                : Icon(icon, size: 20, color: iconColor),
          ),
        ),
      ),
    );
  }
}

class _UploadMenuRow extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;

  const _UploadMenuRow({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: AppTheme.surfaceActive,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppTheme.border),
          ),
          child: Icon(icon, size: 18, color: AppTheme.accent),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: AppTheme.ts(
                  fontSize: 11,
                  color: AppTheme.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ActiveFilesTray extends StatelessWidget {
  final List<SessionFileView> files;
  final IconData Function(SessionFileView file) iconForFile;
  final void Function(SessionFileView file) onRemove;

  const _ActiveFilesTray({
    required this.files,
    required this.iconForFile,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
      decoration: BoxDecoration(
        color: AppTheme.bg,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.layers_outlined,
                size: 15,
                color: AppTheme.accent,
              ),
              const SizedBox(width: 8),
              Text(
                "已激活上下文",
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textPrimary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: files
                .map(
                  (file) => _ActiveFileChip(
                    file: file,
                    icon: iconForFile(file),
                    onRemove: () => onRemove(file),
                  ),
                )
                .toList(),
          ),
        ],
      ),
    );
  }
}

class _ActiveFileChip extends StatelessWidget {
  final SessionFileView file;
  final IconData icon;
  final VoidCallback onRemove;

  const _ActiveFileChip({
    required this.file,
    required this.icon,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 240),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: AppTheme.accent),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              file.filename,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 12,
                color: AppTheme.textPrimary,
              ),
            ),
          ),
          const SizedBox(width: 8),
          InkWell(
            borderRadius: BorderRadius.circular(999),
            onTap: onRemove,
            child: const Padding(
              padding: EdgeInsets.all(2),
              child: Icon(
                Icons.close_rounded,
                size: 14,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SlashCommandTray extends StatelessWidget {
  final List<SessionFileView> files;
  final bool hasUploadedFiles;
  final bool Function(SessionFileView file) isFileActive;
  final IconData Function(SessionFileView file) iconForFile;
  final String Function(SessionFileView file) typeLabelForFile;
  final void Function(SessionFileView file) onSelect;

  const _SlashCommandTray({
    super.key,
    required this.files,
    required this.hasUploadedFiles,
    required this.isFileActive,
    required this.iconForFile,
    required this.typeLabelForFile,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
      decoration: BoxDecoration(
        color: AppTheme.bg,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.keyboard_command_key_rounded,
                size: 15,
                color: AppTheme.accent,
              ),
              const SizedBox(width: 8),
              Text(
                "选择要激活的文件或图片",
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textPrimary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (!hasUploadedFiles)
            Text(
              "还没有可激活的内容，先点击左侧 + 上传文件或图片。",
              style: AppTheme.ts(
                fontSize: 12,
                color: AppTheme.textSecondary,
              ),
            )
          else if (files.isEmpty)
            Text(
              "没有匹配的文件或图片。",
              style: AppTheme.ts(
                fontSize: 12,
                color: AppTheme.textSecondary,
              ),
            )
          else
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 240),
              child: SingleChildScrollView(
                child: Column(
                  children: files
                      .map(
                        (file) => _SlashFileOption(
                          file: file,
                          icon: iconForFile(file),
                          typeLabel: typeLabelForFile(file),
                          active: isFileActive(file),
                          onTap: () => onSelect(file),
                        ),
                      )
                      .toList(),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _SlashFileOption extends StatelessWidget {
  final SessionFileView file;
  final IconData icon;
  final String typeLabel;
  final bool active;
  final VoidCallback onTap;

  const _SlashFileOption({
    required this.file,
    required this.icon,
    required this.typeLabel,
    required this.active,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          margin: const EdgeInsets.only(bottom: 6),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: active
                ? AppTheme.accent.withValues(alpha: 0.08)
                : AppTheme.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: active
                  ? AppTheme.accent.withValues(alpha: 0.35)
                  : AppTheme.border,
            ),
          ),
          child: Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: AppTheme.surfaceActive,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Icon(icon, size: 18, color: AppTheme.accent),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      file.filename,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      "$typeLabel · ${file.sizeDisplay}",
                      style: AppTheme.ts(
                        fontSize: 11,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              if (active)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: AppTheme.accent.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    "已激活",
                    style: AppTheme.ts(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.accent,
                    ),
                  ),
                )
              else
                Text(
                  "激活",
                  style: AppTheme.ts(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.textSecondary,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
