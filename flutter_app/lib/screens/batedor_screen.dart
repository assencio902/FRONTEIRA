import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../repositories/plate_recognition_repository.dart';
import '../services/api.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_button.dart';
import '../widgets/plate_search_field.dart';

// ─── Paleta mapeada para AppColors ───────────────────────────────────────────
const _kBg     = AppColors.background;
const _kCard   = AppColors.surface;
const _kBorder = AppColors.border;
const _kYellow = AppColors.warning;
const _kRed    = AppColors.danger;
const _kMuted  = AppColors.muted;

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

  // ── Estado de busca ───────────────────────────────────────────────────────
  bool   _loading   = false;
  bool   _scanning   = false;
  File? _capturedImage;
  String? _scanResult;
  String? _error;
  Map<String, dynamic>? _result;

  // ── Filtros de comportamento ─────────────────────────────────────────────
  String _window     = '24h';
  int    _coWindow   = 600;
  int    _minCameras = 2;

  // ── Filtros do suspeito ───────────────────────────────────────────────────
  String? _direcao;
  String? _vehicleType;
  String? _vehicleColor;
  final _prefixCtrl = TextEditingController();

  // ── Expansão de evidências ─────────────────────────────────────────────────
  final Set<int> _expanded = {};

  @override
  void dispose() {
    _plateCtrl.dispose();
    _prefixCtrl.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  // ── Reconhecimento via API ───────────────────────────────────────────────

  Future<void> _scanPlate() async {
    setState(() { _scanning = true; _scanResult = null; _capturedImage = null; });

    try {
      final picker = ImagePicker();
      final XFile? photo = await picker.pickImage(
        source: ImageSource.camera,
        imageQuality: 85,
        preferredCameraDevice: CameraDevice.rear,
      );

      if (photo == null) {
        setState(() => _scanning = false);
        return;
      }

      final imageFile = File(photo.path);
      setState(() => _capturedImage = imageFile);

      final result = await PlateRecognitionRepository.recognize(imageFile);
      final plate = result.plate?.trim().toUpperCase() ?? '';

      if (plate.isNotEmpty) {
        _plateCtrl.text = plate;
        setState(() => _scanResult = 'found');
        await Future.delayed(const Duration(milliseconds: 600));
        if (mounted) _search();
      } else {
        setState(() => _scanResult = 'notfound');
      }
    } catch (e) {
      setState(() => _scanResult = 'notfound');
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
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

  void _clearFilters() {
    setState(() {
      _window = '24h';
      _coWindow = 600;
      _minCameras = 2;
      _direcao = null;
      _vehicleType = null;
      _vehicleColor = null;
      _prefixCtrl.clear();
      _plateCtrl.clear();
      _capturedImage = null;
      _scanResult = null;
    });
  }

  // ── Build ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _kBg,
      appBar: AppBar(
        backgroundColor: _kCard,
        elevation: 0,
        title: const Row(
          children: [
            Icon(Icons.route_rounded, color: _kYellow, size: 20),
            SizedBox(width: 8),
            Text(
              'Batedor — Trajeto Conjunto',
              style: TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w800,
                fontSize: 16,
                letterSpacing: 1,
              ),
            ),
          ],
        ),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(height: 1, color: _kBorder),
        ),
      ),
      body: Column(
        children: [
          // Área de resultados
          Expanded(
            child: _buildResultsArea(),
          ),

          // Painel de filtros inferior
          SafeArea(
            top: false,
            child: Container(
              decoration: const BoxDecoration(
                color: _kCard,
                border: Border(top: BorderSide(color: _kBorder)),
              ),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(context).size.height * 0.55,
                ),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _buildFilters(),
                      const SizedBox(height: 12),
                      _buildPlateField(),
                      const SizedBox(height: 12),
                      LoadingButton(
                        label: 'Buscar',
                        loading: _loading,
                        onPressed: _search,
                        icon: Icons.search_rounded,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ─── Área de resultados ───────────────────────────────────────────────────

  Widget _buildResultsArea() {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 90),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_scanning || _loading)
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: _kCard,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _kBorder),
              ),
              child: Row(
                children: [
                  const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: _kYellow),
                  ),
                  const SizedBox(width: 10),
                  Text(
                    _scanning ? 'Capturando e reconhecendo placa...' : 'Pesquisando ameaças...',
                    style: const TextStyle(color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            )
          else if (_scanResult == 'notfound')
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: _kRed.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _kRed.withValues(alpha: 0.35)),
              ),
              child: const Row(
                children: [
                  Icon(Icons.error_outline_rounded, color: _kRed, size: 18),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Nenhuma placa reconhecida. Ajuste o enquadramento e tente novamente.',
                      style: TextStyle(color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            )
          else if (_scanResult == 'found')
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: _kYellow.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _kYellow.withValues(alpha: 0.35)),
              ),
              child: const Row(
                children: [
                  Icon(Icons.check_circle_outline_rounded, color: _kYellow, size: 18),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Placa detectada. Iniciando busca de ameaças...',
                      style: TextStyle(color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            )
          else if (_error != null)
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: _kRed.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _kRed.withValues(alpha: 0.35)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.error_outline_rounded, color: _kRed, size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _error!,
                      style: const TextStyle(color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            )
          else if (_result == null)
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: _kCard,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _kBorder),
              ),
              child: const Row(
                children: [
                  Icon(Icons.info_outline_rounded, color: _kMuted, size: 18),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Configure os filtros, informe uma placa e toque em Buscar.',
                      style: TextStyle(color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            )
          else
            _ResultList(
              result: _result!,
              expanded: _expanded,
              onToggle: (i) => setState(() {
                if (_expanded.contains(i)) {
                  _expanded.remove(i);
                } else {
                  _expanded.add(i);
                }
              }),
            ),
          if (_capturedImage != null) ...[
            const SizedBox(height: 12),
            _buildImagePreview(),
          ],
        ],
      ),
    );
  }

  // ─── Preview imagem ────────────────────────────────────────────────────────

  Widget _buildImagePreview() {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _kBorder),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            color: _kCard,
            child: const Row(
              children: [
                Icon(Icons.image_rounded, color: _kMuted, size: 15),
                SizedBox(width: 8),
                Text(
                  'Imagem capturada',
                  style: TextStyle(
                      color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
          Image.file(
            _capturedImage!,
            fit: BoxFit.cover,
            height: 200,
          ),
        ],
      ),
    );
  }
    final hasAnyFilter = _direcao != null ||
      _vehicleType != null ||
      _vehicleColor != null ||
      _prefixCtrl.text.isNotEmpty ||
      _window != '24h' ||
      _coWindow != 600 ||
      _minCameras != 2;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _kCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _kBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Cabeçalho
          Row(
            children: [
              const Icon(Icons.filter_list_rounded, color: _kYellow, size: 16),
              const SizedBox(width: 8),
              const Text(
                'FILTROS DE AMEAÇAS',
                style: TextStyle(
                  color: _kYellow,
                  fontSize: 14,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 2,
                ),
              ),
              const Spacer(),
              if (hasAnyFilter)
                GestureDetector(
                  onTap: _clearFilters,
                  child: const Text('Limpar',
                      style: TextStyle(
                        color: _kMuted,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        decoration: TextDecoration.underline,
                        decorationColor: _kMuted,
                      )),
                ),
            ],
          ),
          const SizedBox(height: 14),

          // Janela de tempo
          const Row(
            children: [
              Icon(Icons.schedule_rounded, color: _kMuted, size: 14),
              SizedBox(width: 6),
              Text('JANELA DE TEMPO',
                  style: TextStyle(
                      color: _kMuted,
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.5)),
            ],
          ),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _kWindows.map((e) {
                final selected = e.$1 == _window;
                return GestureDetector(
                  onTap: () => setState(() => _window = e.$1),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 160),
                    margin: const EdgeInsets.only(right: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      color: selected ? _kYellow.withValues(alpha: 0.14) : _kBg,
                      borderRadius: BorderRadius.circular(22),
                      border: Border.all(
                        color: selected ? _kYellow.withValues(alpha: 0.7) : _kBorder,
                        width: selected ? 1.3 : 1,
                      ),
                    ),
                    child: Text(e.$2,
                        style: TextStyle(
                          color: selected ? _kYellow : _kMuted,
                          fontSize: 13,
                          fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                        )),
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 14),

          // Co-window
          const Row(
            children: [
              Icon(Icons.timer_rounded, color: _kMuted, size: 14),
              SizedBox(width: 6),
              Text('TEMPO MÁX. POR CÂMERA',
                  style: TextStyle(
                      color: _kMuted,
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.5)),
            ],
          ),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _kCoWindows.map((e) {
                final selected = e.$1 == _coWindow;
                return GestureDetector(
                  onTap: () => setState(() => _coWindow = e.$1),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 160),
                    margin: const EdgeInsets.only(right: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      color: selected ? AppColors.primary.withValues(alpha: 0.14) : _kBg,
                      borderRadius: BorderRadius.circular(22),
                      border: Border.all(
                        color: selected ? AppColors.primary.withValues(alpha: 0.7) : _kBorder,
                        width: selected ? 1.3 : 1,
                      ),
                    ),
                    child: Text(e.$2,
                        style: TextStyle(
                          color: selected ? AppColors.primary : _kMuted,
                          fontSize: 13,
                          fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                        )),
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 14),

          // Mínimo de câmeras
          const Row(
            children: [
              Icon(Icons.videocam_rounded, color: _kMuted, size: 14),
              SizedBox(width: 6),
              Text('MÍNIMO DE CÂMERAS',
                  style: TextStyle(
                      color: _kMuted,
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.5)),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: _kMinCameras.map((n) {
              final selected = n == _minCameras;
              return GestureDetector(
                onTap: () => setState(() => _minCameras = n),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 160),
                  margin: const EdgeInsets.only(right: 8),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                  decoration: BoxDecoration(
                    color: selected ? _kRed.withValues(alpha: 0.14) : _kBg,
                    borderRadius: BorderRadius.circular(22),
                    border: Border.all(
                      color: selected ? _kRed.withValues(alpha: 0.7) : _kBorder,
                      width: selected ? 1.3 : 1,
                    ),
                  ),
                  child: Text('$n+',
                      style: TextStyle(
                        color: selected ? _kRed : _kMuted,
                        fontSize: 13,
                        fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                      )),
                ),
              );
            }).toList(),
          ),
          const SizedBox(height: 16),

          const Divider(color: _kBorder, height: 1),
          const SizedBox(height: 16),

          // Filtros do suspeito
          const Row(
            children: [
              Icon(Icons.person_search_rounded, color: _kRed, size: 16),
              SizedBox(width: 8),
              Text(
                'FILTROS DO SUSPEITO',
                style: TextStyle(
                  color: _kRed,
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.5,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // Prefixo de placa
          const Text('Prefixo da placa (ex: ABC, PR)',
              style: TextStyle(
                  color: _kMuted,
                  fontSize: 12,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          TextField(
            controller: _prefixCtrl,
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
              hintText: 'ABC ou PR',
              hintStyle: const TextStyle(
                  color: AppColors.muted, letterSpacing: 1, fontSize: 12),
              filled: true,
              fillColor: _kBg.withValues(alpha: 0.7),
              contentPadding:
                  const EdgeInsets.symmetric(vertical: 10, horizontal: 14),
              enabledBorder: OutlineInputBorder(
                borderSide: const BorderSide(color: _kBorder),
                borderRadius: BorderRadius.circular(10),
              ),
              focusedBorder: OutlineInputBorder(
                borderSide: const BorderSide(color: _kRed, width: 1.4),
                borderRadius: BorderRadius.circular(10),
              ),
            ),
          ),
          const SizedBox(height: 12),

          // Direção
          const Text('Direção do trajeto',
              style: TextStyle(
                  color: _kMuted,
                  fontSize: 12,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _kDirecoes.map((e) {
                final selected = e.$1 == _direcao;
                return GestureDetector(
                  onTap: () => setState(() => _direcao = selected ? null : e.$1),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 160),
                    margin: const EdgeInsets.only(right: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      color: selected ? _kRed.withValues(alpha: 0.14) : _kBg,
                      borderRadius: BorderRadius.circular(22),
                      border: Border.all(
                        color: selected ? _kRed.withValues(alpha: 0.7) : _kBorder,
                        width: selected ? 1.3 : 1,
                      ),
                    ),
                    child: Text(e.$2,
                        style: TextStyle(
                          color: selected ? _kRed : _kMuted,
                          fontSize: 13,
                          fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                        )),
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 12),

          // Tipo de veículo
          const Text('Tipo de veículo',
              style: TextStyle(
                  color: _kMuted,
                  fontSize: 12,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _kVehicleTypes.map((e) {
                final selected = e.$1 == _vehicleType;
                return GestureDetector(
                  onTap: () => setState(() => _vehicleType = selected ? null : e.$1),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 160),
                    margin: const EdgeInsets.only(right: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      color: selected ? AppColors.primary.withValues(alpha: 0.14) : _kBg,
                      borderRadius: BorderRadius.circular(22),
                      border: Border.all(
                        color: selected ? AppColors.primary.withValues(alpha: 0.7) : _kBorder,
                        width: selected ? 1.3 : 1,
                      ),
                    ),
                    child: Text(e.$2,
                        style: TextStyle(
                          color: selected ? AppColors.primary : _kMuted,
                          fontSize: 13,
                          fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                        )),
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 12),

          // Cor do veículo
          const Text('Cor do veículo',
              style: TextStyle(
                  color: _kMuted,
                  fontSize: 12,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _kVehicleColors.map((cor) {
                final selected = cor == _vehicleColor;
                return GestureDetector(
                  onTap: () => setState(() => _vehicleColor = selected ? null : cor),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 160),
                    margin: const EdgeInsets.only(right: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      color: selected ? _colorFromName(cor).withValues(alpha: 0.2) : _kBg,
                      borderRadius: BorderRadius.circular(22),
                      border: Border.all(
                        color: selected ? _colorFromName(cor) : _kBorder,
                        width: selected ? 1.3 : 1,
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Container(
                          width: 10,
                          height: 10,
                          decoration: BoxDecoration(
                            color: _colorFromName(cor),
                            shape: BoxShape.circle,
                            border: Border.all(color: Colors.white24, width: 0.5),
                          ),
                        ),
                        const SizedBox(width: 5),
                        Text(cor,
                            style: TextStyle(
                              color: selected ? Colors.white : _kMuted,
                              fontSize: 13,
                              fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                            )),
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
        ],
      ),
    );
  }

  // ─── Campo de placa ───────────────────────────────────────────────────────

  Widget _buildPlateField() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'PLACA ALVO',
          style: TextStyle(
            color: _kMuted,
            fontSize: 12,
            fontWeight: FontWeight.w800,
            letterSpacing: 2.0,
          ),
        ),
        const SizedBox(height: 10),
        Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _kYellow.withValues(alpha: 0.4)),
          ),
          clipBehavior: Clip.antiAlias,
          child: PlateSearchField(
            controller: _plateCtrl,
            focusNode: _focusNode,
            hintText: 'ABC1234',
            onSubmitted: _search,
            onChanged: (_) {
              if (_scanResult != null) setState(() => _scanResult = null);
            },
            suffixIcon: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  icon: const Icon(Icons.camera_alt_rounded, color: _kYellow, size: 20),
                  tooltip: 'Fotografar placa',
                  onPressed: _scanning || _loading ? null : _scanPlate,
                  padding: const EdgeInsets.all(8),
                ),
                IconButton(
                  icon: const Icon(Icons.clear_rounded, color: _kMuted, size: 18),
                  tooltip: 'Limpar',
                  onPressed: () {
                    _plateCtrl.clear();
                    setState(() { _scanResult = null; _capturedImage = null; });
                  },
                  padding: const EdgeInsets.all(8),
                ),
              ],
            ),
          ),
        ),
      ],
    );
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
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
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
                            fontSize: 12,
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
                            style: const TextStyle(color: AppColors.muted, fontSize: 13),
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
                          style: const TextStyle(color: AppColors.muted, fontSize: 13),
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
                          fontSize: 12,
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
                                style: const TextStyle(color: AppColors.muted, fontSize: 12),
                              ),
                            ],
                          ),
                          Row(
                            children: [
                              const Icon(Icons.person_search_rounded, size: 11, color: AppColors.danger),
                              const SizedBox(width: 3),
                              Text(
                                'Suspeito: ${_fmtTs(tsComp)}',
                                style: const TextStyle(color: AppColors.muted, fontSize: 12),
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
                                    fontSize: 12,
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
          Text(label, style: TextStyle(color: color, fontSize: 13, fontWeight: FontWeight.w600)),
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
