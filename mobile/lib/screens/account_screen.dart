import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// "حسابي": password, second factor, notification preferences and sessions.
class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final u = s.user ?? {};
    return Scaffold(
      appBar: AppBar(title: const Text('حسابي')),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        if (u['must_change_password'] == true)
          Card(
            color: AppColors.warning.withValues(alpha: 0.1),
            child: const ListTile(
              leading: Icon(Icons.warning_amber, color: AppColors.warning),
              title: Text('تستخدم كلمة مرور مؤقتة، غيّرها الآن'),
            ),
          ),
        Card(
          child: Column(children: [
            ListTile(
              leading: const Icon(Icons.password),
              title: const Text('تغيير كلمة المرور'),
              trailing: const Icon(Icons.chevron_left),
              onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ChangePasswordScreen())),
            ),
            ListTile(
              leading: const Icon(Icons.verified_user_outlined),
              title: const Text('التحقق الثنائي'),
              subtitle: Text(u['mfa_enabled'] == true
                  ? 'مفعّل ${u['mfa_method'] == 'sms' ? 'برسالة نصية' : 'بتطبيق المصادقة'}'
                  : (u['mfa_required'] == true ? 'مطلوب لحسابك' : 'غير مفعّل')),
              trailing: const Icon(Icons.chevron_left),
              onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const MfaScreen())),
            ),
          ]),
        ),
        const _Prefs(),
        Card(
          child: ListTile(
            leading: const Icon(Icons.devices_other, color: AppColors.danger),
            title: const Text('تسجيل الخروج من كل الأجهزة'),
            subtitle: const Text('إذا فقدت هاتفاً أو سجّلت الدخول من جهاز غيرك'),
            onTap: () async {
              final ok = await showDialog<bool>(
                context: context,
                builder: (ctx) => AlertDialog(
                  title: const Text('الخروج من كل الأجهزة؟'),
                  content: const Text('ستحتاج لتسجيل الدخول من جديد على كل الأجهزة، ومنها هذا الهاتف.'),
                  actions: [
                    TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
                    FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('خروج')),
                  ],
                ),
              );
              if (ok != true) return;
              try {
                await s.api.post('/api/me/sessions/revoke-all');
              } catch (_) {}
              await s.logout();
              if (context.mounted) Navigator.popUntil(context, (r) => r.isFirst);
            },
          ),
        ),
      ]),
    );
  }
}

class _Prefs extends StatefulWidget {
  const _Prefs();

  @override
  State<_Prefs> createState() => _PrefsState();
}

class _PrefsState extends State<_Prefs> {
  late bool _push;
  late bool _sms;
  late Set<String> _muted;
  static const _mutable = {'announcement': 'الإعلانات', 'academic_note': 'الملاحظات الأكاديمية', 'admin_notice': 'التعاميم الإدارية'};

  @override
  void initState() {
    super.initState();
    final p = (context.read<Session>().user?['notification_prefs'] as Map?) ?? {};
    _push = p['push'] != false;
    _sms = p['sms'] != false;
    _muted = {...((p['muted_categories'] as List?) ?? const []).cast<String>()};
  }

  Future<void> _save() async {
    final s = context.read<Session>();
    try {
      await s.api.put('/api/me/notification-prefs', {'push': _push, 'sms': _sms, 'muted_categories': _muted.toList()});
      await s.reloadProfile();
      if (mounted) showMessage(context, 'حُفظت التفضيلات');
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Text('تفضيلات الإشعارات', style: TextStyle(fontWeight: FontWeight.bold)),
        ),
        SwitchListTile(
          title: const Text('إشعارات فورية على الهاتف'),
          value: _push,
          onChanged: (v) => setState(() => _push = v),
        ),
        SwitchListTile(
          title: const Text('رسائل نصية للأمور العاجلة'),
          value: _sms,
          onChanged: (v) => setState(() => _sms = v),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16),
          child: Text('كتم (تبقى في صندوق الإشعارات دون تنبيه):', style: TextStyle(color: Colors.grey)),
        ),
        for (final e in _mutable.entries)
          CheckboxListTile(
            title: Text(e.value),
            value: _muted.contains(e.key),
            onChanged: (v) => setState(() => v == true ? _muted.add(e.key) : _muted.remove(e.key)),
          ),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16),
          child: Text('الإنذارات الرسمية والتنبيهات العاجلة تصل دائماً.', style: TextStyle(fontSize: 12, color: Colors.grey)),
        ),
        Padding(
          padding: const EdgeInsets.all(12),
          child: FilledButton(onPressed: _save, child: const Text('حفظ التفضيلات')),
        ),
      ]),
    );
  }
}

class ChangePasswordScreen extends StatefulWidget {
  const ChangePasswordScreen({super.key});

  @override
  State<ChangePasswordScreen> createState() => _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends State<ChangePasswordScreen> {
  final _current = TextEditingController();
  final _new = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;
  bool _hide = true;

  @override
  void dispose() {
    _current.dispose();
    _new.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_new.text != _confirm.text) {
      showMessage(context, 'كلمتا المرور الجديدتان غير متطابقتين', error: true);
      return;
    }
    setState(() => _busy = true);
    final s = context.read<Session>();
    try {
      final r = await s.api.post('/api/auth/password/change',
          {'current_password': _current.text, 'new_password': _new.text}) as Map<String, dynamic>;
      await s.api.acceptSession(r); // other devices were signed out; this one keeps a fresh session
      TextInput.finishAutofillContext(); // lets Google Password Manager update the saved password
      await s.reloadProfile();
      if (!mounted) return;
      showMessage(context, 'تم تغيير كلمة المرور، وخرجت أجهزتك الأخرى');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    InputDecoration deco(String label) => InputDecoration(
          labelText: label,
          suffixIcon: IconButton(
            icon: Icon(_hide ? Icons.visibility : Icons.visibility_off),
            onPressed: () => setState(() => _hide = !_hide),
          ),
        );
    return Scaffold(
      appBar: AppBar(title: const Text('تغيير كلمة المرور')),
      body: AutofillGroup(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          TextField(controller: _current, obscureText: _hide, autofillHints: const [AutofillHints.password],
              decoration: deco('كلمة المرور الحالية')),
          const SizedBox(height: 12),
          TextField(controller: _new, obscureText: _hide, autofillHints: const [AutofillHints.newPassword],
              decoration: deco('كلمة المرور الجديدة')),
          const SizedBox(height: 12),
          TextField(controller: _confirm, obscureText: _hide, autofillHints: const [AutofillHints.newPassword],
              decoration: deco('تأكيد كلمة المرور الجديدة'), onSubmitted: (_) => _submit()),
          const SizedBox(height: 8),
          const Text('10 أحرف على الأقل، وتحتوي حروفاً وأرقاماً، ولا تشبه بريدك أو هاتفك.',
              style: TextStyle(color: Colors.grey)),
          const SizedBox(height: 16),
          FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'جارٍ الحفظ…' : 'تغيير')),
        ]),
      ),
    );
  }
}

/// Turn the second factor on (SMS or authenticator app) or off, from the phone.
class MfaScreen extends StatefulWidget {
  const MfaScreen({super.key});

  @override
  State<MfaScreen> createState() => _MfaScreenState();
}

class _MfaScreenState extends State<MfaScreen> {
  String? _method; // being set up
  String? _secret;
  String? _uri;
  String? _hint;
  final _code = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() f) async {
    setState(() => _busy = true);
    try {
      await f();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _start(String method) => _run(() async {
        final api = context.read<Session>().api;
        if (method == 'sms') {
          final r = await api.post('/api/auth/mfa/sms/start') as Map<String, dynamic>;
          _hint = '\u2066${r['phone_hint']}\u2069';
        } else {
          final r = await api.post('/api/auth/mfa/setup') as Map<String, dynamic>;
          _secret = r['secret'] as String?;
          _uri = r['otpauth_uri'] as String?;
        }
        _code.clear();
        setState(() => _method = method);
      });

  Future<void> _enable() => _run(() async {
        final s = context.read<Session>();
        await s.api.post(_method == 'sms' ? '/api/auth/mfa/sms/enable' : '/api/auth/mfa/enable', {'code': _code.text.trim()});
        await s.reloadProfile();
        if (!mounted) return;
        setState(() => _method = null);
        showMessage(context, 'تم تفعيل التحقق الثنائي');
      });

  Future<void> _disable() async {
    final s = context.read<Session>();
    final sms = s.user?['mfa_method'] == 'sms';
    final password = TextEditingController();
    final code = TextEditingController();
    if (sms) {
      try {
        await s.api.post('/api/auth/mfa/sms/start');
      } catch (e) {
        if (mounted) showMessage(context, e, error: true);
        return;
      }
    }
    if (!mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('إيقاف التحقق الثنائي'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: password, obscureText: true, decoration: const InputDecoration(labelText: 'كلمة المرور')),
          const SizedBox(height: 8),
          TextField(
            controller: code,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText: sms ? 'الرمز المرسل برسالة' : 'رمز تطبيق المصادقة'),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('إيقاف')),
        ],
      ),
    );
    if (ok != true) return;
    await _run(() async {
      await s.api.post('/api/auth/mfa/disable', {'password': password.text, 'code': code.text.trim()});
      await s.reloadProfile();
      if (mounted) showMessage(context, 'أُوقف التحقق الثنائي');
    });
  }

  @override
  Widget build(BuildContext context) {
    final u = context.watch<Session>().user ?? {};
    final methods = ((u['mfa_methods'] as List?) ?? const []).cast<String>();
    final enabled = u['mfa_enabled'] == true;
    return Scaffold(
      appBar: AppBar(title: const Text('التحقق الثنائي')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        const Text('رمز من 6 أرقام يُطلب بعد كلمة المرور، فلا يكفي أن يعرف أحد كلمة مرورك ليدخل حسابك.'),
        const SizedBox(height: 16),
        if (enabled) ...[
          Card(
            child: ListTile(
              leading: const Icon(Icons.verified_user, color: AppColors.success),
              title: Text('مفعّل ${u['mfa_method'] == 'sms' ? 'برسالة نصية' : 'بتطبيق المصادقة'}'),
              subtitle: u['mfa_required'] == true
                  ? const Text('إلزامي لحسابك. لتغيير الطريقة اطلب من الإدارة إعادة تعيينه.')
                  : null,
            ),
          ),
          if (u['mfa_required'] != true)
            OutlinedButton(onPressed: _busy ? null : _disable, child: const Text('إيقاف التحقق الثنائي')),
        ] else if (_method == null) ...[
          if (methods.contains('sms'))
            Card(
              child: ListTile(
                leading: const Icon(Icons.sms_outlined, color: AppColors.primary),
                title: const Text('رسالة نصية'),
                subtitle: Text(u['phone'] == null ? 'لا يوجد رقم هاتف في حسابك' : 'يصلك رمز عند كل دخول'),
                enabled: u['phone'] != null && !_busy,
                onTap: () => _start('sms'),
              ),
            ),
          if (methods.contains('totp'))
            Card(
              child: ListTile(
                leading: const Icon(Icons.phonelink_lock, color: AppColors.primary),
                title: const Text('تطبيق المصادقة'),
                subtitle: const Text('مثل Google Authenticator، يعمل دون شبكة'),
                enabled: !_busy,
                onTap: () => _start('totp'),
              ),
            ),
          if (methods.isEmpty) const Text('لا توجد طريقة تحقق متاحة في مؤسستك'),
        ] else ...[
          if (_method == 'sms')
            Text('أدخل الرمز المرسل إلى ${_hint ?? 'هاتفك'}')
          else ...[
            OutlinedButton.icon(
              icon: const Icon(Icons.open_in_new),
              label: const Text('فتح تطبيق المصادقة'),
              onPressed: _uri == null ? null : () => launchUrl(Uri.parse(_uri!), mode: LaunchMode.externalApplication),
            ),
            const SizedBox(height: 6),
            const Text('أو أدخل هذا المفتاح يدوياً (اضغط لنسخه):', style: TextStyle(color: Colors.grey)),
            InkWell(
              onTap: () => Clipboard.setData(ClipboardData(text: _secret ?? '')),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(_secret ?? '', textDirection: TextDirection.ltr, textAlign: TextAlign.center,
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 16)),
              ),
            ),
          ],
          TextField(
            controller: _code,
            keyboardType: TextInputType.number,
            maxLength: 6,
            textAlign: TextAlign.center,
            autofillHints: const [AutofillHints.oneTimeCode],
            decoration: const InputDecoration(labelText: 'رمز التحقق', counterText: ''),
          ),
          FilledButton(onPressed: _busy ? null : _enable, child: const Text('تفعيل')),
          TextButton(onPressed: () => setState(() => _method = null), child: const Text('رجوع')),
        ],
      ]),
    );
  }
}
