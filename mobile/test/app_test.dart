import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nalut_university/api/api_client.dart';
import 'package:nalut_university/api/token_store.dart';
import 'package:nalut_university/main.dart';
import 'package:nalut_university/state/session.dart';

http.Response jsonRes(Object body, [int status = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

const student = {
  'id': 11,
  'full_name': 'علي محمد الطاهر',
  'role': 'student',
  'code': '2023001',
  'faculty': {'id': 1, 'name': 'كلية تقنية المعلومات'},
};

MockClient fakeServer() => MockClient((req) async {
      switch (req.url.path) {
        case '/api/auth/login':
          final body = jsonDecode(req.body);
          if (body['password'] != 'Demo@12345') return jsonRes({'detail': 'بيانات الدخول غير صحيحة'}, 401);
          return jsonRes({'access_token': 'A', 'refresh_token': 'R', 'user': student});
        case '/api/notifications':
          return jsonRes({'unread': 3, 'items': []});
        case '/api/me/insights':
          return jsonRes({
            'attention': [],
            'due_soon': [
              {'id': 5, 'title': 'مشروع: آلة حاسبة', 'course': 'مقدمة في البرمجة', 'due_at': '2099-01-01T10:00:00+00:00'}
            ]
          });
        case '/api/me/schedule':
          return jsonRes([]);
        case '/api/me/attendance':
          return jsonRes({
            'courses': [
              {'course': {'id': 1, 'title': 'مقدمة في البرمجة'}, 'absence_percent': 10.0, 'sessions': 6, 'present': 5, 'late': 0, 'absent': 1}
            ],
            'records': []
          });
        case '/api/assignments':
          return jsonRes([
            {
              'id': 5,
              'title': 'مشروع: آلة حاسبة',
              'kind': 'project',
              'course_code': 'CS101',
              'due_at': '2099-01-01T10:00:00+00:00',
              'allow_late': true,
              'max_score': 20,
              'my_status': 'not_started',
              'my_score': null,
            }
          ]);
      }
      return jsonRes({'detail': 'not found'}, 404);
    });

Future<Session> pumpApp(WidgetTester tester) async {
  final store = MemoryTokenStore();
  final session = Session(api: ApiClient(store: store, baseUrl: 'https://u.example', client: fakeServer()), store: store);
  await tester.runAsync(session.start);
  await tester.pumpWidget(UniversityApp(session: session));
  await tester.pumpAndSettle();
  return session;
}

void main() {
  testWidgets('wrong password shows the server error', (tester) async {
    await pumpApp(tester);
    expect(find.text('منصة الجامعة الذكية'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('identifier')), 's.ali@nalut.edu.ly');
    await tester.enterText(find.byKey(const Key('password')), 'wrong');
    await tester.tap(find.byKey(const Key('login')));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await tester.pumpAndSettle();
    expect(find.text('بيانات الدخول غير صحيحة'), findsOneWidget);
  });

  testWidgets('student logs in and lands on the home screen (RTL, Arabic)', (tester) async {
    final session = await pumpApp(tester);
    await tester.enterText(find.byKey(const Key('identifier')), 's.ali@nalut.edu.ly');
    await tester.enterText(find.byKey(const Key('password')), 'Demo@12345');
    await tester.tap(find.byKey(const Key('login')));
    for (var i = 0; i < 5; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await tester.pump();
    }
    expect(session.status, SessionStatus.signedIn);
    expect(find.text('مرحباً، علي محمد الطاهر'), findsOneWidget);
    expect(find.text('تسجيل الحضور بمسح الرمز'), findsOneWidget);
    expect(find.text('مشروع: آلة حاسبة'), findsOneWidget);
    expect(find.text('3'), findsWidgets); // unread badge / KPI
    expect(Directionality.of(tester.element(find.text('مرحباً، علي محمد الطاهر'))), TextDirection.rtl);
    // student navigation tabs
    for (final label in ['الرئيسية', 'المهام', 'الحضور', 'الإشعارات', 'المزيد']) {
      expect(find.text(label), findsWidgets);
    }
  });
}
