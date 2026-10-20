import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'api/api_client.dart';
import 'firebase_options.dart';

/// Push notifications. Optional by design: if Firebase is not configured for the
/// platform, or the user refuses permission, the app keeps working with the in-app inbox.
/// A notification the user tapped in the phone's notification tray.
class PushOpen {
  const PushOpen({this.notificationId, this.link, this.title, this.body});
  final int? notificationId;
  final String? link;
  final String? title;
  final String? body;

  factory PushOpen.fromData(Map<String, dynamic> data, {String? title, String? body}) => PushOpen(
        notificationId: int.tryParse('${data['notification_id'] ?? ''}'),
        link: (data['link'] as String?)?.isEmpty == true ? null : data['link'] as String?,
        title: title,
        body: body,
      );
}

abstract class PushService {
  Future<void> start(ApiClient api,
      {void Function(String title, String body)? onForeground,
      VoidCallback? onMessage,
      void Function(PushOpen open)? onOpened});
  Future<void> stop(ApiClient api);
}

// Uses the classic FCM registration token, which the server sends to through the
// HTTP v1 `message.token` field. firebase_messaging 17 deprecates it in favour of
// installation-ID registration; migrate both sides together when the server supports it.
// ignore_for_file: deprecated_member_use

class FirebasePushService implements PushService {
  String? _token;
  final List<StreamSubscription<dynamic>> _subs = [];

  String get _platform => defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android';

  @override
  Future<void> start(ApiClient api,
      {void Function(String title, String body)? onForeground,
      VoidCallback? onMessage,
      void Function(PushOpen open)? onOpened}) async {
    try {
      final options = DefaultFirebaseOptions.currentPlatform;
      if (options == null) return;
      if (Firebase.apps.isEmpty) await Firebase.initializeApp(options: options);
      final messaging = FirebaseMessaging.instance;
      final perm = await messaging.requestPermission();
      if (perm.authorizationStatus == AuthorizationStatus.denied) return;

      Future<void> register(String token) async {
        _token = token;
        await api.post('/api/me/devices', {'platform': _platform, 'token': token});
      }

      final token = await messaging.getToken();
      if (token != null) await register(token);
      await _cancel();
      _subs.add(messaging.onTokenRefresh.listen((t) => register(t).catchError((_) {})));
      // Android/iOS show notifications themselves when the app is in the background;
      // while it is open we refresh the badge and show a short banner.
      _subs.add(FirebaseMessaging.onMessage.listen((m) {
        onMessage?.call();
        final n = m.notification;
        if (n != null) onForeground?.call(n.title ?? '', n.body ?? '');
      }));
      PushOpen opened(RemoteMessage m) =>
          PushOpen.fromData(m.data, title: m.notification?.title, body: m.notification?.body);
      // Tapped while the app was in the background...
      _subs.add(FirebaseMessaging.onMessageOpenedApp.listen((m) {
        onMessage?.call();
        onOpened?.call(opened(m));
      }));
      // ...or the tap launched the app.
      final initial = await messaging.getInitialMessage();
      if (initial != null) onOpened?.call(opened(initial));
    } catch (e) {
      debugPrint('push disabled: $e');
    }
  }

  @override
  Future<void> stop(ApiClient api) async {
    await _cancel();
    final token = _token;
    _token = null;
    if (token == null) return;
    try {
      await api.post('/api/me/devices/remove', {'token': token});
      await FirebaseMessaging.instance.deleteToken();
    } catch (_) {}
  }

  Future<void> _cancel() async {
    for (final s in _subs) {
      await s.cancel();
    }
    _subs.clear();
  }
}
