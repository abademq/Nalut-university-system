import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

/// Captures a photo straight from the front camera. There is deliberately no
/// gallery option: only a live capture is accepted for attendance.
class SelfieScreen extends StatefulWidget {
  const SelfieScreen({super.key, this.document = false});

  /// Photographing a document (e.g. a printed timetable) with the rear camera instead.
  final bool document;

  @override
  State<SelfieScreen> createState() => _SelfieScreenState();
}

class _SelfieScreenState extends State<SelfieScreen> {
  CameraController? _controller;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      final cams = await availableCameras();
      final want = widget.document ? CameraLensDirection.back : CameraLensDirection.front;
      final cam = cams.firstWhere((c) => c.lensDirection == want, orElse: () => cams.first);
      final c = CameraController(cam, widget.document ? ResolutionPreset.veryHigh : ResolutionPreset.medium, enableAudio: false, imageFormatGroup: ImageFormatGroup.jpeg);
      await c.initialize();
      if (!mounted) {
        await c.dispose();
        return;
      }
      setState(() => _controller = c);
    } catch (_) {
      if (mounted) {
        setState(() => _error = widget.document
            ? 'تعذر تشغيل الكاميرا. اسمح للتطبيق باستخدامها، أو اختر الصورة من المعرض.'
            : 'تعذر تشغيل الكاميرا. اسمح للتطبيق باستخدامها، أو اطلب من أستاذ المقرر تسجيلك يدوياً.');
      }
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _take() async {
    final c = _controller;
    if (c == null || _busy) return;
    setState(() => _busy = true);
    try {
      final file = await c.takePicture();
      final Uint8List bytes = await file.readAsBytes();
      if (mounted) Navigator.pop(context, bytes);
    } catch (_) {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = _controller;
    return Scaffold(
      appBar: AppBar(title: Text(widget.document ? 'تصوير' : 'صورة حية للتحقق')),
      body: Column(children: [
        if (!widget.document)
          const Padding(
          padding: EdgeInsets.all(16),
          child: Text('هذه الجلسة تتطلب صورة حية من الكاميرا الأمامية. تُحفظ مشفرة لمدة محدودة، '
              'ولا يطّلع عليها إلا المسؤول عند المراجعة.'),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: _error != null
              ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(_error!, textAlign: TextAlign.center)))
              : c == null
                  ? const Center(child: CircularProgressIndicator())
                  : Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      child: ClipRRect(borderRadius: BorderRadius.circular(16), child: Center(child: CameraPreview(c))),
                    ),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
              onPressed: c == null || _busy ? null : _take,
              icon: const Icon(Icons.camera_alt),
              label: Text(_busy ? 'جارٍ الالتقاط…' : (widget.document ? 'التقاط الصورة' : 'التقاط الصورة وإرسال الحضور')),
            ),
          ),
        ),
      ]),
    );
  }
}
