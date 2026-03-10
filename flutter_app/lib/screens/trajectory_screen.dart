import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:intl/intl.dart';

import '../models/camera.dart';
import '../services/api.dart';
import '../services/camera_service.dart';
import '../theme/app_theme.dart';
import '../widgets/plate_search_field.dart';

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
  GoogleMapController? _googleMapController;
  
  DateTime? _startDate;
  DateTime? _endDate;
  
  bool _loading = false;
  String? _errorMsg;
  Map<String, dynamic>? _trajectoryData;
  
  // Câmeras carregadas da API
  List<Camera> _cameras = [];
  bool _loadingCameras = false;
  bool _showCamerasOnMap = true;

  @override
  void initState() {
    super.initState();
    _loadCameras();
  }

  @override
  void dispose() {
    _plateController.dispose();
    _googleMapController?.dispose();
    super.dispose();
  }

  /// Carrega câmeras do backend
  Future<void> _loadCameras() async {
    setState(() => _loadingCameras = true);
    try {
      final response = await CameraService.instance.getCameras(includeInactive: true);
      if (!mounted) return;
      setState(() {
        _cameras = response.withGps;
        _loadingCameras = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loadingCameras = false);
      debugPrint('[TrajectoryScreen] Erro ao carregar câmeras: $e');
    }
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
      _fitTrajectoryOnMap(points: (data['points'] as List?) ?? []);
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
    
    // Retorna mapa para posição padrão (Brasil central)
    _googleMapController?.animateCamera(
      CameraUpdate.newLatLngZoom(
        const LatLng(-15.0, -52.0),
        5.0,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _kBg,
      appBar: AppBar(
        backgroundColor: _kCard,
        elevation: 0,
        title: const Row(
          children: [
            Icon(Icons.map_rounded, color: _kYellow, size: 20),
            SizedBox(width: 8),
            Text(
              'Trajetória de Veículo',
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
          // tab-results
          Expanded(
            child: Column(
              children: [
                Expanded(
                  child: _buildMap(),
                ),
                if (_trajectoryData != null &&
                    (_trajectoryData!['cameras_without_gps'] as List?)?.isNotEmpty ==
                        true)
                  Container(
                    color: Colors.orange.withOpacity(0.12),
                    padding: const EdgeInsets.all(14),
                    child: Row(
                      children: [
                        const Icon(Icons.warning_amber_rounded, color: Colors.orange, size: 18),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            'Câmeras sem GPS: ${(_trajectoryData!['cameras_without_gps'] as List).join(", ")}',
                            style: const TextStyle(color: Colors.orange, fontSize: 12, fontWeight: FontWeight.w600),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
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
                  maxHeight: MediaQuery.of(context).size.height * 0.56,
                ),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      PlateSearchField(
                        controller: _plateController,
                        hintText: 'ABC1234',
                        onSubmitted: _loading ? null : _loadTrajectory,
                      ),
                      const SizedBox(height: 12),
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
                                        color: Colors.black,
                                      ),
                                    )
                                  : const Icon(Icons.search),
                              label: const Text('Buscar'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: _kYellow,
                                foregroundColor: Colors.black,
                                elevation: 0,
                                padding: const EdgeInsets.symmetric(vertical: 14),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                textStyle: const TextStyle(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w700,
                                  letterSpacing: .4,
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
                              backgroundColor: _kCard,
                              foregroundColor: _kMuted,
                              elevation: 0,
                              padding: const EdgeInsets.symmetric(
                                vertical: 14,
                                horizontal: 16,
                              ),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                                side: const BorderSide(color: _kBorder),
                              ),
                              textStyle: const TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w700,
                                letterSpacing: .4,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                        decoration: BoxDecoration(
                          color: _kBg.withOpacity(0.5),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: _kBorder),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.videocam_rounded, color: _kMuted, size: 16),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                'Exibir câmeras no mapa ${_loadingCameras ? "..." : "(${_cameras.length})"}',
                                style: const TextStyle(color: _kMuted, fontSize: 13, fontWeight: FontWeight.w600),
                              ),
                            ),
                            Switch(
                              value: _showCamerasOnMap,
                              onChanged: (value) {
                                setState(() => _showCamerasOnMap = value);
                              },
                              activeColor: _kYellow,
                            ),
                          ],
                        ),
                      ),
                      if (_errorMsg != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 10),
                          child: Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: _kRed.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: _kRed.withOpacity(0.3)),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.error_outline_rounded, color: _kRed, size: 18),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    _errorMsg!,
                                    style: const TextStyle(color: _kRed, fontSize: 13, fontWeight: FontWeight.w600),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      if (_trajectoryData != null) ...[
                        const SizedBox(height: 10),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: _kYellow.withOpacity(0.08),
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: _kYellow.withOpacity(0.3)),
                          ),
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.spaceAround,
                            children: [
                              _InfoChip(
                                icon: Icons.location_on_rounded,
                                label: 'Pontos GPS',
                                value: '${_trajectoryData!['total_points']}',
                              ),
                              _InfoChip(
                                icon: Icons.event_rounded,
                                label: 'Eventos',
                                value: '${_trajectoryData!['total_events']}',
                              ),
                              if ((_trajectoryData!['cameras_without_gps'] as List?)
                                      ?.isNotEmpty ==
                                  true)
                                _InfoChip(
                                  icon: Icons.warning_amber_rounded,
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
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMap() {
    // Coordenadas padrão (Brasil central) quando não houver dados
    const defaultLat = -15.0;
    const defaultLng = -52.0;
    const defaultZoom = 5.0;

    // Processa pontos de trajetória (se houver)
    final points = (_trajectoryData?['points'] as List?) ?? [];
    final validEntries = points.asMap().entries.where((entry) {
      final lat = _toDouble(entry.value['lat']);
      final lng = _toDouble(entry.value['lng']);
      return lat != null && lng != null;
    }).toList();

    // Define posição inicial do mapa
    final LatLng initialPosition;
    final double initialZoom;
    
    if (validEntries.isNotEmpty) {
      final firstPoint = validEntries.first.value;
      initialPosition = LatLng(
        _toDouble(firstPoint['lat'])!,
        _toDouble(firstPoint['lng'])!,
      );
      initialZoom = 10.0;
    } else {
      initialPosition = const LatLng(defaultLat, defaultLng);
      initialZoom = defaultZoom;
    }

    // Cria marcadores de trajetória
    final trajectoryMarkers = <Marker>{
      if (validEntries.isNotEmpty)
        for (var i = 0; i < validEntries.length; i++)
          Marker(
            markerId: MarkerId('pt_${validEntries[i].key}'),
            position: LatLng(
              _toDouble(validEntries[i].value['lat'])!,
              _toDouble(validEntries[i].value['lng'])!,
            ),
            icon: i == 0
                ? BitmapDescriptor.defaultMarkerWithHue(BitmapDescriptor.hueGreen)
                : (i == validEntries.length - 1
                    ? BitmapDescriptor.defaultMarkerWithHue(BitmapDescriptor.hueOrange)
                    : BitmapDescriptor.defaultMarkerWithHue(BitmapDescriptor.hueRed)),
            onTap: () => _showPointDetails(validEntries[i].value, i + 1),
          ),
    };

    // Cria marcadores de câmeras
    final cameraMarkers = <Marker>{
      if (_showCamerasOnMap)
        ...(_cameras.map((camera) {
          return Marker(
            markerId: MarkerId('cam_${camera.cameraId}'),
            position: LatLng(camera.latitude!, camera.longitude!),
            icon: BitmapDescriptor.defaultMarkerWithHue(
              camera.status == 'Online' 
                ? BitmapDescriptor.hueAzure
                : BitmapDescriptor.hueViolet
            ),
            onTap: () => _showCameraDetails(camera),
            infoWindow: InfoWindow(
              title: '📹 ${camera.nome}',
              snippet: camera.status,
            ),
          );
        })),
    };

    // Combina todos os marcadores
    final allMarkers = {...trajectoryMarkers, ...cameraMarkers};

    // Cria polyline se houver pontos
    final Set<Polyline> polylines;
    if (validEntries.isNotEmpty) {
      final polylinePoints = validEntries
          .map((entry) => LatLng(
                _toDouble(entry.value['lat'])!,
                _toDouble(entry.value['lng'])!,
              ))
          .toList();
      
      polylines = {
        Polyline(
          polylineId: const PolylineId('trajectory_line'),
          points: polylinePoints,
          color: _kRed,
          width: 5,
        ),
      };
    } else {
      polylines = {};
    }

    // Determina mensagem informativa (se houver)
    String? infoMessage;
    if (_trajectoryData == null) {
      infoMessage = '📍 Informe a placa e período para buscar a trajetória';
    } else if (validEntries.isEmpty) {
      infoMessage = '⚠️ Nenhum ponto com GPS encontrado para essa busca';
    }

    return Stack(
      children: [
        // Mapa (sempre visível)
        GoogleMap(
          initialCameraPosition: CameraPosition(
            target: initialPosition,
            zoom: initialZoom,
          ),
          onMapCreated: (controller) {
            _googleMapController = controller;
            if (validEntries.isNotEmpty) {
              _fitTrajectoryOnMap(points: points);
            }
          },
          mapType: MapType.hybrid,
          myLocationButtonEnabled: false,
          mapToolbarEnabled: false,
          zoomControlsEnabled: true,
          markers: allMarkers,
          polylines: polylines,
        ),

        // Mensagem informativa (quando não há dados ou pontos)
        if (infoMessage != null)
          Positioned(
            top: 16,
            left: 16,
            right: 16,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: _kCard.withOpacity(0.95),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _kBorder),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.3),
                    blurRadius: 8,
                    offset: const Offset(0, 2),
                  ),
                ],
              ),
              child: Text(
                infoMessage,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: _kMuted,
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ),
      ],
    );
  }

  Future<void> _fitTrajectoryOnMap({required List points}) async {
    final controller = _googleMapController;
    if (controller == null || points.isEmpty) return;

    final valid = points.where((p) {
      final lat = _toDouble(p['lat']);
      final lng = _toDouble(p['lng']);
      return lat != null && lng != null;
    }).toList();
    if (valid.isEmpty) return;

    var minLat = _toDouble(valid.first['lat'])!;
    var maxLat = minLat;
    var minLng = _toDouble(valid.first['lng'])!;
    var maxLng = minLng;

    for (final p in valid.skip(1)) {
      final lat = _toDouble(p['lat'])!;
      final lng = _toDouble(p['lng'])!;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      if (lng < minLng) minLng = lng;
      if (lng > maxLng) maxLng = lng;
    }

    if ((maxLat - minLat).abs() < 0.0001 && (maxLng - minLng).abs() < 0.0001) {
      await controller.animateCamera(
        CameraUpdate.newLatLngZoom(LatLng(minLat, minLng), 15),
      );
      return;
    }

    final bounds = LatLngBounds(
      southwest: LatLng(minLat, minLng),
      northeast: LatLng(maxLat, maxLng),
    );

    await controller.animateCamera(
      CameraUpdate.newLatLngBounds(bounds, 56),
    );
  }

  double? _toDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value);
    return null;
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

  /// Exibe detalhes da câmera ao clicar no marcador
  void _showCameraDetails(Camera camera) {
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
            Row(
              children: [
                const Text(
                  '📹',
                  style: TextStyle(fontSize: 24),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    camera.nome,
                    style: const TextStyle(
                      color: _kYellow,
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              camera.cameraId,
              style: const TextStyle(color: _kMuted, fontSize: 12),
            ),
            const Divider(height: 24, color: _kBorder),
            
            _DetailRow(
              icon: Icons.router,
              label: 'IP',
              value: camera.ip ?? '—',
            ),
            _DetailRow(
              icon: Icons.circle,
              label: 'Status',
              value: camera.status,
            ),
            if (camera.direcao != null)
              _DetailRow(
                icon: Icons.navigation,
                label: 'Direção',
                value: camera.direcao!,
              ),
            _DetailRow(
              icon: Icons.warning_amber,
              label: 'Criticidade',
              value: camera.criticidade,
            ),
            const Divider(height: 20, color: _kBorder),
            _DetailRow(
              icon: Icons.event,
              label: 'Eventos Hoje',
              value: camera.eventsToday.toString(),
            ),
            _DetailRow(
              icon: Icons.analytics,
              label: 'Total de Eventos',
              value: camera.totalEvents.toString(),
            ),
            if (camera.lastSeen != null) ...[
              const Divider(height: 20, color: _kBorder),
              _DetailRow(
                icon: Icons.access_time,
                label: 'Última Comunicação',
                value: _formatDateTime(camera.lastSeen!),
              ),
            ],
            const Divider(height: 20, color: _kBorder),
            Text(
              '📍 ${camera.latitude?.toStringAsFixed(6)}, ${camera.longitude?.toStringAsFixed(6)}',
              style: const TextStyle(
                color: _kMuted,
                fontSize: 11,
                fontFamily: 'monospace',
              ),
            ),
          ],
        ),
      ),
    );
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
