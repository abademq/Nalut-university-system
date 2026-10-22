import 'package:flutter/material.dart';

import '../launch.dart';

/// The launch screen: picture (or the bundled logo), title and subtitle on the chosen colors.
/// Its defaults match Android's native launch screen, so the hand-over is seamless.
class SplashView extends StatelessWidget {
  const SplashView({super.key, this.config = const LaunchConfig()});
  final LaunchConfig config;

  @override
  Widget build(BuildContext context) {
    final c = config;
    return Scaffold(
      backgroundColor: c.background,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 260, maxHeight: 260),
                child: c.image != null
                    ? Image.memory(c.image!, fit: BoxFit.contain, gaplessPlayback: true,
                        errorBuilder: (_, _, _) => Image.asset('assets/logo_on_dark.png', width: 112, height: 112))
                    : Image.asset('assets/logo_on_dark.png', width: 112, height: 112),
              ),
              const SizedBox(height: 20),
              if (c.title.isNotEmpty)
                Text(c.title,
                    textAlign: TextAlign.center,
                    style: TextStyle(color: c.foreground, fontSize: 24, fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              if (c.subtitle.isNotEmpty)
                Text(c.subtitle, textAlign: TextAlign.center, style: TextStyle(color: c.accent, fontSize: 16)),
              const SizedBox(height: 36),
              SizedBox(
                width: 28,
                height: 28,
                child: c.showLoader ? CircularProgressIndicator(strokeWidth: 2.5, color: c.accent) : null,
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Keeps the launch screen up for the chosen minimum time (and while the session is restored),
/// and plays the start-up sound once.
class LaunchGate extends StatefulWidget {
  const LaunchGate({super.key, required this.config, required this.loading, required this.child, this.playSound});
  final LaunchConfig config;
  final bool loading;
  final Widget child;
  final Future<void> Function(String sound)? playSound;

  @override
  State<LaunchGate> createState() => _LaunchGateState();
}

class _LaunchGateState extends State<LaunchGate> {
  late bool _holding = widget.config.enabled && widget.config.durationMs > 0;

  @override
  void initState() {
    super.initState();
    widget.playSound?.call(widget.config.sound);
    if (_holding) {
      Future.delayed(Duration(milliseconds: widget.config.durationMs), () {
        if (mounted) setState(() => _holding = false);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final show = widget.loading || _holding;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 350),
      child: show ? SplashView(key: const ValueKey('splash'), config: widget.config) : widget.child,
    );
  }
}
