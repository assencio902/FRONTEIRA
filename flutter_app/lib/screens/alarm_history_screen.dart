import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

// Tela de histórico de alarmes (stub básico)
class AlarmHistoryScreen extends StatelessWidget {
  const AlarmHistoryScreen({super.key});
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.surface,
        title: const Text('📊 Histórico de Alarmes'),
      ),
      body: const Center(
        child: Text(
          'Histórico de alarmes\n(em desenvolvimento)',
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.muted),
        ),
      ),
    );
  }
}
