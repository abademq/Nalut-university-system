import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _senders = {
  'announcement': ['university_admin', 'faculty_admin', 'teacher', 'assistant'],
  'academic_note': ['university_admin', 'faculty_admin', 'teacher', 'assistant'],
  'official_warning': ['university_admin', 'faculty_admin'],
  'admin_notice': ['university_admin', 'faculty_admin', 'staff'],
};

/// Categories the user may send. The university's permission matrix (the profile's `can`
/// list) decides; the role table is only a fallback for an older server.
List<String> sendableCategories(Map<String, dynamic>? user) {
  final role = user?['role'] as String? ?? '';
  final can = user?['can'];
  if (can is List) return [for (final k in _senders.keys) if (can.contains('notify.$k')) k];
  return [for (final e in _senders.entries) if (e.value.contains(role)) e.key];
}

bool canSendNotifications(Map<String, dynamic>? user) => sendableCategories(user).isNotEmpty;

class SendNotificationScreen extends StatefulWidget {
  const SendNotificationScreen({super.key, this.presetUsers});
  final List<Map<String, dynamic>>? presetUsers;

  @override
  State<SendNotificationScreen> createState() => _SendNotificationScreenState();
}

class _SendNotificationScreenState extends State<SendNotificationScreen> {
  late String _category;
  String _priority = 'normal';
  late String _targetType;
  String _audience = 'students';
  int? _targetId;
  final _cohort = TextEditingController();
  final _title = TextEditingController();
  final _body = TextEditingController();
  final _search = TextEditingController();
  final List<Map<String, dynamic>> _users = [];
  List<dynamic> _results = [];
  bool _push = true;
  bool _sms = false;
  bool _busy = false;
  List<dynamic> _courses = [];
  Map<String, dynamic>? _structure;

  Session get _s => context.read<Session>();
  bool get _instructor => _s.isInstructor;

  @override
  void initState() {
    super.initState();
    final role = context.read<Session>().role;
    _category = sendableCategories(context.read<Session>().user).first;
    _targetType = widget.presetUsers != null ? 'users' : (_instructorRole(role) ? 'course' : 'users');
    if (widget.presetUsers != null) _users.addAll(widget.presetUsers!);
    _loadOptions();
  }

  static bool _instructorRole(String r) => r == 'teacher' || r == 'assistant';

  Future<void> _loadOptions() async {
    // Loaded separately: teachers may see their courses but not the whole structure.
    try {
      final courses = await _s.api.get('/api/courses') as List<dynamic>;
      if (mounted) setState(() => _courses = courses);
    } catch (_) {}
    try {
      final structure = await _s.api.get('/api/org/structure') as Map<String, dynamic>;
      if (mounted) setState(() => _structure = structure);
    } catch (_) {}
  }

  @override
  void dispose() {
    for (final c in [_cohort, _title, _body, _search]) {
      c.dispose();
    }
    super.dispose();
  }

  List<(String, String)> get _targets {
    final role = _s.role;
    if (_instructorRole(role)) return [('course', 'طلبة مقرر'), ('users', 'طلبة محددون')];
    if (role == 'staff') return [('users', 'أشخاص محددون'), ('faculty', 'الكلية')];
    return [
      ('users', 'أشخاص محددون'), ('course', 'مقرر'), ('department', 'قسم'), ('faculty', 'كلية'), ('cohort', 'دفعة'),
      if (role == 'university_admin') ('university', 'الجامعة كاملة'),
    ];
  }

  Future<void> _searchUsers(String q) async {
    if (q.trim().length < 2) return setState(() => _results = []);
    try {
      final r = await _s.api.get('/api/users?q=${Uri.encodeQueryComponent(q.trim())}&limit=20') as Map<String, dynamic>;
      if (mounted) setState(() => _results = r['items'] as List<dynamic>);
    } catch (_) {}
  }

  Future<void> _send() async {
    if (_title.text.trim().length < 2 || _body.text.trim().length < 2) {
      return showMessage(context, 'اكتب العنوان والنص', error: true);
    }
    List<Object> ids;
    switch (_targetType) {
      case 'users':
        ids = _users.map((u) => u['id'] as Object).toList();
      case 'university':
        ids = [];
      case 'cohort':
        ids = [_cohort.text.trim()];
      default:
        ids = [?_targetId];
    }
    if (_targetType != 'university' && ids.isEmpty) return showMessage(context, 'حدد المستلمين', error: true);
    setState(() => _busy = true);
    try {
      final r = await _s.api.post('/api/notifications', {
        'category': _category,
        'priority': _priority,
        'title': _title.text.trim(),
        'body': _body.text.trim(),
        'target_type': _targetType == 'users' && ids.length == 1 ? 'user' : _targetType,
        'target_ids': ids,
        'audience': _audience,
        'channels': ['inapp', if (_push) 'push', if (_sms) 'sms'],
        if (_targetType == 'course') 'course_id': _targetId,
      }) as Map<String, dynamic>;
      if (!mounted) return;
      showMessage(context, 'أُرسل إلى ${r['recipients']} مستلم');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final faculties = (_structure?['faculties'] as List<dynamic>?) ?? [];
    return Scaffold(
      appBar: AppBar(title: const Text('إرسال إشعار')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        DropdownButtonFormField<String>(
          initialValue: _category,
          decoration: const InputDecoration(labelText: 'النوع'),
          items: [
            for (final k in sendableCategories(_s.user))
              DropdownMenuItem(value: k, child: Text(categoryLabels[k] ?? k)),
          ],
          onChanged: (v) => setState(() => _category = v!),
        ),
        if (_category == 'official_warning')
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('التحذير الرسمي إجراء إداري يُسجَّل في سجل التدقيق ويصل للطلبة فقط ولا يمكن كتمه.',
                style: TextStyle(color: AppColors.warning)),
          ),
        const SizedBox(height: 12),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'normal', label: Text('عادي')),
            ButtonSegment(value: 'important', label: Text('مهم')),
            ButtonSegment(value: 'urgent', label: Text('عاجل')),
          ],
          selected: {_priority},
          onSelectionChanged: (v) => setState(() => _priority = v.first),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _targetType,
          decoration: const InputDecoration(labelText: 'المستلمون'),
          items: [for (final t in _targets) DropdownMenuItem(value: t.$1, child: Text(t.$2))],
          onChanged: (v) => setState(() {
            _targetType = v!;
            _targetId = null;
          }),
        ),
        const SizedBox(height: 12),
        if (_targetType == 'course')
          DropdownButtonFormField<int>(
            initialValue: _targetId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'المقرر'),
            items: [for (final c in _courses) DropdownMenuItem(value: c['id'] as int, child: Text('${c['code']} — ${c['title']}'))],
            onChanged: (v) => setState(() => _targetId = v),
          ),
        if (_targetType == 'faculty')
          DropdownButtonFormField<int>(
            initialValue: _targetId,
            decoration: const InputDecoration(labelText: 'الكلية'),
            items: [for (final f in faculties) DropdownMenuItem(value: f['id'] as int, child: Text(f['name'] as String))],
            onChanged: (v) => setState(() => _targetId = v),
          ),
        if (_targetType == 'department')
          DropdownButtonFormField<int>(
            initialValue: _targetId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'القسم'),
            items: [
              for (final f in faculties)
                for (final d in f['departments'] as List<dynamic>)
                  DropdownMenuItem(value: d['id'] as int, child: Text('${f['name']} — ${d['name']}')),
            ],
            onChanged: (v) => setState(() => _targetId = v),
          ),
        if (_targetType == 'cohort')
          TextField(controller: _cohort, decoration: const InputDecoration(labelText: 'سنة الدفعة مثل 2023')),
        if (_targetType == 'users') ...[
          TextField(
            controller: _search,
            decoration: const InputDecoration(labelText: 'ابحث بالاسم أو رقم القيد', prefixIcon: Icon(Icons.search)),
            onChanged: _searchUsers,
          ),
          for (final u in _results.where((u) => !_users.any((x) => x['id'] == u['id'])).take(6))
            ListTile(
              dense: true,
              leading: const Icon(Icons.person_add_alt),
              title: Text(u['full_name'] as String),
              subtitle: Text('${u['code'] ?? ''}'),
              onTap: () => setState(() => _users.add(Map<String, dynamic>.from(u as Map))),
            ),
          Wrap(spacing: 6, children: [
            for (final u in _users)
              InputChip(label: Text(u['full_name'] as String), onDeleted: () => setState(() => _users.remove(u))),
          ]),
        ],
        if (['department', 'faculty', 'cohort', 'university', 'course'].contains(_targetType) && !_instructor) ...[
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _audience,
            decoration: const InputDecoration(labelText: 'الفئة'),
            items: const [
              DropdownMenuItem(value: 'students', child: Text('الطلبة')),
              DropdownMenuItem(value: 'staff', child: Text('الموظفون وهيئة التدريس')),
              DropdownMenuItem(value: 'all', child: Text('الجميع')),
            ],
            onChanged: (v) => setState(() => _audience = v!),
          ),
        ],
        const SizedBox(height: 12),
        TextField(controller: _title, maxLength: 200, decoration: const InputDecoration(labelText: 'العنوان')),
        TextField(controller: _body, maxLines: 5, decoration: const InputDecoration(labelText: 'النص')),
        SwitchListTile(value: _push, onChanged: (v) => setState(() => _push = v), title: const Text('إشعار فوري على الهاتف')),
        SwitchListTile(
          value: _sms,
          onChanged: (v) => setState(() => _sms = v),
          title: const Text('رسالة SMS'),
          subtitle: const Text('للعاجل والتحذيرات عند تفعيلها في إعدادات الجامعة'),
        ),
        const SizedBox(height: 8),
        FilledButton.icon(
          onPressed: _busy ? null : _send,
          icon: const Icon(Icons.send),
          label: Text(_busy ? 'جارٍ الإرسال…' : 'إرسال'),
        ),
      ]),
    );
  }
}
