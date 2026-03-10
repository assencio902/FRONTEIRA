import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../services/api.dart';
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

class WatchlistScreen extends StatefulWidget {
  const WatchlistScreen({super.key});

  @override
  State<WatchlistScreen> createState() => _WatchlistScreenState();
}

class _WatchlistScreenState extends State<WatchlistScreen> {
  List<Map<String, dynamic>> _lists = [];
  List<Map<String, dynamic>> _vehicles = [];
  Map<String, dynamic>? _selectedList;
  bool _loadingLists = true;
  bool _loadingVehicles = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadLists();
  }

  Future<void> _loadLists() async {
    final tokenExpired = await AuthStorage.isTokenExpired();
    if (tokenExpired) {
      await _handleSessionExpired();
      return;
    }

    setState(() {
      _loadingLists = true;
      _error = null;
    });

    try {
      final lists = await Api.getVehicleLists();
      if (!mounted) return;
      setState(() {
        _lists = lists;
        _loadingLists = false;
        // Selecionar primeira lista automaticamente
        if (lists.isNotEmpty) {
          _selectedList = lists.first;
          _loadVehicles();
        }
      });
    } on ApiUnauthorizedException {
      await _handleSessionExpired();
    } on TimeoutException {
      if (!mounted) return;
      setState(() {
        _loadingLists = false;
        _error = 'A API demorou para responder. Tente novamente.';
      });
    } on SocketException {
      if (!mounted) return;
      setState(() {
        _loadingLists = false;
        _error = 'Sem conexão com a API. Verifique internet/servidor.';
      });
    } catch (e) {
      debugPrint('Error loading lists: $e');
      if (!mounted) return;
      setState(() {
        _loadingLists = false;
        _error = 'Falha ao carregar listas de monitoramento.';
      });
    }
  }

  Future<void> _loadVehicles() async {
    if (_selectedList == null) return;

    final listId = _selectedList!['id'] as int;

    setState(() {
      _loadingVehicles = true;
      _error = null;
    });

    try {
      final vehicles = await Api.getVehicles(listId);
      if (!mounted) return;
      setState(() {
        _vehicles = vehicles;
        _loadingVehicles = false;
      });
    } on ApiUnauthorizedException {
      await _handleSessionExpired();
    } on TimeoutException {
      if (!mounted) return;
      setState(() {
        _loadingVehicles = false;
        _error = 'A API demorou para responder. Tente novamente.';
      });
    } on SocketException {
      if (!mounted) return;
      setState(() {
        _loadingVehicles = false;
        _error = 'Sem conexão com a API. Verifique internet/servidor.';
      });
    } catch (e) {
      debugPrint('Error loading vehicles: $e');
      if (!mounted) return;
      setState(() {
        _loadingVehicles = false;
        _error = 'Falha ao carregar veículos.';
      });
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _kBg,
      appBar: AppBar(
        backgroundColor: _kBg,
        elevation: 0,
        title: const Text(
          'Veículos Monitorados',
          style: TextStyle(
            color: Colors.white,
            fontSize: 16,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      body: _loadingLists
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
                          onPressed: _loadLists,
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
              : _lists.isEmpty
                  ? const Center(
                      child: Text(
                        'Nenhuma lista de monitoramento encontrada.',
                        style: TextStyle(color: _kMuted, fontSize: 14),
                      ),
                    )
                  : Column(
                      children: [
                        // Seletor de lista
                        Container(
                          padding: const EdgeInsets.all(14),
                          color: _kCard,
                          child: Row(
                            children: [
                              const Text(
                                'Lista:',
                                style: TextStyle(
                                  color: _kMuted,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: DropdownButton<Map<String, dynamic>>(
                                  isExpanded: true,
                                  value: _selectedList,
                                  dropdownColor: _kCard,
                                  style: const TextStyle(color: Colors.white),
                                  items: _lists.map((list) {
                                    final name = list['name'] as String;
                                    final count =
                                        list['vehicle_count'] as int? ?? 0;
                                    return DropdownMenuItem(
                                      value: list,
                                      child: Text(
                                        '$name ($count)',
                                        style: const TextStyle(
                                          color: Colors.white,
                                          fontSize: 13,
                                        ),
                                      ),
                                    );
                                  }).toList(),
                                  onChanged: (list) {
                                    if (list != null) {
                                      setState(() => _selectedList = list);
                                      _loadVehicles();
                                    }
                                  },
                                ),
                              ),
                            ],
                          ),
                        ),

                        // Lista de veículos
                        Expanded(
                          child: _loadingVehicles
                              ? const Center(
                                  child: CircularProgressIndicator(
                                    color: _kYellow,
                                    strokeWidth: 2,
                                  ),
                                )
                              : _vehicles.isEmpty
                                  ? const Center(
                                      child: Text(
                                        'Nenhum veículo nesta lista.',
                                        style: TextStyle(
                                          color: _kMuted,
                                          fontSize: 14,
                                        ),
                                      ),
                                    )
                                  : ListView.builder(
                                      itemCount: _vehicles.length,
                                      itemBuilder: (context, index) {
                                        final vehicle = _vehicles[index];
                                        return _VehicleItem(vehicle: vehicle);
                                      },
                                    ),
                        ),
                      ],
                    ),
    );
  }
}

class _VehicleItem extends StatelessWidget {
  final Map<String, dynamic> vehicle;

  const _VehicleItem({required this.vehicle});

  static String _formatDate(String? iso) {
    if (iso == null) return '—';
    try {
      final dt = DateTime.parse(iso).toLocal();
      final d =
          '${dt.day.toString().padLeft(2, '0')}/${dt.month.toString().padLeft(2, '0')}/${dt.year}';
      final t =
          '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
      return '$d $t';
    } catch (_) {
      return iso;
    }
  }

  @override
  Widget build(BuildContext context) {
    final plate = (vehicle['plate'] as String? ?? '?????').toUpperCase();
    final notes = vehicle['notes'] as String?;
    final createdAt = vehicle['created_at'] as String?;
    final listName = vehicle['list_name'] as String? ?? '—';

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: _kCard,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _kBorder),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Placa em destaque
            Text(
              plate,
              style: const TextStyle(
                color: _kYellow,
                fontSize: 18,
                fontWeight: FontWeight.w900,
                letterSpacing: 2,
              ),
            ),
            const SizedBox(height: 8),

            // Lista
            Row(
              children: [
                const Text(
                  'Lista:',
                  style: TextStyle(
                    color: _kMuted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(width: 6),
                Text(
                  listName,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                  ),
                ),
              ],
            ),

            // Observação/Notas
            if (notes != null && notes.isNotEmpty) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  const Text(
                    'Observação:',
                    style: TextStyle(
                      color: _kMuted,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      notes,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                      ),
                    ),
                  ),
                ],
              ),
            ],

            // Data de adição
            if (createdAt != null) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  const Text(
                    'Adicionado em:',
                    style: TextStyle(
                      color: _kMuted,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    _formatDate(createdAt),
                    style: const TextStyle(
                      color: _kMuted,
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
