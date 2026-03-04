import 'dart:async';

import 'package:flutter/material.dart';

import '../services/api.dart';
import '../services/auth_storage.dart';
import '../theme/app_theme.dart';
import 'login_screen.dart';
import 'search_screen.dart';

// ─── Paleta ───────────────────────────────────────────────────────────────────
const _kBg     = AppColors.background;
const _kCard   = AppColors.surface;
const _kBorder = AppColors.border;
const _kYellow = AppColors.warning;
const _kGreen  = AppColors.success;
const _kRed    = AppColors.danger;
const _kMuted  = AppColors.muted;


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

  @override
  void initState() {
    super.initState();
    _clock = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _now = DateTime.now());
    });
    _loadDashboard();
    // Atualiza a cada 30 segundos
    _refreshTimer = Timer.periodic(
        const Duration(seconds: 30), (_) => _loadDashboard());
  }

  Future<void> _loadDashboard() async {
    if (_loadingDash) return;
    setState(() => _loadingDash = true);
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
    } catch (e) {
      debugPrint('Dashboard load error: $e');
    } finally {
      if (mounted) setState(() => _loadingDash = false);
    }
  }

  @override
  void dispose() {
    _clock.cancel();
    _refreshTimer?.cancel();
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
      body: IndexedStack(
        index: _tab,
        children: [
          _buildHome(),
          _buildAlarmeTab(),
          const SearchScreen(),
          _buildCentralAmeacasTab(),
        ],
      ),
      bottomNavigationBar: _buildBottomNav(),
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
        onTap: (i) => setState(() => _tab = i),
        backgroundColor: Colors.transparent,
        elevation: 0,
        type: BottomNavigationBarType.fixed,
        selectedItemColor: _kYellow,
        unselectedItemColor: _kMuted,
        selectedLabelStyle: const TextStyle(
            fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.5),
        unselectedLabelStyle: const TextStyle(fontSize: 10),
        items: const [
          BottomNavigationBarItem(
              icon: Icon(Icons.home_rounded), label: 'Início'),
          BottomNavigationBarItem(
              icon: Icon(Icons.notifications_active_rounded), label: 'Alertas'),
          BottomNavigationBarItem(
              icon: Icon(Icons.search_rounded), label: 'Pesquisa'),
          BottomNavigationBarItem(
              icon: Icon(Icons.crisis_alert_rounded), label: 'Ameaças'),
        ],
      ),
    );
  }

  Widget _buildAlarmeTab() {
    final suspeitos = _events
        .where((e) => ((e['confidence'] as num?)?.toDouble() ?? 100.0) < 70.0)
        .toList();
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
                        fontSize: 13,
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
                            fontSize: 10,
                            fontWeight: FontWeight.w900)),
                  ),
              ],
            ),
          ),
          Expanded(
            child: _loadingDash && suspeitos.isEmpty
                ? const Center(
                    child: CircularProgressIndicator(
                        color: _kYellow, strokeWidth: 2))
                : suspeitos.isEmpty
                    ? const Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.check_circle_outline_rounded,
                                color: _kGreen, size: 48),
                            SizedBox(height: 12),
                            Text('Nenhum alerta no momento',
                                style: TextStyle(
                                    color: _kMuted,
                                    fontSize: 14,
                                    fontWeight: FontWeight.w600)),
                            SizedBox(height: 4),
                            Text('Todas as leituras com confiança ≥ 70%',
                                style:
                                    TextStyle(color: _kMuted, fontSize: 11)),
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

  // ── Central de Ameaças ───────────────────────────────────────────────────────

  Widget _buildCentralAmeacasTab() {
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
            child: const Row(
              children: [
                Icon(Icons.crisis_alert_rounded, color: _kYellow, size: 18),
                SizedBox(width: 8),
                Text('CENTRAL DE AMEAÇAS',
                    style: TextStyle(
                        color: Colors.white,
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 1.5)),
              ],
            ),
          ),
          const Expanded(
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.crisis_alert_rounded,
                      color: _kMuted, size: 56),
                  SizedBox(height: 14),
                  Text('Central de Ameaças',
                      style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1)),
                  SizedBox(height: 6),
                  Text('Em desenvolvimento',
                      style: TextStyle(color: _kMuted, fontSize: 12)),
                ],
              ),
            ),
          ),
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
                          fontSize: 9,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 1)),
                  const SizedBox(width: 10),
                  Text(_timeStr,
                      style: const TextStyle(
                          color: _kYellow,
                          fontSize: 11,
                          fontWeight: FontWeight.w900,
                          letterSpacing: 1.5)),
                  const SizedBox(width: 6),
                  Text(_dateStr,
                      style:
                          const TextStyle(color: _kMuted, fontSize: 9)),
                ]),
              ],
            ),
          ),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            const Text('admin • BPFRON',
                style: TextStyle(color: _kMuted, fontSize: 10)),
            const SizedBox(height: 4),
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
                        fontSize: 8,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 1.5)),
              ),
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
                fontSize: 9,
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
        Text(sub, style: const TextStyle(color: _kMuted, fontSize: 10)),
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
                      fontSize: 10,
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

    return Container(
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
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 2)),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(camNome,
                  style: const TextStyle(color: _kMuted, fontSize: 10),
                  overflow: TextOverflow.ellipsis),
              const SizedBox(height: 2),
              Row(children: [
                Text(ts,
                    style: const TextStyle(color: _kMuted, fontSize: 10)),
                if (dir != null && dir.isNotEmpty) ...
                  [
                    const SizedBox(width: 8),
                    Text(dir,
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                            fontWeight: FontWeight.w600)),
                  ],
              ]),
            ],
          ),
        ),
        _Badge(label: confStr, color: confColor),
      ]),
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
              fontSize: 9,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.8)),
    );
  }
}
