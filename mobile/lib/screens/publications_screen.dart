import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../links.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// Image bytes of protected files, kept for the app's lifetime (posters are small and reused).
class _ImageCache {
  static final Map<int, Future<Uint8List>> _items = {};

  static Future<Uint8List> load(Session s, int fileId) =>
      _items.putIfAbsent(fileId, () => s.api.getBytes('/api/files/$fileId').catchError((Object e) {
            _items.remove(fileId);
            throw e;
          }));
}

class PublicationImage extends StatelessWidget {
  const PublicationImage({super.key, required this.fileId, this.fit = BoxFit.cover});
  final int fileId;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Uint8List>(
      future: _ImageCache.load(context.read<Session>(), fileId),
      builder: (context, snap) {
        if (snap.hasData) return Image.memory(snap.data!, fit: fit, gaplessPlayback: true);
        return Container(
          color: AppColors.primary.withValues(alpha: 0.06),
          alignment: Alignment.center,
          child: snap.hasError
              ? const Icon(Icons.broken_image_outlined, color: Colors.grey)
              : const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2)),
        );
      },
    );
  }
}

/// Opens one item: a zoomable image, or the PDF in the phone's viewer.
Future<void> openPublication(BuildContext context, Map<String, dynamic> p) async {
  final s = context.read<Session>();
  if (p['is_image'] != true) {
    await downloadAndOpen(context, s, '/api/files/${p['file']['id']}', p['file']['name'] as String);
    return;
  }
  await Navigator.push(
    context,
    MaterialPageRoute(
      builder: (_) => Scaffold(
        backgroundColor: Colors.black,
        appBar: AppBar(
          backgroundColor: Colors.black,
          foregroundColor: Colors.white,
          title: Text(p['title'] as String),
          actions: [
            IconButton(
              tooltip: 'فتح أو مشاركة',
              icon: const Icon(Icons.open_in_new),
              onPressed: () => downloadAndOpen(context, s, '/api/files/${p['file']['id']}', p['file']['name'] as String),
            ),
          ],
        ),
        body: Column(children: [
          Expanded(
            child: InteractiveViewer(
              maxScale: 5,
              child: Center(child: PublicationImage(fileId: p['file']['id'] as int, fit: BoxFit.contain)),
            ),
          ),
          if ((p['body'] as String?)?.isNotEmpty == true)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(p['body'] as String, style: const TextStyle(color: Colors.white)),
            ),
        ]),
      ),
    ),
  );
}

String _scope(Map p) =>
    [p['faculty_name'], p['department_name'], if (p['cohort'] != null) 'دفعة ${p['cohort']}'].whereType<String>().join(' · ');

/// Current image announcements as a swipeable strip at the top of the home screen.
class PosterCarousel extends StatefulWidget {
  const PosterCarousel({super.key});

  @override
  State<PosterCarousel> createState() => _PosterCarouselState();
}

class _PosterCarouselState extends State<PosterCarousel> {
  List<dynamic> _items = [];

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get('/api/publications?kind=poster').then((d) {
      if (mounted) setState(() => _items = (d as List).where((p) => p['is_image'] == true).toList());
    }).catchError((Object _) {});
  }

  @override
  Widget build(BuildContext context) {
    if (_items.isEmpty) return const SizedBox.shrink();
    return SizedBox(
      height: 170,
      child: PageView(
        controller: PageController(viewportFraction: 0.88),
        children: [
          for (final p in _items)
            Padding(
              padding: const EdgeInsets.fromLTRB(6, 10, 6, 4),
              child: GestureDetector(
                onTap: () => openPublication(context, p as Map<String, dynamic>),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: Stack(fit: StackFit.expand, children: [
                    PublicationImage(fileId: p['file']['id'] as int),
                    Align(
                      alignment: Alignment.bottomCenter,
                      child: Container(
                        width: double.infinity,
                        padding: const EdgeInsets.fromLTRB(12, 18, 12, 8),
                        decoration: const BoxDecoration(
                          gradient: LinearGradient(
                            begin: Alignment.topCenter,
                            end: Alignment.bottomCenter,
                            colors: [Colors.transparent, Color(0xCC45110A)],
                          ),
                        ),
                        child: Text(p['title'] as String,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                      ),
                    ),
                  ]),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Lecture timetables and image announcements published for the user.
class PublicationsScreen extends StatelessWidget {
  const PublicationsScreen({super.key, this.initialKind = 'schedule', this.openId});
  final String initialKind;
  final int? openId;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return DefaultTabController(
      length: 2,
      initialIndex: initialKind == 'poster' ? 1 : 0,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('الجداول والإعلانات المصورة'),
          bottom: const TabBar(tabs: [Tab(text: 'جداول المحاضرات'), Tab(text: 'الإعلانات المصورة')]),
        ),
        body: AsyncView<List<dynamic>>(
          load: () async {
            final items = await s.api.get('/api/publications') as List<dynamic>;
            final target = openId == null ? null : items.where((p) => p['id'] == openId).firstOrNull;
            if (target != null && context.mounted) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (context.mounted) openPublication(context, target as Map<String, dynamic>);
              });
            }
            return items;
          },
          builder: (context, items, reload) => TabBarView(children: [
            for (final kind in ['schedule', 'poster'])
              Builder(builder: (context) {
                final list = items.where((p) => p['kind'] == kind).toList();
                return ListView(padding: const EdgeInsets.all(12), children: [
                  if (list.isEmpty)
                    EmptyView(kind == 'schedule' ? 'لا توجد جداول منشورة لك' : 'لا توجد إعلانات مصورة',
                        icon: kind == 'schedule' ? Icons.calendar_month_outlined : Icons.image_outlined),
                  for (final p in list)
                    Card(
                      clipBehavior: Clip.antiAlias,
                      child: InkWell(
                        onTap: () => openPublication(context, p as Map<String, dynamic>),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                          if (p['is_image'] == true)
                            AspectRatio(aspectRatio: 4 / 3, child: PublicationImage(fileId: p['file']['id'] as int))
                          else
                            Container(
                              height: 90,
                              color: AppColors.primary.withValues(alpha: 0.06),
                              child: const Icon(Icons.picture_as_pdf_outlined, size: 40, color: AppColors.primary),
                            ),
                          Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(p['title'] as String, style: const TextStyle(fontWeight: FontWeight.bold)),
                              if ((p['body'] as String?)?.isNotEmpty == true) Text(p['body'] as String),
                              Text(
                                [if (_scope(p).isNotEmpty) _scope(p) else 'الجامعة كاملة', fmtDate(p['starts_at'], time: false)]
                                    .join(' · '),
                                style: const TextStyle(fontSize: 12, color: Colors.grey),
                              ),
                            ]),
                          ),
                        ]),
                      ),
                    ),
                ]);
              }),
          ]),
        ),
      ),
    );
  }
}

/// The user's weekly lectures (enrolled or taught courses), day by day.
class TimetableScreen extends StatelessWidget {
  const TimetableScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    final today = (DateTime.now().weekday + 1) % 7; // Saturday = 0
    return Scaffold(
      appBar: AppBar(
        title: const Text('جدولي الأسبوعي'),
        actions: [
          TextButton.icon(
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const PublicationsScreen())),
            icon: const Icon(Icons.description_outlined),
            label: const Text('الجداول المنشورة'),
          ),
        ],
      ),
      body: AsyncView<List<dynamic>>(
        load: () async => await s.api.get('/api/me/schedule') as List<dynamic>,
        builder: (context, slots, reload) {
          final days = [for (var i = 0; i < 7; i++) (today + i) % 7]; // starting today
          return ListView(padding: const EdgeInsets.all(12), children: [
            if (slots.isEmpty) const EmptyView('لا توجد محاضرات مجدولة لمقرراتك', icon: Icons.event_busy),
            for (final d in days)
              if (slots.any((x) => x['day'] == d))
                SectionCard(
                  title: d == today ? '${dayNames[d]} (اليوم)' : dayNames[d],
                  child: Column(children: [
                    for (final x in slots.where((x) => x['day'] == d))
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Container(
                          width: 64,
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          decoration: BoxDecoration(
                            color: AppColors.primary.withValues(alpha: 0.08),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Text('${x['start']}\n${x['end']}',
                              textAlign: TextAlign.center, style: const TextStyle(fontSize: 12, height: 1.3)),
                        ),
                        title: Text('${x['title']}'),
                        subtitle: Text([x['code'], if ((x['room'] as String?)?.isNotEmpty == true) 'القاعة ${x['room']}']
                            .join(' · ')),
                      ),
                  ]),
                ),
          ]);
        },
      ),
    );
  }
}
