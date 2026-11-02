import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:geolocator/geolocator.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../api/token_store.dart';
import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'selfie_screen.dart';

/// Check-in flow: scan the rotating QR or the fixed entrance QR, type the teacher's code, or pick up
/// the teacher's phone over Bluetooth -> the session's requirements -> optional live selfie and
/// location -> server-side verification.
class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

enum _Stage { scanning, working, done }

class _ScanScreenState extends State<ScanScreen> {
  final _scanner = MobileScannerController(detectionSpeed: DetectionSpeed.noDuplicates, facing: CameraFacing.back);
  _Stage _stage = _Stage.scanning;
  String _progress = '';
  Map<String, dynamic>? _result;
  bool _handling = false;

  @override
  void dispose() {
    _scanner.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_handling) return;
    for (final b in capture.barcodes) {
      final v = b.rawValue;
      if (v != null && (v.startsWith('NUS1:') || v.startsWith('NUSP1:'))) {
        _handling = true;
        _start(payload: v);
        return;
      }
    }
  }

  Future<void> _manual() async {
    final sid = TextEditingController();
    final code = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('إدخال الرمز'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
            controller: code,
            autofocus: true,
            keyboardType: TextInputType.number,
            maxLength: 6,
            decoration: const InputDecoration(labelText: 'الرمز الذي قاله الأستاذ (4 أرقام)'),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: sid,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'رقم الجلسة (فقط مع الرمز ذي 6 أرقام تحت QR)'),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('تسجيل')),
        ],
      ),
    );
    final c = code.text.trim();
    if (ok == true && (c.length == 4 || (c.length == 6 && sid.text.trim().isNotEmpty))) {
      _handling = true;
      _start(shortCode: c, sessionId: sid.text.trim().isEmpty ? null : sid.text.trim());
    } else if (ok == true && mounted) {
      showMessage(context, 'اكتب الرمز المكون من 4 أرقام، أو الرمز ذا 6 أرقام مع رقم الجلسة', error: true);
    }
  }

  /// The teacher's phone advertises a service UUID starting with "NU" (4e55) that changes every
  /// 30 seconds; the first one heard is sent to the server, which checks it.
  Future<void> _bluetooth() async {
    if (_handling) return;
    _handling = true;
    setState(() {
      _stage = _Stage.working;
      _progress = 'جارٍ البحث عن هاتف الأستاذ عبر البلوتوث…';
    });
    await _scanner.stop();
    StreamSubscription<List<ScanResult>>? sub;
    try {
      if (await FlutterBluePlus.isSupported == false) throw ApiException(0, 'هذا الهاتف لا يدعم البلوتوث منخفض الطاقة');
      if (FlutterBluePlus.adapterStateNow != BluetoothAdapterState.on) {
        try {
          await FlutterBluePlus.turnOn();
        } catch (_) {}
        await FlutterBluePlus.adapterState
            .firstWhere((s) => s == BluetoothAdapterState.on)
            .timeout(const Duration(seconds: 10), onTimeout: () => throw ApiException(0, 'شغّل البلوتوث ثم أعد المحاولة'));
      }
      final found = Completer<String>();
      sub = FlutterBluePlus.onScanResults.listen((results) {
        for (final r in results) {
          for (final g in r.advertisementData.serviceUuids) {
            final hex = g.str128.replaceAll('-', '').toLowerCase();
            if (hex.length == 32 && hex.startsWith('4e55') && !found.isCompleted) found.complete(hex);
          }
        }
      });
      await FlutterBluePlus.startScan(timeout: const Duration(seconds: 20), androidUsesFineLocation: false);
      final hex = await found.future.timeout(const Duration(seconds: 20),
          onTimeout: () => throw ApiException(0, 'لم يُعثر على هاتف الأستاذ. اقترب منه وتأكد أن البلوتوث يعمل عنده'));
      await FlutterBluePlus.stopScan();
      await sub.cancel();
      sub = null;
      await _start(payload: 'NUB1:$hex', scannerStopped: true);
    } catch (e) {
      await sub?.cancel();
      try {
        await FlutterBluePlus.stopScan();
      } catch (_) {}
      if (!mounted) return;
      showMessage(context, e is ApiException ? e : 'تعذر استخدام البلوتوث: اسمح للتطبيق بالأجهزة القريبة وشغّل البلوتوث',
          error: true);
      setState(() {
        _stage = _Stage.scanning;
        _handling = false;
      });
      await _scanner.start();
    }
  }

  Future<Position?> _position({required bool required}) async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        if (required) throw ApiException(0, 'فعّل خدمة الموقع (GPS) في الهاتف ثم أعد المحاولة');
        return null;
      }
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
        if (required) throw ApiException(0, 'هذه الجلسة تتطلب السماح للتطبيق باستخدام الموقع');
        return null;
      }
      return await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 15)),
      );
    } on ApiException {
      rethrow;
    } catch (_) {
      if (required) throw ApiException(0, 'تعذر تحديد الموقع، حاول مرة أخرى في مكان مفتوح');
      return null;
    }
  }

  Future<void> _start({String? payload, String? shortCode, String? sessionId, bool scannerStopped = false}) async {
    final s = context.read<Session>();
    setState(() {
      _stage = _Stage.working;
      _progress = 'جارٍ التحقق من الجلسة…';
    });
    if (!scannerStopped) await _scanner.stop();
    try {
      // the code is checked the moment it is scanned; the ticket then covers the slow parts
      // (location, live photo, upload on a weak network) without the code expiring meanwhile
      final req = await s.api.post('/api/attendance/prepare', {
        'payload': ?payload,
        if (payload == null) ...{'short_code': shortCode!, 'session_id': ?(sessionId == null ? null : int.tryParse(sessionId))},
      }) as Map<String, dynamic>;
      Uint8List? selfie;
      if (req['require_selfie'] == true) {
        if (!mounted) return;
        selfie = await Navigator.push<Uint8List>(context, MaterialPageRoute(builder: (_) => const SelfieScreen()));
        if (selfie == null) throw ApiException(0, 'تم إلغاء التقاط الصورة');
      }
      Position? pos;
      if (req['require_location'] == true || req['has_geofence'] == true) {
        setState(() => _progress = 'جارٍ تحديد الموقع…');
        pos = await _position(required: req['require_location'] == true);
      }
      setState(() => _progress = 'جارٍ التحقق على الخادم…');
      final result = await s.api.multipart(
        '/api/attendance/check-in',
        fields: {
          'nonce': newNonce(),
          'ticket': req['ticket'] as String,
          'session_id': '${req['id']}',
          if (pos != null) ...{'latitude': '${pos.latitude}', 'longitude': '${pos.longitude}'},
        },
        files: [if (selfie != null) UploadFile('selfie', 'live.jpg', selfie)],
        headers: {'X-Device-Id': await deviceIdFrom(s.store)},
      ) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _result = result;
        _stage = _Stage.done;
      });
    } catch (e) {
      if (!mounted) return;
      showMessage(context, e, error: true);
      setState(() {
        _stage = _Stage.scanning;
        _handling = false;
      });
      await _scanner.start();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('تسجيل الحضور')),
      body: switch (_stage) {
        _Stage.scanning => Column(children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('وجّه الكاميرا إلى رمز QR في القاعة أو رمز الدوام المثبت عند المدخل، '
                  'أو اكتب الرمز الذي يقوله الأستاذ، أو سجّل عبر البلوتوث من هاتف الأستاذ.'),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: Stack(fit: StackFit.expand, children: [
                    MobileScanner(
                      controller: _scanner,
                      onDetect: _onDetect,
                      errorBuilder: (context, error) => Container(
                        color: Colors.black,
                        padding: const EdgeInsets.all(24),
                        alignment: Alignment.center,
                        child: const Text('تعذر تشغيل الكاميرا. اسمح للتطبيق باستخدام الكاميرا أو استخدم الرمز الرقمي.',
                            textAlign: TextAlign.center, style: TextStyle(color: Colors.white)),
                      ),
                    ),
                    IgnorePointer(
                      child: Center(
                        child: Container(
                          width: 230,
                          height: 230,
                          decoration: BoxDecoration(
                            border: Border.all(color: Colors.white, width: 3),
                            borderRadius: BorderRadius.circular(18),
                          ),
                        ),
                      ),
                    ),
                  ]),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(children: [
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: _manual,
                    icon: const Icon(Icons.dialpad),
                    label: const Text('إدخال الرمز'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: _bluetooth,
                    icon: const Icon(Icons.bluetooth_searching),
                    label: const Text('بلوتوث'),
                  ),
                ),
              ]),
            ),
          ]),
        _Stage.working => Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Text(_progress),
            ]),
          ),
        _Stage.done => _ResultView(result: _result!),
      },
    );
  }
}

class _ResultView extends StatelessWidget {
  const _ResultView({required this.result});
  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final pending = result['status'] == 'pending_review';
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(pending ? Icons.hourglass_top : Icons.check_circle,
              size: 80, color: pending ? AppColors.warning : AppColors.success),
          const SizedBox(height: 16),
          Text(result['message'] as String? ?? '', style: Theme.of(context).textTheme.titleLarge, textAlign: TextAlign.center),
          const SizedBox(height: 4),
          Text(result['session'] as String? ?? '', style: const TextStyle(color: Colors.grey)),
          Text(fmtDate(result['check_out_at'] ?? result['check_in_at'])),
          if (pending)
            const Padding(
              padding: EdgeInsets.only(top: 12),
              child: Text('بعض مؤشرات التحقق تحتاج مراجعة بشرية. لن يُتخذ أي إجراء بحقك دون مراجعة.',
                  textAlign: TextAlign.center, style: TextStyle(color: Colors.grey)),
            ),
          const SizedBox(height: 24),
          FilledButton(onPressed: () => Navigator.pop(context), child: const Text('تم')),
        ]),
      ),
    );
  }
}
