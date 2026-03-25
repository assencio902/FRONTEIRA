import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

// Serviço de watchlist (placas vindas do backend)
class WatchlistService {
  static const _cacheKey = 'watchlist_cache_v1';
  final Map<String, Map<String, dynamic>> _watched = {};

  Future<void> init() async {
    await _loadCache();
    await refresh();
  }

  Future<void> refresh() async {
    try {
      final data = await Api.getAllPlates();
      final plates = (data['plates'] as Map<String, dynamic>? ?? {});
      _watched.clear();
      plates.forEach((plate, listsRaw) {
        final key = plate.toString().toUpperCase();
        final lists = List<Map<String, dynamic>>.from(listsRaw as List? ?? []);
        final targetName = _extractTargetName(lists);
        _watched[key] = {
          'target_name': targetName,
          'lists': lists,
        };
      });
      await _saveCache();
    } catch (_) {
      // Mantém cache anterior quando offline
    }
  }

  bool isInWatchlist(String plate) {
    return _watched.containsKey(plate.toUpperCase());
  }

  String? getTargetName(String plate) {
    return _watched[plate.toUpperCase()]?['target_name'] as String?;
  }

  Future<List<String>> getWatchedPlates() async {
    return _watched.keys.toList();
  }

  Future<void> addPlate(String plate) async {
    // Mantido apenas por compatibilidade; listas são controladas pelo backend.
  }

  Future<void> removePlate(String plate) async {
    // Mantido apenas por compatibilidade; listas são controladas pelo backend.
  }

  String _extractTargetName(List<Map<String, dynamic>> lists) {
    for (final l in lists) {
      final notes = (l['notes'] as String?)?.trim();
      if (notes != null && notes.isNotEmpty) return notes;
    }
    if (lists.isNotEmpty) {
      final name = (lists.first['list_name'] ?? lists.first['name'])?.toString();
      if (name != null && name.trim().isNotEmpty) return name.trim();
    }
    return '';
  }

  Future<void> _loadCache() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_cacheKey);
      if (raw == null || raw.isEmpty) return;
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      _watched.clear();
      decoded.forEach((k, v) {
        _watched[k.toUpperCase()] = Map<String, dynamic>.from(v as Map);
      });
    } catch (_) {}
  }

  Future<void> _saveCache() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = jsonEncode(_watched);
      await prefs.setString(_cacheKey, raw);
    } catch (_) {}
  }
}
