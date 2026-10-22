// Runs the app's API client against a real backend.
//   NUS_TEST_SERVER=http://127.0.0.1:8000 flutter test test/contract_test.dart
// Skipped when NUS_TEST_SERVER is not set.
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:nalut_university/api/api_client.dart';
import 'package:nalut_university/api/token_store.dart';

void main() {
  final server = Platform.environment['NUS_TEST_SERVER'];
  final skip = server == null ? 'set NUS_TEST_SERVER to run' : null;

  Future<ApiClient> signIn(String email) async {
    final api = ApiClient(store: MemoryTokenStore(), baseUrl: server!);
    await api.login(email, 'Demo@12345');
    return api;
  }

  test('student screens load from the real API', () async {
    final api = await signIn('s.ali@nalut.edu.ly');
    final insights = await api.get('/api/me/insights') as Map;
    expect(insights.keys, containsAll(['attention', 'due_soon']));
    final assignments = await api.get('/api/assignments') as List;
    expect(assignments.first, contains('my_status'));
    final detail = await api.get('/api/assignments/${assignments.first['id']}') as Map;
    expect(detail, contains('allowed_extensions'));
    final grades = await api.get('/api/me/grades') as List;
    expect(grades.first, contains('published'));
    final att = await api.get('/api/me/attendance') as Map;
    expect(att['courses'].first, contains('absence_percent'));
    final inbox = await api.get('/api/notifications?limit=5') as Map;
    expect(inbox, contains('unread'));
    final contacts = await api.get('/api/contacts') as List;
    expect(contacts.every((c) => ['teacher', 'assistant'].contains(c['role'])), isTrue);
  }, skip: skip);

  test('refresh token rotates through the mobile flow', () async {
    final store = MemoryTokenStore();
    final api = ApiClient(store: store, baseUrl: server!);
    await api.login('s.ali@nalut.edu.ly', 'Demo@12345');
    final first = store.values[StoreKeys.refreshToken];
    expect(first, isNotNull);
    final user = await api.restore();
    expect(user?['role'], 'student');
    expect(store.values[StoreKeys.refreshToken], isNot(first));
  }, skip: skip);

  test('full check-in: teacher opens a session, student scans the rotating QR', () async {
    final teacher = await signIn('t.ahmed@nalut.edu.ly');
    final courses = await teacher.get('/api/courses') as List;
    final cs101 = courses.firstWhere((c) => c['code'] == 'CS101');
    final session = await teacher.post('/api/attendance/sessions', {'course_id': cs101['id']}) as Map;
    final qr = await teacher.get('/api/attendance/sessions/${session['id']}/qr') as Map;

    final student = await signIn('student3@nalut.edu.ly');
    final store = MemoryTokenStore();
    final req = await student.get('/api/attendance/sessions/${session['id']}/requirements') as Map;
    expect(req['require_selfie'], isFalse);
    final result = await student.multipart('/api/attendance/check-in',
        fields: {'payload': qr['payload'] as String, 'nonce': newNonce()},
        headers: {'X-Device-Id': await deviceIdFrom(store)}) as Map;
    expect(result['status'], 'present');

    // a second scan of the same session is refused
    await expectLater(
      student.multipart('/api/attendance/check-in',
          fields: {'payload': qr['payload'] as String, 'nonce': newNonce()},
          headers: {'X-Device-Id': await deviceIdFrom(store)}),
      throwsA(isA<ApiException>().having((e) => e.status, 'status', 409)),
    );
  }, skip: skip);

  test('student uploads a submission like the app does', () async {
    final api = await signIn('student2@nalut.edu.ly');
    final list = await api.get('/api/assignments') as List;
    final project = list.firstWhere((a) => (a['title'] as String).contains('آلة حاسبة'));
    final pdf = '%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'.codeUnits;
    final res = await api.multipart('/api/assignments/${project['id']}/submission',
        fields: {'final': 'true', 'note': 'من التطبيق'},
        files: [UploadFile('upload', 'calc.pdf', Uint8List.fromList(pdf))]) as Map;
    expect(res['status'], 'submitted');
  }, skip: skip);

  test('request: student files one with a document, the registrar processes it', () async {
    final student = await signIn('s.ali@nalut.edu.ly');
    final types = await student.get('/api/requests/types') as Map;
    expect(types['types'], contains('enrollment_certificate'));
    final created = await student.multipart('/api/requests',
        fields: {'type': 'enrollment_certificate', 'subject': 'إفادة للبنك', 'details': ''},
        files: [UploadFile('upload', 'id.pdf', Uint8List.fromList('%PDF-1.4\n%%EOF\n'.codeUnits))]) as Map;
    final staff = await signIn('registrar@nalut.edu.ly');
    final inbox = await staff.get('/api/requests?scope=inbox') as List;
    expect(inbox.any((r) => r['id'] == created['id']), isTrue);
    final done = await staff.post('/api/requests/${created['id']}/actions', {'action': 'approved', 'comment': ''}) as Map;
    expect(done['status'], 'approved');
    final events = (await student.get('/api/requests/${created['id']}') as Map)['events'] as List;
    final file = events.firstWhere((e) => e['file'] != null)['file'];
    expect((await staff.getBytes('/api/files/${file['id']}')).isNotEmpty, isTrue);
  }, skip: skip);

  test('grade entry: teacher saves scores like the app does', () async {
    final teacher = await signIn('t.ahmed@nalut.edu.ly');
    final courses = await teacher.get('/api/courses') as List;
    Map? sheet;
    for (final c in courses) {
      final g = await teacher.get('/api/courses/${c['id']}/grades') as Map;
      if (g['result']['status'] == 'draft' && (g['components'] as List).isNotEmpty) {
        sheet = g;
        break;
      }
    }
    expect(sheet, isNotNull);
    final st = (sheet!['students'] as List).first;
    final comp = (sheet['components'] as List).first;
    final had = st['scores']['${comp['id']}'] != null;
    final r = await teacher.put('/api/courses/${sheet['course']['id']}/grades', {
      'reason': had ? 'تصحيح خطأ إدخال' : '',
      'entries': [{'student_id': st['id'], 'component_id': comp['id'], 'score': 1}],
    }) as Map;
    expect(r['changed'], anyOf(0, 1));
  }, skip: skip);

  test('password change keeps this device signed in; dashboard hand-off link', () async {
    final api = await signIn('student2@nalut.edu.ly');
    final r = await api.post('/api/auth/password/change',
        {'current_password': 'Demo@12345', 'new_password': 'NewPass2026x'}) as Map<String, dynamic>;
    await api.acceptSession(r);
    expect(await api.refresh(), isTrue);
    expect((await api.get('/api/me') as Map)['email'], 'student2@nalut.edu.ly');
    final h = await api.post('/api/auth/handoff/start') as Map;
    expect(h['path'], startsWith('/#/handoff/'));
  }, skip: skip);
}
