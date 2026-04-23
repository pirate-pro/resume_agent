import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';

class FileList extends StatefulWidget {
  final String? sessionId;
  final List<dynamic> files;
  final List<String> activeFileIds;
  final Function(List<String>) onActiveFilesChanged;

  const FileList({
    required this.sessionId,
    required this.files,
    required this.activeFileIds,
    required this.onActiveFilesChanged,
  });

  @override
  _FileListState createState() => _FileListState();
}

class _FileListState extends State<FileList> {
  late List<String> _activeFileIds;

  @override
  void initState() {
    super.initState();
    _activeFileIds = List.from(widget.activeFileIds);
  }

  @override
  Widget build(BuildContext context) {
    if (widget.sessionId == null || widget.files.isEmpty) {
      return Center(
        child: Text(
          '请先发送一条消息或上传文件创建会话。',
          style: TextStyle(
            fontSize: AppTokens.fontSizeSm,
            color: AppTokens.textSub,
          ),
        ),
      );
    }

    return ListView.builder(
      padding: EdgeInsets.all(AppTokens.spacingSm),
      itemCount: widget.files.length,
      itemBuilder: (context, index) {
        final file = widget.files[index];
        final fileId = file['file_id'] as String;
        final isActive = _activeFileIds.contains(fileId);

        return Container(
          margin: EdgeInsets.only(bottom: AppTokens.spacingSm),
          decoration: BoxDecoration(
            color: AppTokens.hoverBg,
            borderRadius: BorderRadius.circular(AppTokens.radiusSm),
          ),
          child: ListTile(
            contentPadding: EdgeInsets.symmetric(
              horizontal: AppTokens.spacingMd,
              vertical: AppTokens.spacingSm,
            ),
            leading: Icon(
              Icons.file_present,
              color: AppTokens.textSub,
              size: 20,
            ),
            title: Text(
              file['filename'],
              style: TextStyle(
                fontSize: AppTokens.fontSizeSm,
                fontWeight: AppTokens.fontWeightMedium,
                color: AppTokens.textMain,
              ),
            ),
            subtitle: Text(
              '${file['media_type']} · ${file['size_bytes']} bytes${file['error'] != null ? ' · ${file['error']}' : ''}',
              style: TextStyle(
                fontSize: AppTokens.fontSizeXs,
                color: AppTokens.textSub,
              ),
            ),
            trailing: Checkbox(
              value: isActive,
              onChanged: (selected) {
                setState(() {
                  if (selected == true) {
                    _activeFileIds.add(fileId);
                  } else {
                    _activeFileIds.remove(fileId);
                  }
                  widget.onActiveFilesChanged(_activeFileIds);
                });
              },
              activeColor: AppTokens.accent,
              checkColor: AppTokens.shellBg,
            ),
            onTap: () {
              setState(() {
                if (_activeFileIds.contains(fileId)) {
                  _activeFileIds.remove(fileId);
                } else {
                  _activeFileIds.add(fileId);
                }
                widget.onActiveFilesChanged(_activeFileIds);
              });
            },
          ),
        );
      },
    );
  }
}
