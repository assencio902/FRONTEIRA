import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models/alert.dart';

/// Tela de alerta detalhado que aparece quando houver detecção crítica
class AlertDetailScreen extends StatefulWidget {
  final AlertModel alert;

  const AlertDetailScreen({
    Key? key,
    required this.alert,
  }) : super(key: key);

  @override
  State<AlertDetailScreen> createState() => _AlertDetailScreenState();
}

class _AlertDetailScreenState extends State<AlertDetailScreen> {
  bool _imageExpanded = false;

  String _formatDateTime(String dateString) {
    try {
      final dt = DateTime.parse(dateString);
      return DateFormat('dd/MM/yyyy HH:mm:ss').format(dt);
    } catch (e) {
      return dateString;
    }
  }

  @override
  Widget build(BuildContext context) {
    final isMobile = MediaQuery.of(context).size.width < 600;
    
    return Scaffold(
      backgroundColor: widget.alert.isCritical 
        ? const Color.fromARGB(255, 139, 0, 0) // Vermelho escuro
        : Colors.grey[900],
      appBar: AppBar(
        backgroundColor: widget.alert.isCritical 
          ? Colors.red 
          : Colors.blueGrey,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: () => Navigator.pop(context),
        ),
        title: widget.alert.isCritical
          ? Row(
              mainAxisSize: MainAxisSize.min,
              children: const [
                Icon(Icons.warning, color: Colors.yellow),
                SizedBox(width: 8),
                Text('ALERTA CRÍTICO'),
              ],
            )
          : const Text('Detecção'),
      ),
      body: SingleChildScrollView(
        child: Column(
          children: [
            // Imagem do veículo
            _buildImageSection(isMobile),
            
            // Placa em destaque
            _buildPlateSection(),
            
            // Informações principais
            _buildInfoSection(),
            
            // Botão de ação
            _buildActionButtons(),
          ],
        ),
      ),
    );
  }

  /// Seção de imagem
  Widget _buildImageSection(bool isMobile) {
    return Container(
      width: double.infinity,
      height: isMobile ? 300 : 400,
      color: Colors.black87,
      child: GestureDetector(
        onTap: () {
          setState(() => _imageExpanded = !_imageExpanded);
        },
        child: Stack(
          alignment: Alignment.center,
          children: [
            // Imagem ou placeholder
            if (widget.alert.imageUrl.isNotEmpty)
              Image.network(
                widget.alert.imageUrl,
                fit: BoxFit.cover,
                errorBuilder: (context, error, stackTrace) {
                  return _buildPlaceholder();
                },
                loadingBuilder: (context, child, loadingProgress) {
                  if (loadingProgress == null) return child;
                  return Center(
                    child: CircularProgressIndicator(
                      value: loadingProgress.expectedTotalBytes != null
                        ? loadingProgress.cumulativeBytesLoaded /
                            loadingProgress.expectedTotalBytes!
                        : null,
                    ),
                  );
                },
              )
            else
              _buildPlaceholder(),
            
            // Overlay com ícone de zoom
            Positioned(
              bottom: 16,
              right: 16,
              child: Container(
                decoration: BoxDecoration(
                  color: Colors.black54,
                  borderRadius: BorderRadius.circular(50),
                ),
                padding: const EdgeInsets.all(8),
                child: Icon(
                  _imageExpanded ? Icons.zoom_out : Icons.zoom_in,
                  color: Colors.white,
                  size: 28,
                ),
              ),
            ),
            
            // Indicador de crítico
            if (widget.alert.isCritical)
              Positioned(
                top: 16,
                left: 16,
                child: Container(
                  decoration: BoxDecoration(
                    color: Colors.red,
                    borderRadius: BorderRadius.circular(8),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.red.withOpacity(0.5),
                        blurRadius: 10,
                      ),
                    ],
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: const [
                      Icon(Icons.local_police, color: Colors.white, size: 16),
                      SizedBox(width: 4),
                      Text(
                        'CRÍTICO',
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// Placeholder quando imagem não existe
  Widget _buildPlaceholder() {
    return Container(
      color: Colors.grey[800],
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.directions_car,
            size: 80,
            color: Colors.grey[600],
          ),
          const SizedBox(height: 16),
          Text(
            'Sem imagem disponível',
            style: TextStyle(color: Colors.grey[400]),
          ),
        ],
      ),
    );
  }

  /// Seção com placa em destaque
  Widget _buildPlateSection() {
    return Container(
      color: Colors.black87,
      padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
      child: Column(
        children: [
          // Placa
          Container(
            decoration: BoxDecoration(
              color: Colors.yellow[700],
              border: Border.all(color: Colors.black, width: 3),
              borderRadius: BorderRadius.circular(8),
              boxShadow: [
                BoxShadow(
                  color: widget.alert.isCritical 
                    ? Colors.red.withOpacity(0.5)
                    : Colors.blue.withOpacity(0.3),
                  blurRadius: 15,
                  spreadRadius: 2,
                ),
              ],
            ),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Text(
              widget.alert.plate,
              style: const TextStyle(
                fontSize: 48,
                fontWeight: FontWeight.bold,
                color: Colors.black,
                fontFamily: 'Courier',
                letterSpacing: 2,
              ),
            ),
          ),
          
          const SizedBox(height: 16),
          
          // Nome do alvo
          Text(
            widget.alert.targetName,
            style: const TextStyle(
              fontSize: 18,
              color: Colors.white,
              fontWeight: FontWeight.bold,
            ),
            textAlign: TextAlign.center,
          ),
          
          if (widget.alert.riskLevel.isNotEmpty && widget.alert.riskLevel != 'normal')
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Container(
                decoration: BoxDecoration(
                  color: _getRiskLevelColor(widget.alert.riskLevel),
                  borderRadius: BorderRadius.circular(4),
                ),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                child: Text(
                  'Nível de risco: ${widget.alert.riskLevel.toUpperCase()}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: Colors.white,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// Seção de informações
  Widget _buildInfoSection() {
    return Container(
      color: Colors.grey[900],
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildInfoRow('📹 Câmera', widget.alert.cameraName),
          const SizedBox(height: 12),
          _buildInfoRow('📍 Local', widget.alert.city),
          const SizedBox(height: 12),
          _buildInfoRow('⏰ Horário', _formatDateTime(widget.alert.detectedAt)),
          const SizedBox(height: 12),
          _buildInfoRow('Código', widget.alert.eventId),
        ],
      ),
    );
  }

  /// Widget para exibir linhas de informação
  Widget _buildInfoRow(String label, String value) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 100,
          child: Text(
            label,
            style: const TextStyle(
              fontSize: 14,
              color: Colors.white70,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(
              fontSize: 14,
              color: Colors.white,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
      ],
    );
  }

  /// Botões de ação
  Widget _buildActionButtons() {
    return Container(
      color: Colors.grey[900],
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Expanded(
            child: ElevatedButton.icon(
              onPressed: () => Navigator.pop(context),
              icon: const Icon(Icons.close),
              label: const Text('Fechar'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.grey[700],
                padding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: ElevatedButton.icon(
              onPressed: () {
                // TODO: Abrir detalhes completo do evento
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Abrindo detalhes completo...')),
                );
              },
              icon: const Icon(Icons.info),
              label: const Text('Ver evento'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.blue,
                padding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Obter cor baseada no nível de risco
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
