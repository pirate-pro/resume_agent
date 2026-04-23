import 'package:flutter/foundation.dart';

@immutable
class Skill {
  final String id;
  final String name;
  final String description;
  final bool enabled;

  const Skill({
    required this.id,
    required this.name,
    required this.description,
    this.enabled = true,
  });

  Skill copyWith({
    String? id,
    String? name,
    String? description,
    bool? enabled,
  }) {
    return Skill(
      id: id ?? this.id,
      name: name ?? this.name,
      description: description ?? this.description,
      enabled: enabled ?? this.enabled,
    );
  }

  factory Skill.fromJson(Map<String, dynamic> json) {
    return Skill(
      id: json['id'] as String,
      name: json['name'] as String,
      description: json['description'] as String,
      enabled: json['enabled'] as bool? ?? true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'description': description,
      'enabled': enabled,
    };
  }

  @override
  String toString() {
    return 'Skill{id: $id, name: $name, enabled: $enabled}';
  }

  @override
  bool operator ==(Object other) {
    if (identical(this, other)) return true;
    return other is Skill &&
        other.id == id &&
        other.name == name &&
        other.description == description &&
        other.enabled == enabled;
  }

  @override
  int get hashCode {
    return id.hashCode ^ name.hashCode ^ description.hashCode ^ enabled.hashCode;
  }
}