import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import '../state/session.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _identifier = TextEditingController();
  final _password = TextEditingController();
  final _code = TextEditingController();
  bool _needCode = false;
  bool _busy = false;
  bool _hide = true;
  String? _error;

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_identifier.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = 'أدخل البريد أو رقم الهاتف وكلمة المرور');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final session = context.read<Session>();
    try {
      final result = await session.login(_identifier.text.trim(), _password.text,
          mfaCode: _needCode ? _code.text.trim() : null);
      if (!mounted) return;
      if (result == 'mfa_required') {
        setState(() => _needCode = true);
      } else if (result == 'mfa_setup_required') {
        setState(() => _error = 'حسابك الإداري يتطلب تفعيل المصادقة الثنائية. فعّلها أولاً من لوحة الويب ثم عد إلى التطبيق.');
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

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
                const Icon(Icons.school, size: 64, color: AppColors.primary),
                const SizedBox(height: 8),
                Text('منصة الجامعة الذكية',
                    textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 4),
                const Text('بوابة موحدة للطلبة وأعضاء هيئة التدريس والإدارة',
                    textAlign: TextAlign.center, style: TextStyle(color: Colors.grey)),
                const SizedBox(height: 24),
                if (_error != null)
                  Container(
                    padding: const EdgeInsets.all(12),
                    margin: const EdgeInsets.only(bottom: 12),
                    decoration: BoxDecoration(
                      color: AppColors.danger.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(_error!, style: const TextStyle(color: AppColors.danger)),
                  ),
                if (!_needCode) ...[
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
                ] else ...[
                  const Text('أدخل رمز التحقق من تطبيق المصادقة'),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _code,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    autofocus: true,
                    textDirection: TextDirection.ltr,
                    onSubmitted: (_) => _submit(),
                    decoration: const InputDecoration(labelText: 'رمز التحقق'),
                  ),
                ],
                const SizedBox(height: 16),
                FilledButton(
                  key: const Key('login'),
                  style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14)),
                  onPressed: _busy ? null : _submit,
                  child: Text(_busy ? 'جارٍ الدخول…' : 'تسجيل الدخول'),
                ),
                TextButton(
                  onPressed: () => launchUrl(Uri.parse(server), mode: LaunchMode.externalApplication),
                  child: const Text('نسيت كلمة المرور؟ (من بوابة الويب)'),
                ),
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

