import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../services/api.dart';
import '../services/auth_service.dart';
import '../services/auth_storage.dart';
import '../theme/app_theme.dart';
import 'login_screen.dart';

// ─── Paleta ───────────────────────────────────────────────────────────────────
const _kBg     = AppColors.background;
const _kCard   = AppColors.surface;
const _kBorder = AppColors.border;
const _kYellow = AppColors.warning;
const _kGreen  = AppColors.success;
const _kRed    = AppColors.danger;
const _kMuted  = AppColors.muted;

class EventDetailScreen extends StatefulWidget {
  final int eventId;
  
  const EventDetailScreen({super.key, required this.eventId});

  @override
  State<EventDetailScreen> createState() => _EventDetailScreenState();
}

class _EventDetailScreenState extends State<EventDetailScreen> {
  bool _loading = true;
  String? _error;
  Map<String, dynamic>? _event;

  @override
  void initState() {
    super.initState();
    _loadEventDetail();
  }

  Future<void> _loadEventDetail() async {
    final tokenExpired = await AuthStorage.isTokenExpired();
    if (tokenExpired) {
      final restored = await AuthService.instance.refreshToken();
      if (!restored) {
        await _handleSessionExpiredForced();
        return;
      }
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final data = await Api.getEventDetail(widget.eventId);
      if (!mounted) return;
      setState(() {
        _event = data;
        _loading = false;
      });
    } on ApiUnauthorizedException {
      final restored = await AuthService.instance.refreshToken();
      if (restored) {
        _loadEventDetail();
      } else {
        await _handleSessionExpiredForced();
      }
    } on TimeoutException {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'A API demorou para responder. Tente novamente.';
      });
    } on SocketException {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Sem conexão com a API. Verifique internet/servidor.';
      });
    } catch (e) {
      debugPrint('Error loading event detail: $e');
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Falha ao carregar detalhe do evento.';
      });
    }
  }

  Future<void> _handleSessionExpiredForced() async {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Sessão expirada. Faça login novamente.'),
        backgroundColor: Colors.orange,
      ),
    );
    await AuthStorage.clear();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  String _formatTimestamp(String? iso) {
    if (iso == null) return '—';
    try {
      final dt = DateTime.parse(iso).toLocal();
      final d = '${dt.day.toString().padLeft(2, '0')}/${dt.month.toString().padLeft(2, '0')}/${dt.year}';
      final t = '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}:${dt.second.toString().padLeft(2, '0')}';
      return '$d às $t';
    } catch (_) {
      return iso;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _kBg,
      appBar: AppBar(
        backgroundColor: _kBg,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Text(
          'Detalhe do Evento #${widget.eventId}',
          style: const TextStyle(
            color: Colors.white,
            fontSize: 16,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      body: _loading
          ? const Center(
              child: CircularProgressIndicator(
                color: _kYellow,
                strokeWidth: 2,
              ),
            )
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.error_outline_rounded,
                            color: _kRed, size: 48),
                        const SizedBox(height: 16),
                        Text(
                          _error!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: _kMuted,
                            fontSize: 14,
                          ),
                        ),
                        const SizedBox(height: 20),
                        ElevatedButton.icon(
                          onPressed: _loadEventDetail,
                          icon: const Icon(Icons.refresh_rounded),
                          label: const Text('Tentar novamente'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _kYellow,
                            foregroundColor: Colors.black,
                          ),
                        ),
                      ],
                    ),
                  ),
                )
              : _event == null
                  ? const Center(
                      child: Text(
                        'Evento não encontrado',
                        style: TextStyle(color: _kMuted, fontSize: 14),
                      ),
                    )
                  : _buildContent(),
    );
  }

  Widget _buildContent() {
    final event = _event!;
    final plate = (event['plate'] as String? ?? '?????').toUpperCase();
    final camera = event['cam_nome'] as String? ?? 
                   event['camera'] as String? ?? 
                   event['channel_name'] as String? ?? '—';
    final timestamp = event['occurred_at'] as String? ?? 
                      event['timestamp'] as String? ?? 
                      event['when_ts'] as String?;
    final confidence = (event['confidence'] as num?)?.toDouble();
    final confStr = confidence != null ? '${confidence.toStringAsFixed(1)}%' : '—';
    final confColor = confidence == null
        ? _kMuted
        : confidence >= 85
            ? _kGreen
            : confidence >= 65
                ? _kYellow
                : _kRed;
    final direcao = event['direcao'] as String?;
    final cameraId = event['camera_id'] as String? ?? '—';
    final cameraIp = event['camera_ip'] as String?;
    final imagePath = event['image_path'] as String? ?? 
                      event['image'] as String? ?? 
                      event['thumb'] as String?;
    
    // Vehicle details (YOLO)
    final vehicleDetails = event['vehicle_details'] as Map<String, dynamic>?;
    final vehicleType = vehicleDetails?['type'] as String?;
    final vehicleColor = vehicleDetails?['color'] as String?;
    final vehicleBrand = vehicleDetails?['brand'] as String?;
    final vehicleModel = vehicleDetails?['model'] as String?;
    
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Imagem do evento
          if (imagePath != null && imagePath.isNotEmpty)
            Container(
              height: 250,
              decoration: BoxDecoration(
                color: _kCard,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _kBorder),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.network(
                  '${Api.baseUrl}$imagePath',
                  fit: BoxFit.contain,
                  errorBuilder: (_, __, ___) => const Center(
                    child: Icon(Icons.broken_image_rounded,
                        color: _kMuted, size: 48),
                  ),
                  loadingBuilder: (context, child, progress) {
                    if (progress == null) return child;
                    return const Center(
                      child: CircularProgressIndicator(
                        color: _kYellow,
                        strokeWidth: 2,
                      ),
                    );
                  },
                ),
              ),
            ),
          
          const SizedBox(height: 16),
          
          // Placa e Confiança
          _buildInfoCard(
            title: 'IDENTIFICAÇÃO',
            items: [
              _InfoRow(label: 'Placa', value: plate, highlight: true),
              _InfoRow(label: 'Confiança', value: confStr, valueColor: confColor),
              if (direcao != null && direcao.isNotEmpty)
                _InfoRow(label: 'Direção', value: direcao),
            ],
          ),
          
          const SizedBox(height: 12),
          
          // Câmera
          _buildInfoCard(
            title: 'CÂMERA',
            items: [
              _InfoRow(label: 'Nome', value: camera),
              _InfoRow(label: 'ID', value: cameraId),
              if (cameraIp != null && cameraIp.isNotEmpty)
                _InfoRow(label: 'IP', value: cameraIp),
            ],
          ),
          
          const SizedBox(height: 12),
          
          // Data/Hora
          _buildInfoCard(
            title: 'DATA E HORA',
            items: [
              _InfoRow(label: 'Ocorrido em', value: _formatTimestamp(timestamp)),
            ],
          ),
          
          // Vehicle Details (se disponível)
          if (vehicleDetails != null && vehicleDetails.isNotEmpty) ...[
            const SizedBox(height: 12),
            _buildInfoCard(
              title: 'DETALHES DO VEÍCULO',
              items: [
                if (vehicleType != null)
                  _InfoRow(label: 'Tipo', value: vehicleType),
                if (vehicleColor != null)
                  _InfoRow(label: 'Cor', value: vehicleColor),
                if (vehicleBrand != null)
                  _InfoRow(label: 'Marca', value: vehicleBrand),
                if (vehicleModel != null)
                  _InfoRow(label: 'Modelo', value: vehicleModel),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildInfoCard({required String title, required List<Widget> items}) {
    return Container(
      decoration: BoxDecoration(
        color: _kCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _kBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: _kBorder)),
            ),
            child: Text(
              title,
              style: const TextStyle(
                color: _kYellow,
                fontSize: 12,
                fontWeight: FontWeight.w800,
                letterSpacing: 2,
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              children: items,
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;
  final bool highlight;

  const _InfoRow({
    required this.label,
    required this.value,
    this.valueColor,
    this.highlight = false,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 100,
            child: Text(
              label,
              style: const TextStyle(
                color: _kMuted,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                color: valueColor ?? Colors.white,
                fontSize: highlight ? 18 : 13,
                fontWeight: highlight ? FontWeight.w900 : FontWeight.w600,
                letterSpacing: highlight ? 2 : 0,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
