class AppConfig {
  static String get defaultBaseUrl {
    final host = Uri.base.host;
    if (host.isEmpty ||
        host == "localhost" ||
        host == "127.0.0.1" ||
        host == "::1" ||
        host == "0.0.0.0") {
      return "http://localhost:8000";
    }
    return "http://$host:8000";
  }

  static const String chatEndpoint = "/api/chat";
  static const String chatStreamEndpoint = "/api/chat/stream";
  static const String memoriesEndpoint = "/api/memories";
  static const int maxToolRounds = 3;
  static const String defaultAgentId = "agent_main";
}
