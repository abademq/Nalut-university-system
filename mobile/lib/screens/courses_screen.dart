import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// Courses: the administration adds and edits courses; the administration and the course's
/// teachers set the weekly lecture times and the assessment components.
class CoursesScreen extends StatefulWidget {
  const CoursesScreen({super.key});

  @override
  State<CoursesScreen> createState() => _CoursesScreenState();
}

class _CoursesScreenState extends State<CoursesScreen> {
  int _version = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('المقررات والمحاضرات')),
      floatingActionButton: s.isAdmin
          ? FloatingActionButton.extended(
              icon: const Icon(Icons.add),
              label: const Text('مقرر جديد'),
              onPressed: () async {
                await Navigator.push(context, MaterialPageRoute(builder: (_) => const CourseFormScreen()));
                setState(() => _version++);
              },
            )
          : null,
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/courses') as List<dynamic>,
        builder: (context, courses, reload) => ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 88), children: [
          if (courses.isEmpty) const EmptyView('لا توجد مقررات'),
          for (final c in courses)
            Card(
              child: ListTile(
                title: Text('${c['code']} — ${c['title']}'),
                subtitle: Text([
                  '${c['students_count']} طالب',
                  if ((c['schedule'] as List).isNotEmpty)
                    (c['schedule'] as List).map((x) => '${dayNames[x['day']]} ${x['start']}').join('، ')
                  else
                    'بلا مواعيد',
                ].join(' · ')),
                trailing: const Icon(Icons.chevron_left),
                onTap: () async {
                  await Navigator.push(
                      context, MaterialPageRoute(builder: (_) => CourseFormScreen(courseId: c['id'] as int)));
                  setState(() => _version++);
                },
              ),
            ),
        ]),
      ),
    );
  }
}

class CourseFormScreen extends StatefulWidget {
  const CourseFormScreen({super.key, this.courseId});
  final int? courseId; // null: new course

  @override
  State<CourseFormScreen> createState() => _CourseFormScreenState();
}

class _CourseFormScreenState extends State<CourseFormScreen> {
  final _code = TextEditingController();
  final _title = TextEditingController();
  final _credits = TextEditingController(text: '3');
  int? _facultyId;
  int? _departmentId;
  int? _termId;
  List<Map<String, dynamic>> _slots = [];
  List<Map<String, dynamic>> _components = [];
  Map<String, dynamic>? _structure;
  bool _loading = true;
  bool _busy = false;
  String _resultStatus = 'draft';

  bool get _isNew => widget.courseId == null;
  bool get _mayEditComponents {
    final s = context.read<Session>();
    return s.isAdmin || s.can('courses.components');
  }

  bool get _mayEditSchedule {
    final s = context.read<Session>();
    return s.isAdmin || s.can('courses.schedule');
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _code.dispose();
    _title.dispose();
    _credits.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final s = context.read<Session>();
    try {
      if (s.isAdmin) _structure = await s.api.get('/api/org/structure') as Map<String, dynamic>;
      if (_isNew) {
        _facultyId = (s.user?['faculty'] as Map?)?['id'] as int?;
        final terms = (_structure?['terms'] as List?) ?? const [];
        _termId = terms.where((t) => t['is_current'] == true).map((t) => t['id'] as int).firstOrNull;
      } else {
        final c = await s.api.get('/api/courses/${widget.courseId}') as Map<String, dynamic>;
        _code.text = c['code'] as String;
        _title.text = c['title'] as String;
        _credits.text = '${c['credits']}';
        _facultyId = c['faculty_id'] as int?;
        _departmentId = c['department_id'] as int?;
        _termId = c['term_id'] as int?;
        _slots = [for (final x in c['schedule'] as List) Map<String, dynamic>.from(x as Map)];
        _components = [for (final x in (c['components'] as List? ?? const [])) Map<String, dynamic>.from(x as Map)];
        try {
          final g = await s.api.get('/api/courses/${widget.courseId}/grades') as Map<String, dynamic>;
          _resultStatus = g['result']['status'] as String;
        } catch (_) {}
      }
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
    if (mounted) setState(() => _loading = false);
  }

  List<dynamic> get _faculties => (_structure?['faculties'] as List?) ?? const [];
  List<dynamic> get _departments =>
      (_faculties.where((f) => f['id'] == _facultyId).firstOrNull?['departments'] as List?) ?? const [];

  Future<void> _save() async {
    final s = context.read<Session>();
    setState(() => _busy = true);
    try {
      if (_isNew) {
        await s.api.post('/api/courses', {
          'code': _code.text.trim(),
          'title': _title.text.trim(),
          'credits': int.tryParse(_credits.text) ?? 3,
          'faculty_id': _facultyId,
          'department_id': _departmentId,
          'term_id': _termId,
          'schedule': _slots,
        });
      } else {
        await s.api.patch('/api/courses/${widget.courseId}', {
          if (s.isAdmin) ...{
            'code': _code.text.trim(),
            'title': _title.text.trim(),
            'credits': int.tryParse(_credits.text) ?? 3,
            'department_id': _departmentId,
            'term_id': _termId,
          },
          'schedule': _slots,
        });
      }
      if (!mounted) return;
      showMessage(context, 'حُفظ المقرر');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editSlot([int? index]) async {
    final slot = index == null ? {'day': 0, 'start': '08:30', 'end': '10:00', 'room': ''} : Map.of(_slots[index]);
    final room = TextEditingController(text: slot['room'] as String? ?? '');
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setD) {
          Future<void> pick(String key) async {
            final parts = (slot[key] as String).split(':');
            final t = await showTimePicker(
                context: ctx, initialTime: TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1])));
            if (t != null) {
              setD(() => slot[key] = '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}');
            }
          }

          return AlertDialog(
            title: Text(index == null ? 'موعد جديد' : 'تعديل الموعد'),
            content: Column(mainAxisSize: MainAxisSize.min, children: [
              DropdownButtonFormField<int>(
                initialValue: slot['day'] as int,
                decoration: const InputDecoration(labelText: 'اليوم'),
                items: [for (var i = 0; i < 7; i++) DropdownMenuItem(value: i, child: Text(dayNames[i]))],
                onChanged: (v) => setD(() => slot['day'] = v),
              ),
              Row(children: [
                Expanded(child: OutlinedButton(onPressed: () => pick('start'), child: Text('من ${slot['start']}'))),
                const SizedBox(width: 8),
                Expanded(child: OutlinedButton(onPressed: () => pick('end'), child: Text('إلى ${slot['end']}'))),
              ]),
              TextField(controller: room, decoration: const InputDecoration(labelText: 'القاعة')),
            ]),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('إلغاء')),
              FilledButton(
                onPressed: () => Navigator.pop(ctx, {...slot, 'room': room.text.trim()}),
                child: const Text('تم'),
              ),
            ],
          );
        },
      ),
    );
    if (result == null) return;
    setState(() => index == null ? _slots.add(result) : _slots[index] = result);
  }

  Future<void> _componentDialog([Map<String, dynamic>? comp]) async {
    final s = context.read<Session>();
    final name = TextEditingController(text: comp?['name'] as String? ?? '');
    final max = TextEditingController(text: comp == null ? '' : '${comp['max_score']}');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(comp == null ? 'عنصر تقييم جديد' : 'تعديل عنصر التقييم'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: name, decoration: const InputDecoration(labelText: 'الاسم (مثل: الامتحان النصفي)')),
          TextField(
            controller: max,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'الدرجة العظمى'),
          ),
        ]),
        actions: [
          if (comp != null)
            TextButton(
              onPressed: () async {
                try {
                  await s.api.delete('/api/components/${comp['id']}');
                  if (ctx.mounted) Navigator.pop(ctx, true);
                } catch (e) {
                  if (ctx.mounted) showMessage(ctx, e, error: true);
                }
              },
              child: const Text('حذف', style: TextStyle(color: AppColors.danger)),
            ),
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(
            onPressed: () async {
              final body = {'name': name.text.trim(), 'max_score': double.tryParse(max.text.trim().replaceAll('٫', '.'))};
              try {
                if (comp == null) {
                  await s.api.post('/api/courses/${widget.courseId}/components', body);
                } else {
                  await s.api.patch('/api/components/${comp['id']}', body);
                }
                if (ctx.mounted) Navigator.pop(ctx, true);
              } catch (e) {
                if (ctx.mounted) showMessage(ctx, e, error: true);
              }
            },
            child: const Text('حفظ'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final c = await s.api.get('/api/courses/${widget.courseId}') as Map<String, dynamic>;
    if (mounted) {
      setState(() => _components = [for (final x in c['components'] as List) Map<String, dynamic>.from(x as Map)]);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    final admin = s.isAdmin;
    if (_loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final total = _components.fold<num>(0, (a, c) => a + (c['max_score'] as num));
    return Scaffold(
      appBar: AppBar(title: Text(_isNew ? 'مقرر جديد' : _code.text)),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: FilledButton.icon(
            icon: const Icon(Icons.save_outlined),
            label: Text(_isNew ? 'إنشاء المقرر' : 'حفظ البيانات والمواعيد'),
            onPressed: _busy ? null : _save,
          ),
        ),
      ),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        SectionCard(
          title: 'بيانات المقرر',
          child: Column(children: [
            TextField(controller: _code, enabled: admin, decoration: const InputDecoration(labelText: 'الرمز (مثل CS101)')),
            const SizedBox(height: 8),
            TextField(controller: _title, enabled: admin, decoration: const InputDecoration(labelText: 'الاسم')),
            const SizedBox(height: 8),
            TextField(
              controller: _credits,
              enabled: admin,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'الوحدات'),
            ),
            if (admin && _isNew && s.role == 'university_admin') ...[
              const SizedBox(height: 8),
              DropdownButtonFormField<int>(
                initialValue: _facultyId,
                decoration: const InputDecoration(labelText: 'الكلية'),
                items: [for (final f in _faculties) DropdownMenuItem(value: f['id'] as int, child: Text('${f['name']}'))],
                onChanged: (v) => setState(() {
                  _facultyId = v;
                  _departmentId = null;
                }),
              ),
            ],
            if (admin) ...[
              const SizedBox(height: 8),
              DropdownButtonFormField<int?>(
                initialValue: _departments.any((d) => d['id'] == _departmentId) ? _departmentId : null,
                decoration: const InputDecoration(labelText: 'القسم'),
                items: [
                  const DropdownMenuItem<int?>(value: null, child: Text('—')),
                  for (final d in _departments) DropdownMenuItem<int?>(value: d['id'] as int, child: Text('${d['name']}')),
                ],
                onChanged: (v) => setState(() => _departmentId = v),
              ),
              const SizedBox(height: 8),
              DropdownButtonFormField<int?>(
                initialValue: _termId,
                decoration: const InputDecoration(labelText: 'الفصل الدراسي'),
                items: [
                  const DropdownMenuItem<int?>(value: null, child: Text('—')),
                  for (final t in (_structure?['terms'] as List?) ?? const [])
                    DropdownMenuItem<int?>(value: t['id'] as int, child: Text('${t['name']}')),
                ],
                onChanged: (v) => setState(() => _termId = v),
              ),
            ],
            if (!admin)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text('بيانات المقرر تعدّلها الإدارة؛ يمكنك تعديل مواعيد محاضراتك وعناصر التقييم.',
                    style: TextStyle(color: Colors.grey)),
              ),
          ]),
        ),
        SectionCard(
          title: 'مواعيد المحاضرات الأسبوعية',
          trailing: _mayEditSchedule
              ? IconButton(tooltip: 'إضافة موعد', icon: const Icon(Icons.add), onPressed: () => _editSlot())
              : null,
          child: Column(children: [
            if (_slots.isEmpty) const Text('لا توجد مواعيد بعد', style: TextStyle(color: Colors.grey)),
            for (var i = 0; i < _slots.length; i++)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.schedule),
                title: Text('${dayNames[_slots[i]['day']]}  ${_slots[i]['start']} – ${_slots[i]['end']}'),
                subtitle: (_slots[i]['room'] as String?)?.isNotEmpty == true ? Text('القاعة ${_slots[i]['room']}') : null,
                onTap: _mayEditSchedule ? () => _editSlot(i) : null,
                trailing: !_mayEditSchedule ? null : IconButton(
                  icon: const Icon(Icons.delete_outline),
                  onPressed: () => setState(() => _slots.removeAt(i)),
                ),
              ),
            const Text('تُحفظ المواعيد مع زر الحفظ أسفل الشاشة، وتظهر في «جدولي الأسبوعي».',
                style: TextStyle(fontSize: 12, color: Colors.grey)),
          ]),
        ),
        if (!_isNew)
          SectionCard(
            title: 'عناصر التقييم (المجموع $total)',
            trailing: _resultStatus == 'draft' && _mayEditComponents
                ? IconButton(tooltip: 'إضافة عنصر', icon: const Icon(Icons.add), onPressed: () => _componentDialog())
                : null,
            child: Column(children: [
              if (_resultStatus != 'draft')
                const Text('النتائج مرفوعة؛ لا يمكن تعديل عناصر التقييم إلا بعد إرجاعها للمسودة.',
                    style: TextStyle(color: AppColors.warning)),
              if (_components.isEmpty) const Text('لا توجد عناصر تقييم', style: TextStyle(color: Colors.grey)),
              for (final c in _components)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text('${c['name']}'),
                  trailing: Text('من ${c['max_score']}'),
                  onTap: _resultStatus == 'draft' && _mayEditComponents ? () => _componentDialog(c) : null,
                ),
            ]),
          ),
      ]),
    );
  }
}
