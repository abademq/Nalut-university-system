import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../push.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _slotIcons = {
  'normal': (Icons.notifications_none, AppColors.primary),
  'important': (Icons.notification_important_outlined, AppColors.warning),
  'urgent': (Icons.campaign_outlined, AppColors.danger),
  'official_warning': (Icons.gavel_outlined, AppColors.danger),
};

const _testPriority = {'normal': 'normal', 'important': 'important', 'urgent': 'urgent'};

/// Diagnostics and the tones chosen by the university (users can listen, not change them).
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
        msg = 'الإشعارات الفورية غير مفعلة على الخادم (ملف Firebase غير موجود)';
      } else if (devices == 0) {
        msg = 'هاتفك غير مسجل. اضغط «إعادة تسجيل هذا الهاتف» ثم جرّب مرة أخرى';
      } else if (sent == 0) {
        msg = 'رفض Firebase الإرسال: ${r['error'] ?? 'سبب غير معروف'}';
      } else {
        msg = 'أُرسل. أغلق التطبيق أو اخرج للشاشة الرئيسية لترى الإشعار في شريط الهاتف';
      }
      showMessage(context, msg, error: sent == 0);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  Future<void> _register() async {
    setState(() => _busy = 'register');
    final status = await context.read<Session>().registerPush();
    if (!mounted) return;
    setState(() => _busy = null);
    showMessage(context, _statusText(status), error: status != 'registered');
  }

  static String _statusText(String status) => switch (status) {
        'registered' => 'هذا الهاتف مسجل لاستقبال الإشعارات',
        'denied' => 'الإشعارات ممنوعة على هذا الهاتف. اسمح بها من إعدادات الهاتف ثم أعد التسجيل',
        'no_firebase' => 'الإشعارات الفورية غير مهيأة في هذه النسخة من التطبيق',
        'not_started' => 'لم يُسجَّل الهاتف بعد',
        _ => 'تعذر التسجيل: ${status.replaceFirst('error: ', '')}',
      };

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final status = s.push?.status ?? 'no_firebase';
    final admin = s.role == 'university_admin' || s.role == 'platform_admin';
    return Scaffold(
      appBar: AppBar(title: const Text('الإشعارات')),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Icon(status == 'registered' ? Icons.check_circle : Icons.error_outline,
                    color: status == 'registered' ? AppColors.success : AppColors.danger),
                const SizedBox(width: 8),
                Expanded(child: Text(_statusText(status))),
              ]),
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                OutlinedButton.icon(
                  onPressed: _busy == null ? _register : null,
                  icon: const Icon(Icons.refresh),
                  label: const Text('إعادة تسجيل هذا الهاتف'),
                ),
                TextButton.icon(
                  onPressed: NativeNotifications.openSettings,
                  icon: const Icon(Icons.settings_outlined),
                  label: const Text('السماح بالإشعارات'),
                ),
              ]),
            ]),
          ),
        ),
        const Padding(
          padding: EdgeInsets.fromLTRB(4, 12, 4, 8),
          child: Text('نغمة كل نوع تحددها إدارة الجامعة. اضغط ▶ للاستماع، أو «تجربة» لإرسال إشعار حقيقي لهاتفك.'),
        ),
        AsyncView<Map<String, dynamic>>(
          load: () async => await s.api.get('/api/notifications/tones') as Map<String, dynamic>,
          builder: (context, d, reload) {
            final labels = {for (final t in d['library'] as List) t['name']: t['label']};
            return Column(children: [
              for (final slot in d['slots'] as List)
                Card(
                  child: ListTile(
                    leading: Icon(_slotIcons[slot['slot']]?.$1 ?? Icons.notifications,
                        color: _slotIcons[slot['slot']]?.$2),
                    title: Text('${slot['label']}'),
                    subtitle: Text('النغمة: ${labels[slot['tone']] ?? slot['tone']}'),
                    trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                      IconButton(
                        tooltip: 'استماع',
                        icon: const Icon(Icons.play_arrow),
                        onPressed: () => NativeNotifications.playTone(slot['tone'] as String?),
                      ),
                      if (_testPriority.containsKey(slot['slot']))
                        TextButton(
                          onPressed: _busy == null ? () => _test(_testPriority[slot['slot']]!) : null,
                          child: _busy == slot['slot']
                              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                              : const Text('تجربة'),
                        ),
                    ]),
                  ),
                ),
            ]);
          },
        ),
        if (admin) const _Health(),
      ]),
    );
  }
}

class _Health extends StatelessWidget {
  const _Health();

  static const _label = {
    'sent': 'وصل',
    'failed': 'فشل',
    'pending': 'قيد الإرسال',
    'no_device': 'بلا هاتف مسجل',
    'skipped': 'متجاوز',
  };

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
              _row('الرسائل النصية', d['sms_ready'] == true ? 'مفعلة' : 'غير مفعلة', d['sms_ready'] == true),
              _row('مستخدمون بهواتف مسجلة', '${d['users_with_devices']}', true),
              const Divider(),
              Text('آخر 24 ساعة — فوري: ${fmt(push)}'),
              const SizedBox(height: 4),
              Text('آخر 24 ساعة — نصي: ${fmt(sms)}'),
              if (d['last_push_error'] != null) ...[
                const Divider(),
                const Text('آخر خطأ من Firebase:', style: TextStyle(color: AppColors.danger)),
                SelectableText('${d['last_push_error']}', textDirection: TextDirection.ltr,
                    style: const TextStyle(fontSize: 12)),
              ],
            ]),
          ),
        );
      },
    );
  }

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
