import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/api.dart';
import '../theme/app_theme.dart';

// ─── Formatadores ─────────────────────────────────────────────────────────────

String _fmtDur(int secs) {
  if (secs <= 0) return '—';
  final h = secs ~/ 3600;
  final m = (secs % 3600) ~/ 60;
  final s = secs % 60;
  if (h > 0) return '${h}h ${m.toString().padLeft(2, '0')}m';
  if (m > 0) return '${m}m ${s.toString().padLeft(2, '0')}s';
  return '${s}s';
}

String _fmtTs(String? iso) {
  if (iso == null || iso.isEmpty) return '—';
  try {
    final dt = DateTime.parse(iso).toLocal();
    return '${dt.day.toString().padLeft(2, '0')}/'
        '${dt.month.toString().padLeft(2, '0')} '
        '${dt.hour.toString().padLeft(2, '0')}:'
        '${dt.minute.toString().padLeft(2, '0')}:'
        '${dt.second.toString().padLeft(2, '0')}';
  } catch (_) {
    return iso;
  }
}

String _fmtDist(double km) {
  if (km <= 0) return '—';
  if (km >= 1) return '${km.toStringAsFixed(1)} km';
  return '${(km * 1000).toStringAsFixed(0)} m';
}

// ─── Constantes de filtro ─────────────────────────────────────────────────────

const _kWindows = [
  ('1h',  '1 hora'),
  ('6h',  '6 horas'),
  ('12h', '12 horas'),
  ('24h', '24 horas'),
  ('48h', '48 horas'),
  ('7d',  '7 dias'),
  ('30d', '30 dias'),
];

const _kCoWindows = [
  (60,    '1 min'),
  (300,   '5 min'),
  (600,   '10 min'),
  (1800,  '30 min'),
  (3600,  '1 hora'),
];

const _kMinCameras = [1, 2, 3, 4, 5];

const _kDirecoes = [
  ('CRESCENTE',   'Crescente'),
  ('DECRESCENTE', 'Decrescente'),
  ('ENTRADA',     'Entrada'),
  ('SAÍDA',       'Saída'),
];

const _kVehicleTypes = [
  ('car',        'Carro'),
  ('motorcycle', 'Moto'),
  ('pickup',     'Caminhonete'),
  ('truck',      'Caminhão'),
  ('bus',        'Ônibus'),
  ('van',        'Van/Kombi'),
];

const _kVehicleColors = [
  'Preto', 'Branco', 'Prata', 'Cinza',
  'Vermelho', 'Azul', 'Amarelo', 'Verde',
  'Marrom', 'Laranja',
];

// Mapa: tipo raw → label em português (para exibir no card)
const _kTypeLabel = {
  'car':        'Carro',
  'motorcycle': 'Moto',
  'pickup':     'Caminhonete',
  'truck':      'Caminhão',
  'bus':        'Ônibus',
  'van':        'Van/Kombi',
  'bicycle':    'Bicicleta',
  'person':     'Pessoa',
};

// ─────────────────────────────────────────────────────────────────────────────
// Screen
// ─────────────────────────────────────────────────────────────────────────────

class BatedorScreen extends StatefulWidget {
  const BatedorScreen({super.key});

  @override
  State<BatedorScreen> createState() => _BatedorScreenState();
}

class _BatedorScreenState extends State<BatedorScreen> {
  final _plateCtrl = TextEditingController();
  final _focusNode = FocusNode();

  // ── Filtros de comportamento ─────────────────────────────────────────────
  String _window     = '24h';
  int    _coWindow   = 600;
  int    _minCameras = 2;
  bool   _filtersOpen = false;

  // ── Filtros do suspeito ───────────────────────────────────────────────────
  String? _direcao;
  String? _vehicleType;
  String? _vehicleColor;
  final _prefixCtrl = TextEditingController();

  // ── Estado ────────────────────────────────────────────────────────────────
  bool   _loading   = false;
  String? _error;
  Map<String, dynamic>? _result;

  // ── Expansão de evidências ─────────────────────────────────────────────────
  final Set<int> _expanded = {};

  @override
  void dispose() {
    _plateCtrl.dispose();
    _prefixCtrl.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  // ── Busca ─────────────────────────────────────────────────────────────────

  Future<void> _search() async {
    final plate = _plateCtrl.text.trim().toUpperCase();
    if (plate.isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() { _loading = true; _error = null; _result = null; _expanded.clear(); });
    try {
      final data = await Api.getBatedorTrajeto(
        plate:        plate,
        window:       _window,
        coWindow:     _coWindow,
        minCameras:   _minCameras,
        limit:        50,
        direcao:      _direcao,
        vehicleType:  _vehicleType,
        vehicleColor: _vehicleColor,
        platePrefix:  _prefixCtrl.text.trim().isEmpty ? null : _prefixCtrl.text.trim().toUpperCase(),
      );
      if (mounted) setState(() { _result = data; _loading = false; });
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _loading = false; });
    }
  }

  // ── Build ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        foregroundColor: AppColors.text,
        elevation: 0,
        title: const Row(
          children: [
            Icon(Icons.route_rounded, color: AppColors.warning, size: 22),
            SizedBox(width: 10),
            Text(
              'Batedor — Trajeto Conjunto',
              style: TextStyle(
                color: AppColors.text,
                fontWeight: FontWeight.w700,
                fontSize: 16,
              ),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          // ── Painel de pesquisa ───────────────────────────────────────────
          _SearchPanel(
            plateCtrl:    _plateCtrl,
            prefixCtrl:   _prefixCtrl,
            focusNode:    _focusNode,
            loading:      _loading,
            filtersOpen:  _filtersOpen,
            window:       _window,
            coWindow:     _coWindow,
            minCameras:   _minCameras,
            direcao:      _direcao,
            vehicleType:  _vehicleType,
            vehicleColor: _vehicleColor,
            onSearch:     _search,
            onToggleFilters:     () => setState(() => _filtersOpen = !_filtersOpen),
            onWindowChanged:     (v) => setState(() => _window = v),
            onCoWindowChanged:   (v) => setState(() => _coWindow = v),
            onMinCamerasChanged: (v) => setState(() => _minCameras = v),
            onDirecaoChanged:    (v) => setState(() => _direcao = v == _direcao ? null : v),
            onVehicleTypeChanged:(v) => setState(() => _vehicleType = v == _vehicleType ? null : v),
            onVehicleColorChanged:(v)=> setState(() => _vehicleColor = v == _vehicleColor ? null : v),
          ),

          // ── Corpo ─────────────────────────────────────────────────────────
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator(color: AppColors.warning))
                : _error != null
                    ? _ErrorView(message: _error!)
                    : _result == null
                        ? const _EmptyHint()
                        : _ResultList(
                            result:   _result!,
                            expanded: _expanded,
                            onToggle: (i) => setState(() {
                              if (_expanded.contains(i)) {
                                _expanded.remove(i);
                              } else {
                                _expanded.add(i);
                              }
                            }),
                          ),
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Painel de pesquisa + filtros
// ─────────────────────────────────────────────────────────────────────────────

class _SearchPanel extends StatelessWidget {
  final TextEditingController plateCtrl;
  final TextEditingController prefixCtrl;
  final FocusNode focusNode;
  final bool loading;
  final bool filtersOpen;
  final String window;
  final int coWindow;
  final int minCameras;
  final String? direcao;
  final String? vehicleType;
  final String? vehicleColor;
  final VoidCallback onSearch;
  final VoidCallback onToggleFilters;
  final ValueChanged<String> onWindowChanged;
  final ValueChanged<int> onCoWindowChanged;
  final ValueChanged<int> onMinCamerasChanged;
  final ValueChanged<String> onDirecaoChanged;
  final ValueChanged<String> onVehicleTypeChanged;
  final ValueChanged<String> onVehicleColorChanged;

  const _SearchPanel({
    required this.plateCtrl,
    required this.prefixCtrl,
    required this.focusNode,
    required this.loading,
    required this.filtersOpen,
    required this.window,
    required this.coWindow,
    required this.minCameras,
    this.direcao,
    this.vehicleType,
    this.vehicleColor,
    required this.onSearch,
    required this.onToggleFilters,
    required this.onWindowChanged,
    required this.onCoWindowChanged,
    required this.onMinCamerasChanged,
    required this.onDirecaoChanged,
    required this.onVehicleTypeChanged,
    required this.onVehicleColorChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.surface,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // ── Campo de placa + botão pesquisa ───────────────────────────
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: plateCtrl,
                  focusNode: focusNode,
                  textCapitalization: TextCapitalization.characters,
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z0-9]')),
                    LengthLimitingTextInputFormatter(8),
                  ],
                  style: const TextStyle(
                    color: AppColors.text,
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                    letterSpacing: 2,
                  ),
                  decoration: InputDecoration(
                    hintText: 'PLACA ALVO',
                    hintStyle: const TextStyle(color: AppColors.muted, letterSpacing: 1),
                    prefixIcon: const Icon(Icons.directions_car_rounded, color: AppColors.warning),
                    filled: true,
                    fillColor: AppColors.background,
                    contentPadding: const EdgeInsets.symmetric(vertical: 14, horizontal: 14),
                    enabledBorder: OutlineInputBorder(
                      borderSide: const BorderSide(color: AppColors.border),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderSide: const BorderSide(color: AppColors.warning, width: 1.6),
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  onSubmitted: (_) => onSearch(),
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                height: 54,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.warning,
                    foregroundColor: Colors.black,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    padding: const EdgeInsets.symmetric(horizontal: 18),
                  ),
                  onPressed: loading ? null : onSearch,
                  child: loading
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                      : const Icon(Icons.search_rounded, size: 24),
                ),
              ),
            ],
          ),

          // ── Toggle filtros ────────────────────────────────────────────
          TextButton.icon(
            style: TextButton.styleFrom(
              foregroundColor: AppColors.muted,
              padding: const EdgeInsets.symmetric(vertical: 6),
            ),
            onPressed: onToggleFilters,
            icon: Icon(filtersOpen ? Icons.expand_less : Icons.tune_rounded, size: 16),
            label: Text(
              filtersOpen
                  ? 'Ocultar filtros'
                  : _buildFilterSummary(),
              style: const TextStyle(fontSize: 11),
            ),
          ),

          // ── Painel de filtros expansível ──────────────────────────────
          if (filtersOpen) ...[
            const Divider(color: AppColors.border, height: 1),
            const SizedBox(height: 12),

            // Janela de tempo
            _FilterSection(
              label: 'Janela de tempo',
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: _kWindows.map((e) {
                    final selected = e.$1 == window;
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(e.$2),
                        selected: selected,
                        selectedColor: AppColors.warning,
                        labelStyle: TextStyle(
                          color: selected ? Colors.black : AppColors.text,
                          fontWeight: selected ? FontWeight.w700 : FontWeight.normal,
                          fontSize: 12,
                        ),
                        backgroundColor: AppColors.background,
                        side: BorderSide(
                          color: selected ? AppColors.warning : AppColors.border,
                        ),
                        onSelected: (_) => onWindowChanged(e.$1),
                      ),
                    );
                  }).toList(),
                ),
              ),
            ),

            const SizedBox(height: 10),

            // Tempo conjunto por câmera
            _FilterSection(
              label: 'Tempo máximo de diferença por câmera',
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: _kCoWindows.map((e) {
                    final selected = e.$1 == coWindow;
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(e.$2),
                        selected: selected,
                        selectedColor: AppColors.primary,
                        labelStyle: TextStyle(
                          color: selected ? Colors.white : AppColors.text,
                          fontWeight: selected ? FontWeight.w700 : FontWeight.normal,
                          fontSize: 12,
                        ),
                        backgroundColor: AppColors.background,
                        side: BorderSide(
                          color: selected ? AppColors.primary : AppColors.border,
                        ),
                        onSelected: (_) => onCoWindowChanged(e.$1),
                      ),
                    );
                  }).toList(),
                ),
              ),
            ),

            const SizedBox(height: 10),

            // Mínimo de câmeras juntas
            _FilterSection(
              label: 'Mínimo de câmeras juntas',
              child: Row(
                children: _kMinCameras.map((n) {
                  final selected = n == minCameras;
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text('$n+'),
                      selected: selected,
                      selectedColor: AppColors.danger,
                      labelStyle: TextStyle(
                        color: selected ? Colors.white : AppColors.text,
                        fontWeight: selected ? FontWeight.w700 : FontWeight.normal,
                        fontSize: 12,
                      ),
                      backgroundColor: AppColors.background,
                      side: BorderSide(
                        color: selected ? AppColors.danger : AppColors.border,
                      ),
                      onSelected: (_) => onMinCamerasChanged(n),
                    ),
                  );
                }).toList(),
              ),
            ),

            const SizedBox(height: 14),
            const Divider(color: AppColors.border, height: 1),
            const SizedBox(height: 10),
            Text('FILTROS DO SUSPEITO',
                style: TextStyle(
                    color: AppColors.danger,
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.2)),
            const SizedBox(height: 10),

            // Prefixo de placa do suspeito
            _FilterSection(
              label: 'Prefixo da placa do suspeito (ex: ABC, PR)',
              child: TextField(
                controller: prefixCtrl,
                textCapitalization: TextCapitalization.characters,
                inputFormatters: [
                  FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z0-9]')),
                  LengthLimitingTextInputFormatter(7),
                ],
                style: const TextStyle(
                    color: AppColors.text,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 2,
                    fontSize: 14),
                decoration: InputDecoration(
                  hintText: 'ex: ABC ou PR',
                  hintStyle: const TextStyle(color: AppColors.muted, letterSpacing: 1, fontSize: 12),
                  prefixIcon: const Icon(Icons.search_rounded, color: AppColors.muted, size: 18),
                  suffixIcon: prefixCtrl.text.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear, color: AppColors.muted, size: 16),
                          onPressed: () => prefixCtrl.clear(),
                        )
                      : null,
                  filled: true,
                  fillColor: AppColors.background,
                  contentPadding: const EdgeInsets.symmetric(vertical: 10, horizontal: 14),
                  enabledBorder: OutlineInputBorder(
                    borderSide: const BorderSide(color: AppColors.border),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderSide: const BorderSide(color: AppColors.danger, width: 1.4),
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ),

            const SizedBox(height: 10),

            // Direção do trajeto
            _FilterSection(
              label: 'Direção do trajeto',
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: _kDirecoes.map((e) {
                    final selected = e.$1 == direcao;
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(e.$2),
                        selected: selected,
                        selectedColor: AppColors.danger,
                        labelStyle: TextStyle(
                          color: selected ? Colors.white : AppColors.text,
                          fontWeight: selected ? FontWeight.w700 : FontWeight.normal,
                          fontSize: 12,
                        ),
                        backgroundColor: AppColors.background,
                        side: BorderSide(
                            color: selected ? AppColors.danger : AppColors.border),
                        onSelected: (_) => onDirecaoChanged(e.$1),
                      ),
                    );
                  }).toList(),
                ),
              ),
            ),

            const SizedBox(height: 10),

            // Tipo de veículo
            _FilterSection(
              label: 'Tipo de veículo do suspeito',
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: _kVehicleTypes.map((e) {
                    final selected = e.$1 == vehicleType;
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(e.$2),
                        selected: selected,
                        selectedColor: AppColors.primary,
                        labelStyle: TextStyle(
                          color: selected ? Colors.white : AppColors.text,
                          fontWeight: selected ? FontWeight.w700 : FontWeight.normal,
                          fontSize: 12,
                        ),
                        backgroundColor: AppColors.background,
                        side: BorderSide(
                            color: selected ? AppColors.primary : AppColors.border),
                        onSelected: (_) => onVehicleTypeChanged(e.$1),
                      ),
                    );
                  }).toList(),
                ),
              ),
            ),

            const SizedBox(height: 10),

            // Cor do veículo
            _FilterSection(
              label: 'Cor do veículo do suspeito',
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: _kVehicleColors.map((cor) {
                    final selected = cor == vehicleColor;
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(cor),
                        selected: selected,
                        selectedColor: _colorFromName(cor),
                        labelStyle: TextStyle(
                          color: selected ? _colorTextFromName(cor) : AppColors.text,
                          fontWeight: selected ? FontWeight.w700 : FontWeight.normal,
                          fontSize: 12,
                        ),
                        backgroundColor: AppColors.background,
                        side: BorderSide(
                            color: selected
                                ? _colorFromName(cor)
                                : AppColors.border),
                        onSelected: (_) => onVehicleColorChanged(cor),
                      ),
                    );
                  }).toList(),
                ),
              ),
            ),

            const SizedBox(height: 12),
          ],

          const Divider(color: AppColors.border, height: 1),
        ],
      ),
    );
  }
}

  // ── Resumo dos filtros ativos para o label ──────────────────────────────
  String _buildFilterSummary() {
    final parts = <String>[
      'janela $_window',
      '${_fmtDur(coWindow)}/câm',
      'mín. $minCameras',
    ];
    if (direcao     != null) parts.add(direcao!);
    if (vehicleType != null) parts.add(_kTypeLabel[vehicleType] ?? vehicleType!);
    if (vehicleColor!= null) parts.add(vehicleColor!);
    if (prefixCtrl.text.isNotEmpty) parts.add('placa: ${prefixCtrl.text.toUpperCase()}');
    return parts.join('  •  ');
  }
}

// ─── Mapeamento de cor nome → Color Flutter ───────────────────────────────────

Color _colorFromName(String cor) {
  switch (cor.toLowerCase()) {
    case 'preto':    return const Color(0xFF1A1A1A);
    case 'branco':   return const Color(0xFFF5F5F5);
    case 'prata':    return const Color(0xFF9E9E9E);
    case 'cinza':    return const Color(0xFF757575);
    case 'vermelho': return AppColors.danger;
    case 'azul':     return const Color(0xFF1565C0);
    case 'amarelo':  return AppColors.warning;
    case 'verde':    return AppColors.primary;
    case 'marrom':   return const Color(0xFF6D4C41);
    case 'laranja':  return const Color(0xFFE65100);
    default:         return AppColors.border;
  }
}

Color _colorTextFromName(String cor) {
  switch (cor.toLowerCase()) {
    case 'branco':
    case 'prata':
    case 'amarelo': return Colors.black;
    default:        return Colors.white;
  }
}

class _FilterSection extends StatelessWidget {
  final String label;
  final Widget child;
  const _FilterSection({required this.label, required this.child});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 11, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        child,
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Lista de resultados
// ─────────────────────────────────────────────────────────────────────────────

class _ResultList extends StatelessWidget {
  final Map<String, dynamic> result;
  final Set<int> expanded;
  final ValueChanged<int> onToggle;

  const _ResultList({required this.result, required this.expanded, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    final companions = (result['companions'] as List?) ?? [];
    final total      = result['total'] as int? ?? 0;
    final plate      = result['plate'] as String? ?? '';
    final window     = result['window'] as String? ?? '';

    if (companions.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.search_off_rounded, color: AppColors.muted, size: 48),
              const SizedBox(height: 16),
              Text(
                'Nenhum veículo encontrado transitando junto à placa $plate na janela de $window.',
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.muted, fontSize: 14),
              ),
            ],
          ),
        ),
      );
    }

    return Column(
      children: [
        // ── Cabeçalho do resultado ─────────────────────────────────────
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          color: AppColors.surface,
          child: Row(
            children: [
              const Icon(Icons.warning_amber_rounded, color: AppColors.warning, size: 16),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '$total veículo(s) suspeito(s) detectado(s) transitando junto a $plate',
                  style: const TextStyle(
                    color: AppColors.warning,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
              ),
            ],
          ),
        ),

        // ── Cards de companheiros ──────────────────────────────────────
        Expanded(
          child: ListView.separated(
            padding: const EdgeInsets.all(12),
            itemCount: companions.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, i) {
              final c = companions[i] as Map<String, dynamic>;
              return _CompanionCard(
                index:    i,
                data:     c,
                isOpen:   expanded.contains(i),
                onToggle: () => onToggle(i),
              );
            },
          ),
        ),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Card de um companheiro suspeito
// ─────────────────────────────────────────────────────────────────────────────

class _CompanionCard extends StatelessWidget {
  final int index;
  final Map<String, dynamic> data;
  final bool isOpen;
  final VoidCallback onToggle;

  const _CompanionCard({
    required this.index,
    required this.data,
    required this.isOpen,
    required this.onToggle,
  });

  @override
  Widget build(BuildContext context) {
    final companion      = data['companion'] as String? ?? '—';
    final camerasTogether= data['cameras_together'] as int? ?? 0;
    final distKm         = (data['route_distance_km'] as num?)?.toDouble() ?? 0.0;
    final avgDelta       = data['avg_delta_sec'] as int? ?? 0;
    final travelTarget   = data['travel_time_target_sec'] as int? ?? 0;
    final travelComp     = data['travel_time_companion_sec'] as int? ?? 0;
    final firstSeen      = data['first_seen'] as String?;
    final lastSeen       = data['last_seen'] as String?;
    final evidence       = (data['evidence'] as List?) ?? [];
    final vtype          = data['vehicle_type'] as String?;
    final vcolor         = data['vehicle_color'] as String?;

    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        children: [
          // ── Cabeçalho do card ────────────────────────────────────────
          InkWell(
            borderRadius: const BorderRadius.vertical(top: Radius.circular(14)),
            onTap: onToggle,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 14, 14, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      // Ranking badge
                      Container(
                        width: 28,
                        height: 28,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: AppColors.border,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          '#${index + 1}',
                          style: const TextStyle(
                            color: AppColors.muted,
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),

                      // Placa
                      Expanded(
                        child: Text(
                          companion,
                          style: const TextStyle(
                            color: AppColors.warning,
                            fontSize: 22,
                            fontWeight: FontWeight.w900,
                            letterSpacing: 3,
                          ),
                        ),
                      ),
                    ],
                  ),

                  const SizedBox(height: 12),

                  // ── Métricas em grid ──────────────────────────────────
                  Row(
                    children: [
                      _MetricChip(
                        icon: Icons.videocam_rounded,
                        label: '$camerasTogether câmera(s) juntos',
                        color: camerasTogether >= 3 ? AppColors.danger : AppColors.warning,
                      ),
                      const SizedBox(width: 8),
                      _MetricChip(
                        icon: Icons.timer_outlined,
                        label: _fmtDur(avgDelta),
                        color: AppColors.muted,
                        tooltip: 'Diferença média entre eles por câmera',
                      ),
                      if (distKm > 0) ...[
                        const SizedBox(width: 8),
                        _MetricChip(
                          icon: Icons.straighten_rounded,
                          label: _fmtDist(distKm),
                          color: AppColors.accent,
                          tooltip: 'Distância total do percurso',
                        ),
                      ],
                    ],
                  ),

                  const SizedBox(height: 8),

                  // ── Tipo / Cor do veículo suspeito ───────────────────
                  if (vtype != null || vcolor != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        children: [
                          if (vtype != null) ...[
                            _MetricChip(
                              icon: Icons.directions_car_rounded,
                              label: _kTypeLabel[vtype] ?? vtype,
                              color: AppColors.primary,
                            ),
                            const SizedBox(width: 8),
                          ],
                          if (vcolor != null)
                            _MetricChip(
                              icon: Icons.palette_rounded,
                              label: vcolor,
                              color: _colorFromName(vcolor),
                            ),
                        ],
                      ),
                    ),

                  // ── Tempos de trajeto ─────────────────────────────────
                  if (travelTarget > 0 || travelComp > 0)
                    Row(
                      children: [
                        const Icon(Icons.route_rounded, size: 13, color: AppColors.muted),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            'Alvo: ${_fmtDur(travelTarget)}   Suspeito: ${_fmtDur(travelComp)}',
                            style: const TextStyle(color: AppColors.muted, fontSize: 11),
                          ),
                        ),
                      ],
                    ),

                  // ── Período ──────────────────────────────────────────
                  if (firstSeen != null) ...[
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        const Icon(Icons.schedule_rounded, size: 13, color: AppColors.muted),
                        const SizedBox(width: 4),
                        Text(
                          '${_fmtTs(firstSeen)} → ${_fmtTs(lastSeen)}',
                          style: const TextStyle(color: AppColors.muted, fontSize: 11),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),

          // ── Botão expandir evidências ────────────────────────────────
          if (evidence.isNotEmpty) ...[
            const Divider(color: AppColors.border, height: 1),
            InkWell(
              onTap: onToggle,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                child: Row(
                  children: [
                    Icon(
                      isOpen ? Icons.expand_less_rounded : Icons.expand_more_rounded,
                      color: AppColors.muted,
                      size: 18,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      isOpen
                          ? 'Ocultar percurso (${evidence.length} câmera(s))'
                          : 'Ver percurso completo (${evidence.length} câmera(s))',
                      style: const TextStyle(color: AppColors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
            ),
          ],

          // ── Evidências expandidas ────────────────────────────────────
          if (isOpen && evidence.isNotEmpty) ...[
            const Divider(color: AppColors.border, height: 1),
            ListView.separated(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              itemCount: evidence.length,
              separatorBuilder: (_, __) => const Divider(
                color: AppColors.border,
                height: 12,
                indent: 12,
              ),
              itemBuilder: (_, i) {
                final ev        = evidence[i] as Map<String, dynamic>;
                final camNome   = ev['cam_nome']     as String? ?? ev['camera_id'] as String? ?? '—';
                final tsTarget  = ev['ts_target']    as String?;
                final tsComp    = ev['ts_companion'] as String?;
                final deltaSec  = ev['delta_sec']    as int? ?? 0;
                final hasCoords = ev['lat'] != null && ev['lon'] != null;

                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Index da câmera no percurso
                    Container(
                      width: 24,
                      height: 24,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: AppColors.primary.withValues(alpha: .2),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        '${i + 1}',
                        style: const TextStyle(
                          color: AppColors.accent,
                          fontSize: 10,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.videocam_outlined, size: 13, color: AppColors.muted),
                              const SizedBox(width: 4),
                              Expanded(
                                child: Text(
                                  camNome,
                                  style: const TextStyle(
                                    color: AppColors.text,
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                  ),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              if (hasCoords)
                                const Icon(Icons.location_on_rounded, size: 11, color: AppColors.accent),
                            ],
                          ),
                          const SizedBox(height: 3),
                          Row(
                            children: [
                              const Icon(Icons.directions_car_rounded, size: 11, color: AppColors.warning),
                              const SizedBox(width: 3),
                              Text(
                                'Alvo: ${_fmtTs(tsTarget)}',
                                style: const TextStyle(color: AppColors.muted, fontSize: 10),
                              ),
                            ],
                          ),
                          Row(
                            children: [
                              const Icon(Icons.person_search_rounded, size: 11, color: AppColors.danger),
                              const SizedBox(width: 3),
                              Text(
                                'Suspeito: ${_fmtTs(tsComp)}',
                                style: const TextStyle(color: AppColors.muted, fontSize: 10),
                              ),
                              const Spacer(),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                                decoration: BoxDecoration(
                                  color: AppColors.border,
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: Text(
                                  '∆ ${_fmtDur(deltaSec)}',
                                  style: const TextStyle(
                                    color: AppColors.muted,
                                    fontSize: 9,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Widgets auxiliares
// ─────────────────────────────────────────────────────────────────────────────

class _MetricChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final String? tooltip;
  const _MetricChip({required this.icon, required this.label, required this.color, this.tooltip});

  @override
  Widget build(BuildContext context) {
    final chip = Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: .30)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 4),
          Text(label, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
        ],
      ),
    );
    if (tooltip != null) {
      return Tooltip(message: tooltip!, child: chip);
    }
    return chip;
  }
}

class _EmptyHint extends StatelessWidget {
  const _EmptyHint();
  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.route_rounded, size: 64, color: AppColors.border),
            SizedBox(height: 20),
            Text(
              'Informe a placa do veículo alvo',
              style: TextStyle(color: AppColors.text, fontSize: 16, fontWeight: FontWeight.w600),
              textAlign: TextAlign.center,
            ),
            SizedBox(height: 8),
            Text(
              'O sistema irá identificar todos os veículos que\nfizeram o mesmo percurso junto ao alvo.',
              style: TextStyle(color: AppColors.muted, fontSize: 13),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  final String message;
  const _ErrorView({required this.message});
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline_rounded, color: AppColors.danger, size: 40),
            const SizedBox(height: 12),
            Text(message, style: const TextStyle(color: AppColors.danger, fontSize: 13), textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}
