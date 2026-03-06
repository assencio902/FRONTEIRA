import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';

import '../services/api.dart';
import '../theme/app_theme.dart';

const _kBg = AppColors.background;
const _kCard = AppColors.surface;
const _kBorder = AppColors.border;
const _kYellow = AppColors.warning;
const _kRed = AppColors.danger;
const _kGreen = AppColors.success;
const _kMuted = AppColors.muted;

class TrajectoryScreen extends StatefulWidget {
  const TrajectoryScreen({super.key});

  @override
  State<TrajectoryScreen> createState() => _TrajectoryScreenState();
}

class _TrajectoryScreenState extends State<TrajectoryScreen> {
  final _plateController = TextEditingController();
  final _mapController = MapController();
  
  DateTime? _startDate;
  DateTime? _endDate;
  
  bool _loading = false;
  String? _errorMsg;
  Map<String, dynamic>? _trajectoryData;

  @override
  void dispose() {
    _plateController.dispose();
    _mapController.dispose();
    super.dispose();
  }

  Future<void> _selectStartDate() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _startDate ?? DateTime.now().subtract(const Duration(days: 1)),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: const ColorScheme.dark(
              primary: _kYellow,
              onSurface: Colors.white,
            ),
          ),
          child: child!,
        );
      },
    );
    if (date == null) return;

    if (!mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_startDate ?? DateTime.now()),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: const ColorScheme.dark(
              primary: _kYellow,
              onSurface: Colors.white,
            ),
          ),
          child: child!,
        );
      },
    );
    if (time == null) return;

    setState(() {
      _startDate = DateTime(date.year, date.month, date.day, time.hour, time.minute);
    });
  }

  Future<void> _selectEndDate() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _endDate ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: const ColorScheme.dark(
              primary: _kYellow,
              onSurface: Colors.white,
            ),
          ),
          child: child!,
        );
      },
    );
    if (date == null) return;

    if (!mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_endDate ?? DateTime.now()),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: const ColorScheme.dark(
              primary: _kYellow,
              onSurface: Colors.white,
            ),
          ),
          child: child!,
        );
      },
    );
    if (time == null) return;

    setState(() {
      _endDate = DateTime(date.year, date.month, date.day, time.hour, time.minute);
    });
  }

  Future<void> _loadTrajectory() async {
    final plate = _plateController.text.trim().toUpperCase();
    if (plate.isEmpty) {
      setState(() => _errorMsg = 'Informe a placa');
      return;
    }
    if (_startDate == null || _endDate == null) {
      setState(() => _errorMsg = 'Informe período de busca');
      return;
    }

    setState(() {
      _loading = true;
      _errorMsg = null;
      _trajectoryData = null;
    });

    try {
      final start = _startDate!.toIso8601String();
      final end = _endDate!.toIso8601String();
      
      final data = await Api.getVehicleTrajectory(plate, start, end);
      
      if (!mounted) return;
      setState(() {
        _trajectoryData = data;
        _loading = false;
      });

      // Auto-zoom para os pontos
      final points = (data['points'] as List?) ?? [];
      if (points.isNotEmpty) {
        final bounds = LatLngBounds.fromPoints(
          points.map((p) => LatLng(p['lat'], p['lng'])).toList(),
        );
        _mapController.fitCamera(
          CameraFit.bounds(
            bounds: bounds,
            padding: const EdgeInsets.all(50),
            maxZoom: 14,
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMsg = e.toString();
        _loading = false;
      });
    }
  }

  void _clearTrajectory() {
    setState(() {
      _plateController.clear();
      _startDate = null;
      _endDate = null;
      _trajectoryData = null;
      _errorMsg = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _kBg,
      appBar: AppBar(
        backgroundColor: _kCard,
        elevation: 0,
        title: const Text(
          '🗺️ Trajetória de Veículo',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
        ),
      ),
      body: Column(
        children: [
          // Painel de busca
          Container(
            color: _kCard,
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Campo de placa
                TextField(
                  controller: _plateController,
                  maxLength: 7,
                  textCapitalization: TextCapitalization.characters,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                    letterSpacing: 1.2,
                  ),
                  decoration: InputDecoration(
                    labelText: 'Placa *',
                    hintText: 'ABC1234',
                    counterText: '',
                    filled: true,
                    fillColor: const Color(0xFF0a3820),
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
                      borderSide: const BorderSide(color: _kYellow, width: 2),
                    ),
                  ),
                ),
                const SizedBox(height: 12),

                // Período
                Row(
                  children: [
                    Expanded(
                      child: _DateButton(
                        label: 'Início',
                        date: _startDate,
                        onTap: _selectStartDate,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _DateButton(
                        label: 'Fim',
                        date: _endDate,
                        onTap: _selectEndDate,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),

                // Botões
                Row(
                  children: [
                    Expanded(
                      child: ElevatedButton.icon(
                        onPressed: _loading ? null : _loadTrajectory,
                        icon: _loading
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Icon(Icons.search),
                        label: const Text('Buscar'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: _kYellow,
                          foregroundColor: Colors.black,
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(8),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    ElevatedButton.icon(
                      onPressed: _clearTrajectory,
                      icon: const Icon(Icons.clear),
                      label: const Text('Limpar'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: _kBorder,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(
                          vertical: 14,
                          horizontal: 16,
                        ),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                    ),
                  ],
                ),

                // Mensagem de erro
                if (_errorMsg != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '⚠️ $_errorMsg',
                      style: const TextStyle(color: _kRed, fontSize: 12),
                    ),
                  ),

                // Info da trajetória
                if (_trajectoryData != null) ...[
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFF0a3820),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: _kYellow.withOpacity(0.3)),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceAround,
                      children: [
                        _InfoChip(
                          icon: Icons.location_on,
                          label: 'Pontos GPS',
                          value: '${_trajectoryData!['total_points']}',
                        ),
                        _InfoChip(
                          icon: Icons.event,
                          label: 'Eventos',
                          value: '${_trajectoryData!['total_events']}',
                        ),
                        if ((_trajectoryData!['cameras_without_gps'] as List?)
                                ?.isNotEmpty ==
                            true)
                          _InfoChip(
                            icon: Icons.warning_amber,
                            label: 'Sem GPS',
                            value:
                                '${(_trajectoryData!['cameras_without_gps'] as List).length}',
                            color: Colors.orange,
                          ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),

          // Mapa
          Expanded(
            child: _trajectoryData == null
                ? const Center(
                    child: Text(
                      '📍 Informe a placa e período\npara buscar a trajetória',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: _kMuted, fontSize: 14),
                    ),
                  )
                : _buildMap(),
          ),

          // Câmeras sem GPS
          if (_trajectoryData != null &&
              (_trajectoryData!['cameras_without_gps'] as List?)?.isNotEmpty ==
                  true)
            Container(
              color: Colors.orange.withOpacity(0.1),
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  const Icon(Icons.warning_amber, color: Colors.orange, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Câmeras sem GPS: ${(_trajectoryData!['cameras_without_gps'] as List).join(', ')}',
                      style: const TextStyle(color: Colors.orange, fontSize: 11),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildMap() {
    final points = (_trajectoryData!['points'] as List?) ?? [];
    if (points.isEmpty) {
      return const Center(
        child: Text(
          '⚠️ Nenhum ponto com GPS encontrado',
          style: TextStyle(color: _kRed, fontSize: 14),
        ),
      );
    }

    final latLngs = points.map((p) => LatLng(p['lat'], p['lng'])).toList();

    return FlutterMap(
      mapController: _mapController,
      options: MapOptions(
        initialCenter: latLngs.first,
        initialZoom: 10,
        minZoom: 5,
        maxZoom: 18,
      ),
      children: [
        TileLayer(
          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          userAgentPackageName: 'com.bpfron.monitoramento',
        ),
        
        // Polyline da rota
        PolylineLayer(
          polylines: [
            Polyline(
              points: latLngs,
              color: _kRed,
              strokeWidth: 4,
            ),
          ],
        ),

        // Marcadores numerados
        MarkerLayer(
          markers: points.asMap().entries.map((entry) {
            final idx = entry.key;
            final point = entry.value;
            final position = LatLng(point['lat'], point['lng']);

            return Marker(
              point: position,
              width: 30,
              height: 30,
              child: GestureDetector(
                onTap: () => _showPointDetails(point, idx + 1),
                child: Container(
                  decoration: BoxDecoration(
                    color: _kRed,
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white, width: 2),
                    boxShadow: const [
                      BoxShadow(
                        color: Colors.black45,
                        blurRadius: 4,
                        offset: Offset(0, 2),
                      ),
                    ],
                  ),
                  child: Center(
                    child: Text(
                      '${idx + 1}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 11,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                ),
              ),
            );
          }).toList(),
        ),

        // Marcador de início
        MarkerLayer(
          markers: [
            Marker(
              point: latLngs.first,
              width: 80,
              height: 30,
              child: Container(
                decoration: BoxDecoration(
                  color: _kGreen,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: Colors.white, width: 2),
                ),
                child: const Center(
                  child: Text(
                    '▶ INÍCIO',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 9,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),

        // Marcador de fim
        if (latLngs.length > 1)
          MarkerLayer(
            markers: [
              Marker(
                point: latLngs.last,
                width: 70,
                height: 30,
                child: Container(
                  decoration: BoxDecoration(
                    color: _kRed,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.white, width: 2),
                  ),
                  child: const Center(
                    child: Text(
                      '■ FIM',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 9,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
      ],
    );
  }

  void _showPointDetails(Map<String, dynamic> point, int index) {
    final totalPoints = (_trajectoryData!['points'] as List).length;
    final timestamp = point['ts'] as String?;
    final camera = point['camera_name'] as String? ?? point['camera_id'];
    final direction = point['direction'] as String?;
    final confidence = point['confidence'] as num?;

    showModalBottomSheet(
      context: context,
      backgroundColor: _kCard,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => Container(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _trajectoryData!['plate'].toString().toUpperCase(),
              style: const TextStyle(
                color: _kYellow,
                fontSize: 20,
                fontWeight: FontWeight.w900,
                letterSpacing: 1.2,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Passagem #$index de $totalPoints',
              style: const TextStyle(color: _kMuted, fontSize: 12),
            ),
            const Divider(height: 24, color: _kBorder),
            _DetailRow(icon: Icons.videocam, label: 'Câmera', value: camera ?? '—'),
            if (direction != null)
              _DetailRow(icon: Icons.navigation, label: 'Direção', value: direction),
            if (timestamp != null)
              _DetailRow(
                icon: Icons.access_time,
                label: 'Data/Hora',
                value: _formatDateTime(timestamp),
              ),
            if (confidence != null)
              _DetailRow(
                icon: Icons.percent,
                label: 'Confiança',
                value: '${(confidence * 100).toStringAsFixed(0)}%',
              ),
          ],
        ),
      ),
    );
  }

  String _formatDateTime(String isoString) {
    try {
      final dt = DateTime.parse(isoString);
      return DateFormat('dd/MM/yyyy HH:mm:ss').format(dt);
    } catch (e) {
      return isoString;
    }
  }
}

// ─── Widgets auxiliares ───────────────────────────────────────────────────────

class _DateButton extends StatelessWidget {
  final String label;
  final DateTime? date;
  final VoidCallback onTap;

  const _DateButton({
    required this.label,
    required this.date,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFF0a3820),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: _kBorder),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: const TextStyle(color: _kMuted, fontSize: 11),
            ),
            const SizedBox(height: 4),
            Text(
              date == null
                  ? 'Selecionar'
                  : DateFormat('dd/MM/yyyy HH:mm').format(date!),
              style: TextStyle(
                color: date == null ? _kMuted : Colors.white,
                fontSize: 13,
                fontWeight: date == null ? FontWeight.normal : FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color? color;

  const _InfoChip({
    required this.icon,
    required this.label,
    required this.value,
    this.color,
  });

  @override
  Widget build(BuildContext context) {
    final chipColor = color ?? _kYellow;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: chipColor, size: 16),
        const SizedBox(height: 2),
        Text(
          value,
          style: TextStyle(
            color: chipColor,
            fontSize: 14,
            fontWeight: FontWeight.w900,
          ),
        ),
        Text(
          label,
          style: const TextStyle(
            color: _kMuted,
            fontSize: 9,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _DetailRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _DetailRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Icon(icon, size: 16, color: _kMuted),
          const SizedBox(width: 8),
          Text(
            '$label: ',
            style: const TextStyle(color: _kMuted, fontSize: 13),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
