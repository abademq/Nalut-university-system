import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _channel = MethodChannel('nus/notifications');

/// The three notification tones (one Android channel each): try each one, change it in the
/// phone's settings, and for administrators a delivery overview.
const tones = [
  ('normal', 'nus_normal', 'الإعلانات العادية', 'نغمة هادئة قصيرة', Icons.notifications_none, AppColors.primary),
  ('important', 'nus_important', 'الإشعارات المهمة', 'ثلاث نغمات صاعدة', Icons.notification_important_outlined,
      AppColors.warning),
  ('urgent', 'nus_urgent', 'التنبيهات العاجلة والإنذارات الرسمية', 'تنبيه متكرر مع اهتزاز أطول',
      Icons.campaign_outlined, AppColors.danger),
];

class NotificationSettingsScreen extends StatefulWidget {
  const NotificationSettingsScreen({super.key});

  @override
  State<NotificationSettingsScreen> createState() => _NotificationSettingsScreenState();
}

class _NotificationSettingsScreenState extends State<NotificationSettingsScreen> {
  String? _busy;

  Future<void> _test(String priority) async {
    setState(() => _busy = priority);
    final s = context.read<Session>();
    try {
      final r = await s.api.post('/api/notifications/test-push', {'priority': priority}) as Map<String, dynamic>;
      if (!mounted) return;
      final devices = (r['devices'] as num?)?.toInt() ?? 0;
      final sent = (r['sent'] as num?)?.toInt() ?? 0;
      final String msg;
      if (r['provider'] == 'logpush' || r['provider'] == 'log') {
        msg = 'الإشعارات الفورية غير مفعلة على الخادم (لا يوجد ملف Firebase)';
      } else if (devices == 0) {
        msg = 'هاتفك غير مسجل لاستقبال الإشعارات. أغلق التطبيق وافتحه، واسمح بالإشعارات';
      } else if (sent == 0) {
        msg = 'فشل الإرسال إلى هاتفك. أعد تسجيل الدخول ثم جرّب مرة أخرى';
      } else {
        msg = 'أُرسل إشعار تجريبي. إن لم يظهر خلال ثوانٍ فراجع إعدادات الإشعارات في الهاتف';
      }
      showMessage(context, msg, error: sent == 0);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _change(String channelId) async {
    try {
      await _channel.invokeMethod('openChannelSettings', {'channel': channelId});
    } catch (_) {
      if (mounted) showMessage(context, 'افتح إعدادات الهاتف ← التطبيقات ← منصة الجامعة ← الإشعارات', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final admin = s.role == 'university_admin' || s.role == 'platform_admin';
    return Scaffold(
      appBar: AppBar(title: const Text('الإشعارات والنغمات')),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(4, 4, 4, 12),
          child: Text('لكل نوع نغمة مختلفة حتى تعرف أهمية الإشعار قبل أن تفتحه. '
              'جرّب كل نغمة، أو غيّرها من إعدادات الهاتف.'),
        ),
        for (final t in tones)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Icon(t.$5, color: t.$6),
                  const SizedBox(width: 10),
                  Expanded(child: Text(t.$3, style: const TextStyle(fontWeight: FontWeight.bold))),
                ]),
                Padding(
                  padding: const EdgeInsets.only(right: 34, top: 2),
                  child: Text(t.$4, style: const TextStyle(color: Colors.grey)),
                ),
                const SizedBox(height: 8),
                Row(children: [
                  FilledButton.tonalIcon(
                    onPressed: _busy == null ? () => _test(t.$1) : null,
                    icon: _busy == t.$1
                        ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.play_arrow),
                    label: const Text('تجربة'),
                  ),
                  const SizedBox(width: 8),
                  TextButton.icon(
                    onPressed: () => _change(t.$2),
                    icon: const Icon(Icons.music_note_outlined),
                    label: const Text('تغيير النغمة'),
                  ),
                ]),
              ]),
            ),
          ),
        if (admin) const _Health(),
      ]),
    );
  }
}

class _Health extends StatelessWidget {
  const _Health();

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return AsyncView<Map<String, dynamic>>(
      load: () async => await s.api.get('/api/notifications/health') as Map<String, dynamic>,
      builder: (context, d, reload) {
        final push = (d['last_24h']?['push'] as Map?) ?? {};
        final sms = (d['last_24h']?['sms'] as Map?) ?? {};
        String fmt(Map m) => m.isEmpty ? 'لا شيء' : m.entries.map((e) => '${_label[e.key] ?? e.key}: ${e.value}').join('، ');
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('حالة الإرسال (للإدارة)', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              _row('الإشعارات الفورية', d['push_ready'] == true ? 'مفعلة' : 'غير مفعلة', d['push_ready'] == true),
              _row('الرسائل النصية', d['sms_ready'] == true ? 'مفعلة (${d['sms_provider']})' : 'غير مفعلة',
                  d['sms_ready'] == true),
              _row('مستخدمون بهواتف مسجلة', '${d['users_with_devices']}', true),
              const Divider(),
              Text('آخر 24 ساعة — فوري: ${fmt(push)}'),
              const SizedBox(height: 4),
              Text('آخر 24 ساعة — نصي: ${fmt(sms)}'),
            ]),
          ),
        );
      },
    );
  }

  static const _label = {
    'sent': 'وصل',
    'failed': 'فشل',
    'pending': 'قيد الإرسال',
    'no_device': 'بلا هاتف مسجل',
    'skipped': 'متجاوز',
  };

  Widget _row(String k, String v, bool ok) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Icon(ok ? Icons.check_circle : Icons.error_outline, size: 18, color: ok ? AppColors.success : AppColors.danger),
          const SizedBox(width: 6),
          Expanded(child: Text(k)),
          Text(v),
        ]),
      );
}
