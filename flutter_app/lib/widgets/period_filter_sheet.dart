import 'package:flutter/material.dart';

import '../models/period_filter.dart';
import '../theme/app_theme.dart';

const _kBg     = AppColors.background;
const _kCard   = AppColors.surface;
const _kBorder = AppColors.border;
const _kYellow = AppColors.warning;
const _kMuted  = AppColors.muted;

/// Wrapper interno para distinguir X (cancelar) de OK (confirmar).
class _SheetResult {
  final PeriodFilter? filter;
  const _SheetResult(this.filter);
}

/// Bottom sheet reutilizável de seleção de período.
///
/// Uso:
/// ```dart
/// final res = await PeriodFilterSheet.show(context, current: _period);
/// if (res.confirmed && mounted) setState(() => _period = res.filter);
/// ```
class PeriodFilterSheet extends StatefulWidget {
  const PeriodFilterSheet({super.key, this.initial});

  final PeriodFilter? initial;

  /// Abre o sheet.
  /// - `confirmed == false` → usuário fechou com X (sem mudança).
  /// - `confirmed == true, filter != null` → filtro selecionado.
  /// - `confirmed == true, filter == null` → usuário redefiniu / OK sem seleção (limpa).
  static Future<({bool confirmed, PeriodFilter? filter})> show(
    BuildContext context, {
    PeriodFilter? current,
  }) async {
    final result = await showModalBottomSheet<_SheetResult>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => PeriodFilterSheet(initial: current),
    );
    if (result == null) return (confirmed: false, filter: null);
    return (confirmed: true, filter: result.filter);
  }

  @override
  State<PeriodFilterSheet> createState() => _PeriodFilterSheetState();
}

class _PeriodFilterSheetState extends State<PeriodFilterSheet> {
  PeriodPreset? _selected;   // null = nenhum preset escolhido
  bool _customEnabled = false;
  DateTime? _customFrom;
  DateTime? _customTo;

  static const _presets = [
    PeriodPreset.last6h,
    PeriodPreset.today,
    PeriodPreset.yesterday,
    PeriodPreset.last7d,
    PeriodPreset.thisWeek,
    PeriodPreset.last30d,
  ];

  @override
  void initState() {
    super.initState();
    final init = widget.initial;
    if (init != null) {
      if (init.preset == PeriodPreset.custom) {
        _customEnabled = true;
        _customFrom = init.customFrom;
        _customTo   = init.customTo;
      } else {
        _selected = init.preset;
      }
    }
  }

  // ─── helpers ──────────────────────────────────────────────────────────────

  Widget _dateTheme(BuildContext ctx, Widget child) => Theme(
        data: ThemeData.dark().copyWith(
          colorScheme: const ColorScheme.dark(
            primary: _kYellow,
            onPrimary: Colors.black,
            surface: _kCard,
            onSurface: Colors.white,
          ),
          textButtonTheme: TextButtonThemeData(
            style: TextButton.styleFrom(foregroundColor: _kYellow),
          ),
        ),
        child: child,
      );

  Future<void> _pickCustomFrom() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _customFrom ?? DateTime.now().subtract(const Duration(days: 1)),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
      helpText: 'DATA INÍCIO',
      builder: (ctx, child) => _dateTheme(ctx, child!),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: _customFrom != null
          ? TimeOfDay.fromDateTime(_customFrom!)
          : const TimeOfDay(hour: 0, minute: 0),
      helpText: 'HORA INÍCIO',
      builder: (ctx, child) => _dateTheme(ctx, child!),
    );
    if (time == null || !mounted) return;
    setState(() {
      _customFrom = DateTime(
          date.year, date.month, date.day, time.hour, time.minute);
    });
  }

  Future<void> _pickCustomTo() async {
    final minDate = _customFrom ?? DateTime(2020);
    final date = await showDatePicker(
      context: context,
      initialDate: _customTo ?? DateTime.now(),
      firstDate: minDate,
      lastDate: DateTime.now().add(const Duration(days: 1)),
      helpText: 'DATA FIM',
      builder: (ctx, child) => _dateTheme(ctx, child!),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: _customTo != null
          ? TimeOfDay.fromDateTime(_customTo!)
          : TimeOfDay.now(),
      helpText: 'HORA FIM',
      builder: (ctx, child) => _dateTheme(ctx, child!),
    );
    if (time == null || !mounted) return;
    final picked =
        DateTime(date.year, date.month, date.day, time.hour, time.minute);
    // Validação: fim >= início
    if (_customFrom != null && picked.isBefore(_customFrom!)) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('A data final deve ser após a data inicial.'),
          backgroundColor: Color(0xFFEF4444),
          behavior: SnackBarBehavior.floating,
        ),
      );
      return;
    }
    setState(() => _customTo = picked);
  }

  String _fmtDt(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')} '
      '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';

  void _onOk() {
    if (_customEnabled) {
      Navigator.pop(
        context,
        _SheetResult(PeriodFilter(
          preset: PeriodPreset.custom,
          customFrom: _customFrom,
          customTo: _customTo,
        )),
      );
    } else if (_selected != null) {
      Navigator.pop(context, _SheetResult(PeriodFilter(preset: _selected!)));
    } else {
      // OK sem seleção = limpar período
      Navigator.pop(context, const _SheetResult(null));
    }
  }

  void _onReset() {
    setState(() {
      _selected      = null;
      _customEnabled = false;
      _customFrom    = null;
      _customTo      = null;
    });
  }

  // ─── build ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Container(
        decoration: const BoxDecoration(
          color: _kCard,
          borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Drag handle
            Container(
              width: 38,
              height: 4,
              margin: const EdgeInsets.only(top: 10, bottom: 4),
              decoration: BoxDecoration(
                color: _kBorder,
                borderRadius: BorderRadius.circular(4),
              ),
            ),

            // ── Cabeçalho ─────────────────────────────────────────────────
            Container(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: _kBorder)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.schedule_rounded,
                      color: _kYellow, size: 18),
                  const SizedBox(width: 8),
                  const Text(
                    'Período',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.5,
                    ),
                  ),
                  const Spacer(),
                  GestureDetector(
                    onTap: () => Navigator.pop(context),
                    child: const Icon(Icons.close_rounded,
                        color: _kMuted, size: 20),
                  ),                ],
              ),
            ),

            // ── Corpo (scrollável) ─────────────────────────────────────────
            Flexible(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Opções rápidas em grid 2 colunas
                    _buildQuickOptions(),
                    const SizedBox(height: 14),

                    // Divisor
                    Container(height: 1, color: _kBorder),
                    const SizedBox(height: 12),

                    // Seção personalizado
                    _buildCustomSection(),
                    const SizedBox(height: 14),
                  ],
                ),
              ),
            ),

            // ── Rodapé ────────────────────────────────────────────────────
            Container(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
              decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: _kBorder)),
              ),
              child: Row(
                children: [
                  // Redefinir
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _onReset,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: _kMuted,
                        side: const BorderSide(color: _kBorder),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                      child: const Text('Redefinir',
                          style: TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 14)),
                    ),
                  ),
                  const SizedBox(width: 10),
                  // OK
                  Expanded(
                    flex: 2,
                    child: ElevatedButton(
                      onPressed: _onOk,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: _kYellow,
                        foregroundColor: Colors.black,
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                      child: const Text('OK',
                          style: TextStyle(
                              fontWeight: FontWeight.w800, fontSize: 14)),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildQuickOptions() {
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: 8,
      crossAxisSpacing: 8,
      childAspectRatio: 3.4,
      children: _presets.map(_buildPresetTile).toList(),
    );
  }

  Widget _buildPresetTile(PeriodPreset preset) {
    final active = !_customEnabled && _selected == preset;
    return GestureDetector(
      onTap: () => setState(() {
        _selected      = preset;
        _customEnabled = false;
        _customFrom    = null;
        _customTo      = null;
      }),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: active
              ? _kYellow.withValues(alpha: 0.14)
              : _kBg.withValues(alpha: 0.5),
          borderRadius: BorderRadius.circular(9),
          border: Border.all(
            color: active ? _kYellow.withValues(alpha: 0.75) : _kBorder,
            width: active ? 1.4 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(preset.icon,
                color: active ? _kYellow : _kMuted, size: 14),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                preset.label,
                style: TextStyle(
                  color: active ? Colors.white : _kMuted,
                  fontSize: 12,
                  fontWeight:
                      active ? FontWeight.w800 : FontWeight.w600,
                ),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            if (active)
              const Icon(Icons.check_rounded, color: _kYellow, size: 13),
          ],
        ),
      ),
    );
  }

  Widget _buildCustomSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Título + switch
        Row(
          children: [
            const Icon(Icons.tune_rounded, color: _kMuted, size: 14),
            const SizedBox(width: 7),
            const Expanded(
              child: Text(
                'Período de tempo personalizado',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            Transform.scale(
              scale: 0.8,
              child: Switch(
                value: _customEnabled,
                onChanged: (v) => setState(() {
                  _customEnabled = v;
                  if (v) _selected = null;
                }),
                activeColor: _kYellow,
              ),
            ),
          ],
        ),

        // Seletores data/hora (aparece quando switch está ON)
        AnimatedCrossFade(
          duration: const Duration(milliseconds: 200),
          crossFadeState: _customEnabled
              ? CrossFadeState.showSecond
              : CrossFadeState.showFirst,
          firstChild: const SizedBox.shrink(),
          secondChild: Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: _DatePickerBtn(
                        label: 'Início',
                        date: _customFrom,
                        onTap: _pickCustomFrom,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: _DatePickerBtn(
                        label: 'Fim',
                        date: _customTo,
                        onTap: _pickCustomTo,
                      ),
                    ),
                  ],
                ),

                // Exibe o range selecionado
                if (_customFrom != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 7),
                      decoration: BoxDecoration(
                        color: _kYellow.withValues(alpha: 0.07),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                            color: _kYellow.withValues(alpha: 0.3)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.date_range_rounded,
                              color: _kYellow, size: 13),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              '${_fmtDt(_customFrom!)}  —  '
                              '${_customTo != null ? _fmtDt(_customTo!) : "Definir fim"}',
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

// ─── Botão de seleção de data ─────────────────────────────────────────────────

class _DatePickerBtn extends StatelessWidget {
  const _DatePickerBtn({
    required this.label,
    required this.date,
    required this.onTap,
  });

  final String   label;
  final DateTime? date;
  final VoidCallback onTap;

  static String _fmt(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}\n'
      '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final hasDate = date != null;
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
        decoration: BoxDecoration(
          color: hasDate
              ? _kYellow.withValues(alpha: 0.08)
              : _kBg.withValues(alpha: 0.5),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: hasDate ? _kYellow.withValues(alpha: 0.6) : _kBorder,
          ),
        ),
        child: Row(
          children: [
            Icon(Icons.calendar_today_rounded,
                color: hasDate ? _kYellow : _kMuted, size: 14),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: TextStyle(
                      color: hasDate ? _kYellow : _kMuted,
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.5,
                    ),
                  ),
                  Text(
                    hasDate ? _fmt(date!) : 'Toque para definir',
                    style: TextStyle(
                      color: hasDate ? Colors.white : _kMuted,
                      fontSize: hasDate ? 11 : 10,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right_rounded,
                color: hasDate ? _kYellow : _kMuted, size: 14),
          ],
        ),
      ),
    );
  }
}
