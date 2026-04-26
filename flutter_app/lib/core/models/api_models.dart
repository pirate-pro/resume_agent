class ChatMessage {
  final String role; // "user" | "assistant"
  final String content;
  final String answerFormat;
  final String renderHint;
  final String layoutHint;
  final String sourceKind;
  final List<AnswerArtifactView> artifacts;
  final List<ToolCallView> toolCalls;
  final DateTime timestamp;

  ChatMessage({
    required this.role,
    required this.content,
    this.answerFormat = "plain_text",
    this.renderHint = "plain",
    this.layoutHint = "paragraph",
    this.sourceKind = "direct_answer",
    this.artifacts = const [],
    this.toolCalls = const [],
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();

  bool get isUser => role == "user";
}

class AnswerArtifactView {
  final String type;
  final String path;
  final String role;

  const AnswerArtifactView({
    required this.type,
    required this.path,
    required this.role,
  });

  factory AnswerArtifactView.fromJson(Map<String, dynamic> json) {
    return AnswerArtifactView(
      type: json["type"] ?? "",
      path: json["path"] ?? "",
      role: json["role"] ?? "",
    );
  }
}

class ToolCallView {
  final String name;
  final Map<String, dynamic> arguments;

  ToolCallView({required this.name, required this.arguments});

  factory ToolCallView.fromJson(Map<String, dynamic> json) {
    return ToolCallView(
      name: json["name"] ?? "",
      arguments: Map<String, dynamic>.from(json["arguments"] ?? {}),
    );
  }
}

class MemoryView {
  final String memoryId;
  final String content;
  final List<String> tags;

  MemoryView({
    required this.memoryId,
    required this.content,
    required this.tags,
  });

  factory MemoryView.fromJson(Map<String, dynamic> json) {
    return MemoryView(
      memoryId: json["memory_id"] ?? "",
      content: json["content"] ?? "",
      tags: List<String>.from(json["tags"] ?? []),
    );
  }
}

class SkillOption {
  final String name;
  final String description;

  SkillOption({required this.name, required this.description});

  factory SkillOption.fromJson(Map<String, dynamic> json) {
    return SkillOption(
      name: json["name"] ?? "",
      description: json["description"] ?? "",
    );
  }
}

class ChatResponse {
  final String sessionId;
  final String answer;
  final bool titlePending;
  final String answerFormat;
  final String renderHint;
  final String layoutHint;
  final String sourceKind;
  final List<AnswerArtifactView> artifacts;
  final List<ToolCallView> toolCalls;
  final List<MemoryView> memoryHits;

  ChatResponse({
    required this.sessionId,
    required this.answer,
    this.titlePending = false,
    this.answerFormat = "plain_text",
    this.renderHint = "plain",
    this.layoutHint = "paragraph",
    this.sourceKind = "direct_answer",
    this.artifacts = const [],
    required this.toolCalls,
    required this.memoryHits,
  });

  factory ChatResponse.fromJson(Map<String, dynamic> json) {
    return ChatResponse(
      sessionId: json["session_id"] ?? "",
      answer: json["answer"] ?? "",
      titlePending: json["title_pending"] == true,
      answerFormat: json["answer_format"] ?? "plain_text",
      renderHint: json["render_hint"] ?? "plain",
      layoutHint: json["layout_hint"] ?? "paragraph",
      sourceKind: json["source_kind"] ?? "direct_answer",
      artifacts: (json["artifacts"] as List?)
              ?.map((e) =>
                  AnswerArtifactView.fromJson(Map<String, dynamic>.from(e)))
              .toList() ??
          const [],
      toolCalls: (json["tool_calls"] as List?)
              ?.map((e) => ToolCallView.fromJson(e))
              .toList() ??
          [],
      memoryHits: (json["memory_hits"] as List?)
              ?.map((e) => MemoryView.fromJson(e))
              .toList() ??
          [],
    );
  }
}

class SessionFileView {
  final String fileId;
  final String filename;
  final String mediaType;
  final int sizeBytes;
  final String status;
  final DateTime uploadedAt;
  final String? error;
  final int? parsedCharCount;
  final int? parsedTokenEstimate;

  SessionFileView({
    required this.fileId,
    required this.filename,
    required this.mediaType,
    required this.sizeBytes,
    required this.status,
    required this.uploadedAt,
    this.error,
    this.parsedCharCount,
    this.parsedTokenEstimate,
  });

  factory SessionFileView.fromJson(Map<String, dynamic> json) {
    return SessionFileView(
      fileId: json["file_id"] ?? "",
      filename: json["filename"] ?? "",
      mediaType: json["media_type"] ?? "",
      sizeBytes: json["size_bytes"] ?? 0,
      status: json["status"] ?? "",
      uploadedAt: DateTime.parse(
        json["uploaded_at"] ?? DateTime.now().toIso8601String(),
      ),
      error: json["error"],
      parsedCharCount: json["parsed_char_count"],
      parsedTokenEstimate: json["parsed_token_estimate"],
    );
  }

  String get sizeDisplay {
    if (sizeBytes < 1024) return "$sizeBytes B";
    if (sizeBytes < 1024 * 1024) {
      return "${(sizeBytes / 1024).toStringAsFixed(1)} KB";
    }
    return "${(sizeBytes / 1024 / 1024).toStringAsFixed(1)} MB";
  }
}

class SessionFilesResponse {
  final String sessionId;
  final List<String> activeFileIds;
  final List<SessionFileView> files;

  SessionFilesResponse({
    required this.sessionId,
    required this.activeFileIds,
    required this.files,
  });

  factory SessionFilesResponse.fromJson(Map<String, dynamic> json) {
    return SessionFilesResponse(
      sessionId: json["session_id"] ?? "",
      activeFileIds: List<String>.from(json["active_file_ids"] ?? []),
      files: (json["files"] as List?)
              ?.map((e) => SessionFileView.fromJson(e))
              .toList() ??
          [],
    );
  }
}

class WorkspaceFilePreview {
  final String sessionId;
  final String path;
  final String content;
  final int sizeBytes;
  final int totalChars;
  final bool truncated;
  final String answerFormat;
  final String renderHint;
  final String layoutHint;

  WorkspaceFilePreview({
    required this.sessionId,
    required this.path,
    required this.content,
    required this.sizeBytes,
    required this.totalChars,
    required this.truncated,
    this.answerFormat = "plain_text",
    this.renderHint = "plain",
    this.layoutHint = "paragraph",
  });

  factory WorkspaceFilePreview.fromJson(Map<String, dynamic> json) {
    return WorkspaceFilePreview(
      sessionId: json["session_id"] ?? "",
      path: json["path"] ?? "",
      content: json["content"] ?? "",
      sizeBytes: json["size_bytes"] ?? 0,
      totalChars: json["total_chars"] ?? 0,
      truncated: json["truncated"] == true,
      answerFormat: json["answer_format"] ?? "plain_text",
      renderHint: json["render_hint"] ?? "plain",
      layoutHint: json["layout_hint"] ?? "paragraph",
    );
  }
}

class SessionMeta {
  final String id;
  final String title;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool isPinned;
  final DateTime? pinnedAt;
  final int messageCount;

  SessionMeta({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.isPinned = false,
    this.pinnedAt,
    this.messageCount = 0,
  });
}

class EventView {
  final String eventId;
  final String sessionId;
  final String agentId;
  final String runId;
  final String? parentRunId;
  final int eventVersion;
  final String type;
  final Map<String, dynamic> payload;
  final DateTime createdAt;

  EventView({
    required this.eventId,
    required this.sessionId,
    required this.agentId,
    required this.runId,
    this.parentRunId,
    required this.eventVersion,
    required this.type,
    required this.payload,
    required this.createdAt,
  });

  factory EventView.fromJson(Map<String, dynamic> json) {
    return EventView(
      eventId: json["event_id"] ?? "",
      sessionId: json["session_id"] ?? "",
      agentId: json["agent_id"] ?? "",
      runId: json["run_id"] ?? "",
      parentRunId: json["parent_run_id"],
      eventVersion: json["event_version"] ?? 0,
      type: json["type"] ?? "",
      payload: Map<String, dynamic>.from(json["payload"] ?? {}),
      createdAt: DateTime.parse(
        json["created_at"] ?? DateTime.now().toIso8601String(),
      ),
    );
  }

  String get shortDescription {
    switch (type) {
      case "run_started":
        return "开始执行任务";
      case "assistant_thinking":
        return "模型思考: ${(payload["content"] ?? "").toString().substring(0, (payload["content"] ?? "").toString().length.clamp(0, 120))}";
      case "tool_call":
        return "调用工具 ${payload["name"] ?? "unknown"}";
      case "tool_result":
        final ok = payload["success"] == true ? "成功" : "失败";
        return "工具$ok ${payload["tool_name"] ?? "unknown"}";
      case "run_finished":
        return "执行完成";
      default:
        return type;
    }
  }
}
