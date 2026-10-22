import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// Password recovery: a code is sent by SMS to the account's phone, then a new password is set.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key, this.identifier = ''});
  final String identifier;

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  late final _identifier = TextEditingController(text: widget.identifier);
  final _code = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _sent = false;
  bool _busy = false;
  bool _hide = true;

  @override
  void dispose() {
    _identifier.dispose();
    _code.dispose();
    _password.dispose();
    _confirm.dispose();
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

  Future<void> _send() => _run(() async {
        if (_identifier.text.trim().length < 3) throw 'أدخل البريد أو رقم الهاتف';
        await context.read<Session>().api.post('/api/auth/password/forgot', {'identifier': _identifier.text.trim()});
        if (mounted) setState(() => _sent = true);
      });

  Future<void> _reset() => _run(() async {
        if (_password.text != _confirm.text) throw 'كلمتا المرور غير متطابقتين';
        final code = _code.text.trim();
        final long = code.length > 10; // a long token from e-mail also works
        await context.read<Session>().api.post('/api/auth/password/reset', {
          if (long) 'token': code else ...{'identifier': _identifier.text.trim(), 'code': code},
          'new_password': _password.text,
        });
        TextInput.finishAutofillContext(); // let Google Password Manager store the new password
        if (!mounted) return;
        showMessage(context, 'تم تعيين كلمة المرور الجديدة، سجّل الدخول بها');
        Navigator.pop(context);
      });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('استعادة كلمة المرور')),
      body: AutofillGroup(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          TextField(
            controller: _identifier,
            enabled: !_sent,
            textDirection: TextDirection.ltr,
            keyboardType: TextInputType.emailAddress,
            autofillHints: const [AutofillHints.username],
            decoration: const InputDecoration(labelText: 'البريد الإلكتروني أو رقم الهاتف'),
          ),
          const SizedBox(height: 12),
          if (!_sent) ...[
            const Text('نرسل رمزاً من 6 أرقام برسالة نصية إلى رقم الهاتف المسجل في حسابك.'),
            const SizedBox(height: 16),
            FilledButton(onPressed: _busy ? null : _send, child: const Text('إرسال الرمز')),
          ] else ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.primary.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Text('إذا كان الحساب موجوداً وله رقم هاتف فسيصلك الرمز خلال لحظات. صالح 5 دقائق.'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _code,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              autofillHints: const [AutofillHints.oneTimeCode],
              style: const TextStyle(fontSize: 22, letterSpacing: 6),
              decoration: const InputDecoration(labelText: 'رمز الاستعادة'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _password,
              obscureText: _hide,
              autofillHints: const [AutofillHints.newPassword],
              decoration: InputDecoration(
                labelText: 'كلمة المرور الجديدة',
                suffixIcon: IconButton(
                  icon: Icon(_hide ? Icons.visibility : Icons.visibility_off),
                  onPressed: () => setState(() => _hide = !_hide),
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _confirm,
              obscureText: _hide,
              autofillHints: const [AutofillHints.newPassword],
              decoration: const InputDecoration(labelText: 'تأكيد كلمة المرور'),
            ),
            const SizedBox(height: 6),
            const Text('10 أحرف على الأقل، حروف وأرقام.', style: TextStyle(color: Colors.grey)),
            const SizedBox(height: 16),
            FilledButton(onPressed: _busy ? null : _reset, child: const Text('تعيين كلمة المرور')),
            TextButton(onPressed: _busy ? null : _send, child: const Text('إعادة إرسال الرمز')),
          ],
        ]),
      ),
    );
  }
}
