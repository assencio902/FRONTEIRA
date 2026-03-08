/// Modelo para alertas críticos de detecção
class AlertModel {
  final String plate;
  final String targetName;
  final String cameraName;
  final String detectedAt;
  final String imageUrl;
  final String eventId;
  final String city;
  final String riskLevel;
  final bool isCritical;

  AlertModel({
    required this.plate,
    required this.targetName,
    required this.cameraName,
    required this.detectedAt,
    required this.imageUrl,
    required this.eventId,
    required this.city,
    required this.riskLevel,
    required this.isCritical,
  });

  factory AlertModel.fromJson(Map<String, dynamic> json) {
    final alertType = (json['alert_type'] ?? json['type'] ?? '').toString();
    final detectedAt = (json['detected_at'] ?? json['occurred_at'] ?? json['timestamp'] ?? '').toString();
    return AlertModel(
      plate: (json['plate'] ?? '').toString(),
      targetName: (json['target_name'] ?? '').toString(),
      cameraName: (json['camera_name'] ?? '').toString(),
      detectedAt: detectedAt,
      imageUrl: (json['image_url'] ?? '').toString(),
      eventId: (json['event_id'] ?? '').toString(),
      city: (json['city'] ?? 'N/A').toString(),
      riskLevel: (json['risk_level'] ?? 'normal').toString(),
      isCritical: alertType == 'critical_alert',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'plate': plate,
      'target_name': targetName,
      'camera_name': cameraName,
      'detected_at': detectedAt,
      'image_url': imageUrl,
      'event_id': eventId,
      'city': city,
      'risk_level': riskLevel,
      'alert_type': isCritical ? 'critical_alert' : 'normal_alert',
      'type': isCritical ? 'critical_alert' : 'normal_alert',
      'screen': 'alert_detail',
      'route': '/alert-detail',
      'occurred_at': detectedAt,
    };
  }
}
