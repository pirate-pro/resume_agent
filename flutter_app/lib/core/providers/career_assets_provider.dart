import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/api_models.dart';
import '../services/api_service.dart';
import 'chat_provider.dart';

final careerAssetsProvider = ChangeNotifierProvider<CareerAssetsProvider>((ref) {
  return CareerAssetsProvider(ref.read(apiServiceProvider));
});

enum CareerAssetsTab {
  all,
  resumes,
  profiles,
  jobs,
  fitReports,
  versions,
}

class CareerAssetSelection {
  final String recordType;
  final String recordId;
  final String sourceSessionId;
  final Object record;

  const CareerAssetSelection({
    required this.recordType,
    required this.recordId,
    required this.sourceSessionId,
    required this.record,
  });

  factory CareerAssetSelection.fromRecord(Object record) {
    if (record is ResumeProfileView) {
      return CareerAssetSelection(
        recordType: "resume",
        recordId: record.resumeProfileId,
        sourceSessionId: record.meta.sourceSessionId,
        record: record,
      );
    }
    if (record is CareerProfileView) {
      return CareerAssetSelection(
        recordType: "profile",
        recordId: record.careerProfileId,
        sourceSessionId: record.meta.sourceSessionId,
        record: record,
      );
    }
    if (record is JDAnalysisView) {
      return CareerAssetSelection(
        recordType: "job",
        recordId: record.jdAnalysisId,
        sourceSessionId: record.meta.sourceSessionId,
        record: record,
      );
    }
    if (record is JobFitReportView) {
      return CareerAssetSelection(
        recordType: "fit_report",
        recordId: record.jobFitReportId,
        sourceSessionId: record.meta.sourceSessionId,
        record: record,
      );
    }
    if (record is ResumeVersionView) {
      return CareerAssetSelection(
        recordType: "resume_version",
        recordId: record.resumeVersionId,
        sourceSessionId: record.meta.sourceSessionId,
        record: record,
      );
    }
    throw ArgumentError("Unsupported career asset record type.");
  }
}

class CareerAssetsProvider extends ChangeNotifier {
  final ApiService _api;

  bool _hasLoaded = false;
  bool _isLoading = false;
  bool _isRefreshing = false;
  String? _error;
  CareerAssetsTab _activeTab = CareerAssetsTab.all;
  CareerAssetSelection? _selection;
  bool _isPreviewLoading = false;
  String? _previewError;
  SessionArtifactContentView? _preview;

  List<ResumeProfileView> _resumeProfiles = [];
  List<CareerProfileView> _careerProfiles = [];
  List<JDAnalysisView> _jdAnalyses = [];
  List<JobFitReportView> _jobFitReports = [];
  List<ResumeVersionView> _resumeVersions = [];

  CareerAssetsProvider(this._api);

  bool get hasLoaded => _hasLoaded;
  bool get isLoading => _isLoading;
  bool get isRefreshing => _isRefreshing;
  String? get error => _error;
  CareerAssetsTab get activeTab => _activeTab;
  CareerAssetSelection? get selection => _selection;
  bool get isPreviewLoading => _isPreviewLoading;
  String? get previewError => _previewError;
  SessionArtifactContentView? get preview => _preview;

  List<ResumeProfileView> get resumeProfiles =>
      List.unmodifiable(_resumeProfiles);
  List<CareerProfileView> get careerProfiles =>
      List.unmodifiable(_careerProfiles);
  List<JDAnalysisView> get jdAnalyses => List.unmodifiable(_jdAnalyses);
  List<JobFitReportView> get jobFitReports =>
      List.unmodifiable(_jobFitReports);
  List<ResumeVersionView> get resumeVersions =>
      List.unmodifiable(_resumeVersions);

  int get totalCount =>
      _resumeProfiles.length +
      _careerProfiles.length +
      _jdAnalyses.length +
      _jobFitReports.length +
      _resumeVersions.length;

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
      final results = await Future.wait<dynamic>([
        _api.listCareerResumeProfiles(),
        _api.listCareerProfiles(),
        _api.listCareerJobs(),
        _api.listCareerJobFitReports(),
        _api.listCareerResumeVersions(),
      ]);
      _resumeProfiles = results[0] as List<ResumeProfileView>;
      _careerProfiles = results[1] as List<CareerProfileView>;
      _jdAnalyses = results[2] as List<JDAnalysisView>;
      _jobFitReports = results[3] as List<JobFitReportView>;
      _resumeVersions = results[4] as List<ResumeVersionView>;
      _hasLoaded = true;
      _selection = _selectionStillExists() ? _selection : null;
    } catch (error, stackTrace) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          library: "career assets",
          context: ErrorDescription("refresh career assets"),
        ),
      );
      _error = error.toString();
    } finally {
      _isLoading = false;
      _isRefreshing = false;
      notifyListeners();
    }
  }

  void setTab(CareerAssetsTab tab) {
    if (_activeTab == tab) return;
    _activeTab = tab;
    if (!_selectionMatchesTab(_selection, tab)) {
      _selection = null;
      _preview = null;
      _previewError = null;
    }
    notifyListeners();
  }

  void selectRecord(Object record) {
    _selection = CareerAssetSelection.fromRecord(record);
    _preview = null;
    _previewError = null;
    notifyListeners();
  }

  Future<void> previewArtifact({
    required String sourceSessionId,
    required String artifactId,
  }) async {
    final normalizedSessionId = sourceSessionId.trim();
    final normalizedArtifactId = artifactId.trim();
    if (normalizedSessionId.isEmpty || normalizedArtifactId.isEmpty) {
      _previewError = "缺少 artifact 预览所需的会话或 artifact id";
      _preview = null;
      notifyListeners();
      return;
    }

    _isPreviewLoading = true;
    _previewError = null;
    _preview = null;
    notifyListeners();

    try {
      _preview = await _api.readSessionArtifactContent(
        sessionId: normalizedSessionId,
        artifactId: normalizedArtifactId,
      );
    } catch (error, stackTrace) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          library: "career assets",
          context: ErrorDescription("preview career artifact"),
        ),
      );
      _previewError = error.toString();
    } finally {
      _isPreviewLoading = false;
      notifyListeners();
    }
  }

  bool _selectionStillExists() {
    final current = _selection;
    if (current == null) return true;
    return [
      ..._resumeProfiles.map((item) => item.resumeProfileId),
      ..._careerProfiles.map((item) => item.careerProfileId),
      ..._jdAnalyses.map((item) => item.jdAnalysisId),
      ..._jobFitReports.map((item) => item.jobFitReportId),
      ..._resumeVersions.map((item) => item.resumeVersionId),
    ].contains(current.recordId);
  }

  bool _selectionMatchesTab(
    CareerAssetSelection? selection,
    CareerAssetsTab tab,
  ) {
    if (selection == null || tab == CareerAssetsTab.all) return true;
    return switch (tab) {
      CareerAssetsTab.resumes => selection.recordType == "resume",
      CareerAssetsTab.profiles => selection.recordType == "profile",
      CareerAssetsTab.jobs => selection.recordType == "job",
      CareerAssetsTab.fitReports => selection.recordType == "fit_report",
      CareerAssetsTab.versions => selection.recordType == "resume_version",
      CareerAssetsTab.all => true,
    };
  }
}
