import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../api/token_store.dart';
import '../config.dart';
import '../push.dart';

enum SessionStatus { loading, signedOut, signedIn }

class Session extends ChangeNotifier {
  Session({required this.api, required this.store, this.push}) {
    api.onSessionExpired = _expired;
  }

  final ApiClient api;
  final TokenStore store;
  final PushService? push;

  /// Shows a banner for notifications that arrive while the app is open.
  void Function(PushOpen message)? onForegroundMessage;
  SessionStatus status = SessionStatus.loading;

  /// A tapped phone notification waiting for the home screen to open its page.
  PushOpen? pendingOpen;
  Map<String, dynamic>? user;
  int unread = 0;

  String get role => user?['role'] as String? ?? '';
  bool get isStudent => role == 'student';
  bool get isInstructor => role == 'teacher' || role == 'assistant';
  bool get isAdmin => role == 'faculty_admin' || role == 'university_admin';
  /// A configurable capability from the permission matrix (the profile's `can` list).
  bool can(String capability) => (user?['can'] as List?)?.contains(capability) ?? false;
  bool get canCheckIn => role.isNotEmpty && role != 'platform_admin';
  String get firstName => (user?['full_name'] as String? ?? '').split(' (').first;

  /// Restores a saved session. Never leaves the app on the loading screen: any failure
  /// (unreadable secure storage, slow network) falls back to the login screen.
  Future<void> start() async {
    Map<String, dynamic>? profile;
    try {
      api.baseUrl = await store.read(StoreKeys.serverUrl) ?? defaultServerUrl;
      profile = await api.restore().timeout(const Duration(seconds: 15));
    } catch (e) {
      debugPrint('session restore failed: $e');
      profile = null;
    }
    _set(profile);
  }

  Future<void> setServer(String url) async {
    var clean = url.trim().replaceAll(RegExp(r'/+$'), '');
    if (!clean.startsWith('http')) clean = 'https://$clean';
    api.baseUrl = clean;
    await store.write(StoreKeys.serverUrl, clean);
    notifyListeners();
  }

  /// Returns null when signed in, otherwise the server's next step: `mfa_required` (with
  /// `method` totp|sms) or `mfa_setup_required` (with `setup_token`, `methods`).
  Future<Map<String, dynamic>?> login(String identifier, String password, {String? mfaCode}) async {
    final data = await api.login(identifier, password, mfaCode: mfaCode);
    if (data['user'] == null) return data;
    _set(data['user'] as Map<String, dynamic>?);
    return null;
  }

  /// Finishes a sign-in that ended with second-factor enrolment.
  void completeLogin(Map<String, dynamic> data) => _set(data['user'] as Map<String, dynamic>?);

  Future<void> refreshUnread() async {
    try {
      final data = await api.get('/api/notifications?limit=1') as Map<String, dynamic>;
      unread = (data['unread'] as num?)?.toInt() ?? 0;
      notifyListeners();
    } catch (_) {}
  }

  /// Marks a notification read by its id (from a push payload) and refreshes the badge.
  Future<void> markNotificationRead(int id) async {
    try {
      await api.post('/api/notifications/by-id/$id/read');
    } catch (_) {}
    await refreshUnread();
  }

  /// Reloads the signed-in user's profile (after changing security settings).
  Future<void> reloadProfile() async {
    try {
      user = await api.get('/api/me') as Map<String, dynamic>;
      notifyListeners();
    } catch (_) {}
  }

  /// Asks the home screen to open a notification's page.
  void openLater(PushOpen open) {
    pendingOpen = open;
    notifyListeners();
  }

  /// Registers this phone for push again (after allowing notifications, or if it failed).
  Future<String> registerPush() async {
    final p = push;
    if (p == null) return 'no_firebase';
    await p.start(api,
        onMessage: refreshUnread,
        onForeground: (m) => onForegroundMessage?.call(m),
        onOpened: (o) {
          pendingOpen = o;
          notifyListeners();
        }).catchError((Object e) => debugPrint('push unavailable: $e'));
    notifyListeners(); // the notifications tab shows a hint while the phone blocks them
    return p.status;
  }

  Future<void> logout() async {
    // needs the session still valid to unregister this phone
    await push?.stop(api).catchError((Object _) {});
    await api.logout();
    _set(null);
  }

  void _expired() => _set(null);

  void _set(Map<String, dynamic>? profile) {
    user = profile;
    status = profile == null ? SessionStatus.signedOut : SessionStatus.signedIn;
    if (profile == null) {
      unread = 0;
      pendingOpen = null;
    }
    notifyListeners();
    if (profile != null) {
      refreshUnread();
      // Push is optional: a failure here must never affect the signed-in session.
      push
          ?.start(api,
              onMessage: refreshUnread,
              onForeground: (m) => onForegroundMessage?.call(m),
              onOpened: (o) {
                pendingOpen = o;
                notifyListeners();
              })
          .catchError((Object e) => debugPrint('push unavailable: $e'));
    }
  }
}
