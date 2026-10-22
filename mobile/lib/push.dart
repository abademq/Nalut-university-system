import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'api/api_client.dart';
import 'firebase_options.dart';

/// Push notifications. Optional by design: if Firebase is not configured for the
/// platform, or the user refuses permission, the app keeps working with the in-app inbox.
/// A notification the user tapped in the phone's notification tray.
class PushOpen {
  const PushOpen({this.notificationId, this.link, this.title, this.body, this.tone});
  final int? notificationId;
  final String? link;
  final String? title;
  final String? body;
  final String? tone; // chosen by the university administration

  factory PushOpen.fromData(Map<String, dynamic> data, {String? title, String? body}) => PushOpen(
        notificationId: int.tryParse('${data['notification_id'] ?? ''}'),
        link: (data['link'] as String?)?.isEmpty == true ? null : data['link'] as String?,
        title: title,
        body: body,
        tone: data['tone'] as String?,
      );
}

/// Plays a bundled tone and opens the phone's notification settings (MainActivity.kt).
class NativeNotifications {
  static const _channel = MethodChannel('nus/notifications');

  static Future<void> playTone(String? tone) async {
    try {
      await _channel.invokeMethod('playTone', {'tone': tone ?? 'chime'});
    } catch (_) {}
  }

  /// The start-up sound (a launch sound or a notification tone); "none" plays nothing.
  static Future<void> playLaunchSound(String sound) async {
    if (sound == 'none' || sound.isEmpty) return;
    try {
      await _channel.invokeMethod('playLaunchSound', {'sound': sound});
    } catch (_) {}
  }

  static Future<void> openSettings() async {
    try {
      await _channel.invokeMethod('openAppSettings');
    } catch (_) {}
  }
}

abstract class PushService {
  Future<void> start(ApiClient api,
      {void Function(PushOpen message)? onForeground,
      VoidCallback? onMessage,
      void Function(PushOpen open)? onOpened});
  Future<void> stop(ApiClient api);

  /// Where registration got to, shown on the notification settings screen.
  String get status;
}

// Uses the classic FCM registration token, which the server sends to through the
// HTTP v1 `message.token` field. firebase_messaging 17 deprecates it in favour of
// installation-ID registration; migrate both sides together when the server supports it.
// ignore_for_file: deprecated_member_use

class FirebasePushService implements PushService {
  String? _token;
  final List<StreamSubscription<dynamic>> _subs = [];
  @override
  String status = 'not_started'; // no_firebase | denied | registered | error: …

  String get _platform => defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android';

  @override
  Future<void> start(ApiClient api,
      {void Function(PushOpen message)? onForeground,
      VoidCallback? onMessage,
      void Function(PushOpen open)? onOpened}) async {
    try {
      final options = DefaultFirebaseOptions.currentPlatform;
      if (options == null) {
        status = 'no_firebase';
        return;
      }
      if (Firebase.apps.isEmpty) await Firebase.initializeApp(options: options);
      final messaging = FirebaseMessaging.instance;
      final perm = await messaging.requestPermission();
      if (perm.authorizationStatus == AuthorizationStatus.denied) {
        status = 'denied';
        return;
      }

      Future<void> register(String token) async {
        _token = token;
        await api.post('/api/me/devices', {'platform': _platform, 'token': token});
      }

      final token = await messaging.getToken();
      if (token == null) {
        status = 'error: لم يُصدر Firebase رمزاً لهذا الهاتف';
        return;
      }
      await register(token);
      status = 'registered';
      await _cancel();
      _subs.add(messaging.onTokenRefresh.listen((t) => register(t).catchError((_) {})));
      // Android/iOS show notifications themselves when the app is in the background;
      // while it is open the system stays silent, so we play the tone and show a banner.
      _subs.add(FirebaseMessaging.onMessage.listen((m) {
        onMessage?.call();
        final n = m.notification;
        if (n != null) {
          NativeNotifications.playTone(m.data['tone'] as String?);
          onForeground?.call(PushOpen.fromData(m.data, title: n.title, body: n.body));
        }
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
      status = 'error: $e';
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
