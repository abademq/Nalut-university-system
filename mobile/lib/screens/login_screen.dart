import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import '../state/session.dart';

enum _Step { credentials, code, chooseMethod, setupSms, setupTotp }

/// Keeps a masked phone number in left-to-right order inside Arabic text.
String? _ltr(String? v) => v == null ? null : '\u2066$v\u2069';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _identifier = TextEditingController();
  final _password = TextEditingController();
  final _code = TextEditingController();
  _Step _step = _Step.credentials;
  String _method = 'totp'; // second factor used at sign-in
  String? _phoneHint;
  String? _setupToken;
  List<String> _methods = const [];
  String? _totpSecret;
  String? _totpUri;
  int _wait = 0; // seconds before another SMS can be requested
  Timer? _timer;
  bool _busy = false;
  bool _hide = true;
  String? _error;
  String? _info;

  @override
  void dispose() {
    _timer?.cancel();
    _identifier.dispose();
    _password.dispose();
    _code.dispose();
    super.dispose();
  }

  void _countdown(int seconds) {
    _timer?.cancel();
    setState(() => _wait = seconds);
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted || _wait <= 1) {
        t.cancel();
        if (mounted) setState(() => _wait = 0);
      } else {
        setState(() => _wait--);
      }
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _afterSms(Map<String, dynamic> r) {
    _phoneHint = _ltr(r['phone_hint'] as String?) ?? _phoneHint;
    _info = r['sent'] == false ? 'أُرسل رمز قبل قليل، استخدمه أو انتظر لطلب رمز جديد' : 'أرسلنا رمز التحقق برسالة نصية';
    final wait = (r['retry_after'] as num?)?.toInt() ?? 0;
    if (wait > 0) _countdown(wait);
  }

  Future<void> _submit({bool resend = false}) async {
    if (_identifier.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = 'أدخل البريد أو رقم الهاتف وكلمة المرور');
      return;
    }
    await _run(() async {
      final session = context.read<Session>();
      final withCode = _step == _Step.code && !resend;
      final r = await session.login(_identifier.text.trim(), _password.text,
          mfaCode: withCode ? _code.text.trim() : null);
      if (!mounted || r == null) return;
      setState(() {
        if (r['mfa_required'] == true) {
          _step = _Step.code;
          _method = r['method'] as String? ?? 'totp';
          if (_method == 'sms') _afterSms(r);
        } else if (r['mfa_setup_required'] == true) {
          _setupToken = r['setup_token'] as String?;
          _methods = ((r['methods'] as List?) ?? const []).cast<String>();
          _phoneHint = _ltr(r['phone_hint'] as String?);
          _step = _Step.chooseMethod;
        }
      });
    });
  }

  Future<void> _startSms() => _run(() async {
        final r = await context.read<Session>().api.postWithSetupToken('/api/auth/mfa/sms/start', _setupToken!);
        if (mounted) {
          setState(() {
            _step = _Step.setupSms;
            _code.clear();
            _afterSms(r);
          });
        }
      });

  Future<void> _startTotp() => _run(() async {
        final r = await context.read<Session>().api.postWithSetupToken('/api/auth/mfa/setup', _setupToken!);
        if (mounted) {
          setState(() {
            _totpSecret = r['secret'] as String?;
            _totpUri = r['otpauth_uri'] as String?;
            _code.clear();
            _step = _Step.setupTotp;
          });
        }
      });

  Future<void> _finishSetup() => _run(() async {
        final session = context.read<Session>();
        final path = _step == _Step.setupSms ? '/api/auth/mfa/sms/enable' : '/api/auth/mfa/enable';
        final r = await session.api.postWithSetupToken(path, _setupToken!, {'code': _code.text.trim()});
        session.completeLogin(r);
      });

  void _back() => setState(() {
        _timer?.cancel();
        _wait = 0;
        _step = _Step.credentials;
        _code.clear();
        _error = _info = null;
      });

  Future<void> _editServer() async {
    final session = context.read<Session>();
    final ctrl = TextEditingController(text: session.api.baseUrl);
    final value = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('عنوان الخادم'),
        content: TextField(
          controller: ctrl,
          textDirection: TextDirection.ltr,
          keyboardType: TextInputType.url,
          decoration: const InputDecoration(hintText: 'https://example.edu.ly'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, defaultServerUrl), child: const Text('الافتراضي')),
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, ctrl.text), child: const Text('حفظ')),
        ],
      ),
    );
    if (value != null && value.trim().isNotEmpty) await session.setServer(value);
  }

  Widget _codeField(VoidCallback onDone) => TextField(
        controller: _code,
        keyboardType: TextInputType.number,
        maxLength: 6,
        autofocus: true,
        autofillHints: const [AutofillHints.oneTimeCode],
        textDirection: TextDirection.ltr,
        textAlign: TextAlign.center,
        style: const TextStyle(fontSize: 24, letterSpacing: 8),
        onSubmitted: (_) => onDone(),
        decoration: const InputDecoration(labelText: 'رمز التحقق', counterText: ''),
      );

  Widget _resend(VoidCallback onTap) => TextButton(
        onPressed: _busy || _wait > 0 ? null : onTap,
        child: Text(_wait > 0 ? 'إعادة الإرسال بعد $_wait ثانية' : 'إعادة إرسال الرمز'),
      );

  List<Widget> _stepBody() {
    switch (_step) {
      case _Step.credentials:
        return [
          TextField(
            key: const Key('identifier'),
            controller: _identifier,
            keyboardType: TextInputType.emailAddress,
            textDirection: TextDirection.ltr,
            autofillHints: const [AutofillHints.username],
            decoration: const InputDecoration(labelText: 'البريد الإلكتروني أو رقم الهاتف'),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('password'),
            controller: _password,
            obscureText: _hide,
            autofillHints: const [AutofillHints.password],
            onSubmitted: (_) => _submit(),
            decoration: InputDecoration(
              labelText: 'كلمة المرور',
              suffixIcon: IconButton(
                icon: Icon(_hide ? Icons.visibility : Icons.visibility_off),
                onPressed: () => setState(() => _hide = !_hide),
              ),
            ),
          ),
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('login'),
            style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14)),
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? 'جارٍ الدخول…' : 'تسجيل الدخول'),
          ),
          TextButton(
            onPressed: () => launchUrl(Uri.parse(context.read<Session>().api.baseUrl),
                mode: LaunchMode.externalApplication),
            child: const Text('نسيت كلمة المرور؟ (من بوابة الويب)'),
          ),
        ];
      case _Step.code:
        return [
          Text(_method == 'sms'
              ? 'أدخل الرمز المرسل برسالة نصية إلى ${_phoneHint ?? 'هاتفك'}'
              : 'أدخل الرمز الظاهر في تطبيق المصادقة'),
          const SizedBox(height: 8),
          _codeField(_submit),
          const SizedBox(height: 8),
          FilledButton(
            style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14)),
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? 'جارٍ التحقق…' : 'تأكيد'),
          ),
          if (_method == 'sms') _resend(() => _submit(resend: true)),
          TextButton(onPressed: _back, child: const Text('رجوع')),
        ];
      case _Step.chooseMethod:
        return [
          const Text('حسابك يتطلب تحققاً ثنائياً. اختر الطريقة التي تناسبك:',
              style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),
          if (_methods.contains('sms'))
            Card(
              child: ListTile(
                leading: const Icon(Icons.sms_outlined, color: AppColors.primary),
                title: const Text('رسالة نصية'),
                subtitle: Text(_phoneHint == null
                    ? 'لا يوجد رقم هاتف في حسابك، تواصل مع الإدارة'
                    : 'يصلك رمز على $_phoneHint عند كل دخول'),
                enabled: _phoneHint != null && !_busy,
                onTap: _startSms,
              ),
            ),
          if (_methods.contains('totp'))
            Card(
              child: ListTile(
                leading: const Icon(Icons.phonelink_lock, color: AppColors.primary),
                title: const Text('تطبيق المصادقة'),
                subtitle: const Text('مثل Google Authenticator، يعمل دون شبكة'),
                enabled: !_busy,
                onTap: _startTotp,
              ),
            ),
          if (_methods.isEmpty) const Text('لا توجد طريقة تحقق متاحة، تواصل مع الإدارة'),
          TextButton(onPressed: _back, child: const Text('رجوع')),
        ];
      case _Step.setupSms:
        return [
          Text('أدخل الرمز المرسل إلى ${_phoneHint ?? 'هاتفك'} لتفعيل التحقق بالرسائل'),
          const SizedBox(height: 8),
          _codeField(_finishSetup),
          FilledButton(onPressed: _busy ? null : _finishSetup, child: const Text('تفعيل والدخول')),
          _resend(_startSms),
          TextButton(onPressed: () => setState(() => _step = _Step.chooseMethod), child: const Text('طريقة أخرى')),
        ];
      case _Step.setupTotp:
        return [
          const Text('1. أضف الحساب إلى تطبيق المصادقة'),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.open_in_new),
            label: const Text('فتح تطبيق المصادقة'),
            onPressed: _totpUri == null
                ? null
                : () => launchUrl(Uri.parse(_totpUri!), mode: LaunchMode.externalApplication),
          ),
          const SizedBox(height: 6),
          const Text('أو أدخل هذا المفتاح يدوياً:', style: TextStyle(color: Colors.grey)),
          InkWell(
            onTap: () {
              Clipboard.setData(ClipboardData(text: _totpSecret ?? ''));
              setState(() => _info = 'نُسخ المفتاح');
            },
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: SelectableText(_totpSecret ?? '', textDirection: TextDirection.ltr,
                  textAlign: TextAlign.center, style: const TextStyle(fontFamily: 'monospace', fontSize: 16)),
            ),
          ),
          const Text('2. أدخل الرمز الظاهر في التطبيق'),
          _codeField(_finishSetup),
          FilledButton(onPressed: _busy ? null : _finishSetup, child: const Text('تفعيل والدخول')),
          TextButton(onPressed: () => setState(() => _step = _Step.chooseMethod), child: const Text('طريقة أخرى')),
        ];
    }
  }

  @override
  Widget build(BuildContext context) {
    final server = context.watch<Session>().api.baseUrl;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Center(child: Image.asset('assets/logo.png', width: 72, height: 72)),
                const SizedBox(height: 12),
                Text('منصة الجامعة الذكية',
                    textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 4),
                const Text('بوابة موحدة للطلبة وأعضاء هيئة التدريس والإدارة',
                    textAlign: TextAlign.center, style: TextStyle(color: Colors.grey)),
                const SizedBox(height: 24),
                if (_error != null)
                  _Note(text: _error!, color: AppColors.danger)
                else if (_info != null && _step != _Step.credentials)
                  _Note(text: _info!, color: AppColors.primary),
                ..._stepBody(),
                const SizedBox(height: 24),
                TextButton.icon(
                  onPressed: _editServer,
                  icon: const Icon(Icons.dns_outlined, size: 18),
                  label: Text(server, textDirection: TextDirection.ltr, style: const TextStyle(fontSize: 12)),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

class _Note extends StatelessWidget {
  const _Note({required this.text, required this.color});
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        margin: const EdgeInsets.only(bottom: 12),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(10)),
        child: Text(text, style: TextStyle(color: color)),
      );
}
