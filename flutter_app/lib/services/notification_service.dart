import 'dart:developer' as developer;
import 'dart:convert';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../models/alert.dart';
import 'api.dart';

/// Serviço de notificações push e alertas críticos
class NotificationService {
  static final NotificationService _instance = NotificationService._internal();

  factory NotificationService() {
    return _instance;
  }

  NotificationService._internal();

  late FirebaseMessaging _firebaseMessaging;
  late FlutterLocalNotificationsPlugin _localNotifications;
  AlertModel? _pendingOpenedAlert;
  bool _useCustomAlarmSound = true;
  
  // Callback para processar alerta quando app está aberto
  void Function(AlertModel)? onAlertReceived;
  // Callback para abrir tela detalhada ao tocar na notificação
  void Function(AlertModel)? onAlertOpened;

  Future<void> initialize() async {
    try {
      // Inicializar Firebase
      await Firebase.initializeApp();
      _firebaseMessaging = FirebaseMessaging.instance;
      
      // Inicializar notificações locais
      await _initializeLocalNotifications();

      // Reagir a refresh de token do Firebase
      _firebaseMessaging.onTokenRefresh.listen((newToken) async {
        developer.log('[NotificationService] FCM Token atualizado');
        await _registerTokenInBackend(newToken);
      });
      
      // Registrar FCM
      final settings = await _firebaseMessaging.requestPermission();
      developer.log('[NotificationService] Permissões: ${settings.authorizationStatus}');
      
      // Obter token e registrar no backend
      final token = await _firebaseMessaging.getToken();
      developer.log('[NotificationService] FCM Token: $token');
      
      if (token != null) {
        await _registerTokenInBackend(token);
      }
      
      // Listeners para diferentes estados do app
      _setupMessageHandlers();
      
      developer.log('[NotificationService] Inicializado com sucesso');
    } catch (e) {
      developer.log('[NotificationService] Erro na inicialização: $e', 
        name: 'NotificationService');
    }
  }

  /// Configurar canal de notificação com alta prioridade para Android
  Future<void> _initializeLocalNotifications() async {
    _localNotifications = FlutterLocalNotificationsPlugin();
    
    // Configuração Android
    const androidInitializationSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    
    // Configuração iOS
    const DarwinInitializationSettings iosInitializationSettings = DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    );
    
    const InitializationSettings initializationSettings = InitializationSettings(
      android: androidInitializationSettings,
      iOS: iosInitializationSettings,
    );
    
    await _localNotifications.initialize(
      initializationSettings,
      onDidReceiveNotificationResponse: _handleNotificationTap,
      onDidReceiveBackgroundNotificationResponse: _handleBackgroundNotificationTap,
    );
    
    // Criar canal de notificação para alertas críticos
    const AndroidNotificationChannel criticalChannel = AndroidNotificationChannel(
      'critical_alerts',
      'Alertas Críticos',
      description: 'Notificações de detecção de veículos monitorados',
      importance: Importance.max,
      enableVibration: true,
      playSound: true,
      sound: RawResourceAndroidNotificationSound('alarm'),
    );
    
    await _localNotifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(criticalChannel);
    
    // Canal para alertas comuns
    const AndroidNotificationChannel normalChannel = AndroidNotificationChannel(
      'normal_alerts',
      'Alertas Comuns',
      description: 'Notificações gerais',
      importance: Importance.defaultImportance,
      enableVibration: true,
      playSound: true,
    );
    
    await _localNotifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(normalChannel);

    // Canal de fallback (som padrão), usado se houver falha com recurso customizado.
    const AndroidNotificationChannel criticalFallbackChannel = AndroidNotificationChannel(
      'critical_alerts_fallback',
      'Alertas Críticos (Fallback)',
      description: 'Canal de fallback para alertas críticos com som padrão do sistema',
      importance: Importance.max,
      enableVibration: true,
      playSound: true,
    );

    await _localNotifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(criticalFallbackChannel);
  }

  /// Configurar handlers para mensagens em diferentes estados
  void _setupMessageHandlers() {
    // App fechado → abre ao tocar na notificação
    FirebaseMessaging.instance.getInitialMessage().then((RemoteMessage? message) {
      if (message != null) {
        developer.log('[NotificationService] App aberto via notificação: ${message.data}');
        _handleRemoteMessage(message, openedFromNotification: true, showLocalNotification: false);
      }
    });
    
    // App em segundo plano → notificação recebida
    FirebaseMessaging.onMessage.listen((RemoteMessage message) {
      developer.log('[NotificationService] Mensagem recebida (app aberto): ${message.data}');
      _handleRemoteMessage(message, openedFromNotification: false, showLocalNotification: true);
    });
    
    // App em segundo plano → ao tocar na notificação
    FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
      developer.log('[NotificationService] Notificação tocada (app em background): ${message.data}');
      _handleRemoteMessage(message, openedFromNotification: true, showLocalNotification: false);
    });
  }

  /// Processar mensagem remota
  Future<void> _handleRemoteMessage(
    RemoteMessage message, {
    required bool openedFromNotification,
    required bool showLocalNotification,
  }) async {
    try {
      final data = message.data;
      developer.log('[NotificationService] Processando alerta: $data');
      
      // Extrair dados
      final plate = data['plate'] ?? '';
      final targetName = data['target_name'] ?? '';
      final cameraName = data['camera_name'] ?? '';
      final detectedAt = data['detected_at'] ?? '';
      final imageUrl = data['image_url'] ?? '';
      final eventId = data['event_id'] ?? '';
      final city = data['city'] ?? '';
      final riskLevel = data['risk_level'] ?? 'normal';
      final type = data['alert_type'] ?? data['type'] ?? 'normal_alert';
      
      final alert = AlertModel(
        plate: plate,
        targetName: targetName,
        cameraName: cameraName,
        detectedAt: detectedAt,
        imageUrl: imageUrl,
        eventId: eventId,
        city: city,
        riskLevel: riskLevel,
        isCritical: type == 'critical_alert',
      );
      
      if (showLocalNotification) {
        await _showNotification(alert);
      }

      if (openedFromNotification) {
        if (onAlertOpened != null) {
          onAlertOpened!(alert);
        } else {
          _pendingOpenedAlert = alert;
        }
      } else if (onAlertReceived != null) {
        onAlertReceived!(alert);
      }
    } catch (e) {
      developer.log('[NotificationService] Erro ao processar alerta: $e',
        name: 'NotificationService');
    }
  }

  AlertModel? consumePendingOpenedAlert() {
    final pending = _pendingOpenedAlert;
    _pendingOpenedAlert = null;
    return pending;
  }

  /// Exibir notificação local
  Future<void> _showNotification(AlertModel alert) async {
    try {
      var channelId = alert.isCritical ? 'critical_alerts' : 'normal_alerts';
      final importance = alert.isCritical ? Importance.max : Importance.defaultImportance;
      RawResourceAndroidNotificationSound? androidSound;
      if (alert.isCritical && _useCustomAlarmSound) {
        androidSound = const RawResourceAndroidNotificationSound('alarm');
      }
      if (alert.isCritical && !_useCustomAlarmSound) {
        channelId = 'critical_alerts_fallback';
      }

      AndroidNotificationDetails androidDetails = AndroidNotificationDetails(
        channelId,
        alert.isCritical ? 'Alertas Críticos' : 'Alertas Comuns',
        importance: importance,
        priority: alert.isCritical ? Priority.max : Priority.defaultPriority,
        enableVibration: true,
        playSound: true,
        sound: androidSound,
      );
      
      const iosDetails = DarwinNotificationDetails(
        presentAlert: true,
        presentBadge: true,
        presentSound: true,
        sound: 'notification.caf',
      );
      
      final notificationDetails = NotificationDetails(
        android: androidDetails,
        iOS: iosDetails,
      );

      final payload = jsonEncode(alert.toJson());
      
      await _localNotifications.show(
        alert.eventId.hashCode,
        alert.isCritical ? 'ALERTA CRITICO' : 'Deteccao',
        '${alert.targetName} - Placa ${alert.plate}',
        notificationDetails,
        payload: payload,
      );
      
      developer.log('[NotificationService] Notificação exibida: ${alert.plate}');
    } catch (e) {
      // fallback para o som padrão caso o recurso customizado falhe.
      if (alert.isCritical && _useCustomAlarmSound) {
        _useCustomAlarmSound = false;
        developer.log('[NotificationService] Falha com som customizado, usando fallback padrão');
        final androidDetails = AndroidNotificationDetails(
          'critical_alerts_fallback',
          'Alertas Críticos (Fallback)',
          importance: Importance.max,
          priority: Priority.max,
          enableVibration: true,
          playSound: true,
        );
        const iosDetails = DarwinNotificationDetails(
          presentAlert: true,
          presentBadge: true,
          presentSound: true,
          sound: 'default',
        );
        await _localNotifications.show(
          alert.eventId.hashCode,
          'ALERTA CRITICO',
          '${alert.targetName} - Placa ${alert.plate}',
          NotificationDetails(android: androidDetails, iOS: iosDetails),
          payload: jsonEncode(alert.toJson()),
        );
        return;
      }
      developer.log('[NotificationService] Erro ao exibir notificação: $e', name: 'NotificationService');
    }
  }

  /// Callback quando usuário toca na notificação (foreground)
  void _handleNotificationTap(NotificationResponse response) {
    developer.log('[NotificationService] Notificação tocada: ${response.payload}');
    final payload = response.payload;
    if (payload == null || payload.isEmpty) return;
    try {
      final data = jsonDecode(payload) as Map<String, dynamic>;
      final alert = AlertModel.fromJson(data);
      if (onAlertOpened != null) {
        onAlertOpened!(alert);
      } else {
        _pendingOpenedAlert = alert;
      }
    } catch (e) {
      developer.log('[NotificationService] Payload inválido na notificação: $e');
    }
  }

  /// Callback quando usuário toca na notificação (background)
  @pragma('vm:entry-point')
  static void _handleBackgroundNotificationTap(NotificationResponse response) {
    developer.log('[NotificationService] Background notification tapped: ${response.payload}');
  }

  /// Registrar token FCM no backend
  Future<void> _registerTokenInBackend(String token) async {
    try {
      // Só tenta registrar se tiver sessão válida
      final sessionValid = await Api.isSessionValid();
      if (!sessionValid) {
        developer.log('[NotificationService] Token JWT expirado, adiando registro FCM');
        return;
      }

      // Gerar ID único do dispositivo
      final prefs = await SharedPreferences.getInstance();
      String? deviceId = prefs.getString('device_id');
      
      if (deviceId == null) {
        deviceId = const Uuid().v4();
        await prefs.setString('device_id', deviceId);
      }
      
      // Registrar token
      final response = await Api.post(
        '/api/fcm/register-token',
        {
          'fcm_token': token,
          'device_id': deviceId,
        },
      );
      
      if (response.statusCode == 200) {
        developer.log('[NotificationService] Token FCM registrado no backend');
      } else if (response.statusCode == 401) {
        developer.log('[NotificationService] 401 ao registrar token FCM - sessão expirada');
      } else {
        developer.log('[NotificationService] Erro ao registrar token: ${response.statusCode} ${response.body}');
      }
    } catch (e) {
      developer.log('[NotificationService] Erro ao registrar token no backend: $e');
    }
  }

  /// Obter token FCM
  Future<String?> getFcmToken() async {
    return await _firebaseMessaging.getToken();
  }

  /// Disparar alerta manualmente para testes
  Future<void> triggerTestAlert({required bool isCritical}) async {
    final alert = AlertModel(
      plate: 'ABC1234',
      targetName: 'Teste - Alvo Monitorado',
      cameraName: 'Câmera Rodovia 1',
      detectedAt: DateTime.now().toIso8601String(),
      imageUrl: '',
      eventId: 'test-${DateTime.now().millisecondsSinceEpoch}',
      city: 'Cuiabá',
      riskLevel: isCritical ? 'high' : 'normal',
      isCritical: isCritical,
    );
    
    await _showNotification(alert);
    
    developer.log('[NotificationService] Alerta de teste disparado (crítico: $isCritical)');
  }

  /// Dispara alerta de teste pelo backend (fluxo completo push + app).
  Future<Map<String, dynamic>> triggerBackendTestAlert() async {
    // Verificar se sessão está válida antes de chamar
    final sessionValid = await Api.isSessionValid();
    if (!sessionValid) {
      developer.log('[NotificationService] Token expirado ou ausente ao disparar teste');
      throw SessionExpiredException('Sessão expirada. Faça login novamente.');
    }

    final payload = {
      'plate': 'ABC1234',
      'target_name': 'Teste Alvo Monitorado',
      'camera_name': 'Camera Teste',
      'detected_at': DateTime.now().toIso8601String(),
      'image_url': '',
      'event_id': 'manual-${DateTime.now().millisecondsSinceEpoch}',
      'city': 'Cuiaba',
      'risk_level': 'high',
      'alert_type': 'critical_alert',
    };

    final response = await Api.post('/api/fcm/send-alert', payload);
    if (response.statusCode == 401) {
      throw SessionExpiredException('Sessão expirada. Faça login novamente.');
    }
    if (response.statusCode >= 400) {
      throw Exception('Falha no envio de alerta (${response.statusCode}): ${response.body}');
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }
}

/// Exceção específica para sessão expirada, permitindo tratamento diferenciado na UI.
class SessionExpiredException implements Exception {
  final String message;
  SessionExpiredException(this.message);
  @override
  String toString() => message;
}

