import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import 'screens/dashboard_screen.dart';
import 'screens/login_screen.dart';
import 'services/auth_service.dart';
import 'services/notification_service.dart';
import 'theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp();
  FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  
  // Inicializar serviço de notificações
  await NotificationService().initialize();
  
  runApp(const MonitoramentoApp());
}

class MonitoramentoApp extends StatefulWidget {
  const MonitoramentoApp({super.key});

  @override
  State<MonitoramentoApp> createState() => _MonitoramentoAppState();
}

class _MonitoramentoAppState extends State<MonitoramentoApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      NotificationService().handleAppOpened(reason: 'app_launch');
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      NotificationService().handleAppOpened(reason: 'app_resumed');
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BPFRON',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.dark,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.dark,
      home: const _Splash(),
    );
  }
}

/// Verifica token salvo e direciona para a tela correta.
class _Splash extends StatefulWidget {
  const _Splash();

  @override
  State<_Splash> createState() => _SplashState();
}

class _SplashState extends State<_Splash> {
  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    // Tenta restaurar sessão: usa access_token válido ou faz refresh automático.
    // Só redireciona para login se não houver sessão recuperável.
    final restored = await AuthService.instance.restoreSession();
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => restored ? const DashboardScreen() : const LoginScreen(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(child: CircularProgressIndicator()),
    );
  }
}
