import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../config.dart';
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
            if (!s.isStudent)
              const SectionCard(
                child: Text('تقييم التسليمات وتنزيل الملفات متاح من لوحة التحكم على الويب.'),
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
