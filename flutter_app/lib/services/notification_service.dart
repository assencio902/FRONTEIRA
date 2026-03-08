import 'dart:developer' as developer;
import 'dart:convert';
import 'dart:io';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../models/alert.dart';
import 'api.dart';

@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  // Background isolate: keep lightweight and avoid UI navigation here.
  if (Firebase.apps.isEmpty) {
    await Firebase.initializeApp();
  }
  developer.log('[NotificationService] onBackgroundMessage recebido: ${message.messageId} data=${message.data}');
}

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
  bool _initialized = false;
  bool _initializing = false;
  
  // Callback para processar alerta quando app está aberto
  void Function(AlertModel)? onAlertReceived;
  // Callback para abrir tela detalhada ao tocar na notificação
  void Function(AlertModel)? onAlertOpened;

  Future<void> initialize() async {
    if (_initialized) {
      developer.log('[NotificationService] Inicialização já concluída');
      return;
    }
    if (_initializing) {
      developer.log('[NotificationService] Inicialização já em andamento');
      return;
    }

    _initializing = true;
    try {
      // Inicializar Firebase
      if (Firebase.apps.isEmpty) {
        await Firebase.initializeApp();
        developer.log('[NotificationService] Firebase.initializeApp OK');
      } else {
        developer.log('[NotificationService] Firebase já inicializado (${Firebase.apps.length} app[s])');
      }
      _firebaseMessaging = FirebaseMessaging.instance;

      // Handler para mensagens quando app está em background/terminated (data-only).
      FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
      
      // Inicializar notificações locais
      await _initializeLocalNotifications();

      // Reagir a refresh de token do Firebase
      _firebaseMessaging.onTokenRefresh.listen((newToken) async {
        developer.log('[NotificationService] FCM Token atualizado (${newToken.length} chars)');
        await _registerTokenInBackend(newToken);
      });
      
      // Registrar FCM
      final settings = await _firebaseMessaging.requestPermission();
      developer.log('[NotificationService] Permissões: ${settings.authorizationStatus}');
      
      // Obter token e registrar no backend
      final token = await _firebaseMessaging.getToken();
      developer.log('[NotificationService] FCM getToken inicial: ${token == null ? "null" : "${token.length} chars"}');
      
      if (token != null) {
        await _registerTokenInBackend(token);
      }
      
      // Listeners para diferentes estados do app
      _setupMessageHandlers();
      _initialized = true;
      
      developer.log('[NotificationService] Inicializado com sucesso');
    } catch (e) {
      developer.log('[NotificationService] Erro na inicialização: $e', 
        name: 'NotificationService');
    } finally {
      _initializing = false;
    }
  }

  Future<bool> _ensureInitializedForTokenOps() async {
    if (_initialized) {
      return true;
    }
    await initialize();
    if (!_initialized) {
      developer.log('[NotificationService] Não foi possível inicializar Firebase/FCM para operação de token');
      return false;
    }
    return true;
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

  }

  /// Configurar handlers para mensagens em diferentes estados
  void _setupMessageHandlers() {
    // App fechado → abre ao tocar na notificação
    FirebaseMessaging.instance.getInitialMessage().then((RemoteMessage? message) {
      if (message != null) {
        developer.log('[NotificationService] getInitialMessage: ${message.data}');
        handleNotificationNavigation(message, source: 'getInitialMessage');
      }
    });
    
    // App em segundo plano → notificação recebida
    FirebaseMessaging.onMessage.listen((RemoteMessage message) {
      developer.log('[NotificationService] Mensagem recebida (app aberto): ${message.data}');
      _handleRemoteMessage(message, openedFromNotification: false, showLocalNotification: true);
    });
    
    // App em segundo plano → ao tocar na notificação
    FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
      developer.log('[NotificationService] onMessageOpenedApp: ${message.data}');
      handleNotificationNavigation(message, source: 'onMessageOpenedApp');
    });
  }

  AlertModel _alertFromPayload(Map<String, dynamic> data) {
    final detectedAt =
        (data['detected_at'] ?? data['occurred_at'] ?? data['timestamp'] ?? '').toString();
    final normalizedData = <String, dynamic>{
      ...data,
      'detected_at': detectedAt,
    };
    return AlertModel.fromJson(normalizedData);
  }

  void _openOrQueueAlert(AlertModel alert, {required String source}) {
    if (onAlertOpened != null) {
      developer.log('[NotificationService] Navegando para alerta (source=$source event_id=${alert.eventId})');
      onAlertOpened!(alert);
    } else {
      developer.log('[NotificationService] Callback de navegação ausente; alerta pendente (source=$source event_id=${alert.eventId})');
      _pendingOpenedAlert = alert;
    }
  }

  void handleNotificationNavigation(RemoteMessage message, {required String source}) {
    try {
      final alert = _alertFromPayload(message.data);
      developer.log(
        '[NotificationService] handleNotificationNavigation source=$source route=alert_detail event_id=${alert.eventId} plate=${alert.plate} image_url=${alert.imageUrl}',
      );
      _openOrQueueAlert(alert, source: source);
    } catch (e) {
      developer.log('[NotificationService] Falha ao navegar via RemoteMessage (source=$source): $e');
    }
  }

  void _handleNotificationNavigationFromPayloadString(String payload, {required String source}) {
    try {
      final data = jsonDecode(payload) as Map<String, dynamic>;
      final alert = _alertFromPayload(data);
      developer.log(
        '[NotificationService] handleNotificationNavigation payload source=$source route=alert_detail event_id=${alert.eventId} plate=${alert.plate} image_url=${alert.imageUrl}',
      );
      _openOrQueueAlert(alert, source: source);
    } catch (e) {
      developer.log('[NotificationService] Falha ao navegar via payload local (source=$source): $e');
    }
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
      final alert = _alertFromPayload(data);
      
      if (showLocalNotification) {
        await _showNotification(alert);
      }

      if (openedFromNotification) {
        _openOrQueueAlert(alert, source: 'remote_message_opened');
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
      final channelId = alert.isCritical ? 'critical_alerts' : 'normal_alerts';
      final importance = alert.isCritical ? Importance.max : Importance.defaultImportance;

      BigPictureStyleInformation? bigPictureStyle;
      if (alert.imageUrl.isNotEmpty) {
        final imagePath = await _downloadImageToTempFile(alert.imageUrl);
        if (imagePath != null) {
          developer.log('[NotificationService] BigPicture pronto para event_id=${alert.eventId} image_path=$imagePath');
          bigPictureStyle = BigPictureStyleInformation(
            FilePathAndroidBitmap(imagePath),
            contentTitle: alert.isCritical ? 'ALERTA CRITICO' : 'Deteccao',
            summaryText: '${alert.targetName} - Placa ${alert.plate}',
          );
        }
      }

      AndroidNotificationDetails androidDetails = AndroidNotificationDetails(
        channelId,
        alert.isCritical ? 'Alertas Críticos' : 'Alertas Comuns',
        importance: importance,
        priority: alert.isCritical ? Priority.max : Priority.defaultPriority,
        enableVibration: true,
        playSound: true,
        styleInformation: bigPictureStyle,
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
      developer.log('[NotificationService] Erro ao exibir notificação: $e', name: 'NotificationService');
    }
  }

  Future<String?> _downloadImageToTempFile(String imageUrl) async {
    try {
      developer.log('[NotificationService] Tentando baixar imagem da notificação: $imageUrl');
      final uri = Uri.tryParse(imageUrl);
      if (uri == null) {
        developer.log('[NotificationService] URL de imagem inválida: $imageUrl');
        return null;
      }
      final response = await http.get(uri).timeout(const Duration(seconds: 8));
      if (response.statusCode != 200 || response.bodyBytes.isEmpty) {
        developer.log('[NotificationService] Falha ao baixar imagem status=${response.statusCode} url=$imageUrl');
        return null;
      }

      final dir = Directory.systemTemp;
      final filePath = '${dir.path}\\notif_${DateTime.now().millisecondsSinceEpoch}.jpg';
      final file = File(filePath);
      await file.writeAsBytes(response.bodyBytes, flush: true);
      return file.path;
    } catch (e) {
      developer.log('[NotificationService] Falha ao baixar imagem da notificação: $e');
      return null;
    }
  }

  /// Callback quando usuário toca na notificação (foreground)
  void _handleNotificationTap(NotificationResponse response) {
    developer.log('[NotificationService] Notificação tocada: ${response.payload}');
    final payload = response.payload;
    if (payload == null || payload.isEmpty) return;
    _handleNotificationNavigationFromPayloadString(payload, source: 'local_notification_tap');
  }

  /// Callback quando usuário toca na notificação (background)
  @pragma('vm:entry-point')
  static void _handleBackgroundNotificationTap(NotificationResponse response) {
    developer.log('[NotificationService] Background notification tapped: ${response.payload}');
  }

  /// Registrar token FCM no backend
  Future<bool> _registerTokenInBackend(String token) async {
    try {
      // Só tenta registrar se tiver sessão válida
      final sessionValid = await Api.isSessionValid();
      if (!sessionValid) {
        developer.log('[NotificationService] Token JWT expirado, adiando registro FCM');
        return false;
      }

      if (token.isEmpty) {
        developer.log('[NotificationService] Token FCM vazio, ignorando registro');
        return false;
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
        developer.log('[NotificationService] Token FCM registrado no backend (device_id=$deviceId)');
        await _logTokenStatusFromBackend();
        return true;
      } else if (response.statusCode == 401) {
        developer.log('[NotificationService] 401 ao registrar token FCM - sessão expirada');
        return false;
      } else {
        developer.log('[NotificationService] Erro ao registrar token: ${response.statusCode} ${response.body}');
        return false;
      }
    } catch (e) {
      developer.log('[NotificationService] Erro ao registrar token no backend: $e');
      return false;
    }
  }

  /// Força sincronização do token atual com o backend (usar após login/restauração de sessão).
  Future<void> syncTokenWithBackend() async {
    try {
      final ready = await _ensureInitializedForTokenOps();
      if (!ready) {
        return;
      }

      final token = await _firebaseMessaging.getToken();
      if (token == null || token.isEmpty) {
        developer.log('[NotificationService] Sem token FCM disponível para sincronizar (getToken retornou null/vazio)');
        return;
      }
      final ok = await _registerTokenInBackend(token);
      developer.log('[NotificationService] syncTokenWithBackend finalizado (ok=$ok)');
    } catch (e) {
      developer.log('[NotificationService] Erro ao sincronizar token FCM: $e');
    }
  }

  /// Obter token FCM
  Future<String?> getFcmToken() async {
    final ready = await _ensureInitializedForTokenOps();
    if (!ready) {
      return null;
    }
    return await _firebaseMessaging.getToken();
  }

  Future<void> _logTokenStatusFromBackend() async {
    try {
      final response = await Api.get('/api/fcm/my-token-status');
      if (response.statusCode != 200) {
        developer.log('[NotificationService] Falha ao consultar status de token no backend: ${response.statusCode} ${response.body}');
        return;
      }
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      developer.log(
        '[NotificationService] Status token backend: active=${data['active_tokens']} inactive=${data['inactive_tokens']} total=${data['total_tokens']} user_id=${data['user_id']}',
      );
    } catch (e) {
      developer.log('[NotificationService] Erro ao consultar status de token no backend: $e');
    }
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
  Future<Map<String, dynamic>> triggerBackendTestAlert({required int alarmeId}) async {
    // Verificar se sessão está válida antes de chamar
    final sessionValid = await Api.isSessionValid();
    if (!sessionValid) {
      developer.log('[NotificationService] Token expirado ou ausente ao disparar teste');
      throw SessionExpiredException('Sessão expirada. Faça login novamente.');
    }

    final payload = {
      'alarme_id': alarmeId,
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

