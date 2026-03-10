import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/alert.dart';
import '../screens/alert_detail_screen.dart';
import '../screens/alert_modal.dart';
import '../screens/event_detail_screen.dart';
import '../services/alarm_service.dart';
import '../services/alarm_history_service.dart';
import '../services/api.dart';
import '../services/auth_storage.dart';
import '../services/notification_service.dart';
import '../services/watchlist_service.dart';
import '../services/websocket_service.dart';
import '../theme/app_theme.dart';
import '../widgets/alarm_overlay.dart';
import '../widgets/plate_search_field.dart';
import 'alarm_history_screen.dart';
import 'login_screen.dart';
import 'search_screen.dart';
import 'trajectory_screen.dart';
import 'watchlist_screen.dart';

// ─── Paleta ───────────────────────────────────────────────────────────────────
const _kBg     = AppColors.background;
const _kCard   = AppColors.surface;
const _kBg2    = Color.fromARGB(255, 15, 54, 34); // verde intermediário para inputs
const _kBorder = AppColors.border;
const _kYellow = AppColors.warning;
const _kGreen  = AppColors.success;
const _kRed    = AppColors.danger;
const _kMuted  = AppColors.muted;

enum _AlertsPeriod { h12, h24, d7, d15, d30 }

extension _AlertsPeriodExt on _AlertsPeriod {
  String get label {
    switch (this) {
      case _AlertsPeriod.h12:
        return '12h';
      case _AlertsPeriod.h24:
        return '24h';
      case _AlertsPeriod.d7:
        return '7d';
      case _AlertsPeriod.d15:
        return '15d';
      case _AlertsPeriod.d30:
        return '30d';
    }
  }

  Duration get window {
    switch (this) {
      case _AlertsPeriod.h12:
        return const Duration(hours: 12);
      case _AlertsPeriod.h24:
        return const Duration(hours: 24);
      case _AlertsPeriod.d7:
        return const Duration(days: 7);
      case _AlertsPeriod.d15:
        return const Duration(days: 15);
      case _AlertsPeriod.d30:
        return const Duration(days: 30);
    }
  }
}


// ─── Widget auxiliar: MetricBadge ─────────────────────────────────────────────
class _MetricBadge extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  const _MetricBadge({
    required this.icon,
    required this.label,
    required this.value,
    this.color = _kYellow,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: color, size: 18),
        const SizedBox(height: 4),
        Text(value,
            style: TextStyle(
              color: color,
              fontSize: 14,
              fontWeight: FontWeight.w900,
            )),
        const SizedBox(height: 2),
        Text(label,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: _kMuted,
              fontSize: 13,
              fontWeight: FontWeight.w600,
              height: 1.2,
            )),
      ],
    );
  }
}


class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  int _tab = 0;
  late Timer _clock;
  Timer? _refreshTimer;
  DateTime _now = DateTime.now();

  // ── Dados da API ──────────────────────────────────────────────────────────
  Map<String, dynamic>? _stats;
  List<Map<String, dynamic>> _events = [];
  bool _loadingDash = false;
  String? _dashboardError;
  _AlertsPeriod _alertsPeriod = _AlertsPeriod.h24;
  
  // ── Dados da Central de Ameaças ───────────────────────────────────────────
  List<Map<String, dynamic>> _gruposComboio = [];
  List<Map<String, dynamic>> _centralResults = [];
  bool _loadingGroups = false;
  String _gruposWindow = '2h';
  String _gruposGroupSizes = '2,3';      // "2", "3", "2,3"
  int _gruposMinCameras = 2;             // 1-5
  String _gruposOrderMode = 'any';       // "any", "leader_front"
  int _gruposCoWindow = 300;             // segundos
  double _gruposLeaderRatio = 0.70;      // 0.5-1.0
  int _gruposPayloadMaxFront = 0;        // 0-5
  String _gruposPlate = '';              // filtro por placa
  final TextEditingController _gruposPlateController = TextEditingController();

  // ── WebSocket e Alarmes ───────────────────────────────────────────────────
  final _watchlistService = WatchlistService();
  final _alarmService = AlarmService();
  final _wsService = WebSocketService();
  StreamSubscription<Map<String, dynamic>>? _wsSubscription;
  bool _wsConnected = false;

  @override
  void initState() {
    super.initState();
    _clock = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _now = DateTime.now());
    });
    _loadDashboard();
    // Garante registro do token FCM no backend após sessão ativa.
    NotificationService().syncTokenWithBackend();
    // Atualiza a cada 30 segundos
    _refreshTimer = Timer.periodic(
        const Duration(seconds: 30), (_) => _loadDashboard());
    
    // ── Inicializar WebSocket e Watchlist ──────────────────────────────────
    _initializeWebSocketAndWatchlist();
    
    // ── Configurar callback para alertas críticos ──────────────────────────
    NotificationService().onAlertReceived = (AlertModel alert) {
      if (mounted) {
        // Mostrar modal de alerta
        AlertModal.show(context, alert);
      }
    };
    NotificationService().onAlertOpened = (AlertModel alert) {
      if (mounted) {
        _openAlertDetail(alert);
      }
    };

    final pending = NotificationService().consumePendingOpenedAlert();
    if (pending != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _openAlertDetail(pending);
        }
      });
    }
  }

  void _openAlertDetail(AlertModel alert) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => AlertDetailScreen(alert: alert),
      ),
    );
  }

  Future<void> _initializeWebSocketAndWatchlist() async {
    // Carregar watchlist do armazenamento local
    await _watchlistService.init();
    
    // Inicializar histórico de alarmes
    final historyService = AlarmHistoryService();
    await historyService.init();
    
    // Conectar ao WebSocket
    await _wsService.connect();
    
    // Escutar eventos em tempo real
    _wsSubscription = _wsService.eventStream.listen(
      (event) => _handleRealtimeEvent(event),
      onError: (error) {
        debugPrint('❌ Erro no WebSocket: $error');
      },
    );
    
    if (mounted) {
      setState(() => _wsConnected = _wsService.isConnected);
    }
  }

  /// Processar evento em tempo real do WebSocket
  void _handleRealtimeEvent(Map<String, dynamic> event) {
    final plate = (event['plate'] as String?)?.toUpperCase() ?? '';
    final camera = event['camera'] ?? event['camera_name'] ?? event['channel_name'] ?? 'Câmera desconhecida';
    final confidenceStr = (event['confidence'] as num?)?.toStringAsFixed(1) ?? '0.0';
    final confidenceValue = double.tryParse(confidenceStr) ?? 0.0;
    final imagePath = event['image_path'] ?? event['image'] ?? '';
    final vehicleType = event['vehicle_type'] as String?;
    
    debugPrint('📨 Evento recebido: $plate em $camera');

    // Verificar se a placa está na watchlist
    if (_watchlistService.isInWatchlist(plate)) {
      debugPrint('🚨 ⚠️ ALERTA: Veículo monitorado detectado - $plate');
      
      // Disparar alarme com dados completos
      _alarmService.triggerAlarm(
        plate: plate,
        camera: camera.toString(),
        confidence: confidenceValue,
        imageUrl: imagePath.toString(),
        vehicleType: vehicleType,
      );
      
      // Mostrar overlay de alarme
      if (mounted) {
        showDialog(
          context: context,
          barrierDismissible: false,
          builder: (ctx) => AlarmOverlay(
            plate: plate,
            camera: camera.toString(),
            confidence: confidenceStr,
            imagePath: imagePath.toString(),
            onDismiss: () => Navigator.of(ctx).pop(),
          ),
        );
      }
    }
  }

  Future<void> _loadDashboard() async {
    if (_loadingDash) return;

    final tokenExpired = await AuthStorage.isTokenExpired();
    if (tokenExpired) {
      await _handleSessionExpired();
      return;
    }

    setState(() {
      _loadingDash = true;
      _dashboardError = null;
    });

    try {
      final results = await Future.wait([
        Api.getStats(),
        Api.getRecentEvents(limit: 15),
      ]);
      if (!mounted) return;
      setState(() {
        _stats  = results[0] as Map<String, dynamic>;
        _events = (results[1] as List).cast<Map<String, dynamic>>();
      });
    } on ApiUnauthorizedException {
      await _handleSessionExpired();
    } on TimeoutException {
      if (!mounted) return;
      setState(() => _dashboardError =
          'A API demorou para responder. Verifique a conexão e tente novamente.');
    } on SocketException {
      if (!mounted) return;
      setState(() => _dashboardError =
          'Sem conexão com a API. Verifique internet/servidor.');
    } catch (e) {
      debugPrint('Dashboard load error: $e');
      if (!mounted) return;
      setState(() => _dashboardError =
          'Falha ao carregar dashboard/eventos. Tente novamente.');
    } finally {
      if (mounted) setState(() => _loadingDash = false);
    }
  }

  Future<void> _handleSessionExpired() async {
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

  Future<void> _loadGruposComboio() async {
    if (_loadingGroups) return;
    setState(() {
      _loadingGroups = true;
      _centralResults = [];
    });
    try {
      // Se houver uma placa específica, busca na Central (com parceiros)
      if (_gruposPlate.isNotEmpty) {
        final result = await Api.getBatedorCentral(
          plate: _gruposPlate,
          limit: 100,
        );
        if (!mounted) return;
        final items = (result['items'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        setState(() {
          _centralResults = items;
          _gruposComboio = [];
        });
      } else {
        // Se não houver placa, busca grupos/comboios normalmente
        final result = await Api.getGruposComboio(
          window: _gruposWindow,
          coWindow: _gruposCoWindow,
          groupSizes: _gruposGroupSizes,
          minCameras: _gruposMinCameras,
          orderMode: _gruposOrderMode,
          leaderRatio: _gruposLeaderRatio,
          maxFrontRatioOther: 0.3,
          payloadMaxFront: _gruposPayloadMaxFront,
          plate: _gruposPlate,
          limit: 100,
        );
        if (!mounted) return;
        final grupos = (result['groups'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        setState(() {
          _gruposComboio = grupos;
          _centralResults = [];
        });
      }
    } catch (e) {
      debugPrint('Grupos comboio load error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Erro ao carregar dados: $e'), backgroundColor: _kRed),
        );
      }
    } finally {
      if (mounted) setState(() => _loadingGroups = false);
    }
  }

  @override
  void dispose() {
    NotificationService().onAlertReceived = null;
    NotificationService().onAlertOpened = null;
    _clock.cancel();
    _refreshTimer?.cancel();
    _wsSubscription?.cancel();
    _wsService.disconnect();
    _alarmService.dispose();
    _gruposPlateController.dispose();
    super.dispose();
  }

  String get _timeStr =>
      '${_now.hour.toString().padLeft(2, '0')}:${_now.minute.toString().padLeft(2, '0')}';
  String get _dateStr =>
      '${_now.day.toString().padLeft(2, '0')}/${_now.month.toString().padLeft(2, '0')}/${_now.year}';

  Future<void> _logout() async {
    await AuthStorage.clear();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _kBg,
      drawer: _buildDrawer(),
      body: IndexedStack(
        index: _tab,
        children: [
          _buildHome(),
          _buildAlarmeTab(),
          const SearchScreen(),
          _buildCentralAmeacasTab(),
          const TrajectoryScreen(),
        ],
      ),
      bottomNavigationBar: _buildBottomNav(),
    );
  }

  /// Menu lateral (Drawer)
  Widget _buildDrawer() {
    return Drawer(
      backgroundColor: _kCard,
      child: ListView(
        padding: EdgeInsets.zero,
        children: [
          // Header
          DrawerHeader(
            decoration: const BoxDecoration(
              color: _kYellow,
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [
                Icon(Icons.security_rounded, size: 40, color: _kBg),
                SizedBox(height: 8),
                Text(
                  'BPFRON Monitoramento',
                  style: TextStyle(
                    color: _kBg,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Text(
                  'LPR - Monitoramento de Veículos',
                  style: TextStyle(
                    color: _kBg,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ),

          // Home
          ListTile(
            leading: const Icon(Icons.home, color: _kYellow),
            title: const Text('Home', style: TextStyle(color: Colors.white)),
            onTap: () {
              Navigator.pop(context); // Fechar drawer
              setState(() => _tab = 0);
            },
          ),

          // Pesquisa
          ListTile(
            leading: const Icon(Icons.search, color: _kYellow),
            title: const Text('Pesquisa', style: TextStyle(color: Colors.white)),
            onTap: () {
              Navigator.pop(context);
              setState(() => _tab = 2);
            },
          ),

          // Mapas
          ListTile(
            leading: const Icon(Icons.map, color: _kYellow),
            title: const Text('Mapas & Rotas', style: TextStyle(color: Colors.white)),
            onTap: () {
              Navigator.pop(context);
              setState(() => _tab = 4);
            },
          ),

          // Watchlist (NOVO)
          ListTile(
            leading: const Icon(Icons.warning_amber_rounded, color: _kRed),
            title: const Text('⚠️ Watchlist', style: TextStyle(color: _kRed)),
            subtitle: const Text(
              'Monitorar Veículos',
              style: TextStyle(color: _kMuted, fontSize: 13),
            ),
            onTap: () {
              Navigator.pop(context); // Fechar drawer
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => const WatchlistScreen(),
                ),
              );
            },
          ),

          // Histórico de Alarmes (NOVO)
          ListTile(
            leading: const Icon(Icons.history, color: Colors.cyan),
            title: const Text('📊 Histórico de Alarmes', style: TextStyle(color: Colors.cyan)),
            subtitle: const Text(
              'Filtrar por período',
              style: TextStyle(color: _kMuted, fontSize: 13),
            ),
            onTap: () {
              Navigator.pop(context); // Fechar drawer
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => const AlarmHistoryScreen(),
                ),
              );
            },
          ),

          // Trajetória de Veículo (NOVO)
          ListTile(
            leading: const Icon(Icons.map, color: Colors.green),
            title: const Text('🗺️ Trajetória', style: TextStyle(color: Colors.green)),
            subtitle: const Text(
              'Buscar rota de veículo',
              style: TextStyle(color: _kMuted, fontSize: 13),
            ),
            onTap: () {
              Navigator.pop(context); // Fechar drawer
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => const TrajectoryScreen(),
                ),
              );
            },
          ),

          const Divider(color: _kBorder, height: 20),

          // Central de Ameaças
          ListTile(
            leading: const Icon(Icons.warning, color: _kYellow),
            title: const Text('Central de Ameaças',
                style: TextStyle(color: Colors.white)),
            onTap: () {
              Navigator.pop(context);
              setState(() => _tab = 3);
            },
          ),

          // Sair
          const Spacer(),
          const Divider(color: _kBorder),
          ListTile(
            leading: const Icon(Icons.logout, color: _kRed),
            title: const Text('Sair', style: TextStyle(color: _kRed)),
            onTap: () {
              Navigator.pop(context);
              _logout();
            },
          ),
          const SizedBox(height: 16),
        ],
      ),
    );
  }

  // ── Bottom nav ──────────────────────────────────────────────────────────────

  Widget _buildBottomNav() {
    return Container(
      decoration: const BoxDecoration(
        color: _kCard,
        border: Border(top: BorderSide(color: _kBorder)),
      ),
      child: BottomNavigationBar(
        currentIndex: _tab,
        onTap: (i) {
          setState(() => _tab = i);
          // Carregar grupos quando entrar na aba de ameaças
          if (i == 3 && _gruposComboio.isEmpty && !_loadingGroups) {
            _loadGruposComboio();
          }
        },
        backgroundColor: Colors.transparent,
        elevation: 0,
        type: BottomNavigationBarType.fixed,
        selectedItemColor: _kYellow,
        unselectedItemColor: _kMuted,
        selectedLabelStyle: const TextStyle(
          fontSize: 14, fontWeight: FontWeight.w700, letterSpacing: 0.5),
        unselectedLabelStyle: const TextStyle(fontSize: 14),
        items: const [
          BottomNavigationBarItem(
              icon: Icon(Icons.home_rounded), label: 'Início'),
          BottomNavigationBarItem(
              icon: Icon(Icons.notifications_active_rounded), label: 'Alertas'),
          BottomNavigationBarItem(
              icon: Icon(Icons.search_rounded), label: 'Pesquisa'),
          BottomNavigationBarItem(
              icon: Icon(Icons.crisis_alert_rounded), label: 'Ameaças'),
          BottomNavigationBarItem(
              icon: Icon(Icons.map_rounded), label: 'Mapas'),
        ],
      ),
    );
  }

  Widget _buildAlarmeTab() {
    final suspeitosBase = _events
        .where((e) => ((e['confidence'] as num?)?.toDouble() ?? 100.0) < 70.0)
        .toList();
    final minTs = DateTime.now().subtract(_alertsPeriod.window);
    final suspeitos = suspeitosBase.where((e) {
      final eventTs = _extractEventTimestamp(e);
      if (eventTs == null) return true;
      return eventTs.isAfter(minTs);
    }).toList();

    return SafeArea(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: const BoxDecoration(
              color: _kCard,
              border: Border(bottom: BorderSide(color: _kBorder)),
            ),
            child: Row(
              children: [
                const Icon(Icons.notifications_active_rounded,
                    color: _kYellow, size: 18),
                const SizedBox(width: 8),
                const Text('ALERTAS',
                    style: TextStyle(
                        color: Colors.white,
                    fontSize: 15,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 1.5)),
                const SizedBox(width: 8),
                if (suspeitos.isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 7, vertical: 2),
                    decoration: BoxDecoration(
                      color: _kRed.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text('${suspeitos.length}',
                        style: const TextStyle(
                            color: _kRed,
                          fontSize: 14,
                            fontWeight: FontWeight.w900)),
                  ),
              ],
            ),
          ),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: const BoxDecoration(
              color: _kCard,
              border: Border(bottom: BorderSide(color: _kBorder)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'FILTROS DE ALERTA: 12h | 24h | 7d | 15d | 30d',
                  style: TextStyle(
                    color: _kYellow,
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.8,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: _AlertsPeriod.values
                      .map((period) => _buildAlertsPeriodChip(period))
                      .toList(),
                ),
              ],
            ),
          ),
          Expanded(
            child: _loadingDash && suspeitos.isEmpty
                ? const Center(
                    child: CircularProgressIndicator(
                        color: _kYellow, strokeWidth: 2))
                : _dashboardError != null && suspeitos.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.error_outline_rounded,
                                color: _kRed, size: 42),
                            const SizedBox(height: 10),
                            Text(
                              _dashboardError!,
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                  color: _kMuted,
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600),
                            ),
                          ],
                        ),
                      )
                : suspeitos.isEmpty
                  ? Center(
                    child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                      const Icon(Icons.check_circle_outline_rounded,
                                color: _kGreen, size: 48),
                      const SizedBox(height: 12),
                      const Text('Nenhum alerta no momento',
                                style: TextStyle(
                                    color: _kMuted,
                                  fontSize: 16,
                                    fontWeight: FontWeight.w600)),
                      const SizedBox(height: 4),
                            Text('Sem alertas no período ${_alertsPeriod.label}',
                                style:
                                TextStyle(color: _kMuted, fontSize: 13)),
                          ],
                        ))
                    : ListView.builder(
                        itemCount: suspeitos.length,
                        itemBuilder: (_, i) =>
                            _PassagemRow(event: suspeitos[i], highlightLow: true),
                      ),
          ),
        ],
      ),
    );
  }

  Widget _buildAlertsPeriodChip(_AlertsPeriod period) {
    final isSelected = _alertsPeriod == period;
    return InkWell(
      onTap: () => setState(() => _alertsPeriod = period),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: isSelected ? _kYellow : _kBg,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected ? _kYellow : _kBorder,
            width: isSelected ? 2 : 1,
          ),
        ),
        child: Text(
          period.label,
          style: TextStyle(
            color: isSelected ? Colors.black : _kMuted,
            fontSize: 15,
            fontWeight: FontWeight.w800,
          ),
        ),
      ),
    );
  }


  DateTime? _extractEventTimestamp(Map<String, dynamic> event) {
    final dynamic raw = event['when_ts'] ??
        event['timestamp'] ??
        event['created_at'] ??
        event['event_time'] ??
        event['seen_at'] ??
        event['ts'];
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

  // ── Central de Ameaças ───────────────────────────────────────────────────────

  Widget _buildCentralAmeacasTab() {
    final hasAnyFilters =
        _gruposWindow != '2h' ||
        _gruposGroupSizes != '2,3' ||
        _gruposMinCameras != 2 ||
        _gruposOrderMode != 'any' ||
        _gruposCoWindow != 300 ||
        _gruposLeaderRatio != 0.70 ||
        _gruposPayloadMaxFront != 0 ||
        _gruposPlate.isNotEmpty;

    return SafeArea(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Header
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: const BoxDecoration(
              color: _kCard,
              border: Border(bottom: BorderSide(color: _kBorder)),
            ),
            child: Row(
              children: [
                const Icon(Icons.crisis_alert_rounded, color: _kYellow, size: 18),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text('CENTRAL DE AMEAÇAS',
                      style: TextStyle(
                          color: Colors.white,
                        fontSize: 15,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 1.5)),
                ),
              ],
            ),
          ),
          // Filtros (estilo igual ao card de Pesquisa)
          Container(
            color: _kBg,
            padding: const EdgeInsets.all(12),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: _kCard,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _kBorder),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.filter_list_rounded, color: _kYellow, size: 16),
                      const SizedBox(width: 6),
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
                      if (hasAnyFilters)
                        GestureDetector(
                          onTap: () => setState(() {
                            _gruposWindow = '2h';
                            _gruposGroupSizes = '2,3';
                            _gruposMinCameras = 2;
                            _gruposOrderMode = 'any';
                            _gruposCoWindow = 300;
                            _gruposLeaderRatio = 0.70;
                            _gruposPayloadMaxFront = 0;
                            _gruposPlate = '';
                            _gruposPlateController.clear();
                          }),
                          child: const Text(
                            'Limpar',
                            style: TextStyle(
                              color: _kMuted,
                              fontSize: 13,
                              decoration: TextDecoration.underline,
                              decorationColor: _kMuted,
                            ),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 12),
                // Campo de filtro por placa
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Filtrar por placa',
                      style: TextStyle(
                        color: _kMuted,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    PlateSearchField(
                      controller: _gruposPlateController,
                      hintText: 'Digite a placa (ex: ABC1234)',
                      onChanged: (v) {
                        final upperText = v.trim().toUpperCase();
                        setState(() => _gruposPlate = upperText);
                      },
                    ),
                  ],
                ),
                  const SizedBox(height: 12),
                // Linha 1: Janela de tempo + Tamanho grupo
                Row(
                  children: [
                    Expanded(
                      flex: 1,
                      child: _buildFilterSelect(
                        label: 'Janela',
                        value: _gruposWindow,
                        options: const ['30m', '1h', '2h', '6h', '12h', '24h'],
                        onChanged: (v) => setState(() => _gruposWindow = v),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      flex: 1,
                      child: _buildFilterSelect(
                        label: 'Grupo',
                        value: _gruposGroupSizes,
                        options: const ['2', '3', '2,3'],
                        onChanged: (v) => setState(() => _gruposGroupSizes = v),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                // Linha 2: Mín câmeras + Modo liderança
                Row(
                  children: [
                    Expanded(
                      flex: 1,
                      child: _buildFilterSelect(
                        label: 'Mín câm.',
                        value: _gruposMinCameras.toString(),
                        options: const ['1', '2', '3', '4', '5'],
                        onChanged: (v) =>
                            setState(() => _gruposMinCameras = int.parse(v)),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      flex: 1,
                      child: _buildFilterSelect(
                        label: 'Liderança',
                        value: _gruposOrderMode,
                        options: const ['any', 'leader_front'],
                        optionLabels: const ['Qualquer', 'Líder na frente'],
                        onChanged: (v) => setState(() => _gruposOrderMode = v),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                // Linha 3: Janela co-detecção + Leader ratio
                Row(
                  children: [
                    Expanded(
                      flex: 1,
                      child: _buildFilterSelect(
                        label: 'Co-window',
                        value: _gruposCoWindow.toString(),
                        options: const ['60', '120', '300', '600', '900', '1800'],
                        optionLabels: const ['1m', '2m', '5m', '10m', '15m', '30m'],
                        onChanged: (v) =>
                            setState(() => _gruposCoWindow = int.parse(v)),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      flex: 1,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Líder ≥',
                              style: TextStyle(
                                  color: _kMuted,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600)),
                          const SizedBox(height: 3),
                          Row(
                            children: [
                              Expanded(
                                child: Slider(
                                  value: _gruposLeaderRatio,
                                  min: 0.5,
                                  max: 1.0,
                                  divisions: 10,
                                  activeColor: _kYellow,
                                  inactiveColor: _kBorder,
                                  onChanged: (v) =>
                                      setState(() => _gruposLeaderRatio = v),
                                ),
                              ),
                              const SizedBox(width: 4),
                              Text(
                                '${(_gruposLeaderRatio * 100).toStringAsFixed(0)}%',
                                style: const TextStyle(
                                    color: _kYellow,
                                    fontSize: 13,
                                    fontWeight: FontWeight.w700),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                // Linha 4: Botões de ação (padrão visual da Pesquisa)
                Row(
                  children: [
                    Expanded(
                      child: SizedBox(
                        height: 50,
                        child: ElevatedButton.icon(
                          onPressed: _loadGruposComboio,
                          icon: const Icon(Icons.search, size: 20),
                          label: const Text('Buscar'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _kYellow,
                            foregroundColor: Colors.black,
                            elevation: 0,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                            textStyle: const TextStyle(
                              fontSize: 17,
                              fontWeight: FontWeight.w700,
                              letterSpacing: .4,
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    SizedBox(
                      height: 50,
                      child: ElevatedButton.icon(
                        onPressed: () => setState(() {
                          _gruposWindow = '2h';
                          _gruposGroupSizes = '2,3';
                          _gruposMinCameras = 2;
                          _gruposOrderMode = 'any';
                          _gruposCoWindow = 300;
                          _gruposLeaderRatio = 0.70;
                          _gruposPayloadMaxFront = 0;
                          _gruposPlate = '';
                          _gruposPlateController.clear();
                        }),
                        icon: const Icon(Icons.refresh, size: 20),
                        label: const Text('Limpar'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: _kCard,
                          foregroundColor: _kMuted,
                          elevation: 0,
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
                    ),
                  ],
                ),
              ],
            ),
          ),
          ),
          // Content
          Expanded(
            child: _centralResults.isNotEmpty
                ? _buildCentralResultsList()
                : _gruposComboio.isEmpty && !_loadingGroups
                    ? _buildEmptyAmeacas()
                    : _loadingGroups
                        ? const Center(
                            child: CircularProgressIndicator(
                                color: _kYellow, strokeWidth: 2))
                        : RefreshIndicator(
                            onRefresh: _loadGruposComboio,
                            color: _kYellow,
                            backgroundColor: _kCard,
                            child: ListView.builder(
                              itemCount: _gruposComboio.length,
                              itemBuilder: (_, i) => _buildGrupoCard(_gruposComboio[i]),
                            ),
                          ),
          ),
        ],
      ),
    );
  }

  Widget _buildFilterSelect({
    required String label,
    required String value,
    required List<String> options,
    List<String>? optionLabels,
    required Function(String) onChanged,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(
                color: _kMuted, fontSize: 12, fontWeight: FontWeight.w600)),
        const SizedBox(height: 3),
        Container(
          decoration: BoxDecoration(
            color: _kBg2,
            border: Border.all(color: _kBorder),
            borderRadius: BorderRadius.circular(6),
          ),
          child: DropdownButton<String>(
            value: value,
            isExpanded: true,
            underline: const SizedBox(),
            style: const TextStyle(color: Colors.white, fontSize: 11),
            dropdownColor: _kCard,
            items: options.asMap().entries.map((e) {
              return DropdownMenuItem(
                value: e.value,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Text(
                    optionLabels != null && e.key < optionLabels.length
                        ? optionLabels[e.key]
                        : e.value,
                    style: const TextStyle(fontSize: 11),
                  ),
                ),
              );
            }).toList(),
            onChanged: (v) => v != null ? onChanged(v) : null,
          ),
        ),
      ],
    );
  }

  Widget _buildEmptyAmeacas() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.check_circle_outline_rounded, color: _kGreen, size: 48),
          const SizedBox(height: 12),
          const Text('Nenhum grupo suspeito detectado',
              style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          const Text('Nenhum veículo andando junto em 2+ câmaras',
              style: TextStyle(color: _kMuted, fontSize: 11)),
          const SizedBox(height: 20),
          ElevatedButton.icon(
            onPressed: _loadGruposComboio,
            icon: const Icon(Icons.refresh_rounded, size: 16),
            label: const Text('Recarregar'),
            style: ElevatedButton.styleFrom(
              backgroundColor: _kYellow.withValues(alpha: 0.15),
              foregroundColor: _kYellow,
              elevation: 0,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGrupoCard(Map<String, dynamic> grupo) {
    final plates = (grupo['plates'] as List?)?.cast<String>() ?? [];
    final camerasCount = (grupo['cameras_count'] as num?)?.toInt() ?? 0;
    final cameras = (grupo['cameras'] as List?)?.cast<String>() ?? [];
    final tripSpan = (grupo['trip_span_sec'] as num?)?.toInt() ?? 0;
    final firstSeen = grupo['first_seen'] as String?;
    final lastSeen = grupo['last_seen'] as String?;
    final groupSize = (grupo['group_size'] as num?)?.toInt() ?? 0;

    final tripSpanMin = (tripSpan / 60).toInt();
    final confidence = 'Confirmado em $camerasCount câmaras';

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _kCard,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _kYellow.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Cabeçalho: Placas
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: _kYellow.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  'GRUPO #$groupSize',
                  style: const TextStyle(
                    color: _kYellow,
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                    letterSpacing: 1,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  plates.join(' • '),
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.5,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          // Métricas
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: _kBg.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _MetricBadge(
                  icon: Icons.videocam_rounded,
                  label: camerasCount > 1 ? '$camerasCount câmaras' : '1 câmara',
                  value: '$camerasCount',
                ),
                Container(width: 1, height: 30, color: _kBorder),
                _MetricBadge(
                  icon: Icons.schedule_rounded,
                  label: '${tripSpanMin}min percurso',
                  value: tripSpanMin > 0 ? '${tripSpanMin}m' : '<1m',
                ),
                Container(width: 1, height: 30, color: _kBorder),
                _MetricBadge(
                  icon: Icons.check_circle_rounded,
                  label: confidence,
                  value: '✓',
                  color: _kGreen,
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          // Câmaras
          if (cameras.isNotEmpty) ...[
            const Text(
              'CÂMARAS',
              style: TextStyle(
                color: _kMuted,
                fontSize: 11,
                fontWeight: FontWeight.w800,
                letterSpacing: 1,
              ),
            ),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: cameras
                  .map((cam) => Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: _kBg,
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(color: _kBorder),
                        ),
                        child: Text(
                          cam,
                          style: const TextStyle(color: _kMuted, fontSize: 12),
                        ),
                      ))
                  .toList(),
            ),
            const SizedBox(height: 8),
          ],
          // Timestamps
          Row(
            children: [
              Icon(Icons.access_time_rounded, color: _kMuted, size: 12),
              const SizedBox(width: 4),
              Text(
                _formatTs(firstSeen),
                style: const TextStyle(color: _kMuted, fontSize: 12),
              ),
              const SizedBox(width: 4),
              Text('→', style: TextStyle(color: _kMuted.withValues(alpha: 0.5), fontSize: 12)),
              const SizedBox(width: 4),
              Text(
                _formatTs(lastSeen),
                style: const TextStyle(color: _kMuted, fontSize: 12),
              ),
            ],
          ),
        ],
      ),
    );
  }

  String _formatTs(String? ts) {
    if (ts == null) return '';
    try {
      final dt = DateTime.parse(ts);
      return '${dt.day.toString().padLeft(2, '0')}/${dt.month.toString().padLeft(2, '0')} ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {
      return ts;
    }
  }

  // ── Central Results (busca por placa específica) ──────────────────────────

  Widget _buildCentralResultsList() {
    if (_centralResults.isEmpty && !_loadingGroups) {
      return _buildEmptyAmeacas();
    }
    return RefreshIndicator(
      onRefresh: _loadGruposComboio,
      color: _kYellow,
      backgroundColor: _kCard,
      child: ListView.builder(
        itemCount: _centralResults.length,
        itemBuilder: (_, i) => _buildCentralResultCard(_centralResults[i]),
      ),
    );
  }

  Widget _buildCentralResultCard(Map<String, dynamic> item) {
    final plate = item['plate'] as String? ?? '—';
    final camera = item['camera'] as String? ?? '—';
    final timestamp = item['timestamp'] as String?;
    final vehicleType = item['vehicle_type'] as String?;
    final vehicleColor = item['vehicle_color'] as String?;
    
    // Dados de parceiros/comboio
    final inGrupos = (item['in_grupos'] as List?)?.cast<String>() ?? [];
    final inComboio = (item['in_comboio'] as List?)?.cast<String>() ?? [];
    final inSuspeitos = (item['in_suspeitos'] as List?)?.cast<String>() ?? [];
    final isAlvo = item['is_alvo'] as bool? ?? false;
    
    // Combinar parceiros (grupos + comboio)
    final parceiros = <String>{...inGrupos, ...inComboio}.toList();
    parceiros.remove(plate); // Remove a própria placa
    
    final hasParceiro = parceiros.isNotEmpty;
    final parceiroText = hasParceiro 
        ? parceiros.join(', ') 
        : 'Parceiro não encontrado';

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _kCard,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: isAlvo ? _kRed : hasParceiro ? _kYellow.withValues(alpha: 0.3) : _kBorder,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Cabeçalho: Placa + Status
          Row(
            children: [
              Expanded(
                child: Text(
                  plate,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1,
                  ),
                ),
              ),
              if (isAlvo)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                  decoration: BoxDecoration(
                    color: _kRed.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Text(
                    'ALVO',
                    style: TextStyle(
                      color: _kRed,
                      fontSize: 11,
                      fontWeight: FontWeight.w900,
                      letterSpacing: 1,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          
          // Parceiro
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: hasParceiro 
                  ? _kYellow.withValues(alpha: 0.08) 
                  : _kBg.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: hasParceiro ? _kYellow.withValues(alpha: 0.3) : _kBorder,
              ),
            ),
            child: Row(
              children: [
                Icon(
                  hasParceiro ? Icons.people_rounded : Icons.person_off_rounded,
                  color: hasParceiro ? _kYellow : _kMuted,
                  size: 16,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'PARCEIRO/COMBOIO',
                        style: TextStyle(
                          color: hasParceiro ? _kYellow : _kMuted,
                          fontSize: 11,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 1,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        parceiroText,
                        style: TextStyle(
                          color: hasParceiro ? Colors.white : _kMuted,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          
          // Informações adicionais
          Row(
            children: [
              Icon(Icons.videocam_rounded, color: _kMuted, size: 12),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  camera,
                  style: const TextStyle(color: _kMuted, fontSize: 12),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 10),
              Icon(Icons.access_time_rounded, color: _kMuted, size: 12),
              const SizedBox(width: 4),
              Text(
                _formatTs(timestamp),
                style: const TextStyle(color: _kMuted, fontSize: 12),
              ),
            ],
          ),
          
          if (vehicleType != null || vehicleColor != null) ...[
            const SizedBox(height: 6),
            Row(
              children: [
                if (vehicleType != null) ...[
                  Icon(Icons.directions_car_rounded, color: _kMuted, size: 12),
                  const SizedBox(width: 4),
                  Text(
                    vehicleType,
                    style: const TextStyle(color: _kMuted, fontSize: 12),
                  ),
                ],
                if (vehicleType != null && vehicleColor != null)
                  const Text(' • ', style: TextStyle(color: _kMuted, fontSize: 12)),
                if (vehicleColor != null) ...[
                  Icon(Icons.palette_rounded, color: _kMuted, size: 12),
                  const SizedBox(width: 4),
                  Text(
                    vehicleColor,
                    style: const TextStyle(color: _kMuted, fontSize: 12),
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    );
  }

  // ── Home ────────────────────────────────────────────────────────────────────

  Widget _buildHome() {
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.only(bottom: 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _buildTopbar(),
            if (_dashboardError != null)
              Container(
                margin: const EdgeInsets.fromLTRB(14, 10, 14, 0),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: _kRed.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: _kRed.withValues(alpha: 0.5)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.wifi_off_rounded, color: _kRed, size: 18),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _dashboardError!,
                        style: const TextStyle(color: _kRed, fontSize: 13, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
                ),
              ),
            Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _buildStatCards(),
                  const SizedBox(height: 14),
                  _buildPassagensPanel(),
                  const SizedBox(height: 14),
                  _buildAlertasPanel(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── Topbar ──────────────────────────────────────────────────────────────────

  Widget _buildTopbar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: const BoxDecoration(
        color: _kCard,
        border: Border(bottom: BorderSide(color: _kBorder)),
      ),
      child: Row(
        children: [
          Container(
            width: 58,
            height: 58,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: _kBg,
              border: Border.all(color: _kYellow, width: 2),
            ),
            padding: const EdgeInsets.all(4),
            child: ClipOval(
              child: Image.asset(
                'assets/logo_bpfron.png',
                width: 50,
                height: 50,
                fit: BoxFit.cover,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '⚡ PAINEL DE MONITORAMENTO',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.5),
                ),
                const SizedBox(height: 3),
                Row(children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: const BoxDecoration(
                        color: _kGreen, shape: BoxShape.circle),
                  ),
                  const SizedBox(width: 5),
                  const Text('AO VIVO',
                      style: TextStyle(
                          color: _kGreen,
                          fontSize: 12,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 1)),
                  const SizedBox(width: 10),
                  Flexible(
                    child: Text('$_timeStr  $_dateStr',
                        style: const TextStyle(
                            color: _kMuted,
                            fontSize: 11,
                            fontWeight: FontWeight.w700),
                        overflow: TextOverflow.ellipsis),
                  ),
                ]),
              ],
            ),
          ),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            const Text('admin • BPFRON',
                style: TextStyle(color: _kMuted, fontSize: 12)),
            const SizedBox(height: 4),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Botão de teste de alerta
                GestureDetector(
                  onTap: () async {
                    try {
                      final alarmesData = await Api.getAlarmes();
                      final items = List<Map<String, dynamic>>.from((alarmesData['items'] ?? []) as List);
                      final active = items.where((a) => a['ativo'] == true).toList();
                      if (active.isEmpty) {
                        throw Exception('Nenhum alarme ativo para teste de push.');
                      }
                      final alarmeId = (active.first['id'] as num).toInt();
                      final result = await NotificationService().triggerBackendTestAlert(alarmeId: alarmeId);
                      if (!mounted) return;
                      final sent = result['sent'] ?? 0;
                      final failed = result['failed'] ?? 0;
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text('Teste push enviado: $sent sucesso, $failed falhas'),
                          backgroundColor: sent > 0 ? _kGreen : _kRed,
                        ),
                      );
                    } on SessionExpiredException {
                      if (!mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('Sessão expirada. Redirecionando para login...'),
                          backgroundColor: Colors.orange,
                        ),
                      );
                      await Future.delayed(const Duration(milliseconds: 800));
                      if (!mounted) return;
                      await AuthStorage.clear();
                      Navigator.of(context).pushAndRemoveUntil(
                        MaterialPageRoute(builder: (_) => const LoginScreen()),
                        (_) => false,
                      );
                    } catch (e) {
                      if (!mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text('Erro no teste: $e'),
                          backgroundColor: _kRed,
                        ),
                      );
                    }
                  },
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                    decoration: BoxDecoration(
                      color: Colors.red.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(4),
                      border:
                          Border.all(color: Colors.red.withValues(alpha: 0.5)),
                    ),
                    child: const Text('TESTE',
                        style: TextStyle(
                            color: Colors.red,
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 1)),
                  ),
                ),
                const SizedBox(width: 6),
                GestureDetector(
                  onTap: _logout,
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: _kRed.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(4),
                      border:
                          Border.all(color: _kRed.withValues(alpha: 0.5)),
                    ),
                    child: const Text('SAIR',
                        style: TextStyle(
                            color: _kRed,
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 1.5)),
                  ),
                ),
              ],
            ),
          ]),
        ],
      ),
    );
  }

  // ── 4 Stat cards ────────────────────────────────────────────────────────────

  Widget _buildStatCards() {
    final todayStr = _stats?['today_events']?.toString() ?? '—';
    final hourStr  = _stats?['last_hour']?.toString() ?? '—';
    final camsStr  = _stats?['active_cameras']?.toString() ?? '—';
    final confRaw  = (_stats?['avg_confidence'] as num?)?.toDouble();
    final confStr  = confRaw != null ? '${confRaw.toStringAsFixed(0)}%' : '—';
    final confColor = confRaw == null
        ? _kMuted
        : confRaw >= 80 ? _kGreen : confRaw >= 60 ? _kYellow : _kRed;
    return Column(children: [
      Row(children: [
        Expanded(
          child: _StatCard(
              label: 'Eventos hoje',
              value: todayStr,
              sub: 'passagens registradas',
              color: Colors.white)),
        const SizedBox(width: 10),
        Expanded(
          child: _StatCard(
              label: 'Câmeras ativas 24h',
              value: camsStr,
              sub: 'com passagens recentes',
              color: _kYellow)),
      ]),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(
          child: _StatCard(
              label: 'Última hora',
              value: hourStr,
              sub: 'eventos nos últimos 60 min',
              color: _kGreen)),
        const SizedBox(width: 10),
        Expanded(
          child: _StatCard(
              label: 'Confiança média',
              value: confStr,
              sub: '50 leituras mais recentes',
              color: confColor)),
      ]),
    ]);
  }

  // ── Painel Últimas Passagens ─────────────────────────────────────────────────

  Widget _buildPassagensPanel() {
    return _Panel(
      icon: Icons.table_rows_rounded,
      title: 'ÚLTIMAS PASSAGENS',
      action: GestureDetector(
        onTap: () => setState(() => _tab = 2),
        child: const Text('Pesquisar →',
            style: TextStyle(
                color: _kYellow,
                fontSize: 11,
                fontWeight: FontWeight.w700)),
      ),
      child: _loadingDash && _events.isEmpty
              ? const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Center(
                  child: CircularProgressIndicator(
                      color: _kYellow, strokeWidth: 2)),
            )
          : _dashboardError != null && _events.isEmpty
              ? Padding(
                  padding: const EdgeInsets.symmetric(vertical: 20),
                  child: Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.error_outline_rounded, color: _kRed, size: 30),
                        const SizedBox(height: 8),
                        Text(
                          _dashboardError!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: _kMuted, fontSize: 12),
                        ),
                        const SizedBox(height: 10),
                        ElevatedButton(
                          onPressed: _loadDashboard,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _kYellow,
                            foregroundColor: Colors.black,
                          ),
                          child: const Text('Tentar novamente'),
                        ),
                      ],
                    ),
                  ),
                )
          : _events.isEmpty
              ? const Padding(
                  padding: EdgeInsets.symmetric(vertical: 20),
                  child: Center(
                      child: Text('Nenhuma passagem registrada ainda.',
                          style: TextStyle(
                              color: _kMuted, fontSize: 12))),
                )
              : Column(
                  children:
                      _events.map((e) => _PassagemRow(event: e)).toList(),
                ),
    );
  }

  // ── Painel Alertas Ativos ────────────────────────────────────────────────────

  Widget _buildAlertasPanel() {
    final suspeitos = _events
        .where((e) => ((e['confidence'] as num?)?.toDouble() ?? 100.0) < 70.0)
        .take(5)
        .toList();
    return _Panel(
      icon: Icons.warning_amber_rounded,
      title: 'LEITURAS SUSPEITAS',
      child: suspeitos.isEmpty
          ? const Padding(
              padding: EdgeInsets.symmetric(vertical: 18),
              child: Center(
                  child: Text('Nenhuma leitura suspeita no momento.',
                      style: TextStyle(color: _kMuted, fontSize: 12))),
            )
          : Column(
              children: suspeitos
                  .map((e) => _PassagemRow(event: e, highlightLow: true))
                  .toList(),
            ),
    );
  }
}


// ─── Widgets ──────────────────────────────────────────────────────────────────

class _StatCard extends StatelessWidget {
  final String label, value, sub;
  final Color color;

  const _StatCard(
      {required this.label,
      required this.value,
      required this.sub,
      required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _kCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _kBorder),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label,
            style: const TextStyle(
                color: _kMuted,
                fontSize: 12,
                fontWeight: FontWeight.w700,
                letterSpacing: 1.5)),
        const SizedBox(height: 6),
        Text(value,
            style: TextStyle(
                color: color,
                fontSize: 26,
                fontWeight: FontWeight.w900,
                height: 1)),
        const SizedBox(height: 4),
        Text(sub, style: const TextStyle(color: _kMuted, fontSize: 12)),
      ]),
    );
  }
}

class _Panel extends StatelessWidget {
  final IconData icon;
  final String title;
  final Widget child;
  final Widget? action;

  const _Panel(
      {required this.icon,
      required this.title,
      required this.child,
      this.action});

  @override
  Widget build(BuildContext context) {
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
            padding:
                const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: _kBorder)),
            ),
            child: Row(children: [
              Icon(icon, color: _kYellow, size: 14),
              const SizedBox(width: 7),
              Text(title,
                  style: const TextStyle(
                      color: _kYellow,
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 2)),
              if (action != null) ...[const Spacer(), action!],
            ]),
          ),
          child,
        ],
      ),
    );
  }
}

class _PassagemRow extends StatelessWidget {
  final Map<String, dynamic> event;
  final bool highlightLow;
  const _PassagemRow({required this.event, this.highlightLow = false});

  static String _fmtTs(String? iso) {
    if (iso == null) return '—';
    try {
      final dt = DateTime.parse(iso).toLocal();
      final d = '${dt.day.toString().padLeft(2,'0')}/${dt.month.toString().padLeft(2,'0')}';
      final t = '${dt.hour.toString().padLeft(2,'0')}:${dt.minute.toString().padLeft(2,'0')}';
      return '$d $t';
    } catch (_) {
      return iso.length > 16 ? iso.substring(0, 16) : iso;
    }
  }

  @override
  Widget build(BuildContext context) {
    final plate   = (event['plate'] as String? ?? '?????').toUpperCase();
    final camNome = event['cam_nome'] as String? ?? event['camera_id'] as String? ?? '—';
    final ts      = _fmtTs(event['when_ts'] as String?);
    final dir     = event['direcao'] as String?;
    final conf    = (event['confidence'] as num?)?.toDouble();
    final confStr = conf != null ? '${conf.toStringAsFixed(0)}%' : '—';
    final confColor = conf == null
        ? _kMuted
        : conf >= 85
            ? _kGreen
            : conf >= 65
                ? _kYellow
                : _kRed;
    final eventId = event['id'] as int?;

    return InkWell(
      onTap: eventId != null
          ? () {
              Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => EventDetailScreen(eventId: eventId),
                ),
              );
            }
          : null,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          border: const Border(bottom: BorderSide(color: _kBorder, width: 0.4)),
          color: highlightLow && (conf ?? 100) < 70
              ? _kRed.withValues(alpha: 0.04)
              : null,
        ),
        child: Row(children: [
        // Placa chip
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
          decoration: BoxDecoration(
            color: _kBorder,
            borderRadius: BorderRadius.circular(5),
          ),
          child: Text(plate,
              style: const TextStyle(
                  color: Colors.white,
                fontSize: 13,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 2)),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(camNome,
                  style: const TextStyle(color: _kMuted, fontSize: 14),
                  overflow: TextOverflow.ellipsis),
              const SizedBox(height: 2),
              Row(children: [
                Text(ts,
                    style: const TextStyle(color: _kMuted, fontSize: 14)),
                if (dir != null && dir.isNotEmpty) ...
                  [
                    const SizedBox(width: 8),
                    Text(dir,
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.w600)),
                  ],
              ]),
            ],
          ),
        ),
        _Badge(label: confStr, color: confColor),
      ]),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final String label;
  final Color color;
  const _Badge({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(label,
          style: TextStyle(
              color: color,
              fontSize: 14,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.8)),
    );
  }
}
