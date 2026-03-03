import 'package:flutter/material.dart';

import '../config.dart';
import '../models/plate_result.dart';

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
                      style: TextStyle(color: Color(0xFF94A3B8), fontSize: 15),
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
        found ? const Color(0xFFEF4444) : const Color(0xFF22C55E);
    final icon = found ? Icons.warning_amber_rounded : Icons.check_circle_outline;
    final label =
        found ? '$total passagem(ns) encontrada(s)' : 'Veículo sem registros';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 18, horizontal: 20),
      color: color.withOpacity(0.12),
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
                      color: Color(0xFF94A3B8), fontSize: 12),
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
        color: (up ? const Color(0xFF3B82F6) : const Color(0xFFF97316))
            .withOpacity(0.18),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(
          color: up ? const Color(0xFF3B82F6) : const Color(0xFFF97316),
          width: .8,
        ),
      ),
      child: Text(
        up ? '↑ CRESCENTE' : '↓ DECRESCENTE',
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: up ? const Color(0xFF3B82F6) : const Color(0xFFF97316),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final imageUrl = hit.imagePath != null && hit.imagePath!.isNotEmpty
        ? '${AppConfig.baseUrl}/${hit.imagePath}'
        : null;

    return Card(
      color: const Color(0xFF1E293B),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Câmera + direção
            Row(
              children: [
                const Icon(Icons.videocam_outlined,
                    size: 15, color: Color(0xFF94A3B8)),
                const SizedBox(width: 5),
                Expanded(
                  child: Text(
                    hit.cameraName ?? hit.cameraId ?? '—',
                    style: const TextStyle(
                        color: Color(0xFF94A3B8), fontSize: 12),
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
                    size: 14, color: Color(0xFF64748B)),
                const SizedBox(width: 5),
                Text(
                  _fmtDate(hit.occurredAt),
                  style: const TextStyle(
                      color: Color(0xFFCBD5E1), fontSize: 13),
                ),
              ],
            ),

            // Confiança
            if (hit.confidence != null) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  const Icon(Icons.analytics_outlined,
                      size: 14, color: Color(0xFF64748B)),
                  const SizedBox(width: 5),
                  Text(
                    'Confiança: ${(hit.confidence! * 100).toStringAsFixed(1)} %',
                    style: const TextStyle(
                        color: Color(0xFF94A3B8), fontSize: 12),
                  ),
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
                  height: 130,
                  width: double.infinity,
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => Container(
                    height: 60,
                    color: const Color(0xFF0F172A),
                    alignment: Alignment.center,
                    child: const Text('Imagem indisponível',
                        style: TextStyle(
                            color: Color(0xFF64748B), fontSize: 12)),
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
