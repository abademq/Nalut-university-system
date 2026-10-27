import 'package:flutter_test/flutter_test.dart';
import 'package:nalut_university/api/api_client.dart';
import 'package:nalut_university/widgets/common.dart';

void main() {
  tearDown(() => ApiClient.clockSkew = Duration.zero);

  String ago(Duration d, {bool past = false}) =>
      fmtRelative(DateTime.now().toUtc().subtract(d).toIso8601String(), past: past);

  test('relative times read naturally in Arabic', () {
    expect(ago(const Duration(seconds: 20)), 'الآن');
    expect(ago(const Duration(minutes: 1, seconds: 5)), 'منذ دقيقة');
    expect(ago(const Duration(minutes: 2, seconds: 5)), 'منذ دقيقتين');
    expect(ago(const Duration(minutes: 5, seconds: 5)), 'منذ 5 دقائق');
    expect(ago(const Duration(hours: 1, minutes: 1)), 'منذ ساعة');
    expect(ago(const Duration(hours: 13)), 'منذ 13 ساعة');
    expect(ago(const Duration(days: 3, hours: 1)), 'منذ 3 أيام');
    expect(ago(const Duration(hours: -2, minutes: -1)), 'خلال ساعتين');
  });

  test('a phone whose clock is an hour behind still shows a new notice as just now', () {
    // the server is one hour ahead of this phone (wrong time zone on the phone)
    ApiClient.clockSkew = const Duration(hours: 1);
    final justNow = DateTime.now().toUtc().add(const Duration(hours: 1)).toIso8601String();
    expect(fmtRelative(justNow, past: true), 'الآن');
    expect(fmtRelative(justNow), 'الآن');
    // and something past never reads as the future
    ApiClient.clockSkew = Duration.zero;
    expect(fmtRelative(justNow, past: true), 'الآن');
  });
}
