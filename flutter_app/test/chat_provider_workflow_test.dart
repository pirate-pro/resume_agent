import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/providers/chat_provider.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test("chat provider captures interrupt and resumes with expected version",
      () async {
    final api = _WorkflowApiService();
    final provider = ChatProvider(api);
    await Future<void>.delayed(Duration.zero);

    await provider.sendMessage("根据已有材料生成笔记");

    expect(provider.pendingWorkflowInterrupt?.workflowInstanceId, "wf_test");
    expect(provider.pendingWorkflowInterrupt?.workflowVersion, 2);

    await provider.resumePendingWorkflow({"action": "approve"});

    expect(api.resumedWorkflowId, "wf_test");
    expect(api.resumedExpectedVersion, 2);
    expect(api.resumedPayload, {"action": "approve"});
    expect(provider.pendingWorkflowInterrupt, isNull);
    expect(provider.messages.last.content, "已保存笔记");

    await Future<void>.delayed(const Duration(milliseconds: 10));
    provider.dispose();
  });
}

class _WorkflowApiService extends ApiService {
  String? resumedWorkflowId;
  int? resumedExpectedVersion;
  Map<String, dynamic>? resumedPayload;

  _WorkflowApiService() : super(baseUrl: "http://localhost");

  @override
  Future<HealthView?> fetchHealth() async =>
      HealthView(status: "ok", midTermFlush: null);

  @override
  Future<List<SkillOption>> listSkills() async => const [];

  @override
  Future<List<SessionMeta>> listSessions() async => const [];

  @override
  Future<TokenUsageSummaryView?> fetchTokenUsageSummary({
    int sessionLimit = 8,
    int callLimit = 8,
    int bucketLimit = 6,
  }) async =>
      null;

  @override
  Future<List<EventView>> listSessionEvents(String sessionId) async => const [];

  @override
  Future<SessionArtifactsResponse> listSessionArtifacts(
    String sessionId,
  ) async {
    return SessionArtifactsResponse(
      sessionId: sessionId,
      activeArtifactIds: const [],
      artifacts: const [],
    );
  }

  @override
  Stream<StreamEvent> chatStream({
    required String message,
    String? sessionId,
    List<String> skillNames = const [],
    int maxToolRounds = 8,
    List<String>? activeArtifactIds,
  }) async* {
    yield StreamEvent(
      event: "session",
      data: {"session_id": "sess_test"},
    );
    yield StreamEvent(
      event: "workflow_waiting_for_input",
      data: {
        "workflow_instance_id": "wf_test",
        "workflow_version": 2,
        "type": "note_review",
        "question": "确认笔记草稿",
        "draft": {
          "title": "草稿",
          "body_markdown": "正文",
        },
      },
    );
    yield StreamEvent(
      event: "done",
      data: {
        "session_id": "sess_test",
        "answer": "笔记草稿已生成，需要确认。",
        "tool_calls": [],
        "memory_hits": [],
      },
    );
  }

  @override
  Stream<StreamEvent> resumeWorkflowStream({
    required String workflowInstanceId,
    required String sessionId,
    required int expectedVersion,
    required Map<String, dynamic> payload,
  }) async* {
    resumedWorkflowId = workflowInstanceId;
    resumedExpectedVersion = expectedVersion;
    resumedPayload = payload;
    yield StreamEvent(
      event: "session",
      data: {
        "session_id": sessionId,
        "workflow_instance_id": workflowInstanceId,
      },
    );
    yield StreamEvent(
      event: "workflow_completed",
      data: {"workflow_instance_id": workflowInstanceId},
    );
    yield StreamEvent(
      event: "done",
      data: {
        "session_id": sessionId,
        "answer": "已保存笔记",
        "tool_calls": [],
        "memory_hits": [],
      },
    );
  }
}
