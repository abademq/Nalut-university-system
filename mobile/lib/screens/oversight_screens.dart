import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// Readable names for the audit actions shown most often.
const _actions = {
  'auth.login': 'تسجيل دخول',
  'auth.login_failed': 'محاولة دخول فاشلة',
  'auth.locked': 'قفل حساب',
  'auth.password_changed': 'تغيير كلمة المرور',
  'auth.password_reset': 'استعادة كلمة المرور',
  'auth.mfa_enabled': 'تفعيل التحقق الثنائي',
  'auth.mfa_disabled': 'إيقاف التحقق الثنائي',
  'user.created': 'إنشاء حساب',
  'user.updated': 'تعديل حساب',
  'user.password_reset_by_admin': 'إعادة تعيين كلمة مرور',
  'user.mfa_changed': 'تعديل التحقق الثنائي لحساب',
  'grade.changed': 'تعديل درجة',
  'results.submitted': 'رفع نتائج للاعتماد',
  'results.approved': 'اعتماد نتائج',
  'results.published': 'نشر نتائج',
  'results.draft': 'إرجاع نتائج',
  'warning.issued': 'إنذار رسمي',
  'notification.sent': 'إرسال إشعار',
  'settings.updated': 'تعديل الإعدادات',
  'archive.viewed': 'اطلاع على ملف طالب',
  'file.downloaded': 'تنزيل ملف',
  'message.report_handled': 'معالجة بلاغ رسالة',
  'publication.created': 'نشر جدول أو إعلان مصور',
  'banner.created': 'إعلان مثبت',
};

String auditLabel(String action) => _actions[action] ?? action;

/// The tamper-evident audit log, with a filter and the chain integrity check.
class AuditScreen extends StatefulWidget {
  const AuditScreen({super.key});

  @override
  State<AuditScreen> createState() => _AuditScreenState();
}

class _AuditScreenState extends State<AuditScreen> {
  String _filter = '';
  int _version = 0;

  static const _filters = {
    '': 'الكل',
    'auth': 'الدخول والأمان',
    'grade': 'الدرجات',
    'results': 'النتائج',
    'user': 'الحسابات',
    'settings': 'الإعدادات',
    'archive': 'الأرشيف',
  };

  Future<void> _verify() async {
    final s = context.read<Session>();
    try {
      final r = await s.api.get('/api/audit/verify') as Map<String, dynamic>;
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          icon: Icon(r['ok'] == true ? Icons.verified : Icons.gpp_bad,
              color: r['ok'] == true ? AppColors.success : AppColors.danger, size: 40),
          title: Text(r['ok'] == true ? 'السجل سليم' : 'تم اكتشاف تعديل!'),
          content: Text(r['ok'] == true
              ? 'فُحص ${r['checked']} سجلاً، ولم يُعدَّل أي منها أو يُحذف.'
              : 'السلسلة منقطعة عند السجل رقم ${r['broken_at']}. أبلغ مسؤول النظام فوراً.'),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('حسناً'))],
        ),
      );
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('سجل التدقيق'),
        actions: [
          if (s.role == 'university_admin')
            TextButton.icon(onPressed: _verify, icon: const Icon(Icons.verified_outlined), label: const Text('فحص السلامة')),
        ],
      ),
      body: Column(children: [
        SizedBox(
          height: 52,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            children: [
              for (final e in _filters.entries)
                Padding(
                  padding: const EdgeInsets.only(left: 6),
                  child: ChoiceChip(
                    label: Text(e.value),
                    selected: _filter == e.key,
                    onSelected: (_) => setState(() {
                      _filter = e.key;
                      _version++;
                    }),
                  ),
                ),
            ],
          ),
        ),
        Expanded(
          child: AsyncView<List<dynamic>>(
            key: ValueKey('$_filter-$_version'),
            load: () async =>
                await s.api.get('/api/audit?limit=200${_filter.isEmpty ? '' : '&action=$_filter'}') as List<dynamic>,
            builder: (context, rows, reload) => ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              itemCount: rows.isEmpty ? 1 : rows.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (context, i) {
                if (rows.isEmpty) return const EmptyView('لا توجد سجلات');
                final r = rows[i] as Map<String, dynamic>;
                final details = (r['details'] as Map?) ?? {};
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(auditLabel(r['action'] as String)),
                  subtitle: Text([
                    r['actor'] ?? 'النظام',
                    fmtDate(r['created_at']),
                    if (details.isNotEmpty) details.entries.take(3).map((e) => '${e.key}: ${e.value}').join('، '),
                  ].join(' · ')),
                  trailing: details['by_platform_admin'] == true
                      ? const Tooltip(message: 'بواسطة مشرف المنصة', child: Icon(Icons.shield_outlined, size: 18))
                      : null,
                );
              },
            ),
          ),
        ),
      ]),
    );
  }
}

/// Messages reported as abusive: read them, then hide the message or dismiss the report.
class AbuseReportsScreen extends StatefulWidget {
  const AbuseReportsScreen({super.key});

  @override
  State<AbuseReportsScreen> createState() => _AbuseReportsScreenState();
}

class _AbuseReportsScreenState extends State<AbuseReportsScreen> {
  int _version = 0;

  Future<void> _handle(int id, String action) async {
    final s = context.read<Session>();
    try {
      await s.api.post('/api/message-reports/$id', {'action': action});
      if (!mounted) return;
      showMessage(context, action == 'hide' ? 'أُخفيت الرسالة' : 'أُغلق البلاغ');
      setState(() => _version++);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('بلاغات الرسائل')),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/message-reports') as List<dynamic>,
        builder: (context, rows, reload) => ListView(padding: const EdgeInsets.all(12), children: [
          if (rows.isEmpty) const EmptyView('لا توجد بلاغات', icon: Icons.flag_outlined),
          for (final r in rows)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(
                      child: Text('من: ${r['sender']['full_name']}', style: const TextStyle(fontWeight: FontWeight.bold)),
                    ),
                    StatusChip(StatusStyle(
                        r['status'] == 'open' ? 'جديد' : (r['status'] == 'actioned' ? 'أُخفيت' : 'مغلق'),
                        r['status'] == 'open' ? AppColors.danger : Colors.grey)),
                  ]),
                  const SizedBox(height: 6),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: Colors.grey.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text('${r['message']['body']}'),
                  ),
                  const SizedBox(height: 6),
                  Text('المُبلِّغ: ${r['reporter']['full_name']} · ${fmtDate(r['created_at'])}',
                      style: const TextStyle(fontSize: 12, color: Colors.grey)),
                  if ((r['reason'] as String?)?.isNotEmpty == true) Text('السبب: ${r['reason']}'),
                  if (r['status'] == 'open')
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Row(children: [
                        FilledButton.tonal(onPressed: () => _handle(r['id'] as int, 'hide'), child: const Text('إخفاء الرسالة')),
                        const SizedBox(width: 8),
                        TextButton(onPressed: () => _handle(r['id'] as int, 'dismiss'), child: const Text('لا مخالفة')),
                      ]),
                    ),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}
