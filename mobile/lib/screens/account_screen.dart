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
            if (s.role == 'platform_admin' || s.role == 'university_admin')
              ListTile(
                leading: const Icon(Icons.badge_outlined),
                title: const Text('تعديل بياناتي'),
                subtitle: const Text('الاسم، البريد، رقم الهاتف'),
                trailing: const Icon(Icons.chevron_left),
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const EditDetailsScreen())),
              ),
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
        const _NotificationChoices(),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const Text('المظهر', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              ValueListenableBuilder<ThemeMode>(
                valueListenable: s.themeMode,
                builder: (context, mode, _) => SegmentedButton<ThemeMode>(
                  segments: const [
                    ButtonSegment(value: ThemeMode.system, icon: Icon(Icons.brightness_auto), label: Text('تلقائي')),
                    ButtonSegment(value: ThemeMode.light, icon: Icon(Icons.light_mode_outlined), label: Text('فاتح')),
                    ButtonSegment(value: ThemeMode.dark, icon: Icon(Icons.dark_mode_outlined), label: Text('داكن')),
                  ],
                  selected: {mode},
                  onSelectionChanged: (v) => s.setThemeMode(v.first),
                ),
              ),
            ]),
          ),
        ),
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

/// Platform and university administrators correct their own name, email and phone.
class EditDetailsScreen extends StatefulWidget {
  const EditDetailsScreen({super.key});

  @override
  State<EditDetailsScreen> createState() => _EditDetailsScreenState();
}

class _EditDetailsScreenState extends State<EditDetailsScreen> {
  late final Map<String, dynamic> _u = context.read<Session>().user ?? {};
  late final _name = TextEditingController(text: _u['full_name'] as String? ?? '');
  late final _email = TextEditingController(text: _u['email'] as String? ?? '');
  late final _phone = TextEditingController(text: _u['phone'] as String? ?? '');
  final _password = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final s = context.read<Session>();
    setState(() => _busy = true);
    try {
      await s.api.patch('/api/me/profile', {
        'full_name': _name.text.trim(),
        'email': _email.text.trim(),
        'phone': _phone.text.trim(),
        'current_password': _password.text,
      });
      await s.reloadProfile();
      if (!mounted) return;
      showMessage(context, 'حُفظت بياناتك');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('تعديل بياناتي')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        TextField(controller: _name, decoration: const InputDecoration(labelText: 'الاسم')),
        const SizedBox(height: 12),
        TextField(
          controller: _email,
          keyboardType: TextInputType.emailAddress,
          textDirection: TextDirection.ltr,
          decoration: const InputDecoration(labelText: 'البريد الإلكتروني (للدخول)'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _phone,
          keyboardType: TextInputType.phone,
          textDirection: TextDirection.ltr,
          decoration: const InputDecoration(labelText: 'رقم الهاتف (للدخول والرسائل)'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _password,
          obscureText: true,
          autofillHints: const [AutofillHints.password],
          decoration: const InputDecoration(labelText: 'كلمة المرور الحالية للتأكيد'),
        ),
        const SizedBox(height: 8),
        const Text('يجب أن يبقى البريد أو الهاتف لتسجيل الدخول.', style: TextStyle(color: Colors.grey)),
        const SizedBox(height: 16),
        FilledButton(onPressed: _busy ? null : _save, child: const Text('حفظ')),
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
    final password = TextEditingController();
    final code = TextEditingController();
    var sms = s.user?['mfa_method'] == 'sms';
    try {
      // the method on now, from the server (it may have been set up a moment ago on this screen)
      final o = await s.api.get('/api/auth/mfa/options') as Map<String, dynamic>;
      sms = o['method'] == 'sms';
    } catch (_) {}
    if (sms) {
      try {
        final r = await s.api.post('/api/auth/mfa/sms/start') as Map<String, dynamic>;
        if (mounted) {
          showMessage(context, r['sent'] == true
              ? 'أُرسل الرمز إلى ${r['phone_hint'] ?? 'هاتفك'}'
              : 'أُرسل رمز قبل قليل؛ استعمله أو انتظر ${r['retry_after']} ثانية لطلب غيره');
        }
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
                leading: Icon(Icons.sms_outlined, color: goldText(context)),
                title: const Text('رسالة نصية'),
                subtitle: Text(u['phone'] == null ? 'لا يوجد رقم هاتف في حسابك' : 'يصلك رمز عند كل دخول'),
                enabled: u['phone'] != null && !_busy,
                onTap: () => _start('sms'),
              ),
            ),
          if (methods.contains('totp'))
            Card(
              child: ListTile(
                leading: Icon(Icons.phonelink_lock, color: goldText(context)),
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


/// The notification types the administration lets this user switch off (none: nothing shown).
class _NotificationChoices extends StatefulWidget {
  const _NotificationChoices();

  @override
  State<_NotificationChoices> createState() => _NotificationChoicesState();
}

class _NotificationChoicesState extends State<_NotificationChoices> {
  List<Map<String, dynamic>> _topics = [];
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await context.read<Session>().api.get('/api/me/notification-mutes') as Map<String, dynamic>;
      if (mounted) setState(() => _topics = (r['topics'] as List).cast<Map<String, dynamic>>());
    } catch (_) {}
  }

  Future<void> _toggle(Map<String, dynamic> t, bool receive) async {
    final muted = [
      for (final x in _topics)
        if (x['topic'] == t['topic'] ? !receive : x['muted'] == true) x['topic'] as String
    ];
    setState(() => _busy = true);
    try {
      final r = await context.read<Session>().api.put('/api/me/notification-mutes', {'muted': muted}) as Map<String, dynamic>;
      if (mounted) setState(() => _topics = (r['topics'] as List).cast<Map<String, dynamic>>());
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_topics.isEmpty) return const SizedBox.shrink();
    return Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Text('الإشعارات', style: TextStyle(fontWeight: FontWeight.bold)),
        ),
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 4, 16, 0),
          child: Text('التحذيرات الرسمية والإشعارات العاجلة تصل دائماً.', style: TextStyle(fontSize: 12)),
        ),
        for (final t in _topics)
          SwitchListTile(
            title: Text(t['label'] as String),
            value: t['muted'] != true,
            onChanged: _busy ? null : (v) => _toggle(t, v),
          ),
      ]),
    );
  }
}
