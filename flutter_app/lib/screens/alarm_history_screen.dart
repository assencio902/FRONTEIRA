import 'package:flutter/material.dart';

import '../services/alarm_history_service.dart';
import '../theme/app_theme.dart';

enum _HistoryPeriod { d7, d15, d30, d60, d90, d180 }

extension _HistoryPeriodExt on _HistoryPeriod {
  String get label {
    switch (this) {
      case _HistoryPeriod.d7:
        return '7d';
      case _HistoryPeriod.d15:
        return '15d';
      case _HistoryPeriod.d30:
        return '30d';
      case _HistoryPeriod.d60:
        return '60d';
      case _HistoryPeriod.d90:
        return '90d';
      case _HistoryPeriod.d180:
        return '180d';
    }
  }

  Duration get window {
    switch (this) {
      case _HistoryPeriod.d7:
        return const Duration(days: 7);
      case _HistoryPeriod.d15:
        return const Duration(days: 15);
      case _HistoryPeriod.d30:
        return const Duration(days: 30);
      case _HistoryPeriod.d60:
        return const Duration(days: 60);
      case _HistoryPeriod.d90:
        return const Duration(days: 90);
      case _HistoryPeriod.d180:
        return const Duration(days: 180);
    }
  }
}

class AlarmHistoryScreen extends StatefulWidget {
  const AlarmHistoryScreen({super.key});

  @override
  State<AlarmHistoryScreen> createState() => _AlarmHistoryScreenState();
}

class _AlarmHistoryScreenState extends State<AlarmHistoryScreen> {
  _HistoryPeriod _period = _HistoryPeriod.d30;

  DateTime? _parseAlarmTime(Map<String, dynamic> alarm) {
    final dynamic raw = alarm['created_at'] ?? alarm['detected_at'] ?? alarm['ts'];
    if (raw == null) return null;
    if (raw is String) {
      try {
        return DateTime.parse(raw).toLocal();
      } catch (_) {
        return null;
      }
    }
    if (raw is num) {
      final value = raw.toInt();
      final ms = value > 9999999999 ? value : value * 1000;
      return DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true).toLocal();
    }
    return null;
  }

  String _fmtDate(dynamic raw) {
    if (raw == null) return '—';
    if (raw is String) {
      try {
        final dt = DateTime.parse(raw).toLocal();
        final d = '${dt.day.toString().padLeft(2, '0')}/${dt.month.toString().padLeft(2, '0')}';
        final t = '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
        return '$d $t';
      } catch (_) {
        return raw;
      }
    }
    return raw.toString();
  }

  @override
  Widget build(BuildContext context) {
    final history = AlarmHistoryService.getHistory();
    final minTs = DateTime.now().subtract(_period.window);
    final filtered = history.where((a) {
      final dt = _parseAlarmTime(a);
      if (dt == null) return true;
      return dt.isAfter(minTs);
    }).toList();

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.surface,
        title: const Text('Histórico de Alarmes'),
      ),
      body: Column(
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
            decoration: const BoxDecoration(
              color: AppColors.surface,
              border: Border(bottom: BorderSide(color: AppColors.border)),
            ),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: _HistoryPeriod.values.map((p) {
                final selected = _period == p;
                return InkWell(
                  onTap: () => setState(() => _period = p),
                  borderRadius: BorderRadius.circular(10),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                      color: selected ? AppColors.warning : AppColors.background,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                        color: selected ? AppColors.warning : AppColors.border,
                      ),
                    ),
                    child: Text(
                      p.label,
                      style: TextStyle(
                        color: selected ? Colors.black : AppColors.muted,
                        fontWeight: FontWeight.w800,
                        fontSize: 13,
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
          Expanded(
            child: filtered.isEmpty
                ? const Center(
                    child: Text(
                      'Nenhum alarme no período selecionado.',
                      style: TextStyle(color: AppColors.muted),
                    ),
                  )
                : ListView.builder(
                    itemCount: filtered.length,
                    itemBuilder: (_, i) {
                      final a = filtered[i];
                      final plate = (a['plate'] ?? a['placa'] ?? '?????').toString().toUpperCase();
                      final target = (a['target_name'] ?? a['alvo'] ?? '').toString();
                      final camera = (a['camera'] ?? a['camera_name'] ?? 'Câmera desconhecida').toString();
                      final createdAt = a['created_at'] ?? a['detected_at'] ?? a['ts'];

                      return Container(
                        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: AppColors.danger.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: AppColors.danger.withValues(alpha: 0.5)),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              plate,
                              style: const TextStyle(
                                color: AppColors.warning,
                                fontSize: 18,
                                fontWeight: FontWeight.w900,
                                letterSpacing: 2,
                              ),
                            ),
                            if (target.isNotEmpty) ...[
                              const SizedBox(height: 4),
                              Text(
                                'Alvo: $target',
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ],
                            const SizedBox(height: 6),
                            Text(
                              'Câmera: $camera',
                              style: const TextStyle(color: Colors.white, fontSize: 12),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              _fmtDate(createdAt),
                              style: const TextStyle(color: AppColors.muted, fontSize: 11),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
