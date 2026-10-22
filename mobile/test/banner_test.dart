import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nalut_university/api/api_client.dart';
import 'package:nalut_university/api/token_store.dart';
import 'package:nalut_university/state/session.dart';
import 'package:nalut_university/widgets/banners.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('pinned banners are drawn above the content', (tester) async {
    final client = MockClient((req) async => http.Response.bytes(
        utf8.encode(jsonEncode([
          {'id': 1, 'title': 'موعد الامتحانات النصفية', 'body': 'تبدأ يوم الأحد', 'level': 'important', 'link': null},
          {'id': 2, 'title': 'تنبيه عاجل', 'body': '', 'level': 'urgent', 'link': null},
        ])),
        200,
        headers: {'content-type': 'application/json'}));
    final store = MemoryTokenStore();
    final session = Session(api: ApiClient(store: store, baseUrl: 'https://u.example', client: client), store: store);
    await tester.pumpWidget(ChangeNotifierProvider.value(
      value: session,
      child: const MaterialApp(home: Directionality(textDirection: TextDirection.rtl, child: Scaffold(body: BannerStrip()))),
    ));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('موعد الامتحانات النصفية'), findsOneWidget);
    expect(find.text('تنبيه عاجل'), findsOneWidget);
  });
}
