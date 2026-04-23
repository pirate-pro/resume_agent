import 'package:flutter/foundation.dart';
import 'message.dart';

@immutable
class Session {
  final String id;
  final String title;
  final String? preview;
  final List<Message> messages;
  final DateTime updatedAt;

  Session({
    required this.id,
    required this.title,
    this.preview,
    required this.messages,
    DateTime? updatedAt,
  }) : updatedAt = updatedAt ?? DateTime.now();

  factory Session.fromJson(Map<String, dynamic> json) {
    return Session(
      id: json['id'] as String,
      title: json['title'] as String,
      preview: json['preview'] as String?,
      messages: (json['messages'] as List)
          .map((msgJson) => Message.fromJson(msgJson))
          .toList(),
      updatedAt: DateTime.parse(json['updated_at'] as String),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'title': title,
      'preview': preview,
      'messages': messages.map((msg) => msg.toJson()).toList(),
      'updated_at': updatedAt.toIso8601String(),
    };
  }

  Session copyWith({
    String? id,
    String? title,
    String? preview,
    List<Message>? messages,
    DateTime? updatedAt,
  }) {
    return Session(
      id: id ?? this.id,
      title: title ?? this.title,
      preview: preview ?? this.preview,
      messages: messages ?? this.messages,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }

  @override
  String toString() {
    return 'Session{id: $id, title: $title, preview: $preview, messages: ${messages.length}, updatedAt: $updatedAt}';
  }

  @override
  bool operator ==(Object other) {
    if (identical(this, other)) return true;
    return other is Session &&
        other.id == id &&
        other.title == title &&
        other.preview == preview &&
        listEquals(other.messages, messages) &&
        other.updatedAt == updatedAt;
  }

  @override
  int get hashCode {
    return id.hashCode ^
        title.hashCode ^
        preview.hashCode ^
        messages.hashCode ^
        updatedAt.hashCode;
  }
}
