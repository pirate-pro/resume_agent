import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
import '../../core/services/api_service.dart';

final careerWorkbenchProvider =
    ChangeNotifierProvider<CareerWorkbenchProvider>((ref) {
  return CareerWorkbenchProvider(ref.read(apiServiceProvider));
});

enum CareerWorkbenchTab {
  overview,
  projects,
  resumes,
  jobs,
  learning,
  notes,
}

enum CareerProjectFilter {
  all,
  draft,
  readyToApply,
  applied,
  interviewing,
  paused,
}

class CareerWorkbenchProvider extends ChangeNotifier {
  final ApiService _api;

  bool _hasLoaded = false;
  bool _isLoading = false;
  bool _isRefreshing = false;
  String? _error;
  CareerWorkbenchTab _activeTab = CareerWorkbenchTab.projects;
  CareerProjectFilter _projectFilter = CareerProjectFilter.all;
  String? _selectedApplicationId;
  CareerWorkbenchListView? _workbench;
  final Map<String, CareerApplicationWorkbenchView> _details = {};
  final Set<String> _loadingApplicationIds = {};
  final Map<String, String> _detailErrors = {};

  CareerWorkbenchProvider(this._api);

  bool get hasLoaded => _hasLoaded;
  bool get isLoading => _isLoading;
  bool get isRefreshing => _isRefreshing;
  String? get error => _error;
  CareerWorkbenchTab get activeTab => _activeTab;
  CareerProjectFilter get projectFilter => _projectFilter;
  String? get selectedApplicationId => _selectedApplicationId;
  CareerWorkbenchListView? get workbench => _workbench;

  List<CareerApplicationSummaryView> get applications {
    final records = [...?_workbench?.applications]
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return records;
  }

  List<CareerApplicationSummaryView> get filteredApplications {
    final filter = _projectFilter;
    if (filter == CareerProjectFilter.all) {
      return applications;
    }
    final stage = _stageForFilter(filter);
    return applications
        .where((item) => item.application.stage == stage)
        .toList(growable: false);
  }

  CareerApplicationSummaryView? get selectedApplicationSummary {
    final selectedId = _selectedApplicationId?.trim() ?? "";
    if (selectedId.isEmpty) return null;
    for (final item in applications) {
      if (item.application.applicationId == selectedId) {
        return item;
      }
    }
    return null;
  }

  CareerApplicationWorkbenchView? get selectedApplicationDetail {
    final selectedId = _selectedApplicationId?.trim() ?? "";
    if (selectedId.isEmpty) return null;
    return _details[selectedId];
  }

  bool isApplicationLoading(String applicationId) {
    return _loadingApplicationIds.contains(applicationId.trim());
  }

  String? detailError(String applicationId) {
    return _detailErrors[applicationId.trim()];
  }

  Future<void> ensureLoaded() async {
    if (_hasLoaded || _isLoading) return;
    await refresh();
  }

  Future<void> refresh() async {
    final firstLoad = !_hasLoaded;
    _isLoading = firstLoad;
    _isRefreshing = !firstLoad;
    _error = null;
    notifyListeners();

    try {
      final next = await _api.getCareerWorkbench();
      _workbench = next;
      _hasLoaded = true;
      _syncSelectedApplication();
      final selectedId = _selectedApplicationId;
      if (selectedId != null && selectedId.isNotEmpty) {
        await loadApplicationDetail(selectedId, force: true);
      }
    } catch (error, stackTrace) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          library: "career workbench",
          context: ErrorDescription("refresh career workbench"),
        ),
      );
      _error = error.toString();
    } finally {
      _isLoading = false;
      _isRefreshing = false;
      notifyListeners();
    }
  }

  void setTab(CareerWorkbenchTab tab) {
    if (_activeTab == tab) return;
    _activeTab = tab;
    notifyListeners();
  }

  void setProjectFilter(CareerProjectFilter filter) {
    if (_projectFilter == filter) return;
    _projectFilter = filter;
    final visible = filteredApplications;
    if (visible.isNotEmpty &&
        !visible.any(
          (item) => item.application.applicationId == _selectedApplicationId,
        )) {
      selectApplication(visible.first.application.applicationId);
      return;
    }
    notifyListeners();
  }

  Future<void> selectApplication(String applicationId) async {
    final normalized = applicationId.trim();
    if (normalized.isEmpty) return;
    _selectedApplicationId = normalized;
    notifyListeners();
    await loadApplicationDetail(normalized);
  }

  Future<CareerApplicationWorkbenchView?> loadApplicationDetail(
    String applicationId, {
    bool force = false,
  }) async {
    final normalized = applicationId.trim();
    if (normalized.isEmpty) return null;
    if (_details.containsKey(normalized) && !force) {
      return _details[normalized];
    }

    _detailErrors.remove(normalized);
    _loadingApplicationIds.add(normalized);
    notifyListeners();
    try {
      final detail = await _api.getCareerApplicationWorkbench(
        applicationId: normalized,
      );
      _details[normalized] = detail;
      return detail;
    } catch (error, stackTrace) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          library: "career workbench",
          context: ErrorDescription("load career application detail"),
        ),
      );
      _detailErrors[normalized] = error.toString();
      rethrow;
    } finally {
      _loadingApplicationIds.remove(normalized);
      notifyListeners();
    }
  }

  Future<SessionArtifactContentView> loadArtifactPreview({
    required String sourceSessionId,
    required String artifactId,
  }) {
    return _api.readSessionArtifactContent(
      sessionId: sourceSessionId.trim(),
      artifactId: artifactId.trim(),
    );
  }

  String artifactDownloadUrl({
    required String sourceSessionId,
    required String artifactId,
  }) {
    return _api.sessionArtifactDownloadUrl(
      sessionId: sourceSessionId.trim(),
      artifactId: artifactId.trim(),
    );
  }

  void _syncSelectedApplication() {
    final records = applications;
    if (records.isEmpty) {
      _selectedApplicationId = null;
      return;
    }
    final selectedId = _selectedApplicationId?.trim() ?? "";
    if (selectedId.isNotEmpty &&
        records.any((item) => item.application.applicationId == selectedId)) {
      return;
    }
    final activeId = _workbench?.activeApplicationId?.trim() ?? "";
    if (activeId.isNotEmpty &&
        records.any((item) => item.application.applicationId == activeId)) {
      _selectedApplicationId = activeId;
      return;
    }
    _selectedApplicationId = records.first.application.applicationId;
  }
}

String _stageForFilter(CareerProjectFilter filter) {
  return switch (filter) {
    CareerProjectFilter.all => "",
    CareerProjectFilter.draft => "draft",
    CareerProjectFilter.readyToApply => "ready_to_apply",
    CareerProjectFilter.applied => "applied",
    CareerProjectFilter.interviewing => "interviewing",
    CareerProjectFilter.paused => "paused",
  };
}
