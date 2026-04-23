import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';
import 'package:agent_runtime/shared/api/chat_api.dart';

class DebugPanel extends StatefulWidget {
  final String sessionId;

  const DebugPanel({required this.sessionId});

  @override
  _DebugPanelState createState() => _DebugPanelState();
}

class _DebugPanelState extends State<DebugPanel> {
  List<dynamic>? _files;
  List<dynamic>? _events;
  List<dynamic>? _memories;
  List<dynamic>? _toolCalls;
  List<dynamic>? _memoryHits;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadDebugData();
  }

  Future<void> _loadDebugData() async {
    final apiClient = ChatApiClient();
    try {
      final files = await apiClient.getSessionFiles(widget.sessionId);
      final events = await apiClient.getEvents(widget.sessionId);
      final memories = await apiClient.getMemories();
      final toolCalls = await apiClient.getToolCalls(widget.sessionId);
      final memoryHits = await apiClient.getMemoryHits(widget.sessionId);

      setState(() {
        _files = files;
        _events = events;
        _memories = memories;
        _toolCalls = toolCalls;
        _memoryHits = memoryHits;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Center(
        child: CircularProgressIndicator(
          color: AppTokens.accent,
        ),
      );
    }

    return Column(
      children: [
        _buildSection(
          title: '会话文件',
          child: _buildFileList(),
        ),
        _buildSection(
          title: '工具调用',
          child: _buildJsonView(_toolCalls ?? []),
        ),
        _buildSection(
          title: 'Memory 命中',
          child: _buildJsonView(_memoryHits ?? []),
        ),
        _buildSection(
          title: 'Events',
          child: _buildJsonView(_events ?? []),
        ),
        _buildSection(
          title: 'Memories',
          child: _buildJsonView(_memories ?? []),
        ),
      ],
    );
  }

  Widget _buildSection({
    required String title,
    required Widget child,
  }) {
    return Expanded(
      child: Container(
        margin: EdgeInsets.only(bottom: AppTokens.spacingMd),
        decoration: BoxDecoration(
          color: AppTokens.shellBg,
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          border: Border.all(
            color: AppTokens.textSub.withOpacity(0.2),
          ),
        ),
        child: Column(
          children: [
            Container(
              padding: EdgeInsets.all(AppTokens.spacingMd),
              decoration: BoxDecoration(
                color: AppTokens.hoverBg,
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(AppTokens.radiusMd),
                  topRight: Radius.circular(AppTokens.radiusMd),
                ),
                border: Border(
                  bottom: BorderSide(
                    color: AppTokens.textSub.withOpacity(0.2),
                    width: 1,
                  ),
                ),
              ),
              child: Text(
                title,
                style: TextStyle(
                  fontSize: AppTokens.fontSizeSm,
                  fontWeight: AppTokens.fontWeightMedium,
                  color: AppTokens.textSub,
                ),
              ),
            ),
            Expanded(
              child: child,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFileList() {
    if (_files == null || _files!.isEmpty) {
      return Center(
        child: Text(
          '暂无文件',
          style: TextStyle(
            fontSize: AppTokens.fontSizeSm,
            color: AppTokens.textSub,
          ),
        ),
      );
    }

    return ListView.builder(
      padding: EdgeInsets.all(AppTokens.spacingSm),
      itemCount: _files!.length,
      itemBuilder: (context, index) {
        final file = _files![index];
        return Container(
          margin: EdgeInsets.only(bottom: AppTokens.spacingSm),
          padding: EdgeInsets.all(AppTokens.spacingSm),
          decoration: BoxDecoration(
            color: AppTokens.hoverBg,
            borderRadius: BorderRadius.circular(AppTokens.radiusSm),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                file['filename'],
                style: TextStyle(
                  fontSize: AppTokens.fontSizeSm,
                  fontWeight: AppTokens.fontWeightMedium,
                  color: AppTokens.textMain,
                ),
              ),
              Text(
                '${file['media_type']} · ${file['size_bytes']} bytes',
                style: TextStyle(
                  fontSize: AppTokens.fontSizeXs,
                  color: AppTokens.textSub,
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildJsonView(List<dynamic> data) {
    return SingleChildScrollView(
      padding: EdgeInsets.all(AppTokens.spacingSm),
      child: Text(
        const JsonEncoder.withIndent('  ').convert(data),
        style: TextStyle(
          fontSize: AppTokens.fontSizeXs,
          color: AppTokens.textSub,
          fontFamily: 'IBM Plex Mono',
        ),
      ),
    );
  }
}

// 模拟API方法
extension ChatApiClientExtensions on ChatApiClient {
  Future<List<dynamic>> getEvents(String sessionId) async {
    // 模拟数据
    return [];
  }

  Future<List<dynamic>> getMemories() async {
    // 模拟数据
    return [];
  }

  Future<List<dynamic>> getToolCalls(String sessionId) async {
    // 模拟数据
    return [];
  }

  Future<List<dynamic>> getMemoryHits(String sessionId) async {
    // 模拟数据
    return [];
  }
}
