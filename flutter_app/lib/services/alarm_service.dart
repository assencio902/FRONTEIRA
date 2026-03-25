import 'alarm_history_service.dart';

// Serviço de alarmes
class AlarmService {
  static bool isEnabled = true;

  void triggerAlarm({
    required String plate,
    required String camera,
    required double confidence,
    required String imageUrl,
    String? vehicleType,
    String? targetName,
  }) {
    final pct = (confidence * 100).toStringAsFixed(0);
    // TODO: Implementar som de alarme
    print('🚨 ALARME: $plate em $camera ($pct%)');
    AlarmHistoryService.addAlarm({
      'plate': plate,
      'camera': camera,
      'confidence': confidence,
      'image_url': imageUrl,
      'vehicle_type': vehicleType,
      'target_name': targetName,
    });
  }

  static void playAlarm() {
    // TODO: Implementar som de alarme
  }

  static void stopAlarm() {
    // TODO: Parar som de alarme
  }

  void dispose() {
    // TODO: Limpar recursos
  }
}
