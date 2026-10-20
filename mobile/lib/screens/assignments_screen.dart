import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../links.dart';
import '../state/session.dart';
import '../widgets/common.dart';

class AssignmentsScreen extends StatefulWidget {
  const AssignmentsScreen({super.key});

  @override
  State<AssignmentsScreen> createState() => _AssignmentsScreenState();
}

class _AssignmentsScreenState extends State<AssignmentsScreen> {
  String _filter = 'open';
  int _version = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Column(children: [
      if (!s.isStudent)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('مهمة جديدة'),
              onPressed: () async {
                final created = await Navigator.push<bool>(
                    context, MaterialPageRoute(builder: (_) => const CreateAssignmentScreen()));
                if (created == true && mounted) setState(() => _version++);
              },
            ),
          ),
        ),
      if (s.isStudent)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'open', label: Text('المطلوبة')),
              ButtonSegment(value: 'done', label: Text('المسلمة')),
              ButtonSegment(value: 'all', label: Text('الكل')),
            ],
            selected: {_filter},
            onSelectionChanged: (v) => setState(() => _filter = v.first),
          ),
        ),
      Expanded(
        child: AsyncView<List<dynamic>>(
          key: ValueKey(_version),
          load: () async => await s.api.get('/api/assignments') as List<dynamic>,
          builder: (context, list, reload) {
            var items = list;
            if (s.isStudent && _filter == 'open') {
              items = list
                  .where((a) =>
                      ['not_started', 'in_progress'].contains(a['my_status']) ||
                      (a['my_status'] == 'late' && a['allow_late'] == true))
                  .toList();
            } else if (s.isStudent && _filter == 'done') {
              items = list.where((a) => ['submitted', 'reviewed'].contains(a['my_status'])).toList();
            }
            if (items.isEmpty) {
              return ListView(children: const [EmptyView('لا توجد مهام', icon: Icons.assignment_turned_in_outlined)]);
            }
            return ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: items.length,
              separatorBuilder: (_, _) => const SizedBox(height: 4),
              itemBuilder: (context, i) {
                final a = items[i] as Map<String, dynamic>;
                return Card(
                  child: ListTile(
                    title: Text(a['title'] as String),
                    subtitle: Text('${kindLabels[a['kind']] ?? a['kind']} · ${a['course_code']} · '
                        'التسليم ${fmtDate(a['due_at'])} (${fmtRelative(a['due_at'])})'
                        '${a['my_score'] != null ? ' · الدرجة ${a['my_score']}/${a['max_score']}' : ''}'),
                    trailing: s.isStudent
                        ? StatusChip.of(assignmentStatus, a['my_status'] as String?)
                        : Text('${a['stats']['submitted']}/${a['stats']['enrolled']}'),
                    onTap: () async {
                      await Navigator.push(context,
                          MaterialPageRoute(builder: (_) => AssignmentDetailScreen(id: a['id'] as int)));
                      if (mounted) setState(() => _version++);
                    },
                  ),
                );
              },
            );
          },
        ),
      ),
    ]);
  }
}

class AssignmentDetailScreen extends StatefulWidget {
  const AssignmentDetailScreen({super.key, required this.id});
  final int id;

  @override
  State<AssignmentDetailScreen> createState() => _AssignmentDetailScreenState();
}

class _AssignmentDetailScreenState extends State<AssignmentDetailScreen> {
  int _version = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('تفاصيل المهمة')),
      body: AsyncView<Map<String, dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/assignments/${widget.id}') as Map<String, dynamic>,
        builder: (context, a, reload) {
          final sub = a['submission'] as Map<String, dynamic>?;
          final due = parseDate(a['due_at']);
          final canSubmit = s.isStudent &&
              sub?['status'] != 'reviewed' &&
              (a['allow_late'] == true || (due != null && due.isAfter(DateTime.now())));
          return ListView(padding: const EdgeInsets.all(16), children: [
            Row(children: [
              Expanded(child: Text(a['title'] as String, style: Theme.of(context).textTheme.titleLarge)),
              if (a['my_status'] != null) StatusChip.of(assignmentStatus, a['my_status'] as String?),
            ]),
            const SizedBox(height: 4),
            Text('${kindLabels[a['kind']] ?? ''} · ${a['course_code']} — ${a['course_title']}',
                style: const TextStyle(color: Colors.grey)),
            const SizedBox(height: 12),
            SectionCard(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text((a['description'] as String?)?.isNotEmpty == true ? a['description'] as String : '—'),
                const Divider(height: 24),
                Text('آخر موعد: ${fmtDate(a['due_at'])} (${fmtRelative(a['due_at'])})'),
                Text('الدرجة القصوى: ${a['max_score']}'),
                Text(a['allow_late'] == true ? 'يُقبل التسليم المتأخر (يُعلَّم كمتأخر)' : 'لا يُقبل التسليم المتأخر'),
              ]),
            ),
            if (sub != null)
              SectionCard(
                title: 'تسليمي',
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(sub['status'] == 'in_progress'
                      ? 'مسودة (لم يُسلَّم نهائياً)'
                      : 'سُلّم ${fmtDate(sub['submitted_at'])}${sub['is_late'] == true ? ' (متأخر)' : ''}'),
                  for (final f in sub['files'] as List<dynamic>)
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.attach_file),
                      title: Text(f['name'] as String),
                      subtitle: Text('نسخة ${f['version']}'),
                      trailing: const Icon(Icons.open_in_new, size: 18),
                      onTap: () => downloadAndOpen(context, s, '/api/files/${f['id']}', f['name'] as String),
                    ),
                  if (sub['grade_released'] == true)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      margin: const EdgeInsets.only(top: 8),
                      decoration: BoxDecoration(
                        color: AppColors.success.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('الدرجة: ${sub['score']} / ${a['max_score']}',
                            style: const TextStyle(fontWeight: FontWeight.bold, color: AppColors.success)),
                        if ((sub['feedback'] as String?)?.isNotEmpty == true) Text('ملاحظات الأستاذ: ${sub['feedback']}'),
                      ]),
                    )
                  else if (sub['status'] == 'reviewed')
                    const Text('تمت المراجعة، وستظهر الدرجة عند نشرها.', style: TextStyle(color: Colors.grey)),
                ]),
              ),
            if (canSubmit) _SubmitCard(assignment: a, onDone: () => setState(() => _version++)),
            if (a['submissions'] != null)
              SectionCard(
                title: 'التسليمات',
                trailing: TextButton(
                  onPressed: () async {
                    try {
                      final r = await s.api.post('/api/assignments/${a['id']}/release-grades') as Map<String, dynamic>;
                      if (context.mounted) showMessage(context, 'نُشرت ${r['released']} درجة');
                      setState(() => _version++);
                    } catch (e) {
                      if (context.mounted) showMessage(context, e, error: true);
                    }
                  },
                  child: const Text('نشر الدرجات المقيّمة'),
                ),
                child: Column(children: [
                  for (final row in a['submissions'] as List<dynamic>)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(row['student']['full_name'] as String),
                      subtitle: Text([
                        '${row['student']['code'] ?? ''}',
                        if (row['submission']?['submitted_at'] != null) fmtDate(row['submission']['submitted_at']),
                        if (row['submission']?['score'] != null) 'الدرجة ${row['submission']['score']}',
                        if (row['submission']?['grade_released'] == true) 'منشورة',
                      ].join(' · ')),
                      trailing: StatusChip.of(assignmentStatus, row['status'] as String?),
                      onTap: row['submission'] == null || row['submission']['status'] == 'in_progress'
                          ? null
                          : () async {
                              await Navigator.push(context, MaterialPageRoute(
                                  builder: (_) => SubmissionScreen(assignment: a, row: row as Map<String, dynamic>)));
                              if (mounted) setState(() => _version++);
                            },
                    ),
                ]),
              ),
          ]);
        },
      ),
    );
  }
}

class _SubmitCard extends StatefulWidget {
  const _SubmitCard({required this.assignment, required this.onDone});
  final Map<String, dynamic> assignment;
  final VoidCallback onDone;

  @override
  State<_SubmitCard> createState() => _SubmitCardState();
}

class _SubmitCardState extends State<_SubmitCard> {
  final List<UploadFile> _files = [];
  final _note = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final a = widget.assignment;
    final exts = (a['allowed_extensions'] as List<dynamic>).cast<String>();
    final maxBytes = (a['max_file_mb'] as num) * 1024 * 1024;
    final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: exts);
    for (final f in picked) {
      final bytes = await f.xFile.readAsBytes();
      if (bytes.length > maxBytes) {
        if (mounted) showMessage(context, 'الملف ${f.name} أكبر من ${a['max_file_mb']} ميغابايت', error: true);
        continue;
      }
      setState(() => _files.add(UploadFile('upload', f.name, bytes)));
    }
  }

  Future<void> _send({required bool finalSubmit}) async {
    final s = context.read<Session>();
    setState(() => _busy = true);
    try {
      await s.api.multipart('/api/assignments/${widget.assignment['id']}/submission',
          fields: {'final': finalSubmit ? 'true' : 'false', 'note': _note.text}, files: _files);
      if (!mounted) return;
      showMessage(context, finalSubmit ? 'تم التسليم بنجاح' : 'تم حفظ المسودة');
      widget.onDone();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.assignment;
    final hasPrevious = (a['submission']?['files'] as List<dynamic>? ?? []).isNotEmpty;
    return SectionCard(
      title: a['submission']?['status'] == 'submitted' ? 'إعادة التسليم' : 'تسليم المهمة',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('الصيغ المسموحة: ${(a['allowed_extensions'] as List).join('، ')} — حتى ${a['max_file_mb']}MB للملف',
            style: const TextStyle(fontSize: 12, color: Colors.grey)),
        const SizedBox(height: 8),
        for (final f in _files)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.insert_drive_file_outlined),
            title: Text(f.filename),
            subtitle: Text('${(f.bytes.length / 1024).ceil()} KB'),
            trailing: IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _files.remove(f))),
          ),
        OutlinedButton.icon(
          onPressed: _busy || _files.length >= 5 ? null : _pick,
          icon: const Icon(Icons.upload_file),
          label: const Text('اختيار ملف'),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _note,
          maxLines: 2,
          decoration: const InputDecoration(labelText: 'ملاحظة للأستاذ (اختياري)'),
        ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: FilledButton(
              onPressed: _busy || (_files.isEmpty && !hasPrevious) ? null : () => _send(finalSubmit: true),
              child: Text(_busy ? 'جارٍ الرفع…' : 'تسليم نهائي'),
            ),
          ),
          const SizedBox(width: 8),
          OutlinedButton(
            onPressed: _busy || (_files.isEmpty && !hasPrevious) ? null : () => _send(finalSubmit: false),
            child: const Text('حفظ كمسودة'),
          ),
        ]),
        if (parseDate(a['due_at'])?.isBefore(DateTime.now()) == true)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('انتهى الموعد؛ سيُسجَّل التسليم كمتأخر.', style: TextStyle(color: AppColors.danger)),
          ),
      ]),
    );
  }
}


/// Teacher view of one submission: open the files, then grade and give feedback.
class SubmissionScreen extends StatefulWidget {
  const SubmissionScreen({super.key, required this.assignment, required this.row});
  final Map<String, dynamic> assignment;
  final Map<String, dynamic> row;

  @override
  State<SubmissionScreen> createState() => _SubmissionScreenState();
}

class _SubmissionScreenState extends State<SubmissionScreen> {
  late final Map<String, dynamic> _sub = widget.row['submission'] as Map<String, dynamic>;
  late final _score = TextEditingController(text: _sub['score']?.toString() ?? '');
  late final _feedback = TextEditingController(text: _sub['feedback'] as String? ?? '');
  final _reason = TextEditingController();
  bool _release = false;
  bool _busy = false;

  @override
  void dispose() {
    _score.dispose();
    _feedback.dispose();
    _reason.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final score = double.tryParse(_score.text.trim().replaceAll(',', '.'));
    final max = (widget.assignment['max_score'] as num).toDouble();
    if (score == null || score < 0 || score > max) return showMessage(context, 'أدخل درجة بين 0 و $max', error: true);
    setState(() => _busy = true);
    try {
      await context.read<Session>().api.post('/api/submissions/${_sub['id']}/grade', {
        'score': score,
        'feedback': _feedback.text.trim(),
        'release': _release,
        'reason': _reason.text.trim(),
      });
      if (!mounted) return;
      showMessage(context, _release ? 'تم الحفظ ونُشرت الدرجة للطالب' : 'تم حفظ التقييم');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    final student = widget.row['student'] as Map<String, dynamic>;
    final graded = _sub['score'] != null;
    return Scaffold(
      appBar: AppBar(title: Text(student['full_name'] as String)),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Text(widget.assignment['title'] as String, style: Theme.of(context).textTheme.titleMedium),
        Text('سُلّم ${fmtDate(_sub['submitted_at'])}${_sub['is_late'] == true ? ' (متأخر)' : ''}',
            style: TextStyle(color: _sub['is_late'] == true ? AppColors.danger : Colors.grey)),
        const SizedBox(height: 12),
        SectionCard(
          title: 'الملفات',
          child: Column(children: [
            for (final f in _sub['files'] as List<dynamic>)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.insert_drive_file_outlined),
                title: Text(f['name'] as String),
                subtitle: Text('نسخة ${f['version']} · ${((f['size'] as num) / 1024).ceil()} KB'),
                trailing: f['scan_status'] == 'clean'
                    ? const Icon(Icons.open_in_new)
                    : const StatusChip(StatusStyle('قيد الفحص', AppColors.warning)),
                onTap: f['scan_status'] == 'clean'
                    ? () => downloadAndOpen(context, s, '/api/files/${f['id']}', f['name'] as String)
                    : null,
              ),
          ]),
        ),
        if ((_sub['note'] as String?)?.isNotEmpty == true)
          SectionCard(title: 'ملاحظة الطالب', child: Text(_sub['note'] as String)),
        SectionCard(
          title: 'التقييم',
          child: Column(children: [
            TextField(
              controller: _score,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(labelText: 'الدرجة من ${widget.assignment['max_score']}'),
            ),
            const SizedBox(height: 12),
            TextField(controller: _feedback, maxLines: 4, decoration: const InputDecoration(labelText: 'الملاحظات والتغذية الراجعة')),
            if (graded) ...[
              const SizedBox(height: 12),
              TextField(controller: _reason, decoration: const InputDecoration(labelText: 'سبب تعديل الدرجة (إلزامي عند تغييرها)')),
            ],
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _release,
              onChanged: (v) => setState(() => _release = v),
              title: const Text('نشر الدرجة للطالب الآن'),
              subtitle: Text(_sub['grade_released'] == true ? 'منشورة مسبقاً' : 'وإلا تبقى مخفية حتى «نشر الدرجات المقيّمة»'),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'جارٍ الحفظ…' : 'حفظ التقييم')),
            ),
          ]),
        ),
      ]),
    );
  }
}

class CreateAssignmentScreen extends StatefulWidget {
  const CreateAssignmentScreen({super.key});

  @override
  State<CreateAssignmentScreen> createState() => _CreateAssignmentScreenState();
}

class _CreateAssignmentScreenState extends State<CreateAssignmentScreen> {
  List<dynamic> _courses = [];
  int? _course;
  String _kind = 'homework';
  final _title = TextEditingController();
  final _desc = TextEditingController();
  final _max = TextEditingController(text: '10');
  final _exts = TextEditingController(text: 'pdf, docx, jpg, png');
  DateTime _due = DateTime.now().add(const Duration(days: 7));
  bool _allowLate = true;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get('/api/courses').then((c) {
      if (mounted) setState(() => _courses = c as List<dynamic>);
    }).catchError((_) {});
  }

  @override
  void dispose() {
    for (final c in [_title, _desc, _max, _exts]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _pickDue() async {
    final d = await showDatePicker(context: context, initialDate: _due, firstDate: DateTime.now(), lastDate: DateTime.now().add(const Duration(days: 365)));
    if (d == null || !mounted) return;
    final t = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(_due));
    setState(() => _due = DateTime(d.year, d.month, d.day, t?.hour ?? 23, t?.minute ?? 59));
  }

  Future<void> _save() async {
    if (_course == null || _title.text.trim().length < 2) return showMessage(context, 'اختر المقرر واكتب العنوان', error: true);
    setState(() => _busy = true);
    try {
      await context.read<Session>().api.post('/api/courses/$_course/assignments', {
        'title': _title.text.trim(),
        'description': _desc.text.trim(),
        'kind': _kind,
        'due_at': _due.toUtc().toIso8601String(),
        'max_score': double.tryParse(_max.text) ?? 10,
        'allow_late': _allowLate,
        'allowed_extensions': _exts.text.split(RegExp(r'[\s,،]+')).where((e) => e.isNotEmpty).toList(),
      });
      if (!mounted) return;
      showMessage(context, 'تم نشر المهمة وإشعار الطلبة');
      Navigator.pop(context, true);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('مهمة جديدة')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        DropdownButtonFormField<int>(
          initialValue: _course,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'المقرر'),
          items: [for (final c in _courses) DropdownMenuItem(value: c['id'] as int, child: Text('${c['code']} — ${c['title']}'))],
          onChanged: (v) => setState(() => _course = v),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _kind,
          decoration: const InputDecoration(labelText: 'النوع'),
          items: [for (final e in kindLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
          onChanged: (v) => setState(() => _kind = v!),
        ),
        const SizedBox(height: 12),
        TextField(controller: _title, decoration: const InputDecoration(labelText: 'العنوان')),
        const SizedBox(height: 12),
        TextField(controller: _desc, maxLines: 4, decoration: const InputDecoration(labelText: 'الوصف والتعليمات')),
        const SizedBox(height: 12),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.event),
          title: const Text('موعد التسليم'),
          subtitle: Text(fmtDate(_due.toUtc().toIso8601String())),
          trailing: const Icon(Icons.edit_calendar),
          onTap: _pickDue,
        ),
        Row(children: [
          Expanded(child: TextField(controller: _max, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'الدرجة القصوى'))),
          const SizedBox(width: 12),
          Expanded(flex: 2, child: TextField(controller: _exts, textDirection: TextDirection.ltr, decoration: const InputDecoration(labelText: 'الصيغ المسموحة'))),
        ]),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: _allowLate,
          onChanged: (v) => setState(() => _allowLate = v),
          title: const Text('السماح بالتسليم المتأخر (يُعلَّم كمتأخر)'),
        ),
        FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'جارٍ النشر…' : 'نشر المهمة')),
      ]),
    );
  }
}
