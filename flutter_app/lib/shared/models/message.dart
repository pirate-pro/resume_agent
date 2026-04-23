import 'package:flutter/foundation.dart';

@immutable
class Message {
  final String id;
  final String role; // 'user', 'assistant', 'error'
  final String content;
  final String? thinking;
  final bool streaming;
  final DateTime timestamp;

  Message({
    required this.id,
    required this.role,
    required this.content,
    this.thinking,
    this.streaming = false,
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();

  Message copyWith({
    String? id,
    String? role,
    String? content,
    String? thinking,
    bool? streaming,
    DateTime? timestamp,
  }) {
    return Message(
      id: id ?? this.id,
      role: role ?? this.role,
      content: content ?? this.content,
      thinking: thinking ?? this.thinking,
      streaming: streaming ?? this.streaming,
      timestamp: timestamp ?? this.timestamp,
    );
  }

  factory Message.fromJson(Map<String, dynamic> json) {
    return Message(
      id: json['id'] as String,
      role: json['role'] as String,
      content: json['content'] as String,
      thinking: json['thinking'] as String?,
      streaming: json['streaming'] as bool? ?? false,
      timestamp: DateTime.parse(json['timestamp'] as String),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'role': role,
      'content': content,
      'thinking': thinking,
      'streaming': streaming,
      'timestamp': timestamp.toIso8601String(),
    };
  }

  @override
  String toString() {
    return 'Message{id: $id, role: $role, content: $content, thinking: $thinking, streaming: $streaming, timestamp: $timestamp}';
  }

  @override
  bool operator ==(Object other) {
    if (identical(this, other)) return true;
    return other is Message &&
        other.id == id &&
        other.role == role &&
        other.content == content &&
        other.thinking == thinking &&
        other.streaming == streaming &&
        other.timestamp == timestamp;
  }

  @override
  int get hashCode {
    return id.hashCode ^
        role.hashCode ^
        content.hashCode ^
        thinking.hashCode ^
        streaming.hashCode ^
        timestamp.hashCode;
  }
}
