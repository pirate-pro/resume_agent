import 'dart:async';

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
  bool _isLoadingNotes = false;
  bool _hasLoadedAssetLibrary = false;
  bool _isLoadingAssetLibrary = false;
  String? _error;
  String? _notesError;
  String? _assetLibraryError;
  CareerWorkbenchTab _activeTab = CareerWorkbenchTab.projects;
  CareerProjectFilter _projectFilter = CareerProjectFilter.all;
  String? _selectedApplicationId;
  String? _selectedNoteId;
  CareerWorkbenchListView? _workbench;
  List<NoteView> _noteList = const [];
  List<ResumeProfileView> _resumeProfiles = const [];
  List<CareerProfileView> _careerProfiles = const [];
  List<JDAnalysisView> _jdAnalyses = const [];
  List<JobFitReportView> _jobFitReports = const [];
  List<ResumeVersionView> _resumeVersions = const [];
  final Map<String, CareerApplicationWorkbenchView> _details = {};
  final Map<String, NoteView> _notes = {};
  final Set<String> _loadingApplicationIds = {};
  final Map<String, String> _detailErrors = {};

  CareerWorkbenchProvider(this._api);

  bool get hasLoaded => _hasLoaded;
  bool get isLoading => _isLoading;
  bool get isRefreshing => _isRefreshing;
  bool get isLoadingNotes => _isLoadingNotes;
  bool get hasLoadedAssetLibrary => _hasLoadedAssetLibrary;
  bool get isLoadingAssetLibrary => _isLoadingAssetLibrary;
  String? get error => _error;
  String? get notesError => _notesError;
  String? get assetLibraryError => _assetLibraryError;
  CareerWorkbenchTab get activeTab => _activeTab;
  CareerProjectFilter get projectFilter => _projectFilter;
  String? get selectedApplicationId => _selectedApplicationId;
  String? get selectedNoteId => _selectedNoteId;
  CareerWorkbenchListView? get workbench => _workbench;
  List<NoteView> get notes {
    final records = [..._noteList]
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return records;
  }

  List<CareerApplicationSummaryView> get applications {
    final records = [...?_workbench?.applications]
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return records;
  }

  List<ResumeProfileView> get resumeProfiles {
    final records = [..._resumeProfiles]
      ..sort((a, b) => b.meta.updatedAt.compareTo(a.meta.updatedAt));
    return records;
  }

  List<CareerProfileView> get careerProfiles {
    final records = [..._careerProfiles]
      ..sort((a, b) => b.meta.updatedAt.compareTo(a.meta.updatedAt));
    return records;
  }

  List<JDAnalysisView> get jdAnalyses {
    final records = [..._jdAnalyses]
      ..sort((a, b) => b.meta.updatedAt.compareTo(a.meta.updatedAt));
    return records;
  }

  List<JobFitReportView> get jobFitReports {
    final records = [..._jobFitReports]
      ..sort((a, b) => b.meta.updatedAt.compareTo(a.meta.updatedAt));
    return records;
  }

  List<ResumeVersionView> get resumeVersions {
    final records = [..._resumeVersions]
      ..sort((a, b) => b.meta.updatedAt.compareTo(a.meta.updatedAt));
    return records;
  }

  int get resumeLibraryCount =>
      _resumeProfiles.length + _careerProfiles.length + _resumeVersions.length;

  int get jobMatchLibraryCount => _jdAnalyses.length + _jobFitReports.length;

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
      if (_hasLoadedAssetLibrary) {
        await loadAssetLibrary(force: true);
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
    if (tab == CareerWorkbenchTab.notes) {
      unawaited(loadNotes());
    }
    if (tab == CareerWorkbenchTab.resumes || tab == CareerWorkbenchTab.jobs) {
      unawaited(loadAssetLibrary());
    }
    notifyListeners();
  }

  Future<void> loadAssetLibrary({bool force = false}) async {
    if (_isLoadingAssetLibrary) return;
    if (_hasLoadedAssetLibrary && !force) return;
    _isLoadingAssetLibrary = true;
    _assetLibraryError = null;
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
      _hasLoadedAssetLibrary = true;
    } catch (error, stackTrace) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          library: "career workbench",
          context: ErrorDescription("load career asset library"),
        ),
      );
      _assetLibraryError = error.toString();
    } finally {
      _isLoadingAssetLibrary = false;
      notifyListeners();
    }
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

  Future<NoteView> loadNote(String noteId, {bool force = false}) async {
    final normalized = noteId.trim();
    if (normalized.isEmpty) {
      throw ArgumentError.value(noteId, "noteId", "noteId cannot be empty");
    }
    if (_notes.containsKey(normalized) && !force) {
      return _notes[normalized]!;
    }
    final note = await _api.getNote(noteId: normalized);
    _notes[normalized] = note;
    return note;
  }

  Future<void> loadNotes({bool force = false}) async {
    if (_isLoadingNotes) return;
    if (_noteList.isNotEmpty && !force) return;
    _isLoadingNotes = true;
    _notesError = null;
    notifyListeners();
    try {
      final records = await _api.listNotes();
      _noteList = records;
      for (final note in records) {
        _notes[note.noteId] = note;
      }
      if (_selectedNoteId == null && records.isNotEmpty) {
        _selectedNoteId = records.first.noteId;
      }
    } catch (error, stackTrace) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stackTrace,
          library: "career workbench",
          context: ErrorDescription("load notes"),
        ),
      );
      _notesError = error.toString();
    } finally {
      _isLoadingNotes = false;
      notifyListeners();
    }
  }

  Future<NoteView> createNote({
    required String sourceSessionId,
    required String title,
    required String bodyMarkdown,
    required String summary,
    required List<String> tags,
    String noteType = "note",
    String? sourceArtifactId,
    List<String> evidenceRefs = const [],
    List<Map<String, dynamic>> sourceRefs = const [],
    String? relatedApplicationId,
  }) async {
    final note = await _api.createNote(
      sourceSessionId: sourceSessionId.trim(),
      sourceArtifactId: sourceArtifactId,
      evidenceRefs: evidenceRefs,
      title: title.trim(),
      bodyMarkdown: bodyMarkdown.trim(),
      bodyFormat: "markdown",
      noteType: _normalizeNoteType(noteType),
      tags: tags,
      sourceRefs: sourceRefs,
      relatedApplicationId: relatedApplicationId,
      summary: summary.trim(),
    );
    _notes[note.noteId] = note;
    _selectedNoteId = note.noteId;
    await loadNotes(force: true);
    final selectedId = _selectedApplicationId;
    if (selectedId != null && selectedId.isNotEmpty) {
      await loadApplicationDetail(selectedId, force: true);
    }
    return note;
  }

  Future<NoteView> updateNote({
    required String noteId,
    required String title,
    required String bodyMarkdown,
    required String summary,
    required List<String> tags,
    String noteType = "note",
  }) async {
    final normalized = noteId.trim();
    final note = await _api.updateNote(
      noteId: normalized,
      title: title.trim(),
      bodyMarkdown: bodyMarkdown.trim(),
      bodyFormat: "markdown",
      noteType: _normalizeNoteType(noteType),
      summary: summary.trim(),
      tags: tags,
    );
    _notes[normalized] = note;
    _selectedNoteId = normalized;
    await loadNotes(force: true);
    final selectedId = _selectedApplicationId;
    if (selectedId != null && selectedId.isNotEmpty) {
      await loadApplicationDetail(selectedId, force: true);
    } else {
      notifyListeners();
    }
    return note;
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

String _normalizeNoteType(String value) {
  final normalized = value.trim().toLowerCase();
  if (normalized == "learning" || normalized == "resource") {
    return normalized;
  }
  return "note";
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
