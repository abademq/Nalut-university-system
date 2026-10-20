import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../links.dart';
import '../state/session.dart';

/// Pinned announcements shown above every tab while they are inside their time window.
class BannerStrip extends StatefulWidget {
  const BannerStrip({super.key});

  @override
  State<BannerStrip> createState() => _BannerStripState();
}

class _BannerStripState extends State<BannerStrip> {
  List<dynamic> _items = [];
  final Set<int> _hidden = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final data = await context.read<Session>().api.get('/api/banners') as List<dynamic>;
      if (mounted) setState(() => _items = data);
    } catch (_) {}
  }

  Color _color(String? level) => switch (level) {
        'urgent' => AppColors.danger,
        'important' => AppColors.warning,
        _ => AppColors.info,
      };

  @override
  Widget build(BuildContext context) {
    final visible = _items.where((b) => !_hidden.contains(b['id'])).toList();
    if (visible.isEmpty) return const SizedBox.shrink();
    return Column(children: [
      for (final b in visible)
        Container(
          margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          decoration: BoxDecoration(
            color: _color(b['level'] as String?).withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(12),
            border: BorderDirectional(start: BorderSide(color: _color(b['level'] as String?), width: 4)),
          ),
          child: InkWell(
            onTap: () => openLink(context, context.read<Session>(), b['link'] as String?,
                title: b['title'] as String, body: b['body'] as String?),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Icon(Icons.push_pin, size: 18, color: _color(b['level'] as String?)),
                const SizedBox(width: 6),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(b['title'] as String, style: const TextStyle(fontWeight: FontWeight.bold)),
                    if ((b['body'] as String?)?.isNotEmpty == true)
                      Text(b['body'] as String, maxLines: 2, overflow: TextOverflow.ellipsis),
                  ]),
                ),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.close, size: 18),
                  tooltip: 'إخفاء',
                  onPressed: () => setState(() => _hidden.add(b['id'] as int)),
                ),
              ]),
            ),
          ),
        ),
    ]);
  }
}
