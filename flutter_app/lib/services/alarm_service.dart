// Serviço de alarmes (stub básico)
class AlarmService {
  static bool isEnabled = true;
  
  void triggerAlarm({
    required String plate,
    required String camera,
    required double confidence,
    required String imageUrl,
    String? vehicleType,
  }) {
    // TODO: Implementar som de alarme
    print('🚨 ALARME: $plate em $camera (${(confidence * 100).toStringAsFixed(0)}%)');
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
