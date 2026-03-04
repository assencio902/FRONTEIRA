import 'package:flutter/material.dart';

import '../config.dart';
import '../models/plate_result.dart';
import '../theme/app_theme.dart';

class ResultScreen extends StatelessWidget {
  final String plate;
  final PlateSearchResult result;

  const ResultScreen({super.key, required this.plate, required this.result});

  @override
  Widget build(BuildContext context) {
    final bool found = result.hits.isNotEmpty;
    return Scaffold(
      appBar: AppBar(
        title: Text('Placa: $plate'),
      ),
      body: Column(
        children: [
          // Status banner
          _StatusBanner(found: found, total: result.total, status: result.status),

          // Lista de hits
          Expanded(
            child: found
                ? ListView.separated(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    itemCount: result.hits.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, i) => _HitCard(hit: result.hits[i]),
                  )
                : const Center(
                    child: Text(
                      'Nenhuma passagem encontrada.',
                      style: TextStyle(color: AppColors.muted, fontSize: 15),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

// ── Status banner ─────────────────────────────────────────────────────────────

class _StatusBanner extends StatelessWidget {
  final bool found;
  final int total;
  final String status;

  const _StatusBanner(
      {required this.found, required this.total, required this.status});

  @override
  Widget build(BuildContext context) {
    final color =
        found ? AppColors.danger : AppColors.success;
    final icon = found ? Icons.warning_amber_rounded : Icons.check_circle_outline;
    final label =
        found ? '$total passagem(ns) encontrada(s)' : 'Veículo sem registros';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 18, horizontal: 20),
      color: color.withValues(alpha: 0.12),
      child: Row(
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(
                      color: color,
                      fontWeight: FontWeight.w700,
                      fontSize: 15),
                ),
                Text(
                  'Status: $status',
                  style: const TextStyle(
                      color: AppColors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Card de um hit ─────────────────────────────────────────────────────────────

class _HitCard extends StatelessWidget {
  final PlateHit hit;

  const _HitCard({required this.hit});

  String _fmtDate(String? iso) {
    if (iso == null || iso.isEmpty) return '—';
    try {
      final dt = DateTime.parse(iso).toLocal();
      return '${dt.day.toString().padLeft(2, '0')}/'
          '${dt.month.toString().padLeft(2, '0')}/'
          '${dt.year}  '
          '${dt.hour.toString().padLeft(2, '0')}:'
          '${dt.minute.toString().padLeft(2, '0')}:'
          '${dt.second.toString().padLeft(2, '0')}';
    } catch (_) {
      return iso;
    }
  }

  Widget _dirBadge(String? dir) {
    if (dir == null) return const SizedBox.shrink();
    final up = dir == 'CRESCENTE';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: (up ? AppColors.primary : AppColors.warning)
            .withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(
          color: up ? AppColors.primary : AppColors.warning,
          width: .8,
        ),
      ),
      child: Text(
        up ? '↑ CRESCENTE' : '↓ DECRESCENTE',
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: up ? AppColors.primary : AppColors.warning,
        ),
      ),
    );
  }

  Widget _tag(IconData icon, String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.5), width: .8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 11, color: color),
          const SizedBox(width: 4),
          Text(label, style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final imageUrl = hit.imagePath != null && hit.imagePath!.isNotEmpty
        ? '${AppConfig.baseUrl}${hit.imagePath!.startsWith('/') ? '' : '/'}${hit.imagePath}'
        : null;

    return Card(
      color: AppColors.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Placa
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              margin: const EdgeInsets.only(bottom: 10),
              decoration: BoxDecoration(
                color: AppColors.warning.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.warning.withValues(alpha: 0.5)),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.directions_car, size: 16, color: AppColors.warning),
                  const SizedBox(width: 8),
                  Text(
                    hit.plate.isEmpty ? '—' : hit.plate,
                    style: const TextStyle(
                      color: AppColors.warning,
                      fontSize: 20,
                      fontWeight: FontWeight.w900,
                      letterSpacing: 4,
                    ),
                  ),
                ],
              ),
            ),
            // Câmera + direção
            Row(
              children: [
                const Icon(Icons.videocam_outlined,
                    size: 15, color: AppColors.muted),
                const SizedBox(width: 5),
                Expanded(
                  child: Text(
                    hit.cameraName ?? hit.cameraId ?? '—',
                    style: const TextStyle(
                        color: AppColors.muted, fontSize: 12),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                _dirBadge(hit.direcao),
              ],
            ),
            const SizedBox(height: 8),

            // Data/hora
            Row(
              children: [
                const Icon(Icons.access_time,
                    size: 14, color: AppColors.muted),
                const SizedBox(width: 5),
                Text(
                  _fmtDate(hit.occurredAt),
                  style: const TextStyle(
                      color: AppColors.text, fontSize: 13),
                ),
              ],
            ),

            // Confiança
            if (hit.confidence != null) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  const Icon(Icons.analytics_outlined,
                      size: 14, color: AppColors.muted),
                  const SizedBox(width: 5),
                  Text(
                    'Confiança: ${(hit.confidence! * (hit.confidence! <= 1.0 ? 100 : 1)).toStringAsFixed(0)}%',
                    style: const TextStyle(
                        color: AppColors.muted, fontSize: 12),
                  ),
                ],
              ),
            ],

            // Dados do veículo
            if (hit.vehicleType != null || hit.vehicleColor != null || hit.plateColor != null) ...[
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  if (hit.vehicleType != null)
                    _tag(Icons.directions_car_outlined, hit.vehicleType!.toUpperCase(), AppColors.accent),
                  if (hit.vehicleColor != null)
                    _tag(Icons.palette_outlined, hit.vehicleColor!.toUpperCase(), AppColors.muted),
                  if (hit.plateColor != null)
                    _tag(Icons.credit_card_outlined, 'PLACA ${hit.plateColor!.toUpperCase()}', AppColors.warning),
                  if (hit.speed != null && hit.speed! > 0)
                    _tag(Icons.speed_outlined, '${hit.speed} km/h',
                        hit.speedLimit != null && hit.speed! > hit.speedLimit!
                            ? AppColors.danger
                            : AppColors.success),
                  if (hit.illegalName != null && hit.illegalName != 'Normal')
                    _tag(Icons.warning_amber_rounded, hit.illegalName!, AppColors.danger),
                ],
              ),
            ],

            // Imagem
            if (imageUrl != null) ...[
              const SizedBox(height: 10),
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image.network(
                  imageUrl,
                  height: 200,
                  width: double.infinity,
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => Container(
                    height: 60,
                    color: AppColors.background,
                    alignment: Alignment.center,
                    child: const Text('Imagem indisponível',
                        style: TextStyle(
                            color: AppColors.muted, fontSize: 12)),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
