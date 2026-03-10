import 'dart:async';
import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../models/alert.dart';
import 'api.dart';

const String _criticalChannelId = 'critical_alerts';
// Novo canal para alarmes com som/vibração máxima. Usamos um channelId novo
// para evitar problemas de cache caso o canal antigo exista sem som.
const String _alarmChannelId = 'alarm_high_importance_v2';
const String _normalChannelId = 'normal_alerts';
const String _androidNotificationIcon = '@mipmap/ic_launcher';

const AndroidNotificationChannel _criticalNotificationChannel =
    AndroidNotificationChannel(
      _criticalChannelId,
      'Alertas Críticos',
      description: 'Notificações de detecção de veículos monitorados',
      importance: Importance.max,
      playSound: true,
      enableVibration: true,
    );

// Canal novo e garantido para alarmes (som e vibração máximos)
const AndroidNotificationChannel _alarmNotificationChannel =
    AndroidNotificationChannel(
      _alarmChannelId,
      'Alarmes Críticos',
      description: 'Notificações de alarmes críticos com som e vibração',
      importance: Importance.max,
      playSound: true,
      enableVibration: true,
    );

const AndroidNotificationChannel _normalNotificationChannel =
    AndroidNotificationChannel(
      _normalChannelId,
      'Alertas Comuns',
      description: 'Notificações gerais do aplicativo',
      importance: Importance.high,
      playSound: true,
      enableVibration: true,
    );

@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  if (Firebase.apps.isEmpty) {
    await Firebase.initializeApp();
  }
  developer.log(
    '[NotificationService] background_message id=${message.messageId} '
    'kind=${NotificationService.describeMessageKind(message)} '
    'title=${message.notification?.title ?? ""} '
    'body=${message.notification?.body ?? ""} '
    'data=${message.data}',
  );

  if (message.notification == null && message.data.isNotEmpty) {
    await NotificationService.showBackgroundDataNotification(message);
  }
}

class PushDiagnostics {
  final String packageName;
  final String? fcmToken;
  final String notificationPermissionStatus;
  final bool firebaseInitialized;
  final bool autoInitEnabled;
  final String deviceId;
  final bool? lastBackendSyncOk;

  const PushDiagnostics({
    required this.packageName,
    required this.fcmToken,
    required this.notificationPermissionStatus,
    required this.firebaseInitialized,
    required this.autoInitEnabled,
    required this.deviceId,
    required this.lastBackendSyncOk,
  });
}

/// Serviço de notificações push e alertas críticos
class NotificationService {
  static final NotificationService _instance = NotificationService._internal();
  static final FlutterLocalNotificationsPlugin _backgroundLocalNotifications =
      FlutterLocalNotificationsPlugin();

  static bool _backgroundNotificationsReady = false;

  factory NotificationService() {
    return _instance;
  }

  NotificationService._internal();

  late FirebaseMessaging _firebaseMessaging;
  late FlutterLocalNotificationsPlugin _localNotifications;
  AlertModel? _pendingOpenedAlert;
  bool _initialized = false;
  bool _initializing = false;
  bool _messageHandlersConfigured = false;
  bool _localNotificationsInitialized = false;
  bool _firebaseReady = false;
  bool? _lastBackendSyncOk;
  NotificationSettings? _lastNotificationSettings;
  StreamSubscription<String>? _tokenRefreshSubscription;
  
  // Callback para processar alerta quando app está aberto
  void Function(AlertModel)? onAlertReceived;
  // Callback para abrir tela detalhada ao tocar na notificação
  void Function(AlertModel)? onAlertOpened;

  Future<void> initialize({String reason = 'initialize'}) async {
    if (_initialized) {
      developer.log('[NotificationService] Inicialização já concluída (reason=$reason)');
      return;
    }
    if (_initializing) {
      developer.log('[NotificationService] Inicialização já em andamento (reason=$reason)');
      return;
    }

    _initializing = true;
    try {
      await _ensureFirebaseReady(reason: reason);
      _firebaseMessaging = FirebaseMessaging.instance;
      await _firebaseMessaging.setAutoInitEnabled(true);
      developer.log('[NotificationService] FirebaseMessaging auto-init habilitado');

      FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);

      await _initializeLocalNotifications();
      await requestNotificationPermission(reason: 'initialize:$reason');
      await _logCurrentToken(reason: 'initialize:$reason');

      _tokenRefreshSubscription ??=
          _firebaseMessaging.onTokenRefresh.listen((newToken) async {
            developer.log('[NotificationService] fcm_token_refresh token=$newToken');
            await _registerTokenInBackend(newToken, reason: 'onTokenRefresh');
          });

      _setupMessageHandlers();
      _initialized = true;

      await syncTokenWithBackend(reason: 'initialize:$reason');
      developer.log('[NotificationService] Inicializado com sucesso (reason=$reason)');
    } catch (e) {
      developer.log(
        '[NotificationService] Erro na inicialização (reason=$reason): $e',
        name: 'NotificationService',
      );
    } finally {
      _initializing = false;
    }
  }

  Future<void> handleAppOpened({String reason = 'app_open'}) async {
    developer.log('[NotificationService] handleAppOpened reason=$reason');
    await initialize(reason: reason);
    await syncTokenWithBackend(reason: reason);
    await collectDiagnostics(reason: reason, logResult: true);
  }

  Future<void> _ensureFirebaseReady({required String reason}) async {
    if (Firebase.apps.isEmpty) {
      await Firebase.initializeApp();
      developer.log('[NotificationService] Firebase.initializeApp OK (reason=$reason)');
    } else {
      developer.log(
        '[NotificationService] Firebase já inicializado (${Firebase.apps.length} app[s]) (reason=$reason)',
      );
    }
    _firebaseReady = Firebase.apps.isNotEmpty;
  }

  Future<bool> _ensureInitializedForTokenOps() async {
    if (_initialized) {
      return true;
    }
    await initialize(reason: 'token_op');
    if (!_initialized) {
      developer.log('[NotificationService] Não foi possível inicializar Firebase/FCM para operação de token');
      return false;
    }
    return true;
  }

  /// Configurar canal de notificação com alta prioridade para Android
  Future<void> _initializeLocalNotifications() async {
    if (_localNotificationsInitialized) {
      return;
    }

    _localNotifications = FlutterLocalNotificationsPlugin();
    
    const androidInitializationSettings = AndroidInitializationSettings(_androidNotificationIcon);

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
    await _createAndroidChannels(_localNotifications);
    _localNotificationsInitialized = true;
    developer.log('[NotificationService] Canais Android inicializados');
  }

  /// Configurar handlers para mensagens em diferentes estados
  void _setupMessageHandlers() {
    if (_messageHandlersConfigured) {
      return;
    }

    FirebaseMessaging.instance.getInitialMessage().then((RemoteMessage? message) {
      if (message != null) {
        developer.log(
          '[NotificationService] notification_open source=getInitialMessage '
          'id=${message.messageId} kind=${describeMessageKind(message)} data=${message.data}',
        );
        handleNotificationNavigation(message, source: 'getInitialMessage');
      }
    });

    FirebaseMessaging.onMessage.listen((RemoteMessage message) {
      _handleRemoteMessage(
        message,
        phase: 'foreground',
        openedFromNotification: false,
        showLocalNotification: true,
      );
    });

    FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
      developer.log(
        '[NotificationService] notification_open source=onMessageOpenedApp '
        'id=${message.messageId} kind=${describeMessageKind(message)} data=${message.data}',
      );
      handleNotificationNavigation(message, source: 'onMessageOpenedApp');
    });

    _messageHandlersConfigured = true;
  }

  static String describeMessageKind(RemoteMessage message) {
    final hasNotification = message.notification != null;
    final hasData = message.data.isNotEmpty;
    if (hasNotification && hasData) {
      return 'notification+data';
    }
    if (hasNotification) {
      return 'notification_only';
    }
    if (hasData) {
      return 'data_only';
    }
    return 'empty';
  }

  static Future<void> _createAndroidChannels(
    FlutterLocalNotificationsPlugin plugin,
  ) async {
    final androidPlugin =
        plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    await androidPlugin?.createNotificationChannel(_criticalNotificationChannel);
    await androidPlugin?.createNotificationChannel(_normalNotificationChannel);
  }

  static Future<void> _ensureBackgroundNotificationsReady() async {
    if (_backgroundNotificationsReady) {
      return;
    }

    const initializationSettings = InitializationSettings(
      android: AndroidInitializationSettings(_androidNotificationIcon),
      iOS: DarwinInitializationSettings(),
    );

    await _backgroundLocalNotifications.initialize(
      initializationSettings,
      onDidReceiveBackgroundNotificationResponse: _handleBackgroundNotificationTap,
    );
    await _createAndroidChannels(_backgroundLocalNotifications);
    _backgroundNotificationsReady = true;
  }

  static Future<void> showBackgroundDataNotification(RemoteMessage message) async {
    await _ensureBackgroundNotificationsReady();
    final alert = buildAlertFromMessage(message);
    await _showNotificationWithPlugin(
      _backgroundLocalNotifications,
      alert,
      logPrefix: '[NotificationService] background_local_notification',
      titleOverride: message.notification?.title,
      bodyOverride: message.notification?.body,
    );
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

  static AlertModel buildAlertFromMessage(RemoteMessage message) {
    final data = Map<String, dynamic>.from(message.data);
    final title = message.notification?.title?.trim() ?? '';
    final body = message.notification?.body?.trim() ?? '';
    final inferredTargetName = _extractTargetName(body, fallbackTitle: title);
    final inferredPlate = _extractPlate(body);
    final explicitType = (data['alert_type'] ?? data['type'] ?? '').toString();
    final isCritical = explicitType.isNotEmpty
        ? explicitType == 'critical_alert'
        : title.toUpperCase().contains('ALERTA');

    final normalizedData = <String, dynamic>{
      ...data,
      'plate': (data['plate'] ?? inferredPlate).toString(),
      'target_name': (data['target_name'] ?? inferredTargetName).toString(),
      'camera_name': (data['camera_name'] ?? data['camera'] ?? '').toString(),
      'detected_at': (
        data['detected_at'] ?? data['occurred_at'] ?? data['timestamp'] ?? DateTime.now().toIso8601String()
      ).toString(),
      'image_url': (data['image_url'] ?? data['image'] ?? '').toString(),
      'event_id': (data['event_id'] ?? message.messageId ?? 'fcm-${DateTime.now().millisecondsSinceEpoch}').toString(),
      'city': (data['city'] ?? 'N/A').toString(),
      'risk_level': (data['risk_level'] ?? (isCritical ? 'high' : 'normal')).toString(),
      'alert_type': explicitType.isNotEmpty
          ? explicitType
          : (isCritical ? 'critical_alert' : 'normal_alert'),
      'type': explicitType.isNotEmpty
          ? explicitType
          : (isCritical ? 'critical_alert' : 'normal_alert'),
      'screen': (data['screen'] ?? 'alert_detail').toString(),
      'route': (data['route'] ?? '/alert-detail').toString(),
      'occurred_at': (
        data['occurred_at'] ?? data['detected_at'] ?? data['timestamp'] ?? DateTime.now().toIso8601String()
      ).toString(),
    };

    return AlertModel.fromJson(normalizedData);
  }

  static String _extractTargetName(String body, {required String fallbackTitle}) {
    if (body.isEmpty) {
      return fallbackTitle;
    }
    const marker = ' - Placa ';
    final idx = body.indexOf(marker);
    if (idx > 0) {
      return body.substring(0, idx).trim();
    }
    return body;
  }

  static String _extractPlate(String body) {
    if (body.isEmpty) {
      return '';
    }
    final match = RegExp(r'placa\s+([a-z0-9-]{4,})', caseSensitive: false).firstMatch(body);
    return match?.group(1)?.toUpperCase() ?? '';
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
      final alert = message.data.isNotEmpty
          ? _alertFromPayload(message.data)
          : buildAlertFromMessage(message);
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
    required String phase,
    required bool openedFromNotification,
    required bool showLocalNotification,
  }) async {
    try {
      developer.log(
        '[NotificationService] ${phase}_message id=${message.messageId} '
        'kind=${describeMessageKind(message)} '
        'title=${message.notification?.title ?? ""} '
        'body=${message.notification?.body ?? ""} '
        'data=${message.data}',
      );
      final data = message.data;
      final fallbackTitle = (data['title'] ?? '').toString().trim();
      final fallbackBody = (data['body'] ?? '').toString().trim();
      final titleOverride =
          message.notification?.title?.trim().isNotEmpty == true
          ? message.notification!.title!.trim()
          : (fallbackTitle.isNotEmpty ? fallbackTitle : 'Novo alarme');
      final bodyOverride =
          message.notification?.body?.trim().isNotEmpty == true
          ? message.notification!.body!.trim()
          : (fallbackBody.isNotEmpty ? fallbackBody : 'Alerta recebido');

      developer.log(
        '[NotificationService] ${phase}_display title=$titleOverride body=$bodyOverride event_id=${data['event_id'] ?? message.messageId}',
      );
      final alert = buildAlertFromMessage(message);
      
      if (showLocalNotification) {
        await _showNotification(
          alert,
          titleOverride: titleOverride,
          bodyOverride: bodyOverride,
        );
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
  Future<void> _showNotification(
    AlertModel alert, {
    String? titleOverride,
    String? bodyOverride,
  }) async {
    await _showNotificationWithPlugin(
      _localNotifications,
      alert,
      titleOverride: titleOverride,
      bodyOverride: bodyOverride,
      logPrefix: '[NotificationService] local_notification',
    );
  }

  static Future<void> _showNotificationWithPlugin(
    FlutterLocalNotificationsPlugin plugin,
    AlertModel alert, {
    String? titleOverride,
    String? bodyOverride,
    required String logPrefix,
  }) async {
    try {
      final channelId = alert.isCritical ? _criticalChannelId : _normalChannelId;
      final importance = alert.isCritical ? Importance.max : Importance.high;
      final title = titleOverride?.trim().isNotEmpty == true
          ? titleOverride!.trim()
          : (alert.isCritical ? 'ALERTA CRITICO' : 'Deteccao');
      final body = bodyOverride?.trim().isNotEmpty == true
          ? bodyOverride!.trim()
          : '${alert.targetName} - Placa ${alert.plate}';

      BigPictureStyleInformation? bigPictureStyle;
      if (alert.imageUrl.isNotEmpty) {
        final imagePath = await _downloadImageToTempFileStatic(alert.imageUrl);
        if (imagePath != null) {
          developer.log('$logPrefix big_picture_ready event_id=${alert.eventId} image_path=$imagePath');
          bigPictureStyle = BigPictureStyleInformation(
            FilePathAndroidBitmap(imagePath),
            contentTitle: title,
            summaryText: body,
          );
        }
      }

      AndroidNotificationDetails androidDetails = AndroidNotificationDetails(
        channelId,
        alert.isCritical ? 'Alertas Críticos' : 'Alertas Comuns',
        importance: importance,
        priority: alert.isCritical ? Priority.max : Priority.high,
        enableVibration: true,
        playSound: true,
        styleInformation: bigPictureStyle,
        icon: _androidNotificationIcon,
        category: alert.isCritical
            ? AndroidNotificationCategory.alarm
            : AndroidNotificationCategory.message,
        visibility: NotificationVisibility.public,
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
      
      await plugin.show(
        alert.eventId.hashCode,
        title,
        body,
        notificationDetails,
        payload: payload,
      );
      
      developer.log('$logPrefix shown event_id=${alert.eventId} plate=${alert.plate} channel=$channelId');
    } catch (e) {
      developer.log('$logPrefix error=$e', name: 'NotificationService');
    }
  }

  static Future<String?> _downloadImageToTempFileStatic(String imageUrl) async {
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
    developer.log('[NotificationService] notification_open source=local_notification_tap payload=${response.payload}');
    final payload = response.payload;
    if (payload == null || payload.isEmpty) return;
    _handleNotificationNavigationFromPayloadString(payload, source: 'local_notification_tap');
  }

  /// Callback quando usuário toca na notificação (background)
  @pragma('vm:entry-point')
  static void _handleBackgroundNotificationTap(NotificationResponse response) {
    developer.log('[NotificationService] notification_open source=background_local_notification_tap payload=${response.payload}');
  }

  Future<NotificationSettings> requestNotificationPermission({String reason = 'manual'}) async {
    final ready = await _ensureInitializedForPermissionOps();
    if (!ready) {
      return _lastNotificationSettings ??
          const NotificationSettings(
            authorizationStatus: AuthorizationStatus.notDetermined,
            alert: AppleNotificationSetting.notSupported,
            announcement: AppleNotificationSetting.notSupported,
            badge: AppleNotificationSetting.notSupported,
            carPlay: AppleNotificationSetting.notSupported,
            lockScreen: AppleNotificationSetting.notSupported,
            notificationCenter: AppleNotificationSetting.notSupported,
            showPreviews: AppleShowPreviewSetting.never,
            sound: AppleNotificationSetting.notSupported,
            timeSensitive: AppleNotificationSetting.notSupported,
            criticalAlert: AppleNotificationSetting.notSupported,
          );
    }

    final settings = await _firebaseMessaging.requestPermission(
      alert: true,
      announcement: false,
      badge: true,
      carPlay: false,
      criticalAlert: false,
      provisional: false,
      sound: true,
    );
    _lastNotificationSettings = settings;
    developer.log(
      '[NotificationService] notification_permission reason=$reason '
      'status=${_authorizationStatusLabel(settings.authorizationStatus)}',
    );
    return settings;
  }

  Future<bool> _ensureInitializedForPermissionOps() async {
    if (_initialized) {
      return true;
    }
    await initialize(reason: 'permission_op');
    return _initialized;
  }

  String _authorizationStatusLabel(AuthorizationStatus status) {
    switch (status) {
      case AuthorizationStatus.authorized:
        return 'authorized';
      case AuthorizationStatus.denied:
        return 'denied';
      case AuthorizationStatus.notDetermined:
        return 'notDetermined';
      case AuthorizationStatus.provisional:
        return 'provisional';
    }
  }

  /// Registrar token FCM no backend
  Future<bool> _registerTokenInBackend(String token, {required String reason}) async {
    try {
      final sessionValid = await Api.isSessionValid();
      if (!sessionValid) {
        _lastBackendSyncOk = false;
        developer.log('[NotificationService] JWT ausente/expirado; adiando registro FCM (reason=$reason)');
        return false;
      }

      if (token.isEmpty) {
        _lastBackendSyncOk = false;
        developer.log('[NotificationService] Token FCM vazio, ignorando registro');
        return false;
      }

      final deviceId = await _getOrCreateDeviceId();
      final response = await Api.post(
        '/api/fcm/register-token',
        {
          'fcm_token': token,
          'device_id': deviceId,
        },
      );
      
      if (response.statusCode == 200) {
        _lastBackendSyncOk = true;
        developer.log(
          '[NotificationService] backend_token_sync ok=true reason=$reason device_id=$deviceId token=$token',
        );
        await _logTokenStatusFromBackend();
        return true;
      } else if (response.statusCode == 401) {
        _lastBackendSyncOk = false;
        developer.log('[NotificationService] 401 ao registrar token FCM - sessão expirada');
        return false;
      } else {
        _lastBackendSyncOk = false;
        developer.log('[NotificationService] Erro ao registrar token: ${response.statusCode} ${response.body}');
        return false;
      }
    } catch (e) {
      _lastBackendSyncOk = false;
      developer.log('[NotificationService] Erro ao registrar token no backend: $e');
      return false;
    }
  }

  /// Força sincronização do token atual com o backend (usar após login/restauração de sessão).
  Future<bool> syncTokenWithBackend({String reason = 'manual'}) async {
    try {
      final ready = await _ensureInitializedForTokenOps();
      if (!ready) {
        return false;
      }

      final token = await _logCurrentToken(reason: 'sync:$reason');
      if (token == null || token.isEmpty) {
        developer.log('[NotificationService] Sem token FCM disponível para sincronizar (getToken retornou null/vazio)');
        _lastBackendSyncOk = false;
        return false;
      }
      final ok = await _registerTokenInBackend(token, reason: reason);
      developer.log('[NotificationService] syncTokenWithBackend finalizado (ok=$ok reason=$reason)');
      return ok;
    } catch (e) {
      developer.log('[NotificationService] Erro ao sincronizar token FCM: $e');
      _lastBackendSyncOk = false;
      return false;
    }
  }

  /// Obter token FCM
  Future<String?> getFcmToken() async {
    final ready = await _ensureInitializedForTokenOps();
    if (!ready) {
      return null;
    }
    return _logCurrentToken(reason: 'get_fcm_token');
  }

  Future<String?> _logCurrentToken({required String reason}) async {
    final token = await _firebaseMessaging.getToken();
    developer.log('[NotificationService] current_fcm_token reason=$reason token=${token ?? "null"}');
    return token;
  }

  Future<String> _getOrCreateDeviceId() async {
    final prefs = await SharedPreferences.getInstance();
    var deviceId = prefs.getString('device_id');
    if (deviceId == null || deviceId.isEmpty) {
      deviceId = const Uuid().v4();
      await prefs.setString('device_id', deviceId);
    }
    return deviceId;
  }

  Future<PushDiagnostics> collectDiagnostics({
    String reason = 'manual',
    bool logResult = false,
  }) async {
    await initialize(reason: 'diagnostics:$reason');
    final packageInfo = await PackageInfo.fromPlatform();
    final notificationSettings = await _firebaseMessaging.getNotificationSettings();
    final autoInitEnabled = _firebaseMessaging.isAutoInitEnabled;
    final token = await _firebaseMessaging.getToken();
    final deviceId = await _getOrCreateDeviceId();

    _lastNotificationSettings = notificationSettings;
    _firebaseReady = Firebase.apps.isNotEmpty;

    final diagnostics = PushDiagnostics(
      packageName: packageInfo.packageName,
      fcmToken: token,
      notificationPermissionStatus: _authorizationStatusLabel(
        notificationSettings.authorizationStatus,
      ),
      firebaseInitialized: _firebaseReady,
      autoInitEnabled: autoInitEnabled,
      deviceId: deviceId,
      lastBackendSyncOk: _lastBackendSyncOk,
    );

    if (logResult) {
      developer.log(
        '[NotificationService] diagnostics reason=$reason '
        'package=${diagnostics.packageName} '
        'firebase_initialized=${diagnostics.firebaseInitialized} '
        'permission=${diagnostics.notificationPermissionStatus} '
        'auto_init=${diagnostics.autoInitEnabled} '
        'device_id=${diagnostics.deviceId} '
        'token=${diagnostics.fcmToken ?? "null"} '
        'backend_sync_ok=${diagnostics.lastBackendSyncOk}',
      );
    }

    return diagnostics;
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

  /// Dispara teste de push para o próprio usuário/dispositivo autenticado.
  Future<Map<String, dynamic>> triggerSelfTestPush({
    String? deviceId,
    String title = 'Teste Push BPFRON',
    String body = 'Mensagem de teste enviada pelo backend',
  }) async {
    final sessionValid = await Api.isSessionValid();
    if (!sessionValid) {
      developer.log('[NotificationService] Sessão inválida para test-self');
      throw SessionExpiredException('Sessão expirada. Faça login novamente.');
    }

    final payload = <String, dynamic>{
      'title': title,
      'body': body,
      'event_id': 'self-${DateTime.now().millisecondsSinceEpoch}',
    };
    if (deviceId != null && deviceId.trim().isNotEmpty) {
      payload['device_id'] = deviceId.trim();
    }

    developer.log('[NotificationService] test-self payload=$payload');
    final response = await Api.post('/api/fcm/test-self', payload);
    if (response.statusCode == 401) {
      throw SessionExpiredException('Sessão expirada. Faça login novamente.');
    }
    if (response.statusCode >= 400) {
      throw Exception('Falha no test-self (${response.statusCode}): ${response.body}');
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    developer.log('[NotificationService] test-self resultado=$data');
    return data;
  }
}

/// Exceção específica para sessão expirada, permitindo tratamento diferenciado na UI.
class SessionExpiredException implements Exception {
  final String message;
  SessionExpiredException(this.message);
  @override
  String toString() => message;
}

