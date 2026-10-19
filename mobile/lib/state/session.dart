import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../api/token_store.dart';
import '../config.dart';

enum SessionStatus { loading, signedOut, signedIn }

class Session extends ChangeNotifier {
  Session({required this.api, required this.store}) {
    api.onSessionExpired = _expired;
  }

  final ApiClient api;
  final TokenStore store;
  SessionStatus status = SessionStatus.loading;
  Map<String, dynamic>? user;
  int unread = 0;

  String get role => user?['role'] as String? ?? '';
  bool get isStudent => role == 'student';
  bool get isInstructor => role == 'teacher' || role == 'assistant';
  bool get canCheckIn => role.isNotEmpty && role != 'platform_admin';
  String get firstName => (user?['full_name'] as String? ?? '').split(' (').first;

  Future<void> start() async {
    api.baseUrl = await store.read(StoreKeys.serverUrl) ?? defaultServerUrl;
    final profile = await api.restore();
    _set(profile);
  }

  Future<void> setServer(String url) async {
    var clean = url.trim().replaceAll(RegExp(r'/+$'), '');
    if (!clean.startsWith('http')) clean = 'https://$clean';
    api.baseUrl = clean;
    await store.write(StoreKeys.serverUrl, clean);
    notifyListeners();
  }

  /// Returns null when signed in, otherwise 'mfa_required' or 'mfa_setup_required'.
  Future<String?> login(String identifier, String password, {String? mfaCode}) async {
    final data = await api.login(identifier, password, mfaCode: mfaCode);
    if (data['mfa_required'] == true) return 'mfa_required';
    if (data['mfa_setup_required'] == true) return 'mfa_setup_required';
    _set(data['user'] as Map<String, dynamic>?);
    return null;
  }

  Future<void> refreshUnread() async {
    try {
      final data = await api.get('/api/notifications?limit=1') as Map<String, dynamic>;
      unread = (data['unread'] as num?)?.toInt() ?? 0;
      notifyListeners();
    } catch (_) {}
  }

  Future<void> logout() async {
    await api.logout();
    _set(null);
  }

  void _expired() => _set(null);

  void _set(Map<String, dynamic>? profile) {
    user = profile;
    status = profile == null ? SessionStatus.signedOut : SessionStatus.signedIn;
    if (profile == null) unread = 0;
    notifyListeners();
    if (profile != null) refreshUnread();
  }
}
