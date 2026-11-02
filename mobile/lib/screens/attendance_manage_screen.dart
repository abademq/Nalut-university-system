import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_ble_peripheral/flutter_ble_peripheral.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'attendance_screen.dart';

const riskFlags = {
  'outside_geofence': 'خارج نطاق القاعة',
  'shared_device': 'جهاز مشترك مع حساب آخر',
  'device_used_by_other_account': 'جهاز استُخدم لحساب آخر مؤخراً',
  'new_device': 'جهاز جديد',
  'no_device_id': 'بدون معرّف جهاز',
  'face_no_match': 'عدم تطابق الوجه',
  'early_leave': 'انصراف مبكر',
};

/// Instructors and administration: sessions, live rotating QR, manual marks and review.
class AttendanceManageScreen extends StatefulWidget {
  const AttendanceManageScreen({super.key});

  @override
  State<AttendanceManageScreen> createState() => _AttendanceManageScreenState();
}

class _AttendanceManageScreenState extends State<AttendanceManageScreen> {
  int _version = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return AsyncView<List<dynamic>>(
      key: ValueKey(_version),
      load: () async => await s.api.get('/api/attendance/sessions') as List<dynamic>,
      builder: (context, sessions, reload) => ListView(padding: const EdgeInsets.all(12), children: [
        Row(children: [
          Expanded(
            child: FilledButton.icon(
              icon: const Icon(Icons.qr_code_2),
              label: const Text('جلسة حضور جديدة'),
              onPressed: () async {
                final created = await Navigator.push<Map<String, dynamic>>(
                    context, MaterialPageRoute(builder: (_) => const NewSessionScreen()));
                if (created != null && context.mounted) {
                  await Navigator.push(context, MaterialPageRoute(builder: (_) => LiveSessionScreen(id: created['id'] as int)));
                  setState(() => _version++);
                }
              },
            ),
          ),
          const SizedBox(width: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.fact_check_outlined),
            label: const Text('المراجعة'),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ReviewQueueScreen())),
          ),
        ]),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          icon: const Icon(Icons.person_pin_circle_outlined),
          label: const Text('حضوري الشخصي (الدوام)'),
          onPressed: () => Navigator.push(context, MaterialPageRoute(
              builder: (_) => Scaffold(appBar: AppBar(title: const Text('حضوري')), body: const AttendanceScreen()))),
        ),
        const SizedBox(height: 8),
        if (sessions.isEmpty) const EmptyView('لا توجد جلسات بعد', icon: Icons.event_busy),
        for (final x in sessions)
          Card(
            child: ListTile(
              title: Text(x['title'] as String),
              subtitle: Text('${fmtDate(x['starts_at'])} · حضور ${((x['counts']['present'] ?? 0) as num) + ((x['counts']['late'] ?? 0) as num)}'
                  '${x['expected'] != null ? '/${x['expected']}' : ''} · غياب ${x['counts']['absent'] ?? 0}'
                  '${(x['counts']['pending_review'] ?? 0) != 0 ? ' · مراجعة ${x['counts']['pending_review']}' : ''}'),
              trailing: x['status'] == 'open'
                  ? const StatusChip(StatusStyle('مفتوحة', AppColors.success))
                  : const StatusChip(StatusStyle('مغلقة', Colors.grey)),
              onTap: () async {
                await Navigator.push(context, MaterialPageRoute(builder: (_) => LiveSessionScreen(id: x['id'] as int)));
                if (mounted) setState(() => _version++);
              },
            ),
          ),
      ]),
    );
  }
}

class NewSessionScreen extends StatefulWidget {
  const NewSessionScreen({super.key});

  @override
  State<NewSessionScreen> createState() => _NewSessionScreenState();
}

class _NewSessionScreenState extends State<NewSessionScreen> {
  List<dynamic> _courses = [];
  int? _course;
  String _kind = 'course';
  String _risk = 'normal';
  String _method = 'code'; // code | bluetooth | qr
  int _codeSeconds = 120;
  final _location = TextEditingController();
  final _duration = TextEditingController(); // empty: the institution's default
  Position? _pos;
  bool _geofence = false;
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
    _location.dispose();
    _duration.dispose();
    super.dispose();
  }

  bool get _isAdmin => context.read<Session>().can('attendance.staff'); // may open staff shifts

  Future<void> _locate() async {
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      final p = await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 15)));
      setState(() {
        _pos = p;
        _geofence = true;
      });
    } catch (_) {
      if (mounted) showMessage(context, 'تعذر تحديد الموقع. فعّل GPS واسمح للتطبيق باستخدامه.', error: true);
    }
  }

  Future<void> _create() async {
    if (_kind == 'course' && _course == null) return showMessage(context, 'اختر المقرر', error: true);
    final method = _kind == 'course' ? _method : 'qr';
    if (method == 'code' && _pos == null) {
      await _locate(); // the room's location is what keeps a shared code from counting at home
      if (_pos == null) return;
    }
    if (!mounted) return;
    if (_geofence && _pos == null) {
      return showMessage(context, 'التحقق بالموقع يتطلب تحديد موقع القاعة: اضغط «استخدام موقعي الحالي» وأنت داخلها', error: true);
    }
    setState(() => _busy = true);
    try {
      final r = await context.read<Session>().api.post('/api/attendance/sessions', {
        'kind': _kind,
        if (_kind == 'course') 'course_id': _course,
        'location': _location.text.trim().isEmpty ? null : _location.text.trim(),
        if (int.tryParse(_duration.text) != null) 'duration_minutes': int.parse(_duration.text),
        'risk_level': _risk,
        'method': method,
        if (method == 'code') 'code_seconds': _codeSeconds,
        if ((_geofence || method == 'code') && _pos != null) ...{'latitude': _pos!.latitude, 'longitude': _pos!.longitude},
      }) as Map<String, dynamic>;
      if (mounted) Navigator.pop(context, r);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('جلسة حضور جديدة')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        if (_isAdmin)
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'course', label: Text('محاضرة')),
              ButtonSegment(value: 'staff', label: Text('دوام الموظفين')),
            ],
            selected: {_kind},
            onSelectionChanged: (v) => setState(() => _kind = v.first),
          ),
        const SizedBox(height: 12),
        if (_kind == 'course')
          DropdownButtonFormField<int>(
            initialValue: _course,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'المقرر'),
            items: [for (final c in _courses) DropdownMenuItem(value: c['id'] as int, child: Text('${c['code']} — ${c['title']}'))],
            onChanged: (v) => setState(() => _course = v),
          ),
        if (_kind == 'course') ...[
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _method,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'طريقة التسجيل'),
            items: const [
              DropdownMenuItem(value: 'code', child: Text('رمز من 4 أرقام أقوله للطلبة (بدون شاشة)')),
              DropdownMenuItem(value: 'bluetooth', child: Text('بلوتوث من هاتفي (بدون شاشة ولا رمز)')),
              DropdownMenuItem(value: 'qr', child: Text('رمز QR على شاشة أو جهاز عرض')),
            ],
            onChanged: (v) => setState(() => _method = v!),
          ),
          if (_method == 'code') ...[
            const SizedBox(height: 12),
            DropdownButtonFormField<int>(
              initialValue: _codeSeconds,
              decoration: const InputDecoration(labelText: 'مدة الرمز قبل أن يتغير'),
              items: const [
                DropdownMenuItem(value: 30, child: Text('30 ثانية')),
                DropdownMenuItem(value: 60, child: Text('دقيقة')),
                DropdownMenuItem(value: 120, child: Text('دقيقتان')),
                DropdownMenuItem(value: 300, child: Text('5 دقائق')),
                DropdownMenuItem(value: 600, child: Text('10 دقائق')),
                DropdownMenuItem(value: 0, child: Text('رمز واحد طوال المحاضرة')),
              ],
              onChanged: (v) => setState(() => _codeSeconds = v!),
            ),
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text('يُحفظ موقعك الحالي كموقع للقاعة: من يرسل له زميله الرمز وهو خارجها يُحال للمراجعة.',
                  style: TextStyle(fontSize: 12, color: Colors.grey)),
            ),
          ],
          if (_method == 'bluetooth')
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text('أبقِ هذه الشاشة مفتوحة والبلوتوث يعمل؛ هواتف الطلبة القريبة (نحو 10–30 متراً) تلتقط إشارة هاتفك.',
                  style: TextStyle(fontSize: 12, color: Colors.grey)),
            ),
        ],
        const SizedBox(height: 12),
        TextField(controller: _location, decoration: const InputDecoration(labelText: 'المكان / القاعة')),
        const SizedBox(height: 12),
        TextField(controller: _duration, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'المدة (دقيقة)', hintText: 'الافتراضي من إعدادات المؤسسة')),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _risk,
          decoration: const InputDecoration(labelText: 'مستوى التحقق'),
          items: const [
            DropdownMenuItem(value: 'normal', child: Text('عادي — QR ديناميكي')),
            DropdownMenuItem(value: 'high', child: Text('مرتفع (امتحان) — QR + موقع + صورة حية')),
          ],
          onChanged: (v) => setState(() => _risk = v!),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: _locate,
          icon: const Icon(Icons.my_location),
          label: Text(_pos == null ? 'استخدام موقعي الحالي كموقع للقاعة' : 'تم تحديد الموقع (±${_pos!.accuracy.round()} م)'),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 6),
          child: Text('النطاق الجغرافي إشارة مساعدة فقط: من يسجّل من خارجه يُحال للمراجعة ولا يُرفض تلقائياً.',
              style: TextStyle(fontSize: 12, color: Colors.grey)),
        ),
        const SizedBox(height: 8),
        FilledButton(onPressed: _busy ? null : _create, child: Text(_busy ? 'جارٍ الإنشاء…' : 'بدء الجلسة')),
      ]),
    );
  }
}

/// Shows the rotating QR (refreshed just after each rotation) plus the live roll.
class LiveSessionScreen extends StatefulWidget {
  const LiveSessionScreen({super.key, required this.id});
  final int id;

  @override
  State<LiveSessionScreen> createState() => _LiveSessionScreenState();
}

class _LiveSessionScreenState extends State<LiveSessionScreen> {
  Map<String, dynamic>? _session;
  Map<String, dynamic>? _qr;
  Timer? _qrTimer;
  Timer? _rollTimer;
  bool _showRoll = false;

  Session get _s => context.read<Session>();

  @override
  void initState() {
    super.initState();
    _loadSession();
    _rollTimer = Timer.periodic(const Duration(seconds: 10), (_) => _loadSession());
  }

  @override
  void dispose() {
    _qrTimer?.cancel();
    _rollTimer?.cancel();
    if (_advertising) FlutterBlePeripheral().stop().catchError((_) => PeripheralBluetoothState.unknown);
    super.dispose();
  }

  bool _advertising = false;
  String? _bleError;
  String get _method => _session?['method'] as String? ?? 'qr';

  Future<void> _advertise(String uuid) async {
    final ble = FlutterBlePeripheral();
    try {
      if (_advertising) await ble.stop();
      var perm = await ble.hasPermission();
      if (perm != PeripheralBluetoothState.granted) perm = await ble.requestPermission();
      if (perm == PeripheralBluetoothState.denied || perm == PeripheralBluetoothState.permanentlyDenied) {
        throw Exception('perm');
      }
      if (!await ble.isBluetoothOn) await ble.enableBluetooth();
      await ble.start(advertiseData: AdvertiseDataCore(serviceUuids: [uuid]));
      _advertising = true;
      _bleError = null;
    } catch (_) {
      _advertising = false;
      _bleError = 'تعذر بث البلوتوث: شغّل البلوتوث واسمح للتطبيق بالأجهزة القريبة';
    }
  }

  Future<void> _loadSession() async {
    try {
      final d = await _s.api.get('/api/attendance/sessions/${widget.id}') as Map<String, dynamic>;
      if (!mounted) return;
      final wasOpen = _session?['status'] == 'open';
      setState(() => _session = d);
      if (d['status'] == 'open' && (!wasOpen || _qr == null)) _loadQr();
    } catch (e) {
      if (mounted && _session == null) showMessage(context, e, error: true);
    }
  }

  Future<void> _loadQr() async {
    _qrTimer?.cancel();
    try {
      final path = switch (_method) { 'code' => 'code', 'bluetooth' => 'ble', _ => 'qr' };
      final q = await _s.api.get('/api/attendance/sessions/${widget.id}/$path') as Map<String, dynamic>;
      if (_method == 'bluetooth') await _advertise(q['uuid'] as String);
      if (!mounted) return;
      setState(() => _qr = q);
      final ms = ((q['expires_in'] as num) * 1000).round() + 300;
      _qrTimer = Timer(Duration(milliseconds: ms < 1000 ? 1000 : ms), _loadQr);
    } catch (_) {
      if (mounted) setState(() => _qr = null);
    }
  }

  Future<void> _close() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('إغلاق الجلسة؟'),
        content: const Text('سيُسجَّل غياب كل من لم يسجّل حضوره.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('إغلاق')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await _s.api.post('/api/attendance/sessions/${widget.id}/close');
      _qrTimer?.cancel();
      if (_advertising) {
        await FlutterBlePeripheral().stop();
        _advertising = false;
      }
      setState(() => _qr = null);
      await _loadSession();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  Future<String?> _reason(String title) async {
    final ctrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: TextField(controller: ctrl, autofocus: true, decoration: const InputDecoration(labelText: 'السبب (إلزامي)')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('حفظ')),
        ],
      ),
    );
    return ok == true && ctrl.text.trim().length >= 3 ? ctrl.text.trim() : null;
  }

  Future<void> _mark(Map<String, dynamic> person) async {
    final status = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(title: Text(person['user']['full_name'] as String, style: const TextStyle(fontWeight: FontWeight.bold))),
          for (final e in const {'present': 'حاضر', 'late': 'متأخر', 'excused': 'بعذر', 'absent': 'غائب'}.entries)
            ListTile(title: Text(e.value), onTap: () => Navigator.pop(ctx, e.key)),
        ]),
      ),
    );
    if (status == null) return;
    final reason = await _reason('سبب التسجيل اليدوي');
    if (reason == null) return;
    try {
      await _s.api.post('/api/attendance/sessions/${widget.id}/manual',
          {'user_id': person['user']['id'], 'status': status, 'reason': reason});
      await _loadSession();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _session;
    final open = d?['status'] == 'open';
    final people = (d?['people'] as List<dynamic>?) ?? [];
    final counts = (d?['counts'] as Map<String, dynamic>?) ?? {};
    final present = ((counts['present'] ?? 0) as num) + ((counts['late'] ?? 0) as num);
    return Scaffold(
      appBar: AppBar(
        title: Text(d?['title'] as String? ?? 'الجلسة'),
        actions: [
          IconButton(
            icon: Icon(_showRoll ? Icons.qr_code_2 : Icons.people_outline),
            tooltip: _showRoll ? 'الرمز' : 'قائمة الحضور',
            onPressed: () => setState(() => _showRoll = !_showRoll),
          ),
          if (open) IconButton(icon: const Icon(Icons.stop_circle_outlined), tooltip: 'إغلاق الجلسة', onPressed: _close),
        ],
      ),
      body: d == null
          ? const Center(child: CircularProgressIndicator())
          : (!_showRoll && open && _qr != null)
              ? Center(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(16),
                    child: Column(children: [
                      Text('سجّل $present${d['expected'] != null ? ' من ${d['expected']}' : ''}',
                          style: const TextStyle(color: AppColors.success, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 12),
                      if (_method == 'code') ...[
                        const Text('قل هذا الرمز للطلبة أو اكتبه على السبورة:'),
                        const SizedBox(height: 8),
                        Text('${_qr!['code']}',
                            textDirection: TextDirection.ltr,
                            style: const TextStyle(fontSize: 72, letterSpacing: 14, fontWeight: FontWeight.bold)),
                        Text(
                            (_qr!['code_seconds'] as num) == 0
                                ? 'الرمز نفسه حتى نهاية المحاضرة'
                                : 'يتغير كل ${_qr!['code_seconds']} ثانية تلقائياً',
                            style: const TextStyle(color: Colors.grey)),
                        const SizedBox(height: 8),
                        const Text('يكتبه الطالب في التطبيق: تسجيل الحضور ← إدخال الرمز.',
                            style: TextStyle(fontSize: 12, color: Colors.grey)),
                      ] else if (_method == 'bluetooth') ...[
                        Icon(_advertising ? Icons.bluetooth_audio : Icons.bluetooth_disabled,
                            size: 96, color: _advertising ? AppColors.success : Colors.grey),
                        const SizedBox(height: 8),
                        Text(_advertising ? 'هاتفك يبث الحضور الآن' : (_bleError ?? 'جارٍ تشغيل البلوتوث…'),
                            textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.bold)),
                        const SizedBox(height: 8),
                        const Text('أبقِ هذه الشاشة مفتوحة. يضغط الطالب «بلوتوث» في شاشة تسجيل الحضور وهو قريب منك.',
                            textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: Colors.grey)),
                        if (!_advertising) TextButton(onPressed: _loadQr, child: const Text('إعادة المحاولة')),
                      ] else ...[
                        Container(
                          color: Colors.white,
                          padding: const EdgeInsets.all(12),
                          child: QrImageView(data: _qr!['payload'] as String, size: 300, backgroundColor: Colors.white),
                        ),
                        const SizedBox(height: 12),
                        Text('يتجدد الرمز كل ${_qr!['rotation_seconds']} ثانية', style: const TextStyle(color: Colors.grey)),
                        const SizedBox(height: 8),
                        Text('رقم الجلسة ${widget.id}'),
                        Text('${_qr!['short_code']}',
                            textDirection: TextDirection.ltr,
                            style: const TextStyle(fontSize: 34, letterSpacing: 6, fontWeight: FontWeight.bold)),
                      ],
                      const SizedBox(height: 16),
                      OutlinedButton.icon(
                        onPressed: () => setState(() => _showRoll = true),
                        icon: const Icon(Icons.people_outline),
                        label: const Text('قائمة الحضور والتسجيل اليدوي'),
                      ),
                    ]),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadSession,
                  child: ListView(padding: const EdgeInsets.all(12), children: [
                    if (!open) const Padding(padding: EdgeInsets.only(bottom: 8), child: Text('الجلسة مغلقة.', style: TextStyle(color: Colors.grey))),
                    Wrap(spacing: 6, runSpacing: 6, children: [
                      for (final e in attendanceStatus.entries)
                        StatusChip(StatusStyle('${e.value.label}: ${counts[e.key] ?? 0}', e.value.color)),
                    ]),
                    const SizedBox(height: 8),
                    const Text('اضغط على أي اسم لتسجيله يدوياً مع ذكر السبب.', style: TextStyle(fontSize: 12, color: Colors.grey)),
                    for (final p in people)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(p['user']['full_name'] as String),
                        subtitle: Text([
                          '${p['user']['code'] ?? ''}',
                          if (p['record']?['check_in_at'] != null) fmtDate(p['record']['check_in_at']),
                          for (final f in (p['record']?['risk_flags'] as List<dynamic>? ?? [])) riskFlags[f] ?? '$f',
                        ].join(' · ')),
                        trailing: p['record'] == null
                            ? const StatusChip(StatusStyle('لم يسجل', Colors.grey))
                            : StatusChip.of(attendanceStatus, p['record']['status'] as String?),
                        onTap: () => _mark(Map<String, dynamic>.from(p as Map)),
                      ),
                  ]),
                ),
    );
  }
}

class ReviewQueueScreen extends StatefulWidget {
  const ReviewQueueScreen({super.key});

  @override
  State<ReviewQueueScreen> createState() => _ReviewQueueScreenState();
}

class _ReviewQueueScreenState extends State<ReviewQueueScreen> {
  int _version = 0;

  Future<void> _decide(int id, bool approve) async {
    final ctrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(approve ? 'قبول التسجيل' : 'رفض التسجيل'),
        content: TextField(controller: ctrl, decoration: const InputDecoration(labelText: 'السبب (إلزامي)')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('تأكيد')),
        ],
      ),
    );
    if (ok != true || ctrl.text.trim().length < 3 || !mounted) return;
    try {
      await context.read<Session>().api.post('/api/attendance/records/$id/review', {'approve': approve, 'reason': ctrl.text.trim()});
      if (mounted) setState(() => _version++);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('تسجيلات بانتظار المراجعة')),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/attendance/review-queue') as List<dynamic>,
        builder: (context, rows, _) => ListView(padding: const EdgeInsets.all(12), children: [
          const Text('تُحال هنا التسجيلات ذات المؤشرات غير المعتادة. لا تُعد أي إشارة وحدها دليلاً على المخالفة.',
              style: TextStyle(color: Colors.grey)),
          if (rows.isEmpty) const EmptyView('لا توجد حالات للمراجعة', icon: Icons.verified_outlined),
          for (final q in rows)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${q['user']['full_name']} (${q['user']['code'] ?? ''})', style: const TextStyle(fontWeight: FontWeight.bold)),
                  Text('${q['session']['title']} · ${fmtDate(q['record']['check_in_at'])}', style: const TextStyle(fontSize: 12)),
                  Wrap(spacing: 6, children: [
                    for (final f in q['record']['risk_flags'] as List<dynamic>) StatusChip(StatusStyle(riskFlags[f] ?? '$f', AppColors.warning)),
                  ]),
                  const SizedBox(height: 8),
                  Row(children: [
                    FilledButton(onPressed: () => _decide(q['record']['id'] as int, true), child: const Text('قبول')),
                    const SizedBox(width: 8),
                    OutlinedButton(onPressed: () => _decide(q['record']['id'] as int, false), child: const Text('رفض')),
                  ]),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}
