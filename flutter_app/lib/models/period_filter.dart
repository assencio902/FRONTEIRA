import 'package:flutter/material.dart';

/// Preset labels (IDs internos)
enum PeriodPreset {
  last6h,
  today,
  yesterday,
  last7d,
  thisWeek,
  last30d,
  custom,
}

extension PeriodPresetLabel on PeriodPreset {
  String get label => switch (this) {
        PeriodPreset.last6h    => 'Últimas 6 horas',
        PeriodPreset.today     => 'Hoje',
        PeriodPreset.yesterday => 'Ontem',
        PeriodPreset.last7d    => 'Últimos 7 dias',
        PeriodPreset.thisWeek  => 'Semana atual',
        PeriodPreset.last30d   => 'Últimos 30 dias',
        PeriodPreset.custom    => 'Personalizado',
      };

  IconData get icon => switch (this) {
        PeriodPreset.last6h    => Icons.access_time_rounded,
        PeriodPreset.today     => Icons.today_rounded,
        PeriodPreset.yesterday => Icons.history_rounded,
        PeriodPreset.last7d    => Icons.date_range_rounded,
        PeriodPreset.thisWeek  => Icons.view_week_rounded,
        PeriodPreset.last30d   => Icons.calendar_month_rounded,
        PeriodPreset.custom    => Icons.tune_rounded,
      };
}

/// Resultado do filtro de período.
class PeriodFilter {
  final PeriodPreset preset;   // 'custom' quando personalizado
  final DateTime? customFrom;  // só preenchido quando preset == custom
  final DateTime? customTo;

  const PeriodFilter({
    required this.preset,
    this.customFrom,
    this.customTo,
  });

  /// Resolve as datas de início/fim conforme o preset.
  DateTimeRange get resolved {
    final now = DateTime.now();
    return switch (preset) {
      PeriodPreset.last6h => DateTimeRange(
          start: now.subtract(const Duration(hours: 6)),
          end: now,
        ),
      PeriodPreset.today => DateTimeRange(
          start: DateTime(now.year, now.month, now.day),
          end: now,
        ),
      PeriodPreset.yesterday => DateTimeRange(
          start: DateTime(now.year, now.month, now.day - 1),
          end: DateTime(now.year, now.month, now.day, 0, 0, 0)
              .subtract(const Duration(seconds: 1)),
        ),
      PeriodPreset.last7d => DateTimeRange(
          start: now.subtract(const Duration(days: 7)),
          end: now,
        ),
      PeriodPreset.thisWeek => DateTimeRange(
          start: now.subtract(Duration(days: now.weekday - 1)),
          end: now,
        ),
      PeriodPreset.last30d => DateTimeRange(
          start: now.subtract(const Duration(days: 30)),
          end: now,
        ),
      PeriodPreset.custom => DateTimeRange(
          start: customFrom ?? now.subtract(const Duration(hours: 24)),
          end: customTo ?? now,
        ),
    };
  }

  DateTime get from => resolved.start;
  DateTime get to   => resolved.end;

  String get displayLabel {
    if (preset == PeriodPreset.custom) {
      if (customFrom == null) return 'Personalizado';
      final f = _fmt(customFrom!);
      final t = customTo != null ? _fmt(customTo!) : '?';
      return '$f — $t';
    }
    return preset.label;
  }

  static String _fmt(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')} '
      '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}
