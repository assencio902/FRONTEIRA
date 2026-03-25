import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

// Serviço de histórico de alarmes (persistência local)
class AlarmHistoryService {
  static const _cacheKey = 'alarm_history_v1';
  static SharedPreferences? _prefs;
  static final List<Map<String, dynamic>> _cache = [];

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    final raw = _prefs?.getString(_cacheKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final data = jsonDecode(raw) as List<dynamic>;
      _cache
        ..clear()
        ..addAll(data.map((e) => Map<String, dynamic>.from(e as Map)));
    } catch (_) {
      _cache.clear();
    }
  }

  static List<Map<String, dynamic>> getHistory() {
    return List<Map<String, dynamic>>.from(_cache);
  }

  static void addAlarm(Map<String, dynamic> alarm) {
    final withTs = Map<String, dynamic>.from(alarm);
    withTs['created_at'] = withTs['created_at'] ?? DateTime.now().toIso8601String();
    _cache.insert(0, withTs);
    if (_cache.length > 400) _cache.removeLast();
    final raw = jsonEncode(_cache);
    _prefs?.setString(_cacheKey, raw);
  }
}
