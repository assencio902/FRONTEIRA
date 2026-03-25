import 'package:flutter/material.dart';

// Widget de overlay de alarme (stub básico)
class AlarmOverlay extends StatelessWidget {
  final String plate;
  final String? targetName;
  final String camera;
  final String confidence;
  final String imagePath;
  final VoidCallback onDismiss;
  
  const AlarmOverlay({
    super.key,
    required this.plate,
    this.targetName,
    required this.camera,
    required this.confidence,
    required this.imagePath,
    required this.onDismiss,
  });
  
  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: Colors.red.withOpacity(0.95),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.warning_amber_rounded, size: 64, color: Colors.white),
            const SizedBox(height: 16),
            const Text(
              '🚨 ALERTA DE WATCHLIST',
              style: TextStyle(
                color: Colors.white,
                fontSize: 18,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 16),
            Text(
              plate,
              style: const TextStyle(
                color: Colors.yellow,
                fontSize: 28,
                fontWeight: FontWeight.w900,
                letterSpacing: 2,
              ),
            ),
            if (targetName != null && targetName!.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                'Alvo: $targetName',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
            const SizedBox(height: 12),
            Text(
              camera,
              style: const TextStyle(color: Colors.white, fontSize: 14),
            ),
            const SizedBox(height: 8),
            Text(
              'Confiança: $confidence%',
              style: const TextStyle(color: Colors.white70, fontSize: 12),
            ),
            const SizedBox(height: 24),
            ElevatedButton(
              onPressed: onDismiss,
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: Colors.red,
                padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 12),
              ),
              child: const Text('OK', style: TextStyle(fontWeight: FontWeight.bold)),
            ),
          ],
        ),
      ),
    );
  }
}
