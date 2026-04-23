import 'package:dio/dio.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import '../models/message.dart';
import '../models/session.dart';
import '../models/skill.dart';

class ChatApiClient {
  final Dio _dio;
  final String _baseUrl;

  ChatApiClient({String baseUrl = 'http://localhost:8000'})
      : _dio = Dio(),
        _baseUrl = baseUrl {
    _dio.options.baseUrl = _baseUrl;
    _dio.options.connectTimeout = const Duration(seconds: 30);
    _dio.options.receiveTimeout = const Duration(seconds: 30);
  }

  // 普通消息发送
  Future<Message> sendMessage({
    required String message,
    required String sessionId,
    List<String>? skillNames,
    int? maxToolRounds,
    List<String>? activeFileIds,
  }) async {
    try {
      final response = await _dio.post(
        '/api/chat',
        data: {
          'message': message,
          'session_id': sessionId,
          'skill_names': skillNames ?? ['base', 'memory', 'memory-editor', 'tools'],
          'max_tool_rounds': maxToolRounds ?? 3,
          'active_file_ids': activeFileIds ?? [],
        },
      );

      if (response.statusCode == 200) {
        return Message.fromJson(response.data['answer']);
      } else {
        throw Exception('Failed to send message: ${response.data['detail'] ?? response.statusMessage}');
      }
    } catch (e) {
      throw Exception('Network error: $e');
    }
  }

  // 流式消息发送
  Stream<Message> streamMessages({
    required String message,
    required String sessionId,
    List<String>? skillNames,
    int? maxToolRounds,
    List<String>? activeFileIds,
  }) async* {
    try {
      final response = await _dio.post(
        '/api/chat/stream',
        data: {
          'message': message,
          'session_id': sessionId,
          'skill_names': skillNames ?? ['base', 'memory', 'memory-editor', 'tools'],
          'max_tool_rounds': maxToolRounds ?? 3,
          'active_file_ids': activeFileIds ?? [],
        },
        options: Options(
          responseType: ResponseType.stream,
        ),
      );

      if (response.statusCode == 200 && response.data != null) {
        final stream = response.data.stream
            .transform(utf8.decoder)
            .transform(LineSplitter());

        await for (final line in stream) {
          if (line.startsWith('data: ')) {
            final data = line.substring(6).trim();
            if (data.isNotEmpty) {
              try {
                final jsonData = json.decode(data);
                if (jsonData['event'] == 'answer_delta') {
                  yield Message(
                    id: 'stream-${DateTime.now().millisecondsSinceEpoch}',
                    role: 'assistant',
                    content: jsonData['delta'] ?? '',
                    streaming: true,
                  );
                } else if (jsonData['event'] == 'done') {
                  final finalAnswer = jsonData['answer'] ?? '';
                  yield Message(
                    id: 'stream-${DateTime.now().millisecondsSinceEpoch}',
                    role: 'assistant',
                    content: finalAnswer,
                    streaming: false,
                  );
                  break;
                }
              } catch (e) {
                continue;
              }
            }
          }
        }
      } else {
        throw Exception('Stream connection failed');
      }
    } catch (e) {
      yield Message(
        id: 'error-${DateTime.now().millisecondsSinceEpoch}',
        role: 'error',
        content: 'Error: $e',
        streaming: false,
      );
    }
  }

  // 创建新会话
  Future<Session> createSession() async {
    try {
      final response = await _dio.post('/api/sessions');
      if (response.statusCode == 200) {
        final sessionData = response.data;
        return Session(
          id: sessionData['session_id'],
          title: 'New Session',
          messages: [],
        );
      } else {
        throw Exception('Failed to create session: ${response.data['detail'] ?? response.statusMessage}');
      }
    } catch (e) {
      throw Exception('Network error: $e');
    }
  }

  // 获取会话列表
  Future<List<Session>> getSessions() async {
    try {
      final response = await _dio.get('/api/sessions');
      if (response.statusCode == 200) {
        final sessionsData = response.data as List;
        return sessionsData.map((sessionJson) => Session.fromJson(sessionJson)).toList();
      } else {
        throw Exception('Failed to get sessions: ${response.data['detail'] ?? response.statusMessage}');
      }
    } catch (e) {
      throw Exception('Network error: $e');
    }
  }

  // 删除会话
  Future<void> deleteSession(String sessionId) async {
    try {
      final response = await _dio.delete('/api/sessions/$sessionId');
      if (response.statusCode != 200) {
        throw Exception('Failed to delete session: ${response.data['detail'] ?? response.statusMessage}');
      }
    } catch (e) {
      throw Exception('Network error: $e');
    }
  }

  // 获取技能列表
  Future<List<Skill>> getSkills() async {
    try {
      final response = await _dio.get('/api/skills');
      if (response.statusCode == 200) {
        final skillsData = response.data as List;
        return skillsData.map((skillJson) => Skill.fromJson(skillJson)).toList();
      } else {
        throw Exception('Failed to get skills: ${response.data['detail'] ?? response.statusMessage}');
      }
    } catch (e) {
      throw Exception('Network error: $e');
    }
  }

  // 上传文件
  Future<void> uploadFile({
    required String sessionId,
    required String filePath,
    required String fileName,
  }) async {
    try {
      final file = await http.MultipartFile.fromPath('file', filePath);
      final request = http.MultipartRequest('POST', Uri.parse('$_baseUrl/api/sessions/$sessionId/files/upload'));
      request.files.add(file);
      request.fields['filename'] = fileName;
      request.fields['auto_activate'] = 'true';

      final streamedResponse = await request.send();
      if (streamedResponse.statusCode != 200) {
        throw Exception('Failed to upload file: ${streamedResponse.reasonPhrase}');
      }
    } catch (e) {
      throw Exception('Network error: $e');
    }
  }

  // 获取会话文件
  Future<List<dynamic>> getSessionFiles(String sessionId) async {
    try {
      final response = await _dio.get('/api/sessions/$sessionId/files');
      if (response.statusCode == 200) {
        return response.data['files'] as List<dynamic>;
      } else {
        throw Exception('Failed to get session files: ${response.data['detail'] ?? response.statusMessage}');
      }
    } catch (e) {
      throw Exception('Network error: $e');
    }
  }

  // 更新活跃文件
  Future<void> updateActiveFiles({
    required String sessionId,
    required List<String> fileIds,
  }) async {
    try {
      final response = await _dio.post(
        '/api/sessions/$sessionId/active-files',
        data: {
          'file_ids': fileIds,
        },
      );
      if (response.statusCode != 200) {
        throw Exception('Failed to update active files: ${response.data['detail'] ?? response.statusMessage}');
      }
    } catch (e) {
      throw Exception('Network error: $e');
    }
  }

  // 模拟API方法
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