import 'package:flutter_test/flutter_test.dart';
import 'package:nalut_university/links.dart';
import 'package:nalut_university/push.dart';
import 'package:nalut_university/screens/send_notification_screen.dart';

void main() {
  const base = 'https://u.example';

  test('notification links open the matching app page', () {
    expect(resolveLink('#/assignments/7', baseUrl: base, role: 'student'), const AppPage('assignment', 7));
    expect(resolveLink('#/assignments', baseUrl: base, role: 'teacher'), const AppPage('assignments'));
    expect(resolveLink('#/messages/12', baseUrl: base, role: 'student'), const AppPage('thread', 12));
    expect(resolveLink('#/grades', baseUrl: base, role: 'student'), const AppPage('grades'));
    expect(resolveLink('#/results', baseUrl: base, role: 'faculty_admin'), const AppPage('results'));
    expect(resolveLink('#/attendance', baseUrl: base, role: 'student'), const AppPage('attendance'));
    expect(resolveLink('#/publications/4', baseUrl: base, role: 'student'), const AppPage('publication', 4));
  });

  test('pages that exist only on the web open the browser', () {
    final t = resolveLink('#/grades', baseUrl: base, role: 'teacher');
    expect(t, isA<WebPage>());
    expect((t as WebPage).url, '$base/#/grades');
    expect(resolveLink('https://x.ly/a', baseUrl: base, role: 'student'), isA<WebPage>());
  });

  test('empty or unsafe links have no target', () {
    expect(resolveLink(null, baseUrl: base, role: 'student'), isA<NoTarget>());
    expect(resolveLink('', baseUrl: base, role: 'student'), isA<NoTarget>());
    expect(resolveLink('#/notifications', baseUrl: base, role: 'student'), isA<NoTarget>());
    expect(resolveLink('javascript:alert(1)', baseUrl: base, role: 'student'), isA<NoTarget>());
  });

  test('push payload data is parsed into an open request', () {
    final o = PushOpen.fromData({'notification_id': '42', 'link': '#/messages/3', 'category': 'message'}, title: 't');
    expect(o.notificationId, 42);
    expect(o.link, '#/messages/3');
    expect(PushOpen.fromData({'link': ''}).link, isNull);
  });

  test('notification categories follow the university permission matrix', () {
    expect(sendableCategories({'role': 'staff', 'can': ['notify.announcement']}), ['announcement']);
    expect(sendableCategories({'role': 'teacher', 'can': <String>[]}), isEmpty);
    expect(canSendNotifications({'role': 'student', 'can': <String>[]}), isFalse);
    expect(sendableCategories({'role': 'university_admin'}).length, 4);
    // older server without `can`: role table
    expect(sendableCategories({'role': 'staff'}), ['admin_notice']);
  });
}
