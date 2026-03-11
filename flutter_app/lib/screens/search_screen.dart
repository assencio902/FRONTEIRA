import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../repositories/plate_recognition_repository.dart';
import '../services/api.dart';
import '../services/auth_storage.dart';
import '../theme/app_theme.dart';
import '../models/period_filter.dart';
import '../widgets/loading_button.dart';
import '../widgets/period_filter_sheet.dart';
import '../widgets/plate_search_field.dart';
import 'login_screen.dart';
import 'result_screen.dart';

// ─── Paleta mapeada para AppColors ───────────────────────────────────────────
const _kBg     = AppColors.background;
const _kCard   = AppColors.surface;
const _kBorder = AppColors.border;
const _kYellow = AppColors.warning;
const _kRed    = AppColors.danger;
const _kMuted  = AppColors.muted;

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _plateCtrl = TextEditingController();
  bool _loading    = false;
  bool _scanning   = false;
  File? _capturedImage;
  String? _scanResult;

  // ─── Filtros ──────────────────────────────────────────────────────────
  // Câmeras da API
  List<Map<String, dynamic>> _cameras   = [];
  bool _camerasLoading                  = false;
  // Câmera selecionada
  Map<String, dynamic>? _filterCamera;
  // Direção
  String? _filterDirecao;          // 'ENTRADA' | 'SAÍDA' | null
  // Cor do veículo
  String? _filterCor;
  // Nome (busca livre)
  String? _filterNome;
  // Período
  PeriodFilter? _filterPeriod;

  @override
  void initState() {
    super.initState();
    _loadCameras();
  }

  Future<void> _loadCameras() async {
    setState(() => _camerasLoading = true);
    try {
      final list = await Api.getCameras();
      if (mounted) setState(() => _cameras = list);
    } catch (_) {
      // silencioso — usa lista vazia se a API falhar
    } finally {
      if (mounted) setState(() => _camerasLoading = false);
    }
  }

  @override
  void dispose() {
    _plateCtrl.dispose();
    super.dispose();
  }

  // ─── Reconhecimento via API ───────────────────────────────────────────────

  Future<void> _scanPlate() async {
    setState(() { _scanning = true; _scanResult = null; _capturedImage = null; });

    try {
      // ── 1. Abrir câmera ──────────────────────────────────────────────────
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

      // ── 2. Enviar para API ───────────────────────────────────────────────
      final result = await PlateRecognitionRepository.recognize(imageFile);

      // Debug: imprime apenas em desenvolvimento
      debugPrint('[SearchScreen] recognize result: $result');

      // ── 3. Avaliar resposta ──────────────────────────────────────────────
      final plate = result.plate?.trim().toUpperCase() ?? '';

      if (plate.isNotEmpty) {
        _plateCtrl.text = plate;
        setState(() => _scanResult = 'found');
        // Pequena pausa para o usuário ver a placa detectada
        await Future.delayed(const Duration(milliseconds: 600));
        if (mounted) _search();
      } else {
        setState(() => _scanResult = 'notfound');
        _showError('Não foi possível reconhecer. Tente novamente.');
      }
    } on Exception catch (e) {
      final msg = e.toString();
      if (msg.contains('401') || msg.contains('Não autenticado')) {
        await AuthStorage.clear();
        if (!mounted) return;
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
          (_) => false,
        );
        return;
      }
      _showError(msg);
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  // ─── PESQUISA ─────────────────────────────────────────────────────────────

  Future<void> _search() async {
    final plate = _plateCtrl.text.trim().toUpperCase().replaceAll(RegExp(r'[- ]'), '');
    setState(() => _loading = true);
    try {
      final result = await Api.platesSearch(
        plate,
        dtFrom: _filterPeriod?.from,
        dtTo: _filterPeriod?.to,
      );
      if (!mounted) return;
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => ResultScreen(
            plate: plate.isEmpty ? 'ÚLTIMAS PASSAGENS' : plate,
            result: result,
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString();
      if (msg.contains('401') || msg.contains('Nao autenticado') || msg.contains('Não autenticado')) {
        await AuthStorage.clear();
        if (!mounted) return;
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
          (_) => false,
        );
        return;
      }
      _showError(msg);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _showError(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: _kRed,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _logout() async {
    await AuthStorage.clear();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  // ─── UI ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _kBg,
      appBar: AppBar(
        backgroundColor: _kCard,
        elevation: 0,
        title: const Row(
          children: [
            Icon(Icons.manage_search_rounded, color: _kYellow, size: 20),
            SizedBox(width: 8),
            Text(
              'PESQUISA DE PLACA',
              style: TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w800,
                fontSize: 16,
                letterSpacing: 2,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout, color: _kMuted),
            tooltip: 'Sair',
            onPressed: _logout,
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(height: 1, color: _kBorder),
        ),
      ),
      body: Column(
        children: [
          // tab-results
          Expanded(
            child: _buildResultsArea(),
          ),

          // tab-filters-bottom
          SafeArea(
            top: false,
            child: Container(
              decoration: const BoxDecoration(
                color: _kCard,
                border: Border(top: BorderSide(color: _kBorder)),
              ),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(context).size.height * 0.38,
                ),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(10, 6, 10, 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _buildTextField(),
                      const SizedBox(height: 5),
                      _buildFilters(),
                      const SizedBox(height: 5),
                      LoadingButton(
                        label: 'Pesquisar',
                        loading: _loading,
                        onPressed: _search,
                        icon: Icons.manage_search_rounded,
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
                    _scanning ? 'Capturando e reconhecendo placa...' : 'Pesquisando passagens...',
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
                      'Placa detectada. Abrindo os resultados da consulta...',
                      style: TextStyle(color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            )
          else
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
                      'Use os filtros no rodapé, informe uma placa e toque em Pesquisar.',
                      style: TextStyle(color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            ),
          if (_capturedImage != null) ...[
            const SizedBox(height: 12),
            _buildImagePreview(),
          ],
        ],
      ),
    );
  }

  // ─── Filtros de pesquisa ─────────────────────────────────────────────────

  Widget _buildFilters() {
    final camLabel = _filterCamera == null
        ? 'Câmera'
        : (_filterCamera!['nome'] as String);
    final hasAny = _filterCamera != null ||
        _filterDirecao != null ||
        _filterCor != null ||
        _filterNome != null ||
        _filterPeriod != null;

    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: _kCard,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: _kBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Cabeçalho
          Row(
            children: [
              const Icon(Icons.filter_list_rounded, color: _kYellow, size: 13),
              const SizedBox(width: 5),
              const Text(
                'FILTROS DE PESQUISA',
                style: TextStyle(
                  color: _kYellow,
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.5,
                ),
              ),
              const Spacer(),
              if (hasAny)
                GestureDetector(
                  onTap: () => setState(() {
                    _filterCamera = null;
                    _filterDirecao = null;
                    _filterCor = null;
                    _filterNome = null;
                    _filterPeriod = null;
                  }),
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
          const SizedBox(height: 6),

          // ── Linha 1: Câmera | Direção ──────────────────────────────────────────
          Row(
            children: [
              Expanded(child: _filterChip(
                icon: _camerasLoading
                    ? Icons.sync_rounded
                    : Icons.videocam_rounded,
                label: camLabel,
                active: _filterCamera != null,
                onTap: _pickCamera,
              )),
              const SizedBox(width: 6),
              Expanded(child: _filterChip(
                icon: Icons.swap_vert_rounded,
                label: _filterDirecao ?? 'Direção',
                active: _filterDirecao != null,
                onTap: _pickDirecao,
              )),
            ],
          ),
          const SizedBox(height: 4),

          // ── Linha 2: Cor | Nome ─────────────────────────────────────────────────
          Row(
            children: [
              Expanded(child: _filterChip(
                icon: Icons.palette_rounded,
                label: _filterCor ?? 'Cor',
                active: _filterCor != null,
                onTap: _pickCor,
              )),
              const SizedBox(width: 6),
              Expanded(child: _filterChip(
                icon: Icons.person_outline_rounded,
                label: _filterNome ?? 'Nome',
                active: _filterNome != null,
                onTap: _pickNome,
              )),
            ],
          ),
          const SizedBox(height: 6),

          // ── Linha 3: Período ───────────────────────────────────────────────────
          _buildPeriodChip(),
        ],
      ),
    );
  }

  Widget _buildPeriodChip() {
    final active = _filterPeriod != null;
    return GestureDetector(
      onTap: () async {
        final res = await PeriodFilterSheet.show(
          context,
          current: _filterPeriod,
        );
        if (res.confirmed && mounted) {
          setState(() => _filterPeriod = res.filter);
        }
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: active ? _kYellow.withValues(alpha: 0.1) : _kBg.withValues(alpha: 0.7),
          borderRadius: BorderRadius.circular(7),
          border: Border.all(
            color: active ? _kYellow.withValues(alpha: 0.6) : _kBorder,
            width: active ? 1.2 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(Icons.schedule_rounded,
                color: active ? _kYellow : _kMuted, size: 13),
            const SizedBox(width: 5),
            Expanded(
              child: Text(
                active ? _filterPeriod!.displayLabel : 'Período',
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: active ? Colors.white : _kMuted,
                  fontSize: 12,
                  fontWeight: active ? FontWeight.w700 : FontWeight.w600,
                ),
              ),
            ),
            Icon(Icons.expand_more_rounded,
                color: active ? _kYellow : _kMuted, size: 13),
          ],
        ),
      ),
    );
  }

  Widget _filterChip({
    required IconData icon,
    required String label,
    required bool active,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: active
              ? _kYellow.withValues(alpha: 0.1)
              : _kBg.withValues(alpha: 0.7),
          borderRadius: BorderRadius.circular(7),
          border: Border.all(
            color: active ? _kYellow.withValues(alpha: 0.6) : _kBorder,
            width: active ? 1.2 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(icon,
                color: active ? _kYellow : _kMuted,
                size: 13),
            const SizedBox(width: 5),
            Expanded(
              child: Text(
                label,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: active ? Colors.white : _kMuted,
                  fontSize: 12,
                  fontWeight: active ? FontWeight.w700 : FontWeight.w600,
                ),
              ),
            ),
            Icon(Icons.expand_more_rounded,
                color: active ? _kYellow : _kMuted,
                size: 13),
          ],
        ),
      ),
    );
  }

  // Pickers ──────────────────────────────────────────────────────────────────

  Future<void> _pickCamera() async {
    if (_camerasLoading) return;
    final picked = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => Dialog(
        backgroundColor: _kCard,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Header
            Container(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: _kBorder)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.videocam_rounded, color: _kYellow, size: 16),
                  const SizedBox(width: 8),
                  const Text('Câmeras',
                      style: TextStyle(
                          color: Colors.white,
                        fontSize: 15,
                          fontWeight: FontWeight.w800)),
                  const Spacer(),
                  GestureDetector(
                    onTap: () => Navigator.pop(context),
                    child: const Icon(Icons.close_rounded,
                        color: _kMuted, size: 18),
                  ),
                ],
              ),
            ),
            // Lista
            ConstrainedBox(
              constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(context).size.height * 0.55),
              child: _cameras.isEmpty
                  ? const Padding(
                      padding: EdgeInsets.all(24),
                      child: Text('Nenhuma câmera encontrada.',
                          style: TextStyle(color: _kMuted, fontSize: 15)),
                    )
                  : ListView(
                      shrinkWrap: true,
                      children: [
                        // Opção: Todas
                        ListTile(
                          dense: true,
                          leading: const Icon(Icons.all_inclusive_rounded,
                              color: _kMuted, size: 18),
                          title: const Text('Todas as câmeras',
                              style:
                                TextStyle(color: _kMuted, fontSize: 15)),
                          onTap: () => Navigator.pop(context, null),
                        ),
                        const Divider(color: _kBorder, height: 1),
                        // Câmeras reais
                        ..._cameras.map((cam) {
                          final nome = cam['nome'] as String;
                          final ativa = cam['ativa'] as bool? ?? true;
                          final crit = cam['criticidade'] as String? ?? '';
                          return ListTile(
                            dense: true,
                            leading: Icon(
                              ativa
                                  ? Icons.videocam_rounded
                                  : Icons.videocam_off_rounded,
                              color: ativa ? _kYellow : _kMuted,
                              size: 18,
                            ),
                            title: Text(nome,
                                style: TextStyle(
                                    color:
                                        ativa ? Colors.white : _kMuted,
                                    fontSize: 14,
                                    fontWeight: FontWeight.w600)),
                            trailing: crit == 'CRITICA'
                                ? Container(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 6, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: _kRed.withValues(alpha: 0.15),
                                      borderRadius:
                                          BorderRadius.circular(4),
                                    ),
                                    child: const Text('CRÍTICA',
                                        style: TextStyle(
                                            color: _kRed,
                                          fontSize: 10,
                                            fontWeight:
                                                FontWeight.w800)))
                                : null,
                            onTap: () => Navigator.pop(context, cam),
                          );
                        }),
                      ],
                    ),
            ),
          ],
        ),
      ),
    );
    // picked == null significa resetar (todas)
    if (picked != null || _filterCamera != null) {
      setState(() => _filterCamera = picked);
    }
  }

  Future<void> _pickDirecao() async {
    const opcoes = ['ENTRADA', 'SAÍDA'];
    final picked = await showDialog<String>(
      context: context,
      builder: (_) => SimpleDialog(
        backgroundColor: _kCard,
        title: const Text('Direção',
            style: TextStyle(
                color: Colors.white,
            fontSize: 16,
                fontWeight: FontWeight.w700)),
        children: [
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, null),
            child: const Text('Todas as direções',
              style: TextStyle(color: _kMuted, fontSize: 15)),
          ),
          ...opcoes.map((o) => SimpleDialogOption(
            onPressed: () => Navigator.pop(context, o),
            child: Row(
              children: [
                Icon(
                  o == 'ENTRADA'
                      ? Icons.arrow_downward_rounded
                      : Icons.arrow_upward_rounded,
                  color: o == 'ENTRADA' ? _kYellow : _kMuted,
                  size: 16,
                ),
                const SizedBox(width: 8),
                Text(o,
                    style: const TextStyle(
                    color: Colors.white, fontSize: 15)),
              ],
            ),
          )),
        ],
      ),
    );
    if (picked != null || _filterDirecao != null) {
      setState(() => _filterDirecao = picked);
    }
  }

  Future<void> _pickCor() async {
    const cores = [
      ('Branca',    Color(0xFFF1F5F9), 'Branca'),
      ('Prata',     Color(0xFFCBD5E1), 'Prata'),
      ('Cinza',     Color(0xFF64748B), 'Cinza'),
      ('Preta',     Color(0xFF1E293B), 'Preta'),
      ('Vermelha',  Color(0xFFEF4444), 'Vermelha'),
      ('Azul',      Color(0xFF3B82F6), 'Azul'),
      ('Verde',     Color(0xFF22C55E), 'Verde'),
      ('Amarela',   Color(0xFFFACC15), 'Amarela'),
      ('Laranja',   Color(0xFFF97316), 'Laranja'),
      ('Marrom',    Color(0xFF92400E), 'Marrom'),
    ];
    final picked = await showDialog<String>(
      context: context,
      builder: (_) => Dialog(
        backgroundColor: _kCard,
        shape:
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.palette_rounded,
                      color: _kYellow, size: 16),
                  const SizedBox(width: 8),
                  const Text('Cor do Veículo',
                      style: TextStyle(
                          color: Colors.white,
                        fontSize: 15,
                          fontWeight: FontWeight.w800)),
                  const Spacer(),
                  GestureDetector(
                    onTap: () => Navigator.pop(context, null),
                    child: const Text('Todas',
                        style: TextStyle(
                            color: _kMuted,
                        fontSize: 15,
                            decoration: TextDecoration.underline,
                            decorationColor: _kMuted)),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: cores.map((c) {
                  final (label, color, _) = c;
                  final sel = _filterCor == label;
                  return GestureDetector(
                    onTap: () => Navigator.pop(context, label),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 150),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 7),
                      decoration: BoxDecoration(
                        color: color.withValues(alpha: sel ? 0.25 : 0.12),
                        borderRadius: BorderRadius.circular(20),
                        border: Border.all(
                          color: sel
                              ? color
                              : color.withValues(alpha: 0.35),
                          width: sel ? 1.5 : 1,
                        ),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            width: 10,
                            height: 10,
                            decoration: BoxDecoration(
                              color: color,
                              shape: BoxShape.circle,
                              border: Border.all(
                                  color: Colors.white24, width: 0.5),
                            ),
                          ),
                          const SizedBox(width: 5),
                          Text(label,
                              style: TextStyle(
                                  color: sel ? Colors.white : _kMuted,
                                fontSize: 15,
                                  fontWeight: sel
                                      ? FontWeight.w700
                                      : FontWeight.normal)),
                        ],
                      ),
                    ),
                  );
                }).toList(),
              ),
            ],
          ),
        ),
      ),
    );
    if (picked != null || _filterCor != null) {
      setState(() => _filterCor = picked);
    }
  }

  Future<void> _pickNome() async {
    final ctrl = TextEditingController(text: _filterNome);
    final picked = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: _kCard,
        shape:
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        title: const Row(
          children: [
            Icon(Icons.person_outline_rounded, color: _kYellow, size: 18),
            SizedBox(width: 8),
            Text('Buscar por Nome',
                style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w700)),
          ],
        ),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          style: const TextStyle(color: Colors.white),
          decoration: InputDecoration(
            hintText: 'Nome do proprietário ou veículo…',
            hintStyle: TextStyle(color: _kMuted.withValues(alpha: 0.6)),
            filled: true,
            fillColor: _kBg,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: const BorderSide(color: _kBorder),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide: const BorderSide(color: _kBorder),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(8),
              borderSide:
                  const BorderSide(color: _kYellow, width: 1.5),
            ),
          ),
          onSubmitted: (v) => Navigator.pop(context, v.trim()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, null),
            child: const Text('Limpar',
                style: TextStyle(color: _kMuted)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: _kYellow,
              foregroundColor: Colors.black,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8)),
            ),
            onPressed: () =>
                Navigator.pop(context, ctrl.text.trim()),
            child: const Text('Aplicar',
                style: TextStyle(fontWeight: FontWeight.w800)),
          ),
        ],
      ),
    );
    if (picked != null || _filterNome != null) {
      setState(() => _filterNome = picked?.isEmpty == true ? null : picked);
    }
  }

  // ─── Campo texto ──────────────────────────────────────────────────────────

  Widget _buildTextField() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'PLACA DO VEÍCULO',
          style: TextStyle(
            color: _kMuted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
            letterSpacing: 2.0,
          ),
        ),
        const SizedBox(height: 4),
        Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: _kYellow.withValues(alpha: 0.4)),
          ),
          clipBehavior: Clip.antiAlias,
          child: PlateSearchField(
            controller: _plateCtrl,
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
                  padding: const EdgeInsets.all(6),
                ),
                IconButton(
                  icon: const Icon(Icons.clear_rounded, color: _kMuted, size: 18),
                  tooltip: 'Limpar',
                  onPressed: () {
                    _plateCtrl.clear();
                    setState(() { _scanResult = null; _capturedImage = null; });
                  },
                  padding: const EdgeInsets.all(6),
                ),
              ],
            ),
          ),
        ),
      ],
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
                  'FOTO CAPTURADA',
                  style: TextStyle(
                    color: _kMuted,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 2,
                  ),
                ),
              ],
            ),
          ),
          Image.file(
            _capturedImage!,
            height: 180,
            fit: BoxFit.cover,
          ),
        ],
      ),
    );
  }
}
