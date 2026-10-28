import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../links.dart';
import '../state/session.dart';
import '../widgets/common.dart';

class MessagesScreen extends StatefulWidget {
  const MessagesScreen({super.key});

  @override
  State<MessagesScreen> createState() => _MessagesScreenState();
}

class _MessagesScreenState extends State<MessagesScreen> {
  int _version = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('الرسائل')),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.edit),
        label: const Text('محادثة جديدة'),
        onPressed: () async {
          final id = await Navigator.push<int>(context, MaterialPageRoute(builder: (_) => const NewConversationScreen()));
          if (!context.mounted) return;
          setState(() => _version++);
          if (id != null) {
            await Navigator.push(context, MaterialPageRoute(builder: (_) => ThreadScreen(id: id)));
            if (mounted) setState(() => _version++);
          }
        },
      ),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/conversations') as List<dynamic>,
        builder: (context, list, _) {
          if (list.isEmpty) return ListView(children: const [EmptyView('لا توجد محادثات', icon: Icons.chat_bubble_outline)]);
          return ListView(padding: const EdgeInsets.all(12), children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(4, 0, 4, 8),
              child: Text('يمكن لإدارة الجامعة الاطلاع على المحادثات لأغراض الرقابة، ويُسجَّل كل اطلاع باسم من قام به.',
                  style: TextStyle(fontSize: 12, color: Colors.grey)),
            ),
            for (final c in list)
              Card(
                child: ListTile(
                  title: Text(c['subject'] as String),
                  subtitle: Text((c['participants'] as List).map((p) => p['full_name']).join('، ')),
                  trailing: (c['unread'] as int) > 0
                      ? Badge(label: Text('${c['unread']}'))
                      : Text(fmtRelative(c['last_message_at'], past: true), style: const TextStyle(fontSize: 11)),
                  onTap: () async {
                    await Navigator.push(context, MaterialPageRoute(builder: (_) => ThreadScreen(id: c['id'] as int)));
                    if (mounted) setState(() => _version++);
                  },
                ),
              ),
          ]);
        },
      ),
    );
  }
}

class NewConversationScreen extends StatefulWidget {
  const NewConversationScreen({super.key});

  @override
  State<NewConversationScreen> createState() => _NewConversationScreenState();
}

class _NewConversationScreenState extends State<NewConversationScreen> {
  Map<String, dynamic>? _to;
  final _subject = TextEditingController();
  final _body = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _subject.dispose();
    _body.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_to == null || _subject.text.trim().length < 2 || _body.text.trim().isEmpty) {
      showMessage(context, 'اختر المستلم واكتب الموضوع والرسالة', error: true);
      return;
    }
    final s = context.read<Session>();
    setState(() => _busy = true);
    try {
      final courses = _to!['course_ids'] as List<dynamic>;
      final r = await s.api.post('/api/conversations', {
        'recipient_ids': [_to!['id']],
        'subject': _subject.text.trim(),
        'body': _body.text.trim(),
        'course_id': courses.isEmpty ? null : courses.first,
      }) as Map<String, dynamic>;
      if (mounted) Navigator.pop(context, r['id'] as int);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('محادثة جديدة')),
      body: AsyncView<List<dynamic>>(
        load: () async => await s.api.get('/api/contacts') as List<dynamic>,
        builder: (context, contacts, _) => ListView(padding: const EdgeInsets.all(16), children: [
          DropdownButtonFormField<int>(
            initialValue: _to?['id'] as int?,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'إلى'),
            items: [
              for (final c in contacts)
                DropdownMenuItem(value: c['id'] as int, child: Text('${c['full_name']} — ${roleLabels[c['role']] ?? ''}')),
            ],
            onChanged: (id) => setState(() => _to = contacts.firstWhere((c) => c['id'] == id) as Map<String, dynamic>),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 6),
            child: Text('تظهر الجهات المسموح بمراسلتها وفق سياسة المؤسسة.', style: TextStyle(fontSize: 12, color: Colors.grey)),
          ),
          TextField(controller: _subject, decoration: const InputDecoration(labelText: 'الموضوع')),
          const SizedBox(height: 12),
          TextField(controller: _body, maxLines: 5, decoration: const InputDecoration(labelText: 'الرسالة')),
          const SizedBox(height: 16),
          FilledButton(onPressed: _busy ? null : _send, child: const Text('إرسال')),
        ]),
      ),
    );
  }
}

class ThreadScreen extends StatefulWidget {
  const ThreadScreen({super.key, required this.id});
  final int id;

  @override
  State<ThreadScreen> createState() => _ThreadScreenState();
}

class _ThreadScreenState extends State<ThreadScreen> with WidgetsBindingObserver {
  final _body = TextEditingController();
  Map<String, dynamic>? _data;
  Timer? _timer;
  bool _sending = false;
  UploadFile? _file; // attachment waiting to be sent

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
    // live: every few seconds only the messages newer than the last one shown (small on weak networks)
    _timer = Timer.periodic(const Duration(seconds: 4), (_) => _poll());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _active = state == AppLifecycleState.resumed;
    if (_active) _poll();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _body.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = await context.read<Session>().api.get('/api/conversations/${widget.id}/messages') as Map<String, dynamic>;
      if (mounted) setState(() => _data = d);
    } catch (e) {
      if (mounted && _data == null) showMessage(context, e, error: true);
    }
  }

  bool _active = true;
  bool _polling = false;

  Future<void> _poll() async {
    final msgs = (_data?['messages'] as List?) ?? const [];
    if (!_active || _polling || msgs.isEmpty) return;
    _polling = true;
    try {
      final lastId = (msgs.last as Map)['id'] as int;
      final d = await context.read<Session>().api.get('/api/conversations/${widget.id}/messages?after=$lastId')
          as Map<String, dynamic>;
      final got = [for (final m in (d['messages'] as List)) if ((m as Map)['id'] as int > lastId) m];
      if (got.isNotEmpty && mounted) {
        setState(() => _data = {..._data!, 'messages': [...msgs, ...got]});
      }
    } catch (_) {
      // a missed poll is retried on the next tick
    } finally {
      _polling = false;
    }
  }

  Future<void> _attach() async {
    final picked = await FilePicker.pickFiles(
        type: FileType.custom, allowedExtensions: ['pdf', 'jpg', 'jpeg', 'png', 'docx', 'doc', 'pptx', 'xlsx', 'txt', 'zip']);
    if (picked.isEmpty) return;
    final f = picked.first;
    final bytes = await f.xFile.readAsBytes();
    if (bytes.length > 5 * 1024 * 1024) {
      if (mounted) showMessage(context, 'الملف أكبر من 5 ميغابايت', error: true);
      return;
    }
    if (mounted) setState(() => _file = UploadFile('upload', f.name, bytes));
  }

  Future<void> _send() async {
    if (_body.text.trim().isEmpty && _file == null) return;
    final s = context.read<Session>();
    setState(() => _sending = true);
    try {
      await s.api.multipart('/api/conversations/${widget.id}/messages',
          fields: {'body': _body.text.trim()}, files: [?_file]);
      _body.clear();
      setState(() => _file = null);
      await _poll();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _report(Map<String, dynamic> m) async {
    final reason = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('الإبلاغ عن رسالة'),
        content: TextField(controller: reason, decoration: const InputDecoration(labelText: 'سبب الإبلاغ')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('إبلاغ')),
        ],
      ),
    );
    if (ok != true || reason.text.trim().length < 3 || !mounted) return;
    try {
      await context.read<Session>().api.post('/api/messages/${m['id']}/report', {'reason': reason.text.trim()});
      if (mounted) showMessage(context, 'تم إرسال البلاغ للإدارة');
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    final messages = (d?['messages'] as List<dynamic>? ?? []).reversed.toList();
    return Scaffold(
      appBar: AppBar(title: Text(d?['subject'] as String? ?? '')),
      body: Column(children: [
        Expanded(
          child: d == null
              ? const Center(child: CircularProgressIndicator())
              : ListView.builder(
                  reverse: true,
                  padding: const EdgeInsets.all(12),
                  itemCount: messages.length,
                  itemBuilder: (context, i) {
                    final m = messages[i] as Map<String, dynamic>;
                    final mine = m['mine'] == true;
                    return Align(
                      alignment: mine ? AlignmentDirectional.centerStart : AlignmentDirectional.centerEnd,
                      child: GestureDetector(
                        onLongPress: mine ? null : () => _report(m),
                        child: Container(
                          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
                          margin: const EdgeInsets.symmetric(vertical: 4),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: mine ? AppColors.primary.withValues(alpha: 0.12) : Theme.of(context).cardColor,
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(color: const Color(0xFFE8E0DB)),
                          ),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text('${m['sender']} · ${fmtDate(m['created_at'])}', style: const TextStyle(fontSize: 11, color: Colors.grey)),
                            const SizedBox(height: 2),
                            if ((m['body'] as String).isNotEmpty) Text(m['body'] as String),
                            if (m['file'] != null)
                              // tap to download and open with the phone's viewer
                              TextButton.icon(
                                style: TextButton.styleFrom(padding: EdgeInsets.zero, visualDensity: VisualDensity.compact),
                                icon: const Icon(Icons.attach_file, size: 18),
                                label: Text('${m['file']['name']}', overflow: TextOverflow.ellipsis),
                                onPressed: () => downloadAndOpen(context, context.read<Session>(),
                                    '/api/files/${m['file']['id']}', m['file']['name'] as String),
                              ),
                          ]),
                        ),
                      ),
                    );
                  },
                ),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 12),
          child: Text('اضغط مطولاً على رسالة للإبلاغ عنها', style: TextStyle(fontSize: 11, color: Colors.grey)),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Row(children: [
              IconButton(tooltip: 'إرفاق ملف', onPressed: _sending ? null : _attach, icon: const Icon(Icons.attach_file)),
              Expanded(
                child: TextField(
                  controller: _body,
                  minLines: 1,
                  maxLines: 4,
                  decoration: InputDecoration(
                    hintText: 'اكتب رسالتك…',
                    isDense: true,
                    helperText: _file == null ? null : 'مرفق: ${_file!.filename}',
                    suffixIcon: _file == null
                        ? null
                        : IconButton(icon: const Icon(Icons.close, size: 18), onPressed: () => setState(() => _file = null)),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(onPressed: _sending ? null : _send, icon: const Icon(Icons.send)),
            ]),
          ),
        ),
      ]),
    );
  }
}
