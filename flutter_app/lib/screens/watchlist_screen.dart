import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

// Tela de watchlist (stub básico)
class WatchlistScreen extends StatelessWidget {
  const WatchlistScreen({super.key});
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.surface,
        title: const Text('⚠️ Watchlist'),
      ),
      body: const Center(
        child: Text(
          'Lista de monitoramento\n(em desenvolvimento)',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.muted),
        ),
      ),
    );
  }
}
