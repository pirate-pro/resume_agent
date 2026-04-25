import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/constants/app_config.dart';
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

enum _PlusPanelMode { closed, menu, config }

class _DismissPlusPanelIntent extends Intent {
  const _DismissPlusPanelIntent();
}

const double _composerMaxWidth = 820;
const double _menuTrayMaxWidth = 468;
const double _slashTrayMaxWidth = 500;
const double _configTrayMaxWidth = 560;

BoxDecoration _trayDecoration({double radius = 22, double alpha = 0.92}) {
  return AppTheme.floatingPanelDecoration(radius: radius, alpha: alpha);
}

class InputBar extends StatefulWidget {
  final Future<void> Function(String) onSend;
  final UploadSessionFileCallback onUpload;
  final ToggleSessionFileCallback onToggleFileActive;
  final Future<void> Function() onRefreshSkills;
  final void Function(String skillName) onToggleSkill;
  final void Function(int value) onMaxToolRoundsChanged;
  final void Function() onResetRuntimeOptions;
  final List<SessionFileView> sessionFiles;
  final List<String> activeFileIds;
  final String? highlightedFileId;
  final List<SkillOption> availableSkills;
  final List<String> selectedSkillNames;
  final int maxToolRounds;
  final bool enabled;
  final bool isUploading;
  final bool isLoadingSkills;
  final String? skillsError;
  final String? hintText;

  const InputBar({
    super.key,
    required this.onSend,
    required this.onUpload,
    required this.onToggleFileActive,
    required this.onRefreshSkills,
    required this.onToggleSkill,
    required this.onMaxToolRoundsChanged,
    required this.onResetRuntimeOptions,
    required this.sessionFiles,
    required this.activeFileIds,
    this.highlightedFileId,
    required this.availableSkills,
    required this.selectedSkillNames,
    required this.maxToolRounds,
    this.enabled = true,
    this.isUploading = false,
    this.isLoadingSkills = false,
    this.skillsError,
    this.hintText,
  });

  @override
  State<InputBar> createState() => _InputBarState();
}

class _InputBarState extends State<InputBar> {
  final _ctrl = TextEditingController();
  final _focus = FocusNode();
  late final TextEditingController _roundsCtrl;
  late final FocusNode _roundsFocus;

  bool _hasText = false;
  String? _slashQuery;
  String? _roundsError;
  _PlusPanelMode _plusPanelMode = _PlusPanelMode.closed;

  @override
  void initState() {
    super.initState();
    _roundsCtrl = TextEditingController(text: widget.maxToolRounds.toString());
    _roundsFocus = FocusNode();
    _ctrl.addListener(_handleComposerChange);
    _focus.addListener(_handleFocusChange);
    _roundsFocus.addListener(_handleRoundsFocusChange);
  }

  @override
  void didUpdateWidget(covariant InputBar oldWidget) {
    super.didUpdateWidget(oldWidget);
    final nextText = widget.maxToolRounds.toString();
    if (!_roundsFocus.hasFocus && _roundsCtrl.text != nextText) {
      _roundsCtrl.text = nextText;
    }
    if (!widget.enabled && _plusPanelMode != _PlusPanelMode.closed) {
      setState(() {
        _plusPanelMode = _PlusPanelMode.closed;
      });
    }
  }

  @override
  void dispose() {
    _ctrl
      ..removeListener(_handleComposerChange)
      ..dispose();
    _focus
      ..removeListener(_handleFocusChange)
      ..dispose();
    _roundsCtrl.dispose();
    _roundsFocus
      ..removeListener(_handleRoundsFocusChange)
      ..dispose();
    super.dispose();
  }

  void _handleComposerChange() {
    final hasText = _ctrl.text.trim().isNotEmpty;
    final slashQuery = _extractSlashQuery(_ctrl.text);
    final nextPanelMode =
        slashQuery != null || hasText ? _PlusPanelMode.closed : _plusPanelMode;
    if (hasText != _hasText ||
        slashQuery != _slashQuery ||
        nextPanelMode != _plusPanelMode) {
      setState(() {
        _hasText = hasText;
        _slashQuery = slashQuery;
        _plusPanelMode = nextPanelMode;
      });
    }
  }

  void _handleFocusChange() {
    setState(() {});
  }

  void _handleRoundsFocusChange() {
    if (!_roundsFocus.hasFocus) {
      _commitRoundInput();
    }
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

  bool get _hasRuntimeOverrides {
    return widget.selectedSkillNames.isNotEmpty ||
        widget.maxToolRounds != AppConfig.maxToolRounds;
  }

  IconData _fileIcon(SessionFileView file) {
    if (_isImage(file)) return Icons.image_outlined;
    final lower = file.filename.toLowerCase();
    if (lower.endsWith(".pdf")) return Icons.picture_as_pdf_outlined;
    if (lower.endsWith(".json")) return Icons.data_object_rounded;
    return Icons.insert_drive_file_outlined;
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

  String? _validateRoundsInput(String raw) {
    final trimmed = raw.trim();
    if (trimmed.isEmpty) return "请输入 0-10 的整数";
    final value = int.tryParse(trimmed);
    if (value == null) return "请输入整数";
    if (value < 0 || value > 10) return "工具轮数仅支持 0-10";
    return null;
  }

  void _handleRoundsChanged(String value) {
    final error = _validateRoundsInput(value);
    if (_roundsError != error) {
      setState(() {
        _roundsError = error;
      });
    }
    if (error == null) {
      widget.onMaxToolRoundsChanged(int.parse(value.trim()));
    }
  }

  void _commitRoundInput() {
    final error = _validateRoundsInput(_roundsCtrl.text);
    if (error != null) {
      setState(() {
        _roundsError = error;
      });
      _roundsCtrl.text = widget.maxToolRounds.toString();
      _roundsCtrl.selection = TextSelection.collapsed(
        offset: _roundsCtrl.text.length,
      );
      return;
    }
    if (_roundsError != null) {
      setState(() {
        _roundsError = null;
      });
    }
  }

  Future<void> _send() async {
    final text = _ctrl.text.trim();
    if (text.isEmpty || !widget.enabled || _inSlashMode) return;
    setState(() {
      _plusPanelMode = _PlusPanelMode.closed;
    });
    _ctrl.clear();
    await widget.onSend(text);
    if (mounted) {
      _focus.requestFocus();
    }
  }

  void _togglePlusPanel() {
    if (!widget.enabled || widget.isUploading) return;
    if (_inSlashMode) {
      _ctrl.clear();
    }
    setState(() {
      _plusPanelMode = _plusPanelMode == _PlusPanelMode.closed
          ? _PlusPanelMode.menu
          : _PlusPanelMode.closed;
    });
    _focus.requestFocus();
  }

  Future<void> _handleUploadAction(_UploadAction action) async {
    setState(() {
      _plusPanelMode = _PlusPanelMode.closed;
    });
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

  Future<void> _openConfigPanel() async {
    setState(() {
      _plusPanelMode = _PlusPanelMode.config;
      _roundsError = null;
    });
    if (widget.availableSkills.isEmpty && !widget.isLoadingSkills) {
      await widget.onRefreshSkills();
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

  void _resetRuntimeOptions() {
    widget.onResetRuntimeOptions();
    _roundsCtrl.text = AppConfig.maxToolRounds.toString();
    setState(() {
      _roundsError = null;
    });
  }

  void _resetMaxToolRoundsOnly() {
    widget.onMaxToolRoundsChanged(AppConfig.maxToolRounds);
    _roundsCtrl.text = AppConfig.maxToolRounds.toString();
    setState(() {
      _roundsError = null;
    });
  }

  void _dismissPlusPanel() {
    if (_plusPanelMode == _PlusPanelMode.closed && !_inSlashMode) return;
    _roundsFocus.unfocus();
    if (_inSlashMode) {
      _ctrl.clear();
    }
    setState(() {
      _plusPanelMode = _PlusPanelMode.closed;
      _roundsError = null;
    });
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

  Widget _buildPanel() {
    if (_inSlashMode) {
      return _SlashCommandTray(
        key: ValueKey("slash-${_slashQuery ?? ""}"),
        files: _slashCandidates,
        hasUploadedFiles: widget.sessionFiles.isNotEmpty,
        isFileActive: _isFileActive,
        iconForFile: _fileIcon,
        onSelect: (file) {
          _activateFromSlash(file);
        },
      );
    }

    switch (_plusPanelMode) {
      case _PlusPanelMode.menu:
        return _PlusMenuTray(
          key: const ValueKey("plus-menu"),
          onFileTap: () => _handleUploadAction(_UploadAction.file),
          onImageTap: () => _handleUploadAction(_UploadAction.image),
          onConfigTap: _openConfigPanel,
        );
      case _PlusPanelMode.config:
        return _RuntimeConfigTray(
          key: const ValueKey("runtime-config"),
          skills: widget.availableSkills,
          selectedSkillNames: widget.selectedSkillNames,
          maxToolRounds: widget.maxToolRounds,
          roundsController: _roundsCtrl,
          roundsFocus: _roundsFocus,
          roundsError: _roundsError,
          isLoadingSkills: widget.isLoadingSkills,
          skillsError: widget.skillsError,
          onBack: () {
            setState(() {
              _plusPanelMode = _PlusPanelMode.menu;
            });
          },
          onRetry: widget.onRefreshSkills,
          onToggleSkill: widget.onToggleSkill,
          onRoundsChanged: _handleRoundsChanged,
          onReset: _resetRuntimeOptions,
          onDone: () {
            _roundsFocus.unfocus();
            setState(() {
              _plusPanelMode = _PlusPanelMode.closed;
            });
          },
        );
      case _PlusPanelMode.closed:
        return const SizedBox.shrink();
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSend = _hasText && widget.enabled && !_inSlashMode;
    final panelVisible =
        _plusPanelMode != _PlusPanelMode.closed || _inSlashMode;
    final plusPanelVisible = _plusPanelMode != _PlusPanelMode.closed;
    final transientPanelVisible = plusPanelVisible || _inSlashMode;
    final transientPanelMaxWidth = _inSlashMode
        ? _slashTrayMaxWidth
        : (_plusPanelMode == _PlusPanelMode.config
            ? _configTrayMaxWidth
            : _menuTrayMaxWidth);
    final borderColor =
        _focus.hasFocus || panelVisible ? AppTheme.accent : AppTheme.border;
    final borderWidth = _focus.hasFocus || panelVisible ? 1.5 : 1.0;
    final activeFiles = _activeFiles;

    return Shortcuts(
      shortcuts: const <ShortcutActivator, Intent>{
        SingleActivator(LogicalKeyboardKey.escape): _DismissPlusPanelIntent(),
      },
      child: Actions(
        actions: <Type, Action<Intent>>{
          _DismissPlusPanelIntent: CallbackAction<_DismissPlusPanelIntent>(
            onInvoke: (_) {
              if (transientPanelVisible) {
                _dismissPlusPanel();
              }
              return null;
            },
          ),
        },
        child: TapRegion(
          onTapOutside: (_) {
            if (transientPanelVisible) {
              _dismissPlusPanel();
            }
          },
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: _composerMaxWidth),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (activeFiles.isNotEmpty) ...[
                      _ActiveFilesTray(
                        files: activeFiles,
                        highlightedFileId: widget.highlightedFileId,
                        iconForFile: _fileIcon,
                        onRemove: (file) {
                          widget.onToggleFileActive(file, false);
                        },
                      ),
                      const SizedBox(height: 10),
                    ],
                    if (panelVisible)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: ConstrainedBox(
                          constraints: BoxConstraints(
                            maxWidth: transientPanelMaxWidth,
                          ),
                          child: AnimatedSwitcher(
                            duration: const Duration(milliseconds: 180),
                            switchInCurve: Curves.easeOut,
                            switchOutCurve: Curves.easeIn,
                            child: _buildPanel(),
                          ),
                        ),
                      ),
                    Container(
                      decoration: AppTheme.floatingPanelDecoration(
                        radius: 24,
                        alpha: 0.94,
                      ).copyWith(
                        border:
                            Border.all(color: borderColor, width: borderWidth),
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Padding(
                            padding: const EdgeInsets.only(left: 8, bottom: 8),
                            child: _ComposerActionButton(
                              icon: Icons.add_rounded,
                              enabled: widget.enabled && !widget.isUploading,
                              busy: widget.isUploading,
                              highlighted: plusPanelVisible,
                              onPressed: _togglePlusPanel,
                            ),
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
                                  hintText:
                                      widget.hintText ?? "输入消息，或键入 / 激活文件和图片",
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
                    if (_hasRuntimeOverrides) ...[
                      const SizedBox(height: 10),
                      _RuntimeSummaryTray(
                        selectedSkillNames: widget.selectedSkillNames,
                        maxToolRounds: widget.maxToolRounds,
                        onClearSkill: widget.onToggleSkill,
                        onClearRounds: _resetMaxToolRoundsOnly,
                      ),
                    ],
                  ],
                ),
              ),
            ),
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
  final bool highlighted;
  final VoidCallback? onPressed;

  const _ComposerActionButton({
    required this.icon,
    required this.enabled,
    required this.onPressed,
    this.accent = false,
    this.busy = false,
    this.highlighted = false,
  });

  @override
  Widget build(BuildContext context) {
    final backgroundColor = accent
        ? (enabled ? AppTheme.accent : AppTheme.surfaceActive)
        : highlighted
            ? AppTheme.surfaceHover
            : (enabled ? AppTheme.surface : AppTheme.surfaceActive);
    final borderColor = accent
        ? Colors.transparent
        : highlighted
            ? AppTheme.accent.withValues(alpha: 0.45)
            : (enabled ? AppTheme.borderLight : AppTheme.border);
    final iconColor = accent
        ? (enabled ? Colors.white : AppTheme.textTertiary)
        : highlighted
            ? AppTheme.accent
            : (enabled ? AppTheme.textSecondary : AppTheme.textTertiary);

    return AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      width: 36,
      height: 36,
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: borderColor, width: accent ? 0 : 1),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: enabled ? onPressed : null,
          child: Center(
            child: busy
                ? SizedBox(
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

class _TrayHeader extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Widget? leading;

  const _TrayHeader({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.leading,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (leading != null) ...[
          leading!,
          const SizedBox(width: 10),
        ],
        Container(
          width: 30,
          height: 30,
          decoration: BoxDecoration(
            color: AppTheme.surfaceActive,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.border),
          ),
          child: Icon(icon, size: 16, color: AppTheme.accent),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 12,
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
                  height: 1.4,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _PlusMenuTray extends StatelessWidget {
  final VoidCallback onFileTap;
  final VoidCallback onImageTap;
  final VoidCallback onConfigTap;

  const _PlusMenuTray({
    super.key,
    required this.onFileTap,
    required this.onImageTap,
    required this.onConfigTap,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 8),
      decoration: _trayDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _TrayHeader(
            icon: Icons.add_circle_outline_rounded,
            title: "添加内容",
            subtitle: "上传和测试配置入口。",
          ),
          const SizedBox(height: 10),
          _MenuTile(
            icon: Icons.insert_drive_file_outlined,
            title: "上传文件",
            subtitle: "PDF / Markdown / JSON / TXT",
            onTap: onFileTap,
          ),
          const SizedBox(height: 8),
          _MenuTile(
            icon: Icons.image_outlined,
            title: "上传图片",
            subtitle: "PNG / JPG / JPEG / WEBP",
            onTap: onImageTap,
          ),
          const SizedBox(height: 8),
          _MenuTile(
            icon: Icons.tune_rounded,
            title: "测试配置",
            subtitle: "选择 skills 并调整最大工具轮数",
            onTap: onConfigTap,
          ),
        ],
      ),
    );
  }
}

class _MenuTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _MenuTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            color: AppTheme.surface,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: AppTheme.border),
          ),
          child: Row(
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: AppTheme.surfaceActive,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Icon(icon, size: 16, color: AppTheme.accent),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      title,
                      style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: AppTheme.ts(
                        fontSize: 10.5,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Icon(
                Icons.chevron_right_rounded,
                size: 16,
                color: AppTheme.textTertiary,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RuntimeConfigTray extends StatelessWidget {
  final List<SkillOption> skills;
  final List<String> selectedSkillNames;
  final int maxToolRounds;
  final TextEditingController roundsController;
  final FocusNode roundsFocus;
  final String? roundsError;
  final bool isLoadingSkills;
  final String? skillsError;
  final VoidCallback onBack;
  final Future<void> Function() onRetry;
  final void Function(String skillName) onToggleSkill;
  final void Function(String value) onRoundsChanged;
  final VoidCallback onReset;
  final VoidCallback onDone;

  const _RuntimeConfigTray({
    super.key,
    required this.skills,
    required this.selectedSkillNames,
    required this.maxToolRounds,
    required this.roundsController,
    required this.roundsFocus,
    required this.roundsError,
    required this.isLoadingSkills,
    required this.skillsError,
    required this.onBack,
    required this.onRetry,
    required this.onToggleSkill,
    required this.onRoundsChanged,
    required this.onReset,
    required this.onDone,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
      decoration: _trayDecoration(),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 320),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _TrayHeader(
                icon: Icons.tune_rounded,
                title: "测试配置",
                subtitle: "控制 skill 和最大工具轮数。",
                leading: _MiniIconButton(
                  icon: Icons.arrow_back_rounded,
                  onTap: onBack,
                ),
              ),
              const SizedBox(height: 14),
              Text(
                "Skills",
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 8),
              if (isLoadingSkills)
                const _PanelHint(
                  icon: Icons.sync_rounded,
                  message: "正在加载技能列表...",
                )
              else if (skillsError != null)
                _ErrorHint(
                  message: skillsError!,
                  onRetry: onRetry,
                )
              else if (skills.isEmpty)
                const _PanelHint(
                  icon: Icons.info_outline_rounded,
                  message: "当前没有可选技能。",
                )
              else
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: skills
                      .map(
                        (skill) => Tooltip(
                          message: skill.description,
                          child: _SkillChip(
                            name: skill.name,
                            selected: selectedSkillNames.contains(skill.name),
                            onTap: () => onToggleSkill(skill.name),
                          ),
                        ),
                      )
                      .toList(),
                ),
              const SizedBox(height: 16),
              Text(
                "最大工具轮数",
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                "输入 0-10，默认 3。",
                style: AppTheme.ts(
                  fontSize: 11,
                  color: AppTheme.textSecondary,
                ),
              ),
              const SizedBox(height: 10),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 92,
                    child: TextField(
                      controller: roundsController,
                      focusNode: roundsFocus,
                      enabled: true,
                      keyboardType: TextInputType.number,
                      inputFormatters: [
                        FilteringTextInputFormatter.digitsOnly,
                        LengthLimitingTextInputFormatter(2),
                      ],
                      onChanged: onRoundsChanged,
                      textAlign: TextAlign.center,
                      style: AppTheme.ts(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.textPrimary,
                      ),
                      decoration: InputDecoration(
                        filled: true,
                        fillColor: AppTheme.surface,
                        hintText: maxToolRounds.toString(),
                        hintStyle: AppTheme.ts(
                          fontSize: 14,
                          color: AppTheme.textTertiary,
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 12,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: AppTheme.border),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(
                            color: roundsError == null
                                ? AppTheme.border
                                : AppTheme.danger.withValues(alpha: 0.45),
                          ),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(
                            color: roundsError == null
                                ? AppTheme.accent
                                : AppTheme.danger,
                            width: 1.5,
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 12,
                      ),
                      decoration: BoxDecoration(
                        color: AppTheme.surface,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: AppTheme.border),
                      ),
                      child: Text(
                        "0 表示不进入工具轮次，数值越大允许模型进行更多轮工具调用。",
                        style: AppTheme.ts(
                          fontSize: 11,
                          color: AppTheme.textSecondary,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              if (roundsError != null) ...[
                const SizedBox(height: 8),
                Text(
                  roundsError!,
                  style: AppTheme.ts(
                    fontSize: 11,
                    color: AppTheme.danger,
                  ),
                ),
              ],
              const SizedBox(height: 14),
              Row(
                children: [
                  TextButton(
                    onPressed: onReset,
                    child: const Text("恢复默认"),
                  ),
                  const Spacer(),
                  _TrayPrimaryButton(
                    label: "完成",
                    onTap: onDone,
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

class _MiniIconButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;

  const _MiniIconButton({
    required this.icon,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 32,
      height: 32,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: Icon(
            icon,
            size: 18,
            color: AppTheme.textSecondary,
          ),
        ),
      ),
    );
  }
}

class _TrayPrimaryButton extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const _TrayPrimaryButton({
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: AppTheme.accent,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(
            label,
            style: AppTheme.ts(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: Colors.white,
            ),
          ),
        ),
      ),
    );
  }
}

class _SkillChip extends StatelessWidget {
  final String name;
  final bool selected;
  final VoidCallback onTap;

  const _SkillChip({
    required this.name,
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
          duration: const Duration(milliseconds: 150),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            color: selected
                ? AppTheme.accent.withValues(alpha: 0.12)
                : AppTheme.surface,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected
                  ? AppTheme.accent.withValues(alpha: 0.45)
                  : AppTheme.border,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                selected
                    ? Icons.check_circle_rounded
                    : Icons.auto_awesome_outlined,
                size: 14,
                color: selected ? AppTheme.accent : AppTheme.textSecondary,
              ),
              const SizedBox(width: 8),
              Text(
                name,
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                  color:
                      selected ? AppTheme.textPrimary : AppTheme.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PanelHint extends StatelessWidget {
  final IconData icon;
  final String message;

  const _PanelHint({
    required this.icon,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        children: [
          Icon(icon, size: 16, color: AppTheme.textSecondary),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: AppTheme.ts(
                fontSize: 12,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorHint extends StatelessWidget {
  final String message;
  final Future<void> Function() onRetry;

  const _ErrorHint({
    required this.message,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.danger.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.danger.withValues(alpha: 0.25)),
      ),
      child: Row(
        children: [
          Icon(
            Icons.error_outline_rounded,
            size: 16,
            color: AppTheme.danger,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: AppTheme.ts(
                fontSize: 12,
                color: AppTheme.danger,
              ),
            ),
          ),
          TextButton(
            onPressed: onRetry,
            style: TextButton.styleFrom(
              foregroundColor: AppTheme.danger,
            ),
            child: const Text("重试"),
          ),
        ],
      ),
    );
  }
}

class _RuntimeSummaryTray extends StatelessWidget {
  final List<String> selectedSkillNames;
  final int maxToolRounds;
  final void Function(String skillName) onClearSkill;
  final VoidCallback onClearRounds;

  const _RuntimeSummaryTray({
    required this.selectedSkillNames,
    required this.maxToolRounds,
    required this.onClearSkill,
    required this.onClearRounds,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
      decoration: _trayDecoration(alpha: 0.9),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.tune_rounded,
                size: 15,
                color: AppTheme.accent,
              ),
              const SizedBox(width: 8),
              Text(
                "测试配置已生效",
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
            children: [
              ...selectedSkillNames.map(
                (name) => _ConfigChip(
                  icon: Icons.auto_awesome_outlined,
                  label: "skill: $name",
                  onRemove: () => onClearSkill(name),
                ),
              ),
              if (maxToolRounds != AppConfig.maxToolRounds)
                _ConfigChip(
                  icon: Icons.rotate_right_rounded,
                  label: "轮数: $maxToolRounds",
                  onRemove: onClearRounds,
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ConfigChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onRemove;

  const _ConfigChip({
    required this.icon,
    required this.label,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: AppTheme.accent),
          const SizedBox(width: 8),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 12,
              color: AppTheme.textPrimary,
            ),
          ),
          const SizedBox(width: 8),
          InkWell(
            borderRadius: BorderRadius.circular(999),
            onTap: onRemove,
            child: Padding(
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

class _ActiveFilesTray extends StatelessWidget {
  final List<SessionFileView> files;
  final String? highlightedFileId;
  final IconData Function(SessionFileView file) iconForFile;
  final void Function(SessionFileView file) onRemove;

  const _ActiveFilesTray({
    required this.files,
    this.highlightedFileId,
    required this.iconForFile,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
      margin: const EdgeInsets.only(bottom: 10),
      decoration: _trayDecoration(alpha: 0.9),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
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
                    highlighted: highlightedFileId == file.fileId,
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
  final bool highlighted;
  final IconData icon;
  final VoidCallback onRemove;

  const _ActiveFileChip({
    required this.file,
    this.highlighted = false,
    required this.icon,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 240),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: highlighted
            ? AppTheme.accent.withValues(alpha: 0.14)
            : AppTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: highlighted
              ? AppTheme.accent.withValues(alpha: 0.42)
              : AppTheme.border,
        ),
        boxShadow: highlighted
            ? [
                BoxShadow(
                  color: AppTheme.accent.withValues(alpha: 0.18),
                  blurRadius: 14,
                  offset: const Offset(0, 4),
                ),
              ]
            : null,
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
            child: Padding(
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
  final void Function(SessionFileView file) onSelect;

  const _SlashCommandTray({
    super.key,
    required this.files,
    required this.hasUploadedFiles,
    required this.isFileActive,
    required this.iconForFile,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
      decoration: _trayDecoration(alpha: 0.9),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _TrayHeader(
            icon: Icons.keyboard_command_key_rounded,
            title: "选择要激活的文件或图片",
            subtitle: "从当前会话里快速选择上下文。",
          ),
          const SizedBox(height: 8),
          if (!hasUploadedFiles)
            const _PanelHint(
              icon: Icons.info_outline_rounded,
              message: "暂无可激活内容，先用 + 上传文件或图片。",
            )
          else if (files.isEmpty)
            const _PanelHint(
              icon: Icons.search_off_rounded,
              message: "没有匹配的文件或图片。",
            )
          else
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 168),
              child: SingleChildScrollView(
                child: Column(
                  children: files
                      .map(
                        (file) => _SlashFileOption(
                          file: file,
                          icon: iconForFile(file),
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
  final bool active;
  final VoidCallback onTap;

  const _SlashFileOption({
    required this.file,
    required this.icon,
    required this.active,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          margin: const EdgeInsets.only(bottom: 6),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            color: active
                ? AppTheme.accent.withValues(alpha: 0.08)
                : AppTheme.surface,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: active
                  ? AppTheme.accent.withValues(alpha: 0.35)
                  : AppTheme.border,
            ),
          ),
          child: Row(
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: AppTheme.surfaceActive,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Icon(icon, size: 16, color: AppTheme.accent),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      file.filename,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w500,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      "${file.sizeDisplay} · ${file.mediaType}",
                      style: AppTheme.ts(
                        fontSize: 10.5,
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
