import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nalut_university/api/api_client.dart';
import 'package:nalut_university/api/token_store.dart';

http.Response jsonRes(Object body, [int status = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

void main() {
  test('login keeps the refresh token in secure storage and sends the mobile header', () async {
    final store = MemoryTokenStore();
    late http.Request seen;
    final api = ApiClient(
      store: store,
      baseUrl: 'https://u.example',
      client: MockClient((req) async {
        seen = req;
        return jsonRes({'access_token': 'A1', 'refresh_token': 'R1', 'user': {'id': 1, 'role': 'student'}});
      }),
    );
    final data = await api.login('s@x.ly', 'pw');
    expect(data['user']['id'], 1);
    expect(seen.headers['X-Client'], 'mobile');
    expect(store.values[StoreKeys.refreshToken], 'R1');
    expect(api.hasAccessToken, isTrue);
  });

  test('401 refreshes once and retries with the new access token', () async {
    final store = MemoryTokenStore()..values[StoreKeys.refreshToken] = 'R1';
    final auths = <String?>[];
    final api = ApiClient(
      store: store,
      baseUrl: 'https://u.example',
      client: MockClient((req) async {
        if (req.url.path == '/api/auth/refresh') {
          expect(jsonDecode(req.body)['refresh_token'], 'R1');
          return jsonRes({'access_token': 'A2', 'refresh_token': 'R2', 'user': {'id': 1}});
        }
        auths.add(req.headers['Authorization']);
        return req.headers['Authorization'] == 'Bearer A2' ? jsonRes({'ok': true}) : jsonRes({'detail': 'expired'}, 401);
      }),
    );
    final res = await api.get('/api/me');
    expect(res['ok'], isTrue);
    expect(auths, [null, 'Bearer A2']);
    expect(store.values[StoreKeys.refreshToken], 'R2'); // rotated
  });

  test('expired session calls onSessionExpired and surfaces the server message', () async {
    final store = MemoryTokenStore()..values[StoreKeys.refreshToken] = 'old';
    var expired = false;
    final api = ApiClient(
      store: store,
      baseUrl: 'https://u.example',
      client: MockClient((req) async => jsonRes({'detail': 'انتهت الجلسة'}, 401)),
    )..onSessionExpired = () => expired = true;
    await expectLater(api.get('/api/me'), throwsA(isA<ApiException>().having((e) => e.message, 'message', 'انتهت الجلسة')));
    expect(expired, isTrue);
    expect(store.values.containsKey(StoreKeys.refreshToken), isFalse);
  });

  test('network failures become a readable Arabic error', () async {
    final api = ApiClient(
      store: MemoryTokenStore(),
      baseUrl: 'https://u.example',
      client: MockClient((req) async => throw http.ClientException('down')),
    );
    await expectLater(api.get('/api/health'), throwsA(isA<ApiException>().having((e) => e.status, 'status', 0)));
  });

  test('device id is stable per install and nonces are unique', () async {
    final store = MemoryTokenStore();
    final a = await deviceIdFrom(store);
    expect(a, hasLength(32));
    expect(await deviceIdFrom(store), a);
    expect(newNonce(), isNot(newNonce()));
  });
}
