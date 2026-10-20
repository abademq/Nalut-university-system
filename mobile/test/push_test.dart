import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nalut_university/api/api_client.dart';
import 'package:nalut_university/api/token_store.dart';
import 'package:nalut_university/push.dart';
import 'package:nalut_university/state/session.dart';

class FakePush implements PushService {
  final events = <String>[];
  bool fail = false;

  @override
  Future<void> start(ApiClient api,
      {void Function(String, String)? onForeground, VoidCallback? onMessage, void Function(PushOpen)? onOpened}) async {
    events.add('start:${api.hasAccessToken}');
    if (fail) throw Exception('no google play services');
  }

  @override
  Future<void> stop(ApiClient api) async => events.add('stop:${api.hasAccessToken}');
}

http.Response jsonRes(Object body, [int status = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

Session makeSession(FakePush push) {
  final store = MemoryTokenStore();
  final client = MockClient((req) async => switch (req.url.path) {
        '/api/auth/login' => jsonRes({'access_token': 'A', 'refresh_token': 'R', 'user': {'id': 1, 'role': 'student', 'full_name': 'x'}}),
        '/api/notifications' => jsonRes({'unread': 0, 'items': []}),
        _ => jsonRes({'ok': true}),
      });
  return Session(api: ApiClient(store: store, baseUrl: 'https://u.example', client: client), store: store, push: push);
}

void main() {
  test('push registers after login and unregisters before the session ends', () async {
    final push = FakePush();
    final s = makeSession(push);
    await s.login('a@b.ly', 'pw');
    await s.logout();
    expect(push.events, ['start:true', 'stop:true']);
    expect(s.status, SessionStatus.signedOut);
  });

  test('startup never hangs when secure storage fails: falls back to the login screen', () async {
    final s = Session(api: ApiClient(store: BrokenStore(), baseUrl: 'https://u.example'), store: BrokenStore());
    expect(s.status, SessionStatus.loading);
    await s.start();
    expect(s.status, SessionStatus.signedOut);
  });

  test('startup with an unreachable server falls back to the login screen', () async {
    final store = MemoryTokenStore()..values[StoreKeys.refreshToken] = 'R';
    final api = ApiClient(store: store, baseUrl: 'https://u.example',
        client: MockClient((req) async => throw http.ClientException('no route')));
    final s = Session(api: api, store: store);
    await s.start();
    expect(s.status, SessionStatus.signedOut);
    expect(store.values[StoreKeys.refreshToken], 'R'); // kept: it may work once the network is back
  });

  test('a failing push service never blocks sign-in', () async {
    final push = FakePush()..fail = true;
    final s = makeSession(push);
    await s.login('a@b.ly', 'pw');
    expect(s.status, SessionStatus.signedIn);
  });
}

class BrokenStore implements TokenStore {
  @override
  Future<String?> read(String key) async => throw Exception('keystore unavailable');

  @override
  Future<void> write(String key, String? value) async {}
}
