import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models/alert.dart';
import 'alert_detail_screen.dart';

/// Modal de alerta que aparece quando o app está aberto
class AlertModal extends StatefulWidget {
  final AlertModel alert;
  final VoidCallback onDismiss;

  const AlertModal({
    Key? key,
    required this.alert,
    required this.onDismiss,
  }) : super(key: key);

  static void show(BuildContext context, AlertModel alert) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertModal(
        alert: alert,
        onDismiss: () => Navigator.pop(context),
      ),
    );
  }

  @override
  State<AlertModal> createState() => _AlertModalState();
}

class _AlertModalState extends State<AlertModal> with TickerProviderStateMixin {
  late AnimationController _pulseController;
  late AnimationController _slideController;

  @override
  void initState() {
    super.initState();
    
    // Animação de pulsação para alertas críticos
    _pulseController = AnimationController(
      duration: const Duration(milliseconds: 1000),
      vsync: this,
    );
    
    if (widget.alert.isCritical) {
      _pulseController.repeat();
    }
    
    // Animação de slide
    _slideController = AnimationController(
      duration: const Duration(milliseconds: 500),
      vsync: this,
    );
    _slideController.forward();
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _slideController.dispose();
    super.dispose();
  }

  String _formatDateTime(String dateString) {
    try {
      final dt = DateTime.parse(dateString);
      return DateFormat('dd/MM HH:mm:ss').format(dt);
    } catch (e) {
      return dateString;
    }
  }

  @override
  Widget build(BuildContext context) {
    return SlideTransition(
      position: Tween<Offset>(
        begin: const Offset(0, -1),
        end: Offset.zero,
      ).animate(_slideController),
      child: AlertDialog(
        backgroundColor: Colors.transparent,
        elevation: 0,
        contentPadding: EdgeInsets.zero,
        content: AnimatedBuilder(
          animation: _pulseController,
          builder: (context, child) {
            final pulse = widget.alert.isCritical 
              ? (0.95 + 0.05 * _pulseController.value)
              : 1.0;
            
            return Transform.scale(
              scale: pulse,
              child: child,
            );
          },
          child: _buildAlertContent(),
        ),
      ),
    );
  }

  Widget _buildAlertContent() {
    return Container(
      decoration: BoxDecoration(
        color: Colors.grey[900],
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: widget.alert.isCritical ? Colors.red : Colors.blue,
          width: 2,
        ),
        boxShadow: [
          BoxShadow(
            color: widget.alert.isCritical 
              ? Colors.red.withOpacity(0.5)
              : Colors.blue.withOpacity(0.3),
            blurRadius: 20,
            spreadRadius: 4,
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Header
          Container(
            decoration: BoxDecoration(
              color: widget.alert.isCritical ? Colors.red : Colors.blue,
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(14),
                topRight: Radius.circular(14),
              ),
            ),
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                if (widget.alert.isCritical)
                  const Padding(
                    padding: EdgeInsets.only(right: 8),
                    child: Icon(Icons.warning, color: Colors.yellow, size: 24),
                  ),
                Expanded(
                  child: Text(
                    widget.alert.isCritical ? '🚨 ALERTA CRÍTICO' : '📢 Detecção',
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                  ),
                ),
                GestureDetector(
                  onTap: () {
                    widget.onDismiss();
                    Navigator.pop(context);
                  },
                  child: Container(
                    decoration: BoxDecoration(
                      color: Colors.white24,
                      borderRadius: BorderRadius.circular(50),
                    ),
                    padding: const EdgeInsets.all(4),
                    child: const Icon(Icons.close, color: Colors.white, size: 20),
                  ),
                ),
              ],
            ),
          ),
          
          // Corpo
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Placa
                Container(
                  width: double.infinity,
                  decoration: BoxDecoration(
                    color: Colors.yellow[700],
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.black, width: 2),
                  ),
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    widget.alert.plate,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 36,
                      fontWeight: FontWeight.bold,
                      color: Colors.black,
                      fontFamily: 'Courier',
                      letterSpacing: 3,
                    ),
                  ),
                ),
                
                const SizedBox(height: 16),
                
                // Nome do alvo
                Text(
                  widget.alert.targetName,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
                
                const SizedBox(height: 8),
                
                // Câmera
                Row(
                  children: [
                    const Icon(Icons.videocam, color: Colors.white70, size: 16),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        widget.alert.cameraName,
                        style: const TextStyle(
                          fontSize: 13,
                          color: Colors.white70,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                
                const SizedBox(height: 8),
                
                // Data e hora
                Row(
                  children: [
                    const Icon(Icons.access_time, color: Colors.white70, size: 16),
                    const SizedBox(width: 8),
                    Text(
                      _formatDateTime(widget.alert.detectedAt),
                      style: const TextStyle(
                        fontSize: 13,
                        color: Colors.white70,
                      ),
                    ),
                  ],
                ),
                
                if (widget.alert.riskLevel.isNotEmpty && widget.alert.riskLevel != 'normal')
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Chip(
                      backgroundColor: _getRiskLevelColor(widget.alert.riskLevel),
                      label: Text(
                        'Risco: ${widget.alert.riskLevel.toUpperCase()}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          
          // Botões
          Padding(
            padding: const EdgeInsets.only(bottom: 16, left: 16, right: 16),
            child: Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () {
                      widget.onDismiss();
                      Navigator.pop(context);
                    },
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white,
                      side: const BorderSide(color: Colors.white54),
                      padding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                    child: const Text('Fechar'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton(
                    onPressed: () {
                      Navigator.pop(context);
                      Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (context) => AlertDetailScreen(
                            alert: widget.alert,
                          ),
                        ),
                      );
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: widget.alert.isCritical 
                        ? Colors.red 
                        : Colors.blue,
                      padding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                    child: const Text('Ver detalhes'),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Color _getRiskLevelColor(String riskLevel) {
    switch (riskLevel.toLowerCase()) {
      case 'high':
      case 'crítico':
        return Colors.red;
      case 'medium':
      case 'médio':
        return Colors.orange;
      case 'low':
      case 'baixo':
        return Colors.yellow;
      default:
        return Colors.green;
    }
  }
}
